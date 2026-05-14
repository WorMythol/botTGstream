"""User management — create, role changes, access control checks."""
from __future__ import annotations

from typing import List, Optional

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import User, UserRole
from db.repositories.user_repo import UserRepository

logger = structlog.get_logger(__name__)


class UserService:
    def __init__(self, session: AsyncSession) -> None:
        self._repo = UserRepository(session)

    async def get_or_create(
        self, telegram_id: int, username: Optional[str], full_name: str
    ) -> User:
        return await self._repo.upsert(telegram_id, username, full_name)

    async def get_user(self, telegram_id: int) -> Optional[User]:
        return await self._repo.get_by_telegram_id(telegram_id)

    async def set_role(self, telegram_id: int, role: UserRole) -> Optional[User]:
        user = await self._repo.get_by_telegram_id(telegram_id)
        if user is None:
            return None
        user.role = role
        logger.info("user.role_changed", user_id=telegram_id, role=role)
        return user

    async def deactivate(self, telegram_id: int) -> bool:
        user = await self._repo.get_by_telegram_id(telegram_id)
        if user is None:
            return False
        user.is_active = False
        logger.info("user.deactivated", user_id=telegram_id)
        return True

    async def list_admins(self) -> List[User]:
        return await self._repo.get_by_role(UserRole.ADMIN)

    async def list_all_active(self) -> List[User]:
        return await self._repo.get_all_active()

    async def can_access(self, telegram_id: int, required_role: UserRole) -> bool:
        """Return True if user has at least the required role level."""
        user = await self._repo.get_by_telegram_id(telegram_id)
        if user is None or not user.is_active:
            return False
        role_order = [UserRole.STREAMER, UserRole.ADMIN, UserRole.OWNER]
        try:
            user_level = role_order.index(user.role)
            required_level = role_order.index(required_role)
            return user_level >= required_level
        except ValueError:
            return False
