"""Persistence for the three-member ancient-domain secret realm."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from ...contracts import serialize_datetime
from ..persistence.errors import (
    AncientDomainBusyError,
    AncientDomainNodeError,
    AncientDomainNotFoundError,
    AncientDomainNotReadyError,
    AncientDomainQuotaError,
    AncientDomainRequirementError,
    OperationConflictError,
    ResourceInsufficientError,
)
from ..social.party_rules import PARTY_TYPE_SECRET_REALM_ANCIENT
from ..specials.codex_projection import record_codex_discovery
from ..utils.assets import grant_player_assets
from ..utils.player import change_player_state, player_combat_values, player_integer
from .ancient_domain_models import AncientDomainRunRecord
from .ancient_domain_rules import (
    ANCIENT_DOMAIN_EXPIRY_SECONDS,
    ANCIENT_DOMAIN_FIRST_REWARD,
    ANCIENT_DOMAIN_KEY,
    ANCIENT_DOMAIN_LOCATION,
    ANCIENT_DOMAIN_NODES,
    ANCIENT_DOMAIN_PARTY_TYPE,
    ANCIENT_DOMAIN_REPEAT_REWARD,
    ANCIENT_DOMAIN_STAMINA_COST,
    resolve_ancient_domain_node,
)
from .secret_realm_rules import realm_at_least


ANCIENT_DOMAIN_CODEX = "codex.domain.ancient_domain"
ACTIVE_STATUSES = ("routing", "combat_pending", "cleared")


class AncientDomainRepositoryMixin:
    """Own ancient-domain route, lock, combat handoff, and reward transactions."""

    @staticmethod
    def _ancient_json(raw: Any, default: dict[str, Any] | None = None) -> dict[str, Any]:
        value = json.loads(raw) if isinstance(raw, str) else raw
        return dict(value) if isinstance(value, dict) else dict(default or {})

    @staticmethod
    def _ancient_week_key(now: datetime) -> str:
        return now.astimezone(timezone.utc).strftime("%G-W%V")

    def _ancient_operation(self, connection, operation_id: str, operation_name: str, request_hash: str):
        row = connection.execute(
            "SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id=?",
            (operation_id,),
        ).fetchone()
        if row is None:
            return None
        if str(row["operation_name"]) != operation_name or str(row["request_hash"]) != request_hash:
            raise OperationConflictError("operation ID was reused with different input")
        return self._ancient_json(row["result_json"])

    @staticmethod
    def _ancient_store_operation(connection, operation_id, operation_name, player_id, request_hash, payload, now_text):
        connection.execute(
            "INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (operation_id, operation_name, player_id, request_hash, json.dumps(payload, ensure_ascii=False, sort_keys=True), now_text),
        )

    async def enter_ancient_domain(
        self, *, platform: str, platform_user_id: str, operation_id: str
    ) -> AncientDomainRunRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._retry_sync, self._enter_ancient_domain_sync, platform, platform_user_id, operation_id
            )

    def _enter_ancient_domain_sync(self, platform: str, platform_user_id: str, operation_id: str) -> AncientDomainRunRecord:
        operation_name = "ancient_domain.enter"
        request_hash = self._request_hash(operation_name, {
            "platform": platform, "platform_user_id": platform_user_id, "instance_key": ANCIENT_DOMAIN_KEY,
        })
        now = self._now()
        now_text = serialize_datetime(now)
        quota_key = self._ancient_week_key(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._ancient_operation(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                replay["already_completed"] = True
                return self._ancient_record(replay)
            leader = self._require_player(connection, platform, platform_user_id)
            membership = connection.execute(
                "SELECT * FROM party_members WHERE player_id=? AND status='active' ORDER BY id DESC LIMIT 1",
                (leader["id"],),
            ).fetchone()
            if membership is None or str(membership["role"]) != "leader":
                raise AncientDomainRequirementError("only the dedicated-party leader can enter")
            party = connection.execute("SELECT * FROM parties WHERE party_id=?", (membership["party_id"],)).fetchone()
            if (
                party is None or str(party["party_type"]) != PARTY_TYPE_SECRET_REALM_ANCIENT
                or str(party["status"]) != "ready" or str(party["location_key"]) != ANCIENT_DOMAIN_LOCATION
                or party["current_session_id"]
            ):
                raise AncientDomainRequirementError("a confirmed ancient-domain party is required")
            members = connection.execute(
                "SELECT m.role, m.confirmed_at, p.* FROM party_members m JOIN players p ON p.id=m.player_id "
                "WHERE m.party_id=? AND m.status='active' ORDER BY m.id",
                (party["party_id"],),
            ).fetchall()
            if len(members) != 3 or any(not row["confirmed_at"] for row in members):
                raise AncientDomainRequirementError("exactly three confirmed members are required")
            if player_integer(leader, "stamina") < ANCIENT_DOMAIN_STAMINA_COST:
                raise ResourceInsufficientError("party leader lacks entry stamina")

            first_clear: dict[int, bool] = {}
            member_combat_snapshots: list[dict[str, Any]] = []
            for row in members:
                player_id = int(row["id"])
                if (
                    str(row["location_key"]) != ANCIENT_DOMAIN_LOCATION
                    or not realm_at_least(str(row["realm_key"]), player_integer(row, "realm_layer"), "soul_transformation", 1, self.content)
                ):
                    raise AncientDomainRequirementError("a member lacks location or soul-transformation access")
                crack_until = row["domain_crack_until"]
                if crack_until:
                    try:
                        if datetime.fromisoformat(str(crack_until)) > now:
                            raise AncientDomainRequirementError("a member has an active domain crack")
                    except ValueError:
                        pass
                if self._has_active_long_action(connection, player_id):
                    raise AncientDomainBusyError("a member has another active action")
                if connection.execute(
                    "SELECT 1 FROM party_battle_members WHERE player_id=? AND asset_lock_status='locked' LIMIT 1",
                    (player_id,),
                ).fetchone():
                    raise AncientDomainBusyError("a member has locked battle assets")
                if connection.execute(
                    "SELECT 1 FROM secret_realm_runs WHERE player_id=? AND status IN ('entered','routing','combat_pending','cleared','failed') LIMIT 1",
                    (player_id,),
                ).fetchone() or connection.execute(
                    "SELECT 1 FROM boundary_rift_members WHERE player_id=? AND status='active' LIMIT 1", (player_id,)
                ).fetchone():
                    raise AncientDomainBusyError("a member has another secret-realm run")
                if connection.execute(
                    "SELECT 1 FROM ancient_domain_members WHERE player_id=? AND status='active' LIMIT 1", (player_id,)
                ).fetchone():
                    raise AncientDomainBusyError("a member has an active ancient-domain run")
                if connection.execute(
                    "SELECT 1 FROM ancient_domain_members WHERE player_id=? AND quota_key=? LIMIT 1",
                    (player_id, quota_key),
                ).fetchone():
                    raise AncientDomainQuotaError("a member already used this UTC week")

                player_state = player_combat_values(row)
                stat_snapshot = self._build_player_stat_snapshot(connection, row)
                skills = self._battle_skill_snapshot(connection, player_id, str(row["path_key"] or ""))
                first_clear[player_id] = connection.execute(
                    "SELECT 1 FROM ancient_domain_members WHERE player_id=? AND status='cleared' LIMIT 1",
                    (player_id,),
                ).fetchone() is None
                member_combat_snapshots.append({
                    "database_id": player_id,
                    "player_id": player_state["player_id"],
                    "platform": player_state["platform"],
                    "platform_user_id": player_state["platform_user_id"],
                    "role": str(row["role"]),
                    "realm_key": player_state["realm_key"],
                    "realm_layer": player_state["realm_layer"],
                    "location_key": player_state["location_key"],
                    "path_key": player_state["path_key"],
                    "qualification": stat_snapshot["base_stats"],
                    "stat_snapshot": stat_snapshot,
                    "stats": stat_snapshot["combat_stats"],
                    "constitution_effect": stat_snapshot["constitution_effect"],
                    "manual_effects": stat_snapshot["manual_effects"],
                    "equipment": stat_snapshot["equipment"],
                    "skills": skills,
                    "soul_power": player_state["soul_power"],
                    "pollution": player_state["pollution"],
                    "bloodline_stability": player_state["bloodline_stability"],
                    "cross_realm_penalty_bp": player_state["cross_realm_penalty_bp"],
                    "faction_reputation": player_state["faction_reputation"],
                    "alliance_key": self._alliance_key_from_row(row),
                    "domain_key": player_state["domain_key"],
                    "domain_charge": player_state["domain_charge"],
                    "domain_charge_max": player_state["domain_charge_max"],
                    "domain_power": player_state["domain_power"],
                })

            run_id = f"ancient-domain-{uuid4().hex}"
            expires_at = serialize_datetime(now + timedelta(seconds=ANCIENT_DOMAIN_EXPIRY_SECONDS))
            snapshot = {
                "instance_key": ANCIENT_DOMAIN_KEY,
                "party_type": ANCIENT_DOMAIN_PARTY_TYPE,
                "party_id": str(party["party_id"]),
                "location_key": ANCIENT_DOMAIN_LOCATION,
                "node_keys": list(ANCIENT_DOMAIN_NODES),
                "current_node": ANCIENT_DOMAIN_NODES[0],
                "node_history": [],
                "path_choice": None,
                "members": [
                    {"database_id": member["database_id"], "player_id": member["player_id"], "role": member["role"]}
                    for member in member_combat_snapshots
                ],
                "member_combat_snapshots": member_combat_snapshots,
                "first_clear_by_player": {str(key): value for key, value in first_clear.items()},
                "entry_cost": {"leader_stamina": ANCIENT_DOMAIN_STAMINA_COST},
            }
            try:
                change_player_state(
                    connection,
                    leader,
                    updated_at=now_text,
                    value_delta={"stamina": -ANCIENT_DOMAIN_STAMINA_COST},
                )
            except ValueError:
                raise ResourceInsufficientError("party leader stamina changed during entry")
            connection.execute(
                "INSERT INTO ancient_domain_runs(run_id, party_id, status, node_index, battle_id, quota_key, starts_at, expires_at, snapshot_json, result_json, entry_operation_id, created_at, updated_at) "
                "VALUES (?, ?, 'routing', 0, NULL, ?, ?, ?, ?, '{}', ?, ?, ?)",
                (run_id, party["party_id"], quota_key, now_text, expires_at,
                 json.dumps(snapshot, ensure_ascii=False, sort_keys=True), operation_id,
                 now_text, now_text),
            )
            for index, row in enumerate(members):
                connection.execute(
                    "INSERT INTO ancient_domain_members(run_id, player_id, quota_key, member_order, first_clear, status, reward_json, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, 'active', '{}', ?, ?)",
                    (run_id, row["id"], quota_key, index, int(first_clear[int(row["id"])]), now_text, now_text),
                )
            run = connection.execute("SELECT * FROM ancient_domain_runs WHERE run_id=?", (run_id,)).fetchone()
            payload = self._ancient_payload(run, snapshot, {})
            self._ancient_store_operation(connection, operation_id, operation_name, int(leader["id"]), request_hash, payload, now_text)
            return self._ancient_record(payload)

    async def choose_ancient_domain_node(
        self, *, platform: str, platform_user_id: str, node_key: str,
        path_choice: str | None, operation_id: str,
    ) -> AncientDomainRunRecord:
        await self.initialize()
        async with self._inflight:
            record = await asyncio.to_thread(
                self._retry_sync, self._choose_ancient_domain_node_sync,
                platform, platform_user_id, node_key, path_choice, operation_id,
            )
        if record.status != "combat_pending":
            return record
        if not record.battle_id:
            try:
                await self.start_party_battle(
                    platform=platform,
                    platform_user_id=platform_user_id,
                    party_id=record.party_id,
                    operation_id=f"ancient_domain.battle.start:{record.run_id}:{record.node_index}",
                    ancient_domain_run_id=record.run_id,
                )
            except Exception:
                await asyncio.to_thread(self._ancient_compensate_sync, record.run_id)
                raise
            record = await asyncio.to_thread(self._get_ancient_domain_run_for_actor, platform, platform_user_id)
            if not record.battle_id:
                raise AncientDomainNotReadyError("battle session did not attach to the run")
        return record

    def _choose_ancient_domain_node_sync(self, platform, platform_user_id, node_key, path_choice, operation_id):
        operation_name = "ancient_domain.choose_node"
        request_hash = self._request_hash(operation_name, {
            "platform": platform, "platform_user_id": platform_user_id,
            "node_key": node_key, "path_choice": path_choice,
        })
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._ancient_operation(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                current = self._active_ancient_domain_for_actor(connection, platform, platform_user_id)
                if current is not None and str(current["status"]) == "combat_pending":
                    return self._ancient_record_from_row(connection, current)
                replay["already_completed"] = True
                return self._ancient_record(replay)
            actor = self._require_player(connection, platform, platform_user_id)
            membership = connection.execute(
                "SELECT role FROM party_members WHERE player_id=? AND status='active' ORDER BY id DESC LIMIT 1",
                (actor["id"],),
            ).fetchone()
            if membership is None or str(membership["role"]) != "leader":
                raise AncientDomainRequirementError("only the party leader may advance the route")
            run = self._active_ancient_domain_for_actor(connection, platform, platform_user_id)
            if run is None:
                raise AncientDomainNotFoundError("no active ancient-domain run")
            if str(run["status"]) != "routing":
                raise AncientDomainNotReadyError("the current run is not routing")
            if now_text >= str(run["expires_at"]):
                self._expire_ancient_domain(connection, run, now_text)
                connection.commit()
                return self._ancient_record_from_row(connection, run["run_id"])
            snapshot = self._ancient_json(run["snapshot_json"])
            node_index = int(run["node_index"])
            if node_index >= len(ANCIENT_DOMAIN_NODES) or node_key != ANCIENT_DOMAIN_NODES[node_index]:
                raise AncientDomainNodeError("node is not the next authorized route step")
            if (node_key == "fractured_gallery" and path_choice not in {"inner", "outer"}) or (
                node_key != "fractured_gallery" and path_choice is not None
            ):
                raise AncientDomainNodeError("route branch input is invalid")
            snapshot.setdefault("node_history", []).append(node_key)
            if path_choice:
                snapshot["path_choice"] = path_choice
            if node_key == "ancient_domain_lord":
                status = "combat_pending"
                next_index = node_index
                snapshot["current_node"] = node_key
            else:
                next_index = node_index + 1
                status = "cleared" if next_index >= len(ANCIENT_DOMAIN_NODES) else "routing"
                snapshot["current_node"] = ANCIENT_DOMAIN_NODES[next_index] if status == "routing" else None
            connection.execute(
                "UPDATE ancient_domain_runs SET status=?, node_index=?, snapshot_json=?, battle_id=NULL, updated_at=? WHERE run_id=?",
                (status, next_index, json.dumps(snapshot, ensure_ascii=False, sort_keys=True), now_text, run["run_id"]),
            )
            updated = connection.execute("SELECT * FROM ancient_domain_runs WHERE run_id=?", (run["run_id"],)).fetchone()
            payload = self._ancient_payload(updated, snapshot, self._ancient_json(updated["result_json"]))
            self._ancient_store_operation(connection, operation_id, operation_name, int(actor["id"]), request_hash, payload, now_text)
            return self._ancient_record(payload)

    async def settle_ancient_domain(
        self, *, platform: str, platform_user_id: str, operation_id: str
    ) -> AncientDomainRunRecord:
        await self.initialize()
        record = await asyncio.to_thread(self._get_ancient_domain_run_for_actor, platform, platform_user_id)
        if record.status == "combat_pending":
            if not record.battle_id:
                raise AncientDomainNotReadyError("the boss encounter has no battle session")
            expired = await asyncio.to_thread(self._ancient_expire_battle_if_due, record.run_id)
            battle_operation = f"ancient_domain.battle.settle:{record.run_id}:{record.node_index}"
            if expired:
                if record.battle_id:
                    await self.resolve_party_battle(
                        platform=platform, platform_user_id=platform_user_id,
                        battle_id=record.battle_id, operation_id=battle_operation,
                    )
                    return await asyncio.to_thread(self._finish_ancient_domain_battle, record.run_id, "expired")
                return await asyncio.to_thread(self._get_ancient_domain_run_for_actor, platform, platform_user_id)
            battle = await self.settle_party_battle(
                platform=platform, platform_user_id=platform_user_id,
                battle_id=record.battle_id, operation_id=battle_operation,
            )
            return await asyncio.to_thread(self._finish_ancient_domain_battle, record.run_id, battle.outcome)
        async with self._inflight:
            return await asyncio.to_thread(
                self._retry_sync, self._settle_ancient_domain_sync,
                platform, platform_user_id, operation_id,
            )

    def _settle_ancient_domain_sync(self, platform, platform_user_id, operation_id):
        operation_name = "ancient_domain.settle"
        request_hash = self._request_hash(operation_name, {"platform": platform, "platform_user_id": platform_user_id})
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._ancient_operation(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                replay["already_completed"] = True
                return self._ancient_record(replay)
            actor = self._require_player(connection, platform, platform_user_id, writable=False)
            run = self._latest_ancient_domain_for_actor(connection, int(actor["id"]))
            if run is None:
                raise AncientDomainNotFoundError("no ancient-domain result exists")
            if str(run["status"]) == "settled":
                result = self._ancient_json(run["result_json"])
                payload = self._ancient_payload(run, self._ancient_json(run["snapshot_json"]), result)
                self._ancient_store_operation(connection, operation_id, operation_name, int(actor["id"]), request_hash, payload, now_text)
                return self._ancient_record(payload)
            if str(run["status"]) != "cleared":
                if str(run["status"]) in {"failed", "expired", "system_aborted"}:
                    return self._ancient_record_from_row(connection, run["run_id"])
                raise AncientDomainNotReadyError("complete all route nodes and the boss before settling")
            if now_text >= str(run["expires_at"]):
                self._expire_ancient_domain(connection, run, now_text)
                return self._ancient_record_from_row(connection, run["run_id"])
            members = connection.execute(
                "SELECT m.*, p.id AS database_id, p.player_id AS stable_player_id, p.spirit_stones, p.inventory_json "
                "FROM ancient_domain_members m JOIN players p ON p.id=m.player_id "
                "WHERE m.run_id=? ORDER BY m.member_order",
                (run["run_id"],),
            ).fetchall()
            rewards: dict[str, dict[str, int]] = {}
            first_clear_members: list[str] = []
            for member in members:
                reward = dict(ANCIENT_DOMAIN_FIRST_REWARD if bool(member["first_clear"]) else ANCIENT_DOMAIN_REPEAT_REWARD)
                rewards[str(member["player_id"])] = reward
                if bool(member["first_clear"]):
                    first_clear_members.append(str(member["stable_player_id"]))
                    record_codex_discovery(
                        connection,
                        player_id=int(member["player_id"]),
                        entry_key=ANCIENT_DOMAIN_CODEX,
                        operation_id=f"{operation_id}:codex:{member['player_id']}",
                        occurred_at=now,
                        snapshot={"run_id": str(run["run_id"]), "instance_key": ANCIENT_DOMAIN_KEY},
                    )
                grant_player_assets(
                    connection,
                    member,
                    reward,
                    now_text,
                )
                connection.execute(
                    "UPDATE ancient_domain_members SET status='cleared', reward_json=?, updated_at=? WHERE run_id=? AND player_id=?",
                    (json.dumps(reward, ensure_ascii=False, sort_keys=True), now_text, run["run_id"], member["player_id"]),
                )
            result = {"outcome": "won", "rewards": rewards, "first_clear_members": first_clear_members}
            connection.execute(
                "UPDATE ancient_domain_runs SET status='settled', result_json=?, updated_at=? WHERE run_id=? AND status='cleared'",
                (json.dumps(result, ensure_ascii=False, sort_keys=True), now_text, run["run_id"]),
            )
            settled = connection.execute("SELECT * FROM ancient_domain_runs WHERE run_id=?", (run["run_id"],)).fetchone()
            payload = self._ancient_payload(settled, self._ancient_json(settled["snapshot_json"]), result)
            self._ancient_store_operation(connection, operation_id, operation_name, int(actor["id"]), request_hash, payload, now_text)
            return self._ancient_record(payload)

    async def compensate_ancient_domain_system_failure(self, *, run_id: str) -> AncientDomainRunRecord:
        await self.initialize()
        return await asyncio.to_thread(self._ancient_compensate_sync, run_id)

    async def has_active_ancient_domain(self, *, platform: str, platform_user_id: str) -> bool:
        await self.initialize()
        return await asyncio.to_thread(self._has_active_ancient_domain_sync, platform, platform_user_id)

    def _has_active_ancient_domain_sync(self, platform: str, platform_user_id: str) -> bool:
        with self._connect() as connection:
            player = self._require_player(connection, platform, platform_user_id, writable=False)
            return connection.execute(
                "SELECT 1 FROM ancient_domain_members m JOIN ancient_domain_runs r ON r.run_id=m.run_id "
                "WHERE m.player_id=? AND m.status='active' AND r.status IN ('routing','combat_pending','cleared') LIMIT 1",
                (player["id"],),
            ).fetchone() is not None

    async def has_ancient_domain_settlement_operation(self, operation_id: str) -> bool:
        await self.initialize()
        return await asyncio.to_thread(self._has_ancient_domain_settlement_operation_sync, operation_id)

    def _has_ancient_domain_settlement_operation_sync(self, operation_id: str) -> bool:
        with self._connect() as connection:
            return connection.execute(
                "SELECT 1 FROM operations WHERE operation_id=? AND operation_name='ancient_domain.settle'",
                (operation_id,),
            ).fetchone() is not None

    async def has_latest_ancient_domain_run(self, *, platform: str, platform_user_id: str) -> bool:
        await self.initialize()
        return await asyncio.to_thread(self._has_latest_ancient_domain_run_sync, platform, platform_user_id)

    def _has_latest_ancient_domain_run_sync(self, platform: str, platform_user_id: str) -> bool:
        with self._connect() as connection:
            player = self._require_player(connection, platform, platform_user_id, writable=False)
            ancient = self._latest_ancient_domain_for_actor(connection, int(player["id"]))
            if ancient is None:
                return False
            ancestral = connection.execute(
                "SELECT starts_at FROM ancestral_hall_runs WHERE player_id=? ORDER BY id DESC LIMIT 1",
                (player["id"],),
            ).fetchone()
            if ancestral is not None and str(ancestral["starts_at"]) > str(ancient["starts_at"]):
                return False
            ordinary = connection.execute(
                "SELECT run_id, created_at FROM secret_realm_runs WHERE player_id=? ORDER BY id DESC LIMIT 1",
                (player["id"],),
            ).fetchone()
            if ordinary is None or str(ancient["starts_at"]) > str(ordinary["created_at"]):
                return True
            if str(ancient["starts_at"]) < str(ordinary["created_at"]):
                return False
            ancient_operation = connection.execute(
                "SELECT rowid FROM operations WHERE operation_id=?",
                (ancient["entry_operation_id"],),
            ).fetchone()
            ordinary_operation = connection.execute(
                "SELECT rowid FROM operations WHERE player_id=? "
                "AND json_extract(result_json, '$.run_id')=? ORDER BY rowid LIMIT 1",
                (player["id"], ordinary["run_id"]),
            ).fetchone()
            return ancient_operation is not None and (
                ordinary_operation is None or int(ancient_operation["rowid"]) > int(ordinary_operation["rowid"])
            )

    def _ancient_compensate_sync(self, run_id: str) -> AncientDomainRunRecord:
        now_text = serialize_datetime(self._now())
        operation_id = f"ancient_domain.system_abort:{run_id}"
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            run = connection.execute("SELECT * FROM ancient_domain_runs WHERE run_id=?", (run_id,)).fetchone()
            if run is None:
                raise AncientDomainNotFoundError("ancient-domain run does not exist")
            if str(run["status"]) == "system_aborted":
                return self._ancient_record_from_row(connection, run_id)
            if str(run["status"]) not in ACTIVE_STATUSES:
                raise AncientDomainNotReadyError("only an unresolved run can be compensated")
            party = connection.execute("SELECT leader_id, current_session_id FROM parties WHERE party_id=?", (run["party_id"],)).fetchone()
            if party is None:
                raise AncientDomainNotFoundError("ancient-domain party no longer exists")
            leader = connection.execute(
                "SELECT * FROM players WHERE id = ?", (party["leader_id"],)
            ).fetchone()
            if leader is not None:
                change_player_state(
                    connection,
                    leader,
                    updated_at=now_text,
                    value_delta={"stamina": ANCIENT_DOMAIN_STAMINA_COST},
                    maximums={"stamina": leader["stamina_max"]},
                )
            energy_rows = connection.execute(
                "SELECT player_id, SUM(amount) AS amount FROM ancient_domain_energy_events WHERE run_id=? GROUP BY player_id",
                (run_id,),
            ).fetchall()
            for row in energy_rows:
                player = connection.execute(
                    "SELECT * FROM players WHERE id = ?", (row["player_id"],)
                ).fetchone()
                if player is not None:
                    change_player_state(
                        connection,
                        player,
                        updated_at=now_text,
                        value_delta={"domain_charge": int(row["amount"])},
                        maximums={"domain_charge": player_integer(player, "domain_charge_max")},
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
                "UPDATE ancient_domain_members SET status='released', quota_key='released:'||?||':'||player_id, updated_at=? WHERE run_id=? AND status='active'",
                (run_id, now_text, run_id),
            )
            result = {"outcome": "system_aborted", "reason": "system_compensation"}
            connection.execute(
                "UPDATE ancient_domain_runs SET status='system_aborted', battle_id=NULL, result_json=?, updated_at=? WHERE run_id=?",
                (json.dumps(result, sort_keys=True), now_text, run_id),
            )
            snapshot = self._ancient_json(run["snapshot_json"])
            updated = connection.execute("SELECT * FROM ancient_domain_runs WHERE run_id=?", (run_id,)).fetchone()
            payload = self._ancient_payload(updated, snapshot, result)
            self._ancient_store_operation(
                connection, operation_id, "ancient_domain.system_abort", int(party["leader_id"]),
                self._request_hash("ancient_domain.system_abort", {"run_id": run_id}), payload, now_text,
            )
            return self._ancient_record(payload)

    def _ancient_expire_battle_if_due(self, run_id: str) -> bool:
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            run = connection.execute("SELECT * FROM ancient_domain_runs WHERE run_id=?", (run_id,)).fetchone()
            if run is None or str(run["status"]) != "combat_pending" or now_text < str(run["expires_at"]):
                return False
            if run["battle_id"]:
                connection.execute(
                    "UPDATE party_battle_sessions SET status='expired', result_json=?, updated_at=? WHERE battle_id=? AND status IN ('created','running')",
                    (json.dumps({"outcome": "expired", "reason": "ancient_domain_timeout"}, sort_keys=True), now_text, run["battle_id"]),
                )
            else:
                self._expire_ancient_domain(connection, run, now_text)
            return True

    def _finish_ancient_domain_battle(self, run_id: str, outcome: str | None) -> AncientDomainRunRecord:
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            run = connection.execute("SELECT * FROM ancient_domain_runs WHERE run_id=?", (run_id,)).fetchone()
            if run is None:
                raise AncientDomainNotFoundError("ancient-domain run no longer exists")
            if str(run["status"]) != "combat_pending":
                return self._ancient_record_from_row(connection, run_id)
            snapshot = self._ancient_json(run["snapshot_json"])
            timed_out = now_text >= str(run["expires_at"]) or outcome == "expired"
            if outcome == "won" and not timed_out:
                next_index = int(run["node_index"]) + 1
                snapshot["current_node"] = ANCIENT_DOMAIN_NODES[next_index]
                status = "routing"
                result = {"last_battle_outcome": "won"}
            else:
                next_index = int(run["node_index"])
                status = "expired" if timed_out else "failed"
                result = {"outcome": "expired" if timed_out else "lost", "reason": "battle_" + str(outcome)}
                connection.execute(
                    "UPDATE ancient_domain_members SET status=?, updated_at=? WHERE run_id=? AND status='active'",
                    (status, now_text, run_id),
                )
            connection.execute(
                "UPDATE ancient_domain_runs SET status=?, node_index=?, battle_id=NULL, snapshot_json=?, result_json=?, updated_at=? WHERE run_id=?",
                (status, next_index, json.dumps(snapshot, ensure_ascii=False, sort_keys=True), json.dumps(result, sort_keys=True), now_text, run_id),
            )
            return self._ancient_record_from_row(connection, run_id)

    def _get_ancient_domain_run_for_actor(self, platform: str, platform_user_id: str) -> AncientDomainRunRecord:
        with self._connect() as connection:
            actor = self._require_player(connection, platform, platform_user_id, writable=False)
            run = self._latest_ancient_domain_for_actor(connection, int(actor["id"]))
            if run is None:
                raise AncientDomainNotFoundError("no ancient-domain run exists for this player")
            return self._ancient_record_from_row(connection, run)

    def _active_ancient_domain_for_actor(self, connection, platform: str, platform_user_id: str):
        actor = connection.execute(
            "SELECT id FROM players WHERE platform=? AND platform_user_id=?", (platform, platform_user_id)
        ).fetchone()
        if actor is None:
            raise AncientDomainNotFoundError("player does not exist")
        return connection.execute(
            "SELECT r.* FROM ancient_domain_runs r JOIN ancient_domain_members m ON m.run_id=r.run_id "
            "WHERE m.player_id=? AND m.status='active' AND r.status IN ('routing','combat_pending','cleared') "
            "ORDER BY r.id DESC LIMIT 1",
            (actor["id"],),
        ).fetchone()

    @staticmethod
    def _latest_ancient_domain_for_actor(connection, player_id: int):
        return connection.execute(
            "SELECT r.* FROM ancient_domain_runs r JOIN ancient_domain_members m ON m.run_id=r.run_id "
            "WHERE m.player_id=? ORDER BY r.id DESC LIMIT 1", (player_id,)
        ).fetchone()

    def _expire_ancient_domain(self, connection, run, now_text: str) -> None:
        result = {"outcome": "expired", "reason": "run_timeout"}
        connection.execute(
            "UPDATE ancient_domain_runs SET status='expired', result_json=?, updated_at=? WHERE run_id=? AND status IN ('routing','combat_pending','cleared')",
            (json.dumps(result, sort_keys=True), now_text, run["run_id"]),
        )
        connection.execute(
            "UPDATE ancient_domain_members SET status='expired', updated_at=? WHERE run_id=? AND status='active'",
            (now_text, run["run_id"]),
        )

    @classmethod
    def _ancient_payload(cls, run, snapshot, result):
        return {
            "run_id": str(run["run_id"]),
            "party_id": str(run["party_id"]),
            "status": str(run["status"]),
            "node_index": int(run["node_index"]),
            "current_node": snapshot.get("current_node"),
            "battle_id": run["battle_id"],
            "expires_at": str(run["expires_at"]),
            "outcome": result.get("outcome", result.get("last_battle_outcome")),
            "rewards": result.get("rewards", {}),
            "first_clear_members": result.get("first_clear_members", []),
        }

    @classmethod
    def _ancient_record_from_row(cls, connection, run):
        row = run if hasattr(run, "keys") else connection.execute(
            "SELECT * FROM ancient_domain_runs WHERE run_id=?", (run,)
        ).fetchone()
        if row is None:
            raise AncientDomainNotFoundError("ancient-domain run does not exist")
        return cls._ancient_record(cls._ancient_payload(
            row, cls._ancient_json(row["snapshot_json"]), cls._ancient_json(row["result_json"])
        ))

    @staticmethod
    def _ancient_record(payload, replay: bool = False) -> AncientDomainRunRecord:
        return AncientDomainRunRecord(
            run_id=str(payload["run_id"]),
            party_id=str(payload["party_id"]),
            status=str(payload["status"]),
            node_index=int(payload["node_index"]),
            current_node=str(payload["current_node"]) if payload.get("current_node") is not None else None,
            battle_id=str(payload["battle_id"]) if payload.get("battle_id") else None,
            rewards={str(player): {str(key): int(value) for key, value in dict(reward).items()} for player, reward in dict(payload.get("rewards", {})).items()},
            first_clear_members=tuple(str(item) for item in payload.get("first_clear_members", [])),
            outcome=str(payload["outcome"]) if payload.get("outcome") else None,
            expires_at=str(payload.get("expires_at", "")),
            already_completed=bool(replay or payload.get("already_completed", False)),
        )


__all__ = ["AncientDomainRepositoryMixin"]
