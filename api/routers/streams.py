"""Feature 4: REST endpoints for stream history and analytics."""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_db, verify_api_key
from services.analytics_service import AnalyticsService

router = APIRouter(prefix="/streams", tags=["Streams"], dependencies=[Depends(verify_api_key)])


class PlatformStreamOut(BaseModel):
    id: int
    platform: str
    title: Optional[str]
    url: str
    viewer_count: Optional[int]
    started_at: Optional[str]
    ended_at: Optional[str]

    model_config = {"from_attributes": True}


class StreamOut(BaseModel):
    id: int
    streamer_id: int
    status: str
    started_at: Optional[str]
    ended_at: Optional[str]
    peak_viewer_count: Optional[int]
    platform_streams: List[PlatformStreamOut] = []

    model_config = {"from_attributes": True}


class StreamerStatsOut(BaseModel):
    streamer_id: int
    display_name: str
    total_streams: int
    total_hours_streamed: float
    total_notifications_sent: int
    peak_viewers: Optional[int]
    last_stream_at: Optional[str]
    platforms: List[str]


@router.get("/history/{streamer_id}", response_model=List[StreamOut])
async def get_stream_history(
    streamer_id: int,
    limit: int = Query(default=20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """Return recent stream history for a streamer."""
    svc = AnalyticsService(db)
    streams = await svc.get_stream_history(streamer_id, limit=limit)
    result = []
    for s in streams:
        result.append(StreamOut(
            id=s.id,
            streamer_id=s.streamer_id,
            status=s.status.value,
            started_at=s.started_at.isoformat() if s.started_at else None,
            ended_at=s.ended_at.isoformat() if s.ended_at else None,
            peak_viewer_count=s.peak_viewer_count,
            platform_streams=[
                PlatformStreamOut(
                    id=ps.id,
                    platform=ps.platform.value,
                    title=ps.title,
                    url=ps.url,
                    viewer_count=ps.viewer_count,
                    started_at=ps.started_at.isoformat() if ps.started_at else None,
                    ended_at=ps.ended_at.isoformat() if ps.ended_at else None,
                )
                for ps in (s.platform_streams or [])
            ],
        ))
    return result


@router.get("/stats/{streamer_id}", response_model=StreamerStatsOut)
async def get_streamer_stats(streamer_id: int, db: AsyncSession = Depends(get_db)):
    """Return aggregate statistics for a streamer."""
    svc = AnalyticsService(db)
    stats = await svc.get_streamer_stats(streamer_id)
    if stats is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Streamer not found")
    return StreamerStatsOut(
        streamer_id=stats.streamer_id,
        display_name=stats.display_name,
        total_streams=stats.total_streams,
        total_hours_streamed=stats.total_hours_streamed,
        total_notifications_sent=stats.total_notifications_sent,
        peak_viewers=stats.peak_viewers,
        last_stream_at=stats.last_stream_at.isoformat() if stats.last_stream_at else None,
        platforms=stats.platforms,
    )
