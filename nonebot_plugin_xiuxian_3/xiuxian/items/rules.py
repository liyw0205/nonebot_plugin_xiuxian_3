"""Versioned rules for the v0.2 production item effects."""

from __future__ import annotations

from dataclasses import dataclass


CONTENT_VERSION = "content-0.2"
RULE_VERSION = "items-0.2.0"
MIST_BARRIER_RISK_REDUCTION_BP = 500
MIST_BARRIER_DURATION_SECONDS = 12 * 60 * 60
CLOUD_TEA_STATE_BP_BONUS = 500


@dataclass(frozen=True, slots=True)
class ItemDefinition:
    key: str
    name: str
    kind: str
    tradeable: bool


ITEM_DEFINITIONS = {
    "item.array.mist_barrier": ItemDefinition(
        "item.array.mist_barrier", "迷雾屏障阵", "mist_barrier", False
    ),
    "item.food.cloud_tea": ItemDefinition(
        "item.food.cloud_tea", "云灵茶", "cloud_tea", True
    ),
}

ITEM_ALIASES = {
    **{key: key for key in ITEM_DEFINITIONS},
    "迷雾屏障阵": "item.array.mist_barrier",
    "迷雾屏障": "item.array.mist_barrier",
    "云灵茶": "item.food.cloud_tea",
    "云茶": "item.food.cloud_tea",
}
ITEM_LABELS = {key: definition.name for key, definition in ITEM_DEFINITIONS.items()}


def resolve_item(value: str) -> ItemDefinition:
    key = ITEM_ALIASES.get((value or "").strip(), (value or "").strip())
    try:
        return ITEM_DEFINITIONS[key]
    except KeyError as exc:
        raise ValueError(f"unsupported usable item: {value}") from exc


__all__ = [
    "CLOUD_TEA_STATE_BP_BONUS",
    "CONTENT_VERSION",
    "ITEM_ALIASES",
    "ITEM_DEFINITIONS",
    "ITEM_LABELS",
    "MIST_BARRIER_DURATION_SECONDS",
    "MIST_BARRIER_RISK_REDUCTION_BP",
    "RULE_VERSION",
    "ItemDefinition",
    "resolve_item",
]
