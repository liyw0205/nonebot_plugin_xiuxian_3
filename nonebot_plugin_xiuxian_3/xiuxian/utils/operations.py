"""Small helpers for reading immutable operation results inside a transaction."""

from __future__ import annotations

import json
from typing import Any


def player_operation(
    connection: Any,
    operation_id: str,
    *,
    player_id: int,
) -> tuple[str, dict[str, Any]] | None:
    """Return an operation owned by ``player_id`` and its JSON result.

    A source operation is evidence only when its ledger row, owner and JSON
    result can all be read from the same transaction. Malformed or foreign
    rows are treated as unavailable so callers cannot use a guessed ID.
    """

    row = connection.execute(
        "SELECT operation_name, player_id, result_json FROM operations WHERE operation_id = ?",
        (str(operation_id),),
    ).fetchone()
    if row is None or int(row["player_id"]) != int(player_id):
        return None
    try:
        payload = json.loads(str(row["result_json"]))
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return str(row["operation_name"]), payload


__all__ = ["player_operation"]
