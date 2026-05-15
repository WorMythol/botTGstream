"""Leaderboard REST endpoints — public (no auth required)."""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_db
from services.gamification_service import GamificationService

router = APIRouter(prefix="/leaderboard", tags=["Leaderboard"])


class LeaderboardEntryOut(BaseModel):
    rank: int
    streamer_id: int
    display_name: str
    value: float
    extra: str


class LeaderboardResponse(BaseModel):
    mode: str
    entries: List[LeaderboardEntryOut]


@router.get("/streams", response_model=LeaderboardResponse)
async def leaderboard_streams(
    limit: int = Query(default=10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
):
    """Top streamers by total stream count."""
    svc = GamificationService(db)
    entries = await svc.leaderboard_by_streams(limit=limit)
    return LeaderboardResponse(
        mode="streams",
        entries=[LeaderboardEntryOut(**e.__dict__) for e in entries],
    )


@router.get("/hours", response_model=LeaderboardResponse)
async def leaderboard_hours(
    limit: int = Query(default=10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
):
    """Top streamers by total hours streamed."""
    svc = GamificationService(db)
    entries = await svc.leaderboard_by_hours(limit=limit)
    return LeaderboardResponse(
        mode="hours",
        entries=[LeaderboardEntryOut(**e.__dict__) for e in entries],
    )


@router.get("/viewers", response_model=LeaderboardResponse)
async def leaderboard_viewers(
    limit: int = Query(default=10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
):
    """Top streamers by all-time peak viewer count."""
    svc = GamificationService(db)
    entries = await svc.leaderboard_by_viewers(limit=limit)
    return LeaderboardResponse(
        mode="viewers",
        entries=[LeaderboardEntryOut(**e.__dict__) for e in entries],
    )


@router.get("/streak", response_model=LeaderboardResponse)
async def leaderboard_streak(
    limit: int = Query(default=10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
):
    """Top streamers by maximum consecutive-day streak."""
    svc = GamificationService(db)
    entries = await svc.leaderboard_by_streak(limit=limit)
    return LeaderboardResponse(
        mode="streak",
        entries=[LeaderboardEntryOut(**e.__dict__) for e in entries],
    )
