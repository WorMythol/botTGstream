"""Streamer management — add, remove, configure, pause/resume."""
from __future__ import annotations

from typing import List, Optional

import aiohttp
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from db.models import Platform, PlatformAccount, Streamer, StreamerChannelAssignment, StreamerUserAssignment
from db.repositories.streamer_repo import AssignmentRepository, PlatformAccountRepository, StreamerRepository
from integrations import YouTubeIntegration, TwitchIntegration, VKIntegration

logger = structlog.get_logger(__name__)


class StreamerService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = StreamerRepository(session)
        self._account_repo = PlatformAccountRepository(session)
        self._assign_repo = AssignmentRepository(session)

    # ── CRUD ──────────────────────────────────────────────────────────────────

    async def create_streamer(self, display_name: str, created_by: int) -> Streamer:
        streamer = Streamer(
            display_name=display_name,
            created_by=created_by,
            max_consecutive_errors=settings.MAX_CONSECUTIVE_ERRORS,
        )
        await self._repo.add(streamer)
        logger.info("streamer.created", name=display_name, by=created_by)
        return streamer

    async def add_platform_account(
        self,
        streamer_id: int,
        platform: Platform,
        url: str,
        http_session: aiohttp.ClientSession,
    ) -> tuple[Optional[PlatformAccount], Optional[str]]:
        """Resolve URL → platform ID, then create PlatformAccount.

        Returns (account, None) on success or (None, error_message) on failure.
        """
        platform_id = await self._resolve_platform_id(platform, url, http_session)
        if platform_id is None:
            return None, f"Could not resolve a valid {platform.value} channel from URL: {url}"

        # Check for duplicate
        existing = await self._account_repo.get_by_streamer_and_platform(streamer_id, platform)
        if existing:
            existing.platform_id = platform_id
            existing.platform_url = url
            existing.is_active = True
            await self._session.flush()
            return existing, None

        account = PlatformAccount(
            streamer_id=streamer_id,
            platform=platform,
            platform_id=platform_id,
            platform_url=url,
        )
        await self._account_repo.add(account)
        logger.info("platform_account.added", streamer_id=streamer_id, platform=platform, id=platform_id)
        return account, None

    async def remove_streamer(self, streamer_id: int) -> bool:
        streamer = await self._repo.get(streamer_id)
        if streamer is None:
            return False
        await self._repo.delete(streamer)
        logger.info("streamer.deleted", streamer_id=streamer_id)
        return True

    async def get_streamer(self, streamer_id: int) -> Optional[Streamer]:
        return await self._repo.get_with_accounts(streamer_id)

    async def list_streamers(self) -> List[Streamer]:
        return await self._repo.get_all_with_details()

    async def list_streamers_for_user(self, user_id: int) -> List[Streamer]:
        return await self._repo.get_for_user(user_id)

    # ── Feature 9: Poll priority ──────────────────────────────────────────────

    async def set_priority(self, streamer_id: int, priority: int) -> bool:
        """Set poll priority (1=low, 2=normal, 3=high). Returns False if not found."""
        streamer = await self._repo.get(streamer_id)
        if streamer is None:
            return False
        streamer.poll_priority = max(1, min(3, priority))
        await self._session.flush()
        logger.info("streamer.priority_set", streamer_id=streamer_id, priority=priority)
        return True

    # ── Pause / resume ────────────────────────────────────────────────────────

    async def pause(self, streamer_id: int) -> bool:
        streamer = await self._repo.get(streamer_id)
        if streamer is None:
            return False
        streamer.is_paused = True
        await self._session.flush()
        logger.info("streamer.paused", streamer_id=streamer_id)
        return True

    async def resume(self, streamer_id: int) -> bool:
        streamer = await self._repo.get(streamer_id)
        if streamer is None:
            return False
        streamer.is_paused = False
        streamer.auto_disabled_at = None
        streamer.auto_disabled_reason = None
        streamer.consecutive_errors = 0
        await self._session.flush()
        logger.info("streamer.resumed", streamer_id=streamer_id)
        return True

    # ── Channel assignments ───────────────────────────────────────────────────

    async def assign_channel(
        self,
        streamer_id: int,
        channel_id: int,
        template: Optional[str] = None,
        min_viewers: int = 0,
    ) -> StreamerChannelAssignment:
        existing = await self._assign_repo.get_by_streamer_and_channel(streamer_id, channel_id)
        if existing:
            existing.is_active = True
            if template is not None:
                existing.message_template = template
            existing.min_viewer_count = min_viewers
            await self._session.flush()
            return existing
        assignment = StreamerChannelAssignment(
            streamer_id=streamer_id,
            channel_id=channel_id,
            message_template=template,
            min_viewer_count=min_viewers,
        )
        await self._assign_repo.add(assignment)
        logger.info("assignment.created", streamer_id=streamer_id, channel_id=channel_id)
        return assignment

    async def unassign_channel(self, streamer_id: int, channel_id: int) -> bool:
        assignment = await self._assign_repo.get_by_streamer_and_channel(streamer_id, channel_id)
        if assignment is None:
            return False
        assignment.is_active = False
        await self._session.flush()
        return True

    async def set_template(
        self, streamer_id: int, channel_id: int, template: str
    ) -> bool:
        assignment = await self._assign_repo.get_by_streamer_and_channel(streamer_id, channel_id)
        if assignment is None:
            return False
        assignment.message_template = template
        await self._session.flush()
        return True

    async def get_assignments(self, streamer_id: int) -> List[StreamerChannelAssignment]:
        return await self._assign_repo.get_for_streamer(streamer_id)

    # ── User ↔ streamer assignments ───────────────────────────────────────────

    async def assign_user(self, streamer_id: int, user_id: int) -> StreamerUserAssignment:
        from sqlalchemy import select
        result = await self._session.execute(
            select(StreamerUserAssignment).where(
                StreamerUserAssignment.streamer_id == streamer_id,
                StreamerUserAssignment.user_id == user_id,
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            return existing
        sua = StreamerUserAssignment(streamer_id=streamer_id, user_id=user_id)
        self._session.add(sua)
        await self._session.flush()
        return sua

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def _resolve_platform_id(
        self, platform: Platform, url: str, http_session: aiohttp.ClientSession
    ) -> Optional[str]:
        if platform == Platform.YOUTUBE:
            client = YouTubeIntegration(settings.YOUTUBE_API_KEY, http_session)
            return await client.resolve_url(url)
        if platform == Platform.TWITCH:
            client = TwitchIntegration(settings.TWITCH_CLIENT_ID, settings.TWITCH_CLIENT_SECRET, http_session)
            return await client.resolve_url(url)
        if platform == Platform.VK:
            client = VKIntegration(settings.VK_ACCESS_TOKEN, settings.VK_API_VERSION, http_session)
            return await client.resolve_url(url)
        return None
