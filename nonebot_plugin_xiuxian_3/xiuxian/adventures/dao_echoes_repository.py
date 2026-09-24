"""Transactions for the v0.6 three-realm dao echoes mainline."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time

from ...contracts import serialize_datetime
from ..persistence.errors import (
    MainlineAlreadyRunningError,
    MainlineContentClosedError,
    MainlineNotStartedError,
    MainlineRequirementError,
    OperationConflictError,
    RepositoryBusyError,
)
from .dao_echoes import (
    DAO_ECHOES_LANES,
    DAO_ECHOES_LANE_LABELS,
    DAO_ECHOES_STAGES,
    DAO_ECHOES_STORY_KEY,
    DaoEchoesStage,
    dao_echoes_definition,
)
from .dao_echoes_models import DaoEchoesLaneProgress, DaoEchoesStatusRecord
from .mainline_models import MainlineClaimRecord, MainlineStageView, MainlineStartRecord


class DaoEchoesRepositoryMixin:
    async def get_dao_echoes_status(
        self, *, platform: str, platform_user_id: str
    ) -> DaoEchoesStatusRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._get_dao_echoes_status_sync, platform, platform_user_id
            )

    def _get_dao_echoes_status_sync(
        self, platform: str, platform_user_id: str
    ) -> DaoEchoesStatusRecord:
        with self._connect() as connection:
            player = self._require_player(
                connection, platform, platform_user_id, writable=False
            )
            return self._dao_echoes_status_from_connection(connection, player)

    def _dao_echoes_status_from_connection(
        self, connection: sqlite3.Connection, player: sqlite3.Row
    ) -> DaoEchoesStatusRecord:
        rows = {
            str(row["stage_key"]): row
            for row in connection.execute(
                "SELECT * FROM mainline_runs WHERE player_id=? AND story_key=?",
                (player["id"], DAO_ECHOES_STORY_KEY),
            ).fetchall()
        }
        completed = {
            key
            for key, row in rows.items()
            if bool(row["first_clear_claimed"])
        }
        stages: list[MainlineStageView] = []
        progress: list[DaoEchoesLaneProgress] = []
        for lane in DAO_ECHOES_LANES:
            lane_definitions = tuple(
                stage for stage in DAO_ECHOES_STAGES if stage.lane == lane
            )
            lane_completed = 0
            next_stage: int | None = None
            for definition in lane_definitions:
                run = rows.get(definition.key)
                claimed = definition.key in completed
                if claimed:
                    lane_completed += 1
                elif next_stage is None:
                    next_stage = definition.stage
                run_snapshot = (
                    self._json_object(run["snapshot_json"], {}) if run is not None else {}
                )
                if run is not None and (
                    str(run["status"]) == "running"
                    or bool(run_snapshot.get("repeat_pending"))
                ):
                    status = "running"
                elif claimed:
                    status = "claimed"
                elif DaoEchoesRepositoryMixin._dao_echoes_prerequisites_met(
                    definition, completed, str(player["realm_key"]), int(player["realm_layer"])
                ):
                    status = "available"
                else:
                    status = "locked"
                stages.append(
                    MainlineStageView(
                        key=definition.key,
                        story_key=DAO_ECHOES_STORY_KEY,
                        chapter=1,
                        stage=definition.stage,
                        label=f"{DAO_ECHOES_LANE_LABELS[lane]}·{definition.label}",
                        description=definition.description,
                        status=status,
                        first_clear_reward={definition.codex_flag: 1},
                        repeat_reward={},
                        completed=claimed,
                        claimed=claimed,
                    )
                )
            progress.append(
                DaoEchoesLaneProgress(
                    lane=lane,
                    completed=lane_completed,
                    total=len(lane_definitions),
                    next_stage=next_stage,
                )
            )
        return DaoEchoesStatusRecord(
            player=self._row_to_player(player),
            lanes=tuple(progress),
            stages=tuple(stages),
        )

    @staticmethod
    def _dao_echoes_prerequisites_met(
        definition: DaoEchoesStage,
        completed: set[str],
        realm_key: str,
        realm_layer: int,
    ) -> bool:
        if realm_key != "void_refining" or realm_layer < 10:
            return False
        return all(prerequisite in completed for prerequisite in definition.prerequisites)

    async def start_dao_echoes_stage(
        self,
        *,
        platform: str,
        platform_user_id: str,
        lane: str,
        stage: int | str,
        operation_id: str,
    ) -> MainlineStartRecord:
        definition = dao_echoes_definition(lane, stage)
        await self.initialize()
        async with self._inflight:
            last_error: Exception | None = None
            for attempt in range(5):
                try:
                    return await asyncio.to_thread(
                        self._start_dao_echoes_stage_sync,
                        platform,
                        platform_user_id,
                        definition,
                        operation_id,
                    )
                except sqlite3.OperationalError as exc:
                    if "locked" not in str(exc).lower():
                        raise
                    if attempt == 4:
                        raise RepositoryBusyError("database remained locked") from exc
                    last_error = exc
                    time.sleep(0.01 * (2**attempt))
            raise RepositoryBusyError("database remained locked") from last_error

    def _start_dao_echoes_stage_sync(
        self,
        platform: str,
        platform_user_id: str,
        definition: DaoEchoesStage,
        operation_id: str,
    ) -> MainlineStartRecord:
        operation_name = "dao_echoes.start_stage"
        request_hash = self._request_hash(
            operation_name,
            {
                "platform": platform,
                "platform_user_id": platform_user_id,
                "stage_key": definition.key,
                "content_version": definition.content_version,
                "rule_version": definition.rule_version,
            },
        )
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._dao_echoes_operation_replay(
                connection, operation_id, operation_name, request_hash
            )
            if replay is not None:
                return self._mainline_start_from_payload(replay, replay=True)
            if definition.runtime_status != "open":
                raise MainlineContentClosedError("dao echoes stage is not open")
            player = self._require_player(connection, platform, platform_user_id)
            status = self._dao_echoes_status_from_connection(connection, player)
            completed = {
                stage.key for stage in status.stages if stage.claimed
            }
            if not self._dao_echoes_prerequisites_met(
                definition,
                completed,
                str(player["realm_key"]),
                int(player["realm_layer"]),
            ):
                raise MainlineRequirementError("dao echoes prerequisites are not met")
            run = connection.execute(
                "SELECT * FROM mainline_runs WHERE player_id=? AND story_key=? AND stage_key=?",
                (player["id"], DAO_ECHOES_STORY_KEY, definition.key),
            ).fetchone()
            run_snapshot = (
                self._json_object(run["snapshot_json"], {}) if run is not None else {}
            )
            if run is not None and (
                str(run["status"]) == "running"
                or bool(run_snapshot.get("repeat_pending"))
            ):
                raise MainlineAlreadyRunningError("dao echoes stage is already running")
            repeat_pending = bool(run is not None and run["first_clear_claimed"])
            first_clear_key = f"{DAO_ECHOES_STORY_KEY}:{definition.key}:{player['id']}"
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
            if run is None:
                connection.execute(
                    """
                    INSERT INTO mainline_runs(
                        player_id, story_key, chapter, stage, stage_key, status,
                        attempt_count, first_clear_claimed, first_clear_key,
                        start_operation_id, snapshot_json, content_version, rule_version,
                        created_at, updated_at
                    ) VALUES (?, ?, 1, ?, ?, 'running', 1, 0, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        player["id"], DAO_ECHOES_STORY_KEY, definition.stage,
                        definition.key, first_clear_key, operation_id,
                        json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
                        definition.content_version, definition.rule_version,
                        now_text, now_text,
                    ),
                )
            else:
                connection.execute(
                    """
                    UPDATE mainline_runs SET status=CASE WHEN first_clear_claimed=1 THEN 'claimed' ELSE 'running' END,
                        attempt_count=attempt_count+1,
                        start_operation_id=?, snapshot_json=?, updated_at=? WHERE id=?
                    """,
                    (
                        operation_id,
                        json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
                        now_text,
                        run["id"],
                    ),
                )
            updated = connection.execute(
                "SELECT * FROM players WHERE id=?", (player["id"],)
            ).fetchone()
            payload = {
                "player": self._player_payload(self._row_to_player(updated)),
                "story_key": DAO_ECHOES_STORY_KEY,
                "chapter": 1,
                "stage": definition.stage,
                "stage_key": definition.key,
                "status": "running",
                "first_clear": not repeat_pending,
                "label": f"{DAO_ECHOES_LANE_LABELS[definition.lane]}·{definition.label}",
                "description": definition.description,
                "content_version": definition.content_version,
                "rule_version": definition.rule_version,
            }
            self._record_dao_echoes_operation(
                connection, operation_id, operation_name, player["id"], request_hash,
                payload, now_text,
            )
            return self._mainline_start_from_payload(payload)

    async def claim_dao_echoes_stage(
        self,
        *,
        platform: str,
        platform_user_id: str,
        lane: str,
        stage: int | str,
        operation_id: str,
    ) -> MainlineClaimRecord:
        definition = dao_echoes_definition(lane, stage)
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._claim_dao_echoes_stage_sync,
                platform,
                platform_user_id,
                definition,
                operation_id,
            )

    def _claim_dao_echoes_stage_sync(
        self,
        platform: str,
        platform_user_id: str,
        definition: DaoEchoesStage,
        operation_id: str,
    ) -> MainlineClaimRecord:
        operation_name = "dao_echoes.claim_stage"
        request_hash = self._request_hash(
            operation_name,
            {
                "platform": platform,
                "platform_user_id": platform_user_id,
                "stage_key": definition.key,
                "content_version": definition.content_version,
                "rule_version": definition.rule_version,
            },
        )
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._dao_echoes_operation_replay(
                connection, operation_id, operation_name, request_hash
            )
            if replay is not None:
                return self._mainline_claim_from_payload(replay, replay=True)
            player = self._require_player(connection, platform, platform_user_id)
            run = connection.execute(
                "SELECT * FROM mainline_runs WHERE player_id=? AND story_key=? AND stage_key=?",
                (player["id"], DAO_ECHOES_STORY_KEY, definition.key),
            ).fetchone()
            run_snapshot = (
                self._json_object(run["snapshot_json"], {}) if run is not None else {}
            )
            if run is None or not (
                str(run["status"]) == "running"
                or bool(run_snapshot.get("repeat_pending"))
            ):
                raise MainlineNotStartedError("dao echoes stage has not been started")
            first_clear = not bool(run["first_clear_claimed"])
            reward = {definition.codex_flag: 1} if first_clear else {}
            connection.execute(
                "UPDATE mainline_runs SET status='reward_pending', updated_at=? WHERE id=?",
                (now_text, run["id"]),
            )
            event_keys = [f"{DAO_ECHOES_STORY_KEY}:{definition.key}"]
            if first_clear:
                event_keys.append(definition.codex_flag)
            for event_key in event_keys:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO activity_events(
                        player_id, event_key, source_operation_id, occurred_at, payload_json
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        player["id"], event_key, operation_id, now_text,
                        json.dumps(
                            {"stage_key": definition.key, "lane": definition.lane},
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                    ),
                )
            result = {
                "status": "claimed",
                "reward": reward,
                "first_clear": first_clear,
                "stage_key": definition.key,
            }
            settled_snapshot = dict(run_snapshot)
            settled_snapshot["repeat_pending"] = False
            connection.execute(
                """
                UPDATE mainline_runs SET status='claimed',
                    first_clear_claimed=CASE WHEN ? THEN 1 ELSE first_clear_claimed END,
                    claim_operation_id=?, snapshot_json=?, result_json=?, updated_at=? WHERE id=?
                """,
                (
                    1 if first_clear else 0,
                    operation_id,
                    json.dumps(settled_snapshot, ensure_ascii=False, sort_keys=True),
                    json.dumps(result, ensure_ascii=False, sort_keys=True),
                    now_text,
                    run["id"],
                ),
            )
            updated = connection.execute(
                "SELECT * FROM players WHERE id=?", (player["id"],)
            ).fetchone()
            payload = {
                "player": self._player_payload(self._row_to_player(updated)),
                "story_key": DAO_ECHOES_STORY_KEY,
                "chapter": 1,
                "stage": definition.stage,
                "stage_key": definition.key,
                "status": "claimed",
                "reward": reward,
                "first_clear": first_clear,
                "label": f"{DAO_ECHOES_LANE_LABELS[definition.lane]}·{definition.label}",
                "source_operation_id": operation_id,
                "content_version": definition.content_version,
                "rule_version": definition.rule_version,
            }
            self._record_dao_echoes_operation(
                connection, operation_id, operation_name, player["id"], request_hash,
                payload, now_text,
            )
            return self._mainline_claim_from_payload(payload)

    @staticmethod
    def _dao_echoes_operation_replay(
        connection: sqlite3.Connection,
        operation_id: str,
        operation_name: str,
        request_hash: str,
    ) -> dict[str, object] | None:
        existing = connection.execute(
            "SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id=?",
            (operation_id,),
        ).fetchone()
        if existing is None:
            return None
        if existing["operation_name"] != operation_name or existing["request_hash"] != request_hash:
            raise OperationConflictError("operation input differs from its original request")
        payload = json.loads(existing["result_json"])
        return payload if isinstance(payload, dict) else None

    @staticmethod
    def _record_dao_echoes_operation(
        connection: sqlite3.Connection,
        operation_id: str,
        operation_name: str,
        player_id: int,
        request_hash: str,
        payload: dict[str, object],
        now_text: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO operations(
                operation_id, operation_name, player_id, request_hash, result_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                operation_id,
                operation_name,
                player_id,
                request_hash,
                json.dumps(payload, ensure_ascii=False, sort_keys=True),
                now_text,
            ),
        )


__all__ = ["DaoEchoesRepositoryMixin"]
