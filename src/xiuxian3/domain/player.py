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
    energy: int = 0
    inventory_json: str = "{}"
    qualification_snapshot_id: str | None = None
    platform: str = "legacy"
    platform_user_id: str = ""
    scene: str = "unknown"
    stage: str = "mortal"
    location_key: str = "xuantian.new_town"

    def __post_init__(self) -> None:
        if not self.player_id or not self.external_id or not self.nickname:
            raise ValueError("player identity and nickname are required")
        if self.level < 1:
            raise ValueError("player level must be positive")
        if min(self.cultivation, self.spirit_stones, self.stamina, self.energy) < 0:
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
            energy=0,
            status=PlayerStatus.ACTIVE,
            platform_user_id=external_id,
        )

    @classmethod
    def new_identity(
        cls,
        *,
        player_id: str,
        platform: str,
        platform_user_id: str,
        scene: str,
        nickname: str,
    ) -> "Player":
        return cls(
            player_id=player_id,
            external_id=f"{platform}:{platform_user_id}",
            nickname=nickname,
            realm="凡人",
            level=1,
            cultivation=0,
            spirit_stones=0,
            stamina=0,
            energy=0,
            status=PlayerStatus.ACTIVE,
            platform=platform,
            platform_user_id=platform_user_id,
            scene=scene,
            stage="new_user",
            location_key="xuantian.new_town",
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
            energy=int(value.get("energy", 0)),
            inventory_json=str(value.get("inventory_json", "{}")),
            qualification_snapshot_id=value.get("qualification_snapshot_id"),
            platform=str(value.get("platform", "legacy")),
            platform_user_id=str(value.get("platform_user_id", value["external_id"])),
            scene=str(value.get("scene", "unknown")),
            stage=str(value.get("stage", "mortal")),
            location_key=str(value.get("location_key", "xuantian.new_town")),
        )