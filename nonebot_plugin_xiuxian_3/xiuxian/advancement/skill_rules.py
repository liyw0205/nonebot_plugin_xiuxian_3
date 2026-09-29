"""Data-backed skill mastery definitions and generic mastery calculations."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping

from ..content import ContentBundle, ContentError, bundled_content


@dataclass(frozen=True, slots=True)
class SkillDefinition:
    key: str
    label: str
    path_key: str | None
    effect: dict[str, Any]
    description: str
    max_level: int
    level_costs: dict[int, dict[str, int]]
    effect_deltas: dict[str, int]
    status: str = "active"
    min_realm_key: str | None = None
    min_layer: int = 1
    style_key: str = "attack"
    style_label: str = "攻势"
    combat_effect: dict[str, Any] | None = None
    acquisition_item_key: str | None = None


SKILL_STYLES = frozenset(
    {"attack", "burst", "support", "sustained", "negative", "charge", "poison", "burn", "reflect"}
)


def _default_content() -> ContentBundle:
    return bundled_content()


def skill_definitions(content: ContentBundle | None = None) -> dict[str, SkillDefinition]:
    bundle = content or _default_content()
    growth_rows = {row["key"]: row for row in bundle.list("skill_growth")}
    definitions: dict[str, SkillDefinition] = {}
    player_skills = {
        row["key"]: row
        for row in bundle.list("skill")
        if row.get("owner_type") == "player"
    }
    orphan_growth = set(growth_rows) - set(player_skills)
    if orphan_growth:
        raise ContentError(f"skill_growth references unknown player skills: {sorted(orphan_growth)}")

    for key, row in player_skills.items():
        name = row.get("name")
        description = row.get("desc")
        effect = row.get("effect")
        growth = growth_rows.get(key)
        if (
            not isinstance(key, str)
            or not isinstance(name, str)
            or not name.strip()
            or not isinstance(description, str)
            or not description.strip()
        ):
            raise ContentError(f"player skill requires key, name and desc: {row!r}")
        if not isinstance(effect, dict) or growth is None:
            raise ContentError(f"player skill {key} requires effect and skill_growth record")
        path_key = row.get("path_key")
        if path_key is not None:
            if not isinstance(path_key, str) or not bundle.has("path", path_key):
                raise ContentError(f"player skill {key} references an unknown path: {path_key!r}")
        min_realm_key = row.get("min_realm_key")
        min_layer = row.get("min_layer", 1)
        if min_realm_key is not None:
            realm = bundle.get("realm", min_realm_key, include_locked=False)
            if realm is None:
                raise ContentError(f"player skill {key} references an unknown minimum realm: {min_realm_key!r}")
            if isinstance(min_layer, bool) or not isinstance(min_layer, int):
                raise ContentError(f"player skill {key} min_layer must be an integer")
            if min_layer < int(realm.get("layer_min", 1)) or min_layer > int(realm.get("layer_max", 1)):
                raise ContentError(f"player skill {key} min_layer is outside realm {min_realm_key}")
        elif "min_layer" in row:
            raise ContentError(f"player skill {key} min_layer requires min_realm_key")
        status = row.get("status")
        if not isinstance(status, str) or status not in {"active", "open", "locked"}:
            raise ContentError(f"player skill {key} has an invalid status: {status!r}")
        style = row.get("combat_style")
        if not isinstance(style, dict):
            raise ContentError(f"player skill {key} combat_style must be an object")
        style_key = style.get("key")
        style_label = style.get("name")
        combat_effect = style.get("effect", {})
        if (
            not isinstance(style_key, str)
            or style_key not in SKILL_STYLES
            or not isinstance(style_label, str)
            or not style_label.strip()
        ):
            raise ContentError(f"player skill {key} has an invalid combat style")
        if not isinstance(combat_effect, dict):
            raise ContentError(f"player skill {key} combat_style.effect must be an object")
        required_style_fields = {
            "attack": set(),
            "burst": {"hit_penalty_bp"},
            "support": {"damage_reduction_bp", "duration_rounds"},
            "sustained": {"damage_over_time_bp", "duration_rounds"},
            "negative": {"enemy_attack_reduction_bp", "duration_rounds"},
            "charge": {"charge_multiplier_bp"},
            "poison": {"damage_over_time_bp", "enemy_attack_reduction_bp", "duration_rounds"},
            "burn": {"damage_over_time_bp", "duration_rounds"},
            "reflect": {"damage_reflection_bp", "duration_rounds"},
        }[style_key]
        if not required_style_fields <= set(combat_effect):
            raise ContentError(f"player skill {key} combat style is missing effect fields")
        for field, value in combat_effect.items():
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ContentError(f"player skill {key} combat style field {field} must be a non-negative integer")
        if style_key == "burst" and combat_effect["hit_penalty_bp"] > 5_000:
            raise ContentError(f"player skill {key} burst hit penalty is too large")
        if style_key == "support" and combat_effect["damage_reduction_bp"] > 5_000:
            raise ContentError(f"player skill {key} support reduction is too large")
        if style_key == "sustained" and combat_effect["damage_over_time_bp"] > 10_000:
            raise ContentError(f"player skill {key} sustained damage is too large")
        if style_key == "negative" and combat_effect["enemy_attack_reduction_bp"] > 5_000:
            raise ContentError(f"player skill {key} enemy attack reduction is too large")
        if style_key == "charge" and combat_effect["charge_multiplier_bp"] < 10_000:
            raise ContentError(f"player skill {key} charge multiplier must be at least 10000")
        if style_key == "poison" and (
            combat_effect["damage_over_time_bp"] > 10_000
            or combat_effect["enemy_attack_reduction_bp"] > 5_000
        ):
            raise ContentError(f"player skill {key} poison effect is too large")
        if style_key == "burn" and combat_effect["damage_over_time_bp"] > 10_000:
            raise ContentError(f"player skill {key} burn damage is too large")
        if style_key == "reflect" and combat_effect["damage_reflection_bp"] > 5_000:
            raise ContentError(f"player skill {key} reflection is too large")
        duration = combat_effect.get("duration_rounds")
        if duration is not None and not 1 <= duration <= 5:
            raise ContentError(f"player skill {key} combat style duration must be 1..5 rounds")
        acquisition_item_key = row.get("acquisition_item_key")
        if acquisition_item_key is not None:
            if not isinstance(acquisition_item_key, str) or not bundle.has("item", acquisition_item_key):
                raise ContentError(f"player skill {key} references an unknown acquisition item")
        cost_rows = growth.get("cost_by_target_level")
        growth_values = growth.get("growth")
        max_level = growth.get("max_level")
        if not isinstance(cost_rows, dict) or not isinstance(growth_values, dict):
            raise ContentError(f"skill_growth {key} requires cost_by_target_level and growth")
        if isinstance(max_level, bool) or not isinstance(max_level, int) or max_level <= 0:
            raise ContentError(f"skill_growth {key} max_level must be positive")
        effect_deltas = growth_values.get("effect_fields")
        if not isinstance(effect_deltas, dict) or not effect_deltas:
            raise ContentError(f"skill_growth {key} requires non-empty growth.effect_fields")
        normalized_deltas: dict[str, int] = {}
        for field, delta in effect_deltas.items():
            if not isinstance(field, str) or not field:
                raise ContentError(f"skill_growth {key} has an invalid effect field")
            if field not in effect or isinstance(effect[field], bool) or not isinstance(effect[field], int):
                raise ContentError(f"skill_growth {key} effect field {field} must reference an integer skill effect")
            if isinstance(delta, bool) or not isinstance(delta, int):
                raise ContentError(f"skill_growth {key} effect delta for {field} must be an integer")
            normalized_deltas[field] = delta
        costs: dict[int, dict[str, int]] = {}
        for raw_level, cost in cost_rows.items():
            try:
                level = int(raw_level)
            except (TypeError, ValueError) as exc:
                raise ContentError(f"skill_growth {key} has invalid target level: {raw_level}") from exc
            if level in costs:
                raise ContentError(f"skill_growth {key} has duplicate target level: {level}")
            if not isinstance(cost, dict):
                raise ContentError(f"skill_growth {key} level {level} cost must be an object")
            if not cost:
                raise ContentError(f"skill_growth {key} level {level} cost cannot be empty")
            costs[level] = {}
            for resource_key, amount in cost.items():
                if (
                    not isinstance(resource_key, str)
                    or isinstance(amount, bool)
                    or not isinstance(amount, int)
                    or amount < 0
                ):
                    raise ContentError(f"skill_growth {key} level {level} has invalid costs")
                skill_resource_definition(resource_key, bundle)
                costs[level][resource_key] = amount
        if set(costs) != set(range(1, max_level + 1)):
            raise ContentError(f"skill_growth {key} must configure every level through max_level")
        definitions[key] = SkillDefinition(
            key=key,
            label=name.strip(),
            path_key=path_key,
            effect=dict(effect),
            description=description.strip(),
            max_level=max_level,
            level_costs=costs,
            effect_deltas=normalized_deltas,
            status=status,
            min_realm_key=min_realm_key,
            min_layer=min_layer,
            style_key=str(style_key),
            style_label=style_label.strip(),
            combat_effect=dict(combat_effect),
            acquisition_item_key=acquisition_item_key,
        )
    return definitions


def skill_mastery_rules(content: ContentBundle | None = None) -> dict[str, Any]:
    bundle = content or _default_content()
    rules = bundle.require("advancement_rule", "skill.mastery", include_locked=False)
    resource_key = rules.get("insight_resource_key")
    if not isinstance(resource_key, str) or not resource_key:
        raise ContentError("skill.mastery requires insight_resource_key")
    skill_resource_definition(resource_key, bundle)
    return rules


def skill_resource_definition(resource_key: str, content: ContentBundle | None = None) -> dict[str, Any]:
    bundle = content or _default_content()
    try:
        resource = bundle.require("resource", resource_key, include_locked=False)
    except KeyError as exc:
        raise ContentError(f"skill resource is unavailable: {resource_key}") from exc
    if (
        not isinstance(resource.get("name"), str)
        or not resource["name"].strip()
        or not isinstance(resource.get("desc"), str)
        or not resource["desc"].strip()
    ):
        raise ContentError(f"resource {resource_key} requires name and desc")
    storage = resource.get("storage")
    if not isinstance(storage, str) or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", storage) is None:
        raise ContentError(f"resource {resource_key} requires a valid storage field")
    return resource


def skill_definition(value: str | None, content: ContentBundle | None = None) -> SkillDefinition:
    definitions = skill_definitions(content)
    aliases = {
        alias: key
        for key, definition in definitions.items()
        for alias in (key, definition.label)
    }
    normalized = (value or "").strip()
    key = aliases.get(normalized, normalized)
    try:
        return definitions[key]
    except KeyError as exc:
        raise ValueError(f"unsupported skill: {value}") from exc


def skill_cost(target_level: int, definition: SkillDefinition) -> dict[str, int]:
    costs = definition.level_costs
    try:
        return dict(costs[int(target_level)])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"unsupported skill level: {target_level}") from exc


def available_skill_keys(
    path_key: str | None,
    content: ContentBundle | None = None,
    *,
    realm_key: str | None = None,
    realm_layer: int = 0,
    inventory: Mapping[str, int] | None = None,
    mastered_keys: tuple[str, ...] = (),
) -> tuple[str, ...]:
    bundle = content or _default_content()
    definitions = skill_definitions(bundle)
    current_realm = bundle.get("realm", realm_key, include_locked=False) if realm_key else None
    current_rank = int(current_realm.get("rank", -1)) if current_realm else -1
    return tuple(
        definition.key
        for definition in definitions.values()
        if definition.status == "active"
        and (definition.path_key is None or definition.path_key == path_key)
        and (
            definition.acquisition_item_key is None
            or definition.key in mastered_keys
            or int((inventory or {}).get(definition.acquisition_item_key, 0)) > 0
        )
        and (
            definition.min_realm_key is None
            or current_rank > int(bundle.require("realm", definition.min_realm_key, include_locked=False)["rank"])
            or (
                realm_key == definition.min_realm_key
                and realm_layer >= definition.min_layer
            )
        )
    )


def effective_skill_effect(definition: SkillDefinition, level: int) -> dict[str, Any]:
    if level < 0 or level > definition.max_level:
        raise ValueError("skill level is out of range")
    effect = dict(definition.effect)
    effect["level"] = level
    for field, delta in definition.effect_deltas.items():
        effect[field] = int(definition.effect[field]) + delta * level
    return effect


__all__ = [
    "SKILL_STYLES",
    "SkillDefinition",
    "available_skill_keys",
    "effective_skill_effect",
    "skill_cost",
    "skill_definition",
    "skill_definitions",
    "skill_mastery_rules",
    "skill_resource_definition",
]
