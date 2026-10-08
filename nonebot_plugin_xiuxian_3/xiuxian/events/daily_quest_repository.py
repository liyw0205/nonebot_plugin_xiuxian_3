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
)
from ..rewards.rules import (
    RewardContentError,
    reward_definition,
    reward_grant_from_snapshot,
    reward_totals,
    reward_value_delta,
)
from ..utils.json_cache import decode_json_strict
from ..utils.operations import operation_replay
from ..utils.player import grant_player_state, player_integer, player_reputation_state
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
            replay = operation_replay(
                connection,
                operation_id,
                operation_name,
                request_hash,
            )
            if replay is not None:
                player = connection.execute(
                    "SELECT p.* FROM operations o JOIN players p ON p.id = o.player_id "
                    "WHERE o.operation_id = ?",
                    (operation_id,),
                ).fetchone()
                if player is None:
                    raise DailyTasksUnavailableError("daily task operation owner is invalid")
                if (
                    str(player["platform"]) != platform
                    or str(player["platform_user_id"]) != platform_user_id
                ):
                    raise DailyTasksUnavailableError("daily task operation owner is invalid")
                claim = connection.execute(
                    "SELECT c.reward_json, r.* FROM daily_task_claims c "
                    "JOIN daily_task_rounds r ON r.id = c.round_id "
                    "WHERE c.operation_id = ? AND c.player_id = ?",
                    (operation_id, player["id"]),
                ).fetchone()
                if claim is None:
                    raise DailyTasksUnavailableError("daily task claim record is missing")
                self._validate_claim_replay(connection, claim, replay)
                return self._daily_task_record_from_payload(
                    replay,
                    replay=True,
                    expected_player=player,
                    expected_round_id=str(claim["round_key"]),
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
            reputation_before = (
                player_reputation_state(connection, int(player["id"]))
                if grant.local_reputation
                else None
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
                local_reputation_maximums=round_snapshot["local_reputation_maximums"] or None,
            )
            reward = reward_totals(grant)
            if "energy" in reward:
                reward["energy"] = energy_gain
            if reputation_before is not None:
                reputation_after = player_reputation_state(connection, int(player["id"]))
                for reputation_key in grant.local_reputation:
                    actual_gain = (
                        reputation_after.local.get(reputation_key, 0)
                        - reputation_before.local.get(reputation_key, 0)
                    )
                    if actual_gain:
                        reward[reputation_key] = actual_gain
                    else:
                        reward.pop(reputation_key, None)
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
            return self._daily_task_record_from_payload(
                payload,
                expected_player=updated_player,
                expected_round_id=str(claimed_round["round_key"]),
            )

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
            "local_reputation_maximums": dict(rules.local_reputation_maximums),
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
            result = self._strict_object(operation["result_json"], "daily source result")
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
        result = DailyQuestRepositoryMixin._strict_object(
            battle["result_json"], "daily battle result"
        )
        return result.get("outcome") == "won"

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
        reward = (
            self._strict_object(claim["reward_json"], "daily claim reward")
            if claim is not None
            else {}
        )
        if any(
            not isinstance(key, str)
            or isinstance(value, bool)
            or not isinstance(value, int)
            for key, value in reward.items()
        ):
            raise DailyTasksUnavailableError("daily claim reward is invalid")
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
                "local_reputation_maximums": snapshot["local_reputation_maximums"],
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
            "snapshot": {
                "timezone": snapshot["timezone"],
                "reward": reward_snapshot,
                "local_reputation_maximums": snapshot["local_reputation_maximums"],
            },
        }

    def _daily_task_record_from_payload(
        self,
        payload: dict[str, Any],
        *,
        replay: bool = False,
        expected_player: Any | None = None,
        expected_round_id: str | None = None,
    ) -> DailyQuestRecord:
        fields = {
            "player",
            "round_id",
            "business_date",
            "starts_at",
            "ends_at",
            "claim_expires_at",
            "status",
            "completed_count",
            "completion_threshold",
            "tasks",
            "reward",
            "snapshot",
        }
        if not isinstance(payload, dict) or set(payload) != fields or not isinstance(payload.get("player"), dict):
            raise DailyTasksUnavailableError("daily task operation result is invalid")
        player_payload = payload["player"]
        if expected_player is not None:
            if (
                player_payload.get("id") != expected_player["player_id"]
                or player_payload.get("platform") != expected_player["platform"]
                or player_payload.get("platform_user_id") != expected_player["platform_user_id"]
            ):
                raise DailyTasksUnavailableError("daily task operation player is invalid")
        if expected_round_id is not None and payload.get("round_id") != expected_round_id:
            raise DailyTasksUnavailableError("daily task operation round is invalid")
        tasks = payload.get("tasks")
        if not isinstance(tasks, list):
            raise DailyTasksUnavailableError("daily task operation tasks are invalid")
        normalized_tasks: list[DailyTaskView] = []
        for task in tasks:
            if not isinstance(task, dict) or set(task) != {
                "task_key", "name", "description", "progress", "target", "status"
            }:
                raise DailyTasksUnavailableError("daily task operation task is invalid")
            progress = task["progress"]
            target = task["target"]
            if (
                not isinstance(task["task_key"], str)
                or not isinstance(task["name"], str)
                or not isinstance(task["description"], str)
                or isinstance(progress, bool)
                or not isinstance(progress, int)
                or isinstance(target, bool)
                or not isinstance(target, int)
                or target <= 0
                or progress < 0
                or progress > target
                or task["status"] not in {"active", "completed"}
            ):
                raise DailyTasksUnavailableError("daily task operation task is invalid")
            normalized_tasks.append(
                DailyTaskView(
                    task_key=task["task_key"],
                    name=task["name"],
                    description=task["description"],
                    progress=progress,
                    target=target,
                    status=task["status"],
                )
            )
        reward = payload.get("reward")
        if not isinstance(reward, dict) or any(
            not isinstance(key, str)
            or isinstance(value, bool)
            or not isinstance(value, int)
            for key, value in reward.items()
        ):
            raise DailyTasksUnavailableError("daily task operation reward is invalid")
        snapshot = payload.get("snapshot")
        if not isinstance(snapshot, dict):
            raise DailyTasksUnavailableError("daily task operation snapshot is invalid")
        completed_count = payload["completed_count"]
        completion_threshold = payload["completion_threshold"]
        if (
            isinstance(completed_count, bool)
            or not isinstance(completed_count, int)
            or completed_count < 0
            or isinstance(completion_threshold, bool)
            or not isinstance(completion_threshold, int)
            or completion_threshold <= 0
            or completed_count > len(normalized_tasks)
            or completed_count != sum(task.status == "completed" for task in normalized_tasks)
        ):
            raise DailyTasksUnavailableError("daily task operation progress is invalid")
        status = payload["status"]
        if status != "claimed":
            raise DailyTasksUnavailableError("daily task operation status is invalid")
        self._validate_record_snapshot(snapshot)
        return DailyQuestRecord(
            player=self._row_to_player(player_payload),
            round_id=self._required_text(payload["round_id"], "round_id"),
            business_date=self._required_text(payload["business_date"], "business_date"),
            starts_at=self._required_text(payload["starts_at"], "starts_at"),
            ends_at=self._required_text(payload["ends_at"], "ends_at"),
            claim_expires_at=self._required_text(payload["claim_expires_at"], "claim_expires_at"),
            status=status,
            completed_count=completed_count,
            completion_threshold=completion_threshold,
            tasks=tuple(normalized_tasks),
            reward=dict(reward),
            snapshot=snapshot,
            already_completed=replay,
        )

    def _validate_claim_replay(
        self,
        connection: Any,
        claim: Any,
        payload: dict[str, Any],
    ) -> None:
        if str(claim["status"]) != "claimed":
            raise DailyTasksUnavailableError("daily task round is not claimed")
        for field in ("business_date", "starts_at", "ends_at", "claim_expires_at"):
            if payload.get(field) != str(claim[field]):
                raise DailyTasksUnavailableError(
                    f"daily task operation {field} does not match round"
                )
        reward = self._strict_object(claim["reward_json"], "daily claim reward")
        if payload.get("reward") != reward:
            raise DailyTasksUnavailableError("daily task operation reward does not match claim")
        round_snapshot = self._daily_round_snapshot(claim)
        expected_snapshot = {
            "timezone": round_snapshot["timezone"],
            "reward": round_snapshot["reward"],
            "local_reputation_maximums": round_snapshot["local_reputation_maximums"],
        }
        if payload.get("snapshot") != expected_snapshot:
            raise DailyTasksUnavailableError("daily task operation snapshot does not match round")
        tasks = self._daily_task_views(connection, int(claim["id"]))
        expected_tasks = [
            {
                "task_key": task.task_key,
                "name": task.name,
                "description": task.description,
                "progress": task.progress,
                "target": task.target,
                "status": task.status,
            }
            for task in tasks
        ]
        if payload.get("tasks") != expected_tasks:
            raise DailyTasksUnavailableError("daily task operation tasks do not match round")
        if (
            payload.get("status") != "claimed"
            or payload.get("completed_count") != self._daily_completed_count(connection, int(claim["id"]))
            or payload.get("completion_threshold") != round_snapshot["completion_threshold"]
        ):
            raise DailyTasksUnavailableError("daily task operation progress does not match round")

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
        snapshot = DailyQuestRepositoryMixin._strict_object(
            task["snapshot_json"], "daily task snapshot"
        )
        if set(snapshot) != {"task_key", "name", "description", "group", "target", "sources"}:
            raise DailyTasksUnavailableError("daily task snapshot is invalid")
        if (
            any(
                not isinstance(snapshot.get(key), str) or not snapshot[key].strip()
                for key in ("task_key", "name", "description", "group")
            )
            or isinstance(snapshot.get("target"), bool)
            or not isinstance(snapshot.get("target"), int)
            or snapshot["target"] <= 0
            or not isinstance(snapshot.get("sources"), list)
            or not snapshot["sources"]
        ):
            raise DailyTasksUnavailableError("daily task snapshot is invalid")
        return snapshot

    @staticmethod
    def _daily_round_snapshot(round_row: Any) -> dict[str, Any]:
        snapshot = DailyQuestRepositoryMixin._strict_object(
            round_row["snapshot_json"], "daily round snapshot"
        )
        if (
            set(snapshot)
            != {
                "timezone",
                "selection_seed",
                "completion_threshold",
                "reward",
                "local_reputation_maximums",
            }
            or not isinstance(snapshot.get("timezone"), str)
            or snapshot["timezone"] != "UTC"
            or not isinstance(snapshot.get("selection_seed"), str)
            or not snapshot["selection_seed"]
            or isinstance(snapshot.get("completion_threshold"), bool)
            or not isinstance(snapshot.get("completion_threshold"), int)
            or snapshot["completion_threshold"] <= 0
            or not isinstance(snapshot.get("reward"), dict)
            or not isinstance(snapshot.get("local_reputation_maximums"), dict)
        ):
            raise DailyTasksUnavailableError("daily round snapshot is invalid")
        try:
            reward_grant_from_snapshot(
                snapshot["reward"], operation="event.claim_daily_tasks"
            )
        except RewardContentError as exc:
            raise DailyTasksUnavailableError("daily round reward snapshot is invalid") from exc
        reward_local = snapshot["reward"].get("local_reputation")
        maximums = snapshot["local_reputation_maximums"]
        if (
            not isinstance(reward_local, dict)
            or set(maximums) != set(reward_local)
            or any(
                not isinstance(key, str)
                or not key.startswith("local.")
                or not key.removeprefix("local.")
                or isinstance(maximum, bool)
                or not isinstance(maximum, int)
                or maximum <= 0
                for key, maximum in maximums.items()
            )
        ):
            raise DailyTasksUnavailableError("daily round reputation snapshot is invalid")
        return snapshot

    @staticmethod
    def _validate_record_snapshot(snapshot: dict[str, Any]) -> None:
        if set(snapshot) != {"timezone", "reward", "local_reputation_maximums"}:
            raise DailyTasksUnavailableError("daily task operation snapshot is invalid")
        if snapshot.get("timezone") != "UTC" or not isinstance(snapshot.get("reward"), dict):
            raise DailyTasksUnavailableError("daily task operation snapshot is invalid")
        try:
            reward_grant_from_snapshot(
                snapshot["reward"], operation="event.claim_daily_tasks"
            )
        except RewardContentError as exc:
            raise DailyTasksUnavailableError("daily task operation reward snapshot is invalid") from exc
        maximums = snapshot.get("local_reputation_maximums")
        if not isinstance(maximums, dict) or any(
            not isinstance(key, str)
            or not key.startswith("local.")
            or isinstance(value, bool)
            or not isinstance(value, int)
            or value <= 0
            for key, value in maximums.items()
        ):
            raise DailyTasksUnavailableError("daily task operation reputation snapshot is invalid")

    @staticmethod
    def _strict_object(value: Any, label: str) -> dict[str, Any]:
        try:
            decoded = decode_json_strict(str(value))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise DailyTasksUnavailableError(f"{label} is invalid") from exc
        if not isinstance(decoded, dict):
            raise DailyTasksUnavailableError(f"{label} is invalid")
        return decoded

    @staticmethod
    def _required_text(value: Any, field: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise DailyTasksUnavailableError(f"daily task operation {field} is invalid")
        return value

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
