"""Immutable records exchanged by the world movement domain."""

from __future__ import annotations

from dataclasses import dataclass

from ...contracts import PlayerView


@dataclass(frozen=True, slots=True)
class TravelPreview:
    player: PlayerView
    destination: str
    source: str
    duration_seconds: int
    stamina_cost: int
    currency_cost: int
    pass_key: str | None
    pass_quantity: int
    ready: bool
    missing: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TravelStartRecord:
    player: PlayerView
    session_id: str
    source: str
    destination: str
    status: str
    starts_at: str
    ends_at: str
    stamina_cost: int
    currency_cost: int
    pass_key: str | None
    pass_quantity: int
    already_completed: bool = False


@dataclass(frozen=True, slots=True)
class TravelSettlementRecord:
    player: PlayerView
    session_id: str
    source: str
    destination: str
    status: str
    arrived: bool
    stamina_cost: int
    currency_cost: int
    pass_key: str | None
    pass_quantity: int
    already_completed: bool = False
