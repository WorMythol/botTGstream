"""Maintenance mode middleware — blocks all non-owner commands while active.

Maintenance mode is stored in the system_settings table under key 'maintenance_mode':
  "0"            — disabled
  "1"            — enabled indefinitely
  "<ISO datetime>" — enabled until that UTC timestamp

Owner-role users always pass through so they can /maintenance off even mid-window.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict

import structlog
from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from bot.texts import T
from db.database import get_session
from db.models import UserRole

logger = structlog.get_logger(__name__)


class MaintenanceMiddleware(BaseMiddleware):
    """Gate middleware that silently drops (or politely rejects) requests during maintenance."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        # Check maintenance mode
        if await _maintenance_active():
            # Allow owner through unconditionally
            user = data.get("db_user")
            if user and user.role == UserRole.OWNER:
                return await handler(event, data)

            # Notify the user
            if isinstance(event, Message):
                await event.answer(T.MAINTENANCE_ACTIVE, parse_mode="Markdown")
            elif isinstance(event, CallbackQuery):
                await event.answer(T.MAINTENANCE_ACTIVE_CALLBACK, show_alert=True)
            return  # block further processing

        return await handler(event, data)


async def _maintenance_active() -> bool:
    """Return True if maintenance mode is currently active."""
    try:
        async with get_session() as session:
            from sqlalchemy import select
            from db.models import SystemSetting
            result = await session.execute(
                select(SystemSetting).where(SystemSetting.key == "maintenance_mode")
            )
            setting = result.scalar_one_or_none()
            if setting is None or setting.value in ("0", "false", ""):
                return False
            if setting.value in ("1", "true"):
                return True
            # Timed maintenance: value is ISO datetime "until"
            try:
                until = datetime.fromisoformat(setting.value)
                if until.tzinfo is None:
                    until = until.replace(tzinfo=timezone.utc)
                return datetime.now(timezone.utc) < until
            except ValueError:
                return False
    except Exception as exc:
        logger.warning("maintenance.check_failed", error=str(exc))
        return False  # Fail open — don't block if DB is down
