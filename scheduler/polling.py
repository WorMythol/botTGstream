"""APScheduler-based polling engine.

Polling strategy per platform:
  YouTube  — quota-aware; switches from search.list to videos.list once stream detected.
  Twitch   — respects rate-limit headers; skips poll cycle if rate-limited.
  VK       — simple periodic poll.

Feature 9: Per-streamer poll priority.
  Priority 3 (high)   — polled every ~60 seconds via high-priority job
  Priority 2 (normal) — polled every POLL_INTERVAL_* (default 300s)
  Priority 1 (low)    — polled every POLL_INTERVAL_* * 2 (default 600s)

Feature 2: Retry job runs every 60 seconds, retries FAILED notifications.

Sprint 2 additions:
  - Maintenance mode check before every poll cycle (skips if active)
  - Daily streak-reset job at 00:05 UTC
  - Daily pg_dump backup job at 03:00 UTC (if BACKUP_DIR configured)
  - Hot-reload: poll intervals reschedule themselves if settings changed
"""
from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Dict, Optional, Set

import aiohttp
import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import settings
from db.database import get_session
from db.models import Platform, Streamer
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

# Feature 9: track which streamer IDs have been covered by high-priority job
# so normal job skips them in the same cycle (avoids double-polling)
_high_priority_checked: Set[int] = set()
_last_high_priority_run: Optional[datetime] = None


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

    # Normal platform poll jobs
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

    # Feature 9: High-priority poll job — runs every 60 seconds for priority=3 streamers
    scheduler.add_job(
        poll_high_priority, "interval", seconds=60, id="poll_high_priority",
        max_instances=1, coalesce=True,
    )

    # Feature 2: Retry failed notifications every 60 seconds
    scheduler.add_job(
        retry_notifications, "interval", seconds=60, id="retry_notifications",
        max_instances=1, coalesce=True,
    )

    # Sprint 2: Daily streak reset at 00:05 UTC
    scheduler.add_job(
        reset_streaks_daily, "cron", hour=0, minute=5, id="reset_streaks",
        max_instances=1, coalesce=True,
    )

    # Sprint 2: Daily pg_dump backup at 03:00 UTC (only if BACKUP_DIR configured)
    if settings.BACKUP_DIR:
        scheduler.add_job(
            run_backup, "cron", hour=3, minute=0, id="run_backup",
            max_instances=1, coalesce=True,
        )

    # Sprint 2: Hot-reload poll interval check every 5 minutes
    scheduler.add_job(
        reload_poll_intervals, "interval", minutes=5, id="reload_poll_intervals",
        max_instances=1, coalesce=True,
    )

    return scheduler


# ── Feature 9: High-priority poll ────────────────────────────────────────────

async def poll_high_priority() -> None:
    """Poll all streamers with poll_priority=3 every 60 seconds."""
    global _high_priority_checked, _last_high_priority_run
    _high_priority_checked = set()
    _last_high_priority_run = datetime.now(timezone.utc)

    async with get_session() as session:
        streamer_repo = StreamerRepository(session)
        all_streamers = await streamer_repo.get_active_streamers()
        high_prio = [s for s in all_streamers if s.poll_priority >= 3]

        if not high_prio:
            return

        account_repo = PlatformAccountRepository(session)
        yt_client = YouTubeIntegration(settings.YOUTUBE_API_KEY, get_http_session())
        vk_client = VKIntegration(settings.VK_ACCESS_TOKEN, settings.VK_API_VERSION, get_http_session())
        results: Dict[int, Dict[Platform, StreamInfo]] = defaultdict(dict)

        for streamer in high_prio:
            _high_priority_checked.add(streamer.id)
            for account in streamer.platform_accounts:
                if not account.is_active:
                    continue
                result = await _check_account(account, get_http_session())
                await _process_account_result(session, account, result, account_repo)
                if result.is_live and result.stream:
                    results[streamer.id][account.platform] = result.stream

        await _process_stream_results(session, results, streamer_ids={s.id for s in high_prio})
        logger.debug("poll.high_priority.done", count=len(high_prio))


# ── Per-platform poll functions ───────────────────────────────────────────────

