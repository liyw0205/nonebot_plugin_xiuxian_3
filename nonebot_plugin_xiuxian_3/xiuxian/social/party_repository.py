"""SQLite transactions for the v0.1 two-player exploration party slice."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from ...contracts import serialize_datetime
from ..persistence.errors import (
    OperationConflictError,
    PartyAlreadyMemberError,
    PartyInvitationExpiredError,
    PartyInvitationNotFoundError,
    PartyLocationMismatchError,
    PartyNotFoundError,
    PartyPermissionDeniedError,
    PartyStateConflictError,
    PlayerNotFoundError,
    PlayerSuspendedError,
)
from .party_models import PartyMemberRecord, PartyRecord
from .party_rules import PARTY_DEFINITION, party_definition_for


class PartyRepositoryMixin:
    """Own party membership, confirmation and leader-transfer transactions."""

    async def create_party(
        self,
        *,
        platform: str,
        platform_user_id: str,
        operation_id: str,
        party_type: str = PARTY_DEFINITION.party_type,
    ) -> PartyRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._party_create_once, platform, platform_user_id, operation_id, party_type)

    async def invite_party(
        self,
        *,
        platform: str,
        platform_user_id: str,
        target_ref: str,
        operation_id: str,
    ) -> PartyRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._party_invite_once,
                platform,
                platform_user_id,
                target_ref,
                operation_id,
            )

    async def accept_party(
        self,
        *,
        platform: str,
        platform_user_id: str,
        party_id: str,
        operation_id: str,
    ) -> PartyRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._party_accept_once,
                platform,
                platform_user_id,
                party_id,
                operation_id,
            )

    async def reject_party(
        self,
        *,
        platform: str,
        platform_user_id: str,
        party_id: str,
        operation_id: str,
    ) -> PartyRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._party_reject_once,
                platform,
                platform_user_id,
                party_id,
                operation_id,
            )

    async def confirm_party(
        self,
        *,
        platform: str,
        platform_user_id: str,
        party_id: str,
        operation_id: str,
    ) -> PartyRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._party_confirm_once,
                platform,
                platform_user_id,
                party_id,
                operation_id,
            )

    async def leave_party(self, *, platform: str, platform_user_id: str, operation_id: str) -> PartyRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._party_leave_once, platform, platform_user_id, operation_id)

    async def get_party(self, *, platform: str, platform_user_id: str) -> PartyRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._party_get_once, platform, platform_user_id)

    def _party_create_once(self, platform: str, platform_user_id: str, operation_id: str, party_type: str) -> PartyRecord:
        operation_name = "social.create_party"
        definition = party_definition_for(party_type)
        request_hash = self._request_hash(
            operation_name,
            {"platform": platform, "platform_user_id": platform_user_id, "party_type": definition.party_type},
        )
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._party_operation(connection, operation_id, operation_name, request_hash)
            if existing is not None:
                return self._party_record_from_payload(existing, replay=True)
            player = self._require_player(connection, platform, platform_user_id)
            if definition.required_location and str(player["location_key"]) != definition.required_location:
                raise PartyLocationMismatchError("party must be created at its required location")
            self._party_expire_due(connection, now, now_text)
            if self._party_current_membership(connection, int(player["id"])) is not None:
                raise PartyAlreadyMemberError("player already belongs to a party")
            party_id = f"party-{uuid4().hex}"
            deadline = now + timedelta(seconds=definition.confirmation_ttl_seconds)
            connection.execute(
                """
                INSERT INTO parties(
                    party_id, party_type, status, leader_id, location_key,
                    confirmation_deadline, current_session_id, distribution_key,
                    content_version, rule_version, created_at, updated_at
                ) VALUES (?, ?, 'forming', ?, ?, ?, NULL, ?, ?, ?, ?, ?)
                """,
                (
                    party_id,
                    definition.party_type,
                    player["id"],
                    str(player["location_key"]),
                    serialize_datetime(deadline),
                    definition.distribution_key,
                    definition.content_version,
                    definition.rule_version,
                    now_text,
                    now_text,
                ),
            )
            connection.execute(
                """
                INSERT INTO party_members(
                    party_id, player_id, role, status, confirmed_at,
                    invited_at, joined_at, left_at, created_at, updated_at
                ) VALUES (?, ?, 'leader', 'active', ?, ?, ?, NULL, ?, ?)
                """,
                (party_id, player["id"], now_text, now_text, now_text, now_text, now_text),
            )
            payload = self._party_payload(connection, party_id)
            self._party_record_operation(connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text)
            return self._party_record_from_payload(payload)

    def _party_invite_once(
        self,
        platform: str,
        platform_user_id: str,
        target_ref: str,
        operation_id: str,
    ) -> PartyRecord:
        operation_name = "social.invite_party"
        target_platform, target_user_id = self._party_target_ref(platform, target_ref)
        request_hash = self._request_hash(
            operation_name,
            {
                "platform": platform,
                "platform_user_id": platform_user_id,
                "target_platform": target_platform,
                "target_platform_user_id": target_user_id,
            },
        )
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._party_operation(connection, operation_id, operation_name, request_hash)
            if existing is not None:
                return self._party_record_from_payload(existing, replay=True)
            leader = self._require_player(connection, platform, platform_user_id)
            self._party_expire_due(connection, now, now_text)
            membership = self._party_current_membership(connection, int(leader["id"]))
            if membership is None or str(membership["role"]) != "leader":
                raise PartyPermissionDeniedError("only the party leader can invite")
            party = connection.execute("SELECT * FROM parties WHERE party_id = ?", (membership["party_id"],)).fetchone()
            if party is None:
                raise PartyNotFoundError("party does not exist")
            if str(party["status"]) != "forming":
                raise PartyStateConflictError("party is not accepting invitations")
            member_count = connection.execute(
                "SELECT COUNT(*) AS count FROM party_members WHERE party_id = ? AND status IN ('invited', 'active')",
                (party["party_id"],),
            ).fetchone()
            definition = party_definition_for(str(party["party_type"]))
            if member_count is not None and int(member_count["count"]) >= definition.max_members:
                raise PartyStateConflictError("party is full")
            target = connection.execute(
                "SELECT * FROM players WHERE platform = ? AND platform_user_id = ?",
                (target_platform, target_user_id),
            ).fetchone()
            if target is None:
                raise PlayerNotFoundError("target player does not exist")
            if str(target["status"]) != "active":
                raise PlayerSuspendedError("target player is not active")
            if int(target["id"]) == int(leader["id"]):
                raise PartyAlreadyMemberError("leader cannot invite self")
            if str(target["location_key"]) != str(party["location_key"]):
                raise PartyLocationMismatchError("party members must share a location")
            target_membership = self._party_current_membership(connection, int(target["id"]))
            if target_membership is not None:
                raise PartyAlreadyMemberError("target player already belongs to a party")
            connection.execute(
                """
                INSERT INTO party_members(
                    party_id, player_id, role, status, confirmed_at,
                    invited_at, joined_at, left_at, created_at, updated_at
                ) VALUES (?, ?, 'member', 'invited', NULL, ?, NULL, NULL, ?, ?)
                """,
                (party["party_id"], target["id"], now_text, now_text, now_text),
            )
            connection.execute("UPDATE parties SET updated_at = ? WHERE party_id = ?", (now_text, party["party_id"]))
            payload = self._party_payload(connection, str(party["party_id"]))
            self._party_record_operation(connection, operation_id, operation_name, int(leader["id"]), request_hash, payload, now_text)
            return self._party_record_from_payload(payload)

    def _party_accept_once(self, platform: str, platform_user_id: str, party_id: str, operation_id: str) -> PartyRecord:
        operation_name = "social.accept_party"
        party_id = party_id.strip()
        request_hash = self._request_hash(operation_name, {"platform": platform, "platform_user_id": platform_user_id, "party_id": party_id})
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._party_operation(connection, operation_id, operation_name, request_hash)
            if existing is not None:
                return self._party_record_from_payload(existing, replay=True)
            player = self._require_player(connection, platform, platform_user_id)
            self._party_expire_due(connection, now, now_text)
            invitation = connection.execute(
                "SELECT * FROM party_members WHERE party_id = ? AND player_id = ? ORDER BY id DESC LIMIT 1",
                (party_id, player["id"]),
            ).fetchone()
            party = connection.execute("SELECT * FROM parties WHERE party_id = ?", (party_id,)).fetchone()
            if party is None or invitation is None:
                raise PartyInvitationNotFoundError("party invitation does not exist")
            if now >= datetime.fromisoformat(str(party["confirmation_deadline"])) or str(party["status"]) == "expired" or str(invitation["status"]) == "expired":
                connection.commit()
                raise PartyInvitationExpiredError("party confirmation window expired")
            if str(invitation["status"]) != "invited":
                raise PartyInvitationNotFoundError("party invitation is no longer pending")
            if str(player["location_key"]) != str(party["location_key"]):
                raise PartyLocationMismatchError("party members must share a location")
            current_membership = self._party_current_membership(connection, int(player["id"]))
            if current_membership is not None and int(current_membership["id"]) != int(invitation["id"]):
                raise PartyAlreadyMemberError("player already belongs to a party")
            connection.execute(
                "UPDATE party_members SET status = 'active', joined_at = ?, updated_at = ? WHERE id = ? AND status = 'invited'",
                (now_text, now_text, invitation["id"]),
            )
            connection.execute("UPDATE parties SET updated_at = ? WHERE party_id = ?", (now_text, party_id))
            payload = self._party_payload(connection, party_id)
            self._party_record_operation(connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text)
            return self._party_record_from_payload(payload)

    def _party_reject_once(self, platform: str, platform_user_id: str, party_id: str, operation_id: str) -> PartyRecord:
        operation_name = "social.reject_party"
        party_id = party_id.strip()
        request_hash = self._request_hash(operation_name, {"platform": platform, "platform_user_id": platform_user_id, "party_id": party_id})
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._party_operation(connection, operation_id, operation_name, request_hash)
            if existing is not None:
                return self._party_record_from_payload(existing, replay=True)
            player = self._require_player(connection, platform, platform_user_id)
            self._party_expire_due(connection, now, now_text)
            invitation = connection.execute(
                "SELECT * FROM party_members WHERE party_id = ? AND player_id = ? ORDER BY id DESC LIMIT 1",
                (party_id, player["id"]),
            ).fetchone()
            if invitation is None:
                raise PartyInvitationNotFoundError("party invitation does not exist")
            if str(invitation["status"]) == "expired":
                connection.commit()
                raise PartyInvitationExpiredError("party confirmation window expired")
            if str(invitation["status"]) != "invited":
                raise PartyInvitationNotFoundError("party invitation is no longer pending")
            connection.execute(
                "UPDATE party_members SET status = 'rejected', updated_at = ? WHERE id = ? AND status = 'invited'",
                (now_text, invitation["id"]),
            )
            connection.execute("UPDATE parties SET updated_at = ? WHERE party_id = ?", (now_text, party_id))
            payload = self._party_payload(connection, party_id)
            self._party_record_operation(connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text)
            return self._party_record_from_payload(payload)

    def _party_confirm_once(self, platform: str, platform_user_id: str, party_id: str, operation_id: str) -> PartyRecord:
        operation_name = "social.confirm_party"
        party_id = party_id.strip()
        request_hash = self._request_hash(operation_name, {"platform": platform, "platform_user_id": platform_user_id, "party_id": party_id})
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._party_operation(connection, operation_id, operation_name, request_hash)
            if existing is not None:
                return self._party_record_from_payload(existing, replay=True)
            player = self._require_player(connection, platform, platform_user_id)
            self._party_expire_due(connection, now, now_text)
            party = connection.execute("SELECT * FROM parties WHERE party_id = ?", (party_id,)).fetchone()
            member = connection.execute(
                "SELECT * FROM party_members WHERE party_id = ? AND player_id = ? AND status = 'active'",
                (party_id, player["id"]),
            ).fetchone()
            if party is None or member is None:
                if party is not None and str(party["status"]) == "expired":
                    connection.commit()
                raise PartyNotFoundError("player is not an active party member")
            if str(party["status"]) not in {"forming", "ready"}:
                raise PartyStateConflictError("party cannot be confirmed")
            if str(player["location_key"]) != str(party["location_key"]):
                raise PartyLocationMismatchError("party members must share a location")
            connection.execute(
                "UPDATE party_members SET confirmed_at = COALESCE(confirmed_at, ?), updated_at = ? WHERE id = ?",
                (now_text, now_text, member["id"]),
            )
            active = connection.execute(
                "SELECT COUNT(*) AS count FROM party_members WHERE party_id = ? AND status = 'active'",
                (party_id,),
            ).fetchone()
            confirmed = connection.execute(
                "SELECT COUNT(*) AS count FROM party_members WHERE party_id = ? AND status = 'active' AND confirmed_at IS NOT NULL",
                (party_id,),
            ).fetchone()
            definition = party_definition_for(str(party["party_type"]))
            active_count = int(active["count"]) if active is not None else 0
            confirmed_count = int(confirmed["count"]) if confirmed is not None else 0
            status = "ready" if definition.min_members <= active_count <= definition.max_members and confirmed_count == active_count else "forming"
            connection.execute("UPDATE parties SET status = ?, updated_at = ? WHERE party_id = ?", (status, now_text, party_id))
            payload = self._party_payload(connection, party_id)
            self._party_record_operation(connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text)
            return self._party_record_from_payload(payload)

    def _party_leave_once(self, platform: str, platform_user_id: str, operation_id: str) -> PartyRecord:
        operation_name = "social.leave_party"
        request_hash = self._request_hash(operation_name, {"platform": platform, "platform_user_id": platform_user_id})
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._party_operation(connection, operation_id, operation_name, request_hash)
            if existing is not None:
                return self._party_record_from_payload(existing, replay=True)
            player = self._require_player(connection, platform, platform_user_id)
            self._party_expire_due(connection, now, now_text)
            member = self._party_current_membership(connection, int(player["id"]))
            if member is None or str(member["status"]) != "active":
                raise PartyNotFoundError("player is not an active party member")
            party_id = str(member["party_id"])
            party = connection.execute("SELECT current_session_id FROM parties WHERE party_id = ?", (party_id,)).fetchone()
            if party is not None and party["current_session_id"]:
                raise PartyStateConflictError("party battle is still active")
            connection.execute(
                "UPDATE party_members SET status = 'left', left_at = ?, updated_at = ? WHERE id = ? AND status = 'active'",
                (now_text, now_text, member["id"]),
            )
            active = connection.execute(
                "SELECT * FROM party_members WHERE party_id = ? AND status = 'active' ORDER BY id",
                (party_id,),
            ).fetchall()
            if str(member["role"]) == "leader" and active:
                new_leader = active[0]
                connection.execute("UPDATE party_members SET role = 'leader', updated_at = ? WHERE id = ?", (now_text, new_leader["id"]))
                connection.execute("UPDATE parties SET leader_id = ?, status = 'forming', updated_at = ? WHERE party_id = ?", (new_leader["player_id"], now_text, party_id))
            elif active:
                connection.execute("UPDATE parties SET status = 'forming', updated_at = ? WHERE party_id = ?", (now_text, party_id))
            else:
                connection.execute("UPDATE party_members SET status = 'expired', updated_at = ? WHERE party_id = ? AND status = 'invited'", (now_text, party_id))
                connection.execute("UPDATE parties SET status = 'disbanded', updated_at = ? WHERE party_id = ?", (now_text, party_id))
            payload = self._party_payload(connection, party_id)
            self._party_record_operation(connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text)
            return self._party_record_from_payload(payload)

    def _party_get_once(self, platform: str, platform_user_id: str) -> PartyRecord:
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            player = self._require_player(connection, platform, platform_user_id, writable=False)
            self._party_expire_due(connection, now, now_text)
            member = self._party_current_membership(connection, int(player["id"]))
            if member is None:
                connection.commit()
                raise PartyNotFoundError("player has no current party")
            return self._party_record_from_payload(self._party_payload(connection, str(member["party_id"])))

    @staticmethod
    def _party_target_ref(platform: str, target_ref: str) -> tuple[str, str]:
        value = target_ref.strip()
        if ":" in value:
            target_platform, target_user_id = value.split(":", 1)
            if target_platform.strip() and target_user_id.strip():
                return target_platform.strip().lower(), target_user_id.strip()
        return platform, value

    @staticmethod
    def _party_current_membership(connection: Any, player_id: int) -> Any:
        return connection.execute(
            "SELECT * FROM party_members WHERE player_id = ? AND status IN ('invited', 'active') ORDER BY id DESC LIMIT 1",
            (player_id,),
        ).fetchone()

    @staticmethod
    def _party_expire_due(connection: Any, now: datetime, now_text: str) -> None:
        rows = connection.execute(
            "SELECT party_id FROM parties WHERE status IN ('forming', 'ready') AND confirmation_deadline <= ?",
            (now_text,),
        ).fetchall()
        for row in rows:
            connection.execute("UPDATE party_members SET status = 'expired', updated_at = ? WHERE party_id = ? AND status IN ('invited', 'active')", (now_text, row["party_id"]))
            connection.execute("UPDATE parties SET status = 'expired', updated_at = ? WHERE party_id = ?", (now_text, row["party_id"]))

    @staticmethod
    def _party_payload(connection: Any, party_id: str) -> dict[str, Any]:
        party = connection.execute("SELECT * FROM parties WHERE party_id = ?", (party_id,)).fetchone()
        if party is None:
            raise PartyNotFoundError("party does not exist")
        rows = connection.execute(
            """
            SELECT m.player_id, m.role, m.status, m.confirmed_at,
                   p.player_id AS stable_player_id, p.platform_user_id, p.dao_name
            FROM party_members m JOIN players p ON p.id = m.player_id
            WHERE m.party_id = ? ORDER BY m.id
            """,
            (party_id,),
        ).fetchall()
        return {
            "party_id": str(party["party_id"]),
            "party_type": str(party["party_type"]),
            "status": str(party["status"]),
            "leader_player_id": str(connection.execute("SELECT player_id FROM players WHERE id = ?", (party["leader_id"],)).fetchone()[0]),
            "location_key": str(party["location_key"]),
            "confirmation_deadline": str(party["confirmation_deadline"]),
            "distribution_key": str(party["distribution_key"]),
            "members": [
                {
                    "player_id": str(row["stable_player_id"]),
                    "platform_user_id": str(row["platform_user_id"]),
                    "dao_name": str(row["dao_name"] or "未命名"),
                    "role": str(row["role"]),
                    "status": str(row["status"]),
                    "confirmed_at": str(row["confirmed_at"]) if row["confirmed_at"] else None,
                }
                for row in rows
            ],
        }

    @staticmethod
    def _party_operation(connection: Any, operation_id: str, operation_name: str, request_hash: str) -> dict[str, Any] | None:
        existing = connection.execute(
            "SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id = ?",
            (operation_id,),
        ).fetchone()
        if existing is None:
            return None
        if existing["operation_name"] != operation_name or existing["request_hash"] != request_hash:
            raise OperationConflictError("operation input differs from its original request")
        return json.loads(existing["result_json"])

    @staticmethod
    def _party_record_operation(connection: Any, operation_id: str, operation_name: str, player_id: int, request_hash: str, payload: dict[str, Any], now_text: str) -> None:
        connection.execute(
            "INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (operation_id, operation_name, player_id, request_hash, json.dumps(payload, ensure_ascii=False, sort_keys=True), now_text),
        )

    @staticmethod
    def _party_record_from_payload(payload: dict[str, Any], *, replay: bool = False) -> PartyRecord:
        return PartyRecord(
            party_id=str(payload["party_id"]),
            party_type=str(payload["party_type"]),
            status=str(payload["status"]),
            leader_player_id=str(payload["leader_player_id"]),
            location_key=str(payload["location_key"]),
            confirmation_deadline=str(payload["confirmation_deadline"]),
            distribution_key=str(payload["distribution_key"]),
            members=tuple(
                PartyMemberRecord(
                    player_id=str(member["player_id"]),
                    platform_user_id=str(member["platform_user_id"]),
                    dao_name=str(member["dao_name"]),
                    role=str(member["role"]),
                    status=str(member["status"]),
                    confirmed_at=member.get("confirmed_at"),
                )
                for member in payload.get("members", [])
            ),
            already_completed=replay,
        )


__all__ = ["PartyRepositoryMixin"]
