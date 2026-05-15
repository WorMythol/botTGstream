"""APScheduler-based polling engine.

Polling strategy per platform:
  YouTube  — quota-aware; switches from search.list to videos.list once stream detected.
  Twitch   — respects rate-limit headers; skips poll cycle if rate-limited.
  VK       — simple periodic poll.

Each platform runs on its own scheduler job at the configured interval.
"""
from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Dict, Optional

import aiohttp
import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import settings
from db.database import get_session
from db.models import Platform
from db.repositories.streamer_repo import PlatformAccountRepository, StreamerRepository
from db.repositories.stream_repo import StreamRepository
from integrations import TwitchIntegration, VKIntegration, YouTubeIntegration
from integrations.base import PlatformCheckResult, StreamInfo
from services.notification_service import NotificationService
from services.stream_service import StreamService

if TYPE_CHECKING:
    from bot.main import BotContext

logger = structlog.get_logger(__name__)

_http_session: Optional[aiohttp.ClientSession] = None
_twitch_client: Optional[TwitchIntegration] = None
_bot_context: Optional["BotContext"] = None


def set_bot_context(ctx: "BotContext") -> None:
    global _bot_context
    _bot_context = ctx


def get_http_session() -> aiohttp.ClientSession:
    global _http_session
    if _http_session is None or _http_session.closed:
        timeout = aiohttp.ClientTimeout(total=settings.REQUEST_TIMEOUT)
        _http_session = aiohttp.ClientSession(timeout=timeout)
    return _http_session


def get_twitch_client() -> TwitchIntegration:
    global _twitch_client
    if _twitch_client is None:
        _twitch_client = TwitchIntegration(
            client_id=settings.TWITCH_CLIENT_ID,
            client_secret=settings.TWITCH_CLIENT_SECRET,
            http_session=get_http_session(),
        )
    return _twitch_client


def create_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        poll_youtube, "interval", seconds=settings.POLL_INTERVAL_YOUTUBE, id="poll_youtube",
        max_instances=1, coalesce=True,
    )
    scheduler.add_job(
        poll_twitch, "interval", seconds=settings.POLL_INTERVAL_TWITCH, id="poll_twitch",
        max_instances=1, coalesce=True,
    )
    scheduler.add_job(
        poll_vk, "interval", seconds=settings.POLL_INTERVAL_VK, id="poll_vk",
        max_instances=1, coalesce=True,
    )
    return scheduler


# ── Per-platform poll functions ───────────────────────────────────────────────

async def poll_youtube() -> None:
    logger.debug("poll.youtube.start")
    async with get_session() as session:
        streamer_repo = StreamerRepository(session)
        account_repo = PlatformAccountRepository(session)
        streamers = await streamer_repo.get_active_streamers()

        yt_client = YouTubeIntegration(settings.YOUTUBE_API_KEY, get_http_session())
        total_quota = 0
        results: Dict[int, Dict[Platform, StreamInfo]] = defaultdict(dict)

        for streamer in streamers:
            for account in streamer.platform_accounts:
                if account.platform != Platform.YOUTUBE or not account.is_active:
                    continue
                result = await yt_client.check_live(
                    platform_id=account.platform_id,
                    known_video_id=account.current_stream_platform_id if account.is_live else None,
                )
                total_quota += result.quota_cost

                if result.error == "quotaExceeded":
                    logger.error("poll.youtube.quota_exceeded")
                    # FIX C-3: persist quota consumed BEFORE returning, so it's not lost
                    from db.repositories.polling_repo import PollingStateRepository
                    _ps_repo = PollingStateRepository(session)
                    await _ps_repo.add_youtube_quota(total_quota)
                    await _ps_repo.record_poll(Platform.YOUTUBE)
                    if _bot_context:
                        await _notify_admins_quota_exceeded(session)
                    return

                await _process_account_result(session, account, result, account_repo)
                if result.is_live and result.stream:
                    results[streamer.id][Platform.YOUTUBE] = result.stream

        # FIX M-2: persist quota usage so /health shows real numbers
        from db.repositories.polling_repo import PollingStateRepository
        ps_repo = PollingStateRepository(session)
        new_total = await ps_repo.add_youtube_quota(total_quota)
        await ps_repo.record_poll(Platform.YOUTUBE)

        # Warn admins if quota approaching limit
        if new_total >= settings.YOUTUBE_QUOTA_WARNING_THRESHOLD and _bot_context:
            await _notify_admins_quota_exceeded(session)

        await _process_stream_results(session, results)
        logger.info("poll.youtube.done", quota_used=total_quota, total_today=new_total)


