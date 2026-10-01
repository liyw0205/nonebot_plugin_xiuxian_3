"""Persistence for the time-fort party instance."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from ...contracts import serialize_datetime
from ..advancement.constitution_effects import constitution_effect_snapshot
from ..persistence.errors import (
    OperationConflictError,
    ResourceInsufficientError,
    TimeFortBusyError,
    TimeFortNodeError,
    TimeFortNotFoundError,
    TimeFortNotReadyError,
    TimeFortQuotaError,
    TimeFortRequirementError,
)
from ..social.party_rules import PARTY_TYPE_SECRET_REALM_TIME_FORT
from ..specials.codex_projection import record_codex_discovery
from ..utils.assets import grant_player_assets
from ..utils.player import change_player_state, player_combat_values, player_integer, player_resource
from .secret_realm_rules import realm_at_least
from .time_fort_models import TimeFortRunRecord
from .time_fort_rules import (
    TIME_FORT_EXPIRY_SECONDS,
    TIME_FORT_FIRST_REWARD,
    TIME_FORT_KEY,
    TIME_FORT_LOCATION,
    TIME_FORT_MAX_MEMBERS,
    TIME_FORT_MIN_MEMBERS,
    TIME_FORT_NODES,
    TIME_FORT_PARTY_TYPE,
    TIME_FORT_PERMISSION,
    TIME_FORT_REPEAT_REWARD,
    TIME_FORT_STAMINA_COST,
    TIME_FORT_STORY_FLAG,
    TIME_FORT_WEEKLY_LIMIT,
)


ACTIVE_TIME_FORT_STATUSES = ("routing", "combat_pending", "cleared")


class TimeFortRepositoryMixin:
    """Own admission, route progression, battle linkage, and rewards."""

    @staticmethod
    def _time_fort_json(raw: Any, default: dict[str, Any] | None = None) -> dict[str, Any]:
        value = json.loads(raw) if isinstance(raw, str) else raw
        return dict(value) if isinstance(value, dict) else dict(default or {})

    @staticmethod
    def _time_fort_week(now: datetime) -> str:
        return now.astimezone(timezone.utc).strftime("%G-W%V")

    def _time_fort_operation(self, connection, operation_id: str, operation_name: str, request_hash: str):
        row = connection.execute(
            "SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id=?",
            (operation_id,),
        ).fetchone()
        if row is None:
            return None
        if str(row["operation_name"]) != operation_name or str(row["request_hash"]) != request_hash:
            raise OperationConflictError("operation ID was reused with different input")
        return self._time_fort_json(row["result_json"])

    @staticmethod
    def _time_fort_store_operation(connection, operation_id, operation_name, player_id, request_hash, payload, now_text):
        connection.execute(
            "INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (operation_id, operation_name, player_id, request_hash, json.dumps(payload, ensure_ascii=False, sort_keys=True), now_text),
        )

    @classmethod
    def _time_fort_payload(cls, run, snapshot: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        index = int(run["node_index"])
        status = str(run["status"])
        current = snapshot.get("current_node")
        if status in ACTIVE_TIME_FORT_STATUSES and current is None and index < len(TIME_FORT_NODES):
            current = TIME_FORT_NODES[index]
        return {
            "run_id": str(run["run_id"]),
            "party_id": str(run["party_id"]),
            "status": status,
            "node_index": index,
            "current_node": current if status in ACTIVE_TIME_FORT_STATUSES else None,
            "battle_id": run["battle_id"],
            "expires_at": str(run["expires_at"]),
            "rewards": result.get("rewards", {}),
            "first_clear_members": result.get("first_clear_members", []),
            "outcome": result.get("outcome", result.get("last_battle_outcome")),
        }

    @classmethod
    def _time_fort_record_from_row(cls, connection, run) -> TimeFortRunRecord:
        row = run if hasattr(run, "keys") else connection.execute("SELECT * FROM time_fort_runs WHERE run_id=?", (run,)).fetchone()
        if row is None:
            raise TimeFortNotFoundError("time-fort run does not exist")
        snapshot = cls._time_fort_json(row["snapshot_json"])
        result = cls._time_fort_json(row["result_json"])
        return cls._time_fort_record(cls._time_fort_payload(row, snapshot, result))

    @staticmethod
    def _time_fort_record(payload: dict[str, Any], *, replay: bool = False) -> TimeFortRunRecord:
        return TimeFortRunRecord(
            run_id=str(payload["run_id"]), party_id=str(payload["party_id"]), status=str(payload["status"]),
            node_index=int(payload.get("node_index", 0)), current_node=payload.get("current_node"),
            battle_id=str(payload["battle_id"]) if payload.get("battle_id") else None,
            expires_at=str(payload.get("expires_at", "")),
            rewards={str(player): {str(key): int(value) for key, value in dict(reward).items()} for player, reward in dict(payload.get("rewards", {})).items()},
            first_clear_members=tuple(str(value) for value in payload.get("first_clear_members", [])),
            outcome=str(payload["outcome"]) if payload.get("outcome") else None,
            already_completed=bool(replay or payload.get("already_completed", False)),
        )

    async def enter_time_fort(self, *, platform: str, platform_user_id: str, operation_id: str) -> TimeFortRunRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._retry_sync, self._time_fort_enter_sync, platform, platform_user_id, operation_id)

    def _time_fort_enter_sync(self, platform: str, platform_user_id: str, operation_id: str) -> TimeFortRunRecord:
        operation_name = "time_fort.enter"
        request_hash = self._request_hash(operation_name, {"platform": platform, "platform_user_id": platform_user_id, "instance_key": TIME_FORT_KEY})
        now = self._now()
        now_text = serialize_datetime(now)
        quota_key = self._time_fort_week(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._time_fort_operation(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                replay["already_completed"] = True
                return self._time_fort_record(replay, replay=True)
            leader = self._require_player(connection, platform, platform_user_id)
            membership = connection.execute(
                "SELECT * FROM party_members WHERE player_id=? AND status='active' ORDER BY id DESC LIMIT 1", (leader["id"],)
            ).fetchone()
            if membership is None or str(membership["role"]) != "leader":
                raise TimeFortRequirementError("only the dedicated-party leader can enter")
            party = connection.execute("SELECT * FROM parties WHERE party_id=?", (membership["party_id"],)).fetchone()
            if (
                party is None or str(party["party_type"]) != PARTY_TYPE_SECRET_REALM_TIME_FORT
                or str(party["status"]) != "ready" or str(party["location_key"]) != TIME_FORT_LOCATION
                or party["current_session_id"]
            ):
                raise TimeFortRequirementError("a confirmed time-fort party is required")
            members = connection.execute(
                "SELECT m.role, m.confirmed_at, p.* FROM party_members m JOIN players p ON p.id=m.player_id WHERE m.party_id=? AND m.status='active' ORDER BY m.id",
                (party["party_id"],),
            ).fetchall()
            if not TIME_FORT_MIN_MEMBERS <= len(members) <= TIME_FORT_MAX_MEMBERS or any(not row["confirmed_at"] for row in members):
                raise TimeFortRequirementError("two to five confirmed members are required")
            if player_resource(leader, "stamina") < TIME_FORT_STAMINA_COST:
                raise ResourceInsufficientError("party leader lacks entry stamina")
            combat_snapshots: list[dict[str, Any]] = []
            first_clear: dict[int, bool] = {}
            for row in members:
                player_id = int(row["id"])
                intro = self._json_object(row["intro_json"], {})
                if (
                    str(row["location_key"]) != TIME_FORT_LOCATION
                    or not realm_at_least(str(row["realm_key"]), player_integer(row, "realm_layer"), "void_refining", 1)
                    or TIME_FORT_PERMISSION not in {str(flag) for flag in intro.get("flags", [])}
                ):
                    raise TimeFortRequirementError("a member lacks time-fort permission or archive location")
                if self._has_active_long_action(connection, player_id):
                    raise TimeFortBusyError("a member has another active action")
                if connection.execute("SELECT 1 FROM party_battle_members WHERE player_id=? AND asset_lock_status='locked' LIMIT 1", (player_id,)).fetchone():
                    raise TimeFortBusyError("a member has locked battle assets")
                if connection.execute("SELECT 1 FROM time_fort_members WHERE player_id=? AND status='active' LIMIT 1", (player_id,)).fetchone():
                    raise TimeFortBusyError("a member already has an active time-fort run")
                if int(connection.execute("SELECT COUNT(*) FROM time_fort_members WHERE player_id=? AND quota_key=? AND status<>'system_aborted'", (player_id, quota_key)).fetchone()[0]) >= TIME_FORT_WEEKLY_LIMIT:
                    raise TimeFortQuotaError("a member already used this UTC week")
                player_state = player_combat_values(row)
                equipment = self._battle_equipment_snapshot(connection, player_id)
                qualification = player_state["qualification"]
                constitution_effect = constitution_effect_snapshot(connection, player_id)
                skills = self._battle_skill_snapshot(connection, player_id, str(row["path_key"] or ""))
                stats = self._battle_stats_for_snapshot(
                    qualification, player_state["max_hp"], player_state["initiative"], equipment,
                    constitution_effect,
                )
                first_clear[player_id] = connection.execute("SELECT 1 FROM time_fort_members WHERE player_id=? AND status='settled' LIMIT 1", (player_id,)).fetchone() is None
                combat_snapshots.append({
                    "database_id": player_id, "player_id": player_state["player_id"], "platform": player_state["platform"],
                    "platform_user_id": player_state["platform_user_id"], "role": str(row["role"]),
                    "realm_key": player_state["realm_key"], "realm_layer": player_state["realm_layer"], "location_key": player_state["location_key"],
                    "path_key": player_state["path_key"], "qualification": qualification, "stats": stats,
                    "constitution_effect": constitution_effect,
                    "equipment": list(equipment), "skills": skills,
                })
            run_id = f"time-fort-{uuid4().hex}"
            expires_at = serialize_datetime(now + timedelta(seconds=TIME_FORT_EXPIRY_SECONDS))
            snapshot = {
                "instance_key": TIME_FORT_KEY, "party_type": TIME_FORT_PARTY_TYPE, "party_id": str(party["party_id"]),
                "location_key": TIME_FORT_LOCATION, "node_keys": list(TIME_FORT_NODES), "current_node": TIME_FORT_NODES[0],
                "members": [{"database_id": item["database_id"], "player_id": item["player_id"], "role": item["role"]} for item in combat_snapshots],
                "member_combat_snapshots": combat_snapshots, "first_clear_by_player": {str(key): value for key, value in first_clear.items()},
                "entry_cost": {"leader_stamina": TIME_FORT_STAMINA_COST}, "time_storm": {"interval_rounds": 3, "damage_bp": 500},
            }
            try:
                change_player_state(
                    connection,
                    leader,
                    updated_at=now_text,
                    value_delta={"stamina": -TIME_FORT_STAMINA_COST},
                )
            except ValueError as exc:
                raise ResourceInsufficientError("party leader stamina changed during entry") from exc
            connection.execute(
                "INSERT INTO time_fort_runs(run_id, party_id, status, node_index, battle_id, quota_key, starts_at, expires_at, stamina_cost, snapshot_json, result_json, entry_operation_id, created_at, updated_at) VALUES (?, ?, 'routing', 0, NULL, ?, ?, ?, ?, ?, '{}', ?, ?, ?)",
                (run_id, party["party_id"], quota_key, now_text, expires_at, TIME_FORT_STAMINA_COST, json.dumps(snapshot, ensure_ascii=False, sort_keys=True), operation_id, now_text, now_text),
            )
            for index, row in enumerate(members):
                connection.execute(
                    "INSERT INTO time_fort_members(run_id, player_id, quota_key, member_order, first_clear, status, reward_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 'active', '{}', ?, ?)",
                    (run_id, int(row["id"]), quota_key, index, int(first_clear[int(row["id"])]), now_text, now_text),
                )
            run = connection.execute("SELECT * FROM time_fort_runs WHERE run_id=?", (run_id,)).fetchone()
            payload = self._time_fort_payload(run, snapshot, {})
            self._time_fort_store_operation(connection, operation_id, operation_name, int(leader["id"]), request_hash, payload, now_text)
            return self._time_fort_record(payload)

    def _battle_stats_for_snapshot(
        self, qualification: dict[str, Any], max_hp: int, initiative: int,
        equipment, constitution_effect: dict[str, Any] | None = None,
    ):
        from ..combat.rules import player_stat_snapshot
        return player_stat_snapshot(
            qualification, max_hp=max_hp, initiative=initiative,
            equipment=equipment, constitution_effect=constitution_effect,
        )

    async def choose_time_fort_node(self, *, platform: str, platform_user_id: str, node_key: str, operation_id: str) -> TimeFortRunRecord:
        await self.initialize()
        async with self._inflight:
            record = await asyncio.to_thread(self._retry_sync, self._time_fort_choose_sync, platform, platform_user_id, node_key, operation_id)
        if record.status == "expired":
            await self._time_fort_end_expired_battle(record)
            return record
        if record.status != "combat_pending" or record.battle_id:
            return record
        try:
            identity = await asyncio.to_thread(self._time_fort_leader_identity, record.run_id)
            if identity is None:
                raise TimeFortNotFoundError("time-fort party leader no longer exists")
            _, lead_platform, lead_user = identity
            battle = await self.start_party_battle(
                platform=lead_platform, platform_user_id=lead_user, party_id=record.party_id,
                operation_id=f"time_fort.battle.start:{record.run_id}:{record.node_index}", time_fort_run_id=record.run_id,
            )
            return await asyncio.to_thread(self._time_fort_attach_battle, record.run_id, battle.battle_id, operation_id)
        except Exception:
            await self.compensate_time_fort_system_failure(run_id=record.run_id)
            raise

    def _time_fort_choose_sync(self, platform, platform_user_id, node_key, operation_id):
        operation_name = "time_fort.choose_node"
        request_hash = self._request_hash(operation_name, {"platform": platform, "platform_user_id": platform_user_id, "node_key": node_key})
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._time_fort_operation(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                replay["already_completed"] = True
                return self._time_fort_record(replay, replay=True)
            actor = self._require_player(connection, platform, platform_user_id)
            run = self._time_fort_active_for_actor(connection, int(actor["id"]))
            if run is None:
                raise TimeFortNotFoundError("no active time-fort run")
            party = connection.execute("SELECT leader_id FROM parties WHERE party_id=?", (run["party_id"],)).fetchone()
            if party is None or int(party["leader_id"]) != int(actor["id"]):
                raise TimeFortRequirementError("only party leader can advance the route")
            if now_text >= str(run["expires_at"]):
                self._time_fort_expire(connection, run, now_text)
                updated = connection.execute("SELECT * FROM time_fort_runs WHERE run_id=?", (run["run_id"],)).fetchone()
                payload = self._time_fort_payload(updated, self._time_fort_json(updated["snapshot_json"]), self._time_fort_json(updated["result_json"]))
                self._time_fort_store_operation(connection, operation_id, operation_name, int(actor["id"]), request_hash, payload, now_text)
                return self._time_fort_record(payload)
            if str(run["status"]) != "routing":
                raise TimeFortNotReadyError("the current route node is not ready")
            snapshot = self._time_fort_json(run["snapshot_json"])
            index = int(run["node_index"])
            expected = TIME_FORT_NODES[index] if index < len(TIME_FORT_NODES) else None
            if node_key != expected:
                raise TimeFortNodeError("node is not the current route node")
            if node_key == "time_keeper":
                snapshot["current_node"] = node_key
                connection.execute("UPDATE time_fort_runs SET status='combat_pending', snapshot_json=?, updated_at=? WHERE run_id=?", (json.dumps(snapshot, ensure_ascii=False, sort_keys=True), now_text, run["run_id"]))
            else:
                index += 1
                status = "cleared" if index >= len(TIME_FORT_NODES) else "routing"
                snapshot["current_node"] = TIME_FORT_NODES[index] if status == "routing" else None
                connection.execute("UPDATE time_fort_runs SET status=?, node_index=?, snapshot_json=?, updated_at=? WHERE run_id=?", (status, index, json.dumps(snapshot, ensure_ascii=False, sort_keys=True), now_text, run["run_id"]))
            updated = connection.execute("SELECT * FROM time_fort_runs WHERE run_id=?", (run["run_id"],)).fetchone()
            payload = self._time_fort_payload(updated, snapshot, {})
            self._time_fort_store_operation(connection, operation_id, operation_name, int(actor["id"]), request_hash, payload, now_text)
            return self._time_fort_record(payload)

    def _time_fort_leader_identity(self, run_id: str):
        with self._connect() as connection:
            run = connection.execute("SELECT * FROM time_fort_runs WHERE run_id=?", (run_id,)).fetchone()
            if run is None:
                return None
            leader = connection.execute("SELECT p.platform, p.platform_user_id FROM parties t JOIN players p ON p.id=t.leader_id WHERE t.party_id=?", (run["party_id"],)).fetchone()
            return (run, str(leader["platform"]), str(leader["platform_user_id"])) if leader else None

    def _time_fort_attach_battle(self, run_id: str, battle_id: str, operation_id: str):
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            run = connection.execute("SELECT * FROM time_fort_runs WHERE run_id=?", (run_id,)).fetchone()
            if run is None or str(run["status"]) != "combat_pending":
                raise TimeFortNotReadyError("time-fort node is no longer pending combat")
            connection.execute("UPDATE time_fort_runs SET battle_id=?, updated_at=? WHERE run_id=?", (battle_id, now_text, run_id))
            updated = connection.execute("SELECT * FROM time_fort_runs WHERE run_id=?", (run_id,)).fetchone()
            payload = self._time_fort_payload(updated, self._time_fort_json(updated["snapshot_json"]), self._time_fort_json(updated["result_json"]))
            if operation_id:
                connection.execute("UPDATE operations SET result_json=? WHERE operation_id=? AND operation_name='time_fort.choose_node'", (json.dumps(payload, ensure_ascii=False, sort_keys=True), operation_id))
            return self._time_fort_record(payload)

    async def settle_time_fort(self, *, platform: str, platform_user_id: str, operation_id: str) -> TimeFortRunRecord:
        await self.initialize()
        operation_name = "time_fort.settle"
        request_hash = self._request_hash(operation_name, {"platform": platform, "platform_user_id": platform_user_id})
        replay = await asyncio.to_thread(self._time_fort_read_operation, operation_id, operation_name, request_hash)
        if replay is not None:
            replay["already_completed"] = True
            return self._time_fort_record(replay, replay=True)
        record = await asyncio.to_thread(self._time_fort_latest_for_actor, platform, platform_user_id)
        if record is None:
            raise TimeFortNotFoundError("no time-fort run exists")
        if record.status in ACTIVE_TIME_FORT_STATUSES and serialize_datetime(self._now()) >= record.expires_at:
            record = await asyncio.to_thread(self._time_fort_expire_by_id, record.run_id)
            await self._time_fort_end_expired_battle(record)
        elif record.status == "combat_pending":
            if not record.battle_id:
                identity = await asyncio.to_thread(self._time_fort_leader_identity, record.run_id)
                if identity is None:
                    raise TimeFortNotFoundError("time-fort party leader no longer exists")
                _, lead_platform, lead_user = identity
                try:
                    battle = await self.start_party_battle(platform=lead_platform, platform_user_id=lead_user, party_id=record.party_id, operation_id=f"time_fort.battle.start:{record.run_id}:{record.node_index}", time_fort_run_id=record.run_id)
                    record = await asyncio.to_thread(self._time_fort_attach_battle, record.run_id, battle.battle_id, "")
                except Exception:
                    await self.compensate_time_fort_system_failure(run_id=record.run_id)
                    raise
            battle_result = await self.settle_party_battle(platform=platform, platform_user_id=platform_user_id, battle_id=record.battle_id, operation_id=f"time_fort.battle.settle:{record.run_id}:{record.node_index}")
            record = await asyncio.to_thread(self._time_fort_record_battle_outcome, record.run_id, battle_result.outcome)
            if record.status == "routing":
                return await asyncio.to_thread(self._time_fort_record_progress, record.run_id, platform, platform_user_id, operation_id, operation_name, request_hash)
        return await asyncio.to_thread(self._time_fort_settle_sync, platform, platform_user_id, operation_id, operation_name, request_hash)

    def _time_fort_read_operation(self, operation_id, operation_name, request_hash):
        with self._connect() as connection:
            return self._time_fort_operation(connection, operation_id, operation_name, request_hash)

    def _time_fort_latest_for_actor(self, platform, platform_user_id):
        with self._connect() as connection:
            actor = self._require_player(connection, platform, platform_user_id, writable=False)
            run = connection.execute("SELECT r.* FROM time_fort_runs r JOIN time_fort_members m ON m.run_id=r.run_id WHERE m.player_id=? ORDER BY r.id DESC LIMIT 1", (actor["id"],)).fetchone()
            return self._time_fort_record_from_row(connection, run) if run else None

    def _time_fort_record_progress(self, run_id, platform, platform_user_id, operation_id, operation_name, request_hash):
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._time_fort_operation(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                replay["already_completed"] = True
                return self._time_fort_record(replay, replay=True)
            actor = self._require_player(connection, platform, platform_user_id)
            run = connection.execute("SELECT * FROM time_fort_runs WHERE run_id=?", (run_id,)).fetchone()
            if run is None or str(run["status"]) != "routing":
                raise TimeFortNotReadyError("the battle did not advance the route")
            payload = self._time_fort_payload(run, self._time_fort_json(run["snapshot_json"]), self._time_fort_json(run["result_json"]))
            self._time_fort_store_operation(connection, operation_id, operation_name, int(actor["id"]), request_hash, payload, now_text)
            return self._time_fort_record(payload)

    def _time_fort_settle_sync(self, platform, platform_user_id, operation_id, operation_name, request_hash):
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._time_fort_operation(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                replay["already_completed"] = True
                return self._time_fort_record(replay, replay=True)
            actor = self._require_player(connection, platform, platform_user_id)
            run = connection.execute("SELECT * FROM time_fort_runs WHERE run_id=?", (self._time_fort_latest_id(connection, int(actor["id"])),)).fetchone()
            if run is None:
                raise TimeFortNotFoundError("no time-fort run exists")
            snapshot = self._time_fort_json(run["snapshot_json"])
            result = self._time_fort_json(run["result_json"])
            status = str(run["status"])
            if status == "cleared":
                members = connection.execute("SELECT m.*, p.id AS database_id, p.player_id AS stable_player_id, p.spirit_stones, p.inventory_json, p.intro_json FROM time_fort_members m JOIN players p ON p.id=m.player_id WHERE m.run_id=? ORDER BY m.member_order", (run["run_id"],)).fetchall()
                rewards: dict[str, dict[str, int]] = {}
                first_clear_members: list[str] = []
                for member in members:
                    stable_id = str(member["stable_player_id"])
                    first = bool(member["first_clear"])
                    reward = dict(TIME_FORT_FIRST_REWARD if first else TIME_FORT_REPEAT_REWARD)
                    intro = self._json_object(member["intro_json"], {})
                    flags = list(intro.get("flags", []))
                    if first:
                        first_clear_members.append(stable_id)
                        if TIME_FORT_STORY_FLAG not in flags:
                            flags.append(TIME_FORT_STORY_FLAG)
                    intro["flags"] = flags
                    grant_player_assets(
                        connection,
                        member,
                        reward,
                        now_text,
                        player_values={"intro_json": json.dumps(intro, ensure_ascii=False, sort_keys=True)},
                    )
                    rewards[stable_id] = reward
                    connection.execute("UPDATE time_fort_members SET status='settled', reward_json=?, updated_at=? WHERE run_id=? AND player_id=?", (json.dumps(reward, ensure_ascii=False, sort_keys=True), now_text, run["run_id"], member["player_id"]))
                result = {"outcome": "won", "rewards": rewards, "first_clear_members": first_clear_members}
                connection.execute("UPDATE time_fort_runs SET status='settled', result_json=?, updated_at=? WHERE run_id=? AND status='cleared'", (json.dumps(result, ensure_ascii=False, sort_keys=True), now_text, run["run_id"]))
            elif status in {"failed", "expired", "settled", "system_aborted"}:
                result.setdefault("outcome", "lost" if status == "failed" else "expired" if status == "expired" else result.get("outcome"))
            else:
                raise TimeFortNotReadyError("complete all route nodes and automatic battle before settlement")
            settled = connection.execute("SELECT * FROM time_fort_runs WHERE run_id=?", (run["run_id"],)).fetchone()
            payload = self._time_fort_payload(settled, snapshot, result)
            self._time_fort_store_operation(connection, operation_id, operation_name, int(actor["id"]), request_hash, payload, now_text)
            return self._time_fort_record(payload)

    @staticmethod
    def _time_fort_latest_id(connection, player_id: int):
        row = connection.execute("SELECT r.run_id FROM time_fort_runs r JOIN time_fort_members m ON m.run_id=r.run_id WHERE m.player_id=? ORDER BY r.id DESC LIMIT 1", (player_id,)).fetchone()
        return row["run_id"] if row else ""

    def _time_fort_record_battle_outcome(self, run_id: str, outcome: str | None):
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            run = connection.execute("SELECT * FROM time_fort_runs WHERE run_id=?", (run_id,)).fetchone()
            if run is None:
                raise TimeFortNotFoundError("time-fort run no longer exists")
            if str(run["status"]) != "combat_pending":
                return self._time_fort_record_from_row(connection, run)
            snapshot = self._time_fort_json(run["snapshot_json"])
            if outcome == "won" and now_text < str(run["expires_at"]):
                index = int(run["node_index"]) + 1
                snapshot["current_node"] = TIME_FORT_NODES[index] if index < len(TIME_FORT_NODES) else None
                connection.execute("UPDATE time_fort_runs SET status='routing', node_index=?, battle_id=NULL, snapshot_json=?, result_json=?, updated_at=? WHERE run_id=?", (index, json.dumps(snapshot, ensure_ascii=False, sort_keys=True), json.dumps({"last_battle_outcome": "won"}), now_text, run_id))
            else:
                status = "expired" if now_text >= str(run["expires_at"]) or outcome == "expired" else "failed"
                snapshot["current_node"] = TIME_FORT_NODES[int(run["node_index"])]
                result = {"outcome": "expired" if status == "expired" else "lost", "reason": "battle_" + str(outcome)}
                connection.execute("UPDATE time_fort_members SET status=?, updated_at=? WHERE run_id=? AND status='active'", (status, now_text, run_id))
                connection.execute("UPDATE time_fort_runs SET status=?, battle_id=NULL, snapshot_json=?, result_json=?, updated_at=? WHERE run_id=?", (status, json.dumps(snapshot, ensure_ascii=False, sort_keys=True), json.dumps(result), now_text, run_id))
            return self._time_fort_record_from_row(connection, run_id)

    async def _time_fort_end_expired_battle(self, record: TimeFortRunRecord) -> None:
        if not record.battle_id:
            return
        with self._connect() as connection:
            session = connection.execute("SELECT status FROM party_battle_sessions WHERE battle_id=?", (record.battle_id,)).fetchone()
        if session is None or str(session["status"]) == "settled":
            return
        access = await asyncio.to_thread(self._time_fort_battle_actor, record.battle_id)
        if access:
            await self.settle_party_battle(platform=access[0], platform_user_id=access[1], battle_id=record.battle_id, operation_id=f"time_fort.expire.battle:{record.run_id}")

    def _time_fort_battle_actor(self, battle_id):
        with self._connect() as connection:
            row = connection.execute("SELECT p.platform, p.platform_user_id FROM party_battle_members m JOIN players p ON p.id=m.player_id WHERE m.battle_id=? ORDER BY m.id LIMIT 1", (battle_id,)).fetchone()
            return (str(row["platform"]), str(row["platform_user_id"])) if row else None

    def _time_fort_expire_by_id(self, run_id):
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            run = connection.execute("SELECT * FROM time_fort_runs WHERE run_id=?", (run_id,)).fetchone()
            if run is None:
                raise TimeFortNotFoundError("time-fort run does not exist")
            if str(run["status"]) in ACTIVE_TIME_FORT_STATUSES:
                self._time_fort_expire(connection, run, now_text)
            return self._time_fort_record_from_row(connection, run_id)

    @staticmethod
    def _time_fort_expire(connection, run, now_text):
        connection.execute("UPDATE time_fort_runs SET status='expired', result_json=?, updated_at=? WHERE run_id=? AND status IN ('routing','combat_pending','cleared')", (json.dumps({"outcome": "expired", "reason": "run_timeout"}), now_text, run["run_id"]))
        connection.execute("UPDATE time_fort_members SET status='expired', updated_at=? WHERE run_id=? AND status='active'", (now_text, run["run_id"]))

    async def compensate_time_fort_system_failure(self, *, run_id: str) -> TimeFortRunRecord:
        await self.initialize()
        return await asyncio.to_thread(self._time_fort_compensate_sync, run_id)

    def _time_fort_compensate_sync(self, run_id):
        now_text = serialize_datetime(self._now())
        operation_id = f"time_fort.system_abort:{run_id}"
        request_hash = self._request_hash("time_fort.system_abort", {"run_id": run_id})
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            run = connection.execute("SELECT * FROM time_fort_runs WHERE run_id=?", (run_id,)).fetchone()
            if run is None:
                raise TimeFortNotFoundError("time-fort run does not exist")
            if str(run["status"]) == "system_aborted":
                replay = self._time_fort_operation(connection, operation_id, "time_fort.system_abort", request_hash)
                if replay is not None:
                    replay["already_completed"] = True
                    return self._time_fort_record(replay, replay=True)
                return self._time_fort_record_from_row(connection, run)
            if str(run["status"]) not in ACTIVE_TIME_FORT_STATUSES:
                raise TimeFortNotReadyError("only an active time-fort run can be compensated")
            party = connection.execute("SELECT leader_id, current_session_id FROM parties WHERE party_id=?", (run["party_id"],)).fetchone()
            if party is None:
                raise TimeFortNotFoundError("time-fort party no longer exists")
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
                connection.execute("UPDATE party_battle_sessions SET status='settled', result_json=?, updated_at=? WHERE battle_id=? AND status IN ('created','running','won','lost','expired')", (json.dumps({"outcome": "system_aborted", "reason": "instance_compensated"}), now_text, battle_id))
                connection.execute("UPDATE party_battle_members SET asset_lock_status='released', settled_at=?, updated_at=? WHERE battle_id=? AND asset_lock_status='locked'", (now_text, now_text, battle_id))
                connection.execute("UPDATE parties SET current_session_id=NULL, updated_at=? WHERE party_id=? AND current_session_id=?", (now_text, run["party_id"], battle_id))
            connection.execute("UPDATE time_fort_members SET status='system_aborted', quota_key='released:'||?||':'||player_id, updated_at=? WHERE run_id=? AND status='active'", (run_id, now_text, run_id))
            result = {"outcome": "system_aborted", "reason": "system_compensation"}
            connection.execute("UPDATE time_fort_runs SET status='system_aborted', battle_id=NULL, result_json=?, updated_at=? WHERE run_id=?", (json.dumps(result), now_text, run_id))
            updated = connection.execute("SELECT * FROM time_fort_runs WHERE run_id=?", (run_id,)).fetchone()
            payload = self._time_fort_payload(updated, self._time_fort_json(updated["snapshot_json"]), result)
            self._time_fort_store_operation(connection, operation_id, "time_fort.system_abort", int(party["leader_id"]), request_hash, payload, now_text)
            return self._time_fort_record(payload)

    async def has_active_time_fort(self, *, platform: str, platform_user_id: str) -> bool:
        await self.initialize()
        return await asyncio.to_thread(self._has_active_time_fort_sync, platform, platform_user_id)

    def _has_active_time_fort_sync(self, platform, platform_user_id):
        with self._connect() as connection:
            actor = self._require_player(connection, platform, platform_user_id, writable=False)
            return self._time_fort_active_for_actor(connection, int(actor["id"])) is not None

    async def has_latest_time_fort(self, *, platform: str, platform_user_id: str) -> bool:
        await self.initialize()
        return await asyncio.to_thread(self._has_latest_time_fort_sync, platform, platform_user_id)

    def _has_latest_time_fort_sync(self, platform, platform_user_id):
        with self._connect() as connection:
            actor = self._require_player(connection, platform, platform_user_id, writable=False)
            return connection.execute(
                "SELECT 1 FROM time_fort_runs r JOIN time_fort_members m ON m.run_id=r.run_id "
                "WHERE m.player_id=? ORDER BY r.id DESC LIMIT 1",
                (actor["id"],),
            ).fetchone() is not None

    async def has_time_fort_settlement_operation(self, operation_id: str) -> bool:
        await self.initialize()
        return await asyncio.to_thread(self._has_time_fort_settlement_operation_sync, operation_id)

    def _has_time_fort_settlement_operation_sync(self, operation_id):
        with self._connect() as connection:
            return connection.execute("SELECT 1 FROM operations WHERE operation_id=? AND operation_name='time_fort.settle'", (operation_id,)).fetchone() is not None

    @staticmethod
    def _time_fort_active_for_actor(connection, player_id: int):
        return connection.execute("SELECT r.* FROM time_fort_runs r JOIN time_fort_members m ON m.run_id=r.run_id WHERE m.player_id=? AND m.status='active' AND r.status IN ('routing','combat_pending','cleared') ORDER BY r.id DESC LIMIT 1", (player_id,)).fetchone()


__all__ = ["TimeFortRepositoryMixin"]
