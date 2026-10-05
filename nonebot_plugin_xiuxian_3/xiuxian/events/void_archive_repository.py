"""SQLite transactions for the archive guard and weekly projections."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from ...contracts import serialize_datetime
from ..utils.player import grant_player_state
from ..rewards.rules import reward_grant_from_snapshot, reward_totals, reward_value_delta
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
from .void_archive_rules import ARCHIVE_EVENT_KEY, archive_week_window, void_archive_definition


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
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT operation_name, result_json FROM operations WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            if existing is not None and str(existing["operation_name"]).startswith("battle.start.pve."):
                return self._battle_start_from_payload(json.loads(existing["result_json"]), replay=True)
        definition = void_archive_definition(self.content)
        battle_type = f"pve.{definition.enemy_key.removeprefix('enemy.')}"
        with self._connect() as connection:
            player = self._require_player(connection, platform, platform_user_id)
            route = connection.execute(
                "SELECT 1 FROM void_route_sessions WHERE player_id = ? AND route_key = ? AND status = 'settled' ORDER BY id DESC LIMIT 1",
                (player["id"], definition.route_key),
            ).fetchone()
            if route is None:
                raise VoidArchiveRouteEvidenceError("a settled archive route is required")
            completed = connection.execute(
                "SELECT 1 FROM void_archive_runs WHERE route_session_id = (SELECT session_id FROM void_route_sessions WHERE player_id = ? AND route_key = ? AND status = 'settled' ORDER BY id DESC LIMIT 1)",
                (player["id"], definition.route_key),
            ).fetchone()
            battle_started = connection.execute(
                "SELECT 1 FROM operations WHERE operation_id = ? AND operation_name = ?",
                (operation_id, f"battle.start.{battle_type}"),
            ).fetchone()
            if completed is not None and battle_started is None:
                raise VoidArchiveGuardAlreadySettledError("archive route already has a guard result")
        return self._start_training_battle_once(
            platform,
            platform_user_id,
            operation_id,
            definition.enemy_key,
            battle_type,
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

    async def replay_void_archive_task(
        self, *, operation_id: str, task_ref: str
    ) -> VoidArchiveTaskClaimRecord | None:
        """Replay a settled task before resolving the current task name."""

        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._replay_void_archive_task_once, operation_id, task_ref
            )

    def _replay_void_archive_task_once(
        self, operation_id: str, task_ref: str
    ) -> VoidArchiveTaskClaimRecord | None:
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT operation_name, result_json FROM operations WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
        if existing is None or not str(existing["operation_name"]).startswith(
            "task.archive_fragment."
        ):
            return None
        payload = json.loads(existing["result_json"])
        task_key = str(payload.get("task_key", ""))
        task_name = str(payload.get("task_name", ""))
        if task_ref.strip() not in {task_key, task_name}:
            raise OperationConflictError("archive task operation conflicts")
        return self._task_claim_from_payload(payload, replay=True)

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

            definition = void_archive_definition(self.content)

            player = self._require_player(connection, platform, platform_user_id)
            battle = connection.execute(
                "SELECT * FROM battle_sessions WHERE battle_id = ? AND player_id = ?",
                (battle_id, player["id"]),
            ).fetchone()
            if battle is None or str(battle["enemy_key"]) != definition.enemy_key:
                raise VoidArchiveRouteEvidenceError("archive keeper battle evidence is invalid")
            result = self._json_object(battle["result_json"], {})
            actual_outcome = result.get("outcome")
            if actual_outcome not in {"won", "lost"}:
                raise VoidArchiveRouteEvidenceError("archive keeper battle is not resolved")
            if outcome != actual_outcome:
                raise VoidArchiveRouteEvidenceError("archive keeper battle outcome differs from evidence")
            outcome = str(actual_outcome)
            route = connection.execute(
                "SELECT * FROM void_route_sessions WHERE player_id = ? AND route_key = ? AND status = 'settled' ORDER BY id DESC LIMIT 1",
                (player["id"], definition.route_key),
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
                if int(weekly_archive_count["count"]) < definition.weekly_cap:
                    reward_grant = definition.first_reward
                else:
                    reward_grant = definition.repeat_reward
                grant_player_state(
                    connection,
                    player,
                    rewards=reward_grant.assets,
                    updated_at=now_text,
                    value_delta=reward_value_delta(reward_grant),
                    player_values=reward_grant.set_values or None,
                    reputation_delta=reward_grant.reputation or None,
                    local_reputation_delta=reward_grant.local_reputation or None,
                )
                reward = reward_totals(reward_grant)
            else:
                reward_grant = None
            run_id = uuid4().hex
            snapshot = {
                "event_key": definition.event_key,
                "route_key": definition.route_key,
                "battle_id": battle_id,
                "enemy_key": definition.enemy_key,
                "route_session_id": route["session_id"],
                "week_id": week_id,
                "weekly_cap": definition.weekly_cap,
                "unlock_duration_seconds": definition.unlock_duration_seconds,
                "first_reward_key": definition.first_reward_key,
                "repeat_reward_key": definition.repeat_reward_key,
                "selected_reward_key": reward_grant.key if reward_grant else None,
                "reward_grant": reward_grant.snapshot() if reward_grant else None,
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
                "snapshot": snapshot,
                "reward_snapshot": snapshot["reward_grant"],
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
        operation_name = f"{task_key}.claim"
        request_hash = self._request_hash(
            operation_name,
            {"platform": platform, "platform_user_id": platform_user_id, "task_key": task_key},
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
                    raise OperationConflictError("archive task operation conflicts")
                return self._task_claim_from_payload(json.loads(existing["result_json"]), replay=True)
            definition = void_archive_definition(self.content)
            task_definition = next((task for task in definition.tasks if task.key == task_key), None)
            if task_definition is None:
                raise VoidArchiveTaskInvalidError("unknown archive task")
            player = self._require_player(connection, platform, platform_user_id)
            claimed = connection.execute(
                "SELECT 1 FROM void_archive_tasks WHERE player_id = ? AND week_id = ? AND task_key = ?",
                (player["id"], week_id, task_key),
            ).fetchone()
            if claimed is not None:
                raise VoidArchiveTaskAlreadyClaimedError("archive task already claimed")
            progress = self._archive_task_evidence(connection, int(player["id"]), week_id, task_key)
            target = task_definition.target
            if progress < target:
                raise VoidArchiveTaskNotCompleteError("archive task evidence is incomplete")
            reward_grant = task_definition.reward
            reward = reward_totals(reward_grant)
            grant_player_state(
                connection,
                player,
                updated_at=now_text,
                rewards=reward_grant.assets,
                value_delta=reward_value_delta(reward_grant),
                player_values=reward_grant.set_values or None,
                reputation_delta=reward_grant.reputation or None,
                local_reputation_delta=reward_grant.local_reputation or None,
            )
            connection.execute(
                "INSERT INTO void_archive_tasks(player_id, week_id, task_key, status, progress, target, reward_json, operation_id, claimed_at) VALUES (?, ?, ?, 'claimed', ?, ?, ?, ?, ?)",
                (player["id"], week_id, task_key, progress, target, json.dumps({"task_key": task_key, "name": task_definition.name, "target": target, "grant": reward_grant.snapshot(), "totals": reward}, ensure_ascii=False, sort_keys=True), operation_id, now_text),
            )
            unlock_activated = False
            if all(
                connection.execute(
                    "SELECT 1 FROM void_archive_tasks WHERE player_id = ? AND week_id = ? AND task_key = ?",
                    (player["id"], week_id, required),
                ).fetchone()
                is not None
                for required in (task.key for task in definition.tasks)
            ):
                unlock_activated = connection.execute(
                    "SELECT 1 FROM void_archive_unlocks WHERE player_id = ? AND week_id = ? AND event_key = ?",
                    (player["id"], week_id, ARCHIVE_EVENT_KEY),
                ).fetchone() is None
                if unlock_activated:
                    connection.execute(
                        "INSERT INTO void_archive_unlocks(player_id, week_id, event_key, starts_at, ends_at, operation_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (player["id"], week_id, ARCHIVE_EVENT_KEY, now_text, serialize_datetime(now + timedelta(seconds=definition.unlock_duration_seconds)), f"{operation_id}:unlock", now_text),
                    )
                    updated_player = connection.execute(
                        "SELECT * FROM players WHERE id = ?",
                        (player["id"],),
                    ).fetchone()
                    if updated_player is None:
                        raise RuntimeError("archive unlock player disappeared")
                    unlock_grant = definition.unlock_reward
                    grant_player_state(
                        connection,
                        updated_player,
                        updated_at=now_text,
                        rewards=unlock_grant.assets,
                        value_delta=reward_value_delta(unlock_grant),
                        player_values=unlock_grant.set_values or None,
                        reputation_delta=unlock_grant.reputation or None,
                        local_reputation_delta=unlock_grant.local_reputation or None,
                    )
                    connection.execute(
                        "INSERT OR IGNORE INTO activity_events(player_id, event_key, source_operation_id, occurred_at, payload_json) VALUES (?, ?, ?, ?, ?)",
                        (player["id"], ARCHIVE_EVENT_KEY, f"{operation_id}:unlock", now_text, json.dumps({"week_id": week_id, "reward": reward_totals(unlock_grant), "reward_grant": unlock_grant.snapshot()}, ensure_ascii=False, sort_keys=True)),
                    )
                else:
                    unlock_grant = None
            else:
                unlock_grant = None
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (player["id"],)).fetchone()
            payload = {
                "player": self._player_payload(self._row_to_player(updated)),
                "week_id": week_id,
                "task_key": task_key,
                "task_name": task_definition.name,
                "progress": progress,
                "target": target,
                "reward": reward,
                "reward_snapshot": reward_grant.snapshot(),
                "unlock_activated": unlock_activated,
                "unlock_reward": reward_totals(unlock_grant) if unlock_grant else {},
                "unlock_reward_snapshot": unlock_grant.snapshot() if unlock_grant else None,
                "unlock_expires_at": (
                    serialize_datetime(now + timedelta(seconds=definition.unlock_duration_seconds))
                    if unlock_activated else None
                ),
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
        definition = void_archive_definition(self.content)
        for task_definition in definition.tasks:
            task_key = task_definition.key
            claimed = connection.execute(
                "SELECT progress, target, reward_json FROM void_archive_tasks WHERE player_id = ? AND week_id = ? AND task_key = ?",
                (player_id, week_id, task_key),
            ).fetchone()
            progress = self._archive_task_evidence(connection, player_id, week_id, task_key)
            target = int(claimed["target"]) if claimed is not None else task_definition.target
            if claimed is not None:
                stored_reward = self._json_object(claimed["reward_json"], {})
                stored_grant = reward_grant_from_snapshot(
                    stored_reward["grant"], operation=f"{task_key}.claim"
                )
                reward = reward_totals(stored_grant)
                task_name = str(stored_reward["name"])
            else:
                reward = reward_totals(task_definition.reward)
                task_name = task_definition.name
            result[task_key] = {
                "progress": progress if claimed is None else int(claimed["progress"]),
                "target": target,
                "status": "claimed" if claimed is not None else ("complete" if progress >= target else "active"),
                "reward": {str(key): int(value) for key, value in dict(reward).items()},
                "name": task_name,
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

        snapshot = payload.get("snapshot")
        if not isinstance(snapshot, dict) or not isinstance(snapshot.get("enemy_key"), str):
            raise ValueError("archive run snapshot is invalid")
        outcome = str(payload["outcome"])
        reward = {str(key): int(value) for key, value in dict(payload.get("reward", {})).items()}
        reward_snapshot = payload.get("reward_snapshot")
        if outcome == "won":
            grant = reward_grant_from_snapshot(reward_snapshot, operation="event.archive_ruins")
            if reward_totals(grant) != reward:
                raise ValueError("archive run reward snapshot differs from result")
        elif reward or reward_snapshot is not None:
            raise ValueError("lost archive run cannot contain a reward")
        return VoidArchiveRunRecord(
            player=SQLitePlayerRepository._row_to_player(payload["player"]),
            run_id=str(payload["run_id"]),
            battle_id=str(payload["battle_id"]),
            route_session_id=str(payload["route_session_id"]),
            outcome=outcome,
            reward=reward,
            already_completed=replay,
        )

    @staticmethod
    def _task_claim_from_payload(payload: dict[str, Any], *, replay: bool) -> VoidArchiveTaskClaimRecord:
        from ..repository import SQLitePlayerRepository

        task_key = str(payload["task_key"])
        reward = {str(key): int(value) for key, value in dict(payload.get("reward", {})).items()}
        grant = reward_grant_from_snapshot(payload.get("reward_snapshot"), operation=f"{task_key}.claim")
        if reward_totals(grant) != reward:
            raise ValueError("archive task reward snapshot differs from result")
        unlock_reward = {str(key): int(value) for key, value in dict(payload.get("unlock_reward", {})).items()}
        unlock_snapshot = payload.get("unlock_reward_snapshot")
        if bool(payload.get("unlock_activated", False)):
            unlock_grant = reward_grant_from_snapshot(unlock_snapshot, operation="event.archive_unlock")
            if reward_totals(unlock_grant) != unlock_reward:
                raise ValueError("archive unlock reward snapshot differs from result")
        elif unlock_reward or unlock_snapshot is not None or payload.get("unlock_expires_at") is not None:
            raise ValueError("inactive archive unlock cannot contain a reward")
        return VoidArchiveTaskClaimRecord(
            player=SQLitePlayerRepository._row_to_player(payload["player"]),
            week_id=str(payload["week_id"]),
            task_key=task_key,
            task_name=str(payload["task_name"]),
            progress=int(payload["progress"]),
            target=int(payload["target"]),
            reward=reward,
            unlock_activated=bool(payload.get("unlock_activated", False)),
            unlock_reward=unlock_reward,
            unlock_expires_at=payload.get("unlock_expires_at"),
            already_completed=replay,
        )


__all__ = ["VoidArchiveRepositoryMixin"]
