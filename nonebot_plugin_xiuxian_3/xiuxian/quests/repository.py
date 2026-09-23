"""SQLite transactions for high-realm quest producers and permits."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from typing import Any

from ...contracts import serialize_datetime
from ..events.rules import final_heaven_season_window
from ..persistence.errors import (
    OperationConflictError,
    PlayerNotFoundError,
    QuestAlreadyCompletedError,
    QuestNotCompletedError,
    QuestRequirementError,
    QuestResourceInsufficientError,
)
from .endgame_repository import EndgameQuestRepositoryMixin
from .models import QuestActionRecord, QuestClaimRecord, QuestStatusRecord
from .rules import (
    ANCIENT_DOMAIN_LINE,
    ANCIENT_DOMAIN_TARGET,
    CONTENT_VERSION,
    CROSS_REALM_VICTORY,
    DOMAIN_COMMISSION,
    DOMAIN_COMMISSION_TARGET,
    RULE_VERSION,
    SOUL_QUEST,
    VOID_ARCHIVE_DELIVERY,
    VOID_QUEST,
    VOID_TRIAL_TARGET,
    VOID_WALL_TRIAL,
    DAO_ORIGIN_TARGET,
    DAO_ORIGIN_TASKS,
    DAO_UNION_QUEST,
    meets_realm,
)


class QuestRepositoryMixin(EndgameQuestRepositoryMixin):
    """Keep quest state separate from the compatibility repository facade."""

    async def get_advanced_quests(self, *, platform: str, platform_user_id: str) -> QuestStatusRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._get_advanced_quests_sync, platform, platform_user_id)

    async def complete_domain_material_commission(
        self, *, platform: str, platform_user_id: str, operation_id: str
    ) -> QuestActionRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._complete_domain_material_commission_sync,
                platform,
                platform_user_id,
                operation_id,
            )

    async def complete_ancient_domain_line(
        self, *, platform: str, platform_user_id: str, operation_id: str
    ) -> QuestActionRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._complete_ancient_domain_line_sync,
                platform,
                platform_user_id,
                operation_id,
            )

    async def record_cross_realm_victory(
        self, *, platform: str, platform_user_id: str, operation_id: str, battle_id: str
    ) -> QuestActionRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._record_cross_realm_victory_sync,
                platform,
                platform_user_id,
                operation_id,
                battle_id,
            )

    async def record_void_wall_trial(
        self,
        *,
        platform: str,
        platform_user_id: str,
        operation_id: str,
        battle_id: str,
        outcome: str,
    ) -> QuestActionRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._record_void_wall_trial_sync,
                platform,
                platform_user_id,
                operation_id,
                battle_id,
                outcome,
            )

    async def acquire_void_archive(
        self, *, platform: str, platform_user_id: str, operation_id: str
    ) -> QuestActionRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._acquire_void_archive_sync,
                platform,
                platform_user_id,
                operation_id,
            )

    async def deliver_void_archive(
        self, *, platform: str, platform_user_id: str, operation_id: str
    ) -> QuestActionRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._deliver_void_archive_sync,
                platform,
                platform_user_id,
                operation_id,
            )

    async def claim_soul_transformation_quest(
        self, *, platform: str, platform_user_id: str, operation_id: str
    ) -> QuestClaimRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._claim_soul_transformation_quest_sync,
                platform,
                platform_user_id,
                operation_id,
            )

    async def claim_void_refining_quest(
        self, *, platform: str, platform_user_id: str, operation_id: str
    ) -> QuestClaimRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._claim_void_refining_quest_sync,
                platform,
                platform_user_id,
                operation_id,
            )

    def _get_advanced_quests_sync(self, platform: str, platform_user_id: str) -> QuestStatusRecord:
        with self._connect() as connection:
            player = self._require_player(connection, platform, platform_user_id, writable=False)
            return QuestStatusRecord(
                player=self._row_to_player(player),
                quests=self._quest_status_payload(connection, int(player["id"])),
            )

    def _complete_domain_material_commission_sync(
        self, platform: str, platform_user_id: str, operation_id: str
    ) -> QuestActionRecord:
        return self._record_component_sync(
            platform,
            platform_user_id,
            operation_id,
            quest_key=DOMAIN_COMMISSION,
            component_key="completed",
            required_realm="nascent_soul",
            target=DOMAIN_COMMISSION_TARGET,
            outcome="success",
            reward_on_target={"item.ancient_fruit": 1},
        )

    def _complete_ancient_domain_line_sync(
        self, platform: str, platform_user_id: str, operation_id: str
    ) -> QuestActionRecord:
        return self._record_component_sync(
            platform,
            platform_user_id,
            operation_id,
            quest_key=ANCIENT_DOMAIN_LINE,
            component_key="success",
            required_realm="nascent_soul",
            target=ANCIENT_DOMAIN_TARGET,
            outcome="success",
            final_material_cost={"item.soul_crystal": 3},
        )

    def _record_cross_realm_victory_sync(
        self, platform: str, platform_user_id: str, operation_id: str, battle_id: str
    ) -> QuestActionRecord:
        return self._record_component_sync(
            platform,
            platform_user_id,
            operation_id,
            quest_key=CROSS_REALM_VICTORY,
            component_key="victory",
            required_realm="nascent_soul",
            target=1,
            outcome="success",
            payload_extra={"battle_id": battle_id},
            evidence_battle_id=battle_id,
            evidence_battle_type="pve.cross_realm",
            evidence_outcome="won",
        )

    def _record_void_wall_trial_sync(
        self,
        platform: str,
        platform_user_id: str,
        operation_id: str,
        battle_id: str,
        outcome: str,
    ) -> QuestActionRecord:
        return self._record_component_sync(
            platform,
            platform_user_id,
            operation_id,
            quest_key=VOID_QUEST,
            component_key=VOID_WALL_TRIAL,
            required_realm="soul_transformation",
            target=VOID_TRIAL_TARGET,
            outcome=outcome if outcome in {"won", "lost"} else "lost",
            payload_extra={"battle_id": battle_id},
            evidence_battle_id=battle_id,
            evidence_battle_type="pve.void_wall_trial",
        )

    def _acquire_void_archive_sync(
        self, platform: str, platform_user_id: str, operation_id: str
    ) -> QuestActionRecord:
        operation_name = "explore.archive_ruins"
        request_hash = self._request_hash(operation_name, {"platform": platform, "platform_user_id": platform_user_id})
        now = self._now()
        now_text = serialize_datetime(now)
        season_id, season_start, season_end = final_heaven_season_window(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._quest_operation_replay(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                return self._action_from_payload(replay, replay=True)
            player = self._require_player(connection, platform, platform_user_id)
            if not meets_realm(str(player["realm_key"]), int(player["realm_layer"]), "soul_transformation"):
                raise QuestRequirementError("archive ruins require soul transformation")
            if self._event_count(connection, int(player["id"]), VOID_QUEST, "archive_source") >= 1:
                raise QuestAlreadyCompletedError("archive source is already claimed")
            inventory = self._json_object(player["inventory_json"], {})
            inventory["item.void_archive"] = int(inventory.get("item.void_archive", 0)) + 1
            connection.execute(
                "UPDATE players SET inventory_json = ?, updated_at = ? WHERE id = ?",
                (json.dumps(inventory, ensure_ascii=False, sort_keys=True), now_text, player["id"]),
            )
            self._insert_quest_event(
                connection,
                player_id=int(player["id"]),
                quest_key=VOID_QUEST,
                component_key="archive_source",
                source_operation_id=operation_id,
                outcome="success",
                payload={"item.void_archive": 1, "source": "explore.archive_ruins"},
                now_text=now_text,
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (player["id"],)).fetchone()
            payload = self._action_payload(
                updated,
                VOID_QUEST,
                "archive_source",
                self._component_progress(connection, int(player["id"]), VOID_QUEST, VOID_WALL_TRIAL),
                {"item.void_archive": 1},
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

    def _deliver_void_archive_sync(
        self, platform: str, platform_user_id: str, operation_id: str
    ) -> QuestActionRecord:
        operation_name = "quest.break_void.deliver_archive"
        request_hash = self._request_hash(operation_name, {"platform": platform, "platform_user_id": platform_user_id})
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._quest_operation_replay(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                return self._action_from_payload(replay, replay=True)
            player = self._require_player(connection, platform, platform_user_id)
            if self._event_count(connection, int(player["id"]), VOID_QUEST, VOID_WALL_TRIAL) < VOID_TRIAL_TARGET:
                raise QuestNotCompletedError("three wall trials are required")
            inventory = self._json_object(player["inventory_json"], {})
            if int(inventory.get("item.void_archive", 0)) < 1:
                raise QuestResourceInsufficientError("void archive is missing")
            inventory["item.void_archive"] = int(inventory["item.void_archive"]) - 1
            if not inventory["item.void_archive"]:
                inventory.pop("item.void_archive")
            connection.execute(
                "UPDATE players SET inventory_json = ?, updated_at = ? WHERE id = ?",
                (json.dumps(inventory, ensure_ascii=False, sort_keys=True), now_text, player["id"]),
            )
            self._insert_quest_event(
                connection,
                player_id=int(player["id"]),
                quest_key=VOID_QUEST,
                component_key=VOID_ARCHIVE_DELIVERY,
                source_operation_id=operation_id,
                outcome="success",
                payload={"item.void_archive": 1},
                now_text=now_text,
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (player["id"],)).fetchone()
            payload = self._action_payload(
                updated,
                VOID_QUEST,
                VOID_ARCHIVE_DELIVERY,
                self._component_progress(connection, int(player["id"]), VOID_QUEST, VOID_WALL_TRIAL),
                {},
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

    def _claim_soul_transformation_quest_sync(
        self, platform: str, platform_user_id: str, operation_id: str
    ) -> QuestClaimRecord:
        return self._claim_permit_sync(
            platform,
            platform_user_id,
            operation_id,
            quest_key=SOUL_QUEST,
            requirements=(
                (DOMAIN_COMMISSION, "completed", DOMAIN_COMMISSION_TARGET),
                (ANCIENT_DOMAIN_LINE, "success", ANCIENT_DOMAIN_TARGET),
                (CROSS_REALM_VICTORY, "victory", 1),
            ),
        )

    def _claim_void_refining_quest_sync(
        self, platform: str, platform_user_id: str, operation_id: str
    ) -> QuestClaimRecord:
        return self._claim_permit_sync(
            platform,
            platform_user_id,
            operation_id,
            quest_key=VOID_QUEST,
            requirements=((VOID_QUEST, VOID_WALL_TRIAL, VOID_TRIAL_TARGET), (VOID_QUEST, VOID_ARCHIVE_DELIVERY, 1)),
        )


    def _record_component_sync(
        self,
        platform: str,
        platform_user_id: str,
        operation_id: str,
        *,
        quest_key: str,
        component_key: str,
        required_realm: str,
        target: int,
        outcome: str,
        reward_on_target: dict[str, int] | None = None,
        final_material_cost: dict[str, int] | None = None,
        payload_extra: dict[str, object] | None = None,
        evidence_battle_id: str | None = None,
        evidence_battle_type: str | None = None,
        evidence_outcome: str | None = None,
    ) -> QuestActionRecord:
        operation_name = quest_key if quest_key.startswith("quest.") else f"quest.{quest_key}"
        request_payload = {
            "platform": platform,
            "platform_user_id": platform_user_id,
            "quest_key": quest_key,
            "component_key": component_key,
            "outcome": outcome,
            **(payload_extra or {}),
        }
        request_hash = self._request_hash(operation_name, request_payload)
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._quest_operation_replay(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                return self._action_from_payload(replay, replay=True)
            player = self._require_player(connection, platform, platform_user_id)
            if not meets_realm(str(player["realm_key"]), int(player["realm_layer"]), required_realm):
                raise QuestRequirementError(f"{quest_key} requires {required_realm}")
            if evidence_battle_id is not None:
                battle = connection.execute(
                    "SELECT player_id, battle_type, status, result_json FROM battle_sessions WHERE battle_id = ?",
                    (evidence_battle_id,),
                ).fetchone()
                if battle is None or int(battle["player_id"]) != int(player["id"]):
                    raise QuestRequirementError("battle evidence does not belong to this player")
                if str(battle["battle_type"]) != evidence_battle_type or str(battle["status"]) != "settled":
                    raise QuestRequirementError("battle evidence is not settled")
                battle_result = self._json_object(battle["result_json"], {})
                actual_outcome = str(battle_result.get("outcome", "lost"))
                if evidence_outcome is not None and actual_outcome != evidence_outcome:
                    raise QuestRequirementError("battle evidence outcome is not eligible")
                if quest_key == VOID_QUEST:
                    outcome = actual_outcome
            count = self._event_count(connection, int(player["id"]), quest_key, component_key)
            if count >= target:
                raise QuestAlreadyCompletedError("quest component reached its target")
            final_cost_due = final_material_cost and count + 1 >= target
            if final_cost_due:
                inventory = self._json_object(player["inventory_json"], {})
                missing = [key for key, amount in final_material_cost.items() if int(inventory.get(key, 0)) < amount]
                if missing:
                    raise QuestResourceInsufficientError("quest material is missing")
                for key, amount in final_material_cost.items():
                    inventory[key] = int(inventory[key]) - amount
                    if not inventory[key]:
                        inventory.pop(key)
            else:
                inventory = self._json_object(player["inventory_json"], {})
            count += 1
            reward = dict(reward_on_target or {}) if count >= target else {}
            for key, amount in reward.items():
                inventory[key] = int(inventory.get(key, 0)) + int(amount)
            if final_cost_due or reward:
                connection.execute(
                    "UPDATE players SET inventory_json = ?, updated_at = ? WHERE id = ?",
                    (json.dumps(inventory, ensure_ascii=False, sort_keys=True), now_text, player["id"]),
                )
            self._insert_quest_event(
                connection,
                player_id=int(player["id"]),
                quest_key=quest_key,
                component_key=component_key,
                source_operation_id=operation_id,
                outcome=outcome,
                payload={"count": count, **(payload_extra or {})},
                now_text=now_text,
            )
            progress = {component_key: count}
            self._upsert_progress(
                connection,
                int(player["id"]),
                quest_key,
                "completed" if count >= target and quest_key != VOID_QUEST else "active",
                progress,
                {"target": target, "last_outcome": outcome},
                operation_id,
                now_text,
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (player["id"],)).fetchone()
            payload = self._action_payload(
                updated,
                quest_key,
                component_key,
                progress,
                reward,
                status="completed" if count >= target and quest_key != VOID_QUEST else "active",
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

    def _claim_permit_sync(
        self,
        platform: str,
        platform_user_id: str,
        operation_id: str,
        *,
        quest_key: str,
        requirements: tuple[tuple[str, str, int], ...],
    ) -> QuestClaimRecord:
        operation_name = f"{quest_key}.claim"
        request_hash = self._request_hash(operation_name, {"platform": platform, "platform_user_id": platform_user_id, "quest_key": quest_key})
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            if existing is not None:
                if existing["operation_name"] != operation_name or existing["request_hash"] != request_hash:
                    raise OperationConflictError("quest operation conflicts")
                return self._claim_from_payload(json.loads(existing["result_json"]), replay=True)
            player = self._require_player(connection, platform, platform_user_id)
            for source_quest, component, target in requirements:
                if self._event_count(connection, int(player["id"]), source_quest, component) < target:
                    raise QuestNotCompletedError("quest requirements are incomplete")
            existing_progress = connection.execute(
                "SELECT status, progress_json FROM quest_progress WHERE player_id = ? AND quest_key = ?",
                (player["id"], quest_key),
            ).fetchone()
            progress: dict[str, int] = {
                f"{source_quest}:{component}": self._event_count(connection, int(player["id"]), source_quest, component)
                for source_quest, component, _target in requirements
            }
            if existing_progress is not None and str(existing_progress["status"]) in {"completed", "claimed"}:
                raise QuestAlreadyCompletedError("quest permit is already claimed")
            flags_state = self._json_object(player["intro_json"], {})
            flags = [str(item) for item in flags_state.get("flags", [])]
            if quest_key not in flags:
                flags.append(quest_key)
            flags_state["flags"] = flags
            connection.execute(
                "UPDATE players SET intro_json = ?, updated_at = ? WHERE id = ?",
                (json.dumps(flags_state, ensure_ascii=False, sort_keys=True), now_text, player["id"]),
            )
            self._upsert_progress(
                connection,
                int(player["id"]),
                quest_key,
                "completed",
                progress,
                {"requirements": [list(item) for item in requirements]},
                operation_id,
                now_text,
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (player["id"],)).fetchone()
            payload = {
                "player": self._player_payload(self._row_to_player(updated)),
                "quest_key": quest_key,
                "status": "completed",
                "progress": progress,
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
            return self._claim_from_payload(payload)

    def _quest_status_payload(self, connection: sqlite3.Connection, player_id: int) -> dict[str, dict[str, object]]:
        result: dict[str, dict[str, object]] = {}
        for quest_key in (DOMAIN_COMMISSION, ANCIENT_DOMAIN_LINE, SOUL_QUEST, VOID_QUEST):
            result[quest_key] = self._quest_status_for_player(connection, player_id, quest_key)
        result[CROSS_REALM_VICTORY] = self._quest_status_for_player(connection, player_id, CROSS_REALM_VICTORY)
        for quest_key in (DAO_UNION_QUEST, *DAO_ORIGIN_TASKS):
            result[quest_key] = self._quest_status_for_player(connection, player_id, quest_key)
        season_id, _, _ = final_heaven_season_window(self._now())
        for task_key in DAO_ORIGIN_TASKS:
            count = self._dao_origin_task_count(connection, player_id, task_key, season_id)
            result[task_key].update(
                status="completed" if count >= DAO_ORIGIN_TARGET else "active",
                progress={"completed": count, "target": DAO_ORIGIN_TARGET},
                season_id=season_id,
            )
        return result


    def _quest_status_for_player(self, connection: sqlite3.Connection, player_id: int, quest_key: str) -> dict[str, object]:
        row = connection.execute(
            "SELECT status, progress_json, snapshot_json FROM quest_progress WHERE player_id = ? AND quest_key = ?",
            (player_id, quest_key),
        ).fetchone()
        events = connection.execute(
            "SELECT component_key, outcome, COUNT(*) AS count FROM quest_events WHERE player_id = ? AND quest_key = ? GROUP BY component_key, outcome",
            (player_id, quest_key),
        ).fetchall()
        counts: dict[str, int] = {}
        outcomes: dict[str, dict[str, int]] = {}
        for event in events:
            key = str(event["component_key"])
            amount = int(event["count"])
            counts[key] = counts.get(key, 0) + amount
            outcome = str(event["outcome"])
            outcomes.setdefault(key, {})[outcome] = amount
        return {
            "status": str(row["status"]) if row else "active",
            "progress": counts or (self._json_object(row["progress_json"], {}) if row else {}),
            "outcomes": outcomes,
            "snapshot": self._json_object(row["snapshot_json"], {}) if row else {},
        }

    def _component_progress(self, connection: sqlite3.Connection, player_id: int, quest_key: str, component_key: str) -> dict[str, int]:
        return {component_key: self._event_count(connection, player_id, quest_key, component_key)}

    @staticmethod
    def _event_count(connection: sqlite3.Connection, player_id: int, quest_key: str, component_key: str) -> int:
        row = connection.execute(
            "SELECT COUNT(*) AS count FROM quest_events WHERE player_id = ? AND quest_key = ? AND component_key = ?",
            (player_id, quest_key, component_key),
        ).fetchone()
        return int(row["count"]) if row else 0

    @staticmethod
    def _insert_quest_event(
        connection: sqlite3.Connection,
        *,
        player_id: int,
        quest_key: str,
        component_key: str,
        source_operation_id: str,
        outcome: str,
        payload: dict[str, object],
        now_text: str,
        content_version: str = CONTENT_VERSION,
        rule_version: str = RULE_VERSION,
    ) -> None:
        connection.execute(
            """
            INSERT INTO quest_events(
                player_id, quest_key, component_key, source_operation_id, outcome,
                payload_json, content_version, rule_version, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                player_id,
                quest_key,
                component_key,
                source_operation_id,
                outcome,
                json.dumps(payload, ensure_ascii=False, sort_keys=True),
                content_version,
                rule_version,
                now_text,
            ),
        )

    @staticmethod
    def _upsert_progress(
        connection: sqlite3.Connection,
        player_id: int,
        quest_key: str,
        status: str,
        progress: dict[str, object],
        snapshot: dict[str, object],
        source_operation_id: str,
        now_text: str,
        *,
        content_version: str = CONTENT_VERSION,
        rule_version: str = RULE_VERSION,
    ) -> None:
        connection.execute(
            """
            INSERT INTO quest_progress(
                player_id, quest_key, status, progress_json, snapshot_json,
                source_operation_id, content_version, rule_version, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(player_id, quest_key) DO UPDATE SET
                status = excluded.status,
                progress_json = excluded.progress_json,
                snapshot_json = excluded.snapshot_json,
                source_operation_id = excluded.source_operation_id,
                content_version = excluded.content_version,
                rule_version = excluded.rule_version,
                updated_at = excluded.updated_at
            """,
            (
                player_id,
                quest_key,
                status,
                json.dumps(progress, ensure_ascii=False, sort_keys=True),
                json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
                source_operation_id,
                content_version,
                rule_version,
                now_text,
                now_text,
            ),
        )

    @staticmethod
    def _quest_operation_replay(
        connection: sqlite3.Connection, operation_id: str, operation_name: str, request_hash: str
    ) -> dict[str, Any] | None:
        existing = connection.execute(
            "SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id = ?",
            (operation_id,),
        ).fetchone()
        if existing is None:
            return None
        if existing["operation_name"] != operation_name or existing["request_hash"] != request_hash:
            raise OperationConflictError("quest operation input differs from its original request")
        return json.loads(existing["result_json"])

    @staticmethod
    def _insert_operation(
        connection: sqlite3.Connection,
        operation_id: str,
        operation_name: str,
        player_id: int,
        request_hash: str,
        payload: dict[str, object],
        now_text: str,
    ) -> None:
        connection.execute(
            "INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (operation_id, operation_name, player_id, request_hash, json.dumps(payload, ensure_ascii=False, sort_keys=True), now_text),
        )

    def _action_payload(
        self,
        player: Any,
        quest_key: str,
        component_key: str,
        progress: dict[str, int],
        reward: dict[str, int],
        status: str | None = None,
    ) -> dict[str, object]:
        return {
            "player": self._player_payload(self._row_to_player(player)),
            "quest_key": quest_key,
            "component_key": component_key,
            "status": status or ("completed" if quest_key in {CROSS_REALM_VICTORY} or component_key in {"archive_source", VOID_ARCHIVE_DELIVERY} else "active"),
            "progress": progress,
            "reward": reward,
        }

    @staticmethod
    def _action_from_payload(payload: dict[str, Any], replay: bool = False) -> QuestActionRecord:
        from ..repository import SQLitePlayerRepository

        return QuestActionRecord(
            player=SQLitePlayerRepository._row_to_player(payload["player"]),
            quest_key=str(payload["quest_key"]),
            component_key=str(payload["component_key"]),
            status=str(payload.get("status", "active")),
            progress={str(key): int(value) for key, value in dict(payload.get("progress", {})).items()},
            reward={str(key): int(value) for key, value in dict(payload.get("reward", {})).items()},
            already_completed=replay,
        )

    @staticmethod
    def _claim_from_payload(payload: dict[str, Any], replay: bool = False) -> QuestClaimRecord:
        from ..repository import SQLitePlayerRepository

        return QuestClaimRecord(
            player=SQLitePlayerRepository._row_to_player(payload["player"]),
            quest_key=str(payload["quest_key"]),
            status=str(payload["status"]),
            progress={str(key): int(value) for key, value in dict(payload.get("progress", {})).items()},
            already_completed=replay,
        )


__all__ = ["QuestRepositoryMixin"]
