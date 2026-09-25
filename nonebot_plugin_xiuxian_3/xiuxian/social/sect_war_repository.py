"""Persistence and deterministic settlement for v0.3 sect-war rounds."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from ...contracts import serialize_datetime
from ..persistence.errors import (
    OperationConflictError,
    SectNotFoundError,
    SectWarParticipantCapError,
    SectWarRegistrationClosedError,
    SectWarRequirementError,
    SectWarRewardAlreadyClaimedError,
    SectWarRewardNotEligibleError,
    SectWarRewardExpiredError,
    SectWarRoundNotActiveError,
    SectWarSourceInvalidError,
)
from .sect_war_models import SectWarClaimRecord, SectWarRecord, SectWarStanding
from .sect_war_rules import (
    SECT_WAR_MAX_PARTICIPANTS,
    SECT_WAR_MEMBER_REWARD,
    SECT_WAR_MEMBER_THRESHOLD,
    SECT_WAR_MIN_LEVEL,
    SECT_WAR_REGISTRATION_FEE,
    SECT_WAR_SECT_REWARD,
    contribution_value,
    sect_war_round_for_id,
    sect_war_round_window,
)


class SectWarRepositoryMixin:
    """Keep roster snapshots, source operations and rewards in one transaction."""

    async def get_sect_war(
        self, *, platform: str, platform_user_id: str, round_id: str | None = None
    ) -> SectWarRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._sect_war_get_once, platform, platform_user_id, round_id)

    async def register_sect_war(
        self, *, platform: str, platform_user_id: str, round_id: str | None, operation_id: str
    ) -> SectWarRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._sect_war_register_once, platform, platform_user_id, round_id, operation_id
            )

    async def contribute_sect_war(
        self,
        *,
        platform: str,
        platform_user_id: str,
        action_key: str,
        source_operation_id: str | None,
        round_id: str | None,
        operation_id: str,
    ) -> SectWarRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._sect_war_contribute_once,
                platform,
                platform_user_id,
                action_key,
                source_operation_id,
                round_id,
                operation_id,
            )

    async def claim_sect_war_reward(
        self, *, platform: str, platform_user_id: str, round_id: str, operation_id: str
    ) -> SectWarClaimRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._sect_war_claim_once, platform, platform_user_id, round_id, operation_id
            )

    def _sect_war_get_once(self, platform: str, platform_user_id: str, requested_id: str | None) -> SectWarRecord:
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            player = self._require_player(connection, platform, platform_user_id, writable=False)
            round_row = self._sect_war_prepare(connection, requested_id, now, now_text)
            return self._sect_war_record(connection, round_row, int(player["id"]))

    def _sect_war_register_once(
        self, platform: str, platform_user_id: str, requested_id: str | None, operation_id: str
    ) -> SectWarRecord:
        operation_name = "social.sect_war.register"
        request_hash = self._request_hash(
            operation_name,
            {"platform": platform, "platform_user_id": platform_user_id, "round_id": requested_id or ""},
        )
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._sect_war_operation_replay(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                round_row = connection.execute(
                    "SELECT * FROM sect_war_rounds WHERE round_id=?", (replay["round_id"],)
                ).fetchone()
                player = self._require_player(connection, platform, platform_user_id, writable=False)
                return self._sect_war_record(connection, round_row, int(player["id"]), already_completed=True)
            player = self._require_player(connection, platform, platform_user_id)
            round_row = self._sect_war_prepare(connection, requested_id, now, now_text)
            starts_at = datetime.fromisoformat(str(round_row["starts_at"]))
            if now < datetime.fromisoformat(str(round_row["registration_open_at"])) or now >= starts_at:
                raise SectWarRegistrationClosedError("sect-war registration is closed")
            membership = connection.execute(
                "SELECT * FROM sect_members WHERE player_id=? AND status='active'", (player["id"],)
            ).fetchone()
            if membership is None:
                raise SectNotFoundError("player is not in a sect")
            if str(membership["role"]) != "leader":
                raise SectWarRequirementError("only the sect leader can register")
            sect = connection.execute(
                "SELECT * FROM sects WHERE sect_id=? AND status='active'", (membership["sect_id"],)
            ).fetchone()
            if sect is None:
                raise SectNotFoundError("sect does not exist")
            if int(sect["level"]) < SECT_WAR_MIN_LEVEL:
                raise SectWarRequirementError("sect level is too low")
            if connection.execute(
                "SELECT 1 FROM sect_war_registrations WHERE round_id=? AND sect_id=? AND status='registered'",
                (round_row["round_id"], sect["sect_id"]),
            ).fetchone() is not None:
                raise SectWarRequirementError("sect is already registered")
            updated = connection.execute(
                "UPDATE sects SET spirit_stones=spirit_stones-?, updated_at=? WHERE sect_id=? AND spirit_stones>=?",
                (SECT_WAR_REGISTRATION_FEE, now_text, sect["sect_id"], SECT_WAR_REGISTRATION_FEE),
            ).rowcount
            if updated != 1:
                raise SectWarRequirementError("sect registration fee is insufficient")
            members = connection.execute(
                "SELECT p.* FROM sect_members m JOIN players p ON p.id=m.player_id "
                "WHERE m.sect_id=? AND m.status='active' ORDER BY m.contribution DESC, m.id ASC LIMIT ?",
                (sect["sect_id"], SECT_WAR_MAX_PARTICIPANTS),
            ).fetchall()
            if not members:
                raise SectWarParticipantCapError("sect has no active participants")
            snapshot = {"sect_id": str(sect["sect_id"]), "level": int(sect["level"]), "members": []}
            for slot, member in enumerate(members, start=1):
                member_snapshot = {
                    "player_id": int(member["id"]),
                    "realm_key": str(member["realm_key"]),
                    "realm_layer": int(member["realm_layer"]),
                    "cultivation": int(member["cultivation"]),
                }
                snapshot["members"].append(member_snapshot)
            connection.execute(
                "INSERT INTO sect_war_registrations(round_id,sect_id,operation_id,entry_fee,status,snapshot_json,registered_at) VALUES (?, ?, ?, ?, 'registered', ?, ?)",
                (round_row["round_id"], sect["sect_id"], operation_id, SECT_WAR_REGISTRATION_FEE, json.dumps(snapshot, sort_keys=True), now_text),
            )
            for slot, member in enumerate(members, start=1):
                member_snapshot = snapshot["members"][slot - 1]
                connection.execute(
                    "INSERT INTO sect_war_members(round_id,sect_id,player_id,roster_slot,snapshot_json,created_at,updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (round_row["round_id"], sect["sect_id"], member["id"], slot, json.dumps(member_snapshot, sort_keys=True), now_text, now_text),
                )
            connection.execute("UPDATE sect_war_rounds SET status='open', updated_at=? WHERE round_id=?", (now_text, round_row["round_id"]))
            payload = {"round_id": str(round_row["round_id"]), "sect_id": str(sect["sect_id"]), "participant_count": len(members)}
            self._sect_war_insert_operation(connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text)
            round_row = connection.execute("SELECT * FROM sect_war_rounds WHERE round_id=?", (round_row["round_id"],)).fetchone()
            return self._sect_war_record(connection, round_row, int(player["id"]))

    def _sect_war_contribute_once(
        self,
        platform: str,
        platform_user_id: str,
        action_key: str,
        source_operation_id: str | None,
        requested_id: str | None,
        operation_id: str,
    ) -> SectWarRecord:
        operation_name = "social.sect_war.contribute"
        request_hash = self._request_hash(
            operation_name,
            {"platform": platform, "platform_user_id": platform_user_id, "action_key": action_key, "source_operation_id": source_operation_id or "", "round_id": requested_id or ""},
        )
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._sect_war_operation_replay(connection, operation_id, operation_name, request_hash)
            player = self._require_player(connection, platform, platform_user_id)
            if replay is not None:
                row = connection.execute("SELECT * FROM sect_war_rounds WHERE round_id=?", (replay["round_id"],)).fetchone()
                return self._sect_war_record(connection, row, int(player["id"]), already_completed=True)
            round_row = self._sect_war_prepare(connection, requested_id, now, now_text)
            if str(round_row["status"]) != "running" or now >= datetime.fromisoformat(str(round_row["ends_at"])):
                raise SectWarRoundNotActiveError("sect-war round is not running")
            member = connection.execute(
                "SELECT * FROM sect_war_members WHERE round_id=? AND player_id=?", (round_row["round_id"], player["id"])
            ).fetchone()
            if member is None:
                raise SectWarRequirementError("player is not in the war roster")
            source_id = source_operation_id
            if not source_id:
                source = connection.execute(
                    "SELECT operation_id FROM operations o WHERE o.player_id=? AND NOT EXISTS (SELECT 1 FROM sect_war_actions a WHERE a.round_id=? AND a.player_id=? AND a.source_operation_id=o.operation_id) ORDER BY o.created_at DESC LIMIT 1",
                    (player["id"], round_row["round_id"], player["id"]),
                ).fetchone()
                source_id = str(source["operation_id"]) if source else None
            source_row = connection.execute("SELECT operation_id FROM operations WHERE operation_id=? AND player_id=?", (source_id, player["id"])).fetchone() if source_id else None
            if source_row is None:
                raise SectWarSourceInvalidError("source operation is not owned by the actor")
            if connection.execute(
                "SELECT 1 FROM sect_war_actions WHERE round_id=? AND player_id=? AND source_operation_id=?",
                (round_row["round_id"], player["id"], source_id),
            ).fetchone() is not None:
                raise SectWarSourceInvalidError("source operation already scored in this round")
            try:
                score = contribution_value(action_key, 1)
            except ValueError as exc:
                raise SectWarSourceInvalidError(str(exc)) from exc
            limits = {"运输": 4, "维修": 4, "击败": 3, "占点": 2}
            used = int(connection.execute("SELECT COUNT(*) FROM sect_war_actions WHERE round_id=? AND player_id=? AND action_key=?", (round_row["round_id"], player["id"], action_key)).fetchone()[0])
            if used >= limits[action_key]:
                raise SectWarSourceInvalidError("action limit reached")
            connection.execute(
                "INSERT INTO sect_war_actions(action_id,round_id,sect_id,player_id,source_operation_id,action_key,score,occurred_at,operation_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (uuid4().hex, round_row["round_id"], member["sect_id"], player["id"], source_id, action_key, score, now_text, operation_id),
            )
            connection.execute("UPDATE sect_war_members SET contribution=contribution+?, updated_at=? WHERE round_id=? AND player_id=?", (score, now_text, round_row["round_id"], player["id"]))
            payload = {"round_id": str(round_row["round_id"]), "action_key": action_key, "score": score, "source_operation_id": source_id}
            self._sect_war_insert_operation(connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text)
            return self._sect_war_record(connection, round_row, int(player["id"]))

    def _sect_war_claim_once(self, platform: str, platform_user_id: str, requested_id: str, operation_id: str) -> SectWarClaimRecord:
        operation_name = "social.sect_war.claim"
        request_hash = self._request_hash(operation_name, {"platform": platform, "platform_user_id": platform_user_id, "round_id": requested_id})
        now = self._now()
        now_text = serialize_datetime(now)
        canonical, _, _, _, claim_until = sect_war_round_for_id(requested_id)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute("SELECT operation_name,request_hash,result_json FROM operations WHERE operation_id=?", (operation_id,)).fetchone()
            if existing is not None:
                if existing["operation_name"] != operation_name or existing["request_hash"] != request_hash:
                    raise OperationConflictError("operation input differs from its original request")
                return self._sect_war_claim_from_payload(json.loads(existing["result_json"]), replay=True)
            player = self._require_player(connection, platform, platform_user_id, writable=False)
            round_row = self._sect_war_prepare(connection, canonical, now, now_text)
            if str(round_row["status"]) != "settled":
                raise SectWarRoundNotActiveError("sect-war round is not settled")
            previous = connection.execute("SELECT reward_json,status FROM sect_war_claims WHERE round_id=? AND player_id=?", (canonical, player["id"])).fetchone()
            if previous is not None:
                if now >= claim_until:
                    payload = {"round_id": canonical, "reward": json.loads(previous["reward_json"]), "claimed_at": now_text, "expired": True}
                    self._sect_war_insert_operation(connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text)
                    return self._sect_war_claim_from_payload(payload)
                raise SectWarRewardAlreadyClaimedError("sect-war reward already claimed")
            if now >= claim_until:
                payload = {"round_id": canonical, "reward": {}, "claimed_at": now_text, "expired": True}
                self._sect_war_insert_operation(connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text)
                raise SectWarRewardExpiredError("sect-war claim window expired")
            member = connection.execute("SELECT contribution FROM sect_war_members WHERE round_id=? AND player_id=?", (canonical, player["id"])).fetchone()
            if member is None or int(member["contribution"]) < SECT_WAR_MEMBER_THRESHOLD:
                raise SectWarRewardNotEligibleError("war contribution threshold is not met")
            reward = {"world_merit": SECT_WAR_MEMBER_REWARD}
            connection.execute("UPDATE players SET world_merit=world_merit+?, updated_at=? WHERE id=?", (SECT_WAR_MEMBER_REWARD, now_text, player["id"]))
            connection.execute("INSERT INTO sect_war_claims(round_id,player_id,operation_id,reward_json,status,claimed_at) VALUES (?, ?, ?, ?, 'claimed', ?)", (canonical, player["id"], operation_id, json.dumps(reward, sort_keys=True), now_text))
            payload = {"round_id": canonical, "reward": reward, "claimed_at": now_text, "expired": False}
            self._sect_war_insert_operation(connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text)
            return self._sect_war_claim_from_payload(payload)

    def _sect_war_prepare(self, connection: Any, requested_id: str | None, now: datetime, now_text: str) -> Any:
        if requested_id is None:
            candidates = [sect_war_round_window(now, index)[0] for index in range(2)]
            selected = None
            for candidate in candidates:
                _, _, starts, _, claim = sect_war_round_for_id(candidate)
                if now < claim:
                    selected = candidate
                    break
            if selected is None:
                selected = sect_war_round_window(now + timedelta(days=7), 0)[0]
        else:
            selected, _, _, _, _ = sect_war_round_for_id(requested_id)
        for round_id in {selected, *[sect_war_round_window(now, index)[0] for index in range(2)]}:
            _, registration_open, starts_at, ends_at, claim_expires_at = sect_war_round_for_id(round_id)
            connection.execute(
                "INSERT OR IGNORE INTO sect_war_rounds(round_id,registration_open_at,registration_close_at,starts_at,ends_at,claim_expires_at,status,created_at,updated_at) VALUES (?, ?, ?, ?, ?, ?, 'scheduled', ?, ?)",
                (round_id, serialize_datetime(registration_open), serialize_datetime(starts_at), serialize_datetime(starts_at), serialize_datetime(ends_at), serialize_datetime(claim_expires_at), now_text, now_text),
            )
        rows = connection.execute("SELECT * FROM sect_war_rounds").fetchall()
        for row in rows:
            _, _, starts_at, ends_at, claim_expires_at = sect_war_round_for_id(str(row["round_id"]))
            if str(row["status"]) in {"scheduled", "open", "running"} and now >= ends_at:
                self._sect_war_settle(connection, row, now_text)
            elif str(row["status"]) in {"scheduled", "open"} and now >= starts_at:
                connection.execute("UPDATE sect_war_rounds SET status='running', updated_at=? WHERE round_id=?", (now_text, row["round_id"]))
            elif str(row["status"]) == "scheduled" and now >= datetime.fromisoformat(str(row["registration_open_at"])):
                connection.execute("UPDATE sect_war_rounds SET status='open', updated_at=? WHERE round_id=?", (now_text, row["round_id"]))
            if now >= claim_expires_at:
                self._sect_war_auto_grant(connection, str(row["round_id"]), now_text)
        return connection.execute("SELECT * FROM sect_war_rounds WHERE round_id=?", (selected,)).fetchone()

    @staticmethod
    def _sect_war_settle(connection: Any, row: Any, now_text: str) -> None:
        round_id = str(row["round_id"])
        standings = connection.execute("SELECT r.sect_id, s.name, COALESCE(SUM(m.contribution),0) AS score FROM sect_war_registrations r JOIN sects s ON s.sect_id=r.sect_id LEFT JOIN sect_war_members m ON m.round_id=r.round_id AND m.sect_id=r.sect_id WHERE r.round_id=? AND r.status='registered' GROUP BY r.sect_id ORDER BY score DESC, r.sect_id", (round_id,)).fetchall()
        winner = str(standings[0]["sect_id"]) if standings else None
        if winner:
            connection.execute("UPDATE sects SET sect_merit=sect_merit+?, updated_at=? WHERE sect_id=?", (SECT_WAR_SECT_REWARD, now_text, winner))
        snapshot = {"winner_sect_id": winner, "standings": [{"sect_id": str(value["sect_id"]), "score": int(value["score"])} for value in standings]}
        connection.execute("UPDATE sect_war_rounds SET status='settled', winner_sect_id=?, snapshot_json=?, updated_at=? WHERE round_id=? AND status IN ('scheduled','open','running')", (winner, json.dumps(snapshot, sort_keys=True), now_text, round_id))

    @staticmethod
    def _sect_war_auto_grant(connection: Any, round_id: str, now_text: str) -> None:
        members = connection.execute("SELECT player_id,contribution FROM sect_war_members WHERE round_id=? AND contribution>=?", (round_id, SECT_WAR_MEMBER_THRESHOLD)).fetchall()
        for member in members:
            if connection.execute("SELECT 1 FROM sect_war_claims WHERE round_id=? AND player_id=?", (round_id, member["player_id"])).fetchone() is not None:
                continue
            reward = {"world_merit": SECT_WAR_MEMBER_REWARD}
            connection.execute("UPDATE players SET world_merit=world_merit+?, updated_at=? WHERE id=?", (SECT_WAR_MEMBER_REWARD, now_text, member["player_id"]))
            connection.execute("INSERT INTO sect_war_claims(round_id,player_id,operation_id,reward_json,status,claimed_at,auto_granted_at) VALUES (?, ?, ?, ?, 'auto_granted', ?, ?)", (round_id, member["player_id"], f"sect-war.auto:{round_id}:{member['player_id']}", json.dumps(reward, sort_keys=True), now_text, now_text))

    def _sect_war_record(self, connection: Any, row: Any, player_id: int, *, already_completed: bool = False) -> SectWarRecord:
        own = connection.execute("SELECT m.contribution,r.sect_id,s.name FROM sect_war_members m JOIN sect_war_registrations r ON r.round_id=m.round_id AND r.sect_id=m.sect_id JOIN sects s ON s.sect_id=m.sect_id WHERE m.round_id=? AND m.player_id=?", (row["round_id"], player_id)).fetchone()
        standings_rows = connection.execute("SELECT r.sect_id,s.name,COALESCE(SUM(m.contribution),0) AS score FROM sect_war_registrations r JOIN sects s ON s.sect_id=r.sect_id LEFT JOIN sect_war_members m ON m.round_id=r.round_id AND m.sect_id=r.sect_id WHERE r.round_id=? AND r.status='registered' GROUP BY r.sect_id ORDER BY score DESC,r.sect_id", (row["round_id"],)).fetchall()
        standings = tuple(SectWarStanding(str(value["sect_id"]), str(value["name"]), int(value["score"]), rank) for rank, value in enumerate(standings_rows, start=1))
        participants = int(connection.execute("SELECT COUNT(*) FROM sect_war_members WHERE round_id=?", (row["round_id"],)).fetchone()[0])
        return SectWarRecord(str(row["round_id"]), str(row["status"]), str(row["registration_open_at"]), str(row["starts_at"]), str(row["ends_at"]), str(row["claim_expires_at"]), own is not None, str(own["sect_id"]) if own else None, str(own["name"]) if own else None, participants, int(own["contribution"]) if own else 0, standings, str(row["winner_sect_id"]) if row["winner_sect_id"] else None, already_completed)

    @staticmethod
    def _sect_war_operation_replay(connection: Any, operation_id: str, operation_name: str, request_hash: str) -> dict[str, Any] | None:
        row = connection.execute("SELECT operation_name,request_hash,result_json FROM operations WHERE operation_id=?", (operation_id,)).fetchone()
        if row is None:
            return None
        if row["operation_name"] != operation_name or row["request_hash"] != request_hash:
            raise OperationConflictError("operation input differs from its original request")
        return json.loads(row["result_json"])

    @staticmethod
    def _sect_war_insert_operation(connection: Any, operation_id: str, operation_name: str, player_id: int, request_hash: str, payload: dict[str, object], now_text: str) -> None:
        connection.execute("INSERT INTO operations(operation_id,operation_name,player_id,request_hash,result_json,created_at) VALUES (?, ?, ?, ?, ?, ?)", (operation_id, operation_name, player_id, request_hash, json.dumps(payload, ensure_ascii=False, sort_keys=True), now_text))

    @staticmethod
    def _sect_war_claim_from_payload(payload: dict[str, object], replay: bool = False) -> SectWarClaimRecord:
        return SectWarClaimRecord(str(payload["round_id"]), {str(key): int(value) for key, value in dict(payload.get("reward", {})).items()}, str(payload["claimed_at"]), replay, bool(payload.get("expired", False)))


__all__ = ["SectWarRepositoryMixin"]
