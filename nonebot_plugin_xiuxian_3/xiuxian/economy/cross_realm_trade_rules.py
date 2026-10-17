"""Rules for the fixed cross-realm trade slice (content-backed)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from .cross_realm_trade_content import (
    cross_realm_trade_alias_map,
    cross_realm_trade_definitions,
)


@dataclass(frozen=True, slots=True)
class CrossRealmTradeDefinition:
    key: str
    label: str
    location_key: str
    input_items: dict[str, int]
    currency_cost: int
    output_items: dict[str, int]
    weekly_limit: int
    binding_seconds: int
    required_faction: str
    required_reputation: int
    required_reputations: dict[str, int] | None = None


TRADE_DEFINITIONS = {
    record["key"]: CrossRealmTradeDefinition(
        key=record["key"],
        label=record["label"],
        location_key=record["location_key"],
        input_items=dict(record["input_items"]),
        currency_cost=record["currency_cost"],
        output_items=dict(record["output_items"]),
        weekly_limit=record["weekly_limit"],
        binding_seconds=record["binding_seconds"],
        required_faction=record["required_faction"],
        required_reputation=record["required_reputation"],
        required_reputations=dict(record["required_reputations"])
        if record.get("required_reputations")
        else None,
    )
    for record in cross_realm_trade_definitions()
}

TRADE_LOCATION = TRADE_DEFINITIONS["trade.xuantian_to_demon"].location_key
BEAST_TRADE_LOCATION = TRADE_DEFINITIONS["trade.xuantian_to_beast"].location_key
THREE_REALMS_TRADE_LOCATION = TRADE_DEFINITIONS["trade.three_realms"].location_key

_EXPLORATION_PAIR = TRADE_DEFINITIONS["trade.xuantian_to_demon"]
WEEKLY_LIMIT = _EXPLORATION_PAIR.weekly_limit
BINDING_SECONDS = _EXPLORATION_PAIR.binding_seconds

TRADE_ALIASES = cross_realm_trade_alias_map()


def resolve_trade(value: str) -> str | None:
    normalized = value.strip()
    if normalized in TRADE_DEFINITIONS:
        return normalized
    return TRADE_ALIASES.get(normalized)


def trade_definition(trade_key: str) -> CrossRealmTradeDefinition:
    try:
        return TRADE_DEFINITIONS[trade_key]
    except KeyError as exc:
        raise ValueError(f"unsupported cross-realm trade: {trade_key}") from exc


def week_start(value) -> str:
    """Return the UTC Monday used by the weekly trade cap."""

    return (value.date() - timedelta(days=value.weekday())).isoformat()


__all__ = [
    "BINDING_SECONDS",
    "CrossRealmTradeDefinition",
    "TRADE_DEFINITIONS",
    "TRADE_LOCATION",
    "BEAST_TRADE_LOCATION",
    "THREE_REALMS_TRADE_LOCATION",
    "WEEKLY_LIMIT",
    "resolve_trade",
    "trade_definition",
    "week_start",
]
