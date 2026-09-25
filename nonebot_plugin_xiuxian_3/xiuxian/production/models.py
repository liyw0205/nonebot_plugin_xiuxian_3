"""Production application records."""

from __future__ import annotations

from dataclasses import dataclass

from ...contracts import PlayerView


@dataclass(frozen=True, slots=True)
class ProductionPreviewRecord:
    player: PlayerView
    recipe_key: str
    recipe_name: str
    energy_cost: int
    duration_seconds: int
    daily_limit: int
    daily_used: int
    inputs: dict[str, int]
    tool_key: str | None
    currency_cost: int


@dataclass(frozen=True, slots=True)
class ProductionOrderRecord:
    player: PlayerView
    order_id: str
    recipe_key: str
    recipe_name: str
    status: str
    starts_at: str
    ends_at: str
    energy_cost: int
    currency_cost: int
    already_completed: bool = False


@dataclass(frozen=True, slots=True)
class ProductionSettlementRecord:
    player: PlayerView
    order_id: str
    recipe_key: str
    recipe_name: str
    status: str
    quality_bp: int
    random_quality_bp: int
    success: bool
    outputs: dict[str, int]
    refunds: dict[str, int]
    currency_spent: int
    tool_durability_bp: int | None
    binding_expires_at: str | None = None
    already_completed: bool = False


__all__ = [
    "ProductionOrderRecord",
    "ProductionPreviewRecord",
    "ProductionSettlementRecord",
]
