"""Immutable application records for branching stories."""

from __future__ import annotations

from dataclasses import dataclass, field

from ...contracts import PlayerView


@dataclass(frozen=True, slots=True)
class StoryBranchView:
    key: str
    label: str
    required_source_count: int
    source_label: str
    evidence_operation_ids: tuple[str, ...] = ()

    @property
    def eligible(self) -> bool:
        return len(self.evidence_operation_ids) >= self.required_source_count


@dataclass(frozen=True, slots=True)
class StoryRecord:
    player: PlayerView
    story_key: str
    story_run_id: str | None
    status: str
    current_node: str
    selected_route: str | None
    ending_key: str | None
    completed_nodes: tuple[str, ...]
    branches: tuple[StoryBranchView, ...]
    snapshot: dict[str, object] = field(default_factory=dict)
    reward: dict[str, int] = field(default_factory=dict)
    already_completed: bool = False


__all__ = ["StoryBranchView", "StoryRecord"]
