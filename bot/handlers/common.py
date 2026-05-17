"""Common handlers — /start, /help, /cancel."""
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from bot.texts import T
from db.models import User, UserRole

router = Router()


@router.message(Command("start"))
async def cmd_start(message: Message, db_user: User) -> None:
    role_label = T.ROLE_NAMES.get(db_user.role.value, db_user.role.value.capitalize())
    await message.answer(
        T.START.format(name=message.from_user.full_name, role=role_label),
        parse_mode="Markdown",
    )


@router.message(Command("help"))
async def cmd_help(message: Message, db_user: User) -> None:
    text = T.HELP_HEADER
    text += T.STREAMER_COMMANDS
    if db_user.role in (UserRole.ADMIN, UserRole.OWNER):
        text += T.ADMIN_COMMANDS
        text += T.ADMIN_EXTRA_COMMANDS
    if db_user.role == UserRole.OWNER:
        text += T.OWNER_COMMANDS
    await message.answer(text, parse_mode="Markdown")


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    current = await state.get_state()
    if current is None:
        await message.answer(T.CANCEL_NOTHING)
        return
    await state.clear()
    await message.answer(T.CANCEL_OK)
