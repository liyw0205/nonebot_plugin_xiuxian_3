"""Owned, post-acceptance exploration evidence for repeatable contracts."""

from __future__ import annotations

from datetime import datetime
from ..utils.json_cache import decode_json_strict


def exploration_completion_count(connection, player_id, mode_key, baseline, deadline):
    rows = connection.execute(
        "SELECT e.*, o.result_json AS start_receipt FROM exploration_sessions e "
        "JOIN operations o ON o.operation_id=e.operation_id AND o.player_id=e.player_id "
        "AND o.operation_name='exploration.start' "
        "WHERE e.player_id=? AND e.mode_key=? AND e.status='settled' AND o.rowid>?",
        (player_id, mode_key, baseline),
    ).fetchall()
    completed = 0
    for row in rows:
        start = decode_json_strict(row["start_receipt"])
        result = decode_json_strict(row["result_json"])
        snapshot = decode_json_strict(row["snapshot_json"])
        if not all(isinstance(value, dict) for value in (start, result, snapshot)):
            raise ValueError("exploration evidence must contain objects")
        if (start.get("exploration_id") != row["exploration_id"]
                or start.get("mode_key") != mode_key or snapshot.get("mode_key") != mode_key
                or start.get("location_key") != row["location_key"]
                or snapshot.get("location_key") != row["location_key"]
                or start.get("random_seed") != row["operation_id"]
                or start.get("patrol") != snapshot.get("patrol")
                or result.get("status") != "settled" or result.get("expired") is not False
                or result.get("battle_pending") is not False
                or not isinstance(result.get("settled_at"), str)):
            raise ValueError("exploration evidence disagrees with its session")
        if datetime.fromisoformat(result["settled_at"]) > datetime.fromisoformat(deadline):
            continue
        reward = result.get("result")
        if not isinstance(reward, dict) or any(not isinstance(k, str) or type(n) is not int or n <= 0 for k, n in reward.items()):
            raise ValueError("exploration evidence reward is invalid")
        if result.get("battle_outcome") not in {None, "won"}:
            continue
        receipts = connection.execute(
            "SELECT result_json FROM operations WHERE player_id=? AND rowid>? "
            "AND operation_name IN ('exploration.settle', 'exploration.settle_combat')",
            (player_id, baseline),
        ).fetchall()
        matched = False
        for receipt in receipts:
            payload = decode_json_strict(receipt["result_json"])
            if not isinstance(payload, dict) or payload.get("exploration_id") != row["exploration_id"]:
                continue
            if (payload.get("status") == "settled" and payload.get("expired") is False
                    and payload.get("battle_pending") is False and payload.get("mode_key") == mode_key
                    and payload.get("result") == reward
                    and payload.get("battle_id") == result.get("battle_id")
                    and payload.get("battle_outcome") == result.get("battle_outcome")):
                matched = True
        if not matched:
            raise ValueError("exploration completion has no matching owned receipt")
        if result.get("battle_id"):
            battle = connection.execute(
                "SELECT result_json FROM battle_sessions WHERE battle_id=? AND player_id=? "
                "AND battle_type='pve.exploration' AND status='settled'",
                (result["battle_id"], player_id),
            ).fetchone()
            if battle is None or decode_json_strict(battle["result_json"]).get("outcome") != "won":
                raise ValueError("exploration completion lacks a winning battle")
        completed += 1
    return completed
