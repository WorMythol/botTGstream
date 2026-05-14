"""Notification delivery — send, edit, delete Telegram messages.

Completely decoupled from aiogram: accepts a callable `send_fn` / `edit_fn`
so the same service can be used from REST (FastAPI) or tests.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, Coroutine, List, Optional, Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Notification, NotificationPlatform, NotificationStatus, Stream
from db.repositories.notification_repo import NotificationRepository
from db.repositories.streamer_repo import AssignmentRepository, StreamerRepository
from services.template_service import PlatformLink, render_template

logger = structlog.get_logger(__name__)

# Type aliases for injectable callables
SendFn = Callable[..., Coroutine[Any, Any, Optional[int]]]   # returns message_id
EditFn = Callable[..., Coroutine[Any, Any, bool]]            # returns success
DeleteFn = Callable[..., Coroutine[Any, Any, bool]]          # returns success


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
    ) -> None:
        self._session = session
        self._notif_repo = NotificationRepository(session)
        self._assign_repo = AssignmentRepository(session)
        self._streamer_repo = StreamerRepository(session)
        self._send = send_fn
        self._edit = edit_fn
        self._delete = delete_fn

    # ── Send ──────────────────────────────────────────────────────────────────

    async def send_stream_notification(self, stream: Stream) -> None:
        """Send notifications to all channels assigned to the streamer."""
        streamer = await self._streamer_repo.get_with_accounts(stream.streamer_id)
        if streamer is None:
            return

        assignments = await self._assign_repo.get_for_streamer(stream.streamer_id)
        platform_links = self._build_links(stream)

        for assignment in assignments:
            await self._deliver_to_channel(
                stream=stream,
                assignment=assignment,
                streamer_name=streamer.display_name,
                platform_links=platform_links,
            )

        stream.notification_sent_at = datetime.now(timezone.utc)
        await self._session.flush()

    async def _deliver_to_channel(
        self,
        stream: Stream,
        assignment: Any,
        streamer_name: str,
        platform_links: List[PlatformLink],
    ) -> None:
        channel = assignment.channel
        if not channel or not channel.is_active:
            return

        # Viewer threshold check (additional feature)
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
            return

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
            logger.info(
                "notification.sent",
                stream_id=stream.id,
                channel_id=channel.id,
                message_id=message_id,
            )
        else:
            notif.status = NotificationStatus.FAILED
            notif.error_message = "send returned None"
            logger.error("notification.send_failed", stream_id=stream.id, channel_id=channel.id)
        await self._session.flush()

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
            if notif.telegram_message_id:
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
        notif = await self._notif_repo.get(notification_id)
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
