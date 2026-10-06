"""Transactional persistence for the party boundary-rift secret realm."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from ...contracts import serialize_datetime
from ..combat.party_models import PartyBattleStartRecord
from ..persistence.errors import (
    BoundaryRiftBusyError,
    BoundaryRiftNodeError,
    BoundaryRiftNotFoundError,
    BoundaryRiftNotReadyError,
    BoundaryRiftQuotaError,
    BoundaryRiftRequirementError,
    OperationConflictError,
    ResourceInsufficientError,
)
from ..social.party_rules import PARTY_TYPE_SECRET_REALM_BOUNDARY
from ..specials.codex_projection import record_codex_discovery
from ..utils.assets import grant_player_assets, inventory_amount, spend_player_items
from ..utils.player import change_player_state, player_integer, player_inventory
from .boundary_rift_models import BoundaryRiftRunRecord
from .boundary_rift_rules import (
    BOUNDARY_RIFT_EXPIRY_SECONDS,
    BOUNDARY_RIFT_FIRST_REWARD,
    BOUNDARY_RIFT_KEY,
    BOUNDARY_RIFT_LOCATION,
    BOUNDARY_RIFT_NODE_DEFINITIONS,
    BOUNDARY_RIFT_NODES,
    BOUNDARY_RIFT_PARTY_TYPE,
    BOUNDARY_RIFT_REPEAT_REWARD,
    BOUNDARY_RIFT_STAMINA_COST,
    BOUNDARY_RIFT_TICKET,
    BOUNDARY_RIFT_TICKET_COST,
    resolve_boundary_rift_node,
)
from .secret_realm_rules import realm_at_least


REQUIRED_FLAG = "story.mainline.three_realms"
REWARD_FLAG = "story.boundary_rift"
BOUNDARY_RIFT_CODEX = "codex.route.boundary"


class BoundaryRiftRepositoryMixin:
    """Own boundary-rift quota, route snapshots, combat handoff, and rewards."""

    @staticmethod
    def _rift_json(raw: Any, default: dict[str, Any] | None = None) -> dict[str, Any]:
        value = json.loads(raw) if isinstance(raw, str) else raw
        return dict(value) if isinstance(value, dict) else dict(default or {})

    @staticmethod
    def _rift_week_key(now: datetime) -> str:
        return now.astimezone(timezone.utc).strftime("%G-W%V")

    @staticmethod
    def _rift_request_hash(repository, operation_name: str, request: dict[str, Any]) -> str:
        return repository._request_hash(operation_name, request)

    def _rift_operation(self, connection, operation_id: str, operation_name: str, request_hash: str):
        row = connection.execute(
            "SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id=?",
            (operation_id,),
        ).fetchone()
        if row is None:
            return None
        if str(row["operation_name"]) != operation_name or str(row["request_hash"]) != request_hash:
            raise OperationConflictError("operation ID was reused with different input")
        return self._rift_json(row["result_json"])

    @staticmethod
    def _rift_record_operation(connection, operation_id, operation_name, player_id, request_hash, payload, now_text):
        connection.execute(
            "INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (operation_id, operation_name, player_id, request_hash, json.dumps(payload, ensure_ascii=False, sort_keys=True), now_text),
        )

    async def enter_boundary_rift(self, *, platform: str, platform_user_id: str, operation_id: str) -> BoundaryRiftRunRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._retry_sync,
                self._enter_boundary_rift_sync,
                platform,
                platform_user_id,
                operation_id,
            )

    def _enter_boundary_rift_sync(self, platform: str, platform_user_id: str, operation_id: str) -> BoundaryRiftRunRecord:
        operation_name = "boundary_rift.enter"
        request_hash = self._rift_request_hash(
            self,
            operation_name,
            {"platform": platform, "platform_user_id": platform_user_id, "instance_key": BOUNDARY_RIFT_KEY},
        )
        now = self._now()
        now_text = serialize_datetime(now)
        quota_key = self._rift_week_key(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._rift_operation(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                replay["already_completed"] = True
                return self._boundary_rift_record(replay)
            leader = self._require_player(connection, platform, platform_user_id)
            membership = connection.execute(
                "SELECT * FROM party_members WHERE player_id=? AND status='active' ORDER BY id DESC LIMIT 1",
                (leader["id"],),
            ).fetchone()
            if membership is None or str(membership["role"]) != "leader":
                raise BoundaryRiftRequirementError("only the leader of a dedicated boundary-rift party may enter")
            party = connection.execute("SELECT * FROM parties WHERE party_id=?", (membership["party_id"],)).fetchone()
            if (
                party is None
                or str(party["party_type"]) != PARTY_TYPE_SECRET_REALM_BOUNDARY
                or str(party["status"]) != "ready"
                or str(party["location_key"]) != BOUNDARY_RIFT_LOCATION
                or party["current_session_id"]
            ):
                raise BoundaryRiftRequirementError("a confirmed boundary-rift party is required")
            members = connection.execute(
                "SELECT m.id AS member_row_id, m.role, m.confirmed_at, p.* FROM party_members m "
                "JOIN players p ON p.id=m.player_id WHERE m.party_id=? AND m.status='active' ORDER BY m.id",
                (party["party_id"],),
            ).fetchall()
            if not 2 <= len(members) <= 5 or any(not row["confirmed_at"] for row in members):
                raise BoundaryRiftRequirementError("all party members must confirm")
            first_clear_by_player: dict[int, bool] = {}
            snapshots: list[dict[str, Any]] = []
            for row in members:
                intro = self._rift_json(row["intro_json"])
                flags = {str(value) for value in intro.get("flags", [])}
                if (
                    str(row["location_key"]) != BOUNDARY_RIFT_LOCATION
                    or not realm_at_least(str(row["realm_key"]), player_integer(row, "realm_layer"), "nascent_soul", 1, self.content)
                    or REQUIRED_FLAG not in flags
                ):
                    raise BoundaryRiftRequirementError("a member lacks location, realm, or three-realms evidence")
                if player_integer(row, "stamina") < BOUNDARY_RIFT_STAMINA_COST:
                    raise ResourceInsufficientError("a party member lacks entry stamina")
                if self._has_active_long_action(connection, int(row["id"])):
                    raise BoundaryRiftBusyError("a party member has another active action")
                if connection.execute(
                    "SELECT 1 FROM party_battle_members WHERE player_id=? AND asset_lock_status='locked' LIMIT 1",
                    (row["id"],),
                ).fetchone():
                    raise BoundaryRiftBusyError("a party member has locked battle assets")
                if connection.execute(
                    "SELECT 1 FROM secret_realm_runs WHERE player_id=? AND status IN ('entered','routing','combat_pending','cleared','failed') LIMIT 1",
                    (row["id"],),
                ).fetchone():
                    raise BoundaryRiftBusyError("a party member has an active solo secret realm")
                if connection.execute(
                    "SELECT 1 FROM boundary_rift_members WHERE player_id=? AND status='active' LIMIT 1",
                    (row["id"],),
                ).fetchone():
                    raise BoundaryRiftBusyError("a party member has an active boundary-rift run")
                if connection.execute(
                    "SELECT 1 FROM boundary_rift_members WHERE player_id=? AND quota_key=? LIMIT 1",
                    (row["id"], quota_key),
                ).fetchone():
                    raise BoundaryRiftQuotaError("a party member already entered this UTC week")
                if player_integer(row, "soul_power") <= 0:
                    raise BoundaryRiftRequirementError("a party member has no soul power")
                fatigue_until = row["soul_fatigue_until"]
                if fatigue_until:
                    try:
                        if datetime.fromisoformat(str(fatigue_until)) > now:
                            raise BoundaryRiftRequirementError("a party member is under soul fatigue")
                    except ValueError:
                        pass
                first_clear_by_player[int(row["id"])] = connection.execute(
                    "SELECT 1 FROM boundary_rift_members WHERE player_id=? AND status='cleared' LIMIT 1",
                    (row["id"],),
                ).fetchone() is None
                snapshots.append(
                    {
                        "player_id": str(row["player_id"]),
                        "database_id": int(row["id"]),
                        "platform": str(row["platform"]),
                        "platform_user_id": str(row["platform_user_id"]),
                        "role": str(row["role"]),
                        "realm_key": str(row["realm_key"]),
                        "realm_layer": player_integer(row, "realm_layer"),
                        "location_key": str(row["location_key"]),
                        "required_flags": sorted(flags & {REQUIRED_FLAG}),
                    }
                )
            leader_inventory = player_inventory(leader)
            if inventory_amount(leader_inventory, BOUNDARY_RIFT_TICKET) < BOUNDARY_RIFT_TICKET_COST:
                raise BoundaryRiftRequirementError("the party leader lacks one soul crystal")
            run_id = f"boundary-rift-{uuid4().hex}"
            expires_at = serialize_datetime(now + timedelta(seconds=BOUNDARY_RIFT_EXPIRY_SECONDS))
            snapshot = {
                "instance_key": BOUNDARY_RIFT_KEY,
                "party_type": PARTY_TYPE_SECRET_REALM_BOUNDARY,
                "party_id": str(party["party_id"]),
                "location_key": BOUNDARY_RIFT_LOCATION,
                "nodes": list(BOUNDARY_RIFT_NODES),
                "current_node": BOUNDARY_RIFT_NODES[0],
                "members": snapshots,
                "first_clear_by_player": {str(key): value for key, value in first_clear_by_player.items()},
                "entry_cost": {
                    "stamina_each": BOUNDARY_RIFT_STAMINA_COST,
                    "ticket": {BOUNDARY_RIFT_TICKET: BOUNDARY_RIFT_TICKET_COST},
                },
                "random_seed": operation_id,
            }
            for row in members:
                try:
                    change_player_state(
                        connection,
                        row,
                        updated_at=now_text,
                        value_delta={"stamina": -BOUNDARY_RIFT_STAMINA_COST},
                    )
                except ValueError as exc:
                    raise ResourceInsufficientError("party stamina changed during entry") from exc
            spend_player_items(
                connection,
                leader,
                {BOUNDARY_RIFT_TICKET: BOUNDARY_RIFT_TICKET_COST},
                now_text,
            )
            connection.execute(
                "INSERT INTO boundary_rift_runs(run_id, party_id, status, node_index, battle_id, quota_key, starts_at, expires_at, snapshot_json, result_json, entry_operation_id, created_at, updated_at) "
                "VALUES (?, ?, 'routing', 0, NULL, ?, ?, ?, ?, '{}', ?, ?, ?)",
                (run_id, party["party_id"], quota_key, now_text, expires_at, json.dumps(snapshot, ensure_ascii=False, sort_keys=True), operation_id, now_text, now_text),
            )
            for index, row in enumerate(members):
                connection.execute(
                    "INSERT INTO boundary_rift_members(run_id, player_id, quota_key, member_order, first_clear, status, reward_json, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, 'active', '{}', ?, ?)",
                    (run_id, row["id"], quota_key, index, int(first_clear_by_player[int(row["id"])]), now_text, now_text),
                )
            payload = {
                "run_id": run_id,
                "party_id": str(party["party_id"]),
                "status": "routing",
                "node_index": 0,
                "current_node": BOUNDARY_RIFT_NODES[0],
                "battle_id": None,
                "expires_at": expires_at,
                "outcome": None,
            }
            self._rift_record_operation(connection, operation_id, operation_name, int(leader["id"]), request_hash, payload, now_text)
            return self._boundary_rift_record(payload)

    async def choose_boundary_rift_node(
        self,
        *,
        platform: str,
        platform_user_id: str,
        node_key: str,
        path_choice: str | None,
        operation_id: str,
    ) -> BoundaryRiftRunRecord:
        await self.initialize()
        async with self._inflight:
            record = await asyncio.to_thread(
                self._retry_sync,
                self._choose_boundary_rift_node_sync,
                platform,
                platform_user_id,
                node_key,
                path_choice,
                operation_id,
            )
        if record.status != "combat_pending":
            return record
        if not record.battle_id:
            try:
                start = await self.start_party_battle(
                    platform=platform,
                    platform_user_id=platform_user_id,
                    party_id=record.party_id,
                    operation_id=f"boundary_rift.battle.start:{record.run_id}:{record.current_node}",
                    boundary_rift_run_id=record.run_id,
                )
            except Exception:
                await asyncio.to_thread(self._retry_sync, self._refund_boundary_rift_start_failure, record.run_id)
                raise
            record = await asyncio.to_thread(self._get_boundary_rift_run_for_actor, platform, platform_user_id)
            if not record.battle_id:
                raise BoundaryRiftNotReadyError("battle start did not attach to the run")
            if record.battle_id != start.battle_id:
                raise BoundaryRiftNotReadyError("battle session changed during node selection")
        return record

    def _choose_boundary_rift_node_sync(self, platform, platform_user_id, node_key, path_choice, operation_id):
        operation_name = "boundary_rift.choose_node"
        request_hash = self._rift_request_hash(
            self,
            operation_name,
            {"platform": platform, "platform_user_id": platform_user_id, "node_key": node_key, "path_choice": path_choice},
        )
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._rift_operation(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                record = self._boundary_rift_record(replay, replay=True)
                return self._current_boundary_rift_record(connection, platform, platform_user_id) if record.status == "combat_pending" else record
            actor = self._require_player(connection, platform, platform_user_id)
            run = self._active_boundary_rift_for_actor(connection, int(actor["id"]))
            if run is None:
                raise BoundaryRiftNotFoundError("no active boundary-rift run")
            snapshot = self._rift_json(run["snapshot_json"])
            retry_battle_start = (
                str(run["status"]) == "combat_pending"
                and run["battle_id"] is None
                and str(snapshot.get("current_node", "")) == node_key
            )
            if (str(run["status"]) != "routing" and not retry_battle_start) or serialize_datetime(now) >= str(run["expires_at"]):
                self._expire_boundary_rift(connection, run, now_text)
                connection.commit()
                raise BoundaryRiftNotReadyError("boundary-rift run has expired or is not routing")
            members = connection.execute(
                "SELECT role FROM party_members WHERE party_id=? AND player_id=? AND status='active'",
                (run["party_id"], actor["id"]),
            ).fetchone()
            if members is None or str(members["role"]) != "leader":
                raise BoundaryRiftRequirementError("only the party leader may advance the route")
            node_index = int(run["node_index"])
            if retry_battle_start:
                status = "combat_pending"
                next_index = node_index
            else:
                if node_index >= len(BOUNDARY_RIFT_NODES) or node_key != BOUNDARY_RIFT_NODES[node_index]:
                    raise BoundaryRiftNodeError("node is not the next authorized route step")
                if node_key == "shattered_path" and path_choice not in {"inner", "outer"}:
                    raise BoundaryRiftNodeError("path choice must be inner or outer")
                if node_key != "shattered_path" and path_choice is not None:
                    raise BoundaryRiftNodeError("path choice is only available at the shattered path")
                snapshot.setdefault("node_history", []).append(node_key)
                if path_choice:
                    snapshot["path_choice"] = path_choice
                if node_key in {"cross_realm_sentinel", "boundary_watcher"}:
                    status = "combat_pending"
                    snapshot["current_node"] = node_key
                    next_index = node_index
                else:
                    next_index = node_index + 1
                    if next_index >= len(BOUNDARY_RIFT_NODES):
                        status = "cleared"
                        snapshot["current_node"] = None
                    else:
                        status = "routing"
                        snapshot["current_node"] = BOUNDARY_RIFT_NODES[next_index]
                connection.execute(
                    "UPDATE boundary_rift_runs SET status=?, node_index=?, snapshot_json=?, battle_id=NULL, updated_at=? WHERE run_id=?",
                    (status, next_index, json.dumps(snapshot, ensure_ascii=False, sort_keys=True), now_text, run["run_id"]),
                )
            payload = {
                "run_id": str(run["run_id"]),
                "party_id": str(run["party_id"]),
                "status": status,
                "node_index": next_index,
                "current_node": snapshot.get("current_node"),
                "battle_id": None,
                "expires_at": str(run["expires_at"]),
                "outcome": None,
            }
            self._rift_record_operation(connection, operation_id, operation_name, int(actor["id"]), request_hash, payload, now_text)
            return self._boundary_rift_record(payload)

    async def settle_boundary_rift(self, *, platform: str, platform_user_id: str, operation_id: str) -> BoundaryRiftRunRecord:
        await self.initialize()
        record = await asyncio.to_thread(self._get_boundary_rift_run_for_actor, platform, platform_user_id)
        if record.status in {"failed", "expired"}:
            return record
        if record.status == "combat_pending":
            if not record.battle_id:
                raise BoundaryRiftNotReadyError("the encounter has no battle session")
            battle = await self.settle_party_battle(
                platform=platform,
                platform_user_id=platform_user_id,
                battle_id=record.battle_id,
                operation_id=f"boundary_rift.battle.settle:{record.run_id}:{record.current_node}",
            )
            return await asyncio.to_thread(self._finish_boundary_rift_battle, record.run_id, battle.outcome)
        async with self._inflight:
            return await asyncio.to_thread(
                self._retry_sync,
                self._settle_boundary_rift_sync,
                platform,
                platform_user_id,
                operation_id,
            )

    def _finish_boundary_rift_battle(self, run_id: str, outcome: str) -> BoundaryRiftRunRecord:
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            run = connection.execute("SELECT * FROM boundary_rift_runs WHERE run_id=?", (run_id,)).fetchone()
            if run is None:
                raise BoundaryRiftNotFoundError("boundary-rift run no longer exists")
            if str(run["status"]) != "combat_pending":
                return self._current_boundary_rift_record_by_id(connection, run_id)
            snapshot = self._rift_json(run["snapshot_json"])
            if outcome == "won" and now <= datetime.fromisoformat(str(run["expires_at"])):
                next_index = int(run["node_index"]) + 1
                snapshot["current_node"] = BOUNDARY_RIFT_NODES[next_index]
                status = "routing"
                result = {"last_battle_outcome": "won"}
            else:
                next_index = int(run["node_index"])
                snapshot["current_node"] = BOUNDARY_RIFT_NODES[next_index]
                status = "expired" if now > datetime.fromisoformat(str(run["expires_at"])) else "failed"
                result = {"outcome": "expired" if status == "expired" else "lost", "reason": "battle_" + outcome}
                connection.execute(
                    "UPDATE boundary_rift_members SET status=?, updated_at=? WHERE run_id=? AND status='active'",
                    (status, now_text, run_id),
                )
            connection.execute(
                "UPDATE boundary_rift_runs SET status=?, node_index=?, battle_id=NULL, snapshot_json=?, result_json=?, updated_at=? WHERE run_id=?",
                (status, next_index, json.dumps(snapshot, ensure_ascii=False, sort_keys=True), json.dumps(result, ensure_ascii=False, sort_keys=True), now_text, run_id),
            )
            return self._boundary_rift_record_from_row(connection, run_id)

    def _settle_boundary_rift_sync(self, platform: str, platform_user_id: str, operation_id: str) -> BoundaryRiftRunRecord:
        operation_name = "boundary_rift.settle"
        request_hash = self._rift_request_hash(self, operation_name, {"platform": platform, "platform_user_id": platform_user_id})
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._rift_operation(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                replay["already_completed"] = True
                return self._boundary_rift_record(replay)
            actor = self._require_player(connection, platform, platform_user_id, writable=False)
            run = self._active_or_cleared_boundary_rift_for_actor(connection, int(actor["id"]))
            if run is None:
                raise BoundaryRiftNotFoundError("no boundary-rift result is available")
            if str(run["status"]) == "settled":
                return self._boundary_rift_record_from_row(connection, str(run["run_id"]))
            if str(run["status"]) != "cleared":
                if str(run["status"]) in {"failed", "expired", "settled"}:
                    raise BoundaryRiftNotReadyError("the boundary-rift run cannot grant a reward")
                raise BoundaryRiftNotReadyError("complete all route nodes and battles before settling")
            if serialize_datetime(now) >= str(run["expires_at"]):
                self._expire_boundary_rift(connection, run, now_text)
                connection.commit()
                raise BoundaryRiftNotReadyError("boundary-rift run has expired")
            snapshot = self._rift_json(run["snapshot_json"])
            members = connection.execute(
                "SELECT m.*, p.id AS database_id, p.player_id AS stable_player_id, p.spirit_stones, p.inventory_json, p.intro_json "
                "FROM boundary_rift_members m JOIN players p ON p.id=m.player_id "
                "WHERE m.run_id=? ORDER BY m.member_order",
                (run["run_id"],),
            ).fetchall()
            reward_map: dict[str, dict[str, int]] = {}
            first_clear_members: list[str] = []
            for member in members:
                reward = dict(BOUNDARY_RIFT_FIRST_REWARD if bool(member["first_clear"]) else BOUNDARY_RIFT_REPEAT_REWARD)
                reward_map[str(member["player_id"])] = reward
                intro = self._rift_json(member["intro_json"])
                flags = {str(value) for value in intro.get("flags", [])}
                if bool(member["first_clear"]):
                    flags.add(REWARD_FLAG)
                    first_clear_members.append(str(member["stable_player_id"]))
                    record_codex_discovery(
                        connection,
                        player_id=int(member["player_id"]),
                        entry_key=BOUNDARY_RIFT_CODEX,
                        operation_id=f"{operation_id}:codex:{member['player_id']}",
                        occurred_at=now,
                        snapshot={"run_id": str(run["run_id"]), "instance_key": BOUNDARY_RIFT_KEY},
                    )
                intro["flags"] = sorted(flags)
                grant_player_assets(
                    connection,
                    member,
                    reward,
                    now_text,
                    player_values={"intro_json": json.dumps(intro, ensure_ascii=False, sort_keys=True)},
                )
                connection.execute(
                    "UPDATE boundary_rift_members SET status='cleared', reward_json=?, updated_at=? WHERE run_id=? AND player_id=?",
                    (json.dumps(reward, ensure_ascii=False, sort_keys=True), now_text, run["run_id"], member["player_id"]),
                )
            result = {"outcome": "won", "rewards": reward_map, "first_clear_members": first_clear_members}
            connection.execute(
                "UPDATE boundary_rift_runs SET status='settled', result_json=?, updated_at=? WHERE run_id=? AND status='cleared'",
                (json.dumps(result, ensure_ascii=False, sort_keys=True), now_text, run["run_id"]),
            )
            payload = {
                "run_id": str(run["run_id"]),
                "party_id": str(run["party_id"]),
                "status": "settled",
                "node_index": int(run["node_index"]),
                "current_node": None,
                "battle_id": None,
                "expires_at": str(run["expires_at"]),
                "outcome": "won",
                "rewards": reward_map,
                "first_clear_members": first_clear_members,
            }
            self._rift_record_operation(connection, operation_id, operation_name, int(actor["id"]), request_hash, payload, now_text)
            return self._boundary_rift_record(payload)

    async def get_boundary_rift_run(self, *, platform: str, platform_user_id: str) -> BoundaryRiftRunRecord:
        await self.initialize()
        return await asyncio.to_thread(self._get_boundary_rift_run_for_actor, platform, platform_user_id)

    def _get_boundary_rift_run_for_actor(self, platform: str, platform_user_id: str) -> BoundaryRiftRunRecord:
        with self._connect() as connection:
            player = self._require_player(connection, platform, platform_user_id, writable=False)
            run = self._active_or_cleared_boundary_rift_for_actor(connection, int(player["id"]))
            if run is None:
                run = connection.execute(
                    "SELECT r.* FROM boundary_rift_runs r JOIN boundary_rift_members m ON m.run_id=r.run_id "
                    "WHERE m.player_id=? ORDER BY r.id DESC LIMIT 1",
                    (player["id"],),
                ).fetchone()
            if run is None:
                raise BoundaryRiftNotFoundError("no boundary-rift run exists for the player")
            if str(run["status"]) in {"routing", "cleared"} and serialize_datetime(self._now()) >= str(run["expires_at"]):
                now_text = serialize_datetime(self._now())
                with self._connect() as write_connection:
                    write_connection.execute("BEGIN IMMEDIATE")
                    current = write_connection.execute("SELECT * FROM boundary_rift_runs WHERE run_id=?", (run["run_id"],)).fetchone()
                    if current is not None and str(current["status"]) in {"routing", "cleared"}:
                        self._expire_boundary_rift(write_connection, current, now_text)
                raise BoundaryRiftNotReadyError("boundary-rift run has expired")
            return self._boundary_rift_record_from_row(connection, str(run["run_id"]))

    @staticmethod
    def _active_boundary_rift_for_actor(connection, player_id: int):
        return connection.execute(
            "SELECT r.* FROM boundary_rift_runs r JOIN boundary_rift_members m ON m.run_id=r.run_id "
            "WHERE m.player_id=? AND m.status='active' AND r.status IN ('routing','combat_pending','cleared') "
            "ORDER BY r.id DESC LIMIT 1",
            (player_id,),
        ).fetchone()

    @classmethod
    def _active_or_cleared_boundary_rift_for_actor(cls, connection, player_id: int):
        return cls._active_boundary_rift_for_actor(connection, player_id) or connection.execute(
            "SELECT r.* FROM boundary_rift_runs r JOIN boundary_rift_members m ON m.run_id=r.run_id "
            "WHERE m.player_id=? AND m.status='cleared' AND r.status='settled' ORDER BY r.id DESC LIMIT 1",
            (player_id,),
        ).fetchone()

    @classmethod
    def _current_boundary_rift_record(cls, connection, platform: str, platform_user_id: str):
        actor = connection.execute("SELECT id FROM players WHERE platform=? AND platform_user_id=?", (platform, platform_user_id)).fetchone()
        if actor is None:
            raise BoundaryRiftNotFoundError("player does not exist")
        run = cls._active_boundary_rift_for_actor(connection, int(actor["id"]))
        if run is None:
            run = connection.execute(
                "SELECT r.* FROM boundary_rift_runs r JOIN boundary_rift_members m ON m.run_id=r.run_id "
                "WHERE m.player_id=? ORDER BY r.id DESC LIMIT 1",
                (actor["id"],),
            ).fetchone()
        if run is None:
            raise BoundaryRiftNotFoundError("no boundary-rift run exists for the player")
        return cls._boundary_rift_record_from_row(connection, str(run["run_id"]))

    @classmethod
    def _current_boundary_rift_record_by_id(cls, connection, run_id: str):
        return cls._boundary_rift_record_from_row(connection, run_id)

    @classmethod
    def _boundary_rift_record_from_row(cls, connection, run_id: str) -> BoundaryRiftRunRecord:
        row = connection.execute("SELECT * FROM boundary_rift_runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            raise BoundaryRiftNotFoundError("boundary-rift run does not exist")
        snapshot = cls._rift_json(row["snapshot_json"])
        result = cls._rift_json(row["result_json"])
        return cls._boundary_rift_record(
            {
                "run_id": str(row["run_id"]),
                "party_id": str(row["party_id"]),
                "status": str(row["status"]),
                "node_index": int(row["node_index"]),
                "current_node": snapshot.get("current_node"),
                "battle_id": row["battle_id"],
                "expires_at": str(row["expires_at"]),
                "outcome": result.get("outcome", result.get("last_battle_outcome")),
                "rewards": result.get("rewards", {}),
                "first_clear_members": result.get("first_clear_members", []),
            }
        )

    def _refund_boundary_rift_start_failure(self, run_id: str) -> None:
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            run = connection.execute("SELECT * FROM boundary_rift_runs WHERE run_id=?", (run_id,)).fetchone()
            if run is None or run["battle_id"] is not None or str(run["status"]) not in {"combat_pending", "routing"}:
                return
            party = connection.execute("SELECT leader_id FROM parties WHERE party_id=?", (run["party_id"],)).fetchone()
            members = connection.execute(
                "SELECT player_id FROM boundary_rift_members WHERE run_id=? AND status='active' ORDER BY member_order",
                (run_id,),
            ).fetchall()
            for member in members:
                player = connection.execute("SELECT * FROM players WHERE id=?", (member["player_id"],)).fetchone()
                if player is not None:
                    change_player_state(
                        connection,
                        player,
                        updated_at=now_text,
                        value_delta={"stamina": BOUNDARY_RIFT_STAMINA_COST},
                        maximums={"stamina": player["stamina_max"]},
                    )
                connection.execute(
                    "UPDATE boundary_rift_members SET status='failed', quota_key=?, updated_at=? WHERE run_id=? AND player_id=?",
                    (f"released:{run_id}", now_text, run_id, member["player_id"]),
                )
            if party is not None and members:
                leader = connection.execute("SELECT * FROM players WHERE id=?", (party["leader_id"],)).fetchone()
                if leader is not None:
                    grant_player_assets(
                        connection,
                        leader,
                        {BOUNDARY_RIFT_TICKET: BOUNDARY_RIFT_TICKET_COST},
                        now_text,
                    )
            result = {"outcome": "failed", "reason": "battle_start_failed", "entry_cost_refunded": True}
            connection.execute(
                "UPDATE boundary_rift_runs SET status='failed', result_json=?, updated_at=? WHERE run_id=?",
                (json.dumps(result, ensure_ascii=False, sort_keys=True), now_text, run_id),
            )

    @staticmethod
    def _boundary_rift_record(payload: dict[str, Any], replay: bool = False) -> BoundaryRiftRunRecord:
        node_index = int(payload.get("node_index", 0))
        return BoundaryRiftRunRecord(
            run_id=str(payload["run_id"]),
            party_id=str(payload["party_id"]),
            status=str(payload["status"]),
            node_index=node_index,
            current_node=str(payload["current_node"]) if payload.get("current_node") is not None else None,
            battle_id=str(payload["battle_id"]) if payload.get("battle_id") else None,
            rewards={str(player): dict(reward) for player, reward in dict(payload.get("rewards", {})).items()},
            first_clear_members=tuple(str(item) for item in payload.get("first_clear_members", [])),
            outcome=str(payload["outcome"]) if payload.get("outcome") else None,
            expires_at=str(payload.get("expires_at", "")),
            already_completed=bool(replay or payload.get("already_completed", False)),
        )

    @classmethod
    def _expire_boundary_rift(cls, connection, run, now_text: str) -> None:
        connection.execute(
            "UPDATE boundary_rift_runs SET status='expired', result_json=?, updated_at=? WHERE run_id=? AND status IN ('routing','cleared')",
            (json.dumps({"outcome": "expired", "reason": "run_timeout"}, sort_keys=True), now_text, run["run_id"]),
        )
        connection.execute(
            "UPDATE boundary_rift_members SET status='expired', updated_at=? WHERE run_id=? AND status='active'",
            (now_text, run["run_id"]),
        )


__all__ = ["BoundaryRiftRepositoryMixin"]
