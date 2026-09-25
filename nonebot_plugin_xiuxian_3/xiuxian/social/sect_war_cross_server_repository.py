"""Persistence for the complete v0.5 cross-server sect-war slice.

The repository intentionally keeps federation sessions local and auditable. A
remote shard may be represented by the frozen ``shard_key`` in the existing
federation tables, but this feature never merges identities or moves assets
between shards.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from typing import Any, Mapping
from uuid import uuid4

from ...contracts import serialize_datetime
from ..persistence.errors import (
    CrossServerBranchLockedError,
    CrossServerFortressBuildError,
    CrossServerFortressRequiredError,
    CrossServerRegistrationCapError,
    CrossServerRegistrationClosedError,
    CrossServerRewardAllocationError,
    CrossServerRewardNotAvailableError,
    CrossServerRosterCapError,
    CrossServerSourceInvalidError,
    CrossServerWarNotActiveError,
    OperationConflictError,
    SectNotFoundError,
    SectPermissionDeniedError,
    SectWarRequirementError,
)
from .sect_war_cross_server_models import (
    CrossServerFortressRecord,
    CrossServerRewardRecord,
    CrossServerStanding,
    CrossServerWarRecord,
)
from .sect_war_cross_server_rules import (
    CROSS_SERVER_CLAIM_SECONDS,
    CROSS_SERVER_CONTENT_VERSION,
    CROSS_SERVER_ENGINE_HP,
    CROSS_SERVER_FORTRESS_ANCHOR_COST,
    CROSS_SERVER_FORTRESS_BUILD_COST,
    CROSS_SERVER_FORTRESS_BUILD_SECONDS,
    CROSS_SERVER_FORTRESS_MAINTENANCE_ANCHOR_COST,
    CROSS_SERVER_MEMBER_MERIT,
    CROSS_SERVER_MIN_SECT_LEVEL,
    CROSS_SERVER_REGISTRATION_CAP,
    CROSS_SERVER_REGISTRATION_FEE,
    CROSS_SERVER_ROSTER_CAP,
    CROSS_SERVER_RULE_VERSION,
    CROSS_SERVER_SCORE_BY_ACTION,
    CROSS_SERVER_WAR_SECONDS,
    CrossServerRoundWindow,
    cross_server_round_for_id,
    current_cross_server_round,
    top_reward_for_rank,
)


class SectWarCrossServerRepositoryMixin:
    """Own fortress, registration, automatic battle and reward-box writes."""

    async def get_cross_server_sect_war(self, *, platform: str, platform_user_id: str, round_id: str | None = None) -> CrossServerWarRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._cross_get_once, platform, platform_user_id, round_id)

    async def get_void_fortress(self, *, platform: str, platform_user_id: str) -> CrossServerFortressRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._cross_get_fortress_once, platform, platform_user_id)

    async def build_void_fortress(self, *, platform: str, platform_user_id: str, operation_id: str) -> CrossServerFortressRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._cross_build_fortress_once, platform, platform_user_id, operation_id)

    async def maintain_void_fortress(self, *, platform: str, platform_user_id: str, operation_id: str) -> CrossServerFortressRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._cross_maintain_fortress_once, platform, platform_user_id, operation_id)

    async def register_cross_server_sect_war(self, *, platform: str, platform_user_id: str, round_id: str | None, operation_id: str) -> CrossServerWarRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._cross_register_once, platform, platform_user_id, round_id, operation_id)

    async def choose_cross_server_war_branch(self, *, platform: str, platform_user_id: str, branch_key: str, round_id: str | None, operation_id: str) -> CrossServerWarRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._cross_branch_once, platform, platform_user_id, branch_key, round_id, operation_id)

    async def record_cross_server_war_score(self, *, platform: str, platform_user_id: str, action_key: str, target_key: str, source_operation_id: str, round_id: str | None, operation_id: str) -> CrossServerWarRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._cross_score_once, platform, platform_user_id, action_key, target_key, source_operation_id, round_id, operation_id)

    async def claim_cross_server_sect_war_reward(self, *, platform: str, platform_user_id: str, round_id: str, operation_id: str) -> CrossServerRewardRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._cross_claim_once, platform, platform_user_id, round_id, operation_id)

    async def allocate_cross_server_reward(self, *, platform: str, platform_user_id: str, round_id: str, target_platform: str, target_platform_user_id: str, quantity: int, operation_id: str) -> CrossServerRewardRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._cross_allocate_once, platform, platform_user_id, round_id, target_platform, target_platform_user_id, quantity, operation_id)

    async def advance_cross_server_sect_war(self, *, round_id: str | None = None) -> CrossServerWarRecord:
        """Advance server-owned turns for operational recovery jobs."""

        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._cross_advance_once, round_id)

    # Stable aliases keep the domain wording discoverable without duplicating
    # transaction code in the composition root.
    build_sect_void_fortress = build_void_fortress
    get_sect_war_cross_server = get_cross_server_sect_war
    maintain_sect_void_fortress = maintain_void_fortress
    register_sect_war_cross_server = register_cross_server_sect_war
    choose_sect_war_fortress_branch = choose_cross_server_war_branch
    contribute_sect_war_cross_server = record_cross_server_war_score
    claim_sect_war_cross_server_reward = claim_cross_server_sect_war_reward
    allocate_sect_war_cross_server_reward = allocate_cross_server_reward

    def _cross_get_once(self, platform: str, platform_user_id: str, requested_id: str | None) -> CrossServerWarRecord:
        now = self._now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            player = self._require_player(connection, platform, platform_user_id, writable=False)
            window, row = self._cross_prepare_round(connection, requested_id, now)
            self._cross_settle_if_due(connection, window, row, now)
            row = connection.execute("SELECT * FROM sect_cross_server_war_rounds WHERE round_id=?", (window.round_id,)).fetchone()
            return self._cross_record(connection, row, int(player["id"]))

    def _cross_get_fortress_once(self, platform: str, platform_user_id: str) -> CrossServerFortressRecord:
        now = self._now(); now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            player = self._require_player(connection, platform, platform_user_id, writable=False)
            membership = connection.execute("SELECT sect_id FROM sect_members WHERE player_id=? AND status='active'", (player["id"],)).fetchone()
            if membership is None:
                raise SectNotFoundError("player is not in a sect")
            fortress = connection.execute("SELECT * FROM sect_void_fortresses WHERE sect_id=?", (membership["sect_id"],)).fetchone()
            if fortress is None:
                raise CrossServerFortressRequiredError("void fortress is missing")
            self._cross_prepare_fortress(connection, fortress, now, now_text)
            fortress = connection.execute("SELECT * FROM sect_void_fortresses WHERE sect_id=?", (membership["sect_id"],)).fetchone()
            payload = self._fortress_payload(fortress)
            if payload["status"] == "active" and payload["maintenance_due_at"] and now >= datetime.fromisoformat(str(payload["maintenance_due_at"])):
                payload["status"] = "inactive"
            return self._fortress_from_payload(payload)

    def _cross_build_fortress_once(self, platform: str, platform_user_id: str, operation_id: str) -> CrossServerFortressRecord:
        operation_name = "social.sect_war_cross_server.build_fortress"
        request_hash = self._request_hash(operation_name, {"platform": platform, "platform_user_id": platform_user_id})
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._cross_operation(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                return self._fortress_from_payload(replay, already_completed=True)
            player = self._require_player(connection, platform, platform_user_id)
            sect, membership = self._cross_require_manager(connection, int(player["id"]))
            if int(sect["level"]) < CROSS_SERVER_MIN_SECT_LEVEL:
                raise SectWarRequirementError("void fortress requires sect level five")
            existing = connection.execute("SELECT * FROM sect_void_fortresses WHERE sect_id=?", (sect["sect_id"],)).fetchone()
            if existing is not None and str(existing["status"]) in {"building", "active"}:
                self._cross_prepare_fortress(connection, existing, now, now_text)
                existing = connection.execute("SELECT * FROM sect_void_fortresses WHERE sect_id=?", (sect["sect_id"],)).fetchone()
                if str(existing["status"]) in {"building", "active"}:
                    raise CrossServerFortressBuildError("void fortress already exists")
            warehouse = self._json_map(sect["warehouse_json"])
            if int(warehouse.get("item.void_anchor", 0)) < CROSS_SERVER_FORTRESS_ANCHOR_COST:
                raise CrossServerFortressBuildError("void anchor is insufficient")
            if int(sect["spirit_stones"]) < CROSS_SERVER_FORTRESS_BUILD_COST:
                raise CrossServerFortressBuildError("sect public wallet is insufficient")
            warehouse["item.void_anchor"] = int(warehouse.get("item.void_anchor", 0)) - CROSS_SERVER_FORTRESS_ANCHOR_COST
            build_end = now + timedelta(seconds=CROSS_SERVER_FORTRESS_BUILD_SECONDS)
            connection.execute("UPDATE sects SET spirit_stones=spirit_stones-?, warehouse_json=?, updated_at=? WHERE sect_id=?", (CROSS_SERVER_FORTRESS_BUILD_COST, json.dumps(warehouse, sort_keys=True), now_text, sect["sect_id"]))
            snapshot_json = json.dumps({"sect_level": int(sect["level"]), "anchor_cost": CROSS_SERVER_FORTRESS_ANCHOR_COST, "wallet_cost": CROSS_SERVER_FORTRESS_BUILD_COST}, sort_keys=True)
            if existing is None:
                connection.execute(
                    "INSERT INTO sect_void_fortresses(sect_id,status,anchor_balance,build_operation_id,build_ends_at,maintenance_due_at,snapshot_json,content_version,rule_version,created_at,updated_at) VALUES (?, 'building', ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (sect["sect_id"], CROSS_SERVER_FORTRESS_ANCHOR_COST, operation_id, serialize_datetime(build_end), serialize_datetime(build_end + timedelta(days=7)), snapshot_json, CROSS_SERVER_CONTENT_VERSION, CROSS_SERVER_RULE_VERSION, now_text, now_text),
                )
            else:
                connection.execute(
                    "UPDATE sect_void_fortresses SET status='building', anchor_balance=?, build_operation_id=?, build_ends_at=?, maintenance_due_at=?, snapshot_json=?, content_version=?, rule_version=?, updated_at=? WHERE sect_id=?",
                    (CROSS_SERVER_FORTRESS_ANCHOR_COST, operation_id, serialize_datetime(build_end), serialize_datetime(build_end + timedelta(days=7)), snapshot_json, CROSS_SERVER_CONTENT_VERSION, CROSS_SERVER_RULE_VERSION, now_text, sect["sect_id"]),
                )
            payload = {"sect_id": str(sect["sect_id"]), "status": "building", "anchors": CROSS_SERVER_FORTRESS_ANCHOR_COST, "build_ends_at": serialize_datetime(build_end), "maintenance_due_at": serialize_datetime(build_end + timedelta(days=7))}
            self._cross_insert_operation(connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text)
            return self._fortress_from_payload(payload)

    def _cross_maintain_fortress_once(self, platform: str, platform_user_id: str, operation_id: str) -> CrossServerFortressRecord:
        operation_name = "social.sect_war_cross_server.maintain_fortress"
        request_hash = self._request_hash(operation_name, {"platform": platform, "platform_user_id": platform_user_id})
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._cross_operation(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                return self._fortress_from_payload(replay, already_completed=True)
            player = self._require_player(connection, platform, platform_user_id)
            sect, _ = self._cross_require_manager(connection, int(player["id"]))
            fortress = connection.execute("SELECT * FROM sect_void_fortresses WHERE sect_id=?", (sect["sect_id"],)).fetchone()
            if fortress is None:
                raise CrossServerFortressRequiredError("void fortress is missing")
            self._cross_prepare_fortress(connection, fortress, now, now_text)
            fortress = connection.execute("SELECT * FROM sect_void_fortresses WHERE sect_id=?", (sect["sect_id"],)).fetchone()
            if str(fortress["status"]) != "active":
                raise CrossServerFortressBuildError("void fortress is not active")
            due = fortress["maintenance_due_at"] and now >= datetime.fromisoformat(str(fortress["maintenance_due_at"]))
            if not due:
                payload = self._fortress_payload(fortress)
                self._cross_insert_operation(connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text)
                return self._fortress_from_payload(payload, already_completed=True)
            warehouse = self._json_map(sect["warehouse_json"])
            if int(warehouse.get("item.void_anchor", 0)) < CROSS_SERVER_FORTRESS_MAINTENANCE_ANCHOR_COST:
                connection.execute("UPDATE sect_void_fortresses SET status='inactive', updated_at=? WHERE sect_id=?", (now_text, sect["sect_id"]))
                raise CrossServerFortressBuildError("void fortress maintenance anchor is insufficient")
            warehouse["item.void_anchor"] = int(warehouse.get("item.void_anchor", 0)) - CROSS_SERVER_FORTRESS_MAINTENANCE_ANCHOR_COST
            due_at = now + timedelta(days=7)
            connection.execute("UPDATE sects SET warehouse_json=?, updated_at=? WHERE sect_id=?", (json.dumps(warehouse, sort_keys=True), now_text, sect["sect_id"]))
            connection.execute("UPDATE sect_void_fortresses SET status='active', maintenance_due_at=?, updated_at=? WHERE sect_id=?", (serialize_datetime(due_at), now_text, sect["sect_id"]))
            fortress = connection.execute("SELECT * FROM sect_void_fortresses WHERE sect_id=?", (sect["sect_id"],)).fetchone()
            payload = self._fortress_payload(fortress)
            self._cross_insert_operation(connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text)
            return self._fortress_from_payload(payload)

    def _cross_register_once(self, platform: str, platform_user_id: str, requested_id: str | None, operation_id: str) -> CrossServerWarRecord:
        operation_name = "social.sect_war_cross_server.register"
        request_hash = self._request_hash(operation_name, {"platform": platform, "platform_user_id": platform_user_id, "round_id": requested_id or ""})
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._cross_operation(connection, operation_id, operation_name, request_hash)
            player = self._require_player(connection, platform, platform_user_id)
            window, round_row = self._cross_prepare_round(connection, requested_id, now)
            if replay is not None:
                return self._cross_record(connection, round_row, int(player["id"]), already_completed=True)
            if now >= window.starts_at:
                raise CrossServerRegistrationClosedError("cross-server registration is closed")
            sect, _ = self._cross_require_manager(connection, int(player["id"]))
            fortress = connection.execute("SELECT * FROM sect_void_fortresses WHERE sect_id=?", (sect["sect_id"],)).fetchone()
            if fortress is None:
                raise CrossServerFortressRequiredError("active void fortress is required")
            self._cross_prepare_fortress(connection, fortress, now, now_text)
            fortress = connection.execute("SELECT * FROM sect_void_fortresses WHERE sect_id=?", (sect["sect_id"],)).fetchone()
            if str(fortress["status"]) != "active":
                raise CrossServerFortressRequiredError("active void fortress is required")
            if fortress["maintenance_due_at"] and now >= datetime.fromisoformat(str(fortress["maintenance_due_at"])):
                raise CrossServerFortressRequiredError("void fortress maintenance is due")
            if int(sect["level"]) < CROSS_SERVER_MIN_SECT_LEVEL:
                raise SectWarRequirementError("sect level is too low")
            existing = connection.execute("SELECT 1 FROM sect_cross_server_war_registrations WHERE round_id=? AND sect_id=?", (window.round_id, sect["sect_id"])).fetchone()
            if existing is not None:
                raise SectWarRequirementError("sect is already registered")
            count = int(connection.execute("SELECT COUNT(*) FROM sect_cross_server_war_registrations WHERE round_id=? AND status='registered'", (window.round_id,)).fetchone()[0])
            if count >= CROSS_SERVER_REGISTRATION_CAP:
                raise CrossServerRegistrationCapError("cross-server registration cap reached")
            members = connection.execute("SELECT p.* FROM sect_members m JOIN players p ON p.id=m.player_id WHERE m.sect_id=? AND m.status='active' ORDER BY m.contribution DESC, m.id ASC LIMIT ?", (sect["sect_id"], CROSS_SERVER_ROSTER_CAP)).fetchall()
            if not members or len(members) > CROSS_SERVER_ROSTER_CAP:
                raise CrossServerRosterCapError("cross-server roster is empty or too large")
            if int(sect["spirit_stones"]) < CROSS_SERVER_REGISTRATION_FEE:
                raise SectWarRequirementError("cross-server registration fee is insufficient")
            roster = []
            for slot, member in enumerate(members, 1):
                roster.append({"player_id": int(member["id"]), "platform": str(member["platform"]), "platform_user_id": str(member["platform_user_id"]), "void_power": int(member["void_power"]), "void_anchor_capacity": int(member["void_anchor_capacity"]), "space_resistance_bp": int(member["space_resistance_bp"]), "void_instability_until": member["void_instability_until"], "roster_slot": slot})
            snapshot = {"round_id": window.round_id, "week_id": window.week_id, "shard_key": "local", "sect_id": str(sect["sect_id"]), "sect_name": str(sect["name"]), "level": int(sect["level"]), "members": roster, "enemy_pool": ["enemy.sect_war_engine"], "rule_version": CROSS_SERVER_RULE_VERSION, "content_version": CROSS_SERVER_CONTENT_VERSION}
            connection.execute("UPDATE sects SET spirit_stones=spirit_stones-?, updated_at=? WHERE sect_id=?", (CROSS_SERVER_REGISTRATION_FEE, now_text, sect["sect_id"]))
            connection.execute("INSERT INTO sect_cross_server_war_registrations(round_id,sect_id,operation_id,entry_fee,status,roster_size,score,snapshot_json,registered_at) VALUES (?, ?, ?, ?, 'registered', ?, 0, ?, ?)", (window.round_id, sect["sect_id"], operation_id, CROSS_SERVER_REGISTRATION_FEE, len(roster), json.dumps(snapshot, sort_keys=True), now_text))
            for member in roster:
                connection.execute("INSERT INTO sect_cross_server_war_members(round_id,sect_id,player_id,roster_slot,snapshot_json,created_at,updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)", (window.round_id, sect["sect_id"], member["player_id"], member["roster_slot"], json.dumps(member, sort_keys=True), now_text, now_text))
            session_id = f"sect-war-cross-session:{window.round_id}:{sect['sect_id']}"
            connection.execute("INSERT INTO sect_cross_server_war_sessions(session_id,round_id,sect_id,status,turn_no,engine_hp,branch_key,snapshot_json,replay_json,result_json,created_at,updated_at) VALUES (?, ?, ?, 'running', 0, ?, NULL, ?, '[]', '{}', ?, ?)", (session_id, window.round_id, sect["sect_id"], CROSS_SERVER_ENGINE_HP, json.dumps(snapshot, sort_keys=True), now_text, now_text))
            connection.execute("UPDATE sect_cross_server_war_rounds SET status='open', updated_at=? WHERE round_id=?", (now_text, window.round_id))
            self._cross_insert_operation(connection, operation_id, operation_name, int(player["id"]), request_hash, {"round_id": window.round_id, "sect_id": str(sect["sect_id"]), "roster_size": len(roster)}, now_text)
            round_row = connection.execute("SELECT * FROM sect_cross_server_war_rounds WHERE round_id=?", (window.round_id,)).fetchone()
            return self._cross_record(connection, round_row, int(player["id"]))

    def _cross_branch_once(self, platform: str, platform_user_id: str, branch_key: str, requested_id: str | None, operation_id: str) -> CrossServerWarRecord:
        if branch_key not in {"repair", "break"}:
            raise CrossServerBranchLockedError("branch must be repair or break")
        operation_name = "social.sect_war_cross_server.choose_branch"
        request_hash = self._request_hash(operation_name, {"platform": platform, "platform_user_id": platform_user_id, "branch_key": branch_key, "round_id": requested_id or ""})
        now = self._now(); now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._cross_operation(connection, operation_id, operation_name, request_hash)
            player = self._require_player(connection, platform, platform_user_id)
            window, row = self._cross_prepare_round(connection, requested_id, now)
            if replay is not None:
                return self._cross_record(connection, row, int(player["id"]), already_completed=True)
            registration = connection.execute("SELECT * FROM sect_cross_server_war_registrations r JOIN sect_cross_server_war_members m ON m.round_id=r.round_id AND m.sect_id=r.sect_id WHERE r.round_id=? AND m.player_id=?", (window.round_id, player["id"])).fetchone()
            if registration is None:
                raise CrossServerWarNotActiveError("player is not in the cross-server roster")
            session = connection.execute("SELECT * FROM sect_cross_server_war_sessions WHERE round_id=? AND sect_id=?", (window.round_id, registration["sect_id"])).fetchone()
            if session is None or str(session["status"]) != "running":
                raise CrossServerWarNotActiveError("automatic battle is not running")
            if session["branch_key"] and str(session["branch_key"]) != branch_key:
                raise CrossServerBranchLockedError("fortress branch is already locked")
            connection.execute("UPDATE sect_cross_server_war_sessions SET branch_key=?, updated_at=? WHERE session_id=?", (branch_key, now_text, session["session_id"]))
            self._cross_insert_operation(connection, operation_id, operation_name, int(player["id"]), request_hash, {"round_id": window.round_id, "branch_key": branch_key}, now_text)
            row = connection.execute("SELECT * FROM sect_cross_server_war_rounds WHERE round_id=?", (window.round_id,)).fetchone()
            return self._cross_record(connection, row, int(player["id"]))

    def _cross_score_once(self, platform: str, platform_user_id: str, action_key: str, target_key: str, source_operation_id: str, requested_id: str | None, operation_id: str) -> CrossServerWarRecord:
        if action_key not in CROSS_SERVER_SCORE_BY_ACTION or not source_operation_id.strip():
            raise CrossServerSourceInvalidError("invalid cross-server score source")
        operation_name = "social.sect_war_cross_server.score"
        request_hash = self._request_hash(operation_name, {"platform": platform, "platform_user_id": platform_user_id, "action_key": action_key, "target_key": target_key, "source_operation_id": source_operation_id, "round_id": requested_id or ""})
        now = self._now(); now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._cross_operation(connection, operation_id, operation_name, request_hash)
            player = self._require_player(connection, platform, platform_user_id)
            window, row = self._cross_prepare_round(connection, requested_id, now)
            if replay is not None:
                return self._cross_record(connection, row, int(player["id"]), already_completed=True)
            self._cross_settle_if_due(connection, window, row, now)
            row = connection.execute("SELECT * FROM sect_cross_server_war_rounds WHERE round_id=?", (window.round_id,)).fetchone()
            if str(row["status"]) != "running":
                raise CrossServerWarNotActiveError("cross-server war is not running")
            member = connection.execute("SELECT * FROM sect_cross_server_war_members WHERE round_id=? AND player_id=?", (window.round_id, player["id"])).fetchone()
            if member is None:
                raise CrossServerSourceInvalidError("player is not in the frozen roster")
            source = connection.execute("SELECT operation_id FROM operations WHERE operation_id=? AND player_id=?", (source_operation_id, player["id"])).fetchone()
            if source is None or connection.execute("SELECT 1 FROM sect_cross_server_war_actions WHERE source_operation_id=?", (source_operation_id,)).fetchone() is not None:
                raise CrossServerSourceInvalidError("source operation is unavailable")
            used = int(connection.execute("SELECT COUNT(*) FROM sect_cross_server_war_actions WHERE round_id=? AND sect_id=? AND target_key=?", (window.round_id, member["sect_id"], target_key)).fetchone()[0])
            if used >= 3:
                raise CrossServerSourceInvalidError("same target score limit reached")
            score = int(CROSS_SERVER_SCORE_BY_ACTION[action_key])
            connection.execute("INSERT INTO sect_cross_server_war_actions(action_id,round_id,sect_id,player_id,target_key,action_key,score,source_operation_id,operation_id,occurred_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (uuid4().hex, window.round_id, member["sect_id"], player["id"], target_key, action_key, score, source_operation_id, operation_id, now_text))
            connection.execute("UPDATE sect_cross_server_war_registrations SET score=score+? WHERE round_id=? AND sect_id=?", (score, window.round_id, member["sect_id"]))
            connection.execute("UPDATE sect_cross_server_war_members SET contribution=contribution+?, updated_at=? WHERE round_id=? AND player_id=?", (score, now_text, window.round_id, player["id"]))
            self._cross_insert_operation(connection, operation_id, operation_name, int(player["id"]), request_hash, {"round_id": window.round_id, "action_key": action_key, "target_key": target_key, "score": score, "source_operation_id": source_operation_id}, now_text)
            return self._cross_record(connection, row, int(player["id"]))

    def _cross_claim_once(self, platform: str, platform_user_id: str, requested_id: str, operation_id: str) -> CrossServerRewardRecord:
        operation_name = "social.sect_war_cross_server.claim"
        request_hash = self._request_hash(operation_name, {"platform": platform, "platform_user_id": platform_user_id, "round_id": requested_id})
        now = self._now(); now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._cross_operation(connection, operation_id, operation_name, request_hash)
            player = self._require_player(connection, platform, platform_user_id, writable=False)
            window, row = self._cross_prepare_round(connection, requested_id, now)
            if replay is not None:
                return self._reward_from_payload(replay, already_completed=True)
            self._cross_settle_if_due(connection, window, row, now)
            member = connection.execute("SELECT * FROM sect_cross_server_war_members WHERE round_id=? AND player_id=?", (window.round_id, player["id"])).fetchone()
            if member is None:
                raise CrossServerRewardNotAvailableError("player has no cross-server reward")
            pending = connection.execute("SELECT reward_json FROM sect_cross_server_weekly_rewards WHERE reward_key=?", (f"season.void_frontier.{window.week_id}:{player['id']}",)).fetchone()
            if pending is None:
                raise CrossServerRewardNotAvailableError("cross-server reward is not available")
            reward = self._json_map(pending["reward_json"])
            if reward.get("status") == "claimed":
                payload = {"round_id": window.round_id, "sect_id": str(member["sect_id"]), "reward": {"void_merit": CROSS_SERVER_MEMBER_MERIT}, "status": "claimed"}
                self._cross_insert_operation(connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text)
                return self._reward_from_payload(payload, already_completed=True)
            connection.execute("UPDATE players SET void_merit=void_merit+?, updated_at=? WHERE id=?", (CROSS_SERVER_MEMBER_MERIT, now_text, player["id"]))
            reward["status"] = "claimed"
            connection.execute("UPDATE sect_cross_server_weekly_rewards SET reward_json=? WHERE reward_key=?", (json.dumps(reward, sort_keys=True), f"season.void_frontier.{window.week_id}:{player['id']}"))
            payload = {"round_id": window.round_id, "sect_id": str(member["sect_id"]), "reward": {"void_merit": CROSS_SERVER_MEMBER_MERIT}, "status": "claimed"}
            self._cross_insert_operation(connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text)
            return self._reward_from_payload(payload)

    def _cross_allocate_once(self, platform: str, platform_user_id: str, requested_id: str, target_platform: str, target_platform_user_id: str, quantity: int, operation_id: str) -> CrossServerRewardRecord:
        if quantity <= 0:
            raise CrossServerRewardAllocationError("quantity must be positive")
        operation_name = "social.sect_war_cross_server.allocate_reward"
        request_hash = self._request_hash(operation_name, {"platform": platform, "platform_user_id": platform_user_id, "round_id": requested_id, "target_platform": target_platform, "target_platform_user_id": target_platform_user_id, "quantity": quantity})
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._cross_operation(connection, operation_id, operation_name, request_hash)
            actor = self._require_player(connection, platform, platform_user_id)
            target = self._require_player(connection, target_platform, target_platform_user_id, writable=False)
            window, row = self._cross_prepare_round(connection, requested_id, self._now())
            membership = connection.execute("SELECT role,sect_id FROM sect_members WHERE player_id=? AND status='active'", (actor["id"],)).fetchone()
            if membership is None or str(membership["role"]) not in {"leader", "vice_leader"}:
                raise SectPermissionDeniedError("only sect leader or vice leader can allocate rewards")
            sect_id = str(membership["sect_id"])
            box = connection.execute("SELECT * FROM sect_cross_server_reward_boxes WHERE round_id=? AND sect_id=?", (window.round_id, sect_id)).fetchone()
            member = connection.execute("SELECT 1 FROM sect_cross_server_war_members WHERE round_id=? AND sect_id=? AND player_id=?", (window.round_id, sect_id, target["id"])).fetchone()
            if box is None or member is None:
                raise CrossServerRewardAllocationError("reward box or target member is unavailable")
            reward = self._json_map(box["reward_json"]); distributed = self._json_map(box["distributed_json"])
            available = int(reward.get("item.void_crystal", 0)) - int(distributed.get("item.void_crystal", 0))
            if quantity > available:
                raise CrossServerRewardAllocationError("reward box quantity is insufficient")
            if replay is not None:
                return self._reward_from_payload(replay, already_completed=True)
            distributed["item.void_crystal"] = int(distributed.get("item.void_crystal", 0)) + quantity
            inventory = self._json_map(target["inventory_json"])
            inventory["item.void_crystal"] = int(inventory.get("item.void_crystal", 0)) + quantity
            connection.execute("UPDATE players SET inventory_json=?, updated_at=? WHERE id=?", (json.dumps(inventory, sort_keys=True), now_text, target["id"]))
            connection.execute("INSERT INTO sect_cross_server_reward_allocations(box_id,player_id,operation_id,item_key,quantity,allocated_at) VALUES (?, ?, ?, 'item.void_crystal', ?, ?)", (box["box_id"], target["id"], operation_id, quantity, now_text))
            status = "distributed" if int(distributed.get("item.void_crystal", 0)) >= int(reward.get("item.void_crystal", 0)) else "partial"
            connection.execute("UPDATE sect_cross_server_reward_boxes SET distributed_json=?, status=?, updated_at=? WHERE box_id=?", (json.dumps(distributed, sort_keys=True), status, now_text, box["box_id"]))
            payload = {"round_id": window.round_id, "sect_id": sect_id, "reward": {"item.void_crystal": quantity}, "status": status}
            self._cross_insert_operation(connection, operation_id, operation_name, int(actor["id"]), request_hash, payload, now_text)
            return self._reward_from_payload(payload)

    def _cross_advance_once(self, requested_id: str | None) -> CrossServerWarRecord:
        now = self._now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            window, row = self._cross_prepare_round(connection, requested_id, now)
            self._cross_settle_if_due(connection, window, row, now)
            row = connection.execute("SELECT * FROM sect_cross_server_war_rounds WHERE round_id=?", (window.round_id,)).fetchone()
            return self._cross_record(connection, row, None)

    def _cross_prepare_round(self, connection: Any, requested_id: str | None, now: datetime) -> tuple[CrossServerRoundWindow, Any]:
        window = current_cross_server_round(now) if not requested_id else cross_server_round_for_id(requested_id, now=now)
        now_text = serialize_datetime(now)
        row = connection.execute("SELECT * FROM sect_cross_server_war_rounds WHERE round_id=?", (window.round_id,)).fetchone()
        status = "open" if now < window.starts_at else "running" if now < window.ends_at else "settled"
        if row is None:
            connection.execute("INSERT INTO sect_cross_server_war_rounds(round_id,week_id,registration_open_at,starts_at,ends_at,claim_expires_at,status,snapshot_json,created_at,updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, '{}', ?, ?)", (window.round_id, window.week_id, serialize_datetime(window.registration_open_at), serialize_datetime(window.starts_at), serialize_datetime(window.ends_at), serialize_datetime(window.claim_expires_at), status, now_text, now_text))
            row = connection.execute("SELECT * FROM sect_cross_server_war_rounds WHERE round_id=?", (window.round_id,)).fetchone()
        elif str(row["status"]) in {"scheduled", "open"} and status in {"running", "settled"}:
            connection.execute("UPDATE sect_cross_server_war_rounds SET status=?, updated_at=? WHERE round_id=?", (status, now_text, window.round_id))
            row = connection.execute("SELECT * FROM sect_cross_server_war_rounds WHERE round_id=?", (window.round_id,)).fetchone()
        return window, row

    def _cross_settle_if_due(self, connection: Any, window: CrossServerRoundWindow, row: Any, now: datetime) -> None:
        if now < window.starts_at:
            return
        if str(row["status"]) == "settled":
            if now >= window.claim_expires_at:
                self._cross_auto_grant(connection, window, now)
            return
        if now < window.ends_at:
            self._cross_advance_sessions(connection, window, now)
            return
        self._cross_advance_sessions(connection, window, now)
        registrations = connection.execute("SELECT * FROM sect_cross_server_war_registrations WHERE round_id=? AND status='registered' ORDER BY score DESC, sect_id ASC", (window.round_id,)).fetchall()
        for rank, registration in enumerate(registrations, 1):
            winner = 1 if rank == 1 else 0
            connection.execute("UPDATE sect_cross_server_war_registrations SET rank=?, winner=?, settled_at=? WHERE id=?", (rank, winner, serialize_datetime(now), registration["id"]))
            crystal = top_reward_for_rank(rank)
            if crystal:
                box_id = f"sect-war-cross-box:{window.round_id}:{registration['sect_id']}"
                connection.execute("INSERT OR IGNORE INTO sect_cross_server_reward_boxes(box_id,round_id,sect_id,status,reward_json,distributed_json,created_at,updated_at) VALUES (?, ?, ?, 'pending', ?, '{}', ?, ?)", (box_id, window.round_id, registration["sect_id"], json.dumps({"item.void_crystal": crystal}, sort_keys=True), serialize_datetime(now), serialize_datetime(now)))
            members = connection.execute("SELECT player_id FROM sect_cross_server_war_members WHERE round_id=? AND sect_id=?", (window.round_id, registration["sect_id"])).fetchall()
            for member in members:
                reward_key = f"season.void_frontier.{window.week_id}:{member['player_id']}"
                connection.execute("INSERT OR IGNORE INTO sect_cross_server_weekly_rewards(reward_key,round_id,player_id,operation_id,reward_json,created_at) VALUES (?, ?, ?, ?, ?, ?)", (reward_key, window.round_id, member["player_id"], f"{reward_key}:pending", json.dumps({"void_merit": CROSS_SERVER_MEMBER_MERIT, "status": "pending"}, sort_keys=True), serialize_datetime(now)))
        connection.execute("UPDATE sect_cross_server_war_rounds SET status='settled', updated_at=? WHERE round_id=?", (serialize_datetime(now), window.round_id))
        if now >= window.claim_expires_at:
            self._cross_auto_grant(connection, window, now)

    def _cross_advance_sessions(self, connection: Any, window: CrossServerRoundWindow, now: datetime) -> None:
        now_text = serialize_datetime(now)
        sessions = connection.execute("SELECT * FROM sect_cross_server_war_sessions WHERE round_id=? AND status='running'", (window.round_id,)).fetchall()
        for session in sessions:
            hp = int(session["engine_hp"]); turn = int(session["turn_no"]); branch = session["branch_key"]
            roster_size = int(connection.execute("SELECT COUNT(*) FROM sect_cross_server_war_members WHERE round_id=? AND sect_id=?", (window.round_id, session["sect_id"])).fetchone()[0])
            replay = self._json_list(session["replay_json"])
            steps = 0
            while turn < 30 and hp > 0 and steps < 5:
                phase = "phase_30" if hp <= 15_000 else "phase_60" if hp <= 30_000 else "normal"
                if branch is None and phase != "normal":
                    break
                turn += 1; steps += 1
                damage = max(1_000, roster_size * 1_000)
                if branch == "repair" and hp <= 30_000:
                    hp = min(CROSS_SERVER_ENGINE_HP, hp + 5_000)
                    event = {"turn": turn, "phase": phase, "action": "repair", "hp": hp}
                else:
                    hp = max(0, hp - damage)
                    event = {"turn": turn, "phase": phase, "action": "break" if branch == "break" else "auto", "damage": damage, "hp": hp}
                replay.append(event)
            status = "settled" if hp <= 0 else "running"
            connection.execute("UPDATE sect_cross_server_war_sessions SET status=?,turn_no=?,engine_hp=?,replay_json=?,result_json=?,updated_at=? WHERE session_id=?", (status, turn, hp, json.dumps(replay, sort_keys=True), json.dumps({"victory": hp <= 0, "rule_version": CROSS_SERVER_RULE_VERSION}, sort_keys=True), now_text, session["session_id"]))

    def _cross_auto_grant(self, connection: Any, window: CrossServerRoundWindow, now: datetime) -> None:
        rows = connection.execute("SELECT reward_key,player_id,reward_json FROM sect_cross_server_weekly_rewards WHERE round_id=?", (window.round_id,)).fetchall()
        for row in rows:
            reward = self._json_map(row["reward_json"])
            if reward.get("status") == "claimed":
                continue
            connection.execute("UPDATE players SET void_merit=void_merit+?, updated_at=? WHERE id=?", (CROSS_SERVER_MEMBER_MERIT, serialize_datetime(now), row["player_id"]))
            reward["status"] = "claimed"
            connection.execute("UPDATE sect_cross_server_weekly_rewards SET reward_json=?, operation_id=? WHERE reward_key=?", (json.dumps(reward, sort_keys=True), f"{row['reward_key']}:auto", row["reward_key"]))

    def _cross_record(self, connection: Any, row: Any, player_id: int | None, *, already_completed: bool = False) -> CrossServerWarRecord:
        registration = None
        if player_id is not None:
            registration = connection.execute("SELECT r.*,s.name FROM sect_cross_server_war_registrations r JOIN sect_members m ON m.sect_id=r.sect_id AND m.player_id=? AND m.status='active' JOIN sects s ON s.sect_id=r.sect_id WHERE r.round_id=?", (player_id, row["round_id"])).fetchone()
        standings_rows = connection.execute("SELECT r.sect_id,s.name,r.score,r.rank,r.winner FROM sect_cross_server_war_registrations r JOIN sects s ON s.sect_id=r.sect_id WHERE r.round_id=? ORDER BY COALESCE(r.rank,999),r.score DESC,r.sect_id", (row["round_id"],)).fetchall()
        standings = tuple(CrossServerStanding(str(item["sect_id"]), str(item["name"]), int(item["score"]), int(item["rank"] or 0), bool(item["winner"])) for item in standings_rows)
        session = connection.execute("SELECT * FROM sect_cross_server_war_sessions WHERE round_id=? AND sect_id=?", (row["round_id"], registration["sect_id"])) .fetchone() if registration else None
        return CrossServerWarRecord(str(row["round_id"]), str(row["status"]), str(row["registration_open_at"]), str(row["starts_at"]), str(row["ends_at"]), str(row["claim_expires_at"]), registration is not None, str(registration["sect_id"]) if registration else None, str(registration["name"]) if registration else None, int(registration["roster_size"]) if registration else 0, int(registration["score"]) if registration else 0, str(session["status"]) if session else None, int(session["engine_hp"]) if session else None, str(session["branch_key"]) if session and session["branch_key"] else None, standings, already_completed)

    @staticmethod
    def _cross_require_manager(connection: Any, player_id: int):
        membership = connection.execute("SELECT * FROM sect_members WHERE player_id=? AND status='active'", (player_id,)).fetchone()
        if membership is None:
            raise SectNotFoundError("player is not in a sect")
        if str(membership["role"]) not in {"leader", "vice_leader"}:
            raise SectPermissionDeniedError("sect leader or vice leader is required")
        sect = connection.execute("SELECT * FROM sects WHERE sect_id=? AND status='active'", (membership["sect_id"],)).fetchone()
        if sect is None:
            raise SectNotFoundError("sect does not exist")
        return sect, membership

    @staticmethod
    def _cross_prepare_fortress(connection: Any, fortress: Any, now: datetime, now_text: str) -> None:
        if str(fortress["status"]) == "building" and fortress["build_ends_at"] and now >= datetime.fromisoformat(str(fortress["build_ends_at"])):
            connection.execute("UPDATE sect_void_fortresses SET status='active', updated_at=? WHERE sect_id=?", (now_text, fortress["sect_id"]))
        # Maintenance expiry is checked by registration/maintenance writes; a
        # read should not destroy the opportunity to pay the due cost.

    @staticmethod
    def _cross_operation(connection: Any, operation_id: str, operation_name: str, request_hash: str) -> dict[str, Any] | None:
        existing = connection.execute("SELECT operation_name,request_hash,result_json FROM operations WHERE operation_id=?", (operation_id,)).fetchone()
        if existing is None:
            return None
        if str(existing["operation_name"]) != operation_name or str(existing["request_hash"]) != request_hash:
            raise OperationConflictError("operation input differs from its original request")
        return json.loads(existing["result_json"])

    @staticmethod
    def _cross_insert_operation(connection: Any, operation_id: str, operation_name: str, player_id: int, request_hash: str, payload: Mapping[str, object], now_text: str) -> None:
        connection.execute("INSERT INTO operations(operation_id,operation_name,player_id,request_hash,result_json,created_at) VALUES (?, ?, ?, ?, ?, ?)", (operation_id, operation_name, player_id, request_hash, json.dumps(dict(payload), ensure_ascii=False, sort_keys=True), now_text))

    @staticmethod
    def _json_map(value: object) -> dict[str, Any]:
        try:
            result = json.loads(value) if isinstance(value, str) else value
        except (TypeError, ValueError):
            result = {}
        return dict(result) if isinstance(result, dict) else {}

    @classmethod
    def _json_list(cls, value: object) -> list[dict[str, Any]]:
        try:
            result = json.loads(value) if isinstance(value, str) else value
        except (TypeError, ValueError):
            result = []
        return [dict(item) for item in result if isinstance(item, dict)] if isinstance(result, list) else []

    @staticmethod
    def _fortress_payload(row: Any) -> dict[str, object]:
        return {"sect_id": str(row["sect_id"]), "status": str(row["status"]), "anchors": int(row["anchor_balance"]), "build_ends_at": row["build_ends_at"], "maintenance_due_at": row["maintenance_due_at"]}

    @staticmethod
    def _fortress_from_payload(payload: Mapping[str, object], *, already_completed: bool = False) -> CrossServerFortressRecord:
        return CrossServerFortressRecord(str(payload["sect_id"]), str(payload["status"]), int(payload.get("anchors", 0)), payload.get("build_ends_at") and str(payload["build_ends_at"]), payload.get("maintenance_due_at") and str(payload["maintenance_due_at"]), already_completed)

    @staticmethod
    def _reward_from_payload(payload: Mapping[str, object], *, already_completed: bool = False) -> CrossServerRewardRecord:
        return CrossServerRewardRecord(str(payload["round_id"]), str(payload["sect_id"]), {str(k): int(v) for k, v in dict(payload.get("reward", {})).items()}, str(payload["status"]), already_completed)


__all__ = ["SectWarCrossServerRepositoryMixin"]
