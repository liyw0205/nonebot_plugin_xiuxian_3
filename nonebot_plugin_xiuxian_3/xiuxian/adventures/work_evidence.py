"""Read owned work receipts before using them as story progress."""

from __future__ import annotations

from datetime import datetime

from ..utils.json_cache import decode_json_strict


def has_full_idle_claim(connection, player_id, route_key, baseline, operation_baseline, started_at):
    from ..specials.idle_repository import IdleRepositoryMixin

    player = connection.execute("SELECT player_id FROM players WHERE id=?", (player_id,)).fetchone()
    assignments = connection.execute(
        "SELECT * FROM idle_assignments WHERE player_id=? AND route_key=? "
        "AND status='claimed' AND starts_at>=? AND id>?",
        (player_id, route_key, started_at, baseline),
    ).fetchall()
    for assignment in assignments:
        receipts = []
        for field, name in (("operation_id", "specials.assign_idle"), ("claim_operation_id", "specials.claim_idle")):
            receipt = connection.execute(
                "SELECT rowid, result_json FROM operations WHERE operation_id=? AND player_id=? AND operation_name=?",
                (assignment[field], player_id, name),
            ).fetchone()
            if receipt is None:
                raise ValueError("mainline idle work lacks owned receipts")
            payload = decode_json_strict(receipt["result_json"])
            if (
                not isinstance(payload, dict) or not isinstance(payload.get("player"), dict)
                or payload["player"].get("player_id") != player["player_id"]
                or payload.get("assignment_id") != assignment["assignment_id"]
                or payload.get("route_key") != route_key
            ):
                raise ValueError("mainline idle receipt disagrees with its assignment")
            receipts.append((receipt["rowid"], payload))
        start_rowid, start = receipts[0]
        claim_rowid, claim = receipts[1]
        snapshot = decode_json_strict(assignment["snapshot_json"])
        result = decode_json_strict(assignment["result_json"])
        if (
            start_rowid <= operation_baseline or claim_rowid <= start_rowid
            or start.get("status") != "running" or claim.get("status") != "claimed"
            or start.get("cost") != decode_json_strict(assignment["cost_json"])
            or any(start.get(key) != assignment[key] for key in ("starts_at", "claim_at", "max_claim_at", "cancel_until"))
            or not isinstance(snapshot, dict) or snapshot.get("route_key") != route_key
            or snapshot.get("location_key") != start["player"].get("location_key")
            or not isinstance(result, dict) or result.get("fallback") is not False
            or claim.get("fallback") is not False or not isinstance(claim.get("reward"), dict)
            or {key: result.get(key) for key in claim["reward"]} != claim["reward"]
        ):
            raise ValueError("mainline full idle evidence is inconsistent")
        if not (
            datetime.fromisoformat(assignment["claim_at"])
            <= datetime.fromisoformat(result["claimed_at"])
            <= datetime.fromisoformat(assignment["max_claim_at"])
        ):
            raise ValueError("mainline idle claim is outside its full window")
        full_reward = IdleRepositoryMixin._required_idle_reward(snapshot.get("full_reward"), "story full")
        actual_reward = IdleRepositoryMixin._required_idle_reward(claim["reward"], "story receipt")
        if (
            {key: value for key, value in full_reward.items() if not key.startswith("local.")}
            != {key: value for key, value in actual_reward.items() if not key.startswith("local.")}
            or any(value > full_reward.get(key, 0) for key, value in actual_reward.items() if key.startswith("local."))
        ):
            raise ValueError("mainline idle reward disagrees with its frozen outcome")
        return True
    return False


def completed_production_rowid(connection, player_id, objective, baseline, operation_baseline, started_at):
    from ..persistence.sqlite_repository import SQLitePlayerRepository

    player = connection.execute("SELECT * FROM players WHERE id=?", (player_id,)).fetchone()
    orders = connection.execute(
        "SELECT * FROM production_orders WHERE player_id=? AND recipe_key=? "
        "AND id>? AND starts_at>=? AND status='completed' ORDER BY id",
        (player_id, objective["recipe_key"], baseline, started_at),
    ).fetchall()
    for order in orders:
        start = connection.execute(
            "SELECT rowid FROM operations WHERE operation_id=? AND player_id=? AND operation_name='production.start'",
            (order["operation_id"], player_id),
        ).fetchone()
        receipts = connection.execute(
            "SELECT rowid, * FROM operations WHERE player_id=? "
            "AND operation_name IN ('production.complete','production.recover') "
            "AND json_extract(result_json, '$.order_id')=? ORDER BY rowid",
            (player_id, order["order_id"]),
        ).fetchall()
        if start is None or not receipts:
            raise ValueError("mainline production lacks owned receipts")
        for receipt in receipts:
            if start["rowid"] <= operation_baseline or receipt["rowid"] <= start["rowid"]:
                raise ValueError("mainline production receipt order is invalid")
            payload = decode_json_strict(receipt["result_json"])
            SQLitePlayerRepository._validate_production_settlement_replay(
                connection, payload, operation_id=receipt["operation_id"],
                operation_name=receipt["operation_name"], platform=player["platform"],
                platform_user_id=player["platform_user_id"],
            )
            quantity = payload["outputs"].get(objective["item_key"])
            if payload["success"] is True and type(quantity) is int and quantity >= 1:
                return int(receipt["rowid"])
    return None
