"""Abstract base class for all stream platform integrations."""
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class StreamInfo:
    """Normalised stream data returned by any platform integration."""
    platform: str
    platform_stream_id: str
    streamer_platform_id: str
    title: str
    url: str
    viewer_count: Optional[int] = None
    thumbnail_url: Optional[str] = None
    started_at: Optional[str] = None  # ISO-8601 string


@dataclass
class PlatformCheckResult:
    """Result of checking a single platform account for live status."""
    is_live: bool
    stream: Optional[StreamInfo] = None
    error: Optional[str] = None
    quota_cost: int = 0  # API quota units consumed


class BasePlatformIntegration(ABC):
    """All platform integrations implement this interface."""

    @abstractmethod
    async def check_live(self, platform_id: str) -> PlatformCheckResult:
        """Check whether the given channel/user is currently live.

        Args:
            platform_id: Platform-specific identifier (channel ID, login, group ID).

        Returns:
            PlatformCheckResult with live status and stream details if live.
        """

    @abstractmethod
    async def resolve_url(self, url: str) -> Optional[str]:
        """Parse a channel URL and return the platform-specific ID.

        Args:
            url: Human-supplied channel URL (e.g. https://www.youtube.com/@channelname).

        Returns:
            Platform ID string, or None if the URL is unrecognised.
        """

    @staticmethod
    def _extract_domain(url: str) -> str:
        match = re.search(r"https?://(?:www\.)?([^/]+)", url)
        return match.group(1) if match else ""
