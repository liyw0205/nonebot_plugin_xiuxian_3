"""Shared, transaction-local projection of verified discoveries."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Any

from ...contracts import serialize_datetime
from ..content import ContentBundle, bundled_content
from .codex_rules import category_for_entry


def _discovery_payload(snapshot: dict[str, Any] | None) -> dict[str, Any]:
    return {str(key): value for key, value in (snapshot or {}).items()}


def record_codex_discovery(
    connection: sqlite3.Connection,
    *,
    player_id: int,
    entry_key: str,
    operation_id: str,
    occurred_at: datetime | str,
    snapshot: dict[str, Any] | None = None,
    content: ContentBundle | None = None,
) -> bool:
    category = category_for_entry(entry_key, content)
    if category is None:
        return False
    now_text = serialize_datetime(occurred_at) if isinstance(occurred_at, datetime) else occurred_at
    connection.execute(
        """
        INSERT INTO codex_entries(
            player_id, entry_key, category, first_seen_operation_id, first_seen_at,
            payload_json, last_seen_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(player_id, entry_key) DO UPDATE SET last_seen_at = excluded.last_seen_at
        WHERE codex_entries.first_seen_operation_id <> excluded.first_seen_operation_id
        """,
        (
            player_id,
            entry_key,
            category,
            operation_id,
            now_text,
            json.dumps(_discovery_payload(snapshot), ensure_ascii=False, sort_keys=True),
            now_text,
        ),
    )
    return True


def record_material_discoveries(
    connection: sqlite3.Connection,
    *,
    player_id: int,
    operation_id: str,
    occurred_at: datetime | str,
    reward: dict[str, int],
    snapshot: dict[str, Any] | None = None,
    content: ContentBundle | None = None,
) -> None:
    for item_key, quantity in reward.items():
        if not item_key.startswith("item.") or int(quantity) <= 0:
            continue
        suffix = item_key.split(".")[-1]
        record_codex_discovery(
            connection,
            player_id=player_id,
            entry_key=f"codex.material.{suffix}",
            operation_id=operation_id,
            occurred_at=occurred_at,
            snapshot=snapshot,
            content=content,
        )


def record_location_discovery(
    connection: sqlite3.Connection,
    *,
    player_id: int,
    location_key: str,
    operation_id: str,
    occurred_at: datetime | str,
    snapshot: dict[str, Any] | None = None,
    content: ContentBundle | None = None,
) -> bool:
    bundle = content or bundled_content()
    location = bundle.get("location", location_key)
    entry_key = location.get("codex_entry_key") if location is not None else None
    if not isinstance(entry_key, str):
        return False
    return record_codex_discovery(
        connection,
        player_id=player_id,
        entry_key=entry_key,
        operation_id=operation_id,
        occurred_at=occurred_at,
        snapshot=snapshot,
        content=bundle,
    )


__all__ = ["record_codex_discovery", "record_location_discovery", "record_material_discoveries"]
