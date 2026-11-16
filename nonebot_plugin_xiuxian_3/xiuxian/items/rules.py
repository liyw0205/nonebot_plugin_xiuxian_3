"""Rules for consumable production item effects."""

from __future__ import annotations


from dataclasses import dataclass
from threading import Lock
from typing import Any

from ..content import ContentBundle, ContentError, bundled_content


_SUPPORTED_EFFECTS = frozenset(
    {
        "next_cultivation_state_bonus_bp",
        "exploration_risk_reduction_bp",
        "restore_choice",
        "grant_intro_flags",
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
    granted_flags: tuple[str, ...] = ()


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


@dataclass(frozen=True, slots=True)
class _ItemCatalogue:
    records: dict[str, ItemRecord]
    aliases: dict[str, str]
    definitions: dict[str, ItemDefinition]


_ITEM_CATALOGUE_CACHE: list[tuple[int, ContentBundle, _ItemCatalogue]] = []
_ITEM_CATALOGUE_CACHE_LOCK = Lock()
_ITEM_CATALOGUE_BUILD_COUNT = 0


def _build_item_records(bundle: ContentBundle) -> dict[str, ItemRecord]:
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


def _build_item_aliases(records: dict[str, ItemRecord]) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, record in records.items():
        for alias in (key, record.name, *record.aliases):
            if alias in result and result[alias] != key:
                raise ContentError(f"duplicate item alias: {alias}")
            result[alias] = key
    return result


def _build_item_definitions(
    bundle: ContentBundle, records: dict[str, ItemRecord]
) -> dict[str, ItemDefinition]:
    result: dict[str, ItemDefinition] = {}
    for key, record in records.items():
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
        granted_flags: tuple[str, ...] = ()
        if effect_type == "grant_intro_flags":
            raw_flags = configured_effect.get("flags")
            if (
                set(configured_effect) != {"type", "flags"}
                or not isinstance(raw_flags, list)
                or not raw_flags
                or any(not isinstance(flag, str) or not flag.strip() for flag in raw_flags)
                or len(set(raw_flags)) != len(raw_flags)
            ):
                raise ContentError(f"usable item {key} grant_intro_flags is invalid")
            granted_flags = tuple(raw_flags)
            value = 0
        else:
            value = configured_effect.get("amount" if effect_type == "restore_choice" else "value")
        if effect_type != "grant_intro_flags" and (not isinstance(value, int) or isinstance(value, bool) or value <= 0):
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
                or any(resource not in {"stamina", "energy", "void_power"} for resource in raw_resources)
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
            granted_flags=granted_flags,
        )
    return result


def _item_catalogue(content: ContentBundle | None = None) -> _ItemCatalogue:
    global _ITEM_CATALOGUE_BUILD_COUNT
    bundle = content or bundled_content()
    bundle_id = id(bundle)
    with _ITEM_CATALOGUE_CACHE_LOCK:
        for cached_id, cached_bundle, catalogue in reversed(_ITEM_CATALOGUE_CACHE):
            if cached_id == bundle_id and cached_bundle is bundle:
                return catalogue
        records = _build_item_records(bundle)
        catalogue = _ItemCatalogue(
            records=records,
            aliases=_build_item_aliases(records),
            definitions=_build_item_definitions(bundle, records),
        )
        _ITEM_CATALOGUE_CACHE[:] = [
            item for item in _ITEM_CATALOGUE_CACHE
            if not (item[0] == bundle_id and item[1] is bundle)
        ]
        _ITEM_CATALOGUE_CACHE.append((bundle_id, bundle, catalogue))
        if len(_ITEM_CATALOGUE_CACHE) > 16:
            del _ITEM_CATALOGUE_CACHE[:-16]
        _ITEM_CATALOGUE_BUILD_COUNT += 1
        return catalogue


def _copy_item_records(records: dict[str, ItemRecord]) -> dict[str, ItemRecord]:
    return {
        key: ItemRecord(
            key=record.key,
            name=record.name,
            aliases=record.aliases,
            item_type=record.item_type,
            bind_type=record.bind_type,
            tradeable=record.tradeable,
            effects=tuple(dict(effect) for effect in record.effects),
        )
        for key, record in records.items()
    }


def item_records(content: ContentBundle | None = None) -> dict[str, ItemRecord]:
    return _copy_item_records(_item_catalogue(content).records)


def item_aliases(content: ContentBundle | None = None) -> dict[str, str]:
    return dict(_item_catalogue(content).aliases)


def _content_item_definitions(content: ContentBundle | None = None) -> dict[str, ItemDefinition]:
    return dict(_item_catalogue(content).definitions)


ITEM_ALIASES = item_aliases()
ITEM_DEFINITIONS = _content_item_definitions()
ITEM_LABELS = {key: definition.name for key, definition in ITEM_DEFINITIONS.items()}

BOUND_ORDER_DURATION_EFFECT = "production_duration_multiplier_bp"


def bound_order_duration_multiplier_bp(
    inventory: dict[str, int], content: ContentBundle | None = None
) -> int | None:
    """Return the strongest *declared* bound-order duration multiplier held.

    A held array item carries its own ``production_duration_multiplier_bp``
    effect, so the facility order speed-up is read from the item's data rather
    than a hardcoded key/value pair. Only effects scoped to a bound order (or
    with no declared scope) apply; the strongest declared multiplier wins when
    several arrays are held. Returns ``None`` when no array declares one.
    """

    records = _item_catalogue(content).records
    best: int | None = None
    for raw_key, raw_quantity in inventory.items():
        try:
            quantity = int(raw_quantity)
        except (TypeError, ValueError):
            continue
        if quantity <= 0:
            continue
        record = records.get(str(raw_key))
        if record is None:
            continue
        for effect in record.effects:
            if effect.get("type") != BOUND_ORDER_DURATION_EFFECT:
                continue
            if effect.get("scope") not in (None, "bound_order"):
                continue
            value = effect.get("value")
            if isinstance(value, bool) or not isinstance(value, int):
                continue
            if not 0 < value < 10_000:
                continue
            best = value if best is None else min(best, value)
    return best


def resolve_item(value: str, content: ContentBundle | None = None) -> ItemDefinition:
    catalogue = _item_catalogue(content)
    definitions = catalogue.definitions
    aliases = catalogue.aliases
    key = aliases.get((value or "").strip(), (value or "").strip())
    try:
        return definitions[key]
    except KeyError as exc:
        raise ValueError(f"unsupported usable item: {value}") from exc


def resolve_item_record(value: str, content: ContentBundle | None = None) -> ItemRecord:
    catalogue = _item_catalogue(content)
    records = catalogue.records
    aliases = catalogue.aliases
    key = aliases.get((value or "").strip(), (value or "").strip())
    try:
        return records[key]
    except KeyError as exc:
        raise ValueError(f"unknown item: {value}") from exc


__all__ = [
    "BOUND_ORDER_DURATION_EFFECT",
    "ITEM_ALIASES",
    "ITEM_DEFINITIONS",
    "ITEM_LABELS",
    "ItemDefinition",
    "ItemRecord",
    "bound_order_duration_multiplier_bp",
    "item_aliases",
    "item_records",
    "resolve_item",
    "resolve_item_record",
]
