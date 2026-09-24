"""Immutable records for the v0.6 realm and endgame progression slice."""

from __future__ import annotations

from dataclasses import dataclass

from ...contracts import PlayerView


@dataclass(frozen=True, slots=True)
class DaoUnionRecord:
    player: PlayerView
    changed: bool
    already_completed: bool = False


@dataclass(frozen=True, slots=True)
class TribulationEntryRecord:
    player: PlayerView
    changed: bool
    already_completed: bool = False


@dataclass(frozen=True, slots=True)
class TrialSessionRecord:
    player: PlayerView
    session_id: str
    battle_id: str
    trial_key: str
    choice_key: str | None
    status: str
    starts_at: str
    ends_at: str
    debt_before: int
    already_completed: bool = False


@dataclass(frozen=True, slots=True)
class TrialSettlementRecord:
    player: PlayerView
    session_id: str
    trial_key: str
    status: str
    success: bool
    roll_bp: int | None
    debt_delta: int
    reward_progress: int
    reward_merit: int
    reward_items: dict[str, int]
    reward_world_merit: int = 0
    dao_fruit_key: str | None = None
    battle_id: str | None = None
    battle_outcome: str | None = None
    already_completed: bool = False


@dataclass(frozen=True, slots=True)
class EndgameEndingRecord:
    player: PlayerView
    ending_key: str
    status: str
    already_completed: bool = False


@dataclass(frozen=True, slots=True)
class FinalBattlePreviewRecord:
    player: PlayerView
    ready: bool
    missing: tuple[str, ...]
    trial_keys: tuple[str, ...]
    certificate_count: int
    runtime_open: bool = False


@dataclass(frozen=True, slots=True)
class FinalBattleSessionRecord:
    battle_id: str
    status: str
    member_player_ids: tuple[str, ...]
    expires_at: str
    already_completed: bool = False


@dataclass(frozen=True, slots=True)
class FinalBattleResolutionRecord:
    battle_id: str
    status: str
    outcome: str
    round_no: int
    debt_delta: int
    cooldown_until: str | None
    rewards: dict[str, dict[str, int]]
    already_completed: bool = False


@dataclass(frozen=True, slots=True)
class FinalBattleReplayRecord:
    battle_id: str
    status: str
    snapshot: dict[str, object]
    state: dict[str, object]
    result: dict[str, object]
    actions: tuple[dict[str, object], ...]


__all__ = [
    "DaoUnionRecord",
    "TribulationEntryRecord",
    "TrialSessionRecord",
    "TrialSettlementRecord",
    "EndgameEndingRecord",
    "FinalBattlePreviewRecord",
    "FinalBattleReplayRecord",
    "FinalBattleResolutionRecord",
    "FinalBattleSessionRecord",
]
