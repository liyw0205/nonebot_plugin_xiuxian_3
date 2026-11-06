"""Immutable records for the 留界据点 (``settlement.dao_hall``)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DaoHallState:
    hall_id: str
    name: str
    status: str
    founder_player_id: int
    core_members: int
    core_capacity: int
    treasury_spirit_stones: int
    contributed_world_merit: int
    built_project_keys: tuple[str, ...]
    rebuild_ends_at: str | None
    next_maintenance_at: str
    maintenance_due: int
    founding_cost_world_merit: int
    founding_cost_spirit_stones: int
    ending_key: str | None
    world_merit: int
    spirit_stones: int
    is_member: bool
    role: str | None
    qualified: bool
    missing: tuple[str, ...]
    construction_project_key: str | None = None
    construction_ends_at: str | None = None


@dataclass(frozen=True, slots=True)
class DaoHallOperationRecord:
    hall_id: str
    action: str
    status: str
    core_members: int
    core_capacity: int
    treasury_spirit_stones: int
    world_merit: int
    world_merit_after: int
    spirit_stones_after: int
    project_key: str | None = None
    world_merit_spent: int = 0
    spirit_stones_spent: int = 0
    rebuild_ends_at: str | None = None
    build_ends_at: str | None = None
    already_completed: bool = False