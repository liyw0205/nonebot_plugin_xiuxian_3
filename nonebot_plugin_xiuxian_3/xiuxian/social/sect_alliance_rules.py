"""Versioned rules for production alliances between sects."""

from __future__ import annotations

from datetime import datetime, timezone


ALLIANCE_CONTENT_VERSION = "content-0.5"
ALLIANCE_RULE_VERSION = "social-0.5.0"
ALLIANCE_MIN_SECT_LEVEL = 5
ALLIANCE_CONFIRMATION_SECONDS = 24 * 60 * 60
ALLIANCE_DURATION_SECONDS = 7 * 24 * 60 * 60
ALLIANCE_RESEARCH_WEEKLY_CAP = 3
ALLIANCE_BREACH_FEE = 10_000
SECT_ALLIANCE_COOLDOWN_SECONDS = 24 * 60 * 60


def alliance_week_id(now: datetime) -> str:
    value = now.astimezone(timezone.utc).isocalendar()
    return f"{value.year:04d}-W{value.week:02d}"


__all__ = [
    "ALLIANCE_BREACH_FEE",
    "ALLIANCE_CONFIRMATION_SECONDS",
    "ALLIANCE_CONTENT_VERSION",
    "ALLIANCE_DURATION_SECONDS",
    "ALLIANCE_MIN_SECT_LEVEL",
    "ALLIANCE_RESEARCH_WEEKLY_CAP",
    "ALLIANCE_RULE_VERSION",
    "SECT_ALLIANCE_COOLDOWN_SECONDS",
    "alliance_week_id",
]
