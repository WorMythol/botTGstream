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

from bot.texts import T
from db.database import get_session
from db.models import SystemSetting, User, UserRole
from services.gamification_service import ACHIEVEMENT_META, GamificationService

router = Router()


# ── /leaderboard ──────────────────────────────────────────────────────────────

@router.message(Command("leaderboard", "top"))
async def cmd_leaderboard(message: Message, db_user: User) -> None:
    """Показать топ-10 рейтинг.

    Использование: /leaderboard [streams|hours|viewers|streak]
    """
    args = (message.text or "").split(maxsplit=1)
    mode = args[1].strip().lower() if len(args) > 1 else "streams"

    valid_modes = {"streams", "hours", "viewers", "streak"}
    if mode not in valid_modes:
        await message.answer(
            T.LEADERBOARD_UNKNOWN_MODE.format(mode=mode),
            parse_mode="Markdown",
        )
        return

    async with get_session() as session:
        svc = GamificationService(session)

        if mode == "streams":
            entries = await svc.leaderboard_by_streams(limit=10)
            title = T.LEADERBOARD_TITLE_STREAMS
        elif mode == "hours":
            entries = await svc.leaderboard_by_hours(limit=10)
            title = T.LEADERBOARD_TITLE_HOURS
        elif mode == "viewers":
            entries = await svc.leaderboard_by_viewers(limit=10)
            title = T.LEADERBOARD_TITLE_VIEWERS
        else:
            entries = await svc.leaderboard_by_streak(limit=10)
            title = T.LEADERBOARD_TITLE_STREAK

    if not entries:
        await message.answer(T.LEADERBOARD_EMPTY)
        return

    lines = [f"*{title}*\n"]
    medals = ["🥇", "🥈", "🥉"]
    for entry in entries:
        medal = medals[entry.rank - 1] if entry.rank <= 3 else f"`{entry.rank:>2}.`"
        lines.append(f"{medal} *{entry.display_name}* — {entry.extra}")

    # Navigation hint
    other_modes = sorted(valid_modes - {mode})
    nav = "  •  ".join(f"`/top {m}`" for m in other_modes)
    lines.append(f"\n{T.LEADERBOARD_OTHER.format(nav=nav)}")

    await message.answer("\n".join(lines), parse_mode="Markdown")


# ── /achievements ─────────────────────────────────────────────────────────────

@router.message(Command("achievements"))
async def cmd_achievements(message: Message, db_user: User) -> None:
    """Показать достижения стримера.

    Использование: /achievements [streamer_id]
    По умолчанию — первый стример, привязанный к пользователю.
    """
    from db.repositories.streamer_repo import StreamerRepository

    args = (message.text or "").split(maxsplit=1)
    streamer_id: Optional[int] = None

    if len(args) > 1:
        try:
            streamer_id = int(args[1].strip())
        except ValueError:
            await message.answer(T.ACHIEVEMENTS_INVALID_ID, parse_mode="Markdown")
            return

    async with get_session() as session:
        if streamer_id is None:
            # Find first streamer assigned to this user
            streamer_repo = StreamerRepository(session)
            streamers = await streamer_repo.get_for_user(db_user.id)
            if not streamers:
                await message.answer(T.ACHIEVEMENTS_NO_STREAMER)
                return
            streamer_id = streamers[0].id

        svc = GamificationService(session)
        achievements = await svc.get_achievements(streamer_id)

        # Get streamer name
        from db.models import Streamer
        streamer = await session.get(Streamer, streamer_id)
        name = streamer.display_name if streamer else f"Стример #{streamer_id}"

        # Get streamer streak info
        if streamer:
            streak_text = T.ACHIEVEMENTS_STREAK.format(
                current=streamer.current_streak,
                max=streamer.max_streak,
            )
        else:
            streak_text = ""

    if not achievements:
        await message.answer(
            T.ACHIEVEMENTS_NONE.format(name=name),
            parse_mode="Markdown",
        )
        return

    lines = [T.ACHIEVEMENTS_HEADER.format(name=name), streak_text, ""]
    for ach in achievements:
        earned = ach.earned_at.strftime("%d %b %Y")
        lines.append(f"{ach.emoji} *{ach.name}* — _{ach.desc}_\n   📅 {earned}")

    # Show locked achievements too
    from db.models import AchievementType
    earned_types = {a.achievement_type for a in achievements}
    locked = [t for t in AchievementType if t not in earned_types]
    if locked:
        lines.append(T.ACHIEVEMENTS_LOCKED.format(count=len(locked)))
        for t in locked:
            meta = ACHIEVEMENT_META.get(t, {})
            lines.append(f"   {meta.get('emoji', '🔒')} {meta.get('name', t.value)}")

    await message.answer("\n".join(lines), parse_mode="Markdown")


