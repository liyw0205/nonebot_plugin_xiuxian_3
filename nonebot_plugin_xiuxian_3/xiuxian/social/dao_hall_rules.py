"""Rules for the 留界据点 (``settlement.dao_hall``).

The hall is a single-server social structure: one founder, at most
``core_capacity`` core seats, a weekly maintenance bill paid from the hall
treasury and a ``rebuild_hours`` window during which the hall keeps its members
but refuses new construction.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from ..content import ContentBundle
from ..world.rules import meets_realm
from .dao_hall_content import dao_hall_defaults, dao_hall_projects


@dataclass(frozen=True, slots=True)
class DaoHallDefinition:
    name: str
    description: str
    required_ending: str
    required_world_merit: int
    spirit_stones: int
    core_capacity: int
    maintenance_spirit_stones: int
    maintenance_period_days: int
    rebuild_hours: int
    core_required_realms: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DaoHallProject:
    key: str
    name: str
    description: str
    world_merit: int
    build_hours: int
    required_project_keys: tuple[str, ...]
    effects: dict[str, int] = field(default_factory=dict)


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
    already_completed: bool = False


def dao_hall_definition(content: ContentBundle) -> DaoHallDefinition:
    raw = dao_hall_defaults(content)
    return DaoHallDefinition(
        name=str(raw["name"]),
        description=str(raw["description"]),
        required_ending=str(raw["required_ending"]),
        required_world_merit=int(raw["required_world_merit"]),
        spirit_stones=int(raw["spirit_stones"]),
        core_capacity=int(raw["core_capacity"]),
        maintenance_spirit_stones=int(raw["maintenance_spirit_stones"]),
        maintenance_period_days=int(raw["maintenance_period_days"]),
        rebuild_hours=int(raw["rebuild_hours"]),
        core_required_realms=tuple(raw["core_required_realms"]),
    )


def dao_hall_project_list(content: ContentBundle) -> tuple[DaoHallProject, ...]:
    return tuple(
        DaoHallProject(
            key=str(raw["key"]),
            name=str(raw["name"]),
            description=str(raw["description"]),
            world_merit=int(raw["world_merit"]),
            build_hours=int(raw["build_hours"]),
            required_project_keys=tuple(raw["required_project_keys"]),
            effects=dict(raw["effects"]),
        )
        for raw in dao_hall_projects(content).values()
    )


def dao_hall_project(content: ContentBundle, key: str) -> DaoHallProject:
    for project in dao_hall_project_list(content):
        if project.key == key:
            return project
    raise KeyError(key)


def effective_core_capacity(
    *, definition: DaoHallDefinition, built: tuple[str, ...], content: ContentBundle
) -> int:
    bonus = 0
    for project in dao_hall_project_list(content):
        if project.key in built:
            bonus += project.effects.get("core_capacity_bonus", 0)
    return definition.core_capacity + bonus


def maintenance_cost(
    *, definition: DaoHallDefinition, built: tuple[str, ...], content: ContentBundle
) -> int:
    cost = definition.maintenance_spirit_stones
    reduction = 0
    for project in dao_hall_project_list(content):
        if project.key in built:
            reduction += project.effects.get("maintenance_discount_bp", 0)
    if reduction:
        cost = cost * (10_000 - min(9_000, reduction)) // 10_000
    return max(0, cost)


def rebuild_hours(
    *, definition: DaoHallDefinition, built: tuple[str, ...], content: ContentBundle
) -> int:
    hours = definition.rebuild_hours
    for project in dao_hall_project_list(content):
        if project.key in built:
            hours -= project.effects.get("rebuild_hours_reduction", 0)
    return max(1, hours)


def maintenance_due_at(*, last_maintained_at: datetime, definition: DaoHallDefinition) -> datetime:
    return last_maintained_at + timedelta(days=definition.maintenance_period_days)


def founding_missing_requirements(
    *,
    definition: DaoHallDefinition,
    ending_key: str | None,
    world_merit: int,
    spirit_stones: int,
    already_member: bool,
) -> list[str]:
    """Return every unmet founding prerequisite in player-facing wording."""

    missing: list[str] = []
    if ending_key != definition.required_ending:
        missing.append("留界结局")
    if already_member:
        missing.append("已加入其他据点")
    if world_merit < definition.required_world_merit:
        missing.append(f"世界功勋 {definition.required_world_merit}")
    if spirit_stones < definition.spirit_stones:
        missing.append(f"灵石 {definition.spirit_stones}")
    return missing


def core_seat_available(
    *,
    definition: DaoHallDefinition,
    built: tuple[str, ...],
    content: ContentBundle,
    core_members: int,
) -> bool:
    return core_members < effective_core_capacity(
        definition=definition, built=built, content=content
    )


def can_hold_core_seat(
    *,
    definition: DaoHallDefinition,
    realm_key: str,
    realm_layer: int,
    ending_key: str | None,
) -> bool:
    """Core seats require 渡劫 (or deeper) or a recorded ``remain_in_world`` ending."""

    if ending_key == definition.required_ending:
        return True
    for required in definition.core_required_realms:
        if meets_realm(realm_key, realm_layer, required, 1):
            return True
    return False


def project_locked(
    *, project: DaoHallProject, built: tuple[str, ...]
) -> bool:
    return any(key not in built for key in project.required_project_keys)


def project_already_built(*, project: DaoHallProject, built: tuple[str, ...]) -> bool:
    return project.key in built