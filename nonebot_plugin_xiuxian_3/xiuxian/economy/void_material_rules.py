"""Rules and records for 虚空物资寄售 (``market.void_material``)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from ..content import ContentBundle
from ..world.rules import meets_realm
from .void_material_content import void_material_defaults

LISTED = "listed"
SOLD = "sold"
CANCELLED = "cancelled"
EXPIRED = "expired"


@dataclass(frozen=True, slots=True)
class VoidMaterialListing:
    listing_id: str
    seller_label: str
    item_key: str
    item_label: str
    quantity: int
    unit_price: int
    status: str
    expires_at: str


@dataclass(frozen=True, slots=True)
class VoidMaterialBoard:
    name: str
    description: str
    admission_realm: str
    admission_layer: int
    admission_merit: int
    fee_bp: int
    listing_hours: int
    expire_grace_minutes: int
    max_listings: int
    allowed_item_keys: tuple[str, ...]
    qualified: bool
    missing: tuple[str, ...]
    own_listings: int
    listings: tuple[VoidMaterialListing, ...] = ()


@dataclass(frozen=True, slots=True)
class VoidMaterialTrade:
    listing_id: str
    trade_id: str
    item_key: str
    quantity: int
    gross: int
    fee: int
    net: int
    seller_stones_after: int
    buyer_stones_after: int
    already_completed: bool = False


def void_material_board_definition(content: ContentBundle) -> dict:
    return void_material_defaults(content)


def listing_expiry(*, created_at: datetime, listing_hours: int) -> datetime:
    return created_at + timedelta(hours=listing_hours)


def fee_for(*, gross: int, fee_bp: int) -> tuple[int, int]:
    """Return ``(fee, net)`` for one sale, rounding the fee down."""

    gross = max(0, int(gross))
    fee = gross * max(0, min(2_000, int(fee_bp))) // 10_000
    return fee, gross - fee


def admission_missing(
    *,
    realm_key: str,
    realm_layer: int,
    merit_key: str,
    merit: int,
    required_realm: str,
    required_layer: int,
    required_merit: int,
) -> list[str]:
    """Return unmet admission reasons; realm OR merit is enough."""

    if meets_realm(realm_key, realm_layer, required_realm, required_layer):
        return []
    if merit >= required_merit:
        return []
    return [f"境界 {required_realm} L{required_layer}", f"{merit_key} {required_merit}"]


def validate_listing_request(
    *,
    item_key: str,
    allowed_item_keys: tuple[str, ...],
    quantity: int,
    unit_price: int,
    held: int,
) -> str | None:
    """Return an error code for an invalid listing request, or ``None``."""

    if item_key not in allowed_item_keys:
        return "VOID_MARKET_ITEM_FORBIDDEN"
    if quantity <= 0 or unit_price <= 0:
        return "INVALID_VOID_MARKET_COMMAND"
    if quantity > held:
        return "VOID_MARKET_NOT_ENOUGH_ITEMS"
    return None


def expires_text(*, created_at: datetime, listing_hours: int) -> str:
    return listing_expiry(created_at=created_at, listing_hours=listing_hours).isoformat()


def is_expired(*, expires_at: str, now: datetime) -> bool:
    moment = datetime.fromisoformat(expires_at)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return now >= moment