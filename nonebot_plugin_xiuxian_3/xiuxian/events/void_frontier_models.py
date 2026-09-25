"""Transport-neutral records for the v0.5 void-frontier season."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class VoidFrontierStanding:
    board_key: str
    rank: int
    anonymous_label: str
    score: int
    achieved_at: str


@dataclass(frozen=True, slots=True)
class VoidFrontierSeasonRecord:
    season_id: str
    status: str
    starts_at: str
    ends_at: str
    claim_expires_at: str
    frozen_at: str | None
    standings: tuple[VoidFrontierStanding, ...] = field(default_factory=tuple)
    personal_standings: tuple[VoidFrontierStanding, ...] = field(default_factory=tuple)
    sect_standings: tuple[VoidFrontierStanding, ...] = field(default_factory=tuple)
    market_priorities: tuple[VoidFrontierStanding, ...] = field(default_factory=tuple)
    weekly_pending: int = 0
    weekly_claimed: int = 0


@dataclass(frozen=True, slots=True)
class VoidFrontierWeeklyRecord:
    week_id: str
    season_id: str
    reward: dict[str, int]
    status: str
    source_key: str
    already_completed: bool = False


@dataclass(frozen=True, slots=True)
class VoidFrontierClaimRecord:
    season_id: str
    rewards: dict[str, int]
    rank: int
    claimed_at: str
    already_completed: bool = False


__all__ = [
    "VoidFrontierClaimRecord",
    "VoidFrontierSeasonRecord",
    "VoidFrontierStanding",
    "VoidFrontierWeeklyRecord",
]
