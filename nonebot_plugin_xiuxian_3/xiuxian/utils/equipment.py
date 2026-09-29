"""Shared persistence helpers for content-backed equipment instances."""

from __future__ import annotations

import sqlite3
from uuid import uuid4

from ..advancement.equipment_rules import (
    equipment_definition,
    equipment_initial_durability_bp,
)
from ..content import ContentBundle


def create_equipment_instances(
    connection: sqlite3.Connection,
    *,
    player_id: int,
    item_key: str,
    quantity: int,
    now_text: str,
    content: ContentBundle | None = None,
    quality: int = 0,
    durability_bp: int | None = None,
) -> bool:
    """Create equipment instances, returning False when the key is not equipment."""

    try:
        definition = equipment_definition(item_key, content)
    except ValueError:
        return False
    if isinstance(quantity, bool) or quantity < 1:
        raise ValueError("equipment quantity must be positive")
    durability = (
        equipment_initial_durability_bp(quality, definition)
        if durability_bp is None
        else max(0, min(10_000, int(durability_bp)))
    )
    connection.executemany(
        """
        INSERT INTO equipment_instances(
            instance_id, player_id, item_key, label, slot, status,
            durability_bp, temper_level, max_temper_level, affixes_json,
            refinement_failure_streak, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, 'active', ?, 0, ?, '{}', 0, ?, ?)
        """,
        [
            (
                uuid4().hex,
                player_id,
                definition.key,
                definition.label,
                definition.slot,
                durability,
                definition.max_temper_level,
                now_text,
                now_text,
            )
            for _ in range(quantity)
        ],
    )
    return True


__all__ = ["create_equipment_instances"]
