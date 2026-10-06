"""Integer-only, content-backed rules for character attributes."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Mapping

from ..content import ContentBundle, ContentError, bundled_content
from ..utils.json_cache import decode_json_strict
from ..utils.player import player_field, player_values

STAT_KEYS = ("body", "spirit", "insight", "root", "agility", "fortune")
DERIVED_KEYS = (
    "max_hp",
    "max_mp",
    "carry_capacity",
    "initiative",
    "training_rate_bp",
    "exploration_rate_bp",
    "breakthrough_prepare_bp", "attack", "agility", "hp_regen", "mana_regen",
    "damage_reduction_bp", "crit_chance_bp", "crit_damage_bp", "evasion_bp",
    "accuracy_bp", "anti_crit_bp", "damage_reflection_bp", "lifesteal_bp",
    "mana_leech_bp", "healing_reduction_bp", "recovery_reduction_bp",
)
COMBAT_STAT_KEYS = (
    "max_hp", "attack", "initiative", "agility", "max_mana", "hp_regen", "mana_regen",
    "damage_reduction_bp", "crit_chance_bp", "crit_damage_bp", "evasion_bp",
    "accuracy_bp", "anti_crit_bp", "damage_reflection_bp", "lifesteal_bp",
    "mana_leech_bp", "healing_reduction_bp", "recovery_reduction_bp",
)
_COMBAT_RATE_KEYS = COMBAT_STAT_KEYS[7:]
_PERMANENT_STATS = {
    "max_hp": "max_hp", "max_mp": "max_mp", "initiative": "initiative",
    "carry_capacity": "carry_capacity", "exploration_efficiency_bp": "exploration_rate_bp",
}
_FLAT_EFFECT_STATS = {
    "physical_damage": "attack", "max_hp": "max_hp", "initiative": "initiative",
    "agility": "agility", "max_mana": "max_mp", "hp_regen": "hp_regen",
    "mana_regen": "mana_regen",
}
_AFFIX_STATS = {
    "damage": "attack", "hp": "max_hp", "initiative": "initiative",
    "damage_reduction": "damage_reduction_bp", "crit_chance": "crit_chance_bp",
    "crit_damage": "crit_damage_bp", "evasion": "evasion_bp", "accuracy": "accuracy_bp",
    "anti_crit": "anti_crit_bp", "reflection": "damage_reflection_bp",
    "lifesteal": "lifesteal_bp", "mana_leech": "mana_leech_bp",
    "healing_reduction": "healing_reduction_bp", "recovery_reduction": "recovery_reduction_bp",
    "hp_regen": "hp_regen", "max_mana": "max_mp", "mana_regen": "mana_regen",
}
_CONSTITUTION_STATS = {"max_hp_bp": "max_hp", "max_mana_bp": "max_mp", "initiative_bp": "initiative"}


class StatError(ValueError):
    """A stat preview or snapshot cannot be constructed."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class StatsFormula:
    values: dict[str, int]
    caps: dict[str, dict[str, int]]
    combat_caps: dict[str, int]
    fingerprint: str


_FORMULA_FIELDS = (
    "realm_growth_per_index", "realm_growth_per_layer", "max_hp_base", "max_hp_body",
    "max_hp_root", "max_mp_base", "max_mp_per_index", "max_mp_per_layer",
    "max_mp_spirit", "max_mp_insight", "carry_base", "carry_body", "carry_per_index",
    "carry_per_layer", "initiative_base", "initiative_agility", "training_base_bp",
    "training_insight_bp", "training_layer_bp", "exploration_base_bp",
    "exploration_agility_bp", "exploration_layer_bp", "breakthrough_root_bp",
    "attack_base", "attack_body_divisor", "weapon_temper_attack",
)
_CAP_FIELDS = ("training_rate_bp", "exploration_rate_bp")


def _content(content: ContentBundle | None) -> ContentBundle:
    return content or bundled_content()


