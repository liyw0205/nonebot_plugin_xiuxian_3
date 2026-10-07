from __future__ import annotations

import json
import sqlite3


def set_travel_end_at(connection: sqlite3.Connection, session_id: str, ends_at: str) -> None:
    operation_id = connection.execute(
        "SELECT operation_id FROM travel_sessions WHERE session_id=?", (session_id,)
    ).fetchone()[0]
    result_json = connection.execute(
        "SELECT result_json FROM operations WHERE operation_id=?", (operation_id,)
    ).fetchone()[0]
    result = json.loads(result_json)
    result["ends_at"] = ends_at
    connection.execute(
        "UPDATE operations SET result_json=? WHERE operation_id=?",
        (json.dumps(result, ensure_ascii=False, sort_keys=True), operation_id),
    )
    connection.execute(
        "UPDATE travel_sessions SET ends_at=? WHERE session_id=?", (ends_at, session_id)
    )
