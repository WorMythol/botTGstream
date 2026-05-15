"""Admin handlers: streamer CRUD, channel management, health, test notifications.

Features:
  - Feature 7:  Template preview before saving (assign_channel_template_input)
  - Feature 8:  /export — CSV analytics export
  - Feature 9:  Poll priority management via set_priority callback
  - Feature 11: Enhanced /health command with uptime + Twitch token status
"""
from __future__ import annotations

import asyncio
import csv
import io
from datetime import datetime, timezone
from typing import Optional

import aiohttp
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
from config import settings
from db.database import get_session
from db.models import Platform, User, UserRole
from scheduler.polling import trigger_poll_for_streamer
from services.analytics_service import AnalyticsService
from services.channel_service import ChannelService
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
        await message.answer("⛔ Admins only.")
        return
    async with get_session() as session:
        svc = StreamerService(session)
        streamers = await svc.list_streamers()
    if not streamers:
        await message.answer("No streamers configured. Use /add_streamer to add one.")
        return
    kb = streamers_list_keyboard(streamers, action_prefix="view_streamer")
    await message.answer("📋 *All streamers* — tap to manage:", reply_markup=kb, parse_mode="Markdown")


@router.callback_query(F.data.startswith("view_streamer:"))
async def cb_view_streamer(callback: CallbackQuery, db_user: User) -> None:
    if not _admin_only(db_user):
        await callback.answer("⛔ Admins only.", show_alert=True)
        return
    streamer_id = int(callback.data.split(":")[1])
    async with get_session() as session:
        svc = StreamerService(session)
        streamer = await svc.get_streamer(streamer_id)
    if not streamer:
        await callback.answer("Streamer not found.", show_alert=True)
        return

    status = "🟢 Active"
    if streamer.auto_disabled_at:
        status = f"⛔ Auto-disabled: {streamer.auto_disabled_reason}"
    elif streamer.is_paused:
        status = "⏸ Paused"

    priority_labels = {1: "🟢 Low", 2: "🟡 Normal", 3: "🔴 High"}
    priority_str = priority_labels.get(getattr(streamer, "poll_priority", 2), "🟡 Normal")

    platforms = ", ".join(a.platform.value for a in streamer.platform_accounts) or "None"
    channels = ", ".join(a.channel.title for a in streamer.channel_assignments if a.is_active) or "None"

    text = (
        f"📡 *{streamer.display_name}*\n"
        f"Status: {status}\n"
        f"Poll priority: {priority_str}\n"
        f"Platforms: {platforms}\n"
        f"Channels: {channels}\n"
    )
    kb = streamer_actions_keyboard(streamer_id, streamer.is_paused)
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")
    await callback.answer()


# ── Add streamer wizard ────────────────────────────────────────────────────────

@router.message(Command("add_streamer"))
async def cmd_add_streamer(message: Message, db_user: User, state: FSMContext) -> None:
    if not _admin_only(db_user):
        await message.answer("⛔ Admins only.")
        return
    await state.set_state(AddStreamerStates.waiting_name)
    await message.answer(
        "🆕 *Add New Streamer*\n\nEnter the streamer's *display name*:",
        parse_mode="Markdown",
    )


@router.message(AddStreamerStates.waiting_name)
async def add_streamer_name(message: Message, db_user: User, state: FSMContext) -> None:
    name = message.text.strip()
    if len(name) < 2:
        await message.answer("Name too short. Try again:")
        return
    await state.update_data(name=name, platforms={})
    await state.set_state(AddStreamerStates.waiting_platform_choice)
    await message.answer(
        f"✅ Name: *{name}*\n\nNow add platform channels. Select a platform to add:",
        reply_markup=platforms_keyboard("add_platform"),
        parse_mode="Markdown",
    )


