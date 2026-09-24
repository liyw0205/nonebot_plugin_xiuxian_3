"""Pure rules for final-heaven seasonal ranking and rewards."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib

from .rules import FINAL_HEAVEN_SEASON_DAYS, FINAL_HEAVEN_SEASON_KEY, final_heaven_season_window


FINAL_HEAVEN_RULE_VERSION = "events-0.6.1"
FINAL_HEAVEN_CLAIM_DAYS = 7
FINAL_HEAVEN_RANKED_PLACES = 10
FINAL_HEAVEN_CHAPTER_ENTITLEMENT = "chapter.final_heaven"
FINAL_HEAVEN_BOARDS = {
    "ascension": {
        "label": "飞升榜",
        "title_key": "title.season.final_heaven.ascension",
        "title_label": "凌霄先登",
        "score": 1000,
    },
    "dao": {
        "label": "留界道统榜",
        "title_key": "title.season.final_heaven.dao",
        "title_label": "留界道统",
        "score": 800,
    },
    "cooperation": {
        "label": "协作终局战榜",
        "title_key": "title.season.final_heaven.cooperation",
        "title_label": "同道共济",
        "score": 50,
    },
}


def final_heaven_window_for_id(season_id: str) -> tuple[str, datetime, datetime]:
    prefix = f"{FINAL_HEAVEN_SEASON_KEY}:"
    if not season_id.startswith(prefix):
        raise ValueError("invalid final-heaven season id")
    try:
        starts_at = datetime.strptime(season_id[len(prefix) :], "%Y%m%d").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise ValueError("invalid final-heaven season id") from exc
    canonical_id, canonical_start, ends_at = final_heaven_season_window(starts_at)
    if canonical_id != season_id or canonical_start != starts_at:
        raise ValueError("invalid final-heaven season id")
    if (ends_at - starts_at).days != FINAL_HEAVEN_SEASON_DAYS:
        raise ValueError("invalid final-heaven season window")
    return canonical_id, starts_at, ends_at


def final_heaven_claim_expiry(ends_at: datetime) -> datetime:
    return ends_at + timedelta(days=FINAL_HEAVEN_CLAIM_DAYS)


def final_heaven_tie_breaker(season_id: str, player_id: int) -> str:
    return hashlib.sha256(f"{season_id}:{player_id}".encode("ascii")).hexdigest()


__all__ = [
    "FINAL_HEAVEN_BOARDS",
    "FINAL_HEAVEN_CHAPTER_ENTITLEMENT",
    "FINAL_HEAVEN_CLAIM_DAYS",
    "FINAL_HEAVEN_RANKED_PLACES",
    "FINAL_HEAVEN_RULE_VERSION",
    "final_heaven_claim_expiry",
    "final_heaven_tie_breaker",
    "final_heaven_window_for_id",
]
