"""Transactional persistence for the open void-spire floors."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from typing import Any
from uuid import uuid4

from ...contracts import serialize_datetime
from ..persistence.errors import (
    OperationConflictError,
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
from ..utils.assets import AssetState, write_player_assets
from .codex_projection import record_codex_discovery, record_material_discoveries
from .void_spire_models import VoidSpirePreviewRecord, VoidSpireRewardRecord, VoidSpireRunRecord
from .void_spire_rules import (
    DAO_SERVICE_REPUTATION_KEY,
    DAO_SERVICE_REPUTATION_REQUIRED,
    LEGACY_MAX_FLOOR,
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
            quota_start, quota_end = quota_floor_range(next_floor)
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
                stamina_cost=floor_definition(max(next_floor, 1)).stamina_cost,
                weekly_limit=floor_definition(max(next_floor, 1)).weekly_limit,
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
                enemy_key=floor_definition(floor_no).enemy_key,
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
            definition = floor_definition(floor_no)
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
            existing = connection.execute(
                "SELECT operation_name,request_hash,result_json FROM operations WHERE operation_id=?",
                (operation_id,),
            ).fetchone()
            if existing is not None:
                if existing["operation_name"] != operation_name or existing["request_hash"] != request_hash:
                    raise OperationConflictError("operation input differs from its original request")
                payload = json.loads(existing["result_json"])
                run = connection.execute(
                    "SELECT * FROM void_spire_runs WHERE run_id=?", (payload["run_id"],)
                ).fetchone()
                if run is None:
                    raise TowerNotFoundError("void spire run no longer exists")
                player = connection.execute("SELECT * FROM players WHERE id=?", (run["player_id"],)).fetchone()
                return self._void_spire_run_from_row(run, player, replay=True)

            player = self._require_player(connection, platform, platform_user_id)
            upper_floor = floor_no > LEGACY_MAX_FLOOR
            reputation_key = DAO_SERVICE_REPUTATION_KEY if upper_floor else SUPPLY_REPUTATION_KEY
            required_reputation = DAO_SERVICE_REPUTATION_REQUIRED if upper_floor else SUPPLY_REPUTATION_REQUIRED
            reputation = self._void_spire_local_reputation(connection, int(player["id"]), reputation_key)
            if not self._meets_realm_values(
                str(player["realm_key"]), int(player["realm_layer"]), definition.required_realm, definition.required_layer
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
            quota_start, quota_end = quota_floor_range(floor_no)
            weekly_used = int(
                connection.execute(
                    "SELECT COUNT(*) FROM void_spire_runs WHERE player_id=? AND tower_key=? "
                    "AND floor_no BETWEEN ? AND ? AND status<>'aborted' AND substr(created_at,1,10)>=?",
                    (player["id"], TOWER_KEY, quota_start, quota_end, week_start(now)),
                ).fetchone()[0]
            )
            if weekly_used >= definition.weekly_limit:
                raise TowerQuotaError("void spire weekly attempt limit is exhausted")
            if int(player["stamina"]) < definition.stamina_cost:
                raise ResourceInsufficientError("stamina is insufficient")
            run_id = uuid4().hex
            reward = reward_for(floor_no, run_id, first_clear=first_clear)
            connection.execute(
                "UPDATE players SET stamina=stamina-?,updated_at=? WHERE id=? AND stamina>=?",
                (definition.stamina_cost, now_text, player["id"], definition.stamina_cost),
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
                {"run_id": run_id, "tower_key": TOWER_KEY, "floor_no": floor_no},
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
            existing = connection.execute(
                "SELECT operation_name,request_hash,result_json FROM operations WHERE operation_id=?",
                (operation_id,),
            ).fetchone()
            if existing is not None:
                if existing["operation_name"] != operation_name or existing["request_hash"] != request_hash:
                    raise OperationConflictError("operation input differs from its original request")
                return self._void_spire_reward_from_payload(json.loads(existing["result_json"]), replay=True)
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
            reward = {str(key): int(value) for key, value in json.loads(run["reward_json"]).items()}
            inventory = self._json_object(player["inventory_json"], {})
            stones = int(player["spirit_stones"])
            local_updates: dict[str, int] = {}
            for key, value in reward.items():
                if key == "spirit_stones":
                    stones += value
                elif key.startswith("local."):
                    local_updates[key] = local_updates.get(key, 0) + value
                else:
                    inventory[key] = int(inventory.get(key, 0)) + value
            if local_updates:
                reputation = connection.execute(
                    "SELECT local_json,service_reputation FROM player_reputations WHERE player_id=?",
                    (player["id"],),
                ).fetchone()
                local = self._json_object(reputation["local_json"], {}) if reputation else {}
                service = int(reputation["service_reputation"]) if reputation else 0
                for key, value in local_updates.items():
                    local[key] = min(1000, int(local.get(key, 0)) + value)
                connection.execute(
                    "INSERT INTO player_reputations(player_id,local_json,service_reputation,updated_at) VALUES (?,?,?,?) "
                    "ON CONFLICT(player_id) DO UPDATE SET local_json=excluded.local_json,updated_at=excluded.updated_at",
                    (player["id"], json.dumps(local, ensure_ascii=False, sort_keys=True), service, now_text),
                )
            write_player_assets(connection, int(player["id"]), AssetState(stones, inventory), now_text)
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
                story = story_codex_for_floor(int(run["floor_no"]))
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
            definition = floor_definition(int(run["floor_no"]))
            connection.execute(
                "UPDATE players SET stamina=MIN(stamina_max,stamina+?),updated_at=? WHERE id=?",
                (definition.stamina_cost, now_text, run["player_id"]),
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
        row = connection.execute(
            "SELECT local_json FROM player_reputations WHERE player_id=?", (player_id,)
        ).fetchone()
        if row is None:
            return 0
        try:
            values = json.loads(str(row["local_json"] or "{}"))
        except (TypeError, ValueError):
            return 0
        try:
            return max(0, int(values.get(key, 0))) if isinstance(values, dict) else 0
        except (TypeError, ValueError):
            return 0

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
        connection.execute(
            "INSERT INTO operations(operation_id,operation_name,player_id,request_hash,result_json,created_at) VALUES (?,?,?,?,?,?)",
            (operation_id, operation_name, player_id, request_hash, json.dumps(payload, ensure_ascii=False, sort_keys=True), now_text),
        )

    def _void_spire_run_from_row(
        self, run: sqlite3.Row, player: sqlite3.Row, *, replay: bool = False
    ) -> VoidSpireRunRecord:
        result = json.loads(run["result_json"])
        return VoidSpireRunRecord(
            player=self._row_to_player(player),
            run_id=str(run["run_id"]),
            tower_key=str(run["tower_key"]),
            floor_no=int(run["floor_no"]),
            route_key=str(run["route_key"]),
            status=str(run["status"]),
            battle_id=str(run["battle_id"]) if run["battle_id"] else None,
            first_clear=bool(run["first_clear"]),
            outcome=str(result["outcome"]) if result.get("outcome") else None,
            reason=str(result["reason"]) if result.get("reason") else None,
            reward={str(key): int(value) for key, value in json.loads(run["reward_json"]).items()} if str(run["status"]) == "reward_pending" else {},
            already_completed=replay,
        )

    def _void_spire_reward_from_payload(
        self, payload: dict[str, Any], *, replay: bool = False
    ) -> VoidSpireRewardRecord:
        discoveries = payload.get("discoveries")
        if discoveries is None and bool(payload["first_clear"]):
            discoveries = [
                f"codex.void.route_spire_{payload['route_key']}",
                f"codex.challenge.void_spire.floor_{payload['floor_no']}",
            ]
            story = story_codex_for_floor(int(payload["floor_no"]))
            if story:
                discoveries.append(story)
        return VoidSpireRewardRecord(
            player=self._row_to_player(payload["player"]),
            run_id=str(payload["run_id"]),
            floor_no=int(payload["floor_no"]),
            route_key=str(payload["route_key"]),
            first_clear=bool(payload["first_clear"]),
            reward={str(key): int(value) for key, value in dict(payload.get("reward", {})).items()},
            discoveries=tuple(str(key) for key in (discoveries or ())),
            already_completed=replay,
        )


__all__ = ["VoidSpireRepositoryMixin"]
