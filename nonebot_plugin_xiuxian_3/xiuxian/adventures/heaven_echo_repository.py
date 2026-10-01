"""Persistence for the v0.6 heaven-echo solo secret realm."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from ...contracts import serialize_datetime
from ..utils.player import change_player_state
from ..persistence.errors import (
    HeavenEchoBusyError,
    HeavenEchoFinalBattleError,
    HeavenEchoNodeError,
    HeavenEchoNotFoundError,
    HeavenEchoNotReadyError,
    HeavenEchoRequirementError,
    OperationConflictError,
)
from .heaven_echo_models import HeavenEchoRunRecord
from .heaven_echo_rules import (
    HEAVEN_ECHO_EXPIRY_SECONDS,
    HEAVEN_ECHO_KEY,
    HEAVEN_ECHO_NODES,
    HEAVEN_ECHO_STORY_FLAG,
)
from .secret_realm_rules import realm_at_least


ACTIVE_HEAVEN_ECHO_STATUSES = ("routing", "cleared")
FINAL_BATTLE_ACTIVE_STATUSES = ("lobby", "running", "won", "lost")


class HeavenEchoRepositoryMixin:
    """Own the route, replay ledger, expiry, and side-story projection."""

    @staticmethod
    def _heaven_echo_json(raw: Any, default: dict[str, Any] | None = None) -> dict[str, Any]:
        value = json.loads(raw) if isinstance(raw, str) else raw
        return dict(value) if isinstance(value, dict) else dict(default or {})

    def _heaven_echo_operation(self, connection, operation_id: str, operation_name: str, request_hash: str):
        row = connection.execute(
            "SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id=?",
            (operation_id,),
        ).fetchone()
        if row is None:
            return None
        if str(row["operation_name"]) != operation_name or str(row["request_hash"]) != request_hash:
            raise OperationConflictError("operation ID was reused with different input")
        return self._heaven_echo_json(row["result_json"])

    @staticmethod
    def _heaven_echo_store_operation(connection, operation_id, operation_name, player_id, request_hash, payload, now_text):
        connection.execute(
            "INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (operation_id, operation_name, player_id, request_hash, json.dumps(payload, ensure_ascii=False, sort_keys=True), now_text),
        )

    @staticmethod
    def _heaven_echo_payload(run, snapshot: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        index = int(run["node_index"])
        nodes = tuple(str(key) for key in snapshot.get("node_keys", HEAVEN_ECHO_NODES))
        return {
            "run_id": str(run["run_id"]),
            "instance_key": HEAVEN_ECHO_KEY,
            "status": str(run["status"]),
            "node_index": index,
            "current_node": nodes[index] if str(run["status"]) == "routing" and index < len(nodes) else None,
            "expires_at": str(run["expires_at"]),
            "outcome": result.get("outcome"),
            "first_clear": bool(result.get("first_clear", snapshot.get("first_clear", False))),
            "story_flag_written": bool(result.get("story_flag_written", False)),
        }

    @staticmethod
    def _heaven_echo_record(payload: dict[str, Any], *, replay: bool = False) -> HeavenEchoRunRecord:
        return HeavenEchoRunRecord(
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

    async def has_active_heaven_echo(self, *, platform: str, platform_user_id: str) -> bool:
        await self.initialize()
        return await asyncio.to_thread(self._has_active_heaven_echo_sync, platform, platform_user_id)

    def _has_active_heaven_echo_sync(self, platform: str, platform_user_id: str) -> bool:
        with self._connect() as connection:
            player = self._require_player(connection, platform, platform_user_id, writable=False)
            return connection.execute(
                "SELECT 1 FROM heaven_echo_runs WHERE player_id=? AND status IN ('routing','cleared') LIMIT 1",
                (player["id"],),
            ).fetchone() is not None

    async def has_latest_heaven_echo(self, *, platform: str, platform_user_id: str) -> bool:
        await self.initialize()
        return await asyncio.to_thread(self._has_latest_heaven_echo_sync, platform, platform_user_id)

    def _has_latest_heaven_echo_sync(self, platform: str, platform_user_id: str) -> bool:
        with self._connect() as connection:
            player = self._require_player(connection, platform, platform_user_id, writable=False)
            latest_echo = connection.execute(
                "SELECT entry_operation_id FROM heaven_echo_runs WHERE player_id=? ORDER BY id DESC LIMIT 1",
                (player["id"],),
            ).fetchone()
            if latest_echo is None:
                return False
            # The generic secret-realm table has no entry-operation column, so
            # compare its entry ledger row with the dedicated realm tables.
            latest_instance = connection.execute(
                "SELECT entries.operation_id FROM ("
                "SELECT entry_operation_id AS operation_id FROM heaven_echo_runs WHERE player_id=? "
                "UNION ALL SELECT o.operation_id FROM operations o JOIN secret_realm_runs r "
                "ON json_extract(o.result_json, '$.run_id')=r.run_id "
                "WHERE r.player_id=? AND o.operation_name IN ('secret_realm.enter','demon_abyss.enter') "
                "UNION ALL SELECT r.entry_operation_id FROM boundary_rift_runs r JOIN boundary_rift_members m ON m.run_id=r.run_id WHERE m.player_id=? "
                "UNION ALL SELECT r.entry_operation_id FROM ancient_domain_runs r JOIN ancient_domain_members m ON m.run_id=r.run_id WHERE m.player_id=? "
                "UNION ALL SELECT entry_operation_id FROM ancestral_hall_runs WHERE player_id=? "
                "UNION ALL SELECT r.entry_operation_id FROM void_ruins_runs r JOIN void_ruins_members m ON m.run_id=r.run_id WHERE m.player_id=? "
                "UNION ALL SELECT r.entry_operation_id FROM time_fort_runs r JOIN time_fort_members m ON m.run_id=r.run_id WHERE m.player_id=? "
                "UNION ALL SELECT entry_operation_id FROM dao_origin_runs WHERE player_id=?"
                ") entries JOIN operations o ON o.operation_id=entries.operation_id "
                "ORDER BY o.rowid DESC LIMIT 1",
                (player["id"],) * 8,
            ).fetchone()
            return latest_instance is not None and str(latest_echo["entry_operation_id"]) == str(latest_instance["operation_id"])

    async def has_heaven_echo_settlement_operation(self, operation_id: str) -> bool:
        await self.initialize()
        return await asyncio.to_thread(self._has_heaven_echo_settlement_operation_sync, operation_id)

    def _has_heaven_echo_settlement_operation_sync(self, operation_id: str) -> bool:
        with self._connect() as connection:
            return connection.execute(
                "SELECT 1 FROM operations WHERE operation_id=? AND operation_name='heaven_echo.settle'",
                (operation_id,),
            ).fetchone() is not None

    async def enter_heaven_echo(self, *, platform: str, platform_user_id: str, operation_id: str) -> HeavenEchoRunRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._retry_sync, self._heaven_echo_enter_sync, platform, platform_user_id, operation_id)

    def _heaven_echo_enter_sync(self, platform: str, platform_user_id: str, operation_id: str) -> HeavenEchoRunRecord:
        operation_name = "heaven_echo.enter"
        request_hash = self._request_hash(operation_name, {"platform": platform, "platform_user_id": platform_user_id, "instance_key": HEAVEN_ECHO_KEY})
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._heaven_echo_operation(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                return self._heaven_echo_record(replay, replay=True)
            player = self._require_player(connection, platform, platform_user_id, writable=False)
            if str(player["endgame_status"] or "none") in {"ascension_ready", "ascended", "remained_in_world"}:
                raise HeavenEchoRequirementError("the player already has a terminal ending")
            if not realm_at_least(str(player["realm_key"]), int(player["realm_layer"]), "tribulation", 1):
                raise HeavenEchoRequirementError("tribulation L1 is required")
            if connection.execute(
                "SELECT 1 FROM final_battle_members m JOIN final_battle_sessions s ON s.battle_id=m.battle_id "
                "WHERE m.player_id=? AND s.status IN ('lobby','running','won','lost') LIMIT 1",
                (player["id"],),
            ).fetchone() is not None:
                raise HeavenEchoFinalBattleError("player is currently in a final battle")
            if connection.execute(
                "SELECT 1 FROM heaven_echo_runs WHERE player_id=? AND status IN ('routing','cleared') LIMIT 1",
                (player["id"],),
            ).fetchone() is not None or self._has_active_long_action(connection, int(player["id"])):
                raise HeavenEchoBusyError("another action or heaven-echo run is active")
            intro = self._heaven_echo_json(player["intro_json"], {})
            flags = list(intro.get("flags", []))
            run_id = f"heaven-echo-{uuid4().hex}"
            expires_at = serialize_datetime(now + timedelta(seconds=HEAVEN_ECHO_EXPIRY_SECONDS))
            snapshot = {
                "instance_key": HEAVEN_ECHO_KEY,
                "realm_key": str(player["realm_key"]),
                "realm_layer": int(player["realm_layer"]),
                "tribulation_debt": int(player["tribulation_debt"]),
                "endgame_status": str(player["endgame_status"] or "none"),
                "node_keys": list(HEAVEN_ECHO_NODES),
                "first_clear": HEAVEN_ECHO_STORY_FLAG not in flags,
            }
            connection.execute(
                "INSERT INTO heaven_echo_runs(run_id, player_id, status, node_index, starts_at, expires_at, snapshot_json, result_json, entry_operation_id, created_at, updated_at) "
                "VALUES (?, ?, 'routing', 0, ?, ?, ?, '{}', ?, ?, ?)",
                (run_id, player["id"], now_text, expires_at, json.dumps(snapshot, ensure_ascii=False, sort_keys=True), operation_id, now_text, now_text),
            )
            run = connection.execute("SELECT * FROM heaven_echo_runs WHERE run_id=?", (run_id,)).fetchone()
            payload = self._heaven_echo_payload(run, snapshot, {})
            self._heaven_echo_store_operation(connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text)
            return self._heaven_echo_record(payload)

    async def choose_heaven_echo_node(self, *, platform: str, platform_user_id: str, node_key: str, operation_id: str) -> HeavenEchoRunRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._retry_sync, self._heaven_echo_choose_sync, platform, platform_user_id, node_key, operation_id)

    def _heaven_echo_choose_sync(self, platform, platform_user_id, node_key, operation_id):
        operation_name = "heaven_echo.choose_node"
        request_hash = self._request_hash(operation_name, {"platform": platform, "platform_user_id": platform_user_id, "node_key": node_key})
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._heaven_echo_operation(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                return self._heaven_echo_record(replay, replay=True)
            player = self._require_player(connection, platform, platform_user_id)
            run = connection.execute(
                "SELECT * FROM heaven_echo_runs WHERE player_id=? AND status='routing' ORDER BY id DESC LIMIT 1", (player["id"],)
            ).fetchone()
            if run is None:
                raise HeavenEchoNotFoundError("no active heaven-echo run")
            if datetime.fromisoformat(str(run["expires_at"])).astimezone(timezone.utc) <= now.astimezone(timezone.utc):
                result = {"outcome": "expired", "first_clear": False, "story_flag_written": False}
                connection.execute("UPDATE heaven_echo_runs SET status='expired', result_json=?, updated_at=? WHERE id=?", (json.dumps(result, sort_keys=True), now_text, run["id"]))
                expired = connection.execute("SELECT * FROM heaven_echo_runs WHERE id=?", (run["id"],)).fetchone()
                payload = self._heaven_echo_payload(expired, self._heaven_echo_json(run["snapshot_json"]), result)
                self._heaven_echo_store_operation(connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text)
                return self._heaven_echo_record(payload)
            snapshot = self._heaven_echo_json(run["snapshot_json"])
            nodes = tuple(str(item) for item in snapshot.get("node_keys", HEAVEN_ECHO_NODES))
            index = int(run["node_index"])
            if index >= len(nodes) or nodes[index] != node_key:
                raise HeavenEchoNodeError("node is not the current route node")
            status = "cleared" if index == len(nodes) - 1 else "routing"
            connection.execute("UPDATE heaven_echo_runs SET status=?, node_index=?, updated_at=? WHERE id=?", (status, index + 1, now_text, run["id"]))
            updated = connection.execute("SELECT * FROM heaven_echo_runs WHERE id=?", (run["id"],)).fetchone()
            payload = self._heaven_echo_payload(updated, snapshot, self._heaven_echo_json(updated["result_json"]))
            self._heaven_echo_store_operation(connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text)
            return self._heaven_echo_record(payload)

    async def settle_heaven_echo(self, *, platform: str, platform_user_id: str, operation_id: str) -> HeavenEchoRunRecord:
        await self.initialize()
        operation_name = "heaven_echo.settle"
        request_hash = self._request_hash(operation_name, {"platform": platform, "platform_user_id": platform_user_id})
        replay = await asyncio.to_thread(self._heaven_echo_read_operation, operation_id, operation_name, request_hash)
        if replay is not None:
            return self._heaven_echo_record(replay, replay=True)
        async with self._inflight:
            return await asyncio.to_thread(self._retry_sync, self._heaven_echo_settle_sync, platform, platform_user_id, operation_id)

    def _heaven_echo_read_operation(self, operation_id, operation_name, request_hash):
        with self._connect() as connection:
            return self._heaven_echo_operation(connection, operation_id, operation_name, request_hash)

    def _heaven_echo_settle_sync(self, platform, platform_user_id, operation_id):
        operation_name = "heaven_echo.settle"
        request_hash = self._request_hash(operation_name, {"platform": platform, "platform_user_id": platform_user_id})
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._heaven_echo_operation(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                return self._heaven_echo_record(replay, replay=True)
            player = self._require_player(connection, platform, platform_user_id)
            run = connection.execute("SELECT * FROM heaven_echo_runs WHERE player_id=? ORDER BY id DESC LIMIT 1", (player["id"],)).fetchone()
            if run is None:
                raise HeavenEchoNotFoundError("no heaven-echo run exists")
            snapshot = self._heaven_echo_json(run["snapshot_json"])
            result = self._heaven_echo_json(run["result_json"])
            status = str(run["status"])
            if status == "routing" and datetime.fromisoformat(str(run["expires_at"])).astimezone(timezone.utc) <= now.astimezone(timezone.utc):
                status = "expired"
                result.update({"outcome": "expired", "first_clear": False, "story_flag_written": False})
            elif status == "cleared":
                intro = self._heaven_echo_json(player["intro_json"], {})
                flags = list(intro.get("flags", []))
                first_clear = HEAVEN_ECHO_STORY_FLAG not in flags
                if first_clear:
                    flags.append(HEAVEN_ECHO_STORY_FLAG)
                    intro["flags"] = flags
                    change_player_state(
                        connection,
                        player,
                        updated_at=now_text,
                        player_values={"intro_json": json.dumps(intro, ensure_ascii=False, sort_keys=True)},
                    )
                result.update({"outcome": "won", "first_clear": first_clear, "story_flag_written": first_clear})
                status = "settled"
            elif status in {"expired", "system_aborted"}:
                result.setdefault("outcome", status)
                result.update({"first_clear": False, "story_flag_written": False})
                status = "settled" if status == "expired" else "system_aborted"
            else:
                raise HeavenEchoNotReadyError("complete the route before settling")
            connection.execute("UPDATE heaven_echo_runs SET status=?, result_json=?, updated_at=? WHERE id=?", (status, json.dumps(result, ensure_ascii=False, sort_keys=True), now_text, run["id"]))
            settled = connection.execute("SELECT * FROM heaven_echo_runs WHERE id=?", (run["id"],)).fetchone()
            payload = self._heaven_echo_payload(settled, snapshot, result)
            self._heaven_echo_store_operation(connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text)
            return self._heaven_echo_record(payload)

    async def compensate_heaven_echo_system_failure(self, *, run_id: str, operation_id: str) -> HeavenEchoRunRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._retry_sync, self._heaven_echo_compensate_sync, run_id, operation_id)

    def _heaven_echo_compensate_sync(self, run_id, operation_id):
        operation_name = "heaven_echo.system_abort"
        request_hash = self._request_hash(operation_name, {"run_id": run_id})
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._heaven_echo_operation(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                return self._heaven_echo_record(replay, replay=True)
            run = connection.execute("SELECT * FROM heaven_echo_runs WHERE run_id=?", (run_id,)).fetchone()
            if run is None or str(run["status"]) not in ACTIVE_HEAVEN_ECHO_STATUSES:
                raise HeavenEchoNotReadyError("only an active heaven-echo run can be compensated")
            result = {"outcome": "system_aborted", "resource_refunded": {}}
            connection.execute("UPDATE heaven_echo_runs SET status='system_aborted', result_json=?, updated_at=? WHERE id=?", (json.dumps(result, ensure_ascii=False, sort_keys=True), now_text, run["id"]))
            updated = connection.execute("SELECT * FROM heaven_echo_runs WHERE id=?", (run["id"],)).fetchone()
            payload = self._heaven_echo_payload(updated, self._heaven_echo_json(run["snapshot_json"]), result)
            self._heaven_echo_store_operation(connection, operation_id, operation_name, int(run["player_id"]), request_hash, payload, now_text)
            return self._heaven_echo_record(payload)


__all__ = ["HeavenEchoRepositoryMixin"]
