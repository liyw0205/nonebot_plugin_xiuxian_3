"""Transactional projections emitted by settled arena matches.

Arena combat owns the match and replay tables.  This module owns the
player-facing knowledge and reputation projections so those concerns do not
grow the arena repositories further.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Mapping
from typing import Any

from .arena_federation import ensure_identity_route, record_settlement_audit


CONTENT_VERSION = "content-0.6"
RULE_VERSION = "arena-projection-0.1.0"
ARENA_LOCATION_KEY = "xuantian.new_town"
ARENA_LOCAL_REPUTATION_KEY = f"local.{ARENA_LOCATION_KEY}"


def project_arena_result(
    connection: sqlite3.Connection,
    *,
    match_id: str,
    operation_id: str,
    mode_key: str,
    outcome: str,
    score_counted: bool,
    settled_at: str,
    participants: Iterable[Mapping[str, Any]],
    request_id: str = "",
    elapsed_ms: int = 0,
) -> dict[str, Any]:
    """Project one settled match for every participant in the same transaction.

    ``arena_projection_events`` is the projection ledger.  Its participant
    uniqueness makes recovery/replay safe even if a caller invokes this helper
    again after the match itself has already been persisted.
    """

    if outcome not in {"challenger_won", "defender_won", "draw"}:
        raise ValueError("invalid arena outcome")
    normalized = [
        {"player_id": int(item["player_id"]), "side": str(item["side"])}
        for item in participants
    ]
    if not normalized or len({item["player_id"] for item in normalized}) != len(normalized):
        raise ValueError("arena projection requires distinct participants")
    if any(item["side"] not in {"challenger", "defender"} for item in normalized):
        raise ValueError("invalid arena participant side")

    projected: list[dict[str, Any]] = []
    for participant in normalized:
        player_id = participant["player_id"]
        side = participant["side"]
        won = (outcome == "challenger_won" and side == "challenger") or (
            outcome == "defender_won" and side == "defender"
        )
        result_key = "victory" if won else "defeat" if outcome != "draw" else "draw"
        reputation_delta = 1 if score_counted and won else 0
        entry_keys = (
            f"codex.challenge.arena.{mode_key}.participation",
            f"codex.challenge.arena.{mode_key}.{result_key}",
        )
        reputation = connection.execute(
            "SELECT local_json, service_reputation FROM player_reputations WHERE player_id = ?",
            (player_id,),
        ).fetchone()
        local = _json_map(reputation["local_json"]) if reputation is not None else {}
        before = int(local.get(ARENA_LOCAL_REPUTATION_KEY, 0))
        after = min(1000, max(0, before + reputation_delta))
        payload = {
            "match_id": match_id,
            "mode_key": mode_key,
            "side": side,
            "outcome": outcome,
            "score_counted": bool(score_counted),
            "reputation_delta": reputation_delta,
            "reputation_before": before,
            "reputation_after": after,
            "entry_keys": entry_keys,
            "content_version": CONTENT_VERSION,
            "rule_version": RULE_VERSION,
            "request_id": request_id,
            "operation_id": operation_id,
            "match_id": match_id,
            "player_id": player_id,
            "elapsed_ms": max(0, int(elapsed_ms)),
            "result": outcome,
        }
        ensure_identity_route(connection, player_id=player_id, now_text=settled_at)
        existing = connection.execute(
            "SELECT reputation_delta, payload_json FROM arena_projection_events "
            "WHERE match_id = ? AND player_id = ?",
            (match_id, player_id),
        ).fetchone()
        if existing is not None:
            projected.append(_json_map(existing["payload_json"]))
            continue

        for entry_key in entry_keys:
            connection.execute(
                """
                INSERT INTO codex_entries(
                    player_id, entry_key, category, first_seen_operation_id,
                    first_seen_at, payload_json, content_version, rule_version,
                    last_seen_at
                ) VALUES (?, ?, 'challenge', ?, ?, ?, ?, ?, ?)
                ON CONFLICT(player_id, entry_key) DO UPDATE SET last_seen_at = excluded.last_seen_at
                """,
                (
                    player_id,
                    entry_key,
                    operation_id,
                    settled_at,
                    json.dumps(payload, ensure_ascii=False, sort_keys=True),
                    CONTENT_VERSION,
                    RULE_VERSION,
                    settled_at,
                ),
            )
        for event_key in (
            "arena.participation",
            f"arena.result.{result_key}",
        ):
            connection.execute(
                """
                INSERT OR IGNORE INTO activity_events(
                    player_id, event_key, source_operation_id, occurred_at, payload_json
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    player_id,
                    event_key,
                    operation_id,
                    settled_at,
                    json.dumps(payload, ensure_ascii=False, sort_keys=True),
                ),
            )

        connection.execute(
            """
            INSERT INTO player_reputations(player_id, local_json, service_reputation, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(player_id) DO UPDATE SET local_json = excluded.local_json,
                service_reputation = excluded.service_reputation, updated_at = excluded.updated_at
            """,
            (
                player_id,
                json.dumps({**local, ARENA_LOCAL_REPUTATION_KEY: after}, ensure_ascii=False, sort_keys=True),
                int(reputation["service_reputation"]) if reputation is not None else 0,
                settled_at,
            ),
        )
        connection.execute(
            """
            INSERT INTO arena_projection_events(
                match_id, player_id, operation_id, mode_key, side, outcome,
                reputation_delta, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                match_id,
                player_id,
                operation_id,
                mode_key,
                side,
                outcome,
                reputation_delta,
                json.dumps(payload, ensure_ascii=False, sort_keys=True),
                settled_at,
            ),
        )
        record_settlement_audit(
            connection,
            match_id=match_id,
            operation_id=operation_id,
            player_id=player_id,
            mode_key=mode_key,
            outcome=outcome,
            payload=payload,
            created_at=settled_at,
            request_id=request_id,
        )
        projected.append(payload)
    return {
        "match_id": match_id,
        "mode_key": mode_key,
        "participants": projected,
        "content_version": CONTENT_VERSION,
        "rule_version": RULE_VERSION,
    }


def _json_map(raw: Any) -> dict[str, Any]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return {}
    return dict(raw) if isinstance(raw, Mapping) else {}


__all__ = [
    "ARENA_LOCAL_REPUTATION_KEY",
    "ARENA_LOCATION_KEY",
    "CONTENT_VERSION",
    "RULE_VERSION",
    "project_arena_result",
]
