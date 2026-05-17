"""Все пользовательские тексты бота на русском языке.

Импортируй нужные константы в хендлерах:
    from bot.texts import T
"""


class T:
    # ── /start, /help, /cancel ────────────────────────────────────────────────
    START = (
        "👋 Привет, *{name}*!\n\n"
        "Ваша роль: *{role}*\n\n"
        "Используйте /help для просмотра доступных команд."
    )

    HELP_HEADER = "📖 *Доступные команды:*\n"

    OWNER_COMMANDS = """
👑 *Команды владельца:*
`/add_admin` — Назначить пользователя администратором
`/remove_admin` — Снять права администратора
`/list_admins` — Список всех администраторов
"""

    ADMIN_COMMANDS = """
🛠 *Команды администратора:*
`/add_streamer` — Добавить стримера (мастер)
`/list_streamers` — Список всех стримеров
`/add_channel` — Зарегистрировать Telegram-канал
`/list_channels` — Список зарегистрированных каналов
`/assign_channel` — Привязать стримера к каналу
`/test_notification` — Отправить тестовое уведомление
`/poll_now` — Принудительная проверка стримов
`/update_api_key` — Обновить API-ключи платформ
`/health` — Состояние системы
`/stream_stats` — Глобальная статистика
`/export [дней]` — Экспорт истории стримов в CSV
`/set_priority` — Приоритет опроса стримера
"""

    ADMIN_EXTRA_COMMANDS = """
⚙️ *Управление:*
`/maintenance [on|off|30m|2h]` — Режим обслуживания
"""

    STREAMER_COMMANDS = """
📊 *Ваши команды:*
`/my_streamers` — Ваши стримеры
`/edit_template` — Редактировать шаблон уведомления
`/my_stats` — Ваша статистика
`/stream_history` — История стримов

🎮 *Геймификация:*
`/top` — Топ-10 (стримы/часы/зрители/серия)
`/leaderboard [streams|hours|viewers|streak]` — Подробный рейтинг
`/achievements [id]` — Достижения и прогресс
"""

    CANCEL_NOTHING = "Нечего отменять."
    CANCEL_OK = "❌ Отменено."

    # ── Права доступа ─────────────────────────────────────────────────────────
    NO_PERMISSION = "⛔ У вас нет прав для этой команды."
    OWNER_ONLY = "⛔ Только для владельца."
    ADMIN_ONLY = "⛔ Только для администраторов."

    # ── Владелец: управление администраторами ─────────────────────────────────
    ADD_ADMIN_PROMPT = (
        "Введите *Telegram ID* пользователя, которого хотите сделать администратором.\n\n"
        "Пользователь должен был запустить бота (/start). Отмена — /cancel."
    )
    REMOVE_ADMIN_PROMPT = "Текущие администраторы:\n{list}\n\nВведите ID пользователя для удаления:"
    LIST_ADMINS_EMPTY = "Администраторы не назначены."
    LIST_ADMINS_HEADER = "👥 *Администраторы:*\n"
    INVALID_USER_ID = "❌ Неверный ID. Введите число или /cancel."
    USER_NOT_FOUND = "❌ Пользователь `{uid}` не найден. Он должен отправить /start боту."
    ADMIN_ADDED = "✅ *{name}* теперь администратор."
    ADMIN_REMOVED = "✅ Роль *{name}* изменена на Стример."

    # ── Стримеры ──────────────────────────────────────────────────────────────
    NO_STREAMERS_ASSIGNED = "У вас нет назначенных стримеров. Обратитесь к администратору."
    NO_STREAMERS = "Стримеры не настроены."
    MY_STREAMERS_HEADER = "📡 *Ваши стримеры:*\n\n"

    # ── Редактирование шаблона ────────────────────────────────────────────────
    EDIT_TEMPLATE_SELECT_STREAMER = "Выберите *стримера*:"
    EDIT_TEMPLATE_NO_ASSIGNMENTS = "У этого стримера нет привязанных каналов."
    EDIT_TEMPLATE_SELECT_CHANNEL = "Выберите *канал*:"
    EDIT_TEMPLATE_PROMPT = (
        "Введите *новый шаблон* уведомления. Доступные переменные:\n"
        "`{{{{ streamer_name }}}}` `{{{{ stream_title }}}}` `{{{{ viewer_count }}}}` `{{{{ platform_links }}}}`\n\n"
        "Шаблон по умолчанию:\n```\n{default}\n```\n\nОтправьте шаблон:"
    )
    EDIT_TEMPLATE_ERROR = "❌ Ошибка шаблона: {err}\n\nПопробуйте ещё раз:"
    EDIT_TEMPLATE_SAVED = "✅ Шаблон сохранён!"
    EDIT_TEMPLATE_NOT_FOUND = "❌ Привязка не найдена."
    NOT_YOUR_STREAMER = "⛔ Это не ваш стример."

    # ── История стримов ───────────────────────────────────────────────────────
    STREAM_HISTORY_HEADER = "📜 *История стримов:*\n"
    NO_STREAM_HISTORY = "Нет истории стримов."

    # ── Статистика ────────────────────────────────────────────────────────────
    MY_STATS_HEADER = "📊 *Статистика ваших стримеров:*\n"
    STATS_STREAMS = "Стримов"
    STATS_HOURS = "Часов"
    STATS_NOTIFS = "Уведомлений"
    STATS_PEAK = "Пик зрителей"
    STATS_LAST = "Последний стрим"
    STATS_PLATFORMS = "Платформы"
    STATS_NEVER = "Никогда"
    STATS_NA = "Н/Д"
    NO_STATS = "Нет статистики."

    GLOBAL_STATS_HEADER = "🌍 *Глобальная статистика*\n"
    GLOBAL_ACTIVE = "Активных стримеров"
    GLOBAL_TOTAL = "Всего стримов"
    GLOBAL_WEEK = "Стримов за неделю"
    GLOBAL_TOP = "🏆 *Топ стримеров по количеству стримов:*"

    # ── Управление стримерами (admin) ─────────────────────────────────────────
    ALL_STREAMERS_HEADER = "📋 *Все стримеры* — нажмите для управления:"
    NO_STREAMERS_ADD_HINT = "Стримеры не добавлены. Используйте /add_streamer."
    STREAMER_NOT_FOUND = "Стример не найден."

    ADD_STREAMER_START = "🆕 *Добавление стримера*\n\nВведите *отображаемое имя* стримера:"
    ADD_STREAMER_NAME_SHORT = "Имя слишком короткое. Попробуйте снова:"
    ADD_STREAMER_SELECT_PLATFORM = "✅ Имя: *{name}*\n\nТеперь добавьте каналы. Выберите платформу:"
    ADD_STREAMER_PLATFORM_NEED_ONE = "Сначала добавьте хотя бы одну платформу."
    ADD_STREAMER_DONE = (
        "✅ Стример *{name}* создан с {count} платформой(ами)!\n\n"
        "Используйте /assign\\_channel для привязки к каналу уведомлений."
    )
    ADD_STREAMER_ENTER_URL = "Введите URL канала *{platform}*:"
    ADD_STREAMER_URL_ADDED = "✅ Добавлен {platform} URL.\n\nПлатформы:\n{list}\n\nДобавьте ещё или нажмите Готово:"

    STREAMER_PAUSED = "⏸ Стример поставлен на паузу."
    STREAMER_RESUMED = "▶️ Стример возобновлён."

    DELETE_STREAMER_CONFIRM = (
        "⚠️ Вы уверены, что хотите *удалить* этого стримера?\n"
        "Вся история стримов и уведомлений также будет удалена."
    )
    STREAMER_DELETED = "✅ Стример удалён."
    STREAMER_DELETE_FAILED = "❌ Стример не найден."

    PRIORITY_LABELS = {1: "🟢 Низкий (10м)", 2: "🟡 Обычный (5м)", 3: "🔴 Высокий (60с)"}
    SET_PRIORITY_HEADER = "🎚 *Приоритет опроса*\n\nВыберите стримера:"
    SET_PRIORITY_CURRENT = "📡 *{name}*\nТекущий приоритет: {current}\n\nВыберите новый:"
    SET_PRIORITY_DONE = "✅ Приоритет опроса обновлён до *{label}*."

    # ── Каналы ────────────────────────────────────────────────────────────────
    ADD_CHANNEL_PROMPT = (
        "📢 *Добавление канала уведомлений*\n\n"
        "Перешлите любое сообщение из канала, или отправьте его `@username` / числовой ID.\n\n"
        "Убедитесь, что бот является *администратором* в этом канале."
    )
    ADD_CHANNEL_NOT_FOUND = (
        "❌ Канал не найден. Проверьте ID/username и убедитесь, что бот — администратор."
    )
    ADD_CHANNEL_DONE = "✅ Канал *{title}* (`{chat_id}`) {verb}!\n\nИспользуйте /assign\\_channel для привязки стримеров."
    ADD_CHANNEL_ADDED = "добавлен"
    ADD_CHANNEL_UPDATED = "обновлён"
    NO_CHANNELS = "Каналы не зарегистрированы. Используйте /add_channel."
    LIST_CHANNELS_HEADER = "📢 *Зарегистрированные каналы:*\n"

    # ── Привязка канала ───────────────────────────────────────────────────────
    ASSIGN_CHANNEL_SELECT_STREAMER = "Выберите *стримера* для привязки:"
    ASSIGN_CHANNEL_SELECT_CHANNEL = "Выберите *канал* для привязки:"
    ASSIGN_CHANNEL_TEMPLATE_PROMPT = (
        "Введите *шаблон сообщения* для этой пары стример/канал (необязательно).\n\n"
        "Переменные: `{{{{ streamer_name }}}}`, `{{{{ stream_title }}}}`, "
        "`{{{{ viewer_count }}}}`, `{{{{ platform_links }}}}`\n\n"
        "Нажмите *Пропустить* для использования шаблона по умолчанию."
    )
    ASSIGN_CHANNEL_VIEWERS_PROMPT = "Введите *минимальное количество зрителей* (0 — без ограничений):"
    ASSIGN_CHANNEL_DONE = (
        "✅ Привязка создана!\n"
        "Мин. зрителей: {viewers}\n"
        "Шаблон: {tmpl}\n"
        "Уведомление об окончании: ✅ включено"
    )
    ASSIGN_TEMPLATE_CUSTOM = "Свой"
    ASSIGN_TEMPLATE_DEFAULT = "По умолчанию"
    ASSIGN_NO_CHANNELS = "Нет зарегистрированных каналов. Используйте /add_channel."
    ASSIGN_NO_STREAMERS = "Стримеры не найдены. Сначала добавьте через /add_streamer."
    ASSIGN_TEMPLATE_INVALID = "❌ Ошибка синтаксиса шаблона: `{err}`\n\nИсправьте и попробуйте снова:"
    ASSIGN_TEMPLATE_PREVIEW = (
        "✅ Шаблон корректен! *Предпросмотр:*\n\n{preview}\n\n"
        "─────────────────────\n"
        "Введите *минимальное количество зрителей* (0 — без ограничений):"
    )
    ASSIGN_ENTER_NUMBER = "Введите число:"

    # ── Тестовое уведомление ──────────────────────────────────────────────────
    TEST_NOTIF_SELECT_STREAMER = "Выберите *стримера* для теста:"
    TEST_NOTIF_SELECT_CHANNEL = "Выберите *канал* для отправки теста:"
    TEST_NOTIF_NO_CHANNELS = "Нет зарегистрированных каналов. Используйте /add_channel."
    TEST_NOTIF_NOT_FOUND = "❌ Стример или канал не найден."
    TEST_NOTIF_SUCCESS = "✅ Тестовое уведомление отправлено в *{title}*!"
    TEST_NOTIF_FAILED = "❌ Не удалось отправить тестовое уведомление."
    TEST_NOTIF_NO_STREAMERS = "Стримеры не найдены."

    # ── Ручной опрос ──────────────────────────────────────────────────────────
    POLL_NOW_START = "🔍 Запускаю ручную проверку всех активных стримеров..."
    POLL_NOW_RESULTS_HEADER = "📊 *Результаты проверки:*\n"
    POLL_NOW_LIVE = "🟢 LIVE: {platforms}"
    POLL_NOW_OFFLINE = "⚫ Офлайн"
    POLL_NOW_NO_STREAMERS = "Нет активных стримеров."

    # ── Здоровье системы ─────────────────────────────────────────────────────
    HEALTH_HEADER = "🏥 *Состояние системы*\n"
    HEALTH_UPTIME = "🤖 Аптайм бота: {hours}ч {minutes}м\n"
    HEALTH_NEVER = "никогда"
    HEALTH_STREAMERS = "📊 Стримеров: {active}/{total} активных"
    HEALTH_STREAMS = "📡 Стримов за 7 дней: {count}"
    HEALTH_NOTIFS = "📨 Всего уведомлений: {count}"
    HEALTH_MODE_WEBHOOK = "Webhook"
    HEALTH_MODE_POLLING = "Лонг-поллинг"
    HEALTH_CONNECTION = "\n🔌 Режим: {mode}"
    HEALTH_NO_DATA = "нет данных"

    # ── Экспорт CSV ───────────────────────────────────────────────────────────
    EXPORT_GENERATING = "📤 Генерирую CSV за последние {days} дней..."
    EXPORT_NO_DATA = "Стримов за последние {days} дней не найдено."
    EXPORT_CAPTION = "📊 История стримов: {count} записей, последние {days} дней"

    # ── API-ключи ─────────────────────────────────────────────────────────────
    UPDATE_API_KEY_HEADER = "🔑 *Обновление API-ключей*\n\nВыберите платформу:"
    UPDATE_API_KEY_PLATFORM = "Платформа: *{platform}*\n\nВведите *название* ключа (например: `api_key`, `client_secret`):"
    UPDATE_API_KEY_VALUE = "Введите *значение* ключа (будет сохранено в зашифрованном виде):"
    UPDATE_API_KEY_DONE = "✅ *{platform}* `{key_name}` успешно обновлён.\n\nПерезапустите бота или запустите опрос для применения нового ключа."
    UPDATE_API_KEY_NO_ENCRYPTION = "❌ *ENCRYPTION\\_KEY* не настроен.\nСгенерируйте ключ и перезапустите бота."
    UPDATE_API_KEY_CANCELLED = "Отменено."

    # ── Стример stats (admin) ─────────────────────────────────────────────────
    STREAMER_STATS_NOT_FOUND = "Стример не найден."
    STREAMER_STATS = (
        "📊 *{name}* — Статистика\n\n"
        "Стримов: {total}\n"
        "Часов в эфире: {hours}ч\n"
        "Уведомлений отправлено: {notifs}\n"
        "Пик зрителей: {peak}\n"
        "Последний стрим: {last}\n"
        "Платформы: {platforms}"
    )
    STREAMER_CHANNELS_NONE = "📢 *{name}* — каналы не привязаны.\n\nИспользуйте /assign\\_channel."
    STREAMER_CHANNELS_HEADER = "📢 *{name}* — каналы:\n\n"
    BACK_TO_STREAMERS = "📋 *Все стримеры* — нажмите для управления:"

    # ── Глобальная статистика (admin) ─────────────────────────────────────────
    STREAM_STATS_HEADER = "📊 *Глобальная статистика*\n"
    STREAM_STATS_TOP = "🏆 *Топ стримеров:*"

    # ── Режим обслуживания ────────────────────────────────────────────────────
    MAINTENANCE_ACTIVE = (
        "🔧 *Бот на техническом обслуживании*\n\n"
        "Сервис временно недоступен. Пожалуйста, попробуйте позже."
    )
    MAINTENANCE_ACTIVE_CALLBACK = "🔧 Бот на обслуживании. Попробуйте позже."
    MAINTENANCE_DISABLED = "✅ *Режим обслуживания:* отключён — бот работает в штатном режиме."
    MAINTENANCE_ACTIVE_INDEF = "🔧 *Режим обслуживания:* АКТИВЕН (бессрочно)\n\nИспользуйте `/maintenance off` для отключения."
    MAINTENANCE_ACTIVE_TIMED = (
        "🔧 *Режим обслуживания:* АКТИВЕН\n"
        "⏱ Завершится через ~{mins}м (`{until}`)\n\n"
        "Используйте `/maintenance off` для досрочной отмены."
    )
    MAINTENANCE_EXPIRED = "✅ *Режим обслуживания:* истёк — бот работает в штатном режиме."
    MAINTENANCE_VALUE = "🔧 *Режим обслуживания:* активен (значение: `{value}`)"
    MAINTENANCE_NO_PERMISSION = "⛔ У вас нет прав для управления режимом обслуживания."
    MAINTENANCE_OFF_DONE = "✅ Режим обслуживания *отключён*. Бот работает."
    MAINTENANCE_ON_DONE = (
        "🔧 Режим обслуживания *включён* бессрочно.\n\n"
        "Используйте `/maintenance off` для отключения."
    )
    MAINTENANCE_TIMED_DONE = (
        "🔧 Режим обслуживания *включён* на *{label}*.\n\n"
        "⏱ До: `{until}`\n"
        "Используйте `/maintenance off` для досрочной отмены."
    )
    MAINTENANCE_UNKNOWN_ARG = "❓ Неизвестный аргумент.\n\nИспользование: `/maintenance [on|off|30m|2h]`"
    MAINTENANCE_MINUTES = "{n} минут{suffix}"
    MAINTENANCE_HOURS = "{n} час{suffix}"

    # ── Рейтинги (геймификация) ───────────────────────────────────────────────
    LEADERBOARD_UNKNOWN_MODE = (
        "❓ Неизвестный режим `{mode}`.\n"
        "Доступные: `streams` `hours` `viewers` `streak`"
    )
    LEADERBOARD_EMPTY = "Данных пока нет. Начните стримить, чтобы попасть в рейтинг! 🎮"
    LEADERBOARD_TITLE_STREAMS = "🏆 Топ стримеров — Количество стримов"
    LEADERBOARD_TITLE_HOURS = "⏱ Топ стримеров — Часов в эфире"
    LEADERBOARD_TITLE_VIEWERS = "👥 Топ стримеров — Пик зрителей"
    LEADERBOARD_TITLE_STREAK = "🔥 Топ стримеров — Макс. серия"
    LEADERBOARD_OTHER = "📊 Другие рейтинги: {nav}"

    # ── Достижения ────────────────────────────────────────────────────────────
    ACHIEVEMENTS_NO_STREAMER = "У вас нет привязанных стримеров. Обратитесь к администратору."
    ACHIEVEMENTS_INVALID_ID = "❓ Использование: `/achievements [streamer_id]`"
    ACHIEVEMENTS_NONE = (
        "🏅 *{name}* ещё не получил достижений.\n\n"
        "Продолжайте стримить, чтобы разблокировать их!"
    )
    ACHIEVEMENTS_HEADER = "🏅 *Достижения — {name}*\n"
    ACHIEVEMENTS_STREAK = "🔥 Текущая серия: *{current}д*  │  Макс: *{max}д*"
    ACHIEVEMENTS_LOCKED = "\n🔒 *Заблокировано* (осталось {count}):"

    # ── Общее ─────────────────────────────────────────────────────────────────
    CANCELLED = "❌ Отменено."

    # ── Роли ─────────────────────────────────────────────────────────────────
    ROLE_NAMES = {
        "owner": "Владелец",
        "admin": "Администратор",
        "streamer": "Стример",
    }
