"""SQLite transactions for the v0.5 archive guard and weekly projections."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any
from uuid import uuid4

from ...contracts import serialize_datetime
from ..persistence.errors import (
    OperationConflictError,
    VoidArchiveGuardAlreadySettledError,
    VoidArchiveRouteEvidenceError,
    VoidArchiveTaskAlreadyClaimedError,
    VoidArchiveTaskInvalidError,
    VoidArchiveTaskNotCompleteError,
)
from .void_archive_models import (
    VoidArchiveRunRecord,
    VoidArchiveStatusRecord,
    VoidArchiveTaskClaimRecord,
)
from .void_archive_rules import (
    ARCHIVE_CONVERSION_REWARD,
    ARCHIVE_EVENT_KEY,
    ARCHIVE_REWARD,
    ARCHIVE_ROUTE_KEY,
    ARCHIVE_WEEKLY_CAP,
    CONTENT_VERSION,
    RULE_VERSION,
    TASK_REWARDS,
    TASKS,
    TASK_VOID_MERIT,
    UNLOCK_VOID_MERIT,
    archive_week_window,
    task_target,
)


class VoidArchiveRepositoryMixin:
    """Own archive runs while reusing the shared battle and operation ledgers."""

    async def get_void_archive_status(
        self, *, platform: str, platform_user_id: str
    ) -> VoidArchiveStatusRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._get_void_archive_status_once, platform, platform_user_id
            )

    async def start_void_archive_guard(
        self, *, platform: str, platform_user_id: str, operation_id: str
    ):
        """Validate the settled route before creating the shared battle snapshot."""

        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._start_void_archive_guard_once,
                platform,
                platform_user_id,
                operation_id,
            )

    def _start_void_archive_guard_once(
        self, platform: str, platform_user_id: str, operation_id: str
    ):
        from ..persistence.errors import PlayerNotFoundError

        with self._connect() as connection:
            player = self._require_player(connection, platform, platform_user_id)
            route = connection.execute(
                "SELECT 1 FROM void_route_sessions WHERE player_id = ? AND route_key = ? AND status = 'settled' ORDER BY id DESC LIMIT 1",
                (player["id"], ARCHIVE_ROUTE_KEY),
            ).fetchone()
            if route is None:
                raise VoidArchiveRouteEvidenceError("a settled archive route is required")
            completed = connection.execute(
                "SELECT 1 FROM void_archive_runs WHERE route_session_id = (SELECT session_id FROM void_route_sessions WHERE player_id = ? AND route_key = ? AND status = 'settled' ORDER BY id DESC LIMIT 1)",
                (player["id"], ARCHIVE_ROUTE_KEY),
            ).fetchone()
            battle_started = connection.execute(
                "SELECT 1 FROM operations WHERE operation_id = ? AND operation_name = 'battle.start.pve.archive_keeper'",
                (operation_id,),
            ).fetchone()
            if completed is not None and battle_started is None:
                raise VoidArchiveGuardAlreadySettledError("archive route already has a guard result")
        return self._start_training_battle_once(
            platform,
            platform_user_id,
            operation_id,
            "enemy.archive_keeper",
            "pve.archive_keeper",
        )

    async def record_void_archive_run(
        self,
        *,
        platform: str,
        platform_user_id: str,
        battle_id: str,
        outcome: str,
        operation_id: str,
    ) -> VoidArchiveRunRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._record_void_archive_run_once,
                platform,
                platform_user_id,
                battle_id,
                outcome,
                operation_id,
            )

    async def claim_void_archive_task(
        self, *, platform: str, platform_user_id: str, task_key: str, operation_id: str
    ) -> VoidArchiveTaskClaimRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._claim_void_archive_task_once,
                platform,
                platform_user_id,
                task_key,
                operation_id,
            )

    def _get_void_archive_status_once(
        self, platform: str, platform_user_id: str
    ) -> VoidArchiveStatusRecord:
        now = self._now()
        week_id, _week_start, week_end = archive_week_window(now)
        with self._connect() as connection:
            player = self._require_player(connection, platform, platform_user_id, writable=False)
            tasks = self._archive_task_projection(connection, int(player["id"]), week_id)
            unlock = connection.execute(
                "SELECT starts_at, ends_at FROM void_archive_unlocks WHERE player_id = ? AND week_id = ? AND event_key = ?",
                (player["id"], week_id, ARCHIVE_EVENT_KEY),
            ).fetchone()
            return VoidArchiveStatusRecord(
                player=self._row_to_player(player),
                week_id=week_id,
                week_ends_at=serialize_datetime(week_end),
                tasks=tasks,
                unlocked=unlock is not None and now < datetime.fromisoformat(str(unlock["ends_at"])),
                unlock_expires_at=str(unlock["ends_at"]) if unlock else None,
            )

    def _record_void_archive_run_once(
        self,
        platform: str,
        platform_user_id: str,
        battle_id: str,
        outcome: str,
        operation_id: str,
    ) -> VoidArchiveRunRecord:
        operation_name = "event.archive_ruins"
        request_hash = self._request_hash(
            operation_name,
            {
                "platform": platform,
                "platform_user_id": platform_user_id,
                "battle_id": battle_id,
                "outcome": outcome,
            },
        )
        now = self._now()
        now_text = serialize_datetime(now)
        week_id, _week_start, _week_end = archive_week_window(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            if existing is not None:
                if existing["operation_name"] != operation_name or existing["request_hash"] != request_hash:
                    raise OperationConflictError("archive operation input differs from its original request")
                return self._archive_run_from_payload(json.loads(existing["result_json"]), replay=True)

            player = self._require_player(connection, platform, platform_user_id)
            battle = connection.execute(
                "SELECT * FROM battle_sessions WHERE battle_id = ? AND player_id = ?",
                (battle_id, player["id"]),
            ).fetchone()
            if battle is None or str(battle["enemy_key"]) != "enemy.archive_keeper":
                raise VoidArchiveRouteEvidenceError("archive keeper battle evidence is invalid")
            result = self._json_object(battle["result_json"], {})
            actual_outcome = str(result.get("outcome", outcome))
            if actual_outcome not in {"won", "lost"}:
                raise VoidArchiveRouteEvidenceError("archive keeper battle is not resolved")
            outcome = actual_outcome
            route = connection.execute(
                "SELECT * FROM void_route_sessions WHERE player_id = ? AND route_key = ? AND status = 'settled' ORDER BY id DESC LIMIT 1",
                (player["id"], ARCHIVE_ROUTE_KEY),
            ).fetchone()
            if route is None:
                raise VoidArchiveRouteEvidenceError("a settled archive route is required")
            duplicate = connection.execute(
                "SELECT 1 FROM void_archive_runs WHERE route_session_id = ?",
                (route["session_id"],),
            ).fetchone()
            if duplicate is not None:
                raise VoidArchiveGuardAlreadySettledError("archive route already has a guard result")

            reward: dict[str, int] = {}
            if outcome == "won":
                weekly_archive_count = connection.execute(
                    "SELECT COUNT(*) AS count FROM void_archive_runs WHERE player_id = ? AND week_id = ? AND outcome = 'won'",
                    (player["id"], week_id),
                ).fetchone()
                if int(weekly_archive_count["count"]) < ARCHIVE_WEEKLY_CAP:
                    reward = dict(ARCHIVE_REWARD)
                else:
                    reward = dict(ARCHIVE_CONVERSION_REWARD)
                inventory = self._json_object(player["inventory_json"], {})
                for key, amount in reward.items():
                    inventory[key] = int(inventory.get(key, 0)) + int(amount)
                connection.execute(
                    "UPDATE players SET inventory_json = ?, updated_at = ? WHERE id = ?",
                    (json.dumps(inventory, ensure_ascii=False, sort_keys=True), now_text, player["id"]),
                )
            run_id = uuid4().hex
            snapshot = {
                "battle_id": battle_id,
                "enemy_key": "enemy.archive_keeper",
                "route_session_id": route["session_id"],
                "week_id": week_id,
                "content_version": CONTENT_VERSION,
                "rule_version": RULE_VERSION,
            }
            connection.execute(
                "INSERT INTO void_archive_runs(run_id, player_id, week_id, route_session_id, battle_id, operation_id, outcome, reward_json, snapshot_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    player["id"],
                    week_id,
                    route["session_id"],
                    battle_id,
                    operation_id,
                    outcome,
                    json.dumps(reward, ensure_ascii=False, sort_keys=True),
                    json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
                    now_text,
                ),
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (player["id"],)).fetchone()
            payload = {
                "player": self._player_payload(self._row_to_player(updated)),
                "run_id": run_id,
                "battle_id": battle_id,
                "route_session_id": route["session_id"],
                "outcome": outcome,
                "reward": reward,
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
            return self._archive_run_from_payload(payload, replay=False)

    def _claim_void_archive_task_once(
        self,
        platform: str,
        platform_user_id: str,
        task_key: str,
        operation_id: str,
    ) -> VoidArchiveTaskClaimRecord:
        if task_key not in TASKS:
            raise VoidArchiveTaskInvalidError("unknown archive task")
        operation_name = f"{task_key}.claim"
        request_hash = self._request_hash(
            operation_name,
            {"platform": platform, "platform_user_id": platform_user_id, "task_key": task_key},
        )
        now = self._now()
        now_text = serialize_datetime(now)
        week_id, _week_start, week_end = archive_week_window(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            if existing is not None:
                if existing["operation_name"] != operation_name or existing["request_hash"] != request_hash:
                    raise OperationConflictError("archive task operation conflicts")
                return self._task_claim_from_payload(json.loads(existing["result_json"]), replay=True)
            player = self._require_player(connection, platform, platform_user_id)
            claimed = connection.execute(
                "SELECT 1 FROM void_archive_tasks WHERE player_id = ? AND week_id = ? AND task_key = ?",
                (player["id"], week_id, task_key),
            ).fetchone()
            if claimed is not None:
                raise VoidArchiveTaskAlreadyClaimedError("archive task already claimed")
            progress = self._archive_task_evidence(connection, int(player["id"]), week_id, task_key)
            target = task_target(task_key)
            if progress < target:
                raise VoidArchiveTaskNotCompleteError("archive task evidence is incomplete")
            reward = dict(TASK_REWARDS[task_key])
            inventory = self._json_object(player["inventory_json"], {})
            for key, amount in reward.items():
                inventory[key] = int(inventory.get(key, 0)) + int(amount)
            connection.execute(
                "UPDATE players SET inventory_json = ?, void_merit = void_merit + ?, updated_at = ? WHERE id = ?",
                (json.dumps(inventory, ensure_ascii=False, sort_keys=True), TASK_VOID_MERIT, now_text, player["id"]),
            )
            connection.execute(
                "INSERT INTO void_archive_tasks(player_id, week_id, task_key, status, progress, target, reward_json, operation_id, claimed_at) VALUES (?, ?, ?, 'claimed', ?, ?, ?, ?, ?)",
                (player["id"], week_id, task_key, progress, target, json.dumps(reward, ensure_ascii=False, sort_keys=True), operation_id, now_text),
            )
            unlock_activated = False
            if all(
                connection.execute(
                    "SELECT 1 FROM void_archive_tasks WHERE player_id = ? AND week_id = ? AND task_key = ?",
                    (player["id"], week_id, required),
                ).fetchone()
                is not None
                for required in TASKS
            ):
                unlock_activated = connection.execute(
                    "SELECT 1 FROM void_archive_unlocks WHERE player_id = ? AND week_id = ? AND event_key = ?",
                    (player["id"], week_id, ARCHIVE_EVENT_KEY),
                ).fetchone() is None
                if unlock_activated:
                    connection.execute(
                        "INSERT INTO void_archive_unlocks(player_id, week_id, event_key, starts_at, ends_at, operation_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (player["id"], week_id, ARCHIVE_EVENT_KEY, now_text, serialize_datetime(week_end), f"{operation_id}:unlock", now_text),
                    )
                    connection.execute(
                        "UPDATE players SET void_merit = void_merit + ? WHERE id = ?",
                        (UNLOCK_VOID_MERIT, player["id"]),
                    )
                    connection.execute(
                        "INSERT OR IGNORE INTO activity_events(player_id, event_key, source_operation_id, occurred_at, payload_json) VALUES (?, ?, ?, ?, ?)",
                        (player["id"], ARCHIVE_EVENT_KEY, f"{operation_id}:unlock", now_text, json.dumps({"week_id": week_id}, ensure_ascii=False, sort_keys=True)),
                    )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (player["id"],)).fetchone()
            payload = {
                "player": self._player_payload(self._row_to_player(updated)),
                "week_id": week_id,
                "task_key": task_key,
                "progress": progress,
                "target": target,
                "reward": reward,
                "unlock_activated": unlock_activated,
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
            return self._task_claim_from_payload(payload, replay=False)

    def _archive_task_projection(
        self, connection, player_id: int, week_id: str
    ) -> dict[str, dict[str, object]]:
        result: dict[str, dict[str, object]] = {}
        for task_key in TASKS:
            claimed = connection.execute(
                "SELECT progress, target, reward_json FROM void_archive_tasks WHERE player_id = ? AND week_id = ? AND task_key = ?",
                (player_id, week_id, task_key),
            ).fetchone()
            progress = self._archive_task_evidence(connection, player_id, week_id, task_key)
            target = task_target(task_key)
            result[task_key] = {
                "progress": progress if claimed is None else int(claimed["progress"]),
                "target": target,
                "status": "claimed" if claimed is not None else ("complete" if progress >= target else "active"),
                "reward": dict(TASK_REWARDS[task_key]),
            }
        return result

    @staticmethod
    def _archive_task_evidence(connection, player_id: int, week_id: str, task_key: str) -> int:
        if task_key == "task.archive_fragment.alpha":
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM void_route_sessions WHERE player_id = ? AND route_key = 'void.first_route' AND status = 'settled' AND substr(starts_at, 1, 10) >= ? AND substr(starts_at, 1, 10) < date(?, '+7 day')",
                (player_id, week_id, week_id),
            ).fetchone()
        elif task_key == "task.archive_fragment.beta":
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM void_archive_runs WHERE player_id = ? AND week_id = ? AND outcome = 'won'",
                (player_id, week_id),
            ).fetchone()
        else:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM production_orders WHERE player_id = ? AND recipe_key = 'recipe.void.crystal_refine' AND status = 'completed' AND substr(starts_at, 1, 10) >= ? AND substr(starts_at, 1, 10) < date(?, '+7 day')",
                (player_id, week_id, week_id),
            ).fetchone()
        return int(row["count"]) if row else 0

    @staticmethod
    def _archive_run_from_payload(payload: dict[str, Any], *, replay: bool) -> VoidArchiveRunRecord:
        from ..repository import SQLitePlayerRepository

        return VoidArchiveRunRecord(
            player=SQLitePlayerRepository._row_to_player(payload["player"]),
            run_id=str(payload["run_id"]),
            battle_id=str(payload["battle_id"]),
            route_session_id=str(payload["route_session_id"]),
            outcome=str(payload["outcome"]),
            reward={str(key): int(value) for key, value in dict(payload.get("reward", {})).items()},
            already_completed=replay,
        )

    @staticmethod
    def _task_claim_from_payload(payload: dict[str, Any], *, replay: bool) -> VoidArchiveTaskClaimRecord:
        from ..repository import SQLitePlayerRepository

        return VoidArchiveTaskClaimRecord(
            player=SQLitePlayerRepository._row_to_player(payload["player"]),
            week_id=str(payload["week_id"]),
            task_key=str(payload["task_key"]),
            progress=int(payload["progress"]),
            target=int(payload["target"]),
            reward={str(key): int(value) for key, value in dict(payload.get("reward", {})).items()},
            unlock_activated=bool(payload.get("unlock_activated", False)),
            already_completed=replay,
        )


__all__ = ["VoidArchiveRepositoryMixin"]
