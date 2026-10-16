"""Rules for production alliances between sects."""

from __future__ import annotations

from datetime import datetime, timezone

from .social_content import sect_alliance_record

_ALLIANCE = sect_alliance_record()

ALLIANCE_MIN_SECT_LEVEL = int(_ALLIANCE["min_sect_level"])
ALLIANCE_CONFIRMATION_SECONDS = int(_ALLIANCE["confirmation_seconds"])
ALLIANCE_DURATION_SECONDS = int(_ALLIANCE["duration_seconds"])
ALLIANCE_RESEARCH_WEEKLY_CAP = int(_ALLIANCE["research_weekly_cap"])
ALLIANCE_BREACH_FEE = int(_ALLIANCE["breach_fee"])
SECT_ALLIANCE_COOLDOWN_SECONDS = int(_ALLIANCE["cooldown_seconds"])


def alliance_week_id(now: datetime) -> str:
    value = now.astimezone(timezone.utc).isocalendar()
    return f"{value.year:04d}-W{value.week:02d}"


__all__ = [
    "ALLIANCE_BREACH_FEE",
    "ALLIANCE_CONFIRMATION_SECONDS",
    "ALLIANCE_DURATION_SECONDS",
    "ALLIANCE_MIN_SECT_LEVEL",
    "ALLIANCE_RESEARCH_WEEKLY_CAP",
    "SECT_ALLIANCE_COOLDOWN_SECONDS",
    "alliance_week_id",
]
