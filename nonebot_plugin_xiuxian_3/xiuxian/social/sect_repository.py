"""SQLite transactions for the v0.1 sect membership slice."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from ...contracts import serialize_datetime
from ..persistence.errors import (
    OperationConflictError,
    PlayerNotFoundError,
    PlayerSuspendedError,
    ResourceInsufficientError,
    SectAlreadyJoinedError,
    SectApplicationExpiredError,
    SectApplicationExistsError,
    SectApplicationNotFoundError,
    SectAssetLockedError,
    SectFullError,
    SectJoinCooldownError,
    SectLeaderCannotLeaveError,
    SectNameInvalidError,
    SectNotFoundError,
    SectPermissionDeniedError,
    SectRequirementError,
)
from .sect_models import SectApplicationRecord, SectRecord
from .sect_rules import (
    MANAGEMENT_ROLES,
    SECT_APPLICATION_TTL_SECONDS,
    SECT_DEFINITION,
    SECT_JOIN_COOLDOWN_SECONDS,
    SectRole,
    normalize_sect_name_key,
    validate_sect_motto,
    validate_sect_name,
)


class SectRepositoryMixin:
    """Own sect creation, membership applications and leave transactions."""

    async def create_sect(
        self,
        *,
        platform: str,
        platform_user_id: str,
        name: str,
        motto: str,
        operation_id: str,
    ) -> SectRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._sect_create_once,
                platform,
                platform_user_id,
                name,
                motto,
                operation_id,
            )

    def _sect_create_once(
        self,
        platform: str,
        platform_user_id: str,
        name: str,
        motto: str,
        operation_id: str,
    ) -> SectRecord:
        try:
            normalized_name = validate_sect_name(name)
            normalized_motto = validate_sect_motto(motto)
        except ValueError as exc:
            raise SectNameInvalidError(str(exc)) from exc
        operation_name = "social.create_sect"
        request_hash = self._request_hash(
            operation_name,
            {
                "platform": platform,
                "platform_user_id": platform_user_id,
                "name": normalized_name,
                "motto": normalized_motto,
            },
        )
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._sect_operation(connection, operation_id, operation_name, request_hash)
            if existing is not None:
                return self._sect_record_from_payload(existing, replay=True)
            player = self._require_player(connection, platform, platform_user_id)
            self._sect_require_no_membership(connection, player)
            self._sect_require_no_cooldown(player, now)
            if str(player["realm_key"]) not in {
                "foundation",
                "golden_core",
                "nascent_soul",
                "soul_transformation",
                "void_refining",
                "dao_union",
                "tribulation",
            }:
                raise SectRequirementError("sect creation requires foundation realm")
            if int(player["spirit_stones"]) < SECT_DEFINITION.create_cost:
                raise ResourceInsufficientError("sect creation cost is insufficient")
            name_key = normalize_sect_name_key(normalized_name)
            if connection.execute(
                "SELECT 1 FROM sects WHERE name_key = ? AND status IN ('active', 'dissolving')",
                (name_key,),
            ).fetchone() is not None:
                raise SectNameInvalidError("sect name is already used")
            sect_id = f"sect-{uuid4().hex}"
            connection.execute(
                """
                INSERT INTO sects(
                    sect_id, name, name_key, motto, leader_id, status, max_members,
                    warehouse_capacity, construction, created_at, updated_at,
                    content_version, rule_version
                ) VALUES (?, ?, ?, ?, ?, 'active', ?, ?, 0, ?, ?, ?, ?)
                """,
                (
                    sect_id,
                    normalized_name,
                    name_key,
                    normalized_motto,
                    player["id"],
                    SECT_DEFINITION.max_members,
                    SECT_DEFINITION.warehouse_capacity,
                    now_text,
                    now_text,
                    SECT_DEFINITION.content_version,
                    SECT_DEFINITION.rule_version,
                ),
            )
            connection.execute(
                """
                INSERT INTO sect_members(
                    sect_id, player_id, role, status, contribution,
                    joined_at, last_action_at, created_at, updated_at
                ) VALUES (?, ?, 'leader', 'active', 0, ?, ?, ?, ?)
                """,
                (sect_id, player["id"], now_text, now_text, now_text, now_text),
            )
            connection.execute(
                "UPDATE players SET spirit_stones = spirit_stones - ?, updated_at = ? WHERE id = ?",
                (SECT_DEFINITION.create_cost, now_text, player["id"]),
            )
            payload = self._sect_payload(connection, sect_id, player_id=int(player["id"]), role="leader")
            self._sect_record_operation(
                connection,
                operation_id,
                operation_name,
                int(player["id"]),
                request_hash,
                payload,
                now_text,
            )
            return self._sect_record_from_payload(payload)

    async def apply_sect(
        self,
        *,
        platform: str,
        platform_user_id: str,
        sect_ref: str,
        reason: str,
        operation_id: str,
    ) -> SectApplicationRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._sect_apply_once,
                platform,
                platform_user_id,
                sect_ref,
                reason,
                operation_id,
            )

    def _sect_apply_once(
        self,
        platform: str,
        platform_user_id: str,
        sect_ref: str,
        reason: str,
        operation_id: str,
    ) -> SectApplicationRecord:
        normalized_reason = " ".join(reason.strip().split())
        if len(normalized_reason) > 120:
            raise SectNameInvalidError("application reason is too long")
        operation_name = "social.apply_sect"
        request_hash = self._request_hash(
            operation_name,
            {"platform": platform, "platform_user_id": platform_user_id, "sect_ref": sect_ref.strip(), "reason": normalized_reason},
        )
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._sect_operation(connection, operation_id, operation_name, request_hash)
            if existing is not None:
                return self._sect_application_from_payload(existing, replay=True)
            player = self._require_player(connection, platform, platform_user_id)
            self._sect_require_no_membership(connection, player)
            self._sect_require_no_cooldown(player, now)
            sect = self._sect_find(connection, sect_ref)
            if sect is None or str(sect["status"]) != "active":
                raise SectNotFoundError("sect does not exist")
            pending = connection.execute(
                "SELECT * FROM sect_applications WHERE sect_id = ? AND applicant_id = ? AND status = 'pending'",
                (sect["sect_id"], player["id"]),
            ).fetchone()
            if pending is not None:
                if now >= datetime.fromisoformat(str(pending["expires_at"])):
                    connection.execute(
                        "UPDATE sect_applications SET status = 'expired', updated_at = ? WHERE id = ?",
                        (now_text, pending["id"]),
                    )
                else:
                    raise SectApplicationExistsError("pending application already exists")
            application_id = f"sect-app-{uuid4().hex}"
            expires_at = now + timedelta(seconds=SECT_APPLICATION_TTL_SECONDS)
            connection.execute(
                """
                INSERT INTO sect_applications(
                    application_id, sect_id, applicant_id, status, reason,
                    review_reason, reviewer_id, apply_operation_id, review_operation_id,
                    expires_at, created_at, updated_at
                ) VALUES (?, ?, ?, 'pending', ?, '', NULL, ?, NULL, ?, ?, ?)
                """,
                (application_id, sect["sect_id"], player["id"], normalized_reason, operation_id, serialize_datetime(expires_at), now_text, now_text),
            )
            payload = self._sect_application_payload(connection, application_id)
            self._sect_record_operation(
                connection,
                operation_id,
                operation_name,
                int(player["id"]),
                request_hash,
                payload,
                now_text,
            )
            return self._sect_application_from_payload(payload)

    async def list_sect_applications(
        self,
        *,
        platform: str,
        platform_user_id: str,
    ) -> tuple[SectApplicationRecord, ...]:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._sect_list_applications_once, platform, platform_user_id)

    def _sect_list_applications_once(self, platform: str, platform_user_id: str) -> tuple[SectApplicationRecord, ...]:
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            actor = self._require_player(connection, platform, platform_user_id, writable=False)
            membership = self._sect_member(connection, int(actor["id"]))
            if membership is None or SectRole(str(membership["role"])) not in MANAGEMENT_ROLES:
                raise SectPermissionDeniedError("sect application review requires management role")
            connection.execute(
                "UPDATE sect_applications SET status = 'expired', updated_at = ? WHERE sect_id = ? AND status = 'pending' AND expires_at <= ?",
                (now_text, membership["sect_id"], now_text),
            )
            rows = connection.execute(
                "SELECT application_id FROM sect_applications WHERE sect_id = ? AND status = 'pending' ORDER BY created_at, id",
                (membership["sect_id"],),
            ).fetchall()
            return tuple(self._sect_application_from_payload(self._sect_application_payload(connection, row["application_id"])) for row in rows)

    async def review_sect_application(
        self,
        *,
        platform: str,
        platform_user_id: str,
        application_id: str,
        approve: bool,
        review_reason: str,
        operation_id: str,
    ) -> SectApplicationRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._sect_review_once,
                platform,
                platform_user_id,
                application_id,
                approve,
                review_reason,
                operation_id,
            )

    def _sect_review_once(
        self,
        platform: str,
        platform_user_id: str,
        application_id: str,
        approve: bool,
        review_reason: str,
        operation_id: str,
    ) -> SectApplicationRecord:
        normalized_reason = " ".join(review_reason.strip().split())
        if len(normalized_reason) > 120:
            raise SectNameInvalidError("review reason is too long")
        operation_name = "social.review_sect_application"
        request_hash = self._request_hash(
            operation_name,
            {"platform": platform, "platform_user_id": platform_user_id, "application_id": application_id, "approve": bool(approve), "review_reason": normalized_reason},
        )
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._sect_operation(connection, operation_id, operation_name, request_hash)
            if existing is not None:
                return self._sect_application_from_payload(existing, replay=True)
            reviewer = self._require_player(connection, platform, platform_user_id)
            membership = self._sect_member(connection, int(reviewer["id"]))
            if membership is None or SectRole(str(membership["role"])) not in MANAGEMENT_ROLES:
                raise SectPermissionDeniedError("sect application review requires management role")
            application = connection.execute(
                "SELECT * FROM sect_applications WHERE application_id = ? AND sect_id = ?",
                (application_id.strip(), membership["sect_id"]),
            ).fetchone()
            if application is None:
                raise SectApplicationNotFoundError("application does not exist")
            if str(application["status"]) != "pending":
                if str(application["status"]) == "expired":
                    raise SectApplicationExpiredError("application has expired")
                raise SectApplicationNotFoundError("application is no longer pending")
            if now >= datetime.fromisoformat(str(application["expires_at"])):
                connection.execute(
                    "UPDATE sect_applications SET status = 'expired', updated_at = ? WHERE id = ?",
                    (now_text, application["id"]),
                )
                raise SectApplicationExpiredError("application has expired")
            if approve:
                sect = connection.execute("SELECT * FROM sects WHERE sect_id = ?", (membership["sect_id"],)).fetchone()
                if sect is None or str(sect["status"]) != "active":
                    raise SectNotFoundError("sect is not active")
                member_count = connection.execute(
                    "SELECT COUNT(*) AS count FROM sect_members WHERE sect_id = ? AND status = 'active'",
                    (membership["sect_id"],),
                ).fetchone()
                if member_count is not None and int(member_count["count"]) >= int(sect["max_members"]):
                    raise SectFullError("sect is full")
                applicant = self._sect_require_player_by_id(connection, int(application["applicant_id"]))
                self._sect_require_no_membership(connection, applicant)
                self._sect_require_no_cooldown(applicant, now)
                connection.execute(
                    "INSERT INTO sect_members(sect_id, player_id, role, status, contribution, joined_at, last_action_at, created_at, updated_at) VALUES (?, ?, 'member', 'active', 0, ?, ?, ?, ?)",
                    (membership["sect_id"], applicant["id"], now_text, now_text, now_text, now_text),
                )
                status = "accepted"
            else:
                status = "rejected"
            connection.execute(
                "UPDATE sect_applications SET status = ?, review_reason = ?, reviewer_id = ?, review_operation_id = ?, updated_at = ? WHERE id = ? AND status = 'pending'",
                (status, normalized_reason, reviewer["id"], operation_id, now_text, application["id"]),
            )
            payload = self._sect_application_payload(connection, application_id)
            self._sect_record_operation(
                connection,
                operation_id,
                operation_name,
                int(reviewer["id"]),
                request_hash,
                payload,
                now_text,
            )
            return self._sect_application_from_payload(payload)

    async def leave_sect(
        self,
        *,
        platform: str,
        platform_user_id: str,
        operation_id: str,
    ) -> SectRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._sect_leave_once, platform, platform_user_id, operation_id)

    def _sect_leave_once(self, platform: str, platform_user_id: str, operation_id: str) -> SectRecord:
        operation_name = "social.leave_sect"
        request_hash = self._request_hash(operation_name, {"platform": platform, "platform_user_id": platform_user_id})
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._sect_operation(connection, operation_id, operation_name, request_hash)
            if existing is not None:
                return self._sect_record_from_payload(existing, replay=True)
            player = self._require_player(connection, platform, platform_user_id)
            membership = self._sect_member(connection, int(player["id"]))
            if membership is None:
                raise SectNotFoundError("player is not in a sect")
            if str(membership["role"]) == SectRole.LEADER:
                raise SectLeaderCannotLeaveError("sect leader cannot leave")
            self._sect_require_no_locked_assets(connection, int(player["id"]))
            connection.execute(
                "UPDATE sect_members SET status = 'left', left_at = ?, last_action_at = ?, updated_at = ? WHERE id = ? AND status = 'active'",
                (now_text, now_text, now_text, membership["id"]),
            )
            cooldown_until = now + timedelta(seconds=SECT_JOIN_COOLDOWN_SECONDS)
            connection.execute(
                "UPDATE players SET sect_join_cooldown_until = ?, updated_at = ? WHERE id = ?",
                (serialize_datetime(cooldown_until), now_text, player["id"]),
            )
            payload = self._sect_payload(
                connection,
                str(membership["sect_id"]),
                player_id=int(player["id"]),
                role="left",
            )
            self._sect_record_operation(
                connection,
                operation_id,
                operation_name,
                int(player["id"]),
                request_hash,
                payload,
                now_text,
            )
            return self._sect_record_from_payload(payload)

    async def get_sect_profile(
        self,
        *,
        platform: str,
        platform_user_id: str,
        sect_ref: str | None = None,
    ) -> SectRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._sect_profile_once, platform, platform_user_id, sect_ref)

    def _sect_profile_once(self, platform: str, platform_user_id: str, sect_ref: str | None) -> SectRecord:
        with self._connect() as connection:
            player = self._require_player(connection, platform, platform_user_id, writable=False)
            if sect_ref:
                sect = self._sect_find(connection, sect_ref)
                if sect is None or str(sect["status"]) != "active":
                    raise SectNotFoundError("sect does not exist")
                membership = self._sect_member(connection, int(player["id"]), sect_id=str(sect["sect_id"]))
                role = str(membership["role"]) if membership is not None else "visitor"
                return self._sect_record_from_payload(self._sect_payload(connection, str(sect["sect_id"]), player_id=int(player["id"]), role=role))
            membership = self._sect_member(connection, int(player["id"]))
            if membership is None:
                raise SectNotFoundError("player is not in a sect")
            return self._sect_record_from_payload(self._sect_payload(connection, str(membership["sect_id"]), player_id=int(player["id"]), role=str(membership["role"])))

    @staticmethod
    def _sect_require_no_membership(connection: Any, player: Any) -> None:
        if connection.execute(
            "SELECT 1 FROM sect_members WHERE player_id = ? AND status = 'active' LIMIT 1",
            (player["id"],),
        ).fetchone() is not None:
            raise SectAlreadyJoinedError("player already belongs to a sect")

    @staticmethod
    def _sect_require_no_cooldown(player: Any, now: datetime) -> None:
        value = player["sect_join_cooldown_until"]
        if value and now < datetime.fromisoformat(str(value)):
            raise SectJoinCooldownError("sect join cooldown is active")

    @staticmethod
    def _sect_member(connection: Any, player_id: int, *, sect_id: str | None = None) -> Any:
        if sect_id is None:
            return connection.execute(
                "SELECT * FROM sect_members WHERE player_id = ? AND status = 'active' ORDER BY id DESC LIMIT 1",
                (player_id,),
            ).fetchone()
        return connection.execute(
            "SELECT * FROM sect_members WHERE player_id = ? AND sect_id = ? AND status = 'active' ORDER BY id DESC LIMIT 1",
            (player_id, sect_id),
        ).fetchone()

    @staticmethod
    def _sect_find(connection: Any, sect_ref: str) -> Any:
        value = sect_ref.strip()
        return connection.execute(
            "SELECT * FROM sects WHERE (sect_id = ? OR name_key = ?) LIMIT 1",
            (value, normalize_sect_name_key(value)),
        ).fetchone()

    @staticmethod
    def _sect_require_player_by_id(connection: Any, player_id: int) -> Any:
        row = connection.execute("SELECT * FROM players WHERE id = ?", (player_id,)).fetchone()
        if row is None:
            raise PlayerNotFoundError("player does not exist")
        if str(row["status"]) != "active":
            raise PlayerSuspendedError("applicant is not active")
        return row

    @staticmethod
    def _sect_require_no_locked_assets(connection: Any, player_id: int) -> None:
        checks = (
            ("cultivation_sessions", "status = 'running'"),
            ("retreat_sessions", "status = 'running'"),
            ("production_orders", "status = 'processing'"),
            ("travel_sessions", "status = 'running'"),
            ("exploration_sessions", "status IN ('created', 'running', 'combat_pending')"),
            ("breakthrough_sessions", "status = 'preparing'"),
            ("livelihood_trade_routes", "status = 'in_transit'"),
        )
        for table, status_clause in checks:
            if connection.execute(f"SELECT 1 FROM {table} WHERE player_id = ? AND {status_clause} LIMIT 1", (player_id,)).fetchone() is not None:
                raise SectAssetLockedError("player has an active session")
        if connection.execute(
            "SELECT 1 FROM livelihood_service_orders WHERE (publisher_id = ? OR provider_id = ?) AND status IN ('published', 'accepted', 'delivered') LIMIT 1",
            (player_id, player_id),
        ).fetchone() is not None:
            raise SectAssetLockedError("player has an active service order")

    @staticmethod
    def _sect_payload(connection: Any, sect_id: str, *, player_id: int, role: str) -> dict[str, Any]:
        sect = connection.execute("SELECT * FROM sects WHERE sect_id = ?", (sect_id,)).fetchone()
        if sect is None:
            raise SectNotFoundError("sect does not exist")
        count = connection.execute(
            "SELECT COUNT(*) AS count FROM sect_members WHERE sect_id = ? AND status = 'active'",
            (sect_id,),
        ).fetchone()
        player = connection.execute("SELECT spirit_stones FROM players WHERE id = ?", (player_id,)).fetchone()
        return {
            "sect_id": str(sect["sect_id"]),
            "name": str(sect["name"]),
            "motto": str(sect["motto"]),
            "status": str(sect["status"]),
            "leader_player_id": str(sect["leader_id"]),
            "role": role,
            "member_count": int(count["count"]) if count is not None else 0,
            "max_members": int(sect["max_members"]),
            "construction": int(sect["construction"]),
            "spirit_stones": int(player["spirit_stones"]) if player is not None else 0,
            "created_at": str(sect["created_at"]),
            "player_id": str(player_id),
        }

    @staticmethod
    def _sect_application_payload(connection: Any, application_id: str) -> dict[str, Any]:
        row = connection.execute(
            """
            SELECT a.*, s.name AS sect_name, s.sect_id,
                   p.player_id AS applicant_player_id, p.dao_name AS applicant_dao_name
            FROM sect_applications a
            JOIN sects s ON s.sect_id = a.sect_id
            JOIN players p ON p.id = a.applicant_id
            WHERE a.application_id = ?
            """,
            (application_id,),
        ).fetchone()
        if row is None:
            raise SectApplicationNotFoundError("application does not exist")
        return {
            "application_id": str(row["application_id"]),
            "sect_id": str(row["sect_id"]),
            "sect_name": str(row["sect_name"]),
            "applicant_player_id": str(row["applicant_player_id"]),
            "applicant_name": str(row["applicant_dao_name"] or "未命名"),
            "status": str(row["status"]),
            "reason": str(row["reason"]),
            "review_reason": str(row["review_reason"]),
            "expires_at": str(row["expires_at"]),
            "created_at": str(row["created_at"]),
            "reviewer_player_id": None,
        }

    @staticmethod
    def _sect_operation(connection: Any, operation_id: str, operation_name: str, request_hash: str) -> dict[str, Any] | None:
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
    def _sect_record_operation(connection: Any, operation_id: str, operation_name: str, player_id: int, request_hash: str, payload: dict[str, Any], now_text: str) -> None:
        connection.execute(
            "INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (operation_id, operation_name, player_id, request_hash, json.dumps(payload, ensure_ascii=False, sort_keys=True), now_text),
        )

    @staticmethod
    def _sect_record_from_payload(payload: dict[str, Any], *, replay: bool = False) -> SectRecord:
        return SectRecord(
            sect_id=str(payload["sect_id"]),
            name=str(payload["name"]),
            motto=str(payload["motto"]),
            status=str(payload["status"]),
            leader_player_id=str(payload["leader_player_id"]),
            role=str(payload["role"]),
            member_count=int(payload["member_count"]),
            max_members=int(payload["max_members"]),
            construction=int(payload["construction"]),
            spirit_stones=int(payload.get("spirit_stones", 0)),
            created_at=str(payload["created_at"]),
            already_completed=replay,
        )

    @staticmethod
    def _sect_application_from_payload(payload: dict[str, Any], *, replay: bool = False) -> SectApplicationRecord:
        return SectApplicationRecord(
            application_id=str(payload["application_id"]),
            sect_id=str(payload["sect_id"]),
            sect_name=str(payload["sect_name"]),
            applicant_player_id=str(payload["applicant_player_id"]),
            applicant_name=str(payload["applicant_name"]),
            status=str(payload["status"]),
            reason=str(payload["reason"]),
            review_reason=str(payload.get("review_reason", "")),
            expires_at=str(payload["expires_at"]),
            created_at=str(payload["created_at"]),
            reviewer_player_id=payload.get("reviewer_player_id"),
            already_completed=replay,
        )


__all__ = ["SectRepositoryMixin"]
