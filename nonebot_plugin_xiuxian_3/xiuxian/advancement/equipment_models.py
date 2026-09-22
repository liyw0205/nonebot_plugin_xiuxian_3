"""Immutable records exchanged by the v0.1 equipment growth use cases."""

from __future__ import annotations

from dataclasses import dataclass, field

from ...contracts import PlayerView


@dataclass(frozen=True, slots=True)
class EquipmentRecord:
    instance_id: str
    item_key: str
    label: str
    slot: str
    status: str
    durability_bp: int
    temper_level: int
    max_temper_level: int
    affixes: dict[str, int] = field(default_factory=dict)
    refinement_failure_streak: int = 0


@dataclass(frozen=True, slots=True)
class TemperingRecord:
    player: PlayerView
    equipment: EquipmentRecord
    from_level: int
    to_level: int
    success: bool
    roll_bp: int
    success_bp: int
    material_key: str
    material_spent: int
    spirit_stones_spent: int
    already_completed: bool = False


@dataclass(frozen=True, slots=True)
class RefinementRecord:
    player: PlayerView
    equipment: EquipmentRecord
    old_affixes: dict[str, int]
    new_affixes: dict[str, int]
    success: bool
    roll_bp: int
    success_bp: int
    material_key: str
    material_spent: int
    spirit_stones_spent: int
    failure_streak_before: int
    failure_streak_after: int
    already_completed: bool = False


__all__ = ["EquipmentRecord", "RefinementRecord", "TemperingRecord"]
