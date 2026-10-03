"""Content-backed rules for livelihood trade routes."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from functools import lru_cache

from ..content import ContentBundle, ContentError, bundled_content
from ..player.rules import STAGE_LABELS
from ..rewards.rules import local_reputation_maximum


ROUTE_NEW_TOWN_OUTSKIRTS = "route.new_town_outskirts"


@dataclass(frozen=True, slots=True)
class RouteDefinition:
    key: str
    label: str
    source_location: str
    source_name: str
    destination_location: str
    duration_seconds: int
    stamina_cost: int
    reward_stones: int
    local_reputation: int
    local_reputation_key: str
    local_reputation_maximum: int
    daily_limit: int
    delay_chance_bp: int
    delay_seconds: int
    max_cargo_value: int
    cargo_values: dict[str, int]
    cargo_aliases: dict[str, str]
    default_cargo_key: str
    allowed_stages: tuple[str, ...]
    random_pool: str
    aliases: tuple[str, ...] = ()


@lru_cache(maxsize=1)
def _default_content() -> ContentBundle:
    return bundled_content()


def _bundle(content: ContentBundle | None) -> ContentBundle:
    return content if content is not None else _default_content()


def route_definitions(content: ContentBundle | None = None) -> dict[str, RouteDefinition]:
    bundle = _bundle(content)
    result: dict[str, RouteDefinition] = {}
    selectors: set[str] = set()
    for row in bundle.list("livelihood", include_locked=False):
        if row.get("record_type") != "route":
            continue
        key, label, desc = row.get("key"), row.get("name"), row.get("desc")
        if (
            not isinstance(key, str) or not key
            or not isinstance(label, str) or not label.strip()
            or not isinstance(desc, str) or not desc.strip()
        ):
            raise ContentError(f"route {key!r} requires key, name and desc")
        source = row.get("source_location")
        destination = row.get("destination_location")
        if (
            not isinstance(source, str) or not source
            or not isinstance(destination, str) or not destination
            or bundle.get("location", source, include_locked=False) is None
            or bundle.get("location", destination, include_locked=False) is None
        ):
            raise ContentError(f"route {key} references an inactive location")
        try:
            source_name = bundle.label("location", source)
        except KeyError as exc:
            raise ContentError(f"route {key} source location requires a name") from exc
        cost = row.get("cost")
        reward = row.get("reward")
        cargo = row.get("cargo")
        numeric = {
            "duration_seconds": row.get("duration_seconds"),
            "daily_limit": row.get("daily_limit"),
            "delay_chance_bp": row.get("delay_chance_bp"),
            "delay_seconds": row.get("delay_seconds"),
        }
        if (
            not isinstance(cost, dict)
            or isinstance(cost.get("stamina"), bool)
            or not isinstance(cost.get("stamina"), int)
            or cost["stamina"] <= 0
            or not isinstance(reward, dict)
            or reward.get("currency_key") != "currency.spirit_stone"
            or isinstance(reward.get("amount"), bool)
            or not isinstance(reward.get("amount"), int)
            or reward["amount"] < 0
        ):
            raise ContentError(f"route {key} has invalid cost or reward")
        if any(isinstance(value, bool) or not isinstance(value, int) for value in numeric.values()):
            raise ContentError(f"route {key} has invalid numeric values")
        if (
            numeric["duration_seconds"] <= 0
            or numeric["daily_limit"] <= 0
            or not 0 <= numeric["delay_chance_bp"] <= 10_000
            or numeric["delay_seconds"] < 0
        ):
            raise ContentError(f"route {key} has out-of-range numeric values")
        reputation_key = reward.get("reputation_key")
        reputation = reward.get("reputation")
        if (
            not isinstance(reputation_key, str) or not reputation_key
            or isinstance(reputation, bool) or not isinstance(reputation, int) or reputation < 0
        ):
            raise ContentError(f"route {key} has invalid local reputation reward")
        try:
            reputation_maximum = local_reputation_maximum(reputation_key, bundle)
        except (ContentError, ValueError) as exc:
            raise ContentError(f"route {key} references an invalid reputation location") from exc
        if not isinstance(cargo, dict):
            raise ContentError(f"route {key} has invalid cargo")
        max_value = cargo.get("max_value")
        unit_values = cargo.get("unit_values")
        if (
            isinstance(max_value, bool) or not isinstance(max_value, int) or max_value <= 0
            or not isinstance(unit_values, dict) or not unit_values
        ):
            raise ContentError(f"route {key} has invalid cargo values")
        normalized_values: dict[str, int] = {}
        for item_key, unit_value in unit_values.items():
            if (
                not isinstance(item_key, str) or not item_key
                or isinstance(unit_value, bool) or not isinstance(unit_value, int) or unit_value <= 0
                or bundle.get("item", item_key, include_locked=False) is None
            ):
                raise ContentError(f"route {key} references invalid cargo item {item_key!r}")
            normalized_values[item_key] = unit_value
        aliases = row.get("aliases", [])
        if not isinstance(aliases, list) or any(not isinstance(alias, str) or not alias.strip() for alias in aliases):
            raise ContentError(f"route {key} aliases must be non-empty strings")
        cargo_aliases = cargo.get("aliases", {})
        if not isinstance(cargo_aliases, dict):
            raise ContentError(f"route {key} cargo aliases must be an object")
        normalized_aliases: dict[str, str] = {}
        for alias, item_key in cargo_aliases.items():
            if (
                not isinstance(alias, str) or not alias.strip()
                or not isinstance(item_key, str) or item_key not in normalized_values
            ):
                raise ContentError(f"route {key} has invalid cargo alias {alias!r}")
            normalized = alias.strip()
            if normalized in normalized_aliases and normalized_aliases[normalized] != item_key:
                raise ContentError(f"route {key} has a conflicting cargo alias {alias!r}")
            normalized_aliases[normalized] = item_key
        for item_key in normalized_values:
            item_label = cargo_label(item_key, bundle)
            if item_label in normalized_aliases and normalized_aliases[item_label] != item_key:
                raise ContentError(f"route {key} has a conflicting cargo name {item_label!r}")
            normalized_aliases[item_label] = item_key
        default_cargo_key = cargo.get("default_item_key")
        if not isinstance(default_cargo_key, str) or default_cargo_key not in normalized_values:
            raise ContentError(f"route {key} has invalid cargo default_item_key")
        allowed_stages = row.get("allowed_stages")
        if (
            not isinstance(allowed_stages, list)
            or not allowed_stages
            or any(not isinstance(stage, str) or stage not in STAGE_LABELS for stage in allowed_stages)
        ):
            raise ContentError(f"route {key} has invalid allowed_stages")
        random_pool = row.get("random_pool")
        if not isinstance(random_pool, str) or not random_pool:
            raise ContentError(f"route {key} has invalid random_pool")
        selectors_for_row = {key, label.strip(), *(alias.strip() for alias in aliases)}
        if selectors & selectors_for_row:
            raise ContentError(f"route {key} has a duplicate name or alias")
        selectors.update(selectors_for_row)
        result[key] = RouteDefinition(
            key=key,
            label=label.strip(),
            source_location=source,
            source_name=source_name,
            destination_location=destination,
            duration_seconds=numeric["duration_seconds"],
            stamina_cost=cost["stamina"],
            reward_stones=reward["amount"],
            local_reputation=reputation,
            local_reputation_key=reputation_key,
            local_reputation_maximum=reputation_maximum,
            daily_limit=numeric["daily_limit"],
            delay_chance_bp=numeric["delay_chance_bp"],
            delay_seconds=numeric["delay_seconds"],
            max_cargo_value=max_value,
            cargo_values=normalized_values,
            cargo_aliases=normalized_aliases,
            default_cargo_key=default_cargo_key,
            allowed_stages=tuple(allowed_stages),
            random_pool=random_pool,
            aliases=tuple(alias.strip() for alias in aliases),
        )
    if not result:
        raise ContentError("no active route content records")
    return result


def route_definition(value: str | None = None, content: ContentBundle | None = None) -> RouteDefinition:
    normalized = (value or ROUTE_NEW_TOWN_OUTSKIRTS).strip()
    for definition in route_definitions(content).values():
        if normalized in {definition.key, definition.label, *definition.aliases}:
            return definition
    raise ValueError(f"unsupported route key: {value}")


def resolve_route(value: str | None = None, content: ContentBundle | None = None) -> str | None:
    normalized = (value or "").strip()
    if not normalized:
        return ROUTE_NEW_TOWN_OUTSKIRTS
    bundle = _bundle(content)
    for row in bundle.list("livelihood", include_locked=True):
        if row.get("record_type") != "route":
            continue
        key, label = row.get("key"), row.get("name")
        aliases = row.get("aliases", [])
        if isinstance(key, str) and isinstance(label, str) and isinstance(aliases, list):
            if normalized in {key, label.strip(), *(str(alias).strip() for alias in aliases)}:
                return key
    return None


def resolve_cargo(
    value: str | None = None,
    route_key: str | None = None,
    content: ContentBundle | None = None,
) -> str | None:
    normalized = (value or "").strip()
    if not normalized:
        return None
    bundle = _bundle(content)
    # Resolve identity without reopening rules, so a closed route can replay its ledger.
    for row in bundle.list("livelihood", include_locked=True):
        if row.get("record_type") != "route" or (route_key is not None and row["key"] != route_key):
            continue
        cargo = row.get("cargo")
        if not isinstance(cargo, dict) or not isinstance(cargo.get("unit_values"), dict):
            raise ContentError(f"route {row['key']} has invalid cargo values")
        if normalized in cargo["unit_values"]:
            return normalized
        aliases = cargo.get("aliases", {})
        if not isinstance(aliases, dict):
            raise ContentError(f"route {row['key']} cargo aliases must be an object")
        if normalized in aliases:
            return aliases[normalized]
        for item_key in cargo["unit_values"]:
            if normalized == cargo_label(item_key, bundle):
                return item_key
    return None


def cargo_unit_value(cargo_key: str, definition: RouteDefinition) -> int:
    if cargo_key in definition.cargo_values:
        return definition.cargo_values[cargo_key]
    raise ValueError(f"unsupported cargo key: {cargo_key}")


def route_delay_roll_bp(operation_id: str) -> int:
    digest = hashlib.blake2b(operation_id.encode("utf-8"), digest_size=2).digest()
    return int.from_bytes(digest, "big") % 10_000


def cargo_label(cargo_key: str, content: ContentBundle | None = None) -> str:
    try:
        return _bundle(content).label("item", cargo_key)
    except KeyError as exc:
        raise ContentError(f"route cargo {cargo_key} requires an item name") from exc


__all__ = [
    "ROUTE_NEW_TOWN_OUTSKIRTS",
    "RouteDefinition",
    "cargo_label",
    "cargo_unit_value",
    "resolve_cargo",
    "resolve_route",
    "route_definition",
    "route_definitions",
    "route_delay_roll_bp",
]
