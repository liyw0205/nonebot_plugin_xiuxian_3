"""Immutable records exchanged by the exploration application."""

from __future__ import annotations

from dataclasses import dataclass

from ...contracts import PlayerView


@dataclass(frozen=True, slots=True)
class ExplorationDefinition:
    key: str
    label: str
    location_key: str
    duration_seconds: int
    stamina_cost: int
    required_realm: str | None
    required_layer: int
    daily_limit: int
    random_pool: str
    battle_chance_bp: int
    rule_version: str
    energy_cost: int = 0
    content_version: str = "content-0.1"


@dataclass(frozen=True, slots=True)
class ExplorationStartRecord:
    player: PlayerView
    exploration_id: str
    mode_key: str
    location_key: str
    status: str
    starts_at: str
    ends_at: str
    stamina_cost: int
    daily_limit: int
    already_completed: bool = False
    energy_cost: int = 0


@dataclass(frozen=True, slots=True)
class ExplorationSettlementRecord:
    player: PlayerView
    exploration_id: str
    mode_key: str
    location_key: str
    status: str
    result: dict[str, int]
    battle_pending: bool
    expired: bool
    stamina_cost: int
    battle_id: str | None = None
    battle_outcome: str | None = None
    already_completed: bool = False
    energy_cost: int = 0
    content_version: str = "content-0.1"
    storm_pending: bool = False
    storm_options: tuple[str, ...] = ()
    storm_deadline: str | None = None
    storm_choice: str | None = None