async def poll_youtube() -> None:
    logger.debug("poll.youtube.start")
    async with get_session() as session:
        if await _is_maintenance_mode(session):
            logger.debug("poll.youtube.skipped_maintenance")
            return
        streamer_repo = StreamerRepository(session)
        account_repo = PlatformAccountRepository(session)
        streamers = await streamer_repo.get_active_streamers()

        # Feature 9: skip high-priority streamers recently polled (<90s ago)
        if _last_high_priority_run and (datetime.now(timezone.utc) - _last_high_priority_run).total_seconds() < 90:
            streamers = [s for s in streamers if s.id not in _high_priority_checked]

        # Feature 9: skip low-priority streamers every other cycle
        normal_and_low = _filter_by_priority(streamers)

        yt_client = YouTubeIntegration(settings.YOUTUBE_API_KEY, get_http_session())
        total_quota = 0
        results: Dict[int, Dict[Platform, StreamInfo]] = defaultdict(dict)

        for streamer in normal_and_low:
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
        if await _is_maintenance_mode(session):
            logger.debug("poll.twitch.skipped_maintenance")
            return

        streamer_repo = StreamerRepository(session)
        account_repo = PlatformAccountRepository(session)
        streamers = await streamer_repo.get_active_streamers()

        # Feature 9: skip high-priority (already covered) and low-priority filtering
        if _last_high_priority_run and (datetime.now(timezone.utc) - _last_high_priority_run).total_seconds() < 90:
            streamers = [s for s in streamers if s.id not in _high_priority_checked]
        streamers = _filter_by_priority(streamers)

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
        if await _is_maintenance_mode(session):
            logger.debug("poll.vk.skipped_maintenance")
            return

        streamer_repo = StreamerRepository(session)
        account_repo = PlatformAccountRepository(session)
        streamers = await streamer_repo.get_active_streamers()

        if _last_high_priority_run and (datetime.now(timezone.utc) - _last_high_priority_run).total_seconds() < 90:
            streamers = [s for s in streamers if s.id not in _high_priority_checked]
        streamers = _filter_by_priority(streamers)

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


# ── Feature 2: Retry failed notifications ────────────────────────────────────

async def retry_notifications() -> None:
    """Feature 2: Retry FAILED notifications with exponential backoff."""
    if _bot_context is None:
        return
    async with get_session() as session:
        notif_service = NotificationService(
            session=session,
            send_fn=_bot_context.send_notification,
            edit_fn=_bot_context.edit_notification,
            delete_fn=_bot_context.delete_notification,
            vk_send_fn=getattr(_bot_context, "send_vk_notification", None),
        )
        count = await notif_service.retry_failed_notifications()
        if count > 0:
            logger.info("retry_notifications.done", retried=count)


# ── Sprint 2: Maintenance mode helper ─────────────────────────────────────────

async def _is_maintenance_mode(session) -> bool:
    """Return True if maintenance mode is currently active."""
    from sqlalchemy import select as _select
    from db.models import SystemSetting
    result = await session.execute(
        _select(SystemSetting).where(SystemSetting.key == "maintenance_mode")
    )
    setting = result.scalar_one_or_none()
    if setting is None or setting.value == "0":
        return False
    # Value can be "1" (indefinite) or ISO timestamp for timed maintenance
    if setting.value == "1":
        return True
    try:
        until = datetime.fromisoformat(setting.value)
        if until.tzinfo is None:
            until = until.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) < until
    except ValueError:
        return False


# ── Sprint 2: Daily streak reset ──────────────────────────────────────────────

async def reset_streaks_daily() -> None:
    """Reset broken streaks for all streamers who missed yesterday."""
    async with get_session() as session:
        from services.gamification_service import GamificationService
        svc = GamificationService(session)
        count = await svc.reset_broken_streaks()
        if count > 0:
            logger.info("scheduler.streaks_reset", count=count)


# ── Sprint 2: pg_dump backup ──────────────────────────────────────────────────

