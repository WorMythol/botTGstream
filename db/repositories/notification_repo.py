"""Notification repository."""
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Notification, NotificationStatus
from db.repositories.base import BaseRepository


class NotificationRepository(BaseRepository[Notification]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(Notification, session)

    async def get_for_stream_and_channel(
        self, stream_id: int, channel_id: int
    ) -> Optional[Notification]:
        result = await self.session.execute(
            select(Notification).where(
                Notification.stream_id == stream_id,
                Notification.channel_id == channel_id,
                Notification.status.notin_([NotificationStatus.DELETED, NotificationStatus.FAILED]),
            )
        )
        return result.scalar_one_or_none()

    async def get_active_for_stream(self, stream_id: int) -> List[Notification]:
        result = await self.session.execute(
            select(Notification)
            .options(selectinload(Notification.channel))
            .where(
                Notification.stream_id == stream_id,
                Notification.status.notin_([NotificationStatus.DELETED, NotificationStatus.FAILED]),
            )
        )
        return list(result.scalars().all())

    async def get_all_for_stream(self, stream_id: int) -> List[Notification]:
        result = await self.session.execute(
            select(Notification)
            .options(selectinload(Notification.channel))
            .where(Notification.stream_id == stream_id)
        )
        return list(result.scalars().all())

    async def get_with_channel(self, notification_id: int) -> Optional[Notification]:
        """Load notification with channel eagerly — use instead of get() when channel is needed."""
        # FIX C-2: BaseRepository.get() uses session.get() with no selectinload,
        # accessing .channel in async context raises MissingGreenlet.
        result = await self.session.execute(
            select(Notification)
            .options(selectinload(Notification.channel))
            .where(Notification.id == notification_id)
        )
        return result.scalar_one_or_none()
