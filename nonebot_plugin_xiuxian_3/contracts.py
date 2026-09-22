"""Adapter-neutral request and response contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class CommandContext:
    """Normalized identity and scene data supplied by an adapter."""

    adapter: str
    user_id: str
    scene_id: str = ""
    nickname: str = ""
    request_id: str = field(default_factory=lambda: uuid4().hex)
    message_id: str = ""
    scene: str = "unknown"
    group_id: str = ""
    bot_id: str = ""
    capabilities: tuple[str, ...] = ("text",)
    can_write_assets: bool = True
    command_args: tuple[str, ...] = ()
    operation_id: str = ""

    def validate(self) -> None:
        if not self.adapter.strip():
            raise ValueError("adapter is required")
        if not self.user_id.strip():
            raise ValueError("user_id is required")


@dataclass(frozen=True, slots=True)
class CommandResult:
    ok: bool
    code: str
    message: str
    request_id: str
    operation_id: str | None = None
    data: dict[str, Any] = field(default_factory=dict)
    retryable: bool = False


@dataclass(frozen=True, slots=True)
class PlayerView:
    player_id: str
    platform: str
    platform_user_id: str
    scene_id: str
    nickname: str
    stage: str
    spirit_stones: int
    qualification: dict[str, int]
    created_at: datetime
    updated_at: datetime
    status: str = "active"
    location_key: str = "xuantian.new_town"
    rule_version: str = "player-onboarding-v0.1.0"
    path_key: str | None = None
    subprofession_key: str | None = None
    dao_name: str = ""
    stamina: int = 0
    stamina_max: int = 0
    energy: int = 0
    energy_max: int = 0
    inventory: dict[str, int] = field(default_factory=dict)
    durability: dict[str, int] = field(default_factory=dict)
    intro_flags: tuple[str, ...] = ()
    selected_service: str | None = None
    realm_key: str = "mortal"
    realm_layer: int = 0
    cultivation: int = 0
    total_cultivation: int = 0


def serialize_datetime(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()
