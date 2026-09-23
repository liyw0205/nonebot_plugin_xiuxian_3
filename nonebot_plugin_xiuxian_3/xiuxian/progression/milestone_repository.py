"""Persistence helpers for immutable progression milestone qualifications."""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Mapping

from .milestone_rules import due_milestones
from .models import LayerUnlock


def record_due_milestones(
    connection: sqlite3.Connection,
    *,
    player: Mapping[str, Any],
    source_operation_id: str,
    now_text: str,
) -> tuple[LayerUnlock, ...]:
    """Persist each newly qualified milestone and return its player-facing unlock."""

    player_id = int(player["id"])
    try:
        faction_reputation = json.loads(str(player["faction_reputation_json"]))
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        faction_reputation = {}
    if not isinstance(faction_reputation, dict):
        faction_reputation = {}
    maximum_faction_reputation = max(
        (int(value) for value in faction_reputation.values()),
        default=0,
    )
    domain_level = int(player["domain_level"])
    unlocks: list[LayerUnlock] = []
    for definition in due_milestones(
        realm_key=str(player["realm_key"]),
        realm_layer=int(player["realm_layer"]),
        total_cultivation=int(player["total_cultivation"]),
        maximum_faction_reputation=maximum_faction_reputation,
        domain_level=domain_level,
    ):
        snapshot = {
            "realm_key": str(player["realm_key"]),
            "realm_layer": int(player["realm_layer"]),
            "total_cultivation": int(player["total_cultivation"]),
            "required_realm": definition.required_realm,
            "required_layer": definition.required_layer,
            "required_total_cultivation": definition.required_total_cultivation,
            "maximum_faction_reputation": maximum_faction_reputation,
            "required_max_faction_reputation": definition.required_max_faction_reputation,
            "domain_level": domain_level,
            "required_domain_level": definition.required_domain_level,
        }
        cursor = connection.execute(
            """
            INSERT OR IGNORE INTO progression_milestones(
                player_id, milestone_key, status, source_operation_id, snapshot_json,
                content_version, rule_version, unlocked_at, created_at
            ) VALUES (?, ?, 'unlocked', ?, ?, ?, ?, ?, ?)
            """,
            (
                player_id,
                definition.key,
                source_operation_id,
                json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
                definition.content_version,
                definition.rule_version,
                now_text,
                now_text,
            ),
        )
        if cursor.rowcount:
            unlocks.append(definition.as_unlock())
    return tuple(unlocks)


__all__ = ["record_due_milestones"]
