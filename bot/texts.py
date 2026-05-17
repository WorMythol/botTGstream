"""Все пользовательские тексты бота на русском языке.

Импортируй нужные константы в хендлерах:
    from bot.texts import T
"""

_SEP = "─" * 22   # визуальный разделитель секций


class T:
    # ── /start ────────────────────────────────────────────────────────────────
    START = (
        "👋 Привет, *{name}*!\n"
        + _SEP + "\n"
        "👤 Роль: *{role}*\n\n"
        "Введите /help, чтобы увидеть доступные команды."
    )

    # ── /help ─────────────────────────────────────────────────────────────────
    HELP_HEADER = "📖 *Доступные команды*\n" + _SEP + "\n"

    OWNER_COMMANDS = (
        "\n👑 *Владелец:*\n"
        "`/add_admin` — назначить администратора\n"
        "`/remove_admin` — снять администратора\n"
        "`/list_admins` — список администраторов\n"
    )

    ADMIN_COMMANDS = (
        "\n🛠 *Администратор:*\n"
        "`/add_streamer` — добавить стримера\n"
        "`/list_streamers` — список стримеров\n"
        "`/add_channel` — добавить канал\n"
        "`/list_channels` — список каналов\n"
        "`/assign_channel` — привязать стримера к каналу\n"
        "`/test_notification` — тестовое уведомление\n"
        "`/poll_now` — принудительная проверка стримов\n"
        "`/set_priority` — приоритет опроса\n"
        "`/update_api_key` — обновить API-ключи\n"
        "`/export [дней]` — экспорт истории в CSV\n"
        "`/stream_stats` — глобальная статистика\n"
        "`/health` — состояние системы\n"
    )

    ADMIN_EXTRA_COMMANDS = (
        "\n⚙️ *Управление:*\n"
        "`/maintenance [on|off|30m|2h]` — режим обслуживания\n"
    )

    STREAMER_COMMANDS = (
        "\n📡 *Стример:*\n"
        "`/my_streamers` — мои стримеры\n"
        "`/edit_template` — редактировать шаблон\n"
        "`/my_stats` — моя статистика\n"
        "`/stream_history` — история стримов\n"
        "\n🏆 *Рейтинги:*\n"
        "`/top` — топ-10 стримеров\n"
        "`/leaderboard [streams|hours|viewers|streak]` — рейтинг\n"
        "`/achievements [id]` — достижения\n"
    )

    CANCEL_NOTHING = "ℹ️ Нечего отменять — активных действий нет."
    CANCEL_OK = "❌ Действие отменено."

    # ── Права доступа ─────────────────────────────────────────────────────────
    NO_PERMISSION = "⛔ Недостаточно прав для этой команды."
    OWNER_ONLY   = "⛔ Только для владельца бота."
    ADMIN_ONLY   = "⛔ Только для администраторов."

    # ── Управление администраторами ───────────────────────────────────────────
    ADD_ADMIN_PROMPT = (
        "👤 *Добавление администратора*\n"
        + _SEP + "\n"
        "Введите *Telegram ID* пользователя.\n\n"
        "Пользователь должен был хотя бы раз запустить бота.\n"
        "Отмена — /cancel"
    )
    REMOVE_ADMIN_PROMPT = (
        "👥 *Текущие администраторы:*\n{list}\n\n"
        + _SEP + "\n"
        "Введите ID пользователя для удаления:"
    )
    LIST_ADMINS_EMPTY  = "ℹ️ Администраторы пока не назначены."
    LIST_ADMINS_HEADER = "👥 *Администраторы*\n" + _SEP + "\n"
    INVALID_USER_ID    = "❌ Некорректный ID. Введите число или /cancel."
    USER_NOT_FOUND     = (
        "❌ Пользователь `{uid}` не найден.\n"
        "Он должен сначала отправить /start боту."
    )
    ADMIN_ADDED   = "✅ *{name}* теперь является администратором."
    ADMIN_REMOVED = "✅ Роль *{name}* изменена обратно на «Стример»."

    # ── Стримеры ──────────────────────────────────────────────────────────────
    NO_STREAMERS_ASSIGNED = (
        "📭 У вас нет привязанных стримеров.\n"
        "Обратитесь к администратору."
    )
    NO_STREAMERS      = "📭 Стримеры не настроены."
    MY_STREAMERS_HEADER = "📡 *Мои стримеры*\n" + _SEP + "\n"

    # ── Добавление стримера (мастер) ──────────────────────────────────────────
    ADD_STREAMER_START = (
        "🆕 *Добавление стримера*  —  шаг 1 из 3\n"
        + _SEP + "\n"
        "Введите *отображаемое имя* стримера:\n\n"
        "_Например: Ninja, xQc, DrDisrespect_"
    )
    ADD_STREAMER_NAME_SHORT = "⚠️ Имя слишком короткое (минимум 2 символа). Попробуйте снова:"
    ADD_STREAMER_SELECT_PLATFORM = (
        "🆕 *Добавление стримера*  —  шаг 2 из 3\n"
        + _SEP + "\n"
        "✅ Имя: *{name}*\n\n"
        "Выберите платформу и добавьте ссылку.\n"
        "Когда все платформы добавлены — нажмите *Готово*:"
    )
    ADD_STREAMER_PLATFORM_NEED_ONE = "⚠️ Добавьте хотя бы одну платформу перед завершением."
    ADD_STREAMER_ENTER_URL = (
        "🔗 Введите URL канала *{platform}*:\n\n"
        "_Например: https://www.youtube.com/\\@channelname_"
    )
    ADD_STREAMER_URL_ADDED = (
        "✅ *{platform}* добавлен.\n\n"
        "📋 *Платформы:*\n{list}\n\n"
        "Добавьте ещё или нажмите *Готово*:"
    )
    ADD_STREAMER_DONE = (
        "🎉 *Стример создан!*\n"
        + _SEP + "\n"
        "👤 Имя: *{name}*\n"
        "🔗 Платформ добавлено: *{count}*\n\n"
        "Теперь привяжите его к каналу командой /assign\\_channel"
    )

    STREAMER_PAUSED  = "⏸ Стример поставлен на паузу."
    STREAMER_RESUMED = "▶️ Стример возобновлён."

    DELETE_STREAMER_CONFIRM = (
        "⚠️ *Удаление стримера*\n"
        + _SEP + "\n"
        "Это действие *необратимо*.\n"
        "Вся история стримов и уведомлений будет удалена.\n\n"
        "Вы уверены?"
    )
    STREAMER_DELETED       = "✅ Стример успешно удалён."
    STREAMER_DELETE_FAILED = "❌ Стример не найден."
    STREAMER_NOT_FOUND     = "❌ Стример не найден."

    PRIORITY_LABELS = {
        1: "🟢 Низкий (10м)",
        2: "🟡 Обычный (5м)",
        3: "🔴 Высокий (60с)",
    }
    SET_PRIORITY_HEADER = (
        "🎚 *Приоритет опроса*\n"
        + _SEP + "\n"
        "Выберите стримера:"
    )
    SET_PRIORITY_CURRENT = (
        "📡 *{name}*\n"
        + _SEP + "\n"
        "Текущий приоритет: {current}\n\n"
        "Выберите новый:"
    )
    SET_PRIORITY_DONE = "✅ Приоритет обновлён → *{label}*"

    # ── Каналы ────────────────────────────────────────────────────────────────
    ADD_CHANNEL_PROMPT = (
        "📢 *Добавление канала*  —  шаг 1 из 1\n"
        + _SEP + "\n"
        "Перешлите любое сообщение из канала,\n"
        "или введите `@username` / числовой ID.\n\n"
        "⚠️ Убедитесь, что бот является *администратором* в канале."
    )
    ADD_CHANNEL_NOT_FOUND = (
        "❌ Канал не найден.\n\n"
        "Проверьте ID или username и убедитесь, что бот добавлен как администратор."
    )
    ADD_CHANNEL_DONE    = "✅ Канал *{title}* (`{chat_id}`) {verb}!\n\nТеперь привяжите стримеров: /assign\\_channel"
    ADD_CHANNEL_ADDED   = "добавлен"
    ADD_CHANNEL_UPDATED = "обновлён"
    NO_CHANNELS          = "📭 Каналы не зарегистрированы. Используйте /add\\_channel."
    LIST_CHANNELS_HEADER = "📢 *Зарегистрированные каналы*\n" + _SEP + "\n"

    # ── Привязка канала ───────────────────────────────────────────────────────
    ASSIGN_CHANNEL_SELECT_STREAMER = (
        "🔗 *Привязка*  —  шаг 1 из 3\n"
        + _SEP + "\n"
        "Выберите *стримера*:"
    )
    ASSIGN_CHANNEL_SELECT_CHANNEL = (
        "🔗 *Привязка*  —  шаг 2 из 3\n"
        + _SEP + "\n"
        "Выберите *канал* для уведомлений:"
    )
    ASSIGN_CHANNEL_TEMPLATE_PROMPT = (
        "🔗 *Привязка*  —  шаг 3 из 3\n"
        + _SEP + "\n"
        "Введите *шаблон сообщения* (необязательно).\n\n"
        "Переменные: `{{ streamer_name }}`, `{{ stream_title }}`,\n"
        "`{{ viewer_count }}`, `{{ platform_links }}`\n\n"
        "Нажмите *Пропустить* для использования стандартного шаблона."
    )
    ASSIGN_CHANNEL_VIEWERS_PROMPT = (
        "👥 Введите *минимальное количество зрителей*\n"
        "для отправки уведомления.\n\n"
        "`0` — уведомлять всегда, без ограничений:"
    )
    ASSIGN_CHANNEL_DONE = (
        "✅ *Привязка создана!*\n"
        + _SEP + "\n"
        "👥 Мин. зрителей: `{viewers}`\n"
        "📝 Шаблон: {tmpl}\n"
        "🔔 Уведомление об окончании: включено"
    )
    ASSIGN_TEMPLATE_CUSTOM  = "Свой"
    ASSIGN_TEMPLATE_DEFAULT = "По умолчанию"
    ASSIGN_NO_CHANNELS  = "📭 Нет зарегистрированных каналов. Используйте /add\\_channel."
    ASSIGN_NO_STREAMERS = "📭 Стримеры не найдены. Сначала добавьте через /add\\_streamer."
    ASSIGN_TEMPLATE_INVALID = (
        "❌ Ошибка синтаксиса шаблона:\n`{err}`\n\nИсправьте и попробуйте снова:"
    )
    ASSIGN_TEMPLATE_PREVIEW = (
        "✅ *Шаблон корректен!*\n\n"
        "📋 *Предпросмотр:*\n"
        + _SEP + "\n"
        "{preview}\n"
        + _SEP + "\n\n"
        "👥 Введите *минимальное количество зрителей* (0 — без ограничений):"
    )
    ASSIGN_ENTER_NUMBER = "❌ Введите целое число:"

    # ── Тестовое уведомление ──────────────────────────────────────────────────
    TEST_NOTIF_SELECT_STREAMER = (
        "🧪 *Тестовое уведомление*\n"
        + _SEP + "\n"
        "Выберите стримера:"
    )
    TEST_NOTIF_SELECT_CHANNEL = (
        "🧪 *Тестовое уведомление*\n"
        + _SEP + "\n"
        "Выберите канал для отправки теста:"
    )
    TEST_NOTIF_NO_CHANNELS  = "📭 Нет зарегистрированных каналов. Используйте /add\\_channel."
    TEST_NOTIF_NOT_FOUND    = "❌ Стример или канал не найден."
    TEST_NOTIF_SUCCESS      = "✅ Тестовое уведомление отправлено в *{title}*!"
    TEST_NOTIF_FAILED       = "❌ Не удалось отправить тестовое уведомление."
    TEST_NOTIF_NO_STREAMERS = "📭 Стримеры не найдены."

    # ── Ручной опрос ──────────────────────────────────────────────────────────
    POLL_NOW_START          = "🔍 Запускаю ручную проверку активных стримеров…"
    POLL_NOW_RESULTS_HEADER = "📊 *Результаты проверки*\n" + _SEP + "\n"
    POLL_NOW_LIVE           = "🔴 LIVE: {platforms}"
    POLL_NOW_OFFLINE        = "⚫ офлайн"
    POLL_NOW_NO_STREAMERS   = "ℹ️ Нет активных стримеров для проверки."

    # ── /health ───────────────────────────────────────────────────────────────
    HEALTH_HEADER   = "🏥 *Состояние системы*\n" + _SEP + "\n"
    HEALTH_UPTIME   = "🤖 Аптайм: *{hours}ч {minutes}м*\n"
    HEALTH_NEVER    = "никогда"
    HEALTH_STREAMERS = "👤 Стримеров: *{active}* активных / {total} всего"
    HEALTH_STREAMS  = "📺 Стримов за 7 дней: *{count}*"
    HEALTH_NOTIFS   = "🔔 Уведомлений всего: *{count}*"
    HEALTH_MODE_WEBHOOK = "Webhook"
    HEALTH_MODE_POLLING = "Long polling"
    HEALTH_CONNECTION   = "\n🔌 Режим: *{mode}*"
    HEALTH_NO_DATA      = "нет данных"

    # ── Экспорт CSV ───────────────────────────────────────────────────────────
    EXPORT_GENERATING = "📤 Генерирую CSV за последние *{days}* дней…"
    EXPORT_NO_DATA    = "ℹ️ Нет стримов за последние {days} дней."
    EXPORT_CAPTION    = "📊 История стримов: {count} записей  ·  последние {days} дней"

    # ── API-ключи ─────────────────────────────────────────────────────────────
    UPDATE_API_KEY_HEADER   = (
        "🔑 *Обновление API-ключей*\n"
        + _SEP + "\n"
        "Выберите платформу:"
    )
    UPDATE_API_KEY_PLATFORM = (
        "🔑 *{platform}*\n"
        + _SEP + "\n"
        "Введите *название* ключа:\n"
        "_Например: `api_key`, `client_id`, `client_secret`_"
    )
    UPDATE_API_KEY_VALUE    = (
        "🔐 Введите *значение* ключа.\n\n"
        "Сообщение будет немедленно удалено, ключ сохранится в зашифрованном виде:"
    )
    UPDATE_API_KEY_DONE     = (
        "✅ *{platform}* — ключ `{key_name}` обновлён.\n\n"
        "Перезапустите бота или запустите /poll\\_now для применения."
    )
    UPDATE_API_KEY_NO_ENCRYPTION = (
        "❌ *ENCRYPTION\\_KEY* не настроен.\n"
        "Сгенерируйте ключ Fernet и добавьте в переменные окружения."
    )
    UPDATE_API_KEY_CANCELLED = "❌ Отменено."

    # ── Стример stats (admin) ─────────────────────────────────────────────────
    STREAMER_STATS_NOT_FOUND = "❌ Стример не найден."
    STREAMER_STATS = (
        "📊 *{name}*\n"
        + _SEP + "\n"
        "📺 Стримов: *{total}*\n"
        "⏱ Часов в эфире: *{hours}ч*\n"
        "🔔 Уведомлений: *{notifs}*\n"
        "👥 Пик зрителей: *{peak}*\n"
        "📅 Последний стрим: *{last}*\n"
        "🔗 Платформы: {platforms}"
    )
    STREAMER_CHANNELS_NONE   = (
        "📢 *{name}*\n"
        + _SEP + "\n"
        "Каналы не привязаны.\n\n"
        "Используйте /assign\\_channel"
    )
    STREAMER_CHANNELS_HEADER = "📢 *{name}* — каналы\n" + _SEP + "\n"
    BACK_TO_STREAMERS        = "📋 *Все стримеры*\n" + _SEP + "\nВыберите стримера для управления:"

    ALL_STREAMERS_HEADER   = "📋 *Все стримеры*\n" + _SEP + "\nНажмите на стримера для управления:"
    NO_STREAMERS_ADD_HINT  = "📭 Стримеры не добавлены. Используйте /add\\_streamer."

    # ── Глобальная статистика ─────────────────────────────────────────────────
    STREAM_STATS_HEADER = "📊 *Глобальная статистика*\n" + _SEP + "\n"
    STREAM_STATS_TOP    = "\n🏆 *Топ стримеров:*"

    GLOBAL_STATS_HEADER = "🌍 *Глобальная статистика*\n" + _SEP + "\n"
    GLOBAL_ACTIVE       = "🟢 Активных стримеров"
    GLOBAL_TOTAL        = "📺 Всего стримов"
    GLOBAL_WEEK         = "📅 Стримов за 7 дней"
    GLOBAL_TOP          = "\n🏆 *Топ стримеров по количеству стримов:*"

    # ── My stats ──────────────────────────────────────────────────────────────
    MY_STATS_HEADER  = "📊 *Статистика стримеров*\n" + _SEP + "\n"
    STATS_STREAMS    = "📺 Стримов"
    STATS_HOURS      = "⏱ Часов"
    STATS_NOTIFS     = "🔔 Уведомлений"
    STATS_PEAK       = "👥 Пик зрителей"
    STATS_LAST       = "📅 Последний стрим"
    STATS_PLATFORMS  = "🔗 Платформы"
    STATS_NEVER      = "никогда"
    STATS_NA         = "—"
    NO_STATS         = "ℹ️ Статистика пока недоступна."

    # ── История стримов ───────────────────────────────────────────────────────
    STREAM_HISTORY_HEADER = "📜 *История стримов*\n" + _SEP + "\n"
    NO_STREAM_HISTORY     = "ℹ️ История стримов пуста."

    # ── Редактирование шаблона ────────────────────────────────────────────────
    EDIT_TEMPLATE_SELECT_STREAMER = (
        "✏️ *Редактирование шаблона*  —  шаг 1 из 2\n"
        + _SEP + "\n"
        "Выберите стримера:"
    )
    EDIT_TEMPLATE_NO_ASSIGNMENTS = "ℹ️ У стримера нет привязанных каналов."
    EDIT_TEMPLATE_SELECT_CHANNEL = (
        "✏️ *Редактирование шаблона*  —  шаг 2 из 2\n"
        + _SEP + "\n"
        "Выберите канал:"
    )
    EDIT_TEMPLATE_PROMPT = (
        "✏️ *Новый шаблон уведомления*\n"
        + _SEP + "\n"
        "Доступные переменные:\n"
        "`{{{{ streamer_name }}}}` `{{{{ stream_title }}}}` `{{{{ viewer_count }}}}` `{{{{ platform_links }}}}`\n\n"
        "📋 *Стандартный шаблон:*\n```\n{default}\n```\n\n"
        "Введите свой шаблон или /cancel для отмены:"
    )
    EDIT_TEMPLATE_ERROR    = "❌ Ошибка шаблона: `{err}`\n\nИсправьте и попробуйте снова:"
    EDIT_TEMPLATE_SAVED    = "✅ Шаблон успешно сохранён!"
    EDIT_TEMPLATE_NOT_FOUND = "❌ Привязка не найдена."
    NOT_YOUR_STREAMER      = "⛔ Это не ваш стример."

    # ── Режим обслуживания ────────────────────────────────────────────────────
    MAINTENANCE_ACTIVE = (
        "🔧 *Технические работы*\n"
        + _SEP + "\n"
        "Бот временно недоступен.\n"
        "Пожалуйста, попробуйте позже."
    )
    MAINTENANCE_ACTIVE_CALLBACK = "🔧 Технические работы. Попробуйте позже."
    MAINTENANCE_DISABLED     = "✅ *Режим обслуживания:* отключён — бот работает."
    MAINTENANCE_ACTIVE_INDEF = (
        "🔧 *Режим обслуживания:* АКТИВЕН (бессрочно)\n\n"
        "Отключить: `/maintenance off`"
    )
    MAINTENANCE_ACTIVE_TIMED = (
        "🔧 *Режим обслуживания:* АКТИВЕН\n"
        "⏱ Завершится через ~{mins}м (`{until}`)\n\n"
        "Отключить досрочно: `/maintenance off`"
    )
    MAINTENANCE_EXPIRED    = "✅ *Режим обслуживания:* истёк — бот работает."
    MAINTENANCE_VALUE      = "🔧 *Режим обслуживания:* активен (значение: `{value}`)"
    MAINTENANCE_NO_PERMISSION = "⛔ У вас нет прав управлять режимом обслуживания."
    MAINTENANCE_OFF_DONE   = "✅ Режим обслуживания *отключён*. Бот работает."
    MAINTENANCE_ON_DONE    = (
        "🔧 Режим обслуживания *включён* бессрочно.\n\n"
        "Отключить: `/maintenance off`"
    )
    MAINTENANCE_TIMED_DONE = (
        "🔧 Режим обслуживания *включён* на *{label}*.\n"
        "⏱ До: `{until}`\n\n"
        "Отключить: `/maintenance off`"
    )
    MAINTENANCE_UNKNOWN_ARG = (
        "❓ Неизвестный аргумент.\n\n"
        "Использование: `/maintenance [on|off|30m|2h]`"
    )
    MAINTENANCE_MINUTES = "{n} минут{suffix}"
    MAINTENANCE_HOURS   = "{n} час{suffix}"

    # ── Рейтинги ──────────────────────────────────────────────────────────────
    LEADERBOARD_UNKNOWN_MODE = (
        "❓ Неизвестный режим `{mode}`.\n"
        "Доступные: `streams` `hours` `viewers` `streak`"
    )
    LEADERBOARD_EMPTY          = "📭 Данных пока нет. Начните стримить! 🎮"
    LEADERBOARD_TITLE_STREAMS  = "🏆 Топ-10 — Количество стримов"
    LEADERBOARD_TITLE_HOURS    = "⏱ Топ-10 — Часов в эфире"
    LEADERBOARD_TITLE_VIEWERS  = "👥 Топ-10 — Пик зрителей"
    LEADERBOARD_TITLE_STREAK   = "🔥 Топ-10 — Максимальная серия"
    LEADERBOARD_OTHER          = "📊 Другие рейтинги: {nav}"

    # ── Достижения ────────────────────────────────────────────────────────────
    ACHIEVEMENTS_NO_STREAMER = "📭 Нет привязанных стримеров. Обратитесь к администратору."
    ACHIEVEMENTS_INVALID_ID  = "❓ Использование: `/achievements [streamer_id]`"
    ACHIEVEMENTS_NONE = (
        "🏅 *{name}*\n"
        + _SEP + "\n"
        "Достижений пока нет.\n\n"
        "Продолжайте стримить, чтобы разблокировать их! 🎮"
    )
    ACHIEVEMENTS_HEADER  = "🏅 *Достижения — {name}*\n" + _SEP + "\n"
    ACHIEVEMENTS_STREAK  = "🔥 Текущая серия: *{current}д*  │  Макс: *{max}д*"
    ACHIEVEMENTS_LOCKED  = "\n🔒 *Заблокировано* ({count} шт.):"

    # ── Общее ─────────────────────────────────────────────────────────────────
    CANCELLED = "❌ Отменено."

    # ── Роли ──────────────────────────────────────────────────────────────────
    ROLE_NAMES = {
        "owner":   "Владелец",
        "admin":   "Администратор",
        "streamer": "Стример",
    }
