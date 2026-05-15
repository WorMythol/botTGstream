"""Feature 4: REST health endpoint — no auth required."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_db
from bot.main import get_uptime_seconds
from config import settings
from db.models import Platform, PollingState

router = APIRouter(prefix="/health", tags=["Health"])


class PlatformHealth(BaseModel):
    platform: str
    last_poll_at: Optional[str] = None
    youtube_quota_used: Optional[int] = None
    youtube_quota_limit: Optional[int] = None
    rate_limited: bool = False
    twitch_token_valid: Optional[bool] = None


class HealthResponse(BaseModel):
    status: str
    uptime_seconds: Optional[float]
    mode: str
    platforms: List[PlatformHealth]


@router.get("/", response_model=HealthResponse)
async def health_check(db: AsyncSession = Depends(get_db)):
    """System health status — usable by monitoring tools without authentication."""
    result = await db.execute(select(PollingState))
    states = {ps.platform: ps for ps in result.scalars().all()}

    now = datetime.now(timezone.utc)
    platforms = []
    for platform in Platform:
        ps = states.get(platform)
        if ps:
            rate_limited = bool(ps.rate_limited_until and ps.rate_limited_until > now)
            twitch_valid = None
            if platform == Platform.TWITCH and ps.twitch_token_expires_at:
                twitch_valid = ps.twitch_token_expires_at > now
            platforms.append(PlatformHealth(
                platform=platform.value,
                last_poll_at=ps.last_poll_at.isoformat() if ps.last_poll_at else None,
                youtube_quota_used=ps.youtube_quota_used if platform == Platform.YOUTUBE else None,
                youtube_quota_limit=settings.YOUTUBE_DAILY_QUOTA_LIMIT if platform == Platform.YOUTUBE else None,
                rate_limited=rate_limited,
                twitch_token_valid=twitch_valid,
            ))
        else:
            platforms.append(PlatformHealth(platform=platform.value))

    return HealthResponse(
        status="ok",
        uptime_seconds=get_uptime_seconds(),
        mode="webhook" if settings.WEBHOOK_URL else "polling",
        platforms=platforms,
    )
