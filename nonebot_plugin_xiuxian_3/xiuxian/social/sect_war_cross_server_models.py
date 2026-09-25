"""DTOs for the cross-server sect-war application boundary."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class CrossServerFortressRecord:
    sect_id: str
    status: str
    anchors: int
    build_ends_at: str | None
    maintenance_due_at: str | None
    already_completed: bool = False


@dataclass(frozen=True, slots=True)
class CrossServerStanding:
    sect_id: str
    sect_name: str
    score: int
    rank: int
    winner: bool = False


@dataclass(frozen=True, slots=True)
class CrossServerWarRecord:
    round_id: str
    status: str
    registration_open_at: str
    starts_at: str
    ends_at: str
    claim_expires_at: str
    registered: bool
    sect_id: str | None
    sect_name: str | None
    roster_size: int
    score: int
    session_status: str | None
    engine_hp: int | None
    branch_key: str | None
    standings: tuple[CrossServerStanding, ...] = field(default_factory=tuple)
    already_completed: bool = False


@dataclass(frozen=True, slots=True)
class CrossServerRewardRecord:
    round_id: str
    sect_id: str
    reward: dict[str, int]
    status: str
    already_completed: bool = False


__all__ = [
    "CrossServerFortressRecord",
    "CrossServerRewardRecord",
    "CrossServerStanding",
    "CrossServerWarRecord",
]
