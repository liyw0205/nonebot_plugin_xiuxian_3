"""Immutable records for fixed cross-realm trades."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CrossRealmTradeRecord:
    trade_id: str
    trade_key: str
    status: str
    week_start: str
    location_key: str
    input_items: dict[str, int]
    currency_cost: int
    output_items: dict[str, int]
    binding_expires_at: str
    content_version: str
    rule_version: str
    already_completed: bool = False


__all__ = ["CrossRealmTradeRecord"]
