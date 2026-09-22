"""Immutable records exchanged by the mainline application layer."""

from __future__ import annotations

from dataclasses import dataclass, field

from ...contracts import PlayerView


@dataclass(frozen=True, slots=True)
class MainlineStageView:
    key: str
    story_key: str
    chapter: int
    stage: int
    label: str
    description: str
    status: str
    first_clear_reward: dict[str, int | str] = field(default_factory=dict)
    repeat_reward: dict[str, int | str] = field(default_factory=dict)
    completed: bool = False
    claimed: bool = False


@dataclass(frozen=True, slots=True)
class MainlineStatusRecord:
    player: PlayerView
    story_key: str
    chapter: int
    current_stage: int
    status: str
    stages: tuple[MainlineStageView, ...]
    content_version: str = "content-0.1"
    rule_version: str = "mainline-0.1.0"
    already_completed: bool = False


@dataclass(frozen=True, slots=True)
class MainlineStartRecord:
    player: PlayerView
    story_key: str
    chapter: int
    stage: int
    stage_key: str
    status: str
    first_clear: bool = True
    label: str = ""
    description: str = ""
    starts_at: str | None = None
    ends_at: str | None = None
    already_completed: bool = False


@dataclass(frozen=True, slots=True)
class MainlineClaimRecord:
    player: PlayerView
    story_key: str
    chapter: int
    stage: int
    stage_key: str
    status: str
    reward: dict[str, int | str] = field(default_factory=dict)
    first_clear: bool = True
    label: str = ""
    source_operation_id: str | None = None
    already_completed: bool = False


__all__ = [
    "MainlineClaimRecord",
    "MainlineStageView",
    "MainlineStartRecord",
    "MainlineStatusRecord",
]