@router.callback_query(F.data.startswith("add_platform:"), AddStreamerStates.waiting_platform_choice)
async def add_streamer_platform_choice(callback: CallbackQuery, state: FSMContext) -> None:
    platform_str = callback.data.split(":")[1]
    if platform_str == "done":
        data = await state.get_data()
        if not data.get("platforms"):
            await callback.answer("Add at least one platform first.", show_alert=True)
            return
        # Create the streamer
        async with get_session() as session:
            svc = StreamerService(session)
            streamer = await svc.create_streamer(data["name"], callback.from_user.id)
            http_session = aiohttp.ClientSession()
            try:
                for platform_str, url in data["platforms"].items():
                    platform = Platform(platform_str)
                    account, error = await svc.add_platform_account(
                        streamer.id, platform, url, http_session
                    )
                    if error:
                        logger.warning("add_streamer.platform_error", error=error)
            finally:
                await http_session.close()

        await state.clear()
        await callback.message.edit_text(
            f"✅ Streamer *{data['name']}* created with "
            f"{len(data['platforms'])} platform(s)!\n\n"
            f"Use /assign_channel to link them to notification channels.",
            parse_mode="Markdown",
        )
        await callback.answer()
        return

    await state.update_data(current_platform=platform_str)
    await state.set_state(AddStreamerStates.waiting_platform_url)
    await callback.message.edit_text(
        f"Enter the *{platform_str.capitalize()}* channel URL:",
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
        f"✅ Added {platform_str} URL.\n\nPlatforms so far:\n{added}\n\nAdd more or tap Done:",
        reply_markup=platforms_keyboard("add_platform"),
        parse_mode="Markdown",
    )


# ── Pause / Resume ────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("streamer_pause:"))
async def cb_pause_streamer(callback: CallbackQuery, db_user: User) -> None:
    if not _admin_only(db_user):
        await callback.answer("⛔ Admins only.", show_alert=True)
        return
    streamer_id = int(callback.data.split(":")[1])
    async with get_session() as session:
        svc = StreamerService(session)
        success = await svc.pause(streamer_id)
    if success:
        await callback.answer("⏸ Streamer paused.", show_alert=True)
    else:
        await callback.answer("Streamer not found.", show_alert=True)


@router.callback_query(F.data.startswith("streamer_resume:"))
async def cb_resume_streamer(callback: CallbackQuery, db_user: User) -> None:
    if not _admin_only(db_user):
        await callback.answer("⛔ Admins only.", show_alert=True)
        return
    streamer_id = int(callback.data.split(":")[1])
    async with get_session() as session:
        svc = StreamerService(session)
        success = await svc.resume(streamer_id)
    if success:
        await callback.answer("▶️ Streamer resumed.", show_alert=True)
    else:
        await callback.answer("Streamer not found.", show_alert=True)


# ── Delete streamer ────────────────────────────────────────────────────────────

@router.callback_query(F.data.startswith("streamer_delete:"))
async def cb_delete_streamer(callback: CallbackQuery, db_user: User) -> None:
    if not _admin_only(db_user):
        await callback.answer("⛔ Admins only.", show_alert=True)
        return
    streamer_id = int(callback.data.split(":")[1])
    kb = confirm_keyboard(f"confirm_delete_streamer:{streamer_id}")
    await callback.message.edit_text(
        "⚠️ Are you sure you want to *permanently delete* this streamer?\n"
        "All stream history and notifications will also be deleted.",
        reply_markup=kb,
        parse_mode="Markdown",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("confirm_delete_streamer:"))
async def cb_confirm_delete_streamer(callback: CallbackQuery, db_user: User) -> None:
    if not _admin_only(db_user):
        await callback.answer("⛔ Admins only.", show_alert=True)
        return
    streamer_id = int(callback.data.split(":")[1])
    async with get_session() as session:
        svc = StreamerService(session)
        success = await svc.remove_streamer(streamer_id)
    if success:
        await callback.message.edit_text("✅ Streamer deleted.")
    else:
        await callback.message.edit_text("❌ Streamer not found.")
    await callback.answer()


# ── Streamer action callbacks (from streamer_actions_keyboard) ────────────────

