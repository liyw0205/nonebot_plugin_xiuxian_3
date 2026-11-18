"""Strict content contract for player-facing batch production commissions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..content import ContentBundle, ContentError, resolve_content_key
from ..production.rules import production_batch_supported, recipe_definition


KIND = "batch_commission"
_FIELDS = frozenset(
    {
        "key", "name", "desc", "aliases", "recipe_key", "source_recipe_key",
        "max_quantity", "min_reward_per_unit", "max_reward_per_unit",
        "ttl_seconds", "recovery_grace_seconds", "status",
    }
)


@dataclass(frozen=True, slots=True)
class BatchCommissionDefinition:
    key: str
    name: str
    desc: str
    aliases: tuple[str, ...]
    recipe_key: str
    max_quantity: int
    min_reward_per_unit: int
    max_reward_per_unit: int
    ttl_seconds: int
    recovery_grace_seconds: int
    status: str


def batch_commission_definitions(
    content: ContentBundle | None = None,
) -> dict[str, BatchCommissionDefinition]:
    bundle = content
    if bundle is None:
        from ..content import bundled_content

        bundle = bundled_content()
    result: dict[str, BatchCommissionDefinition] = {}
    selectors: dict[str, str] = {}
    for row in bundle.list(KIND, include_locked=True):
        key = row.get("key")
        if not isinstance(key, str) or not key.strip():
            raise ContentError("batch commission key must be non-empty")
        if set(row) != _FIELDS:
            raise ContentError(f"batch commission {key} has missing or unused fields")
        for field in ("name", "desc", "recipe_key", "source_recipe_key"):
            if not isinstance(row[field], str) or not row[field].strip():
                raise ContentError(f"batch commission {key} {field} must be non-empty")
        aliases = row["aliases"]
        if (
            not isinstance(aliases, list)
            or any(not isinstance(value, str) or not value.strip() for value in aliases)
            or len(set(aliases)) != len(aliases)
        ):
            raise ContentError(f"batch commission {key} aliases must be unique strings")
        recipe_key = resolve_content_key(bundle, "recipe", row["recipe_key"], include_locked=False)
        if recipe_key != row["recipe_key"] or row["source_recipe_key"] != recipe_key:
            raise ContentError(f"batch commission {key} source recipe must match recipe_key")
        recipe = recipe_definition(recipe_key, bundle)
        if not production_batch_supported(recipe):
            raise ContentError(f"batch commission {key} references a non-batchable recipe")
        for field in ("max_quantity", "min_reward_per_unit", "max_reward_per_unit", "ttl_seconds", "recovery_grace_seconds"):
            value = row[field]
            if type(value) is not int or value <= 0:
                raise ContentError(f"batch commission {key} {field} must be a positive integer")
        if row["max_quantity"] < 2 or row["max_quantity"] > 5:
            raise ContentError(f"batch commission {key} max_quantity must be 2..5")
        if row["min_reward_per_unit"] > row["max_reward_per_unit"]:
            raise ContentError(f"batch commission {key} reward range is reversed")
        if row["max_reward_per_unit"] * row["max_quantity"] > 500:
            raise ContentError(f"batch commission {key} can exceed the escrow ceiling")
        if row["status"] not in {"active", "open", "locked"}:
            raise ContentError(f"batch commission {key} status is invalid")
        definition = BatchCommissionDefinition(
            key=key,
            name=row["name"],
            desc=row["desc"],
            aliases=tuple(aliases),
            recipe_key=recipe_key,
            max_quantity=row["max_quantity"],
            min_reward_per_unit=row["min_reward_per_unit"],
            max_reward_per_unit=row["max_reward_per_unit"],
            ttl_seconds=row["ttl_seconds"],
            recovery_grace_seconds=row["recovery_grace_seconds"],
            status=row["status"],
        )
        if key in result:
            raise ContentError(f"duplicate batch commission key: {key}")
        result[key] = definition
        recipe_aliases = tuple(bundle.require("recipe", recipe.key).get("aliases", ()))
        for selector in (key, definition.name, *definition.aliases, recipe.key, recipe.name, *recipe_aliases):
            if selector in selectors and selectors[selector] != key:
                raise ContentError(f"ambiguous batch commission selector: {selector}")
            selectors[selector] = key
    if not result:
        raise ContentError("batch commission catalogue must not be empty")
    return result


def resolve_batch_commission(value: str, content: ContentBundle | None = None) -> BatchCommissionDefinition:
    definitions = batch_commission_definitions(content)
    normalized = (value or "").strip()
    for definition in definitions.values():
        recipe = recipe_definition(definition.recipe_key, content)
        bundle = content
        if bundle is None:
            from ..content import bundled_content

            bundle = bundled_content()
        recipe_aliases = tuple(bundle.require("recipe", recipe.key).get("aliases", ()))
        if normalized in (definition.key, definition.name, *definition.aliases, recipe.key, recipe.name, *recipe_aliases):
            if definition.status not in {"active", "open"}:
                break
            return definition
    raise ValueError(f"unknown or closed batch commission: {value}")


__all__ = ["BatchCommissionDefinition", "KIND", "batch_commission_definitions", "resolve_batch_commission"]
