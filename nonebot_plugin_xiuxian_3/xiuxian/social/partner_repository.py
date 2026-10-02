"""SQLite transactions for the partner relationship lifecycle."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from ...contracts import serialize_datetime
from ..content import ContentBundle, bundled_content
from ..persistence.errors import (
    OperationConflictError,
    PartnerBreakCooldownError,
    PartnerDissolutionExpiredError,
    PartnerDissolutionNotFoundError,
    PartnerInvitationExpiredError,
    PartnerInvitationNotFoundError,
    PartnerPermissionDeniedError,
    PartnerRelationConflictError,
    PartnerRequirementError,
    PartnerStateConflictError,
    PlayerNotFoundError,
    PlayerSuspendedError,
)
from ..utils.operations import operation_replay, record_operation
from .partner_models import PartnerRelationRecord
from .partner_rules import PartnerDefinition, partner_definition, partner_eligible


class PartnerRepositoryMixin:
    """Own all state transitions for one pair of players."""

    def _partner_content(self) -> ContentBundle:
        return self.content if self.content is not None else bundled_content()

    async def invite_partner(
        self,
        *,
        platform: str,
        platform_user_id: str,
        target_ref: str,
        operation_id: str,
    ) -> PartnerRelationRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._partner_invite_once,
                platform,
                platform_user_id,
                target_ref,
                operation_id,
            )

    async def accept_partner(
        self,
        *,
        platform: str,
        platform_user_id: str,
        relation_id: str,
        operation_id: str,
    ) -> PartnerRelationRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._partner_accept_once,
                platform,
                platform_user_id,
                relation_id,
                operation_id,
            )

    async def reject_partner(
        self,
        *,
        platform: str,
        platform_user_id: str,
        relation_id: str,
        operation_id: str,
    ) -> PartnerRelationRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._partner_reject_once,
                platform,
                platform_user_id,
                relation_id,
                operation_id,
            )

    async def get_partner(
        self,
        *,
        platform: str,
        platform_user_id: str,
    ) -> PartnerRelationRecord | None:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._partner_get_once, platform, platform_user_id)

    async def request_partner_dissolution(
        self,
        *,
        platform: str,
        platform_user_id: str,
        relation_id: str,
        operation_id: str,
    ) -> PartnerRelationRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._partner_request_dissolution_once,
                platform,
                platform_user_id,
                relation_id,
                operation_id,
            )

    async def confirm_partner_dissolution(
        self,
        *,
        platform: str,
        platform_user_id: str,
        relation_id: str,
        operation_id: str,
    ) -> PartnerRelationRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._partner_confirm_dissolution_once,
                platform,
                platform_user_id,
                relation_id,
                operation_id,
            )

    async def reject_partner_dissolution(
        self,
        *,
        platform: str,
        platform_user_id: str,
        relation_id: str,
        operation_id: str,
    ) -> PartnerRelationRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._partner_reject_dissolution_once,
                platform,
                platform_user_id,
                relation_id,
                operation_id,
            )

    def _partner_invite_once(self, platform: str, platform_user_id: str, target_ref: str, operation_id: str) -> PartnerRelationRecord:
        definition = partner_definition(self._partner_content())
        target_ref = target_ref.strip()
        operation_name = "social.invite_partner"
        request_hash = self._request_hash(operation_name, {"platform": platform, "platform_user_id": platform_user_id, "target_ref": target_ref})
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            actor = self._require_player(connection, platform, platform_user_id)
            existing = operation_replay(connection, operation_id, operation_name, request_hash, player_id=int(actor["id"]))
            if existing is not None:
                return self._partner_record_from_payload(existing, replay=True)
            self._partner_expire_due(connection, now_text, operation_id)
            if not partner_eligible(actor, definition, self._partner_content()):
                raise PartnerRequirementError("initiator is below the configured partner realm")
            target = connection.execute(
                "SELECT * FROM players WHERE dao_name = ? AND dao_name <> ''",
                (target_ref,),
            ).fetchone()
            if target is None:
                raise PlayerNotFoundError("target dao name does not exist")
            if int(target["id"]) == int(actor["id"]):
                raise PartnerRelationConflictError("a player cannot invite self")
            if str(target["status"]) != "active":
                raise PlayerSuspendedError("target player is not active")
            if not partner_eligible(target, definition, self._partner_content()):
                raise PartnerRequirementError("invitee is below the configured partner realm")
            player_a, player_b = sorted((int(actor["id"]), int(target["id"])))
            pair_key = f"{player_a}:{player_b}"
            current = connection.execute(
                "SELECT 1 FROM partner_relations WHERE (player_a_id IN (?, ?) OR player_b_id IN (?, ?)) "
                "AND status IN ('invited', 'active', 'dissolution_pending') LIMIT 1",
                (actor["id"], target["id"], actor["id"], target["id"]),
            ).fetchone()
            if current is not None:
                raise PartnerRelationConflictError("a player already has a current partner relation")
            cooldown = connection.execute(
                "SELECT cooldown_until FROM partner_relations WHERE pair_key = ? AND status = 'dissolved' "
                "AND cooldown_until IS NOT NULL ORDER BY id DESC LIMIT 1",
                (pair_key,),
            ).fetchone()
            if cooldown is not None and now < datetime.fromisoformat(str(cooldown["cooldown_until"])):
                raise PartnerBreakCooldownError("pair reunion cooldown is active")
            relation_id = f"partner-{uuid4().hex}"
            expires_at = serialize_datetime(now + timedelta(seconds=definition.invitation_ttl_seconds))
            connection.execute(
                "INSERT INTO partner_relations(" \
                "relation_id, player_a_id, player_b_id, pair_key, initiator_id, invitee_id, status, " \
                "invited_at, invitation_expires_at, invitation_operation_id, snapshot_json, created_at, updated_at) " \
                "VALUES (?, ?, ?, ?, ?, ?, 'invited', ?, ?, ?, ?, ?, ?)",
                (
                    relation_id,
                    player_a,
                    player_b,
                    pair_key,
                    actor["id"],
                    target["id"],
                    now_text,
                    expires_at,
                    operation_id,
                    json.dumps(definition.snapshot(), ensure_ascii=False, sort_keys=True),
                    now_text,
                    now_text,
                ),
            )
            payload = self._partner_payload(connection, relation_id)
            record_operation(connection, operation_id, operation_name, int(actor["id"]), request_hash, payload, now_text)
            return self._partner_record_from_payload(payload)

    def _partner_accept_once(self, platform: str, platform_user_id: str, relation_id: str, operation_id: str) -> PartnerRelationRecord:
        return self._partner_invitation_transition(platform, platform_user_id, relation_id, operation_id, accept=True)

    def _partner_reject_once(self, platform: str, platform_user_id: str, relation_id: str, operation_id: str) -> PartnerRelationRecord:
        return self._partner_invitation_transition(platform, platform_user_id, relation_id, operation_id, accept=False)

    def _partner_invitation_transition(self, platform: str, platform_user_id: str, relation_id: str, operation_id: str, *, accept: bool) -> PartnerRelationRecord:
        definition = partner_definition(self._partner_content())
        relation_id = relation_id.strip()
        operation_name = "social.accept_partner" if accept else "social.reject_partner"
        request_hash = self._request_hash(operation_name, {"platform": platform, "platform_user_id": platform_user_id, "relation_id": relation_id})
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            actor = self._require_player(connection, platform, platform_user_id)
            existing = operation_replay(connection, operation_id, operation_name, request_hash, player_id=int(actor["id"]))
            if existing is not None:
                return self._partner_record_from_payload(existing, replay=True)
            self._partner_expire_due(connection, now_text, operation_id)
            relation = connection.execute(
                "SELECT * FROM partner_relations WHERE relation_id = ? AND invitee_id = ?",
                (relation_id, actor["id"]),
            ).fetchone()
            if relation is None:
                raise PartnerInvitationNotFoundError("partner invitation does not exist")
            if str(relation["status"]) == "expired" or now >= datetime.fromisoformat(str(relation["invitation_expires_at"])):
                connection.execute(
                    "UPDATE partner_relations SET status='expired', expired_at=?, invitation_expiry_operation_id=?, updated_at=? "
                    "WHERE id=? AND status='invited'",
                    (now_text, f"{operation_id}:invite-expire", now_text, relation["id"]),
                )
                raise PartnerInvitationExpiredError("partner invitation has expired")
            if str(relation["status"]) != "invited":
                raise PartnerInvitationNotFoundError("partner invitation is no longer pending")
            if accept:
                if not partner_eligible(actor, definition, self._partner_content()):
                    raise PartnerRequirementError("invitee is below the configured partner realm")
                initiator = connection.execute(
                    "SELECT * FROM players WHERE id = ?",
                    (relation["initiator_id"],),
                ).fetchone()
                if initiator is None or not partner_eligible(initiator, definition, self._partner_content()):
                    raise PartnerRequirementError("initiator is below the configured partner realm")
                connection.execute(
                    "UPDATE partner_relations SET status='active', accepted_at=?, acceptance_operation_id=?, updated_at=? WHERE id=? AND status='invited'",
                    (now_text, operation_id, now_text, relation["id"]),
                )
            else:
                connection.execute(
                    "UPDATE partner_relations SET status='rejected', rejected_at=?, rejection_operation_id=?, updated_at=? WHERE id=? AND status='invited'",
                    (now_text, operation_id, now_text, relation["id"]),
                )
            payload = self._partner_payload(connection, relation_id)
            record_operation(connection, operation_id, operation_name, int(actor["id"]), request_hash, payload, now_text)
            return self._partner_record_from_payload(payload)

    def _partner_get_once(self, platform: str, platform_user_id: str) -> PartnerRelationRecord | None:
        now = self._now()
        with self._connect() as connection:
            actor = self._require_player(connection, platform, platform_user_id, writable=False)
            relation = connection.execute(
                "SELECT relation_id FROM partner_relations WHERE (player_a_id=? OR player_b_id=?) "
                "AND status IN ('invited', 'active', 'dissolution_pending') ORDER BY id DESC LIMIT 1",
                (actor["id"], actor["id"]),
            ).fetchone()
            if relation is None:
                return None
            payload = self._partner_payload(connection, str(relation["relation_id"]))
            if payload["status"] == "invited" and now >= datetime.fromisoformat(str(payload["invitation_expires_at"])):
                payload["status"] = "expired"
            elif payload["status"] == "dissolution_pending" and now >= datetime.fromisoformat(str(payload["dissolution_expires_at"])):
                payload["status"] = "active"
            return self._partner_record_from_payload(payload)

    def _partner_request_dissolution_once(self, platform: str, platform_user_id: str, relation_id: str, operation_id: str) -> PartnerRelationRecord:
        definition = partner_definition(self._partner_content())
        return self._partner_dissolution_transition(platform, platform_user_id, relation_id, operation_id, definition, action="request")

    def _partner_confirm_dissolution_once(self, platform: str, platform_user_id: str, relation_id: str, operation_id: str) -> PartnerRelationRecord:
        definition = partner_definition(self._partner_content())
        return self._partner_dissolution_transition(platform, platform_user_id, relation_id, operation_id, definition, action="confirm")

    def _partner_reject_dissolution_once(self, platform: str, platform_user_id: str, relation_id: str, operation_id: str) -> PartnerRelationRecord:
        definition = partner_definition(self._partner_content())
        return self._partner_dissolution_transition(platform, platform_user_id, relation_id, operation_id, definition, action="reject")

    def _partner_dissolution_transition(self, platform: str, platform_user_id: str, relation_id: str, operation_id: str, definition: PartnerDefinition, *, action: str) -> PartnerRelationRecord:
        relation_id = relation_id.strip()
        operation_name = f"social.{action}_partner_dissolution"
        request_hash = self._request_hash(operation_name, {"platform": platform, "platform_user_id": platform_user_id, "relation_id": relation_id})
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            actor = self._require_player(connection, platform, platform_user_id)
            existing = operation_replay(connection, operation_id, operation_name, request_hash, player_id=int(actor["id"]))
            if existing is not None:
                return self._partner_record_from_payload(existing, replay=True)
            self._partner_expire_due(connection, now_text, operation_id, expire_dissolutions=False)
            relation = connection.execute(
                "SELECT * FROM partner_relations WHERE relation_id=? AND (player_a_id=? OR player_b_id=?)",
                (relation_id, actor["id"], actor["id"]),
            ).fetchone()
            if relation is None:
                raise PartnerDissolutionNotFoundError("partner relation does not exist")
            status = str(relation["status"])
            dissolution_expired = (
                status == "dissolution_pending"
                and relation["dissolution_expires_at"]
                and now >= datetime.fromisoformat(str(relation["dissolution_expires_at"]))
            )
            if dissolution_expired:
                connection.execute(
                    "UPDATE partner_relations SET status='active', dissolution_expiry_operation_id=?, updated_at=? "
                    "WHERE id=? AND status='dissolution_pending'",
                    (f"{operation_id}:dissolution-expire", now_text, relation["id"]),
                )
                if action != "request":
                    raise PartnerDissolutionExpiredError("partner dissolution request has expired")
                relation = connection.execute(
                    "SELECT * FROM partner_relations WHERE id = ?",
                    (relation["id"],),
                ).fetchone()
                status = "active"
            if action == "request":
                if status != "active":
                    raise PartnerStateConflictError("partner relation is not active")
                expires_at = serialize_datetime(now + timedelta(seconds=definition.dissolution_ttl_seconds))
                connection.execute(
                    "UPDATE partner_relations SET status='dissolution_pending', dissolution_requested_by=?, "
                    "dissolution_requested_at=?, dissolution_expires_at=?, dissolution_request_operation_id=?, updated_at=? "
                    "WHERE id=? AND status='active'",
                    (actor["id"], now_text, expires_at, operation_id, now_text, relation["id"]),
                )
            else:
                if status != "dissolution_pending":
                    raise PartnerDissolutionNotFoundError("partner dissolution request does not exist")
                if int(relation["dissolution_requested_by"]) == int(actor["id"]):
                    raise PartnerPermissionDeniedError("the requester cannot confirm its own dissolution")
                if action == "confirm":
                    cooldown_until = serialize_datetime(now + timedelta(seconds=definition.reunion_cooldown_seconds))
                    connection.execute(
                        "UPDATE partner_relations SET status='dissolved', dissolved_at=?, cooldown_until=?, "
                        "dissolution_confirmation_operation_id=?, updated_at=? WHERE id=? AND status='dissolution_pending'",
                        (now_text, cooldown_until, operation_id, now_text, relation["id"]),
                    )
                else:
                    connection.execute(
                        "UPDATE partner_relations SET status='active', dissolution_rejected_at=?, dissolution_rejection_operation_id=?, updated_at=? "
                        "WHERE id=? AND status='dissolution_pending'",
                        (now_text, operation_id, now_text, relation["id"]),
                    )
            payload = self._partner_payload(connection, relation_id)
            record_operation(connection, operation_id, operation_name, int(actor["id"]), request_hash, payload, now_text)
            return self._partner_record_from_payload(payload)

    @staticmethod
    def _partner_expire_due(connection: Any, now_text: str, operation_id: str, *, expire_dissolutions: bool = True) -> None:
        connection.execute(
            "UPDATE partner_relations SET status='expired', expired_at=?, invitation_expiry_operation_id=?, updated_at=? "
            "WHERE status='invited' AND invitation_expires_at <= ?",
            (now_text, f"{operation_id}:invite-expire", now_text, now_text),
        )
        if expire_dissolutions:
            connection.execute(
                "UPDATE partner_relations SET status='active', dissolution_expiry_operation_id=?, updated_at=? "
                "WHERE status='dissolution_pending' AND dissolution_expires_at <= ?",
                (f"{operation_id}:dissolution-expire", now_text, now_text),
            )

    @staticmethod
    def _partner_payload(connection: Any, relation_id: str) -> dict[str, Any]:
        row = connection.execute(
            "SELECT r.*, ip.dao_name AS initiator_dao_name, ep.dao_name AS invitee_dao_name, "
            "ap.dao_name AS player_a_dao_name, bp.dao_name AS player_b_dao_name, dp.dao_name AS dissolution_dao_name "
            "FROM partner_relations r JOIN players ip ON ip.id=r.initiator_id JOIN players ep ON ep.id=r.invitee_id "
            "JOIN players ap ON ap.id=r.player_a_id JOIN players bp ON bp.id=r.player_b_id "
            "LEFT JOIN players dp ON dp.id=r.dissolution_requested_by WHERE r.relation_id=?",
            (relation_id,),
        ).fetchone()
        if row is None:
            raise PartnerInvitationNotFoundError("partner relation does not exist")
        return {
            "relation_id": str(row["relation_id"]),
            "status": str(row["status"]),
            "initiator_dao_name": str(row["initiator_dao_name"] or "未命名"),
            "invitee_dao_name": str(row["invitee_dao_name"] or "未命名"),
            "player_a_dao_name": str(row["player_a_dao_name"] or "未命名"),
            "player_b_dao_name": str(row["player_b_dao_name"] or "未命名"),
            "invited_at": str(row["invited_at"]),
            "invitation_expires_at": str(row["invitation_expires_at"]),
            "accepted_at": str(row["accepted_at"]) if row["accepted_at"] else None,
            "dissolution_requested_by_dao_name": str(row["dissolution_dao_name"]) if row["dissolution_dao_name"] else None,
            "dissolution_requested_at": str(row["dissolution_requested_at"]) if row["dissolution_requested_at"] else None,
            "dissolution_expires_at": str(row["dissolution_expires_at"]) if row["dissolution_expires_at"] else None,
            "dissolved_at": str(row["dissolved_at"]) if row["dissolved_at"] else None,
            "cooldown_until": str(row["cooldown_until"]) if row["cooldown_until"] else None,
        }

    @staticmethod
    def _partner_record_from_payload(payload: dict[str, Any], *, replay: bool = False) -> PartnerRelationRecord:
        return PartnerRelationRecord(
            relation_id=str(payload["relation_id"]),
            status=str(payload["status"]),
            initiator_dao_name=str(payload["initiator_dao_name"]),
            invitee_dao_name=str(payload["invitee_dao_name"]),
            player_a_dao_name=str(payload["player_a_dao_name"]),
            player_b_dao_name=str(payload["player_b_dao_name"]),
            invited_at=str(payload["invited_at"]),
            invitation_expires_at=str(payload["invitation_expires_at"]),
            accepted_at=payload.get("accepted_at"),
            dissolution_requested_by_dao_name=payload.get("dissolution_requested_by_dao_name"),
            dissolution_requested_at=payload.get("dissolution_requested_at"),
            dissolution_expires_at=payload.get("dissolution_expires_at"),
            dissolved_at=payload.get("dissolved_at"),
            cooldown_until=payload.get("cooldown_until"),
            already_completed=replay,
        )


__all__ = ["PartnerRepositoryMixin"]
