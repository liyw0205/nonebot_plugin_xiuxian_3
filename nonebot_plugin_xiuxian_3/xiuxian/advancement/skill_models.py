"""Application records for v0.1 skill mastery."""

from __future__ import annotations

from dataclasses import dataclass, field

from ...contracts import PlayerView


@dataclass(frozen=True, slots=True)
class SkillMasteryRecord:
    player: PlayerView | None
    skill_key: str
    label: str
    path_key: str | None
    level: int
    max_level: int
    base_effect: dict[str, int | str] = field(default_factory=dict)
    effective_effect: dict[str, int | str] = field(default_factory=dict)
    resource_costs: dict[str, int] = field(default_factory=dict)
    trained_at: str = ""
    already_completed: bool = False


@dataclass(frozen=True, slots=True)
class SkillProfileRecord:
    player: PlayerView
    skills: tuple[SkillMasteryRecord, ...] = ()
    insight_balance: int = 0


__all__ = ["SkillMasteryRecord", "SkillProfileRecord"]
