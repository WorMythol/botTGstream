"""Telegram channel repository."""
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import TelegramChannel
from db.repositories.base import BaseRepository


class ChannelRepository(BaseRepository[TelegramChannel]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(TelegramChannel, session)

    async def get_by_telegram_id(self, telegram_id: int) -> Optional[TelegramChannel]:
        result = await self.session.execute(
            select(TelegramChannel).where(TelegramChannel.telegram_id == telegram_id)
        )
        return result.scalar_one_or_none()

    async def get_active(self) -> List[TelegramChannel]:
        result = await self.session.execute(
            select(TelegramChannel).where(TelegramChannel.is_active.is_(True))
        )
        return list(result.scalars().all())
