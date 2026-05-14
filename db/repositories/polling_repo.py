"""PollingState repository — quota tracking and rate-limit state."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Platform, PollingState
from db.repositories.base import BaseRepository


class PollingStateRepository(BaseRepository[PollingState]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(PollingState, session)

    async def get_for_platform(self, platform: Platform) -> Optional[PollingState]:
        result = await self.session.execute(
            select(PollingState).where(PollingState.platform == platform)
        )
        return result.scalar_one_or_none()

    async def get_or_create(self, platform: Platform) -> PollingState:
        ps = await self.get_for_platform(platform)
        if ps is None:
            ps = PollingState(platform=platform)
            self.session.add(ps)
            await self.session.flush()
        return ps

    async def record_poll(self, platform: Platform) -> None:
        ps = await self.get_or_create(platform)
        ps.last_poll_at = datetime.now(timezone.utc)
        await self.session.flush()

    async def add_youtube_quota(self, units: int) -> int:
        """Add quota units used. Returns new total."""
        ps = await self.get_or_create(Platform.YOUTUBE)
        # Reset daily quota if past reset time
        if ps.youtube_quota_reset_at and datetime.now(timezone.utc) >= ps.youtube_quota_reset_at:
            ps.youtube_quota_used = 0
        ps.youtube_quota_used = (ps.youtube_quota_used or 0) + units
        await self.session.flush()
        return ps.youtube_quota_used

    async def is_youtube_quota_exceeded(self, limit: int) -> bool:
        ps = await self.get_for_platform(Platform.YOUTUBE)
        if ps is None:
            return False
        # Reset check
        if ps.youtube_quota_reset_at and datetime.now(timezone.utc) >= ps.youtube_quota_reset_at:
            return False
        return (ps.youtube_quota_used or 0) >= limit
