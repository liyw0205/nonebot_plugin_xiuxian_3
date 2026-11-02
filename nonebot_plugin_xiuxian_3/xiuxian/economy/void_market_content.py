"""Content-backed contract for the weekly void market.

The market contract was frozen by ``docs/gameplay/economy/content-v0.5.md``
(``market.void_weekly.<week_id>``): twenty stock slots per UTC week, three
items per player per UTC day, fixed spirit-stone prices and a void-refining
(or void-merit) gate.  This module owns parsing and validation only; pricing,
stock arithmetic and settlement live in the rules and repository layers.

The market sits at an anchor-route terminal (``void.void_market``) rather than
a regular map location: the destination is only reachable through
``进入虚空航道``, which already enforces the void-merit route gate.  The loader
therefore validates the location against the void-route content instead of the
location table.
"""

from __future__ import annotations

from typing import Any

from ..content import ContentBundle, ContentError, bundled_content

KIND = "void_market"
DEFAULTS_KEY = "market.void.defaults"
OFFER_PREFIX = "offer."


def _bundle(content: ContentBundle | None) -> ContentBundle:
    return content if content is not None else bundled_content()


def _positive_int(value: Any, field: str, key: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ContentError(f"void market {key} {field} must be a positive integer")
    return int(value)


def _non_negative_int(value: Any, field: str, key: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ContentError(f"void market {key} {field} must be a non-negative integer")
    return int(value)


def _text(row: dict[str, Any], field: str, key: str) -> str:
    value = row.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ContentError(f"void market {key} requires a {field}")
    return value.strip()


def void_market_defaults(content: ContentBundle | None = None) -> dict[str, Any]:
    """Return the validated shared market parameters."""

    bundle = _bundle(content)
    try:
        row = bundle.require(KIND, DEFAULTS_KEY, include_locked=True)
    except KeyError as exc:
        raise ContentError(f"missing void_market content: {DEFAULTS_KEY}") from exc
    if row.get("status") != "active":
        raise ContentError(f"{DEFAULTS_KEY} is not active")
    _text(row, "name", DEFAULTS_KEY)
    _text(row, "desc", DEFAULTS_KEY)

    location_key = _text(row, "location_key", DEFAULTS_KEY)
    if not bundle.has("world_void_route", location_key, include_locked=True):
        raise ContentError(
            f"{DEFAULTS_KEY} must name an anchor-route terminal, got {location_key!r}"
        )

    weekday = row.get("week_start_weekday")
    if isinstance(weekday, bool) or not isinstance(weekday, int) or not 1 <= weekday <= 7:
        raise ContentError(f"{DEFAULTS_KEY} week_start_weekday must be an ISO weekday 1-7")
    hour = row.get("week_start_hour_utc")
    if isinstance(hour, bool) or not isinstance(hour, int) or not 0 <= hour <= 23:
        raise ContentError(f"{DEFAULTS_KEY} week_start_hour_utc must be an hour 0-23")

    realm_key = _text(row, "required_realm", DEFAULTS_KEY)
    realm = bundle.get("realm", realm_key, include_locked=True)
    if realm is None:
        raise ContentError(f"{DEFAULTS_KEY} references unknown realm {realm_key}")
    if realm.get("status") not in {"active", "open"}:
        raise ContentError(f"{DEFAULTS_KEY} references closed realm {realm_key}")

    return {
        "location_key": location_key,
        "week_start_weekday": int(weekday),
        "week_start_hour_utc": int(hour),
        "stock_slots": _positive_int(row.get("stock_slots"), "stock_slots", DEFAULTS_KEY),
        "daily_purchase_limit": _positive_int(
            row.get("daily_purchase_limit"), "daily_purchase_limit", DEFAULTS_KEY
        ),
        "binding_seconds": _positive_int(row.get("binding_seconds"), "binding_seconds", DEFAULTS_KEY),
        "required_realm": realm_key,
        "required_layer": _positive_int(row.get("required_layer"), "required_layer", DEFAULTS_KEY),
        "required_merit": _non_negative_int(row.get("required_merit"), "required_merit", DEFAULTS_KEY),
    }


def void_market_offers(content: ContentBundle | None = None) -> tuple[dict[str, Any], ...]:
    """Return validated market offers, guaranteeing the frozen slot count."""

    bundle = _bundle(content)
    defaults = void_market_defaults(bundle)
    rows = [
        row
        for row in bundle.list(KIND, include_locked=True)
        if str(row.get("key")) != DEFAULTS_KEY
    ]
    if not rows:
        raise ContentError("no void market offer content is active")

    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    aliases: dict[str, str] = {}
    for row in sorted(rows, key=lambda item: str(item.get("key"))):
        key = str(row.get("key"))
        if not key.startswith(OFFER_PREFIX):
            raise ContentError(f"void market offer key must start with {OFFER_PREFIX!r}: {key!r}")
        if key in seen:
            raise ContentError(f"void market has a duplicate offer key {key!r}")
        seen.add(key)
        if row.get("status") != "active":
            raise ContentError(f"void market {key} is not active")
        label = _text(row, "label", key)
        _text(row, "name", key)
        _text(row, "desc", key)

        item_key = _text(row, "item_key", key)
        try:
            bundle.require("item", item_key, include_locked=False)
        except KeyError as exc:
            raise ContentError(f"void market {key} references unknown item {item_key}") from exc

        row_aliases = row.get("aliases")
        if not isinstance(row_aliases, list) or not row_aliases:
            raise ContentError(f"void market {key} aliases must be a non-empty list")
        for alias in row_aliases:
            if not isinstance(alias, str) or not alias.strip():
                raise ContentError(f"void market {key} has an invalid alias")
            alias = alias.strip()
            owner = aliases.get(alias)
            if owner is not None and owner != key:
                raise ContentError(f"void market alias {alias} is already owned by {owner}")
            aliases[alias] = key

        records.append(
            {
                "key": key,
                "label": label,
                "item_key": item_key,
                "quantity": _positive_int(row.get("quantity"), "quantity", key),
                "price_spirit_stones": _positive_int(
                    row.get("price_spirit_stones"), "price_spirit_stones", key
                ),
                "stock": _positive_int(row.get("stock"), "stock", key),
                "aliases": tuple(str(alias).strip() for alias in row_aliases),
            }
        )

    total_stock = sum(record["stock"] for record in records)
    if total_stock != defaults["stock_slots"]:
        raise ContentError(
            "void market weekly stock slots must equal stock_slots "
            f"({total_stock} != {defaults['stock_slots']})"
        )
    return tuple(records)


def void_market_alias_map(content: ContentBundle | None = None) -> dict[str, str]:
    """Map every stable key and Chinese alias to its offer key."""

    bundle = _bundle(content)
    aliases: dict[str, str] = {}
    for record in void_market_offers(bundle):
        aliases[record["key"]] = record["key"]
        for alias in record["aliases"]:
            aliases[alias] = record["key"]
    return aliases


__all__ = [
    "DEFAULTS_KEY",
    "KIND",
    "OFFER_PREFIX",
    "void_market_alias_map",
    "void_market_defaults",
    "void_market_offers",
]
