"""Rules for the v0.5 cross-server sect-war slice."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


CROSS_SERVER_CONTENT_VERSION = "content-0.5"
CROSS_SERVER_RULE_VERSION = "social-0.5.0"
CROSS_SERVER_MIN_SECT_LEVEL = 5
CROSS_SERVER_FORTRESS_ANCHOR_COST = 20
CROSS_SERVER_FORTRESS_BUILD_COST = 10_000
CROSS_SERVER_FORTRESS_BUILD_SECONDS = 48 * 60 * 60
CROSS_SERVER_FORTRESS_MAINTENANCE_ANCHOR_COST = 2
CROSS_SERVER_REGISTRATION_FEE = 5_000
CROSS_SERVER_REGISTRATION_CAP = 30
CROSS_SERVER_ROSTER_CAP = 15
CROSS_SERVER_WAR_SECONDS = 30 * 60
CROSS_SERVER_CLAIM_SECONDS = 7 * 24 * 60 * 60
CROSS_SERVER_ENGINE_HP = 50_000
CROSS_SERVER_MEMBER_MERIT = 20
CROSS_SERVER_SCORE_BY_ACTION = {"占点": 10, "击败": 5, "摧毁战争机关": 30}
CROSS_SERVER_TOP_REWARDS = (10, 6, 3)


@dataclass(frozen=True, slots=True)
class CrossServerRoundWindow:
    round_id: str
    week_id: str
    registration_open_at: datetime
    starts_at: datetime
    ends_at: datetime
    claim_expires_at: datetime


def cross_server_round_for_id(round_id: str, *, now: datetime) -> CrossServerRoundWindow:
    """Resolve a stable weekly round, accepting only the documented key shape."""

    if not round_id.startswith("sect_war.cross:"):
        raise ValueError("invalid cross-server sect-war round")
    week_id = round_id.removeprefix("sect_war.cross:")
    try:
        year, week = (int(part) for part in week_id.split("-W", 1))
        anchor = datetime.fromisocalendar(year, week, 1).replace(tzinfo=timezone.utc)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid cross-server sect-war week") from exc
    starts = anchor + timedelta(days=6, hours=20)
    return CrossServerRoundWindow(
        round_id=round_id,
        week_id=week_id,
        registration_open_at=anchor,
        starts_at=starts,
        ends_at=starts + timedelta(seconds=CROSS_SERVER_WAR_SECONDS),
        claim_expires_at=starts + timedelta(seconds=CROSS_SERVER_WAR_SECONDS + CROSS_SERVER_CLAIM_SECONDS),
    )


def current_cross_server_round(now: datetime) -> CrossServerRoundWindow:
    value = now.astimezone(timezone.utc)
    iso = value.isocalendar()
    round_id = f"sect_war.cross:{iso.year:04d}-W{iso.week:02d}"
    return cross_server_round_for_id(round_id, now=value)


def top_reward_for_rank(rank: int) -> int:
    return CROSS_SERVER_TOP_REWARDS[rank - 1] if 1 <= rank <= len(CROSS_SERVER_TOP_REWARDS) else 0


__all__ = [
    "CROSS_SERVER_CLAIM_SECONDS",
    "CROSS_SERVER_CONTENT_VERSION",
    "CROSS_SERVER_ENGINE_HP",
    "CROSS_SERVER_FORTRESS_ANCHOR_COST",
    "CROSS_SERVER_FORTRESS_BUILD_COST",
    "CROSS_SERVER_FORTRESS_BUILD_SECONDS",
    "CROSS_SERVER_FORTRESS_MAINTENANCE_ANCHOR_COST",
    "CROSS_SERVER_MEMBER_MERIT",
    "CROSS_SERVER_MIN_SECT_LEVEL",
    "CROSS_SERVER_REGISTRATION_CAP",
    "CROSS_SERVER_REGISTRATION_FEE",
    "CROSS_SERVER_ROSTER_CAP",
    "CROSS_SERVER_RULE_VERSION",
    "CROSS_SERVER_SCORE_BY_ACTION",
    "CROSS_SERVER_TOP_REWARDS",
    "CROSS_SERVER_WAR_SECONDS",
    "CrossServerRoundWindow",
    "cross_server_round_for_id",
    "current_cross_server_round",
    "top_reward_for_rank",
]
