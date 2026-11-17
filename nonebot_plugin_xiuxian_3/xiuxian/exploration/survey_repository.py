"""Atomic persistent discoveries, observation costs and field retries."""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime, timedelta
from uuid import uuid4

from ...contracts import serialize_datetime
from ..content import bundled_content
from ..utils.assets import player_available_item_amount
from ..utils.json_cache import decode_json_strict
from ..utils.operations import operation_replay, record_operation
from ..utils.player import grant_player_state, player_integer, spend_player_state
from .survey_rules import resolve_survey, survey_definitions, validate_survey


class SurveyRequirementError(ValueError):
    pass


def _dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


class SurveyRepositoryMixin:
    @staticmethod
    def _survey_payload(payload):
        if not isinstance(payload, dict):
            raise ValueError("survey operation payload is malformed")
        site = validate_survey(payload.get("site"))
        state = payload.get("state")
        if (not isinstance(state, dict) or set(state) != {"site_key", "status", "step", "attempts", "ready_at"}
                or state["site_key"] != site["key"] or state["status"] not in {"active", "resting", "completed"}
                or type(state["step"]) is not int or not 0 <= state["step"] <= len(site["nodes"])
                or type(state["attempts"]) is not int or state["attempts"] < state["step"]
                or (state["status"] == "completed") != (state["step"] == len(site["nodes"]))):
            raise ValueError("survey operation state is malformed")
        if not isinstance(state["ready_at"], str) or datetime.fromisoformat(state["ready_at"]).tzinfo is None:
            raise ValueError("survey operation time is malformed")
        for field in ("costs", "reward"):
            amounts = payload.get(field)
            if not isinstance(amounts, dict) or any(not isinstance(k, str) or type(n) is not int or n <= 0 for k, n in amounts.items()):
                raise ValueError("survey operation assets are malformed")
        if payload["reward"] != (site["rewards"] if state["status"] == "completed" else {}):
            raise ValueError("survey operation reward disagrees with state")
        if not isinstance(payload.get("text"), str) or not payload["text"]:
            raise ValueError("survey operation narrative is missing")
        return payload

    @staticmethod
    def _survey_state(row):
        return {key: row[key] for key in ("site_key", "status", "step", "attempts", "ready_at")}

    def _survey_evidence(self, connection, row):
        start = connection.execute(
            "SELECT * FROM operations WHERE operation_id=? AND player_id=? AND operation_name='survey.start'",
            (row["start_operation_id"], row["player_id"]),
        ).fetchone()
        last = connection.execute(
            "SELECT * FROM operations WHERE operation_id=? AND player_id=?",
            (row["last_operation_id"], row["player_id"]),
        ).fetchone()
        if start is None or last is None or last["operation_name"] not in {"survey.start", "survey.choose", "survey.rest"}:
            raise ValueError("survey operation evidence is missing")
        frozen = decode_json_strict(row["snapshot_json"])
        if not isinstance(frozen, dict) or set(frozen) != {"site", "seed"} or not isinstance(frozen["seed"], str) or not frozen["seed"]:
            raise ValueError("survey snapshot is malformed")
        site = validate_survey(frozen["site"])
        initial = self._survey_payload(decode_json_strict(start["result_json"]))
        current = self._survey_payload(decode_json_strict(last["result_json"]))
        state = self._survey_state(row)
        if (initial.get("snapshot") != frozen or current.get("state") != state or site["key"] != row["site_key"]
                or type(state["step"]) is not int or not 0 <= state["step"] <= len(site["nodes"])
                or type(state["attempts"]) is not int or state["attempts"] < state["step"]
                or (state["status"] == "completed") != (state["step"] == len(site["nodes"]))):
            raise ValueError("survey projection disagrees with operation evidence")
        datetime.fromisoformat(state["ready_at"])
        if state["status"] == "completed" and current.get("reward") != site["rewards"]:
            raise ValueError("survey discovery reward evidence is missing")
        return frozen

    def _survey_gate(self, connection, player, site):
        if player["stage"] != "cultivator":
            raise SurveyRequirementError("先完成引导并选择道途。")
        if player["location_key"] != site["location_key"]:
            raise SurveyRequirementError("需先抵达" + (self.content or bundled_content()).label("location", site["location_key"]) + "。")
        if not self._meets_realm_values(str(player["realm_key"]), player_integer(player, "realm_layer"),
                                        site["required_realm"], site["required_layer"]):
            raise SurveyRequirementError("境界不足，请先修炼至" + (self.content or bundled_content()).label("realm", site["required_realm"]) + f"{site['required_layer']}层。")
        if self._has_active_long_action(connection, int(player["id"])):
            raise SurveyRequirementError("先结算当前移动、探索、生产或其他长时行动。")
        if site["prerequisite"]:
            parent = connection.execute("SELECT * FROM field_surveys WHERE player_id=? AND site_key=?",
                                        (player["id"], site["prerequisite"])).fetchone()
            if parent is None or parent["status"] != "completed":
                raise SurveyRequirementError("先完成前一处地貌勘察；山野手札可查路线。")
            self._survey_evidence(connection, parent)

    def _survey_spend(self, connection, player, costs, now):
        for key, amount in costs.items():
            available = (player_integer(player, key) if key in {"stamina", "energy"}
                         else player_available_item_amount(connection, player, key))
            if available < amount:
                label = {"stamina": "体力", "energy": "精力"}.get(key) or (self.content or bundled_content()).label("item", key)
                raise SurveyRequirementError(f"{label}不足，需要 {amount}；先恢复状态或补齐材料再来。")
        spend_player_state(connection, player, {k: n for k, n in costs.items() if k.startswith("item.")}, now,
                           value_delta={k: -n for k, n in costs.items() if k in {"stamina", "energy"}})

    async def survey_command(self, *, platform, platform_user_id, action, selector="", choice="", operation_id=""):
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._survey_command_once, platform, platform_user_id,
                                           action, selector, choice, operation_id)

    def _survey_command_once(self, platform, user, action, selector, choice, operation_id):
        bundle = self.content or bundled_content()
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            if action != "journal":
                connection.execute("BEGIN IMMEDIATE")
            player = self._require_player(connection, platform, user, writable=action != "journal")
            operation_name = "survey." + action
            request_hash = self._request_hash(operation_name, {"platform": platform, "user": user,
                                                              "selector": selector, "choice": choice})
            if action != "journal":
                replay = operation_replay(connection, operation_id, operation_name, request_hash, player_id=int(player["id"]))
                if replay is not None:
                    self._survey_payload(replay)
                    return {**replay, "idempotent_replay": True}
            if action == "journal":
                saved = connection.execute("SELECT * FROM field_surveys WHERE player_id=?", (player["id"],)).fetchall()
                entries = {}
                for row in saved:
                    frozen = self._survey_evidence(connection, row)
                    entries[row["site_key"]] = {"site": frozen["site"], "state": self._survey_state(row)}
                for key, site in survey_definitions(bundle).items():
                    if site["status"] in {"active", "open"} and key not in entries:
                        entries[key] = {"site": site, "state": {"site_key": key, "status": "unknown", "step": 0,
                                                               "attempts": 0, "ready_at": now_text}}
                if selector:
                    entries = {k: v for k, v in entries.items() if selector in {k, v["site"]["name"]}}
                    if not entries:
                        raise SurveyRequirementError("手札没有这一处勘察点。")
                return {"entries": list(entries.values())}
            row = connection.execute("SELECT * FROM field_surveys WHERE player_id=?", (player["id"],)).fetchall()
            selected = None
            for candidate in row:
                frozen = self._survey_evidence(connection, candidate)
                if selector in {candidate["site_key"], frozen["site"]["name"]}:
                    selected = candidate
                    break
            row = selected
            if row is None:
                if action != "start":
                    raise SurveyRequirementError("尚未开始此处勘察，先查山野手札。")
                try:
                    site = resolve_survey(bundle, selector)
                except LookupError as exc:
                    raise SurveyRequirementError(str(exc)) from exc
                self._survey_gate(connection, player, site)
                frozen = {"site": site, "seed": uuid4().hex}
                state = {"site_key": site["key"], "status": "active", "step": 0, "attempts": 0, "ready_at": now_text}
                payload = {"snapshot": frozen, "site": site, "state": state, "reward": {}, "costs": {},
                           "text": site["desc"], "idempotent_replay": False}
                record_operation(connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text)
                connection.execute("INSERT INTO field_surveys VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                                   (player["id"], site["key"], operation_id, operation_id, "active", 0, 0, now_text, _dump(frozen)))
                return payload
            frozen = self._survey_evidence(connection, row)
            site, state = frozen["site"], self._survey_state(row)
            if state["status"] == "completed":
                raise SurveyRequirementError("此地已经完成勘察，发现与首勘奖励保留在手札，不会重复发放。")
            reward, costs, success = {}, {}, None
            if action == "rest":
                if state["status"] == "resting":
                    raise SurveyRequirementError("已经收起手札，随时可在原地继续勘察。")
                state["status"] = "resting"
                text = "你收起勘察工具，已查明的地貌与进度保留；下次到原地继续，不退还已做观察的成本。"
            else:
                self._survey_gate(connection, player, site)
                if action == "start":
                    if state["status"] != "resting":
                        raise SurveyRequirementError("勘察正在进行，请在手札选择当前节点的做法，或暂离勘察。")
                    state["status"] = "active"
                    text = "你依照手札回到标记处，接着上次的地貌继续查验。"
                elif action == "choose":
                    if state["status"] != "active":
                        raise SurveyRequirementError("先继续勘察，再选择现场做法。")
                    if now < datetime.fromisoformat(state["ready_at"]):
                        raise SurveyRequirementError("上次观察尚未结束，等到 " + state["ready_at"] + " 再继续；可先收起手札。")
                    node = site["nodes"][state["step"]]
                    option = next((c for c in node["choices"] if choice in {c["key"], c["name"]}), None)
                    if option is None:
                        raise SurveyRequirementError("当前做法不存在，请在山野手札查看当前节点。")
                    costs = option["costs"]
                    self._survey_spend(connection, player, costs, now_text)
                    digest = hashlib.sha256(f"{frozen['seed']}:{state['attempts']}".encode()).digest()
                    success = int.from_bytes(digest[:8], "big") % 10000 < option["success_bp"]
                    state["attempts"] += 1
                    state["ready_at"] = serialize_datetime(now + timedelta(seconds=option["seconds"]))
                    state["step"] += int(success)
                    text = option["success_text"] if success else option["failure_text"]
                    if state["step"] == len(site["nodes"]):
                        state["status"] = "completed"
                        reward = site["rewards"]
                        updated = connection.execute("SELECT * FROM players WHERE id=?", (player["id"],)).fetchone()
                        grant_player_state(connection, updated, reward, now_text)
                        text += "\n\n" + site["completion_text"]
                else:
                    raise ValueError("unknown survey action")
            payload = {"site": site, "state": state, "reward": reward, "costs": costs, "success": success,
                       "text": text, "idempotent_replay": False}
            record_operation(connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text)
            connection.execute("UPDATE field_surveys SET last_operation_id=?, status=?, step=?, attempts=?, ready_at=? "
                               "WHERE player_id=? AND site_key=?",
                               (operation_id, state["status"], state["step"], state["attempts"], state["ready_at"], player["id"], site["key"]))
            return payload
