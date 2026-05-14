"""Streamer-role handlers: view own streamers, edit templates, view stats."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.keyboards.inline import channels_list_keyboard, streamers_list_keyboard, back_keyboard
from bot.states import EditTemplateStates
from db.database import get_session
from db.models import User, UserRole
from services.analytics_service import AnalyticsService
from services.streamer_service import StreamerService
from services.template_service import validate_template, DEFAULT_TEMPLATE

router = Router()


def _streamer_access(user: User) -> bool:
    return user.is_active


# ── My streamers ──────────────────────────────────────────────────────────────

@router.message(Command("my_streamers"))
async def cmd_my_streamers(message: Message, db_user: User) -> None:
    if not _streamer_access(db_user):
        return

    async with get_session() as session:
        svc = StreamerService(session)
        if db_user.role in (UserRole.ADMIN, UserRole.OWNER):
            streamers = await svc.list_streamers()
        else:
            streamers = await svc.list_streamers_for_user(db_user.id)

    if not streamers:
        await message.answer(
            "You have no streamers assigned. Contact an admin to be assigned streamers."
        )
        return

    lines = []
    for s in streamers:
        platforms = ", ".join(a.platform.value for a in s.platform_accounts)
        status = "⏸" if s.is_paused else ("⛔" if s.auto_disabled_at else "🟢")
        lines.append(f"{status} *{s.display_name}* — {platforms}")

    await message.answer(
        "📡 *Your streamers:*\n\n" + "\n".join(lines),
        parse_mode="Markdown",
    )


# ── Edit template ─────────────────────────────────────────────────────────────

@router.message(Command("edit_template"))
async def cmd_edit_template(message: Message, db_user: User, state: FSMContext) -> None:
    async with get_session() as session:
        svc = StreamerService(session)
        if db_user.role in (UserRole.ADMIN, UserRole.OWNER):
            streamers = await svc.list_streamers()
        else:
            streamers = await svc.list_streamers_for_user(db_user.id)

    if not streamers:
        await message.answer("No streamers available.")
        return

    await state.set_state(EditTemplateStates.waiting_streamer)
    kb = streamers_list_keyboard(streamers, "edit_tmpl_streamer")
    await message.answer("Select a *streamer*:", reply_markup=kb, parse_mode="Markdown")


@router.callback_query(F.data.startswith("edit_tmpl_streamer:"), EditTemplateStates.waiting_streamer)
async def edit_template_streamer_selected(callback: CallbackQuery, db_user: User, state: FSMContext) -> None:
    streamer_id = int(callback.data.split(":")[1])

    # Verify access for streamer-role users
    if db_user.role == UserRole.STREAMER:
        async with get_session() as session:
            svc = StreamerService(session)
            owned = await svc.list_streamers_for_user(db_user.id)
            if streamer_id not in {s.id for s in owned}:
                await callback.answer("⛔ Not your streamer.", show_alert=True)
                return

    await state.update_data(streamer_id=streamer_id)
    await state.set_state(EditTemplateStates.waiting_channel)

    async with get_session() as session:
        svc = StreamerService(session)
        assignments = await svc.get_assignments(streamer_id)

    if not assignments:
        await callback.message.edit_text("This streamer has no channel assignments.")
        await state.clear()
        return

    channels = [a.channel for a in assignments]
    kb = channels_list_keyboard(channels, "edit_tmpl_channel")
    await callback.message.edit_text("Select a *channel*:", reply_markup=kb, parse_mode="Markdown")
    await callback.answer()


@router.callback_query(F.data.startswith("edit_tmpl_channel:"), EditTemplateStates.waiting_channel)
async def edit_template_channel_selected(callback: CallbackQuery, state: FSMContext) -> None:
    channel_id = int(callback.data.split(":")[1])
    await state.update_data(channel_id=channel_id)
    await state.set_state(EditTemplateStates.waiting_template)
    await callback.message.edit_text(
        "Enter your *new template*. Available variables:\n"
        "`{{ streamer_name }}` `{{ stream_title }}` `{{ viewer_count }}` `{{ platform_links }}`\n\n"
        f"Default template:\n```\n{DEFAULT_TEMPLATE}\n```\n\nSend your template:",
        parse_mode="Markdown",
    )
    await callback.answer()


@router.message(EditTemplateStates.waiting_template)
async def edit_template_input(message: Message, db_user: User, state: FSMContext) -> None:
    template = message.text.strip()
    err = validate_template(template)
    if err:
        await message.answer(f"❌ Template error: {err}\n\nTry again:")
        return

    data = await state.get_data()
    await state.clear()

    async with get_session() as session:
        svc = StreamerService(session)
        success = await svc.set_template(data["streamer_id"], data["channel_id"], template)

    if success:
        await message.answer("✅ Template saved!")
    else:
        await message.answer("❌ Assignment not found.")


# ── Stream history ────────────────────────────────────────────────────────────

@router.message(Command("stream_history"))
async def cmd_stream_history(message: Message, db_user: User) -> None:
    async with get_session() as session:
        svc = StreamerService(session)
        if db_user.role in (UserRole.ADMIN, UserRole.OWNER):
            streamers = await svc.list_streamers()
        else:
            streamers = await svc.list_streamers_for_user(db_user.id)

    if not streamers:
        await message.answer("No streamers.")
        return

    # Show history for first streamer (or all for admins)
    async with get_session() as session:
        analytics = AnalyticsService(session)
        lines = ["📜 *Recent Streams:*\n"]
        for streamer in streamers[:3]:
            history = await analytics.get_stream_history(streamer.id, limit=5)
            if history:
                lines.append(f"*{streamer.display_name}*")
                for stream in history:
                    platforms = ", ".join(ps.platform.value for ps in stream.platform_streams)
                    duration = ""
                    if stream.ended_at and stream.started_at:
                        mins = int((stream.ended_at - stream.started_at).total_seconds() / 60)
                        duration = f" ({mins}m)"
                    started = stream.started_at.strftime("%d %b %H:%M") if stream.started_at else "?"
                    lines.append(f"  • {started}{duration} — {platforms}")
                lines.append("")

    await message.answer("\n".join(lines), parse_mode="Markdown")


# ── My stats ──────────────────────────────────────────────────────────────────

@router.message(Command("my_stats"))
async def cmd_my_stats(message: Message, db_user: User) -> None:
    async with get_session() as session:
        streamer_svc = StreamerService(session)
        analytics = AnalyticsService(session)

        if db_user.role in (UserRole.ADMIN, UserRole.OWNER):
            streamers = await streamer_svc.list_streamers()
        else:
            streamers = await streamer_svc.list_streamers_for_user(db_user.id)

        lines = ["📊 *Your Streamer Statistics:*\n"]
        for streamer in streamers:
            stats = await analytics.get_streamer_stats(streamer.id)
            if stats:
                last = stats.last_stream_at.strftime("%d %b %Y") if stats.last_stream_at else "Never"
                lines.append(
                    f"*{stats.display_name}*\n"
                    f"  Streams: {stats.total_streams}\n"
                    f"  Hours: {stats.total_hours_streamed}h\n"
                    f"  Notifications: {stats.total_notifications_sent}\n"
                    f"  Peak viewers: {stats.peak_viewers or 'N/A'}\n"
                    f"  Last stream: {last}\n"
                    f"  Platforms: {', '.join(stats.platforms)}\n"
                )

    await message.answer("\n".join(lines) if lines else "No stats.", parse_mode="Markdown")


# ── Global stats (leaderboard) ────────────────────────────────────────────────

@router.message(Command("global_stats"))
async def cmd_global_stats(message: Message, db_user: User) -> None:
    async with get_session() as session:
        analytics = AnalyticsService(session)
        stats = await analytics.get_global_stats()

    lines = [
        "🌍 *Global Statistics*\n",
        f"Active streamers: {stats.active_streamers}",
        f"Total streams: {stats.total_streams}",
        f"Streams this week: {stats.streams_last_7_days}",
        "",
        "🏆 *Top Streamers by Stream Count:*",
    ]
    for i, s in enumerate(stats.top_streamers, 1):
        trophy = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"][i - 1]
        lines.append(
            f"{trophy} *{s.display_name}*\n"
            f"    {s.total_streams} streams · {s.total_hours_streamed}h · "
            f"peak {s.peak_viewers or '?'} viewers"
        )

    await message.answer("\n".join(lines), parse_mode="Markdown")
