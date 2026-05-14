"""Analytics — stream history, statistics, health reports."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from db.models import (
    Notification, NotificationStatus, Platform, PlatformStream,
    Stream, StreamStatus, Streamer,
)


@dataclass
class StreamerStats:
    streamer_id: int
    display_name: str
    total_streams: int
    total_hours_streamed: float
    total_notifications_sent: int
    peak_viewers: Optional[int]
    last_stream_at: Optional[datetime]
    platforms: List[str]


@dataclass
class GlobalStats:
    total_streamers: int
    active_streamers: int
    total_streams: int
    total_notifications: int
    streams_last_7_days: int
    top_streamers: List[StreamerStats]


class AnalyticsService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_streamer_stats(self, streamer_id: int) -> Optional[StreamerStats]:
        result = await self._session.execute(
            select(Streamer)
            .options(
                selectinload(Streamer.streams).selectinload(Stream.platform_streams),
                selectinload(Streamer.streams).selectinload(Stream.notifications),
            )
            .where(Streamer.id == streamer_id)
        )
        streamer = result.scalar_one_or_none()
        if streamer is None:
            return None
        return self._compute_streamer_stats(streamer)

    async def get_global_stats(self) -> GlobalStats:
        # Total / active streamers
        total_q = await self._session.execute(select(func.count(Streamer.id)))
        total_streamers = total_q.scalar_one()

        active_q = await self._session.execute(
            select(func.count(Streamer.id)).where(
                Streamer.is_active.is_(True), Streamer.auto_disabled_at.is_(None)
            )
        )
        active_streamers = active_q.scalar_one()

        # Total streams
        stream_q = await self._session.execute(select(func.count(Stream.id)))
        total_streams = stream_q.scalar_one()

        # Total notifications sent
        notif_q = await self._session.execute(
            select(func.count(Notification.id)).where(
                Notification.status.in_([NotificationStatus.SENT, NotificationStatus.EDITED])
            )
        )
        total_notifications = notif_q.scalar_one()

        # Streams in last 7 days
        seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)
        recent_q = await self._session.execute(
            select(func.count(Stream.id)).where(Stream.started_at >= seven_days_ago)
        )
        streams_last_7_days = recent_q.scalar_one()

        # Top 5 streamers by total streams
        streamers_result = await self._session.execute(
            select(Streamer)
            .options(
                selectinload(Streamer.streams).selectinload(Stream.platform_streams),
                selectinload(Streamer.streams).selectinload(Stream.notifications),
            )
            .where(Streamer.is_active.is_(True))
        )
        all_streamers = list(streamers_result.scalars().all())
        all_stats = sorted(
            [self._compute_streamer_stats(s) for s in all_streamers],
            key=lambda x: x.total_streams,
            reverse=True,
        )

        return GlobalStats(
            total_streamers=total_streamers,
            active_streamers=active_streamers,
            total_streams=total_streams,
            total_notifications=total_notifications,
            streams_last_7_days=streams_last_7_days,
            top_streamers=all_stats[:5],
        )

    async def get_stream_history(
        self, streamer_id: int, limit: int = 20
    ) -> List[Stream]:
        result = await self._session.execute(
            select(Stream)
            .options(selectinload(Stream.platform_streams))
            .where(Stream.streamer_id == streamer_id)
            .order_by(Stream.started_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    # ── Internal ──────────────────────────────────────────────────────────────

    @staticmethod
    def _compute_streamer_stats(streamer: Streamer) -> StreamerStats:
        streams = streamer.streams or []
        total_hours = 0.0
        peak_viewers = None
        last_stream_at = None
        platforms_set: set[str] = set()

        for stream in streams:
            if stream.ended_at and stream.started_at:
                duration = (stream.ended_at - stream.started_at).total_seconds() / 3600
                total_hours += duration
            if stream.started_at:
                if last_stream_at is None or stream.started_at > last_stream_at:
                    last_stream_at = stream.started_at
            if stream.peak_viewer_count:
                if peak_viewers is None or stream.peak_viewer_count > peak_viewers:
                    peak_viewers = stream.peak_viewer_count
            for ps in (stream.platform_streams or []):
                platforms_set.add(ps.platform.value)

        notifications_sent = sum(
            1
            for s in streams
            for n in (s.notifications or [])
            if n.status in (NotificationStatus.SENT, NotificationStatus.EDITED)
        )

        return StreamerStats(
            streamer_id=streamer.id,
            display_name=streamer.display_name,
            total_streams=len(streams),
            total_hours_streamed=round(total_hours, 1),
            total_notifications_sent=notifications_sent,
            peak_viewers=peak_viewers,
            last_stream_at=last_stream_at,
            platforms=sorted(platforms_set),
        )
