"""Telegram Mini App API endpoints — no auth required (public data only).

These endpoints back the Mini App SPA:
  GET /miniapp/live          — currently live streams
  GET /miniapp/leaderboard   — all four leaderboards in one call
  GET /miniapp/achievements/{streamer_id}  — streamer achievements
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from api.dependencies import get_db
from db.models import Stream, StreamStatus, Streamer
from services.gamification_service import ACHIEVEMENT_META, GamificationService

router = APIRouter(prefix="/miniapp", tags=["Mini App"])


# ── Response models ────────────────────────────────────────────────────────────

class LivePlatformOut(BaseModel):
    platform: str
    title: Optional[str]
    url: str
    viewer_count: Optional[int]
    thumbnail_url: Optional[str]


class LiveStreamOut(BaseModel):
    streamer_id: int
    streamer_name: str
    started_at: datetime
    platforms: List[LivePlatformOut]
    total_viewers: int


class LeaderboardRow(BaseModel):
    rank: int
    streamer_id: int
    display_name: str
    value: float
    extra: str


class AllLeaderboards(BaseModel):
    streams: List[LeaderboardRow]
    hours: List[LeaderboardRow]
    viewers: List[LeaderboardRow]
    streak: List[LeaderboardRow]


class AchievementRow(BaseModel):
    type: str
    emoji: str
    name: str
    desc: str
    earned_at: datetime
    locked: bool


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/live", response_model=List[LiveStreamOut])
async def get_live_streams(db: AsyncSession = Depends(get_db)):
    """Return all currently live streams with platform details."""
    result = await db.execute(
        select(Stream)
        .options(
            selectinload(Stream.platform_streams),
            selectinload(Stream.streamer),
        )
        .where(Stream.status == StreamStatus.LIVE)
    )
    streams = list(result.scalars().all())

    out = []
    for stream in streams:
        active_ps = [ps for ps in stream.platform_streams if ps.ended_at is None]
        total_viewers = sum(ps.viewer_count or 0 for ps in active_ps)
        out.append(LiveStreamOut(
            streamer_id=stream.streamer_id,
            streamer_name=stream.streamer.display_name if stream.streamer else f"#{stream.streamer_id}",
            started_at=stream.started_at,
            platforms=[
                LivePlatformOut(
                    platform=ps.platform.value,
                    title=ps.title,
                    url=ps.url,
                    viewer_count=ps.viewer_count,
                    thumbnail_url=ps.thumbnail_url,
                )
                for ps in active_ps
            ],
            total_viewers=total_viewers,
        ))

    # Sort by total viewers descending
    out.sort(key=lambda s: s.total_viewers, reverse=True)
    return out


@router.get("/leaderboard", response_model=AllLeaderboards)
async def get_leaderboard(db: AsyncSession = Depends(get_db)):
    """Return all four leaderboards (top-10 each) in a single call."""
    svc = GamificationService(db)
    streams_lb, hours_lb, viewers_lb, streak_lb = (
        await svc.leaderboard_by_streams(limit=10),
        await svc.leaderboard_by_hours(limit=10),
        await svc.leaderboard_by_viewers(limit=10),
        await svc.leaderboard_by_streak(limit=10),
    )

    def to_rows(entries):
        return [LeaderboardRow(**e.__dict__) for e in entries]

    return AllLeaderboards(
        streams=to_rows(streams_lb),
        hours=to_rows(hours_lb),
        viewers=to_rows(viewers_lb),
        streak=to_rows(streak_lb),
    )


@router.get("/achievements/{streamer_id}", response_model=List[AchievementRow])
async def get_achievements(streamer_id: int, db: AsyncSession = Depends(get_db)):
    """Return achievements for a streamer — includes locked achievements."""
    from db.models import AchievementType
    streamer = await db.get(Streamer, streamer_id)
    if streamer is None:
        raise HTTPException(status_code=404, detail="Streamer not found")

    svc = GamificationService(db)
    earned = await svc.get_achievements(streamer_id)
    earned_types = {a.achievement_type for a in earned}

    rows: List[AchievementRow] = []

    # Earned first
    for a in earned:
        meta = ACHIEVEMENT_META.get(a.achievement_type, {})
        rows.append(AchievementRow(
            type=a.achievement_type.value,
            emoji=meta.get("emoji", "🏅"),
            name=meta.get("name", a.achievement_type.value),
            desc=meta.get("desc", ""),
            earned_at=a.earned_at,
            locked=False,
        ))

    # Locked (use a placeholder earned_at)
    from datetime import timezone
    placeholder = datetime(1970, 1, 1, tzinfo=timezone.utc)
    for t in AchievementType:
        if t not in earned_types:
            meta = ACHIEVEMENT_META.get(t, {})
            rows.append(AchievementRow(
                type=t.value,
                emoji=meta.get("emoji", "🔒"),
                name=meta.get("name", t.value),
                desc=meta.get("desc", ""),
                earned_at=placeholder,
                locked=True,
            ))

    return rows
