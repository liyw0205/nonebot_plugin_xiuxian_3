"""Immutable records returned by the economy repository."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MarketOrderRecord:
    order_id: str
    status: str
    seller_player_id: str
    seller_platform_user_id: str
    seller_dao_name: str
    buyer_player_id: str | None
    buyer_platform_user_id: str | None
    item_key: str
    quantity: int
    remaining_quantity: int
    unit_price: int
    listing_fee: int
    trade_fee: int
    total_price: int
    expires_at: str
    created_at: str
    already_completed: bool = False


__all__ = ["MarketOrderRecord"]
