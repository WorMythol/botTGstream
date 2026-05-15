"""Discord webhook management endpoints — requires API key auth."""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, HttpUrl
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_db, verify_api_key
from services.discord_service import DiscordService

router = APIRouter(
    prefix="/discord",
    tags=["Discord"],
    dependencies=[Depends(verify_api_key)],
)


class WebhookCreate(BaseModel):
    name: str
    webhook_url: str
    send_end_notifications: bool = True


class WebhookOut(BaseModel):
    id: int
    name: str
    webhook_url: str
    is_active: bool
    send_end_notifications: bool

    model_config = {"from_attributes": True}


@router.get("/webhooks", response_model=List[WebhookOut])
async def list_webhooks(db: AsyncSession = Depends(get_db)):
    """List all registered Discord webhooks."""
    svc = DiscordService(db)
    return await svc.list_webhooks()


@router.post("/webhooks", response_model=WebhookOut, status_code=status.HTTP_201_CREATED)
async def create_webhook(body: WebhookCreate, db: AsyncSession = Depends(get_db)):
    """Register a new Discord webhook."""
    svc = DiscordService(db)
    wh = await svc.add_webhook(
        name=body.name,
        url=body.webhook_url,
        send_end_notifications=body.send_end_notifications,
    )
    return wh


@router.patch("/webhooks/{webhook_id}/toggle", response_model=WebhookOut)
async def toggle_webhook(webhook_id: int, db: AsyncSession = Depends(get_db)):
    """Enable or disable a Discord webhook."""
    svc = DiscordService(db)
    new_state = await svc.toggle_webhook(webhook_id)
    if new_state is None:
        raise HTTPException(status_code=404, detail="Webhook not found")
    # Reload to return full object
    from db.models import DiscordWebhook
    wh = await db.get(DiscordWebhook, webhook_id)
    return wh


@router.delete("/webhooks/{webhook_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_webhook(webhook_id: int, db: AsyncSession = Depends(get_db)):
    """Delete a Discord webhook."""
    svc = DiscordService(db)
    deleted = await svc.delete_webhook(webhook_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Webhook not found")
