"""Versioned rules for cross-realm purchase orders."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from .rules import NON_TRADEABLE_ITEMS, resolve_market_item


CONTENT_VERSION = "content-0.3"
RULE_VERSION = "economy-0.3.0"
PURCHASE_ORDER_TTL_SECONDS = 12 * 60 * 60
PURCHASE_DELIVERY_GRACE_SECONDS = 10 * 60
PURCHASE_MAX_LISTINGS = 3
PURCHASE_FEE_BP = 800
BP_DENOMINATOR = 10_000
PURCHASE_MIN_QUANTITY = 1
PURCHASE_MAX_QUANTITY = 99
PURCHASE_MIN_UNIT_PRICE = 1
PURCHASE_MAX_UNIT_PRICE = 500_000

TRADE_MARKET_FACTIONS = {
    "demon.abyss_market": "demon",
    "beast.ten_thousand_hills": "beast",
    "beast.three_realms_trade_port": "beast",
}


@dataclass(frozen=True, slots=True)
class PurchaseOrderItem:
    key: str
    label: str


def resolve_purchase_item(value: str) -> PurchaseOrderItem:
    try:
        item = resolve_market_item(value)
    except ValueError as exc:
        raise ValueError("item is not allowed in a purchase order") from exc
    if item.key in NON_TRADEABLE_ITEMS:
        raise ValueError("item is not allowed in a purchase order")
    return PurchaseOrderItem(item.key, item.label)


def validate_purchase_order(quantity: int, unit_price: int) -> None:
    if not PURCHASE_MIN_QUANTITY <= int(quantity) <= PURCHASE_MAX_QUANTITY:
        raise ValueError("quantity out of range")
    if not PURCHASE_MIN_UNIT_PRICE <= int(unit_price) <= PURCHASE_MAX_UNIT_PRICE:
        raise ValueError("unit price out of range")


def purchase_fee(total_price: int) -> int:
    total = int(total_price)
    return max(1, (total * PURCHASE_FEE_BP + BP_DENOMINATOR - 1) // BP_DENOMINATOR)


def delivery_deadline(value):
    return value + timedelta(seconds=PURCHASE_DELIVERY_GRACE_SECONDS)


def order_region(location_key: str) -> str:
    value = str(location_key or "")
    if value.startswith("demon."):
        return "demon"
    if value.startswith("beast."):
        return "beast"
    return "xuantian"


def faction_for_location(location_key: str) -> str:
    return TRADE_MARKET_FACTIONS.get(str(location_key), order_region(location_key))


def required_faction_reputation(location_key: str) -> tuple[str, int] | None:
    faction = TRADE_MARKET_FACTIONS.get(str(location_key))
    return (faction, 200) if faction else None


__all__ = [
    "BP_DENOMINATOR",
    "CONTENT_VERSION",
    "PURCHASE_DELIVERY_GRACE_SECONDS",
    "PURCHASE_FEE_BP",
    "PURCHASE_MAX_LISTINGS",
    "PURCHASE_MAX_QUANTITY",
    "PURCHASE_MAX_UNIT_PRICE",
    "PURCHASE_MIN_QUANTITY",
    "PURCHASE_MIN_UNIT_PRICE",
    "PURCHASE_ORDER_TTL_SECONDS",
    "PurchaseOrderItem",
    "RULE_VERSION",
    "delivery_deadline",
    "faction_for_location",
    "order_region",
    "purchase_fee",
    "required_faction_reputation",
    "resolve_purchase_item",
    "validate_purchase_order",
]
