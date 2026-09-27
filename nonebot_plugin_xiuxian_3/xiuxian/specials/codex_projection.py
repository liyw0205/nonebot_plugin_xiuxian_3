"""Shared, transaction-local projection of verified discoveries."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Any

from ...contracts import serialize_datetime
from .codex_rules import CONTENT_VERSION, RULE_VERSION, category_for_entry


def record_codex_discovery(
    connection: sqlite3.Connection,
    *,
    player_id: int,
    entry_key: str,
    operation_id: str,
    occurred_at: datetime | str,
    snapshot: dict[str, Any] | None = None,
    content_version: str = CONTENT_VERSION,
    rule_version: str = RULE_VERSION,
) -> bool:
    category = category_for_entry(entry_key)
    if category is None:
        return False
    now_text = serialize_datetime(occurred_at) if isinstance(occurred_at, datetime) else occurred_at
    connection.execute(
        """
        INSERT INTO codex_entries(
            player_id, entry_key, category, first_seen_operation_id, first_seen_at,
            payload_json, content_version, rule_version, last_seen_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(player_id, entry_key) DO UPDATE SET last_seen_at = excluded.last_seen_at
        WHERE codex_entries.first_seen_operation_id <> excluded.first_seen_operation_id
        """,
        (
            player_id,
            entry_key,
            category,
            operation_id,
            now_text,
            json.dumps(snapshot or {}, ensure_ascii=False, sort_keys=True),
            content_version,
            rule_version,
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
        )


__all__ = ["record_codex_discovery", "record_material_discoveries"]