async def poll_twitch() -> None:
    logger.debug("poll.twitch.start")
    twitch = get_twitch_client()

    if twitch.is_rate_limited:
        logger.info("poll.twitch.rate_limited_skip")
        return

    async with get_session() as session:
        streamer_repo = StreamerRepository(session)
        account_repo = PlatformAccountRepository(session)
        streamers = await streamer_repo.get_active_streamers()
        results: Dict[int, Dict[Platform, StreamInfo]] = defaultdict(dict)

        for streamer in streamers:
            for account in streamer.platform_accounts:
                if account.platform != Platform.TWITCH or not account.is_active:
                    continue
                result = await twitch.check_live(account.platform_id)
                await _process_account_result(session, account, result, account_repo)
                if result.is_live and result.stream:
                    results[streamer.id][Platform.TWITCH] = result.stream

        # Persist refreshed Twitch token + record poll time (FIX M-2)
        from db.repositories.polling_repo import PollingStateRepository
        ps_repo = PollingStateRepository(session)
        ps = await ps_repo.get_or_create(Platform.TWITCH)
        token, expires_at = twitch.get_token_state()
        if token:
            ps.twitch_access_token = token
            ps.twitch_token_expires_at = datetime.fromtimestamp(expires_at, tz=timezone.utc)
        ps.last_poll_at = datetime.now(timezone.utc)
        await session.flush()  # FIX M-6: persist token before stream processing that may raise

        await _process_stream_results(session, results)
        logger.info("poll.twitch.done")


async def poll_vk() -> None:
    logger.debug("poll.vk.start")
    async with get_session() as session:
        streamer_repo = StreamerRepository(session)
        account_repo = PlatformAccountRepository(session)
        streamers = await streamer_repo.get_active_streamers()
        vk_client = VKIntegration(settings.VK_ACCESS_TOKEN, settings.VK_API_VERSION, get_http_session())
        results: Dict[int, Dict[Platform, StreamInfo]] = defaultdict(dict)

        for streamer in streamers:
            for account in streamer.platform_accounts:
                if account.platform != Platform.VK or not account.is_active:
                    continue
                result = await vk_client.check_live(account.platform_id)
                await _process_account_result(session, account, result, account_repo)
                if result.is_live and result.stream:
                    results[streamer.id][Platform.VK] = result.stream

        from db.repositories.polling_repo import PollingStateRepository
        await PollingStateRepository(session).record_poll(Platform.VK)

        await _process_stream_results(session, results)
        logger.info("poll.vk.done")


# ── Manual trigger ────────────────────────────────────────────────────────────

async def trigger_poll_for_streamer(streamer_id: int) -> Dict[str, bool]:
    """Manually trigger a full platform poll for a single streamer.

    Returns dict of {platform: is_live}.
    """
    http = get_http_session()
    results: Dict[str, bool] = {}

    async with get_session() as session:
        account_repo = PlatformAccountRepository(session)
        streamer_repo = StreamerRepository(session)
        streamer = await streamer_repo.get_with_accounts(streamer_id)
        if streamer is None:
            return results

        live_map: Dict[Platform, StreamInfo] = {}
        for account in streamer.platform_accounts:
            if not account.is_active:
                continue
            result = await _check_account(account, http)
            await _process_account_result(session, account, result, account_repo)
            results[account.platform.value] = result.is_live
            if result.is_live and result.stream:
                live_map[account.platform] = result.stream

        await _process_stream_results(session, {streamer_id: live_map} if live_map else {})
    return results


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _check_account(account, http: aiohttp.ClientSession) -> PlatformCheckResult:
    if account.platform == Platform.YOUTUBE:
        client = YouTubeIntegration(settings.YOUTUBE_API_KEY, http)
        return await client.check_live(account.platform_id)
    if account.platform == Platform.TWITCH:
        return await get_twitch_client().check_live(account.platform_id)
    if account.platform == Platform.VK:
        client = VKIntegration(settings.VK_ACCESS_TOKEN, settings.VK_API_VERSION, http)
        return await client.check_live(account.platform_id)
    return PlatformCheckResult(is_live=False, error="unknown platform")


