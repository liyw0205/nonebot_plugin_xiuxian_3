"""Immutable records for 器修机关 (``device.scout_doll``)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class DeviceStatusRecord:
    entity_key: str
    label: str
    description: str
    path_key: str
    owned: int
    max_instances: int
    required_realm: str
    min_layer: int
    qualified: bool
    missing: tuple[str, ...]
    durability_bp: int = 0
    max_durability_bp: int = 0
    status: str = "none"
    deployed: bool = False
    instance_id: str | None = None
    assembly_spirit_stones: int = 0
    assembly_items: dict[str, int] = field(default_factory=dict)
    maintenance_spirit_stones: int = 0
    maintenance_items: dict[str, int] = field(default_factory=dict)
    attack_multiplier_bp: int = 0
    duration_rounds: int = 0
    max_actions_per_battle: int = 0


@dataclass(frozen=True, slots=True)
class DeviceOperationRecord:
    entity_key: str
    label: str
    action: str
    instance_id: str
    durability_bp: int
    max_durability_bp: int
    status: str
    deployed: bool
    spirit_stones_before: int
    spirit_stones_after: int
    items_spent: dict[str, int] = field(default_factory=dict)
    already_completed: bool = False