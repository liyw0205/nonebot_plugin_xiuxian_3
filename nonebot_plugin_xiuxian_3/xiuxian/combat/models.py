"""Immutable records exchanged by the automatic combat application."""

from __future__ import annotations

from dataclasses import dataclass, field

from ...contracts import PlayerView


@dataclass(frozen=True, slots=True)
class BattleStartRecord:
    player: PlayerView
    battle_id: str
    enemy_key: str
    status: str
    round_no: int
    max_rounds: int
    already_completed: bool = False


@dataclass(frozen=True, slots=True)
class BattleTurnRecord:
    battle_id: str
    status: str
    outcome: str | None
    round_no: int
    player_hp: int
    enemy_hp: int
    action_count: int
    already_completed: bool = False


@dataclass(frozen=True, slots=True)
class BattleResolutionRecord:
    player: PlayerView
    battle_id: str
    enemy_key: str
    status: str
    outcome: str
    reason: str
    round_no: int
    reward: dict[str, int] = field(default_factory=dict)
    reward_status: str = "none"
    already_completed: bool = False


@dataclass(frozen=True, slots=True)
class BattleRewardClaimRecord:
    player: PlayerView
    battle_id: str
    reward: dict[str, int]
    reward_status: str
    already_completed: bool = False


@dataclass(frozen=True, slots=True)
class BattleReplayRecord:
    battle_id: str
    enemy_key: str
    status: str
    snapshot: dict[str, object]
    result: dict[str, object]
    actions: tuple[dict[str, object], ...]


__all__ = [
    "BattleReplayRecord",
    "BattleResolutionRecord",
    "BattleRewardClaimRecord",
    "BattleStartRecord",
    "BattleTurnRecord",
]
