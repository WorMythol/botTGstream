"""SQLAlchemy ORM models — platform-agnostic, shared by Telegram and future VK."""
from __future__ import annotations

import enum
from datetime import datetime
from typing import List, Optional

from sqlalchemy import (
    BigInteger, Boolean, DateTime, Enum, ForeignKey, Index, Integer,
    String, Text, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


# ─── Enums ────────────────────────────────────────────────────────────────────

class Platform(str, enum.Enum):
    YOUTUBE = "youtube"
    TWITCH = "twitch"
    VK = "vk"


class UserRole(str, enum.Enum):
    OWNER = "owner"
    ADMIN = "admin"
    STREAMER = "streamer"


class StreamStatus(str, enum.Enum):
    LIVE = "live"
    ENDED = "ended"
    UNKNOWN = "unknown"


class NotificationStatus(str, enum.Enum):
    PENDING = "pending"
    SENT = "sent"
    EDITED = "edited"
    DELETED = "deleted"
    FAILED = "failed"


class NotificationPlatform(str, enum.Enum):
    TELEGRAM = "telegram"
    VK = "vk"


# ─── Users ────────────────────────────────────────────────────────────────────

class User(Base):
    """Bot users with role-based access control."""
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)  # Telegram user ID
    username: Mapped[Optional[str]] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(255))
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), default=UserRole.STREAMER)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    created_by: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=True)

    streamers_managed: Mapped[List["StreamerUserAssignment"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


# ─── Streamers ────────────────────────────────────────────────────────────────

class Streamer(Base):
    """A streamer entity — platform-agnostic. Has platform accounts for each service."""
    __tablename__ = "streamers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_paused: Mapped[bool] = mapped_column(Boolean, default=False)

    # Feature 9: polling priority (1=low/10min, 2=normal/5min, 3=high/1min)
    poll_priority: Mapped[int] = mapped_column(Integer, default=2)

    # Error tracking for auto-disable
    consecutive_errors: Mapped[int] = mapped_column(Integer, default=0)
    max_consecutive_errors: Mapped[int] = mapped_column(Integer, default=5)
    auto_disabled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    auto_disabled_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    created_by: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=True)

    platform_accounts: Mapped[List["PlatformAccount"]] = relationship(
        back_populates="streamer", cascade="all, delete-orphan"
    )
    channel_assignments: Mapped[List["StreamerChannelAssignment"]] = relationship(
        back_populates="streamer", cascade="all, delete-orphan"
    )
    user_assignments: Mapped[List["StreamerUserAssignment"]] = relationship(
        back_populates="streamer", cascade="all, delete-orphan"
    )
    streams: Mapped[List["Stream"]] = relationship(
        back_populates="streamer", cascade="all, delete-orphan"  # FIX C-3: was missing cascade
    )


class PlatformAccount(Base):
    """Platform-specific identity for a streamer (YouTube channel, Twitch login, VK group)."""
    __tablename__ = "platform_accounts"
    __table_args__ = (
        UniqueConstraint("streamer_id", "platform", name="uq_streamer_platform"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    streamer_id: Mapped[int] = mapped_column(Integer, ForeignKey("streamers.id", ondelete="CASCADE"))
    platform: Mapped[Platform] = mapped_column(Enum(Platform))
    platform_id: Mapped[str] = mapped_column(String(255))      # channel/user/group ID
    platform_url: Mapped[str] = mapped_column(String(500))     # original URL supplied by admin
    platform_username: Mapped[Optional[str]] = mapped_column(String(255))  # resolved username

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_checked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    consecutive_errors: Mapped[int] = mapped_column(Integer, default=0)

    # Current live-status cache (avoids unnecessary notifications on restart)
    is_live: Mapped[bool] = mapped_column(Boolean, default=False)
    current_stream_platform_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    streamer: Mapped["Streamer"] = relationship(back_populates="platform_accounts")


# ─── Telegram Channels ────────────────────────────────────────────────────────

class TelegramChannel(Base):
    """Telegram channel or community that receives stream notifications."""
    __tablename__ = "telegram_channels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    title: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    added_by: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=True)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Feature 12: VK peer_id for cross-posting to VK (None = no VK delivery)
    vk_peer_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)

    assignments: Mapped[List["StreamerChannelAssignment"]] = relationship(back_populates="channel")


# ─── Assignments ──────────────────────────────────────────────────────────────

class StreamerChannelAssignment(Base):
    """Which streamer posts to which Telegram channel, with per-assignment template and settings."""
    __tablename__ = "streamer_channel_assignments"
    __table_args__ = (
        UniqueConstraint("streamer_id", "channel_id", name="uq_streamer_channel"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    streamer_id: Mapped[int] = mapped_column(Integer, ForeignKey("streamers.id", ondelete="CASCADE"))
    channel_id: Mapped[int] = mapped_column(Integer, ForeignKey("telegram_channels.id", ondelete="CASCADE"))

    # Per-assignment Jinja2 template (None → use default)
    message_template: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Feature: viewer threshold — don't notify if viewer count below this
    min_viewer_count: Mapped[int] = mapped_column(Integer, default=0)

    # Feature 1: send a "stream ended" notification when the session closes
    send_end_notification: Mapped[bool] = mapped_column(Boolean, default=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    streamer: Mapped["Streamer"] = relationship(back_populates="channel_assignments")
    channel: Mapped["TelegramChannel"] = relationship(back_populates="assignments")


class StreamerUserAssignment(Base):
    """Which bot users (streamer role) manage which streamers."""
    __tablename__ = "streamer_user_assignments"
    __table_args__ = (
        UniqueConstraint("streamer_id", "user_id", name="uq_streamer_user"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    streamer_id: Mapped[int] = mapped_column(Integer, ForeignKey("streamers.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    streamer: Mapped["Streamer"] = relationship(back_populates="user_assignments")
    user: Mapped["User"] = relationship(back_populates="streamers_managed")


# ─── Streams (broadcast sessions) ─────────────────────────────────────────────

class Stream(Base):
    """One broadcast session for a streamer — may span multiple platforms simultaneously."""
    __tablename__ = "streams"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    streamer_id: Mapped[int] = mapped_column(Integer, ForeignKey("streamers.id", ondelete="CASCADE"))  # FIX C-4
    status: Mapped[StreamStatus] = mapped_column(Enum(StreamStatus), default=StreamStatus.LIVE)

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    notification_sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Cooldown: re-use this session (not create new) if stream restarts within window
    cooldown_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Aggregate peak metrics
    peak_viewer_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    streamer: Mapped["Streamer"] = relationship(back_populates="streams")
    platform_streams: Mapped[List["PlatformStream"]] = relationship(
        back_populates="stream", cascade="all, delete-orphan"
    )
    notifications: Mapped[List["Notification"]] = relationship(
        back_populates="stream", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_streams_streamer_status", "streamer_id", "status"),
    )


class PlatformStream(Base):
    """Platform-specific stream data within a broadcast session."""
    __tablename__ = "platform_streams"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    stream_id: Mapped[int] = mapped_column(Integer, ForeignKey("streams.id", ondelete="CASCADE"))
    platform: Mapped[Platform] = mapped_column(Enum(Platform))
    platform_stream_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    title: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    url: Mapped[str] = mapped_column(String(500))
    viewer_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    thumbnail_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    stream: Mapped["Stream"] = relationship(back_populates="platform_streams")


# ─── Notifications ────────────────────────────────────────────────────────────

class Notification(Base):
    """Record of every notification message sent to a channel."""
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    stream_id: Mapped[int] = mapped_column(Integer, ForeignKey("streams.id", ondelete="CASCADE"))
    channel_id: Mapped[int] = mapped_column(Integer, ForeignKey("telegram_channels.id"))

    # The platform this notification was sent through
    delivery_platform: Mapped[NotificationPlatform] = mapped_column(
        Enum(NotificationPlatform), default=NotificationPlatform.TELEGRAM
    )

    # Message reference for editing/deletion
    telegram_message_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)

    status: Mapped[NotificationStatus] = mapped_column(Enum(NotificationStatus), default=NotificationStatus.PENDING)
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    edited_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Snapshot of rendered message text at send time
    rendered_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # FIX M-1: track whether message was sent as photo (caption) or plain text,
    # so the correct edit method can be chosen later.
    is_photo_message: Mapped[bool] = mapped_column(Boolean, default=False)

    # Telegram reactions (updated periodically if API supports)
    reactions: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    # Feature 2: retry support for failed deliveries
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    retry_after: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    stream: Mapped["Stream"] = relationship(back_populates="notifications")
    channel: Mapped["TelegramChannel"] = relationship()

    __table_args__ = (
        Index("ix_notifications_stream_channel", "stream_id", "channel_id"),
    )


# ─── API Credentials ──────────────────────────────────────────────────────────

class ApiCredential(Base):
    """Encrypted API credentials stored in DB. Updatable by admins via bot commands."""
    __tablename__ = "api_credentials"
    __table_args__ = (
        UniqueConstraint("platform", "key_name", name="uq_credential_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    platform: Mapped[Platform] = mapped_column(Enum(Platform))
    key_name: Mapped[str] = mapped_column(String(100))    # e.g. "api_key", "client_id"
    key_value: Mapped[str] = mapped_column(Text)          # Fernet-encrypted value
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    updated_by: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=True)


# ─── System Settings ──────────────────────────────────────────────────────────

class SystemSetting(Base):
    """Key-value store for runtime-configurable system settings."""
    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    updated_by: Mapped[Optional[int]] = mapped_column(BigInteger, ForeignKey("users.id"), nullable=True)


# ─── Polling State ────────────────────────────────────────────────────────────

class PollingState(Base):
    """Tracks per-platform polling metadata: quota usage, rate limit state."""
    __tablename__ = "polling_state"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    platform: Mapped[Platform] = mapped_column(Enum(Platform), unique=True)
    last_poll_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # YouTube-specific quota tracking
    youtube_quota_used: Mapped[int] = mapped_column(Integer, default=0)
    youtube_quota_reset_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Rate-limit backoff (any platform)
    rate_limited_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Twitch OAuth token cache
    twitch_access_token: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    twitch_token_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
