"""Finite field stocks with elapsed-time recovery and atomic extraction/upkeep."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

from ...contracts import serialize_datetime
from ..content import bundled_content
from ..utils.json_cache import decode_json_strict
from ..utils.operations import operation_replay, record_operation
from ..utils.player import grant_player_state
from .deposit_rules import deposit_definitions, validate_deposit
from .survey_repository import SurveyRequirementError, _dump
from .survey_rules import validate_survey


def project_stock(definition, state, now):
    state = dict(state)
    regen = datetime.fromisoformat(state["regenerates_at"])
    if now >= regen:
        ticks = int((now - regen).total_seconds()) // definition["regen_seconds"] + 1
        state["stock"] = min(definition["capacity"], state["stock"] + ticks * definition["regen_units"])
        state["regenerates_at"] = serialize_datetime(regen + timedelta(seconds=ticks * definition["regen_seconds"]))
    if state["maintenance_date"] != now.date().isoformat():
        state["maintenance_date"], state["maintenance_used"] = now.date().isoformat(), 0
    return state


class DepositRepositoryMixin:
    @staticmethod
    def _deposit_state(row):
        return {key: row[key] for key in ("deposit_key", "stock", "regenerates_at", "ready_at", "maintenance_date", "maintenance_used")}

    @staticmethod
    def _deposit_payload(payload):
        if not isinstance(payload, dict):
            raise ValueError("deposit receipt is malformed")
        frozen = payload.get("snapshot")
        if not isinstance(frozen, dict) or set(frozen) != {"definition", "site"}:
            raise ValueError("deposit snapshot is malformed")
        definition, site = validate_deposit(frozen["definition"]), validate_survey(frozen["site"])
        state = payload.get("state")
        if (definition["survey_key"] != site["key"] or not isinstance(state, dict)
                or set(state) != {"deposit_key", "stock", "regenerates_at", "ready_at", "maintenance_date", "maintenance_used"}
                or state["deposit_key"] != definition["key"]
                or type(state["stock"]) is not int or not 0 <= state["stock"] <= definition["capacity"]
                or type(state["maintenance_used"]) is not int or not 0 <= state["maintenance_used"] <= definition["maintenance"]["daily_limit"]):
            raise ValueError("deposit state is malformed")
        for field in ("regenerates_at", "ready_at"):
            if not isinstance(state[field], str) or datetime.fromisoformat(state[field]).tzinfo is None:
                raise ValueError("deposit time is malformed")
        if not isinstance(state["maintenance_date"], str):
            raise ValueError("deposit maintenance date is malformed")
        datetime.strptime(state["maintenance_date"], "%Y-%m-%d")
        for field in ("costs", "reward"):
            if not isinstance(payload.get(field), dict) or any(not isinstance(k, str) or type(n) is not int or n <= 0
                                                              for k, n in payload[field].items()):
                raise ValueError("deposit receipt amounts are malformed")
        before = payload.get("stock_before")
        if type(before) is not int or not 0 <= before <= definition["capacity"]:
            raise ValueError("deposit receipt stock evidence is malformed")
        if payload.get("action") == "extract":
            option = next((p for p in definition["plans"] if p["key"] == payload.get("plan_key")), None)
            if option is None or before < option["stock_cost"] or state["stock"] != before - option["stock_cost"]:
                raise ValueError("deposit extraction stock evidence is malformed")
            reward = option["rewards"]
        elif payload.get("action") == "maintain" and payload.get("plan_key") is None:
            option, reward = definition["maintenance"], {}
            if before == definition["capacity"] or state["stock"] != min(definition["capacity"], before + option["restore_units"]):
                raise ValueError("deposit maintenance stock evidence is malformed")
        else:
            raise ValueError("deposit receipt action is invalid")
        if payload["costs"] != option["costs"] or payload["reward"] != reward or payload.get("text") != option["text"]:
            raise ValueError("deposit receipt costs/rewards disagree with its frozen plan")
        return payload

    def _deposit_evidence(self, connection, row):
        receipts = []
        for key in ("first_operation_id", "last_operation_id"):
            receipt = connection.execute("SELECT * FROM operations WHERE operation_id=? AND player_id=?",
                                         (row[key], row["player_id"])).fetchone()
            if receipt is None or receipt["operation_name"] not in {"deposit.extract", "deposit.maintain"}:
                raise ValueError("deposit operation evidence is missing")
            payload = self._deposit_payload(decode_json_strict(receipt["result_json"]))
            if receipt["operation_name"] != "deposit." + payload["action"]:
                raise ValueError("deposit operation kind disagrees with its receipt")
            receipts.append(payload)
        frozen = decode_json_strict(row["snapshot_json"])
        if receipts[0]["snapshot"] != frozen or receipts[1]["snapshot"] != frozen or receipts[1]["state"] != self._deposit_state(row):
            raise ValueError("deposit projection disagrees with its operation evidence")
        return frozen

    async def deposit_command(self, *, platform, platform_user_id, action, selector="", plan="", operation_id=""):
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._deposit_command_once, platform, platform_user_id,
                                           action, selector, plan, operation_id)

    def _deposit_command_once(self, platform, user, action, selector, plan, operation_id):
        bundle = self.content or bundled_content()
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            if action != "preview":
                connection.execute("BEGIN IMMEDIATE")
            player = self._require_player(connection, platform, user, writable=action != "preview")
            name = "deposit." + action
            request_hash = self._request_hash(name, {"platform": platform, "user": user, "selector": selector, "plan": plan})
            if action != "preview":
                replay = operation_replay(connection, operation_id, name, request_hash, player_id=int(player["id"]))
                if replay is not None:
                    self._deposit_payload(replay)
                    if replay["action"] != action:
                        raise ValueError("deposit replay action disagrees with receipt")
                    return {**replay, "idempotent_replay": True}
            definitions = deposit_definitions(bundle)
            rows = connection.execute("SELECT * FROM field_deposits WHERE player_id=?", (player["id"],)).fetchall()
            saved = {}
            for row in rows:
                saved[row["deposit_key"]] = (row, self._deposit_evidence(connection, row))
            candidates = {key: {"definition": value, "site": None} for key, value in definitions.items()
                          if value["status"] in {"active", "open"}}
            candidates.update({key: frozen for key, (_, frozen) in saved.items()})
            if selector:
                candidates = {key: frozen for key, frozen in candidates.items()
                              if selector in {key, frozen["definition"]["name"]}}
            if not candidates:
                raise SurveyRequirementError("没有找到资源脉，先用资源脉预览查阅开放地点。")
            entries = []
            for key, frozen in candidates.items():
                definition = frozen["definition"]
                discovery = connection.execute("SELECT * FROM field_surveys WHERE player_id=? AND site_key=?",
                                               (player["id"], definition["survey_key"])).fetchone()
                unlocked = discovery is not None and discovery["status"] == "completed"
                site = self._survey_evidence(connection, discovery)["site"] if unlocked else None
                current = definitions.get(key)
                opened = current is not None and current["status"] in {"active", "open"}
                state = (self._deposit_state(saved[key][0]) if key in saved else {
                    "deposit_key": key, "stock": definition["capacity"],
                    "regenerates_at": serialize_datetime(now + timedelta(seconds=definition["regen_seconds"])),
                    "ready_at": now_text, "maintenance_date": now.date().isoformat(), "maintenance_used": 0,
                })
                state = project_stock(definition, state, now)
                frozen = {"definition": definition, "site": saved[key][1]["site"] if key in saved else site}
                if action == "preview":
                    entries.append({"snapshot": frozen, "state": state, "unlocked": unlocked, "opened": opened})
                    continue
                if not unlocked:
                    raise SurveyRequirementError("需先完整勘察此处地貌，再来取材；山野手札可查进度。")
                if not opened:
                    raise SurveyRequirementError("该资源脉暂不开放新取材，已有回执仍可原样重放。")
                self._survey_gate(connection, player, frozen["site"])
                if now < datetime.fromisoformat(state["ready_at"]):
                    raise SurveyRequirementError("资源脉刚受过扰动，等到 " + state["ready_at"] + " 再取材或养护。")
                reward, stock_before = {}, state["stock"]
                if action == "extract":
                    option = next((p for p in definition["plans"] if plan in {p["key"], p["name"]}), None)
                    if option is None:
                        raise SurveyRequirementError("请明确选择留养或强采做法，资源脉预览可查成本与恢复代价。")
                    if state["stock"] < option["stock_cost"]:
                        raise SurveyRequirementError("可采储量不足；等自然恢复，或制作护脉木楔后养护资源脉。")
                    costs, reward, text = option["costs"], option["rewards"], option["text"]
                    state["stock"] -= option["stock_cost"]
                    state["ready_at"] = serialize_datetime(now + timedelta(seconds=option["cooldown_seconds"]))
                    state["regenerates_at"] = serialize_datetime(max(datetime.fromisoformat(state["regenerates_at"]),
                                                                    now + timedelta(seconds=option["recovery_delay"])))
                elif action == "maintain":
                    option = definition["maintenance"]
                    if state["stock"] == definition["capacity"]:
                        raise SurveyRequirementError("储量已经充足，无需消耗物资养护。")
                    if state["maintenance_used"] >= option["daily_limit"]:
                        raise SurveyRequirementError("这处资源脉今日已充分养护，等自然恢复或明日再来。")
                    costs, text = option["costs"], option["text"]
                    state["stock"] = min(definition["capacity"], state["stock"] + option["restore_units"])
                    state["maintenance_used"] += 1
                    state["ready_at"] = serialize_datetime(now + timedelta(seconds=option["cooldown_seconds"]))
                else:
                    raise ValueError("unknown deposit action")
                self._survey_spend(connection, player, costs, now_text)
                if reward:
                    updated = connection.execute("SELECT * FROM players WHERE id=?", (player["id"],)).fetchone()
                    grant_player_state(connection, updated, reward, now_text)
                payload = {"snapshot": frozen, "state": state, "costs": costs, "reward": reward,
                           "text": text, "idempotent_replay": False, "action": action, "stock_before": stock_before,
                           "plan_key": option["key"] if action == "extract" else None}
                record_operation(connection, operation_id, name, int(player["id"]), request_hash, payload, now_text)
                if key not in saved:
                    connection.execute("INSERT INTO field_deposits VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                                       (player["id"], key, operation_id, operation_id, state["stock"], state["regenerates_at"],
                                        state["ready_at"], state["maintenance_date"], state["maintenance_used"], _dump(frozen)))
                else:
                    connection.execute("UPDATE field_deposits SET last_operation_id=?, stock=?, regenerates_at=?, ready_at=?, "
                                       "maintenance_date=?, maintenance_used=? WHERE player_id=? AND deposit_key=?",
                                       (operation_id, state["stock"], state["regenerates_at"], state["ready_at"],
                                        state["maintenance_date"], state["maintenance_used"], player["id"], key))
                return payload
            return {"entries": entries}
