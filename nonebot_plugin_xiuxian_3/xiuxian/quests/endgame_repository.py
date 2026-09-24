"""SQLite transactions for dao-union qualification and dao-origin tasks."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from ...contracts import serialize_datetime
from ..events.rules import final_heaven_season_window
from ..persistence.errors import (
    DaoOriginTaskRequirementError,
    QuestAlreadyCompletedError,
    QuestNotCompletedError,
    QuestRequirementError,
    QuestResourceInsufficientError,
)
from .models import DaoUnionQualificationRecord, QuestActionRecord
from .rules import (
    DAO_ORIGIN_CONTENT_VERSION,
    DAO_ORIGIN_REWARDS,
    DAO_ORIGIN_RULE_VERSION,
    DAO_ORIGIN_TARGET,
    DAO_ORIGIN_TASKS,
    DAO_ORIGIN_WORLD_MERIT,
    DAO_UNION_CHALLENGE,
    DAO_UNION_CONTENT_VERSION,
    DAO_UNION_MAINLINE,
    DAO_UNION_MAINLINE_CONTENT_VERSION,
    DAO_UNION_MAINLINE_LANES,
    DAO_UNION_MAINLINE_RULE_VERSION,
    DAO_UNION_MAINLINE_STAGE_KEYS,
    DAO_UNION_MAINLINE_STORY_KEY,
    DAO_UNION_QUEST,
    DAO_UNION_RULE_VERSION,
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
            or payload.get("content_version") != DAO_UNION_MAINLINE_CONTENT_VERSION
            or payload.get("rule_version") != DAO_UNION_MAINLINE_RULE_VERSION
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
            if not meets_realm(str(player["realm_key"]), int(player["realm_layer"]), "void_refining", 10):
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
                    "SELECT stage_key FROM mainline_runs WHERE player_id=? AND story_key=? AND status='claimed' "
                    "AND content_version=? AND rule_version=?",
                    (
                        player["id"],
                        DAO_UNION_MAINLINE_STORY_KEY,
                        DAO_UNION_MAINLINE_CONTENT_VERSION,
                        DAO_UNION_MAINLINE_RULE_VERSION,
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
                    "content_version": DAO_UNION_MAINLINE_CONTENT_VERSION,
                    "rule_version": DAO_UNION_MAINLINE_RULE_VERSION,
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
                inventory = self._json_object(player["inventory_json"], {})
                if not work_key or int(inventory.get(work_key, 0)) < 1:
                    raise QuestResourceInsufficientError("profession endgame work is missing")
                inventory[work_key] = int(inventory[work_key]) - 1
                if inventory[work_key] == 0:
                    inventory.pop(work_key)
                connection.execute(
                    "UPDATE players SET inventory_json = ?, updated_at = ? WHERE id = ?",
                    (json.dumps(inventory, ensure_ascii=False, sort_keys=True), now_text, player["id"]),
                )
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
                content_version=DAO_UNION_CONTENT_VERSION,
                rule_version=DAO_UNION_RULE_VERSION,
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
                content_version=DAO_UNION_CONTENT_VERSION,
                rule_version=DAO_UNION_RULE_VERSION,
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
            snapshot = {
                "path_key": player["path_key"],
                "subprofession_key": player["subprofession_key"],
                "realm_key": str(player["realm_key"]),
                "realm_layer": int(player["realm_layer"]),
                "components": progress,
                "content_version": DAO_UNION_CONTENT_VERSION,
                "rule_version": DAO_UNION_RULE_VERSION,
            }
            flags_state = self._json_object(player["intro_json"], {})
            flags = set(str(item) for item in flags_state.get("flags", []))
            flags.add(DAO_UNION_QUEST)
            flags_state["flags"] = sorted(flags)
            connection.execute(
                "UPDATE players SET intro_json = ?, updated_at = ? WHERE id = ?",
                (json.dumps(flags_state, ensure_ascii=False, sort_keys=True), now_text, player["id"]),
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
                content_version=DAO_UNION_CONTENT_VERSION,
                rule_version=DAO_UNION_RULE_VERSION,
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (player["id"],)).fetchone()
            payload = {
                "player": self._player_payload(self._row_to_player(updated)),
                "quest_key": DAO_UNION_QUEST,
                "status": "completed",
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
            if not meets_realm(str(player["realm_key"]), int(player["realm_layer"]), "dao_union"):
                raise DaoOriginTaskRequirementError("dao-origin tasks require 合道")
            if str(player["endgame_status"] or "none") not in {"dao_union", "tribulation"}:
                raise DaoOriginTaskRequirementError("dao-origin tasks require an active endgame route")
            count = self._dao_origin_task_count(connection, int(player["id"]), task_key, season_id)
            if count >= DAO_ORIGIN_TARGET:
                raise QuestAlreadyCompletedError("dao-origin task is already complete for this season")
            source = self._find_dao_origin_source(
                connection, int(player["id"]), task_key, season_id, season_start, season_end
            )
            if source is None:
                raise QuestNotCompletedError("no eligible server activity is available for this dao-origin task")
            count += 1
            reward = dict(DAO_ORIGIN_REWARDS[task_key]) if count == DAO_ORIGIN_TARGET else {}
            world_merit_reward = DAO_ORIGIN_WORLD_MERIT[task_key] if count == DAO_ORIGIN_TARGET else 0
            connection.execute(
                "UPDATE players SET dao_fruit_progress = dao_fruit_progress + ?, ascension_merit = ascension_merit + ?, world_merit = world_merit + ?, updated_at = ? WHERE id = ?",
                (int(reward.get("dao_fruit_progress", 0)), int(reward.get("ascension_merit", 0)), world_merit_reward, now_text, player["id"]),
            )
            if world_merit_reward:
                reward["world_merit"] = world_merit_reward
            self._insert_quest_event(
                connection,
                player_id=int(player["id"]),
                quest_key=task_key,
                component_key="completed",
                source_operation_id=str(source["source_operation_id"]),
                outcome="success",
                payload={"count": count, "reward": reward, "event_key": "event.dao_origin", **source},
                now_text=now_text,
                content_version=DAO_ORIGIN_CONTENT_VERSION,
                rule_version=DAO_ORIGIN_RULE_VERSION,
            )
            self._insert_quest_event(
                connection,
                player_id=int(player["id"]),
                quest_key="event.dao_origin",
                component_key=task_key,
                source_operation_id=str(source["source_operation_id"]),
                outcome="success",
                payload={"count": count, "reward": reward, **source},
                now_text=now_text,
                content_version=DAO_ORIGIN_CONTENT_VERSION,
                rule_version=DAO_ORIGIN_RULE_VERSION,
            )
            progress = {"completed": count}
            self._upsert_progress(
                connection,
                int(player["id"]),
                task_key,
                "completed" if count >= DAO_ORIGIN_TARGET else "active",
                progress,
                {
                    "target": DAO_ORIGIN_TARGET,
                    "season_id": season_id,
                    "reward": DAO_ORIGIN_REWARDS[task_key],
                    "world_merit_on_completion": DAO_ORIGIN_WORLD_MERIT[task_key],
                },
                operation_id,
                now_text,
                content_version=DAO_ORIGIN_CONTENT_VERSION,
                rule_version=DAO_ORIGIN_RULE_VERSION,
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (player["id"],)).fetchone()
            payload = self._action_payload(
                updated,
                task_key,
                "completed",
                progress,
                reward,
                status="completed" if count >= DAO_ORIGIN_TARGET else "active",
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

    def _dao_origin_task_count(
        self, connection: sqlite3.Connection, player_id: int, task_key: str, season_id: str
    ) -> int:
        rows = connection.execute(
            "SELECT payload_json FROM quest_events WHERE player_id = ? AND quest_key = ? "
            "AND component_key = 'completed' AND outcome = 'success'",
            (player_id, task_key),
        ).fetchall()
        return sum(
            1
            for row in rows
            if self._json_object(row["payload_json"], {}).get("season_id") == season_id
        )

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
            already_completed=replay,
        )


__all__ = ["EndgameQuestRepositoryMixin"]
