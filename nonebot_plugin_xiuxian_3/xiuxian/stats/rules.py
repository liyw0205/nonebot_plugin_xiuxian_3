"""Integer-only, content-backed rules for character attributes."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping

from ..content import ContentBundle, ContentError, bundled_content
from ..utils.json import json_object
from ..utils.player import player_integer, player_values

STAT_KEYS = ("body", "spirit", "insight", "root", "agility", "fortune")
DERIVED_KEYS = (
    "max_hp",
    "max_mp",
    "carry_capacity",
    "initiative",
    "training_rate_bp",
    "exploration_rate_bp",
    "breakthrough_prepare_bp",
)


class StatError(ValueError):
    """A stat preview or snapshot cannot be constructed."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class StatsFormula:
    values: dict[str, int]
    caps: dict[str, dict[str, int]]
    fingerprint: str


_FORMULA_FIELDS = (
    "realm_growth_per_index", "realm_growth_per_layer", "max_hp_base", "max_hp_body",
    "max_hp_root", "max_mp_base", "max_mp_per_index", "max_mp_per_layer",
    "max_mp_spirit", "max_mp_insight", "carry_base", "carry_body", "carry_per_index",
    "carry_per_layer", "initiative_base", "initiative_agility", "training_base_bp",
    "training_insight_bp", "training_layer_bp", "exploration_base_bp",
    "exploration_agility_bp", "exploration_layer_bp", "breakthrough_root_bp",
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
    canonical = json.dumps({"formulas": normalized, "caps": normalized_caps}, sort_keys=True, separators=(",", ":"))
    return StatsFormula(normalized, normalized_caps, hashlib.sha256(canonical.encode("utf-8")).hexdigest())


def _qualification(row: Mapping[str, Any]) -> dict[str, int]:
    raw = row["qualification_json"] if "qualification_json" in row.keys() else row.get("qualification", {})
    values = json_object(raw, {})
    if set(values) != set(STAT_KEYS):
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
    layer = player_integer(row, "realm_layer")
    if isinstance(layer, bool) or not isinstance(layer, int) or not realm["layer_min"] <= layer <= realm["layer_max"]:
        raise StatError("STAT_VALUE_OUT_OF_RANGE", "境界层数无效。")
    layer_tail = max(layer - 1, 0)
    return realm_key, int(realm["rank"]), layer_tail


def build_stat_preview(row: Mapping[str, Any], content: ContentBundle | None = None) -> dict[str, Any]:
    # Attribute formulas consume the same normalized player projection as
    # profile, status, and battle-start readers.  This keeps JSON aliases,
    # neutral defaults, and integer conversion in one place.
    row = player_values(row)
    bundle = _content(content)
    formula = stats_formula(bundle)
    base = _qualification(row)
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
    }
    warnings: list[dict[str, int | str]] = []
    for stat_key in ("training_rate_bp", "exploration_rate_bp"):
        bonus = derived[stat_key] - 10_000
        cap = formula.caps[stat_key]["permanent"]
        if bonus > cap:
            derived[stat_key] = 10_000 + cap
            warnings.append({"code": "STAT_CAP_APPLIED", "stat_key": stat_key, "cap": cap})
    path_key = row["path_key"] if "path_key" in row.keys() else row.get("path_key")
    source_refs = [
        {"key": "realm", "value": realm_key, "multiplier_zone": "base"},
        {"key": "qualification", "value": dict(base), "multiplier_zone": "base"},
    ]
    if path_key:
        source_refs.append({"key": "path", "value": str(path_key), "multiplier_zone": "path", "effect": {}})
    return {
        "base_stats": base,
        "path_stats": {},
        "derived_stats": derived,
        "source_refs": source_refs,
        "formula_fingerprint": formula.fingerprint,
        "warnings": warnings,
        "realm_key": realm_key,
        "realm_layer": player_integer(row, "realm_layer"),
    }


def explain_stat(preview: Mapping[str, Any], stat_key: str) -> dict[str, Any]:
    derived = dict(preview.get("derived_stats", {}))
    if stat_key not in derived:
        raise StatError("STAT_RULE_NOT_FOUND", "未找到这项属性。")
    sources = [dict(source) for source in preview.get("source_refs", ())]
    return {"stat_key": stat_key, "value": int(derived[stat_key]), "sources": sources, "formula_fingerprint": str(preview["formula_fingerprint"])}


__all__ = ["DERIVED_KEYS", "STAT_KEYS", "StatError", "StatsFormula", "build_stat_preview", "explain_stat", "stats_formula"]
