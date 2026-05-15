"""Shared FastAPI dependencies."""
from __future__ import annotations

from typing import AsyncGenerator

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from db.database import get_session as _get_session


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: yields an async DB session."""
    async with _get_session() as session:
        yield session


async def verify_api_key(x_api_key: str = Header(...)) -> None:
    """Simple API key auth — set API_SECRET_KEY in .env for REST access."""
    secret = getattr(settings, "API_SECRET_KEY", "")
    if not secret or x_api_key != secret:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-Api-Key header",
        )
