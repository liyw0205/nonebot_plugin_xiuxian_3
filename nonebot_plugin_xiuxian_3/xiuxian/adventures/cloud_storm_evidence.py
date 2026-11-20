"""Replay owned storm transitions when checking a fresh boat-trial receipt."""

from __future__ import annotations

from datetime import datetime, timedelta

from ..exploration.rules import (
    CLOUD_BOAT_STORM_CHANCE_BP, CLOUD_BOAT_STORM_WAIT_SECONDS,
    cloud_boat_storm_payment_reward, cloud_boat_storm_roll_bp,
)
from ..utils.json_cache import decode_json_strict


def cloud_storm_evidence(session, initial, snapshot, result, receipts, identity):
    from ..persistence.sqlite_repository import SQLitePlayerRepository

    expected_end = datetime.fromisoformat(initial["ends_at"])
    deadline = None
    resolved = False
    terminal_choice = None
    expected_reward = None
    if (
        type(snapshot.get("storm_roll_bp")) is not int
        or snapshot["storm_roll_bp"] != cloud_boat_storm_roll_bp(session["operation_id"])
        or type(snapshot.get("storm_chance_bp")) is not int
        or snapshot["storm_chance_bp"] != CLOUD_BOAT_STORM_CHANCE_BP
    ):
        raise ValueError("cloud trial storm snapshot disagrees with its seed")
    storm_hit = snapshot["storm_roll_bp"] < snapshot["storm_chance_bp"]
    for receipt in receipts:
        payload = decode_json_strict(receipt["result_json"])
        if not isinstance(payload, dict):
            raise ValueError("cloud trial receipt must be an object")
        status = payload.get("status")
        at = datetime.fromisoformat(receipt["created_at"])
        if status == "storm_pending":
            if (
                not storm_hit or resolved or receipt["operation_name"] != "exploration.settle"
                or at < expected_end or payload.get("storm_pending") is not True
                or payload.get("storm_preview") != snapshot["frozen_result"]
            ):
                raise ValueError("cloud trial storm prompt disagrees with its source")
            expected_deadline = deadline or at + timedelta(seconds=CLOUD_BOAT_STORM_WAIT_SECONDS)
            if datetime.fromisoformat(payload["storm_deadline"]) != expected_deadline:
                raise ValueError("cloud trial storm deadline is inconsistent")
            deadline = expected_deadline
        elif status == "running" and payload.get("storm_choice") == "wait":
            if deadline is None or resolved:
                raise ValueError("cloud trial waiting lacks a storm prompt")
            if receipt["operation_name"] == "exploration.settle":
                if at < deadline:
                    raise ValueError("cloud trial default wait precedes its deadline")
            elif receipt["operation_name"] == "exploration.storm":
                wait_hash = SQLitePlayerRepository._request_hash("exploration.storm", {**identity, "choice": "wait"})
                if at < deadline and receipt["request_hash"] != wait_hash:
                    raise ValueError("cloud trial waiting differs from its request")
            else:
                raise ValueError("cloud trial waiting has an invalid operation")
            expected_end = at + timedelta(seconds=CLOUD_BOAT_STORM_WAIT_SECONDS)
            if payload.get("storm_pending") is not False or datetime.fromisoformat(payload["storm_deadline"]) != expected_end:
                raise ValueError("cloud trial waiting end is inconsistent")
            resolved = True
            deadline = None
        elif status == "running":
            raise ValueError("cloud trial running receipt lacks its wait choice")
        elif receipt["operation_name"] == "exploration.storm":
            choice = payload.get("storm_choice")
            if deadline is None or resolved or status != "settled" or choice not in {"pay", "turn_back"} or at >= deadline:
                raise ValueError("cloud trial terminal choice lacks a live storm prompt")
            if receipt["request_hash"] != SQLitePlayerRepository._request_hash("exploration.storm", {**identity, "choice": choice}):
                raise ValueError("cloud trial terminal choice differs from its request")
            if (
                result.get("storm_resolved") is not True or result.get("storm_pending") is not False
                or result.get("storm_choice") != choice or datetime.fromisoformat(result["settled_at"]) != at
            ):
                raise ValueError("cloud trial terminal choice disagrees with its session")
            if choice == "pay":
                expected_reward = cloud_boat_storm_payment_reward(snapshot["frozen_result"])
            else:
                reward = result.get("result")
                if (
                    not isinstance(reward, dict) or set(reward) != {"stamina_refund"}
                    or type(reward["stamina_refund"]) is not int
                    or not 0 <= reward["stamina_refund"] <= session["stamina_cost"] // 2
                ):
                    raise ValueError("cloud trial return reward is invalid")
                expected_reward = reward
            terminal_choice = choice
            resolved = True
            deadline = None
    if expected_end != datetime.fromisoformat(session["ends_at"]) or deadline is not None:
        raise ValueError("cloud trial end lacks its matching storm transition")
    if storm_hit and not resolved:
        raise ValueError("cloud trial lacks its owned storm resolution")
    return expected_reward, terminal_choice