@router.callback_query(F.data.startswith("streamer_stats:"))
async def cb_streamer_stats(callback: CallbackQuery, db_user: User) -> None:
    if not _admin_only(db_user):
        await callback.answer("⛔ Admins only.", show_alert=True)
        return
    streamer_id = int(callback.data.split(":")[1])
    async with get_session() as session:
        svc = AnalyticsService(session)
        stats = await svc.get_streamer_stats(streamer_id)
    if stats is None:
        await callback.answer("Streamer not found.", show_alert=True)
        return
    last = stats.last_stream_at.strftime("%d %b %Y") if stats.last_stream_at else "Never"
    text = (
        f"📊 *{stats.display_name}* — Stats\n\n"
        f"Total streams: {stats.total_streams}\n"
        f"Hours streamed: {stats.total_hours_streamed}h\n"
        f"Notifications sent: {stats.total_notifications_sent}\n"
        f"Peak viewers: {stats.peak_viewers or 'N/A'}\n"
        f"Last stream: {last}\n"
        f"Platforms: {', '.join(stats.platforms) or 'None'}"
    )
    await callback.message.edit_text(text, parse_mode="Markdown",
                                     reply_markup=back_keyboard("back_to_streamers"))
    await callback.answer()


@router.callback_query(F.data.startswith("streamer_channels:"))
async def cb_streamer_channels(callback: CallbackQuery, db_user: User) -> None:
    if not _admin_only(db_user):
        await callback.answer("⛔ Admins only.", show_alert=True)
        return
    streamer_id = int(callback.data.split(":")[1])
    async with get_session() as session:
        svc = StreamerService(session)
        streamer = await svc.get_streamer(streamer_id)
        assignments = await svc.get_assignments(streamer_id)
    if streamer is None:
        await callback.answer("Streamer not found.", show_alert=True)
        return
    if not assignments:
        text = f"📢 *{streamer.display_name}* — no channels assigned.\n\nUse /assign\\_channel to add one."
    else:
        lines = []
        for a in assignments:
            ch = a.channel
            viewers = f"min {a.min_viewer_count}👥" if a.min_viewer_count else "no threshold"
            tmpl = "Custom template" if a.message_template else "Default template"
            end_notif = "✅ end notif" if getattr(a, "send_end_notification", True) else "❌ end notif"
            lines.append(f"• *{ch.title}* — {tmpl}, {viewers}, {end_notif}")
        text = f"📢 *{streamer.display_name}* — channels:\n\n" + "\n".join(lines)
    await callback.message.edit_text(text, parse_mode="Markdown",
                                     reply_markup=back_keyboard("back_to_streamers"))
    await callback.answer()


@router.callback_query(F.data == "back_to_streamers")
async def cb_back_to_streamers(callback: CallbackQuery, db_user: User) -> None:
    async with get_session() as session:
        svc = StreamerService(session)
        streamers = await svc.list_streamers()
    kb = streamers_list_keyboard(streamers, action_prefix="view_streamer")
    await callback.message.edit_text("📋 *All streamers* — tap to manage:",
                                     reply_markup=kb, parse_mode="Markdown")
    await callback.answer()


# ── Feature 9: Set poll priority ──────────────────────────────────────────────

@router.callback_query(F.data.startswith("streamer_test:"))
async def cb_streamer_test_redirect(callback: CallbackQuery, db_user: User, state: FSMContext) -> None:
    """Re-entry point from streamer action keyboard — starts test notification flow."""
    if not _admin_only(db_user):
        await callback.answer("⛔ Admins only.", show_alert=True)
        return
    streamer_id = int(callback.data.split(":")[1])
    await state.update_data(streamer_id=streamer_id)
    await state.set_state(TestNotificationStates.waiting_channel)
    async with get_session() as session:
        svc = ChannelService(session)
        channels = await svc.list_channels()
    if not channels:
        await callback.message.edit_text("No channels registered. Use /add_channel first.")
        await state.clear()
        await callback.answer()
        return
    kb = channels_list_keyboard(channels, "test_notif_channel")
    await callback.message.edit_text(
        "Select a *channel* to send the test to:", reply_markup=kb, parse_mode="Markdown"
    )
    await callback.answer()


