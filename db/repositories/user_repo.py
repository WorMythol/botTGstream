"""User repository — CRUD + role queries."""
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
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
        """Atomic upsert: INSERT … ON CONFLICT (id) DO UPDATE.

        Eliminates the race condition where two concurrent requests from the
        same user both SELECT → find nothing → both INSERT, causing a
        UniqueViolationError on the primary key.

        After the core-level upsert, session.get() loads the ORM object from
        the identity map (no extra SELECT if already cached, one SELECT
        otherwise) so we always return a properly tracked User instance.
        """
        stmt = (
            pg_insert(User)
            .values(id=telegram_id, username=username, full_name=full_name)
            .on_conflict_do_update(
                index_elements=["id"],
                set_={"username": username, "full_name": full_name},
            )
        )
        await self.session.execute(stmt)
        await self.session.flush()
        # Re-fetch via SELECT so we always get a fresh, session-tracked ORM object.
        # (Core-level pg_insert doesn't populate the ORM identity map.)
        result = await self.session.execute(
            select(User).where(User.id == telegram_id)
        )
        return result.scalar_one()
