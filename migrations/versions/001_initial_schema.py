"""Initial schema

Revision ID: 001
Revises:
Create Date: 2026-05-15
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Users
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(255), nullable=True),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("role", sa.Enum("owner", "admin", "streamer", name="userrole"), nullable=False, server_default="streamer"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
    )

    # Streamers
    op.create_table(
        "streamers",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("is_paused", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("consecutive_errors", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_consecutive_errors", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("auto_disabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("auto_disabled_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("created_by", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=True),
    )

    # Platform accounts
    op.create_table(
        "platform_accounts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("streamer_id", sa.Integer(), sa.ForeignKey("streamers.id", ondelete="CASCADE")),
        sa.Column("platform", sa.Enum("youtube", "twitch", "vk", name="platform"), nullable=False),
        sa.Column("platform_id", sa.String(255), nullable=False),
        sa.Column("platform_url", sa.String(500), nullable=False),
        sa.Column("platform_username", sa.String(255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("consecutive_errors", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_live", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("current_stream_platform_id", sa.String(255), nullable=True),
        sa.UniqueConstraint("streamer_id", "platform", name="uq_streamer_platform"),
    )

    # Telegram channels
    op.create_table(
        "telegram_channels",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("telegram_id", sa.BigInteger(), unique=True, nullable=False),
        sa.Column("username", sa.String(255), nullable=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("added_by", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("added_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )

    # Streamer-channel assignments
    op.create_table(
        "streamer_channel_assignments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("streamer_id", sa.Integer(), sa.ForeignKey("streamers.id", ondelete="CASCADE")),
        sa.Column("channel_id", sa.Integer(), sa.ForeignKey("telegram_channels.id", ondelete="CASCADE")),
        sa.Column("message_template", sa.Text(), nullable=True),
        sa.Column("min_viewer_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("streamer_id", "channel_id", name="uq_streamer_channel"),
    )

    # Streamer-user assignments
    op.create_table(
        "streamer_user_assignments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("streamer_id", sa.Integer(), sa.ForeignKey("streamers.id", ondelete="CASCADE")),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="CASCADE")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("streamer_id", "user_id", name="uq_streamer_user"),
    )

    # Streams
    op.create_table(
        "streams",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("streamer_id", sa.Integer(), sa.ForeignKey("streamers.id"), nullable=False),
        sa.Column("status", sa.Enum("live", "ended", "unknown", name="streamstatus"), nullable=False, server_default="live"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notification_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cooldown_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("peak_viewer_count", sa.Integer(), nullable=True),
    )
    op.create_index("ix_streams_streamer_status", "streams", ["streamer_id", "status"])

    # Platform streams
    op.create_table(
        "platform_streams",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("stream_id", sa.Integer(), sa.ForeignKey("streams.id", ondelete="CASCADE")),
        sa.Column("platform", sa.Enum("youtube", "twitch", "vk", name="platform"), nullable=False),
        sa.Column("platform_stream_id", sa.String(255), nullable=True),
        sa.Column("title", sa.String(500), nullable=True),
        sa.Column("url", sa.String(500), nullable=False),
        sa.Column("viewer_count", sa.Integer(), nullable=True),
        sa.Column("thumbnail_url", sa.String(500), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
    )

    # Notifications
    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("stream_id", sa.Integer(), sa.ForeignKey("streams.id", ondelete="CASCADE")),
        sa.Column("channel_id", sa.Integer(), sa.ForeignKey("telegram_channels.id")),
        sa.Column("delivery_platform", sa.Enum("telegram", "vk", name="notificationplatform"), nullable=False, server_default="telegram"),
        sa.Column("telegram_message_id", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.Enum("pending", "sent", "edited", "deleted", "failed", name="notificationstatus"), nullable=False, server_default="pending"),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("rendered_text", sa.Text(), nullable=True),
        sa.Column("is_photo_message", sa.Boolean(), nullable=False, server_default="false"),  # FIX M-1
        sa.Column("reactions", postgresql.JSONB(), nullable=True),
    )
    op.create_index("ix_notifications_stream_channel", "notifications", ["stream_id", "channel_id"])

    # API credentials
    op.create_table(
        "api_credentials",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("platform", sa.Enum("youtube", "twitch", "vk", name="platform"), nullable=False),
        sa.Column("key_name", sa.String(100), nullable=False),
        sa.Column("key_value", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_by", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=True),
        sa.UniqueConstraint("platform", "key_name", name="uq_credential_key"),
    )

    # System settings
    op.create_table(
        "system_settings",
        sa.Column("key", sa.String(100), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_by", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=True),
    )

    # Polling state
    op.create_table(
        "polling_state",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("platform", sa.Enum("youtube", "twitch", "vk", name="platform"), unique=True),
        sa.Column("last_poll_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("youtube_quota_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("youtube_quota_reset_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rate_limited_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("twitch_access_token", sa.Text(), nullable=True),
        sa.Column("twitch_token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )


def downgrade() -> None:
    op.drop_table("polling_state")
    op.drop_table("system_settings")
    op.drop_table("api_credentials")
    op.drop_index("ix_notifications_stream_channel", "notifications")
    op.drop_table("notifications")
    op.drop_table("platform_streams")
    op.drop_index("ix_streams_streamer_status", "streams")
    op.drop_table("streams")
    op.drop_table("streamer_user_assignments")
    op.drop_table("streamer_channel_assignments")
    op.drop_table("telegram_channels")
    op.drop_table("platform_accounts")
    op.drop_table("streamers")
    op.drop_table("users")
    for enum_name in ("userrole", "platform", "streamstatus", "notificationplatform", "notificationstatus"):
        op.execute(f"DROP TYPE IF EXISTS {enum_name}")
