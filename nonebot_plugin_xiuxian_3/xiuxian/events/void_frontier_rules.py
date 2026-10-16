"""Rules for the void-frontier season."""

from __future__ import annotations


import hashlib
from datetime import datetime, timedelta, timezone

from .season_content import VOID_FRONTIER_SEASON_KEY, season_record

_RECORD = season_record(VOID_FRONTIER_SEASON_KEY)

SEASON_KEY = VOID_FRONTIER_SEASON_KEY
SEASON_DAYS = int(_RECORD["duration_days"])
CLAIM_DAYS = int(_RECORD["claim_days"])
WEEKLY_CAP = int(_RECORD["weekly_cap"])
WEEKLY_REWARD = dict(_RECORD["weekly_reward"])
RANKED_PLACES = int(_RECORD["rank_limit"])
SEASON_ANCHOR = _RECORD["anchor"]

SCORE_VALUES = dict(_RECORD["score_values"])

_RANK_REWARDS = {
    entry["rank"]: dict(entry["reward"]) for entry in _RECORD["rank_rewards"]
}
_DEFAULT_RANK_REWARD = dict(_RECORD["default_rank_reward"])


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
    return dict(_RANK_REWARDS.get(rank, _DEFAULT_RANK_REWARD))


__all__ = [
    "CLAIM_DAYS",
    "RANKED_PLACES",
    "SCORE_VALUES",
    "SEASON_DAYS",
    "SEASON_KEY",
    "WEEKLY_CAP",
    "WEEKLY_REWARD",
    "anonymous_label",
    "claim_expiry",
    "reward_for_rank",
    "season_window",
    "season_window_for_id",
    "week_id",
]
