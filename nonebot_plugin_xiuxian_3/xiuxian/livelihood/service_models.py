"""Application records for player-to-player livelihood services."""

from __future__ import annotations

from dataclasses import dataclass, field

from ...contracts import PlayerView


@dataclass(frozen=True, slots=True)
class ServiceOrderRecord:
    player: PlayerView
    order_id: str
    service_key: str
    service_name: str
    status: str
    reward_stones: int
    starts_at: str
    expires_at: str
    publisher_outputs: dict[str, int] = field(default_factory=dict)
    already_completed: bool = False


@dataclass(frozen=True, slots=True)
class ServiceSettlementRecord:
    player: PlayerView
    order_id: str
    service_key: str
    service_name: str
    status: str
    reward_stones: int
    provider_payment: int
    publisher_refund: int
    platform_fee: int = 0
    outputs: dict[str, int] = field(default_factory=dict)
    provider_refunds: dict[str, int] = field(default_factory=dict)
    stamina_refund: int = 0
    already_completed: bool = False


__all__ = ["ServiceOrderRecord", "ServiceSettlementRecord"]
