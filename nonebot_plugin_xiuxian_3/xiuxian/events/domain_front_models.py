"""Transport-neutral records for domain-front activity and season."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class DomainFrontRecord:
    round_id: str
    activity_id: str
    status: str
    activity_starts_at: str
    activity_ends_at: str
    starts_at: str
    ends_at: str
    claim_expires_at: str
    total_contribution: int
    player_contribution: int
    participant: bool
    sect_id: str | None
    domain_key: str | None
    winner_domain: str | None
    success: bool | None
    reward: dict[str, int] = field(default_factory=dict)
    already_completed: bool = False


@dataclass(frozen=True, slots=True)
class DomainFrontSeasonStanding:
    rank: int
    anonymous_label: str
    score: int
    achieved_at: str
    reward: dict[str, int]


@dataclass(frozen=True, slots=True)
class DomainFrontSeasonRecord:
    season_id: str
    status: str
    starts_at: str
    ends_at: str
    claim_expires_at: str
    frozen_at: str | None
    standings: tuple[DomainFrontSeasonStanding, ...]
    personal: DomainFrontSeasonStanding | None


@dataclass(frozen=True, slots=True)
class DomainFrontClaimRecord:
    round_id: str
    reward: dict[str, int]
    already_completed: bool = False


@dataclass(frozen=True, slots=True)
class DomainFrontSeasonClaimRecord:
    season_id: str
    reward: dict[str, int]
    rank: int
    already_completed: bool = False
    expired: bool = False


@dataclass(frozen=True, slots=True)
class DomainCoreRedeemRecord:
    season_id: str
    item_key: str
    quantity: int
    already_completed: bool = False


__all__ = [
    "DomainFrontClaimRecord",
    "DomainFrontRecord",
    "DomainFrontSeasonClaimRecord",
    "DomainFrontSeasonRecord",
    "DomainFrontSeasonStanding",
    "DomainCoreRedeemRecord",
]
