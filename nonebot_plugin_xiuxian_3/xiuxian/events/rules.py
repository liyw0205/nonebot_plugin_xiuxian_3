"""Pure rules for the spirit-spring world event."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .season_content import FINAL_HEAVEN_SEASON_KEY as _FINAL_HEAVEN_KEY
from .season_content import season_record

_RECORD = season_record(_FINAL_HEAVEN_KEY)

FINAL_HEAVEN_SEASON_KEY = _FINAL_HEAVEN_KEY
FINAL_HEAVEN_SEASON_DAYS = int(_RECORD["duration_days"])
FINAL_HEAVEN_SEASON_ANCHOR = _RECORD["anchor"]


def final_heaven_season_window(now: datetime) -> tuple[str, datetime, datetime]:
    value = now.astimezone(timezone.utc)
    season_days = (value.date() - FINAL_HEAVEN_SEASON_ANCHOR.date()).days // FINAL_HEAVEN_SEASON_DAYS
    starts_at = FINAL_HEAVEN_SEASON_ANCHOR + timedelta(days=season_days * FINAL_HEAVEN_SEASON_DAYS)
    ends_at = starts_at + timedelta(days=FINAL_HEAVEN_SEASON_DAYS)
    season_id = f"{FINAL_HEAVEN_SEASON_KEY}:{starts_at:%Y%m%d}"
    return season_id, starts_at, ends_at


__all__ = [
    "FINAL_HEAVEN_SEASON_ANCHOR",
    "FINAL_HEAVEN_SEASON_DAYS",
    "FINAL_HEAVEN_SEASON_KEY",
    "final_heaven_season_window",
]
