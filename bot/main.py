"""Bot entry point — wires together aiogram, APScheduler, and the service layer."""
from __future__ import annotations

import asyncio
import logging
from typing import List, Optional

import structlog
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardMarkup

from bot.handlers import admin, common, owner, streamer
from bot.middlewares.auth import AuthMiddleware
from config import settings
from db.database import close_db, init_db
from scheduler.polling import create_scheduler, set_bot_context
from services.template_service import PlatformLink

logger = structlog.get_logger(__name__)

# Singleton context — injected into scheduler and services
_bot_context: Optional["BotContext"] = None


def get_bot_context() -> "BotContext":
    if _bot_context is None:
        raise RuntimeError("BotContext not initialized")
    return _bot_context


class BotContext:
    """Holds the Bot instance and exposes notification callables for the service layer."""

    def __init__(self, bot: Bot) -> None:
        self.bot = bot

    async def send_notification(
        self,
        chat_id: int,
        text: str,
        platform_links: List[PlatformLink],
        thumbnail_url: Optional[str] = None,
    ) -> Optional[int]:
        """Send a stream notification message. Returns telegram message_id or None on failure."""
        from bot.keyboards.inline import stream_links_keyboard
        from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest

        keyboard = stream_links_keyboard(platform_links) if platform_links else None
        try:
            if thumbnail_url:
                msg = await self.bot.send_photo(
                    chat_id=chat_id,
                    photo=thumbnail_url,
                    caption=text,
                    reply_markup=keyboard,
                    parse_mode=ParseMode.MARKDOWN,
                )
            else:
                msg = await self.bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    reply_markup=keyboard,
                    parse_mode=ParseMode.MARKDOWN,
                    disable_web_page_preview=False,
                )
            return msg.message_id
        except TelegramForbiddenError:
            logger.error("bot.send.forbidden", chat_id=chat_id)
            return None
        except TelegramBadRequest as exc:
            logger.error("bot.send.bad_request", chat_id=chat_id, error=str(exc))
            return None
        except Exception as exc:
            logger.exception("bot.send.error", chat_id=chat_id)
            return None

    async def edit_notification(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        platform_links: List[PlatformLink],
    ) -> bool:
        from bot.keyboards.inline import stream_links_keyboard
        from aiogram.exceptions import TelegramBadRequest

        keyboard = stream_links_keyboard(platform_links) if platform_links else None
        try:
            await self.bot.edit_message_caption(
                chat_id=chat_id,
                message_id=message_id,
                caption=text,
                reply_markup=keyboard,
                parse_mode=ParseMode.MARKDOWN,
            )
            return True
        except TelegramBadRequest:
            # Message may not have a caption (text message) — try edit_message_text
            try:
                await self.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=text,
                    reply_markup=keyboard,
                    parse_mode=ParseMode.MARKDOWN,
                )
                return True
            except TelegramBadRequest as exc:
                if "message is not modified" in str(exc).lower():
                    return True  # no-op is OK
                logger.warning("bot.edit.failed", chat_id=chat_id, message_id=message_id, error=str(exc))
                return False
        except Exception as exc:
            logger.exception("bot.edit.error", chat_id=chat_id, message_id=message_id)
            return False

    async def delete_notification(self, chat_id: int, message_id: int) -> bool:
        from aiogram.exceptions import TelegramBadRequest

        try:
            await self.bot.delete_message(chat_id=chat_id, message_id=message_id)
            return True
        except TelegramBadRequest as exc:
            logger.warning("bot.delete.failed", chat_id=chat_id, message_id=message_id, error=str(exc))
            return False
        except Exception:
            logger.exception("bot.delete.error", chat_id=chat_id, message_id=message_id)
            return False


def _setup_logging() -> None:
    log_level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
    logging.basicConfig(level=log_level)
    if settings.LOG_FORMAT == "json":
        structlog.configure(
            processors=[
                structlog.contextvars.merge_contextvars,
                structlog.processors.add_log_level,
                structlog.processors.TimeStamper(fmt="iso"),
                structlog.processors.JSONRenderer(),
            ],
            wrapper_class=structlog.make_filtering_bound_logger(log_level),
            logger_factory=structlog.PrintLoggerFactory(),
        )
    else:
        structlog.configure(
            processors=[
                structlog.contextvars.merge_contextvars,
                structlog.processors.add_log_level,
                structlog.processors.TimeStamper(fmt="%Y-%m-%d %H:%M:%S"),
                structlog.dev.ConsoleRenderer(),
            ],
            wrapper_class=structlog.make_filtering_bound_logger(log_level),
            logger_factory=structlog.PrintLoggerFactory(),
        )


async def main() -> None:
    global _bot_context

    _setup_logging()
    logger.info("bot.starting")

    # Init database
    await init_db()
    logger.info("bot.db_ready")

    # Create bot and dispatcher
    bot = Bot(
        token=settings.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN),
    )
    dp = Dispatcher(storage=MemoryStorage())

    # Register middleware
    dp.update.middleware(AuthMiddleware())

    # Register routers
    dp.include_router(common.router)
    dp.include_router(owner.router)
    dp.include_router(admin.router)
    dp.include_router(streamer.router)

    # Create bot context and inject into scheduler
    _bot_context = BotContext(bot)
    set_bot_context(_bot_context)

    # Start scheduler
    scheduler = create_scheduler()
    scheduler.start()
    logger.info("bot.scheduler_started")

    try:
        logger.info("bot.polling_started")
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        scheduler.shutdown()
        await close_db()
        await bot.session.close()
        logger.info("bot.shutdown")


if __name__ == "__main__":
    asyncio.run(main())
