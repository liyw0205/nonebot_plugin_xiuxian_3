"""SQLite transactions for the v0.1 mentor relationship slice."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from ...contracts import serialize_datetime
from ..persistence.errors import (
    MentorGraduationNotReadyError,
    MentorInvitationExpiredError,
    MentorInvitationNotFoundError,
    MentorPermissionDeniedError,
    MentorRelationConflictError,
    MentorRequirementError,
    MentorStateConflictError,
    OperationConflictError,
    PlayerNotFoundError,
    PlayerSuspendedError,
)
from .mentor_models import MentorRelationRecord
from .mentor_rules import (
    MENTOR_APPRENTICE_LOCAL_REPUTATION,
    MENTOR_CONTENT_VERSION,
    MENTOR_CONTRIBUTION,
    MENTOR_INVITATION_TTL_SECONDS,
    MENTOR_MAX_APPRENTICES,
    MENTOR_RULE_VERSION,
    MENTOR_SERVICE_REPUTATION,
    is_apprentice_eligible,
    is_graduation_ready,
    is_master_eligible,
)


class MentorRepositoryMixin:
    """Own mentor invitations, acceptance and one-time graduation rewards."""

    async def invite_mentor(
        self,
        *,
        platform: str,
        platform_user_id: str,
        target_ref: str,
        operation_id: str,
    ) -> MentorRelationRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._mentor_invite_once,
                platform,
                platform_user_id,
                target_ref,
                operation_id,
            )

    async def accept_mentor(
        self,
        *,
        platform: str,
        platform_user_id: str,
        relation_id: str,
        operation_id: str,
    ) -> MentorRelationRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._mentor_accept_once,
                platform,
                platform_user_id,
                relation_id,
                operation_id,
            )

    async def reject_mentor(
        self,
        *,
        platform: str,
        platform_user_id: str,
        relation_id: str,
        operation_id: str,
    ) -> MentorRelationRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._mentor_reject_once,
                platform,
                platform_user_id,
                relation_id,
                operation_id,
            )

    async def graduate_apprentice(
        self,
        *,
        platform: str,
        platform_user_id: str,
        relation_id: str,
        operation_id: str,
    ) -> MentorRelationRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._mentor_graduate_once,
                platform,
                platform_user_id,
                relation_id,
                operation_id,
            )

    def _mentor_invite_once(
        self,
        platform: str,
        platform_user_id: str,
        target_ref: str,
        operation_id: str,
    ) -> MentorRelationRecord:
        target_platform, target_user_id = self._mentor_target_ref(platform, target_ref)
        operation_name = "social.invite_mentor"
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
            existing = self._mentor_operation(connection, operation_id, operation_name, request_hash)
            if existing is not None:
                return self._mentor_record_from_payload(existing, replay=True)
            master = self._require_player(connection, platform, platform_user_id)
            self._mentor_expire_due(connection, now_text)
            if not is_master_eligible(str(master["realm_key"]), int(master["realm_layer"])):
                raise MentorRequirementError("master does not meet foundation L4 requirement")
            count = connection.execute(
                """
                SELECT COUNT(*) AS count FROM mentor_relations
                WHERE master_id = ? AND status IN ('invited', 'active')
                """,
                (master["id"],),
            ).fetchone()
            if count is not None and int(count["count"]) >= MENTOR_MAX_APPRENTICES:
                raise MentorRelationConflictError("master has reached the apprentice cap")
            target = connection.execute(
                "SELECT * FROM players WHERE platform = ? AND platform_user_id = ?",
                (target_platform, target_user_id),
            ).fetchone()
            if target is None:
                raise PlayerNotFoundError("target player does not exist")
            if str(target["status"]) != "active":
                raise PlayerSuspendedError("target player is not active")
            if int(target["id"]) == int(master["id"]):
                raise MentorRelationConflictError("master cannot invite self")
            if not is_apprentice_eligible(str(target["stage"]), str(target["realm_key"]), int(target["realm_layer"])):
                raise MentorRequirementError("target is outside the apprentice realm range")
            conflict = connection.execute(
                """
                SELECT 1 FROM mentor_relations
                WHERE status IN ('invited', 'active')
                  AND ((master_id = ? AND apprentice_id = ?)
                       OR apprentice_id = ?)
                LIMIT 1
                """,
                (master["id"], target["id"], target["id"]),
            ).fetchone()
            if conflict is not None:
                raise MentorRelationConflictError("target already has a mentor relationship")
            relation_id = f"mentor-{uuid4().hex}"
            expires_at = serialize_datetime(now + timedelta(seconds=MENTOR_INVITATION_TTL_SECONDS))
            connection.execute(
                """
                INSERT INTO mentor_relations(
                    relation_id, master_id, apprentice_id, status, expires_at,
                    invited_at, accepted_at, rejected_at, graduated_at,
                    graduate_operation_id, master_contribution,
                    content_version, rule_version, created_at, updated_at
                ) VALUES (?, ?, ?, 'invited', ?, ?, NULL, NULL, NULL, NULL, 0, ?, ?, ?, ?)
                """,
                (
                    relation_id,
                    master["id"],
                    target["id"],
                    expires_at,
                    now_text,
                    MENTOR_CONTENT_VERSION,
                    MENTOR_RULE_VERSION,
                    now_text,
                    now_text,
                ),
            )
            payload = self._mentor_payload(connection, relation_id)
            self._mentor_record_operation(connection, operation_id, operation_name, int(master["id"]), request_hash, payload, now_text)
            return self._mentor_record_from_payload(payload)

    def _mentor_accept_once(
        self,
        platform: str,
        platform_user_id: str,
        relation_id: str,
        operation_id: str,
    ) -> MentorRelationRecord:
        relation_id = relation_id.strip()
        operation_name = "social.accept_mentor"
        request_hash = self._request_hash(
            operation_name,
            {"platform": platform, "platform_user_id": platform_user_id, "relation_id": relation_id},
        )
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._mentor_operation(connection, operation_id, operation_name, request_hash)
            if existing is not None:
                return self._mentor_record_from_payload(existing, replay=True)
            apprentice = self._require_player(connection, platform, platform_user_id)
            self._mentor_expire_due(connection, now_text)
            relation = connection.execute(
                "SELECT * FROM mentor_relations WHERE relation_id = ? AND apprentice_id = ?",
                (relation_id, apprentice["id"]),
            ).fetchone()
            if relation is None:
                raise MentorInvitationNotFoundError("mentor invitation does not exist")
            if str(relation["status"]) == "expired" or now >= datetime.fromisoformat(str(relation["expires_at"])):
                connection.execute(
                    "UPDATE mentor_relations SET status = 'expired', updated_at = ? WHERE id = ? AND status = 'invited'",
                    (now_text, relation["id"]),
                )
                connection.commit()
                raise MentorInvitationExpiredError("mentor invitation has expired")
            if str(relation["status"]) != "invited":
                raise MentorInvitationNotFoundError("mentor invitation is no longer pending")
            master = connection.execute("SELECT * FROM players WHERE id = ?", (relation["master_id"],)).fetchone()
            if master is None:
                raise PlayerNotFoundError("master does not exist")
            if not is_master_eligible(str(master["realm_key"]), int(master["realm_layer"])):
                raise MentorRequirementError("master no longer meets the mentor requirement")
            if not is_apprentice_eligible(str(apprentice["stage"]), str(apprentice["realm_key"]), int(apprentice["realm_layer"])):
                raise MentorRequirementError("apprentice no longer meets the realm requirement")
            current = connection.execute(
                "SELECT 1 FROM mentor_relations WHERE apprentice_id = ? AND status = 'active' LIMIT 1",
                (apprentice["id"],),
            ).fetchone()
            if current is not None:
                raise MentorRelationConflictError("apprentice already has an active mentor")
            connection.execute(
                "UPDATE mentor_relations SET status = 'active', accepted_at = ?, updated_at = ? WHERE id = ? AND status = 'invited'",
                (now_text, now_text, relation["id"]),
            )
            payload = self._mentor_payload(connection, relation_id)
            self._mentor_record_operation(connection, operation_id, operation_name, int(apprentice["id"]), request_hash, payload, now_text)
            return self._mentor_record_from_payload(payload)

    def _mentor_reject_once(
        self,
        platform: str,
        platform_user_id: str,
        relation_id: str,
        operation_id: str,
    ) -> MentorRelationRecord:
        relation_id = relation_id.strip()
        operation_name = "social.reject_mentor"
        request_hash = self._request_hash(
            operation_name,
            {"platform": platform, "platform_user_id": platform_user_id, "relation_id": relation_id},
        )
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._mentor_operation(connection, operation_id, operation_name, request_hash)
            if existing is not None:
                return self._mentor_record_from_payload(existing, replay=True)
            apprentice = self._require_player(connection, platform, platform_user_id)
            self._mentor_expire_due(connection, now_text)
            relation = connection.execute(
                "SELECT * FROM mentor_relations WHERE relation_id = ? AND apprentice_id = ?",
                (relation_id, apprentice["id"]),
            ).fetchone()
            if relation is None:
                raise MentorInvitationNotFoundError("mentor invitation does not exist")
            if str(relation["status"]) == "expired" or now >= datetime.fromisoformat(str(relation["expires_at"])):
                connection.execute(
                    "UPDATE mentor_relations SET status = 'expired', updated_at = ? WHERE id = ? AND status = 'invited'",
                    (now_text, relation["id"]),
                )
                connection.commit()
                raise MentorInvitationExpiredError("mentor invitation has expired")
            if str(relation["status"]) != "invited":
                raise MentorInvitationNotFoundError("mentor invitation is no longer pending")
            connection.execute(
                "UPDATE mentor_relations SET status = 'rejected', rejected_at = ?, updated_at = ? WHERE id = ? AND status = 'invited'",
                (now_text, now_text, relation["id"]),
            )
            payload = self._mentor_payload(connection, relation_id)
            self._mentor_record_operation(connection, operation_id, operation_name, int(apprentice["id"]), request_hash, payload, now_text)
            return self._mentor_record_from_payload(payload)

    def _mentor_graduate_once(
        self,
        platform: str,
        platform_user_id: str,
        relation_id: str,
        operation_id: str,
    ) -> MentorRelationRecord:
        relation_id = relation_id.strip()
        operation_name = "social.graduate_apprentice"
        request_hash = self._request_hash(
            operation_name,
            {"platform": platform, "platform_user_id": platform_user_id, "relation_id": relation_id},
        )
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._mentor_operation(connection, operation_id, operation_name, request_hash)
            if existing is not None:
                return self._mentor_record_from_payload(existing, replay=True)
            master = self._require_player(connection, platform, platform_user_id)
            relation = connection.execute(
                "SELECT * FROM mentor_relations WHERE relation_id = ? AND master_id = ?",
                (relation_id, master["id"]),
            ).fetchone()
            if relation is None:
                raise MentorPermissionDeniedError("only the mentor can graduate this relation")
            if str(relation["status"]) != "active":
                raise MentorStateConflictError("mentor relation is not active")
            apprentice = connection.execute("SELECT * FROM players WHERE id = ?", (relation["apprentice_id"],)).fetchone()
            if apprentice is None:
                raise PlayerNotFoundError("apprentice does not exist")
            if not is_graduation_ready(str(apprentice["stage"]), str(apprentice["realm_key"]), int(apprentice["realm_layer"])):
                raise MentorGraduationNotReadyError("apprentice has not reached qi gathering L3 after entry")
            if not self._mentor_has_completed_service(connection, int(apprentice["id"])):
                raise MentorGraduationNotReadyError("apprentice has not completed production or livelihood service")
            connection.execute(
                """
                UPDATE mentor_relations
                SET status = 'graduated', graduated_at = ?, graduate_operation_id = ?,
                    master_contribution = master_contribution + ?, updated_at = ?
                WHERE id = ? AND status = 'active'
                """,
                (now_text, operation_id, MENTOR_CONTRIBUTION, now_text, relation["id"]),
            )
            self._mentor_add_reputation(connection, int(apprentice["id"]), MENTOR_APPRENTICE_LOCAL_REPUTATION, MENTOR_SERVICE_REPUTATION, now_text)
            self._mentor_add_reputation(connection, int(master["id"]), 0, MENTOR_SERVICE_REPUTATION, now_text)
            # Sect contribution is the existing shared contribution ledger. The
            # relation row remains the source of truth when the mentor is not in a sect.
            connection.execute(
                """
                UPDATE sect_members
                SET contribution = contribution + ?, last_action_at = ?, updated_at = ?
                WHERE player_id = ? AND status = 'active'
                """,
                (MENTOR_CONTRIBUTION, now_text, now_text, master["id"]),
            )
            payload = self._mentor_payload(
                connection,
                relation_id,
                apprentice_local_reputation=MENTOR_APPRENTICE_LOCAL_REPUTATION,
                service_reputation_delta=MENTOR_SERVICE_REPUTATION,
            )
            self._mentor_record_operation(connection, operation_id, operation_name, int(master["id"]), request_hash, payload, now_text)
            return self._mentor_record_from_payload(payload)

    @staticmethod
    def _mentor_has_completed_service(connection: Any, player_id: int) -> bool:
        production = connection.execute(
            "SELECT 1 FROM production_orders WHERE player_id = ? AND status = 'completed' LIMIT 1",
            (player_id,),
        ).fetchone()
        if production is not None:
            return True
        livelihood = connection.execute(
            "SELECT 1 FROM livelihood_service_orders WHERE provider_id = ? AND status = 'delivered' LIMIT 1",
            (player_id,),
        ).fetchone()
        if livelihood is not None:
            return True
        commission = connection.execute(
            "SELECT 1 FROM town_commission_claims WHERE player_id = ? AND status = 'delivered' LIMIT 1",
            (player_id,),
        ).fetchone()
        return commission is not None

    @staticmethod
    def _mentor_add_reputation(connection: Any, player_id: int, local_delta: int, service_delta: int, now_text: str) -> None:
        reputation = connection.execute(
            "SELECT local_json, service_reputation FROM player_reputations WHERE player_id = ?",
            (player_id,),
        ).fetchone()
        if reputation is None:
            local: dict[str, Any] = {}
        else:
            try:
                decoded = json.loads(str(reputation["local_json"]))
            except (TypeError, ValueError):
                decoded = {}
            local = decoded if isinstance(decoded, dict) else {}
        local_key = "local.xuantian.new_town"
        local[local_key] = int(local.get(local_key, 0)) + int(local_delta)
        service = int(reputation["service_reputation"]) if reputation is not None else 0
        service = min(100, service + int(service_delta))
        connection.execute(
            """
            INSERT INTO player_reputations(player_id, local_json, service_reputation, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(player_id) DO UPDATE SET local_json = excluded.local_json,
                service_reputation = excluded.service_reputation, updated_at = excluded.updated_at
            """,
            (player_id, json.dumps(local, ensure_ascii=False, sort_keys=True), service, now_text),
        )

    @staticmethod
    def _mentor_target_ref(platform: str, target_ref: str) -> tuple[str, str]:
        value = target_ref.strip()
        if ":" in value:
            target_platform, target_user_id = value.split(":", 1)
            if target_platform.strip() and target_user_id.strip():
                return target_platform.strip().lower(), target_user_id.strip()
        return platform, value

    @staticmethod
    def _mentor_expire_due(connection: Any, now_text: str) -> None:
        connection.execute(
            "UPDATE mentor_relations SET status = 'expired', updated_at = ? WHERE status = 'invited' AND expires_at <= ?",
            (now_text, now_text),
        )

    @staticmethod
    def _mentor_payload(
        connection: Any,
        relation_id: str,
        *,
        apprentice_local_reputation: int = 0,
        service_reputation_delta: int = 0,
    ) -> dict[str, Any]:
        row = connection.execute(
            """
            SELECT r.*, mp.player_id AS master_player_id, mp.platform_user_id AS master_platform_user_id,
                   mp.dao_name AS master_dao_name, ap.player_id AS apprentice_player_id,
                   ap.platform_user_id AS apprentice_platform_user_id, ap.dao_name AS apprentice_dao_name
            FROM mentor_relations r
            JOIN players mp ON mp.id = r.master_id
            JOIN players ap ON ap.id = r.apprentice_id
            WHERE r.relation_id = ?
            """,
            (relation_id,),
        ).fetchone()
        if row is None:
            raise MentorInvitationNotFoundError("mentor relation does not exist")
        return {
            "relation_id": str(row["relation_id"]),
            "status": str(row["status"]),
            "master_player_id": str(row["master_player_id"]),
            "master_platform_user_id": str(row["master_platform_user_id"]),
            "master_dao_name": str(row["master_dao_name"] or "未命名"),
            "apprentice_player_id": str(row["apprentice_player_id"]),
            "apprentice_platform_user_id": str(row["apprentice_platform_user_id"]),
            "apprentice_dao_name": str(row["apprentice_dao_name"] or "未命名"),
            "expires_at": str(row["expires_at"]),
            "accepted_at": str(row["accepted_at"]) if row["accepted_at"] else None,
            "graduated_at": str(row["graduated_at"]) if row["graduated_at"] else None,
            "master_contribution": int(row["master_contribution"]),
            "apprentice_local_reputation": int(apprentice_local_reputation),
            "service_reputation_delta": int(service_reputation_delta),
        }

    @staticmethod
    def _mentor_operation(connection: Any, operation_id: str, operation_name: str, request_hash: str) -> dict[str, Any] | None:
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
    def _mentor_record_operation(connection: Any, operation_id: str, operation_name: str, player_id: int, request_hash: str, payload: dict[str, Any], now_text: str) -> None:
        connection.execute(
            "INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (operation_id, operation_name, player_id, request_hash, json.dumps(payload, ensure_ascii=False, sort_keys=True), now_text),
        )

    @staticmethod
    def _mentor_record_from_payload(payload: dict[str, Any], *, replay: bool = False) -> MentorRelationRecord:
        return MentorRelationRecord(
            relation_id=str(payload["relation_id"]),
            status=str(payload["status"]),
            master_player_id=str(payload["master_player_id"]),
            master_platform_user_id=str(payload["master_platform_user_id"]),
            master_dao_name=str(payload["master_dao_name"]),
            apprentice_player_id=str(payload["apprentice_player_id"]),
            apprentice_platform_user_id=str(payload["apprentice_platform_user_id"]),
            apprentice_dao_name=str(payload["apprentice_dao_name"]),
            expires_at=str(payload["expires_at"]),
            accepted_at=payload.get("accepted_at"),
            graduated_at=payload.get("graduated_at"),
            master_contribution=int(payload.get("master_contribution", 0)),
            apprentice_local_reputation=int(payload.get("apprentice_local_reputation", 0)),
            service_reputation_delta=int(payload.get("service_reputation_delta", 0)),
            already_completed=replay,
        )


__all__ = ["MentorRepositoryMixin"]
