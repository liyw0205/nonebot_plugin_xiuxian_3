"""Stable rules for demon and beast trade permits (content-backed)."""

from __future__ import annotations

from dataclasses import dataclass

from .trade_permit_content import permit_records


@dataclass(frozen=True, slots=True)
class TradePermitDefinition:
    key: str
    label: str
    faction_key: str
    required_quest: str
    reputation_required: int = 80
    cost: int = 500
    duration_seconds: int = 7 * 24 * 60 * 60


def _definition(record: dict) -> TradePermitDefinition:
    return TradePermitDefinition(
        key=str(record["key"]),
        label=str(record["label"]),
        faction_key=str(record["faction"]),
        required_quest=str(record["required_quest_flag"]),
        reputation_required=int(record["required_reputation"]),
        cost=int(record["cost"]),
        duration_seconds=int(record["duration_seconds"]),
    )


TRADE_PERMITS = {
    str(record["key"]): _definition(record) for record in permit_records()
}

PERMIT_COST = min(definition.cost for definition in TRADE_PERMITS.values())
PERMIT_DURATION_SECONDS = max(
    definition.duration_seconds for definition in TRADE_PERMITS.values()
)

ALIASES = {
    **{
        alias: str(record["key"])
        for record in permit_records()
        for alias in record["aliases"]
    },
    **{key: key for key in TRADE_PERMITS},
}


def resolve_trade_permit(value: str) -> TradePermitDefinition:
    key = ALIASES.get(value.strip(), value.strip())
    try:
        return TRADE_PERMITS[key]
    except KeyError as exc:
        raise ValueError(f"unsupported trade permit: {value}") from exc


__all__ = [
    "PERMIT_COST",
    "PERMIT_DURATION_SECONDS",
    "TRADE_PERMITS",
    "TradePermitDefinition",
    "resolve_trade_permit",
]
