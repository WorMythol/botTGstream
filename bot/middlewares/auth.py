"""Auth middleware — auto-creates users and enriches handler data with user record."""
from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict

import structlog
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Update

from db.database import get_session
from db.models import UserRole
from db.repositories.user_repo import UserRepository
from config import settings

logger = structlog.get_logger(__name__)


class AuthMiddleware(BaseMiddleware):
    """Register every user on first interaction and inject their User record into handler data."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        # Extract Telegram user from any update type
        tg_user = None
        if hasattr(event, "message") and event.message:
            tg_user = event.message.from_user
        elif hasattr(event, "callback_query") and event.callback_query:
            tg_user = event.callback_query.from_user

        if tg_user is None:
            return await handler(event, data)

        async with get_session() as session:
            repo = UserRepository(session)
            user = await repo.upsert(
                telegram_id=tg_user.id,
                username=tg_user.username,
                full_name=tg_user.full_name,
            )
            # Bootstrap: first run — owner gets the owner role automatically
            if tg_user.id == settings.OWNER_TELEGRAM_ID and user.role != UserRole.OWNER:
                user.role = UserRole.OWNER
                logger.info("auth.owner_role_assigned", user_id=tg_user.id)

            if not user.is_active:
                # Silently drop inactive users
                return

            data["db_user"] = user
            # Note: db_session intentionally NOT injected — handlers open their own sessions
            return await handler(event, data)
