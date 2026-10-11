"""Validate material sources against the existing acquisition and production rules."""

from __future__ import annotations

from .content import ContentBundle, ContentError
from .exploration.rules import exploration_definition, exploration_reward_pool
from .production.rules import recipe_definitions
from .rewards.rules import reward_pool_outcomes


def _labels(row: dict, context: str) -> None:
    for field in ("name", "desc"):
        if not isinstance(row.get(field), str) or not row[field].strip():
            raise ContentError(f"{context} requires non-empty {field}")


def validate_material_content(bundle: ContentBundle) -> dict[str, int]:
    """Check declared sources, their actual rewards, and an existing recipe consumer.

    This is a focused content check, not a new acquisition path. Exploration keeps
    its own access checks and freezes the configured rewards before settlement.
    """

    recipes = recipe_definitions(bundle)
    materials: set[str] = set()
    modes: set[str] = set()
    consumers: set[str] = set()
    source_count = 0
    for item in bundle.list("item"):
        if "gathering_sources" not in item:
            continue
        key = item["key"]
        _labels(item, f"material {key}")
        if item.get("status") not in {"active", "open"}:
            raise ContentError(f"material {key} sources require an active item")
        sources = item["gathering_sources"]
        if not isinstance(sources, list) or not sources:
            raise ContentError(f"material {key} gathering_sources must be a non-empty list")
        recipe_consumers = {recipe.key for recipe in recipes.values() if key in recipe.inputs}
        if not recipe_consumers:
            raise ContentError(f"material {key} has no active production consumer")
        seen: set[str] = set()
        for source in sources:
            if not isinstance(source, dict) or set(source) != {"mode_key", "reward_pool_key"}:
                raise ContentError(f"material {key} has malformed gathering_sources")
            mode_key, pool_key = source["mode_key"], source["reward_pool_key"]
            if any(not isinstance(value, str) or not value.strip() for value in (mode_key, pool_key)):
                raise ContentError(f"material {key} source references must be non-empty strings")
            if mode_key in seen:
                raise ContentError(f"material {key} has duplicate gathering mode {mode_key}")
            seen.add(mode_key)
            try:
                mode = exploration_definition(mode_key, bundle)
            except ContentError:
                raise
            except ValueError as exc:
                raise ContentError(f"material {key} references unavailable mode {mode_key}") from exc
            if not bundle.has("location", mode.location_key, include_locked=False):
                raise ContentError(f"material {key} source references an unavailable location")
            if not bundle.has("realm", mode.required_realm, include_locked=False):
                raise ContentError(f"material {key} source references an unavailable realm")
            if mode.required_layer > bundle.require("realm", mode.required_realm)["layer_max"]:
                raise ContentError(f"material {key} source realm layer is invalid")
            if not bundle.has("reward", pool_key, include_locked=False):
                raise ContentError(f"material {key} references unavailable reward pool {pool_key}")
            _labels(bundle.require("reward", pool_key), f"material {key} reward pool {pool_key}")
            if exploration_reward_pool(mode_key, bundle) != pool_key:
                raise ContentError(f"material {key} reward pool is not consumed by {mode_key}")
            if not any(rewards.get(key, 0) > 0 for _, rewards in reward_pool_outcomes(pool_key, bundle)):
                raise ContentError(f"material {key} is not produced by {pool_key}")
            modes.add(mode_key)
            source_count += 1
        materials.add(key)
        consumers.update(recipe_consumers)
    return {
        "materials": len(materials),
        "gathering_sources": source_count,
        "modes": len(modes),
        "recipe_consumers": len(consumers),
    }


if __name__ == "__main__":
    import argparse
    import json

    from .content import bundled_content

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data_dir", nargs="?")
    args = parser.parse_args()
    print(json.dumps(validate_material_content(bundled_content(args.data_dir)), sort_keys=True))
