"""Rules for the v0.3 sect-war weekly rounds."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


SECT_WAR_KEY = "sect_war"
SECT_WAR_ANCHOR = datetime(2025, 1, 6, tzinfo=timezone.utc)
SECT_WAR_ROUNDS_PER_WEEK = 2
SECT_WAR_DURATION_MINUTES = 30
SECT_WAR_REGISTRATION_FEE = 2_000
SECT_WAR_MAX_PARTICIPANTS = 10
SECT_WAR_MIN_LEVEL = 4
SECT_WAR_MEMBER_THRESHOLD = 20
SECT_WAR_SECT_REWARD = 100
SECT_WAR_MEMBER_REWARD = 30
SECT_WAR_CLAIM_HOURS = 24
SECT_WAR_CONTENT_VERSION = "content-0.3"
SECT_WAR_RULE_VERSION = "social-0.3.1"


def _week_start(value: datetime) -> datetime:
    value = value.astimezone(timezone.utc)
    monday = value - timedelta(days=value.weekday())
    return monday.replace(hour=0, minute=0, second=0, microsecond=0)


def sect_war_round_window(now: datetime, round_index: int = 0) -> tuple[str, datetime, datetime, datetime, datetime]:
    """Return round id, registration bounds, battle bounds and claim expiry."""

    if round_index not in range(SECT_WAR_ROUNDS_PER_WEEK):
        raise ValueError("invalid sect-war round index")
    week = _week_start(now)
    # Two fixed 30-minute windows keep settlement deterministic without a job.
    starts_at = week + timedelta(days=2 + round_index * 3, hours=20)
    ends_at = starts_at + timedelta(minutes=SECT_WAR_DURATION_MINUTES)
    claim_expires_at = ends_at + timedelta(hours=SECT_WAR_CLAIM_HOURS)
    return f"{SECT_WAR_KEY}:{week:%Y%m%d}:{round_index + 1}", week, starts_at, ends_at, claim_expires_at


def sect_war_round_for_id(round_id: str) -> tuple[str, datetime, datetime, datetime, datetime]:
    prefix = f"{SECT_WAR_KEY}:"
    if not round_id.startswith(prefix):
        raise ValueError("invalid sect-war round id")
    try:
        date_text, index_text = round_id[len(prefix) :].split(":", 1)
        week = datetime.strptime(date_text, "%Y%m%d").replace(tzinfo=timezone.utc)
        index = int(index_text) - 1
    except (ValueError, TypeError) as exc:
        raise ValueError("invalid sect-war round id") from exc
    canonical, registration_start, starts_at, ends_at, claim_expires_at = sect_war_round_window(week, index)
    if canonical != round_id or registration_start != week:
        raise ValueError("invalid sect-war round window")
    return canonical, registration_start, starts_at, ends_at, claim_expires_at


def contribution_value(action_key: str, source_quantity: int) -> int:
    """Normalize an audited source into the documented war score."""

    if source_quantity <= 0:
        return 0
    values = {"占点": 10, "击败": 5, "运输": 15, "维修": 15}
    if action_key not in values:
        raise ValueError("invalid sect-war action")
    return values[action_key]


__all__ = [
    "SECT_WAR_CLAIM_HOURS",
    "SECT_WAR_CONTENT_VERSION",
    "SECT_WAR_DURATION_MINUTES",
    "SECT_WAR_KEY",
    "SECT_WAR_MEMBER_REWARD",
    "SECT_WAR_MEMBER_THRESHOLD",
    "SECT_WAR_MAX_PARTICIPANTS",
    "SECT_WAR_MIN_LEVEL",
    "SECT_WAR_REGISTRATION_FEE",
    "SECT_WAR_RULE_VERSION",
    "SECT_WAR_SECT_REWARD",
    "contribution_value",
    "sect_war_round_for_id",
    "sect_war_round_window",
]
