"""Small helpers for reading immutable operation results inside a transaction."""

from __future__ import annotations

import json
from typing import Any

from ..persistence.errors import OperationConflictError, OperationResultMalformedError
from .json_cache import decode_json_strict


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


def operation_replay(
    connection: Any,
    operation_id: str,
    operation_name: str,
    request_hash: str,
    *,
    player_id: int | None = None,
) -> dict[str, Any] | None:
    """Load one operation result when its input, and optionally its owner, match."""

    row = connection.execute(
        "SELECT operation_name, player_id, request_hash, result_json "
        "FROM operations WHERE operation_id = ?",
        (str(operation_id),),
    ).fetchone()
    if row is None:
        return None
    if player_id is not None and int(row["player_id"]) != int(player_id):
        raise OperationConflictError("operation belongs to another player")
    if str(row["operation_name"]) != operation_name or str(row["request_hash"]) != request_hash:
        raise OperationConflictError("operation input differs from its original request")
    try:
        payload = decode_json_strict(str(row["result_json"]))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise OperationResultMalformedError("operation result is malformed") from exc
    if not isinstance(payload, dict):
        raise OperationResultMalformedError("operation result must be an object")
    return payload


def record_operation(
    connection: Any,
    operation_id: str,
    operation_name: str,
    player_id: int,
    request_hash: str,
    payload: dict[str, Any],
    created_at: str,
) -> None:
    """Persist a JSON operation result in the caller's transaction."""

    if not isinstance(payload, dict):
        raise ValueError("operation payload must be an object")
    connection.execute(
        "INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            str(operation_id),
            str(operation_name),
            int(player_id),
            str(request_hash),
            json.dumps(payload, ensure_ascii=False, sort_keys=True),
            str(created_at),
        ),
    )


__all__ = ["operation_replay", "player_operation", "record_operation"]
