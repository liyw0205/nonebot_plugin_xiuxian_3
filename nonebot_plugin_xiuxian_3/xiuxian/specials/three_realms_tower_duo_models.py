"""Immutable records for the three-realms tower duo flow."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class ThreeRealmsTowerDuoRunRecord:
    duo_run_id: str
    party_id: str
    battle_id: str | None
    floor_no: int
    status: str
    outcome: str | None = None
    reason: str | None = None
    member_run_ids: tuple[str, ...] = ()
    first_clear_by_player: dict[str, bool] = field(default_factory=dict)
    reward_by_player: dict[str, dict[str, int]] = field(default_factory=dict)
    already_completed: bool = False


@dataclass(frozen=True, slots=True)
class ThreeRealmsTowerDuoRewardRecord:
    duo_run_id: str
    run_id: str
    player_id: str
    floor_no: int
    first_clear: bool
    reward: dict[str, int]
    already_completed: bool = False


__all__ = ["ThreeRealmsTowerDuoRunRecord", "ThreeRealmsTowerDuoRewardRecord"]
