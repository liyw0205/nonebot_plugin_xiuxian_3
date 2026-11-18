"""SQLite transactions for dao-union qualification and dao-origin tasks."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from ...contracts import serialize_datetime
from ..content import ContentError, bundled_content
from ..utils.assets import inventory_amount, spend_player_items
from ..utils.player import grant_player_state, player_integer, player_inventory
from ..events.rules import final_heaven_season_window
from ..events.season_content import FINAL_HEAVEN_SEASON_KEY, season_record
from ..persistence.errors import (
    DaoOriginQualificationAlreadyClaimedError,
    DaoOriginQualificationIncompleteError,
    DaoOriginTaskRequirementError,
    QuestAlreadyCompletedError,
    QuestNotCompletedError,
    QuestRequirementError,
    QuestResourceInsufficientError,
)
from ..specials.codex_projection import record_codex_discovery
from .models import (
    DaoOriginSeasonQualificationRecord,
    DaoUnionQualificationRecord,
    QuestActionRecord,
)
from .rules import (
    DAO_ORIGIN_TASKS,
    dao_origin_task_definition,
    dao_origin_task_snapshot_from_event,
    parse_dao_origin_task_snapshot,
    DAO_UNION_CHALLENGE,
    DAO_UNION_FRAGMENT_REWARD,
    DAO_UNION_MAINLINE,
    DAO_UNION_MAINLINE_LANES,
    DAO_UNION_MAINLINE_STAGE_KEYS,
    DAO_UNION_MAINLINE_STORY_KEY,
    DAO_UNION_QUEST,
    DAO_UNION_TRIBULATION_TOKEN_REWARD,
    DAO_UNION_WORK,
    meets_realm,
)


class EndgameQuestRepositoryMixin:
    """Keep endgame evidence and qualification transactions out of generic quests."""

    @staticmethod
    def _dao_union_mainline_payload_is_valid(payload: dict[str, Any]) -> bool:
        if (
            payload.get("source") != "mainline_runs"
            or payload.get("story_key") != DAO_UNION_MAINLINE_STORY_KEY
        ):
            return False
        lane_stage_keys = payload.get("lane_stage_keys")
        if not isinstance(lane_stage_keys, dict):
            return False
        for lane in DAO_UNION_MAINLINE_LANES:
            values = lane_stage_keys.get(lane)
            if not isinstance(values, (list, tuple)):
                return False
            if not set(DAO_UNION_MAINLINE_STAGE_KEYS[lane]).issubset({str(key) for key in values}):
                return False
        return True

    @classmethod
    def _valid_dao_union_mainline_event_count(cls, connection: sqlite3.Connection, player_id: int) -> int:
        rows = connection.execute(
            "SELECT payload_json FROM quest_events WHERE player_id=? AND quest_key=? AND component_key=? AND outcome='success'",
            (player_id, DAO_UNION_QUEST, DAO_UNION_MAINLINE),
        ).fetchall()
        count = 0
        for row in rows:
            try:
                payload = json.loads(row["payload_json"] or "{}")
            except (TypeError, json.JSONDecodeError):
                continue
            if isinstance(payload, dict) and cls._dao_union_mainline_payload_is_valid(payload):
                count += 1
        return count

    async def record_dao_union_mainline(
        self, *, platform: str, platform_user_id: str, operation_id: str
    ) -> QuestActionRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._record_dao_union_component_sync,
                platform,
                platform_user_id,
                operation_id,
                DAO_UNION_MAINLINE,
                None,
            )

    async def record_dao_union_challenge(
        self, *, platform: str, platform_user_id: str, operation_id: str, battle_id: str
    ) -> QuestActionRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._record_dao_union_component_sync,
                platform,
                platform_user_id,
                operation_id,
                DAO_UNION_CHALLENGE,
                battle_id,
            )

    async def deliver_dao_union_work(
        self, *, platform: str, platform_user_id: str, operation_id: str
    ) -> QuestActionRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._record_dao_union_component_sync,
                platform,
                platform_user_id,
                operation_id,
                DAO_UNION_WORK,
                None,
            )

    async def claim_dao_union_quest(
        self, *, platform: str, platform_user_id: str, operation_id: str
    ) -> DaoUnionQualificationRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._claim_dao_union_quest_sync,
                platform,
                platform_user_id,
                operation_id,
            )

    async def complete_dao_origin_task(
        self, *, platform: str, platform_user_id: str, task_key: str, operation_id: str
    ) -> QuestActionRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._complete_dao_origin_task_sync,
                platform,
                platform_user_id,
                task_key,
                operation_id,
            )

    async def get_dao_origin_qualification(
        self, *, platform: str, platform_user_id: str
    ) -> DaoOriginSeasonQualificationRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._get_dao_origin_qualification_sync,
                platform,
                platform_user_id,
            )

    async def claim_dao_origin_qualification(
        self, *, platform: str, platform_user_id: str, operation_id: str
    ) -> DaoOriginSeasonQualificationRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._claim_dao_origin_qualification_sync,
                platform,
                platform_user_id,
                operation_id,
            )

    def _record_dao_union_component_sync(
        self,
        platform: str,
        platform_user_id: str,
        operation_id: str,
        component_key: str,
        battle_id: str | None,
    ) -> QuestActionRecord:
        operation_name = f"quest.dao_union.{component_key}"
        request_hash = self._request_hash(
            operation_name,
            {"platform": platform, "platform_user_id": platform_user_id, "component_key": component_key, "battle_id": battle_id},
        )
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._quest_operation_replay(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                return self._action_from_payload(replay, replay=True)
            player = self._require_player(connection, platform, platform_user_id)
            if not meets_realm(str(player["realm_key"]), player_integer(player, "realm_layer"), "void_refining", 10):
                raise QuestRequirementError("dao union qualification requires void refining L10")
            count = (
                self._valid_dao_union_mainline_event_count(connection, int(player["id"]))
                if component_key == DAO_UNION_MAINLINE
                else self._event_count(connection, int(player["id"]), DAO_UNION_QUEST, component_key)
            )
            if count >= 1:
                raise QuestAlreadyCompletedError("dao union component is already complete")

            source: dict[str, object]
            if component_key == DAO_UNION_MAINLINE:
                rows = connection.execute(
                    "SELECT stage_key FROM mainline_runs WHERE player_id=? AND story_key=? AND status='claimed'",
                    (
                        player["id"],
                        DAO_UNION_MAINLINE_STORY_KEY,
                    ),
                ).fetchall()
                claimed = {str(row["stage_key"]) for row in rows}
                lane_stage_keys = {
                    lane: sorted(set(DAO_UNION_MAINLINE_STAGE_KEYS[lane]).intersection(claimed))
                    for lane in DAO_UNION_MAINLINE_LANES
                }
                if any(
                    len(lane_stage_keys[lane]) != len(DAO_UNION_MAINLINE_STAGE_KEYS[lane])
                    for lane in DAO_UNION_MAINLINE_LANES
                ):
                    raise QuestNotCompletedError("all three dao echoes lanes must be claimed")
                source = {
                    "source": "mainline_runs",
                    "story_key": DAO_UNION_MAINLINE_STORY_KEY,
                    "lane_stage_keys": lane_stage_keys,
                }
            elif component_key == DAO_UNION_WORK:
                path_key = str(player["path_key"] or "")
                work_key = {
                    "body": "item.masterwork.body",
                    "spell": "item.masterwork.spell",
                    "device": "item.masterwork.device",
                    "demonic": "item.masterwork.demonic",
                    "beast": "item.masterwork.beast",
                    "support": "item.masterwork.support",
                }.get(path_key)
                inventory = player_inventory(player)
                if not work_key or inventory_amount(inventory, work_key) < 1:
                    raise QuestResourceInsufficientError("profession endgame work is missing")
                spend_player_items(connection, player, {work_key: 1}, now_text)
                source = {"source": "inventory_delivery", "item_key": work_key, "path_key": path_key}
            elif component_key == DAO_UNION_CHALLENGE:
                battle = connection.execute(
                    "SELECT player_id, battle_type, status, result_json FROM battle_sessions WHERE battle_id = ?",
                    (battle_id,),
                ).fetchone()
                result = self._json_object(battle["result_json"], {}) if battle is not None else {}
                if (
                    battle is None
                    or int(battle["player_id"]) != int(player["id"])
                    or str(battle["battle_type"]) != "pve.dao_union_challenge"
                    or str(battle["status"]) != "settled"
                    or str(result.get("outcome", "")) != "won"
                ):
                    raise QuestRequirementError("a settled personal challenge victory is required")
                source = {"source": "battle_sessions", "battle_id": battle_id, "challenge": "dao_union"}
            else:
                raise QuestRequirementError("unknown dao union component")

            self._insert_quest_event(
                connection,
                player_id=int(player["id"]),
                quest_key=DAO_UNION_QUEST,
                component_key=component_key,
                source_operation_id=operation_id,
                outcome="success",
                payload=source,
                now_text=now_text,
            )
            progress = {component_key: 1}
            self._upsert_progress(
                connection,
                int(player["id"]),
                DAO_UNION_QUEST,
                "active",
                progress,
                {"last_component": component_key, "source": source},
                operation_id,
                now_text,
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (player["id"],)).fetchone()
            payload = self._action_payload(updated, DAO_UNION_QUEST, component_key, progress, {}, status="active")
            self._insert_operation(
                connection,
                operation_id=operation_id,
                operation_name=operation_name,
                player_id=int(player["id"]),
                request_hash=request_hash,
                payload=payload,
                now_text=now_text,
            )
            return self._action_from_payload(payload)

    def _claim_dao_union_quest_sync(
        self, platform: str, platform_user_id: str, operation_id: str
    ) -> DaoUnionQualificationRecord:
        operation_name = "quest.dao_union.claim"
        request_hash = self._request_hash(
            operation_name, {"platform": platform, "platform_user_id": platform_user_id}
        )
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._quest_operation_replay(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                return self._dao_union_from_payload(replay, replay=True)
            player = self._require_player(connection, platform, platform_user_id)
            progress = {
                component: (
                    self._valid_dao_union_mainline_event_count(connection, int(player["id"]))
                    if component == DAO_UNION_MAINLINE
                    else self._event_count(connection, int(player["id"]), DAO_UNION_QUEST, component)
                )
                for component in (DAO_UNION_MAINLINE, DAO_UNION_CHALLENGE, DAO_UNION_WORK)
            }
            if any(value < 1 for value in progress.values()):
                raise QuestNotCompletedError("dao union qualification is incomplete")
            existing = connection.execute(
                "SELECT status, snapshot_json FROM quest_progress WHERE player_id = ? AND quest_key = ?",
                (player["id"], DAO_UNION_QUEST),
            ).fetchone()
            if existing is not None and str(existing["status"]) in {"completed", "claimed"}:
                raise QuestAlreadyCompletedError("dao union qualification is already claimed")
            qualification_reward = {
                "item.dao_fruit_fragment": DAO_UNION_FRAGMENT_REWARD,
                "item.tribulation_token": DAO_UNION_TRIBULATION_TOKEN_REWARD,
            }
            snapshot = {
                "path_key": player["path_key"],
                "subprofession_key": player["subprofession_key"],
                "realm_key": str(player["realm_key"]),
                "realm_layer": player_integer(player, "realm_layer"),
                "components": progress,
                "reward": qualification_reward,
            }
            flags_state = self._json_object(player["intro_json"], {})
            flags = set(str(item) for item in flags_state.get("flags", []))
            flags.add(DAO_UNION_QUEST)
            flags_state["flags"] = sorted(flags)
            grant_player_state(
                connection,
                player,
                updated_at=now_text,
                rewards={
                    "item.dao_fruit_fragment": DAO_UNION_FRAGMENT_REWARD,
                    "item.tribulation_token": DAO_UNION_TRIBULATION_TOKEN_REWARD,
                },
                player_values={"intro_json": json.dumps(flags_state, ensure_ascii=False, sort_keys=True)},
            )
            self._upsert_progress(
                connection,
                int(player["id"]),
                DAO_UNION_QUEST,
                "completed",
                progress,
                snapshot,
                operation_id,
                now_text,
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (player["id"],)).fetchone()
            payload = {
                "player": self._player_payload(self._row_to_player(updated)),
                "quest_key": DAO_UNION_QUEST,
                "status": "completed",
                "progress": progress,
                "snapshot": snapshot,
                "reward": qualification_reward,
            }
            self._insert_operation(
                connection,
                operation_id=operation_id,
                operation_name=operation_name,
                player_id=int(player["id"]),
                request_hash=request_hash,
                payload=payload,
                now_text=now_text,
            )
            return self._dao_union_from_payload(payload)

    def _complete_dao_origin_task_sync(
        self, platform: str, platform_user_id: str, task_key: str, operation_id: str
    ) -> QuestActionRecord:
        if task_key not in DAO_ORIGIN_TASKS:
            raise DaoOriginTaskRequirementError("unknown dao-origin task")
        operation_name = f"{task_key}.complete"
        request_hash = self._request_hash(
            operation_name, {"platform": platform, "platform_user_id": platform_user_id, "task_key": task_key}
        )
        now = self._now()
        now_text = serialize_datetime(now)
        season_id, season_start, season_end = final_heaven_season_window(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._quest_operation_replay(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                return self._action_from_payload(replay, replay=True)
            player = self._require_player(connection, platform, platform_user_id)
            if not meets_realm(str(player["realm_key"]), player_integer(player, "realm_layer"), "dao_union"):
                raise DaoOriginTaskRequirementError("dao-origin tasks require 合道")
            if str(player["endgame_status"] or "none") not in {"dao_union", "tribulation"}:
                raise DaoOriginTaskRequirementError("dao-origin tasks require an active endgame route")
            content = self.content or bundled_content()
            if not content.has("quest", task_key, include_locked=False):
                raise DaoOriginTaskRequirementError("dao-origin task is not open")
            count, task_snapshot = self._dao_origin_task_progress(
                connection, int(player["id"]), task_key, season_id
            )
            if task_snapshot is None:
                task_snapshot = dao_origin_task_definition(task_key, content).snapshot(season_id)
            target = int(task_snapshot["target"])
            codex_entry_key = task_snapshot["codex_entry_key"]
            if count >= target:
                raise QuestAlreadyCompletedError("dao-origin task is already complete for this season")
            source = self._find_dao_origin_source(
                connection, int(player["id"]), task_key, season_id, season_start, season_end
            )
            if source is None:
                raise QuestNotCompletedError("no eligible server activity is available for this dao-origin task")
            count += 1
            reward = dict(task_snapshot["reward"]) if count == target else {}
            discovery: dict[str, object] = {}
            if count == target and codex_entry_key is not None:
                discovery = {
                    "entry_key": codex_entry_key,
                    "label": task_snapshot["codex_label"],
                    "task_key": task_key,
                    "task_operation_id": operation_id,
                    "source_operation_id": str(source["source_operation_id"]),
                    "source_kind": str(source["source_kind"]),
                    "evidence_id": str(source["evidence_id"]),
                    "season_id": season_id,
                    "occurred_at": str(source["occurred_at"]),
                }
                if "source_key" in source:
                    discovery["source_key"] = str(source["source_key"])
                if not record_codex_discovery(
                    connection,
                    player_id=int(player["id"]),
                    entry_key=codex_entry_key,
                    operation_id=operation_id,
                    occurred_at=now_text,
                    snapshot=discovery,
                    content=content,
                    category_snapshot="service",
                ):
                    raise ContentError(f"unable to record dao-origin service discovery: {codex_entry_key}")
            if reward:
                grant_player_state(
                    connection,
                    player,
                    updated_at=now_text,
                    rewards={key: amount for key, amount in reward.items() if key.startswith("item.")},
                    value_delta={key: amount for key, amount in reward.items() if not key.startswith("item.")},
                )
            event_payload = {
                "count": count,
                "reward": reward,
                "season_id": season_id,
                "task_snapshot": task_snapshot,
                "event_key": "event.dao_origin",
                "discovery": discovery,
                **source,
            }
            self._insert_quest_event(
                connection,
                player_id=int(player["id"]),
                quest_key=task_key,
                component_key="completed",
                source_operation_id=str(source["source_operation_id"]),
                outcome="success",
                payload=event_payload,
                now_text=now_text,
            )
            self._insert_quest_event(
                connection,
                player_id=int(player["id"]),
                quest_key="event.dao_origin",
                component_key=task_key,
                source_operation_id=str(source["source_operation_id"]),
                outcome="success",
                payload=event_payload,
                now_text=now_text,
            )
            progress = {"completed": count, "target": target}
            self._upsert_progress(
                connection,
                int(player["id"]),
                task_key,
                "completed" if count >= target else "active",
                progress,
                task_snapshot,
                operation_id,
                now_text,
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (player["id"],)).fetchone()
            payload = self._action_payload(
                updated,
                task_key,
                "completed",
                progress,
                reward,
                status="completed" if count >= target else "active",
                display_name=str(task_snapshot["name"]),
                discovery=discovery,
                reward_labels=task_snapshot["reward_labels"],
            )
            self._insert_operation(
                connection,
                operation_id=operation_id,
                operation_name=operation_name,
                player_id=int(player["id"]),
                request_hash=request_hash,
                payload=payload,
                now_text=now_text,
            )
            return self._action_from_payload(payload)

    def _dao_origin_qualification_config(self) -> tuple[tuple[str, ...], str]:
        record = season_record(FINAL_HEAVEN_SEASON_KEY, self.content or bundled_content())
        qualification = record.get("qualification")
        if not isinstance(qualification, dict):
            raise ContentError("final-heaven qualification content is missing")
        task_keys = qualification.get("task_keys")
        readiness_flag = qualification.get("readiness_flag")
        if (
            not isinstance(task_keys, tuple)
            or not task_keys
            or not isinstance(readiness_flag, str)
            or not readiness_flag.strip()
        ):
            raise ContentError("final-heaven qualification content is invalid")
        return tuple(str(key) for key in task_keys), readiness_flag.strip()

    def _dao_origin_task_evidence(
        self,
        connection: sqlite3.Connection,
        player_id: int,
        task_key: str,
        season_id: str,
        season_start: datetime,
        season_end: datetime,
    ) -> list[dict[str, str]]:
        rows = connection.execute(
            "SELECT source_operation_id, payload_json FROM quest_events "
            "WHERE player_id = ? AND quest_key = ? AND component_key = 'completed' "
            "AND outcome = 'success' ORDER BY id",
            (player_id, task_key),
        ).fetchall()
        evidence: list[dict[str, str]] = []
        seen_operations: set[str] = set()
        for row in rows:
            source_operation_id = str(row["source_operation_id"] or "")
            if not source_operation_id or source_operation_id in seen_operations:
                raise ContentError(f"dao-origin task evidence is duplicated: {task_key}")
            try:
                payload = json.loads(row["payload_json"] or "{}")
            except (TypeError, json.JSONDecodeError) as exc:
                raise ContentError(f"dao-origin task event cannot be read: {task_key}") from exc
            if not isinstance(payload, dict) or payload.get("season_id") != season_id:
                continue
            if payload.get("source_operation_id") != source_operation_id:
                raise ContentError(f"dao-origin task source operation is inconsistent: {task_key}")
            source_kind = str(payload.get("source_kind") or "")
            evidence_id = str(payload.get("evidence_id") or "")
            occurred_at = str(payload.get("occurred_at") or "")
            if not source_kind or not evidence_id or not occurred_at:
                raise ContentError(f"dao-origin task evidence is incomplete: {task_key}")
            try:
                occurred = datetime.fromisoformat(occurred_at).astimezone(timezone.utc)
            except (TypeError, ValueError) as exc:
                raise ContentError(f"dao-origin task evidence timestamp is invalid: {task_key}") from exc
            if not season_start <= occurred < season_end:
                raise ContentError(f"dao-origin task evidence is outside its season: {task_key}")
            if not self._dao_origin_evidence_matches_source(
                connection,
                player_id=player_id,
                task_key=task_key,
                source_kind=source_kind,
                source_operation_id=source_operation_id,
                evidence_id=evidence_id,
                occurred_at=occurred,
                source_key=payload.get("source_key"),
            ):
                raise ContentError(f"dao-origin task evidence source is invalid: {task_key}")
            seen_operations.add(source_operation_id)
            evidence.append(
                {
                    "source_operation_id": source_operation_id,
                    "source_kind": source_kind,
                    "evidence_id": evidence_id,
                    "occurred_at": occurred_at,
                }
            )
        return evidence

    def _dao_origin_evidence_matches_source(
        self,
        connection: sqlite3.Connection,
        *,
        player_id: int,
        task_key: str,
        source_kind: str,
        source_operation_id: str,
        evidence_id: str,
        occurred_at: datetime,
        source_key: object,
    ) -> bool:
        """Cross-check persisted task evidence against its producing record."""

        if task_key == "task.dao_origin.guard":
            if source_kind != "battle_sessions":
                return False
            row = connection.execute(
                "SELECT battle_id, starts_at, result_json FROM battle_sessions "
                "WHERE player_id=? AND battle_type='pve.dao_union_challenge' "
                "AND start_operation_id=? AND status='settled'",
                (player_id, source_operation_id),
            ).fetchone()
            if row is None or str(row["battle_id"]) != evidence_id:
                return False
            result = self._json_object(row["result_json"], {})
            if str(result.get("outcome", "")) != "won":
                return False
            actual_at = str(row["starts_at"])
        elif task_key == "task.dao_origin.build":
            if source_kind != "livelihood_project_rewards" or not isinstance(source_key, str):
                return False
            row = connection.execute(
                "SELECT r.project_id, r.created_at, p.project_key FROM livelihood_project_rewards r "
                "JOIN livelihood_projects p ON p.project_id=r.project_id "
                "WHERE r.player_id=? AND r.operation_id=? AND r.eligible=1",
                (player_id, source_operation_id),
            ).fetchone()
            if row is None or str(row["project_id"]) != evidence_id or str(row["project_key"]) != source_key:
                return False
            actual_at = str(row["created_at"])
        elif task_key == "task.dao_origin.teach":
            if source_kind != "mentor_relations":
                return False
            row = connection.execute(
                "SELECT relation_id, graduated_at FROM mentor_relations "
                "WHERE master_id=? AND graduate_operation_id=? AND status='graduated'",
                (player_id, source_operation_id),
            ).fetchone()
            if row is None or str(row["relation_id"]) != evidence_id:
                return False
            actual_at = str(row["graduated_at"])
        else:
            return False
        try:
            return datetime.fromisoformat(actual_at).astimezone(timezone.utc) == occurred_at
        except (TypeError, ValueError):
            return False

    def _dao_origin_qualification_snapshot(
        self,
        connection: sqlite3.Connection,
        player_id: int,
        season_id: str,
        season_start: datetime,
        season_end: datetime,
        task_keys: tuple[str, ...],
        readiness_flag: str,
    ) -> tuple[dict[str, object], dict[str, int]]:
        content = self.content or bundled_content()
        tasks: list[dict[str, object]] = []
        progress: dict[str, int] = {}
        for task_key in task_keys:
            definition = dao_origin_task_definition(task_key, content)
            count, task_snapshot = self._dao_origin_task_progress(
                connection, player_id, task_key, season_id
            )
            if task_snapshot is None:
                task_snapshot = definition.snapshot(season_id)
            if task_snapshot["key"] != task_key or task_snapshot["season_id"] != season_id:
                raise ContentError(f"dao-origin task snapshot is inconsistent: {task_key}")
            evidence = self._dao_origin_task_evidence(
                connection, player_id, task_key, season_id, season_start, season_end
            )
            if len(evidence) != count:
                raise ContentError(f"dao-origin task evidence differs from progress: {task_key}")
            target = int(task_snapshot["target"])
            progress[task_key] = count
            tasks.append(
                {
                    "key": task_key,
                    "name": str(task_snapshot["name"]),
                    "target": target,
                    "completed": count,
                    "ready": count >= target,
                    "task_snapshot": dict(task_snapshot),
                    "evidence": evidence,
                }
            )
        return (
            {
                "season_id": season_id,
                "starts_at": serialize_datetime(season_start),
                "ends_at": serialize_datetime(season_end),
                "readiness_flag": readiness_flag,
                "tasks": tasks,
            },
            progress,
        )

    def _get_dao_origin_qualification_sync(
        self, platform: str, platform_user_id: str
    ) -> DaoOriginSeasonQualificationRecord:
        now = self._now()
        season_id, season_start, season_end = final_heaven_season_window(now)
        with self._connect() as connection:
            player = self._require_player(connection, platform, platform_user_id, writable=False)
            task_keys, readiness_flag = self._dao_origin_qualification_config()
            row = connection.execute(
                "SELECT status, readiness_flag, snapshot_json FROM dao_origin_qualifications "
                "WHERE player_id = ? AND season_id = ?",
                (player["id"], season_id),
            ).fetchone()
            if row is not None:
                try:
                    snapshot = json.loads(row["snapshot_json"] or "{}")
                except (TypeError, json.JSONDecodeError) as exc:
                    raise ContentError("dao-origin qualification snapshot cannot be read") from exc
                if not isinstance(snapshot, dict):
                    raise ContentError("dao-origin qualification snapshot is invalid")
                progress = {
                    str(task["key"]): int(task["completed"])
                    for task in snapshot.get("tasks", ())
                    if isinstance(task, dict) and "key" in task and "completed" in task
                }
                return self._dao_origin_qualification_from_payload(
                    {
                        "player": self._player_payload(self._row_to_player(player)),
                        "season_id": season_id,
                        "status": str(row["status"]),
                        "readiness_flag": str(row["readiness_flag"]),
                        "progress": progress,
                        "snapshot": snapshot,
                    }
                )
            snapshot, progress = self._dao_origin_qualification_snapshot(
                connection,
                int(player["id"]),
                season_id,
                season_start,
                season_end,
                task_keys,
                readiness_flag,
            )
            status = "ready" if all(
                int(task["completed"]) >= int(task["target"])
                for task in snapshot["tasks"]
            ) else "pending"
            return self._dao_origin_qualification_from_payload(
                {
                    "player": self._player_payload(self._row_to_player(player)),
                    "season_id": season_id,
                    "status": status,
                    "readiness_flag": readiness_flag,
                    "progress": progress,
                    "snapshot": snapshot,
                }
            )

    def _claim_dao_origin_qualification_sync(
        self, platform: str, platform_user_id: str, operation_id: str
    ) -> DaoOriginSeasonQualificationRecord:
        operation_name = "quest.dao_origin.qualification.claim"
        request_hash = self._request_hash(
            operation_name,
            {"platform": platform, "platform_user_id": platform_user_id},
        )
        now = self._now()
        now_text = serialize_datetime(now)
        season_id, season_start, season_end = final_heaven_season_window(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._quest_operation_replay(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                return self._dao_origin_qualification_from_payload(replay, replay=True)
            player = self._require_player(connection, platform, platform_user_id)
            task_keys, readiness_flag = self._dao_origin_qualification_config()
            existing = connection.execute(
                "SELECT 1 FROM dao_origin_qualifications WHERE player_id = ? AND season_id = ?",
                (player["id"], season_id),
            ).fetchone()
            if existing is not None:
                raise DaoOriginQualificationAlreadyClaimedError(
                    "dao-origin qualification is already claimed for this season"
                )
            snapshot, progress = self._dao_origin_qualification_snapshot(
                connection,
                int(player["id"]),
                season_id,
                season_start,
                season_end,
                task_keys,
                readiness_flag,
            )
            if any(
                int(task["completed"]) < int(task["target"])
                for task in snapshot["tasks"]
            ):
                raise DaoOriginQualificationIncompleteError(
                    "all final-heaven dao-origin tasks must be complete"
                )
            snapshot["qualified_at"] = now_text
            flags_state = self._json_object(player["intro_json"], {})
            flags = [str(value) for value in flags_state.get("flags", ())]
            if readiness_flag not in flags:
                flags.append(readiness_flag)
            flags_state["flags"] = flags
            connection.execute(
                "UPDATE players SET intro_json = ?, updated_at = ? WHERE id = ?",
                (json.dumps(flags_state, ensure_ascii=False, sort_keys=True), now_text, player["id"]),
            )
            connection.execute(
                "INSERT INTO dao_origin_qualifications("
                "player_id, season_id, readiness_flag, status, snapshot_json, operation_id, created_at, updated_at) "
                "VALUES (?, ?, ?, 'qualified', ?, ?, ?, ?)",
                (
                    player["id"],
                    season_id,
                    readiness_flag,
                    json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
                    operation_id,
                    now_text,
                    now_text,
                ),
            )
            connection.execute(
                "INSERT INTO activity_events(player_id, event_key, source_operation_id, occurred_at, payload_json) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    player["id"],
                    "season.final_heaven.dao_origin_qualified",
                    operation_id,
                    now_text,
                    json.dumps(
                        {"season_id": season_id, "readiness_flag": readiness_flag, "snapshot": snapshot},
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                ),
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (player["id"],)).fetchone()
            payload = {
                "player": self._player_payload(self._row_to_player(updated)),
                "season_id": season_id,
                "status": "qualified",
                "readiness_flag": readiness_flag,
                "progress": progress,
                "snapshot": snapshot,
            }
            self._insert_operation(
                connection,
                operation_id=operation_id,
                operation_name=operation_name,
                player_id=int(player["id"]),
                request_hash=request_hash,
                payload=payload,
                now_text=now_text,
            )
            return self._dao_origin_qualification_from_payload(payload)

    def _dao_origin_task_seasons(
        self, connection: sqlite3.Connection, player_id: int, task_key: str
    ) -> dict[str, tuple[int, dict[str, Any]]]:
        rows = connection.execute(
            "SELECT source_operation_id, payload_json FROM quest_events WHERE player_id = ? AND quest_key = ? "
            "AND component_key = 'completed' AND outcome = 'success'",
            (player_id, task_key),
        ).fetchall()
        seasons: dict[str, tuple[int, dict[str, Any]]] = {}
        seen_operations: set[tuple[str, str]] = set()
        for row in rows:
            try:
                payload = json.loads(row["payload_json"])
            except (TypeError, json.JSONDecodeError) as exc:
                raise ContentError(f"dao-origin task event cannot be read: {task_key}") from exc
            snapshot = dao_origin_task_snapshot_from_event(task_key, payload)
            season_id = snapshot["season_id"]
            source_operation_id = str(row["source_operation_id"] or "")
            if not source_operation_id or (season_id, source_operation_id) in seen_operations:
                raise ContentError(f"dao-origin task evidence is duplicated: {task_key}")
            seen_operations.add((season_id, source_operation_id))
            count, previous = seasons.get(season_id, (0, snapshot))
            if previous != snapshot or count >= snapshot["target"]:
                raise ContentError(f"dao-origin task events are inconsistent: {task_key}")
            seasons[season_id] = (count + 1, snapshot)
        return seasons

    def _dao_origin_task_progress(
        self,
        connection: sqlite3.Connection,
        player_id: int,
        task_key: str,
        season_id: str,
    ) -> tuple[int, dict[str, Any] | None]:
        count, evidence_snapshot = self._dao_origin_task_seasons(
            connection, player_id, task_key
        ).get(season_id, (0, None))
        row = connection.execute(
            "SELECT snapshot_json FROM quest_progress WHERE player_id = ? AND quest_key = ?",
            (player_id, task_key),
        ).fetchone()
        if row is None:
            if count:
                raise ContentError(f"dao-origin task progress snapshot is missing: {task_key}")
            return 0, None
        try:
            value = json.loads(row["snapshot_json"])
        except (TypeError, json.JSONDecodeError) as exc:
            raise ContentError(f"dao-origin task progress snapshot cannot be read: {task_key}") from exc
        snapshot = parse_dao_origin_task_snapshot(task_key, value)
        if snapshot["season_id"] == season_id:
            if snapshot != evidence_snapshot:
                raise ContentError(f"dao-origin task progress differs from its events: {task_key}")
            return count, snapshot
        if count:
            raise ContentError(f"dao-origin task events differ from progress snapshot: {task_key}")
        return 0, None

    def _find_dao_origin_source(
        self,
        connection: sqlite3.Connection,
        player_id: int,
        task_key: str,
        season_id: str,
        season_start: datetime,
        season_end: datetime,
    ) -> dict[str, object] | None:
        consumed = {
            str(row["source_operation_id"])
            for row in connection.execute(
                "SELECT source_operation_id FROM quest_events WHERE player_id = ? AND quest_key = ?",
                (player_id, task_key),
            ).fetchall()
        }
        if task_key == "task.dao_origin.guard":
            candidates = connection.execute(
                "SELECT battle_id AS evidence_id, start_operation_id AS source_operation_id, "
                "starts_at AS occurred_at, result_json FROM battle_sessions "
                "WHERE player_id = ? AND battle_type = 'pve.dao_union_challenge' "
                "AND status = 'settled' AND location_key = 'cave.boundary_realm' ORDER BY id",
                (player_id,),
            ).fetchall()
            source_kind = "battle_sessions"
        elif task_key == "task.dao_origin.build":
            candidates = connection.execute(
                "SELECT p.project_id AS evidence_id, r.operation_id AS source_operation_id, "
                "r.created_at AS occurred_at, p.project_key AS source_key "
                "FROM livelihood_project_rewards r JOIN livelihood_projects p ON p.project_id = r.project_id "
                "WHERE r.player_id = ? AND r.eligible = 1 ORDER BY r.id",
                (player_id,),
            ).fetchall()
            source_kind = "livelihood_project_rewards"
        elif task_key == "task.dao_origin.teach":
            candidates = connection.execute(
                "SELECT relation_id AS evidence_id, graduate_operation_id AS source_operation_id, "
                "graduated_at AS occurred_at FROM mentor_relations "
                "WHERE master_id = ? AND status = 'graduated' AND graduate_operation_id IS NOT NULL ORDER BY id",
                (player_id,),
            ).fetchall()
            source_kind = "mentor_relations"
        else:
            return None

        for candidate in candidates:
            source_operation_id = str(candidate["source_operation_id"] or "")
            if not source_operation_id or source_operation_id in consumed:
                continue
            if task_key == "task.dao_origin.guard":
                result = self._json_object(candidate["result_json"], {})
                if str(result.get("outcome", "")) != "won":
                    continue
            try:
                occurred_at = datetime.fromisoformat(str(candidate["occurred_at"])).astimezone(timezone.utc)
            except (TypeError, ValueError):
                continue
            if not season_start <= occurred_at < season_end:
                continue
            source = {
                "source_kind": source_kind,
                "source_operation_id": source_operation_id,
                "evidence_id": str(candidate["evidence_id"]),
                "season_id": season_id,
                "occurred_at": str(candidate["occurred_at"]),
            }
            if task_key == "task.dao_origin.build":
                source["source_key"] = str(candidate["source_key"])
            return source
        return None

    @staticmethod
    def _dao_union_from_payload(payload: dict[str, Any], replay: bool = False) -> DaoUnionQualificationRecord:
        from ..repository import SQLitePlayerRepository

        return DaoUnionQualificationRecord(
            player=SQLitePlayerRepository._row_to_player(payload["player"]),
            quest_key=str(payload["quest_key"]),
            status=str(payload["status"]),
            progress={str(key): int(value) for key, value in dict(payload.get("progress", {})).items()},
            snapshot=dict(payload.get("snapshot", {})),
            reward={str(key): int(value) for key, value in dict(payload.get("reward", {})).items()},
            already_completed=replay,
        )

    @staticmethod
    def _dao_origin_qualification_from_payload(
        payload: dict[str, Any], replay: bool = False
    ) -> DaoOriginSeasonQualificationRecord:
        from ..repository import SQLitePlayerRepository

        return DaoOriginSeasonQualificationRecord(
            player=SQLitePlayerRepository._row_to_player(payload["player"]),
            season_id=str(payload["season_id"]),
            status=str(payload.get("status", "pending")),
            readiness_flag=str(payload.get("readiness_flag", "")),
            progress={
                str(key): int(value)
                for key, value in dict(payload.get("progress", {})).items()
            },
            snapshot=dict(payload.get("snapshot", {})),
            already_completed=replay,
        )


__all__ = ["EndgameQuestRepositoryMixin"]
