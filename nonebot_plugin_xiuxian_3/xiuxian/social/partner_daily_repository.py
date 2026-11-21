"""Transactional storage for daily partner fieldwork and personal rewards."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from ...contracts import serialize_datetime
from ..content import ContentError, ContentBundle, bundled_content
from ..partner_daily_content import (
    partner_daily_definition,
    partner_daily_snapshot,
    partner_daily_task_snapshot,
)
from ..persistence.errors import (
    OperationResultMalformedError,
    PartnerTaskNoPartnerError,
)
from ..utils.assets import inventory_value
from ..utils.player import grant_player_state
from ..utils.json_cache import decode_json_strict
from ..utils.operations import operation_replay, record_operation


class PartnerDailyTaskError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


class PartnerDailyTaskRepositoryMixin:
    def _partner_daily_content(self) -> ContentBundle:
        return self.content if self.content is not None else bundled_content()

    async def partner_daily_history(self, *, platform: str, platform_user_id: str,
                                    page: int = 1) -> dict[str, Any]:
        if type(page) is not int or not 1 <= page <= 10000:
            raise ValueError("partner daily history page must be between 1 and 10000")
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._partner_daily_history_once, platform, platform_user_id, page
            )

    def _partner_daily_history_once(self, platform: str, platform_user_id: str,
                                    page: int) -> dict[str, Any]:
        now = self._now().astimezone(timezone.utc)
        page_size = 5
        with self._connect() as connection:
            connection.execute("BEGIN")
            actor = self._require_player(connection, platform, platform_user_id, writable=False)
            tasks = connection.execute(
                "SELECT * FROM partner_daily_tasks WHERE player_a_id=? OR player_b_id=? "
                "ORDER BY created_at DESC,task_id DESC LIMIT ? OFFSET ?",
                (actor["id"], actor["id"], page_size + 1, (page - 1) * page_size),
            ).fetchall()
            return {
                "page": page, "page_size": page_size,
                "has_next": len(tasks) > page_size and page < 10000,
                "tasks": [self._partner_daily_task_view(connection, task, int(actor["id"]), now)
                          for task in tasks[:page_size]],
            }

    async def partner_daily_status(self, *, platform: str, platform_user_id: str,
                                   task_id: str = "") -> dict[str, Any]:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._partner_daily_status_once, platform, platform_user_id, task_id.strip()
            )

    def _partner_daily_status_once(self, platform: str, platform_user_id: str,
                                   task_id: str) -> dict[str, Any]:
        try:
            rule = partner_daily_definition(self._partner_daily_content())
            rule_available = True
        except ContentError:
            rule = None
            rule_available = False
        now = self._now().astimezone(timezone.utc)
        today = now.date().isoformat()
        with self._connect() as connection:
            connection.execute("BEGIN")
            actor = self._require_player(connection, platform, platform_user_id, writable=False)
            relation = self._partner_daily_active_relation(connection, int(actor["id"]))
            if task_id:
                task = connection.execute(
                    "SELECT * FROM partner_daily_tasks WHERE task_id=? AND (player_a_id=? OR player_b_id=?)",
                    (task_id, actor["id"], actor["id"]),
                ).fetchone()
                if task is None:
                    raise PartnerDailyTaskError("NOT_FOUND")
            elif relation is not None:
                task = connection.execute(
                    "SELECT * FROM partner_daily_tasks WHERE relation_id=? "
                    "ORDER BY quota_day DESC LIMIT 1", (relation["relation_id"],),
                ).fetchone()
            else:
                task = connection.execute(
                    "SELECT * FROM partner_daily_tasks WHERE player_a_id=? OR player_b_id=? "
                    "ORDER BY created_at DESC LIMIT 1", (actor["id"], actor["id"]),
                ).fetchone()
            used = int(connection.execute(
                "SELECT COUNT(*) FROM partner_daily_tasks WHERE relation_id=? AND quota_day=?",
                (relation["relation_id"], today),
            ).fetchone()[0]) if relation is not None else 0
            eligible = relation is not None and self._partner_daily_pair_available(
                connection, {int(relation["player_a_id"]), int(relation["player_b_id"])}
            )
            return {"has_partner": relation is not None, "eligible": eligible,
                    "rule": rule, "rule_available": rule_available,
                    "quota_day": today,
                    "used_today": used,
                    "task": self._partner_daily_task_view(connection, task, int(actor["id"]), now)
                    if task is not None else None}

    async def start_partner_daily_task(self, *, platform: str, platform_user_id: str,
                                       operation_id: str) -> dict[str, Any]:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._start_partner_daily_task_once, platform, platform_user_id, operation_id
            )

    def _start_partner_daily_task_once(self, platform: str, platform_user_id: str,
                                       operation_id: str) -> dict[str, Any]:
        operation_name = "social.partner_daily.start"
        request_hash = self._request_hash(operation_name, {"platform": platform, "user": platform_user_id})
        now = self._now().astimezone(timezone.utc)
        now_text = serialize_datetime(now)
        day = now.date().isoformat()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            player = self._require_player(connection, platform, platform_user_id, writable=False)
            replay = operation_replay(connection, operation_id, operation_name, request_hash,
                                      player_id=int(player["id"]))
            if replay is not None:
                return self._partner_daily_replay(connection, replay, int(player["id"]), operation_id, "start")
            self._require_player(connection, platform, platform_user_id)
            actor_id = int(player["id"])
            relation = self._partner_daily_active_relation(connection, actor_id)
            if relation is None:
                raise PartnerTaskNoPartnerError("the player has no active partner")
            pair_ids = {int(relation["player_a_id"]), int(relation["player_b_id"])}
            if not self._partner_daily_pair_available(connection, pair_ids):
                raise PartnerDailyTaskError("PLAYER")

            connection.execute(
                "UPDATE partner_daily_tasks SET status='expired' WHERE relation_id=? "
                "AND status='open' AND expires_at<=?",
                (relation["relation_id"], now_text),
            )
            current = connection.execute(
                "SELECT * FROM partner_daily_tasks WHERE relation_id=? AND quota_day=?",
                (relation["relation_id"], day),
            ).fetchone()
            if current is not None:
                snapshot = self._partner_daily_snapshot(current)
                self._partner_daily_claims(connection, current)
                payload = self._partner_daily_start_payload(current, snapshot)
                record_operation(connection, operation_id, operation_name, actor_id, request_hash,
                                 payload, now_text)
                return dict(payload, idempotent_replay=False, resumed=True)
            try:
                rule = partner_daily_definition(self._partner_daily_content())
            except ContentError as exc:
                raise PartnerDailyTaskError("UNAVAILABLE") from exc
            active = connection.execute(
                "SELECT task_id FROM partner_daily_tasks WHERE relation_id=? "
                "AND status IN ('open','claimable') LIMIT 1",
                (relation["relation_id"],),
            ).fetchone()
            if active is not None:
                raise PartnerDailyTaskError("ACTIVE")
            task_id = "partner-daily-" + uuid4().hex
            expires_at = serialize_datetime(now + timedelta(seconds=rule["window_seconds"]))
            snapshot = partner_daily_task_snapshot(rule)
            snapshot_json = _json(snapshot)
            snapshot_hash = self._request_hash("social.partner_daily.snapshot", snapshot)
            connection.execute(
                "INSERT INTO partner_daily_tasks(task_id,relation_id,quota_day,player_a_id,player_b_id,"
                "status,created_at,expires_at,snapshot_json,snapshot_hash,create_operation_id) "
                "VALUES (?,?,?,?,?,'open',?,?,?,?,?)",
                (task_id, relation["relation_id"], day, int(relation["player_a_id"]),
                 int(relation["player_b_id"]), now_text, expires_at, snapshot_json, snapshot_hash, operation_id),
            )
            payload = {"task_id": task_id, "relation_id": str(relation["relation_id"]),
                       "quota_day": day, "status": "open", "created_at": now_text,
                       "expires_at": expires_at, "snapshot_hash": snapshot_hash,
                       "name": rule["name"], "target_each": rule["target_each"],
                       "reward_world_merit": rule["reward_world_merit"],
                       "reward_items": dict(rule["reward_items"])}
            record_operation(connection, operation_id, operation_name, actor_id, request_hash,
                             payload, now_text)
            return dict(payload, idempotent_replay=False)

    async def claim_partner_daily_task(self, *, platform: str, platform_user_id: str,
                                       task_id: str, operation_id: str) -> dict[str, Any]:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._claim_partner_daily_task_once, platform, platform_user_id,
                task_id.strip(), operation_id,
            )

    def _claim_partner_daily_task_once(self, platform: str, platform_user_id: str,
                                       task_id: str, operation_id: str) -> dict[str, Any]:
        operation_name = "social.partner_daily.claim"
        request_hash = self._request_hash(operation_name, {"platform": platform,
                                                           "user": platform_user_id,
                                                           "task_id": task_id})
        now_text = serialize_datetime(self._now().astimezone(timezone.utc))
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            player = self._require_player(connection, platform, platform_user_id, writable=False)
            player_id = int(player["id"])
            replay = operation_replay(connection, operation_id, operation_name, request_hash,
                                      player_id=player_id)
            if replay is not None:
                return self._partner_daily_replay(connection, replay, player_id, operation_id, "claim")
            self._require_player(connection, platform, platform_user_id)
            relation = self._partner_daily_active_relation(connection, player_id)
            if relation is None:
                raise PartnerDailyTaskError("RELATION")
            if task_id:
                task = connection.execute(
                    "SELECT * FROM partner_daily_tasks WHERE task_id=? AND relation_id=?",
                    (task_id, relation["relation_id"]),
                ).fetchone()
            else:
                task = connection.execute(
                    "SELECT * FROM partner_daily_tasks WHERE relation_id=? "
                    "ORDER BY quota_day DESC LIMIT 1", (relation["relation_id"],),
                ).fetchone()
            if task is None:
                raise PartnerDailyTaskError("NOT_FOUND")
            task_id = str(task["task_id"])
            snapshot = self._partner_daily_snapshot(task)
            claims = self._partner_daily_claims(connection, task)
            if player_id in claims:
                raise PartnerDailyTaskError("CLAIMED")
            if task["status"] != "claimable":
                raise PartnerDailyTaskError("NOT_COMPLETE")
            if not self._partner_daily_pair_available(
                connection, {int(task["player_a_id"]), int(task["player_b_id"])}
            ):
                raise PartnerDailyTaskError("PLAYER")
            progress = self._partner_daily_progress(connection, task)
            if any(progress[pid] < snapshot["target_each"] for pid in progress):
                raise PartnerDailyTaskError("NOT_COMPLETE")

            reward_items = dict(snapshot["reward_items"])
            reward = dict(reward_items, world_merit=snapshot["reward_world_merit"])
            inventory = inventory_value(player["inventory_json"])
            before = {key: inventory.get(key, 0) for key in reward_items}
            before["world_merit"] = int(player["world_merit"])
            after = {key: before[key] + amount for key, amount in reward.items()}
            grant_player_state(connection, player, reward_items, now_text,
                               value_delta={"world_merit": snapshot["reward_world_merit"]})
            for key, amount in reward.items():
                connection.execute(
                    "INSERT INTO economy_ledger_entries(operation_id,player_id,asset_kind,asset_key,reason,"
                    "direction,amount,before_value,after_value,source_id,created_at) "
                    "VALUES (?,?,?,?,?,'credit',?,?,?,?,?)",
                    (operation_id, player_id, "resource" if key == "world_merit" else "item", key,
                     "partner_daily", amount, before[key], after[key], task_id, now_text),
                )
            connection.execute(
                "INSERT INTO partner_daily_claims(task_id,player_id,reward_json,before_json,after_json,"
                "operation_id,claimed_at) VALUES (?,?,?,?,?,?,?)",
                (task_id, player_id, _json(reward), _json(before), _json(after), operation_id, now_text),
            )
            if int(connection.execute(
                    "SELECT COUNT(*) FROM partner_daily_claims WHERE task_id=?", (task_id,)
            ).fetchone()[0]) == 2:
                connection.execute(
                    "UPDATE partner_daily_tasks SET status='completed' WHERE task_id=? AND status='claimable'",
                    (task_id,),
                )
            payload = {"task_id": task_id, "relation_id": str(task["relation_id"]),
                       "status": "claimed", "progress": self._partner_daily_progress_view(
                           task, progress, player_id
                       ), "reward": reward}
            record_operation(connection, operation_id, operation_name, player_id, request_hash,
                             payload, now_text)
            return dict(payload, idempotent_replay=False)

    def _record_partner_daily_evidence(self, connection: sqlite3.Connection, *, player_id: int,
                                       source_operation_id: str, source_key: str,
                                       occurred_at: str) -> None:
        receipt = connection.execute(
            "SELECT operation_name,player_id FROM operations WHERE operation_id=?",
            (source_operation_id,),
        ).fetchone()
        if (receipt is None or receipt["operation_name"] != "deposit.extract"
                or int(receipt["player_id"]) != player_id):
            raise ValueError("partner daily evidence requires its player's extraction receipt")
        task = connection.execute(
            "SELECT t.* FROM partner_daily_tasks t JOIN partner_relations r USING(relation_id) "
            "WHERE t.status='open' AND r.status='active' AND t.created_at<=? AND t.expires_at>? "
            "AND (t.player_a_id=? OR t.player_b_id=?) ORDER BY t.created_at DESC LIMIT 1",
            (occurred_at, occurred_at, player_id, player_id),
        ).fetchone()
        if task is None:
            return
        if not self._partner_daily_pair_available(
            connection, {int(task["player_a_id"]), int(task["player_b_id"])}
        ):
            return
        snapshot = self._partner_daily_snapshot(task)
        if source_key not in snapshot["deposit_keys"]:
            return
        if self._partner_daily_progress(connection, task)[player_id] >= snapshot["target_each"]:
            return
        connection.execute(
            "INSERT INTO partner_daily_evidence(task_id,player_id,source_operation_id,source_key,occurred_at) "
            "VALUES (?,?,?,?,?)",
            (task["task_id"], player_id, source_operation_id, source_key, occurred_at),
        )
        progress = self._partner_daily_progress(connection, task)
        if all(progress[pid] >= snapshot["target_each"] for pid in progress):
            connection.execute(
                "UPDATE partner_daily_tasks SET status='claimable' WHERE task_id=? AND status='open'",
                (task["task_id"],),
            )

    def _partner_daily_task_view(self, connection: sqlite3.Connection, task: Any,
                                 actor_id: int, now: Any) -> dict[str, Any]:
        snapshot = self._partner_daily_snapshot(task)
        progress = self._partner_daily_progress(connection, task)
        claimed = self._partner_daily_claims(connection, task)
        current_status = str(task["status"])
        if current_status == "open" and str(task["expires_at"]) <= serialize_datetime(now):
            current_status = "expired"
        partner_id = int(task["player_b_id"] if actor_id == int(task["player_a_id"])
                         else task["player_a_id"])
        partner = connection.execute("SELECT dao_name FROM players WHERE id=?", (partner_id,)).fetchone()
        relation = self._partner_daily_active_relation(connection, actor_id)
        return {"task_id": str(task["task_id"]), "quota_day": str(task["quota_day"]),
                "status": current_status, "created_at": str(task["created_at"]),
                "expires_at": str(task["expires_at"]), "name": snapshot["name"],
                "description": snapshot["description"], "target_each": snapshot["target_each"],
                "deposit_keys": list(snapshot["deposit_keys"]),
                "progress": self._partner_daily_progress_view(task, progress, actor_id),
                "claimed": actor_id in claimed,
                "partner_claimed": partner_id in claimed, "partner_name": str(partner["dao_name"]),
                "relation_active": relation is not None and relation["relation_id"] == task["relation_id"],
                "reward_world_merit": snapshot["reward_world_merit"],
                "reward_items": dict(snapshot["reward_items"])}

    @staticmethod
    def _partner_daily_progress_view(task: Any, progress: dict[int, int], actor_id: int) -> dict[str, int]:
        partner_id = int(task["player_b_id"] if actor_id == int(task["player_a_id"])
                         else task["player_a_id"])
        return {"self": progress[actor_id], "partner": progress[partner_id]}

    @staticmethod
    def _partner_daily_start_payload(task: Any, snapshot: dict[str, Any]) -> dict[str, Any]:
        return {"task_id": str(task["task_id"]), "relation_id": str(task["relation_id"]),
                "quota_day": str(task["quota_day"]), "status": str(task["status"]),
                "created_at": str(task["created_at"]), "expires_at": str(task["expires_at"]),
                "snapshot_hash": str(task["snapshot_hash"]), "name": snapshot["name"],
                "target_each": snapshot["target_each"],
                "reward_world_merit": snapshot["reward_world_merit"],
                "reward_items": dict(snapshot["reward_items"])}

    def _partner_daily_snapshot(self, task: Any) -> dict[str, Any]:
        try:
            snapshot = decode_json_strict(task["snapshot_json"])
            rule = partner_daily_snapshot(snapshot)
            if self._request_hash("social.partner_daily.snapshot", rule) != task["snapshot_hash"]:
                raise ValueError("snapshot hash mismatch")
            created = datetime.fromisoformat(task["created_at"])
            expires = datetime.fromisoformat(task["expires_at"])
            if (created.tzinfo is None or expires.tzinfo is None
                    or serialize_datetime(created) != task["created_at"]
                    or serialize_datetime(expires) != task["expires_at"]
                    or expires != created + timedelta(seconds=rule["window_seconds"])
                    or created.date().isoformat() != task["quota_day"]):
                raise ValueError("task window disagrees with snapshot")
            return rule
        except (ValueError, TypeError, KeyError) as exc:
            raise ContentError("partner daily task snapshot is malformed") from exc

    @staticmethod
    def _partner_daily_active_relation(connection: sqlite3.Connection,
                                       player_id: int) -> sqlite3.Row | None:
        return connection.execute(
            "SELECT * FROM partner_relations WHERE status='active' AND "
            "(player_a_id=? OR player_b_id=?) ORDER BY accepted_at DESC LIMIT 1",
            (player_id, player_id),
        ).fetchone()

    @staticmethod
    def _partner_daily_pair_available(connection: sqlite3.Connection, player_ids: set[int]) -> bool:
        if len(player_ids) != 2:
            return False
        rows = connection.execute(
            "SELECT id,status,endgame_status FROM players WHERE id IN (?,?) ORDER BY id",
            tuple(sorted(player_ids)),
        ).fetchall()
        return len(rows) == 2 and all(
            row["status"] == "active" and row["endgame_status"] not in {
                "ascension_ready", "ascended", "remained_in_world"
            } for row in rows
        ) and connection.execute(
            "SELECT 1 FROM final_battle_members WHERE player_id IN (?,?) AND asset_lock_status='locked' LIMIT 1",
            tuple(sorted(player_ids)),
        ).fetchone() is None

    def _partner_daily_progress(self, connection: sqlite3.Connection, task: Any) -> dict[int, int]:
        rule = self._partner_daily_snapshot(task)
        result = {int(task["player_a_id"]): 0, int(task["player_b_id"]): 0}
        creation = connection.execute(
            "SELECT rowid,operation_name,player_id,result_json FROM operations WHERE operation_id=?",
            (task["create_operation_id"],),
        ).fetchone()
        if (creation is None or creation["operation_name"] != "social.partner_daily.start"
                or int(creation["player_id"]) not in result):
            raise ValueError("partner daily task has no creation receipt")
        expected_start = self._partner_daily_start_payload(task, rule)
        expected_start["status"] = "open"
        if decode_json_strict(creation["result_json"]) != expected_start:
            raise ValueError("partner daily creation receipt disagrees with task")
        rows = connection.execute(
            "SELECT e.*,o.rowid AS source_rowid,o.operation_name,o.player_id AS source_player_id,"
            "o.result_json,o.created_at FROM partner_daily_evidence e "
            "LEFT JOIN operations o ON o.operation_id=e.source_operation_id WHERE e.task_id=?",
            (task["task_id"],),
        ).fetchall()
        for row in rows:
            if (row["player_id"] not in result or row["operation_name"] != "deposit.extract"
                    or row["source_player_id"] != row["player_id"]
                    or row["source_key"] not in rule["deposit_keys"]
                    or row["source_rowid"] <= creation["rowid"]
                    or row["occurred_at"] != row["created_at"]
                    or not task["created_at"] <= row["occurred_at"] < task["expires_at"]):
                raise ValueError("partner daily source evidence is invalid")
            payload = self._deposit_payload(decode_json_strict(row["result_json"]))
            if payload["action"] != "extract" or payload["snapshot"]["definition"]["key"] != row["source_key"]:
                raise ValueError("partner daily source key disagrees with extraction")
            result[row["player_id"]] += 1
        if any(value > rule["target_each"] for value in result.values()):
            raise ValueError("partner daily source count exceeds target")
        return result

    def _partner_daily_claims(self, connection: sqlite3.Connection, task: Any) -> set[int]:
        rule = self._partner_daily_snapshot(task)
        progress = self._partner_daily_progress(connection, task)
        reward = dict(rule["reward_items"], world_merit=rule["reward_world_merit"])
        claimed: set[int] = set()
        rows = connection.execute(
            "SELECT * FROM partner_daily_claims WHERE task_id=?", (task["task_id"],)
        ).fetchall()
        for row in rows:
            player_id = int(row["player_id"])
            before = decode_json_strict(row["before_json"])
            after = decode_json_strict(row["after_json"])
            if (player_id not in progress or decode_json_strict(row["reward_json"]) != reward
                    or not isinstance(before, dict) or not isinstance(after, dict)
                    or set(before) != set(reward) or set(after) != set(reward)
                    or any(type(value) is not int or value < 0 for value in (*before.values(), *after.values()))
                    or after != {key: before[key] + amount for key, amount in reward.items()}):
                raise ValueError("partner daily claim assets are malformed")
            operation = connection.execute(
                "SELECT operation_name,player_id,result_json FROM operations WHERE operation_id=?",
                (row["operation_id"],),
            ).fetchone()
            expected = {"task_id": task["task_id"], "relation_id": task["relation_id"],
                        "status": "claimed", "reward": reward,
                        "progress": self._partner_daily_progress_view(task, progress, player_id)}
            if (operation is None or operation["operation_name"] != "social.partner_daily.claim"
                    or operation["player_id"] != player_id
                    or decode_json_strict(operation["result_json"]) != expected):
                raise ValueError("partner daily claim has no matching receipt")
            ledger = connection.execute(
                "SELECT player_id,asset_kind,asset_key,direction,amount,before_value,after_value,source_id "
                "FROM economy_ledger_entries WHERE operation_id=? AND reason='partner_daily'",
                (row["operation_id"],),
            ).fetchall()
            expected_ledger = {
                (player_id, "resource" if key == "world_merit" else "item", key, "credit", amount,
                 before[key], after[key], task["task_id"]) for key, amount in reward.items()
            }
            if len(ledger) != len(reward) or {tuple(entry) for entry in ledger} != expected_ledger:
                raise ValueError("partner daily claim ledger is incomplete")
            claimed.add(player_id)
        complete = all(value >= rule["target_each"] for value in progress.values())
        if (task["status"] not in {"open", "claimable", "completed", "expired"}
                or bool(claimed) and not complete
                or task["status"] == "completed" and len(claimed) != 2
                or task["status"] == "claimable" and (not complete or len(claimed) == 2)
                or task["status"] in {"open", "expired"} and (complete or claimed)):
            raise ValueError("partner daily task state disagrees with evidence/claims")
        return claimed

    def _partner_daily_replay(self, connection: sqlite3.Connection, payload: dict[str, Any],
                              actor_id: int, operation_id: str, action: str) -> dict[str, Any]:
        task = connection.execute(
            "SELECT * FROM partner_daily_tasks WHERE task_id=? AND (player_a_id=? OR player_b_id=?)",
            (payload.get("task_id"), actor_id, actor_id),
        ).fetchone()
        if task is None:
            raise OperationResultMalformedError("partner daily operation has no task")
        rule = self._partner_daily_snapshot(task)
        claims = self._partner_daily_claims(connection, task)
        if action == "start":
            expected = self._partner_daily_start_payload(task, rule)
            expected["status"] = payload.get("status")
            if payload.get("status") not in {"open", "claimable", "completed", "expired"}:
                raise OperationResultMalformedError("partner daily start state is invalid")
        else:
            if actor_id not in claims or connection.execute(
                "SELECT 1 FROM partner_daily_claims WHERE task_id=? AND player_id=? AND operation_id=?",
                (task["task_id"], actor_id, operation_id),
            ).fetchone() is None:
                raise OperationResultMalformedError("partner daily operation has no personal claim")
            progress = self._partner_daily_progress(connection, task)
            expected = {"task_id": task["task_id"], "relation_id": task["relation_id"],
                        "status": "claimed", "progress": self._partner_daily_progress_view(task, progress, actor_id),
                        "reward": dict(rule["reward_items"], world_merit=rule["reward_world_merit"])}
        if payload != expected:
            raise OperationResultMalformedError("partner daily operation disagrees with frozen task")
        return dict(payload, idempotent_replay=True)