@router.message(Command("set_priority"))
async def cmd_set_priority(message: Message, db_user: User) -> None:
    """Feature 9: /set_priority — change poll priority for a streamer."""
    if not _admin_only(db_user):
        await message.answer("⛔ Admins only.")
        return
    async with get_session() as session:
        svc = StreamerService(session)
        streamers = await svc.list_streamers()
    if not streamers:
        await message.answer("No streamers configured.")
        return
    kb = streamers_list_keyboard(streamers, "priority_select")
    await message.answer(
        "🎚 *Set Poll Priority*\n\nSelect a streamer:",
        reply_markup=kb,
        parse_mode="Markdown",
    )


@router.callback_query(F.data.startswith("priority_select:"))
async def cb_priority_streamer_selected(callback: CallbackQuery, db_user: User) -> None:
    if not _admin_only(db_user):
        await callback.answer("⛔ Admins only.", show_alert=True)
        return
    streamer_id = int(callback.data.split(":")[1])
    async with get_session() as session:
        svc = StreamerService(session)
        streamer = await svc.get_streamer(streamer_id)
    if not streamer:
        await callback.answer("Not found.", show_alert=True)
        return
    current = getattr(streamer, "poll_priority", 2)
    labels = {1: "🟢 Low (10m)", 2: "🟡 Normal (5m)", 3: "🔴 High (60s)"}
    await callback.message.edit_text(
        f"📡 *{streamer.display_name}*\nCurrent priority: {labels.get(current, 'Normal')}\n\nSelect new priority:",
        reply_markup=priority_keyboard(f"priority_set:{streamer_id}"),
        parse_mode="Markdown",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("priority_set:"))
async def cb_priority_set(callback: CallbackQuery, db_user: User) -> None:
    if not _admin_only(db_user):
        await callback.answer("⛔ Admins only.", show_alert=True)
        return
    # Format: priority_set:{streamer_id}:{priority}
    parts = callback.data.split(":")
    streamer_id = int(parts[1])
    priority = int(parts[2])
    async with get_session() as session:
        svc = StreamerService(session)
        await svc.set_priority(streamer_id, priority)
    labels = {1: "🟢 Low (10m)", 2: "🟡 Normal (5m)", 3: "🔴 High (60s)"}
    await callback.answer(f"Priority set to {labels.get(priority, priority)}", show_alert=True)
    await callback.message.edit_text(f"✅ Poll priority updated to *{labels.get(priority)}*.",
                                     parse_mode="Markdown")


# ── Add channel ────────────────────────────────────────────────────────────────

@router.message(Command("add_channel"))
async def cmd_add_channel(message: Message, db_user: User, state: FSMContext) -> None:
    if not _admin_only(db_user):
        await message.answer("⛔ Admins only.")
        return
    await state.set_state(AddChannelStates.waiting_channel_id)
    await message.answer(
        "📢 *Add Notification Channel*\n\n"
        "Forward any message from the channel here, or send its `@username` or numeric ID.\n\n"
        "Make sure the bot is an *admin* in the channel first.",
        parse_mode="Markdown",
    )


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
            await message.answer(
                "❌ Could not find that channel. Check the ID/username and ensure the bot is an admin."
            )
            return

    async with get_session() as session:
        svc = ChannelService(session)
        channel, created = await svc.add_channel(chat_id, title, username, db_user.id)

    await state.clear()
    verb = "added" if created else "updated"
    await message.answer(
        f"✅ Channel *{title}* (`{chat_id}`) {verb}!\n\n"
        f"Use /assign_channel to link streamers to it.",
        parse_mode="Markdown",
    )


@router.message(Command("list_channels"))
async def cmd_list_channels(message: Message, db_user: User) -> None:
    if not _admin_only(db_user):
        await message.answer("⛔ Admins only.")
        return
    async with get_session() as session:
        svc = ChannelService(session)
        channels = await svc.list_channels()
    if not channels:
        await message.answer("No channels registered. Use /add_channel.")
        return
    lines = [
        f"• *{ch.title}* (`{ch.telegram_id}`)"
        + (f" @{ch.username}" if ch.username else "")
        + (f" | VK peer: `{ch.vk_peer_id}`" if ch.vk_peer_id else "")
        for ch in channels
    ]
    await message.answer("📢 *Registered channels:*\n" + "\n".join(lines), parse_mode="Markdown")


