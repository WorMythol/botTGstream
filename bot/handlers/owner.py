"""Owner-only handlers: admin management."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.states import ManageUserStates
from bot.texts import T
from db.models import User, UserRole
from db.database import get_session
from db.repositories.user_repo import UserRepository
from services.user_service import UserService

router = Router()


def _owner_only(user: User) -> bool:
    return user.role == UserRole.OWNER


# ── Add admin ─────────────────────────────────────────────────────────────────

@router.message(Command("add_admin"))
async def cmd_add_admin(message: Message, db_user: User, state: FSMContext) -> None:
    if not _owner_only(db_user):
        await message.answer(T.OWNER_ONLY)
        return
    await state.set_state(ManageUserStates.waiting_user_id)
    await state.update_data(action="add_admin")
    await message.answer(T.ADD_ADMIN_PROMPT, parse_mode="Markdown")


@router.message(Command("remove_admin"))
async def cmd_remove_admin(message: Message, db_user: User, state: FSMContext) -> None:
    if not _owner_only(db_user):
        await message.answer(T.OWNER_ONLY)
        return
    async with get_session() as session:
        svc = UserService(session)
        admins = await svc.list_admins()
    if not admins:
        await message.answer(T.LIST_ADMINS_EMPTY)
        return
    lines = [f"• `{a.id}` — {a.full_name} (@{a.username or 'N/A'})" for a in admins]
    await state.set_state(ManageUserStates.waiting_user_id)
    await state.update_data(action="remove_admin")
    await message.answer(
        T.REMOVE_ADMIN_PROMPT.format(list="\n".join(lines)),
        parse_mode="Markdown",
    )


@router.message(Command("list_admins"))
async def cmd_list_admins(message: Message, db_user: User) -> None:
    if not _owner_only(db_user):
        await message.answer(T.OWNER_ONLY)
        return
    async with get_session() as session:
        svc = UserService(session)
        admins = await svc.list_admins()
    if not admins:
        await message.answer(T.LIST_ADMINS_EMPTY)
        return
    lines = [f"• `{a.id}` — {a.full_name} (@{a.username or 'N/A'})" for a in admins]
    await message.answer(T.LIST_ADMINS_HEADER + "\n".join(lines), parse_mode="Markdown")


# ── FSM handler for user ID input ─────────────────────────────────────────────

@router.message(ManageUserStates.waiting_user_id)
async def handle_user_id_input(message: Message, db_user: User, state: FSMContext) -> None:
    data = await state.get_data()
    action = data.get("action")
    try:
        target_id = int(message.text.strip())
    except ValueError:
        await message.answer(T.INVALID_USER_ID)
        return

    await state.clear()
    async with get_session() as session:
        svc = UserService(session)
        if action == "add_admin":
            user = await svc.set_role(target_id, UserRole.ADMIN)
            if user is None:
                await message.answer(
                    T.USER_NOT_FOUND.format(uid=target_id),
                    parse_mode="Markdown",
                )
            else:
                await message.answer(T.ADMIN_ADDED.format(name=user.full_name), parse_mode="Markdown")

        elif action == "remove_admin":
            user = await svc.set_role(target_id, UserRole.STREAMER)
            if user is None:
                await message.answer(T.USER_NOT_FOUND.format(uid=target_id), parse_mode="Markdown")
            else:
                await message.answer(T.ADMIN_REMOVED.format(name=user.full_name), parse_mode="Markdown")
