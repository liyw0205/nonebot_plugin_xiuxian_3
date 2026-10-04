"""Shared persistence helpers for content-backed equipment instances."""

from __future__ import annotations

import sqlite3
from typing import Any, Mapping
from uuid import uuid4

from ..advancement.equipment_rules import (
    equipment_definition,
    equipment_initial_durability_bp,
)
from ..content import ContentBundle, bundled_content


def equipment_instance_template(
    item_key: str, content: ContentBundle | None = None
) -> dict[str, Any] | None:
    """Freeze the fields needed to create an equipment instance later."""

    bundle = content or bundled_content()
    item = bundle.require("item", item_key, include_locked=False)
    if item.get("item_type") not in {"weapon", "armor", "accessory"}:
        return None
    definition = equipment_definition(item_key, bundle)
    return {
        "item_key": definition.key,
        "label": definition.label,
        "slot": definition.slot,
        "durability_bp": equipment_initial_durability_bp(0, definition),
        "max_temper_level": definition.max_temper_level,
    }


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
    frozen_template: Mapping[str, Any] | None = None,
) -> bool:
    """Create equipment instances, returning False for non-equipment keys."""

    if isinstance(quantity, bool) or quantity < 1:
        raise ValueError("equipment quantity must be positive")
    if frozen_template is None:
        try:
            definition = equipment_definition(item_key, content)
        except ValueError:
            return False
        label = definition.label
        slot = definition.slot
        max_temper_level = definition.max_temper_level
        default_durability = equipment_initial_durability_bp(quality, definition)
    else:
        frozen_key = frozen_template.get("item_key")
        label = frozen_template.get("label")
        slot = frozen_template.get("slot")
        default_durability = frozen_template.get("durability_bp")
        max_temper_level = frozen_template.get("max_temper_level")
        if (
            frozen_key != item_key
            or not isinstance(label, str)
            or not label
            or not isinstance(slot, str)
            or not slot
            or isinstance(default_durability, bool)
            or not isinstance(default_durability, int)
            or default_durability < 0
            or isinstance(max_temper_level, bool)
            or not isinstance(max_temper_level, int)
            or max_temper_level <= 0
        ):
            raise ValueError("frozen equipment instance template is invalid")
    durability = (
        default_durability
        if durability_bp is None
        else max(0, min(10_000, int(durability_bp)))
    )
    occupied_slots = {
        str(row[0])
        for row in connection.execute(
            "SELECT slot FROM equipment_instances WHERE player_id = ? AND status = 'active' AND equipped = 1",
            (player_id,),
        ).fetchall()
    }
    rows: list[tuple[Any, ...]] = []
    for _ in range(quantity):
        is_equipped = slot not in occupied_slots
        occupied_slots.add(slot)
        rows.append(
            (
                uuid4().hex,
                player_id,
                item_key,
                label,
                slot,
                int(is_equipped),
                durability,
                max_temper_level,
                now_text,
                now_text,
            )
        )
    connection.executemany(
        """
        INSERT INTO equipment_instances(
            instance_id, player_id, item_key, label, slot, status,
            equipped, durability_bp, temper_level, max_temper_level, affixes_json,
            refinement_failure_streak, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, 'active', ?, ?, 0, ?, '{}', 0, ?, ?)
        """,
        rows,
    )
    return True


def equipment_instance_rows(
    connection: sqlite3.Connection,
    player_id: int,
    *,
    equipped_only: bool = False,
    durable_only: bool = False,
    active_only: bool = False,
) -> list[sqlite3.Row]:
    """Read owned equipment with one shared loadout filter for all snapshots."""

    clauses = ["player_id = ?", "status = 'active'" if active_only else "status IN ('active', 'broken')"]
    parameters: list[Any] = [player_id]
    if equipped_only:
        clauses.append("equipped = 1")
    if durable_only:
        clauses.append("durability_bp > 0")
    return connection.execute(
        "SELECT * FROM equipment_instances WHERE " + " AND ".join(clauses) + " ORDER BY id",
        parameters,
    ).fetchall()


__all__ = ["create_equipment_instances", "equipment_instance_rows", "equipment_instance_template"]
