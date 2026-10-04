"""Rules for consumable production item effects."""

from __future__ import annotations


from dataclasses import dataclass
from typing import Any

from ..content import ContentBundle, ContentError, bundled_content


_SUPPORTED_EFFECTS = frozenset(
    {
        "next_cultivation_state_bonus_bp",
        "exploration_risk_reduction_bp",
        "restore_choice",
    }
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
    location_key: str | None = None
    resources: tuple[str, ...] = ()
    cooldown_seconds: int | None = None


@dataclass(frozen=True, slots=True)
class ItemRecord:
    """Content-backed item metadata shared by inventory-facing domains."""

    key: str
    name: str
    aliases: tuple[str, ...]
    item_type: str
    bind_type: str
    tradeable: bool
    effects: tuple[dict[str, Any], ...]


def item_records(content: ContentBundle | None = None) -> dict[str, ItemRecord]:
    bundle = content or bundled_content()
    result: dict[str, ItemRecord] = {}
    for row in bundle.list("item", include_locked=False):
        key = row.get("key")
        name = row.get("name")
        item_type = row.get("item_type")
        bind_type = row.get("bind_type")
        aliases = row.get("aliases", [])
        effects = row.get("effects")
        if not isinstance(key, str) or not key.strip() or not isinstance(name, str) or not name.strip():
            raise ContentError(f"item requires key and name: {row!r}")
        if not isinstance(item_type, str) or not item_type.strip():
            raise ContentError(f"item {key} item_type must be a non-empty string")
        if not isinstance(bind_type, str) or not bind_type.strip():
            raise ContentError(f"item {key} bind_type must be a non-empty string")
        if not isinstance(aliases, list) or any(not isinstance(alias, str) or not alias.strip() for alias in aliases):
            raise ContentError(f"item {key} aliases must be non-empty strings")
        if not isinstance(effects, list) or any(not isinstance(effect, dict) or not isinstance(effect.get("type"), str) for effect in effects):
            raise ContentError(f"item {key} effects must be a list of typed objects")
        tradeable = row.get("tradeable")
        if not isinstance(tradeable, bool):
            raise ContentError(f"item {key} tradeable must be boolean")
        result[key] = ItemRecord(
            key=key,
            name=name.strip(),
            aliases=tuple(aliases),
            item_type=item_type.strip(),
            bind_type=bind_type.strip(),
            tradeable=tradeable,
            effects=tuple(dict(effect) for effect in effects),
        )
    return result


def item_aliases(content: ContentBundle | None = None) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, record in item_records(content).items():
        for alias in (key, record.name, *record.aliases):
            if alias in result and result[alias] != key:
                raise ContentError(f"duplicate item alias: {alias}")
            result[alias] = key
    return result


def _content_item_definitions(content: ContentBundle | None = None) -> dict[str, ItemDefinition]:
    bundle = content or bundled_content()
    result: dict[str, ItemDefinition] = {}
    for key, record in item_records(bundle).items():
        effects = list(record.effects)
        supported = [effect for effect in effects if effect.get("type") in _SUPPORTED_EFFECTS]
        if not supported:
            continue
        if len(supported) != 1:
            raise ContentError(f"usable item {key} must define exactly one supported active effect")
        configured_effect = supported[0]
        effect_type = configured_effect.get("type")
        if not isinstance(effect_type, str) or not effect_type.strip():
            raise ContentError(f"usable item {key} effect type must be a string")
        value = configured_effect.get("amount" if effect_type == "restore_choice" else "value")
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise ContentError(f"usable item {key} effect amount must be a positive integer")
        row = bundle.get("item", key, include_locked=False)
        if row is None:
            raise ContentError(f"usable item {key} is not active")
        duration = row.get("bind_duration_seconds")
        if duration is not None and (not isinstance(duration, int) or isinstance(duration, bool) or duration <= 0):
            raise ContentError(f"usable item {key} bind_duration_seconds must be positive")
        if effect_type == "exploration_risk_reduction_bp" and duration is None:
            raise ContentError(f"usable item {key} requires bind_duration_seconds")
        resources: tuple[str, ...] = ()
        cooldown_seconds: int | None = None
        if effect_type == "restore_choice":
            raw_resources = configured_effect.get("resources")
            if (
                not isinstance(raw_resources, list)
                or not raw_resources
                or any(resource not in {"stamina", "energy"} for resource in raw_resources)
                or len(set(raw_resources)) != len(raw_resources)
            ):
                raise ContentError(f"usable item {key} restore_choice resources are invalid")
            raw_cooldown = configured_effect.get("cooldown_seconds")
            if isinstance(raw_cooldown, bool) or not isinstance(raw_cooldown, int) or raw_cooldown <= 0:
                raise ContentError(f"usable item {key} restore_choice cooldown_seconds must be positive")
            resources = tuple(raw_resources)
            cooldown_seconds = raw_cooldown
        location_key = configured_effect.get("location_key")
        if location_key is not None and (not isinstance(location_key, str) or not location_key.strip()):
            raise ContentError(f"usable item {key} location_key must be a non-empty string")
        if location_key is not None and not bundle.has("location", location_key, include_locked=False):
            raise ContentError(f"usable item {key} location_key is not an active location")
        result[key] = ItemDefinition(
            key=key,
            name=record.name,
            effect_type=effect_type,
            effect_value=value,
            duration_seconds=duration,
            tradeable=record.tradeable,
            aliases=record.aliases,
            location_key=location_key,
            resources=resources,
            cooldown_seconds=cooldown_seconds,
        )
    return result


ITEM_ALIASES = item_aliases()
ITEM_DEFINITIONS = _content_item_definitions()
ITEM_LABELS = {key: definition.name for key, definition in ITEM_DEFINITIONS.items()}


def resolve_item(value: str, content: ContentBundle | None = None) -> ItemDefinition:
    definitions = _content_item_definitions(content)
    aliases = item_aliases(content)
    key = aliases.get((value or "").strip(), (value or "").strip())
    try:
        return definitions[key]
    except KeyError as exc:
        raise ValueError(f"unsupported usable item: {value}") from exc


def resolve_item_record(value: str, content: ContentBundle | None = None) -> ItemRecord:
    records = item_records(content)
    aliases = item_aliases(content)
    key = aliases.get((value or "").strip(), (value or "").strip())
    try:
        return records[key]
    except KeyError as exc:
        raise ValueError(f"unknown item: {value}") from exc


__all__ = [
    "ITEM_ALIASES",
    "ITEM_DEFINITIONS",
    "ITEM_LABELS",
    "ItemDefinition",
    "ItemRecord",
    "item_aliases",
    "item_records",
    "resolve_item",
    "resolve_item_record",
]
