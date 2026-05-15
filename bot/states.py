"""FSM state groups for multi-step bot conversations."""
from aiogram.fsm.state import State, StatesGroup


class AddStreamerStates(StatesGroup):
    waiting_name = State()
    waiting_platform_choice = State()
    waiting_platform_url = State()


class AddChannelStates(StatesGroup):
    waiting_channel_id = State()


class AssignChannelStates(StatesGroup):
    waiting_streamer = State()
    waiting_channel = State()
    waiting_template = State()
    waiting_min_viewers = State()


class EditTemplateStates(StatesGroup):
    waiting_streamer = State()
    waiting_channel = State()
    waiting_template = State()


class UpdateApiKeyStates(StatesGroup):
    waiting_platform = State()
    waiting_key_name = State()
    waiting_key_value = State()


class ManageUserStates(StatesGroup):
    waiting_user_id = State()
    # waiting_role: reserved for future two-step role selection wizard


class TestNotificationStates(StatesGroup):
    waiting_streamer = State()
    waiting_channel = State()
