"""Versioned rules for the v0.5 void-frontier season."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

SEASON_KEY = "season.void_frontier"
CONTENT_VERSION = "content-0.5"
RULE_VERSION = "events-0.5.0"
SEASON_DAYS = 28
CLAIM_DAYS = 7
WEEKLY_CAP = 5
RANKED_PLACES = 100
SEASON_ANCHOR = datetime(2025, 1, 1, tzinfo=timezone.utc)

SCORE_VALUES = {
    "route_completed": 30,
    "storm_rescue": 50,
    "cross_server_victory": 100,
    "alliance_contract": 20,
}


def season_window(now: datetime) -> tuple[str, datetime, datetime]:
    value = now.astimezone(timezone.utc)
    offset = (value.date() - SEASON_ANCHOR.date()).days // SEASON_DAYS
    starts_at = SEASON_ANCHOR + timedelta(days=offset * SEASON_DAYS)
    ends_at = starts_at + timedelta(days=SEASON_DAYS)
    return f"{SEASON_KEY}:{starts_at:%Y%m%d}", starts_at, ends_at


def season_window_for_id(season_id: str) -> tuple[str, datetime, datetime]:
    prefix = f"{SEASON_KEY}:"
    if not season_id.startswith(prefix):
        raise ValueError("invalid void-frontier season id")
    try:
        starts_at = datetime.strptime(season_id[len(prefix) :], "%Y%m%d").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise ValueError("invalid void-frontier season id") from exc
    canonical_id, canonical_start, ends_at = season_window(starts_at)
    if canonical_id != season_id or canonical_start != starts_at:
        raise ValueError("invalid void-frontier season window")
    return canonical_id, starts_at, ends_at


def week_id(value: datetime) -> str:
    current = value.astimezone(timezone.utc)
    start = (current - timedelta(days=current.weekday())).date()
    return start.isoformat()


def claim_expiry(ends_at: datetime) -> datetime:
    return ends_at + timedelta(days=CLAIM_DAYS)


def anonymous_label(scope: str, entity_id: str | int) -> str:
    digest = hashlib.sha256(f"{scope}:{entity_id}".encode("utf-8")).hexdigest()[:8]
    return f"匿名-{digest}"


def reward_for_rank(rank: int) -> dict[str, int]:
    if rank == 1:
        return {"item.void_crystal": 5, "void_merit": 100}
    if rank == 2:
        return {"item.void_crystal": 3, "void_merit": 60}
    if rank == 3:
        return {"item.void_crystal": 2, "void_merit": 40}
    return {"item.void_crystal": 1, "void_merit": 20}


__all__ = [
    "CLAIM_DAYS",
    "CONTENT_VERSION",
    "RANKED_PLACES",
    "RULE_VERSION",
    "SCORE_VALUES",
    "SEASON_DAYS",
    "SEASON_KEY",
    "WEEKLY_CAP",
    "anonymous_label",
    "claim_expiry",
    "reward_for_rank",
    "season_window",
    "season_window_for_id",
    "week_id",
]
