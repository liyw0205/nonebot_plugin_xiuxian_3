"""Versioned rules for the v0.2 production item effects."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..content import ContentBundle
from ..versions import active_content_version


# Kept as a compatibility export for old snapshots; new operations read the
# active content manifest rather than a documentation release number.
CONTENT_VERSION = active_content_version(fallback="content-0.2")
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


_FALLBACK_ITEM_DEFINITIONS = {
    "item.array.mist_barrier": ItemDefinition(
        "item.array.mist_barrier", "迷雾屏障阵", "mist_barrier", False
    ),
    "item.food.cloud_tea": ItemDefinition(
        "item.food.cloud_tea", "云灵茶", "cloud_tea", True
    ),
}


def _content_item_definitions() -> dict[str, ItemDefinition]:
    bundle = ContentBundle.load_optional(Path(__file__).resolve().parents[3] / "data")
    if bundle is None:
        return dict(_FALLBACK_ITEM_DEFINITIONS)
    result: dict[str, ItemDefinition] = {}
    for row in bundle.list("item", include_locked=False):
        key = row.get("key")
        if not isinstance(key, str):
            continue
        if key not in _FALLBACK_ITEM_DEFINITIONS and row.get("item_type") not in {"food", "array"}:
            continue
        fallback = _FALLBACK_ITEM_DEFINITIONS.get(key)
        result[key] = ItemDefinition(
            key=key,
            name=str(row.get("name") or (fallback.name if fallback else key)),
            kind=fallback.kind if fallback else str(row.get("item_type") or "item"),
            tradeable=bool(row.get("tradeable", fallback.tradeable if fallback else False)),
        )
    for key, definition in _FALLBACK_ITEM_DEFINITIONS.items():
        result.setdefault(key, definition)
    return result


ITEM_DEFINITIONS = _content_item_definitions()

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
