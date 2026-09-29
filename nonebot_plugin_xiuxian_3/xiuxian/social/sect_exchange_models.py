"""Records returned by sect warehouse exchange transactions."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SectExchangeRecord:
    offer_key: str
    label: str
    item_key: str
    quantity: int
    contribution_spent: int
    sect_id: str
    member_contribution: int
    warehouse_quantity: int
    inventory_quantity: int
    content_version: str = ""
    rule_version: str = ""
    already_completed: bool = False


__all__ = ["SectExchangeRecord"]
