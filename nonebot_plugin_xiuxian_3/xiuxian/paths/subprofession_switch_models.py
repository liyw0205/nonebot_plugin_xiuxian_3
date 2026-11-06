"""Read models for the standalone support sub-profession switch."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class SubprofessionSwitchPlanRecord:
    plan_id: str
    status: str
    from_subprofession_key: str
    from_subprofession_label: str
    to_subprofession_key: str
    to_subprofession_label: str
    cost: dict[str, Any]
    snapshot: dict[str, Any]
    expires_at: str
    idempotent_replay: bool = False


@dataclass(frozen=True, slots=True)
class SubprofessionSwitchResultRecord:
    switch_id: str
    plan_id: str
    from_subprofession_key: str
    from_subprofession_label: str
    to_subprofession_key: str
    to_subprofession_label: str
    spirit_stones_before: int
    spirit_stones_after: int
    player: Any = None
    already_completed: bool = False


__all__ = ["SubprofessionSwitchPlanRecord", "SubprofessionSwitchResultRecord"]
