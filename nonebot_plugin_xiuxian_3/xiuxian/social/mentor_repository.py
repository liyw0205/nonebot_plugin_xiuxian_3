"""SQLite transactions for the mentor relationship slice."""

from __future__ import annotations

import asyncio
from dataclasses import fields
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from ...contracts import serialize_datetime
from ..utils.operations import operation_replay, record_operation
from ..utils.player import change_player_state_actual, player_integer
from ..persistence.errors import (
    MentorGraduationNotReadyError,
    MentorInvitationExpiredError,
    MentorInvitationNotFoundError,
    MentorPermissionDeniedError,
    MentorRelationConflictError,
    MentorRequirementError,
    MentorStateConflictError,
    PlayerNotFoundError,
    PlayerSuspendedError,
)
from .mentor_models import MentorRelationRecord, MentorRelationView
from .mentor_rules import (
    MENTOR_INVITATION_TTL_SECONDS,
    MENTOR_MAX_APPRENTICES,
    is_apprentice_eligible,
    is_graduation_ready,
    is_master_eligible,
    mentor_graduation_definition,
    mentor_graduation_from_snapshot,
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

    async def get_mentor_relations(
        self,
        *,
        platform: str,
        platform_user_id: str,
    ) -> list[MentorRelationView]:
        """Return the caller's mentor relationships without changing state."""

        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._mentor_list_once,
                platform,
                platform_user_id,
            )

    def _mentor_list_once(self, platform: str, platform_user_id: str) -> list[MentorRelationView]:
        now = self._now()
        with self._connect() as connection:
            player = self._require_player(connection, platform, platform_user_id, writable=False)
            rows = connection.execute(
                """
                SELECT r.relation_id, r.status, r.invited_at, r.expires_at, r.accepted_at,
                       r.rejected_at, r.graduated_at, r.master_contribution, r.created_at,
                       r.master_id, r.apprentice_id,
                       mp.dao_name AS master_dao_name, ap.dao_name AS apprentice_dao_name
                FROM mentor_relations r
                JOIN players mp ON mp.id = r.master_id
                JOIN players ap ON ap.id = r.apprentice_id
                WHERE r.master_id = ? OR r.apprentice_id = ?
                ORDER BY r.created_at DESC, r.relation_id DESC
                """,
                (player["id"], player["id"]),
            ).fetchall()
            return [self._mentor_view_from_row(row, int(player["id"]), now) for row in rows]

    @staticmethod
    def _mentor_view_from_row(row: Any, player_id: int, now: datetime) -> MentorRelationView:
        allowed_statuses = {"invited", "active", "graduated", "rejected", "expired"}
        status = row["status"]
        if not isinstance(status, str) or status not in allowed_statuses:
            raise ValueError("mentor relationship status is invalid")
        relation_id = row["relation_id"]
        if not isinstance(relation_id, str) or not relation_id.strip():
            raise ValueError("mentor relationship id is invalid")
        if type(row["master_contribution"]) is not int or row["master_contribution"] < 0:
            raise ValueError("mentor relationship contribution is invalid")

        def parse_time(key: str, *, required: bool) -> tuple[str | None, datetime | None]:
            value = row[key]
            if value is None and not required:
                return None, None
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"mentor relationship {key} is invalid")
            parsed = datetime.fromisoformat(value)
            if parsed.utcoffset() is None:
                raise ValueError(f"mentor relationship {key} lacks timezone")
            return value, parsed

        invited_at, invited_time = parse_time("invited_at", required=True)
        expires_at, expires_time = parse_time("expires_at", required=True)
        accepted_at, accepted_time = parse_time("accepted_at", required=False)
        rejected_at, rejected_time = parse_time("rejected_at", required=False)
        graduated_at, graduated_time = parse_time("graduated_at", required=False)
        _, created_time = parse_time("created_at", required=True)
        if invited_time is None or expires_time is None or created_time is None:
            raise ValueError("mentor relationship timestamps are incomplete")
        if invited_time > expires_time or created_time > invited_time:
            raise ValueError("mentor relationship timestamps are out of order")
        if accepted_time is not None and accepted_time >= expires_time:
            raise ValueError("mentor relationship was accepted after expiry")
        if accepted_time is not None and accepted_time < invited_time:
            raise ValueError("mentor relationship acceptance precedes invitation")
        if graduated_time is not None and (accepted_time is None or graduated_time < accepted_time):
            raise ValueError("mentor relationship graduation is out of order")
        if status == "invited" and any(value is not None for value in (accepted_time, rejected_time, graduated_time)):
            raise ValueError("pending mentor relationship has terminal timestamps")
        if status == "active" and (accepted_time is None or rejected_time is not None or graduated_time is not None):
            raise ValueError("active mentor relationship timestamps are invalid")
        if status == "rejected" and (rejected_time is None or accepted_time is not None or graduated_time is not None):
            raise ValueError("rejected mentor relationship timestamps are invalid")
        if status == "expired" and any(value is not None for value in (accepted_time, rejected_time, graduated_time)):
            raise ValueError("expired mentor relationship timestamps are invalid")
        if status == "graduated" and (accepted_time is None or graduated_time is None or rejected_time is not None):
            raise ValueError("graduated mentor relationship timestamps are invalid")
        projected_status = "expired" if status == "invited" and now >= expires_time else status
        master_id = row["master_id"]
        apprentice_id = row["apprentice_id"]
        if type(master_id) is not int or type(apprentice_id) is not int or master_id == apprentice_id:
            raise ValueError("mentor relationship participants are invalid")
        if player_id == master_id:
            role = "master"
            counterpart = row["apprentice_dao_name"]
        elif player_id == apprentice_id:
            role = "apprentice"
            counterpart = row["master_dao_name"]
        else:
            raise ValueError("mentor relationship does not belong to player")
        master_dao_name = row["master_dao_name"]
        apprentice_dao_name = row["apprentice_dao_name"]
        if (
            not isinstance(counterpart, str)
            or not counterpart.strip()
            or not isinstance(master_dao_name, str)
            or not master_dao_name.strip()
            or not isinstance(apprentice_dao_name, str)
            or not apprentice_dao_name.strip()
        ):
            raise ValueError("mentor relationship counterpart is invalid")
        return MentorRelationView(
            relation_id=relation_id,
            role=role,
            counterpart_dao_name=counterpart.strip(),
            master_dao_name=master_dao_name.strip(),
            apprentice_dao_name=apprentice_dao_name.strip(),
            status=projected_status,
            invited_at=invited_at,
            expires_at=expires_at,
            accepted_at=accepted_at,
            rejected_at=rejected_at,
            graduated_at=graduated_at,
            master_contribution=row["master_contribution"],
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
            master = self._require_player(connection, platform, platform_user_id, writable=False)
            existing = operation_replay(connection, operation_id, operation_name, request_hash, player_id=int(master["id"]))
            if existing is not None:
                return self._mentor_record_from_payload(
                    connection, existing, operation_name=operation_name, replay=True,
                    expected_fields={"master_player_id": master["player_id"],
                                     "master_platform_user_id": platform_user_id,
                                     "apprentice_platform_user_id": target_user_id},
                )
            self._require_player(connection, platform, platform_user_id)
            self._mentor_expire_due(connection, now_text)
            if not is_master_eligible(str(master["realm_key"]), player_integer(master, "realm_layer")):
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
            if not is_apprentice_eligible(
                str(target["stage"]), str(target["realm_key"]), player_integer(target, "realm_layer")
            ):
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
                    created_at, updated_at
                ) VALUES (?, ?, ?, 'invited', ?, ?, NULL, NULL, NULL, NULL, 0, ?, ?)
                """,
                (
                    relation_id,
                    master["id"],
                    target["id"],
                    expires_at,
                    now_text,
                    now_text,
                    now_text,
                ),
            )
            payload = self._mentor_payload(connection, relation_id)
            record_operation(connection, operation_id, operation_name, int(master["id"]), request_hash, payload, now_text)
            return self._mentor_record_from_payload(connection, payload, operation_name=operation_name)

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
            apprentice = self._require_player(connection, platform, platform_user_id, writable=False)
            existing = operation_replay(connection, operation_id, operation_name, request_hash, player_id=int(apprentice["id"]))
            if existing is not None:
                return self._mentor_record_from_payload(
                    connection, existing, operation_name=operation_name, replay=True,
                    expected_fields={"relation_id": relation_id, "apprentice_player_id": apprentice["player_id"],
                                     "apprentice_platform_user_id": platform_user_id},
                )
            self._require_player(connection, platform, platform_user_id)
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
            if not is_master_eligible(str(master["realm_key"]), player_integer(master, "realm_layer")):
                raise MentorRequirementError("master no longer meets the mentor requirement")
            if not is_apprentice_eligible(
                str(apprentice["stage"]), str(apprentice["realm_key"]), player_integer(apprentice, "realm_layer")
            ):
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
            record_operation(connection, operation_id, operation_name, int(apprentice["id"]), request_hash, payload, now_text)
            return self._mentor_record_from_payload(connection, payload, operation_name=operation_name)

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
            apprentice = self._require_player(connection, platform, platform_user_id, writable=False)
            existing = operation_replay(connection, operation_id, operation_name, request_hash, player_id=int(apprentice["id"]))
            if existing is not None:
                return self._mentor_record_from_payload(
                    connection, existing, operation_name=operation_name, replay=True,
                    expected_fields={"relation_id": relation_id, "apprentice_player_id": apprentice["player_id"],
                                     "apprentice_platform_user_id": platform_user_id},
                )
            self._require_player(connection, platform, platform_user_id)
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
            record_operation(connection, operation_id, operation_name, int(apprentice["id"]), request_hash, payload, now_text)
            return self._mentor_record_from_payload(connection, payload, operation_name=operation_name)

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
            master = self._require_player(connection, platform, platform_user_id, writable=False)
            existing = operation_replay(connection, operation_id, operation_name, request_hash, player_id=int(master["id"]))
            if existing is not None:
                return self._mentor_record_from_payload(
                    connection, existing, operation_name=operation_name, replay=True,
                    expected_fields={"relation_id": relation_id, "master_player_id": master["player_id"],
                                     "master_platform_user_id": platform_user_id},
                )
            self._require_player(connection, platform, platform_user_id)
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
            definition = mentor_graduation_definition(self.content)
            if not is_graduation_ready(
                str(apprentice["stage"]), str(apprentice["realm_key"]), apprentice["realm_layer"],
                definition, self.content,
            ):
                raise MentorGraduationNotReadyError("apprentice has not reached the graduation realm after entry")
            if not self._mentor_has_completed_service(connection, int(apprentice["id"])):
                raise MentorGraduationNotReadyError("apprentice has not completed production or livelihood service")
            local_key = definition.local_reputation_key
            connection.execute(
                """
                UPDATE mentor_relations
                SET status = 'graduated', graduated_at = ?, graduate_operation_id = ?,
                    master_contribution = master_contribution + ?, updated_at = ?
                WHERE id = ? AND status = 'active'
                """,
                (now_text, operation_id, definition.master_contribution, now_text, relation["id"]),
            )
            apprentice_actual = change_player_state_actual(
                connection,
                apprentice,
                updated_at=now_text,
                local_reputation_delta={local_key: definition.apprentice_local_reputation},
                local_reputation_maximums={local_key: definition.local_reputation_maximum},
                service_reputation_delta=definition.service_reputation,
            )
            master_actual = change_player_state_actual(
                connection,
                master,
                updated_at=now_text,
                service_reputation_delta=definition.service_reputation,
            )
            # Sect contribution is the existing shared contribution ledger. The
            # relation row remains the source of truth when the mentor is not in a sect.
            sect_member = connection.execute(
                "SELECT sect_id FROM sect_members WHERE player_id = ? AND status = 'active'",
                (master["id"],),
            ).fetchone()
            connection.execute(
                """
                UPDATE sect_members
                SET contribution = contribution + ?, last_action_at = ?, updated_at = ?
                WHERE player_id = ? AND status = 'active'
                """,
                (definition.master_contribution, now_text, now_text, master["id"]),
            )
            if sect_member is not None and definition.master_contribution:
                connection.execute(
                    "INSERT INTO sect_contribution_events(sect_id, player_id, source_operation_id, quantity, occurred_at) VALUES (?, ?, ?, ?, ?)",
                    (sect_member["sect_id"], master["id"], operation_id, definition.master_contribution, now_text),
                )
            payload = self._mentor_payload(
                connection,
                relation_id,
                apprentice_local_reputation=apprentice_actual[local_key],
                apprentice_service_reputation_gain=apprentice_actual["service_reputation"],
                master_service_reputation_gain=master_actual["service_reputation"],
            )
            payload["graduation_rules"] = definition.snapshot()
            record_operation(connection, operation_id, operation_name, int(master["id"]), request_hash, payload, now_text)
            return self._mentor_record_from_payload(connection, payload, operation_name=operation_name)

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
        apprentice_service_reputation_gain: int = 0,
        master_service_reputation_gain: int = 0,
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
            "apprentice_service_reputation_gain": int(apprentice_service_reputation_gain),
            "master_service_reputation_gain": int(master_service_reputation_gain),
        }

    @staticmethod
    def _mentor_record_from_payload(
        connection: Any, payload: dict[str, Any], *, operation_name: str, replay: bool = False,
        expected_fields: dict[str, Any] | None = None,
    ) -> MentorRelationRecord:
        record_fields = {field.name for field in fields(MentorRelationRecord)} - {"already_completed"}
        graduating = operation_name == "social.graduate_apprentice"
        expected = record_fields | ({"graduation_rules"} if graduating else set())
        if set(payload) != expected:
            raise ValueError("mentor result fields are incomplete or unsupported")
        rewards = {"master_contribution", "apprentice_local_reputation",
                   "apprentice_service_reputation_gain", "master_service_reputation_gain"}
        for key in record_fields:
            value = payload[key]
            if key in rewards:
                if type(value) is not int or value < 0:
                    raise ValueError(f"mentor result {key} is invalid")
            elif key in {"accepted_at", "graduated_at"} and value is None:
                continue
            elif not isinstance(value, str) or not value.strip():
                raise ValueError(f"mentor result {key} is invalid")
        expected_status = {
            "social.invite_mentor": "invited", "social.accept_mentor": "active",
            "social.reject_mentor": "rejected", "social.graduate_apprentice": "graduated",
        }[operation_name]
        if payload["status"] != expected_status:
            raise ValueError("mentor result state differs from its operation")
        if payload["master_player_id"] == payload["apprentice_player_id"]:
            raise ValueError("mentor result participants must differ")
        times = {
            key: datetime.fromisoformat(payload[key]) if payload[key] is not None else None
            for key in ("expires_at", "accepted_at", "graduated_at")
        }
        if any(value is not None and value.utcoffset() is None for value in times.values()):
            raise ValueError("mentor result timestamps must have timezones")
        accepted, graduated = times["accepted_at"], times["graduated_at"]
        if (accepted is not None) != (expected_status in {"active", "graduated"}):
            raise ValueError("mentor result acceptance time differs from its state")
        if (graduated is not None) != graduating:
            raise ValueError("mentor result graduation time differs from its state")
        if accepted is not None and accepted >= times["expires_at"]:
            raise ValueError("mentor result was accepted after its invitation expired")
        if graduating:
            if graduated < accepted:
                raise ValueError("mentor result was graduated before acceptance")
            definition = mentor_graduation_from_snapshot(payload["graduation_rules"])
            if (
                payload["master_contribution"] != definition.master_contribution
                or payload["apprentice_local_reputation"] > min(definition.apprentice_local_reputation, definition.local_reputation_maximum)
                or payload["apprentice_service_reputation_gain"] > definition.service_reputation
                or payload["master_service_reputation_gain"] > definition.service_reputation
            ):
                raise ValueError("mentor result reward differs from its rules")
        elif any(payload[key] for key in rewards):
            raise ValueError("ungraduated mentor result cannot contain rewards")
        if expected_fields is not None and any(payload[key] != value for key, value in expected_fields.items()):
            raise ValueError("mentor result differs from its request")
        if replay:
            participants = connection.execute(
                """SELECT mp.player_id AS master_player_id, mp.platform_user_id AS master_platform_user_id,
                          ap.player_id AS apprentice_player_id, ap.platform_user_id AS apprentice_platform_user_id
                   FROM mentor_relations r JOIN players mp ON mp.id=r.master_id
                   JOIN players ap ON ap.id=r.apprentice_id WHERE r.relation_id=?""",
                (payload["relation_id"],),
            ).fetchone()
            if participants is None or any(payload[key] != participants[key] for key in participants.keys()):
                raise ValueError("mentor result participants differ from its relation")
        return MentorRelationRecord(**{key: payload[key] for key in record_fields}, already_completed=replay)


__all__ = ["MentorRepositoryMixin"]
