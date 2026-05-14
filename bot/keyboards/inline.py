"""Inline keyboard builders for all bot menus."""
from __future__ import annotations

from typing import List, Optional

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from services.template_service import PlatformLink

PLATFORM_EMOJI = {
    "youtube": "▶️",
    "twitch": "🎮",
    "vk": "📱",
    "YouTube": "▶️",
    "Twitch": "🎮",
    "Vk": "📱",
}


def stream_links_keyboard(platform_links: List[PlatformLink]) -> InlineKeyboardMarkup:
    """Keyboard for a stream notification — one button per live platform."""
    builder = InlineKeyboardBuilder()
    for link in platform_links:
        emoji = PLATFORM_EMOJI.get(link.platform, "🔗")
        builder.button(
            text=f"{emoji} Watch on {link.platform}",
            url=link.url,
        )
    builder.adjust(1)
    return builder.as_markup()


def streamers_list_keyboard(
    streamers: list,
    action_prefix: str,
    include_back: bool = False,
) -> InlineKeyboardMarkup:
    """Generic streamer list keyboard."""
    builder = InlineKeyboardBuilder()
    for streamer in streamers:
        status = ""
        if streamer.is_paused:
            status = " ⏸"
        elif streamer.auto_disabled_at:
            status = " ⛔"
        builder.button(
            text=f"{streamer.display_name}{status}",
            callback_data=f"{action_prefix}:{streamer.id}",
        )
    if include_back:
        builder.button(text="« Back", callback_data="back")
    builder.adjust(1)
    return builder.as_markup()


def channels_list_keyboard(channels: list, action_prefix: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for ch in channels:
        name = ch.username or ch.title
        builder.button(text=name, callback_data=f"{action_prefix}:{ch.id}")
    builder.adjust(1)
    return builder.as_markup()


def platforms_keyboard(action_prefix: str = "platform") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="▶️ YouTube", callback_data=f"{action_prefix}:youtube")
    builder.button(text="🎮 Twitch", callback_data=f"{action_prefix}:twitch")
    builder.button(text="📱 VK", callback_data=f"{action_prefix}:vk")
    builder.button(text="✅ Done", callback_data=f"{action_prefix}:done")
    builder.adjust(3, 1)
    return builder.as_markup()


def confirm_keyboard(confirm_data: str, cancel_data: str = "cancel") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Confirm", callback_data=confirm_data)
    builder.button(text="❌ Cancel", callback_data=cancel_data)
    builder.adjust(2)
    return builder.as_markup()


def streamer_actions_keyboard(streamer_id: int, is_paused: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if is_paused:
        builder.button(text="▶️ Resume", callback_data=f"streamer_resume:{streamer_id}")
    else:
        builder.button(text="⏸ Pause", callback_data=f"streamer_pause:{streamer_id}")
    builder.button(text="🧪 Test Notification", callback_data=f"streamer_test:{streamer_id}")
    builder.button(text="🔗 Manage Channels", callback_data=f"streamer_channels:{streamer_id}")
    builder.button(text="📊 Stats", callback_data=f"streamer_stats:{streamer_id}")
    builder.button(text="🗑 Delete", callback_data=f"streamer_delete:{streamer_id}")
    builder.adjust(2, 1, 1, 1)
    return builder.as_markup()


def back_keyboard(callback_data: str = "back") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="« Back", callback_data=callback_data)
    return builder.as_markup()


def skip_keyboard(callback_data: str = "skip") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Skip →", callback_data=callback_data)
    builder.button(text="❌ Cancel", callback_data="cancel")
    builder.adjust(2)
    return builder.as_markup()
