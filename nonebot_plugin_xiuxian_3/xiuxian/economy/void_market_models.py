"""Immutable records for the weekly void market."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class VoidMarketOfferState:
    key: str
    label: str
    item_key: str
    quantity: int
    price_spirit_stones: int
    stock: int
    remaining: int


@dataclass(frozen=True, slots=True)
class VoidMarketPreviewRecord:
    location_key: str
    week_id: str
    refresh_at: str
    stock_slots: int
    stock_remaining: int
    daily_limit: int
    daily_used: int
    at_market: bool
    qualified: bool
    missing: tuple[str, ...]
    offers: tuple[VoidMarketOfferState, ...]


@dataclass(frozen=True, slots=True)
class VoidMarketPurchaseRecord:
    purchase_id: str
    offer_key: str
    label: str
    item_key: str
    quantity: int
    unit_price: int
    total_cost: int
    week_id: str
    business_date: str
    daily_used: int
    daily_limit: int
    remaining: int
    binding_expires_at: str
    already_completed: bool = False


__all__ = [
    "VoidMarketOfferState",
    "VoidMarketPreviewRecord",
    "VoidMarketPurchaseRecord",
]
