-- ============================================================
-- StreamBot — полная схема БД
-- Запуск: psql -U user -d dbname -f create_tables.sql
-- ============================================================

-- Enum типы
CREATE TYPE userrole AS ENUM ('owner', 'admin', 'streamer');
CREATE TYPE platform AS ENUM ('youtube', 'twitch', 'vk');
CREATE TYPE streamstatus AS ENUM ('live', 'ended', 'unknown');
CREATE TYPE notificationplatform AS ENUM ('telegram', 'vk');
CREATE TYPE notificationstatus AS ENUM ('pending', 'sent', 'edited', 'deleted', 'failed');

-- ── Пользователи ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
    id              BIGINT PRIMARY KEY,          -- Telegram user ID
    username        VARCHAR(255),
    full_name       VARCHAR(255)    NOT NULL,
    role            userrole        NOT NULL DEFAULT 'streamer',
    is_active       BOOLEAN         NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    created_by      BIGINT          REFERENCES users(id)
);

-- ── Стримеры ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS streamers (
    id                      SERIAL PRIMARY KEY,
    display_name            VARCHAR(255)    NOT NULL,
    is_active               BOOLEAN         NOT NULL DEFAULT TRUE,
    is_paused               BOOLEAN         NOT NULL DEFAULT FALSE,
    poll_priority           INT             NOT NULL DEFAULT 2,   -- Feature 9: 1=low, 2=normal, 3=high
    consecutive_errors      INT             NOT NULL DEFAULT 0,
    max_consecutive_errors  INT             NOT NULL DEFAULT 5,
    auto_disabled_at        TIMESTAMPTZ,
    auto_disabled_reason    TEXT,
    created_at              TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    created_by              BIGINT          REFERENCES users(id)
);

-- ── Аккаунты на платформах ────────────────────────────────────
CREATE TABLE IF NOT EXISTS platform_accounts (
    id                          SERIAL PRIMARY KEY,
    streamer_id                 INT             NOT NULL REFERENCES streamers(id) ON DELETE CASCADE,
    platform                    platform        NOT NULL,
    platform_id                 VARCHAR(255)    NOT NULL,
    platform_url                VARCHAR(500)    NOT NULL,
    platform_username           VARCHAR(255),
    is_active                   BOOLEAN         NOT NULL DEFAULT TRUE,
    last_checked_at             TIMESTAMPTZ,
    last_error                  TEXT,
    consecutive_errors          INT             NOT NULL DEFAULT 0,
    is_live                     BOOLEAN         NOT NULL DEFAULT FALSE,
    current_stream_platform_id  VARCHAR(255),
    CONSTRAINT uq_streamer_platform UNIQUE (streamer_id, platform)
);

-- ── Telegram-каналы ───────────────────────────────────────────
CREATE TABLE IF NOT EXISTS telegram_channels (
    id          SERIAL PRIMARY KEY,
    telegram_id BIGINT          NOT NULL UNIQUE,
    username    VARCHAR(255),
    title       VARCHAR(255)    NOT NULL,
    is_active   BOOLEAN         NOT NULL DEFAULT TRUE,
    added_by    BIGINT          REFERENCES users(id),
    added_at    TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    vk_peer_id  BIGINT                                  -- Feature 12: VK peer ID for cross-posting
);

-- ── Привязка стример → канал ──────────────────────────────────
CREATE TABLE IF NOT EXISTS streamer_channel_assignments (
    id                      SERIAL PRIMARY KEY,
    streamer_id             INT     NOT NULL REFERENCES streamers(id) ON DELETE CASCADE,
    channel_id              INT     NOT NULL REFERENCES telegram_channels(id) ON DELETE CASCADE,
    message_template        TEXT,
    min_viewer_count        INT     NOT NULL DEFAULT 0,
    send_end_notification   BOOLEAN NOT NULL DEFAULT TRUE,    -- Feature 1
    is_active               BOOLEAN NOT NULL DEFAULT TRUE,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_streamer_channel UNIQUE (streamer_id, channel_id)
);

-- ── Привязка стример → пользователь бота ─────────────────────
CREATE TABLE IF NOT EXISTS streamer_user_assignments (
    id          SERIAL PRIMARY KEY,
    streamer_id INT     NOT NULL REFERENCES streamers(id) ON DELETE CASCADE,
    user_id     BIGINT  NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_streamer_user UNIQUE (streamer_id, user_id)
);

-- ── Стримы (сессии вещания) ───────────────────────────────────
CREATE TABLE IF NOT EXISTS streams (
    id                      SERIAL PRIMARY KEY,
    streamer_id             INT         NOT NULL REFERENCES streamers(id) ON DELETE CASCADE,
    status                  streamstatus NOT NULL DEFAULT 'live',
    started_at              TIMESTAMPTZ NOT NULL,
    ended_at                TIMESTAMPTZ,
    notification_sent_at    TIMESTAMPTZ,
    cooldown_until          TIMESTAMPTZ,
    peak_viewer_count       INT
);

