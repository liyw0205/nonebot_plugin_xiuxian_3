"""Content-backed contracts for the social rules."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..content import ContentBundle, ContentError, bundled_content

KIND = "social_interaction"
MENTOR_KEY = "social.mentor"
PARTY_KEY = "social.party"
SECT_KEY = "social.sect"
SECT_ALLIANCE_KEY = "social.sect_alliance"
SECT_BEACON_KEY = "social.sect_beacon"
SECT_EXCHANGE_KEY = "social.sect_exchange"
SECT_WAR_KEY = "social.sect_war"


def _bundle(content: ContentBundle | None) -> ContentBundle:
    return content if content is not None else bundled_content()


def _record(bundle: ContentBundle, key: str) -> dict[str, Any]:
    try:
        row = bundle.require(KIND, key, include_locked=True)
    except KeyError as exc:
        raise ContentError(f"missing social_interaction content: {key}") from exc
    if row.get("status") not in {"active", "open"}:
        raise ContentError(f"{key} status is not open")
    for field in ("name", "desc"):
        if not isinstance(row.get(field), str) or not row[field].strip():
            raise ContentError(f"{key} requires a {field}")
    return row


def _positive(value: Any, field: str, key: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ContentError(f"{key} {field} must be a positive integer")
    return int(value)


def _realm(bundle: ContentBundle, realm_key: Any, key: str, field: str) -> None:
    if not isinstance(realm_key, str) or not realm_key.strip():
        raise ContentError(f"{key} {field} is invalid")
    try:
        bundle.require("realm", realm_key, include_locked=False)
    except KeyError as exc:
        raise ContentError(f"{key} {field} references unknown realm {realm_key}") from exc


def realm_rank(realm_key: str, content: ContentBundle | None = None) -> int:
    """Rank of an open realm, read from the realm content instead of a table."""

    bundle = _bundle(content)
    try:
        row = bundle.require("realm", realm_key, include_locked=False)
    except KeyError:
        return -1
    rank = row.get("rank")
    if isinstance(rank, bool) or not isinstance(rank, int):
        raise ContentError(f"realm {realm_key} has no integer rank")
    return int(rank)


def mentor_rules_record(content: ContentBundle | None = None) -> dict[str, Any]:
    bundle = _bundle(content)
    row = _record(bundle, MENTOR_KEY)
    master_realm = row.get("master_realm")
    _realm(bundle, master_realm, MENTOR_KEY, "master_realm")
    apprentice_realms = row.get("apprentice_realms")
    if not isinstance(apprentice_realms, list) or not apprentice_realms:
        raise ContentError(f"{MENTOR_KEY} apprentice_realms must be a non-empty list")
    for realm_key in apprentice_realms:
        _realm(bundle, realm_key, MENTOR_KEY, "apprentice_realms")
    return {
        "key": MENTOR_KEY,
        "invitation_ttl_seconds": _positive(
            row.get("invitation_ttl_seconds"), "invitation_ttl_seconds", MENTOR_KEY
        ),
        "max_apprentices": _positive(
            row.get("max_apprentices"), "max_apprentices", MENTOR_KEY
        ),
        "master_realm": str(master_realm),
        "master_min_layer": _positive(
            row.get("master_min_layer"), "master_min_layer", MENTOR_KEY
        ),
        "apprentice_realms": tuple(str(realm_key) for realm_key in apprentice_realms),
        "apprentice_max_qi_gathering_layer": _positive(
            row.get("apprentice_max_qi_gathering_layer"),
            "apprentice_max_qi_gathering_layer",
            MENTOR_KEY,
        ),
    }


def party_definitions(content: ContentBundle | None = None) -> tuple[dict[str, Any], ...]:
    bundle = _bundle(content)
    row = _record(bundle, PARTY_KEY)
    definitions = row.get("definitions")
    if not isinstance(definitions, list) or not definitions:
        raise ContentError(f"{PARTY_KEY} definitions must be a non-empty list")
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(definitions):
        if not isinstance(item, dict):
            raise ContentError(f"{PARTY_KEY} definition {index} must be an object")
        party_type = item.get("party_type")
        if not isinstance(party_type, str) or not party_type.strip() or party_type in seen:
            raise ContentError(
                f"{PARTY_KEY} definition {index} has an invalid or duplicate party_type"
            )
        seen.add(party_type)
        min_members = _positive(item.get("min_members"), "min_members", party_type)
        max_members = _positive(item.get("max_members"), "max_members", party_type)
        if max_members < min_members:
            raise ContentError(f"{PARTY_KEY} {party_type} max_members is below min_members")
        distribution_key = item.get("distribution_key")
        if not isinstance(distribution_key, str) or not distribution_key.strip():
            raise ContentError(f"{PARTY_KEY} {party_type} has an invalid distribution_key")
        required_location = item.get("required_location")
        if required_location is not None:
            if not isinstance(required_location, str) or not required_location.strip():
                raise ContentError(
                    f"{PARTY_KEY} {party_type} has an invalid required_location"
                )
            try:
                bundle.require("location", required_location, include_locked=True)
            except KeyError as exc:
                raise ContentError(
                    f"{PARTY_KEY} {party_type} references unknown location {required_location}"
                ) from exc
        records.append(
            {
                "party_type": party_type,
                "min_members": min_members,
                "max_members": max_members,
                "confirmation_ttl_seconds": _positive(
                    item.get("confirmation_ttl_seconds"),
                    "confirmation_ttl_seconds",
                    party_type,
                ),
                "distribution_key": distribution_key,
                "required_location": required_location,
            }
        )
    return tuple(records)


def _positive_fields(key: str, row: dict[str, Any], fields: tuple[str, ...]) -> dict[str, int]:
    return {field: _positive(row.get(field), field, key) for field in fields}


def sect_alliance_record(content: ContentBundle | None = None) -> dict[str, Any]:
    bundle = _bundle(content)
    row = _record(bundle, SECT_ALLIANCE_KEY)
    return {
        "key": SECT_ALLIANCE_KEY,
        **_positive_fields(
            SECT_ALLIANCE_KEY,
            row,
            (
                "min_sect_level",
                "confirmation_seconds",
                "duration_seconds",
                "research_weekly_cap",
                "breach_fee",
                "cooldown_seconds",
            ),
        ),
    }


def sect_beacon_record(content: ContentBundle | None = None) -> dict[str, Any]:
    bundle = _bundle(content)
    row = _record(bundle, SECT_BEACON_KEY)
    return {
        "key": SECT_BEACON_KEY,
        **_positive_fields(
            SECT_BEACON_KEY,
            row,
            (
                "anchor_cost",
                "sand_cost",
                "build_seconds",
                "maintenance_anchor_cost",
                "route_discount",
            ),
        ),
    }


def _item_key(bundle: ContentBundle, value: Any, key: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContentError(f"{key} {field} is invalid")
    try:
        bundle.require("item", value, include_locked=True)
    except KeyError as exc:
        raise ContentError(f"{key} {field} references unknown item {value}") from exc
    return value


def sect_exchange_record(content: ContentBundle | None = None) -> dict[str, Any]:
    bundle = _bundle(content)
    row = _record(bundle, SECT_EXCHANGE_KEY)
    daily_cap = _positive(row.get("daily_cap"), "daily_cap", SECT_EXCHANGE_KEY)

    raw_items = row.get("donation_items")
    if not isinstance(raw_items, list) or not raw_items:
        raise ContentError(f"{SECT_EXCHANGE_KEY} donation_items must be a non-empty list")
    donation_items = tuple(
        _item_key(bundle, item, SECT_EXCHANGE_KEY, "donation_items") for item in raw_items
    )

    raw_aliases = row.get("donation_aliases")
    if not isinstance(raw_aliases, dict) or not raw_aliases:
        raise ContentError(
            f"{SECT_EXCHANGE_KEY} donation_aliases must be a non-empty object"
        )
    donation_aliases: dict[str, str] = {}
    for label, item_key in raw_aliases.items():
        if not isinstance(label, str) or not label.strip():
            raise ContentError(f"{SECT_EXCHANGE_KEY} has an invalid donation alias")
        if item_key not in donation_items:
            raise ContentError(
                f"{SECT_EXCHANGE_KEY} donation alias {label} maps outside donation_items"
            )
        donation_aliases[label] = item_key

    raw_recipes = row.get("supply_recipes")
    if not isinstance(raw_recipes, dict) or not raw_recipes:
        raise ContentError(f"{SECT_EXCHANGE_KEY} supply_recipes must be a non-empty object")
    supply_recipes: dict[str, tuple[dict[str, int], int]] = {}
    for recipe_key, recipe in raw_recipes.items():
        if not isinstance(recipe_key, str) or not recipe_key.strip():
            raise ContentError(f"{SECT_EXCHANGE_KEY} has an invalid supply recipe key")
        if not isinstance(recipe, dict):
            raise ContentError(f"{SECT_EXCHANGE_KEY} recipe {recipe_key} must be an object")
        materials = recipe.get("materials")
        if not isinstance(materials, dict) or not materials:
            raise ContentError(
                f"{SECT_EXCHANGE_KEY} recipe {recipe_key} materials must be a non-empty object"
            )
        parsed_materials: dict[str, int] = {}
        for material_key, quantity in materials.items():
            parsed_materials[
                _item_key(bundle, material_key, SECT_EXCHANGE_KEY, f"recipe {recipe_key}")
            ] = _positive(quantity, f"recipe {recipe_key} material quantity", SECT_EXCHANGE_KEY)
        supply_recipes[recipe_key] = (
            parsed_materials,
            _positive(recipe.get("contribution"), f"recipe {recipe_key} contribution", SECT_EXCHANGE_KEY),
        )

    raw_offers = row.get("offers")
    if not isinstance(raw_offers, list) or not raw_offers:
        raise ContentError(f"{SECT_EXCHANGE_KEY} offers must be a non-empty list")
    offers: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, offer in enumerate(raw_offers):
        if not isinstance(offer, dict):
            raise ContentError(f"{SECT_EXCHANGE_KEY} offer {index} must be an object")
        offer_key = offer.get("key")
        if not isinstance(offer_key, str) or not offer_key.strip() or offer_key in seen:
            raise ContentError(
                f"{SECT_EXCHANGE_KEY} offer {index} has an invalid or duplicate key"
            )
        seen.add(offer_key)
        label = offer.get("label")
        if not isinstance(label, str) or not label.strip():
            raise ContentError(f"{SECT_EXCHANGE_KEY} offer {offer_key} requires a label")
        offers.append(
            {
                "key": offer_key,
                "label": label,
                "contribution_cost": _positive(
                    offer.get("contribution_cost"), f"offer {offer_key} cost", SECT_EXCHANGE_KEY
                ),
                "item_key": _item_key(bundle, offer.get("item_key"), SECT_EXCHANGE_KEY, f"offer {offer_key}"),
                "quantity": _positive(
                    offer.get("quantity"), f"offer {offer_key} quantity", SECT_EXCHANGE_KEY
                ),
            }
        )

    raw_exchange_aliases = row.get("aliases")
    if not isinstance(raw_exchange_aliases, dict) or not raw_exchange_aliases:
        raise ContentError(f"{SECT_EXCHANGE_KEY} aliases must be a non-empty object")
    exchange_aliases: dict[str, str] = {}
    for alias, offer_key in raw_exchange_aliases.items():
        if not isinstance(alias, str) or not alias.strip():
            raise ContentError(f"{SECT_EXCHANGE_KEY} has an invalid alias")
        if offer_key not in seen:
            raise ContentError(
                f"{SECT_EXCHANGE_KEY} alias {alias} references unknown offer {offer_key}"
            )
        exchange_aliases[alias] = offer_key

    return {
        "key": SECT_EXCHANGE_KEY,
        "daily_cap": daily_cap,
        "donation_items": donation_items,
        "donation_aliases": donation_aliases,
        "supply_recipes": supply_recipes,
        "offers": tuple(offers),
        "aliases": exchange_aliases,
    }


def _anchor_datetime(value: Any, key: str) -> Any:
    if not isinstance(value, str):
        raise ContentError(f"{key} anchor is invalid")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ContentError(f"{key} anchor is invalid") from exc
    if parsed.tzinfo is None:
        raise ContentError(f"{key} anchor must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def sect_war_record(content: ContentBundle | None = None) -> dict[str, Any]:
    bundle = _bundle(content)
    row = _record(bundle, SECT_WAR_KEY)
    war_key = row.get("war_key")
    if not isinstance(war_key, str) or not war_key.strip():
        raise ContentError(f"{SECT_WAR_KEY} war_key is invalid")
    action_values = row.get("action_values")
    if not isinstance(action_values, dict) or not action_values:
        raise ContentError(f"{SECT_WAR_KEY} action_values must be a non-empty object")
    parsed_actions: dict[str, int] = {}
    for action_key, score in action_values.items():
        if not isinstance(action_key, str) or not action_key.strip():
            raise ContentError(f"{SECT_WAR_KEY} has an invalid action key")
        parsed_actions[action_key] = _positive(
            score, f"action_values.{action_key}", SECT_WAR_KEY
        )
    return {
        "key": SECT_WAR_KEY,
        "war_key": war_key,
        "anchor": _anchor_datetime(row.get("anchor"), SECT_WAR_KEY),
        "action_values": parsed_actions,
        **_positive_fields(
            SECT_WAR_KEY,
            row,
            (
                "rounds_per_week",
                "duration_minutes",
                "registration_fee",
                "max_participants",
                "min_level",
                "member_threshold",
                "sect_reward",
                "member_reward",
                "claim_hours",
            ),
        ),
    }


def sect_rules_record(content: ContentBundle | None = None) -> dict[str, Any]:
    bundle = _bundle(content)
    row = _record(bundle, SECT_KEY)
    return {
        "key": SECT_KEY,
        "create_cost": _positive(row.get("create_cost"), "create_cost", SECT_KEY),
        "max_members": _positive(row.get("max_members"), "max_members", SECT_KEY),
        "warehouse_capacity": _positive(
            row.get("warehouse_capacity"), "warehouse_capacity", SECT_KEY
        ),
        "application_ttl_seconds": _positive(
            row.get("application_ttl_seconds"), "application_ttl_seconds", SECT_KEY
        ),
        "join_cooldown_seconds": _positive(
            row.get("join_cooldown_seconds"), "join_cooldown_seconds", SECT_KEY
        ),
    }


def party_aliases(content: ContentBundle | None = None) -> dict[str, str]:
    bundle = _bundle(content)
    row = _record(bundle, PARTY_KEY)
    aliases = row.get("aliases") or {}
    if not isinstance(aliases, dict):
        raise ContentError(f"{PARTY_KEY} aliases must be an object")
    result: dict[str, str] = {}
    for alias, party_type in aliases.items():
        if (
            not isinstance(alias, str)
            or not alias.strip()
            or not isinstance(party_type, str)
            or not party_type.strip()
        ):
            raise ContentError(f"{PARTY_KEY} has an invalid alias")
        result[alias] = party_type
    return result


__all__ = [
    "KIND",
    "MENTOR_KEY",
    "PARTY_KEY",
    "mentor_rules_record",
    "party_aliases",
    "party_definitions",
    "realm_rank",
    "sect_alliance_record",
    "sect_beacon_record",
    "sect_exchange_record",
    "sect_rules_record",
    "sect_war_record",
]
