"""Immutable records returned by the cross-realm purchase-order domain."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PurchaseOrderRecord:
    order_id: str
    status: str
    buyer_player_id: str
    buyer_platform_user_id: str
    buyer_dao_name: str
    buyer_faction: str
    seller_player_id: str | None
    seller_platform_user_id: str | None
    seller_dao_name: str | None
    seller_faction: str | None
    item_key: str
    quantity: int
    unit_price: int
    purchase_fee: int
    total_price: int
    escrow_amount: int
    item_region: str | None
    item_source_location: str | None
    first_binding_expires_at: str | None
    alliance_key: str | None
    expires_at: str
    delivery_deadline: str | None
    created_at: str
    already_completed: bool = False
    transition_notice: str | None = None


__all__ = ["PurchaseOrderRecord"]
