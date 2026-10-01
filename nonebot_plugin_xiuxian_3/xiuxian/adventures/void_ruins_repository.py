"""Persistence for the void-ruins party instance."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from ...contracts import serialize_datetime
from ..advancement.constitution_effects import constitution_effect_snapshot
from ..combat.rules import enemy_definition, player_stat_snapshot
from ..persistence.errors import (
    OperationConflictError,
    ResourceInsufficientError,
    VoidRuinsBusyError,
    VoidRuinsNodeError,
    VoidRuinsNotFoundError,
    VoidRuinsNotReadyError,
    VoidRuinsQuotaError,
    VoidRuinsRequirementError,
)
from ..social.party_rules import PARTY_TYPE_SECRET_REALM_VOID_RUINS
from ..specials.codex_projection import record_codex_discovery
from ..utils.assets import grant_player_assets, inventory_amount, spend_player_items
from ..utils.player import (
    change_player_state,
    player_combat_values,
    player_integer,
    player_inventory,
    player_resource,
)
from .secret_realm_rules import realm_at_least
from .void_ruins_models import VoidRuinsRunRecord
from .void_ruins_rules import (
    VOID_RUINS_ANCHOR_LOCK,
    VOID_RUINS_CODEX,
    VOID_RUINS_ENEMIES,
    VOID_RUINS_EXPIRY_SECONDS,
    VOID_RUINS_KEY,
    VOID_RUINS_LOCATION,
    VOID_RUINS_MAX_MEMBERS,
    VOID_RUINS_MIN_MEMBERS,
    VOID_RUINS_NODES,
    VOID_RUINS_PARTY_TYPE,
    VOID_RUINS_REPEAT_REWARD,
    VOID_RUINS_ROUTE_PERMISSION,
    VOID_RUINS_STAMINA_COST,
    VOID_RUINS_WEEKLY_LIMIT,
)


ACTIVE_STATUSES = ("routing", "combat_pending", "cleared")


class VoidRuinsRepositoryMixin:
    """Own admission, route progression, escrow, and reward transactions."""

    @staticmethod
    def _void_ruins_json(raw: Any, default: dict[str, Any] | None = None) -> dict[str, Any]:
        value = json.loads(raw) if isinstance(raw, str) else raw
        return dict(value) if isinstance(value, dict) else dict(default or {})

    @staticmethod
    def _void_ruins_week(now: datetime) -> str:
        return now.astimezone(timezone.utc).strftime("%G-W%V")

    def _void_ruins_operation(self, connection, operation_id: str, operation_name: str, request_hash: str):
        row = connection.execute(
            "SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id=?",
            (operation_id,),
        ).fetchone()
        if row is None:
            return None
        if str(row["operation_name"]) != operation_name or str(row["request_hash"]) != request_hash:
            raise OperationConflictError("operation ID was reused with different input")
        return self._void_ruins_json(row["result_json"])

    @staticmethod
    def _void_ruins_store_operation(connection, operation_id, operation_name, player_id, request_hash, payload, now_text):
        connection.execute(
            "INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (operation_id, operation_name, player_id, request_hash, json.dumps(payload, ensure_ascii=False, sort_keys=True), now_text),
        )

    @classmethod
    def _void_ruins_payload(cls, run, snapshot: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        index = int(run["node_index"])
        status = str(run["status"])
        current = snapshot.get("current_node")
        if status in {"routing", "combat_pending"} and current is None and index < len(VOID_RUINS_NODES):
            current = VOID_RUINS_NODES[index]
        return {
            "run_id": str(run["run_id"]),
            "party_id": str(run["party_id"]),
            "status": status,
            "node_index": index,
            "current_node": current if status in {"routing", "combat_pending"} else None,
            "battle_id": run["battle_id"],
            "expires_at": str(run["expires_at"]),
            "rewards": result.get("rewards", {}),
            "first_clear_members": result.get("first_clear_members", []),
            "outcome": result.get("outcome", result.get("last_battle_outcome")),
        }

    @classmethod
    def _void_ruins_record_from_row(cls, connection, run) -> VoidRuinsRunRecord:
        row = run if hasattr(run, "keys") else connection.execute(
            "SELECT * FROM void_ruins_runs WHERE run_id=?", (run,)
        ).fetchone()
        if row is None:
            raise VoidRuinsNotFoundError("void-ruins run does not exist")
        snapshot = cls._void_ruins_json(row["snapshot_json"])
        result = cls._void_ruins_json(row["result_json"])
        payload = cls._void_ruins_payload(row, snapshot, result)
        return cls._void_ruins_record(payload)

    @staticmethod
    def _void_ruins_record(payload: dict[str, Any], *, replay: bool = False) -> VoidRuinsRunRecord:
        return VoidRuinsRunRecord(
            run_id=str(payload["run_id"]),
            party_id=str(payload["party_id"]),
            status=str(payload["status"]),
            node_index=int(payload.get("node_index", 0)),
            current_node=str(payload["current_node"]) if payload.get("current_node") is not None else None,
            battle_id=str(payload["battle_id"]) if payload.get("battle_id") else None,
            expires_at=str(payload.get("expires_at", "")),
            rewards={str(player): {str(key): int(value) for key, value in dict(reward).items()} for player, reward in dict(payload.get("rewards", {})).items()},
            first_clear_members=tuple(str(value) for value in payload.get("first_clear_members", [])),
            outcome=str(payload["outcome"]) if payload.get("outcome") else None,
            already_completed=bool(replay or payload.get("already_completed", False)),
        )

    async def enter_void_ruins(self, *, platform: str, platform_user_id: str, operation_id: str) -> VoidRuinsRunRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._retry_sync, self._void_ruins_enter_sync, platform, platform_user_id, operation_id)

    def _void_ruins_enter_sync(self, platform: str, platform_user_id: str, operation_id: str) -> VoidRuinsRunRecord:
        operation_name = "void_ruins.enter"
        request_hash = self._request_hash(operation_name, {
            "platform": platform, "platform_user_id": platform_user_id, "instance_key": VOID_RUINS_KEY,
        })
        now = self._now()
        now_text = serialize_datetime(now)
        quota_key = self._void_ruins_week(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._void_ruins_operation(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                replay["already_completed"] = True
                return self._void_ruins_record(replay, replay=True)
            leader = self._require_player(connection, platform, platform_user_id)
            membership = connection.execute(
                "SELECT * FROM party_members WHERE player_id=? AND status='active' ORDER BY id DESC LIMIT 1",
                (leader["id"],),
            ).fetchone()
            if membership is None or str(membership["role"]) != "leader":
                raise VoidRuinsRequirementError("only the dedicated-party leader can enter")
            party = connection.execute("SELECT * FROM parties WHERE party_id=?", (membership["party_id"],)).fetchone()
            if (
                party is None or str(party["party_type"]) != VOID_RUINS_PARTY_TYPE
                or str(party["status"]) != "ready" or str(party["location_key"]) != VOID_RUINS_LOCATION
                or party["current_session_id"]
            ):
                raise VoidRuinsRequirementError("a confirmed void-ruins party is required")
            members = connection.execute(
                "SELECT m.role, m.confirmed_at, p.* FROM party_members m JOIN players p ON p.id=m.player_id "
                "WHERE m.party_id=? AND m.status='active' ORDER BY m.id",
                (party["party_id"],),
            ).fetchall()
            if not VOID_RUINS_MIN_MEMBERS <= len(members) <= VOID_RUINS_MAX_MEMBERS or any(not row["confirmed_at"] for row in members):
                raise VoidRuinsRequirementError("two to five confirmed members are required")
            if player_resource(leader, "stamina") < VOID_RUINS_STAMINA_COST:
                raise ResourceInsufficientError("party leader lacks entry stamina")

            combat_snapshots: list[dict[str, Any]] = []
            first_clear: dict[int, bool] = {}
            inventories: dict[int, dict[str, Any]] = {}
            instability: dict[int, bool] = {}
            for row in members:
                player_id = int(row["id"])
                if (
                    str(row["location_key"]) != VOID_RUINS_LOCATION
                    or not realm_at_least(str(row["realm_key"]), player_integer(row, "realm_layer"), "void_refining", 1)
                ):
                    raise VoidRuinsRequirementError("a member lacks void-refining realm or archive location")
                if self._has_active_long_action(connection, player_id):
                    raise VoidRuinsBusyError("a member has another active action")
                if connection.execute(
                    "SELECT 1 FROM party_battle_members WHERE player_id=? AND asset_lock_status='locked' LIMIT 1",
                    (player_id,),
                ).fetchone():
                    raise VoidRuinsBusyError("a member has locked battle assets")
                if connection.execute(
                    "SELECT 1 FROM void_ruins_members WHERE player_id=? AND status='active' LIMIT 1",
                    (player_id,),
                ).fetchone():
                    raise VoidRuinsBusyError("a member already has an active void-ruins run")
                if int(connection.execute(
                    "SELECT COUNT(*) FROM void_ruins_members WHERE player_id=? AND quota_key=? AND status<>'system_aborted'",
                    (player_id, quota_key),
                ).fetchone()[0]) >= VOID_RUINS_WEEKLY_LIMIT:
                    raise VoidRuinsQuotaError("a member already used this UTC week")
                inventory = player_inventory(row)
                if inventory_amount(inventory, "item.void_anchor") < VOID_RUINS_ANCHOR_LOCK:
                    raise VoidRuinsRequirementError("a member lacks a void anchor to lock")
                inventories[player_id] = inventory
                unstable_until = row["void_instability_until"]
                unstable = False
                if unstable_until:
                    try:
                        unstable = datetime.fromisoformat(str(unstable_until)) > now
                    except ValueError:
                        unstable = False
                instability[player_id] = unstable
                player_state = player_combat_values(row)
                equipment = self._battle_equipment_snapshot(connection, player_id)
                qualification = player_state["qualification"]
                constitution_effect = constitution_effect_snapshot(connection, player_id)
                skills = self._battle_skill_snapshot(connection, player_id, str(row["path_key"] or ""))
                stats = player_stat_snapshot(
                    qualification, max_hp=player_state["max_hp"], initiative=player_state["initiative"], equipment=equipment,
                    constitution_effect=constitution_effect,
                )
                first_clear[player_id] = connection.execute(
                    "SELECT 1 FROM void_ruins_members WHERE player_id=? AND status='settled' LIMIT 1", (player_id,)
                ).fetchone() is None
                combat_snapshots.append({
                    "database_id": player_id,
                    "player_id": player_state["player_id"],
                    "platform": player_state["platform"],
                    "platform_user_id": player_state["platform_user_id"],
                    "role": str(row["role"]),
                    "realm_key": player_state["realm_key"],
                    "realm_layer": player_state["realm_layer"],
                    "location_key": player_state["location_key"],
                    "path_key": player_state["path_key"],
                    "qualification": qualification,
                    "stats": stats,
                    "constitution_effect": constitution_effect,
                    "equipment": list(equipment),
                    "skills": skills,
                    "void_instability_active": unstable,
                })

            run_id = f"void-ruins-{uuid4().hex}"
            expires_at = serialize_datetime(now + timedelta(seconds=VOID_RUINS_EXPIRY_SECONDS))
            snapshot = {
                "instance_key": VOID_RUINS_KEY,
                "party_type": VOID_RUINS_PARTY_TYPE,
                "party_id": str(party["party_id"]),
                "location_key": VOID_RUINS_LOCATION,
                "node_keys": list(VOID_RUINS_NODES),
                "current_node": VOID_RUINS_NODES[0],
                "members": [
                    {"database_id": item["database_id"], "player_id": item["player_id"], "role": item["role"]}
                    for item in combat_snapshots
                ],
                "member_combat_snapshots": combat_snapshots,
                "instability_active_by_player": {str(key): value for key, value in instability.items()},
                "first_clear_by_player": {str(key): value for key, value in first_clear.items()},
                "entry_cost": {"leader_stamina": VOID_RUINS_STAMINA_COST, "void_anchor_per_member": VOID_RUINS_ANCHOR_LOCK},
            }
            try:
                change_player_state(
                    connection,
                    leader,
                    updated_at=now_text,
                    value_delta={"stamina": -VOID_RUINS_STAMINA_COST},
                )
            except ValueError as exc:
                raise ResourceInsufficientError("party leader stamina changed during entry") from exc
            connection.execute(
                "INSERT INTO void_ruins_runs(run_id, party_id, status, node_index, battle_id, quota_key, starts_at, expires_at, stamina_cost, snapshot_json, result_json, entry_operation_id, created_at, updated_at) "
                "VALUES (?, ?, 'routing', 0, NULL, ?, ?, ?, ?, ?, '{}', ?, ?, ?)",
                (run_id, party["party_id"], quota_key, now_text, expires_at, VOID_RUINS_STAMINA_COST,
                 json.dumps(snapshot, ensure_ascii=False, sort_keys=True), operation_id,
                 now_text, now_text),
            )
            for index, row in enumerate(members):
                player_id = int(row["id"])
                spend_player_items(
                    connection,
                    row,
                    {"item.void_anchor": VOID_RUINS_ANCHOR_LOCK},
                    now_text,
                )
                connection.execute(
                    "INSERT INTO void_ruins_members(run_id, player_id, quota_key, member_order, first_clear, status, anchor_status, reward_json, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, 'active', 'locked', '{}', ?, ?)",
                    (run_id, player_id, quota_key, index, int(first_clear[player_id]), now_text, now_text),
                )
            run = connection.execute("SELECT * FROM void_ruins_runs WHERE run_id=?", (run_id,)).fetchone()
            payload = self._void_ruins_payload(run, snapshot, {})
            self._void_ruins_store_operation(connection, operation_id, operation_name, int(leader["id"]), request_hash, payload, now_text)
            return self._void_ruins_record(payload)

    async def choose_void_ruins_node(
        self, *, platform: str, platform_user_id: str, node_key: str, operation_id: str
    ) -> VoidRuinsRunRecord:
        await self.initialize()
        async with self._inflight:
            record = await asyncio.to_thread(
                self._retry_sync, self._void_ruins_choose_sync, platform, platform_user_id, node_key, operation_id,
            )
        if record.status == "expired":
            await self._void_ruins_end_expired_battle(record)
            return record
        if record.status != "combat_pending" or record.battle_id:
            return record
        try:
            battle = await self._start_void_ruins_battle(record.run_id, platform, platform_user_id)
            return await asyncio.to_thread(self._void_ruins_attach_battle, record.run_id, battle.battle_id, operation_id)
        except Exception:
            await self.compensate_void_ruins_system_failure(run_id=record.run_id)
            raise

    def _void_ruins_choose_sync(self, platform, platform_user_id, node_key, operation_id):
        operation_name = "void_ruins.choose_node"
        request_hash = self._request_hash(operation_name, {
            "platform": platform, "platform_user_id": platform_user_id, "node_key": node_key,
        })
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._void_ruins_operation(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                replay["already_completed"] = True
                return self._void_ruins_record(replay, replay=True)
            actor = self._require_player(connection, platform, platform_user_id)
            run = self._active_void_ruins_for_actor(connection, int(actor["id"]))
            if run is None:
                raise VoidRuinsNotFoundError("no active void-ruins run")
            party = connection.execute("SELECT leader_id FROM parties WHERE party_id=?", (run["party_id"],)).fetchone()
            if party is None or int(party["leader_id"]) != int(actor["id"]):
                raise VoidRuinsRequirementError("only party leader can advance the route")
            if now_text >= str(run["expires_at"]):
                self._void_ruins_expire(connection, run, now_text)
                expired = connection.execute("SELECT * FROM void_ruins_runs WHERE run_id=?", (run["run_id"],)).fetchone()
                snapshot = self._void_ruins_json(expired["snapshot_json"])
                payload = self._void_ruins_payload(expired, snapshot, self._void_ruins_json(expired["result_json"]))
                self._void_ruins_store_operation(connection, operation_id, operation_name, int(actor["id"]), request_hash, payload, now_text)
                return self._void_ruins_record(payload)
            if str(run["status"]) != "routing":
                raise VoidRuinsNotReadyError("the current route node is not ready")
            snapshot = self._void_ruins_json(run["snapshot_json"])
            index = int(run["node_index"])
            expected = VOID_RUINS_NODES[index] if index < len(VOID_RUINS_NODES) else None
            if node_key != expected:
                raise VoidRuinsNodeError("node is not the current route node")
            if node_key in {"rift_sentinel", "archive_keeper"}:
                snapshot["current_node"] = node_key
                connection.execute(
                    "UPDATE void_ruins_runs SET status='combat_pending', snapshot_json=?, updated_at=? WHERE run_id=?",
                    (json.dumps(snapshot, ensure_ascii=False, sort_keys=True), now_text, run["run_id"]),
                )
            else:
                index += 1
                status = "cleared" if index >= len(VOID_RUINS_NODES) else "routing"
                snapshot["current_node"] = VOID_RUINS_NODES[index] if status == "routing" else None
                connection.execute(
                    "UPDATE void_ruins_runs SET status=?, node_index=?, snapshot_json=?, updated_at=? WHERE run_id=?",
                    (status, index, json.dumps(snapshot, ensure_ascii=False, sort_keys=True), now_text, run["run_id"]),
                )
            updated = connection.execute("SELECT * FROM void_ruins_runs WHERE run_id=?", (run["run_id"],)).fetchone()
            payload = self._void_ruins_payload(updated, snapshot, {})
            self._void_ruins_store_operation(connection, operation_id, operation_name, int(actor["id"]), request_hash, payload, now_text)
            return self._void_ruins_record(payload)

    async def _start_void_ruins_battle(self, run_id: str, platform: str, platform_user_id: str):
        identity = await asyncio.to_thread(self._void_ruins_leader_identity, run_id)
        if identity is None:
            raise VoidRuinsNotFoundError("void-ruins party leader no longer exists")
        run, leader_platform, leader_user = identity
        snapshot = self._void_ruins_json(run["snapshot_json"])
        node_key = str(snapshot.get("current_node", ""))
        unstable = any(bool(value) for value in snapshot.get("instability_active_by_player", {}).values())
        enemy_key = VOID_RUINS_ENEMIES.get((node_key, unstable))
        if enemy_key is None:
            raise VoidRuinsNotReadyError("the selected route node has no registered enemy")
        return await self.start_party_battle(
            platform=leader_platform,
            platform_user_id=leader_user,
            party_id=str(run["party_id"]),
            operation_id=f"void_ruins.battle.start:{run_id}:{int(run['node_index'])}",
            void_ruins_run_id=run_id,
        )

    def _void_ruins_leader_identity(self, run_id: str):
        with self._connect() as connection:
            run = connection.execute("SELECT * FROM void_ruins_runs WHERE run_id=?", (run_id,)).fetchone()
            if run is None:
                return None
            leader = connection.execute(
                "SELECT p.platform, p.platform_user_id FROM parties t JOIN players p ON p.id=t.leader_id WHERE t.party_id=?",
                (run["party_id"],),
            ).fetchone()
            if leader is None:
                return None
            return run, str(leader["platform"]), str(leader["platform_user_id"])

    def _void_ruins_attach_battle(self, run_id: str, battle_id: str, choose_operation_id: str):
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            run = connection.execute("SELECT * FROM void_ruins_runs WHERE run_id=?", (run_id,)).fetchone()
            if run is None or str(run["status"]) != "combat_pending":
                raise VoidRuinsNotReadyError("void-ruins node is no longer pending combat")
            connection.execute(
                "UPDATE void_ruins_runs SET battle_id=?, updated_at=? WHERE run_id=?",
                (battle_id, now_text, run_id),
            )
            updated = connection.execute("SELECT * FROM void_ruins_runs WHERE run_id=?", (run_id,)).fetchone()
            snapshot = self._void_ruins_json(updated["snapshot_json"])
            payload = self._void_ruins_payload(updated, snapshot, self._void_ruins_json(updated["result_json"]))
            connection.execute(
                "UPDATE operations SET result_json=? WHERE operation_id=? AND operation_name='void_ruins.choose_node'",
                (json.dumps(payload, ensure_ascii=False, sort_keys=True), choose_operation_id),
            )
            return self._void_ruins_record(payload)

    async def settle_void_ruins(self, *, platform: str, platform_user_id: str, operation_id: str) -> VoidRuinsRunRecord:
        await self.initialize()
        operation_name = "void_ruins.settle"
        request_hash = self._request_hash(operation_name, {"platform": platform, "platform_user_id": platform_user_id})
        replay = await asyncio.to_thread(self._void_ruins_read_operation, operation_id, operation_name, request_hash)
        if replay is not None:
            replay["already_completed"] = True
            return self._void_ruins_record(replay, replay=True)
        record = await asyncio.to_thread(self._void_ruins_get_latest_for_actor, platform, platform_user_id)
        if record is None:
            raise VoidRuinsNotFoundError("no void-ruins run exists")
        if record.status in ACTIVE_STATUSES and serialize_datetime(self._now()) >= record.expires_at:
            record = await asyncio.to_thread(self._void_ruins_expire_by_id, record.run_id)
            await self._void_ruins_end_expired_battle(record)
        elif record.status == "combat_pending":
            if not record.battle_id:
                identity = await asyncio.to_thread(self._void_ruins_leader_identity, record.run_id)
                if identity is None:
                    raise VoidRuinsNotFoundError("void-ruins party leader no longer exists")
                _, lead_platform, lead_user = identity
                try:
                    battle = await self._start_void_ruins_battle(record.run_id, lead_platform, lead_user)
                    record = await asyncio.to_thread(self._void_ruins_attach_battle, record.run_id, battle.battle_id, "")
                except Exception:
                    await self.compensate_void_ruins_system_failure(run_id=record.run_id)
                    raise
            battle_result = await self.settle_party_battle(
                platform=platform,
                platform_user_id=platform_user_id,
                battle_id=record.battle_id,
                operation_id=f"void_ruins.battle.settle:{record.run_id}:{record.node_index}",
            )
            record = await asyncio.to_thread(self._void_ruins_record_battle_outcome, record.run_id, battle_result.outcome)
            if record.status == "routing":
                return await asyncio.to_thread(
                    self._void_ruins_record_progress,
                    record.run_id,
                    platform,
                    platform_user_id,
                    operation_id,
                    operation_name,
                    request_hash,
                )
        return await asyncio.to_thread(
            self._void_ruins_settle_sync, platform, platform_user_id, operation_id, operation_name, request_hash,
        )

    def _void_ruins_read_operation(self, operation_id: str, operation_name: str, request_hash: str):
        with self._connect() as connection:
            return self._void_ruins_operation(connection, operation_id, operation_name, request_hash)

    def _void_ruins_get_latest_for_actor(self, platform: str, platform_user_id: str):
        with self._connect() as connection:
            actor = connection.execute(
                "SELECT id FROM players WHERE platform=? AND platform_user_id=?", (platform, platform_user_id)
            ).fetchone()
            if actor is None:
                raise VoidRuinsNotFoundError("player does not exist")
            run = self._latest_void_ruins_for_actor(connection, int(actor["id"]))
            return self._void_ruins_record_from_row(connection, run) if run is not None else None

    def _void_ruins_record_progress(
        self, run_id: str, platform: str, platform_user_id: str,
        operation_id: str, operation_name: str, request_hash: str,
    ) -> VoidRuinsRunRecord:
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._void_ruins_operation(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                replay["already_completed"] = True
                return self._void_ruins_record(replay, replay=True)
            actor = self._require_player(connection, platform, platform_user_id)
            run = connection.execute(
                "SELECT * FROM void_ruins_runs WHERE run_id=?", (run_id,)
            ).fetchone()
            if run is None or str(run["status"]) != "routing":
                raise VoidRuinsNotReadyError("the battle did not advance the route")
            snapshot = self._void_ruins_json(run["snapshot_json"])
            result = self._void_ruins_json(run["result_json"])
            payload = self._void_ruins_payload(run, snapshot, result)
            self._void_ruins_store_operation(
                connection, operation_id, operation_name, int(actor["id"]), request_hash, payload, now_text,
            )
            return self._void_ruins_record(payload)

    def _void_ruins_settle_sync(self, platform, platform_user_id, operation_id, operation_name, request_hash):
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._void_ruins_operation(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                replay["already_completed"] = True
                return self._void_ruins_record(replay, replay=True)
            actor = self._require_player(connection, platform, platform_user_id)
            run = self._latest_void_ruins_for_actor(connection, int(actor["id"]))
            if run is None:
                raise VoidRuinsNotFoundError("no void-ruins run exists")
            snapshot = self._void_ruins_json(run["snapshot_json"])
            result = self._void_ruins_json(run["result_json"])
            status = str(run["status"])
            if status == "cleared":
                members = connection.execute(
                    "SELECT m.*, p.id AS database_id, p.player_id AS stable_player_id, p.spirit_stones, p.inventory_json, p.intro_json "
                    "FROM void_ruins_members m JOIN players p ON p.id=m.player_id WHERE m.run_id=? ORDER BY m.member_order",
                    (run["run_id"],),
                ).fetchall()
                rewards: dict[str, dict[str, int]] = {}
                first_clear_members: list[str] = []
                for member in members:
                    stable_id = str(member["stable_player_id"])
                    first = bool(member["first_clear"])
                    reward = dict(VOID_RUINS_REPEAT_REWARD)
                    if first:
                        first_clear_members.append(stable_id)
                    intro = self._json_object(member["intro_json"], {})
                    flags = list(intro.get("flags", []))
                    if first and VOID_RUINS_ROUTE_PERMISSION not in flags:
                        flags.append(VOID_RUINS_ROUTE_PERMISSION)
                    intro["flags"] = flags
                    grant_player_assets(
                        connection,
                        member,
                        {"item.void_crystal": 1},
                        now_text,
                        player_values={"intro_json": json.dumps(intro, ensure_ascii=False, sort_keys=True)},
                    )
                    if first:
                        record_codex_discovery(
                            connection,
                            player_id=int(member["player_id"]),
                            entry_key=VOID_RUINS_CODEX,
                            operation_id=f"{operation_id}:codex:{member['player_id']}",
                            occurred_at=now,
                            snapshot={"run_id": str(run["run_id"]), "instance_key": VOID_RUINS_KEY},
                        )
                    rewards[stable_id] = reward
                    connection.execute(
                        "UPDATE void_ruins_members SET status='settled', reward_json=?, updated_at=? WHERE run_id=? AND player_id=?",
                        (json.dumps(reward, ensure_ascii=False, sort_keys=True), now_text, run["run_id"], member["player_id"]),
                    )
                self._void_ruins_release_anchors(connection, str(run["run_id"]), now_text)
                result = {"outcome": "won", "rewards": rewards, "first_clear_members": first_clear_members}
                connection.execute(
                    "UPDATE void_ruins_runs SET status='settled', result_json=?, updated_at=? WHERE run_id=? AND status='cleared'",
                    (json.dumps(result, ensure_ascii=False, sort_keys=True), now_text, run["run_id"]),
                )
            elif status in {"failed", "expired", "settled", "system_aborted"}:
                if status in {"failed", "expired"}:
                    self._void_ruins_release_anchors(connection, str(run["run_id"]), now_text)
                    result.setdefault("outcome", "lost" if status == "failed" else "expired")
            else:
                raise VoidRuinsNotReadyError("complete all route nodes and automatic battles before settlement")
            settled = connection.execute("SELECT * FROM void_ruins_runs WHERE run_id=?", (run["run_id"],)).fetchone()
            payload = self._void_ruins_payload(settled, snapshot, result)
            self._void_ruins_store_operation(connection, operation_id, operation_name, int(actor["id"]), request_hash, payload, now_text)
            return self._void_ruins_record(payload)

    def _void_ruins_record_battle_outcome(self, run_id: str, outcome: str | None) -> VoidRuinsRunRecord:
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            run = connection.execute("SELECT * FROM void_ruins_runs WHERE run_id=?", (run_id,)).fetchone()
            if run is None:
                raise VoidRuinsNotFoundError("void-ruins run no longer exists")
            if str(run["status"]) != "combat_pending":
                return self._void_ruins_record_from_row(connection, run)
            expired = now_text >= str(run["expires_at"]) or outcome == "expired"
            snapshot = self._void_ruins_json(run["snapshot_json"])
            if outcome == "won" and not expired:
                index = int(run["node_index"]) + 1
                status = "routing"
                snapshot["current_node"] = VOID_RUINS_NODES[index] if index < len(VOID_RUINS_NODES) else None
                result = {"last_battle_outcome": "won"}
            else:
                index = int(run["node_index"])
                status = "expired" if expired else "failed"
                snapshot["current_node"] = VOID_RUINS_NODES[index]
                result = {"outcome": "expired" if expired else "lost", "reason": "battle_" + str(outcome)}
                connection.execute(
                    "UPDATE void_ruins_members SET status=?, updated_at=? WHERE run_id=? AND status='active'",
                    (status, now_text, run_id),
                )
                self._void_ruins_release_anchors(connection, run_id, now_text)
            connection.execute(
                "UPDATE void_ruins_runs SET status=?, node_index=?, battle_id=NULL, snapshot_json=?, result_json=?, updated_at=? WHERE run_id=?",
                (status, index, json.dumps(snapshot, ensure_ascii=False, sort_keys=True), json.dumps(result, sort_keys=True), now_text, run_id),
            )
            updated = connection.execute("SELECT * FROM void_ruins_runs WHERE run_id=?", (run_id,)).fetchone()
            return self._void_ruins_record_from_row(connection, updated)

    async def _void_ruins_end_expired_battle(self, record: VoidRuinsRunRecord) -> None:
        if not record.battle_id:
            return
        access = await asyncio.to_thread(self._void_ruins_mark_battle_expired, record.battle_id)
        if access is None or access["status"] == "settled":
            return
        await self.settle_party_battle(
            platform=access["platform"],
            platform_user_id=access["platform_user_id"],
            battle_id=record.battle_id,
            operation_id=f"void_ruins.expire.battle:{record.run_id}",
        )

    def _void_ruins_mark_battle_expired(self, battle_id: str) -> dict[str, str] | None:
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            session = connection.execute(
                "SELECT status FROM party_battle_sessions WHERE battle_id=?", (battle_id,)
            ).fetchone()
            if session is None:
                return None
            if str(session["status"]) != "settled":
                result = {"outcome": "expired", "reason": "void_ruins_expired"}
                connection.execute(
                    "UPDATE party_battle_sessions SET status='expired', result_json=?, updated_at=? "
                    "WHERE battle_id=? AND status IN ('created','running','won','lost','expired')",
                    (json.dumps(result, sort_keys=True), now_text, battle_id),
                )
            member = connection.execute(
                "SELECT p.platform, p.platform_user_id FROM party_battle_members m "
                "JOIN players p ON p.id=m.player_id WHERE m.battle_id=? ORDER BY m.id LIMIT 1",
                (battle_id,),
            ).fetchone()
            if member is None:
                return None
            return {
                "status": str(session["status"]),
                "platform": str(member["platform"]),
                "platform_user_id": str(member["platform_user_id"]),
            }

    def _void_ruins_expire_by_id(self, run_id: str) -> VoidRuinsRunRecord:
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            run = connection.execute("SELECT * FROM void_ruins_runs WHERE run_id=?", (run_id,)).fetchone()
            if run is None:
                raise VoidRuinsNotFoundError("void-ruins run does not exist")
            if str(run["status"]) in ACTIVE_STATUSES:
                self._void_ruins_expire(connection, run, now_text)
            return self._void_ruins_record_from_row(connection, run_id)

    def _void_ruins_expire(self, connection, run, now_text: str) -> None:
        result = {"outcome": "expired", "reason": "run_timeout"}
        connection.execute(
            "UPDATE void_ruins_runs SET status='expired', result_json=?, updated_at=? WHERE run_id=? AND status IN ('routing','combat_pending','cleared')",
            (json.dumps(result, sort_keys=True), now_text, run["run_id"]),
        )
        connection.execute(
            "UPDATE void_ruins_members SET status='expired', updated_at=? WHERE run_id=? AND status='active'",
            (now_text, run["run_id"]),
        )
        self._void_ruins_release_anchors(connection, str(run["run_id"]), now_text)

    @staticmethod
    def _void_ruins_release_anchors(connection, run_id: str, now_text: str) -> None:
        members = connection.execute(
            "SELECT m.player_id, m.anchor_status, p.inventory_json FROM void_ruins_members m "
            "JOIN players p ON p.id=m.player_id WHERE m.run_id=? AND m.anchor_status='locked'",
            (run_id,),
        ).fetchall()
        for member in members:
            player = connection.execute("SELECT * FROM players WHERE id=?", (member["player_id"],)).fetchone()
            if player is None:
                continue
            grant_player_assets(
                connection,
                player,
                {"item.void_anchor": VOID_RUINS_ANCHOR_LOCK},
                now_text,
            )
            connection.execute(
                "UPDATE void_ruins_members SET anchor_status='released', updated_at=? WHERE run_id=? AND player_id=? AND anchor_status='locked'",
                (now_text, run_id, member["player_id"]),
            )

    async def compensate_void_ruins_system_failure(self, *, run_id: str) -> VoidRuinsRunRecord:
        await self.initialize()
        return await asyncio.to_thread(self._void_ruins_compensate_sync, run_id)

    def _void_ruins_compensate_sync(self, run_id: str) -> VoidRuinsRunRecord:
        now_text = serialize_datetime(self._now())
        operation_id = f"void_ruins.system_abort:{run_id}"
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            run = connection.execute("SELECT * FROM void_ruins_runs WHERE run_id=?", (run_id,)).fetchone()
            if run is None:
                raise VoidRuinsNotFoundError("void-ruins run does not exist")
            if str(run["status"]) == "system_aborted":
                replay = self._void_ruins_operation(
                    connection,
                    operation_id,
                    "void_ruins.system_abort",
                    self._request_hash("void_ruins.system_abort", {"run_id": run_id}),
                )
                if replay is not None:
                    replay["already_completed"] = True
                    return self._void_ruins_record(replay, replay=True)
                return self._void_ruins_record_from_row(connection, run)
            if str(run["status"]) not in ACTIVE_STATUSES:
                raise VoidRuinsNotReadyError("only an active void-ruins run can be compensated")
            party = connection.execute(
                "SELECT leader_id, current_session_id FROM parties WHERE party_id=?", (run["party_id"],)
            ).fetchone()
            if party is None:
                raise VoidRuinsNotFoundError("void-ruins party no longer exists")
            leader = connection.execute("SELECT * FROM players WHERE id=?", (party["leader_id"],)).fetchone()
            if leader is not None:
                change_player_state(
                    connection,
                    leader,
                    updated_at=now_text,
                    value_delta={"stamina": int(run["stamina_cost"])},
                    maximums={"stamina": leader["stamina_max"]},
                )
            if party["current_session_id"]:
                battle_id = str(party["current_session_id"])
                result = {"outcome": "system_aborted", "reason": "instance_compensated"}
                connection.execute(
                    "UPDATE party_battle_sessions SET status='settled', result_json=?, updated_at=? WHERE battle_id=? AND status IN ('created','running','won','lost','expired')",
                    (json.dumps(result, sort_keys=True), now_text, battle_id),
                )
                connection.execute(
                    "UPDATE party_battle_members SET asset_lock_status='released', settled_at=?, updated_at=? WHERE battle_id=? AND asset_lock_status='locked'",
                    (now_text, now_text, battle_id),
                )
                connection.execute(
                    "UPDATE parties SET current_session_id=NULL, updated_at=? WHERE party_id=? AND current_session_id=?",
                    (now_text, run["party_id"], battle_id),
                )
            connection.execute(
                "UPDATE void_ruins_members SET status='system_aborted', quota_key='released:'||?||':'||player_id, updated_at=? WHERE run_id=? AND status='active'",
                (run_id, now_text, run_id),
            )
            self._void_ruins_release_anchors(connection, run_id, now_text)
            result = {"outcome": "system_aborted", "reason": "system_compensation"}
            connection.execute(
                "UPDATE void_ruins_runs SET status='system_aborted', battle_id=NULL, result_json=?, updated_at=? WHERE run_id=?",
                (json.dumps(result, sort_keys=True), now_text, run_id),
            )
            snapshot = self._void_ruins_json(run["snapshot_json"])
            updated = connection.execute("SELECT * FROM void_ruins_runs WHERE run_id=?", (run_id,)).fetchone()
            payload = self._void_ruins_payload(updated, snapshot, result)
            self._void_ruins_store_operation(
                connection, operation_id, "void_ruins.system_abort", int(party["leader_id"]),
                self._request_hash("void_ruins.system_abort", {"run_id": run_id}), payload, now_text,
            )
            return self._void_ruins_record(payload)

    async def has_active_void_ruins(self, *, platform: str, platform_user_id: str) -> bool:
        await self.initialize()
        return await asyncio.to_thread(self._has_active_void_ruins_sync, platform, platform_user_id)

    def _has_active_void_ruins_sync(self, platform: str, platform_user_id: str) -> bool:
        with self._connect() as connection:
            player = self._require_player(connection, platform, platform_user_id, writable=False)
            return self._active_void_ruins_for_actor(connection, int(player["id"])) is not None

    async def has_latest_void_ruins(self, *, platform: str, platform_user_id: str) -> bool:
        await self.initialize()
        return await asyncio.to_thread(self._has_latest_void_ruins_sync, platform, platform_user_id)

    def _has_latest_void_ruins_sync(self, platform: str, platform_user_id: str) -> bool:
        with self._connect() as connection:
            player = self._require_player(connection, platform, platform_user_id, writable=False)
            run = self._latest_void_ruins_for_actor(connection, int(player["id"]))
            if run is None:
                return False
            newer = []
            for table, column, join in (
                ("secret_realm_runs", "created_at", ""),
                ("boundary_rift_runs", "starts_at", "JOIN boundary_rift_members m ON m.run_id=r.run_id"),
                ("ancient_domain_runs", "starts_at", "JOIN ancient_domain_members m ON m.run_id=r.run_id"),
                ("ancestral_hall_runs", "starts_at", ""),
            ):
                alias = "r" if join else "x"
                sql = (
                    f"SELECT MAX({alias}.{column}) AS latest FROM {table} {alias} {join} "
                    f"WHERE {alias}.player_id=?" if not join else
                    f"SELECT MAX({alias}.{column}) AS latest FROM {table} {alias} {join} WHERE m.player_id=?"
                )
                row = connection.execute(sql, (player["id"],)).fetchone()
                newer.append(str(row["latest"] or ""))
            return str(run["starts_at"]) >= max(newer, default="")

    async def has_void_ruins_settlement_operation(self, operation_id: str) -> bool:
        await self.initialize()
        return await asyncio.to_thread(self._has_void_ruins_settlement_operation_sync, operation_id)

    def _has_void_ruins_settlement_operation_sync(self, operation_id: str) -> bool:
        with self._connect() as connection:
            return connection.execute(
                "SELECT 1 FROM operations WHERE operation_id=? AND operation_name='void_ruins.settle'",
                (operation_id,),
            ).fetchone() is not None

    @staticmethod
    def _active_void_ruins_for_actor(connection, player_id: int):
        return connection.execute(
            "SELECT r.* FROM void_ruins_runs r JOIN void_ruins_members m ON m.run_id=r.run_id "
            "WHERE m.player_id=? AND m.status='active' AND r.status IN ('routing','combat_pending','cleared') ORDER BY r.id DESC LIMIT 1",
            (player_id,),
        ).fetchone()

    @staticmethod
    def _latest_void_ruins_for_actor(connection, player_id: int):
        return connection.execute(
            "SELECT r.* FROM void_ruins_runs r JOIN void_ruins_members m ON m.run_id=r.run_id "
            "WHERE m.player_id=? ORDER BY r.id DESC LIMIT 1", (player_id,),
        ).fetchone()


__all__ = ["VoidRuinsRepositoryMixin"]
