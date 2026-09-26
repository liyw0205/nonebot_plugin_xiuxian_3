"""Transactional persistence for the Yuan-ying three-realms mainline."""

from __future__ import annotations

import asyncio
import json
import sqlite3

from ...contracts import serialize_datetime
from ..persistence.errors import (
    MainlineAlreadyRunningError,
    MainlineContentClosedError,
    MainlineNotStartedError,
    MainlineRequirementError,
    OperationConflictError,
    PlayerNotFoundError,
    RepositoryBusyError,
)
from .mainline import meets_realm
from .mainline_models import MainlineClaimRecord, MainlineStageView, MainlineStartRecord
from .three_realms import (
    THREE_REALMS_LANE_FACTIONS,
    THREE_REALMS_LANE_LABELS,
    THREE_REALMS_LANES,
    THREE_REALMS_STAGES,
    THREE_REALMS_STORY_KEY,
    ThreeRealmsStage,
    three_realms_definition,
)
from .three_realms_models import ThreeRealmsLaneProgress, ThreeRealmsStatusRecord


class ThreeRealmsRepositoryMixin:
    async def get_three_realms_status(self, *, platform: str, platform_user_id: str) -> ThreeRealmsStatusRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._get_three_realms_status_sync, platform, platform_user_id)

    def _get_three_realms_status_sync(self, platform: str, platform_user_id: str) -> ThreeRealmsStatusRecord:
        with self._connect() as connection:
            player = self._require_player(connection, platform, platform_user_id, writable=False)
            return self._three_realms_status_from_connection(connection, player)

    @staticmethod
    def _three_realms_status_from_connection(connection: sqlite3.Connection, player: sqlite3.Row) -> ThreeRealmsStatusRecord:
        rows = {
            str(row["stage_key"]): row
            for row in connection.execute(
                "SELECT * FROM mainline_runs WHERE player_id=? AND story_key=?",
                (player["id"], THREE_REALMS_STORY_KEY),
            ).fetchall()
        }
        completed = {key for key, row in rows.items() if bool(row["first_clear_claimed"])}
        chosen_lane = next(
            (str(key).split(".")[1] for key, row in rows.items() if str(row["status"]) == "running" or bool(row["first_clear_claimed"])),
            None,
        )
        stages: list[MainlineStageView] = []
        lanes: list[ThreeRealmsLaneProgress] = []
        for lane in THREE_REALMS_LANES:
            lane_stages = tuple(stage for stage in THREE_REALMS_STAGES if stage.lane == lane)
            lane_completed = sum(1 for stage in lane_stages if stage.key in completed)
            next_stage = next((stage.stage for stage in lane_stages if stage.key not in completed), None)
            lanes.append(ThreeRealmsLaneProgress(lane, lane_completed, len(lane_stages), next_stage))
            for definition in lane_stages:
                run = rows.get(definition.key)
                claimed = definition.key in completed
                running = run is not None and str(run["status"]) == "running"
                available = (
                    str(player["realm_key"]) == "nascent_soul"
                    and int(player["realm_layer"]) >= 1
                    and (chosen_lane is None or chosen_lane == lane)
                    and all(item in completed for item in definition.prerequisites)
                )
                status = "claimed" if claimed else "running" if running else "available" if available else "locked"
                stages.append(
                    MainlineStageView(
                        key=definition.key,
                        story_key=THREE_REALMS_STORY_KEY,
                        chapter=1,
                        stage=definition.stage,
                        label=f"{THREE_REALMS_LANE_LABELS[lane]}·{definition.label}",
                        description=definition.description,
                        status=status,
                        first_clear_reward=(
                            {definition.codex_flag: 1}
                            | ({"item.token.rebuild_path": 1, f"faction_reputation.{THREE_REALMS_LANE_FACTIONS[lane]}": 1000} if definition.stage == 5 else {})
                        ),
                        completed=claimed,
                        claimed=claimed,
                    )
                )
        return ThreeRealmsStatusRecord(
            player=self._row_to_player(player),
            lanes=tuple(lanes),
            stages=tuple(stages),
        )

    async def start_three_realms_stage(
        self, *, platform: str, platform_user_id: str, lane: str, stage: int | str, operation_id: str
    ) -> MainlineStartRecord:
        definition = three_realms_definition(lane, stage)
        await self.initialize()
        async with self._inflight:
            try:
                return await asyncio.to_thread(
                    self._start_three_realms_stage_sync, platform, platform_user_id, definition, operation_id
                )
            except sqlite3.OperationalError as exc:
                if "locked" in str(exc).lower():
                    raise RepositoryBusyError("database remained locked") from exc
                raise

    def _start_three_realms_stage_sync(
        self, platform: str, platform_user_id: str, definition: ThreeRealmsStage, operation_id: str
    ) -> MainlineStartRecord:
        operation_name = "three_realms.start_stage"
        request_hash = self._request_hash(
            operation_name,
            {"platform": platform, "platform_user_id": platform_user_id, "stage_key": definition.key},
        )
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._three_realms_operation_replay(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                return self._mainline_start_from_payload(replay, replay=True)
            if definition.runtime_status != "open":
                raise MainlineContentClosedError("three-realms mainline stage is closed")
            player = self._require_player(connection, platform, platform_user_id)
            if not meets_realm(str(player["realm_key"]), int(player["realm_layer"]), "nascent_soul", 1):
                raise MainlineRequirementError("nascent soul is required")
            rows = connection.execute(
                "SELECT * FROM mainline_runs WHERE player_id=? AND story_key=?",
                (player["id"], THREE_REALMS_STORY_KEY),
            ).fetchall()
            chosen_lane = next(
                (str(row["stage_key"]).split(".")[1] for row in rows if str(row["status"]) == "running" or bool(row["first_clear_claimed"])),
                None,
            )
            if chosen_lane is not None and chosen_lane != definition.lane:
                raise MainlineRequirementError("a three-realms route has already been chosen")
            if any(str(row["status"]) == "running" for row in rows):
                running = next(row for row in rows if str(row["status"]) == "running")
                if str(running["stage_key"]) != definition.key:
                    raise MainlineAlreadyRunningError("another three-realms stage is running")
            completed = {str(row["stage_key"]) for row in rows if bool(row["first_clear_claimed"])}
            if not all(item in completed for item in definition.prerequisites):
                raise MainlineRequirementError("the previous three-realms stage is incomplete")
            run = connection.execute(
                "SELECT * FROM mainline_runs WHERE player_id=? AND story_key=? AND stage_key=?",
                (player["id"], THREE_REALMS_STORY_KEY, definition.key),
            ).fetchone()
            repeat_pending = run is not None and bool(run["first_clear_claimed"])
            snapshot = {
                "lane": definition.lane,
                "stage_key": definition.key,
                "realm_key": str(player["realm_key"]),
                "realm_layer": int(player["realm_layer"]),
                "location_key": str(player["location_key"]),
                "content_version": definition.content_version,
                "rule_version": definition.rule_version,
                "repeat_pending": repeat_pending,
            }
            first_clear_key = f"{THREE_REALMS_STORY_KEY}:{definition.key}:{player['id']}"
            if run is None:
                connection.execute(
                    """
                    INSERT INTO mainline_runs(
                        player_id, story_key, chapter, stage, stage_key, status,
                        attempt_count, first_clear_claimed, first_clear_key, start_operation_id,
                        snapshot_json, content_version, rule_version, created_at, updated_at
                    ) VALUES (?, ?, 1, ?, ?, 'running', 1, 0, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (player["id"], THREE_REALMS_STORY_KEY, definition.stage, definition.key, first_clear_key, operation_id,
                     json.dumps(snapshot, ensure_ascii=False, sort_keys=True), definition.content_version,
                     definition.rule_version, now_text, now_text),
                )
            else:
                connection.execute(
                    "UPDATE mainline_runs SET status='running', attempt_count=attempt_count+1, start_operation_id=?, snapshot_json=?, updated_at=? WHERE id=?",
                    (operation_id, json.dumps(snapshot, ensure_ascii=False, sort_keys=True), now_text, run["id"]),
                )
            updated = connection.execute("SELECT * FROM players WHERE id=?", (player["id"],)).fetchone()
            payload = {
                "player": self._player_payload(self._row_to_player(updated)),
                "story_key": THREE_REALMS_STORY_KEY,
                "chapter": 1,
                "stage": definition.stage,
                "stage_key": definition.key,
                "status": "running",
                "first_clear": not repeat_pending,
                "label": f"{THREE_REALMS_LANE_LABELS[definition.lane]}·{definition.label}",
                "description": definition.description,
            }
            self._record_three_realms_operation(connection, operation_id, operation_name, player["id"], request_hash, payload, now_text)
            return self._mainline_start_from_payload(payload)

    async def claim_three_realms_stage(
        self, *, platform: str, platform_user_id: str, lane: str, stage: int | str, operation_id: str
    ) -> MainlineClaimRecord:
        definition = three_realms_definition(lane, stage)
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._claim_three_realms_stage_sync, platform, platform_user_id, definition, operation_id
            )

    def _claim_three_realms_stage_sync(
        self, platform: str, platform_user_id: str, definition: ThreeRealmsStage, operation_id: str
    ) -> MainlineClaimRecord:
        operation_name = "three_realms.claim_stage"
        request_hash = self._request_hash(
            operation_name,
            {"platform": platform, "platform_user_id": platform_user_id, "stage_key": definition.key},
        )
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._three_realms_operation_replay(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                return self._mainline_claim_from_payload(replay, replay=True)
            player = self._require_player(connection, platform, platform_user_id)
            run = connection.execute(
                "SELECT * FROM mainline_runs WHERE player_id=? AND story_key=? AND stage_key=?",
                (player["id"], THREE_REALMS_STORY_KEY, definition.key),
            ).fetchone()
            if run is None or str(run["status"]) != "running":
                raise MainlineNotStartedError("three-realms stage has not been started")
            first_clear = not bool(run["first_clear_claimed"])
            reward: dict[str, int | str] = {definition.codex_flag: 1} if first_clear else {}
            faction = THREE_REALMS_LANE_FACTIONS[definition.lane]
            if first_clear and definition.stage == 5:
                reward.update({"item.token.rebuild_path": 1, f"faction_reputation.{faction}": 1000})
            inventory = self._json_object(player["inventory_json"], {})
            reputation = self._json_object(player["faction_reputation_json"], {})
            for key, raw_value in reward.items():
                value = int(raw_value) if isinstance(raw_value, int) else raw_value
                if key.startswith("item."):
                    inventory[key] = int(inventory.get(key, 0)) + int(value)
                elif key.startswith("faction_reputation."):
                    faction_key = key.removeprefix("faction_reputation.")
                    reputation[faction_key] = int(reputation.get(faction_key, 0)) + int(value)
            flags_state = self._json_object(player["intro_json"], {})
            flags = [str(item) for item in flags_state.get("flags", [])]
            if first_clear and definition.stage == 5 and THREE_REALMS_STORY_KEY not in flags:
                flags.append(THREE_REALMS_STORY_KEY)
            flags_state["flags"] = flags
            connection.execute(
                "UPDATE players SET inventory_json=?, faction_reputation_json=?, intro_json=?, updated_at=? WHERE id=?",
                (json.dumps(inventory, ensure_ascii=False, sort_keys=True), json.dumps(reputation, ensure_ascii=False, sort_keys=True),
                 json.dumps(flags_state, ensure_ascii=False, sort_keys=True), now_text, player["id"]),
            )
            connection.execute("UPDATE mainline_runs SET status='claimed', first_clear_claimed=CASE WHEN ? THEN 1 ELSE first_clear_claimed END, claim_operation_id=?, result_json=?, updated_at=? WHERE id=?",
                               (1 if first_clear else 0, operation_id, json.dumps({"reward": reward, "first_clear": first_clear}, ensure_ascii=False, sort_keys=True), now_text, run["id"]))
            connection.execute(
                "INSERT INTO quest_events(player_id, quest_key, component_key, source_operation_id, outcome, payload_json, content_version, rule_version, created_at) VALUES (?, ?, ?, ?, 'success', ?, ?, ?, ?)",
                (player["id"], THREE_REALMS_STORY_KEY, definition.key, operation_id,
                 json.dumps({"lane": definition.lane, "stage": definition.stage, "first_clear": first_clear}, ensure_ascii=False, sort_keys=True),
                 definition.content_version, definition.rule_version, now_text),
            )
            completed = connection.execute(
                "SELECT COUNT(*) AS count FROM quest_events WHERE player_id=? AND quest_key=? AND component_key LIKE ?",
                (player["id"], THREE_REALMS_STORY_KEY, f"lane.{definition.lane}.chapter.%"),
            ).fetchone()["count"]
            connection.execute(
                "INSERT INTO quest_progress(player_id, quest_key, status, progress_json, snapshot_json, source_operation_id, content_version, rule_version, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(player_id, quest_key) DO UPDATE SET status=excluded.status, progress_json=excluded.progress_json, snapshot_json=excluded.snapshot_json, source_operation_id=excluded.source_operation_id, updated_at=excluded.updated_at",
                (player["id"], THREE_REALMS_STORY_KEY, "completed" if int(completed) >= 5 else "active",
                 json.dumps({"lane": definition.lane, "completed": int(completed), "target": 5}, ensure_ascii=False, sort_keys=True),
                 json.dumps({"lane": definition.lane, "content_version": definition.content_version, "rule_version": definition.rule_version}, ensure_ascii=False, sort_keys=True),
                 operation_id, definition.content_version, definition.rule_version, now_text, now_text),
            )
            event_keys = [f"{THREE_REALMS_STORY_KEY}:{definition.key}"]
            if first_clear:
                event_keys.append(definition.codex_flag)
            if first_clear and definition.stage == 5:
                event_keys.append(THREE_REALMS_STORY_KEY)
            for event_key in event_keys:
                connection.execute(
                    "INSERT OR IGNORE INTO activity_events(player_id, event_key, source_operation_id, occurred_at, payload_json) VALUES (?, ?, ?, ?, ?)",
                    (player["id"], event_key, operation_id, now_text, json.dumps({"lane": definition.lane, "stage": definition.stage}, ensure_ascii=False, sort_keys=True)),
                )
            updated = connection.execute("SELECT * FROM players WHERE id=?", (player["id"],)).fetchone()
            payload = {
                "player": self._player_payload(self._row_to_player(updated)),
                "story_key": THREE_REALMS_STORY_KEY,
                "chapter": 1,
                "stage": definition.stage,
                "stage_key": definition.key,
                "status": "claimed",
                "reward": reward,
                "first_clear": first_clear,
                "label": f"{THREE_REALMS_LANE_LABELS[definition.lane]}·{definition.label}",
                "source_operation_id": operation_id,
            }
            self._record_three_realms_operation(connection, operation_id, operation_name, player["id"], request_hash, payload, now_text)
            return self._mainline_claim_from_payload(payload)

    @staticmethod
    def _three_realms_operation_replay(connection: sqlite3.Connection, operation_id: str, operation_name: str, request_hash: str) -> dict[str, object] | None:
        existing = connection.execute("SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id=?", (operation_id,)).fetchone()
        if existing is None:
            return None
        if existing["operation_name"] != operation_name or existing["request_hash"] != request_hash:
            raise OperationConflictError("operation input differs from its original request")
        payload = json.loads(existing["result_json"])
        return payload if isinstance(payload, dict) else None

    @staticmethod
    def _record_three_realms_operation(connection: sqlite3.Connection, operation_id: str, operation_name: str, player_id: int, request_hash: str, payload: dict[str, object], now_text: str) -> None:
        connection.execute(
            "INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (operation_id, operation_name, player_id, request_hash, json.dumps(payload, ensure_ascii=False, sort_keys=True), now_text),
        )


__all__ = ["ThreeRealmsRepositoryMixin"]
