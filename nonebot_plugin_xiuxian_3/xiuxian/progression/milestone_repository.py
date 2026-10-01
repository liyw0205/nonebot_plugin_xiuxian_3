"""Persistence helpers for immutable progression milestone qualifications."""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Mapping

from .milestone_rules import due_milestones
from .models import LayerUnlock
from ..utils.player import player_integer, player_reputation, player_resource


def record_due_milestones(
    connection: sqlite3.Connection,
    *,
    player: Mapping[str, Any],
    source_operation_id: str,
    now_text: str,
) -> tuple[LayerUnlock, ...]:
    """Persist each newly qualified milestone and return its player-facing unlock."""

    player_id = int(player["id"])
    faction_reputation = player_reputation(player)
    maximum_faction_reputation = max(
        (int(value) for value in faction_reputation.values()),
        default=0,
    )
    domain_level = player_resource(player, "domain_level")
    void_route_count = player_resource(player, "void_route_count")
    unlocks: list[LayerUnlock] = []
    for definition in due_milestones(
        realm_key=str(player["realm_key"]),
        realm_layer=player_integer(player, "realm_layer"),
        total_cultivation=player_resource(player, "total_cultivation"),
        maximum_faction_reputation=maximum_faction_reputation,
        domain_level=domain_level,
        void_route_count=void_route_count,
    ):
        snapshot = {
            "realm_key": str(player["realm_key"]),
            "realm_layer": player_integer(player, "realm_layer"),
            "total_cultivation": player_resource(player, "total_cultivation"),
            "required_realm": definition.required_realm,
            "required_layer": definition.required_layer,
            "required_total_cultivation": definition.required_total_cultivation,
            "maximum_faction_reputation": maximum_faction_reputation,
            "required_max_faction_reputation": definition.required_max_faction_reputation,
            "domain_level": domain_level,
            "required_domain_level": definition.required_domain_level,
            "void_route_count": void_route_count,
            "required_void_route_count": definition.required_void_route_count,
        }
        cursor = connection.execute(
            """
            INSERT OR IGNORE INTO progression_milestones(
                player_id, milestone_key, status, source_operation_id, snapshot_json,
                unlocked_at, created_at
            ) VALUES (?, ?, 'unlocked', ?, ?, ?, ?)
            """,
            (
                player_id,
                definition.key,
                source_operation_id,
                json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
                now_text,
                now_text,
            ),
        )
        if cursor.rowcount:
            unlocks.append(definition.as_unlock())
    return tuple(unlocks)


__all__ = ["record_due_milestones"]
