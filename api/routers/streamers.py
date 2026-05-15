"""Feature 4: REST endpoints for streamer management."""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_db, verify_api_key
from services.streamer_service import StreamerService

router = APIRouter(prefix="/streamers", tags=["Streamers"], dependencies=[Depends(verify_api_key)])


# ── Schemas ────────────────────────────────────────────────────────────────────

class PlatformAccountOut(BaseModel):
    id: int
    platform: str
    platform_id: str
    platform_url: str
    is_active: bool
    is_live: bool

    model_config = {"from_attributes": True}


class StreamerOut(BaseModel):
    id: int
    display_name: str
    is_active: bool
    is_paused: bool
    poll_priority: int
    consecutive_errors: int
    auto_disabled_at: Optional[str] = None
    platform_accounts: List[PlatformAccountOut] = []

    model_config = {"from_attributes": True}


class StreamerCreate(BaseModel):
    display_name: str


class PriorityUpdate(BaseModel):
    priority: int  # 1=low, 2=normal, 3=high


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.get("/", response_model=List[StreamerOut])
async def list_streamers(db: AsyncSession = Depends(get_db)):
    """List all streamers with their platform accounts."""
    svc = StreamerService(db)
    streamers = await svc.list_streamers()
    return [
        StreamerOut(
            id=s.id,
            display_name=s.display_name,
            is_active=s.is_active,
            is_paused=s.is_paused,
            poll_priority=getattr(s, "poll_priority", 2),
            consecutive_errors=s.consecutive_errors,
            auto_disabled_at=s.auto_disabled_at.isoformat() if s.auto_disabled_at else None,
            platform_accounts=[
                PlatformAccountOut(
                    id=a.id,
                    platform=a.platform.value,
                    platform_id=a.platform_id,
                    platform_url=a.platform_url,
                    is_active=a.is_active,
                    is_live=a.is_live,
                )
                for a in s.platform_accounts
            ],
        )
        for s in streamers
    ]


@router.get("/{streamer_id}", response_model=StreamerOut)
async def get_streamer(streamer_id: int, db: AsyncSession = Depends(get_db)):
    svc = StreamerService(db)
    streamer = await svc.get_streamer(streamer_id)
    if streamer is None:
        raise HTTPException(status_code=404, detail="Streamer not found")
    return StreamerOut(
        id=streamer.id,
        display_name=streamer.display_name,
        is_active=streamer.is_active,
        is_paused=streamer.is_paused,
        poll_priority=getattr(streamer, "poll_priority", 2),
        consecutive_errors=streamer.consecutive_errors,
        auto_disabled_at=streamer.auto_disabled_at.isoformat() if streamer.auto_disabled_at else None,
        platform_accounts=[
            PlatformAccountOut(
                id=a.id,
                platform=a.platform.value,
                platform_id=a.platform_id,
                platform_url=a.platform_url,
                is_active=a.is_active,
                is_live=a.is_live,
            )
            for a in streamer.platform_accounts
        ],
    )


@router.patch("/{streamer_id}/pause", status_code=status.HTTP_204_NO_CONTENT)
async def pause_streamer(streamer_id: int, db: AsyncSession = Depends(get_db)):
    svc = StreamerService(db)
    if not await svc.pause(streamer_id):
        raise HTTPException(status_code=404, detail="Streamer not found")


@router.patch("/{streamer_id}/resume", status_code=status.HTTP_204_NO_CONTENT)
async def resume_streamer(streamer_id: int, db: AsyncSession = Depends(get_db)):
    svc = StreamerService(db)
    if not await svc.resume(streamer_id):
        raise HTTPException(status_code=404, detail="Streamer not found")


@router.patch("/{streamer_id}/priority", status_code=status.HTTP_204_NO_CONTENT)
async def set_priority(streamer_id: int, body: PriorityUpdate, db: AsyncSession = Depends(get_db)):
    """Feature 9: Set poll priority via REST."""
    svc = StreamerService(db)
    if not await svc.set_priority(streamer_id, body.priority):
        raise HTTPException(status_code=404, detail="Streamer not found")


@router.delete("/{streamer_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_streamer(streamer_id: int, db: AsyncSession = Depends(get_db)):
    svc = StreamerService(db)
    if not await svc.remove_streamer(streamer_id):
        raise HTTPException(status_code=404, detail="Streamer not found")
