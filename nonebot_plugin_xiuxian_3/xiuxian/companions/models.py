"""灵兽领域的应用记录。"""

from __future__ import annotations

from dataclasses import dataclass, field

from ...contracts import PlayerView


@dataclass(frozen=True, slots=True)
class CompanionView:
    instance_id: str
    companion_key: str
    name: str
    kind: str
    level: int
    experience: int
    affinity: int
    stamina: int
    status: str
    deployed: bool
    gear: tuple[dict[str, object], ...] = ()


@dataclass(frozen=True, slots=True)
class CompanionStatusRecord:
    player: PlayerView
    companions: tuple[CompanionView, ...] = ()


@dataclass(frozen=True, slots=True)
class CompanionMutationRecord:
    player: PlayerView
    companion: CompanionView
    changed: bool
    already_completed: bool = False
    spent: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CompanionSnapshot:
    player_id: str
    companions: tuple[dict[str, object], ...] = ()


__all__ = [
    "CompanionMutationRecord",
    "CompanionSnapshot",
    "CompanionStatusRecord",
    "CompanionView",
]
