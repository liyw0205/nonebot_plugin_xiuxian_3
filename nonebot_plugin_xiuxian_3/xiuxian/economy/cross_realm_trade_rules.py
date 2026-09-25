"""Rules for the first fixed cross-realm trade slice."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta


CONTENT_VERSION = "content-0.3"
RULE_VERSION = "economy-0.3.0"
WEEKLY_LIMIT = 5
BINDING_SECONDS = 24 * 60 * 60
TRADE_LOCATION = "demon.abyss_market"


@dataclass(frozen=True, slots=True)
class CrossRealmTradeDefinition:
    key: str
    label: str
    location_key: str
    input_items: dict[str, int]
    currency_cost: int
    output_items: dict[str, int]
    weekly_limit: int = WEEKLY_LIMIT
    binding_seconds: int = BINDING_SECONDS
    content_version: str = CONTENT_VERSION
    rule_version: str = RULE_VERSION


TRADE_DEFINITIONS = {
    "trade.xuantian_to_demon": CrossRealmTradeDefinition(
        key="trade.xuantian_to_demon",
        label="云铁兑换魔核",
        location_key=TRADE_LOCATION,
        input_items={"item.material.cloud_iron": 10},
        currency_cost=200,
        output_items={"item.demon_core": 1},
    ),
}

TRADE_ALIASES = {
    "trade.xuantian_to_demon": "trade.xuantian_to_demon",
    "xuantian_to_demon": "trade.xuantian_to_demon",
    "云铁兑换魔核": "trade.xuantian_to_demon",
    "云铁换魔核": "trade.xuantian_to_demon",
    "玄天到魔界": "trade.xuantian_to_demon",
    "玄天界到魔界": "trade.xuantian_to_demon",
    "魔界贸易": "trade.xuantian_to_demon",
}


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
    "CONTENT_VERSION",
    "CrossRealmTradeDefinition",
    "RULE_VERSION",
    "TRADE_DEFINITIONS",
    "TRADE_LOCATION",
    "WEEKLY_LIMIT",
    "resolve_trade",
    "trade_definition",
    "week_start",
]
