"""Immutable records for void spire previews, runs, and claims."""

from __future__ import annotations

from dataclasses import dataclass, field

from ...contracts import PlayerView


@dataclass(frozen=True, slots=True)
class VoidSpirePreviewRecord:
    player: PlayerView
    highest_floor: int
    next_floor: int
    active_floor: int | None
    active_status: str | None
    stamina_cost: int
    weekly_limit: int
    weekly_used: int
    supply_reputation: int
    dao_service_reputation: int = 0


@dataclass(frozen=True, slots=True)
class VoidSpireRunRecord:
    player: PlayerView
    run_id: str
    tower_key: str
    floor_no: int
    route_key: str
    status: str
    battle_id: str | None
    first_clear: bool
    outcome: str | None = None
    reason: str | None = None
    reward: dict[str, int] = field(default_factory=dict)
    already_completed: bool = False


@dataclass(frozen=True, slots=True)
class VoidSpireRewardRecord:
    player: PlayerView
    run_id: str
    floor_no: int
    route_key: str
    first_clear: bool
    reward: dict[str, int]
    discoveries: tuple[str, ...] = ()
    already_completed: bool = False


__all__ = ["VoidSpirePreviewRecord", "VoidSpireRewardRecord", "VoidSpireRunRecord"]
