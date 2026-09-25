"""Versioned rules and rolling windows for cross-realm public events."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


CONTENT_VERSION = "content-0.3"
RULE_VERSION = "events-0.3.1"
BEAST_TRADE_EVENT_KEY = "event.beast_trade"
BEAST_TRADE_LOCATION = "beast.three_realms_trade_port"
BEAST_TRADE_DURATION_SECONDS = 7 * 24 * 60 * 60
BEAST_TRADE_TARGET = 300
BEAST_TRADE_THRESHOLD = 30
BEAST_TRADE_REWARD = {"faction_reputation.beast": 50, "item.material.array_sand": 10}
BOUNDARY_RIFT_EVENT_KEY = "event.boundary_rift"
BOUNDARY_RIFT_LOCATION = "cave.boundary_realm"
BOUNDARY_RIFT_DURATION_SECONDS = 2 * 60 * 60
BOUNDARY_RIFT_TARGET = 400
BOUNDARY_RIFT_THRESHOLD = 40
BOUNDARY_RIFT_REWARD = {"item.soul_crystal": 2, "world_merit": 30}


def beast_trade_window(now: datetime) -> tuple[str, datetime, datetime, datetime]:
    value = now.astimezone(timezone.utc)
    start_date = value.date() - timedelta(days=value.weekday())
    starts_at = datetime.combine(start_date, datetime.min.time(), tzinfo=timezone.utc)
    ends_at = starts_at + timedelta(seconds=BEAST_TRADE_DURATION_SECONDS)
    claim_expires_at = ends_at + timedelta(days=1)
    return f"{BEAST_TRADE_EVENT_KEY}:{starts_at:%Y%m%d}", starts_at, ends_at, claim_expires_at


def boundary_rift_window(now: datetime) -> tuple[str, datetime, datetime, datetime]:
    value = now.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
    block = value.hour // 2
    starts_at = value.replace(hour=block * 2)
    ends_at = starts_at + timedelta(seconds=BOUNDARY_RIFT_DURATION_SECONDS)
    claim_expires_at = ends_at + timedelta(days=1)
    return f"{BOUNDARY_RIFT_EVENT_KEY}:{starts_at:%Y%m%d%H}", starts_at, ends_at, claim_expires_at


EVENT_DEFINITIONS = {
    BEAST_TRADE_EVENT_KEY: {
        "location_key": BEAST_TRADE_LOCATION,
        "target": BEAST_TRADE_TARGET,
        "threshold": BEAST_TRADE_THRESHOLD,
        "reward": BEAST_TRADE_REWARD,
    },
    BOUNDARY_RIFT_EVENT_KEY: {
        "location_key": BOUNDARY_RIFT_LOCATION,
        "target": BOUNDARY_RIFT_TARGET,
        "threshold": BOUNDARY_RIFT_THRESHOLD,
        "reward": BOUNDARY_RIFT_REWARD,
    },
}


__all__ = [
    "BEAST_TRADE_EVENT_KEY",
    "BEAST_TRADE_LOCATION",
    "BEAST_TRADE_REWARD",
    "BEAST_TRADE_TARGET",
    "BEAST_TRADE_THRESHOLD",
    "BOUNDARY_RIFT_EVENT_KEY",
    "BOUNDARY_RIFT_LOCATION",
    "BOUNDARY_RIFT_REWARD",
    "BOUNDARY_RIFT_TARGET",
    "BOUNDARY_RIFT_THRESHOLD",
    "CONTENT_VERSION",
    "EVENT_DEFINITIONS",
    "RULE_VERSION",
    "beast_trade_window",
    "boundary_rift_window",
]
