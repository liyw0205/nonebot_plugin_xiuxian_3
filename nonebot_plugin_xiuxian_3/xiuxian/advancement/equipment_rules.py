"""Data-backed equipment growth definitions and deterministic rolls."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any


from ..content import ContentBundle, ContentError, bundled_content


FLAT_EQUIPMENT_STATS = frozenset(
    {"physical_damage", "max_hp", "initiative", "agility", "max_mana", "hp_regen", "mana_regen"}
)
COMBAT_EQUIPMENT_STATS = frozenset(
    {
        "damage_reduction_bp", "crit_chance_bp", "crit_damage_bp", "evasion_bp", "accuracy_bp",
        "anti_crit_bp", "damage_reflection_bp", "lifesteal_bp", "mana_leech_bp",
        "healing_reduction_bp", "recovery_reduction_bp",
    }
)
EQUIPMENT_SLOTS = frozenset({"weapon", "armor", "accessory"})


@dataclass(frozen=True, slots=True)
class EquipmentDefinition:
    key: str
    label: str
    slot: str
    base_durability_bp: int
    growth: dict[str, Any]
    aliases: tuple[str, ...] = ()
    min_realm_key: str | None = None
    min_layer: int = 1
    path_key: str | None = None

    @property
    def max_temper_level(self) -> int:
        return int(self.growth["temper"]["max_level"])


def _default_content() -> ContentBundle:
    return bundled_content()


def equipment_definitions(content: ContentBundle | None = None) -> dict[str, EquipmentDefinition]:
    bundle = content or _default_content()
    result: dict[str, EquipmentDefinition] = {}
    for row in bundle.list("item", include_locked=False):
        if row.get("item_type") not in {"weapon", "armor", "accessory"}:
            continue
        key = row.get("key")
        name = row.get("name")
        growth = row.get("growth")
        growth_profile_key = row.get("growth_profile_key")
        if growth_profile_key is not None:
            if not isinstance(growth_profile_key, str) or growth is not None:
                raise ContentError(f"equipment {key} must use either growth or growth_profile_key")
            try:
                growth = bundle.require("equipment_growth", growth_profile_key, include_locked=False).get("growth")
            except KeyError as exc:
                raise ContentError(f"equipment {key} references unknown growth profile {growth_profile_key}") from exc
        if not isinstance(key, str) or not isinstance(name, str) or not isinstance(growth, dict):
            raise ContentError(f"equipment item requires key, name and growth configuration: {row!r}")
        slot = row.get("equipment_slot", row.get("item_type"))
        if not isinstance(slot, str) or slot not in EQUIPMENT_SLOTS:
            raise ContentError(f"equipment {key} has an unsupported equipment slot")
        if not isinstance(row.get("desc"), str) or not row["desc"].strip():
            raise ContentError(f"equipment {key} requires desc")
        if row.get("quality") not in {"common", "uncommon", "rare", "heaven", "mythic"}:
            raise ContentError(f"equipment {key} has an invalid quality")
        effects = row.get("effects", [])
        if not isinstance(effects, list):
            raise ContentError(f"equipment {key} effects must be a list")
        for effect in effects:
            if not isinstance(effect, dict):
                raise ContentError(f"equipment {key} has an invalid effect")
            effect_type = effect.get("type")
            stat = effect.get("stat")
            value = effect.get("value")
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ContentError(f"equipment {key} effect value must be a non-negative integer")
            if effect_type == "flat_stat" and stat in FLAT_EQUIPMENT_STATS:
                continue
            if effect_type == "combat_stat_bp" and stat in COMBAT_EQUIPMENT_STATS and value <= 10_000:
                continue
            raise ContentError(f"equipment {key} has an unsupported effect: {effect!r}")
        requirements = row.get("requirements", [])
        if not isinstance(requirements, list):
            raise ContentError(f"equipment {key} requirements must be a list")
        min_realm_key: str | None = None
        min_layer = 1
        for requirement in requirements:
            if not isinstance(requirement, dict) or requirement.get("type") != "realm":
                raise ContentError(f"equipment {key} has an unsupported requirement")
            realm_key = requirement.get("realm_key")
            layer = requirement.get("min_layer", 1)
            realm = bundle.get("realm", realm_key, include_locked=False) if isinstance(realm_key, str) else None
            if realm is None or isinstance(layer, bool) or not isinstance(layer, int):
                raise ContentError(f"equipment {key} has an invalid realm requirement")
            if layer < int(realm.get("layer_min", 1)) or layer > int(realm.get("layer_max", 1)):
                raise ContentError(f"equipment {key} realm layer is outside {realm_key}")
            if min_realm_key is not None:
                raise ContentError(f"equipment {key} can only define one realm requirement")
            min_realm_key = realm_key
            min_layer = layer
        path_key = row.get("path_key")
        if path_key is not None and (not isinstance(path_key, str) or not bundle.has("path", path_key)):
            raise ContentError(f"equipment {key} references an unknown path: {path_key!r}")
        base_durability = row.get("durability_bp")
        if not isinstance(base_durability, int) or base_durability < 0:
            raise ContentError(f"equipment {key} durability_bp must be a non-negative integer")
        temper = growth.get("temper")
        refinement = growth.get("refinement")
        if not isinstance(temper, dict) or not isinstance(refinement, dict):
            raise ContentError(f"equipment {key} requires temper and refinement rules")
        if not isinstance(temper.get("costs"), dict) or not isinstance(temper.get("success_bp"), dict):
            raise ContentError(f"equipment {key} temper requires costs and success_bp")
        if not isinstance(refinement.get("cost"), dict) or not isinstance(refinement.get("affix_pool"), list):
            raise ContentError(f"equipment {key} refinement requires cost and affix_pool")
        max_level = temper.get("max_level")
        if not isinstance(max_level, int) or max_level <= 0:
            raise ContentError(f"equipment {key} temper max_level must be positive")
        levels = {str(level) for level in range(1, max_level + 1)}
        if set(temper["costs"]) != levels or set(temper["success_bp"]) != levels:
            raise ContentError(f"equipment {key} temper must configure every level through max_level")
        for level, costs in temper["costs"].items():
            _validated_costs(costs, key, f"temper level {level}")
            _validate_cost_references(costs, key, bundle)
            _validated_probability(temper["success_bp"][level], key, f"temper level {level}")
        _validated_costs(refinement["cost"], key, "refinement")
        _validate_cost_references(refinement["cost"], key, bundle)
        _validated_probability(refinement.get("success_bp"), key, "refinement")
        pity = refinement.get("pity_failures")
        if not isinstance(pity, int) or pity < 0:
            raise ContentError(f"equipment {key} refinement pity_failures must be non-negative")
        for affix in refinement["affix_pool"]:
            if not isinstance(affix, dict) or not isinstance(affix.get("key"), str):
                raise ContentError(f"equipment {key} has an invalid refinement affix")
            bundle.require("equipment_affix", affix["key"], include_locked=False)
            if not isinstance(affix.get("value"), int):
                raise ContentError(f"equipment {key} affix {affix['key']} value must be an integer")
            if not isinstance(affix.get("weight", 1), int) or affix.get("weight", 1) <= 0:
                raise ContentError(f"equipment {key} affix {affix['key']} weight must be positive")
        if "craft_durability" in growth:
            equipment_initial_durability_bp(0, EquipmentDefinition(
                key=key,
                label=name.strip(),
                slot=slot,
                base_durability_bp=base_durability,
                growth=dict(growth),
                path_key=path_key,
            ))
        aliases = row.get("aliases", [])
        if not isinstance(aliases, list) or any(not isinstance(alias, str) for alias in aliases):
            raise ContentError(f"equipment {key} aliases must be a string list")
        result[key] = EquipmentDefinition(
            key=key,
            label=name.strip(),
            slot=slot,
            base_durability_bp=base_durability,
            growth=dict(growth),
            aliases=tuple(aliases),
            min_realm_key=min_realm_key,
            min_layer=min_layer,
            path_key=path_key,
        )
    return result


def equipment_definition(value: str | None, content: ContentBundle | None = None) -> EquipmentDefinition:
    definitions = EQUIPMENT_DEFINITIONS if content is None else equipment_definitions(content)
    aliases = {
        alias: key
        for key, definition in definitions.items()
        for alias in (key, definition.label, *definition.aliases)
    }
    normalized = (value or "").strip()
    key = aliases.get(normalized, normalized)
    try:
        return definitions[key]
    except KeyError as exc:
        raise ValueError(f"unsupported equipment: {value}") from exc


def equipment_meets_realm(
    definition: EquipmentDefinition,
    realm_key: str,
    realm_layer: int,
    content: ContentBundle | None = None,
) -> bool:
    if definition.min_realm_key is None:
        return True
    bundle = content or _default_content()
    current = bundle.get("realm", realm_key, include_locked=False)
    required = bundle.require("realm", definition.min_realm_key, include_locked=False)
    if current is None:
        return False
    return (int(current.get("rank", -1)), int(realm_layer)) >= (
        int(required.get("rank", -1)),
        definition.min_layer,
    )


def equipment_meets_path(definition: EquipmentDefinition, path_key: str | None) -> bool:
    return definition.path_key is None or definition.path_key == path_key


def temper_cost(target_level: int, definition: EquipmentDefinition) -> dict[str, int]:
    selected = definition
    try:
        costs = selected.growth["temper"]["costs"][str(int(target_level))]
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"unsupported temper level: {target_level}") from exc
    return _validated_costs(costs, selected.key, "temper")


def temper_success_bp(target_level: int, definition: EquipmentDefinition) -> int:
    selected = definition
    try:
        value = selected.growth["temper"]["success_bp"][str(int(target_level))]
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"unsupported temper level: {target_level}") from exc
    return _validated_probability(value, selected.key, "temper")


def refinement_cost(definition: EquipmentDefinition) -> dict[str, int]:
    return _validated_costs(definition.growth["refinement"]["cost"], definition.key, "refinement")


def refinement_success_bp(definition: EquipmentDefinition) -> int:
    return _validated_probability(definition.growth["refinement"].get("success_bp"), definition.key, "refinement")


def refinement_pity_failures(definition: EquipmentDefinition) -> int:
    value = definition.growth["refinement"].get("pity_failures")
    if not isinstance(value, int) or value < 0:
        raise ContentError(f"equipment {definition.key} refinement pity_failures must be non-negative")
    return value


def _validated_costs(value: Any, key: str, operation: str) -> dict[str, int]:
    if not isinstance(value, dict) or not value:
        raise ContentError(f"equipment {key} {operation} cost must be a non-empty object")
    if any(not isinstance(resource, str) or not isinstance(quantity, int) or quantity <= 0 for resource, quantity in value.items()):
        raise ContentError(f"equipment {key} {operation} cost quantities must be positive integers")
    return {str(resource): int(quantity) for resource, quantity in value.items()}


def _validated_probability(value: Any, key: str, operation: str) -> int:
    if not isinstance(value, int) or not 0 <= value <= 10000:
        raise ContentError(f"equipment {key} {operation} success_bp must be between 0 and 10000")
    return value


def _validate_cost_references(costs: dict[str, int], equipment_key: str, content: ContentBundle) -> None:
    for resource_key in costs:
        if resource_key.startswith("item."):
            content.require("item", resource_key, include_locked=False)
        elif resource_key.startswith("currency."):
            resource = content.require("resource", resource_key, include_locked=False)
            if resource.get("storage") != "spirit_stones":
                raise ContentError(f"equipment {equipment_key} currency has unsupported storage: {resource_key}")
        else:
            raise ContentError(f"equipment {equipment_key} uses unsupported cost resource: {resource_key}")


def temper_roll_bp(seed: str) -> int:
    digest = hashlib.blake2b(seed.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big") % 10000


def refinement_roll_bp(seed: str) -> int:
    return temper_roll_bp(f"{seed}:success")


def refinement_affix(seed: str, definition: EquipmentDefinition) -> tuple[str, int]:
    selected = definition
    pool = selected.growth["refinement"]["affix_pool"]
    if not pool:
        raise ContentError(f"equipment {selected.key} refinement affix_pool cannot be empty")
    weights: list[int] = []
    for row in pool:
        if not isinstance(row, dict) or not isinstance(row.get("key"), str) or not isinstance(row.get("value"), int):
            raise ContentError(f"equipment {selected.key} has an invalid refinement affix")
        weight = row.get("weight", 1)
        if not isinstance(weight, int) or weight <= 0:
            raise ContentError(f"equipment {selected.key} affix weight must be positive")
        weights.append(weight)
    roll = int.from_bytes(hashlib.sha256(f"{seed}:affix".encode("utf-8")).digest()[:8], "big") % sum(weights)
    for row, weight in zip(pool, weights):
        roll -= weight
        if roll < 0:
            return str(row["key"]), int(row["value"])
    raise AssertionError("weighted affix selection fell through")


def equipment_resource_label(resource_key: str, content: ContentBundle | None = None) -> str:
    bundle = content or _default_content()
    if resource_key.startswith("item."):
        return bundle.label("item", resource_key)
    if resource_key.startswith("currency."):
        return bundle.label("resource", resource_key)
    raise ContentError(f"unsupported equipment resource key: {resource_key}")


def equipment_affix_label(affix_key: str, content: ContentBundle | None = None) -> str:
    return (content or _default_content()).label("equipment_affix", affix_key)


def equipment_initial_durability_bp(quality: int, definition: EquipmentDefinition) -> int:
    rule = definition.growth.get("craft_durability")
    if rule is None:
        return definition.base_durability_bp
    if not isinstance(rule, dict):
        raise ContentError(f"equipment {definition.key} craft_durability must be an object")
    base = rule.get("base_bp")
    divisor = rule.get("quality_divisor")
    minimum = rule.get("minimum_bp")
    maximum = rule.get("maximum_bp")
    values = (base, divisor, minimum, maximum)
    if any(not isinstance(value, int) for value in values) or divisor <= 0 or minimum < 0 or maximum < minimum:
        raise ContentError(f"equipment {definition.key} has invalid craft_durability values")
    return max(minimum, min(maximum, base + max(0, int(quality)) // divisor))


EQUIPMENT_DEFINITIONS = equipment_definitions()
EQUIPMENT_ALIASES = {
    value: key
    for key, definition in EQUIPMENT_DEFINITIONS.items()
    for value in (key, definition.label, *definition.aliases)
}


__all__ = [
    "COMBAT_EQUIPMENT_STATS",
    "EQUIPMENT_SLOTS",
    "EQUIPMENT_ALIASES",
    "EQUIPMENT_DEFINITIONS",
    "FLAT_EQUIPMENT_STATS",
    "EquipmentDefinition",
    "equipment_affix_label",
    "equipment_definition",
    "equipment_definitions",
    "equipment_initial_durability_bp",
    "equipment_meets_path",
    "equipment_meets_realm",
    "equipment_resource_label",
    "refinement_affix",
    "refinement_cost",
    "refinement_pity_failures",
    "refinement_roll_bp",
    "refinement_success_bp",
    "temper_cost",
    "temper_roll_bp",
    "temper_success_bp",
]
