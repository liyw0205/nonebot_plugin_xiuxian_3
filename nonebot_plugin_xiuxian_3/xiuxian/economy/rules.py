"""Pure rules for the fixed-price market v0.1 slice."""

from __future__ import annotations

from dataclasses import dataclass


ECONOMY_CONTENT_VERSION = "content-0.1"
ECONOMY_RULE_VERSION = "economy-0.1.0"
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
NON_TRADEABLE_ITEMS = frozenset({
    "item.pill.core_condense",
    "item.pill.golden_core_guard",
    "item.array.mist_barrier",
})


@dataclass(frozen=True, slots=True)
class MarketItem:
    key: str
    label: str


_ITEMS = {
    "item.food.coarse_spirit_rice": "粗糙灵米",
    "item.food.spirit_rice": "灵米饭",
    "item.herb.blood_grass": "止血草",
    "item.herb.spirit_leaf": "灵叶",
    "item.mat.wood": "木材",
    "item.ore.ironstone": "铁石",
    "item.mat.array_sand": "阵砂",
    "item.pill.healing_low": "低阶疗伤丹",
    "item.weapon.wood_sword": "木纹剑",
}
_ALIASES = {
    "粗糙灵米": "item.food.coarse_spirit_rice",
    "灵米饭": "item.food.spirit_rice",
    "止血草": "item.herb.blood_grass",
    "血草": "item.herb.blood_grass",
    "灵叶": "item.herb.spirit_leaf",
    "木材": "item.mat.wood",
    "木头": "item.mat.wood",
    "铁石": "item.ore.ironstone",
    "阵砂": "item.mat.array_sand",
    "低阶疗伤丹": "item.pill.healing_low",
    "木纹剑": "item.weapon.wood_sword",
    "木剑": "item.weapon.wood_sword",
}


def resolve_market_item(value: str) -> MarketItem:
    key = _ALIASES.get(value.strip(), value.strip())
    if not key or not key.startswith("item."):
        raise ValueError("item is not tradeable")
    if key in NON_TRADEABLE_ITEMS or any(marker in key for marker in ("manual", "token", "certificate", "bound", "locked", "masterwork")):
        raise ValueError("item is not tradeable")
    return MarketItem(key=key, label=_ITEMS.get(key, key))


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
    "ECONOMY_CONTENT_VERSION",
    "ECONOMY_RULE_VERSION",
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
    "NON_TRADEABLE_ITEMS",
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