async def run_backup() -> None:
    """Create a pg_dump backup of the database and prune old backups."""
    if not settings.BACKUP_DIR:
        return

    import os
    import subprocess
    from pathlib import Path
    from urllib.parse import urlparse

    backup_dir = Path(settings.BACKUP_DIR)
    backup_dir.mkdir(parents=True, exist_ok=True)

    # Parse DATABASE_URL for pg_dump args
    parsed = urlparse(settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://"))
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_file = backup_dir / f"backup_{timestamp}.sql.gz"

    env = os.environ.copy()
    if parsed.password:
        env["PGPASSWORD"] = parsed.password

    cmd = [
        "pg_dump",
        "-h", parsed.hostname or "localhost",
        "-p", str(parsed.port or 5432),
        "-U", parsed.username or "postgres",
        "-d", (parsed.path or "/postgres").lstrip("/"),
        "-F", "p",   # plain SQL
        "--no-owner",
        "--no-acl",
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            logger.error("backup.pg_dump_failed", stderr=stderr.decode()[:500])
            return

        # Gzip the output
        import gzip
        with gzip.open(backup_file, "wb") as f:
            f.write(stdout)

        size_kb = backup_file.stat().st_size // 1024
        logger.info("backup.created", file=str(backup_file), size_kb=size_kb)

        # Prune backups older than BACKUP_KEEP_DAYS
        cutoff = datetime.now(timezone.utc).timestamp() - settings.BACKUP_KEEP_DAYS * 86400
        pruned = 0
        for old in backup_dir.glob("backup_*.sql.gz"):
            if old.stat().st_mtime < cutoff:
                old.unlink()
                pruned += 1
        if pruned:
            logger.info("backup.pruned", count=pruned)

    except FileNotFoundError:
        logger.error("backup.pg_dump_not_found", hint="Install postgresql-client for pg_dump")
    except Exception as exc:
        logger.exception("backup.error", error=str(exc))


# ── Sprint 2: Hot-reload poll intervals ───────────────────────────────────────

# Track last-known interval values for hot-reload detection
_last_intervals: Dict[str, int] = {}


async def reload_poll_intervals() -> None:
    """Reschedule poll jobs if POLL_INTERVAL_* settings changed at runtime.

    This allows operators to update intervals via SystemSettings or env reload
    without restarting the bot.
    """
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    # Access the running scheduler via APScheduler's global registry
    from apscheduler.schedulers.base import STATE_RUNNING

    new_intervals = {
        "poll_youtube": settings.POLL_INTERVAL_YOUTUBE,
        "poll_twitch": settings.POLL_INTERVAL_TWITCH,
        "poll_vk": settings.POLL_INTERVAL_VK,
    }
    global _last_intervals
    if not _last_intervals:
        _last_intervals = dict(new_intervals)
        return  # First run — just record

    changed = {k: v for k, v in new_intervals.items() if _last_intervals.get(k) != v}
    if not changed:
        return

    # Reschedule changed jobs — requires access to running scheduler
    # We access it via APScheduler's running instance attached to the event loop
    try:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler as _Sched
        import asyncio as _asyncio
        loop = _asyncio.get_event_loop()
        # Find the running scheduler — APScheduler doesn't have a global registry,
        # so we check all schedulers stored on the loop
        scheduler: Optional[AsyncIOScheduler] = getattr(loop, "_apscheduler_instance", None)
        if scheduler is None or scheduler.state != STATE_RUNNING:
            return

        for job_id, seconds in changed.items():
            job = scheduler.get_job(job_id)
            if job:
                job.reschedule("interval", seconds=seconds)
                logger.info("scheduler.interval_reloaded", job_id=job_id, seconds=seconds)

        _last_intervals.update(changed)
    except Exception as exc:
        logger.warning("scheduler.reload_failed", error=str(exc))


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

def _filter_by_priority(streamers: list) -> list:
    """Feature 9: Filter out low-priority streamers on alternating cycles.

    Low-priority (1) streamers are polled every other call using a simple
    time-based modulus: if the current minute is even, skip them.
    This effectively halves their poll frequency without extra jobs.
    """
    minute = datetime.now(timezone.utc).minute
    result = []
    for s in streamers:
        priority = getattr(s, "poll_priority", 2)
        if priority == 1 and minute % 2 != 0:
            # Low priority: skip every other cycle
            continue
        result.append(s)
    return result


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
    streamer_ids: Optional[Set[int]] = None,
) -> None:
    """For each streamer, get all their live platforms and process together."""
    if _bot_context is None:
        return

    from services.gamification_service import GamificationService
    from services.discord_service import DiscordService

    notif_service = NotificationService(
        session=session,
        send_fn=_bot_context.send_notification,
        edit_fn=_bot_context.edit_notification,
        delete_fn=_bot_context.delete_notification,
        vk_send_fn=getattr(_bot_context, "send_vk_notification", None),
    )
    gamification_service = GamificationService(session)
    discord_service = DiscordService(session)
    stream_service = StreamService(
        session=session,
        notification_service=notif_service,
        gamification_service=gamification_service,
        discord_service=discord_service,
    )

    # Also include streamers with NO live results (need to close active streams)
    if streamer_ids is not None:
        # Specific subset (high-priority job)
        all_streamer_ids = streamer_ids
    else:
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
