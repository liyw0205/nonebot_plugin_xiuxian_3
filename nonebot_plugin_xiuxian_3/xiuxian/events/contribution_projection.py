"""Transaction-local projection of settled spirit-spring exploration results."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Mapping

from ...contracts import serialize_datetime
from ..content import ContentBundle, ContentError, bundled_content
from .spirit_spring_rules import (
    SPIRIT_SPRING_EVENT_KEY,
    SpiritSpringDefinition,
    spirit_spring_definition,
    spirit_spring_result,
    spirit_spring_snapshot,
    spirit_spring_window,
)


def record_spirit_spring_contribution(
    connection: Any,
    *,
    content: ContentBundle | None,
    player_id: int,
    source_operation_id: str,
    result: Mapping[str, Any],
    occurred_at: datetime,
) -> None:
    """Project one settled exploration result without owning player state."""

    if not source_operation_id:
        return
    source_time = occurred_at.astimezone(timezone.utc)
    event = connection.execute(
        "SELECT * FROM world_event_rounds WHERE event_key = ? AND starts_at <= ? AND ends_at > ? ORDER BY starts_at DESC LIMIT 1",
        (SPIRIT_SPRING_EVENT_KEY, serialize_datetime(source_time), serialize_datetime(source_time)),
    ).fetchone()
    definition: SpiritSpringDefinition
    if event is not None:
        definition = spirit_spring_snapshot(str(event["result_json"]))
    else:
        definition = spirit_spring_definition(content or bundled_content())
    raw_quantity = result.get(definition.source_item_key, 0)
    if isinstance(raw_quantity, bool) or not isinstance(raw_quantity, int) or raw_quantity <= 0:
        return
    if event is None:
        window = spirit_spring_window(definition, source_time)
        if window is None:
            return
        _insert_round(connection, definition, window)
        event = connection.execute(
            "SELECT * FROM world_event_rounds WHERE event_key = ? AND round_id = ?",
            (SPIRIT_SPRING_EVENT_KEY, window[0]),
        ).fetchone()
        if event is None:
            raise ContentError("spirit spring round was not created")
        definition = spirit_spring_snapshot(str(event["result_json"]))
    quantity = raw_quantity * definition.contribution_per_quantity
    current = connection.execute(
        "SELECT contribution FROM world_event_contributions WHERE round_id = ? AND player_id = ?",
        (event["round_id"], player_id),
    ).fetchone()
    current_value = int(current["contribution"]) if current else 0
    applied = max(0, min(quantity, definition.contribution_cap - current_value))
    connection.execute(
        """
        INSERT OR IGNORE INTO world_event_contribution_events(
            round_id, player_id, source_operation_id, quantity, applied_quantity, occurred_at
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            event["round_id"],
            player_id,
            source_operation_id,
            quantity,
            applied,
            serialize_datetime(source_time),
        ),
    )
    if connection.execute("SELECT changes()").fetchone()[0] != 1 or applied <= 0:
        return
    connection.execute(
        """
        INSERT INTO world_event_contributions(round_id, player_id, contribution, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(round_id, player_id) DO UPDATE SET
            contribution = MIN(world_event_contributions.contribution + excluded.contribution, ?),
            updated_at = excluded.updated_at
        """,
        (
            event["round_id"],
            player_id,
            applied,
            serialize_datetime(source_time),
            definition.contribution_cap,
        ),
    )
    total = int(
        connection.execute(
            "SELECT COALESCE(SUM(contribution), 0) AS total FROM world_event_contributions WHERE round_id = ?",
            (event["round_id"],),
        ).fetchone()["total"]
    )
    result_json, _ = spirit_spring_result(str(event["result_json"]))
    result_json = dict(result_json)
    if str(event["status"]) in {"settled", "failed"}:
        result_json["success"] = total >= definition.target_quantity
    connection.execute(
        """
        UPDATE world_event_rounds
        SET status = CASE WHEN status = 'open' THEN 'running' ELSE status END,
            total_contribution = ?, result_json = ?, updated_at = ?
        WHERE round_id = ?
        """,
        (
            total,
            json.dumps(result_json, ensure_ascii=False, sort_keys=True),
            serialize_datetime(source_time),
            event["round_id"],
        ),
    )


def _insert_round(
    connection: Any,
    definition: SpiritSpringDefinition,
    window: tuple[str, datetime, datetime, datetime],
) -> None:
    round_id, starts_at, ends_at, claim_expires_at = window
    connection.execute(
        """
        INSERT OR IGNORE INTO world_event_rounds(
            round_id, event_key, location_key, status, starts_at, ends_at,
            claim_expires_at, target_quantity, total_contribution, result_json,
            created_at, updated_at
        ) VALUES (?, ?, ?, 'open', ?, ?, ?, ?, 0, ?, ?, ?)
        """,
        (
            round_id,
            SPIRIT_SPRING_EVENT_KEY,
            definition.location_key,
            serialize_datetime(starts_at),
            serialize_datetime(ends_at),
            serialize_datetime(claim_expires_at),
            definition.target_quantity,
            json.dumps(
                {"success": False, "configuration": definition.snapshot()},
                ensure_ascii=False,
                sort_keys=True,
            ),
            serialize_datetime(starts_at),
            serialize_datetime(starts_at),
        ),
    )


__all__ = ["record_spirit_spring_contribution"]
