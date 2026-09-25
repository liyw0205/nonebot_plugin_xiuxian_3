"""Versioned rules for the v0.3 demon invasion event."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


DEMON_EVENT_KEY = "event.demon_invasion"
DEMON_EVENT_CONTENT_VERSION = "content-0.3"
DEMON_EVENT_RULE_VERSION = "events-0.3.0"
DEMON_EVENT_LOCATION = "xuantian.war_front"
DEMON_EVENT_TARGET = 1000
DEMON_EVENT_DURATION_SECONDS = 3 * 60 * 60
DEMON_EVENT_CLAIM_WINDOW_SECONDS = 24 * 60 * 60
DEMON_EVENT_START_HOUR_UTC = 20
DEMON_EVENT_WEEKDAYS = frozenset({2})
DEMON_PERSONAL_REWARD_THRESHOLD = 50
DEMON_ACTION_VALUES = {"战斗": "battle", "运输": "transport", "维修": "maintenance"}
DEMON_ACTION_CONTRIBUTION = {"transport": 10, "maintenance": 15}


def demon_meets_realm(realm_key: str, layer: int) -> bool:
    ranks = {
        "mortal": 0,
        "qi_sensing": 1,
        "qi_gathering": 2,
        "foundation": 3,
        "golden_core": 4,
        "nascent_soul": 5,
        "soul_transformation": 6,
        "void_refining": 7,
        "dao_union": 8,
        "tribulation": 9,
    }
    return (ranks.get(realm_key, -1), int(layer)) >= (ranks["nascent_soul"], 1)


def demon_scheduled_start(now: datetime) -> datetime | None:
    value = now.astimezone(timezone.utc)
    if value.weekday() not in DEMON_EVENT_WEEKDAYS:
        return None
    start = value.replace(hour=DEMON_EVENT_START_HOUR_UTC, minute=0, second=0, microsecond=0)
    return start if value >= start else None


def demon_round_id_for(start: datetime) -> str:
    return f"{DEMON_EVENT_KEY}:{start.astimezone(timezone.utc):%Y%m%d%H}"


def demon_event_times(start: datetime) -> tuple[datetime, datetime, datetime]:
    end = start + timedelta(seconds=DEMON_EVENT_DURATION_SECONDS)
    return start, end, end + timedelta(seconds=DEMON_EVENT_CLAIM_WINDOW_SECONDS)


__all__ = [
    "DEMON_ACTION_CONTRIBUTION",
    "DEMON_ACTION_VALUES",
    "DEMON_EVENT_CLAIM_WINDOW_SECONDS",
    "DEMON_EVENT_CONTENT_VERSION",
    "DEMON_EVENT_DURATION_SECONDS",
    "DEMON_EVENT_KEY",
    "DEMON_EVENT_LOCATION",
    "DEMON_EVENT_RULE_VERSION",
    "DEMON_EVENT_START_HOUR_UTC",
    "DEMON_EVENT_TARGET",
    "DEMON_EVENT_WEEKDAYS",
    "DEMON_PERSONAL_REWARD_THRESHOLD",
    "demon_event_times",
    "demon_meets_realm",
    "demon_round_id_for",
    "demon_scheduled_start",
]
