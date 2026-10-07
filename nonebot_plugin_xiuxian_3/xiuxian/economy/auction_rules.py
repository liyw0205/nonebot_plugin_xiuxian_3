"""Content rules and frozen terms for the limited weekly auction."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, fields
from datetime import datetime, timedelta, timezone
from typing import Any

from ..content import ContentBundle, ContentError, bundled_content
from .rules import MarketItem, resolve_market_item


BP_DENOMINATOR = 10_000


@dataclass(frozen=True, slots=True)
class AuctionDefinition:
    key: str
    name: str
    desc: str
    slot_limit: int
    duration_seconds: int
    settlement_grace_seconds: int
    min_quantity: int
    max_quantity: int
    min_starting_bid: int
    min_increment_bp: int

    def snapshot(self) -> dict[str, Any]:
        return asdict(self)


_SNAPSHOT_FIELDS = frozenset(field.name for field in fields(AuctionDefinition))
_NUMBER_FIELDS = _SNAPSHOT_FIELDS - {"key", "name", "desc"}


def _integer(value: object, name: str, minimum: int = 1) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"auction {name} is invalid")
    return value


def auction_definition_from_snapshot(value: object) -> AuctionDefinition:
    if not isinstance(value, Mapping) or set(value) != _SNAPSHOT_FIELDS:
        raise ValueError("auction snapshot fields are incomplete or unsupported")
    if value["key"] != "auction.weekly":
        raise ValueError("auction key is invalid")
    for name in ("name", "desc"):
        if not isinstance(value[name], str) or not value[name].strip():
            raise ValueError(f"auction {name} is invalid")
    for name in _NUMBER_FIELDS:
        _integer(value[name], name)
    if value["max_quantity"] < value["min_quantity"]:
        raise ValueError("auction max_quantity is below min_quantity")
    return AuctionDefinition(**dict(value))


def auction_definition(content: ContentBundle | None = None) -> AuctionDefinition:
    bundle = content if content is not None else bundled_content()
    try:
        row = bundle.require("auction", "auction.weekly", include_locked=True)
    except KeyError as exc:
        raise ContentError("missing auction content: auction.weekly") from exc
    if row.get("status") not in {"active", "open"}:
        raise ContentError("auction.weekly status is not open")
    try:
        return auction_definition_from_snapshot({name: row[name] for name in _SNAPSHOT_FIELDS})
    except (KeyError, ValueError) as exc:
        raise ContentError(f"invalid auction.weekly content: {exc}") from exc


def auction_week_start(value: datetime) -> str:
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ValueError("auction time must include a timezone")
    utc = value.astimezone(timezone.utc)
    return (utc.date() - timedelta(days=utc.weekday())).isoformat()


def validate_auction_listing(
    item_key: str, quantity: int, starting_bid: int, definition: AuctionDefinition,
    content: ContentBundle | None = None,
) -> MarketItem:
    item = resolve_market_item(item_key, content)
    quantity = _integer(quantity, "quantity")
    starting_bid = _integer(starting_bid, "starting_bid")
    if not definition.min_quantity <= quantity <= definition.max_quantity:
        raise ValueError("auction quantity out of range")
    if starting_bid < definition.min_starting_bid:
        raise ValueError("auction starting_bid is below minimum")
    return item


def minimum_next_bid(current_bid: int, starting_bid: int, increment_bp: int) -> int:
    current_bid = _integer(current_bid, "current_bid", 0)
    starting_bid = _integer(starting_bid, "starting_bid")
    increment_bp = _integer(increment_bp, "increment_bp")
    if current_bid == 0:
        return starting_bid
    increment = (current_bid * increment_bp + BP_DENOMINATOR - 1) // BP_DENOMINATOR
    return current_bid + increment


__all__ = [
    "AuctionDefinition", "BP_DENOMINATOR", "auction_definition",
    "auction_definition_from_snapshot", "auction_week_start", "minimum_next_bid",
    "validate_auction_listing",
]
