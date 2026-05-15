"""Gamification handlers — leaderboards, achievements, maintenance mode.

Commands:
  /leaderboard [streams|hours|viewers|streak]  — top-10 leaderboard (default: streams)
  /top         — same as /leaderboard (alias)
  /achievements [streamer_id]                  — achievements for a streamer
  /maintenance [on|off|Xm|Xh]                 — toggle / timed maintenance (owner/admin only)
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import select

from db.database import get_session
from db.models import SystemSetting, User, UserRole
from services.gamification_service import ACHIEVEMENT_META, GamificationService

router = Router()


# ── /leaderboard ──────────────────────────────────────────────────────────────

@router.message(Command("leaderboard", "top"))
async def cmd_leaderboard(message: Message, db_user: User) -> None:
    """Show a top-10 leaderboard.

    Usage: /leaderboard [streams|hours|viewers|streak]
    """
    args = (message.text or "").split(maxsplit=1)
    mode = args[1].strip().lower() if len(args) > 1 else "streams"

    valid_modes = {"streams", "hours", "viewers", "streak"}
    if mode not in valid_modes:
        await message.answer(
            f"❓ Unknown mode `{mode}`.\n"
            "Available: `streams` `hours` `viewers` `streak`",
            parse_mode="Markdown",
        )
        return

    async with get_session() as session:
        svc = GamificationService(session)

        if mode == "streams":
            entries = await svc.leaderboard_by_streams(limit=10)
            title = "🏆 Top Streamers — Stream Count"
        elif mode == "hours":
            entries = await svc.leaderboard_by_hours(limit=10)
            title = "⏱ Top Streamers — Hours Streamed"
        elif mode == "viewers":
            entries = await svc.leaderboard_by_viewers(limit=10)
            title = "👥 Top Streamers — Peak Viewers"
        else:
            entries = await svc.leaderboard_by_streak(limit=10)
            title = "🔥 Top Streamers — Max Streak"

    if not entries:
        await message.answer("No data yet. Start streaming to appear on the leaderboard! 🎮")
        return

    lines = [f"*{title}*\n"]
    medals = ["🥇", "🥈", "🥉"]
    for entry in entries:
        medal = medals[entry.rank - 1] if entry.rank <= 3 else f"`{entry.rank:>2}.`"
        lines.append(f"{medal} *{entry.display_name}* — {entry.extra}")

    # Navigation hint
    other_modes = sorted(valid_modes - {mode})
    nav = "  •  ".join(f"`/top {m}`" for m in other_modes)
    lines.append(f"\n📊 Other boards: {nav}")

    await message.answer("\n".join(lines), parse_mode="Markdown")


# ── /achievements ─────────────────────────────────────────────────────────────

@router.message(Command("achievements"))
async def cmd_achievements(message: Message, db_user: User) -> None:
    """Show achievements for a streamer.

    Usage: /achievements [streamer_id]
    Defaults to the first streamer assigned to the calling user.
    """
    from db.repositories.streamer_repo import StreamerRepository

    args = (message.text or "").split(maxsplit=1)
    streamer_id: Optional[int] = None

    if len(args) > 1:
        try:
            streamer_id = int(args[1].strip())
        except ValueError:
            await message.answer("❓ Usage: `/achievements [streamer_id]`", parse_mode="Markdown")
            return

    async with get_session() as session:
        if streamer_id is None:
            # Find first streamer assigned to this user
            streamer_repo = StreamerRepository(session)
            streamers = await streamer_repo.get_for_user(db_user.id)
            if not streamers:
                await message.answer(
                    "You have no streamers assigned. Ask an admin to assign one."
                )
                return
            streamer_id = streamers[0].id

        svc = GamificationService(session)
        achievements = await svc.get_achievements(streamer_id)

        # Get streamer name
        from db.models import Streamer
        streamer = await session.get(Streamer, streamer_id)
        name = streamer.display_name if streamer else f"Streamer #{streamer_id}"

        # Get streamer streak info
        if streamer:
            streak_text = (
                f"🔥 Current streak: *{streamer.current_streak}d*  "
                f"│  Max: *{streamer.max_streak}d*"
            )
        else:
            streak_text = ""

    if not achievements:
        await message.answer(
            f"🏅 *{name}* has no achievements yet.\n\n"
            "Keep streaming to unlock them!",
            parse_mode="Markdown",
        )
        return

    lines = [f"🏅 *Achievements — {name}*\n", streak_text, ""]
    for ach in achievements:
        earned = ach.earned_at.strftime("%d %b %Y")
        lines.append(f"{ach.emoji} *{ach.name}* — _{ach.desc}_\n   📅 {earned}")

    # Show locked achievements too
    from db.models import AchievementType
    earned_types = {a.achievement_type for a in achievements}
    locked = [t for t in AchievementType if t not in earned_types]
    if locked:
        lines.append(f"\n🔒 *Locked* ({len(locked)} remaining):")
        for t in locked:
            meta = ACHIEVEMENT_META.get(t, {})
            lines.append(f"   {meta.get('emoji','🔒')} {meta.get('name', t.value)}")

    await message.answer("\n".join(lines), parse_mode="Markdown")


# ── /maintenance ──────────────────────────────────────────────────────────────

@router.message(Command("maintenance"))
async def cmd_maintenance(message: Message, db_user: User) -> None:
    """Toggle maintenance mode (owner/admin only).

    Usage:
      /maintenance on          — enable indefinitely
      /maintenance off         — disable
      /maintenance 30m         — enable for 30 minutes
      /maintenance 2h          — enable for 2 hours
      /maintenance             — show current status
    """
    if db_user.role not in (UserRole.ADMIN, UserRole.OWNER):
        await message.answer("⛔ You don't have permission to manage maintenance mode.")
        return

    args = (message.text or "").split(maxsplit=1)
    arg = args[1].strip().lower() if len(args) > 1 else ""

    async with get_session() as session:
        if not arg:
            # Show current status
            status = await _get_maintenance_status(session)
            await message.answer(status, parse_mode="Markdown")
            return

        if arg == "off":
            await _set_maintenance(session, "0", db_user.id)
            await message.answer("✅ Maintenance mode *disabled*. Bot is live.", parse_mode="Markdown")
            return

        if arg == "on":
            await _set_maintenance(session, "1", db_user.id)
            await message.answer(
                "🔧 Maintenance mode *enabled* indefinitely.\n\n"
                "Use `/maintenance off` to disable.",
                parse_mode="Markdown",
            )
            return

        # Timed: Xm or Xh
        match = re.fullmatch(r"(\d+)([mh])", arg)
        if match:
            amount = int(match.group(1))
            unit = match.group(2)
            delta = timedelta(minutes=amount) if unit == "m" else timedelta(hours=amount)
            until = datetime.now(timezone.utc) + delta
            await _set_maintenance(session, until.isoformat(), db_user.id)
            label = f"{amount} minute{'s' if amount != 1 else ''}" if unit == "m" else f"{amount} hour{'s' if amount != 1 else ''}"
            await message.answer(
                f"🔧 Maintenance mode *enabled* for *{label}*.\n\n"
                f"⏱ Until: `{until.strftime('%H:%M UTC')}`\n"
                "Use `/maintenance off` to cancel early.",
                parse_mode="Markdown",
            )
            return

        await message.answer(
            "❓ Unknown argument.\n\n"
            "Usage: `/maintenance [on|off|30m|2h]`",
            parse_mode="Markdown",
        )


async def _get_maintenance_status(session) -> str:
    result = await session.execute(
        select(SystemSetting).where(SystemSetting.key == "maintenance_mode")
    )
    setting = result.scalar_one_or_none()

    if setting is None or setting.value in ("0", "false", ""):
        return "✅ *Maintenance mode:* disabled — bot is running normally."

    if setting.value in ("1", "true"):
        return (
            "🔧 *Maintenance mode:* ACTIVE (indefinite)\n\n"
            "Use `/maintenance off` to disable."
        )

    try:
        until = datetime.fromisoformat(setting.value)
        if until.tzinfo is None:
            until = until.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        if now >= until:
            return "✅ *Maintenance mode:* expired — bot is running normally."
        remaining = until - now
        mins = int(remaining.total_seconds() // 60)
        return (
            f"🔧 *Maintenance mode:* ACTIVE\n"
            f"⏱ Expires in ~{mins}m (`{until.strftime('%H:%M UTC')}`)\n\n"
            "Use `/maintenance off` to cancel early."
        )
    except ValueError:
        return f"🔧 *Maintenance mode:* active (value: `{setting.value}`)"


async def _set_maintenance(session, value: str, updated_by: int) -> None:
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    result = await session.execute(
        select(SystemSetting).where(SystemSetting.key == "maintenance_mode")
    )
    setting = result.scalar_one_or_none()
    if setting:
        setting.value = value
        setting.updated_by = updated_by
    else:
        session.add(SystemSetting(
            key="maintenance_mode",
            value=value,
            updated_by=updated_by,
        ))
    await session.flush()