def stats_formula(content: ContentBundle | None = None) -> StatsFormula:
    bundle = _content(content)
    record = bundle.get("advancement_rule", "stats.formula", include_locked=False)
    if not isinstance(record, dict):
        raise ContentError("missing active advancement_rule stats.formula")
    values = record.get("formulas")
    caps = record.get("caps")
    if not isinstance(values, dict) or set(values) != set(_FORMULA_FIELDS):
        raise ContentError("stats.formula formulas are incomplete")
    normalized: dict[str, int] = {}
    for key in _FORMULA_FIELDS:
        value = values[key]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ContentError(f"stats.formula field {key} must be a non-negative integer")
        normalized[key] = value
    if normalized["attack_body_divisor"] == 0:
        raise ContentError("stats.formula attack_body_divisor must be positive")
    if not isinstance(caps, dict) or set(caps) != set(_CAP_FIELDS):
        raise ContentError("stats.formula caps are incomplete")
    normalized_caps: dict[str, dict[str, int]] = {}
    for key in _CAP_FIELDS:
        row = caps[key]
        if not isinstance(row, dict) or set(row) != {"permanent", "temporary"}:
            raise ContentError(f"stats.formula cap {key} is incomplete")
        normalized_caps[key] = {}
        for cap_key in ("permanent", "temporary"):
            value = row[cap_key]
            if isinstance(value, bool) or not isinstance(value, int) or value < 0 or value > 10_000:
                raise ContentError(f"stats.formula cap {key}.{cap_key} is invalid")
            normalized_caps[key][cap_key] = value
    combat_caps = record.get("combat_caps")
    if not isinstance(combat_caps, dict) or set(combat_caps) != set(_COMBAT_RATE_KEYS):
        raise ContentError("stats.formula combat_caps are incomplete")
    if any(type(value) is not int or value < 0 for value in combat_caps.values()):
        raise ContentError("stats.formula combat_caps must be non-negative integers")
    if any(value > 10_000 for key, value in combat_caps.items() if key != "crit_damage_bp"):
        raise ContentError("stats.formula probability and recovery caps cannot exceed 10000")
    canonical = json.dumps(
        {"formulas": normalized, "caps": normalized_caps, "combat_caps": combat_caps},
        sort_keys=True, separators=(",", ":"),
    )
    return StatsFormula(normalized, normalized_caps, dict(combat_caps), hashlib.sha256(canonical.encode("utf-8")).hexdigest())


def _qualification(row: Mapping[str, Any]) -> dict[str, int]:
    raw = player_field(row, "qualification", None)
    if raw is None:
        raw = player_field(row, "qualification_json", "{}")
    values = decode_json_strict(raw) if isinstance(raw, str) else raw
    if not isinstance(values, Mapping) or set(values) != set(STAT_KEYS):
        raise StatError("STAT_VALUE_OUT_OF_RANGE", "六项资质尚未完整生成。")
    normalized = {key: values[key] for key in STAT_KEYS}
    if any(isinstance(value, bool) or not isinstance(value, int) or not 5 <= value <= 15 for value in normalized.values()):
        raise StatError("STAT_VALUE_OUT_OF_RANGE", "六项资质必须在五至十五之间。")
    if sum(normalized.values()) != 60:
        raise StatError("STAT_VALUE_OUT_OF_RANGE", "六项资质总和必须为六十。")
    return normalized


def _realm_index(row: Mapping[str, Any], content: ContentBundle) -> tuple[str, int, int]:
    realm_key = str(row["realm_key"] if "realm_key" in row.keys() else row.get("realm_key") or "mortal")
    realm = content.get("realm", realm_key, include_locked=False)
    if (
        realm is None
        or isinstance(realm.get("rank"), bool)
        or not isinstance(realm.get("rank"), int)
        or isinstance(realm.get("layer_min"), bool)
        or not isinstance(realm.get("layer_min"), int)
        or isinstance(realm.get("layer_max"), bool)
        or not isinstance(realm.get("layer_max"), int)
        or realm["layer_min"] > realm["layer_max"]
    ):
        raise StatError("STAT_RULE_NOT_FOUND", "当前境界没有可用的属性推演规则。")
    layer = row["realm_layer"]
    if isinstance(layer, bool) or not isinstance(layer, int) or not realm["layer_min"] <= layer <= realm["layer_max"]:
        raise StatError("STAT_VALUE_OUT_OF_RANGE", "境界层数无效。")
    layer_tail = max(layer - 1, 0)
    return realm_key, int(realm["rank"]), layer_tail


def _nonnegative_integer(value: Any, field: str) -> int:
    if type(value) is not int or value < 0:
        raise StatError("STAT_VALUE_OUT_OF_RANGE", "此身灵机紊乱，暂时无法推演属性。") from ValueError(
            f"stat source {field} must be a non-negative integer"
        )
    return value


def _constitution_bonus(effect: Mapping[str, Any] | None) -> dict[str, int]:
    if effect is None or effect == {}:
        return {}
    if not isinstance(effect, Mapping):
        raise ValueError("constitution effect must be an object")
    effect_type = effect.get("type")
    value = _nonnegative_integer(effect.get("value"), "constitution.value")
    if effect_type in _CONSTITUTION_STATS:
        return {_CONSTITUTION_STATS[effect_type]: value}
    if effect_type not in {"production_quality_bp", "drop_weight_bp"}:
        raise ValueError("constitution effect is unsupported")
    return {}


