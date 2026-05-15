"""Discord webhook delivery service.

Sends rich embeds to Discord channels via incoming webhooks.
Supports both global webhooks (DiscordWebhook table) and per-channel
webhooks stored on TelegramChannel.discord_webhook_url.

Embed colour legend:
  🟢  0x57F287  stream started
  🔴  0xED4245  stream ended
  🔵  0x5865F2  informational
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import List, Optional, Any

import aiohttp
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import DiscordWebhook, Stream
from services.template_service import PlatformLink

logger = structlog.get_logger(__name__)

_COLOUR_LIVE = 0x57F287   # green
_COLOUR_END  = 0xED4245   # red
_COLOUR_INFO = 0x5865F2   # blurple

_TIMEOUT = aiohttp.ClientTimeout(total=10)


class DiscordService:
    """Send stream events to Discord via incoming webhooks."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ── Public API ────────────────────────────────────────────────────────────

    async def notify_stream_live(
        self,
        stream: Stream,
        streamer_name: str,
        platform_links: List[PlatformLink],
        thumbnail_url: Optional[str] = None,
    ) -> None:
        """Send a 'stream started' embed to all active Discord webhooks."""
        active_ps = [ps for ps in stream.platform_streams if ps.ended_at is None]
        title = active_ps[0].title if active_ps else "Live Stream"
        viewers = max((ps.viewer_count or 0 for ps in active_ps), default=0)

        embed = _build_live_embed(
            streamer_name=streamer_name,
            stream_title=title,
            platform_links=platform_links,
            viewer_count=viewers if viewers else None,
            thumbnail_url=thumbnail_url,
        )
        await self._broadcast(embed, include_end=False)

        # Per-channel discord_webhook_url (on TelegramChannel)
        await self._deliver_per_channel_webhooks(stream, embed)

    async def notify_stream_ended(
        self,
        stream: Stream,
        streamer_name: str,
    ) -> None:
        """Send a 'stream ended' embed to all webhooks that want end notifications."""
        embed = _build_end_embed(
            streamer_name=streamer_name,
            started_at=stream.started_at,
            ended_at=stream.ended_at or datetime.now(timezone.utc),
            peak_viewers=stream.peak_viewer_count,
        )
        await self._broadcast(embed, include_end=True)

        # Per-channel webhooks — end notifications (always send if configured)
        await self._deliver_per_channel_webhooks(stream, embed)

    # ── CRUD helpers ──────────────────────────────────────────────────────────

    async def list_webhooks(self) -> List[DiscordWebhook]:
        result = await self._session.execute(
            select(DiscordWebhook).order_by(DiscordWebhook.id)
        )
        return list(result.scalars().all())

    async def add_webhook(
        self,
        name: str,
        url: str,
        send_end_notifications: bool = True,
        created_by: Optional[int] = None,
    ) -> DiscordWebhook:
        wh = DiscordWebhook(
            name=name,
            webhook_url=url,
            is_active=True,
            send_end_notifications=send_end_notifications,
            created_by=created_by,
        )
        self._session.add(wh)
        await self._session.flush()
        return wh

    async def toggle_webhook(self, webhook_id: int) -> Optional[bool]:
        """Toggle is_active. Returns new state or None if not found."""
        wh = await self._session.get(DiscordWebhook, webhook_id)
        if wh is None:
            return None
        wh.is_active = not wh.is_active
        await self._session.flush()
        return wh.is_active

    async def delete_webhook(self, webhook_id: int) -> bool:
        wh = await self._session.get(DiscordWebhook, webhook_id)
        if wh is None:
            return False
        await self._session.delete(wh)
        await self._session.flush()
        return True

    # ── Internal delivery ─────────────────────────────────────────────────────

    async def _broadcast(self, embed: dict, include_end: bool) -> None:
        """Send embed to all active global webhooks."""
        result = await self._session.execute(
            select(DiscordWebhook).where(DiscordWebhook.is_active.is_(True))
        )
        webhooks = list(result.scalars().all())

        tasks = []
        for wh in webhooks:
            if not include_end and not wh.send_end_notifications:
                # For live events we always send; for end events honour flag
                pass
            if include_end and not wh.send_end_notifications:
                continue
            tasks.append(_post_embed(wh.webhook_url, embed))

        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for url, res in zip([w.webhook_url for w in webhooks], results):
                if isinstance(res, Exception):
                    logger.error("discord.webhook_failed", url=url[:50], error=str(res))

    async def _deliver_per_channel_webhooks(self, stream: Stream, embed: dict) -> None:
        """Send to per-channel discord_webhook_url fields (lazy-loaded channels)."""
        from sqlalchemy.orm import selectinload
        from db.models import TelegramChannel
        from db.repositories.streamer_repo import AssignmentRepository

        assign_repo = AssignmentRepository(self._session)
        assignments = await assign_repo.get_for_streamer(stream.streamer_id)
        urls_seen: set[str] = set()
        tasks = []
        for assignment in assignments:
            channel: Optional[TelegramChannel] = assignment.channel
            if (
                channel
                and channel.is_active
                and getattr(channel, "discord_webhook_url", None)
            ):
                url = channel.discord_webhook_url
                if url not in urls_seen:
                    urls_seen.add(url)
                    tasks.append(_post_embed(url, embed))

        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for res in results:
                if isinstance(res, Exception):
                    logger.error("discord.per_channel_failed", error=str(res))


# ── Embed builders ─────────────────────────────────────────────────────────────

def _build_live_embed(
    streamer_name: str,
    stream_title: str,
    platform_links: List[PlatformLink],
    viewer_count: Optional[int] = None,
    thumbnail_url: Optional[str] = None,
) -> dict:
    fields = []
    if platform_links:
        links_text = "  •  ".join(f"[{pl.platform}]({pl.url})" for pl in platform_links)
        fields.append({"name": "🔗 Watch now", "value": links_text, "inline": False})
    if viewer_count:
        fields.append({"name": "👥 Viewers", "value": f"{viewer_count:,}", "inline": True})

    embed: dict[str, Any] = {
        "title": f"🔴 {streamer_name} is live!",
        "description": stream_title,
        "color": _COLOUR_LIVE,
        "fields": fields,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if thumbnail_url:
        embed["image"] = {"url": thumbnail_url}
    return embed


def _build_end_embed(
    streamer_name: str,
    started_at: datetime,
    ended_at: datetime,
    peak_viewers: Optional[int] = None,
) -> dict:
    duration = ended_at - started_at
    total_minutes = int(duration.total_seconds() // 60)
    hours, minutes = divmod(total_minutes, 60)
    duration_str = f"{hours}h {minutes}m" if hours else f"{minutes}m"

    fields = [{"name": "⏱ Duration", "value": duration_str, "inline": True}]
    if peak_viewers:
        fields.append({"name": "👥 Peak viewers", "value": f"{peak_viewers:,}", "inline": True})

    return {
        "title": f"⬛ {streamer_name} ended the stream",
        "color": _COLOUR_END,
        "fields": fields,
        "timestamp": ended_at.isoformat(),
    }


# ── HTTP helper ────────────────────────────────────────────────────────────────

async def _post_embed(url: str, embed: dict) -> None:
    """POST a single embed to a Discord webhook URL."""
    payload = {"embeds": [embed]}
    async with aiohttp.ClientSession(timeout=_TIMEOUT) as http:
        async with http.post(url, json=payload) as resp:
            if resp.status not in (200, 204):
                body = await resp.text()
                raise RuntimeError(f"Discord returned {resp.status}: {body[:200]}")
