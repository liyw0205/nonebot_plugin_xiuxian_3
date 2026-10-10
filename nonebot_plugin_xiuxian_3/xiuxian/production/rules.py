"""Content-backed personal production recipes and quality rules."""

from __future__ import annotations

from dataclasses import fields
from hashlib import blake2b
from typing import Any

from ..content import ContentBundle, ContentError, bundled_content
from ..player.path_rules import subprofession_records
from .recipe_models import RecipeDefinition


QUALITY_SUCCESS_THRESHOLD_BP = 4500
HIGH_QUALITY_THRESHOLD_BP = 8000
TOOL_MAX_DURABILITY_BP = 2000
_RECIPE_FIELDS = frozenset(field.name for field in fields(RecipeDefinition))
_LIST_REFERENCES = {
    "additional_realms": "realm",
    "required_location": "location",
    "required_paths": "path",
}
_SUBPROFESSION_LIST = "required_subprofession"


class UnknownRecipeError(ValueError):
    """The requested stable recipe ID is absent or closed for new orders."""


def recipe_definitions(content: ContentBundle | None = None) -> dict[str, RecipeDefinition]:
    bundle = content or bundled_content()
    professions = {row["key"] for row in subprofession_records(content=bundle)}
    result: dict[str, RecipeDefinition] = {}
    for row in bundle.list("recipe", include_locked=False):
        key = row["key"]
        if set(row) != _RECIPE_FIELDS | {"desc", "status", "aliases"}:
            raise ContentError(f"recipe {key} has missing or unused fields")
        for field in ("key", "name", "desc"):
            if not isinstance(row[field], str) or not row[field].strip():
                raise ContentError(f"recipe {key} {field} must be non-empty")
        _strings(row["aliases"], key, "aliases")
        profession = row["profession"]
        if profession is not None and (not isinstance(profession, str) or profession not in professions):
            raise ContentError(f"recipe {key} profession is unavailable")
        for field in ("energy_cost", "duration_seconds", "daily_limit", "min_realm_layer"):
            _integer(row[field], key, field, minimum=1)
        for field in ("currency_cost", "binding_duration_seconds", "binding_slot_limit"):
            _integer(row[field], key, field)
        for field in ("tool_cost_bp", "proficiency_bp"):
            _integer(row[field], key, field, maximum=10000)
        _integer(row["success_threshold_bp"], key, "success_threshold_bp", minimum=1, maximum=10000)
        _integer(row["high_quality_threshold_bp"], key, "high_quality_threshold_bp", minimum=1, maximum=10001)
        if row["high_quality_threshold_bp"] < row["success_threshold_bp"]:
            raise ContentError(f"recipe {key} quality thresholds are reversed")
        if type(row["teaching_allowed"]) is not bool:
            raise ContentError(f"recipe {key} teaching_allowed must be boolean")
        for field, kind in _LIST_REFERENCES.items():
            for reference in _strings(row[field], key, field):
                _reference(bundle, kind, reference, key, field)
        for reference in _strings(row[_SUBPROFESSION_LIST], key, _SUBPROFESSION_LIST):
            if reference not in professions:
                raise ContentError(f"recipe {key} required_subprofession is unavailable")
        _reference(bundle, "realm", row["required_realm"], key, "required_realm")
        realms = [row["required_realm"], *row["additional_realms"]]
        if any(row["min_realm_layer"] > bundle.require("realm", realm)["layer_max"] for realm in realms):
            raise ContentError(f"recipe {key} min_realm_layer exceeds realm layers")
        if row["required_path"] is not None:
            _reference(bundle, "path", row["required_path"], key, "required_path")
        if row["facility_kind"] not in (None, "alchemy", "artifice", "array"):
            raise ContentError(f"recipe {key} facility_kind is unsupported")
        if row["cross_realm_faction"] not in (None, "beast", "demon"):
            raise ContentError(f"recipe {key} cross_realm_faction is unsupported")
        if row["binding_kind"] not in (None, "contract"):
            raise ContentError(f"recipe {key} binding_kind is unsupported")
        if row["binding_kind"] is None:
            if row["binding_duration_seconds"] or row["binding_slot_limit"]:
                raise ContentError(f"recipe {key} has binding values without a binding")
        elif not row["binding_duration_seconds"] or not row["binding_slot_limit"]:
            raise ContentError(f"recipe {key} binding values must be positive")
        if row["failure_refund_bp"] is not None:
            _integer(row["failure_refund_bp"], key, "failure_refund_bp", maximum=10000)
        for field in ("inputs", "outputs", "high_quality_bonus", "failure_refunds"):
            _assets(bundle, row[field], key, field, allow_zero=field == "failure_refunds")
        if not row["inputs"] or not row["outputs"]:
            raise ContentError(f"recipe {key} inputs and outputs must not be empty")
        if set(row["high_quality_bonus"]) - set(row["outputs"]):
            raise ContentError(f"recipe {key} quality bonus is not an output")
        if any(amount > row["inputs"].get(asset, -1) for asset, amount in row["failure_refunds"].items()):
            raise ContentError(f"recipe {key} refund exceeds its inputs")
        if row["tool_key"] is not None:
            _reference(bundle, "item", row["tool_key"], key, "tool_key")
            if bundle.require("item", row["tool_key"]).get("item_type") != "tool":
                raise ContentError(f"recipe {key} tool_key is not a tool")
        elif row["tool_cost_bp"]:
            raise ContentError(f"recipe {key} has tool cost without a tool")
        values = {field: row[field] for field in _RECIPE_FIELDS}
        for field in (*_LIST_REFERENCES, _SUBPROFESSION_LIST):
            values[field] = tuple(values[field])
        result[key] = RecipeDefinition(**values)
    _validate_sources(bundle)
    _recipe_selectors(bundle, result)
    return result


