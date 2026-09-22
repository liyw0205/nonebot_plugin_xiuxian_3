"""Application records for the v0.1 talent tree."""

from __future__ import annotations

from dataclasses import dataclass, field

from ...contracts import PlayerView


@dataclass(frozen=True, slots=True)
class TalentNodeRecord:
    node_key: str
    tree_key: str
    tier: int
    label: str
    description: str
    effect: dict[str, int | str] = field(default_factory=dict)
    cost_points: int = 0
    status: str = "learned"
    unlocked_at: str = ""
    already_completed: bool = False
    player: PlayerView | None = None


@dataclass(frozen=True, slots=True)
class TalentProfileRecord:
    player: PlayerView
    tree_key: str
    tree_label: str
    nodes: tuple[TalentNodeRecord, ...] = ()
    points_available: int = 0
    points_spent: int = 0
    already_completed: bool = False


__all__ = ["TalentNodeRecord", "TalentProfileRecord"]
