"""Immutable records returned by production commission transactions."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class ProductionCommissionRecord:
    commission_id: str
    status: str
    publisher_player_id: str
    publisher_platform_user_id: str
    publisher_dao_name: str
    producer_player_id: str | None
    producer_platform_user_id: str | None
    producer_dao_name: str | None
    recipe_key: str
    recipe_name: str
    reward_stones: int
    material_mode: str
    starts_at: str | None
    ends_at: str | None
    expires_at: str
    outputs: dict[str, int] = field(default_factory=dict)
    refunds: dict[str, int] = field(default_factory=dict)
    producer_payment: int = 0
    publisher_refund: int = 0
    platform_fee: int = 0
    quality_bp: int | None = None
    already_completed: bool = False


__all__ = ["ProductionCommissionRecord"]
