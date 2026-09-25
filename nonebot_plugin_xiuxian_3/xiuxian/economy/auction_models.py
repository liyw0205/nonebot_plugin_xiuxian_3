"""Immutable records returned by the limited auction domain."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AuctionRecord:
    auction_id: str
    status: str
    week_start: str
    seller_platform_user_id: str
    seller_dao_name: str
    item_key: str
    quantity: int
    starting_bid: int
    current_bid: int
    current_bidder_platform_user_id: str | None
    ends_at: str
    settlement_deadline: str
    created_at: str
    already_completed: bool = False


__all__ = ["AuctionRecord"]
