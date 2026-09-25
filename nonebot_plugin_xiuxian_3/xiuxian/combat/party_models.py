"""Immutable records for party automatic PVE sessions."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class PartyBattleStartRecord:
    battle_id: str
    party_id: str
    enemy_key: str
    status: str
    round_no: int
    max_rounds: int
    member_player_ids: tuple[str, ...]
    already_completed: bool = False


@dataclass(frozen=True, slots=True)
class PartyBattleResolutionRecord:
    battle_id: str
    party_id: str
    enemy_key: str
    status: str
    outcome: str
    reason: str
    round_no: int
    rewards: dict[str, dict[str, int]] = field(default_factory=dict)
    contributions: dict[str, int] = field(default_factory=dict)
    reward_order: tuple[str, ...] = ()
    reward_rolls: dict[str, int] = field(default_factory=dict)
    already_completed: bool = False


@dataclass(frozen=True, slots=True)
class PartyBattleReplayRecord:
    battle_id: str
    party_id: str
    enemy_key: str
    status: str
    snapshot: dict[str, object]
    result: dict[str, object]
    actions: tuple[dict[str, object], ...]


__all__ = [
    "PartyBattleReplayRecord",
    "PartyBattleResolutionRecord",
    "PartyBattleStartRecord",
]
