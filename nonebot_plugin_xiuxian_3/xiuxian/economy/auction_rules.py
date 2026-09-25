"""Versioned rules for the v0.3 limited weekly auction."""

from __future__ import annotations

from datetime import timedelta

from .rules import NON_TRADEABLE_ITEMS, resolve_market_item


CONTENT_VERSION = "content-0.3"
RULE_VERSION = "economy-0.3.0"
AUCTION_SLOT_LIMIT = 20
AUCTION_DURATION = timedelta(hours=12)
AUCTION_SETTLEMENT_GRACE = timedelta(minutes=10)
AUCTION_MIN_QUANTITY = 1
AUCTION_MAX_QUANTITY = 99
AUCTION_MIN_BID = 1
AUCTION_MIN_INCREMENT_BP = 500
BP_DENOMINATOR = 10_000


def auction_week_start(value) -> str:
    return (value.date() - timedelta(days=value.weekday())).isoformat()


def validate_auction_listing(item_key: str, quantity: int, starting_bid: int):
    item = resolve_market_item(item_key)
    if item.key in NON_TRADEABLE_ITEMS:
        raise ValueError("item is not allowed in the auction")
    if not AUCTION_MIN_QUANTITY <= int(quantity) <= AUCTION_MAX_QUANTITY:
        raise ValueError("quantity out of range")
    if int(starting_bid) < AUCTION_MIN_BID:
        raise ValueError("starting bid is invalid")
    return item


def minimum_next_bid(current_bid: int, starting_bid: int) -> int:
    if current_bid <= 0:
        return int(starting_bid)
    increment = (int(current_bid) * AUCTION_MIN_INCREMENT_BP + BP_DENOMINATOR - 1) // BP_DENOMINATOR
    return int(current_bid) + max(1, increment)


__all__ = [
    "AUCTION_DURATION",
    "AUCTION_MAX_QUANTITY",
    "AUCTION_MIN_BID",
    "AUCTION_MIN_INCREMENT_BP",
    "AUCTION_MIN_QUANTITY",
    "AUCTION_SETTLEMENT_GRACE",
    "AUCTION_SLOT_LIMIT",
    "BP_DENOMINATOR",
    "CONTENT_VERSION",
    "RULE_VERSION",
    "auction_week_start",
    "minimum_next_bid",
    "validate_auction_listing",
]
