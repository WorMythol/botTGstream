"""Common handlers — /start, /help, /cancel."""
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from db.models import User, UserRole

router = Router()

OWNER_COMMANDS = """
👑 *Owner commands:*
`/add_admin` — Grant admin role to a user
`/remove_admin` — Revoke admin role
`/list_admins` — List all admins
"""

ADMIN_COMMANDS = """
🛠 *Admin commands:*
`/add_streamer` — Add a new streamer (wizard)
`/list_streamers` — List all streamers
`/pause_streamer` — Pause a streamer's notifications
`/resume_streamer` — Resume a paused streamer
`/add_channel` — Register a Telegram channel
`/list_channels` — List all registered channels
`/assign_channel` — Assign streamer → channel
`/test_notification` — Send test notification
`/poll_now` — Manually trigger stream check
`/update_api_key` — Update platform API credentials
`/health` — System health dashboard
`/manage_user` — Add or change user roles
`/stream_stats` — Global stream statistics
"""

STREAMER_COMMANDS = """
📊 *Your commands:*
`/my_streamers` — View your streamers
`/edit_template` — Edit a notification template
`/my_stats` — Your streamer statistics
`/stream_history` — Recent stream history

🎮 *Gamification:*
`/top` — Top-10 leaderboard (streams/hours/viewers/streak)
`/leaderboard [streams|hours|viewers|streak]` — Detailed leaderboard
`/achievements [id]` — Unlocked achievements & progress
"""

ADMIN_EXTRA_COMMANDS = """
⚙️ *Operational:*
`/maintenance [on|off|30m|2h]` — Toggle maintenance mode
"""


@router.message(Command("start"))
async def cmd_start(message: Message, db_user: User) -> None:
    role_label = db_user.role.value.capitalize()
    await message.answer(
        f"👋 Welcome, *{message.from_user.full_name}*!\n\n"
        f"Your role: *{role_label}*\n\n"
        f"Use /help to see available commands.",
        parse_mode="Markdown",
    )


@router.message(Command("help"))
async def cmd_help(message: Message, db_user: User) -> None:
    text = "📖 *Available commands:*\n"
    text += STREAMER_COMMANDS
    if db_user.role in (UserRole.ADMIN, UserRole.OWNER):
        text += ADMIN_COMMANDS
        text += ADMIN_EXTRA_COMMANDS
    if db_user.role == UserRole.OWNER:
        text += OWNER_COMMANDS
    await message.answer(text, parse_mode="Markdown")


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    current = await state.get_state()
    if current is None:
        await message.answer("Nothing to cancel.")
        return
    await state.clear()
    await message.answer("❌ Cancelled.")
