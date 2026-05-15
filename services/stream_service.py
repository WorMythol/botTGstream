"""Core stream lifecycle management.

This is the heart of the system:
  - Ingests live-check results from platform integrations
  - Manages Stream / PlatformStream session lifecycle
  - Triggers unified notifications (one message per streamer, all platforms)
  - Handles cooldown window to avoid duplicate alerts on short stream restarts
  - Detects new platforms going live mid-session → edits existing notifications
  - Feature 1: sends "stream ended" notification when session closes
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from db.models import Platform, PlatformStream, Stream, StreamStatus
from db.repositories.stream_repo import PlatformStreamRepository, StreamRepository
from integrations.base import StreamInfo
from services.notification_service import NotificationService

logger = structlog.get_logger(__name__)


class StreamService:
    def __init__(self, session: AsyncSession, notification_service: NotificationService) -> None:
        self._session = session
        self._stream_repo = StreamRepository(session)
        self._ps_repo = PlatformStreamRepository(session)
        self._notif = notification_service

    async def process_live_results(
        self,
        streamer_id: int,
        live_streams: Dict[Platform, StreamInfo],
    ) -> None:
        """Process aggregated live-check results for a streamer.

        Args:
            streamer_id: DB streamer ID.
            live_streams: Mapping of platform → StreamInfo for every platform
                          currently live (empty dict = no platforms live).
        """
        active = await self._stream_repo.get_active_for_streamer(streamer_id)

        if not live_streams:
            # Nothing live — close active session if there is one
            if active:
                await self._close_stream(active)
            return

        if active is None:
            # Check cooldown window (stream ended recently, maybe a restart)
            cooldown = await self._stream_repo.get_in_cooldown(streamer_id)
            if cooldown:
                await self._handle_cooldown_restart(cooldown, live_streams)
                return
            # Brand-new stream session
            await self._open_stream(streamer_id, live_streams)
        else:
            # Stream already known — check for newly-added platforms
            await self._update_stream(active, live_streams)

    # ── Session open/close ────────────────────────────────────────────────────

    async def _open_stream(
        self,
        streamer_id: int,
        live_streams: Dict[Platform, StreamInfo],
    ) -> Stream:
        now = datetime.now(timezone.utc)
        stream = Stream(
            streamer_id=streamer_id,
            status=StreamStatus.LIVE,
            started_at=now,
        )
        self._session.add(stream)
        await self._session.flush()  # get stream.id

        for platform, info in live_streams.items():
            ps = PlatformStream(
                stream_id=stream.id,
                platform=platform,
                platform_stream_id=info.platform_stream_id,
                title=info.title,
                url=info.url,
                viewer_count=info.viewer_count,
                thumbnail_url=info.thumbnail_url,
                started_at=_parse_dt(info.started_at),
            )
            self._session.add(ps)
        await self._session.flush()

        logger.info("stream.opened", stream_id=stream.id, streamer_id=streamer_id,
                    platforms=[p.value for p in live_streams])

        # Reload with relationships for notification
        stream = await self._stream_repo.get_with_details(stream.id)
        await self._notif.send_stream_notification(stream)
        return stream

    async def _close_stream(self, stream: Stream) -> None:
        """End a stream session and send 'stream ended' notification (Feature 1)."""
        now = datetime.now(timezone.utc)
        cooldown = now + timedelta(seconds=settings.STREAM_COOLDOWN_SECONDS)
        await self._stream_repo.end_stream(stream.id, cooldown)
        # End all active platform streams
        for ps in stream.platform_streams:
            if ps.ended_at is None:
                ps.ended_at = now
        await self._session.flush()
        logger.info("stream.closed", stream_id=stream.id)

        # Feature 1: send stream-end notification
        # Reload to get updated ended_at and peak_viewer_count
        updated_stream = await self._stream_repo.get_with_details(stream.id)
        if updated_stream:
            try:
                await self._notif.send_stream_end_notification(updated_stream)
            except Exception as exc:
                logger.warning("stream.end_notification_failed", stream_id=stream.id, error=str(exc))

    async def _update_stream(
        self,
        stream: Stream,
        live_streams: Dict[Platform, StreamInfo],
    ) -> None:
        """Handle platforms going on/offline during an active session."""
        existing_platforms = {ps.platform for ps in stream.platform_streams if ps.ended_at is None}
        new_platforms = set(live_streams.keys()) - existing_platforms
        ended_platforms = existing_platforms - set(live_streams.keys())

        # Mark ended platforms
        for ps in stream.platform_streams:
            if ps.platform in ended_platforms and ps.ended_at is None:
                ps.ended_at = datetime.now(timezone.utc)
                logger.info("stream.platform_ended", stream_id=stream.id, platform=ps.platform)

        # Add new platforms
        for platform in new_platforms:
            info = live_streams[platform]
            ps = PlatformStream(
                stream_id=stream.id,
                platform=platform,
                platform_stream_id=info.platform_stream_id,
                title=info.title,
                url=info.url,
                viewer_count=info.viewer_count,
                thumbnail_url=info.thumbnail_url,
                started_at=_parse_dt(info.started_at),
            )
            self._session.add(ps)
            logger.info("stream.new_platform", stream_id=stream.id, platform=platform)

        # Update viewer counts for existing platforms
        for ps in stream.platform_streams:
            if ps.platform in live_streams and ps.ended_at is None:
                info = live_streams[ps.platform]
                ps.viewer_count = info.viewer_count
                if info.viewer_count and (stream.peak_viewer_count is None or
                                          info.viewer_count > stream.peak_viewer_count):
                    stream.peak_viewer_count = info.viewer_count

        await self._session.flush()

        # If new platforms appeared, edit existing notifications
        if new_platforms:
            stream = await self._stream_repo.get_with_details(stream.id)
            await self._notif.update_stream_notifications(stream)

    async def _handle_cooldown_restart(
        self,
        cooldown_stream: Stream,
        live_streams: Dict[Platform, StreamInfo],
    ) -> None:
        """Stream restarted within cooldown window — reactivate session."""
        cooldown_stream.status = StreamStatus.LIVE
        cooldown_stream.cooldown_until = None
        for platform, info in live_streams.items():
            existing_ps = await self._ps_repo.get_by_stream_and_platform(
                cooldown_stream.id, platform
            )
            if existing_ps:
                existing_ps.ended_at = None
                existing_ps.viewer_count = info.viewer_count
            else:
                ps = PlatformStream(
                    stream_id=cooldown_stream.id,
                    platform=platform,
                    platform_stream_id=info.platform_stream_id,
                    title=info.title,
                    url=info.url,
                    viewer_count=info.viewer_count,
                )
                self._session.add(ps)
        await self._session.flush()
        # Update the notifications with new data
        stream = await self._stream_repo.get_with_details(cooldown_stream.id)
        await self._notif.update_stream_notifications(stream)
        logger.info("stream.cooldown_restart", stream_id=cooldown_stream.id)


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
