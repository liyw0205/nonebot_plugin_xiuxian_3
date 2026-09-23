"""Pure rules for the v0.1 spirit-spring world event."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

EVENT_KEY = "event.spirit_spring"
EVENT_LOCATION = "xuantian.spirit_field"
EVENT_RULE_VERSION = "events-0.1.0"
EVENT_TARGET = 100
PERSONAL_CONTRIBUTION_CAP = 30
PERSONAL_REWARD_THRESHOLD = 10
EVENT_DURATION_SECONDS = 30 * 60
EVENT_CLAIM_WINDOW_SECONDS = 24 * 60 * 60
EVENT_START_HOUR_UTC = 20
EVENT_WEEKDAYS = frozenset({2, 6})


def scheduled_start(now: datetime) -> datetime | None:
    """Return today's scheduled start, if the current UTC day hosts an event."""

    value = now.astimezone(timezone.utc)
    if value.weekday() not in EVENT_WEEKDAYS:
        return None
    start = value.replace(hour=EVENT_START_HOUR_UTC, minute=0, second=0, microsecond=0)
    if value < start:
        return None
    return start


def event_times(start: datetime) -> tuple[datetime, datetime, datetime]:
    end = start + timedelta(seconds=EVENT_DURATION_SECONDS)
    return start, end, end + timedelta(seconds=EVENT_CLAIM_WINDOW_SECONDS)


def round_id_for(start: datetime) -> str:
    return start.astimezone(timezone.utc).strftime("%Y%m%d")


__all__ = [
    "EVENT_CLAIM_WINDOW_SECONDS",
    "EVENT_DURATION_SECONDS",
    "EVENT_KEY",
    "EVENT_LOCATION",
    "EVENT_RULE_VERSION",
    "EVENT_START_HOUR_UTC",
    "EVENT_TARGET",
    "EVENT_WEEKDAYS",
    "PERSONAL_CONTRIBUTION_CAP",
    "PERSONAL_REWARD_THRESHOLD",
    "event_times",
    "round_id_for",
    "scheduled_start",
]
