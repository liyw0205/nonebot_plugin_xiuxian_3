"""Rules for the 器修机关 (``device.scout_doll``).

Foundation docs freeze the shape: one device per cultivator, attack equal to
50% of the player's, three rounds of participation, plus durability and
repair.  The battle core already models a player-side actor, so the device is
expressed as extra player actions inside the same turn loop rather than as a
second combat engine.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..content import ContentBundle
from ..world.rules import meets_realm
from .entity_content import entity_alias_map, entity_definitions, resolve_entity_key

DEFAULT_ENTITY_KEY = "device.scout_doll"
STRATEGY_KEY = "strategy.device.scout_doll"


@dataclass(frozen=True, slots=True)
class DeviceDefinition:
    key: str
    label: str
    description: str
    aliases: tuple[str, ...]
    entity_type: str
    status: str
    owner_path_key: str
    max_instances: int
    required_realm: str
    min_layer: int
    assembly_spirit_stones: int
    assembly_items: dict[str, int]
    maintenance_spirit_stones: int
    maintenance_items: dict[str, int]
    max_durability_bp: int
    loss_per_action_bp: int
    repair_bp_per_material: int
    attack_multiplier_bp: int
    duration_rounds: int
    max_actions_per_battle: int
    codex_entry_key: str | None


@dataclass(frozen=True, slots=True)
class DeviceView:
    """One owned device instance as the player sees it."""

    instance_id: str
    entity_key: str
    label: str
    durability_bp: int
    max_durability_bp: int
    status: str
    deployed: bool


def _definition(raw: dict[str, Any]) -> DeviceDefinition:
    return DeviceDefinition(
        key=str(raw["key"]),
        label=str(raw["name"]),
        description=str(raw["desc"]),
        aliases=tuple(raw["aliases"]),
        entity_type=str(raw["entity_type"]),
        status=str(raw["status"]),
        owner_path_key=str(raw["owner_path_key"]),
        max_instances=int(raw["max_instances"]),
        required_realm=str(raw["required_realm"]),
        min_layer=int(raw["min_layer"]),
        assembly_spirit_stones=int(raw["assembly"]["spirit_stones"]),
        assembly_items=dict(raw["assembly"]["items"]),
        maintenance_spirit_stones=int(raw["maintenance"]["spirit_stones"]),
        maintenance_items=dict(raw["maintenance"]["items"]),
        max_durability_bp=int(raw["durability"]["max_bp"]),
        loss_per_action_bp=int(raw["durability"]["loss_per_action_bp"]),
        repair_bp_per_material=int(raw["durability"]["repair_bp_per_material"]),
        attack_multiplier_bp=int(raw["combat"]["attack_multiplier_bp"]),
        duration_rounds=int(raw["combat"]["duration_rounds"]),
        max_actions_per_battle=int(raw["combat"]["max_actions_per_battle"]),
        codex_entry_key=raw.get("codex_entry_key"),
    )


def device_definitions(content: ContentBundle) -> dict[str, DeviceDefinition]:
    """Return every validated device definition keyed by its stable key."""

    return {
        key: _definition(raw) for key, raw in entity_definitions(content).items()
    }


def device_definition(
    content: ContentBundle, key: str = DEFAULT_ENTITY_KEY
) -> DeviceDefinition:
    definitions = device_definitions(content)
    entry = definitions.get(key)
    if entry is None:
        raise KeyError(key)
    return entry


def device_alias_map(content: ContentBundle) -> dict[str, str]:
    return entity_alias_map(content)


def resolve_device_key(content: ContentBundle, value: str | None) -> str | None:
    return resolve_entity_key(value, content)


def device_missing_requirements(
    *, definition: DeviceDefinition, path_key: str, realm_key: str, realm_layer: int
) -> list[str]:
    """Return every unmet assembly prerequisite in player-facing wording."""

    missing: list[str] = []
    if definition.status != "active":
        missing.append("机关尚未开放")
    if path_key != definition.owner_path_key:
        missing.append(f"需{definition.owner_path_key}道途")
    if not meets_realm(realm_key, realm_layer, definition.required_realm, definition.min_layer):
        missing.append("境界要求")
    return missing


def durability_after(*, current_bp: int, actions: int, definition: DeviceDefinition) -> int:
    """Return the durability left after ``actions`` device strikes."""

    loss = max(0, int(actions)) * definition.loss_per_action_bp
    return max(0, min(definition.max_durability_bp, int(current_bp) - loss))


def repair_steps_missing(*, current_bp: int, definition: DeviceDefinition) -> int:
    """Return how many repair steps a full restoration would need."""

    deficit = max(0, definition.max_durability_bp - int(current_bp))
    if deficit == 0:
        return 0
    return max(1, -(-deficit // definition.repair_bp_per_material))


def device_action_plan(
    *, definition: DeviceDefinition, rounds_elapsed: int
) -> tuple[bool, int]:
    """Return ``(may_act, actions_used)`` for one already-run round window."""

    used = min(definition.max_actions_per_battle, max(0, rounds_elapsed))
    return used < definition.max_actions_per_battle, used


def plan_actions(
    *, duration_rounds: int, max_actions_per_battle: int, used_actions: int, round_no: int
) -> bool:
    """Return whether the device may strike in ``round_no``.

    The device acts in the first ``duration_rounds`` rounds of the battle and
    at most ``max_actions_per_battle`` times overall, so a short fight cannot
    bank unused strikes and a long one cannot exceed the frozen cap.  The
    battle core calls this with the frozen snapshot numbers, which keeps the
    turn loop free of a second definition lookup.
    """

    if round_no < 1 or round_no > int(duration_rounds):
        return False
    return int(used_actions) < int(max_actions_per_battle)


def device_view(
    *, instance_id: str, definition: DeviceDefinition, durability_bp: int,
    status: str, deployed: bool
) -> DeviceView:
    return DeviceView(
        instance_id=instance_id,
        entity_key=definition.key,
        label=definition.label,
        durability_bp=int(durability_bp),
        max_durability_bp=definition.max_durability_bp,
        status=str(status),
        deployed=bool(deployed),
    )


def device_frozen_snapshot(
    *,
    definition: DeviceDefinition,
    instance_id: str,
    durability_bp: int,
) -> dict[str, Any]:
    """Freeze a deployed device into a battle snapshot.

    Snapshots are written once at battle start, so the repository must be able
    to settle durability from the frozen numbers alone: the instance id, the
    per-action loss and the caps all travel with the battle.
    """

    return {
        "instance_id": str(instance_id),
        "entity_key": definition.key,
        "label": definition.label,
        "durability_bp": int(durability_bp),
        "max_durability_bp": definition.max_durability_bp,
        "attack_multiplier_bp": definition.attack_multiplier_bp,
        "duration_rounds": definition.duration_rounds,
        "max_actions_per_battle": definition.max_actions_per_battle,
        "loss_per_action_bp": definition.loss_per_action_bp,
    }