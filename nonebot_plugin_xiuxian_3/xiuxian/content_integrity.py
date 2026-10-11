"""Cross-domain checks for the shipped content package.

The loader intentionally stays structural so individual domains can be loaded
without importing every rules module.  Release validation uses this module to
prove that active JSON records are registered, referenced, and consumable.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .content import ContentBundle, ContentError

_OPEN = {"active", "open"}


def validate_reward_content(bundle: ContentBundle) -> int:
    from .rewards.rules import reward_pool_outcomes

    pools = 0
    for row in bundle.list("reward", include_locked=False):
        if row.get("pool_type") != "weighted":
            continue
        key = _record_key(row, "reward pool")
        outcomes = reward_pool_outcomes(key, bundle)
        if not outcomes or not any(rewards for _, rewards in outcomes):
            raise ContentError(f"reward pool {key} is empty")
        pools += 1
    return pools


def validate_source_content(bundle: ContentBundle) -> int:
    """Validate source declarations without treating them as new producers."""

    source_count = 0
    for row in bundle.list("source", include_locked=False):
        key = _record_key(row, "source")
        _labels(row, f"source {key}")
        assets = row.get("asset_keys")
        selector = row.get("asset_selector")
        if assets is None and selector is None:
            raise ContentError(f"source {key} requires asset_keys or asset_selector")
        if assets is not None:
            if not isinstance(assets, list) or not assets:
                raise ContentError(f"source {key} asset_keys must be non-empty")
            for asset_key in assets:
                if not isinstance(asset_key, str) or not asset_key.strip() or not _asset_exists(bundle, asset_key):
                    raise ContentError(f"source {key} references unavailable asset {asset_key!r}")
        if selector is not None:
            if not isinstance(selector, dict) or selector.get("kind") != "item":
                raise ContentError(f"source {key} has an invalid asset_selector")
            item_types = selector.get("item_types")
            if not isinstance(item_types, list) or not item_types or any(
                not isinstance(value, str) or not value.strip() for value in item_types
            ):
                raise ContentError(f"source {key} asset_selector item_types must be non-empty")
            matches = [
                item for item in bundle.list("item", include_locked=False)
                if item.get("item_type") in item_types
                and selector.get("status", "active") in {"active", "open"}
            ]
            if not matches:
                raise ContentError(f"source {key} asset_selector matches no items")
        channels = row.get("channels")
        if not isinstance(channels, list) or not channels:
            raise ContentError(f"source {key} channels must be non-empty")
        for channel in channels:
            if not isinstance(channel, dict):
                raise ContentError(f"source {key} has a malformed channel")
            operation = channel.get("operation")
            reference = channel.get("reference")
            if not isinstance(operation, str) or not operation.strip():
                raise ContentError(f"source {key} channel operation is required")
            if not isinstance(reference, str) or not reference.strip():
                raise ContentError(f"source {key} channel reference is required")
            _validate_source_reference(bundle, key, reference)
        source_count += 1
    return source_count


def validate_exploration_content(bundle: ContentBundle) -> int:
    """Validate active modes and their non-empty reward/encounter pools."""

    from .exploration.rules import _definitions
    from .rewards.rules import reward_pool_outcomes

    definitions = _definitions(bundle)
    for row in bundle.list("exploration_mode", include_locked=False):
        key = str(row["key"])
        outcomes = reward_pool_outcomes(str(row["reward_pool_key"]), bundle)
        if not any(rewards for _, rewards in outcomes):
            raise ContentError(f"exploration mode {key} references an empty reward pool")
        enemy_pool_key = row.get("enemy_pool_key")
        if enemy_pool_key is not None:
            pool = bundle.get("encounter_pool", str(enemy_pool_key), include_locked=False)
            if pool is None or not isinstance(pool.get("candidates"), list) or not pool["candidates"]:
                raise ContentError(f"exploration mode {key} references an empty encounter pool")
    return len(definitions)


def validate_content_references(bundle: ContentBundle) -> dict[str, int]:
    """Run the release-time validation for all currently active content domains."""

    _validate_manifest_files(bundle)
    from .adventures.rules import bounty_definitions
    from .combat_content import validate_combat_content
    from .material_content import validate_material_content
    from .production.rules import recipe_definitions
    from .world_content import validate_world_content
    from .exploration.rules import _definitions

    world = validate_world_content(bundle)
    combat = validate_combat_content(bundle)
    modes = validate_exploration_content(bundle)
    rewards = validate_reward_content(bundle)
    bounties = len(bounty_definitions(bundle))
    recipes = len(recipe_definitions(bundle))
    materials = validate_material_content(bundle)
    sources = validate_source_content(bundle)
    return {
        **world,
        "exploration_modes": modes,
        "reward_pools": rewards,
        "bounties": bounties,
        "recipes": recipes,
        "sources": sources,
        **{f"materials_{key}": value for key, value in materials.items()},
        **{f"combat_{key}": value for key, value in combat.items()},
    }


def _validate_manifest_files(bundle: ContentBundle) -> None:
    listed = {str(path) for path in bundle.manifest.get("files", [])}
    actual = {
        path.relative_to(bundle.root).as_posix()
        for path in bundle.root.rglob("*.json")
        if path.name != "内容清单.json"
    }
    if actual != listed:
        missing = sorted(actual - listed)
        stale = sorted(listed - actual)
        raise ContentError(f"content manifest coverage mismatch; missing={missing!r}, stale={stale!r}")


def _validate_source_reference(bundle: ContentBundle, source_key: str, reference: str) -> None:
    if reference.startswith("reward_pool."):
        from .rewards.rules import reward_pool_outcomes

        try:
            reward_pool_outcomes(reference, bundle)
        except (KeyError, ValueError) as exc:
            raise ContentError(f"source {source_key} references invalid reward pool {reference}") from exc
        return
    if reference.startswith("reward."):
        if not bundle.has("reward", reference, include_locked=False):
            raise ContentError(f"source {source_key} references unavailable reward {reference}")
        return
    if reference.startswith("story.") and ":" in reference:
        story_key, stage_key = reference.split(":", 1)
        if story_key == "story.mainline.xuantian":
            if not bundle.has("mainline", stage_key, include_locked=False):
                raise ContentError(f"source {source_key} references unavailable mainline stage {stage_key}")
        elif not (bundle.has("mainline", story_key, include_locked=False) or bundle.has("story", story_key, include_locked=False)):
            raise ContentError(f"source {source_key} references unavailable story {story_key}")
        return
    if reference.startswith("recipe.") and not bundle.has("recipe", reference, include_locked=False):
        raise ContentError(f"source {source_key} references unavailable recipe {reference}")
    if reference.startswith("beast.evolution.") and not bundle.has("companion_evolution", reference, include_locked=False):
        raise ContentError(f"source {source_key} references unavailable evolution {reference}")


def _asset_exists(bundle: ContentBundle, key: str) -> bool:
    return any(bundle.has(kind, key, include_locked=False) for kind in ("item", "companion", "codex_entry"))


def _record_key(row: dict[str, Any], kind: str) -> str:
    key = row.get("key")
    if not isinstance(key, str) or not key.strip():
        raise ContentError(f"{kind} requires a stable key")
    return key


def _labels(row: dict[str, Any], context: str) -> None:
    for field in ("name", "desc"):
        if not isinstance(row.get(field), str) or not row[field].strip():
            raise ContentError(f"{context} requires non-empty {field}")


__all__ = [
    "validate_content_references",
    "validate_exploration_content",
    "validate_reward_content",
    "validate_source_content",
]


if __name__ == "__main__":
    import argparse
    import json

    from .content import bundled_content

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("data_dir", nargs="?")
    args = parser.parse_args()
    print(json.dumps(validate_content_references(bundled_content(args.data_dir)), ensure_ascii=False, sort_keys=True))
