"""Persistence for the dao-origin solo secret realm."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from ...contracts import serialize_datetime
from ..persistence.errors import (
    DaoOriginBusyError,
    DaoOriginNodeError,
    DaoOriginNotFoundError,
    DaoOriginNotReadyError,
    DaoOriginQuotaError,
    DaoOriginRequirementError,
    OperationConflictError,
    ResourceInsufficientError,
)
from ..specials.codex_projection import record_codex_discovery
from ..utils.player import change_player_state, player_integer
from .dao_origin_models import DaoOriginRunRecord
from .dao_origin_rules import (
    DAO_ORIGIN_CODEX,
    DAO_ORIGIN_EXPIRY_SECONDS,
    DAO_ORIGIN_KEY,
    DAO_ORIGIN_LOCATION,
    DAO_ORIGIN_NODES,
    DAO_ORIGIN_PERMISSION,
    DAO_ORIGIN_QUOTA_KEY,
    DAO_ORIGIN_STAMINA_COST,
    DAO_ORIGIN_STORY_FLAG,
)
from .secret_realm_rules import realm_at_least


ACTIVE_DAO_ORIGIN_STATUSES = ("routing", "cleared")


class DaoOriginRepositoryMixin:
    """Own route, lifetime quota, operation replay, and first-clear projection."""

    @staticmethod
    def _dao_origin_json(raw: Any, default: dict[str, Any] | None = None) -> dict[str, Any]:
        value = json.loads(raw) if isinstance(raw, str) else raw
        return dict(value) if isinstance(value, dict) else dict(default or {})

    def _dao_origin_operation(self, connection, operation_id: str, operation_name: str, request_hash: str):
        row = connection.execute(
            "SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id=?",
            (operation_id,),
        ).fetchone()
        if row is None:
            return None
        if str(row["operation_name"]) != operation_name or str(row["request_hash"]) != request_hash:
            raise OperationConflictError("operation ID was reused with different input")
        return self._dao_origin_json(row["result_json"])

    @staticmethod
    def _dao_origin_store_operation(connection, operation_id, operation_name, player_id, request_hash, payload, now_text):
        connection.execute(
            "INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (operation_id, operation_name, player_id, request_hash, json.dumps(payload, ensure_ascii=False, sort_keys=True), now_text),
        )

    @classmethod
    def _dao_origin_payload(cls, run, snapshot: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        index = int(run["node_index"])
        nodes = tuple(str(key) for key in snapshot.get("node_keys", DAO_ORIGIN_NODES))
        return {
            "run_id": str(run["run_id"]),
            "instance_key": DAO_ORIGIN_KEY,
            "status": str(run["status"]),
            "node_index": index,
            "current_node": nodes[index] if str(run["status"]) == "routing" and index < len(nodes) else None,
            "expires_at": str(run["expires_at"]),
            "outcome": result.get("outcome"),
            "first_clear": bool(result.get("first_clear", snapshot.get("first_clear", False))),
            "story_flag_written": bool(result.get("story_flag_written", False)),
            "codex_written": bool(result.get("codex_written", False)),
        }

    @staticmethod
    def _dao_origin_record(payload: dict[str, Any], *, replay: bool = False) -> DaoOriginRunRecord:
        return DaoOriginRunRecord(
            run_id=str(payload["run_id"]),
            status=str(payload["status"]),
            node_index=int(payload.get("node_index", 0)),
            current_node=payload.get("current_node"),
            expires_at=str(payload.get("expires_at", "")),
            outcome=payload.get("outcome"),
            first_clear=bool(payload.get("first_clear", False)),
            story_flag_written=bool(payload.get("story_flag_written", False)),
            codex_written=bool(payload.get("codex_written", False)),
            already_completed=replay or bool(payload.get("already_completed", False)),
        )

    async def has_active_dao_origin(self, *, platform: str, platform_user_id: str) -> bool:
        await self.initialize()
        return await asyncio.to_thread(self._has_active_dao_origin_sync, platform, platform_user_id)

    def _has_active_dao_origin_sync(self, platform: str, platform_user_id: str) -> bool:
        with self._connect() as connection:
            player = self._require_player(connection, platform, platform_user_id, writable=False)
            return connection.execute(
                "SELECT 1 FROM dao_origin_runs WHERE player_id=? AND status IN ('routing','cleared') LIMIT 1",
                (player["id"],),
            ).fetchone() is not None

    async def has_latest_dao_origin(self, *, platform: str, platform_user_id: str) -> bool:
        await self.initialize()
        return await asyncio.to_thread(self._has_latest_dao_origin_sync, platform, platform_user_id)

    def _has_latest_dao_origin_sync(self, platform: str, platform_user_id: str) -> bool:
        with self._connect() as connection:
            player = self._require_player(connection, platform, platform_user_id, writable=False)
            row = connection.execute("SELECT 1 FROM dao_origin_runs WHERE player_id=? LIMIT 1", (player["id"],)).fetchone()
            return row is not None

    async def has_dao_origin_settlement_operation(self, operation_id: str) -> bool:
        await self.initialize()
        return await asyncio.to_thread(self._has_dao_origin_settlement_operation_sync, operation_id)

    def _has_dao_origin_settlement_operation_sync(self, operation_id: str) -> bool:
        with self._connect() as connection:
            return connection.execute(
                "SELECT 1 FROM operations WHERE operation_id=? AND operation_name='dao_origin.settle'", (operation_id,)
            ).fetchone() is not None

    async def enter_dao_origin(self, *, platform: str, platform_user_id: str, operation_id: str) -> DaoOriginRunRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._retry_sync, self._dao_origin_enter_sync, platform, platform_user_id, operation_id)

    def _dao_origin_enter_sync(self, platform: str, platform_user_id: str, operation_id: str) -> DaoOriginRunRecord:
        operation_name = "dao_origin.enter"
        request_hash = self._request_hash(operation_name, {"platform": platform, "platform_user_id": platform_user_id, "instance_key": DAO_ORIGIN_KEY})
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._dao_origin_operation(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                return self._dao_origin_record(replay, replay=True)
            player = self._require_player(connection, platform, platform_user_id)
            if (
                str(player["location_key"]) != DAO_ORIGIN_LOCATION
                or not realm_at_least(str(player["realm_key"]), player_integer(player, "realm_layer"), "dao_union", 1)
                or DAO_ORIGIN_PERMISSION not in self._dao_origin_json(player["intro_json"], {}).get("flags", [])
            ):
                raise DaoOriginRequirementError("location, realm, or dao-origin permission is missing")
            if connection.execute("SELECT 1 FROM dao_origin_runs WHERE player_id=? AND status IN ('routing','cleared') LIMIT 1", (player["id"],)).fetchone():
                raise DaoOriginBusyError("dao-origin run is already active")
            if self._has_active_long_action(connection, int(player["id"])):
                raise DaoOriginBusyError("another long action is active")
            if connection.execute("SELECT 1 FROM dao_origin_runs WHERE player_id=? AND quota_key=? AND status<>'system_aborted' LIMIT 1", (player["id"], DAO_ORIGIN_QUOTA_KEY)).fetchone():
                raise DaoOriginQuotaError("dao-origin lifetime quota is exhausted")
            if player_integer(player, "stamina") < DAO_ORIGIN_STAMINA_COST:
                raise ResourceInsufficientError("stamina is insufficient")
            intro = self._dao_origin_json(player["intro_json"], {})
            flags = list(intro.get("flags", []))
            run_id = f"dao-origin-{uuid4().hex}"
            expires_at = serialize_datetime(now + timedelta(seconds=DAO_ORIGIN_EXPIRY_SECONDS))
            snapshot = {
                "instance_key": DAO_ORIGIN_KEY,
                "location_key": DAO_ORIGIN_LOCATION,
                "realm_key": str(player["realm_key"]),
                "realm_layer": player_integer(player, "realm_layer"),
                "permission": DAO_ORIGIN_PERMISSION,
                "node_keys": list(DAO_ORIGIN_NODES),
                "first_clear": DAO_ORIGIN_STORY_FLAG not in flags,
            }
            try:
                change_player_state(
                    connection,
                    player,
                    updated_at=now_text,
                    value_delta={"stamina": -DAO_ORIGIN_STAMINA_COST},
                )
            except ValueError:
                raise ResourceInsufficientError("stamina changed during entry")
            connection.execute(
                "INSERT INTO dao_origin_runs(run_id, player_id, status, node_index, quota_key, starts_at, expires_at, stamina_cost, snapshot_json, result_json, entry_operation_id, created_at, updated_at) VALUES (?, ?, 'routing', 0, ?, ?, ?, ?, ?, '{}', ?, ?, ?)",
                (run_id, player["id"], DAO_ORIGIN_QUOTA_KEY, now_text, expires_at, DAO_ORIGIN_STAMINA_COST, json.dumps(snapshot, ensure_ascii=False, sort_keys=True), operation_id, now_text, now_text),
            )
            run = connection.execute("SELECT * FROM dao_origin_runs WHERE run_id=?", (run_id,)).fetchone()
            payload = self._dao_origin_payload(run, snapshot, {})
            self._dao_origin_store_operation(connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text)
            return self._dao_origin_record(payload)

    async def choose_dao_origin_node(self, *, platform: str, platform_user_id: str, node_key: str, operation_id: str) -> DaoOriginRunRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._retry_sync, self._dao_origin_choose_sync, platform, platform_user_id, node_key, operation_id)

    def _dao_origin_choose_sync(self, platform, platform_user_id, node_key, operation_id):
        operation_name = "dao_origin.choose_node"
        request_hash = self._request_hash(operation_name, {"platform": platform, "platform_user_id": platform_user_id, "node_key": node_key})
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._dao_origin_operation(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                return self._dao_origin_record(replay, replay=True)
            player = self._require_player(connection, platform, platform_user_id)
            run = connection.execute("SELECT * FROM dao_origin_runs WHERE player_id=? AND status='routing' ORDER BY id DESC LIMIT 1", (player["id"],)).fetchone()
            if run is None:
                raise DaoOriginNotFoundError("no active dao-origin run")
            if datetime.fromisoformat(str(run["expires_at"])).astimezone(timezone.utc) <= now.astimezone(timezone.utc):
                result = {"outcome": "expired", "first_clear": False, "story_flag_written": False, "codex_written": False}
                connection.execute("UPDATE dao_origin_runs SET status='expired', result_json=?, updated_at=? WHERE id=?", (json.dumps(result, sort_keys=True), now_text, run["id"]))
                expired = connection.execute("SELECT * FROM dao_origin_runs WHERE id=?", (run["id"],)).fetchone()
                payload = self._dao_origin_payload(expired, self._dao_origin_json(run["snapshot_json"]), result)
                self._dao_origin_store_operation(connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text)
                return self._dao_origin_record(payload)
            snapshot = self._dao_origin_json(run["snapshot_json"])
            nodes = tuple(str(item) for item in snapshot.get("node_keys", DAO_ORIGIN_NODES))
            index = int(run["node_index"])
            if index >= len(nodes) or nodes[index] != node_key:
                raise DaoOriginNodeError("node is not the current route node")
            status = "cleared" if index == len(nodes) - 1 else "routing"
            connection.execute("UPDATE dao_origin_runs SET status=?, node_index=?, updated_at=? WHERE id=?", (status, index + 1, now_text, run["id"]))
            updated = connection.execute("SELECT * FROM dao_origin_runs WHERE id=?", (run["id"],)).fetchone()
            payload = self._dao_origin_payload(updated, snapshot, self._dao_origin_json(updated["result_json"]))
            self._dao_origin_store_operation(connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text)
            return self._dao_origin_record(payload)

    async def settle_dao_origin(self, *, platform: str, platform_user_id: str, operation_id: str) -> DaoOriginRunRecord:
        await self.initialize()
        operation_name = "dao_origin.settle"
        request_hash = self._request_hash(operation_name, {"platform": platform, "platform_user_id": platform_user_id})
        replay = await asyncio.to_thread(self._dao_origin_read_operation, operation_id, operation_name, request_hash)
        if replay is not None:
            return self._dao_origin_record(replay, replay=True)
        async with self._inflight:
            return await asyncio.to_thread(self._retry_sync, self._dao_origin_settle_sync, platform, platform_user_id, operation_id)

    def _dao_origin_read_operation(self, operation_id, operation_name, request_hash):
        with self._connect() as connection:
            return self._dao_origin_operation(connection, operation_id, operation_name, request_hash)

    def _dao_origin_settle_sync(self, platform, platform_user_id, operation_id):
        operation_name = "dao_origin.settle"
        request_hash = self._request_hash(operation_name, {"platform": platform, "platform_user_id": platform_user_id})
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._dao_origin_operation(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                return self._dao_origin_record(replay, replay=True)
            player = self._require_player(connection, platform, platform_user_id)
            run = connection.execute("SELECT * FROM dao_origin_runs WHERE player_id=? ORDER BY id DESC LIMIT 1", (player["id"],)).fetchone()
            if run is None:
                raise DaoOriginNotFoundError("no dao-origin run exists")
            snapshot = self._dao_origin_json(run["snapshot_json"])
            result = self._dao_origin_json(run["result_json"])
            status = str(run["status"])
            if status == "routing" and datetime.fromisoformat(str(run["expires_at"])).astimezone(timezone.utc) <= now.astimezone(timezone.utc):
                status = "expired"
                result.update({"outcome": "expired", "first_clear": False, "story_flag_written": False, "codex_written": False})
            elif status == "cleared":
                intro = self._dao_origin_json(player["intro_json"], {})
                flags = list(intro.get("flags", []))
                first_clear = DAO_ORIGIN_STORY_FLAG not in flags
                story_written = False
                if first_clear:
                    flags.append(DAO_ORIGIN_STORY_FLAG)
                    intro["flags"] = flags
                    change_player_state(
                        connection,
                        player,
                        updated_at=now_text,
                        player_values={"intro_json": json.dumps(intro, ensure_ascii=False, sort_keys=True)},
                    )
                    story_written = True
                codex_written = False
                if first_clear:
                    codex_written = record_codex_discovery(connection, player_id=int(player["id"]), entry_key=DAO_ORIGIN_CODEX, operation_id=f"{operation_id}:codex", occurred_at=now, snapshot={"run_id": str(run["run_id"]), "instance_key": DAO_ORIGIN_KEY})
                result.update({"outcome": "won", "first_clear": first_clear, "story_flag_written": story_written, "codex_written": codex_written})
                status = "settled"
            elif status in {"expired", "failed", "system_aborted"}:
                result.setdefault("outcome", status)
                result.update({"first_clear": False, "story_flag_written": False, "codex_written": False})
                status = "settled" if status != "system_aborted" else "system_aborted"
            else:
                raise DaoOriginNotReadyError("complete the route before settling")
            connection.execute("UPDATE dao_origin_runs SET status=?, result_json=?, updated_at=? WHERE id=?", (status, json.dumps(result, ensure_ascii=False, sort_keys=True), now_text, run["id"]))
            settled = connection.execute("SELECT * FROM dao_origin_runs WHERE id=?", (run["id"],)).fetchone()
            payload = self._dao_origin_payload(settled, snapshot, result)
            self._dao_origin_store_operation(connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text)
            return self._dao_origin_record(payload)

    async def compensate_dao_origin_system_failure(self, *, run_id: str, operation_id: str) -> DaoOriginRunRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._retry_sync, self._dao_origin_compensate_sync, run_id, operation_id)

    def _dao_origin_compensate_sync(self, run_id, operation_id):
        operation_name = "dao_origin.system_abort"
        request_hash = self._request_hash(operation_name, {"run_id": run_id})
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._dao_origin_operation(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                return self._dao_origin_record(replay, replay=True)
            run = connection.execute("SELECT * FROM dao_origin_runs WHERE run_id=?", (run_id,)).fetchone()
            if run is None or str(run["status"]) not in ACTIVE_DAO_ORIGIN_STATUSES:
                raise DaoOriginNotReadyError("only an active dao-origin run can be compensated")
            player = connection.execute(
                "SELECT * FROM players WHERE id = ?", (run["player_id"],)
            ).fetchone()
            if player is not None:
                change_player_state(
                    connection,
                    player,
                    updated_at=now_text,
                    value_delta={"stamina": int(run["stamina_cost"])},
                    maximums={"stamina": player["stamina_max"]},
                )
            result = {"outcome": "system_aborted", "stamina_refunded": int(run["stamina_cost"]), "quota_released": True}
            connection.execute("UPDATE dao_origin_runs SET status='system_aborted', result_json=?, updated_at=? WHERE id=?", (json.dumps(result, ensure_ascii=False, sort_keys=True), now_text, run["id"]))
            updated = connection.execute("SELECT * FROM dao_origin_runs WHERE id=?", (run["id"],)).fetchone()
            payload = self._dao_origin_payload(updated, self._dao_origin_json(run["snapshot_json"]), result)
            self._dao_origin_store_operation(connection, operation_id, operation_name, int(run["player_id"]), request_hash, payload, now_text)
            return self._dao_origin_record(payload)


__all__ = ["DaoOriginRepositoryMixin"]
