"""Content-backed contracts for the fixed cross-realm trade slice.

Item identifiers are validated as existing open items: the trade layer
spends and grants exactly these inventory keys. The `trade.defaults`
record carries the shared weekly/binding/reputation defaults; per-trade
records may override them and must resolve every alias they declare.
"""

from __future__ import annotations

from typing import Any

from ..content import ContentBundle, ContentError, bundled_content

KIND = "cross_realm_trade"
DEFAULTS_KEY = "trade.defaults"
_FACTIONS = ("demon", "beast", "xuantian")


def _bundle(content: ContentBundle | None) -> ContentBundle:
    return content if content is not None else bundled_content()


def _positive_int(value: Any, field: str, key: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ContentError(f"cross-realm trade {key} {field} must be a positive integer")
    return int(value)


def _non_negative_int(value: Any, field: str, key: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ContentError(f"cross-realm trade {key} {field} must be a non-negative integer")
    return int(value)


def _item_map(value: Any, *, field: str, key: str, bundle: ContentBundle) -> dict[str, int]:
    if not isinstance(value, dict) or not value:
        raise ContentError(f"cross-realm trade {key} {field} must be a non-empty object")
    items: dict[str, int] = {}
    for item_key, raw_amount in value.items():
        item_key = str(item_key)
        try:
            bundle.require("item", item_key, include_locked=False)
        except KeyError as exc:
            raise ContentError(
                f"cross-realm trade {key} {field} references unknown item {item_key}"
            ) from exc
        items[item_key] = _positive_int(raw_amount, f"{field}.{item_key}", key)
    return items


def _reputation_map(
    value: Any, *, key: str, bundle: ContentBundle, default: int | None
) -> dict[str, int]:
    if value is None:
        return {}
    if not isinstance(value, dict) or not value:
        raise ContentError(f"cross-realm trade {key} required_reputations must be a non-empty object")
    gates: dict[str, int] = {}
    for faction, raw_minimum in value.items():
        faction = str(faction)
        if faction not in _FACTIONS:
            raise ContentError(f"cross-realm trade {key} names unknown faction {faction}")
        gates[faction] = _non_negative_int(raw_minimum, f"required_reputations.{faction}", key)
    return gates


def cross_realm_trade_defaults(content: ContentBundle | None = None) -> dict[str, int]:
    bundle = _bundle(content)
    try:
        row = bundle.require(KIND, DEFAULTS_KEY, include_locked=False)
    except KeyError as exc:
        raise ContentError(f"missing cross_realm_trade content: {DEFAULTS_KEY}") from exc
    if row.get("status") != "active":
        raise ContentError(f"{DEFAULTS_KEY} is not active")
    for field in ("name", "desc"):
        if not isinstance(row.get(field), str) or not row[field].strip():
            raise ContentError(f"{DEFAULTS_KEY} requires a {field}")
    return {
        "weekly_limit": _positive_int(row.get("weekly_limit"), "weekly_limit", DEFAULTS_KEY),
        "binding_seconds": _positive_int(row.get("binding_seconds"), "binding_seconds", DEFAULTS_KEY),
        "required_reputation": _non_negative_int(
            row.get("required_reputation"), "required_reputation", DEFAULTS_KEY
        ),
    }


def cross_realm_trade_definitions(
    content: ContentBundle | None = None,
) -> tuple[dict[str, Any], ...]:
    bundle = _bundle(content)
    defaults = cross_realm_trade_defaults(bundle)
    rows = [
        row
        for row in bundle.list(KIND, include_locked=False)
        if str(row.get("key")) != DEFAULTS_KEY
    ]
    if not rows:
        raise ContentError("no cross-realm trade content is active")
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    aliases: dict[str, str] = {}
    for row in sorted(rows, key=lambda item: str(item.get("key"))):
        key = str(row.get("key"))
        if not key.strip() or key in seen:
            raise ContentError(f"cross-realm trade has an invalid or duplicate key {key!r}")
        seen.add(key)
        if row.get("status") != "active":
            raise ContentError(f"cross-realm trade {key} is not active")
        for field in ("name", "desc", "label"):
            if not isinstance(row.get(field), str) or not row[field].strip():
                raise ContentError(f"cross-realm trade {key} requires a {field}")
        location_key = row.get("location_key")
        if not isinstance(location_key, str) or not location_key.strip():
            raise ContentError(f"cross-realm trade {key} has an invalid location")
        try:
            bundle.require("location", location_key, include_locked=True)
        except KeyError as exc:
            raise ContentError(
                f"cross-realm trade {key} references unknown location {location_key}"
            ) from exc
        faction = row.get("required_faction")
        if faction not in _FACTIONS:
            raise ContentError(f"cross-realm trade {key} names unknown faction {faction!r}")
        record: dict[str, Any] = {
            "key": key,
            "label": str(row["label"]),
            "location_key": location_key,
            "input_items": _item_map(row.get("input_items"), field="input_items", key=key, bundle=bundle),
            "currency_cost": _non_negative_int(row.get("currency_cost"), "currency_cost", key),
            "output_items": _item_map(row.get("output_items"), field="output_items", key=key, bundle=bundle),
            "weekly_limit": _positive_int(row.get("weekly_limit", defaults["weekly_limit"]), "weekly_limit", key),
            "binding_seconds": _positive_int(
                row.get("binding_seconds", defaults["binding_seconds"]), "binding_seconds", key
            ),
            "required_faction": str(faction),
            "required_reputation": _non_negative_int(
                row.get("required_reputation", defaults["required_reputation"]),
                "required_reputation",
                key,
            ),
        }
        gates = _reputation_map(
            row.get("required_reputations"), key=key, bundle=bundle, default=None
        )
        if gates:
            record["required_reputations"] = gates
        row_aliases = row.get("aliases")
        if not isinstance(row_aliases, list) or not row_aliases:
            raise ContentError(f"cross-realm trade {key} aliases must be a non-empty list")
        for alias in row_aliases:
            if not isinstance(alias, str) or not alias.strip():
                raise ContentError(f"cross-realm trade {key} has an invalid alias")
            alias = alias.strip()
            owner = aliases.get(alias)
            if owner is not None and owner != key:
                raise ContentError(
                    f"cross-realm trade alias {alias} is already owned by {owner}"
                )
            aliases[alias] = key
        record["aliases"] = tuple(row_aliases)
        records.append(record)
    return tuple(records)


def cross_realm_trade_alias_map(content: ContentBundle | None = None) -> dict[str, str]:
    bundle = _bundle(content)
    aliases: dict[str, str] = {}
    for record in cross_realm_trade_definitions(bundle):
        aliases[record["key"]] = record["key"]
        for alias in record["aliases"]:
            aliases[alias] = record["key"]
    return aliases


__all__ = [
    "DEFAULTS_KEY",
    "KIND",
    "cross_realm_trade_alias_map",
    "cross_realm_trade_defaults",
    "cross_realm_trade_definitions",
]
