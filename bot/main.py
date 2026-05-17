"""Bot entry point — wires together aiogram, APScheduler, and the service layer.

Feature 5: Webhook mode activated when WEBHOOK_URL is set in config.
Feature 11: Bot uptime tracked here and exposed to /health command.
Feature 12: VK Bot API send callable injected into BotContext.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import List, Optional

import structlog
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from bot.handlers import admin, common, gamification, owner, streamer
from bot.middlewares.auth import AuthMiddleware
from bot.middlewares.maintenance import MaintenanceMiddleware
from config import settings
from db.database import close_db, init_db
from scheduler.polling import create_scheduler, set_bot_context
from services.http_client import close_http_session
from services.template_service import PlatformLink

logger = structlog.get_logger(__name__)

# Singleton context — injected into scheduler and services
_bot_context: Optional["BotContext"] = None

# Feature 11: uptime tracking
_bot_started_at: Optional[datetime] = None


def get_bot_context() -> "BotContext":
    if _bot_context is None:
        raise RuntimeError("BotContext not initialized")
    return _bot_context


def get_uptime_seconds() -> Optional[float]:
    """Feature 11: Return bot uptime in seconds, or None if not started."""
    if _bot_started_at is None:
        return None
    return (datetime.now(timezone.utc) - _bot_started_at).total_seconds()


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
        is_photo_message: bool = False,  # FIX M-1: use correct edit method per message type
    ) -> bool:
        from bot.keyboards.inline import stream_links_keyboard
        from aiogram.exceptions import TelegramBadRequest

        keyboard = stream_links_keyboard(platform_links) if platform_links else None
        try:
            if is_photo_message:
                # Photo messages must be edited via edit_message_caption
                await self.bot.edit_message_caption(
                    chat_id=chat_id,
                    message_id=message_id,
                    caption=text,
                    reply_markup=keyboard,
                    parse_mode=ParseMode.MARKDOWN,
                )
            else:
                # Plain text messages use edit_message_text
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

    # ── Feature 12: VK Bot API delivery ──────────────────────────────────────

    async def send_vk_notification(
        self,
        peer_id: int,
        text: str,
        platform_links: List[PlatformLink],
        thumbnail_url: Optional[str] = None,
    ) -> Optional[int]:
        """Send a message to VK community chat via VK Bot API.

        Requires VK_GROUP_TOKEN and VK_GROUP_ID to be configured.
        Returns VK message_id or None on failure.
        """
        if not settings.VK_GROUP_TOKEN or not settings.VK_GROUP_ID:
            return None

        import aiohttp as _aiohttp
        from scheduler.polling import get_http_session

        http = get_http_session()
        params = {
            "peer_id": peer_id,
            "message": text,
            "random_id": int(datetime.now(timezone.utc).timestamp() * 1000) % 2147483647,
            "access_token": settings.VK_GROUP_TOKEN,
            "v": settings.VK_API_VERSION,
        }
        try:
            async with http.post(
                "https://api.vk.com/method/messages.send",
                data=params,
            ) as resp:
                data = await resp.json()
            if "error" in data:
                err = data["error"]
                logger.error("vk.send.error", code=err.get("error_code"), msg=err.get("error_msg"))
                return None
            return data.get("response")  # VK message_id
        except Exception as exc:
            logger.exception("vk.send.exception", peer_id=peer_id)
            return None


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
    global _bot_context, _bot_started_at

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

    # Register middleware (order matters — auth first, then maintenance gate)
    dp.update.middleware(AuthMiddleware())
    dp.update.middleware(MaintenanceMiddleware())

    # Register routers
    dp.include_router(common.router)
    dp.include_router(owner.router)
    dp.include_router(admin.router)
    dp.include_router(streamer.router)
    dp.include_router(gamification.router)

    # Create bot context and inject into scheduler
    _bot_context = BotContext(bot)
    set_bot_context(_bot_context)

    # Start scheduler
    scheduler = create_scheduler()
    scheduler.start()
    logger.info("bot.scheduler_started")

    # Feature 11: record start time for uptime tracking
    _bot_started_at = datetime.now(timezone.utc)

    try:
        if settings.WEBHOOK_URL:
            # Feature 5: Webhook mode
            await _run_webhook(bot, dp)
        else:
            logger.info("bot.polling_started")
            await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        scheduler.shutdown()
        await close_db()
        await bot.session.close()
        await close_http_session()  # shared aiohttp session (polling + discord + streamer_service)
        logger.info("bot.shutdown")


async def _run_webhook(bot: Bot, dp: Dispatcher) -> None:
    """Feature 5: Run bot in webhook mode using aiohttp server."""
    from aiohttp import web
    from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

    webhook_path = f"/webhook/{settings.BOT_TOKEN}"
    full_url = settings.WEBHOOK_URL.rstrip("/") + webhook_path

    await bot.set_webhook(
        url=full_url,
        secret_token=settings.WEBHOOK_SECRET or None,
        drop_pending_updates=True,
    )
    logger.info("bot.webhook_set", url=full_url)

    app = web.Application()
    SimpleRequestHandler(
        dispatcher=dp,
        bot=bot,
        secret_token=settings.WEBHOOK_SECRET or None,
    ).register(app, path=webhook_path)
    setup_application(app, dp, bot=bot)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host=settings.WEBHOOK_HOST, port=settings.WEBHOOK_PORT)
    await site.start()

    logger.info("bot.webhook_listening", host=settings.WEBHOOK_HOST, port=settings.WEBHOOK_PORT)
    # Run indefinitely
    await asyncio.Event().wait()


if __name__ == "__main__":
    import sys
    try:
        asyncio.run(main())
    except Exception as exc:
        import traceback
        traceback.print_exc()
        sys.exit(1)
