"""DTOs for sect-war rounds."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SectWarStanding:
    sect_id: str
    sect_name: str
    score: int
    rank: int


@dataclass(frozen=True, slots=True)
class SectWarRecord:
    round_id: str
    status: str
    registration_open_at: str
    starts_at: str
    ends_at: str
    claim_expires_at: str
    registered: bool
    sect_id: str | None
    sect_name: str | None
    participant_count: int
    player_contribution: int
    standings: tuple[SectWarStanding, ...]
    winner_sect_id: str | None
    already_completed: bool = False


@dataclass(frozen=True, slots=True)
class SectWarClaimRecord:
    round_id: str
    reward: dict[str, int]
    claimed_at: str
    already_completed: bool = False
    expired: bool = False


__all__ = ["SectWarClaimRecord", "SectWarRecord", "SectWarStanding"]
