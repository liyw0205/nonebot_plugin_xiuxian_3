"""Rules for the v0.3 three-realms temporary season."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone


SEASON_KEY = "season.three_realms"
CONTENT_VERSION = "content-0.3"
RULE_VERSION = "events-0.3.2"
SEASON_DAYS = 28
CLAIM_DAYS = 7
SEASON_ANCHOR = datetime(2025, 1, 1, tzinfo=timezone.utc)
RANKED_PLACES = 100
BOARDS = {
    "faction_merit": {"label": "阵营功勋榜"},
    "party_contribution": {"label": "多人副本贡献榜"},
    "sect_contribution": {"label": "宗门贡献榜"},
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
        raise ValueError("invalid three-realms season id")
    try:
        starts_at = datetime.strptime(season_id[len(prefix) :], "%Y%m%d").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise ValueError("invalid three-realms season id") from exc
    canonical_id, canonical_start, ends_at = season_window(starts_at)
    if canonical_id != season_id or canonical_start != starts_at:
        raise ValueError("invalid three-realms season window")
    return canonical_id, starts_at, ends_at


def claim_expiry(ends_at: datetime) -> datetime:
    return ends_at + timedelta(days=CLAIM_DAYS)


def tie_breaker(season_id: str, player_id: int) -> str:
    return hashlib.sha256(f"{season_id}:{player_id}".encode("ascii")).hexdigest()


def reward_for_rank(rank: int) -> dict[str, int]:
    if rank == 1:
        return {"item.soul_crystal": 5, "world_merit": 200}
    if rank == 2:
        return {"item.soul_crystal": 3, "world_merit": 120}
    if rank == 3:
        return {"item.soul_crystal": 2, "world_merit": 80}
    return {"item.soul_crystal": 1, "world_merit": 30}


__all__ = [
    "BOARDS",
    "CLAIM_DAYS",
    "CONTENT_VERSION",
    "RANKED_PLACES",
    "RULE_VERSION",
    "SEASON_DAYS",
    "SEASON_KEY",
    "claim_expiry",
    "reward_for_rank",
    "season_window",
    "season_window_for_id",
    "tie_breaker",
]
