"""Inline keyboard builders — все меню бота."""
from __future__ import annotations

from typing import List, Optional

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from services.template_service import PlatformLink

# ── Platform emojis ───────────────────────────────────────────────────────────

PLATFORM_EMOJI = {
    "youtube": "▶️",
    "twitch": "🎮",
    "vk": "💬",
    "YouTube": "▶️",
    "Twitch": "🎮",
    "Vk": "💬",
}


# ── Stream notification buttons ───────────────────────────────────────────────

def stream_links_keyboard(platform_links: List[PlatformLink]) -> InlineKeyboardMarkup:
    """Кнопки «Смотреть» в уведомлении о стриме."""
    builder = InlineKeyboardBuilder()
    if len(platform_links) == 1:
        link = platform_links[0]
        emoji = PLATFORM_EMOJI.get(link.platform, "🔗")
        builder.button(text=f"{emoji} Смотреть", url=link.url)
    else:
        for link in platform_links:
            emoji = PLATFORM_EMOJI.get(link.platform, "🔗")
            builder.button(text=f"{emoji} {link.platform}", url=link.url)
        builder.adjust(2)
    return builder.as_markup()


# ── Streamer list ─────────────────────────────────────────────────────────────

def streamers_list_keyboard(
    streamers: list,
    action_prefix: str,
    include_back: bool = False,
) -> InlineKeyboardMarkup:
    """Список стримеров с иконками статуса."""
    builder = InlineKeyboardBuilder()
    for s in streamers:
        if s.auto_disabled_at:
            icon = "⛔"
        elif s.is_paused:
            icon = "⏸"
        else:
            icon = "🟢"
        builder.button(
            text=f"{icon}  {s.display_name}",
            callback_data=f"{action_prefix}:{s.id}",
        )
    if include_back:
        builder.button(text="◀️  Назад", callback_data="back")
    builder.adjust(1)
    return builder.as_markup()


# ── Channel list ──────────────────────────────────────────────────────────────

def channels_list_keyboard(channels: list, action_prefix: str) -> InlineKeyboardMarkup:
    """Список каналов."""
    builder = InlineKeyboardBuilder()
    for ch in channels:
        name = ch.title or ch.username or str(ch.telegram_id)
        builder.button(text=f"📢  {name}", callback_data=f"{action_prefix}:{ch.id}")
    builder.adjust(1)
    return builder.as_markup()


# ── Platform selection ────────────────────────────────────────────────────────

def platforms_keyboard(action_prefix: str = "platform") -> InlineKeyboardMarkup:
    """Выбор платформы при добавлении стримера / API-ключей."""
    builder = InlineKeyboardBuilder()
    builder.button(text="▶️  YouTube", callback_data=f"{action_prefix}:youtube")
    builder.button(text="🎮  Twitch",  callback_data=f"{action_prefix}:twitch")
    builder.button(text="💬  VK",      callback_data=f"{action_prefix}:vk")
    builder.button(text="✅  Готово",  callback_data=f"{action_prefix}:done")
    builder.adjust(3, 1)
    return builder.as_markup()


# ── Confirm / Cancel ──────────────────────────────────────────────────────────

def confirm_keyboard(
    confirm_data: str,
    cancel_data: str = "cancel",
) -> InlineKeyboardMarkup:
    """Кнопки подтверждения опасного действия."""
    builder = InlineKeyboardBuilder()
    builder.button(text="✅  Да, удалить",  callback_data=confirm_data)
    builder.button(text="◀️  Отмена",       callback_data=cancel_data)
    builder.adjust(2)
    return builder.as_markup()


# ── Streamer action panel ─────────────────────────────────────────────────────

def streamer_actions_keyboard(
    streamer_id: int,
    is_paused: bool,
) -> InlineKeyboardMarkup:
    """Панель управления конкретным стримером."""
    builder = InlineKeyboardBuilder()

    # Row 1 — toggle + test
    if is_paused:
        builder.button(text="▶️  Возобновить", callback_data=f"streamer_resume:{streamer_id}")
    else:
        builder.button(text="⏸  Пауза",        callback_data=f"streamer_pause:{streamer_id}")
    builder.button(text="🧪  Тест",             callback_data=f"streamer_test:{streamer_id}")

    # Row 2 — info
    builder.button(text="📢  Каналы",           callback_data=f"streamer_channels:{streamer_id}")
    builder.button(text="📊  Статистика",       callback_data=f"streamer_stats:{streamer_id}")

    # Row 3 — danger zone
    builder.button(text="🗑  Удалить",          callback_data=f"streamer_delete:{streamer_id}")

    # Row 4 — navigation
    builder.button(text="◀️  К списку",         callback_data="back_to_streamers")

    builder.adjust(2, 2, 1, 1)
    return builder.as_markup()


# ── Navigation ────────────────────────────────────────────────────────────────

def back_keyboard(callback_data: str = "back") -> InlineKeyboardMarkup:
    """Одиночная кнопка «Назад»."""
    builder = InlineKeyboardBuilder()
    builder.button(text="◀️  К списку", callback_data=callback_data)
    return builder.as_markup()


def skip_keyboard(skip_data: str = "skip") -> InlineKeyboardMarkup:
    """Кнопки «Пропустить» + «Отмена» для опциональных шагов мастера."""
    builder = InlineKeyboardBuilder()
    builder.button(text="⏭  Пропустить", callback_data=skip_data)
    builder.button(text="❌  Отмена",     callback_data="cancel")
    builder.adjust(2)
    return builder.as_markup()


# ── Priority ──────────────────────────────────────────────────────────────────

def priority_keyboard(action_prefix: str = "priority") -> InlineKeyboardMarkup:
    """Выбор приоритета опроса стримера."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🔴  Высокий  — каждые 60с",  callback_data=f"{action_prefix}:3")
    builder.button(text="🟡  Обычный  — каждые 5м",   callback_data=f"{action_prefix}:2")
    builder.button(text="🟢  Низкий   — каждые 10м",  callback_data=f"{action_prefix}:1")
    builder.button(text="◀️  Отмена",                  callback_data="cancel")
    builder.adjust(1)
    return builder.as_markup()
