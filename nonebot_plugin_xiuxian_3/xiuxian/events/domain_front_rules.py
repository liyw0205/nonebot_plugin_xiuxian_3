"""Versioned rules for the v0.4 domain-front event and season."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone


EVENT_KEY = "event.domain_front"
CONTENT_VERSION = "content-0.4"
RULE_VERSION = "events-0.4.0"
LOCATION_KEY = "xuantian.domain_front"
ACTIVITY_HOURS = 4
ROUND_MINUTES = 30
CLAIM_DAYS = 1
PERSONAL_THRESHOLD = 100
EVENT_TARGET = 1000
SEASON_KEY = "season.domain_war"
SEASON_DAYS = 21
SEASON_CLAIM_DAYS = 7
SEASON_ANCHOR = datetime(2025, 1, 1, tzinfo=timezone.utc)
PARTICIPANT_CAP = 20
JOIN_STAMINA_COST = 20
ACTION_VALUES = {"战斗": "battle", "领域战": "battle", "占点": "point", "据点": "point"}
BATTLE_CONTRIBUTION = 100
POINT_CONTRIBUTION_PER_MINUTE = 10


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def domain_rank(realm_key: str) -> int:
    return {
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
    }.get(realm_key, -1)


def meets_domain_front_realm(realm_key: str, layer: int) -> bool:
    return (domain_rank(realm_key), int(layer)) >= (domain_rank("soul_transformation"), 1)


def activity_window(now: datetime) -> tuple[str, datetime, datetime]:
    """Return the deterministic four-hour UTC activity block containing now.

    The content contract fixes the activity length but does not prescribe a
    daily start hour. Four-hour UTC blocks avoid a scheduler dependency while
    keeping every round and its end boundary reproducible.
    """

    value = _utc(now).replace(minute=0, second=0, microsecond=0)
    start_hour = (value.hour // ACTIVITY_HOURS) * ACTIVITY_HOURS
    starts_at = value.replace(hour=start_hour)
    ends_at = starts_at + timedelta(hours=ACTIVITY_HOURS)
    return f"{EVENT_KEY}:{starts_at:%Y%m%d%H}", starts_at, ends_at


def round_window(now: datetime) -> tuple[str, str, datetime, datetime, datetime, datetime]:
    activity_id, activity_start, activity_end = activity_window(now)
    value = _utc(now)
    elapsed_minutes = max(0, int((value - activity_start).total_seconds() // 60))
    round_index = min(elapsed_minutes // ROUND_MINUTES, (ACTIVITY_HOURS * 60 // ROUND_MINUTES) - 1)
    starts_at = activity_start + timedelta(minutes=round_index * ROUND_MINUTES)
    ends_at = min(starts_at + timedelta(minutes=ROUND_MINUTES), activity_end)
    round_id = f"{activity_id}:r{round_index + 1}"
    return round_id, activity_id, activity_start, activity_end, starts_at, ends_at


def season_window(now: datetime) -> tuple[str, datetime, datetime]:
    value = _utc(now)
    offset = (value.date() - SEASON_ANCHOR.date()).days // SEASON_DAYS
    starts_at = SEASON_ANCHOR + timedelta(days=offset * SEASON_DAYS)
    ends_at = starts_at + timedelta(days=SEASON_DAYS)
    return f"{SEASON_KEY}:{starts_at:%Y%m%d}", starts_at, ends_at


def season_window_for_id(season_id: str) -> tuple[str, datetime, datetime]:
    prefix = f"{SEASON_KEY}:"
    if not season_id.startswith(prefix):
        raise ValueError("invalid domain-war season id")
    try:
        starts_at = datetime.strptime(season_id[len(prefix) :], "%Y%m%d").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise ValueError("invalid domain-war season id") from exc
    canonical_id, canonical_start, ends_at = season_window(starts_at)
    if canonical_id != season_id or canonical_start != starts_at:
        raise ValueError("invalid domain-war season window")
    return canonical_id, starts_at, ends_at


def claim_expiry(ends_at: datetime) -> datetime:
    return ends_at + timedelta(days=SEASON_CLAIM_DAYS)


def reward_for_rank(rank: int) -> dict[str, int]:
    if rank == 1:
        return {"item.domain_core_fragment": 20}
    if rank == 2:
        return {"item.domain_core_fragment": 15}
    if rank == 3:
        return {"item.domain_core_fragment": 10}
    if 4 <= rank <= 10:
        return {"item.domain_core_fragment": 5}
    if 11 <= rank <= 50:
        return {"world_merit": 100}
    return {}


def anonymous_label(season_id: str, player_id: int) -> str:
    digest = hashlib.sha256(f"{season_id}:{player_id}".encode("ascii")).hexdigest()[:8]
    return f"领域道友-{digest}"


__all__ = [
    "ACTION_VALUES",
    "ACTIVITY_HOURS",
    "BATTLE_CONTRIBUTION",
    "CLAIM_DAYS",
    "CONTENT_VERSION",
    "EVENT_KEY",
    "EVENT_TARGET",
    "JOIN_STAMINA_COST",
    "LOCATION_KEY",
    "PARTICIPANT_CAP",
    "PERSONAL_THRESHOLD",
    "POINT_CONTRIBUTION_PER_MINUTE",
    "ROUND_MINUTES",
    "RULE_VERSION",
    "SEASON_CLAIM_DAYS",
    "SEASON_DAYS",
    "SEASON_KEY",
    "activity_window",
    "anonymous_label",
    "claim_expiry",
    "domain_rank",
    "meets_domain_front_realm",
    "reward_for_rank",
    "round_window",
    "season_window",
    "season_window_for_id",
]