def _equipment_bonuses(
    item: Mapping[str, Any], formula: StatsFormula
) -> dict[str, int]:
    if not isinstance(item, Mapping):
        raise ValueError("equipment snapshot must be an object")
    if not isinstance(item.get("item_key"), str) or not item["item_key"].startswith("item."):
        raise ValueError("equipment snapshot requires an item key")
    if item.get("slot") not in {"weapon", "armor", "accessory"}:
        raise ValueError("equipment snapshot has an invalid slot")
    durability = _nonnegative_integer(item.get("durability_bp"), "equipment.durability_bp")
    if durability > 10_000:
        raise ValueError("equipment durability cannot exceed 10000")
    temper = _nonnegative_integer(item.get("temper_level"), "equipment.temper_level")
    affixes = item.get("affixes")
    effects = item.get("effects")
    if not isinstance(affixes, Mapping) or not isinstance(effects, (list, tuple)):
        raise ValueError("equipment effects or affixes are incomplete")
    bonuses: dict[str, int] = {}
    for key, raw_value in affixes.items():
        if key not in _AFFIX_STATS:
            raise ValueError(f"unsupported equipment affix: {key}")
        value = _nonnegative_integer(raw_value, f"equipment.affix.{key}")
        stat = _AFFIX_STATS[key]
        bonuses[stat] = bonuses.get(stat, 0) + value * durability // 10_000
    for effect in effects:
        if not isinstance(effect, Mapping):
            raise ValueError("equipment effect must be an object")
        kind, stat = effect.get("type"), effect.get("stat")
        value = _nonnegative_integer(effect.get("value"), "equipment.effect.value")
        if kind == "flat_stat" and stat in _FLAT_EFFECT_STATS:
            stat = _FLAT_EFFECT_STATS[stat]
        elif kind != "combat_stat_bp" or stat not in _COMBAT_RATE_KEYS:
            raise ValueError("equipment effect is unsupported")
        bonuses[stat] = bonuses.get(stat, 0) + value * durability // 10_000
    if item["slot"] == "weapon":
        bonuses["attack"] = bonuses.get("attack", 0) + temper * formula.values["weapon_temper_attack"] * durability // 10_000
    return bonuses


