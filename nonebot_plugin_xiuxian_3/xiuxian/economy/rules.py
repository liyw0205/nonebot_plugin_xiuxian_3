"""Pure rules for the fixed-price market slice."""

from __future__ import annotations

from dataclasses import dataclass

from ..content import ContentBundle
from ..items.rules import resolve_item_record


MARKET_ORDER_TTL_SECONDS = 24 * 60 * 60
MARKET_MAX_LISTINGS = 10
MARKET_MIN_QUANTITY = 1
MARKET_MAX_QUANTITY = 99
MARKET_MIN_UNIT_PRICE = 1
MARKET_MAX_UNIT_PRICE = 100_000
MARKET_LISTING_FEE_PER_ITEM = 1
MARKET_TRADE_FEE_BP = 500
MARKET_BP_DENOMINATOR = 10_000
COMMISSION_MIN_REWARD = 1
COMMISSION_MAX_REWARD = 500
COMMISSION_PLATFORM_FEE_BP = 200
COMMISSION_FAILURE_REFUND_BP = 8000
COMMISSION_TTL_SECONDS = 24 * 60 * 60
COMMISSION_RECOVERY_GRACE_SECONDS = 24 * 60 * 60
COMMISSION_RECIPES = frozenset({"recipe.pill.healing_low", "recipe.weapon.wood_sword"})
@dataclass(frozen=True, slots=True)
class MarketItem:
    key: str
    label: str


def resolve_market_item(value: str, content: ContentBundle | None = None) -> MarketItem:
    try:
        item = resolve_item_record(value, content)
    except ValueError as exc:
        raise ValueError("item is not tradeable") from exc
    # The content contract supplies the static gate; a stack's binding state is
    # checked later by the repository's binding ledger.
    if not item.tradeable:
        raise ValueError("item is not tradeable")
    return MarketItem(key=item.key, label=item.name)


def validate_market_listing(quantity: int, unit_price: int) -> None:
    if not MARKET_MIN_QUANTITY <= quantity <= MARKET_MAX_QUANTITY:
        raise ValueError("quantity out of range")
    if not MARKET_MIN_UNIT_PRICE <= unit_price <= MARKET_MAX_UNIT_PRICE:
        raise ValueError("unit price out of range")


def listing_fee(quantity: int) -> int:
    return quantity * MARKET_LISTING_FEE_PER_ITEM


def trade_fee(total_price: int) -> int:
    return max(1, (total_price * MARKET_TRADE_FEE_BP + MARKET_BP_DENOMINATOR - 1) // MARKET_BP_DENOMINATOR)


def commission_platform_fee(reward: int) -> int:
    return (reward * COMMISSION_PLATFORM_FEE_BP) // MARKET_BP_DENOMINATOR


def commission_failure_refund(reward: int) -> int:
    return (reward * COMMISSION_FAILURE_REFUND_BP) // MARKET_BP_DENOMINATOR


__all__ = [
    "MARKET_BP_DENOMINATOR",
    "MARKET_LISTING_FEE_PER_ITEM",
    "MARKET_MAX_LISTINGS",
    "MARKET_MAX_QUANTITY",
    "MARKET_MAX_UNIT_PRICE",
    "MARKET_MIN_QUANTITY",
    "MARKET_MIN_UNIT_PRICE",
    "MARKET_ORDER_TTL_SECONDS",
    "COMMISSION_FAILURE_REFUND_BP",
    "COMMISSION_MAX_REWARD",
    "COMMISSION_MIN_REWARD",
    "COMMISSION_PLATFORM_FEE_BP",
    "COMMISSION_RECIPES",
    "COMMISSION_RECOVERY_GRACE_SECONDS",
    "COMMISSION_TTL_SECONDS",
    "MarketItem",
    "listing_fee",
    "resolve_market_item",
    "trade_fee",
    "commission_failure_refund",
    "commission_platform_fee",
    "validate_market_listing",
]
