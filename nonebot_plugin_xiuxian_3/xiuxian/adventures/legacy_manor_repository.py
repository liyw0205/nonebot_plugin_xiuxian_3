"""Persistence for the clue-driven demon legacy manor."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from ...contracts import serialize_datetime
from ..persistence.errors import (
    LegacyManorBusyError,
    LegacyManorNodeError,
    LegacyManorNotFoundError,
    LegacyManorNotReadyError,
    LegacyManorQuotaError,
    LegacyManorRequirementError,
    OperationConflictError,
)
from .legacy_manor_models import LegacyManorRunRecord
from .legacy_manor_rules import (
    LEGACY_MANOR_KEY,
    get_legacy_manor_definition,
)
from .secret_realm_rules import realm_at_least


ACTIVE_LEGACY_MANOR_STATUSES = ("routing", "cleared")


class LegacyManorRepositoryMixin:
    """Own legacy-manor sessions, replay records, expiry, and story projection."""

    @staticmethod
    def _legacy_manor_operation_name(action: str, instance_key: str) -> str:
        definition = get_legacy_manor_definition(instance_key)
        suffix = "" if instance_key == LEGACY_MANOR_KEY else definition.operation_scope.removeprefix("legacy_manor")
        return f"legacy_manor{suffix}.{action}"

    @staticmethod
    def _legacy_manor_request(operation_payload: dict[str, Any], instance_key: str) -> dict[str, Any]:
        if instance_key == LEGACY_MANOR_KEY:
            return operation_payload
        return {**operation_payload, "instance_key": instance_key}

    @staticmethod
    def _legacy_manor_json(raw: Any, default: dict[str, Any] | None = None) -> dict[str, Any]:
        value = json.loads(raw) if isinstance(raw, str) else raw
        return dict(value) if isinstance(value, dict) else dict(default or {})

    def _legacy_manor_operation(self, connection, operation_id: str, operation_name: str, request_hash: str):
        row = connection.execute(
            "SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id=?",
            (operation_id,),
        ).fetchone()
        if row is None:
            return None
        if str(row["operation_name"]) != operation_name or str(row["request_hash"]) != request_hash:
            raise OperationConflictError("operation ID was reused with different input")
        return self._legacy_manor_json(row["result_json"])

    @staticmethod
    def _legacy_manor_store_operation(connection, operation_id, operation_name, player_id, request_hash, payload, now_text):
        connection.execute(
            "INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (operation_id, operation_name, player_id, request_hash, json.dumps(payload, ensure_ascii=False, sort_keys=True), now_text),
        )

    @staticmethod
    def _legacy_manor_payload(run, snapshot: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        index = int(run["node_index"])
        definition = get_legacy_manor_definition(str(snapshot.get("instance_key", LEGACY_MANOR_KEY)))
        nodes = tuple(str(key) for key in snapshot.get("node_keys", definition.nodes))
        return {
            "run_id": str(run["run_id"]),
            "instance_key": definition.instance_key,
            "status": str(run["status"]),
            "node_index": index,
            "current_node": nodes[index] if str(run["status"]) == "routing" and index < len(nodes) else None,
            "expires_at": str(run["expires_at"]),
            "outcome": result.get("outcome"),
            "first_clear": bool(result.get("first_clear", snapshot.get("first_clear", False))),
            "story_flag_written": bool(result.get("story_flag_written", False)),
        }

    @staticmethod
    def _legacy_manor_record(payload: dict[str, Any], *, replay: bool = False) -> LegacyManorRunRecord:
        return LegacyManorRunRecord(
            run_id=str(payload["run_id"]),
            status=str(payload["status"]),
            node_index=int(payload.get("node_index", 0)),
            current_node=payload.get("current_node"),
            expires_at=str(payload.get("expires_at", "")),
            outcome=payload.get("outcome"),
            first_clear=bool(payload.get("first_clear", False)),
            story_flag_written=bool(payload.get("story_flag_written", False)),
            already_completed=replay or bool(payload.get("already_completed", False)),
        )

    async def has_active_legacy_manor(self, *, platform: str, platform_user_id: str) -> bool:
        await self.initialize()
        return await asyncio.to_thread(self._has_active_legacy_manor_sync, platform, platform_user_id)

    def _has_active_legacy_manor_sync(self, platform: str, platform_user_id: str) -> bool:
        with self._connect() as connection:
            player = self._require_player(connection, platform, platform_user_id, writable=False)
            return connection.execute(
                "SELECT 1 FROM legacy_manor_runs WHERE player_id=? AND status IN ('routing','cleared') LIMIT 1",
                (player["id"],),
            ).fetchone() is not None

    async def get_legacy_manor_status(
        self, *, platform: str, platform_user_id: str, instance_key: str = LEGACY_MANOR_KEY
    ) -> LegacyManorRunRecord | None:
        await self.initialize()
        return await asyncio.to_thread(self._get_legacy_manor_status_sync, platform, platform_user_id, instance_key)

    def _get_legacy_manor_status_sync(
        self, platform: str, platform_user_id: str, instance_key: str
    ) -> LegacyManorRunRecord | None:
        with self._connect() as connection:
            player = self._require_player(connection, platform, platform_user_id, writable=False)
            run = connection.execute(
                "SELECT * FROM legacy_manor_runs WHERE player_id=? AND instance_key=? "
                "AND status IN ('routing','cleared') ORDER BY id DESC LIMIT 1",
                (player["id"], instance_key),
            ).fetchone()
            if run is None:
                return None
            snapshot = self._legacy_manor_json(run["snapshot_json"])
            result = self._legacy_manor_json(run["result_json"])
            payload_run = dict(run)
            if (
                str(run["status"]) == "routing"
                and datetime.fromisoformat(str(run["expires_at"])).astimezone(timezone.utc)
                <= self._now().astimezone(timezone.utc)
            ):
                payload_run["status"] = "expired"
                result.update({"outcome": "expired", "first_clear": False, "story_flag_written": False})
            return self._legacy_manor_record(self._legacy_manor_payload(payload_run, snapshot, result))

    async def enter_legacy_manor(
        self, *, platform: str, platform_user_id: str, operation_id: str, instance_key: str = LEGACY_MANOR_KEY
    ) -> LegacyManorRunRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._retry_sync, self._legacy_manor_enter_sync, platform, platform_user_id, operation_id, instance_key
            )

    def _legacy_manor_enter_sync(
        self, platform: str, platform_user_id: str, operation_id: str, instance_key: str
    ) -> LegacyManorRunRecord:
        definition = get_legacy_manor_definition(instance_key)
        operation_name = self._legacy_manor_operation_name("enter", instance_key)
        request_hash = self._request_hash(operation_name, {"platform": platform, "platform_user_id": platform_user_id, "instance_key": instance_key})
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._legacy_manor_operation(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                return self._legacy_manor_record(replay, replay=True)
            player = self._require_player(connection, platform, platform_user_id)
            if str(player["location_key"]) != definition.location_key:
                raise LegacyManorRequirementError("player is not at the reliquary location")
            if not realm_at_least(
                str(player["realm_key"]), int(player["realm_layer"]), definition.realm_key, definition.realm_layer
            ):
                raise LegacyManorRequirementError("minimum legacy-manor realm is required")
            intro = self._legacy_manor_json(player["intro_json"], {})
            flags = list(intro.get("flags", []))
            if definition.permission not in flags:
                raise LegacyManorRequirementError("the legacy-manor permission is missing")
            inventory = self._legacy_manor_json(player["inventory_json"], {})
            if int(inventory.get(definition.clue, 0)) < 1:
                raise LegacyManorRequirementError("the required clue is missing")
            if definition.story_flag in flags:
                raise LegacyManorQuotaError("the legacy manor has already been cleared")
            if connection.execute(
                "SELECT 1 FROM legacy_manor_runs WHERE player_id=? AND status IN ('routing','cleared') LIMIT 1",
                (player["id"],),
            ).fetchone() is not None or self._has_active_long_action(connection, int(player["id"])):
                raise LegacyManorBusyError("another action or legacy-manor run is active")

            run_id = f"legacy-manor-{uuid4().hex}"
            expires_at = serialize_datetime(now + timedelta(seconds=definition.expiry_seconds))
            snapshot = {
                "instance_key": definition.instance_key,
                "location_key": definition.location_key,
                "realm_key": str(player["realm_key"]),
                "realm_layer": int(player["realm_layer"]),
                "permission": definition.permission,
                "clue_key": definition.clue,
                "clue_consumed": False,
                "node_keys": list(definition.nodes),
                "first_clear": True,
            }
            connection.execute(
                "INSERT INTO legacy_manor_runs(run_id, player_id, instance_key, status, node_index, starts_at, expires_at, "
                "snapshot_json, result_json, entry_operation_id, created_at, updated_at) "
                "VALUES (?, ?, ?, 'routing', 0, ?, ?, ?, '{}', ?, ?, ?)",
                (run_id, player["id"], definition.instance_key, now_text, expires_at, json.dumps(snapshot, ensure_ascii=False, sort_keys=True), operation_id, now_text, now_text),
            )
            run = connection.execute("SELECT * FROM legacy_manor_runs WHERE run_id=?", (run_id,)).fetchone()
            payload = self._legacy_manor_payload(run, snapshot, {})
            self._legacy_manor_store_operation(connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text)
            return self._legacy_manor_record(payload)

    async def choose_legacy_manor_node(
        self, *, platform: str, platform_user_id: str, node_key: str, operation_id: str,
        instance_key: str = LEGACY_MANOR_KEY,
    ) -> LegacyManorRunRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._retry_sync, self._legacy_manor_choose_sync, platform, platform_user_id, node_key, operation_id, instance_key
            )

    def _legacy_manor_choose_sync(self, platform, platform_user_id, node_key, operation_id, instance_key):
        operation_name = self._legacy_manor_operation_name("choose_node", instance_key)
        request_hash = self._request_hash(
            operation_name,
            self._legacy_manor_request(
                {"platform": platform, "platform_user_id": platform_user_id, "node_key": node_key}, instance_key
            ),
        )
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._legacy_manor_operation(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                return self._legacy_manor_record(replay, replay=True)
            player = self._require_player(connection, platform, platform_user_id)
            run = connection.execute(
                "SELECT * FROM legacy_manor_runs WHERE player_id=? AND instance_key=? "
                "AND status='routing' ORDER BY id DESC LIMIT 1",
                (player["id"], instance_key),
            ).fetchone()
            if run is None:
                raise LegacyManorNotFoundError("no active legacy-manor run")
            if datetime.fromisoformat(str(run["expires_at"])).astimezone(timezone.utc) <= now.astimezone(timezone.utc):
                result = {"outcome": "expired", "first_clear": False, "story_flag_written": False}
                connection.execute(
                    "UPDATE legacy_manor_runs SET status='expired', result_json=?, updated_at=? WHERE id=?",
                    (json.dumps(result, sort_keys=True), now_text, run["id"]),
                )
                expired = connection.execute("SELECT * FROM legacy_manor_runs WHERE id=?", (run["id"],)).fetchone()
                payload = self._legacy_manor_payload(expired, self._legacy_manor_json(run["snapshot_json"]), result)
                self._legacy_manor_store_operation(connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text)
                return self._legacy_manor_record(payload)
            snapshot = self._legacy_manor_json(run["snapshot_json"])
            definition = get_legacy_manor_definition(instance_key)
            nodes = tuple(str(item) for item in snapshot.get("node_keys", definition.nodes))
            index = int(run["node_index"])
            if index >= len(nodes) or nodes[index] != node_key:
                raise LegacyManorNodeError("node is not the current route node")
            status = "cleared" if index == len(nodes) - 1 else "routing"
            connection.execute(
                "UPDATE legacy_manor_runs SET status=?, node_index=?, updated_at=? WHERE id=?",
                (status, index + 1, now_text, run["id"]),
            )
            updated = connection.execute("SELECT * FROM legacy_manor_runs WHERE id=?", (run["id"],)).fetchone()
            payload = self._legacy_manor_payload(updated, snapshot, self._legacy_manor_json(updated["result_json"]))
            self._legacy_manor_store_operation(connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text)
            return self._legacy_manor_record(payload)

    async def settle_legacy_manor(
        self, *, platform: str, platform_user_id: str, operation_id: str, instance_key: str = LEGACY_MANOR_KEY
    ) -> LegacyManorRunRecord:
        await self.initialize()
        operation_name = self._legacy_manor_operation_name("settle", instance_key)
        request_hash = self._request_hash(
            operation_name,
            self._legacy_manor_request({"platform": platform, "platform_user_id": platform_user_id}, instance_key),
        )
        replay = await asyncio.to_thread(self._legacy_manor_read_operation, operation_id, operation_name, request_hash)
        if replay is not None:
            return self._legacy_manor_record(replay, replay=True)
        async with self._inflight:
            return await asyncio.to_thread(
                self._retry_sync, self._legacy_manor_settle_sync, platform, platform_user_id, operation_id, instance_key
            )

    def _legacy_manor_read_operation(self, operation_id, operation_name, request_hash):
        with self._connect() as connection:
            return self._legacy_manor_operation(connection, operation_id, operation_name, request_hash)

    def _legacy_manor_settle_sync(self, platform, platform_user_id, operation_id, instance_key):
        definition = get_legacy_manor_definition(instance_key)
        operation_name = self._legacy_manor_operation_name("settle", instance_key)
        request_hash = self._request_hash(
            operation_name,
            self._legacy_manor_request({"platform": platform, "platform_user_id": platform_user_id}, instance_key),
        )
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._legacy_manor_operation(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                return self._legacy_manor_record(replay, replay=True)
            player = self._require_player(connection, platform, platform_user_id)
            run = connection.execute(
                "SELECT * FROM legacy_manor_runs WHERE player_id=? AND instance_key=? ORDER BY id DESC LIMIT 1",
                (player["id"], instance_key),
            ).fetchone()
            if run is None:
                raise LegacyManorNotFoundError("no legacy-manor run exists")
            snapshot = self._legacy_manor_json(run["snapshot_json"])
            result = self._legacy_manor_json(run["result_json"])
            status = str(run["status"])
            if status == "routing" and datetime.fromisoformat(str(run["expires_at"])).astimezone(timezone.utc) <= now.astimezone(timezone.utc):
                status = "expired"
                result.update({"outcome": "expired", "first_clear": False, "story_flag_written": False})
            elif status == "cleared":
                intro = self._legacy_manor_json(player["intro_json"], {})
                flags = list(intro.get("flags", []))
                first_clear = definition.story_flag not in flags
                if first_clear:
                    flags.append(definition.story_flag)
                    intro["flags"] = flags
                    connection.execute(
                        "UPDATE players SET intro_json=?, updated_at=? WHERE id=?",
                        (json.dumps(intro, ensure_ascii=False, sort_keys=True), now_text, player["id"]),
                    )
                result.update({"outcome": "won", "first_clear": first_clear, "story_flag_written": first_clear})
                status = "settled"
            elif status in {"expired", "system_aborted"}:
                result.setdefault("outcome", status)
                result.update({"first_clear": False, "story_flag_written": False})
                status = "settled" if status == "expired" else "system_aborted"
            else:
                raise LegacyManorNotReadyError("complete the route before settling")
            connection.execute(
                "UPDATE legacy_manor_runs SET status=?, result_json=?, updated_at=? WHERE id=?",
                (status, json.dumps(result, ensure_ascii=False, sort_keys=True), now_text, run["id"]),
            )
            settled = connection.execute("SELECT * FROM legacy_manor_runs WHERE id=?", (run["id"],)).fetchone()
            payload = self._legacy_manor_payload(settled, snapshot, result)
            self._legacy_manor_store_operation(connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text)
            return self._legacy_manor_record(payload)

    async def compensate_legacy_manor_system_failure(
        self, *, run_id: str, operation_id: str, instance_key: str = LEGACY_MANOR_KEY
    ) -> LegacyManorRunRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._retry_sync, self._legacy_manor_compensate_sync, run_id, operation_id, instance_key
            )

    def _legacy_manor_compensate_sync(self, run_id, operation_id, instance_key):
        operation_name = self._legacy_manor_operation_name("system_abort", instance_key)
        request_hash = self._request_hash(
            operation_name, self._legacy_manor_request({"run_id": run_id}, instance_key)
        )
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._legacy_manor_operation(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                return self._legacy_manor_record(replay, replay=True)
            run = connection.execute("SELECT * FROM legacy_manor_runs WHERE run_id=?", (run_id,)).fetchone()
            if (
                run is None
                or str(run["instance_key"]) != instance_key
                or str(run["status"]) not in ACTIVE_LEGACY_MANOR_STATUSES
            ):
                raise LegacyManorNotReadyError("only an active legacy-manor run can be compensated")
            result = {"outcome": "system_aborted", "resource_refunded": {}}
            connection.execute(
                "UPDATE legacy_manor_runs SET status='system_aborted', result_json=?, updated_at=? WHERE id=?",
                (json.dumps(result, ensure_ascii=False, sort_keys=True), now_text, run["id"]),
            )
            updated = connection.execute("SELECT * FROM legacy_manor_runs WHERE id=?", (run["id"],)).fetchone()
            payload = self._legacy_manor_payload(updated, self._legacy_manor_json(run["snapshot_json"]), result)
            self._legacy_manor_store_operation(connection, operation_id, operation_name, int(run["player_id"]), request_hash, payload, now_text)
            return self._legacy_manor_record(payload)


__all__ = ["LegacyManorRepositoryMixin"]
