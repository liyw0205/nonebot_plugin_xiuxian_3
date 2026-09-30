"""Persistence for the solo demon-abyss secret-realm slice."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from ...contracts import serialize_datetime
from ..persistence.errors import (
    DemonAbyssBusyError,
    DemonAbyssNodeError,
    DemonAbyssNotFoundError,
    DemonAbyssNotReadyError,
    DemonAbyssQuotaError,
    DemonAbyssRequirementError,
    OperationConflictError,
    ResourceInsufficientError,
)
from ..utils.assets import inventory_grant, inventory_json, inventory_value
from ..utils.player import player_intro_flags, player_object, player_reputation
from .demon_abyss_models import DemonAbyssRunRecord
from .demon_abyss_rules import (
    DEMON_ABYSS_ENEMIES,
    DEMON_ABYSS_EXPIRY_SECONDS,
    DEMON_ABYSS_FIRST_REWARD,
    DEMON_ABYSS_KEY,
    DEMON_ABYSS_LABEL,
    DEMON_ABYSS_LOCATION,
    DEMON_ABYSS_NODES,
    DEMON_ABYSS_QUOTA_LIMIT,
    DEMON_ABYSS_REPEAT_REWARD,
    DEMON_ABYSS_REQUIRED_FLAG,
    DEMON_ABYSS_RISK_BASE_BP,
    DEMON_ABYSS_RISK_MODIFIER_BP,
    DEMON_ABYSS_STAMINA_COST,
    demon_abyss_risk_applies,
    demon_abyss_risk_roll_bp,
)
from .secret_realm_rules import realm_at_least


ACTIVE_RUN_STATUSES = ("entered", "routing", "combat_pending", "cleared", "failed")


class DemonAbyssRepositoryMixin:
    """Own demon-abyss route, risk, reward, and recovery transactions."""

    @staticmethod
    def _demon_week_key(now: datetime) -> str:
        return now.astimezone(timezone.utc).strftime("%G-W%V")

    @staticmethod
    def _demon_operation(connection, operation_id: str, operation_name: str, request_hash: str):
        row = connection.execute(
            "SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id=?",
            (operation_id,),
        ).fetchone()
        if row is None:
            return None
        if row["operation_name"] != operation_name or row["request_hash"] != request_hash:
            raise OperationConflictError("operation ID was reused with different input")
        return json.loads(row["result_json"])

    @staticmethod
    def _demon_store_operation(connection, operation_id, operation_name, player_id, request_hash, payload, now_text):
        connection.execute(
            "INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (operation_id, operation_name, player_id, request_hash, json.dumps(payload, ensure_ascii=False, sort_keys=True), now_text),
        )

    def _demon_payload(self, player, run, snapshot, result) -> dict[str, Any]:
        nodes = tuple(str(item) for item in snapshot.get("node_keys", DEMON_ABYSS_NODES))
        node_index = int(run["node_index"])
        status = str(run["status"])
        current_node = nodes[node_index] if node_index < len(nodes) and status in {"routing", "combat_pending"} else None
        risk = snapshot.get("pollution_risk", {})
        record = DemonAbyssRunRecord(
            player=self._row_to_player(player),
            run_id=str(run["run_id"]),
            status=status,
            node_index=node_index,
            current_node=current_node,
            allowed_nodes=(current_node,) if status == "routing" and current_node else (),
            battle_id=run["battle_id"],
            reward={str(key): int(value) for key, value in result.get("reward", {}).items()},
            first_clear=bool(result.get("first_clear", snapshot.get("first_clear", False))),
            outcome=result.get("outcome"),
            expires_at=str(run["expires_at"]),
            pollution_before=int(risk.get("pollution_before", snapshot.get("pollution_before", player["pollution"]))),
            pollution_after=int(result.get("pollution_after", risk.get("pollution_after", player["pollution"]))),
            risk_roll_bp=(int(risk["roll_bp"]) if "roll_bp" in risk else None),
            system_aborted=result.get("outcome") == "system_aborted",
        )
        return {
            "player": self._player_payload(record.player),
            "run_id": record.run_id,
            "status": record.status,
            "node_index": record.node_index,
            "current_node": record.current_node,
            "allowed_nodes": list(record.allowed_nodes),
            "battle_id": record.battle_id,
            "reward": record.reward,
            "first_clear": record.first_clear,
            "outcome": record.outcome,
            "expires_at": record.expires_at,
            "pollution_before": record.pollution_before,
            "pollution_after": record.pollution_after,
            "risk_roll_bp": record.risk_roll_bp,
            "system_aborted": record.system_aborted,
        }

    def _demon_record(self, payload: dict[str, Any], *, replay: bool = False) -> DemonAbyssRunRecord:
        return DemonAbyssRunRecord(
            player=self._row_to_player(payload["player"]),
            run_id=str(payload["run_id"]),
            status=str(payload["status"]),
            node_index=int(payload["node_index"]),
            current_node=payload.get("current_node"),
            allowed_nodes=tuple(str(item) for item in payload.get("allowed_nodes", ())),
            battle_id=payload.get("battle_id"),
            reward={str(key): int(value) for key, value in dict(payload.get("reward", {})).items()},
            first_clear=bool(payload.get("first_clear", False)),
            outcome=payload.get("outcome"),
            expires_at=str(payload.get("expires_at", "")),
            pollution_before=int(payload.get("pollution_before", 0)),
            pollution_after=int(payload.get("pollution_after", 0)),
            risk_roll_bp=(int(payload["risk_roll_bp"]) if payload.get("risk_roll_bp") is not None else None),
            system_aborted=bool(payload.get("system_aborted", False)),
            already_completed=replay,
        )

    async def has_active_demon_abyss(self, *, platform: str, platform_user_id: str) -> bool:
        await self.initialize()
        return await asyncio.to_thread(self._has_active_demon_abyss_sync, platform, platform_user_id)

    async def has_demon_abyss_settlement_operation(self, operation_id: str) -> bool:
        await self.initialize()
        return await asyncio.to_thread(self._has_demon_abyss_settlement_operation_sync, operation_id)

    def _has_demon_abyss_settlement_operation_sync(self, operation_id: str) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM operations WHERE operation_id=? AND operation_name='demon_abyss.settle'",
                (operation_id,),
            ).fetchone()
            return row is not None

    def _has_active_demon_abyss_sync(self, platform: str, platform_user_id: str) -> bool:
        with self._connect() as connection:
            player = self._require_player(connection, platform, platform_user_id, writable=False)
            row = connection.execute(
                "SELECT 1 FROM secret_realm_runs WHERE player_id=? AND instance_key=? "
                "AND status IN ('entered','routing','combat_pending','cleared','failed') LIMIT 1",
                (player["id"], DEMON_ABYSS_KEY),
            ).fetchone()
            return row is not None

    async def enter_demon_abyss(
        self, *, platform: str, platform_user_id: str, operation_id: str
    ) -> DemonAbyssRunRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._demon_enter_sync, platform, platform_user_id, operation_id
            )

    def _demon_enter_sync(self, platform: str, platform_user_id: str, operation_id: str) -> DemonAbyssRunRecord:
        operation_name = "demon_abyss.enter"
        request_hash = self._request_hash(
            operation_name,
            {"platform": platform, "platform_user_id": platform_user_id, "instance_key": DEMON_ABYSS_KEY},
        )
        now = self._now()
        now_text = serialize_datetime(now)
        quota_key = self._demon_week_key(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._demon_operation(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                return self._demon_record(replay, replay=True)

            player = self._require_player(connection, platform, platform_user_id)
            if (
                str(player["location_key"]) != DEMON_ABYSS_LOCATION
                or not realm_at_least(str(player["realm_key"]), int(player["realm_layer"]), "foundation", 1)
            ):
                raise DemonAbyssRequirementError("realm or location requirement is not met")
            intro = self._json_object(player["intro_json"], {})
            if DEMON_ABYSS_REQUIRED_FLAG not in set(intro.get("flags", [])):
                raise DemonAbyssRequirementError("demon-abyss gate access is missing")
            faction = self._json_object(player["faction_reputation_json"], {})
            if int(faction.get("demon", 0)) < 200:
                raise DemonAbyssRequirementError("demon reputation is too low")
            active_run = connection.execute(
                "SELECT 1 FROM secret_realm_runs WHERE player_id=? "
                "AND status IN ('entered','routing','combat_pending','cleared','failed') LIMIT 1",
                (player["id"],),
            ).fetchone()
            if active_run is not None:
                raise DemonAbyssBusyError("another secret-realm run is active")
            if self._has_active_long_action(connection, int(player["id"])):
                raise DemonAbyssBusyError("another long action is active")
            attempts = connection.execute(
                "SELECT COUNT(*) AS count FROM secret_realm_runs WHERE player_id=? AND instance_key=? AND quota_key=?",
                (player["id"], DEMON_ABYSS_KEY, quota_key),
            ).fetchone()
            if int(attempts["count"]) >= DEMON_ABYSS_QUOTA_LIMIT:
                raise DemonAbyssQuotaError("demon-abyss weekly quota is exhausted")
            if int(player["stamina"]) < DEMON_ABYSS_STAMINA_COST:
                raise ResourceInsufficientError("stamina is insufficient")

            run_id = uuid4().hex
            snapshot = {
                "instance_key": DEMON_ABYSS_KEY,
                "location_key": DEMON_ABYSS_LOCATION,
                "realm_key": str(player["realm_key"]),
                "realm_layer": int(player["realm_layer"]),
                "access_flag": DEMON_ABYSS_REQUIRED_FLAG,
                "demon_reputation": int(faction.get("demon", 0)),
                "pollution_before": int(player["pollution"]),
                "pollution_delta": 0,
                "risk_base_bp": DEMON_ABYSS_RISK_BASE_BP,
                "risk_modifier_bp": DEMON_ABYSS_RISK_MODIFIER_BP,
                "random_seed": uuid4().hex,
                "node_keys": list(DEMON_ABYSS_NODES),
                "first_clear": self._is_first_clear(connection, int(player["id"]), DEMON_ABYSS_KEY),
            }
            expires_at = serialize_datetime(now + timedelta(seconds=DEMON_ABYSS_EXPIRY_SECONDS))
            connection.execute(
                "UPDATE players SET stamina=stamina-?, updated_at=? WHERE id=? AND stamina>=?",
                (DEMON_ABYSS_STAMINA_COST, now_text, player["id"], DEMON_ABYSS_STAMINA_COST),
            )
            connection.execute(
                """
                INSERT INTO secret_realm_runs(
                    run_id, player_id, instance_key, status, node_index, starts_at, expires_at,
                    quota_period, quota_key, ticket_key, ticket_locked, stamina_locked,
                    snapshot_json, result_json, created_at, updated_at
                ) VALUES (?, ?, ?, 'routing', 0, ?, ?, 'week', ?, NULL, 0, ?, ?, '{}', ?, ?)
                """,
                (
                    run_id, player["id"], DEMON_ABYSS_KEY, now_text, expires_at, quota_key,
                    DEMON_ABYSS_STAMINA_COST, json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
                    now_text, now_text,
                ),
            )
            run = connection.execute("SELECT * FROM secret_realm_runs WHERE run_id=?", (run_id,)).fetchone()
            updated = connection.execute("SELECT * FROM players WHERE id=?", (player["id"],)).fetchone()
            payload = self._demon_payload(updated, run, snapshot, {})
            self._demon_store_operation(connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text)
            return self._demon_record(payload)

    async def choose_demon_abyss_node(
        self, *, platform: str, platform_user_id: str, node_key: str, operation_id: str
    ) -> DemonAbyssRunRecord:
        await self.initialize()
        async with self._inflight:
            record = await asyncio.to_thread(
                self._demon_choose_sync, platform, platform_user_id, node_key, operation_id
            )
        if record.status != "combat_pending":
            return record
        return await self._ensure_demon_battle(record, platform, platform_user_id, operation_id)

    def _demon_choose_sync(
        self, platform: str, platform_user_id: str, node_key: str, operation_id: str
    ) -> DemonAbyssRunRecord:
        operation_name = "demon_abyss.choose_node"
        request_hash = self._request_hash(
            operation_name,
            {"platform": platform, "platform_user_id": platform_user_id, "node_key": node_key},
        )
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._demon_operation(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                return self._demon_record(replay, replay=True)
            player = self._require_player(connection, platform, platform_user_id)
            run = self._active_demon_run(connection, int(player["id"]))
            if run is None:
                raise DemonAbyssNotFoundError("no active demon-abyss run")
            if self._demon_run_expired(run, now):
                raise DemonAbyssNotReadyError("demon-abyss run expired")
            if str(run["status"]) != "routing":
                raise DemonAbyssNotReadyError("demon-abyss run is not routing")
            snapshot = self._json_object(run["snapshot_json"], {})
            result = self._json_object(run["result_json"], {})
            nodes = tuple(str(item) for item in snapshot.get("node_keys", DEMON_ABYSS_NODES))
            node_index = int(run["node_index"])
            if node_index >= len(nodes) or nodes[node_index] != node_key:
                raise DemonAbyssNodeError("node is not the current route node")

            next_index = node_index
            next_status = "combat_pending" if node_key in DEMON_ABYSS_ENEMIES else "routing"
            if node_key == "pollution_seep":
                base_bp = int(snapshot["risk_base_bp"])
                modifier_bp = int(snapshot["risk_modifier_bp"])
                risk_bp = max(0, min(10_000, base_bp + modifier_bp))
                roll_bp = demon_abyss_risk_roll_bp(f"{snapshot['random_seed']}:{node_key}")
                pollution_before = int(player["pollution"])
                polluted = demon_abyss_risk_applies(roll_bp, risk_bp)
                pollution_after = min(100, pollution_before + (1 if polluted else 0))
                if pollution_after != pollution_before:
                    connection.execute(
                        "UPDATE players SET pollution=?, updated_at=? WHERE id=?",
                        (pollution_after, now_text, player["id"]),
                    )
                    snapshot["pollution_delta"] = int(snapshot.get("pollution_delta", 0)) + pollution_after - pollution_before
                snapshot["pollution_risk"] = {
                    "base_bp": base_bp,
                    "modifier_bp": modifier_bp,
                    "final_bp": risk_bp,
                    "roll_bp": roll_bp,
                    "polluted": polluted,
                    "pollution_before": pollution_before,
                    "pollution_after": pollution_after,
                }
                next_index += 1
            elif next_status != "combat_pending":
                next_index += 1

            connection.execute(
                "UPDATE secret_realm_runs SET status=?, node_index=?, battle_id=NULL, snapshot_json=?, updated_at=? WHERE id=?",
                (next_status, next_index, json.dumps(snapshot, ensure_ascii=False, sort_keys=True), now_text, run["id"]),
            )
            updated_player = connection.execute("SELECT * FROM players WHERE id=?", (player["id"],)).fetchone()
            updated_run = connection.execute("SELECT * FROM secret_realm_runs WHERE id=?", (run["id"],)).fetchone()
            payload = self._demon_payload(updated_player, updated_run, snapshot, result)
            self._demon_store_operation(connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text)
            return self._demon_record(payload)

    async def _ensure_demon_battle(
        self,
        record: DemonAbyssRunRecord,
        platform: str,
        platform_user_id: str,
        choose_operation_id: str,
    ) -> DemonAbyssRunRecord:
        if record.battle_id:
            return record
        enemy_key = DEMON_ABYSS_ENEMIES.get(record.current_node or "")
        if enemy_key is None:
            raise DemonAbyssNotReadyError("the current demon-abyss node has no encounter")
        battle_operation = f"demon_abyss.battle.start:{record.run_id}:{record.node_index}"
        battle = await self.start_quest_battle(
            platform=platform,
            platform_user_id=platform_user_id,
            enemy_key=enemy_key,
            battle_type="pve.secret_realm.demon_abyss",
            operation_id=battle_operation,
            ignore_secret_realm_run_id=record.run_id,
        )
        return await asyncio.to_thread(
            self._demon_attach_battle, record.run_id, battle.battle_id, choose_operation_id
        )

    def _demon_attach_battle(self, run_id: str, battle_id: str, choose_operation_id: str) -> DemonAbyssRunRecord:
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            run = connection.execute("SELECT * FROM secret_realm_runs WHERE run_id=?", (run_id,)).fetchone()
            if run is None or str(run["status"]) != "combat_pending":
                raise DemonAbyssNotReadyError("demon-abyss encounter is no longer pending")
            attached = str(run["battle_id"] or battle_id)
            connection.execute(
                "UPDATE secret_realm_runs SET battle_id=?, updated_at=? WHERE id=?",
                (attached, now_text, run["id"]),
            )
            player = connection.execute("SELECT * FROM players WHERE id=?", (run["player_id"],)).fetchone()
            snapshot = self._json_object(run["snapshot_json"], {})
            result = self._json_object(run["result_json"], {})
            payload = self._demon_payload(player, run, snapshot, result)
            payload["battle_id"] = attached
            connection.execute(
                "UPDATE operations SET result_json=? WHERE operation_id=? AND operation_name='demon_abyss.choose_node'",
                (json.dumps(payload, ensure_ascii=False, sort_keys=True), choose_operation_id),
            )
            return self._demon_record(payload)

    async def settle_demon_abyss(
        self, *, platform: str, platform_user_id: str, operation_id: str
    ) -> DemonAbyssRunRecord:
        await self.initialize()
        operation_name = "demon_abyss.settle"
        request_hash = self._request_hash(operation_name, {"platform": platform, "platform_user_id": platform_user_id})
        replay = await asyncio.to_thread(
            self._demon_settle_replay, operation_id, operation_name, request_hash
        )
        if replay is not None:
            return self._demon_record(replay, replay=True)
        pending = await asyncio.to_thread(self._demon_pending_sync, platform, platform_user_id)
        expired = datetime.fromisoformat(pending.expires_at).astimezone(timezone.utc) <= self._now()
        if pending.status == "combat_pending":
            if expired:
                if pending.battle_id and await self.expire_battle_session(
                    battle_id=pending.battle_id, reason="secret_realm_expired"
                ):
                    await self.resolve_battle(battle_id=pending.battle_id)
            else:
                pending = await self._ensure_demon_battle(pending, platform, platform_user_id, "")
                turn = None
                for expected_round in range(1, 21):
                    turn = await self.run_battle_turn(battle_id=str(pending.battle_id), expected_round=expected_round)
                    if turn.status not in {"created", "running"}:
                        break
                if turn is None or turn.status in {"created", "running"}:
                    raise DemonAbyssNotReadyError("demon-abyss battle is still running")
                battle = await self.resolve_battle(battle_id=str(pending.battle_id))
                await asyncio.to_thread(self._demon_apply_battle_result, pending.run_id, battle.outcome)
                progress = await asyncio.to_thread(self._demon_pending_sync, platform, platform_user_id)
                if progress.status == "routing":
                    return await asyncio.to_thread(
                        self._demon_record_progress, progress.run_id, platform, platform_user_id,
                        operation_id, operation_name, request_hash,
                    )
        async with self._inflight:
            return await asyncio.to_thread(
                self._demon_settle_sync, platform, platform_user_id, operation_id
            )

    def _demon_settle_replay(self, operation_id: str, operation_name: str, request_hash: str):
        with self._connect() as connection:
            return self._demon_operation(connection, operation_id, operation_name, request_hash)

    def _demon_pending_sync(self, platform: str, platform_user_id: str) -> DemonAbyssRunRecord:
        with self._connect() as connection:
            player = self._require_player(connection, platform, platform_user_id)
            run = self._active_demon_run(connection, int(player["id"]))
            if run is None:
                raise DemonAbyssNotFoundError("no active demon-abyss run")
            return self._demon_record(
                self._demon_payload(
                    player,
                    run,
                    self._json_object(run["snapshot_json"], {}),
                    self._json_object(run["result_json"], {}),
                )
            )

    @staticmethod
    def _active_demon_run(connection, player_id: int):
        return connection.execute(
            "SELECT * FROM secret_realm_runs WHERE player_id=? AND instance_key=? "
            "AND status IN ('entered','routing','combat_pending','cleared','failed') ORDER BY id DESC LIMIT 1",
            (player_id, DEMON_ABYSS_KEY),
        ).fetchone()

    def _demon_apply_battle_result(self, run_id: str, outcome: str) -> None:
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            run = connection.execute("SELECT * FROM secret_realm_runs WHERE run_id=?", (run_id,)).fetchone()
            if run is None or str(run["status"]) != "combat_pending":
                return
            snapshot = self._json_object(run["snapshot_json"], {})
            node_key = str(snapshot["node_keys"][int(run["node_index"])])
            battles = dict(snapshot.get("battle_results", {}))
            battles[node_key] = {"battle_id": run["battle_id"], "outcome": outcome}
            snapshot["battle_results"] = battles
            if outcome == "won":
                next_index = int(run["node_index"]) + 1
                next_status = "cleared" if next_index == len(snapshot["node_keys"]) else "routing"
            else:
                next_index = int(run["node_index"])
                next_status = "failed"
            connection.execute(
                "UPDATE secret_realm_runs SET status=?, node_index=?, snapshot_json=?, updated_at=? WHERE id=?",
                (next_status, next_index, json.dumps(snapshot, ensure_ascii=False, sort_keys=True), now_text, run["id"]),
            )

    def _demon_record_progress(
        self, run_id: str, platform: str, platform_user_id: str, operation_id: str,
        operation_name: str, request_hash: str,
    ) -> DemonAbyssRunRecord:
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._demon_operation(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                return self._demon_record(replay, replay=True)
            player = self._require_player(connection, platform, platform_user_id)
            run = connection.execute(
                "SELECT * FROM secret_realm_runs WHERE run_id=? AND player_id=?",
                (run_id, player["id"]),
            ).fetchone()
            if run is None:
                raise DemonAbyssNotFoundError("demon-abyss run does not exist")
            snapshot = self._json_object(run["snapshot_json"], {})
            result = self._json_object(run["result_json"], {})
            payload = self._demon_payload(player, run, snapshot, result)
            self._demon_store_operation(
                connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text
            )
            return self._demon_record(payload)

    def _demon_settle_sync(self, platform: str, platform_user_id: str, operation_id: str) -> DemonAbyssRunRecord:
        operation_name = "demon_abyss.settle"
        request_hash = self._request_hash(operation_name, {"platform": platform, "platform_user_id": platform_user_id})
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._demon_operation(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                return self._demon_record(replay, replay=True)
            player = self._require_player(connection, platform, platform_user_id)
            run = self._active_demon_run(connection, int(player["id"]))
            if run is None:
                raise DemonAbyssNotFoundError("no active demon-abyss run")
            status = str(run["status"])
            snapshot = self._json_object(run["snapshot_json"], {})
            if self._demon_run_expired(run, now):
                result = {"reward": {}, "outcome": "expired", "first_clear": False}
            elif status == "failed":
                result = {"reward": {}, "outcome": "lost", "first_clear": False}
            elif status == "cleared":
                first_clear = bool(snapshot.get("first_clear"))
                reward = dict(DEMON_ABYSS_FIRST_REWARD if first_clear else DEMON_ABYSS_REPEAT_REWARD)
                self._demon_apply_reward(connection, player, reward, now_text)
                result = {"reward": reward, "outcome": "won", "first_clear": first_clear}
            elif status in {"routing", "combat_pending", "entered"}:
                raise DemonAbyssNotReadyError("complete the current route node before settling")
            else:
                raise DemonAbyssNotReadyError("demon-abyss run is not ready to settle")

            connection.execute(
                "UPDATE secret_realm_runs SET status='settled', result_json=?, updated_at=? WHERE id=?",
                (json.dumps(result, ensure_ascii=False, sort_keys=True), now_text, run["id"]),
            )
            updated = connection.execute("SELECT * FROM players WHERE id=?", (player["id"],)).fetchone()
            settled = connection.execute("SELECT * FROM secret_realm_runs WHERE id=?", (run["id"],)).fetchone()
            payload = self._demon_payload(
                updated, settled, snapshot, result
            )
            self._demon_store_operation(connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text)
            return self._demon_record(payload)

    @staticmethod
    def _demon_apply_reward(connection, player, reward: dict[str, int], now_text: str) -> None:
        inventory = inventory_value(player["inventory_json"])
        intro = player_object(player, "intro_json")
        faction = player_reputation(player)
        flags = list(player_intro_flags(player))
        for key, quantity in reward.items():
            if key == "faction_reputation.demon":
                faction["demon"] = int(faction.get("demon", 0)) + int(quantity)
            elif key.startswith("item."):
                inventory = inventory_grant(inventory, {key: quantity})
            elif key.startswith("story.") and key not in flags:
                flags.append(key)
        intro["flags"] = flags
        connection.execute(
            "UPDATE players SET inventory_json=?, intro_json=?, faction_reputation_json=?, updated_at=? WHERE id=?",
            (
                inventory_json(inventory),
                json.dumps(intro, ensure_ascii=False, sort_keys=True),
                json.dumps(faction, ensure_ascii=False, sort_keys=True),
                now_text,
                player["id"],
            ),
        )

    async def compensate_demon_abyss_system_failure(
        self, *, run_id: str, operation_id: str
    ) -> DemonAbyssRunRecord:
        """Refund an operator-aborted run only after any battle is terminal."""

        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._demon_compensate_system_failure_sync, run_id, operation_id
            )

    def _demon_compensate_system_failure_sync(self, run_id: str, operation_id: str) -> DemonAbyssRunRecord:
        operation_name = "demon_abyss.system_abort"
        request_hash = self._request_hash(operation_name, {"run_id": run_id})
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._demon_operation(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                return self._demon_record(replay, replay=True)
            run = connection.execute(
                "SELECT * FROM secret_realm_runs WHERE run_id=? AND instance_key=?",
                (run_id, DEMON_ABYSS_KEY),
            ).fetchone()
            if run is None or str(run["status"]) not in ACTIVE_RUN_STATUSES:
                raise DemonAbyssNotReadyError("only an active demon-abyss run can be compensated")
            if run["battle_id"]:
                battle = connection.execute(
                    "SELECT status FROM battle_sessions WHERE battle_id=?", (run["battle_id"],)
                ).fetchone()
                if battle is not None and str(battle["status"]) in {"created", "running"}:
                    raise DemonAbyssNotReadyError("resolve the active automatic battle before compensation")
            player = connection.execute("SELECT * FROM players WHERE id=?", (run["player_id"],)).fetchone()
            snapshot = self._json_object(run["snapshot_json"], {})
            pollution_delta = int(snapshot.get("pollution_delta", 0))
            connection.execute(
                "UPDATE players SET stamina=MIN(stamina_max, stamina+?), pollution=MAX(0, pollution-?), updated_at=? WHERE id=?",
                (int(run["stamina_locked"]), pollution_delta, now_text, player["id"]),
            )
            quota_key = f"system_aborted:{run_id}"
            result = {
                "reward": {},
                "outcome": "system_aborted",
                "first_clear": False,
                "stamina_refunded": int(run["stamina_locked"]),
                "quota_released": True,
                "pollution_rolled_back": pollution_delta,
                "pollution_after": max(0, int(player["pollution"]) - pollution_delta),
            }
            connection.execute(
                "UPDATE secret_realm_runs SET status='settled', quota_key=?, result_json=?, updated_at=? WHERE id=?",
                (quota_key, json.dumps(result, ensure_ascii=False, sort_keys=True), now_text, run["id"]),
            )
            updated = connection.execute("SELECT * FROM players WHERE id=?", (player["id"],)).fetchone()
            settled = connection.execute("SELECT * FROM secret_realm_runs WHERE id=?", (run["id"],)).fetchone()
            payload = self._demon_payload(updated, settled, snapshot, result)
            self._demon_store_operation(
                connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text
            )
            return self._demon_record(payload)

    @staticmethod
    def _demon_run_expired(run: sqlite3.Row, now: datetime) -> bool:
        return now >= datetime.fromisoformat(str(run["expires_at"])).astimezone(timezone.utc)


__all__ = ["DemonAbyssRepositoryMixin"]