# ── Assign channel wizard ─────────────────────────────────────────────────────

@router.message(Command("assign_channel"))
async def cmd_assign_channel(message: Message, db_user: User, state: FSMContext) -> None:
    if not _admin_only(db_user):
        await message.answer("⛔ Admins only.")
        return
    async with get_session() as session:
        svc = StreamerService(session)
        streamers = await svc.list_streamers()
    if not streamers:
        await message.answer("No streamers found. Add one first with /add_streamer.")
        return
    await state.set_state(AssignChannelStates.waiting_streamer)
    kb = streamers_list_keyboard(streamers, "assign_streamer_sel")
    await message.answer("Select a *streamer* to assign:", reply_markup=kb, parse_mode="Markdown")


@router.callback_query(F.data.startswith("assign_streamer_sel:"), AssignChannelStates.waiting_streamer)
async def assign_channel_streamer_selected(callback: CallbackQuery, state: FSMContext) -> None:
    streamer_id = int(callback.data.split(":")[1])
    await state.update_data(streamer_id=streamer_id)
    await state.set_state(AssignChannelStates.waiting_channel)
    async with get_session() as session:
        svc = ChannelService(session)
        channels = await svc.list_channels()
    if not channels:
        await callback.message.edit_text("No channels registered. Use /add_channel first.")
        await state.clear()
        return
    kb = channels_list_keyboard(channels, "assign_channel_sel")
    await callback.message.edit_text("Select a *channel* to assign to:", reply_markup=kb, parse_mode="Markdown")
    await callback.answer()


@router.callback_query(F.data.startswith("assign_channel_sel:"), AssignChannelStates.waiting_channel)
async def assign_channel_channel_selected(callback: CallbackQuery, state: FSMContext) -> None:
    channel_id = int(callback.data.split(":")[1])
    await state.update_data(channel_id=channel_id)
    await state.set_state(AssignChannelStates.waiting_template)
    await callback.message.edit_text(
        "Optionally enter a *custom message template* for this streamer/channel pair.\n\n"
        "Available variables: `{{ streamer_name }}`, `{{ stream_title }}`, `{{ viewer_count }}`, `{{ platform_links }}`\n\n"
        "Tap *Skip* to use the default template.",
        reply_markup=skip_keyboard("assign_skip_template"),
        parse_mode="Markdown",
    )
    await callback.answer()