def _integer(value: Any, key: str, field: str, *, minimum: int = 0, maximum: int | None = None) -> None:
    if type(value) is not int or value < minimum or (maximum is not None and value > maximum):
        raise ContentError(f"recipe {key} {field} has an invalid integer")


def _strings(value: Any, key: str, field: str) -> list[str]:
    if (
        not isinstance(value, list)
        or any(not isinstance(item, str) or not item.strip() for item in value)
        or len(set(value)) != len(value)
    ):
        raise ContentError(f"recipe {key} {field} must be unique non-empty strings")
    return value


def _reference(bundle: ContentBundle, kind: str, value: Any, key: str, field: str) -> None:
    # Locations retain their existing domain permission gates, including the array hall.
    if not isinstance(value, str) or not bundle.has(kind, value, include_locked=kind == "location"):
        raise ContentError(f"recipe {key} {field} references unavailable {kind}: {value}")


def _assets(bundle: ContentBundle, value: Any, key: str, field: str, *, allow_zero: bool) -> None:
    if not isinstance(value, dict):
        raise ContentError(f"recipe {key} {field} must be an object")
    for asset, amount in value.items():
        _integer(amount, key, field, minimum=0 if allow_zero else 1)
        if bundle.has("item", asset, include_locked=False):
            continue
        companion = bundle.get("companion", asset, include_locked=False)
        if companion is None or companion.get("kind") not in {"beast_gear", "mount_tack"}:
            raise ContentError(f"recipe {key} {field} references unavailable asset: {asset}")


def _validate_sources(bundle: ContentBundle) -> None:
    for kind in ("item", "companion"):
        for row in bundle.list(kind, include_locked=False):
            source = row.get("source_recipe_key")
            if source is None:
                continue
            if not isinstance(source, str) or not source:
                raise ContentError(f"{kind} {row['key']} source_recipe_key is invalid")
            recipe = bundle.get("recipe", source)
            outputs = recipe.get("outputs") if recipe is not None else None
            amount = outputs.get(row["key"]) if isinstance(outputs, dict) else None
            if type(amount) is not int or amount <= 0:
                raise ContentError(f"{kind} {row['key']} source_recipe_key does not produce it")


def _recipe_selectors(bundle: ContentBundle, definitions: dict[str, RecipeDefinition]) -> dict[str, str]:
    selectors: dict[str, str] = {}
    for key, definition in definitions.items():
        row = bundle.require("recipe", key)
        for selector in (key, definition.name, *row["aliases"]):
            if selector in selectors and selectors[selector] != key:
                raise ContentError(f"ambiguous recipe selector: {selector}")
            selectors[selector] = key
    return selectors


def resolve_recipe(value: str, content: ContentBundle | None = None) -> str | None:
    normalized = value.strip()
    # Stable IDs reach the repository so historical operations can replay before content lookup.
    if normalized.startswith("recipe."):
        return normalized
    bundle = content or bundled_content()
    return _recipe_selectors(bundle, recipe_definitions(bundle)).get(normalized)


def recipe_definition(recipe_key: str, content: ContentBundle | None = None) -> RecipeDefinition:
    try:
        return recipe_definitions(content)[recipe_key]
    except KeyError as exc:
        raise UnknownRecipeError(f"unsupported production recipe: {recipe_key}") from exc


def item_label(item_key: str, content: ContentBundle | None = None) -> str:
    bundle = content or bundled_content()
    kind = "companion" if bundle.has("companion", item_key) else "item"
    return bundle.label(kind, item_key)


def random_quality_bp(operation_id: str) -> int:
    value = blake2b(operation_id.encode("utf-8"), digest_size=1).digest()[0]
    if value < 128:
        return 0
    if value < 217:
        return 500
    return 1000


def production_quality(
    *,
    material_quality_bp: int,
    proficiency_bp: int,
    tool_durability_bp: int,
    random_quality_bp_value: int,
) -> int:
    value = (
        (max(0, material_quality_bp) * 4000) // 10000
        + (max(0, proficiency_bp) * 3000) // 10000
        + (max(0, tool_durability_bp) * 2000) // 10000
        + max(0, random_quality_bp_value)
    )
    return min(10000, value)


__all__ = [
    "HIGH_QUALITY_THRESHOLD_BP", "QUALITY_SUCCESS_THRESHOLD_BP", "TOOL_MAX_DURABILITY_BP",
    "RecipeDefinition", "recipe_definitions", "production_quality", "random_quality_bp",
    "item_label", "recipe_definition", "resolve_recipe",
]
