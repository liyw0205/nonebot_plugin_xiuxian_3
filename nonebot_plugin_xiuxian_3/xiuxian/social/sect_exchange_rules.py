"""Versioned rules for the sect warehouse exchange slice."""

from __future__ import annotations

from dataclasses import dataclass


SECT_EXCHANGE_DAILY_CAP = 5
SECT_EXCHANGE_CONTENT_VERSION = "content-0.2"
SECT_EXCHANGE_RULE_VERSION = "economy-0.2.0"
SECT_SUPPLY_RULE_VERSION = "social-0.2.1"
SECT_DONATION_ITEMS = frozenset({
    "item.herb.spirit_leaf", "item.herb.blood_grass",
    "item.mat.array_sand", "item.material.cloud_iron",
})
SECT_DONATION_ALIASES = {
    "灵叶": "item.herb.spirit_leaf", "止血草": "item.herb.blood_grass",
    "阵砂": "item.mat.array_sand", "云铁": "item.material.cloud_iron",
}
SECT_SUPPLY_RECIPES = {
    "sect.exchange.foundation_guard": (
        {"item.herb.spirit_leaf": 2, "item.mat.array_sand": 1, "item.herb.blood_grass": 1},
        100,
    ),
    "sect.exchange.golden_core_guard": (
        {"item.herb.spirit_leaf": 3, "item.material.cloud_iron": 1, "item.herb.blood_grass": 2},
        200,
    ),
}


@dataclass(frozen=True, slots=True)
class SectExchangeOffer:
    key: str
    label: str
    contribution_cost: int
    item_key: str
    quantity: int


SECT_EXCHANGE_OFFERS: dict[str, SectExchangeOffer] = {
    "sect.exchange.foundation_guard": SectExchangeOffer(
        key="sect.exchange.foundation_guard",
        label="筑基护脉丹",
        contribution_cost=30,
        item_key="item.pill.foundation_guard",
        quantity=1,
    ),
    "sect.exchange.cloud_iron": SectExchangeOffer(
        key="sect.exchange.cloud_iron",
        label="云铁",
        contribution_cost=20,
        item_key="item.material.cloud_iron",
        quantity=2,
    ),
    "sect.exchange.golden_core_guard": SectExchangeOffer(
        key="sect.exchange.golden_core_guard",
        label="金丹护脉丹",
        contribution_cost=50,
        item_key="item.pill.golden_core_guard",
        quantity=1,
    ),
    "sect.exchange.array_sand": SectExchangeOffer(
        key="sect.exchange.array_sand",
        label="阵砂",
        contribution_cost=10,
        item_key="item.mat.array_sand",
        quantity=5,
    ),
}

SECT_EXCHANGE_ALIASES = {
    "筑基护脉丹": "sect.exchange.foundation_guard",
    "筑基保护丹": "sect.exchange.foundation_guard",
    "sect.exchange.foundation_guard": "sect.exchange.foundation_guard",
    "云铁": "sect.exchange.cloud_iron",
    "sect.exchange.cloud_iron": "sect.exchange.cloud_iron",
    "金丹护脉丹": "sect.exchange.golden_core_guard",
    "金丹保护丹": "sect.exchange.golden_core_guard",
    "sect.exchange.golden_core_guard": "sect.exchange.golden_core_guard",
    "阵砂": "sect.exchange.array_sand",
    "sect.exchange.array_sand": "sect.exchange.array_sand",
}


def resolve_sect_exchange_offer(value: str) -> SectExchangeOffer | None:
    key = SECT_EXCHANGE_ALIASES.get(value.strip())
    return SECT_EXCHANGE_OFFERS.get(key) if key else None


__all__ = [
    "SECT_EXCHANGE_ALIASES",
    "SECT_EXCHANGE_CONTENT_VERSION",
    "SECT_EXCHANGE_DAILY_CAP",
    "SECT_EXCHANGE_OFFERS",
    "SECT_EXCHANGE_RULE_VERSION",
    "SECT_SUPPLY_RULE_VERSION",
    "SECT_DONATION_ITEMS",
    "SECT_DONATION_ALIASES",
    "SECT_SUPPLY_RECIPES",
    "SectExchangeOffer",
    "resolve_sect_exchange_offer",
]
