"""Owned exploration receipts for explicitly strict story objectives."""

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


def has_owned_exploration_reward(connection, player_id, objective, baseline, started_at):
    from ..exploration.repository import ExplorationRepositoryMixin
    from ..persistence.sqlite_repository import SQLitePlayerRepository

    player = connection.execute("SELECT * FROM players WHERE id=?", (player_id,)).fetchone()
    sessions = connection.execute(
        "SELECT * FROM exploration_sessions WHERE player_id=? AND mode_key=? "
        "AND location_key=? AND status='settled' AND starts_at>=? ORDER BY id",
        (player_id, objective["mode_key"], objective["location_key"], started_at),
    ).fetchall()
    strict_reward = ExplorationRepositoryMixin._strict_exploration_reward
    identity = {"platform": player["platform"], "platform_user_id": player["platform_user_id"]}
    for session in sessions:
        start = connection.execute(
            "SELECT rowid, * FROM operations WHERE operation_id=? AND player_id=? "
            "AND operation_name='exploration.start'",
            (session["operation_id"], player_id),
        ).fetchone()
        if start is None:
            raise ValueError("mainline exploration lacks its owned start receipt")
        if start["rowid"] <= baseline:
            continue
        snapshot = decode_json_strict(session["snapshot_json"])
        result = decode_json_strict(session["result_json"])
        initial = decode_json_strict(start["result_json"])
        if not all(isinstance(value, dict) for value in (snapshot, result, initial)):
            raise ValueError("mainline exploration evidence must be objects")
        frozen = strict_reward(snapshot.get("frozen_result"), "story exploration reward")
        actual = strict_reward(result.get("result"), "story exploration result")
        request = {**identity, "mode_key": session["mode_key"]}
        if snapshot.get("patrol"):
            request["approach"] = snapshot["patrol"]["approach"]["key"]
        if (
            start["request_hash"] != SQLitePlayerRepository._request_hash("exploration.start", request)
            or initial.get("status") != "created"
            or snapshot.get("random_seed") != session["operation_id"]
            or initial.get("random_seed") != session["operation_id"]
            or initial.get("starts_at") != session["starts_at"]
            or initial.get("ends_at") != session["ends_at"]
            or initial.get("stamina_cost") != session["stamina_cost"]
            or initial.get("frozen_result") != frozen
            or result.get("frozen_result") != frozen
            or result.get("status") != "settled"
            or result.get("battle_pending") is not False
            or result.get("expired") is not False
            or datetime.fromisoformat(result["settled_at"]) < datetime.fromisoformat(session["ends_at"])
        ):
            raise ValueError("mainline exploration start or frozen result is inconsistent")
        for field in ("mode_key", "location_key", "stamina_cost", "energy_cost", "reward_pool_key", "encounter_enemy_key"):
            expected = session[field] if field in {"mode_key", "location_key", "stamina_cost"} else snapshot.get(field)
            if initial.get(field) != expected or snapshot.get(field) != expected:
                raise ValueError("mainline exploration start disagrees with its snapshot")
        if (
            initial.get("exploration_id") != session["exploration_id"]
            or not isinstance(initial.get("player"), dict)
            or initial["player"].get("player_id") != player["player_id"]
            or initial["player"].get("location_key") != session["location_key"]
        ):
            raise ValueError("mainline exploration start belongs to another source")
        receipts = connection.execute(
            "SELECT rowid, * FROM operations WHERE player_id=? "
            "AND operation_name IN ('exploration.settle','exploration.settle_combat') "
            "AND json_extract(result_json, '$.exploration_id')=? ORDER BY rowid",
            (player_id, session["exploration_id"]),
        ).fetchall()
        settled = False
        for receipt in receipts:
            payload = decode_json_strict(receipt["result_json"])
            if payload.get("status") == "combat_pending":
                continue
            request = dict(identity)
            if receipt["operation_name"] == "exploration.settle_combat":
                request.update(exploration_id=session["exploration_id"], battle_id=result.get("battle_id"))
            if (
                receipt["rowid"] <= start["rowid"]
                or receipt["request_hash"] != SQLitePlayerRepository._request_hash(receipt["operation_name"], request)
                or not isinstance(payload.get("player"), dict)
                or payload["player"].get("player_id") != player["player_id"]
                or any(payload.get(field) != session[field] for field in ("mode_key", "location_key"))
                or payload.get("status") != "settled"
                or payload.get("battle_pending") is not False
                or payload.get("expired") is not False
                or payload.get("battle_id") != result.get("battle_id")
                or payload.get("battle_outcome") != result.get("battle_outcome")
                or strict_reward(payload.get("result"), "story exploration receipt") != actual
            ):
                raise ValueError("mainline exploration settlement disagrees with its source")
            settled = True
        if not settled:
            raise ValueError("mainline exploration lacks an owned settlement receipt")
        outcome = result.get("battle_outcome")
        if outcome not in {None, "won", "lost"} or bool(result.get("battle_id")) != (outcome is not None):
            raise ValueError("mainline exploration battle identity is invalid")
        if result.get("battle_id"):
            battle = connection.execute(
                "SELECT result_json FROM battle_sessions WHERE battle_id=? AND player_id=? "
                "AND battle_type='pve.exploration' AND status='settled'",
                (result["battle_id"], player_id),
            ).fetchone()
            if battle is None or decode_json_strict(battle["result_json"]).get("outcome") != outcome:
                raise ValueError("mainline exploration lacks its matching settled battle")
        expected = frozen if outcome in {None, "won"} else strict_reward(
            snapshot.get("battle_failure_result", {}), "story failed exploration reward",
        )
        if actual != expected:
            raise ValueError("mainline exploration reward disagrees with its frozen outcome")
        if outcome in {None, "won"} and actual.get(objective["item_key"], 0) >= objective["quantity"]:
            return True
    return False
