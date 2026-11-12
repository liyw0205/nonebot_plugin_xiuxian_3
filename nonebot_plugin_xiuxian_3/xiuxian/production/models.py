"""Production application records."""

from __future__ import annotations

from dataclasses import dataclass, field

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
    batch_count: int = 1
    batch_supported: bool = False
    tool_cost_bp: int = 0
    outputs: dict[str, int] = field(default_factory=dict)
    high_quality_bonus: dict[str, int] = field(default_factory=dict)
    failure_refunds: dict[str, int] = field(default_factory=dict)


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
    batch_count: int = 1


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
    batch_count: int = 1


@dataclass(frozen=True, slots=True)
class PollutionPurificationRecord:
    player: PlayerView
    item_key: str
    pollution_before: int
    pollution_after: int
    pollution_reduced: int
    item_quantity: int
    already_completed: bool = False


__all__ = [
    "ProductionOrderRecord",
    "ProductionPreviewRecord",
    "ProductionSettlementRecord",
    "PollutionPurificationRecord",
]
