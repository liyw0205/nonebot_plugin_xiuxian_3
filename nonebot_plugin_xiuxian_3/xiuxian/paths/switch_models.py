"""Read models for the path-switch flow."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class PathSwitchPlanRecord:
    plan_id: str
    status: str
    from_path_key: str
    from_path_label: str
    to_path_key: str
    to_path_label: str
    to_subprofession_key: str | None
    to_subprofession_label: str | None
    cost: dict[str, Any]
    snapshot: dict[str, Any]
    expires_at: str
    already_completed: bool = False
    idempotent_replay: bool = False


@dataclass(frozen=True, slots=True)
class PathSwitchTokenRecord:
    item_key: str
    item_label: str
    quantity: int
    player: Any
    claimed_at: str
    already_completed: bool = False


@dataclass(frozen=True, slots=True)
class PathSwitchResultRecord:
    plan_id: str
    from_path_key: str
    from_path_label: str
    to_path_key: str
    to_path_label: str
    to_subprofession_key: str | None
    to_subprofession_label: str | None
    spirit_stones_before: int
    spirit_stones_after: int
    token_quantity_before: int
    token_quantity_after: int
    retained: tuple[str, ...] = field(default_factory=tuple)
    frozen: tuple[str, ...] = field(default_factory=tuple)
    cleared: tuple[str, ...] = field(default_factory=tuple)
    player: Any = None
    already_completed: bool = False


__all__ = [
    "PathSwitchPlanRecord",
    "PathSwitchResultRecord",
    "PathSwitchTokenRecord",
]
