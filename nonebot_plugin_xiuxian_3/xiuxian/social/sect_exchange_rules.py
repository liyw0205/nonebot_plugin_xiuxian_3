"""Rules for the sect warehouse exchange slice (content-backed)."""

from __future__ import annotations

from dataclasses import dataclass

from .social_content import sect_exchange_record

_EXCHANGE = sect_exchange_record()

SECT_EXCHANGE_DAILY_CAP = int(_EXCHANGE["daily_cap"])
SECT_DONATION_ITEMS = frozenset(_EXCHANGE["donation_items"])
SECT_DONATION_ALIASES = dict(_EXCHANGE["donation_aliases"])
SECT_SUPPLY_RECIPES = {
    recipe_key: (dict(materials), contribution)
    for recipe_key, (materials, contribution) in _EXCHANGE["supply_recipes"].items()
}


@dataclass(frozen=True, slots=True)
class SectExchangeOffer:
    key: str
    label: str
    contribution_cost: int
    item_key: str
    quantity: int


SECT_EXCHANGE_OFFERS: dict[str, SectExchangeOffer] = {
    offer["key"]: SectExchangeOffer(
        key=offer["key"],
        label=offer["label"],
        contribution_cost=offer["contribution_cost"],
        item_key=offer["item_key"],
        quantity=offer["quantity"],
    )
    for offer in _EXCHANGE["offers"]
}

SECT_EXCHANGE_ALIASES = dict(_EXCHANGE["aliases"])


def resolve_sect_exchange_offer(value: str) -> SectExchangeOffer | None:
    key = SECT_EXCHANGE_ALIASES.get(value.strip())
    return SECT_EXCHANGE_OFFERS.get(key) if key else None


__all__ = [
    "SECT_EXCHANGE_ALIASES",
    "SECT_EXCHANGE_DAILY_CAP",
    "SECT_EXCHANGE_OFFERS",
    "SECT_DONATION_ITEMS",
    "SECT_DONATION_ALIASES",
    "SECT_SUPPLY_RECIPES",
    "SectExchangeOffer",
    "resolve_sect_exchange_offer",
]
