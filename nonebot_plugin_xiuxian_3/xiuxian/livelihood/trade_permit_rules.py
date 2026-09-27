"""Stable rules for v0.3 demon and beast trade permits."""

from __future__ import annotations

from dataclasses import dataclass


CONTENT_VERSION = "content-0.3"
RULE_VERSION = "livelihood-0.3.0"
PERMIT_DURATION_SECONDS = 7 * 24 * 60 * 60
PERMIT_COST = 500


@dataclass(frozen=True, slots=True)
class TradePermitDefinition:
    key: str
    label: str
    faction_key: str
    required_quest: str
    reputation_required: int = 80
    cost: int = PERMIT_COST
    duration_seconds: int = PERMIT_DURATION_SECONDS
    content_version: str = CONTENT_VERSION
    rule_version: str = RULE_VERSION


TRADE_PERMITS = {
    "permit.demon_trade": TradePermitDefinition(
        "permit.demon_trade", "魔界贸易许可", "demon", "quest.demon_intro"
    ),
    "permit.beast_trade": TradePermitDefinition(
        "permit.beast_trade", "妖界贸易许可", "beast", "quest.beast_intro"
    ),
}

ALIASES = {
    "魔界": "permit.demon_trade",
    "魔界贸易": "permit.demon_trade",
    "魔界贸易许可": "permit.demon_trade",
    "妖界": "permit.beast_trade",
    "妖界贸易": "permit.beast_trade",
    "妖界贸易许可": "permit.beast_trade",
    **{key: key for key in TRADE_PERMITS},
}


def resolve_trade_permit(value: str) -> TradePermitDefinition:
    key = ALIASES.get(value.strip(), value.strip())
    try:
        return TRADE_PERMITS[key]
    except KeyError as exc:
        raise ValueError(f"unsupported trade permit: {value}") from exc


__all__ = [
    "CONTENT_VERSION",
    "PERMIT_COST",
    "PERMIT_DURATION_SECONDS",
    "RULE_VERSION",
    "TRADE_PERMITS",
    "TradePermitDefinition",
    "resolve_trade_permit",
]
