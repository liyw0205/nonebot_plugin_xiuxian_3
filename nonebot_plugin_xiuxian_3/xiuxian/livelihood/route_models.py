"""Application records for short-haul livelihood routes."""

from __future__ import annotations

from dataclasses import dataclass, field

from ...contracts import PlayerView


@dataclass(frozen=True, slots=True)
class RoutePreviewRecord:
    player: PlayerView
    route_key: str
    route_name: str
    source_location: str
    destination_location: str
    cargo_key: str
    cargo_quantity: int
    cargo_value: int
    stamina_cost: int
    duration_seconds: int
    daily_used: int
    daily_limit: int
    ready: bool
    missing: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RouteStartRecord:
    player: PlayerView
    route_id: str
    route_key: str
    route_name: str
    cargo_key: str
    cargo_quantity: int
    cargo_value: int
    source_location: str
    destination_location: str
    status: str
    starts_at: str
    arrives_at: str
    stamina_cost: int
    reward_stones: int
    delay_seconds: int = 0
    already_completed: bool = False


@dataclass(frozen=True, slots=True)
class RouteSettlementRecord:
    player: PlayerView
    route_id: str
    route_key: str
    route_name: str
    cargo_key: str
    cargo_quantity: int
    status: str
    reward_stones: int
    local_reputation_delta: int
    delay_seconds: int = 0
    already_completed: bool = False
    cargo: dict[str, int] = field(default_factory=dict)


__all__ = ["RoutePreviewRecord", "RouteSettlementRecord", "RouteStartRecord"]
