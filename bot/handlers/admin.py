"""Admin handlers: streamer CRUD, channel management, health, test notifications.

Features:
  - Feature 7:  Template preview before saving (assign_channel_template_input)
  - Feature 8:  /export — CSV analytics export
  - Feature 9:  Poll priority management via set_priority callback
  - Feature 11: Enhanced /health command with uptime + Twitch token status
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import structlog
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from bot.keyboards.inline import (
    back_keyboard, channels_list_keyboard, confirm_keyboard,
    platforms_keyboard, priority_keyboard, skip_keyboard,
    streamer_actions_keyboard, streamers_list_keyboard,
)
from bot.states import (
    AddChannelStates, AddStreamerStates, AssignChannelStates,
    TestNotificationStates, UpdateApiKeyStates,
)
from bot.texts import T
from config import settings
from db.database import get_session
from db.models import Platform, User, UserRole
from scheduler.polling import trigger_poll_for_streamer
from services.admin_service import AdminService
from services.analytics_service import AnalyticsService
from services.channel_service import ChannelService
from services.http_client import get_http_session
from services.streamer_service import StreamerService
from services.template_service import preview_template, validate_template

logger = structlog.get_logger(__name__)
router = Router()


def _admin_only(user: User) -> bool:
    return user.role in (UserRole.ADMIN, UserRole.OWNER)


# ── Streamer list ─────────────────────────────────────────────────────────────

@router.message(Command("list_streamers"))
async def cmd_list_streamers(message: Message, db_user: User) -> None:
    if not _admin_only(db_user):
        await message.answer(T.ADMIN_ONLY)
        return
    async with get_session() as session:
        svc = StreamerService(session)
        streamers = await svc.list_streamers()
    if not streamers:
        await message.answer(T.NO_STREAMERS_ADD_HINT)
        return
    kb = streamers_list_keyboard(streamers, action_prefix="view_streamer")
    await message.answer(T.ALL_STREAMERS_HEADER, reply_markup=kb, parse_mode="Markdown")


@router.callback_query(F.data.startswith("view_streamer:"))
async def cb_view_streamer(callback: CallbackQuery, db_user: User) -> None:
    if not _admin_only(db_user):
        await callback.answer(T.ADMIN_ONLY, show_alert=True)
        return
    streamer_id = int(callback.data.split(":")[1])
    async with get_session() as session:
        svc = StreamerService(session)
        streamer = await svc.get_streamer(streamer_id)
    if not streamer:
        await callback.answer(T.STREAMER_NOT_FOUND, show_alert=True)
        return

    status = "🟢 Активен"
    if streamer.auto_disabled_at:
        status = f"⛔ Авто-отключён: {streamer.auto_disabled_reason}"
    elif streamer.is_paused:
        status = "⏸ На паузе"

    priority_str = T.PRIORITY_LABELS.get(getattr(streamer, "poll_priority", 2), T.PRIORITY_LABELS[2])
    platforms = ", ".join(a.platform.value for a in streamer.platform_accounts) or "—"
    channels = ", ".join(a.channel.title for a in streamer.channel_assignments if a.is_active) or "—"

    text = (
        f"📡 *{streamer.display_name}*\n"
        f"Статус: {status}\n"
        f"Приоритет опроса: {priority_str}\n"
        f"Платформы: {platforms}\n"
        f"Каналы: {channels}\n"
    )
    kb = streamer_actions_keyboard(streamer_id, streamer.is_paused)
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")
    await callback.answer()


# ── Add streamer wizard ────────────────────────────────────────────────────────

@router.message(Command("add_streamer"))
async def cmd_add_streamer(message: Message, db_user: User, state: FSMContext) -> None:
    if not _admin_only(db_user):
        await message.answer(T.ADMIN_ONLY)
        return
    await state.set_state(AddStreamerStates.waiting_name)
    await message.answer(T.ADD_STREAMER_START, parse_mode="Markdown")


@router.message(AddStreamerStates.waiting_name)
async def add_streamer_name(message: Message, db_user: User, state: FSMContext) -> None:
    name = message.text.strip()
    if len(name) < 2:
        await message.answer(T.ADD_STREAMER_NAME_SHORT)
        return
    await state.update_data(name=name, platforms={})
    await state.set_state(AddStreamerStates.waiting_platform_choice)
    await message.answer(
        T.ADD_STREAMER_SELECT_PLATFORM.format(name=name),
        reply_markup=platforms_keyboard("add_platform"),
        parse_mode="Markdown",
    )


@router.callback_query(F.data.startswith("add_platform:"), AddStreamerStates.waiting_platform_choice)
async def add_streamer_platform_choice(callback: CallbackQuery, state: FSMContext) -> None:
    platform_str = callback.data.split(":")[1]
    if platform_str == "done":
        data = await state.get_data()
        if not data.get("platforms"):
            await callback.answer(T.ADD_STREAMER_PLATFORM_NEED_ONE, show_alert=True)
            return
        # Create the streamer — use shared HTTP session (no per-request ClientSession)
        async with get_session() as session:
            svc = StreamerService(session)
            streamer = await svc.create_streamer(data["name"], callback.from_user.id)
            http = get_http_session()
            for p_str, url in data["platforms"].items():
                platform = Platform(p_str)
                account, error = await svc.add_platform_account(
                    streamer.id, platform, url, http
                )
                if error:
                    logger.warning("add_streamer.platform_error", error=error)

        await state.clear()
        await callback.message.edit_text(
            T.ADD_STREAMER_DONE.format(
                name=data["name"],
                count=len(data["platforms"]),
            ),
            parse_mode="Markdown",
        )
        await callback.answer()
        return

    await state.update_data(current_platform=platform_str)
    await state.set_state(AddStreamerStates.waiting_platform_url)
    await callback.message.edit_text(
        T.ADD_STREAMER_ENTER_URL.format(platform=platform_str.capitalize()),
        parse_mode="Markdown",
    )
    await callback.answer()


@router.message(AddStreamerStates.waiting_platform_url)
async def add_streamer_platform_url(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    url = message.text.strip()
    platform_str = data.get("current_platform", "")

    platforms = data.get("platforms", {})
    platforms[platform_str] = url
    await state.update_data(platforms=platforms)
    await state.set_state(AddStreamerStates.waiting_platform_choice)

    added = "\n".join(f"  ✓ {p}: {u}" for p, u in platforms.items())
    await message.answer(
        T.ADD_STREAMER_URL_ADDED.format(platform=platform_str, list=added),
        reply_markup=platforms_keyboard("add_platform"),
        parse_mode="Markdown",
    )


# ── Pause / Resume ────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("streamer_pause:"))
async def cb_pause_streamer(callback: CallbackQuery, db_user: User) -> None:
    if not _admin_only(db_user):
        await callback.answer(T.ADMIN_ONLY, show_alert=True)
        return
    streamer_id = int(callback.data.split(":")[1])
    async with get_session() as session:
        svc = StreamerService(session)
        success = await svc.pause(streamer_id)
    if success:
        await callback.answer(T.STREAMER_PAUSED, show_alert=True)
    else:
        await callback.answer(T.STREAMER_NOT_FOUND, show_alert=True)


@router.callback_query(F.data.startswith("streamer_resume:"))
async def cb_resume_streamer(callback: CallbackQuery, db_user: User) -> None:
    if not _admin_only(db_user):
        await callback.answer(T.ADMIN_ONLY, show_alert=True)
        return
    streamer_id = int(callback.data.split(":")[1])
    async with get_session() as session:
        svc = StreamerService(session)
        success = await svc.resume(streamer_id)
    if success:
        await callback.answer(T.STREAMER_RESUMED, show_alert=True)
    else:
        await callback.answer(T.STREAMER_NOT_FOUND, show_alert=True)


# ── Delete streamer ────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("streamer_delete:"))
async def cb_delete_streamer(callback: CallbackQuery, db_user: User) -> None:
    if not _admin_only(db_user):
        await callback.answer(T.ADMIN_ONLY, show_alert=True)
        return
    streamer_id = int(callback.data.split(":")[1])
    kb = confirm_keyboard(f"confirm_delete_streamer:{streamer_id}")
    await callback.message.edit_text(
        T.DELETE_STREAMER_CONFIRM,
        reply_markup=kb,
        parse_mode="Markdown",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("confirm_delete_streamer:"))
async def cb_confirm_delete_streamer(callback: CallbackQuery, db_user: User) -> None:
    if not _admin_only(db_user):
        await callback.answer(T.ADMIN_ONLY, show_alert=True)
        return
    streamer_id = int(callback.data.split(":")[1])
    async with get_session() as session:
        svc = StreamerService(session)
        success = await svc.remove_streamer(streamer_id)
    if success:
        await callback.message.edit_text(T.STREAMER_DELETED)
    else:
        await callback.message.edit_text(T.STREAMER_DELETE_FAILED)
    await callback.answer()


# ── Streamer action callbacks ─────────────────────────────────────────────────

@router.callback_query(F.data.startswith("streamer_stats:"))
async def cb_streamer_stats(callback: CallbackQuery, db_user: User) -> None:
    if not _admin_only(db_user):
        await callback.answer(T.ADMIN_ONLY, show_alert=True)
        return
    streamer_id = int(callback.data.split(":")[1])
    async with get_session() as session:
        svc = AnalyticsService(session)
        stats = await svc.get_streamer_stats(streamer_id)
    if stats is None:
        await callback.answer(T.STREAMER_STATS_NOT_FOUND, show_alert=True)
        return
    last = stats.last_stream_at.strftime("%d %b %Y") if stats.last_stream_at else T.STATS_NEVER
    text = T.STREAMER_STATS.format(
        name=stats.display_name,
        total=stats.total_streams,
        hours=stats.total_hours_streamed,
        notifs=stats.total_notifications_sent,
        peak=stats.peak_viewers or T.STATS_NA,
        last=last,
        platforms=", ".join(stats.platforms) or "—",
    )
    await callback.message.edit_text(text, parse_mode="Markdown",
                                     reply_markup=back_keyboard("back_to_streamers"))
    await callback.answer()


@router.callback_query(F.data.startswith("streamer_channels:"))
async def cb_streamer_channels(callback: CallbackQuery, db_user: User) -> None:
    if not _admin_only(db_user):
        await callback.answer(T.ADMIN_ONLY, show_alert=True)
        return
    streamer_id = int(callback.data.split(":")[1])
    async with get_session() as session:
        svc = StreamerService(session)
        streamer = await svc.get_streamer(streamer_id)
        assignments = await svc.get_assignments(streamer_id)
    if streamer is None:
        await callback.answer(T.STREAMER_NOT_FOUND, show_alert=True)
        return
    if not assignments:
        text = T.STREAMER_CHANNELS_NONE.format(name=streamer.display_name)
    else:
        lines = []
        for a in assignments:
            ch = a.channel
            viewers = f"мин {a.min_viewer_count}👥" if a.min_viewer_count else "без порога"
            tmpl = "Свой шаблон" if a.message_template else "Шаблон по умолчанию"
            end_notif = "✅ уведомление об окончании" if getattr(a, "send_end_notification", True) else "❌ уведомление об окончании"
            lines.append(f"• *{ch.title}* — {tmpl}, {viewers}, {end_notif}")
        text = T.STREAMER_CHANNELS_HEADER.format(name=streamer.display_name) + "\n".join(lines)
    await callback.message.edit_text(text, parse_mode="Markdown",
                                     reply_markup=back_keyboard("back_to_streamers"))
    await callback.answer()


@router.callback_query(F.data == "back_to_streamers")
async def cb_back_to_streamers(callback: CallbackQuery, db_user: User) -> None:
    async with get_session() as session:
        svc = StreamerService(session)
        streamers = await svc.list_streamers()
    kb = streamers_list_keyboard(streamers, action_prefix="view_streamer")
    await callback.message.edit_text(T.BACK_TO_STREAMERS, reply_markup=kb, parse_mode="Markdown")
    await callback.answer()


# ── Feature 9: Set poll priority ──────────────────────────────────────────────

@router.callback_query(F.data.startswith("streamer_test:"))
async def cb_streamer_test_redirect(callback: CallbackQuery, db_user: User, state: FSMContext) -> None:
    """Re-entry point from streamer action keyboard — starts test notification flow."""
    if not _admin_only(db_user):
        await callback.answer(T.ADMIN_ONLY, show_alert=True)
        return
    streamer_id = int(callback.data.split(":")[1])
    await state.update_data(streamer_id=streamer_id)
    await state.set_state(TestNotificationStates.waiting_channel)
    async with get_session() as session:
        svc = ChannelService(session)
        channels = await svc.list_channels()
    if not channels:
        await callback.message.edit_text(T.TEST_NOTIF_NO_CHANNELS)
        await state.clear()
        await callback.answer()
        return
    kb = channels_list_keyboard(channels, "test_notif_channel")
    await callback.message.edit_text(
        T.TEST_NOTIF_SELECT_CHANNEL, reply_markup=kb, parse_mode="Markdown"
    )
    await callback.answer()


@router.message(Command("set_priority"))
async def cmd_set_priority(message: Message, db_user: User) -> None:
    """Feature 9: /set_priority — change poll priority for a streamer."""
    if not _admin_only(db_user):
        await message.answer(T.ADMIN_ONLY)
        return
    async with get_session() as session:
        svc = StreamerService(session)
        streamers = await svc.list_streamers()
    if not streamers:
        await message.answer(T.NO_STREAMERS_ADD_HINT)
        return
    kb = streamers_list_keyboard(streamers, "priority_select")
    await message.answer(
        T.SET_PRIORITY_HEADER,
        reply_markup=kb,
        parse_mode="Markdown",
    )


@router.callback_query(F.data.startswith("priority_select:"))
async def cb_priority_streamer_selected(callback: CallbackQuery, db_user: User) -> None:
    if not _admin_only(db_user):
        await callback.answer(T.ADMIN_ONLY, show_alert=True)
        return
    streamer_id = int(callback.data.split(":")[1])
    async with get_session() as session:
        svc = StreamerService(session)
        streamer = await svc.get_streamer(streamer_id)
    if not streamer:
        await callback.answer(T.STREAMER_NOT_FOUND, show_alert=True)
        return
    current = getattr(streamer, "poll_priority", 2)
    current_label = T.PRIORITY_LABELS.get(current, T.PRIORITY_LABELS[2])
    await callback.message.edit_text(
        T.SET_PRIORITY_CURRENT.format(name=streamer.display_name, current=current_label),
        reply_markup=priority_keyboard(f"priority_set:{streamer_id}"),
        parse_mode="Markdown",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("priority_set:"))
async def cb_priority_set(callback: CallbackQuery, db_user: User) -> None:
    if not _admin_only(db_user):
        await callback.answer(T.ADMIN_ONLY, show_alert=True)
        return
    # Format: priority_set:{streamer_id}:{priority}
    parts = callback.data.split(":")
    streamer_id = int(parts[1])
    priority = int(parts[2])
    async with get_session() as session:
        svc = StreamerService(session)
        await svc.set_priority(streamer_id, priority)
    label = T.PRIORITY_LABELS.get(priority, str(priority))
    await callback.answer(f"Приоритет: {label}", show_alert=True)
    await callback.message.edit_text(
        T.SET_PRIORITY_DONE.format(label=label),
        parse_mode="Markdown",
    )


# ── Add channel ────────────────────────────────────────────────────────────────

@router.message(Command("add_channel"))
async def cmd_add_channel(message: Message, db_user: User, state: FSMContext) -> None:
    if not _admin_only(db_user):
        await message.answer(T.ADMIN_ONLY)
        return
    await state.set_state(AddChannelStates.waiting_channel_id)
    await message.answer(T.ADD_CHANNEL_PROMPT, parse_mode="Markdown")


@router.message(AddChannelStates.waiting_channel_id)
async def add_channel_input(message: Message, db_user: User, state: FSMContext) -> None:
    from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
    bot = message.bot

    # Accept forwarded messages from channels
    if message.forward_from_chat:
        chat = message.forward_from_chat
        chat_id = chat.id
        title = chat.title
        username = chat.username
    else:
        raw = message.text.strip()
        # Resolve @username or numeric ID
        try:
            chat = await bot.get_chat(raw)
            chat_id = chat.id
            title = chat.title or raw
            username = chat.username
        except (TelegramBadRequest, TelegramForbiddenError):
            await message.answer(T.ADD_CHANNEL_NOT_FOUND)
            return

    async with get_session() as session:
        svc = ChannelService(session)
        channel, created = await svc.add_channel(chat_id, title, username, db_user.id)

    await state.clear()
    verb = T.ADD_CHANNEL_ADDED if created else T.ADD_CHANNEL_UPDATED
    await message.answer(
        T.ADD_CHANNEL_DONE.format(title=title, chat_id=chat_id, verb=verb),
        parse_mode="Markdown",
    )


@router.message(Command("list_channels"))
async def cmd_list_channels(message: Message, db_user: User) -> None:
    if not _admin_only(db_user):
        await message.answer(T.ADMIN_ONLY)
        return
    async with get_session() as session:
        svc = ChannelService(session)
        channels = await svc.list_channels()
    if not channels:
        await message.answer(T.NO_CHANNELS)
        return
    lines = [
        f"• *{ch.title}* (`{ch.telegram_id}`)"
        + (f" @{ch.username}" if ch.username else "")
        + (f" | VK peer: `{ch.vk_peer_id}`" if ch.vk_peer_id else "")
        for ch in channels
    ]
    await message.answer(T.LIST_CHANNELS_HEADER + "\n".join(lines), parse_mode="Markdown")


# ── Assign channel wizard ─────────────────────────────────────────────────────

@router.message(Command("assign_channel"))
async def cmd_assign_channel(message: Message, db_user: User, state: FSMContext) -> None:
    if not _admin_only(db_user):
        await message.answer(T.ADMIN_ONLY)
        return
    async with get_session() as session:
        svc = StreamerService(session)
        streamers = await svc.list_streamers()
    if not streamers:
        await message.answer(T.ASSIGN_NO_STREAMERS)
        return
    await state.set_state(AssignChannelStates.waiting_streamer)
    kb = streamers_list_keyboard(streamers, "assign_streamer_sel")
    await message.answer(T.ASSIGN_CHANNEL_SELECT_STREAMER, reply_markup=kb, parse_mode="Markdown")


@router.callback_query(F.data.startswith("assign_streamer_sel:"), AssignChannelStates.waiting_streamer)
async def assign_channel_streamer_selected(callback: CallbackQuery, state: FSMContext) -> None:
    streamer_id = int(callback.data.split(":")[1])
    await state.update_data(streamer_id=streamer_id)
    await state.set_state(AssignChannelStates.waiting_channel)
    async with get_session() as session:
        svc = ChannelService(session)
        channels = await svc.list_channels()
    if not channels:
        await callback.message.edit_text(T.ASSIGN_NO_CHANNELS)
        await state.clear()
        return
    kb = channels_list_keyboard(channels, "assign_channel_sel")
    await callback.message.edit_text(T.ASSIGN_CHANNEL_SELECT_CHANNEL, reply_markup=kb, parse_mode="Markdown")
    await callback.answer()


@router.callback_query(F.data.startswith("assign_channel_sel:"), AssignChannelStates.waiting_channel)
async def assign_channel_channel_selected(callback: CallbackQuery, state: FSMContext) -> None:
    channel_id = int(callback.data.split(":")[1])
    await state.update_data(channel_id=channel_id)
    await state.set_state(AssignChannelStates.waiting_template)
    await callback.message.edit_text(
        T.ASSIGN_CHANNEL_TEMPLATE_PROMPT,
        reply_markup=skip_keyboard("assign_skip_template"),
        parse_mode="Markdown",
    )
    await callback.answer()


@router.callback_query(F.data == "assign_skip_template", AssignChannelStates.waiting_template)
async def assign_channel_skip_template(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(template=None)
    await state.set_state(AssignChannelStates.waiting_min_viewers)
    await callback.message.edit_text(
        T.ASSIGN_CHANNEL_VIEWERS_PROMPT,
        reply_markup=skip_keyboard("assign_skip_viewers"),
        parse_mode="Markdown",
    )
    await callback.answer()


@router.message(AssignChannelStates.waiting_template)
async def assign_channel_template_input(message: Message, state: FSMContext) -> None:
    """Feature 7: Validate template and show preview before saving."""
    template = message.text.strip()
    err = validate_template(template)
    if err:
        await message.answer(
            T.ASSIGN_TEMPLATE_INVALID.format(err=err),
            parse_mode="Markdown",
        )
        return

    # Feature 7: render preview with sample data
    try:
        data = await state.get_data()
        async with get_session() as session:
            svc = StreamerService(session)
            streamer = await svc.get_streamer(data.get("streamer_id", 0))
        streamer_name = streamer.display_name if streamer else "StreamerName"
        rendered_preview = preview_template(template, streamer_name=streamer_name)
    except Exception:
        rendered_preview = preview_template(template)

    await state.update_data(template=template, preview_shown=True)
    await state.set_state(AssignChannelStates.waiting_min_viewers)

    await message.answer(
        T.ASSIGN_TEMPLATE_PREVIEW.format(preview=rendered_preview),
        reply_markup=skip_keyboard("assign_skip_viewers"),
        parse_mode="Markdown",
    )


@router.callback_query(F.data == "assign_skip_viewers", AssignChannelStates.waiting_min_viewers)
async def assign_skip_viewers(callback: CallbackQuery, state: FSMContext) -> None:
    await _complete_assignment(callback.message, state, min_viewers=0)
    await state.clear()
    await callback.answer()


@router.message(AssignChannelStates.waiting_min_viewers)
async def assign_channel_min_viewers(message: Message, state: FSMContext) -> None:
    try:
        min_viewers = int(message.text.strip())
    except ValueError:
        await message.answer(T.ASSIGN_ENTER_NUMBER)
        return
    await _complete_assignment(message, state, min_viewers=min_viewers)
    await state.clear()


async def _complete_assignment(msg, state: FSMContext, min_viewers: int) -> None:
    data = await state.get_data()
    async with get_session() as session:
        svc = StreamerService(session)
        assignment = await svc.assign_channel(
            streamer_id=data["streamer_id"],
            channel_id=data["channel_id"],
            template=data.get("template"),
            min_viewers=min_viewers,
        )
    tmpl_label = T.ASSIGN_TEMPLATE_CUSTOM if data.get("template") else T.ASSIGN_TEMPLATE_DEFAULT
    await msg.answer(
        T.ASSIGN_CHANNEL_DONE.format(
            viewers=min_viewers if min_viewers else "0",
            tmpl=tmpl_label,
        ),
        parse_mode="Markdown",
    )


# ── Test notification ─────────────────────────────────────────────────────────

@router.message(Command("test_notification"))
async def cmd_test_notification(message: Message, db_user: User, state: FSMContext) -> None:
    if not _admin_only(db_user):
        await message.answer(T.ADMIN_ONLY)
        return
    async with get_session() as session:
        svc = StreamerService(session)
        streamers = await svc.list_streamers()
    if not streamers:
        await message.answer(T.TEST_NOTIF_NO_STREAMERS)
        return
    await state.set_state(TestNotificationStates.waiting_streamer)
    kb = streamers_list_keyboard(streamers, "test_notif_streamer")
    await message.answer(T.TEST_NOTIF_SELECT_STREAMER, reply_markup=kb, parse_mode="Markdown")


@router.callback_query(F.data.startswith("test_notif_streamer:"), TestNotificationStates.waiting_streamer)
async def test_notif_streamer_selected(callback: CallbackQuery, state: FSMContext) -> None:
    streamer_id = int(callback.data.split(":")[1])
    await state.update_data(streamer_id=streamer_id)
    await state.set_state(TestNotificationStates.waiting_channel)
    async with get_session() as session:
        svc = ChannelService(session)
        channels = await svc.list_channels()
    if not channels:
        await callback.message.edit_text(T.TEST_NOTIF_NO_CHANNELS)
        await state.clear()
        await callback.answer()
        return
    kb = channels_list_keyboard(channels, "test_notif_channel")
    await callback.message.edit_text(
        T.TEST_NOTIF_SELECT_CHANNEL, reply_markup=kb, parse_mode="Markdown"
    )
    await callback.answer()


@router.callback_query(F.data.startswith("test_notif_channel:"), TestNotificationStates.waiting_channel)
async def test_notif_channel_selected(callback: CallbackQuery, db_user: User, state: FSMContext) -> None:
    from bot.main import get_bot_context
    channel_id = int(callback.data.split(":")[1])
    data = await state.get_data()
    await state.clear()

    async with get_session() as session:
        streamer_svc = StreamerService(session)
        channel_svc = ChannelService(session)
        streamer = await streamer_svc.get_streamer(data["streamer_id"])
        channel = await channel_svc.get_channel(channel_id)

    if not streamer or not channel:
        await callback.message.edit_text(T.TEST_NOTIF_NOT_FOUND)
        return

    ctx = get_bot_context()
    from services.notification_service import NotificationService
    async with get_session() as session:
        notif_svc = NotificationService(
            session=session,
            send_fn=ctx.send_notification,
            edit_fn=ctx.edit_notification,
            delete_fn=ctx.delete_notification,
        )
        success = await notif_svc.send_test_notification(
            channel_telegram_id=channel.telegram_id,
            streamer_name=streamer.display_name,
        )

    if success:
        await callback.message.edit_text(
            T.TEST_NOTIF_SUCCESS.format(title=channel.title), parse_mode="Markdown"
        )
    else:
        await callback.message.edit_text(T.TEST_NOTIF_FAILED)
    await callback.answer()


# ── Manual poll ────────────────────────────────────────────────────────────────

@router.message(Command("poll_now"))
async def cmd_poll_now(message: Message, db_user: User) -> None:
    if not _admin_only(db_user):
        await message.answer(T.ADMIN_ONLY)
        return
    await message.answer(T.POLL_NOW_START)
    async with get_session() as session:
        svc = StreamerService(session)
        streamers = await svc.list_streamers()

    results = []
    for streamer in streamers:
        if not streamer.is_active or streamer.is_paused or streamer.auto_disabled_at:
            continue
        res = await trigger_poll_for_streamer(streamer.id)
        live = [p for p, is_live in res.items() if is_live]
        status = T.POLL_NOW_LIVE.format(platforms=", ".join(live)) if live else T.POLL_NOW_OFFLINE
        results.append(f"• *{streamer.display_name}*: {status}")

    if results:
        text = T.POLL_NOW_RESULTS_HEADER + "\n".join(results)
    else:
        text = T.POLL_NOW_NO_STREAMERS
    await message.answer(text, parse_mode="Markdown")


# ── Feature 11: Enhanced /health command ─────────────────────────────────────

@router.message(Command("health"))
async def cmd_health(message: Message, db_user: User) -> None:
    if not _admin_only(db_user):
        await message.answer(T.ADMIN_ONLY)
        return
    from sqlalchemy import select
    from db.models import Platform, PollingState
    from bot.main import get_uptime_seconds

    async with get_session() as session:
        result = await session.execute(select(PollingState))
        states = {ps.platform: ps for ps in result.scalars().all()}
        svc = AnalyticsService(session)
        global_stats = await svc.get_global_stats()

    now = datetime.now(timezone.utc)
    lines = [T.HEALTH_HEADER]

    # Feature 11: Bot uptime
    uptime_sec = get_uptime_seconds()
    if uptime_sec is not None:
        hours = int(uptime_sec // 3600)
        minutes = int((uptime_sec % 3600) // 60)
        lines.append(T.HEALTH_UPTIME.format(hours=hours, minutes=minutes))

    # Platform poll states
    for platform in Platform:
        ps = states.get(platform)
        if ps:
            last = ps.last_poll_at
            if last:
                secs_ago = int((now - last).total_seconds())
                if secs_ago < 60:
                    ago = f"{secs_ago}с назад"
                else:
                    ago = f"{secs_ago // 60}м назад"
            else:
                ago = T.HEALTH_NEVER
            rate_limited = ps.rate_limited_until and ps.rate_limited_until > now
            rl_str = f" ⚠️ Лимит до {ps.rate_limited_until:%H:%M}" if rate_limited else ""
            yt_quota = (
                f" | Квота: {ps.youtube_quota_used}/{settings.YOUTUBE_DAILY_QUOTA_LIMIT}"
                if platform == Platform.YOUTUBE else ""
            )
            # Feature 11: Twitch token status
            twitch_token_str = ""
            if platform == Platform.TWITCH and ps.twitch_token_expires_at:
                remaining = (ps.twitch_token_expires_at - now).total_seconds()
                if remaining > 0:
                    twitch_token_str = f" | Токен: {int(remaining // 3600)}ч"
                else:
                    twitch_token_str = " | Токен: ⚠️ истёк"
            lines.append(f"• *{platform.value.upper()}*: последний опрос {ago}{yt_quota}{twitch_token_str}{rl_str}")
        else:
            lines.append(f"• *{platform.value.upper()}*: {T.HEALTH_NO_DATA}")

    lines.append("")
    lines.append(T.HEALTH_STREAMERS.format(
        active=global_stats.active_streamers,
        total=global_stats.total_streamers,
    ))
    lines.append(T.HEALTH_STREAMS.format(count=global_stats.streams_last_7_days))
    lines.append(T.HEALTH_NOTIFS.format(count=global_stats.total_notifications))

    mode = T.HEALTH_MODE_WEBHOOK if settings.WEBHOOK_URL else T.HEALTH_MODE_POLLING
    lines.append(T.HEALTH_CONNECTION.format(mode=mode))

    await message.answer("\n".join(lines), parse_mode="Markdown")


# ── Feature 8: CSV export ─────────────────────────────────────────────────────

@router.message(Command("export"))
async def cmd_export(message: Message, db_user: User) -> None:
    """Feature 8: /export — download stream history as CSV.

    Usage: /export [days=30]
    Example: /export 7 — export last 7 days
    """
    if not _admin_only(db_user):
        await message.answer(T.ADMIN_ONLY)
        return

    args = message.text.split()
    try:
        days = int(args[1]) if len(args) > 1 else 30
    except ValueError:
        days = 30

    await message.answer(T.EXPORT_GENERATING.format(days=days))

    async with get_session() as session:
        svc = AdminService(session)
        csv_bytes, record_count = await svc.export_streams_csv(days)

    if record_count == 0:
        await message.answer(T.EXPORT_NO_DATA.format(days=days))
        return

    filename = f"streams_{datetime.now(timezone.utc).strftime('%Y%m%d')}_last{days}d.csv"
    await message.answer_document(
        document=BufferedInputFile(csv_bytes, filename=filename),
        caption=T.EXPORT_CAPTION.format(count=record_count, days=days),
    )


# ── Update API key ─────────────────────────────────────────────────────────────

@router.message(Command("update_api_key"))
async def cmd_update_api_key(message: Message, db_user: User, state: FSMContext) -> None:
    if not _admin_only(db_user):
        await message.answer(T.ADMIN_ONLY)
        return
    await state.set_state(UpdateApiKeyStates.waiting_platform)
    kb = platforms_keyboard("apikey_platform")
    await message.answer(T.UPDATE_API_KEY_HEADER, reply_markup=kb, parse_mode="Markdown")


@router.callback_query(F.data.startswith("apikey_platform:"), UpdateApiKeyStates.waiting_platform)
async def apikey_platform_selected(callback: CallbackQuery, state: FSMContext) -> None:
    platform_str = callback.data.split(":")[1]
    if platform_str == "done":
        await state.clear()
        await callback.message.edit_text(T.UPDATE_API_KEY_CANCELLED)
        return
    await state.update_data(platform=platform_str)
    await state.set_state(UpdateApiKeyStates.waiting_key_name)
    await callback.message.edit_text(
        T.UPDATE_API_KEY_PLATFORM.format(platform=platform_str.upper()),
        parse_mode="Markdown",
    )
    await callback.answer()


@router.message(UpdateApiKeyStates.waiting_key_name)
async def apikey_name_input(message: Message, state: FSMContext) -> None:
    await state.update_data(key_name=message.text.strip())
    await state.set_state(UpdateApiKeyStates.waiting_key_value)
    await message.answer(T.UPDATE_API_KEY_VALUE, parse_mode="Markdown")


@router.message(UpdateApiKeyStates.waiting_key_value)
async def apikey_value_input(message: Message, db_user: User, state: FSMContext) -> None:
    data = await state.get_data()
    await state.clear()

    # Delete the message immediately to avoid leaking the key in chat
    try:
        await message.delete()
    except Exception:
        pass

    key_value = message.text.strip()
    platform = Platform(data["platform"])
    key_name = data["key_name"]

    async with get_session() as session:
        svc = AdminService(session)
        try:
            await svc.upsert_api_credential(platform, key_name, key_value, db_user.id)
        except ValueError as exc:
            await message.answer(
                T.UPDATE_API_KEY_NO_ENCRYPTION if "ENCRYPTION_KEY" in str(exc) else f"❌ {exc}",
                parse_mode="Markdown",
            )
            return

    await message.answer(
        T.UPDATE_API_KEY_DONE.format(platform=platform.value.upper(), key_name=key_name),
        parse_mode="Markdown",
    )


# ── Global stats ───────────────────────────────────────────────────────────────

@router.message(Command("stream_stats"))
async def cmd_stream_stats(message: Message, db_user: User) -> None:
    if not _admin_only(db_user):
        await message.answer(T.ADMIN_ONLY)
        return
    async with get_session() as session:
        svc = AnalyticsService(session)
        stats = await svc.get_global_stats()

    lines = [
        T.STREAM_STATS_HEADER,
        f"Стримеров: {stats.total_streamers} ({stats.active_streamers} активных)",
        f"Всего стримов: {stats.total_streams}",
        f"Стримов за 7 дней: {stats.streams_last_7_days}",
        f"Уведомлений отправлено: {stats.total_notifications}",
        "",
        T.STREAM_STATS_TOP,
    ]
    for i, s in enumerate(stats.top_streamers, 1):
        lines.append(
            f"{i}. *{s.display_name}* — {s.total_streams} стр., "
            f"{s.total_hours_streamed}ч, {s.total_notifications_sent} ув."
        )

    await message.answer("\n".join(lines), parse_mode="Markdown")


# ── Cancel callback ────────────────────────────────────────────────────────────

@router.callback_query(F.data == "cancel")
async def cb_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text(T.CANCELLED)
    await callback.answer()
