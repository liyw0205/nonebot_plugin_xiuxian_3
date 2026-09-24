"""DTOs for final-heaven season rankings and claims."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FinalHeavenStanding:
    board_key: str
    board_label: str
    rank: int
    anonymous_label: str
    score: int
    achieved_at: str
    title_key: str | None = None


@dataclass(frozen=True, slots=True)
class FinalHeavenSeasonRecord:
    season_id: str
    status: str
    starts_at: str
    ends_at: str
    claim_expires_at: str
    frozen_at: str | None
    standings: tuple[FinalHeavenStanding, ...]
    personal_standings: tuple[FinalHeavenStanding, ...]


@dataclass(frozen=True, slots=True)
class FinalHeavenClaimRecord:
    season_id: str
    title_keys: tuple[str, ...]
    entitlements: tuple[str, ...]
    claimed_at: str
    already_completed: bool = False
    expired: bool = False


__all__ = [
    "FinalHeavenClaimRecord",
    "FinalHeavenSeasonRecord",
    "FinalHeavenStanding",
]