@router.callback_query(F.data == "assign_skip_template", AssignChannelStates.waiting_template)
async def assign_channel_skip_template(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(template=None)
    await state.set_state(AssignChannelStates.waiting_min_viewers)
    await callback.message.edit_text(
        "Enter *minimum viewer count* (0 = no threshold):",
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
        await message.answer(f"❌ Invalid template syntax: `{err}`\n\nFix it and try again:",
                              parse_mode="Markdown")
        return

    # Feature 7: render preview with sample data
    try:
        data = await state.get_data()
        # Try to get streamer name for preview
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
        f"✅ Template valid! *Preview:*\n\n{rendered_preview}\n\n"
        f"─────────────────────\n"
        f"Now enter *minimum viewer count* (0 = no threshold):",
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
        await message.answer("Enter a number:")
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
    await msg.answer(
        f"✅ Assignment created!\n"
        f"Min viewers: {min_viewers if min_viewers else 'None'}\n"
        f"Template: {'Custom' if data.get('template') else 'Default'}\n"
        f"End notifications: ✅ enabled",
        parse_mode="Markdown",
    )


# ── Test notification ─────────────────────────────────────────────────────────

@router.message(Command("test_notification"))
async def cmd_test_notification(message: Message, db_user: User, state: FSMContext) -> None:
    if not _admin_only(db_user):
        await message.answer("⛔ Admins only.")
        return
    async with get_session() as session:
        svc = StreamerService(session)
        streamers = await svc.list_streamers()
    if not streamers:
        await message.answer("No streamers found.")
        return
    await state.set_state(TestNotificationStates.waiting_streamer)
    kb = streamers_list_keyboard(streamers, "test_notif_streamer")
    await message.answer("Select a *streamer* for the test:", reply_markup=kb, parse_mode="Markdown")


@router.callback_query(F.data.startswith("test_notif_streamer:"), TestNotificationStates.waiting_streamer)
async def test_notif_streamer_selected(callback: CallbackQuery, state: FSMContext) -> None:
    streamer_id = int(callback.data.split(":")[1])
    await state.update_data(streamer_id=streamer_id)
    await state.set_state(TestNotificationStates.waiting_channel)
    async with get_session() as session:
        svc = ChannelService(session)
        channels = await svc.list_channels()
    # FIX m-3: guard against empty channel list
    if not channels:
        await callback.message.edit_text("No channels registered. Use /add_channel first.")
        await state.clear()
        await callback.answer()
        return
    kb = channels_list_keyboard(channels, "test_notif_channel")
    await callback.message.edit_text(
        "Select a *channel* to send the test to:", reply_markup=kb, parse_mode="Markdown"
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
        await callback.message.edit_text("❌ Streamer or channel not found.")
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
        await callback.message.edit_text(f"✅ Test notification sent to *{channel.title}*!", parse_mode="Markdown")
    else:
        await callback.message.edit_text(f"❌ Failed to send test notification.")
    await callback.answer()


# ── Manual poll ────────────────────────────────────────────────────────────────

@router.message(Command("poll_now"))
async def cmd_poll_now(message: Message, db_user: User) -> None:
    if not _admin_only(db_user):
        await message.answer("⛔ Admins only.")
        return
    await message.answer("🔍 Triggering manual poll for all active streamers...")
    async with get_session() as session:
        svc = StreamerService(session)
        streamers = await svc.list_streamers()

    results = []
    for streamer in streamers:
        if not streamer.is_active or streamer.is_paused or streamer.auto_disabled_at:
            continue
        res = await trigger_poll_for_streamer(streamer.id)
        live = [p for p, is_live in res.items() if is_live]
        status = f"🟢 LIVE: {', '.join(live)}" if live else "⚫ Offline"
        results.append(f"• *{streamer.display_name}*: {status}")

    text = "📊 *Poll results:*\n" + "\n".join(results) if results else "No active streamers."
    await message.answer(text, parse_mode="Markdown")


# ── Feature 11: Enhanced /health command ─────────────────────────────────────

@router.message(Command("health"))
async def cmd_health(message: Message, db_user: User) -> None:
    if not _admin_only(db_user):
        await message.answer("⛔ Admins only.")
        return
    from sqlalchemy import select
    from db.models import Platform, PollingState
    from bot.main import get_uptime_seconds
    from scheduler.polling import get_twitch_client

    async with get_session() as session:
        result = await session.execute(select(PollingState))
        states = {ps.platform: ps for ps in result.scalars().all()}
        svc = AnalyticsService(session)
        global_stats = await svc.get_global_stats()

    now = datetime.now(timezone.utc)
    lines = ["🏥 *System Health*\n"]

    # Feature 11: Bot uptime
    uptime_sec = get_uptime_seconds()
    if uptime_sec is not None:
        hours = int(uptime_sec // 3600)
        minutes = int((uptime_sec % 3600) // 60)
        lines.append(f"🤖 Bot uptime: {hours}h {minutes}m\n")

    # Platform poll states
    for platform in Platform:
        ps = states.get(platform)
        if ps:
            last = ps.last_poll_at
            if last:
                secs_ago = int((now - last).total_seconds())
                if secs_ago < 60:
                    ago = f"{secs_ago}s ago"
                else:
                    ago = f"{secs_ago // 60}m ago"
            else:
                ago = "never"
            rate_limited = ps.rate_limited_until and ps.rate_limited_until > now
            rl_str = f" ⚠️ Rate limited until {ps.rate_limited_until:%H:%M}" if rate_limited else ""
            yt_quota = (
                f" | Quota: {ps.youtube_quota_used}/{settings.YOUTUBE_DAILY_QUOTA_LIMIT}"
                if platform == Platform.YOUTUBE else ""
            )
            # Feature 11: Twitch token status
            twitch_token_str = ""
            if platform == Platform.TWITCH and ps.twitch_token_expires_at:
                remaining = (ps.twitch_token_expires_at - now).total_seconds()
                if remaining > 0:
                    twitch_token_str = f" | Token: {int(remaining // 3600)}h left"
                else:
                    twitch_token_str = " | Token: ⚠️ expired"
            lines.append(f"• *{platform.value.upper()}*: last poll {ago}{yt_quota}{twitch_token_str}{rl_str}")
        else:
            lines.append(f"• *{platform.value.upper()}*: no poll data")

    lines.append("")
    lines.append(f"📊 Streamers: {global_stats.active_streamers}/{global_stats.total_streamers} active")
    lines.append(f"📡 Streams last 7d: {global_stats.streams_last_7_days}")
    lines.append(f"📨 Total notifications: {global_stats.total_notifications}")

    # Webhook / polling mode
    mode = "Webhook" if settings.WEBHOOK_URL else "Long polling"
    lines.append(f"\n🔌 Mode: {mode}")

    await message.answer("\n".join(lines), parse_mode="Markdown")


# ── Feature 8: CSV export ─────────────────────────────────────────────────────

@router.message(Command("export"))
async def cmd_export(message: Message, db_user: User) -> None:
    """Feature 8: /export — download stream history as CSV.

    Usage: /export [days=30]
    Example: /export 7 — export last 7 days
    """
    if not _admin_only(db_user):
        await message.answer("⛔ Admins only.")
        return

    # Parse optional days argument
    args = message.text.split()
    try:
        days = int(args[1]) if len(args) > 1 else 30
        days = max(1, min(days, 365))
    except ValueError:
        days = 30

    await message.answer(f"📤 Generating CSV for last {days} days...")

    from datetime import timedelta
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    from db.models import Stream, Streamer, PlatformStream, StreamStatus

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    async with get_session() as session:
        result = await session.execute(
            select(Stream)
            .options(
                selectinload(Stream.streamer),
                selectinload(Stream.platform_streams),
            )
            .where(Stream.started_at >= cutoff)
            .order_by(Stream.started_at.desc())
        )
        streams = list(result.scalars().all())

    if not streams:
        await message.answer(f"No streams found in the last {days} days.")
        return

    # Build CSV in memory
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=[
        "stream_id", "streamer", "status", "started_at", "ended_at",
        "duration_min", "peak_viewers", "platforms", "notifications_sent",
    ])
    writer.writeheader()

    for s in streams:
        duration_min = None
        if s.started_at and s.ended_at:
            duration_min = round((s.ended_at - s.started_at).total_seconds() / 60, 1)
        platforms = ", ".join(sorted({ps.platform.value for ps in (s.platform_streams or [])}))
        writer.writerow({
            "stream_id": s.id,
            "streamer": s.streamer.display_name if s.streamer else "",
            "status": s.status.value,
            "started_at": s.started_at.strftime("%Y-%m-%d %H:%M:%S") if s.started_at else "",
            "ended_at": s.ended_at.strftime("%Y-%m-%d %H:%M:%S") if s.ended_at else "",
            "duration_min": duration_min or "",
            "peak_viewers": s.peak_viewer_count or "",
            "platforms": platforms,
            "notifications_sent": "",  # avoid extra query for now
        })

    csv_bytes = output.getvalue().encode("utf-8-sig")  # UTF-8 BOM for Excel
    filename = f"streams_{datetime.now(timezone.utc).strftime('%Y%m%d')}_last{days}d.csv"

    await message.answer_document(
        document=BufferedInputFile(csv_bytes, filename=filename),
        caption=f"📊 Stream history: {len(streams)} records, last {days} days",
    )


# ── Update API key ─────────────────────────────────────────────────────────────

@router.message(Command("update_api_key"))
async def cmd_update_api_key(message: Message, db_user: User, state: FSMContext) -> None:
    if not _admin_only(db_user):
        await message.answer("⛔ Admins only.")
        return
    await state.set_state(UpdateApiKeyStates.waiting_platform)
    kb = platforms_keyboard("apikey_platform")
    await message.answer(
        "🔑 *Update API Credentials*\n\nSelect platform:",
        reply_markup=kb,
        parse_mode="Markdown",
    )


@router.callback_query(F.data.startswith("apikey_platform:"), UpdateApiKeyStates.waiting_platform)
async def apikey_platform_selected(callback: CallbackQuery, state: FSMContext) -> None:
    platform_str = callback.data.split(":")[1]
    if platform_str == "done":
        await state.clear()
        await callback.message.edit_text("Cancelled.")
        return
    await state.update_data(platform=platform_str)
    await state.set_state(UpdateApiKeyStates.waiting_key_name)
    await callback.message.edit_text(
        f"Platform: *{platform_str.upper()}*\n\nEnter the key *name* (e.g. `api_key`, `client_secret`):",
        parse_mode="Markdown",
    )
    await callback.answer()


@router.message(UpdateApiKeyStates.waiting_key_name)
async def apikey_name_input(message: Message, state: FSMContext) -> None:
    await state.update_data(key_name=message.text.strip())
    await state.set_state(UpdateApiKeyStates.waiting_key_value)
    await message.answer("Enter the key *value* (will be stored encrypted):", parse_mode="Markdown")


@router.message(UpdateApiKeyStates.waiting_key_value)
async def apikey_value_input(message: Message, db_user: User, state: FSMContext) -> None:
    data = await state.get_data()
    await state.clear()

    # Delete the user's message to avoid key leaks
    try:
        await message.delete()
    except Exception:
        pass

    # FIX M-4: guard against empty ENCRYPTION_KEY before attempting Fernet
    if not settings.ENCRYPTION_KEY:
        await message.answer(
            "❌ *ENCRYPTION\\_KEY* is not configured in `.env`.\n"
            "Generate one and restart the bot before storing API credentials.",
            parse_mode="Markdown",
        )
        return

    from db.models import ApiCredential
    from cryptography.fernet import Fernet
    from sqlalchemy import select

    key_value = message.text.strip()
    platform = Platform(data["platform"])
    key_name = data["key_name"]

    fernet = Fernet(settings.ENCRYPTION_KEY.encode())
    encrypted = fernet.encrypt(key_value.encode()).decode()

    async with get_session() as session:
        result = await session.execute(
            select(ApiCredential).where(
                ApiCredential.platform == platform,
                ApiCredential.key_name == key_name,
            )
        )
        cred = result.scalar_one_or_none()
        if cred:
            cred.key_value = encrypted
            cred.updated_by = db_user.id
        else:
            cred = ApiCredential(
                platform=platform,
                key_name=key_name,
                key_value=encrypted,
                updated_by=db_user.id,
            )
            session.add(cred)

    await message.answer(
        f"✅ *{platform.value.upper()}* `{key_name}` updated securely.\n\n"
        f"Restart or trigger a poll for the new key to take effect.",
        parse_mode="Markdown",
    )


# ── Global stats ───────────────────────────────────────────────────────────────

@router.message(Command("stream_stats"))
async def cmd_stream_stats(message: Message, db_user: User) -> None:
    if not _admin_only(db_user):
        await message.answer("⛔ Admins only.")
        return
    async with get_session() as session:
        svc = AnalyticsService(session)
        stats = await svc.get_global_stats()

    lines = [
        "📊 *Global Stream Statistics*\n",
        f"Total streamers: {stats.total_streamers} ({stats.active_streamers} active)",
        f"Total streams: {stats.total_streams}",
        f"Streams last 7 days: {stats.streams_last_7_days}",
        f"Total notifications sent: {stats.total_notifications}",
        "",
        "🏆 *Top Streamers:*",
    ]
    for i, s in enumerate(stats.top_streamers, 1):
        lines.append(
            f"{i}. *{s.display_name}* — {s.total_streams} streams, "
            f"{s.total_hours_streamed}h, {s.total_notifications_sent} notifs"
        )

    await message.answer("\n".join(lines), parse_mode="Markdown")


# ── Cancel callback ────────────────────────────────────────────────────────────

@router.callback_query(F.data == "cancel")
async def cb_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text("❌ Cancelled.")
    await callback.answer()
