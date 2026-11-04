"""Read models for the talent-tree reset."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class TalentResetPlanRecord:
    plan_id: str
    status: str
    path_key: str
    path_label: str
    tree_key: str
    tree_label: str
    nodes: tuple[dict[str, Any], ...]
    refund_points: int
    cost: dict[str, Any]
    snapshot: dict[str, Any]
    expires_at: str
    already_completed: bool = False
    idempotent_replay: bool = False


@dataclass(frozen=True, slots=True)
class TalentResetResultRecord:
    plan_id: str
    path_key: str
    path_label: str
    tree_key: str
    tree_label: str
    nodes: tuple[dict[str, Any], ...]
    refund_points: int
    spirit_stones_before: int
    spirit_stones_after: int
    talent_points_before: int
    talent_points_after: int
    player: Any = None
    already_completed: bool = False


__all__ = ["TalentResetPlanRecord", "TalentResetResultRecord"]
