"""Rules for the three-realms temporary season."""

from __future__ import annotations


import hashlib
from datetime import datetime, timedelta, timezone

from .season_content import THREE_REALMS_SEASON_KEY, season_record

_RECORD = season_record(THREE_REALMS_SEASON_KEY)

SEASON_KEY = THREE_REALMS_SEASON_KEY
SEASON_DAYS = int(_RECORD["duration_days"])
CLAIM_DAYS = int(_RECORD["claim_days"])
SEASON_ANCHOR = _RECORD["anchor"]
RANKED_PLACES = int(_RECORD["rank_limit"])
BOARDS = {
    board_key: dict(board) for board_key, board in _RECORD["boards"].items()
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
    "RANKED_PLACES",
    "SEASON_DAYS",
    "SEASON_KEY",
    "claim_expiry",
    "reward_for_rank",
    "season_window",
    "season_window_for_id",
    "tie_breaker",
]
