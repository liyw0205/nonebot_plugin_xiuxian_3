"""SQLite transactions for v0.5 production alliance contracts."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from typing import Any, Mapping
from uuid import uuid4

from ...contracts import serialize_datetime
from ..persistence.errors import (
    AllianceBreachFeeError,
    AllianceConfirmationExpiredError,
    AllianceNotFoundError,
    AllianceResearchWeeklyCapError,
    AllianceRequirementError,
    OperationConflictError,
    SectAllianceCooldownError,
    SectNotFoundError,
    SectPermissionDeniedError,
)
from .sect_alliance_models import AllianceResearchRecord, SectAllianceRecord
from .sect_alliance_rules import (
    ALLIANCE_BREACH_FEE,
    ALLIANCE_CONFIRMATION_SECONDS,
    ALLIANCE_CONTENT_VERSION,
    ALLIANCE_DURATION_SECONDS,
    ALLIANCE_MIN_SECT_LEVEL,
    ALLIANCE_RESEARCH_WEEKLY_CAP,
    ALLIANCE_RULE_VERSION,
    SECT_ALLIANCE_COOLDOWN_SECONDS,
    alliance_week_id,
)


class SectAllianceRepositoryMixin:
    """Own alliance contract state and recipe-marker synchronization."""

    async def create_sect_alliance(self, *, platform: str, platform_user_id: str, partner_ref: str, operation_id: str) -> SectAllianceRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._create_sect_alliance_once, platform, platform_user_id, partner_ref, operation_id)

    async def confirm_sect_alliance(self, *, platform: str, platform_user_id: str, alliance_id: str, operation_id: str) -> SectAllianceRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._confirm_sect_alliance_once, platform, platform_user_id, alliance_id, operation_id)

    async def get_sect_alliance(self, *, platform: str, platform_user_id: str, alliance_id: str | None = None) -> SectAllianceRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._get_sect_alliance_once, platform, platform_user_id, alliance_id)

    async def end_sect_alliance(self, *, platform: str, platform_user_id: str, alliance_id: str, operation_id: str) -> SectAllianceRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._end_sect_alliance_once, platform, platform_user_id, alliance_id, operation_id)

    async def sync_sect_alliance_research(self, *, platform: str, platform_user_id: str, alliance_id: str, recipe_key: str, operation_id: str) -> AllianceResearchRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._sync_sect_alliance_research_once, platform, platform_user_id, alliance_id, recipe_key, operation_id)

    propose_sect_alliance = create_sect_alliance
    confirm_alliance = confirm_sect_alliance
    get_alliance = get_sect_alliance
    end_alliance = end_sect_alliance
    sync_alliance_research = sync_sect_alliance_research

    def _create_sect_alliance_once(self, platform: str, platform_user_id: str, partner_ref: str, operation_id: str) -> SectAllianceRecord:
        operation_name = "social.sect_alliance.create"
        partner_ref = partner_ref.strip()
        request_hash = self._request_hash(operation_name, {"platform": platform, "platform_user_id": platform_user_id, "partner_ref": partner_ref})
        now = self._now(); now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._alliance_operation(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                return self._alliance_from_payload(replay, already_completed=True)
            player = self._require_player(connection, platform, platform_user_id)
            source, membership = self._alliance_require_leader(connection, int(player["id"]))
            self._alliance_require_level(source)
            self._alliance_require_cooldown(connection, str(source["sect_id"]), now)
            target = self._alliance_find_sect(connection, partner_ref)
            if target is None or str(target["sect_id"]) == str(source["sect_id"]):
                raise SectNotFoundError("partner sect does not exist")
            self._alliance_require_level(target)
            self._alliance_require_cooldown(connection, str(target["sect_id"]), now)
            existing = connection.execute(
                "SELECT * FROM sect_alliance_contracts WHERE ((sect_a_id=? AND sect_b_id=?) OR (sect_a_id=? AND sect_b_id=?)) AND status IN ('pending','active') ORDER BY created_at DESC LIMIT 1",
                (source["sect_id"], target["sect_id"], target["sect_id"], source["sect_id"]),
            ).fetchone()
            if existing is not None:
                raise AllianceRequirementError("an alliance already exists")
            alliance_id = f"alliance-{uuid4().hex}"
            confirmation_expires = now + timedelta(seconds=ALLIANCE_CONFIRMATION_SECONDS)
            snapshot = {"min_sect_level": ALLIANCE_MIN_SECT_LEVEL, "duration_seconds": ALLIANCE_DURATION_SECONDS, "research_weekly_cap": ALLIANCE_RESEARCH_WEEKLY_CAP}
            connection.execute(
                "INSERT INTO sect_alliance_contracts(alliance_id,sect_a_id,sect_b_id,proposer_sect_id,proposer_player_id,status,sect_a_confirmed,sect_b_confirmed,confirmation_expires_at,starts_at,ends_at, snapshot_json,content_version,rule_version,created_at,updated_at) VALUES (?, ?, ?, ?, ?, 'pending', 1, 0, ?, NULL, NULL, ?, ?, ?, ?, ?)",
                (alliance_id, source["sect_id"], target["sect_id"], source["sect_id"], player["id"], serialize_datetime(confirmation_expires), json.dumps(snapshot, sort_keys=True), ALLIANCE_CONTENT_VERSION, ALLIANCE_RULE_VERSION, now_text, now_text),
            )
            row = connection.execute("SELECT * FROM sect_alliance_contracts WHERE alliance_id=?", (alliance_id,)).fetchone()
            payload = self._alliance_payload(connection, row, viewer_sect_id=str(source["sect_id"]))
            self._alliance_insert_operation(connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text)
            return self._alliance_from_payload(payload)

    def _confirm_sect_alliance_once(self, platform: str, platform_user_id: str, alliance_id: str, operation_id: str) -> SectAllianceRecord:
        operation_name = "social.sect_alliance.confirm"
        request_hash = self._request_hash(operation_name, {"platform": platform, "platform_user_id": platform_user_id, "alliance_id": alliance_id})
        now = self._now(); now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._alliance_operation(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                return self._alliance_from_payload(replay, already_completed=True)
            player = self._require_player(connection, platform, platform_user_id)
            alliance = self._alliance_load(connection, alliance_id, now)
            if alliance is None:
                raise AllianceNotFoundError("alliance does not exist")
            membership = self._alliance_leader_membership(connection, int(player["id"]))
            if membership is None or str(membership["sect_id"]) not in {str(alliance["sect_a_id"]), str(alliance["sect_b_id"])}:
                raise SectPermissionDeniedError("alliance partner leader is required")
            if str(alliance["status"]) == "active":
                payload = self._alliance_payload(connection, alliance, viewer_sect_id=str(membership["sect_id"]))
                self._alliance_insert_operation(connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text)
                return self._alliance_from_payload(payload, already_completed=True)
            if str(alliance["status"]) != "pending":
                raise AllianceConfirmationExpiredError("alliance confirmation expired")
            if now >= datetime.fromisoformat(str(alliance["confirmation_expires_at"])):
                connection.execute("UPDATE sect_alliance_contracts SET status='expired', updated_at=? WHERE alliance_id=?", (now_text, alliance_id))
                raise AllianceConfirmationExpiredError("alliance confirmation expired")
            side = "sect_a_confirmed" if str(membership["sect_id"]) == str(alliance["sect_a_id"]) else "sect_b_confirmed"
            connection.execute(f"UPDATE sect_alliance_contracts SET {side}=1, updated_at=? WHERE alliance_id=?", (now_text, alliance_id))
            updated = connection.execute("SELECT * FROM sect_alliance_contracts WHERE alliance_id=?", (alliance_id,)).fetchone()
            if int(updated["sect_a_confirmed"]) and int(updated["sect_b_confirmed"]):
                ends = now + timedelta(seconds=ALLIANCE_DURATION_SECONDS)
                connection.execute("UPDATE sect_alliance_contracts SET status='active', starts_at=?, ends_at=?, updated_at=? WHERE alliance_id=?", (now_text, serialize_datetime(ends), now_text, alliance_id))
            updated = connection.execute("SELECT * FROM sect_alliance_contracts WHERE alliance_id=?", (alliance_id,)).fetchone()
            payload = self._alliance_payload(connection, updated, viewer_sect_id=str(membership["sect_id"]))
            self._alliance_insert_operation(connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text)
            return self._alliance_from_payload(payload)

    def _get_sect_alliance_once(self, platform: str, platform_user_id: str, alliance_id: str | None) -> SectAllianceRecord:
        now = self._now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            player = self._require_player(connection, platform, platform_user_id, writable=False)
            membership = connection.execute("SELECT sect_id FROM sect_members WHERE player_id=? AND status='active'", (player["id"],)).fetchone()
            if membership is None:
                raise SectNotFoundError("player is not in a sect")
            if alliance_id:
                row = self._alliance_load(connection, alliance_id, now)
                if row is None or str(membership["sect_id"]) not in {str(row["sect_a_id"]), str(row["sect_b_id"])}:
                    raise AllianceNotFoundError("alliance does not exist")
            else:
                row = connection.execute("SELECT * FROM sect_alliance_contracts WHERE (sect_a_id=? OR sect_b_id=?) AND status IN ('pending','active') ORDER BY created_at DESC LIMIT 1", (membership["sect_id"], membership["sect_id"])).fetchone()
                if row is None:
                    raise AllianceNotFoundError("alliance does not exist")
                row = self._alliance_load(connection, str(row["alliance_id"]), now)
                if row is None:
                    raise AllianceNotFoundError("alliance does not exist")
            return self._alliance_from_payload(self._alliance_payload(connection, row, viewer_sect_id=str(membership["sect_id"])))

    def _end_sect_alliance_once(self, platform: str, platform_user_id: str, alliance_id: str, operation_id: str) -> SectAllianceRecord:
        operation_name = "social.sect_alliance.end"
        request_hash = self._request_hash(operation_name, {"platform": platform, "platform_user_id": platform_user_id, "alliance_id": alliance_id})
        now = self._now(); now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._alliance_operation(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                return self._alliance_from_payload(replay, already_completed=True)
            player = self._require_player(connection, platform, platform_user_id)
            alliance = self._alliance_load(connection, alliance_id, now)
            if alliance is None:
                raise AllianceNotFoundError("alliance does not exist")
            membership = self._alliance_leader_membership(connection, int(player["id"]))
            if membership is None or str(membership["sect_id"]) not in {str(alliance["sect_a_id"]), str(alliance["sect_b_id"])}:
                raise SectPermissionDeniedError("alliance leader is required")
            if str(alliance["status"]) != "active":
                raise AllianceRequirementError("alliance is not active")
            actor_sect_id = str(membership["sect_id"])
            requested_by = alliance["termination_requested_by"]
            if requested_by is None:
                connection.execute("UPDATE sect_alliance_contracts SET termination_requested_by=?, termination_requested_at=?, updated_at=? WHERE alliance_id=?", (actor_sect_id, now_text, now_text, alliance_id))
                updated = connection.execute("SELECT * FROM sect_alliance_contracts WHERE alliance_id=?", (alliance_id,)).fetchone()
                payload = self._alliance_payload(connection, updated, viewer_sect_id=actor_sect_id)
                self._alliance_insert_operation(connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text)
                return self._alliance_from_payload(payload)
            if str(requested_by) == actor_sect_id:
                raise AllianceRequirementError("the other sect leader must confirm termination")
            payer = connection.execute("SELECT * FROM sects WHERE sect_id=?", (requested_by,)).fetchone()
            if payer is None or int(payer["spirit_stones"]) < ALLIANCE_BREACH_FEE:
                raise AllianceBreachFeeError("alliance breach fee is insufficient")
            connection.execute("UPDATE sects SET spirit_stones=spirit_stones-?, updated_at=? WHERE sect_id=?", (ALLIANCE_BREACH_FEE, now_text, requested_by))
            cooldown_until = serialize_datetime(now + timedelta(seconds=SECT_ALLIANCE_COOLDOWN_SECONDS))
            for sect_id in (alliance["sect_a_id"], alliance["sect_b_id"]):
                connection.execute("INSERT INTO sect_alliance_cooldowns(sect_id,cooldown_until,reason,updated_at) VALUES (?,?,'early_termination',?) ON CONFLICT(sect_id) DO UPDATE SET cooldown_until=excluded.cooldown_until, reason=excluded.reason, updated_at=excluded.updated_at", (sect_id, cooldown_until, now_text))
            connection.execute("UPDATE sect_alliance_contracts SET status='ended', ends_at=?, breach_fee_operation_id=?, updated_at=? WHERE alliance_id=?", (now_text, operation_id, now_text, alliance_id))
            updated = connection.execute("SELECT * FROM sect_alliance_contracts WHERE alliance_id=?", (alliance_id,)).fetchone()
            payload = self._alliance_payload(connection, updated, viewer_sect_id=actor_sect_id)
            self._alliance_insert_operation(connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text)
            return self._alliance_from_payload(payload)

    def _sync_sect_alliance_research_once(self, platform: str, platform_user_id: str, alliance_id: str, recipe_key: str, operation_id: str) -> AllianceResearchRecord:
        operation_name = "social.sect_alliance.sync_research"
        recipe_key = recipe_key.strip()
        request_hash = self._request_hash(operation_name, {"platform": platform, "platform_user_id": platform_user_id, "alliance_id": alliance_id, "recipe_key": recipe_key})
        now = self._now(); now_text = serialize_datetime(now); week_id = alliance_week_id(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._alliance_operation(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                return self._research_from_payload(replay, already_completed=True)
            if not recipe_key or len(recipe_key) > 160:
                raise AllianceRequirementError("recipe key is invalid")
            player = self._require_player(connection, platform, platform_user_id)
            alliance = self._alliance_load(connection, alliance_id, now)
            if alliance is None or str(alliance["status"]) != "active":
                raise AllianceNotFoundError("active alliance does not exist")
            membership = self._alliance_leader_membership(connection, int(player["id"]))
            if membership is None or str(membership["sect_id"]) not in {str(alliance["sect_a_id"]), str(alliance["sect_b_id"])}:
                raise SectPermissionDeniedError("alliance leader is required")
            source_sect_id = str(membership["sect_id"])
            target_sect_id = str(alliance["sect_b_id"] if source_sect_id == str(alliance["sect_a_id"]) else alliance["sect_a_id"])
            existing = connection.execute("SELECT * FROM sect_alliance_research WHERE alliance_id=? AND week_id=? AND recipe_key=?", (alliance_id, week_id, recipe_key)).fetchone()
            if existing is not None:
                payload = self._research_payload(existing)
                self._alliance_insert_operation(connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text)
                return self._research_from_payload(payload, already_completed=True)
            source_unlock = connection.execute("SELECT 1 FROM sect_recipe_unlocks WHERE sect_id=? AND recipe_key=?", (source_sect_id, recipe_key)).fetchone()
            if source_unlock is None:
                raise AllianceRequirementError("source sect has not unlocked this recipe")
            used = connection.execute("SELECT COUNT(*) FROM sect_alliance_research WHERE alliance_id=? AND week_id=?", (alliance_id, week_id)).fetchone()[0]
            if int(used) >= ALLIANCE_RESEARCH_WEEKLY_CAP:
                raise AllianceResearchWeeklyCapError("alliance research weekly cap reached")
            connection.execute("INSERT OR IGNORE INTO sect_recipe_unlocks(sect_id,recipe_key,source_operation_id,unlocked_at) VALUES (?,?,?,?)", (target_sect_id, recipe_key, operation_id, now_text))
            connection.execute("INSERT INTO sect_alliance_research(alliance_id,week_id,recipe_key,source_sect_id,target_sect_id,operation_id,synced_at) VALUES (?,?,?,?,?,?,?)", (alliance_id, week_id, recipe_key, source_sect_id, target_sect_id, operation_id, now_text))
            row = connection.execute("SELECT * FROM sect_alliance_research WHERE alliance_id=? AND week_id=? AND recipe_key=?", (alliance_id, week_id, recipe_key)).fetchone()
            payload = self._research_payload(row)
            self._alliance_insert_operation(connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text)
            return self._research_from_payload(payload)

    @staticmethod
    def _alliance_require_level(sect: Any) -> None:
        if int(sect["level"]) < ALLIANCE_MIN_SECT_LEVEL:
            raise AllianceRequirementError("sect level five is required")

    @staticmethod
    def _alliance_find_sect(connection: Any, ref: str) -> Any:
        return connection.execute("SELECT * FROM sects WHERE status='active' AND (sect_id=? OR name=? OR name_key=?)", (ref, ref, ref.casefold())).fetchone()

    @staticmethod
    def _alliance_leader_membership(connection: Any, player_id: int) -> Any:
        row = connection.execute("SELECT * FROM sect_members WHERE player_id=? AND status='active' AND role='leader'", (player_id,)).fetchone()
        return row

    @classmethod
    def _alliance_require_leader(cls, connection: Any, player_id: int):
        membership = cls._alliance_leader_membership(connection, player_id)
        if membership is None:
            raise SectPermissionDeniedError("sect leader is required")
        sect = connection.execute("SELECT * FROM sects WHERE sect_id=? AND status='active'", (membership["sect_id"],)).fetchone()
        if sect is None:
            raise SectNotFoundError("sect does not exist")
        return sect, membership

    @staticmethod
    def _alliance_require_cooldown(connection: Any, sect_id: str, now: datetime) -> None:
        row = connection.execute("SELECT cooldown_until FROM sect_alliance_cooldowns WHERE sect_id=?", (sect_id,)).fetchone()
        if row is not None and now < datetime.fromisoformat(str(row["cooldown_until"])):
            raise SectAllianceCooldownError("sect alliance cooldown is active")

    @staticmethod
    def _alliance_load(connection: Any, alliance_id: str, now: datetime) -> Any:
        row = connection.execute("SELECT * FROM sect_alliance_contracts WHERE alliance_id=?", (alliance_id,)).fetchone()
        if row is None:
            return None
        if str(row["status"]) == "pending" and now >= datetime.fromisoformat(str(row["confirmation_expires_at"])):
            connection.execute("UPDATE sect_alliance_contracts SET status='expired', updated_at=? WHERE alliance_id=?", (serialize_datetime(now), alliance_id))
            row = connection.execute("SELECT * FROM sect_alliance_contracts WHERE alliance_id=?", (alliance_id,)).fetchone()
        elif str(row["status"]) == "active" and row["ends_at"] and now >= datetime.fromisoformat(str(row["ends_at"])):
            connection.execute("UPDATE sect_alliance_contracts SET status='expired', updated_at=? WHERE alliance_id=?", (serialize_datetime(now), alliance_id))
            row = connection.execute("SELECT * FROM sect_alliance_contracts WHERE alliance_id=?", (alliance_id,)).fetchone()
        return row

    @staticmethod
    def _alliance_payload(connection: Any, row: Any, *, viewer_sect_id: str | None = None) -> dict[str, object]:
        own_sect_id = viewer_sect_id if viewer_sect_id in {str(row["sect_a_id"]), str(row["sect_b_id"])} else str(row["sect_a_id"])
        partner_sect_id = str(row["sect_b_id"]) if own_sect_id == str(row["sect_a_id"]) else str(row["sect_a_id"])
        partner = connection.execute("SELECT name FROM sects WHERE sect_id=?", (partner_sect_id,)).fetchone()
        synced = connection.execute("SELECT recipe_key FROM sect_alliance_research WHERE alliance_id=? ORDER BY synced_at, id", (row["alliance_id"],)).fetchall()
        return {"alliance_id": str(row["alliance_id"]), "sect_id": own_sect_id, "partner_sect_id": partner_sect_id, "partner_sect_name": str(partner["name"] if partner else partner_sect_id), "status": str(row["status"]), "confirmation_expires_at": str(row["confirmation_expires_at"]), "starts_at": row["starts_at"], "ends_at": row["ends_at"], "termination_requested": row["termination_requested_by"] is not None, "synced_recipe_keys": [str(item["recipe_key"]) for item in synced]}

    @staticmethod
    def _alliance_from_payload(payload: Mapping[str, object], *, already_completed: bool = False) -> SectAllianceRecord:
        return SectAllianceRecord(str(payload["alliance_id"]), str(payload["sect_id"]), str(payload["partner_sect_id"]), str(payload["partner_sect_name"]), str(payload["status"]), str(payload["confirmation_expires_at"]), payload.get("starts_at") and str(payload["starts_at"]), payload.get("ends_at") and str(payload["ends_at"]), bool(payload.get("termination_requested", False)), tuple(str(item) for item in payload.get("synced_recipe_keys", [])), already_completed)

    @staticmethod
    def _research_payload(row: Any) -> dict[str, object]:
        return {"alliance_id": str(row["alliance_id"]), "recipe_key": str(row["recipe_key"]), "week_id": str(row["week_id"]), "source_sect_id": str(row["source_sect_id"]), "target_sect_id": str(row["target_sect_id"])}

    @staticmethod
    def _research_from_payload(payload: Mapping[str, object], *, already_completed: bool = False) -> AllianceResearchRecord:
        return AllianceResearchRecord(str(payload["alliance_id"]), str(payload["recipe_key"]), str(payload["week_id"]), str(payload["source_sect_id"]), str(payload["target_sect_id"]), already_completed)

    @staticmethod
    def _alliance_operation(connection: Any, operation_id: str, operation_name: str, request_hash: str) -> dict[str, Any] | None:
        existing = connection.execute("SELECT operation_name,request_hash,result_json FROM operations WHERE operation_id=?", (operation_id,)).fetchone()
        if existing is None:
            return None
        if str(existing["operation_name"]) != operation_name or str(existing["request_hash"]) != request_hash:
            raise OperationConflictError("operation input differs from its original request")
        return json.loads(existing["result_json"])

    @staticmethod
    def _alliance_insert_operation(connection: Any, operation_id: str, operation_name: str, player_id: int, request_hash: str, payload: Mapping[str, object], now_text: str) -> None:
        connection.execute("INSERT INTO operations(operation_id,operation_name,player_id,request_hash,result_json,created_at) VALUES (?,?,?,?,?,?)", (operation_id, operation_name, player_id, request_hash, json.dumps(dict(payload), ensure_ascii=False, sort_keys=True), now_text))


__all__ = ["SectAllianceRepositoryMixin"]