async def _process_account_result(
    session,
    account,
    result: PlatformCheckResult,
    account_repo: PlatformAccountRepository,
) -> None:
    if result.error and result.error not in ("quotaExceeded", "rate_limited"):
        await account_repo.record_error(account.id, result.error)
        # FIX M-3: actually disable the streamer in DB, not just log a warning
        errors_after = account.consecutive_errors + 1
        if errors_after >= settings.MAX_CONSECUTIVE_ERRORS:
            streamer_repo = StreamerRepository(session)
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
                # Notify admins
                if _bot_context:
                    await _notify_admins_streamer_disabled(session, account.streamer_id)
    elif result.is_live:
        stream_id = result.stream.platform_stream_id if result.stream else None
        await account_repo.update_live_status(account.id, True, stream_id)
        # FIX C-2: removed dead StreamerRepository(session) call
        await StreamerRepository(session).reset_errors(account.streamer_id)
    else:
        await account_repo.update_live_status(account.id, False, None)


async def _process_stream_results(
    session,
    results: Dict[int, Dict[Platform, StreamInfo]],
) -> None:
    """For each streamer, get all their live platforms and process together."""
    if _bot_context is None:
        return

    notif_service = NotificationService(
        session=session,
        send_fn=_bot_context.send_notification,
        edit_fn=_bot_context.edit_notification,
        delete_fn=_bot_context.delete_notification,
    )
    stream_service = StreamService(session=session, notification_service=notif_service)

    # Also include streamers with NO live results (need to close active streams)
    streamer_repo = StreamerRepository(session)
    all_active = await streamer_repo.get_active_streamers()
    all_streamer_ids = {s.id for s in all_active}

    for streamer_id in all_streamer_ids:
        live_map = results.get(streamer_id, {})
        try:
            await stream_service.process_live_results(streamer_id, live_map)
        except Exception as exc:
            logger.exception("stream_service.error", streamer_id=streamer_id, error=str(exc))


async def _notify_admins_streamer_disabled(session, streamer_id: int) -> None:
    """Notify admins when a streamer is auto-disabled due to repeated errors."""
    if _bot_context is None:
        return
    from db.repositories.user_repo import UserRepository
    from db.repositories.streamer_repo import StreamerRepository
    from db.models import UserRole
    user_repo = UserRepository(session)
    streamer = await StreamerRepository(session).get(streamer_id)
    name = streamer.display_name if streamer else f"#{streamer_id}"
    admins = await user_repo.get_by_role(UserRole.ADMIN)
    owners = await user_repo.get_by_role(UserRole.OWNER)
    for user in admins + owners:
        try:
            await _bot_context.bot.send_message(
                user.id,
                f"⛔ *Streamer auto-disabled*\n\n"
                f"*{name}* was disabled after {settings.MAX_CONSECUTIVE_ERRORS} consecutive API errors.\n\n"
                f"Use /list\\_streamers → Resume to re-enable once the issue is resolved.",
                parse_mode="Markdown",
            )
        except Exception:
            pass


async def _notify_admins_quota_exceeded(session) -> None:
    if _bot_context is None:
        return
    from db.repositories.user_repo import UserRepository
    from db.models import UserRole
    user_repo = UserRepository(session)
    admins = await user_repo.get_by_role(UserRole.ADMIN)
    owners = await user_repo.get_by_role(UserRole.OWNER)
    for user in admins + owners:
        try:
            await _bot_context.bot.send_message(
                user.id,
                "⚠️ *YouTube API quota exceeded!*\n\nYouTube polling has been halted for today. "
                "Quota resets at midnight Pacific Time. Use /update\\_api\\_key to set a new key if needed.",
                parse_mode="Markdown",
            )
        except Exception:
            pass
