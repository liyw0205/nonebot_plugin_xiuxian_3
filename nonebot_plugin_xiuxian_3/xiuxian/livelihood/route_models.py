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
    cargo_name: str
    cargo_quantity: int
    cargo_value: int
    stamina_cost: int
    duration_seconds: int
    daily_used: int
    daily_limit: int
    ready: bool
    missing: tuple[str, ...] = ()
    mount_instance_id: str | None = None
    mount_name: str | None = None
    mount_level: int | None = None
    mount_stamina: int | None = None
    mount_stamina_cost: int = 0
    duration_seconds_with_mount: int | None = None


@dataclass(frozen=True, slots=True)
class RouteStartRecord:
    player: PlayerView
    route_id: str
    route_key: str
    route_name: str
    cargo_key: str
    cargo_name: str
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
    mount_instance_id: str | None = None
    mount_name: str | None = None
    mount_level: int | None = None
    mount_stamina_cost: int = 0


@dataclass(frozen=True, slots=True)
class RouteSettlementRecord:
    player: PlayerView
    route_id: str
    route_key: str
    route_name: str
    cargo_key: str
    cargo_name: str
    cargo_quantity: int
    status: str
    reward_stones: int
    local_reputation_delta: int
    local_reputation_before: int
    local_reputation_after: int
    delay_seconds: int = 0
    already_completed: bool = False
    cargo: dict[str, int] = field(default_factory=dict)
    mount_instance_id: str | None = None
    mount_name: str | None = None
    mount_level: int | None = None
    mount_experience: int = 0
    mount_level_after: int | None = None


__all__ = ["RoutePreviewRecord", "RouteSettlementRecord", "RouteStartRecord"]
