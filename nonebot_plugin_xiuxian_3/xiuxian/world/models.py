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
    # These gate projections come from the same SQLite read as the player;
    # cloud-boat previews must not reopen the repository for quest evidence.
    completed_quests: frozenset[str] = frozenset()
    intro_flags: frozenset[str] = frozenset()


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
    pass_consumed: bool = False
    already_completed: bool = False
