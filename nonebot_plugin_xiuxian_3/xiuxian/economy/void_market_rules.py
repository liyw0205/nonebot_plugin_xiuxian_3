"""Rules for the weekly void market (``market.void_weekly.<week_id>``).

The market refreshes on a fixed UTC weekday/hour (Monday 00:00 UTC in the
shipped content), keeps a host-wide stock pool of twenty slots per week and
limits each player to three items per UTC day.  Prices are fixed, so the
market is a deterministic storefront rather than an order book.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from ..content import ContentBundle
from ..world.rules import meets_realm
from .void_market_content import void_market_alias_map, void_market_defaults, void_market_offers


@dataclass(frozen=True, slots=True)
class VoidMarketOffer:
    key: str
    label: str
    item_key: str
    quantity: int
    price_spirit_stones: int
    stock: int


@dataclass(frozen=True, slots=True)
class VoidMarketDefinition:
    location_key: str
    week_start_weekday: int
    week_start_hour_utc: int
    stock_slots: int
    daily_purchase_limit: int
    binding_seconds: int
    required_realm: str
    required_layer: int
    required_merit: int
    offers: tuple[VoidMarketOffer, ...]

    def offer(self, offer_key: str) -> VoidMarketOffer:
        for offer in self.offers:
            if offer.key == offer_key:
                return offer
        raise ValueError(f"unsupported void market offer: {offer_key}")


def void_market_definition(content: ContentBundle | None = None) -> VoidMarketDefinition:
    defaults = void_market_defaults(content)
    offers = tuple(
        VoidMarketOffer(
            key=str(record["key"]),
            label=str(record["label"]),
            item_key=str(record["item_key"]),
            quantity=int(record["quantity"]),
            price_spirit_stones=int(record["price_spirit_stones"]),
            stock=int(record["stock"]),
        )
        for record in void_market_offers(content)
    )
    return VoidMarketDefinition(
        location_key=str(defaults["location_key"]),
        week_start_weekday=int(defaults["week_start_weekday"]),
        week_start_hour_utc=int(defaults["week_start_hour_utc"]),
        stock_slots=int(defaults["stock_slots"]),
        daily_purchase_limit=int(defaults["daily_purchase_limit"]),
        binding_seconds=int(defaults["binding_seconds"]),
        required_realm=str(defaults["required_realm"]),
        required_layer=int(defaults["required_layer"]),
        required_merit=int(defaults["required_merit"]),
        offers=offers,
    )


# Built at import so a host loading malformed market content fails the deploy
# validation gate instead of the first player command.
DEFINITIONS = void_market_definition()


def resolve_void_market_offer(
    value: str, content: ContentBundle | None = None
) -> str | None:
    normalized = value.strip()
    if not normalized:
        return None
    try:
        aliases = void_market_alias_map(content)
    except (KeyError, ValueError):
        return None
    return aliases.get(normalized)


def week_start(value: datetime, definition: VoidMarketDefinition = DEFINITIONS) -> datetime:
    """Return the UTC market week start that contains ``value``."""

    moment = value.astimezone(timezone.utc) if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    days = (moment.isoweekday() - definition.week_start_weekday) % 7
    candidate = (moment.date() - timedelta(days=days))
    start = datetime(
        candidate.year,
        candidate.month,
        candidate.day,
        definition.week_start_hour_utc,
        tzinfo=timezone.utc,
    )
    if start > moment:
        start -= timedelta(days=7)
    return start


def week_id(value: datetime, definition: VoidMarketDefinition = DEFINITIONS) -> str:
    return week_start(value, definition).date().isoformat()


def week_refresh_at(value: datetime, definition: VoidMarketDefinition = DEFINITIONS) -> datetime:
    return week_start(value, definition) + timedelta(days=7)


def business_date(value: datetime) -> str:
    moment = value.astimezone(timezone.utc) if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    return moment.date().isoformat()


def void_market_missing_requirements(
    *,
    realm_key: str,
    realm_layer: int,
    void_merit: int,
    definition: VoidMarketDefinition = DEFINITIONS,
) -> tuple[str, ...]:
    """Return the player-facing reasons a purchase is not allowed yet.

    The contract admits a void-refining cultivator *or* a character holding
    the required void merit, so the gate is satisfied by either branch.
    """

    if meets_realm(realm_key, realm_layer, definition.required_realm, definition.required_layer):
        return ()
    if void_merit >= definition.required_merit:
        return ()
    return (f"炼虚 L1 或虚空功勋 {definition.required_merit}",)


__all__ = [
    "DEFINITIONS",
    "VoidMarketDefinition",
    "VoidMarketOffer",
    "business_date",
    "resolve_void_market_offer",
    "void_market_definition",
    "void_market_missing_requirements",
    "week_id",
    "week_refresh_at",
    "week_start",
]
