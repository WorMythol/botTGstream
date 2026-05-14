"""Central configuration loaded from environment variables."""
from pydantic_settings import BaseSettings
from pydantic import field_validator
from typing import Optional


class Settings(BaseSettings):
    # ── Telegram ──────────────────────────────────────────────────────────────
    BOT_TOKEN: str
    OWNER_TELEGRAM_ID: int

    # ── Database ──────────────────────────────────────────────────────────────
    DATABASE_URL: str  # postgresql+asyncpg://user:pass@host/dbname

    # ── YouTube ───────────────────────────────────────────────────────────────
    YOUTUBE_API_KEY: str = ""
    YOUTUBE_DAILY_QUOTA_LIMIT: int = 10_000
    YOUTUBE_QUOTA_WARNING_THRESHOLD: int = 8_000

    # ── Twitch ────────────────────────────────────────────────────────────────
    TWITCH_CLIENT_ID: str = ""
    TWITCH_CLIENT_SECRET: str = ""

    # ── VK ────────────────────────────────────────────────────────────────────
    VK_ACCESS_TOKEN: str = ""
    VK_API_VERSION: str = "5.199"

    # ── Polling intervals (seconds) ───────────────────────────────────────────
    POLL_INTERVAL_YOUTUBE: int = 300   # 5 min – quota-aware
    POLL_INTERVAL_TWITCH: int = 300    # 5 min
    POLL_INTERVAL_VK: int = 300        # 5 min

    # ── Reliability ───────────────────────────────────────────────────────────
    MAX_CONSECUTIVE_ERRORS: int = 5    # disable streamer after N errors
    STREAM_COOLDOWN_SECONDS: int = 1800  # 30 min before re-notification
    REQUEST_TIMEOUT: int = 15          # HTTP request timeout

    # ── Security ──────────────────────────────────────────────────────────────
    # 32-byte URL-safe base64 key; generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    ENCRYPTION_KEY: str = ""

    # ── Logging ───────────────────────────────────────────────────────────────
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "json"  # "json" or "text"

    @field_validator("DATABASE_URL")
    @classmethod
    def validate_db_url(cls, v: str) -> str:
        if not v.startswith("postgresql+asyncpg://"):
            raise ValueError("DATABASE_URL must use postgresql+asyncpg:// scheme")
        return v

    model_config = {"env_file": ".env", "case_sensitive": True}


settings = Settings()
