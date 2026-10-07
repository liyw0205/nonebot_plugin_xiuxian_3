"""Transactional persistence for the open void-spire floors."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from typing import Any
from uuid import uuid4

from ...contracts import serialize_datetime
from ..persistence.errors import (
    OperationResultMalformedError,
    PlayerNotFoundError,
    ResourceInsufficientError,
    TowerAlreadyClaimedError,
    TowerBusyError,
    TowerFloorLockedError,
    TowerNotFoundError,
    TowerNotReadyError,
    TowerQuotaError,
    TowerRequirementError,
    TowerRewardNotAvailableError,
    TowerStartFailedError,
)
from ..utils.json_cache import decode_json_strict
from ..utils.operations import operation_replay, record_operation
from ..utils.player import (
    change_player_state,
    grant_player_reward,
    player_integer,
    player_local_reputation,
    split_player_rewards,
)
from .codex_projection import record_codex_discovery, record_material_discoveries
from .void_spire_models import VoidSpirePreviewRecord, VoidSpireRewardRecord, VoidSpireRunRecord
from .void_spire_rules import (
    DAO_SERVICE_REPUTATION_KEY,
    DAO_SERVICE_REPUTATION_REQUIRED,
    LOWER_ROUTE_END,
    MAX_FLOOR,
    SUPPLY_REPUTATION_KEY,
    SUPPLY_REPUTATION_REQUIRED,
    TOWER_KEY,
    floor_definition,
    quota_floor_range,
    reward_for,
    story_codex_for_floor,
    week_start,
)


class VoidSpireRepositoryMixin:
    async def preview_void_spire(self, *, platform: str, platform_user_id: str) -> VoidSpirePreviewRecord:
        await self.initialize()
        return await asyncio.to_thread(self._preview_void_spire_sync, platform, platform_user_id)

    def _preview_void_spire_sync(self, platform: str, platform_user_id: str) -> VoidSpirePreviewRecord:
        now = self._now()
        with self._connect() as connection:
            player = self._require_player(connection, platform, platform_user_id, writable=False)
            highest = int(
                connection.execute(
                    "SELECT COALESCE(MAX(floor_no), 0) FROM void_spire_runs "
                    "WHERE player_id=? AND tower_key=? AND first_clear=1 AND status='claimed'",
                    (player["id"], TOWER_KEY),
                ).fetchone()[0]
            )
            next_floor = min(highest + 1, MAX_FLOOR)
            quota_start, quota_end = quota_floor_range(next_floor, self.content)
            active = connection.execute(
                "SELECT floor_no,status FROM void_spire_runs "
                "WHERE player_id=? AND tower_key=? AND status IN ('battle_running','reward_pending') ORDER BY id DESC LIMIT 1",
                (player["id"], TOWER_KEY),
            ).fetchone()
            weekly_used = int(
                connection.execute(
                    "SELECT COUNT(*) FROM void_spire_runs WHERE player_id=? AND tower_key=? "
                    "AND floor_no BETWEEN ? AND ? AND status<>'aborted' AND substr(created_at,1,10)>=?",
                    (player["id"], TOWER_KEY, quota_start, quota_end, week_start(now)),
                ).fetchone()[0]
            )
            reputation = self._void_spire_supply_reputation(connection, int(player["id"]))
            return VoidSpirePreviewRecord(
                player=self._row_to_player(player),
                highest_floor=highest,
                next_floor=next_floor,
                active_floor=int(active["floor_no"]) if active else None,
                active_status=str(active["status"]) if active else None,
                stamina_cost=floor_definition(max(next_floor, 1), self.content).stamina_cost,
                weekly_limit=floor_definition(max(next_floor, 1), self.content).weekly_limit,
                weekly_used=weekly_used,
                supply_reputation=reputation,
                dao_service_reputation=self._void_spire_local_reputation(
                    connection, int(player["id"]), DAO_SERVICE_REPUTATION_KEY
                ),
            )

    async def start_void_spire_run(
        self, *, platform: str, platform_user_id: str, floor_no: int, operation_id: str
    ) -> VoidSpireRunRecord:
        await self.initialize()
        async with self._inflight:
            record = await asyncio.to_thread(
                self._start_void_spire_once, platform, platform_user_id, floor_no, operation_id
            )
        if record.status != "battle_running":
            return record
        battle_operation = f"specials.void_spire.battle.start:{record.run_id}"
        try:
            battle = await self.start_quest_battle(
                platform=platform,
                platform_user_id=platform_user_id,
                enemy_key=floor_definition(floor_no, self.content).enemy_key,
                battle_type="pve.tower",
                operation_id=battle_operation,
                ignore_void_spire_run_id=record.run_id,
            )
        except Exception as exc:
            await asyncio.to_thread(self._abort_void_spire_run, record.run_id)
            raise TowerStartFailedError("void spire battle could not be started; entry cost refunded") from exc
        record = await asyncio.to_thread(self._attach_void_spire_battle, record.run_id, battle.battle_id)
        return await self._resolve_void_spire_run(record)

    def _start_void_spire_once(
        self, platform: str, platform_user_id: str, floor_no: int, operation_id: str
    ) -> VoidSpireRunRecord:
        try:
            definition = floor_definition(floor_no, self.content)
        except ValueError as exc:
            raise TowerRequirementError(str(exc)) from exc
        operation_name = "specials.start_void_spire"
        request_payload = {
            "platform": platform,
            "platform_user_id": platform_user_id,
            "tower_key": TOWER_KEY,
            "floor_no": floor_no,
            "route_key": definition.route_key,
        }
        request_hash = self._request_hash(operation_name, request_payload)
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay_player = self._require_player(
                connection, platform, platform_user_id, writable=False
            )
            payload = operation_replay(
                connection,
                operation_id,
                operation_name,
                request_hash,
                player_id=int(replay_player["id"]),
            )
            if payload is not None:
                self._validate_void_spire_start_payload(payload)
                run = connection.execute(
                    "SELECT * FROM void_spire_runs WHERE run_id=?", (payload["run_id"],)
                ).fetchone()
                if run is None:
                    raise TowerNotFoundError("void spire run no longer exists")
                if (
                    int(run["player_id"]) != int(replay_player["id"])
                    or str(run["tower_key"]) != payload["tower_key"]
                    or int(run["floor_no"]) != payload["floor_no"]
                    or str(run["route_key"]) != payload["route_key"]
                ):
                    raise OperationResultMalformedError("void spire start operation does not match its run")
                return self._void_spire_run_from_row(run, replay_player, replay=True)

            player = self._require_player(connection, platform, platform_user_id)
            upper_floor = floor_no > LOWER_ROUTE_END
            reputation_key = DAO_SERVICE_REPUTATION_KEY if upper_floor else SUPPLY_REPUTATION_KEY
            required_reputation = DAO_SERVICE_REPUTATION_REQUIRED if upper_floor else SUPPLY_REPUTATION_REQUIRED
            reputation = self._void_spire_local_reputation(connection, int(player["id"]), reputation_key)
            if not self._meets_realm_values(
                str(player["realm_key"]), player_integer(player, "realm_layer"), definition.required_realm, definition.required_layer
            ) and reputation < required_reputation:
                raise TowerRequirementError("realm or stage-specific reputation is required")
            if self._has_active_long_action(connection, int(player["id"])):
                raise TowerBusyError("another long action is active")
            active = connection.execute(
                "SELECT 1 FROM void_spire_runs WHERE player_id=? AND status IN ('battle_running','reward_pending') LIMIT 1",
                (player["id"],),
            ).fetchone()
            if active is not None:
                raise TowerBusyError("another void spire run is active")
            if floor_no > 1:
                previous = connection.execute(
                    "SELECT 1 FROM void_spire_runs WHERE player_id=? AND tower_key=? AND floor_no=? "
                    "AND first_clear=1 AND status='claimed' LIMIT 1",
                    (player["id"], TOWER_KEY, floor_no - 1),
                ).fetchone()
                if previous is None:
                    raise TowerFloorLockedError("previous void spire floor has not been cleared")
            existing_clear = connection.execute(
                "SELECT 1 FROM void_spire_runs WHERE player_id=? AND tower_key=? AND floor_no=? "
                "AND first_clear=1 AND status='claimed' LIMIT 1",
                (player["id"], TOWER_KEY, floor_no),
            ).fetchone()
            first_clear = existing_clear is None
            quota_start, quota_end = quota_floor_range(floor_no, self.content)
            weekly_used = int(
                connection.execute(
                    "SELECT COUNT(*) FROM void_spire_runs WHERE player_id=? AND tower_key=? "
                    "AND floor_no BETWEEN ? AND ? AND status<>'aborted' AND substr(created_at,1,10)>=?",
                    (player["id"], TOWER_KEY, quota_start, quota_end, week_start(now)),
                ).fetchone()[0]
            )
            if weekly_used >= definition.weekly_limit:
                raise TowerQuotaError("void spire weekly attempt limit is exhausted")
            if player_integer(player, "stamina") < definition.stamina_cost:
                raise ResourceInsufficientError("stamina is insufficient")
            run_id = uuid4().hex
            reward = reward_for(floor_no, run_id, first_clear=first_clear, content=self.content)
            change_player_state(
                connection,
                player,
                updated_at=now_text,
                value_delta={"stamina": -definition.stamina_cost},
            )
            connection.execute(
                """
                INSERT INTO void_spire_runs(
                    run_id, player_id, tower_key, floor_no, route_key, status,
                    battle_id, first_clear, starts_at, result_json, reward_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'battle_running', NULL, ?, ?, '{}', ?, ?, ?)
                """,
                (
                    run_id,
                    player["id"],
                    TOWER_KEY,
                    floor_no,
                    definition.route_key,
                    int(first_clear),
                    now_text,
                    json.dumps(reward, ensure_ascii=False, sort_keys=True),
                    now_text,
                    now_text,
                ),
            )
            updated = connection.execute("SELECT * FROM players WHERE id=?", (player["id"],)).fetchone()
            run = connection.execute("SELECT * FROM void_spire_runs WHERE run_id=?", (run_id,)).fetchone()
            self._insert_void_spire_operation(
                connection,
                operation_id,
                operation_name,
                int(player["id"]),
                request_hash,
                {
                    "run_id": run_id,
                    "tower_key": TOWER_KEY,
                    "floor_no": floor_no,
                    "route_key": definition.route_key,
                },
                now_text,
            )
            return self._void_spire_run_from_row(run, updated)

    def _attach_void_spire_battle(self, run_id: str, battle_id: str) -> VoidSpireRunRecord:
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            run = connection.execute("SELECT * FROM void_spire_runs WHERE run_id=?", (run_id,)).fetchone()
            if run is None:
                raise TowerNotFoundError("void spire run does not exist")
            if run["battle_id"] is None:
                connection.execute(
                    "UPDATE void_spire_runs SET battle_id=?,updated_at=? WHERE id=?",
                    (battle_id, now_text, run["id"]),
                )
            player = connection.execute("SELECT * FROM players WHERE id=?", (run["player_id"],)).fetchone()
            run = connection.execute("SELECT * FROM void_spire_runs WHERE run_id=?", (run_id,)).fetchone()
            return self._void_spire_run_from_row(run, player)

    async def _resolve_void_spire_run(self, record: VoidSpireRunRecord) -> VoidSpireRunRecord:
        if record.status != "battle_running" or not record.battle_id:
            return record
        turn = None
        for expected_round in range(1, 21):
            turn = await self.run_battle_turn(battle_id=record.battle_id, expected_round=expected_round)
            if turn.status not in {"created", "running"}:
                break
        if turn is None or turn.status in {"created", "running"}:
            raise TowerNotReadyError("void spire battle is still running")
        resolved = await self.resolve_battle(battle_id=record.battle_id)
        return await asyncio.to_thread(
            self._record_void_spire_outcome, record.run_id, resolved.outcome, resolved.reason
        )

    def _record_void_spire_outcome(self, run_id: str, outcome: str, reason: str) -> VoidSpireRunRecord:
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            run = connection.execute("SELECT * FROM void_spire_runs WHERE run_id=?", (run_id,)).fetchone()
            if run is None:
                raise TowerNotFoundError("void spire run does not exist")
            if str(run["status"]) == "battle_running":
                status = "reward_pending" if outcome == "won" else "lost"
                connection.execute(
                    "UPDATE void_spire_runs SET status=?,result_json=?,updated_at=? WHERE id=? AND status='battle_running'",
                    (status, json.dumps({"outcome": outcome, "reason": reason, "resolved_at": now_text}, sort_keys=True), now_text, run["id"]),
                )
                if outcome == "won" and bool(run["first_clear"]):
                    connection.execute(
                        "INSERT OR IGNORE INTO activity_events(player_id,event_key,source_operation_id,occurred_at,payload_json) VALUES (?,?,?,?,?)",
                        (
                            run["player_id"],
                            f"specials.void_spire.floor.{run['floor_no']}",
                            f"battle.resolve:{run['battle_id']}",
                            now_text,
                            json.dumps({"tower_key": TOWER_KEY, "floor_no": int(run["floor_no"]), "route_key": run["route_key"]}, sort_keys=True),
                        ),
                    )
            run = connection.execute("SELECT * FROM void_spire_runs WHERE run_id=?", (run_id,)).fetchone()
            player = connection.execute("SELECT * FROM players WHERE id=?", (run["player_id"],)).fetchone()
            return self._void_spire_run_from_row(run, player)

    async def claim_void_spire_reward(
        self, *, platform: str, platform_user_id: str, operation_id: str
    ) -> VoidSpireRewardRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._claim_void_spire_reward_once, platform, platform_user_id, operation_id
            )

    def _claim_void_spire_reward_once(
        self, platform: str, platform_user_id: str, operation_id: str
    ) -> VoidSpireRewardRecord:
        operation_name = "specials.claim_void_spire_reward"
        request_hash = self._request_hash(
            operation_name, {"platform": platform, "platform_user_id": platform_user_id}
        )
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay_player = self._require_player(
                connection, platform, platform_user_id, writable=False
            )
            payload = operation_replay(
                connection,
                operation_id,
                operation_name,
                request_hash,
                player_id=int(replay_player["id"]),
            )
            if payload is not None:
                return self._void_spire_reward_replay(
                    connection, payload, operation_id, replay_player
                )
            player = self._require_player(connection, platform, platform_user_id)
            run = connection.execute(
                "SELECT * FROM void_spire_runs WHERE player_id=? AND status='reward_pending' ORDER BY id DESC LIMIT 1",
                (player["id"],),
            ).fetchone()
            if run is None:
                claimed = connection.execute(
                    "SELECT 1 FROM void_spire_reward_claims WHERE player_id=? LIMIT 1", (player["id"],)
                ).fetchone()
                if claimed is not None:
                    raise TowerAlreadyClaimedError("void spire reward was already claimed")
                raise TowerRewardNotAvailableError("no void spire reward is pending")
            reward = self._decode_void_spire_reward(run["reward_json"])
            if reward:
                grant_player_reward(
                    connection,
                    player,
                    reward,
                    now_text,
                    local_reputation_maximums={
                        key: 1000 for key in reward if key.startswith("local.")
                    } or None,
                )
            snapshot = {
                "source": TOWER_KEY,
                "floor_no": int(run["floor_no"]),
                "route_key": str(run["route_key"]),
            }
            record_material_discoveries(
                connection,
                player_id=int(player["id"]),
                operation_id=operation_id,
                occurred_at=now,
                reward=reward,
                snapshot=snapshot,
            )
            discoveries: list[str] = []
            if bool(run["first_clear"]):
                discoveries = [
                    f"codex.void.route_spire_{run['route_key']}",
                    f"codex.challenge.void_spire.floor_{run['floor_no']}",
                ]
                story = story_codex_for_floor(int(run["floor_no"]), self.content)
                if story:
                    discoveries.append(story)
                for entry_key in discoveries:
                    record_codex_discovery(
                        connection,
                        player_id=int(player["id"]),
                        entry_key=entry_key,
                        operation_id=operation_id,
                        occurred_at=now,
                        snapshot=snapshot,
                    )
            connection.execute(
                "INSERT INTO void_spire_reward_claims(run_id,player_id,floor_no,route_key,first_clear,operation_id,reward_json,claimed_at) VALUES (?,?,?,?,?,?,?,?)",
                (run["run_id"], player["id"], run["floor_no"], run["route_key"], run["first_clear"], operation_id, json.dumps(reward, sort_keys=True), now_text),
            )
            connection.execute(
                "UPDATE void_spire_runs SET status='claimed',claim_operation_id=?,updated_at=? WHERE id=? AND status='reward_pending'",
                (operation_id, now_text, run["id"]),
            )
            updated = connection.execute("SELECT * FROM players WHERE id=?", (player["id"],)).fetchone()
            payload = {
                "player": self._player_payload(self._row_to_player(updated)),
                "run_id": str(run["run_id"]),
                "floor_no": int(run["floor_no"]),
                "route_key": str(run["route_key"]),
                "first_clear": bool(run["first_clear"]),
                "reward": reward,
                "discoveries": discoveries,
            }
            self._insert_void_spire_operation(
                connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text
            )
            return self._void_spire_reward_from_payload(payload)

    def _abort_void_spire_run(self, run_id: str) -> None:
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            run = connection.execute(
                "SELECT * FROM void_spire_runs WHERE run_id=? AND status='battle_running'", (run_id,)
            ).fetchone()
            if run is None:
                return
            definition = floor_definition(int(run["floor_no"]), self.content)
            player = connection.execute(
                "SELECT * FROM players WHERE id = ?", (run["player_id"],)
            ).fetchone()
            if player is None:
                raise PlayerNotFoundError("void spire player disappeared during recovery")
            change_player_state(
                connection,
                player,
                updated_at=now_text,
                value_delta={"stamina": definition.stamina_cost},
                maximums={"stamina": player["stamina_max"]},
            )
            connection.execute(
                "UPDATE void_spire_runs SET status='aborted',result_json=?,updated_at=? WHERE id=?",
                (json.dumps({"reason": "battle_start_failed"}, sort_keys=True), now_text, run["id"]),
            )

    @staticmethod
    def _void_spire_supply_reputation(connection: sqlite3.Connection, player_id: int) -> int:
        return VoidSpireRepositoryMixin._void_spire_local_reputation(connection, player_id, SUPPLY_REPUTATION_KEY)

    @staticmethod
    def _void_spire_local_reputation(connection: sqlite3.Connection, player_id: int, key: str) -> int:
        return player_local_reputation(connection, player_id, key)

    @staticmethod
    def _insert_void_spire_operation(
        connection: sqlite3.Connection,
        operation_id: str,
        operation_name: str,
        player_id: int,
        request_hash: str,
        payload: dict[str, Any],
        now_text: str,
    ) -> None:
        record_operation(connection, operation_id, operation_name, player_id, request_hash, payload, now_text)

    def _void_spire_run_from_row(
        self, run: sqlite3.Row, player: sqlite3.Row, *, replay: bool = False
    ) -> VoidSpireRunRecord:
        floor_no = run["floor_no"]
        if (
            isinstance(floor_no, bool)
            or not isinstance(floor_no, int)
            or not 1 <= floor_no <= MAX_FLOOR
            or str(run["tower_key"]) != TOWER_KEY
            or not isinstance(run["route_key"], str)
            or not str(run["route_key"]).strip()
            or run["first_clear"] not in (0, 1)
            or int(run["player_id"]) != int(player["id"])
        ):
            raise OperationResultMalformedError("void spire run identity is invalid")
        status = str(run["status"])
        if status not in {"battle_running", "reward_pending", "lost", "claimed", "aborted"}:
            raise OperationResultMalformedError("void spire run status is invalid")
        if run["battle_id"] is not None and (
            not isinstance(run["battle_id"], str) or not str(run["battle_id"]).strip()
        ):
            raise OperationResultMalformedError("void spire battle reference is invalid")
        result = self._decode_void_spire_object(run["result_json"], "result")
        if any(
            key in result and (not isinstance(result[key], str) or not result[key].strip())
            for key in ("outcome", "reason")
        ):
            raise OperationResultMalformedError("void spire result snapshot is invalid")
        outcome = result.get("outcome")
        if status == "battle_running" and result:
            raise OperationResultMalformedError("running void spire run has a result")
        if status == "reward_pending" and outcome != "won":
            raise OperationResultMalformedError("pending void spire reward has no victory result")
        if status == "lost" and outcome != "lost":
            raise OperationResultMalformedError("lost void spire run has an invalid result")
        if status == "aborted" and result.get("reason") != "battle_start_failed":
            raise OperationResultMalformedError("aborted void spire run has an invalid result")
        if status == "claimed" and outcome not in (None, "won"):
            raise OperationResultMalformedError("claimed void spire run has an invalid result")
        reward = self._decode_void_spire_reward(run["reward_json"])
        return VoidSpireRunRecord(
            player=self._row_to_player(player),
            run_id=str(run["run_id"]),
            tower_key=str(run["tower_key"]),
            floor_no=floor_no,
            route_key=str(run["route_key"]),
            status=status,
            battle_id=str(run["battle_id"]) if run["battle_id"] else None,
            first_clear=bool(run["first_clear"]),
            outcome=str(result["outcome"]) if result.get("outcome") else None,
            reason=str(result["reason"]) if result.get("reason") else None,
            reward=reward if str(run["status"]) == "reward_pending" else {},
            already_completed=replay,
        )

    def _void_spire_reward_from_payload(
        self, payload: dict[str, Any], *, replay: bool = False
    ) -> VoidSpireRewardRecord:
        expected = {"player", "run_id", "floor_no", "route_key", "first_clear", "reward", "discoveries"}
        if set(payload) != expected or not isinstance(payload.get("player"), dict):
            raise OperationResultMalformedError("void spire reward operation result has invalid fields")
        if not isinstance(payload["run_id"], str) or not payload["run_id"].strip():
            raise OperationResultMalformedError("void spire reward operation run is invalid")
        if (
            isinstance(payload["floor_no"], bool)
            or not isinstance(payload["floor_no"], int)
            or not 1 <= payload["floor_no"] <= MAX_FLOOR
        ):
            raise OperationResultMalformedError("void spire reward operation floor is invalid")
        if not isinstance(payload["route_key"], str) or not payload["route_key"].strip():
            raise OperationResultMalformedError("void spire reward operation route is invalid")
        if not isinstance(payload["first_clear"], bool):
            raise OperationResultMalformedError("void spire reward operation first-clear flag is invalid")
        reward = self._validate_void_spire_reward(payload["reward"], "operation reward")
        discoveries = payload["discoveries"]
        if not isinstance(discoveries, list) or any(not isinstance(key, str) or not key for key in discoveries):
            raise OperationResultMalformedError("void spire reward operation discoveries are invalid")
        try:
            player = self._row_to_player(payload["player"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise OperationResultMalformedError("void spire reward operation player snapshot is invalid") from exc
        return VoidSpireRewardRecord(
            player=player,
            run_id=str(payload["run_id"]),
            floor_no=int(payload["floor_no"]),
            route_key=str(payload["route_key"]),
            first_clear=bool(payload["first_clear"]),
            reward=reward,
            discoveries=tuple(discoveries),
            already_completed=replay,
        )

    @staticmethod
    def _decode_void_spire_object(value: Any, label: str) -> dict[str, Any]:
        try:
            decoded = decode_json_strict(str(value))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise OperationResultMalformedError(f"void spire {label} snapshot is malformed") from exc
        if not isinstance(decoded, dict):
            raise OperationResultMalformedError(f"void spire {label} snapshot must be an object")
        return decoded

    @classmethod
    def _validate_void_spire_reward(cls, value: Any, label: str) -> dict[str, int]:
        if not isinstance(value, dict):
            raise OperationResultMalformedError(f"void spire {label} is invalid")
        try:
            split_player_rewards(value)
        except (TypeError, ValueError) as exc:
            raise OperationResultMalformedError(f"void spire {label} is invalid") from exc
        return {str(key): int(amount) for key, amount in value.items()}

    @classmethod
    def _decode_void_spire_reward(cls, value: Any) -> dict[str, int]:
        payload = cls._decode_void_spire_object(value, "reward")
        return cls._validate_void_spire_reward(payload, "reward snapshot")

    @staticmethod
    def _validate_void_spire_start_payload(payload: dict[str, Any]) -> None:
        if set(payload) != {"run_id", "tower_key", "floor_no", "route_key"}:
            raise OperationResultMalformedError("void spire start operation result has invalid fields")
        if not isinstance(payload["run_id"], str) or not payload["run_id"].strip():
            raise OperationResultMalformedError("void spire start operation run is invalid")
        if payload["tower_key"] != TOWER_KEY:
            raise OperationResultMalformedError("void spire start operation tower is invalid")
        if not isinstance(payload["route_key"], str) or not payload["route_key"].strip():
            raise OperationResultMalformedError("void spire start operation route is invalid")
        if isinstance(payload["floor_no"], bool) or not isinstance(payload["floor_no"], int):
            raise OperationResultMalformedError("void spire start operation floor is invalid")
        if not 1 <= payload["floor_no"] <= MAX_FLOOR:
            raise OperationResultMalformedError("void spire start operation floor is invalid")

    def _void_spire_reward_replay(
        self,
        connection: sqlite3.Connection,
        payload: dict[str, Any],
        operation_id: str,
        expected_player: sqlite3.Row,
    ) -> VoidSpireRewardRecord:
        record = self._void_spire_reward_from_payload(payload, replay=True)
        player_id = int(expected_player["id"])
        run = connection.execute(
            "SELECT * FROM void_spire_runs WHERE run_id=?", (record.run_id,)
        ).fetchone()
        if run is None:
            raise OperationResultMalformedError("void spire reward operation run is missing")
        claim = connection.execute(
            "SELECT * FROM void_spire_reward_claims WHERE run_id=? AND operation_id=?",
            (record.run_id, operation_id),
        ).fetchone()
        if (
            claim is None
            or record.player.player_id != str(expected_player["player_id"])
            or record.player.platform != str(expected_player["platform"])
            or record.player.platform_user_id != str(expected_player["platform_user_id"])
            or int(run["player_id"]) != player_id
            or str(run["status"]) != "claimed"
        ):
            raise OperationResultMalformedError("void spire reward operation does not match its claim")
        if (
            int(run["floor_no"]) != record.floor_no
            or str(run["tower_key"]) != TOWER_KEY
            or str(run["route_key"]) != record.route_key
            or bool(run["first_clear"]) != record.first_clear
            or int(claim["player_id"]) != player_id
            or int(claim["floor_no"]) != record.floor_no
            or str(claim["route_key"]) != record.route_key
            or bool(claim["first_clear"]) != record.first_clear
        ):
            raise OperationResultMalformedError("void spire reward operation fields do not match its claim")
        stored_reward = self._decode_void_spire_reward(run["reward_json"])
        claimed_reward = self._decode_void_spire_reward(claim["reward_json"])
        if stored_reward != record.reward or claimed_reward != record.reward:
            raise OperationResultMalformedError("void spire reward operation reward does not match its claim")
        return record


__all__ = ["VoidSpireRepositoryMixin"]
