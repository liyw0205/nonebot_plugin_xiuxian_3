"""Immutable records for 道统路线议事."""

from __future__ import annotations

from dataclasses import dataclass, field

from .dao_route_rules import DaoRouteOption


@dataclass(frozen=True, slots=True)
class DaoRouteState:
    sect_id: str
    sect_name: str
    sect_level: int
    sect_merit: int
    route_key: str | None
    route_label: str | None
    locked_until: str | None
    locked: bool
    cycle_id: str
    cycle_starts_at: str
    cycle_ends_at: str
    settled: bool
    quorum: int
    voter_count: int
    my_vote_key: str | None
    my_vote_label: str | None
    eligible: bool
    missing: tuple[str, ...]
    options: tuple[DaoRouteOption, ...] = ()
    tie_carryover: bool = False


@dataclass(frozen=True, slots=True)
class DaoRouteVoteRecord:
    sect_id: str
    cycle_id: str
    route_key: str
    route_label: str
    voter_count: int
    already_completed: bool = False


@dataclass(frozen=True, slots=True)
class DaoRouteSettlementRecord:
    sect_id: str
    cycle_id: str
    route_key: str | None
    route_label: str | None
    tie_carryover: bool
    voter_count: int
    sect_merit_spent: int
    sect_merit_after: int
    locked_until: str | None
    already_completed: bool = False
    options: tuple[DaoRouteOption, ...] = field(default_factory=tuple)
    quorum_missing: bool = False