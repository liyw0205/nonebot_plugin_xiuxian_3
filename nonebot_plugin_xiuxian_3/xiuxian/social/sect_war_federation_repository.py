"""Read-only federation preparation for cross-server sect wars.

This module freezes local roster evidence and accepts an audited remote result.
It deliberately exposes no matching or asset-transfer command.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Mapping
from uuid import uuid4

from ...contracts import serialize_datetime
from ..persistence.errors import OperationConflictError, SectNotFoundError, SectWarRequirementError
from .sect_war_federation_models import SectWarFederationResultRecord, SectWarFederationSnapshotRecord
from .sect_war_federation_rules import (
    CROSS_SERVER_ROSTER_CAP,
    CROSS_SERVER_SECT_WAR_CONTENT_VERSION,
    CROSS_SERVER_SECT_WAR_RULE_VERSION,
    federation_snapshot_id,
)


class SectWarFederationRepositoryMixin:
    """Freeze and audit federation inputs without opening cross-server play."""

    async def freeze_sect_war_federation_snapshot(
        self,
        *,
        platform: str,
        platform_user_id: str,
        round_id: str,
        shard_key: str = "local",
        operation_id: str,
    ) -> SectWarFederationSnapshotRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._freeze_sect_war_federation_snapshot_once,
                platform,
                platform_user_id,
                round_id,
                shard_key,
                operation_id,
            )

    async def import_sect_war_federation_result(
        self,
        *,
        platform: str,
        platform_user_id: str,
        round_id: str,
        shard_key: str,
        sect_id: str,
        score: int,
        winner: bool,
        source_operation_id: str,
        operation_id: str,
        result_id: str | None = None,
    ) -> SectWarFederationResultRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._import_sect_war_federation_result_once,
                platform,
                platform_user_id,
                round_id,
                shard_key,
                sect_id,
                score,
                winner,
                source_operation_id,
                operation_id,
                result_id,
            )

    def _freeze_sect_war_federation_snapshot_once(
        self,
        platform: str,
        platform_user_id: str,
        round_id: str,
        shard_key: str,
        operation_id: str,
    ) -> SectWarFederationSnapshotRecord:
        operation_name = "social.sect_war_federation.freeze"
        request_hash = self._request_hash(
            operation_name,
            {
                "platform": platform,
                "platform_user_id": platform_user_id,
                "round_id": round_id,
                "shard_key": shard_key,
            },
        )
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._federation_operation(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                return self._sect_war_federation_snapshot_from_payload(replay, already_completed=True)
            player = self._require_player(connection, platform, platform_user_id)
            membership = connection.execute(
                "SELECT sect_id, role FROM sect_members WHERE player_id=? AND status='active'",
                (player["id"],),
            ).fetchone()
            if membership is None:
                raise SectNotFoundError("player is not in a sect")
            if str(membership["role"]) not in {"leader", "vice_leader"}:
                raise SectWarRequirementError("only a sect leader can freeze a federation snapshot")
            registration = connection.execute(
                "SELECT * FROM sect_war_registrations WHERE round_id=? AND sect_id=? AND status='registered'",
                (round_id, membership["sect_id"]),
            ).fetchone()
            if registration is None:
                raise SectWarRequirementError("sect is not registered for this round")
            members = connection.execute(
                "SELECT player_id, roster_slot, contribution, snapshot_json FROM sect_war_members "
                "WHERE round_id=? AND sect_id=? ORDER BY roster_slot LIMIT ?",
                (round_id, membership["sect_id"], CROSS_SERVER_ROSTER_CAP),
            ).fetchall()
            if not members or len(members) > CROSS_SERVER_ROSTER_CAP:
                raise SectWarRequirementError("federation roster is outside the allowed cap")
            sect = connection.execute(
                "SELECT sect_id, name, level FROM sects WHERE sect_id=? AND status='active'",
                (membership["sect_id"],),
            ).fetchone()
            if sect is None:
                raise SectNotFoundError("sect does not exist")
            snapshot_id = federation_snapshot_id(round_id, shard_key, str(sect["sect_id"]))
            snapshot = {
                "round_id": round_id,
                "shard_key": shard_key,
                "sect_id": str(sect["sect_id"]),
                "sect_name": str(sect["name"]),
                "level": int(sect["level"]),
                "members": [
                    {
                        "player_id": int(member["player_id"]),
                        "roster_slot": int(member["roster_slot"]),
                        "contribution": int(member["contribution"]),
                        "snapshot": self._json_map(member["snapshot_json"]),
                    }
                    for member in members
                ],
                "source_registration_operation_id": str(registration["operation_id"]),
            }
            connection.execute(
                "INSERT INTO sect_war_federation_snapshots(snapshot_id,round_id,shard_key,sect_id,roster_size,status,snapshot_json,content_version,rule_version,frozen_at,created_at,updated_at) "
                "VALUES (?, ?, ?, ?, ?, 'frozen', ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(round_id,shard_key,sect_id) DO UPDATE SET status='frozen', snapshot_json=excluded.snapshot_json, roster_size=excluded.roster_size, frozen_at=excluded.frozen_at, updated_at=excluded.updated_at",
                (
                    snapshot_id,
                    round_id,
                    shard_key,
                    sect["sect_id"],
                    len(members),
                    json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
                    CROSS_SERVER_SECT_WAR_CONTENT_VERSION,
                    CROSS_SERVER_SECT_WAR_RULE_VERSION,
                    now_text,
                    now_text,
                    now_text,
                ),
            )
            payload = {
                "snapshot_id": snapshot_id,
                "round_id": round_id,
                "shard_key": shard_key,
                "sect_id": str(sect["sect_id"]),
                "roster_size": len(members),
                "frozen_at": now_text,
            }
            self._federation_insert_operation(connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text)
            return self._sect_war_federation_snapshot_from_payload(payload)

    def _import_sect_war_federation_result_once(
        self,
        platform: str,
        platform_user_id: str,
        round_id: str,
        shard_key: str,
        sect_id: str,
        score: int,
        winner: bool,
        source_operation_id: str,
        operation_id: str,
        result_id: str | None,
    ) -> SectWarFederationResultRecord:
        operation_name = "social.sect_war_federation.import_result"
        request_payload = {
            "platform": platform,
            "platform_user_id": platform_user_id,
            "round_id": round_id,
            "shard_key": shard_key,
            "sect_id": sect_id,
            "score": score,
            "winner": bool(winner),
            "source_operation_id": source_operation_id,
            "result_id": result_id or "",
        }
        request_hash = self._request_hash(operation_name, request_payload)
        now_text = serialize_datetime(self._now())
        if int(score) < 0 or not source_operation_id.strip():
            raise SectWarRequirementError("federation result is invalid")
        result_id = result_id or f"sect-war.federation-result:{uuid4().hex}"
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._federation_operation(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                return self._result_from_payload(replay, already_completed=True)
            player = self._require_player(connection, platform, platform_user_id, writable=False)
            existing = connection.execute(
                "SELECT result_id,round_id,shard_key,sect_id,score,winner FROM sect_war_federation_results "
                "WHERE result_id=? OR source_operation_id=? OR (round_id=? AND shard_key=? AND sect_id=?)",
                (result_id, source_operation_id, round_id, shard_key, sect_id),
            ).fetchone()
            if existing is not None:
                if (
                    str(existing["round_id"]),
                    str(existing["shard_key"]),
                    str(existing["sect_id"]),
                    int(existing["score"]),
                    bool(existing["winner"]),
                ) != (round_id, shard_key, sect_id, int(score), bool(winner)):
                    raise OperationConflictError("federation result differs from its original import")
                payload = self._result_payload(existing)
                self._federation_insert_operation(connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text)
                return self._result_from_payload(payload, already_completed=True)
            payload = {
                "result_id": result_id,
                "round_id": round_id,
                "shard_key": shard_key,
                "sect_id": sect_id,
                "score": int(score),
                "winner": bool(winner),
                "source_operation_id": source_operation_id,
                "imported_at": now_text,
            }
            connection.execute(
                "INSERT INTO sect_war_federation_results(result_id,round_id,shard_key,sect_id,score,winner,source_operation_id,result_json,content_version,rule_version,imported_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    result_id,
                    round_id,
                    shard_key,
                    sect_id,
                    int(score),
                    1 if winner else 0,
                    source_operation_id,
                    json.dumps(payload, ensure_ascii=False, sort_keys=True),
                    CROSS_SERVER_SECT_WAR_CONTENT_VERSION,
                    CROSS_SERVER_SECT_WAR_RULE_VERSION,
                    now_text,
                ),
            )
            self._federation_insert_operation(connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text)
            return self._result_from_payload(payload)

    @staticmethod
    def _federation_operation(connection: Any, operation_id: str, operation_name: str, request_hash: str) -> dict[str, Any] | None:
        row = connection.execute(
            "SELECT operation_name,request_hash,result_json FROM operations WHERE operation_id=?",
            (operation_id,),
        ).fetchone()
        if row is None:
            return None
        if row["operation_name"] != operation_name or row["request_hash"] != request_hash:
            raise OperationConflictError("operation input differs from its original request")
        return json.loads(row["result_json"])

    @staticmethod
    def _federation_insert_operation(connection: Any, operation_id: str, operation_name: str, player_id: int, request_hash: str, payload: Mapping[str, object], now_text: str) -> None:
        connection.execute(
            "INSERT INTO operations(operation_id,operation_name,player_id,request_hash,result_json,created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (operation_id, operation_name, player_id, request_hash, json.dumps(dict(payload), ensure_ascii=False, sort_keys=True), now_text),
        )

    @staticmethod
    def _sect_war_federation_snapshot_from_payload(payload: Mapping[str, object], *, already_completed: bool = False) -> SectWarFederationSnapshotRecord:
        return SectWarFederationSnapshotRecord(
            str(payload["snapshot_id"]),
            str(payload["round_id"]),
            str(payload["shard_key"]),
            str(payload["sect_id"]),
            int(payload["roster_size"]),
            str(payload["frozen_at"]),
            already_completed,
        )

    @staticmethod
    def _result_payload(row: Any) -> dict[str, object]:
        return {
            "result_id": str(row["result_id"]),
            "round_id": str(row["round_id"]),
            "shard_key": str(row["shard_key"]),
            "sect_id": str(row["sect_id"]),
            "score": int(row["score"]),
            "winner": bool(row["winner"]),
        }

    @staticmethod
    def _result_from_payload(payload: Mapping[str, object], *, already_completed: bool = False) -> SectWarFederationResultRecord:
        return SectWarFederationResultRecord(
            str(payload["result_id"]),
            str(payload["round_id"]),
            str(payload["shard_key"]),
            str(payload["sect_id"]),
            int(payload["score"]),
            bool(payload["winner"]),
            already_completed,
        )


__all__ = ["SectWarFederationRepositoryMixin"]