CREATE INDEX IF NOT EXISTS ix_streams_streamer_status ON streams(streamer_id, status);

-- ── Данные стрима по платформе ────────────────────────────────
CREATE TABLE IF NOT EXISTS platform_streams (
    id                  SERIAL PRIMARY KEY,
    stream_id           INT         NOT NULL REFERENCES streams(id) ON DELETE CASCADE,
    platform            platform    NOT NULL,
    platform_stream_id  VARCHAR(255),
    title               VARCHAR(500),
    url                 VARCHAR(500) NOT NULL,
    viewer_count        INT,
    thumbnail_url       VARCHAR(500),
    started_at          TIMESTAMPTZ,
    ended_at            TIMESTAMPTZ
);

-- ── Уведомления ───────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS notifications (
    id                  SERIAL PRIMARY KEY,
    stream_id           INT                 NOT NULL REFERENCES streams(id) ON DELETE CASCADE,
    channel_id          INT                 NOT NULL REFERENCES telegram_channels(id),
    delivery_platform   notificationplatform NOT NULL DEFAULT 'telegram',
    telegram_message_id BIGINT,
    status              notificationstatus  NOT NULL DEFAULT 'pending',
    sent_at             TIMESTAMPTZ,
    edited_at           TIMESTAMPTZ,
    error_message       TEXT,
    rendered_text       TEXT,
    is_photo_message    BOOLEAN     NOT NULL DEFAULT FALSE,
    reactions           JSONB,
    retry_count         INT         NOT NULL DEFAULT 0,    -- Feature 2
    retry_after         TIMESTAMPTZ                        -- Feature 2: next retry timestamp
);

CREATE INDEX IF NOT EXISTS ix_notifications_stream_channel ON notifications(stream_id, channel_id);
CREATE INDEX IF NOT EXISTS ix_notifications_retry ON notifications(status, retry_after)
    WHERE status = 'failed' AND retry_after IS NOT NULL;  -- Feature 2: fast retry lookup

-- ── API-ключи (зашифрованные) ─────────────────────────────────
CREATE TABLE IF NOT EXISTS api_credentials (
    id          SERIAL PRIMARY KEY,
    platform    platform        NOT NULL,
    key_name    VARCHAR(100)    NOT NULL,
    key_value   TEXT            NOT NULL,
    expires_at  TIMESTAMPTZ,
    is_active   BOOLEAN         NOT NULL DEFAULT TRUE,
    updated_at  TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_by  BIGINT          REFERENCES users(id),
    CONSTRAINT uq_credential_key UNIQUE (platform, key_name)
);

-- ── Системные настройки ───────────────────────────────────────
CREATE TABLE IF NOT EXISTS system_settings (
    key         VARCHAR(100)    PRIMARY KEY,
    value       TEXT            NOT NULL,
    updated_at  TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_by  BIGINT          REFERENCES users(id)
);

-- ── Состояние поллинга ────────────────────────────────────────
CREATE TABLE IF NOT EXISTS polling_state (
    id                      SERIAL PRIMARY KEY,
    platform                platform    NOT NULL UNIQUE,
    last_poll_at            TIMESTAMPTZ,
    youtube_quota_used      INT         NOT NULL DEFAULT 0,
    youtube_quota_reset_at  TIMESTAMPTZ,
    rate_limited_until      TIMESTAMPTZ,
    twitch_access_token     TEXT,
    twitch_token_expires_at TIMESTAMPTZ,
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================
-- Инициализация: строки поллинга для каждой платформы
-- ============================================================
INSERT INTO polling_state (platform) VALUES ('youtube') ON CONFLICT DO NOTHING;
INSERT INTO polling_state (platform) VALUES ('twitch')  ON CONFLICT DO NOTHING;
INSERT INTO polling_state (platform) VALUES ('vk')      ON CONFLICT DO NOTHING;

-- ============================================================
-- Миграция: добавить новые колонки в существующую БД
-- (выполнить только если таблицы уже существуют)
-- ============================================================
-- ALTER TABLE streamers ADD COLUMN IF NOT EXISTS poll_priority INT NOT NULL DEFAULT 2;
-- ALTER TABLE telegram_channels ADD COLUMN IF NOT EXISTS vk_peer_id BIGINT;
-- ALTER TABLE streamer_channel_assignments ADD COLUMN IF NOT EXISTS send_end_notification BOOLEAN NOT NULL DEFAULT TRUE;
-- ALTER TABLE notifications ADD COLUMN IF NOT EXISTS retry_count INT NOT NULL DEFAULT 0;
-- ALTER TABLE notifications ADD COLUMN IF NOT EXISTS retry_after TIMESTAMPTZ;
-- CREATE INDEX IF NOT EXISTS ix_notifications_retry ON notifications(status, retry_after) WHERE status = 'failed' AND retry_after IS NOT NULL;
