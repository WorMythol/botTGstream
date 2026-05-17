"""Async SQLAlchemy engine, session factory, and helpers."""
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config import settings
from db.models import Base

logger = structlog.get_logger(__name__)

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def init_db() -> None:
    """Create all tables on startup.

    If the environment variable DB_FORCE_RECREATE=true is set, all tables and
    custom enum types are dropped first (destructive — use only on fresh deploys).
    After recreation the variable is ignored on the next start — remove it from
    the hosting panel once the bot is up.
    """
    force_recreate = settings.DB_FORCE_RECREATE

    async with engine.begin() as conn:
        if force_recreate:
            logger.warning("database.force_recreate.start — dropping all tables and enum types")
            # Drop tables first (CASCADE handles FK order automatically)
            await conn.run_sync(Base.metadata.drop_all)
            # Also drop leftover custom enum types that SQLAlchemy may not track
            enum_types = [
                "userrole", "platform", "streamstatus",
                "notificationplatform", "notificationstatus", "achievementtype",
            ]
            for t in enum_types:
                await conn.execute(
                    __import__("sqlalchemy").text(f"DROP TYPE IF EXISTS {t} CASCADE")
                )
            logger.warning("database.force_recreate.dropped")

        await conn.run_sync(Base.metadata.create_all)

    logger.info("database.initialized", force_recreate=force_recreate)


async def close_db() -> None:
    """Dispose engine connection pool on shutdown."""
    await engine.dispose()
    logger.info("database.closed")


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Async context manager that yields a transactional session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_session_dependency() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI-compatible session dependency (for future REST layer)."""
    async with get_session() as session:
        yield session