def build_stat_preview(
    row: Mapping[str, Any], content: ContentBundle | None = None, *,
    equipment: tuple[Mapping[str, Any], ...] = (),
    constitution_effect: Mapping[str, Any] | None = None,
    manual_effects: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    base = _qualification(row)
    permanent = {
        target: _nonnegative_integer(player_field(row, source, 0), source)
        for source, target in _PERMANENT_STATS.items()
    }
    _nonnegative_integer(player_field(row, "realm_layer", 0), "realm_layer")
    row = player_values(row)
    bundle = _content(content)
    formula = stats_formula(bundle)
    realm_key, realm_index, layer_tail = _realm_index(row, bundle)
    f = formula.values
    derived = {
        "max_hp": f["max_hp_base"] + f["realm_growth_per_index"] * realm_index + f["realm_growth_per_layer"] * layer_tail + f["max_hp_body"] * base["body"] + f["max_hp_root"] * base["root"],
        "max_mp": f["max_mp_base"] + f["max_mp_per_index"] * realm_index + f["max_mp_per_layer"] * layer_tail + f["max_mp_spirit"] * base["spirit"] + f["max_mp_insight"] * base["insight"],
        "carry_capacity": f["carry_base"] + f["carry_body"] * base["body"] + f["carry_per_index"] * realm_index + (f["carry_per_layer"] * layer_tail) // 2,
        "initiative": f["initiative_base"] + f["initiative_agility"] * base["agility"],
        "training_rate_bp": f["training_base_bp"] + f["training_insight_bp"] * base["insight"] + f["training_layer_bp"] * layer_tail,
        "exploration_rate_bp": f["exploration_base_bp"] + f["exploration_agility_bp"] * base["agility"] + f["exploration_layer_bp"] * layer_tail,
        "breakthrough_prepare_bp": f["breakthrough_root_bp"] * base["root"],
        "attack": f["attack_base"] + base["body"] // f["attack_body_divisor"],
        "agility": base["agility"],
        "hp_regen": 0,
        "mana_regen": 0,
        **dict.fromkeys(_COMBAT_RATE_KEYS, 0),
    }
    path_key = row["path_key"] if "path_key" in row.keys() else row.get("path_key")
    source_refs = [
        {"key": "realm", "value": realm_key, "multiplier_zone": "base"},
        {"key": "qualification", "value": dict(base), "multiplier_zone": "base"},
        {"key": "permanent", "value": dict(permanent), "multiplier_zone": "base", "effect": dict(permanent)},
    ]
    for stat, value in permanent.items():
        derived[stat] += value
    if path_key:
        source_refs.append({"key": "path", "value": str(path_key), "multiplier_zone": "path", "effect": {}})
    if not isinstance(equipment, (tuple, list)):
        raise ValueError("equipment snapshots must be a sequence")
    seen_slots: set[str] = set()
    for item in equipment:
        bonuses = _equipment_bonuses(item, formula)
        slot = str(item["slot"])
        if slot in seen_slots:
            raise ValueError("equipment snapshot contains duplicate slots")
        seen_slots.add(slot)
        for stat, value in bonuses.items():
            derived[stat] += value
        source_refs.append({"key": "equipment", "value": deepcopy(dict(item)), "multiplier_zone": "build", "effect": bonuses})
    build_bonus: dict[str, int] = {}
    if manual_effects is not None:
        if not isinstance(manual_effects, Mapping) or set(manual_effects) != {"combat_stat_bonus_bp", "cultivation_gain_bp", "damage_reflection_bp"}:
            raise ValueError("manual effects are incomplete")
        manual_bonus = manual_effects["combat_stat_bonus_bp"]
        if not isinstance(manual_bonus, Mapping) or set(manual_bonus) != {"attack", "max_hp", "initiative", "agility"}:
            raise ValueError("manual combat bonuses are incomplete")
        for stat, value in manual_bonus.items():
            build_bonus[stat] = _nonnegative_integer(value, f"manual.{stat}")
        _nonnegative_integer(manual_effects["cultivation_gain_bp"], "manual.cultivation_gain_bp")
        derived["damage_reflection_bp"] += _nonnegative_integer(manual_effects["damage_reflection_bp"], "manual.damage_reflection_bp")
        source_refs.append({
            "key": "manual", "value": deepcopy(dict(manual_effects)), "multiplier_zone": "build",
            "effect": {**build_bonus, "damage_reflection_bp": manual_effects["damage_reflection_bp"]},
        })
    constitution_bonus = _constitution_bonus(constitution_effect)
    for stat, value in constitution_bonus.items():
        build_bonus[stat] = build_bonus.get(stat, 0) + value
    if constitution_effect:
        source_refs.append({"key": "constitution", "value": deepcopy(dict(constitution_effect)), "multiplier_zone": "build", "effect": dict(constitution_bonus)})
    for stat, value in build_bonus.items():
        derived[stat] += derived[stat] * value // 10_000
    warnings: list[dict[str, int | str]] = []
    limits = {key: 10_000 + formula.caps[key]["permanent"] for key in _CAP_FIELDS}
    limits.update(formula.combat_caps)
    for stat, maximum in limits.items():
        if derived[stat] > maximum:
            derived[stat] = maximum
            warnings.append({"code": "STAT_CAP_APPLIED", "stat_key": stat, "cap": maximum})
    combat_stats = frozen_combat_stats({
        "stats": {key: derived["max_mp" if key == "max_mana" else key] for key in COMBAT_STAT_KEYS}
    })
    return {
        "base_stats": base,
        "path_stats": {},
        "derived_stats": derived,
        "combat_stats": combat_stats,
        "source_refs": source_refs,
        "formula_fingerprint": formula.fingerprint,
        "warnings": warnings,
        "realm_key": realm_key,
        "realm_layer": row["realm_layer"],
    }


def frozen_combat_stats(snapshot: Mapping[str, Any]) -> dict[str, int]:
    if not isinstance(snapshot, Mapping):
        raise ValueError("combat snapshot must be an object")
    stats = snapshot.get("stats")
    if not isinstance(stats, Mapping) or set(stats) != set(COMBAT_STAT_KEYS):
        raise ValueError("combat stat snapshot is incomplete")
    result = {key: _nonnegative_integer(stats[key], key) for key in COMBAT_STAT_KEYS}
    if result["max_hp"] == 0 or result["attack"] == 0:
        raise ValueError("combat max_hp and attack must be positive")
    return result


def apply_constitution_combat_effect(
    stats: Mapping[str, int], effect: Mapping[str, Any] | None
) -> dict[str, int]:
    """Apply the constitution after an explicit high-tier encounter projection."""
    result = frozen_combat_stats({"stats": stats})
    for stat, value in _constitution_bonus(effect).items():
        combat_key = "max_mana" if stat == "max_mp" else stat
        result[combat_key] += result[combat_key] * value // 10_000
    return result


def explain_stat(preview: Mapping[str, Any], stat_key: str) -> dict[str, Any]:
    derived = dict(preview.get("derived_stats", {}))
    if stat_key not in derived:
        raise StatError("STAT_RULE_NOT_FOUND", "未找到这项属性。")
    sources = [dict(source) for source in preview.get("source_refs", ())]
    return {"stat_key": stat_key, "value": int(derived[stat_key]), "sources": sources, "formula_fingerprint": str(preview["formula_fingerprint"])}


__all__ = [
    "COMBAT_STAT_KEYS", "DERIVED_KEYS", "STAT_KEYS", "StatError", "StatsFormula",
    "apply_constitution_combat_effect", "build_stat_preview", "explain_stat",
    "frozen_combat_stats", "stats_formula",
]
