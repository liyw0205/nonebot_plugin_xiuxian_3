"""Durable daily task rounds projected from the player's settled operations."""

from __future__ import annotations

import asyncio
import json
import secrets
from datetime import datetime, time, timedelta, timezone
from typing import Any

from ...contracts import serialize_datetime
from ..content import ContentError
from ..persistence.errors import (
    DailyTaskRewardAlreadyClaimedError,
    DailyTaskRewardExpiredError,
    DailyTasksIncompleteError,
    DailyTasksUnavailableError,
    OperationConflictError,
)
from ..rewards.rules import (
    RewardContentError,
    reward_definition,
    reward_grant_from_snapshot,
    reward_totals,
    reward_value_delta,
)
from ..utils.player import grant_player_state, player_integer
from .daily_quest_models import DailyQuestRecord, DailyTaskView
from .daily_quest_rules import (
    DailyTaskDefinition,
    DailyTaskSource,
    daily_quest_rules,
    daily_task_definitions,
    select_daily_tasks,
    source_matches,
)


class DailyQuestRepositoryMixin:
    async def get_daily_tasks(
        self,
        *,
        platform: str,
        platform_user_id: str,
    ) -> DailyQuestRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._daily_tasks_get_once, platform, platform_user_id
            )

    async def claim_daily_task_reward(
        self,
        *,
        platform: str,
        platform_user_id: str,
        operation_id: str,
    ) -> DailyQuestRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._daily_task_claim_once,
                platform,
                platform_user_id,
                operation_id,
            )

    def _daily_tasks_get_once(self, platform: str, platform_user_id: str) -> DailyQuestRecord:
        now = self._now()
        now_text = serialize_datetime(now)
        business_date = now.date().isoformat()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            player = self._require_player(
                connection, platform, platform_user_id, writable=False
            )
            self._expire_daily_task_rounds(connection, int(player["id"]), now_text)
            round_row = connection.execute(
                "SELECT * FROM daily_task_rounds WHERE player_id = ? AND business_date = ?",
                (player["id"], business_date),
            ).fetchone()
            if round_row is None:
                round_row = self._materialize_daily_task_round(
                    connection, player, now, business_date
                )
            self._project_daily_task_sources(connection, player, round_row, now)
            return self._daily_task_record(connection, player, round_row)

    def _daily_task_claim_once(
        self,
        platform: str,
        platform_user_id: str,
        operation_id: str,
    ) -> DailyQuestRecord:
        operation_name = "event.claim_daily_tasks"
        request_hash = self._request_hash(
            operation_name,
            {"platform": platform, "platform_user_id": platform_user_id},
        )
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            if existing is not None:
                if existing["operation_name"] != operation_name or existing["request_hash"] != request_hash:
                    raise OperationConflictError("operation input differs from its original request")
                return self._daily_task_record_from_payload(
                    json.loads(existing["result_json"]), replay=True
                )

            player = self._require_player(connection, platform, platform_user_id)
            self._expire_daily_task_rounds(connection, int(player["id"]), now_text)
            candidates = connection.execute(
                """
                SELECT * FROM daily_task_rounds
                WHERE player_id = ? AND status IN ('open', 'expired') AND starts_at <= ?
                ORDER BY ends_at ASC
                """,
                (player["id"], now_text),
            ).fetchall()
            eligible_round = None
            expired_complete = False
            threshold = 0
            for candidate in candidates:
                self._project_daily_task_sources(connection, player, candidate, now)
                snapshot = self._daily_round_snapshot(candidate)
                threshold = int(snapshot["completion_threshold"])
                complete = self._daily_completed_count(connection, int(candidate["id"]))
                if complete < threshold:
                    continue
                if (
                    str(candidate["status"]) == "expired"
                    or str(candidate["claim_expires_at"]) <= now_text
                ):
                    expired_complete = True
                    continue
                eligible_round = candidate
                break

            if eligible_round is None:
                current = connection.execute(
                    "SELECT * FROM daily_task_rounds WHERE player_id = ? AND business_date = ?",
                    (player["id"], now.date().isoformat()),
                ).fetchone()
                if current is not None and str(current["status"]) == "claimed":
                    raise DailyTaskRewardAlreadyClaimedError("daily task reward already claimed")
                if current is None:
                    current = self._materialize_daily_task_round(
                        connection, player, now, now.date().isoformat()
                    )
                    self._project_daily_task_sources(connection, player, current, now)
                current_snapshot = self._daily_round_snapshot(current)
                threshold = int(current_snapshot["completion_threshold"])
                current_complete = self._daily_completed_count(connection, int(current["id"])) >= threshold
                if current_complete and (
                    str(current["status"]) == "expired"
                    or str(current["claim_expires_at"]) <= now_text
                ):
                    expired_complete = True
                elif current_complete:
                    eligible_round = current
                if eligible_round is None:
                    if expired_complete:
                        raise DailyTaskRewardExpiredError("daily task reward window has ended")
                    raise DailyTasksIncompleteError("daily task completion threshold is not met")

            round_snapshot = self._daily_round_snapshot(eligible_round)
            grant = reward_grant_from_snapshot(
                round_snapshot.get("reward"), operation=operation_name
            )
            completed_count = self._daily_completed_count(
                connection, int(eligible_round["id"])
            )
            current_energy = player_integer(player, "energy")
            requested_energy = int(grant.value_delta.get("energy", 0))
            energy_gain = min(
                requested_energy,
                max(0, player_integer(player, "energy_max") - current_energy),
            )
            applied_values = dict(reward_value_delta(grant))
            if "energy" in applied_values:
                applied_values["energy"] = energy_gain
            grant_player_state(
                connection,
                player,
                rewards=grant.assets,
                updated_at=now_text,
                value_delta=applied_values,
                player_values=grant.set_values or None,
                reputation_delta=grant.reputation or None,
                local_reputation_delta=grant.local_reputation or None,
            )
            reward = reward_totals(grant)
            if "energy" in reward:
                reward["energy"] = energy_gain
            connection.execute(
                "INSERT INTO daily_task_claims(round_id, player_id, operation_id, reward_json, claimed_at) VALUES (?, ?, ?, ?, ?)",
                (
                    eligible_round["id"],
                    player["id"],
                    operation_id,
                    json.dumps(reward, ensure_ascii=False, sort_keys=True),
                    now_text,
                ),
            )
            connection.execute(
                "UPDATE daily_task_rounds SET status = 'claimed', updated_at = ? WHERE id = ? AND status = 'open'",
                (now_text, eligible_round["id"]),
            )
            updated_player = connection.execute(
                "SELECT * FROM players WHERE id = ?", (player["id"],)
            ).fetchone()
            if updated_player is None:
                raise RuntimeError("daily task claim returned no player")
            claimed_round = connection.execute(
                "SELECT * FROM daily_task_rounds WHERE id = ?", (eligible_round["id"],)
            ).fetchone()
            payload = self._daily_task_payload(
                connection,
                updated_player,
                claimed_round,
                reward=reward,
                reward_snapshot=grant.snapshot(),
            )
            connection.execute(
                """
                INSERT INTO operations(
                    operation_id, operation_name, player_id, request_hash, result_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    operation_id,
                    operation_name,
                    player["id"],
                    request_hash,
                    json.dumps(payload, ensure_ascii=False, sort_keys=True),
                    now_text,
                ),
            )
            return self._daily_task_record_from_payload(payload)

    def _materialize_daily_task_round(
        self,
        connection: Any,
        player: Any,
        now: datetime,
        business_date: str,
    ) -> Any:
        try:
            rules = daily_quest_rules(self.content)
            definitions = daily_task_definitions(self.content)
        except (ContentError, RewardContentError) as exc:
            raise DailyTasksUnavailableError("daily task content is unavailable") from exc
        start = datetime.combine(now.date(), time.min, tzinfo=timezone.utc)
        end = start + timedelta(days=1)
        seed = secrets.token_hex(16)
        selected = select_daily_tasks(rules, definitions, seed)
        if len(selected) != rules.task_count:
            raise DailyTasksUnavailableError("daily task candidates are incomplete")
        round_key = f"daily.{business_date.replace('-', '')}"
        now_text = serialize_datetime(now)
        snapshot = {
            "timezone": rules.timezone,
            "selection_seed": seed,
            "completion_threshold": rules.completion_threshold,
            "reward": rules.reward.snapshot(),
        }
        connection.execute(
            """
            INSERT INTO daily_task_rounds(
                player_id, round_key, business_date, status, starts_at, ends_at,
                claim_expires_at, snapshot_json, created_at, updated_at
            ) VALUES (?, ?, ?, 'open', ?, ?, ?, ?, ?, ?)
            """,
            (
                player["id"],
                round_key,
                business_date,
                serialize_datetime(start),
                serialize_datetime(end),
                serialize_datetime(end + timedelta(seconds=rules.claim_window_seconds)),
                json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
                now_text,
                now_text,
            ),
        )
        round_row = connection.execute(
            "SELECT * FROM daily_task_rounds WHERE player_id = ? AND business_date = ?",
            (player["id"], business_date),
        ).fetchone()
        if round_row is None:
            raise RuntimeError("daily task round was not created")
        for position, definition in enumerate(selected):
            task_snapshot = definition.snapshot()
            connection.execute(
                """
                INSERT INTO daily_tasks(
                    round_id, player_id, position, task_key, target, progress,
                    status, snapshot_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 0, 'active', ?, ?, ?)
                """,
                (
                    round_row["id"],
                    player["id"],
                    position,
                    definition.key,
                    definition.target,
                    json.dumps(task_snapshot, ensure_ascii=False, sort_keys=True),
                    now_text,
                    now_text,
                ),
            )
        return round_row

    def _project_daily_task_sources(
        self,
        connection: Any,
        player: Any,
        round_row: Any,
        now: datetime,
    ) -> None:
        start_text = str(round_row["starts_at"])
        # Include a source committed at the same instant as the projection read,
        # while keeping the round end exclusive.
        end_text = min(
            serialize_datetime(now + timedelta(microseconds=1)),
            str(round_row["ends_at"]),
        )
        if end_text <= start_text:
            return
        tasks = connection.execute(
            "SELECT * FROM daily_tasks WHERE round_id = ? ORDER BY position",
            (round_row["id"],),
        ).fetchall()
        sources: dict[str, list[tuple[Any, DailyTaskSource]]] = {}
        for task in tasks:
            if int(task["progress"]) >= int(task["target"]):
                continue
            snapshot = self._daily_task_snapshot(task)
            for raw_source in snapshot["sources"]:
                source = self._daily_source_snapshot(raw_source)
                sources.setdefault(source.operation, []).append((task, source))
        if not sources:
            return
        if any(len(values) > 1 for values in sources.values()):
            raise DailyTasksUnavailableError("daily task sources overlap")
        operation_names = sorted(sources)
        placeholders = ",".join("?" for _ in operation_names)
        operations = connection.execute(
            f"""
            SELECT operation_id, operation_name, result_json, created_at
            FROM operations
            WHERE player_id = ? AND created_at >= ? AND created_at < ?
                AND operation_name IN ({placeholders})
            ORDER BY created_at, operation_id
            """,
            (player["id"], start_text, end_text, *operation_names),
        ).fetchall()
        now_text = serialize_datetime(now)
        for operation in operations:
            try:
                result = json.loads(str(operation["result_json"]))
            except (TypeError, ValueError) as exc:
                raise DailyTasksUnavailableError("daily source result is invalid") from exc
            if not isinstance(result, dict):
                raise DailyTasksUnavailableError("daily source result is invalid")
            for task, source in sources[str(operation["operation_name"])]:
                if not source_matches(source, str(operation["operation_name"]), result):
                    continue
                if source.battle_types and not self._daily_battle_source_is_eligible(
                    connection, int(player["id"]), result, source.battle_types
                ):
                    continue
                payload = {
                    "source_result": result,
                    "source_filter": source.snapshot(),
                }
                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO daily_task_events(
                        round_id, task_id, player_id, source_operation_id,
                        source_operation_name, occurred_at, payload_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        round_row["id"],
                        task["id"],
                        player["id"],
                        operation["operation_id"],
                        operation["operation_name"],
                        operation["created_at"],
                        json.dumps(payload, ensure_ascii=False, sort_keys=True),
                        now_text,
                    ),
                )
                if cursor.rowcount:
                    count = self._daily_task_event_count(connection, int(task["id"]))
                    progress = min(int(task["target"]), count)
                    connection.execute(
                        "UPDATE daily_tasks SET progress = ?, status = ?, updated_at = ? WHERE id = ?",
                        (
                            progress,
                            "completed" if progress >= int(task["target"]) else "active",
                            now_text,
                            task["id"],
                        ),
                    )

    @staticmethod
    def _daily_battle_source_is_eligible(
        connection: Any,
        player_id: int,
        operation_result: dict[str, Any],
        allowed_types: tuple[str, ...],
    ) -> bool:
        battle_id = operation_result.get("battle_id")
        if not isinstance(battle_id, str) or not battle_id:
            return False
        battle = connection.execute(
            "SELECT player_id, battle_type, status, result_json FROM battle_sessions WHERE battle_id = ?",
            (battle_id,),
        ).fetchone()
        if battle is None or int(battle["player_id"]) != player_id:
            return False
        if str(battle["battle_type"]) not in allowed_types or str(battle["status"]) != "settled":
            return False
        try:
            result = json.loads(str(battle["result_json"]))
        except (TypeError, ValueError) as exc:
            raise DailyTasksUnavailableError("daily battle result is invalid") from exc
        return isinstance(result, dict) and result.get("outcome") == "won"

    @staticmethod
    def _daily_source_snapshot(value: Any) -> DailyTaskSource:
        if not isinstance(value, dict) or not isinstance(value.get("operation"), str):
            raise DailyTasksUnavailableError("daily task source snapshot is invalid")
        if not isinstance(value.get("result"), dict):
            raise DailyTasksUnavailableError("daily task source snapshot is invalid")
        required = value.get("required_fields")
        battle_types = value.get("battle_types", [])
        if (
            not isinstance(required, list)
            or not required
            or any(not isinstance(item, str) or not item for item in required)
            or not isinstance(battle_types, list)
            or any(not isinstance(item, str) for item in battle_types)
        ):
            raise DailyTasksUnavailableError("daily task source snapshot is invalid")
        return DailyTaskSource(
            operation=value["operation"],
            result=dict(value["result"]),
            required_fields=tuple(required),
            battle_types=tuple(battle_types),
        )

    def _daily_task_record(
        self,
        connection: Any,
        player: Any,
        round_row: Any,
        *,
        already_completed: bool = False,
    ) -> DailyQuestRecord:
        claim = connection.execute(
            "SELECT reward_json FROM daily_task_claims WHERE round_id = ?",
            (round_row["id"],),
        ).fetchone()
        reward = json.loads(str(claim["reward_json"])) if claim is not None else {}
        snapshot = self._daily_round_snapshot(round_row)
        return DailyQuestRecord(
            player=self._row_to_player(player),
            round_id=str(round_row["round_key"]),
            business_date=str(round_row["business_date"]),
            starts_at=str(round_row["starts_at"]),
            ends_at=str(round_row["ends_at"]),
            claim_expires_at=str(round_row["claim_expires_at"]),
            status=str(round_row["status"]),
            completed_count=self._daily_completed_count(connection, int(round_row["id"])),
            completion_threshold=int(snapshot["completion_threshold"]),
            tasks=self._daily_task_views(connection, int(round_row["id"])),
            reward={str(key): int(value) for key, value in reward.items()},
            snapshot={
                "timezone": snapshot["timezone"],
                "reward": snapshot["reward"],
            },
            already_completed=already_completed,
        )

    def _daily_task_payload(
        self,
        connection: Any,
        player: Any,
        round_row: Any,
        *,
        reward: dict[str, int],
        reward_snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        snapshot = self._daily_round_snapshot(round_row)
        return {
            "player": self._player_payload(self._row_to_player(player)),
            "round_id": str(round_row["round_key"]),
            "business_date": str(round_row["business_date"]),
            "starts_at": str(round_row["starts_at"]),
            "ends_at": str(round_row["ends_at"]),
            "claim_expires_at": str(round_row["claim_expires_at"]),
            "status": str(round_row["status"]),
            "completed_count": self._daily_completed_count(connection, int(round_row["id"])),
            "completion_threshold": int(snapshot["completion_threshold"]),
            "tasks": [
                {
                    "task_key": task.task_key,
                    "name": task.name,
                    "description": task.description,
                    "progress": task.progress,
                    "target": task.target,
                    "status": task.status,
                }
                for task in self._daily_task_views(connection, int(round_row["id"]))
            ],
            "reward": reward,
            "snapshot": {"timezone": snapshot["timezone"], "reward": reward_snapshot},
        }

    def _daily_task_record_from_payload(
        self,
        payload: dict[str, Any],
        *,
        replay: bool = False,
    ) -> DailyQuestRecord:
        if not isinstance(payload, dict) or not isinstance(payload.get("player"), dict):
            raise DailyTasksUnavailableError("daily task operation result is invalid")
        tasks = payload.get("tasks")
        if not isinstance(tasks, list):
            raise DailyTasksUnavailableError("daily task operation tasks are invalid")
        return DailyQuestRecord(
            player=self._row_to_player(payload["player"]),
            round_id=str(payload["round_id"]),
            business_date=str(payload["business_date"]),
            starts_at=str(payload["starts_at"]),
            ends_at=str(payload["ends_at"]),
            claim_expires_at=str(payload["claim_expires_at"]),
            status=str(payload["status"]),
            completed_count=int(payload["completed_count"]),
            completion_threshold=int(payload["completion_threshold"]),
            tasks=tuple(
                DailyTaskView(
                    task_key=str(task["task_key"]),
                    name=str(task["name"]),
                    description=str(task["description"]),
                    progress=int(task["progress"]),
                    target=int(task["target"]),
                    status=str(task["status"]),
                )
                for task in tasks
            ),
            reward={str(key): int(value) for key, value in dict(payload.get("reward", {})).items()},
            snapshot=dict(payload.get("snapshot", {})),
            already_completed=replay,
        )

    def _daily_task_views(self, connection: Any, round_id: int) -> tuple[DailyTaskView, ...]:
        rows = connection.execute(
            "SELECT * FROM daily_tasks WHERE round_id = ? ORDER BY position", (round_id,)
        ).fetchall()
        tasks: list[DailyTaskView] = []
        for row in rows:
            snapshot = self._daily_task_snapshot(row)
            tasks.append(
                DailyTaskView(
                    task_key=str(row["task_key"]),
                    name=str(snapshot["name"]),
                    description=str(snapshot["description"]),
                    progress=int(row["progress"]),
                    target=int(row["target"]),
                    status=str(row["status"]),
                )
            )
        return tuple(tasks)

    @staticmethod
    def _daily_task_snapshot(task: Any) -> dict[str, Any]:
        try:
            snapshot = json.loads(str(task["snapshot_json"]))
        except (TypeError, ValueError) as exc:
            raise DailyTasksUnavailableError("daily task snapshot is invalid") from exc
        if not isinstance(snapshot, dict) or not isinstance(snapshot.get("sources"), list):
            raise DailyTasksUnavailableError("daily task snapshot is invalid")
        return snapshot

    @staticmethod
    def _daily_round_snapshot(round_row: Any) -> dict[str, Any]:
        try:
            snapshot = json.loads(str(round_row["snapshot_json"]))
        except (TypeError, ValueError) as exc:
            raise DailyTasksUnavailableError("daily round snapshot is invalid") from exc
        if (
            not isinstance(snapshot, dict)
            or not isinstance(snapshot.get("timezone"), str)
            or isinstance(snapshot.get("completion_threshold"), bool)
            or not isinstance(snapshot.get("completion_threshold"), int)
            or not isinstance(snapshot.get("reward"), dict)
        ):
            raise DailyTasksUnavailableError("daily round snapshot is invalid")
        return snapshot

    @staticmethod
    def _daily_task_event_count(connection: Any, task_id: int) -> int:
        row = connection.execute(
            "SELECT COUNT(*) AS count FROM daily_task_events WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        return int(row["count"])

    @staticmethod
    def _daily_completed_count(connection: Any, round_id: int) -> int:
        row = connection.execute(
            "SELECT COUNT(*) AS count FROM daily_tasks WHERE round_id = ? AND status = 'completed'",
            (round_id,),
        ).fetchone()
        return int(row["count"])

    @staticmethod
    def _expire_daily_task_rounds(connection: Any, player_id: int, now_text: str) -> None:
        connection.execute(
            """
            UPDATE daily_task_rounds
            SET status = 'expired', updated_at = ?
            WHERE player_id = ? AND status = 'open' AND claim_expires_at <= ?
            """,
            (now_text, player_id, now_text),
        )


__all__ = ["DailyQuestRepositoryMixin"]
