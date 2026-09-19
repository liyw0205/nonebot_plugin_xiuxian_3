"""Pure player entity and initial-state invariants."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from collections.abc import Mapping
from typing import Any


class PlayerStatus(str, Enum):
    ACTIVE = "active"
    DISABLED = "disabled"
    DELETED = "deleted"


@dataclass(frozen=True, slots=True)
class Player:
    player_id: str
    external_id: str
    nickname: str
    realm: str
    level: int
    cultivation: int
    spirit_stones: int
    stamina: int
    status: PlayerStatus

    def __post_init__(self) -> None:
        if not self.player_id or not self.external_id or not self.nickname:
            raise ValueError("player identity and nickname are required")
        if self.level < 1:
            raise ValueError("player level must be positive")
        if min(self.cultivation, self.spirit_stones, self.stamina) < 0:
            raise ValueError("player assets cannot be negative")
        if not self.realm:
            raise ValueError("player realm is required")

    @classmethod
    def new(cls, *, player_id: str, external_id: str, nickname: str) -> "Player":
        return cls(
            player_id=player_id,
            external_id=external_id,
            nickname=nickname,
            realm="凡人",
            level=1,
            cultivation=0,
            spirit_stones=0,
            stamina=100,
            status=PlayerStatus.ACTIVE,
        )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "Player":
        return cls(
            player_id=str(value["player_id"]),
            external_id=str(value["external_id"]),
            nickname=str(value["nickname"]),
            realm=str(value["realm"]),
            level=int(value["level"]),
            cultivation=int(value["cultivation"]),
            spirit_stones=int(value["spirit_stones"]),
            stamina=int(value["stamina"]),
            status=PlayerStatus(str(value["status"])),
        )