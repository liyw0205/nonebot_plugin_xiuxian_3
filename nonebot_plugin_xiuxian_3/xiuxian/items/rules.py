"""Versioned rules for the v0.2 production item effects."""

from __future__ import annotations


from dataclasses import dataclass

from ..content import ContentBundle, ContentError, bundled_content


# Kept as a compatibility export for old snapshots; new operations read the
# active content manifest rather than a documentation release number.
CONTENT_VERSION = ""
RULE_VERSION = ""
_SUPPORTED_EFFECTS = frozenset(
    {"next_cultivation_state_bonus_bp", "exploration_risk_reduction_bp"}
)


@dataclass(frozen=True, slots=True)
class ItemDefinition:
    key: str
    name: str
    effect_type: str
    effect_value: int
    duration_seconds: int | None
    tradeable: bool
    aliases: tuple[str, ...]


def _content_item_definitions() -> dict[str, ItemDefinition]:
    bundle = bundled_content()
    result: dict[str, ItemDefinition] = {}
    for row in bundle.list("item", include_locked=False):
        effects = row.get("effects")
        if not isinstance(effects, list) or any(
            not isinstance(effect, dict) or not isinstance(effect.get("type"), str)
            for effect in effects
        ):
            raise ContentError(f"item {row.get('key')} effects must be a list")
        supported = [effect for effect in effects if effect.get("type") in _SUPPORTED_EFFECTS]
        if not supported:
            continue
        key = row.get("key")
        name = row.get("name")
        if not isinstance(key, str) or not isinstance(name, str) or not name.strip():
            raise ContentError(f"usable item requires key and name: {row!r}")
        if len(supported) != 1:
            raise ContentError(f"usable item {key} must define exactly one supported active effect")
        configured_effect = supported[0]
        value = configured_effect.get("value")
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise ContentError(f"usable item {key} effect value must be a positive integer")
        duration = row.get("bind_duration_seconds")
        if duration is not None and (not isinstance(duration, int) or isinstance(duration, bool) or duration <= 0):
            raise ContentError(f"usable item {key} bind_duration_seconds must be positive")
        effect_type = str(configured_effect["type"])
        if effect_type == "exploration_risk_reduction_bp" and duration is None:
            raise ContentError(f"usable item {key} requires bind_duration_seconds")
        aliases = row.get("aliases", [])
        if not isinstance(aliases, list) or any(not isinstance(alias, str) or not alias.strip() for alias in aliases):
            raise ContentError(f"usable item {key} aliases must be non-empty strings")
        if not isinstance(row.get("tradeable"), bool):
            raise ContentError(f"usable item {key} tradeable must be boolean")
        result[key] = ItemDefinition(
            key=key,
            name=name.strip(),
            effect_type=effect_type,
            effect_value=value,
            duration_seconds=duration,
            tradeable=row["tradeable"],
            aliases=tuple(aliases),
        )
    return result


ITEM_DEFINITIONS = _content_item_definitions()

ITEM_ALIASES: dict[str, str] = {}
for _key, _definition in ITEM_DEFINITIONS.items():
    for _alias in (_key, _definition.name, *_definition.aliases):
        if _alias in ITEM_ALIASES:
            raise ContentError(f"duplicate usable item alias: {_alias}")
        ITEM_ALIASES[_alias] = _key
ITEM_LABELS = {key: definition.name for key, definition in ITEM_DEFINITIONS.items()}


def resolve_item(value: str) -> ItemDefinition:
    key = ITEM_ALIASES.get((value or "").strip(), (value or "").strip())
    try:
        return ITEM_DEFINITIONS[key]
    except KeyError as exc:
        raise ValueError(f"unsupported usable item: {value}") from exc


__all__ = [
    "CONTENT_VERSION",
    "ITEM_ALIASES",
    "ITEM_DEFINITIONS",
    "ITEM_LABELS",
    "RULE_VERSION",
    "ItemDefinition",
    "resolve_item",
]
