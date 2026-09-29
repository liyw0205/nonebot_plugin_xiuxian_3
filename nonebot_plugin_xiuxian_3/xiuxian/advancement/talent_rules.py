"""Data-backed talent-tree definitions and lookups."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..content import ContentBundle, ContentError, bundled_content


_DEFAULT_CONTENT = bundled_content()


@dataclass(frozen=True, slots=True)
class TalentNodeDefinition:
    key: str
    tree_key: str
    tree_label: str
    tier: int
    label: str
    description: str
    effect: dict[str, Any]
    cost_points: int
    prerequisites: tuple[str, ...]


def _content(content: ContentBundle | None) -> ContentBundle:
    return content or _DEFAULT_CONTENT


def talent_node_definitions(content: ContentBundle | None = None) -> tuple[TalentNodeDefinition, ...]:
    bundle = _content(content)
    definitions: list[TalentNodeDefinition] = []
    positions: set[tuple[str, int]] = set()
    for row in bundle.list("talent", include_locked=False):
        key = row.get("key")
        tree_key = row.get("tree_key")
        label = row.get("name")
        description = row.get("desc")
        tier = row.get("tier")
        cost = row.get("cost_points")
        effect = row.get("effect")
        prerequisites = row.get("prerequisites")
        if not isinstance(key, str) or not key:
            raise ContentError("talent record requires key")
        if not isinstance(tree_key, str) or not tree_key:
            raise ContentError(f"talent {key} requires tree_key")
        tree = _tree_record(bundle, tree_key)
        tree_label = tree.get("talent_tree_label")
        if not isinstance(tree_label, str) or not tree_label.strip():
            raise ContentError(f"path {tree_key} requires talent_tree_label")
        if not isinstance(label, str) or not label.strip():
            raise ContentError(f"talent {key} requires name")
        if not isinstance(description, str) or not description.strip():
            raise ContentError(f"talent {key} requires desc")
        if not isinstance(tier, int) or isinstance(tier, bool) or tier < 1:
            raise ContentError(f"talent {key} tier must be a positive integer")
        if not isinstance(cost, int) or isinstance(cost, bool) or cost < 0:
            raise ContentError(f"talent {key} cost_points must be a non-negative integer")
        if not isinstance(effect, dict) or not effect:
            raise ContentError(f"talent {key} effect must be a non-empty object")
        if not isinstance(prerequisites, list) or any(not isinstance(item, str) for item in prerequisites):
            raise ContentError(f"talent {key} prerequisites must be a string list")
        position = (tree_key, tier)
        if position in positions:
            raise ContentError(f"duplicate talent tier: {tree_key}:{tier}")
        positions.add(position)
        definitions.append(
            TalentNodeDefinition(
                key=key,
                tree_key=tree_key,
                tree_label=tree_label.strip(),
                tier=tier,
                label=label.strip(),
                description=description.strip(),
                effect=dict(effect),
                cost_points=cost,
                prerequisites=tuple(prerequisites),
            )
        )

    keys = {definition.key for definition in definitions}
    for definition in definitions:
        for prerequisite_key in definition.prerequisites:
            prerequisite = next((item for item in definitions if item.key == prerequisite_key), None)
            if prerequisite is None:
                raise ContentError(f"talent {definition.key} references missing prerequisite {prerequisite_key}")
            if prerequisite.tree_key != definition.tree_key or prerequisite.tier >= definition.tier:
                raise ContentError(f"talent {definition.key} has invalid prerequisite {prerequisite_key}")
    if len(keys) != len(definitions):
        raise ContentError("duplicate talent key")
    return tuple(definitions)


def _tree_record(content: ContentBundle, value: str) -> dict[str, Any]:
    for row in content.list("path", include_locked=False):
        if value in {str(row.get("key", "")), str(row.get("name", "")), str(row.get("talent_tree_label", ""))}:
            return row
    raise ContentError(f"talent tree references unknown path: {value}")


def tree_definition(tree_key: str | None, content: ContentBundle | None = None) -> tuple[str, str]:
    normalized = (tree_key or "").strip()
    bundle = _content(content)
    if not normalized:
        raise ValueError(f"unsupported talent tree: {tree_key}")
    for row in bundle.list("path", include_locked=False):
        if normalized not in {
            str(row.get("key", "")),
            str(row.get("name", "")),
            str(row.get("talent_tree_label", "")),
        }:
            continue
        key = str(row["key"])
        label = row.get("talent_tree_label")
        if not isinstance(label, str) or not label.strip():
            raise ContentError(f"path {key} requires talent_tree_label")
        return key, label.strip()
    raise ValueError(f"unsupported talent tree: {tree_key}")


def talent_node_definition(
    node_key: str,
    content: ContentBundle | None = None,
) -> TalentNodeDefinition:
    normalized = node_key.strip()
    for definition in talent_node_definitions(content):
        if definition.key == normalized:
            return definition
    raise ValueError(f"unsupported talent node: {node_key}")


def talent_node_for_reference(
    reference: str,
    *,
    tree_key: str | None = None,
    content: ContentBundle | None = None,
) -> TalentNodeDefinition:
    normalized = reference.strip()
    definitions = talent_node_definitions(content)
    definition = next((item for item in definitions if item.key == normalized), None)
    if definition is None:
        try:
            tier = int(normalized)
        except ValueError as exc:
            raise ValueError(f"unsupported talent node: {reference}") from exc
        if tree_key is None:
            raise ValueError(f"talent tier requires a tree: {reference}")
        resolved_tree, _ = tree_definition(tree_key, content)
        matches = [item for item in definitions if item.tree_key == resolved_tree and item.tier == tier]
        if len(matches) != 1:
            raise ValueError(f"unsupported talent tier: {reference}")
        definition = matches[0]
    if tree_key is not None:
        resolved_tree, _ = tree_definition(tree_key, content)
        if definition.tree_key != resolved_tree:
            raise ValueError("talent node does not belong to the selected path")
    return definition


def talent_tree_keys(content: ContentBundle | None = None) -> tuple[str, ...]:
    return tuple(dict.fromkeys(item.tree_key for item in talent_node_definitions(content)))


def talent_tree_nodes(tree_key: str, content: ContentBundle | None = None) -> tuple[TalentNodeDefinition, ...]:
    resolved_tree, _ = tree_definition(tree_key, content)
    nodes = tuple(
        sorted(
            (item for item in talent_node_definitions(content) if item.tree_key == resolved_tree),
            key=lambda item: item.tier,
        )
    )
    if not nodes:
        raise ValueError(f"talent tree has no nodes: {tree_key}")
    return nodes


__all__ = [
    "TalentNodeDefinition",
    "talent_node_definition",
    "talent_node_definitions",
    "talent_node_for_reference",
    "talent_tree_keys",
    "talent_tree_nodes",
    "tree_definition",
]
