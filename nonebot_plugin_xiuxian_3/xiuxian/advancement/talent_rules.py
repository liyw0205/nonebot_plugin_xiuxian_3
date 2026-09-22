"""Pure, versioned rules for the v0.1 talent trees."""

from __future__ import annotations

from dataclasses import dataclass


CONTENT_VERSION = "content-0.1"
RULE_VERSION = "advancement-0.1.0"
TALENT_POINT_RESOURCE = "resource.talent_point"
MAX_TALENT_TIER = 5
TALENT_COSTS = (0, 1, 2, 3, 5)


@dataclass(frozen=True, slots=True)
class TalentNodeDefinition:
    key: str
    tree_key: str
    tree_label: str
    tier: int
    label: str
    description: str
    effect: dict[str, int | str]
    cost_points: int
    content_version: str = CONTENT_VERSION
    rule_version: str = RULE_VERSION


_TREE_META = {
    "body": ("体修道脉", "体魄淬炼"),
    "spell": ("法修道脉", "灵力运转"),
    "device": ("器修道脉", "机关精研"),
    "demonic": ("魔修道脉", "魔息锻魂"),
    "beast": ("妖修道脉", "血脉驭形"),
    "support": ("辅修道脉", "百艺通明"),
}

_TREE_EFFECTS = {
    "body": ("body_efficiency_bp", "体魄行动效率"),
    "spell": ("spell_efficiency_bp", "术法行动效率"),
    "device": ("device_efficiency_bp", "机关行动效率"),
    "demonic": ("demonic_efficiency_bp", "魔息行动效率"),
    "beast": ("beast_efficiency_bp", "灵兽行动效率"),
    "support": ("support_efficiency_bp", "辅修行动效率"),
}

_TIER_VALUES = (100, 150, 200, 250, 300)


def _build_definitions() -> dict[str, TalentNodeDefinition]:
    definitions: dict[str, TalentNodeDefinition] = {}
    for tree_key, (tree_label, stem) in _TREE_META.items():
        effect_type, effect_label = _TREE_EFFECTS[tree_key]
        for tier, (cost, value) in enumerate(zip(TALENT_COSTS, _TIER_VALUES, strict=True), start=1):
            key = f"talent.tree.{tree_key}.tier{tier}"
            whole = value // 100
            fraction = value % 100
            definitions[key] = TalentNodeDefinition(
                key=key,
                tree_key=tree_key,
                tree_label=tree_label,
                tier=tier,
                label=f"{stem}·第{tier}阶",
                description=f"{effect_label} +{whole}.{fraction // 10}%。",
                effect={"type": effect_type, "value": value},
                cost_points=cost,
            )
    return definitions


TALENT_NODE_DEFINITIONS = _build_definitions()
TREE_ALIASES = {
    "体修": "body",
    "体修道脉": "body",
    "法修": "spell",
    "法修道脉": "spell",
    "器修": "device",
    "器修道脉": "device",
    "魔修": "demonic",
    "魔修道脉": "demonic",
    "妖修": "beast",
    "妖修道脉": "beast",
    "辅修": "support",
    "辅修道脉": "support",
    **{key: key for key in _TREE_META},
}


def tree_definition(tree_key: str | None) -> tuple[str, str]:
    normalized = (tree_key or "").strip()
    key = TREE_ALIASES.get(normalized, normalized)
    try:
        return key, _TREE_META[key][0]
    except KeyError as exc:
        raise ValueError(f"unsupported talent tree: {tree_key}") from exc


def talent_node_definition(node_key: str) -> TalentNodeDefinition:
    normalized = node_key.strip()
    try:
        return TALENT_NODE_DEFINITIONS[normalized]
    except KeyError as exc:
        raise ValueError(f"unsupported talent node: {node_key}") from exc


def talent_node_for_reference(reference: str, *, tree_key: str | None = None) -> TalentNodeDefinition:
    normalized = reference.strip()
    if normalized in TALENT_NODE_DEFINITIONS:
        definition = TALENT_NODE_DEFINITIONS[normalized]
    else:
        try:
            tier = int(normalized)
        except ValueError as exc:
            raise ValueError(f"unsupported talent node: {reference}") from exc
        if tier < 1 or tier > MAX_TALENT_TIER:
            raise ValueError(f"unsupported talent tier: {reference}")
        resolved_tree, _ = tree_definition(tree_key)
        definition = talent_node_definition(f"talent.tree.{resolved_tree}.tier{tier}")
    if tree_key:
        resolved_tree, _ = tree_definition(tree_key)
        if definition.tree_key != resolved_tree:
            raise ValueError("talent node does not belong to the selected path")
    return definition


def talent_tree_nodes(tree_key: str) -> tuple[TalentNodeDefinition, ...]:
    resolved_tree, _ = tree_definition(tree_key)
    return tuple(
        TALENT_NODE_DEFINITIONS[f"talent.tree.{resolved_tree}.tier{tier}"]
        for tier in range(1, MAX_TALENT_TIER + 1)
    )


__all__ = [
    "CONTENT_VERSION",
    "MAX_TALENT_TIER",
    "RULE_VERSION",
    "TALENT_COSTS",
    "TALENT_NODE_DEFINITIONS",
    "TALENT_POINT_RESOURCE",
    "TalentNodeDefinition",
    "talent_node_definition",
    "talent_node_for_reference",
    "talent_tree_nodes",
    "tree_definition",
]
