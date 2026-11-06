"""Read models for the nascent-soul path rebuild."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class PathRebuildPlanRecord:
    plan_id: str
    status: str
    from_path_key: str
    from_path_label: str
    to_path_key: str
    to_path_label: str
    to_subprofession_key: str | None
    to_subprofession_label: str | None
    old_level: int
    inherited_level: int
    cost: dict[str, Any]
    snapshot: dict[str, Any]
    expires_at: str
    already_completed: bool = False
    idempotent_replay: bool = False


@dataclass(frozen=True, slots=True)
class PathRebuildResultRecord:
    rebuild_id: str
    plan_id: str
    from_path_key: str
    from_path_label: str
    to_path_key: str
    to_path_label: str
    to_subprofession_key: str | None
    to_subprofession_label: str | None
    old_level: int
    inherited_level: int
    spirit_stones_before: int
    spirit_stones_after: int
    token_quantity_before: int
    token_quantity_after: int
    from_nodes: tuple[dict[str, Any], ...]
    inherited_nodes: tuple[dict[str, Any], ...]
    player: Any = None
    already_completed: bool = False


__all__ = ["PathRebuildPlanRecord", "PathRebuildResultRecord"]
