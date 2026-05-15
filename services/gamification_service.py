"""Gamification service — streaks, achievements, leaderboards.

Achievement catalogue:
  first_stream   — 1st stream in system
  streams_10/50/100 — milestone stream counts
  hours_10/100/500  — total hours streamed
  streak_7/30    — consecutive-day streaks
  viewers_1k/10k — peak viewer milestones
  marathon       — single session ≥ 8 hours
  night_owl      — stream started after midnight UTC
  early_bird     — stream started before 07:00 UTC
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from db.models import Achievement, AchievementType, Stream, StreamStatus, Streamer

logger = structlog.get_logger(__name__)

# ── Achievement metadata ──────────────────────────────────────────────────────

ACHIEVEMENT_META: Dict[AchievementType, dict] = {
    AchievementType.FIRST_STREAM:  {"emoji": "🎉", "name": "First Stream",      "desc": "Went live for the first time"},
    AchievementType.STREAMS_10:    {"emoji": "🔟", "name": "10 Streams",         "desc": "Completed 10 streams"},
    AchievementType.STREAMS_50:    {"emoji": "⭐", "name": "50 Streams",         "desc": "Completed 50 streams"},
    AchievementType.STREAMS_100:   {"emoji": "💯", "name": "100 Streams",        "desc": "100 streams — dedicated streamer!"},
    AchievementType.HOURS_10:      {"emoji": "⏰", "name": "10 Hours",           "desc": "Streamed 10 hours total"},
    AchievementType.HOURS_100:     {"emoji": "🏅", "name": "100 Hours",          "desc": "Streamed 100 hours total"},
    AchievementType.HOURS_500:     {"emoji": "🏆", "name": "500 Hours",          "desc": "500 hours — true veteran"},
    AchievementType.STREAK_7:      {"emoji": "🔥", "name": "Week Streak",        "desc": "7 days live in a row"},
    AchievementType.STREAK_30:     {"emoji": "🌙", "name": "Month Streak",       "desc": "30 days live in a row"},
    AchievementType.VIEWERS_1K:    {"emoji": "👥", "name": "1K Viewers",         "desc": "Reached 1,000 concurrent viewers"},
    AchievementType.VIEWERS_10K:   {"emoji": "🚀", "name": "10K Viewers",        "desc": "Reached 10,000 concurrent viewers"},
    AchievementType.MARATHON:      {"emoji": "🏃", "name": "Marathon",           "desc": "Streamed 8+ hours in one session"},
    AchievementType.NIGHT_OWL:     {"emoji": "🦉", "name": "Night Owl",          "desc": "Started a stream after midnight UTC"},
    AchievementType.EARLY_BIRD:    {"emoji": "🐦", "name": "Early Bird",         "desc": "Started a stream before 07:00 UTC"},
}


@dataclass
class LeaderboardEntry:
    rank: int
    streamer_id: int
    display_name: str
    value: float
    extra: str = ""  # formatted value string


@dataclass
class AchievementOut:
    achievement_type: AchievementType
    emoji: str
    name: str
    desc: str
    earned_at: datetime


class GamificationService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ── Achievements ──────────────────────────────────────────────────────────

    async def check_and_award(
        self,
        streamer_id: int,
        stream: Optional[Stream] = None,
    ) -> List[AchievementType]:
        """Check all achievements for a streamer and award any that are newly earned.

        Returns list of newly awarded achievement types (so callers can notify).
        """
        streamer = await self._get_streamer_with_stats(streamer_id)
        if streamer is None:
            return []

        already = await self._get_earned_types(streamer_id)
        newly_earned: List[AchievementType] = []

        # Total ended streams
        total_streams = sum(1 for s in streamer.streams if s.status == StreamStatus.ENDED)
        # Total hours
        total_hours = sum(
            (s.ended_at - s.started_at).total_seconds() / 3600
            for s in streamer.streams
            if s.ended_at and s.started_at and s.status == StreamStatus.ENDED
        )
        # Peak viewers ever
        peak_ever = max((s.peak_viewer_count or 0 for s in streamer.streams), default=0)

        checks: List[Tuple[AchievementType, bool]] = [
            (AchievementType.FIRST_STREAM,  total_streams >= 1),
            (AchievementType.STREAMS_10,    total_streams >= 10),
            (AchievementType.STREAMS_50,    total_streams >= 50),
            (AchievementType.STREAMS_100,   total_streams >= 100),
            (AchievementType.HOURS_10,      total_hours >= 10),
            (AchievementType.HOURS_100,     total_hours >= 100),
            (AchievementType.HOURS_500,     total_hours >= 500),
            (AchievementType.STREAK_7,      streamer.max_streak >= 7),
            (AchievementType.STREAK_30,     streamer.max_streak >= 30),
            (AchievementType.VIEWERS_1K,    peak_ever >= 1_000),
            (AchievementType.VIEWERS_10K,   peak_ever >= 10_000),
        ]

        # Stream-specific achievements (require current stream)
        if stream and stream.started_at and stream.ended_at:
            duration_h = (stream.ended_at - stream.started_at).total_seconds() / 3600
            hour = stream.started_at.hour
            checks += [
                (AchievementType.MARATHON,    duration_h >= 8),
                (AchievementType.NIGHT_OWL,   0 <= hour < 5),
                (AchievementType.EARLY_BIRD,  5 <= hour < 7),
            ]

        for ach_type, condition in checks:
            if condition and ach_type not in already:
                await self._award(streamer_id, ach_type, {
                    "total_streams": total_streams,
                    "total_hours": round(total_hours, 1),
                })
                newly_earned.append(ach_type)
                logger.info("achievement.awarded", streamer_id=streamer_id, type=ach_type.value)

        return newly_earned

    async def get_achievements(self, streamer_id: int) -> List[AchievementOut]:
        """Return all achievements earned by a streamer, newest first."""
        result = await self._session.execute(
            select(Achievement)
            .where(Achievement.streamer_id == streamer_id)
            .order_by(Achievement.earned_at.desc())
        )
        rows = list(result.scalars().all())
        out = []
        for a in rows:
            meta = ACHIEVEMENT_META.get(a.achievement_type, {})
            out.append(AchievementOut(
                achievement_type=a.achievement_type,
                emoji=meta.get("emoji", "🏅"),
                name=meta.get("name", a.achievement_type.value),
                desc=meta.get("desc", ""),
                earned_at=a.earned_at,
            ))
        return out

    # ── Streaks ───────────────────────────────────────────────────────────────

    async def update_streak(self, streamer_id: int) -> Tuple[int, bool]:
        """Update daily stream streak after a stream ends.

        Returns (new_streak, is_new_max).
        """
        streamer = await self._session.get(Streamer, streamer_id)
        if streamer is None:
            return 0, False

        today = datetime.now(timezone.utc).date()
        last = streamer.last_stream_date
        last_date = last.date() if last else None

        if last_date is None or (today - last_date).days > 1:
            # First stream or gap — reset streak
            streamer.current_streak = 1
        elif last_date == today:
            # Already counted today
            return streamer.current_streak, False
        else:
            # Consecutive day
            streamer.current_streak += 1

        streamer.last_stream_date = datetime.now(timezone.utc)
        is_new_max = streamer.current_streak > streamer.max_streak
        if is_new_max:
            streamer.max_streak = streamer.current_streak

        await self._session.flush()
        return streamer.current_streak, is_new_max

    async def reset_broken_streaks(self) -> int:
        """Called daily at midnight — reset streaks for streamers who missed yesterday."""
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).date()
        result = await self._session.execute(
            select(Streamer).where(
                Streamer.is_active.is_(True),
                Streamer.current_streak > 0,
            )
        )
        streamers = list(result.scalars().all())
        reset_count = 0
        for s in streamers:
            if s.last_stream_date is None:
                continue
            last_date = s.last_stream_date.date()
            if last_date < yesterday:
                logger.info("streak.broken", streamer_id=s.id, last=str(last_date))
                s.current_streak = 0
                reset_count += 1
        if reset_count:
            await self._session.flush()
        return reset_count

    # ── Leaderboards ──────────────────────────────────────────────────────────

    async def leaderboard_by_streams(self, limit: int = 10) -> List[LeaderboardEntry]:
        """Top streamers by total stream count."""
        result = await self._session.execute(
            select(Streamer)
            .options(selectinload(Streamer.streams))
            .where(Streamer.is_active.is_(True))
        )
        streamers = list(result.scalars().all())
        data = []
        for s in streamers:
            count = len(s.streams)
            data.append((count, s))
        data.sort(key=lambda x: x[0], reverse=True)
        return [
            LeaderboardEntry(
                rank=i + 1,
                streamer_id=s.id,
                display_name=s.display_name,
                value=count,
                extra=f"{count} streams",
            )
            for i, (count, s) in enumerate(data[:limit])
        ]

    async def leaderboard_by_hours(self, limit: int = 10) -> List[LeaderboardEntry]:
        """Top streamers by total hours streamed."""
        result = await self._session.execute(
            select(Streamer)
            .options(selectinload(Streamer.streams))
            .where(Streamer.is_active.is_(True))
        )
        streamers = list(result.scalars().all())
        data = []
        for s in streamers:
            hours = sum(
                (st.ended_at - st.started_at).total_seconds() / 3600
                for st in s.streams
                if st.ended_at and st.started_at
            )
            data.append((hours, s))
        data.sort(key=lambda x: x[0], reverse=True)
        return [
            LeaderboardEntry(
                rank=i + 1,
                streamer_id=s.id,
                display_name=s.display_name,
                value=hours,
                extra=f"{hours:.1f}h",
            )
            for i, (hours, s) in enumerate(data[:limit])
        ]

    async def leaderboard_by_viewers(self, limit: int = 10) -> List[LeaderboardEntry]:
        """Top streamers by all-time peak viewer count."""
        result = await self._session.execute(
            select(Streamer)
            .options(selectinload(Streamer.streams))
            .where(Streamer.is_active.is_(True))
        )
        streamers = list(result.scalars().all())
        data = []
        for s in streamers:
            peak = max((st.peak_viewer_count or 0 for st in s.streams), default=0)
            data.append((peak, s))
        data.sort(key=lambda x: x[0], reverse=True)
        return [
            LeaderboardEntry(
                rank=i + 1,
                streamer_id=s.id,
                display_name=s.display_name,
                value=peak,
                extra=_fmt_viewers(peak),
            )
            for i, (peak, s) in enumerate(data[:limit])
        ]

    async def leaderboard_by_streak(self, limit: int = 10) -> List[LeaderboardEntry]:
        """Top streamers by max streak."""
        result = await self._session.execute(
            select(Streamer)
            .where(Streamer.is_active.is_(True))
            .order_by(Streamer.max_streak.desc())
            .limit(limit)
        )
        streamers = list(result.scalars().all())
        return [
            LeaderboardEntry(
                rank=i + 1,
                streamer_id=s.id,
                display_name=s.display_name,
                value=s.max_streak,
                extra=f"{s.max_streak}d streak",
            )
            for i, s in enumerate(streamers)
        ]

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def _get_streamer_with_stats(self, streamer_id: int) -> Optional[Streamer]:
        result = await self._session.execute(
            select(Streamer)
            .options(selectinload(Streamer.streams))
            .where(Streamer.id == streamer_id)
        )
        return result.scalar_one_or_none()

    async def _get_earned_types(self, streamer_id: int) -> set:
        result = await self._session.execute(
            select(Achievement.achievement_type)
            .where(Achievement.streamer_id == streamer_id)
        )
        return set(result.scalars().all())

    async def _award(self, streamer_id: int, ach_type: AchievementType, meta: dict) -> None:
        a = Achievement(streamer_id=streamer_id, achievement_type=ach_type, meta=meta)
        self._session.add(a)
        await self._session.flush()


def _fmt_viewers(count: int) -> str:
    if count >= 1_000_000:
        return f"{count / 1_000_000:.1f}M"
    if count >= 1_000:
        return f"{count / 1_000:.1f}K"
    return str(count)
