"""Transactional persistence for the mist-trial tower."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime
from typing import Any
from uuid import uuid4

from ...contracts import serialize_datetime
from ..content import ContentError
from .codex_projection import record_codex_discovery, record_material_discoveries
from .codex_rules import category_for_entry
from .tower_models import TowerPreviewRecord, TowerRewardRecord, TowerRunRecord
from .tower_rules import (
    TOWER_KEY,
    attempt_band_for,
    codex_first_clear_floors,
    codex_entry_key,
    floor_definition,
    max_floor,
    practice_weekly_limit,
    practice_week_start,
    reward_local_reputation_maximums,
    reward_for,
)
from ..persistence.errors import (
    OperationConflictError,
    PlayerNotFoundError,
    ResourceInsufficientError,
    TowerBusyError,
    TowerFloorLockedError,
    TowerNotFoundError,
    TowerNotReadyError,
    TowerQuotaError,
    TowerRequirementError,
    TowerRewardNotAvailableError,
    TowerStartFailedError,
)
from ..utils.player import change_player_state, grant_player_reward, player_integer


class TowerRepositoryMixin:
    async def preview_tower(self, *, platform: str, platform_user_id: str) -> TowerPreviewRecord:
        await self.initialize()
        return await asyncio.to_thread(self._preview_tower_sync, platform, platform_user_id)

    def _preview_tower_sync(self, platform: str, platform_user_id: str) -> TowerPreviewRecord:
        now = self._now()
        with self._connect() as connection:
            player = self._require_player(connection, platform, platform_user_id, writable=False)
            highest = int(connection.execute(
                "SELECT COALESCE(MAX(floor_no), 0) FROM tower_runs WHERE player_id=? AND tower_key=? AND first_clear=1 AND status='claimed'",
                (player["id"], TOWER_KEY),
            ).fetchone()[0])
            active = connection.execute(
                "SELECT floor_no, status FROM tower_runs WHERE player_id=? AND status IN ('battle_running', 'reward_pending') ORDER BY id DESC LIMIT 1",
                (player["id"],),
            ).fetchone()
            tower_max_floor = max_floor(self.content)
            next_floor = min(highest + 1, tower_max_floor)
            definition = floor_definition(max(next_floor, 1), self.content)
            start = now.date().isoformat()
            daily_used = int(connection.execute(
                "SELECT COUNT(*) FROM tower_runs WHERE player_id=? AND tower_key=? AND status<>'aborted' AND substr(created_at,1,10)=? AND floor_no BETWEEN ? AND ?",
                (player["id"], TOWER_KEY, start, *attempt_band_for(next_floor, self.content)),
            ).fetchone()[0])
            week_start = practice_week_start(now)
            practice_used = int(connection.execute(
                "SELECT COUNT(*) FROM tower_runs WHERE player_id=? AND tower_key=? AND floor_no=? AND first_clear=0 AND status<>'aborted' AND substr(created_at,1,10)>=?",
                (player["id"], TOWER_KEY, next_floor, week_start),
            ).fetchone()[0])
            return TowerPreviewRecord(
                player=self._row_to_player(player),
                highest_floor=highest,
                next_floor=next_floor,
                active_floor=int(active["floor_no"]) if active else None,
                active_status=str(active["status"]) if active else None,
                stamina_cost=definition.stamina_cost,
                daily_limit=definition.daily_limit,
                daily_used=daily_used,
                practice_used=practice_used,
            )

    async def start_tower_run(
        self, *, platform: str, platform_user_id: str, floor_no: int, operation_id: str
    ) -> TowerRunRecord:
        await self.initialize()
        async with self._inflight:
            record = await asyncio.to_thread(
                self._start_tower_run_once, platform, platform_user_id, floor_no, operation_id
            )
        if record.status != "battle_running":
            return record
        battle_operation = f"specials.tower.battle.start:{record.run_id}"
        try:
            battle = await self.start_quest_battle(
                platform=platform,
                platform_user_id=platform_user_id,
                enemy_key=record.enemy_key or "",
                battle_type="pve.tower",
                operation_id=battle_operation,
                ignore_tower_run_id=record.run_id,
            )
        except Exception as exc:
            await asyncio.to_thread(self._abort_tower_run, record.run_id)
            raise TowerStartFailedError("tower battle could not be started; entry cost refunded") from exc
        record = await asyncio.to_thread(self._attach_tower_battle, record.run_id, battle.battle_id)
        return await self._resolve_tower_run(record)

    def _start_tower_run_once(
        self, platform: str, platform_user_id: str, floor_no: int, operation_id: str
    ) -> TowerRunRecord:
        operation_name = "specials.start_tower"
        payload = {
            "platform": platform,
            "platform_user_id": platform_user_id,
            "tower_key": TOWER_KEY,
            "floor_no": floor_no,
        }
        request_hash = self._request_hash(operation_name, payload)
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id=?",
                (operation_id,),
            ).fetchone()
            if existing is not None:
                if existing["operation_name"] != operation_name or existing["request_hash"] != request_hash:
                    raise OperationConflictError("operation input differs from its original request")
                old_payload = json.loads(existing["result_json"])
                run = connection.execute("SELECT * FROM tower_runs WHERE run_id=?", (old_payload["run_id"],)).fetchone()
                if run is None:
                    raise TowerNotFoundError("tower run no longer exists")
                player = connection.execute("SELECT * FROM players WHERE id=?", (run["player_id"],)).fetchone()
                return self._tower_run_from_rows(run, player, replay=True)

            try:
                definition = floor_definition(floor_no, self.content)
            except (ContentError, ValueError, KeyError) as exc:
                raise TowerRequirementError(str(exc)) from exc

            player = self._require_player(connection, platform, platform_user_id)
            if not self._meets_realm_values(
                str(player["realm_key"]), int(player["realm_layer"]),
                definition.required_realm, definition.required_layer,
            ):
                raise TowerRequirementError("realm requirement is not met")
            if self._has_active_long_action(connection, int(player["id"])):
                raise TowerBusyError("another long action is active")
            active = connection.execute(
                "SELECT 1 FROM tower_runs WHERE player_id=? AND status IN ('battle_running', 'reward_pending') LIMIT 1",
                (player["id"],),
            ).fetchone()
            if active is not None:
                raise TowerBusyError("another tower run is active")
            if floor_no > 1:
                previous = connection.execute(
                    "SELECT 1 FROM tower_runs WHERE player_id=? AND tower_key=? AND floor_no=? AND first_clear=1 AND status='claimed' LIMIT 1",
                    (player["id"], TOWER_KEY, floor_no - 1),
                ).fetchone()
                if previous is None:
                    raise TowerFloorLockedError("previous floor has not been cleared")
            existing_clear = connection.execute(
                "SELECT 1 FROM tower_runs WHERE player_id=? AND tower_key=? AND floor_no=? AND first_clear=1 AND status='claimed' LIMIT 1",
                (player["id"], TOWER_KEY, floor_no),
            ).fetchone()
            first_clear = existing_clear is None
            try:
                band_start, band_end = attempt_band_for(floor_no, self.content)
            except (ContentError, ValueError, KeyError) as exc:
                raise TowerRequirementError(str(exc)) from exc
            daily_used = int(connection.execute(
                "SELECT COUNT(*) FROM tower_runs WHERE player_id=? AND tower_key=? AND status<>'aborted' AND substr(created_at,1,10)=? AND floor_no BETWEEN ? AND ?",
                (player["id"], TOWER_KEY, now.date().isoformat(), band_start, band_end),
            ).fetchone()[0])
            if daily_used >= definition.daily_limit:
                raise TowerQuotaError("daily tower attempts are exhausted")
            if not first_clear:
                week_start = practice_week_start(now)
                practice_count = int(connection.execute(
                    "SELECT COUNT(*) FROM tower_runs WHERE player_id=? AND tower_key=? AND floor_no=? AND first_clear=0 AND status<>'aborted' AND substr(created_at,1,10)>=?",
                    (player["id"], TOWER_KEY, floor_no, week_start),
                ).fetchone()[0])
                try:
                    practice_limit = practice_weekly_limit(self.content)
                except (ContentError, ValueError, KeyError) as exc:
                    raise TowerRequirementError(str(exc)) from exc
                if practice_count >= practice_limit:
                    raise TowerQuotaError("weekly tower practice limit is exhausted")
            if player_integer(player, "stamina") < definition.stamina_cost:
                raise ResourceInsufficientError("stamina is insufficient")
            run_id = uuid4().hex
            try:
                reward = reward_for(
                    floor_no,
                    run_id,
                    first_clear=first_clear,
                    content=self.content,
                )
                reward_maximums = reward_local_reputation_maximums(reward, self.content)
                should_record_codex = (
                    not first_clear
                    or floor_no in codex_first_clear_floors(self.content)
                )
                codex_key = codex_entry_key(floor_no, self.content) if should_record_codex else ""
                codex_category = category_for_entry(codex_key, self.content) if codex_key else ""
                if codex_key and not codex_category:
                    raise ContentError(f"codex entry is unavailable: {codex_key}")
            except (ContentError, ValueError, KeyError) as exc:
                raise TowerRequirementError(str(exc)) from exc
            change_player_state(
                connection,
                player,
                updated_at=now_text,
                value_delta={"stamina": -definition.stamina_cost},
            )
            connection.execute(
                """
                INSERT INTO tower_runs(
                    run_id, player_id, tower_key, floor_no, status, battle_id, first_clear,
                    enemy_key, stamina_cost,
                    starts_at, result_json, reward_json, reward_maximums_json,
                    codex_entry_key, codex_category,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'battle_running', NULL, ?, ?, ?, ?, '{}', ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id, player["id"], TOWER_KEY, floor_no, int(first_clear),
                    definition.enemy_key, definition.stamina_cost, now_text,
                    json.dumps(reward, ensure_ascii=False, sort_keys=True),
                    json.dumps(reward_maximums, ensure_ascii=False, sort_keys=True),
                    codex_key,
                    codex_category,
                    now_text, now_text,
                ),
            )
            updated = connection.execute("SELECT * FROM players WHERE id=?", (player["id"],)).fetchone()
            run = connection.execute("SELECT * FROM tower_runs WHERE run_id=?", (run_id,)).fetchone()
            result_payload = {"run_id": run_id, "tower_key": TOWER_KEY, "floor_no": floor_no}
            self._insert_tower_operation(
                connection, operation_id, operation_name, int(player["id"]), request_hash,
                result_payload, now_text,
            )
            return self._tower_run_from_rows(run, updated)

    def _attach_tower_battle(self, run_id: str, battle_id: str) -> TowerRunRecord:
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            run = connection.execute("SELECT * FROM tower_runs WHERE run_id=?", (run_id,)).fetchone()
            if run is None:
                raise TowerNotFoundError("tower run does not exist")
            if run["battle_id"] is None:
                connection.execute(
                    "UPDATE tower_runs SET battle_id=?, updated_at=? WHERE id=?",
                    (battle_id, now_text, run["id"]),
                )
            player = connection.execute("SELECT * FROM players WHERE id=?", (run["player_id"],)).fetchone()
            run = connection.execute("SELECT * FROM tower_runs WHERE run_id=?", (run_id,)).fetchone()
            return self._tower_run_from_rows(run, player)

    async def _resolve_tower_run(self, record: TowerRunRecord) -> TowerRunRecord:
        if record.status != "battle_running" or not record.battle_id:
            return record
        turn = None
        for expected_round in range(1, 21):
            turn = await self.run_battle_turn(battle_id=record.battle_id, expected_round=expected_round)
            if turn.status not in {"created", "running"}:
                break
        if turn is None or turn.status in {"created", "running"}:
            raise TowerNotReadyError("tower battle is still running")
        resolved = await self.resolve_battle(battle_id=record.battle_id)
        return await asyncio.to_thread(
            self._record_tower_outcome, record.run_id, resolved.outcome, resolved.reason
        )

    def _record_tower_outcome(self, run_id: str, outcome: str, reason: str) -> TowerRunRecord:
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            run = connection.execute("SELECT * FROM tower_runs WHERE run_id=?", (run_id,)).fetchone()
            if run is None:
                raise TowerNotFoundError("tower run does not exist")
            if str(run["status"]) == "battle_running":
                status = "reward_pending" if outcome == "won" else "lost"
                result = {"outcome": outcome, "reason": reason, "resolved_at": now_text}
                connection.execute(
                    "UPDATE tower_runs SET status=?, result_json=?, updated_at=? WHERE id=? AND status='battle_running'",
                    (status, json.dumps(result, ensure_ascii=False, sort_keys=True), now_text, run["id"]),
                )
                if outcome == "won" and bool(run["first_clear"]):
                    connection.execute(
                        "INSERT OR IGNORE INTO activity_events(player_id,event_key,source_operation_id,occurred_at,payload_json) VALUES (?,?,?,?,?)",
                        (
                            run["player_id"], f"specials.tower.floor.{run['floor_no']}",
                            f"battle.resolve:{run['battle_id']}", now_text,
                            json.dumps({"tower_key": TOWER_KEY, "floor_no": int(run["floor_no"]), "battle_id": run["battle_id"]}, ensure_ascii=False, sort_keys=True),
                        ),
                    )
            run = connection.execute("SELECT * FROM tower_runs WHERE run_id=?", (run_id,)).fetchone()
            player = connection.execute("SELECT * FROM players WHERE id=?", (run["player_id"],)).fetchone()
            return self._tower_run_from_rows(run, player)

    async def claim_tower_reward(
        self, *, platform: str, platform_user_id: str, operation_id: str
    ) -> TowerRewardRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._claim_tower_reward_once, platform, platform_user_id, operation_id
            )

    def _claim_tower_reward_once(
        self, platform: str, platform_user_id: str, operation_id: str
    ) -> TowerRewardRecord:
        operation_name = "specials.claim_tower_reward"
        request_hash = self._request_hash(
            operation_name, {"platform": platform, "platform_user_id": platform_user_id}
        )
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id=?",
                (operation_id,),
            ).fetchone()
            if existing is not None:
                if existing["operation_name"] != operation_name or existing["request_hash"] != request_hash:
                    raise OperationConflictError("operation input differs from its original request")
                return self._tower_reward_from_payload(json.loads(existing["result_json"]), replay=True)
            player = self._require_player(connection, platform, platform_user_id)
            run = connection.execute(
                "SELECT * FROM tower_runs WHERE player_id=? AND status='reward_pending' ORDER BY id DESC LIMIT 1",
                (player["id"],),
            ).fetchone()
            if run is None:
                raise TowerRewardNotAvailableError("no tower reward is pending")
            try:
                reward_payload = json.loads(run["reward_json"])
                reward_maximums = json.loads(run["reward_maximums_json"])
            except (TypeError, ValueError) as exc:
                raise TowerRequirementError("tower reward snapshot is invalid") from exc
            if not isinstance(reward_payload, dict) or any(
                not isinstance(key, str)
                or not key
                or isinstance(value, bool)
                or not isinstance(value, int)
                or value <= 0
                for key, value in reward_payload.items()
            ):
                raise TowerRequirementError("tower reward snapshot is invalid")
            reward = {str(key): int(value) for key, value in reward_payload.items()}
            if not isinstance(reward_maximums, dict) or any(
                not isinstance(key, str)
                or not key.startswith("local.")
                or isinstance(value, bool)
                or not isinstance(value, int)
                or value <= 0
                for key, value in reward_maximums.items()
            ) or set(reward_maximums) != {
                key for key in reward if key.startswith("local.")
            }:
                raise TowerRequirementError("tower reward reputation snapshot is invalid")
            settlement_reward: dict[str, int] = {}
            for key, value in reward.items():
                settlement_reward[key] = value
            if settlement_reward:
                grant_player_reward(
                    connection,
                    player,
                    settlement_reward,
                    now_text,
                    local_reputation_maximums=reward_maximums or None,
                )
            record_material_discoveries(
                connection, player_id=int(player["id"]), operation_id=operation_id,
                occurred_at=now, reward=reward, snapshot={"source": TOWER_KEY, "floor_no": int(run["floor_no"])},
                content=self.content,
            )
            if run["codex_entry_key"]:
                record_codex_discovery(
                    connection,
                    player_id=int(player["id"]),
                    entry_key=str(run["codex_entry_key"]),
                    operation_id=operation_id,
                    occurred_at=now,
                    snapshot={
                        "tower_key": TOWER_KEY,
                        "floor_no": int(run["floor_no"]),
                        "run_id": run["run_id"],
                        "practice": not bool(run["first_clear"]),
                    },
                    content=self.content,
                    category_snapshot=str(run["codex_category"]),
                )
            connection.execute(
                "INSERT INTO tower_reward_claims(run_id,player_id,floor_no,first_clear,operation_id,reward_json,claimed_at) VALUES (?,?,?,?,?,?,?)",
                (run["run_id"], player["id"], run["floor_no"], run["first_clear"], operation_id, json.dumps(reward, ensure_ascii=False, sort_keys=True), now_text),
            )
            connection.execute(
                "UPDATE tower_runs SET status='claimed', claim_operation_id=?, updated_at=? WHERE id=? AND status='reward_pending'",
                (operation_id, now_text, run["id"]),
            )
            updated = connection.execute("SELECT * FROM players WHERE id=?", (player["id"],)).fetchone()
            result = {
                "player": self._player_payload(self._row_to_player(updated)),
                "run_id": str(run["run_id"]),
                "floor_no": int(run["floor_no"]),
                "first_clear": bool(run["first_clear"]),
                "reward": reward,
            }
            self._insert_tower_operation(
                connection, operation_id, operation_name, int(player["id"]), request_hash, result, now_text
            )
            return self._tower_reward_from_payload(result)

    def _abort_tower_run(self, run_id: str) -> None:
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            run = connection.execute(
                "SELECT * FROM tower_runs WHERE run_id=? AND status='battle_running'", (run_id,)
            ).fetchone()
            if run is None:
                return
            player = connection.execute(
                "SELECT * FROM players WHERE id = ?", (run["player_id"],)
            ).fetchone()
            if player is None:
                raise PlayerNotFoundError("tower player disappeared during recovery")
            change_player_state(
                connection,
                player,
                updated_at=now_text,
                value_delta={"stamina": int(run["stamina_cost"])},
                maximums={"stamina": player["stamina_max"]},
            )
            connection.execute(
                "UPDATE tower_runs SET status='aborted', result_json=?, updated_at=? WHERE id=?",
                (json.dumps({"reason": "battle_start_failed"}), now_text, run["id"]),
            )

    @staticmethod
    def _insert_tower_operation(
        connection: sqlite3.Connection,
        operation_id: str,
        operation_name: str,
        player_id: int,
        request_hash: str,
        payload: dict[str, Any],
        now_text: str,
    ) -> None:
        connection.execute(
            "INSERT INTO operations(operation_id,operation_name,player_id,request_hash,result_json,created_at) VALUES (?,?,?,?,?,?)",
            (operation_id, operation_name, player_id, request_hash, json.dumps(payload, ensure_ascii=False, sort_keys=True), now_text),
        )

    def _tower_run_from_rows(self, run: sqlite3.Row, player: sqlite3.Row, *, replay: bool = False) -> TowerRunRecord:
        result = json.loads(run["result_json"])
        return TowerRunRecord(
            player=self._row_to_player(player),
            run_id=str(run["run_id"]),
            tower_key=str(run["tower_key"]),
            floor_no=int(run["floor_no"]),
            status=str(run["status"]),
            battle_id=str(run["battle_id"]) if run["battle_id"] else None,
            first_clear=bool(run["first_clear"]),
            enemy_key=str(run["enemy_key"]) if run["enemy_key"] else None,
            stamina_cost=int(run["stamina_cost"]),
            outcome=str(result["outcome"]) if result.get("outcome") else None,
            reason=str(result["reason"]) if result.get("reason") else None,
            reward={str(key): int(value) for key, value in json.loads(run["reward_json"]).items()} if str(run["status"]) == "reward_pending" else {},
            already_completed=replay,
        )

    def _tower_reward_from_payload(self, payload: dict[str, Any], *, replay: bool = False) -> TowerRewardRecord:
        return TowerRewardRecord(
            player=self._row_to_player(payload["player"]),
            run_id=str(payload["run_id"]),
            floor_no=int(payload["floor_no"]),
            first_clear=bool(payload["first_clear"]),
            reward={str(key): int(value) for key, value in dict(payload.get("reward", {})).items()},
            already_completed=replay,
        )


__all__ = ["TowerRepositoryMixin"]
