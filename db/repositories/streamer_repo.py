"""Streamer + PlatformAccount + assignment repositories."""
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import (
    Platform, PlatformAccount, Streamer, StreamerChannelAssignment,
    StreamerUserAssignment,
)
from db.repositories.base import BaseRepository


class StreamerRepository(BaseRepository[Streamer]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(Streamer, session)

    async def get_with_accounts(self, streamer_id: int) -> Optional[Streamer]:
        result = await self.session.execute(
            select(Streamer)
            .options(
                selectinload(Streamer.platform_accounts),
                selectinload(Streamer.channel_assignments).selectinload(
                    StreamerChannelAssignment.channel
                ),
            )
            .where(Streamer.id == streamer_id)
        )
        return result.scalar_one_or_none()

    async def get_active_streamers(self) -> List[Streamer]:
        """Return streamers that are active, not paused, and not auto-disabled."""
        result = await self.session.execute(
            select(Streamer)
            .options(selectinload(Streamer.platform_accounts))
            .where(
                Streamer.is_active.is_(True),
                Streamer.is_paused.is_(False),
                Streamer.auto_disabled_at.is_(None),
            )
        )
        return list(result.scalars().all())

    async def get_all_with_details(self) -> List[Streamer]:
        result = await self.session.execute(
            select(Streamer)
            .options(
                selectinload(Streamer.platform_accounts),
                selectinload(Streamer.channel_assignments).selectinload(
                    StreamerChannelAssignment.channel
                ),
            )
            .order_by(Streamer.display_name)
        )
        return list(result.scalars().all())

    async def get_for_user(self, user_id: int) -> List[Streamer]:
        """Return streamers assigned to a specific user (streamer role)."""
        result = await self.session.execute(
            select(Streamer)
            .join(StreamerUserAssignment, StreamerUserAssignment.streamer_id == Streamer.id)
            .options(
                selectinload(Streamer.platform_accounts),
                selectinload(Streamer.channel_assignments),
            )
            .where(StreamerUserAssignment.user_id == user_id, Streamer.is_active.is_(True))
        )
        return list(result.scalars().all())

    async def increment_errors(self, streamer_id: int, max_errors: int) -> bool:
        """Increment error counter; auto-disable when max reached. Returns True if disabled."""
        streamer = await self.get(streamer_id)
        if streamer is None:
            return False
        streamer.consecutive_errors += 1
        if streamer.consecutive_errors >= max_errors:
            streamer.auto_disabled_at = datetime.now(timezone.utc)
            streamer.auto_disabled_reason = f"Auto-disabled after {streamer.consecutive_errors} consecutive errors"
            await self.session.flush()
            return True
        await self.session.flush()
        return False

    async def reset_errors(self, streamer_id: int) -> None:
        streamer = await self.get(streamer_id)
        if streamer:
            streamer.consecutive_errors = 0
            await self.session.flush()


class PlatformAccountRepository(BaseRepository[PlatformAccount]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(PlatformAccount, session)

    async def get_by_streamer_and_platform(
        self, streamer_id: int, platform: Platform
    ) -> Optional[PlatformAccount]:
        result = await self.session.execute(
            select(PlatformAccount).where(
                PlatformAccount.streamer_id == streamer_id,
                PlatformAccount.platform == platform,
            )
        )
        return result.scalar_one_or_none()

    async def get_all_active(self) -> List[PlatformAccount]:
        result = await self.session.execute(
            select(PlatformAccount)
            .options(selectinload(PlatformAccount.streamer))
            .where(PlatformAccount.is_active.is_(True))
        )
        return list(result.scalars().all())

    async def update_live_status(
        self,
        account_id: int,
        is_live: bool,
        stream_platform_id: Optional[str] = None,
    ) -> None:
        account = await self.get(account_id)
        if account:
            account.is_live = is_live
            account.current_stream_platform_id = stream_platform_id
            account.last_checked_at = datetime.now(timezone.utc)
            account.last_error = None
            account.consecutive_errors = 0
            await self.session.flush()

    async def record_error(self, account_id: int, error: str) -> None:
        account = await self.get(account_id)
        if account:
            account.last_error = error
            account.consecutive_errors += 1
            account.last_checked_at = datetime.now(timezone.utc)
            await self.session.flush()


class AssignmentRepository(BaseRepository[StreamerChannelAssignment]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(StreamerChannelAssignment, session)

    async def get_for_streamer(self, streamer_id: int) -> List[StreamerChannelAssignment]:
        result = await self.session.execute(
            select(StreamerChannelAssignment)
            .options(selectinload(StreamerChannelAssignment.channel))
            .where(
                StreamerChannelAssignment.streamer_id == streamer_id,
                StreamerChannelAssignment.is_active.is_(True),
            )
        )
        return list(result.scalars().all())

    async def get_by_streamer_and_channel(
        self, streamer_id: int, channel_id: int
    ) -> Optional[StreamerChannelAssignment]:
        result = await self.session.execute(
            select(StreamerChannelAssignment).where(
                StreamerChannelAssignment.streamer_id == streamer_id,
                StreamerChannelAssignment.channel_id == channel_id,
            )
        )
        return result.scalar_one_or_none()
