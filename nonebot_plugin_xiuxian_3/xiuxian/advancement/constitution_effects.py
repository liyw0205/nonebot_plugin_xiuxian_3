"""Read the selected constitution's frozen effect for a player."""

from __future__ import annotations

import json
import sqlite3
from typing import Any


def constitution_effect_snapshot(connection: sqlite3.Connection, player_id: int) -> dict[str, Any]:
    row = connection.execute(
        "SELECT snapshot_json FROM constitution_profiles WHERE player_id = ? LIMIT 1",
        (player_id,),
    ).fetchone()
    if row is None:
        return {}
    try:
        snapshot = json.loads(str(row["snapshot_json"]))
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("constitution profile snapshot is invalid JSON") from exc
    effect = snapshot.get("effect") if isinstance(snapshot, dict) else None
    if not isinstance(effect, dict):
        raise ValueError("constitution profile snapshot is missing its effect")
    effect_type = effect.get("type")
    value = effect.get("value")
    if (
        not isinstance(effect_type, str)
        or not effect_type
        or isinstance(value, bool)
        or not isinstance(value, int)
        or value < 0
    ):
        raise ValueError("constitution profile snapshot has an invalid effect")
    return {"type": effect_type, "value": value}


__all__ = ["constitution_effect_snapshot"]
