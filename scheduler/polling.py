"""APScheduler-based polling engine — job definitions only.

Business logic (account checking, result processing, admin notifications) lives in
services/polling_orchestrator.py. This module is responsible only for:
  - Creating the scheduler and registering jobs
  - Per-platform poll coroutines (thin wrappers around PollOrchestrator)
  - Maintenance-mode gate
  - Retry, streak-reset, backup, and hot-reload jobs
  - BotContext wiring (set_bot_context)

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

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import settings
from db.database import get_session
from db.models import Platform
from db.repositories.streamer_repo import PlatformAccountRepository, StreamerRepository
from services.http_client import get_http_session, get_twitch_client
from services.notification_service import NotificationService
from services.polling_orchestrator import PollOrchestrator, check_account, filter_by_priority

if TYPE_CHECKING:
    from bot.main import BotContext

logger = structlog.get_logger(__name__)

_bot_context: Optional["BotContext"] = None

# Feature 9: track which streamer IDs have been covered by the high-priority job
# so the normal platform jobs skip them in the same cycle (avoids double-polling)
_high_priority_checked: Set[int] = set()
_last_high_priority_run: Optional[datetime] = None


def set_bot_context(ctx: "BotContext") -> None:
    global _bot_context
    _bot_context = ctx


# ── Scheduler setup ───────────────────────────────────────────────────────────

def create_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="UTC")

    # Normal platform poll jobs
    scheduler.add_job(
        poll_youtube, "interval", seconds=settings.POLL_INTERVAL_YOUTUBE,
        id="poll_youtube", max_instances=1, coalesce=True,
    )
    scheduler.add_job(
        poll_twitch, "interval", seconds=settings.POLL_INTERVAL_TWITCH,
        id="poll_twitch", max_instances=1, coalesce=True,
    )
    scheduler.add_job(
        poll_vk, "interval", seconds=settings.POLL_INTERVAL_VK,
        id="poll_vk", max_instances=1, coalesce=True,
    )

    # Feature 9: High-priority poll every 60 seconds
    scheduler.add_job(
        poll_high_priority, "interval", seconds=60,
        id="poll_high_priority", max_instances=1, coalesce=True,
    )

    # Feature 2: Retry failed notifications every 60 seconds
    scheduler.add_job(
        retry_notifications, "interval", seconds=60,
        id="retry_notifications", max_instances=1, coalesce=True,
    )

    # Sprint 2: Daily streak reset at 00:05 UTC
    scheduler.add_job(
        reset_streaks_daily, "cron", hour=0, minute=5,
        id="reset_streaks", max_instances=1, coalesce=True,
    )

    # Sprint 2: Daily pg_dump backup at 03:00 UTC (only if BACKUP_DIR configured)
    if settings.BACKUP_DIR:
        scheduler.add_job(
            run_backup, "cron", hour=3, minute=0,
            id="run_backup", max_instances=1, coalesce=True,
        )

    # Sprint 2: Hot-reload poll interval check every 5 minutes
    scheduler.add_job(
        reload_poll_intervals, "interval", minutes=5,
        id="reload_poll_intervals", max_instances=1, coalesce=True,
    )

    return scheduler


# ── Feature 9: High-priority poll ────────────────────────────────────────────

async def poll_high_priority() -> None:
    """Poll all streamers with poll_priority=3 every 60 seconds."""
    global _high_priority_checked, _last_high_priority_run
    _high_priority_checked = set()
    _last_high_priority_run = datetime.now(timezone.utc)

    http = get_http_session()
    async with get_session() as session:
        streamer_repo = StreamerRepository(session)
        all_streamers = await streamer_repo.get_active_streamers()
        high_prio = [s for s in all_streamers if s.poll_priority >= 3]
        if not high_prio:
            return

        account_repo = PlatformAccountRepository(session)
        orchestrator = PollOrchestrator(session, _bot_context)
        results: Dict[int, Dict[Platform, object]] = defaultdict(dict)

        for streamer in high_prio:
            _high_priority_checked.add(streamer.id)
            for account in streamer.platform_accounts:
                if not account.is_active:
                    continue
                result = await check_account(account, http)
                await orchestrator.process_account_result(account, result, account_repo)
                if result.is_live and result.stream:
                    results[streamer.id][account.platform] = result.stream

        await orchestrator.process_stream_results(results, streamer_ids={s.id for s in high_prio})
        logger.debug("poll.high_priority.done", count=len(high_prio))


# ── Per-platform poll functions ───────────────────────────────────────────────

async def poll_youtube() -> None:
    logger.debug("poll.youtube.start")
    http = get_http_session()

    async with get_session() as session:
        if await _is_maintenance_mode(session):
            logger.debug("poll.youtube.skipped_maintenance")
            return

        from integrations import YouTubeIntegration
        streamer_repo = StreamerRepository(session)
        account_repo = PlatformAccountRepository(session)
        orchestrator = PollOrchestrator(session, _bot_context)

        streamers = await streamer_repo.get_active_streamers()

        # Feature 9: skip high-priority streamers recently covered
        if _last_high_priority_run and (
            datetime.now(timezone.utc) - _last_high_priority_run
        ).total_seconds() < 90:
            streamers = [s for s in streamers if s.id not in _high_priority_checked]
        streamers = filter_by_priority(streamers)

        yt_client = YouTubeIntegration(settings.YOUTUBE_API_KEY, http)
        total_quota = 0
        results: Dict[int, Dict[Platform, object]] = defaultdict(dict)

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
                    from db.repositories.polling_repo import PollingStateRepository
                    ps_repo = PollingStateRepository(session)
                    await ps_repo.add_youtube_quota(total_quota)
                    await ps_repo.record_poll(Platform.YOUTUBE)
                    await orchestrator.notify_admins_quota_exceeded()
                    return

                await orchestrator.process_account_result(account, result, account_repo)
                if result.is_live and result.stream:
                    results[streamer.id][Platform.YOUTUBE] = result.stream

        from db.repositories.polling_repo import PollingStateRepository
        ps_repo = PollingStateRepository(session)
        new_total = await ps_repo.add_youtube_quota(total_quota)
        await ps_repo.record_poll(Platform.YOUTUBE)

        if new_total >= settings.YOUTUBE_QUOTA_WARNING_THRESHOLD:
            await orchestrator.notify_admins_quota_exceeded()

        await orchestrator.process_stream_results(results)
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
        orchestrator = PollOrchestrator(session, _bot_context)

        streamers = await streamer_repo.get_active_streamers()
        if _last_high_priority_run and (
            datetime.now(timezone.utc) - _last_high_priority_run
        ).total_seconds() < 90:
            streamers = [s for s in streamers if s.id not in _high_priority_checked]
        streamers = filter_by_priority(streamers)

        results: Dict[int, Dict[Platform, object]] = defaultdict(dict)

        for streamer in streamers:
            for account in streamer.platform_accounts:
                if account.platform != Platform.TWITCH or not account.is_active:
                    continue
                result = await twitch.check_live(account.platform_id)
                await orchestrator.process_account_result(account, result, account_repo)
                if result.is_live and result.stream:
                    results[streamer.id][Platform.TWITCH] = result.stream

        # Persist refreshed Twitch OAuth token
        from db.repositories.polling_repo import PollingStateRepository
        ps_repo = PollingStateRepository(session)
        ps = await ps_repo.get_or_create(Platform.TWITCH)
        token, expires_at = twitch.get_token_state()
        if token:
            ps.twitch_access_token = token
            ps.twitch_token_expires_at = datetime.fromtimestamp(expires_at, tz=timezone.utc)
        ps.last_poll_at = datetime.now(timezone.utc)
        await session.flush()

        await orchestrator.process_stream_results(results)
        logger.info("poll.twitch.done")


async def poll_vk() -> None:
    logger.debug("poll.vk.start")
    http = get_http_session()

    async with get_session() as session:
        if await _is_maintenance_mode(session):
            logger.debug("poll.vk.skipped_maintenance")
            return

        from integrations import VKIntegration
        streamer_repo = StreamerRepository(session)
        account_repo = PlatformAccountRepository(session)
        orchestrator = PollOrchestrator(session, _bot_context)

        streamers = await streamer_repo.get_active_streamers()
        if _last_high_priority_run and (
            datetime.now(timezone.utc) - _last_high_priority_run
        ).total_seconds() < 90:
            streamers = [s for s in streamers if s.id not in _high_priority_checked]
        streamers = filter_by_priority(streamers)

        vk_client = VKIntegration(settings.VK_ACCESS_TOKEN, settings.VK_API_VERSION, http)
        results: Dict[int, Dict[Platform, object]] = defaultdict(dict)

        for streamer in streamers:
            for account in streamer.platform_accounts:
                if account.platform != Platform.VK or not account.is_active:
                    continue
                result = await vk_client.check_live(account.platform_id)
                await orchestrator.process_account_result(account, result, account_repo)
                if result.is_live and result.stream:
                    results[streamer.id][Platform.VK] = result.stream

        from db.repositories.polling_repo import PollingStateRepository
        await PollingStateRepository(session).record_poll(Platform.VK)

        await orchestrator.process_stream_results(results)
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


# ── Sprint 2: Maintenance mode gate ──────────────────────────────────────────

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
        count = await GamificationService(session).reset_broken_streaks()
        if count > 0:
            logger.info("scheduler.streaks_reset", count=count)


# ── Sprint 2: pg_dump backup ──────────────────────────────────────────────────

async def run_backup() -> None:
    """Create a pg_dump backup and prune old backups."""
    if not settings.BACKUP_DIR:
        return

    import os
    from pathlib import Path
    from urllib.parse import urlparse

    backup_dir = Path(settings.BACKUP_DIR)
    backup_dir.mkdir(parents=True, exist_ok=True)

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
        "-F", "p", "--no-owner", "--no-acl",
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

        import gzip
        with gzip.open(backup_file, "wb") as f:
            f.write(stdout)

        size_kb = backup_file.stat().st_size // 1024
        logger.info("backup.created", file=str(backup_file), size_kb=size_kb)

        # Prune old backups
        cutoff = datetime.now(timezone.utc).timestamp() - settings.BACKUP_KEEP_DAYS * 86400
        pruned = sum(
            1 for old in backup_dir.glob("backup_*.sql.gz")
            if old.stat().st_mtime < cutoff and not old.unlink()
        )
        if pruned:
            logger.info("backup.pruned", count=pruned)

    except FileNotFoundError:
        logger.error("backup.pg_dump_not_found", hint="Install postgresql-client")
    except Exception:
        logger.exception("backup.error")


# ── Sprint 2: Hot-reload poll intervals ───────────────────────────────────────

_last_intervals: Dict[str, int] = {}


async def reload_poll_intervals() -> None:
    """Reschedule poll jobs if POLL_INTERVAL_* settings changed at runtime."""
    from apscheduler.schedulers.base import STATE_RUNNING

    new_intervals = {
        "poll_youtube": settings.POLL_INTERVAL_YOUTUBE,
        "poll_twitch":  settings.POLL_INTERVAL_TWITCH,
        "poll_vk":      settings.POLL_INTERVAL_VK,
    }
    global _last_intervals
    if not _last_intervals:
        _last_intervals = dict(new_intervals)
        return

    changed = {k: v for k, v in new_intervals.items() if _last_intervals.get(k) != v}
    if not changed:
        return

    try:
        loop = asyncio.get_event_loop()
        scheduler: Optional[AsyncIOScheduler] = getattr(loop, "_apscheduler_instance", None)
        if scheduler is None or scheduler.state != STATE_RUNNING:
            return
        for job_id, seconds in changed.items():
            job = scheduler.get_job(job_id)
            if job:
                job.reschedule("interval", seconds=seconds)
                logger.info("scheduler.interval_reloaded", job_id=job_id, seconds=seconds)
        _last_intervals.update(changed)
    except Exception:
        logger.warning("scheduler.reload_failed")


# ── Manual trigger (used by /poll_now handler) ────────────────────────────────

async def trigger_poll_for_streamer(streamer_id: int) -> Dict[str, bool]:
    """Manually trigger a full platform poll for a single streamer.

    Returns dict of {platform: is_live}.
    """
    http = get_http_session()
    results: Dict[str, bool] = {}

    async with get_session() as session:
        account_repo = PlatformAccountRepository(session)
        streamer = await StreamerRepository(session).get_with_accounts(streamer_id)
        if streamer is None:
            return results

        orchestrator = PollOrchestrator(session, _bot_context)
        live_map: Dict[Platform, object] = {}

        for account in streamer.platform_accounts:
            if not account.is_active:
                continue
            result = await check_account(account, http)
            await orchestrator.process_account_result(account, result, account_repo)
            results[account.platform.value] = result.is_live
            if result.is_live and result.stream:
                live_map[account.platform] = result.stream

        await orchestrator.process_stream_results(
            {streamer_id: live_map} if live_map else {}
        )

    return results
