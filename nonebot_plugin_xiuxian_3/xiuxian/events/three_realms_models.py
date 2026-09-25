"""DTOs for the three-realms temporary season."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ThreeRealmsStanding:
    board_key: str
    board_label: str
    rank: int
    anonymous_label: str
    score: int
    achieved_at: str


@dataclass(frozen=True, slots=True)
class ThreeRealmsSeasonRecord:
    season_id: str
    status: str
    starts_at: str
    ends_at: str
    claim_expires_at: str
    frozen_at: str | None
    standings: tuple[ThreeRealmsStanding, ...]
    personal_standings: tuple[ThreeRealmsStanding, ...]


@dataclass(frozen=True, slots=True)
class ThreeRealmsClaimRecord:
    season_id: str
    rewards: dict[str, int]
    boards: tuple[str, ...]
    claimed_at: str
    already_completed: bool = False
    expired: bool = False


__all__ = ["ThreeRealmsClaimRecord", "ThreeRealmsSeasonRecord", "ThreeRealmsStanding"]
