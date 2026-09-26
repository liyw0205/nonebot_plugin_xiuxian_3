"""Immutable records for the v0.2 world vertical slice."""

from __future__ import annotations

from dataclasses import dataclass, field

from ...contracts import PlayerView


@dataclass(frozen=True, slots=True)
class CloudBoatStartRecord:
    player: PlayerView
    session_id: str
    route_key: str
    source: str
    destination: str
    status: str
    starts_at: str
    ends_at: str
    stamina_cost: int
    currency_cost: int
    pass_key: str | None = None
    pass_quantity: int = 0
    already_completed: bool = False


@dataclass(frozen=True, slots=True)
class CloudBoatSettlementRecord:
    player: PlayerView
    session_id: str
    route_key: str
    source: str
    destination: str
    status: str
    arrived: bool
    stamina_cost: int
    currency_cost: int
    pass_key: str | None = None
    pass_quantity: int = 0
    already_completed: bool = False


@dataclass(frozen=True, slots=True)
class DemonIntroRecord:
    player: PlayerView
    quest_key: str
    status: str
    reward: dict[str, int] = field(default_factory=dict)
    already_completed: bool = False


@dataclass(frozen=True, slots=True)
class BeastHistoryRecord:
    quest_key: str
    component_key: str
    already_completed: bool = False


@dataclass(frozen=True, slots=True)
class BeastIntroRecord:
    player: PlayerView
    quest_key: str
    status: str
    reward: dict[str, int] = field(default_factory=dict)
    already_completed: bool = False


@dataclass(frozen=True, slots=True)
class ArrayHallRecord:
    player: PlayerView
    status: str
    permission: str
    action: str
    already_completed: bool = False


__all__ = [
    "ArrayHallRecord",
    "BeastHistoryRecord",
    "BeastIntroRecord",
    "CloudBoatSettlementRecord",
    "CloudBoatStartRecord",
    "DemonIntroRecord",
]
