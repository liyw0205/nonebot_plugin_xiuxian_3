"""Immutable records for high-realm quest progress."""

from __future__ import annotations

from dataclasses import dataclass, field

from ...contracts import PlayerView


@dataclass(frozen=True, slots=True)
class QuestStatusRecord:
    player: PlayerView
    quests: dict[str, dict[str, object]] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class QuestActionRecord:
    player: PlayerView
    quest_key: str
    component_key: str
    status: str
    progress: dict[str, int]
    reward: dict[str, int] = field(default_factory=dict)
    already_completed: bool = False


@dataclass(frozen=True, slots=True)
class QuestClaimRecord:
    player: PlayerView
    quest_key: str
    status: str
    progress: dict[str, int]
    snapshot: dict[str, object] = field(default_factory=dict)
    already_completed: bool = False


@dataclass(frozen=True, slots=True)
class DaoUnionQualificationRecord:
    """The immutable qualification snapshot used by the 合道 permit."""

    player: PlayerView
    quest_key: str
    status: str
    progress: dict[str, int]
    snapshot: dict[str, object]
    already_completed: bool = False


__all__ = [
    "DaoUnionQualificationRecord",
    "QuestActionRecord",
    "QuestClaimRecord",
    "QuestStatusRecord",
]
