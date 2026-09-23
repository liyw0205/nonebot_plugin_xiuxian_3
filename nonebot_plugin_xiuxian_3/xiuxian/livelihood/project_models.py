"""Application records for weekly public projects."""

from __future__ import annotations

from dataclasses import dataclass, field

from ...contracts import PlayerView


@dataclass(frozen=True, slots=True)
class PublicProjectView:
    project_id: str
    project_key: str
    label: str
    business_week: str
    status: str
    contribution_points: int
    target_points: int
    progress: dict[str, int] = field(default_factory=dict)
    requirements: dict[str, int] = field(default_factory=dict)
    effect_key: str = ""
    effect_ends_at: str = ""


@dataclass(frozen=True, slots=True)
class ProjectContributionRecord:
    player: PlayerView
    project: PublicProjectView
    resource_key: str
    resource_amount: int
    contribution_points: int
    already_completed: bool = False


@dataclass(frozen=True, slots=True)
class ProjectSettlementRecord:
    player: PlayerView
    project: PublicProjectView
    eligible: bool
    rewarded: bool
    reward: dict[str, int] = field(default_factory=dict)
    already_completed: bool = False


__all__ = [
    "ProjectContributionRecord",
    "ProjectSettlementRecord",
    "PublicProjectView",
]
