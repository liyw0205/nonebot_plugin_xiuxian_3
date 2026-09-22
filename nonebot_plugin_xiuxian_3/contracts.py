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
        if not isinstance(self.adapter, str) or not self.adapter.strip():
            raise ValueError("adapter is required")
        if not isinstance(self.user_id, str) or not self.user_id.strip():
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


def validate_command_identity(
    context: CommandContext,
    *,
    require_write: bool = False,
    write_message: str = "当前事件不允许执行此操作。",
) -> CommandResult | None:
    """Validate normalized adapter identity at the application boundary.

    Read-only commands only need a stable adapter/user identity. Asset-mutating
    commands additionally require the adapter to prove that the event can be
    written safely (for example, it has a message and scene identity).
    """

    try:
        context.validate()
    except ValueError:
        return CommandResult(
            False,
            "INVALID_CONTEXT",
            "无法识别你的平台身份，请稍后重试。",
            context.request_id,
        )
    if require_write and not context.can_write_assets:
        return CommandResult(False, "INVALID_CONTEXT", write_message, context.request_id)
    return None


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
    foundation_quality: int = 0
    world_merit: int = 0
    weakness_until: datetime | None = None
    breakthrough_pity_bp: int = 0
    talent_points: int = 0
    skill_insights: int = 0
    soul_power: int = 0
    soul_power_max: int = 0
    domain_charge: int = 0
    domain_charge_max: int = 0
    pollution: int = 0
    bloodline_stability: int = 0
    cross_realm_penalty_bp: int = 0
    soul_fatigue_until: datetime | None = None
    heart_demon_bonus_bp: int = 0
    max_hp: int = 0
    max_mp: int = 0
    carry_capacity: int = 0
    exploration_efficiency_bp: int = 0
    domain_key: str | None = None
    domain_power: int = 0
    realm_resistance_bp: int = 0
    domain_crack_until: datetime | None = None
    initiative: int = 0
    faction_reputation: dict[str, int] = field(default_factory=dict)
    domain_level: int = 0


def serialize_datetime(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()
