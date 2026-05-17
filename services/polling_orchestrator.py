"""Polling orchestration logic — account checking, result processing, admin notifications.

Extracted from scheduler/polling.py so the scheduler module only contains
job definitions and scheduling setup, not business logic.

Public surface:
  filter_by_priority(streamers)     — filter list by poll priority
  check_account(account, http)      — one-shot live check for a platform account
  PollOrchestrator                  — stateful orchestrator per poll cycle
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Dict, Optional, Set

import structlog

from config import settings
from db.models import Platform, UserRole
from db.repositories.streamer_repo import PlatformAccountRepository, StreamerRepository
from integrations import VKIntegration, YouTubeIntegration
from integrations.base import PlatformCheckResult, StreamInfo

if TYPE_CHECKING:
    import aiohttp
    from sqlalchemy.ext.asyncio import AsyncSession
    from bot.main import BotContext

logger = structlog.get_logger(__name__)


# ── Stateless helpers ─────────────────────────────────────────────────────────

def filter_by_priority(streamers: list) -> list:
    """Feature 9: Skip low-priority (1) streamers on alternating poll cycles.

    Uses current UTC minute parity — low-priority streamers are polled only
    on even minutes, halving their effective poll frequency without extra jobs.
    """
    minute = datetime.now(timezone.utc).minute
    result = []
    for s in streamers:
        priority = getattr(s, "poll_priority", 2)
        if priority == 1 and minute % 2 != 0:
            continue  # skip this cycle
        result.append(s)
    return result


async def check_account(account, http: "aiohttp.ClientSession") -> PlatformCheckResult:
    """Return live-check result for a single platform account."""
    from services.http_client import get_twitch_client
    if account.platform == Platform.YOUTUBE:
        client = YouTubeIntegration(settings.YOUTUBE_API_KEY, http)
        return await client.check_live(
            platform_id=account.platform_id,
            known_video_id=account.current_stream_platform_id if account.is_live else None,
        )
    if account.platform == Platform.TWITCH:
        return await get_twitch_client().check_live(account.platform_id)
    if account.platform == Platform.VK:
        client = VKIntegration(settings.VK_ACCESS_TOKEN, settings.VK_API_VERSION, http)
        return await client.check_live(account.platform_id)
    return PlatformCheckResult(is_live=False, error="unknown platform")


# ── Stateful orchestrator ─────────────────────────────────────────────────────

class PollOrchestrator:
    """Orchestrates per-cycle result processing and admin notifications.

    Instantiated once per poll cycle inside a DB session context.
    """

    def __init__(
        self,
        session: "AsyncSession",
        bot_context: Optional["BotContext"] = None,
    ) -> None:
        self._session = session
        self._ctx = bot_context

    # ── Account result handling ───────────────────────────────────────────────

    async def process_account_result(
        self,
        account,
        result: PlatformCheckResult,
        account_repo: PlatformAccountRepository,
    ) -> None:
        """Update DB state after a live-check: error counters, live flag, auto-disable."""
        if result.error and result.error not in ("quotaExceeded", "rate_limited"):
            await account_repo.record_error(account.id, result.error)
            errors_after = account.consecutive_errors + 1
            if errors_after >= settings.MAX_CONSECUTIVE_ERRORS:
                streamer_repo = StreamerRepository(self._session)
                disabled = await streamer_repo.increment_errors(
                    account.streamer_id, settings.MAX_CONSECUTIVE_ERRORS
                )
                if disabled:
                    logger.warning(
                        "streamer.auto_disabled",
                        streamer_id=account.streamer_id,
                        platform=account.platform,
                        errors=errors_after,
                    )
                    if self._ctx:
                        await self.notify_admins_streamer_disabled(account.streamer_id)
        elif result.is_live:
            stream_id = result.stream.platform_stream_id if result.stream else None
            await account_repo.update_live_status(account.id, True, stream_id)
            await StreamerRepository(self._session).reset_errors(account.streamer_id)
        else:
            await account_repo.update_live_status(account.id, False, None)

    # ── Stream result processing ──────────────────────────────────────────────

    async def process_stream_results(
        self,
        results: Dict[int, Dict[Platform, StreamInfo]],
        streamer_ids: Optional[Set[int]] = None,
    ) -> None:
        """Open/close stream sessions and dispatch Telegram/Discord/VK notifications.

        Args:
            results:      {streamer_id: {platform: StreamInfo}} for live streamers.
            streamer_ids: Subset of streamer IDs to process. None = all active.
        """
        if self._ctx is None:
            return

        from services.discord_service import DiscordService
        from services.gamification_service import GamificationService
        from services.notification_service import NotificationService
        from services.stream_service import StreamService

        notif_service = NotificationService(
            session=self._session,
            send_fn=self._ctx.send_notification,
            edit_fn=self._ctx.edit_notification,
            delete_fn=self._ctx.delete_notification,
            vk_send_fn=getattr(self._ctx, "send_vk_notification", None),
        )
        stream_service = StreamService(
            session=self._session,
            notification_service=notif_service,
            gamification_service=GamificationService(self._session),
            discord_service=DiscordService(self._session),
        )

        # Resolve which streamers to process
        if streamer_ids is not None:
            all_ids = streamer_ids
        else:
            all_active = await StreamerRepository(self._session).get_active_streamers()
            all_ids = {s.id for s in all_active}

        for streamer_id in all_ids:
            live_map = results.get(streamer_id, {})
            try:
                await stream_service.process_live_results(streamer_id, live_map)
            except Exception:
                logger.exception("stream_service.error", streamer_id=streamer_id)

    # ── Admin notifications ───────────────────────────────────────────────────

    async def notify_admins_streamer_disabled(self, streamer_id: int) -> None:
        """DM all admins and owners when a streamer is auto-disabled."""
        if self._ctx is None:
            return
        from db.repositories.user_repo import UserRepository
        user_repo = UserRepository(self._session)
        streamer = await StreamerRepository(self._session).get(streamer_id)
        name = streamer.display_name if streamer else f"#{streamer_id}"
        recipients = (
            await user_repo.get_by_role(UserRole.ADMIN)
            + await user_repo.get_by_role(UserRole.OWNER)
        )
        for user in recipients:
            try:
                await self._ctx.bot.send_message(
                    user.id,
                    f"⛔ *Streamer auto-disabled*\n\n"
                    f"*{name}* was disabled after {settings.MAX_CONSECUTIVE_ERRORS} "
                    f"consecutive API errors.\n\n"
                    f"Use /list\\_streamers → Resume to re-enable once resolved.",
                    parse_mode="Markdown",
                )
            except Exception:
                pass

    async def notify_admins_quota_exceeded(self) -> None:
        """DM all admins and owners when YouTube quota is exhausted."""
        if self._ctx is None:
            return
        from db.repositories.user_repo import UserRepository
        user_repo = UserRepository(self._session)
        recipients = (
            await user_repo.get_by_role(UserRole.ADMIN)
            + await user_repo.get_by_role(UserRole.OWNER)
        )
        for user in recipients:
            try:
                await self._ctx.bot.send_message(
                    user.id,
                    "⚠️ *YouTube API quota exceeded!*\n\n"
                    "YouTube polling has been halted for today. "
                    "Quota resets at midnight Pacific Time.\n\n"
                    "Use /update\\_api\\_key to set a new key if needed.",
                    parse_mode="Markdown",
                )
            except Exception:
                pass
