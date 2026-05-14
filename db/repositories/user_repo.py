"""User repository — CRUD + role queries."""
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import User, UserRole
from db.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(User, session)

    async def get_by_telegram_id(self, telegram_id: int) -> Optional[User]:
        result = await self.session.execute(
            select(User).where(User.id == telegram_id)
        )
        return result.scalar_one_or_none()

    async def get_by_role(self, role: UserRole) -> List[User]:
        result = await self.session.execute(
            select(User).where(User.role == role, User.is_active.is_(True))
        )
        return list(result.scalars().all())

    async def get_all_active(self) -> List[User]:
        result = await self.session.execute(
            select(User).where(User.is_active.is_(True))
        )
        return list(result.scalars().all())

    async def upsert(self, telegram_id: int, username: Optional[str], full_name: str) -> User:
        """Create user if not exists, update name/username if exists."""
        user = await self.get_by_telegram_id(telegram_id)
        if user is None:
            user = User(id=telegram_id, username=username, full_name=full_name)
            self.session.add(user)
        else:
            user.username = username
            user.full_name = full_name
        await self.session.flush()
        return user
