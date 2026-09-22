"""Immutable records for v0.5 void-route sessions."""

from __future__ import annotations

from dataclasses import dataclass

from ...contracts import PlayerView


@dataclass(frozen=True, slots=True)
class VoidRouteDefinition:
    key: str
    label: str
    duration_seconds: int
    stamina_cost: int
    anchor_cost: int
    random_pool: str


@dataclass(frozen=True, slots=True)
class VoidRouteStartRecord:
    player: PlayerView
    session_id: str
    route_key: str
    status: str
    starts_at: str
    ends_at: str
    anchor_cost: int
    stamina_cost: int
    space_resistance_bp: int
    storm_roll_bp: int
    already_completed: bool = False


@dataclass(frozen=True, slots=True)
class VoidRouteSettlementRecord:
    player: PlayerView
    session_id: str
    route_key: str
    status: str
    reward: dict[str, int]
    storm: bool
    extra_anchor_lost: int
    already_completed: bool = False
