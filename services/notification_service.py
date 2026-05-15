"""Notification delivery — send, edit, delete Telegram messages.

Completely decoupled from aiogram: accepts a callable `send_fn` / `edit_fn`
so the same service can be used from REST (FastAPI) or tests.

Features:
  - Feature 1: stream end notifications via send_end_notification()
  - Feature 2: retry failed deliveries with exponential backoff
  - Feature 12: VK delivery via vk_send_fn
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Callable, Coroutine, List, Optional, Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Notification, NotificationPlatform, NotificationStatus, Stream
from db.repositories.notification_repo import NotificationRepository
from db.repositories.streamer_repo import AssignmentRepository, StreamerRepository
from services.template_service import PlatformLink, render_template, render_end_template

logger = structlog.get_logger(__name__)

# Type aliases for injectable callables
SendFn = Callable[..., Coroutine[Any, Any, Optional[int]]]   # returns message_id
EditFn = Callable[..., Coroutine[Any, Any, bool]]            # returns success
DeleteFn = Callable[..., Coroutine[Any, Any, bool]]          # returns success
VkSendFn = Callable[..., Coroutine[Any, Any, Optional[int]]] # returns vk message_id or None

# Feature 2: retry delays — 1 min, 5 min, 15 min
_RETRY_DELAYS = [60, 300, 900]
_MAX_RETRIES = 3


class NotificationService:
    """Orchestrates rendering and delivery of stream notifications.

    The bot layer injects `send_fn`, `edit_fn`, `delete_fn` so that business
    logic stays platform-agnostic and testable.
    """

    def __init__(
        self,
        session: AsyncSession,
        send_fn: SendFn,
        edit_fn: EditFn,
        delete_fn: DeleteFn,
        vk_send_fn: Optional[VkSendFn] = None,  # Feature 12: optional VK delivery
    ) -> None:
        self._session = session
        self._notif_repo = NotificationRepository(session)
        self._assign_repo = AssignmentRepository(session)
        self._streamer_repo = StreamerRepository(session)
        self._send = send_fn
        self._edit = edit_fn
        self._delete = delete_fn
        self._vk_send = vk_send_fn

    # ── Send ──────────────────────────────────────────────────────────────────

    async def send_stream_notification(self, stream: Stream) -> None:
        """Send notifications to all channels assigned to the streamer."""
        streamer = await self._streamer_repo.get_with_accounts(stream.streamer_id)
        if streamer is None:
            return

        assignments = await self._assign_repo.get_for_streamer(stream.streamer_id)
        platform_links = self._build_links(stream)

        any_sent = False
        for assignment in assignments:
            sent = await self._deliver_to_channel(
                stream=stream,
                assignment=assignment,
                streamer_name=streamer.display_name,
                platform_links=platform_links,
            )
            any_sent = any_sent or sent

            # Feature 12: VK delivery if channel has a vk_peer_id
            if self._vk_send and assignment.channel and assignment.channel.vk_peer_id:
                await self._deliver_to_vk(
                    stream=stream,
                    assignment=assignment,
                    streamer_name=streamer.display_name,
                    platform_links=platform_links,
                )

        # FIX M-4: only mark notification_sent_at if at least one channel succeeded
        if any_sent:
            stream.notification_sent_at = datetime.now(timezone.utc)
        await self._session.flush()

    async def _deliver_to_channel(
        self,
        stream: Stream,
        assignment: Any,
        streamer_name: str,
        platform_links: List[PlatformLink],
    ) -> bool:
        """Deliver notification to one channel. Returns True if message was sent."""
        channel = assignment.channel
        if not channel or not channel.is_active:
            return False

        # Viewer threshold check
        total_viewers = sum(
            (ps.viewer_count or 0)
            for ps in stream.platform_streams
            if ps.ended_at is None
        )
        if assignment.min_viewer_count > 0 and total_viewers < assignment.min_viewer_count:
            logger.info(
                "notification.skipped_threshold",
                stream_id=stream.id,
                channel_id=channel.id,
                viewers=total_viewers,
                threshold=assignment.min_viewer_count,
            )
            return False

        # Render message
        active_ps = [ps for ps in stream.platform_streams if ps.ended_at is None]
        stream_title = active_ps[0].title if active_ps else None
        peak_viewers = max((ps.viewer_count or 0 for ps in active_ps), default=None) or None

        rendered = render_template(
            template_str=assignment.message_template,
            streamer_name=streamer_name,
            stream_title=stream_title,
            viewer_count=peak_viewers,
            platform_links=platform_links,
        )

        # Create notification record (pending)
        notif = Notification(
            stream_id=stream.id,
            channel_id=channel.id,
            delivery_platform=NotificationPlatform.TELEGRAM,
            status=NotificationStatus.PENDING,
            rendered_text=rendered,
        )
        self._session.add(notif)
        await self._session.flush()

        # Deliver
        thumbnail = active_ps[0].thumbnail_url if active_ps else None
        message_id = await self._send(
            chat_id=channel.telegram_id,
            text=rendered,
            platform_links=platform_links,
            thumbnail_url=thumbnail,
        )

        if message_id:
            notif.telegram_message_id = message_id
            notif.status = NotificationStatus.SENT
            notif.sent_at = datetime.now(timezone.utc)
            notif.is_photo_message = thumbnail is not None  # FIX M-1: track message type
            logger.info(
                "notification.sent",
                stream_id=stream.id,
                channel_id=channel.id,
                message_id=message_id,
            )
            await self._session.flush()
            return True
        else:
            # Feature 2: schedule retry
            notif.status = NotificationStatus.FAILED
            notif.error_message = "send returned None"
            notif.retry_after = datetime.now(timezone.utc) + timedelta(seconds=_RETRY_DELAYS[0])
            logger.error("notification.send_failed", stream_id=stream.id, channel_id=channel.id)
            await self._session.flush()
            return False

    # ── Feature 12: VK delivery ───────────────────────────────────────────────

    async def _deliver_to_vk(
        self,
        stream: Stream,
        assignment: Any,
        streamer_name: str,
        platform_links: List[PlatformLink],
    ) -> None:
        """Cross-post notification to VK community wall/chat."""
        if not self._vk_send:
            return
        channel = assignment.channel
        if not channel or not channel.vk_peer_id:
            return

        active_ps = [ps for ps in stream.platform_streams if ps.ended_at is None]
        stream_title = active_ps[0].title if active_ps else None
        peak_viewers = max((ps.viewer_count or 0 for ps in active_ps), default=None) or None

        # VK messages use plain text (no Markdown)
        rendered = render_template(
            template_str=assignment.message_template,
            streamer_name=streamer_name,
            stream_title=stream_title,
            viewer_count=peak_viewers,
            platform_links=platform_links,
        )
        # Strip Markdown markers for VK plain text
        import re
        plain_text = re.sub(r"[*_`\[]", "", rendered)
        plain_text = re.sub(r"\]\([^)]+\)", "", plain_text)

        notif = Notification(
            stream_id=stream.id,
            channel_id=channel.id,
            delivery_platform=NotificationPlatform.VK,
            status=NotificationStatus.PENDING,
            rendered_text=plain_text,
        )
        self._session.add(notif)
        await self._session.flush()

        thumbnail = active_ps[0].thumbnail_url if active_ps else None
        msg_id = await self._vk_send(
            peer_id=channel.vk_peer_id,
            text=plain_text,
            platform_links=platform_links,
            thumbnail_url=thumbnail,
        )

        if msg_id:
            notif.telegram_message_id = msg_id  # reusing field for VK message ID
            notif.status = NotificationStatus.SENT
            notif.sent_at = datetime.now(timezone.utc)
            logger.info("notification.vk_sent", stream_id=stream.id, vk_peer_id=channel.vk_peer_id)
        else:
            notif.status = NotificationStatus.FAILED
            notif.error_message = "vk_send returned None"
            logger.error("notification.vk_send_failed", stream_id=stream.id)
        await self._session.flush()

    # ── Feature 1: Stream end notification ───────────────────────────────────

    async def send_stream_end_notification(self, stream: Stream) -> None:
        """Send 'stream ended' message to all channels that want it.

        Called when a stream session transitions to ENDED.
        Each assignment controls this via `send_end_notification` flag.
        """
        streamer = await self._streamer_repo.get_with_accounts(stream.streamer_id)
        if streamer is None:
            return

        assignments = await self._assign_repo.get_for_streamer(stream.streamer_id)
        rendered = render_end_template(
            streamer_name=streamer.display_name,
            started_at=stream.started_at,
            ended_at=stream.ended_at or datetime.now(timezone.utc),
            peak_viewers=stream.peak_viewer_count,
        )

        for assignment in assignments:
            if not getattr(assignment, "send_end_notification", True):
                continue
            channel = assignment.channel
            if not channel or not channel.is_active:
                continue

            notif = Notification(
                stream_id=stream.id,
                channel_id=channel.id,
                delivery_platform=NotificationPlatform.TELEGRAM,
                status=NotificationStatus.PENDING,
                rendered_text=rendered,
            )
            self._session.add(notif)
            await self._session.flush()

            message_id = await self._send(
                chat_id=channel.telegram_id,
                text=rendered,
                platform_links=[],
                thumbnail_url=None,
            )

            if message_id:
                notif.telegram_message_id = message_id
                notif.status = NotificationStatus.SENT
                notif.sent_at = datetime.now(timezone.utc)
                logger.info("notification.end_sent", stream_id=stream.id, channel_id=channel.id)
            else:
                notif.status = NotificationStatus.FAILED
                notif.error_message = "end notification send failed"
            await self._session.flush()

    # ── Feature 2: Retry failed notifications ─────────────────────────────────

    async def retry_failed_notifications(self) -> int:
        """Retry FAILED notifications that are due for retry.

        Called by APScheduler every minute. Returns count retried.
        """
        now = datetime.now(timezone.utc)
        failed = await self._notif_repo.get_failed_for_retry(now)
        retried = 0

        for notif in failed:
            if notif.retry_count >= _MAX_RETRIES:
                # Give up — mark as permanently failed
                notif.retry_after = None
                logger.warning("notification.retry_exhausted", notif_id=notif.id)
                await self._session.flush()
                continue

            # Try to re-deliver
            if notif.delivery_platform == NotificationPlatform.TELEGRAM:
                message_id = await self._send(
                    chat_id=notif.channel.telegram_id,
                    text=notif.rendered_text or "",
                    platform_links=[],  # links already embedded in rendered text
                    thumbnail_url=None,
                )
                if message_id:
                    notif.telegram_message_id = message_id
                    notif.status = NotificationStatus.SENT
                    notif.sent_at = now
                    notif.retry_after = None
                    logger.info("notification.retry_success", notif_id=notif.id,
                                attempt=notif.retry_count + 1)
                else:
                    notif.retry_count += 1
                    delay = _RETRY_DELAYS[min(notif.retry_count, len(_RETRY_DELAYS) - 1)]
                    notif.retry_after = now + timedelta(seconds=delay)
                    logger.warning("notification.retry_failed", notif_id=notif.id,
                                   next_retry_in=delay)

            elif notif.delivery_platform == NotificationPlatform.VK and self._vk_send:
                channel = notif.channel
                if channel and channel.vk_peer_id:
                    msg_id = await self._vk_send(
                        peer_id=channel.vk_peer_id,
                        text=notif.rendered_text or "",
                        platform_links=[],
                        thumbnail_url=None,
                    )
                    if msg_id:
                        notif.telegram_message_id = msg_id
                        notif.status = NotificationStatus.SENT
                        notif.sent_at = now
                        notif.retry_after = None
                    else:
                        notif.retry_count += 1
                        delay = _RETRY_DELAYS[min(notif.retry_count, len(_RETRY_DELAYS) - 1)]
                        notif.retry_after = now + timedelta(seconds=delay)

            retried += 1
            await self._session.flush()

        return retried

    # ── Update (edit) ─────────────────────────────────────────────────────────

    async def update_stream_notifications(self, stream: Stream) -> None:
        """Edit existing notifications when stream platforms change."""
        streamer = await self._streamer_repo.get_with_accounts(stream.streamer_id)
        if streamer is None:
            return

        platform_links = self._build_links(stream)
        active_ps = [ps for ps in stream.platform_streams if ps.ended_at is None]
        stream_title = active_ps[0].title if active_ps else None
        peak_viewers = max((ps.viewer_count or 0 for ps in active_ps), default=None) or None

        existing_notifs = await self._notif_repo.get_active_for_stream(stream.id)
        assignments = await self._assign_repo.get_for_streamer(stream.streamer_id)
        template_map = {a.channel_id: a.message_template for a in assignments}

        for notif in existing_notifs:
            if notif.telegram_message_id is None:
                continue
            # Skip VK notifications — we can't edit VK messages the same way
            if notif.delivery_platform == NotificationPlatform.VK:
                continue
            rendered = render_template(
                template_str=template_map.get(notif.channel_id),
                streamer_name=streamer.display_name,
                stream_title=stream_title,
                viewer_count=peak_viewers,
                platform_links=platform_links,
            )
            success = await self._edit(
                chat_id=notif.channel.telegram_id,
                message_id=notif.telegram_message_id,
                text=rendered,
                platform_links=platform_links,
                is_photo_message=notif.is_photo_message,  # FIX M-1
            )
            if success:
                notif.status = NotificationStatus.EDITED
                notif.edited_at = datetime.now(timezone.utc)
                notif.rendered_text = rendered
                logger.info("notification.edited", notif_id=notif.id)
        await self._session.flush()

    # ── Delete ────────────────────────────────────────────────────────────────

    async def delete_stream_notifications(self, stream_id: int) -> int:
        """Delete all sent notifications for a stream. Returns count deleted."""
        notifs = await self._notif_repo.get_active_for_stream(stream_id)
        deleted = 0
        for notif in notifs:
            if notif.telegram_message_id and notif.delivery_platform == NotificationPlatform.TELEGRAM:
                success = await self._delete(
                    chat_id=notif.channel.telegram_id,
                    message_id=notif.telegram_message_id,
                )
                if success:
                    notif.status = NotificationStatus.DELETED
                    deleted += 1
        await self._session.flush()
        return deleted

    async def delete_notification(self, notification_id: int) -> bool:
        # FIX C-2: use get_with_channel() to eager-load .channel,
        # avoiding MissingGreenlet error in async SQLAlchemy context.
        notif = await self._notif_repo.get_with_channel(notification_id)
        if notif is None or notif.telegram_message_id is None:
            return False
        success = await self._delete(
            chat_id=notif.channel.telegram_id,
            message_id=notif.telegram_message_id,
        )
        if success:
            notif.status = NotificationStatus.DELETED
            await self._session.flush()
        return success

    # ── Test notification ──────────────────────────────────────────────────────

    async def send_test_notification(
        self,
        channel_telegram_id: int,
        streamer_name: str,
        template: Optional[str] = None,
    ) -> bool:
        """Send a test notification to a channel (no DB stream record)."""
        platform_links = [
            PlatformLink(platform="YouTube", url="https://youtube.com"),
            PlatformLink(platform="Twitch", url="https://twitch.tv"),
        ]
        rendered = render_template(
            template_str=template,
            streamer_name=streamer_name,
            stream_title="Test Stream Title",
            viewer_count=42,
            platform_links=platform_links,
        )
        message_id = await self._send(
            chat_id=channel_telegram_id,
            text=f"🧪 *[TEST]*\n\n{rendered}",
            platform_links=platform_links,
            thumbnail_url=None,
        )
        return message_id is not None

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _build_links(stream: Stream) -> List[PlatformLink]:
        return [
            PlatformLink(platform=ps.platform.value.capitalize(), url=ps.url)
            for ps in stream.platform_streams
            if ps.ended_at is None
        ]
