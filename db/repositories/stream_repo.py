"""Stream and PlatformStream repositories."""
from datetime import datetime
from typing import List, Optional

from sqlalchemy import and_, select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Platform, PlatformStream, Stream, StreamStatus
from db.repositories.base import BaseRepository


class StreamRepository(BaseRepository[Stream]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(Stream, session)

    async def get_active_for_streamer(self, streamer_id: int) -> Optional[Stream]:
        """Return the current live/cooldown stream session for a streamer."""
        result = await self.session.execute(
            select(Stream)
            .options(
                selectinload(Stream.platform_streams),
                selectinload(Stream.notifications),
            )
            .where(
                Stream.streamer_id == streamer_id,
                Stream.status == StreamStatus.LIVE,
            )
        )
        return result.scalar_one_or_none()

    async def get_with_details(self, stream_id: int) -> Optional[Stream]:
        result = await self.session.execute(
            select(Stream)
            .options(
                selectinload(Stream.platform_streams),
                selectinload(Stream.notifications),
                selectinload(Stream.streamer),
            )
            .where(Stream.id == stream_id)
        )
        return result.scalar_one_or_none()

    async def get_history_for_streamer(
        self, streamer_id: int, limit: int = 50
    ) -> List[Stream]:
        result = await self.session.execute(
            select(Stream)
            .options(selectinload(Stream.platform_streams))
            .where(Stream.streamer_id == streamer_id)
            .order_by(Stream.started_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def end_stream(self, stream_id: int, cooldown_until: datetime) -> None:
        stream = await self.get(stream_id)
        if stream:
            stream.status = StreamStatus.ENDED
            stream.ended_at = datetime.utcnow()
            stream.cooldown_until = cooldown_until
            await self.session.flush()

    async def get_in_cooldown(self, streamer_id: int) -> Optional[Stream]:
        """Return stream in cooldown window (recently ended)."""
        now = datetime.utcnow()
        result = await self.session.execute(
            select(Stream)
            .options(selectinload(Stream.platform_streams))
            .where(
                Stream.streamer_id == streamer_id,
                Stream.status == StreamStatus.ENDED,
                Stream.cooldown_until > now,
            )
        )
        return result.scalar_one_or_none()

    async def get_recent_streams(self, limit: int = 100) -> List[Stream]:
        result = await self.session.execute(
            select(Stream)
            .options(selectinload(Stream.streamer), selectinload(Stream.platform_streams))
            .order_by(Stream.started_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())


class PlatformStreamRepository(BaseRepository[PlatformStream]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(PlatformStream, session)

    async def get_active_for_stream(self, stream_id: int) -> List[PlatformStream]:
        result = await self.session.execute(
            select(PlatformStream).where(
                PlatformStream.stream_id == stream_id,
                PlatformStream.ended_at.is_(None),
            )
        )
        return list(result.scalars().all())

    async def get_by_stream_and_platform(
        self, stream_id: int, platform: Platform
    ) -> Optional[PlatformStream]:
        result = await self.session.execute(
            select(PlatformStream).where(
                PlatformStream.stream_id == stream_id,
                PlatformStream.platform == platform,
            )
        )
        return result.scalar_one_or_none()

    async def end_platform_stream(self, platform_stream_id: int) -> None:
        ps = await self.get(platform_stream_id)
        if ps:
            ps.ended_at = datetime.utcnow()
            await self.session.flush()
