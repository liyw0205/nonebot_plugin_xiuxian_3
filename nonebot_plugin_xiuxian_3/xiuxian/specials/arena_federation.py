"""Pre-cross-server identity, season and audit primitives.

These helpers deliberately do not match or transfer players between shards.
They only preserve the immutable inputs that a future federation service will
need to reconcile.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from typing import Any


LOCAL_SHARD_KEY = "local"
FEDERATION_RULE_VERSION = "arena-federation-0.1.0"


def ensure_identity_route(
    connection: sqlite3.Connection,
    *,
    player_id: int,
    now_text: str,
    shard_key: str = LOCAL_SHARD_KEY,
) -> dict[str, str]:
    """Materialize a private platform identity route for one player."""

    player = connection.execute(
        "SELECT platform, platform_user_id, player_id FROM players WHERE id = ?",
        (player_id,),
    ).fetchone()
    if player is None:
        raise ValueError("arena identity route requires an existing player")
    route_key = f"arena.identity:{shard_key}:{player_id}"
    connection.execute(
        """
        INSERT INTO arena_identity_routes(
            route_key, player_id, shard_key, platform, platform_user_id,
            status, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, 'active', ?, ?)
        ON CONFLICT(player_id) DO UPDATE SET status = 'active', updated_at = excluded.updated_at
        """,
        (
            route_key,
            player_id,
            shard_key,
            str(player["platform"]),
            str(player["platform_user_id"]),
            now_text,
            now_text,
        ),
    )
    return {
        "route_key": route_key,
        "shard_key": shard_key,
        "stable_player_id": str(player["player_id"]),
    }


def record_settlement_audit(
    connection: sqlite3.Connection,
    *,
    match_id: str,
    operation_id: str,
    player_id: int,
    mode_key: str,
    outcome: str,
    payload: Mapping[str, Any],
    created_at: str,
) -> None:
    """Append one idempotent settlement audit event for a participant."""

    connection.execute(
        """
        INSERT OR IGNORE INTO arena_audit_events(
            event_key, match_id, operation_id, player_id, mode_key, outcome,
            payload_json, created_at
        ) VALUES ('arena.settlement', ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            match_id,
            operation_id,
            player_id,
            mode_key,
            outcome,
            json.dumps(dict(payload), ensure_ascii=False, sort_keys=True),
            created_at,
        ),
    )


def freeze_arena_season_snapshot(
    connection: sqlite3.Connection,
    *,
    season_key: str,
    frozen_at: str,
    shard_key: str = LOCAL_SHARD_KEY,
) -> int:
    """Freeze current local arena standings for later cross-server exchange."""

    season_key = str(season_key).strip()
    if not season_key:
        raise ValueError("season_key is required")
    rows = connection.execute(
        "SELECT id, arena_rating, arena_wins, arena_losses, arena_draws FROM players WHERE status = 'active'"
    ).fetchall()
    for row in rows:
        payload = {
            "player_id": int(row["id"]),
            "arena_rating": int(row["arena_rating"]),
            "arena_wins": int(row["arena_wins"]),
            "arena_losses": int(row["arena_losses"]),
            "arena_draws": int(row["arena_draws"]),
            "rule_version": FEDERATION_RULE_VERSION,
        }
        connection.execute(
            """
            INSERT OR IGNORE INTO arena_season_snapshots(
                season_key, shard_key, player_id, rating, wins, losses, draws,
                snapshot_json, frozen_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                season_key,
                shard_key,
                row["id"],
                row["arena_rating"],
                row["arena_wins"],
                row["arena_losses"],
                row["arena_draws"],
                json.dumps(payload, ensure_ascii=False, sort_keys=True),
                frozen_at,
                frozen_at,
            ),
        )
    return int(
        connection.execute(
            "SELECT COUNT(*) FROM arena_season_snapshots WHERE season_key = ? AND shard_key = ?",
            (season_key, shard_key),
        ).fetchone()[0]
    )


__all__ = [
    "FEDERATION_RULE_VERSION",
    "LOCAL_SHARD_KEY",
    "ensure_identity_route",
    "freeze_arena_season_snapshot",
    "record_settlement_audit",
]