# ── /maintenance ──────────────────────────────────────────────────────────────

@router.message(Command("maintenance"))
async def cmd_maintenance(message: Message, db_user: User) -> None:
    """Управление режимом обслуживания (только владелец/администратор).

    Использование:
      /maintenance on          — включить бессрочно
      /maintenance off         — отключить
      /maintenance 30m         — включить на 30 минут
      /maintenance 2h          — включить на 2 часа
      /maintenance             — показать текущий статус
    """
    if db_user.role not in (UserRole.ADMIN, UserRole.OWNER):
        await message.answer(T.MAINTENANCE_NO_PERMISSION)
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
            await message.answer(T.MAINTENANCE_OFF_DONE, parse_mode="Markdown")
            return

        if arg == "on":
            await _set_maintenance(session, "1", db_user.id)
            await message.answer(T.MAINTENANCE_ON_DONE, parse_mode="Markdown")
            return

        # Timed: Xm or Xh
        match = re.fullmatch(r"(\d+)([mh])", arg)
        if match:
            amount = int(match.group(1))
            unit = match.group(2)
            delta = timedelta(minutes=amount) if unit == "m" else timedelta(hours=amount)
            until = datetime.now(timezone.utc) + delta
            await _set_maintenance(session, until.isoformat(), db_user.id)

            if unit == "m":
                # Russian plural for minutes: 1=минута, 2-4=минуты, 5+=минут
                if amount % 10 == 1 and amount % 100 != 11:
                    suffix = "а"
                elif 2 <= amount % 10 <= 4 and not (12 <= amount % 100 <= 14):
                    suffix = "ы"
                else:
                    suffix = ""
                label = T.MAINTENANCE_MINUTES.format(n=amount, suffix=suffix)
            else:
                # Russian plural for hours: 1=час, 2-4=часа, 5+=часов
                if amount % 10 == 1 and amount % 100 != 11:
                    suffix = ""
                elif 2 <= amount % 10 <= 4 and not (12 <= amount % 100 <= 14):
                    suffix = "а"
                else:
                    suffix = "ов"
                label = T.MAINTENANCE_HOURS.format(n=amount, suffix=suffix)

            await message.answer(
                T.MAINTENANCE_TIMED_DONE.format(
                    label=label,
                    until=until.strftime("%H:%M UTC"),
                ),
                parse_mode="Markdown",
            )
            return

        await message.answer(T.MAINTENANCE_UNKNOWN_ARG, parse_mode="Markdown")


async def _get_maintenance_status(session) -> str:
    result = await session.execute(
        select(SystemSetting).where(SystemSetting.key == "maintenance_mode")
    )
    setting = result.scalar_one_or_none()

    if setting is None or setting.value in ("0", "false", ""):
        return T.MAINTENANCE_DISABLED

    if setting.value in ("1", "true"):
        return T.MAINTENANCE_ACTIVE_INDEF

    try:
        until = datetime.fromisoformat(setting.value)
        if until.tzinfo is None:
            until = until.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        if now >= until:
            return T.MAINTENANCE_EXPIRED
        remaining = until - now
        mins = int(remaining.total_seconds() // 60)
        return T.MAINTENANCE_ACTIVE_TIMED.format(
            mins=mins,
            until=until.strftime("%H:%M UTC"),
        )
    except ValueError:
        return T.MAINTENANCE_VALUE.format(value=setting.value)


async def _set_maintenance(session, value: str, updated_by: int) -> None:
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
