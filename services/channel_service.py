"""Telegram channel management."""
from __future__ import annotations

from typing import List, Optional

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import TelegramChannel
from db.repositories.channel_repo import ChannelRepository

logger = structlog.get_logger(__name__)


class ChannelService:
    def __init__(self, session: AsyncSession) -> None:
        self._repo = ChannelRepository(session)

    async def add_channel(
        self,
        telegram_id: int,
        title: str,
        username: Optional[str],
        added_by: int,
    ) -> tuple[TelegramChannel, bool]:
        """Add channel. Returns (channel, created) — created=False if already existed."""
        existing = await self._repo.get_by_telegram_id(telegram_id)
        if existing:
            existing.title = title
            existing.username = username
            existing.is_active = True
            await self._session_flush()
            return existing, False

        channel = TelegramChannel(
            telegram_id=telegram_id,
            title=title,
            username=username,
            added_by=added_by,
        )
        await self._repo.add(channel)
        logger.info("channel.added", telegram_id=telegram_id, title=title)
        return channel, True

    async def remove_channel(self, channel_id: int) -> bool:
        channel = await self._repo.get(channel_id)
        if channel is None:
            return False
        channel.is_active = False
        await self._session_flush()
        logger.info("channel.removed", channel_id=channel_id)
        return True

    async def list_channels(self) -> List[TelegramChannel]:
        return await self._repo.get_active()

    async def get_channel(self, channel_id: int) -> Optional[TelegramChannel]:
        return await self._repo.get(channel_id)

    async def get_by_telegram_id(self, telegram_id: int) -> Optional[TelegramChannel]:
        return await self._repo.get_by_telegram_id(telegram_id)

    async def _session_flush(self) -> None:
        await self._repo.session.flush()
