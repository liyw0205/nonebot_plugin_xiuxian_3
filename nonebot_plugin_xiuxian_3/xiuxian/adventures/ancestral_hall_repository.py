"""Persistence for the solo ancestral-hall secret realm."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from ...contracts import serialize_datetime
from ..content import bundled_content
from ..specials.codex_projection import record_codex_discovery
from ..persistence.errors import (
    AncestralHallBusyError,
    AncestralHallNodeError,
    AncestralHallNotFoundError,
    AncestralHallNotReadyError,
    AncestralHallQuotaError,
    AncestralHallRequirementError,
    OperationConflictError,
    ResourceInsufficientError,
)
from ..combat.rules import MAX_TURNS
from ..utils.player import change_player_state, player_integer
from .ancestral_hall_models import AncestralHallRunRecord
from .ancestral_hall_rules import (
    ANCESTRAL_HALL_ENEMY,
    ANCESTRAL_HALL_EXPIRY_SECONDS,
    ANCESTRAL_HALL_KEY,
    ANCESTRAL_HALL_LOCATION,
    ANCESTRAL_HALL_NODES,
    ANCESTRAL_HALL_STAMINA_COST,
    ANCESTRAL_HALL_STORY_FLAG,
    ANCESTRAL_HALL_CODEX_ENTRY,
)
from .secret_realm_rules import realm_at_least


ACTIVE_STATUSES = ("routing", "combat_pending", "cleared")


class AncestralHallRepositoryMixin:
    """Own ancestral-hall route, quota, combat handoff, and settlement transactions."""

    @staticmethod
    def _hall_json(raw: Any, default: dict[str, Any] | None = None) -> dict[str, Any]:
        value = json.loads(raw) if isinstance(raw, str) else raw
        return dict(value) if isinstance(value, dict) else dict(default or {})

    @staticmethod
    def _hall_week_key(now: datetime) -> str:
        return now.astimezone(timezone.utc).strftime("%G-W%V")

    def _hall_operation(self, connection, operation_id: str, operation_name: str, request_hash: str):
        row = connection.execute(
            "SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id=?",
            (operation_id,),
        ).fetchone()
        if row is None:
            return None
        if str(row["operation_name"]) != operation_name or str(row["request_hash"]) != request_hash:
            raise OperationConflictError("operation ID was reused with different input")
        return self._hall_json(row["result_json"])

    @staticmethod
    def _hall_store_operation(connection, operation_id, operation_name, player_id, request_hash, payload, now_text):
        connection.execute(
            "INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (operation_id, operation_name, player_id, request_hash,
             json.dumps(payload, ensure_ascii=False, sort_keys=True), now_text),
        )

    def _hall_payload(self, run, snapshot: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        index = int(run["node_index"])
        status = str(run["status"])
        nodes = tuple(str(key) for key in snapshot.get("node_keys", ANCESTRAL_HALL_NODES))
        current = nodes[index] if status in {"routing", "combat_pending"} and index < len(nodes) else None
        return {
            "run_id": str(run["run_id"]),
            "status": status,
            "node_index": index,
            "current_node": current,
            "battle_id": run["battle_id"],
            "outcome": result.get("outcome"),
            "expires_at": str(run["expires_at"]),
            "first_clear": bool(result.get("first_clear", snapshot.get("first_clear", False))),
            "story_flag_written": bool(result.get("story_flag_written", False)),
        }

    @staticmethod
    def _hall_record(payload: dict[str, Any], *, replay: bool = False) -> AncestralHallRunRecord:
        return AncestralHallRunRecord(
            run_id=str(payload["run_id"]),
            status=str(payload["status"]),
            node_index=int(payload.get("node_index", 0)),
            current_node=payload.get("current_node"),
            battle_id=payload.get("battle_id"),
            outcome=payload.get("outcome"),
            expires_at=str(payload.get("expires_at", "")),
            first_clear=bool(payload.get("first_clear", False)),
            already_completed=replay or bool(payload.get("already_completed", False)),
            story_flag_written=bool(payload.get("story_flag_written", False)),
        )

    async def has_active_ancestral_hall(self, *, platform: str, platform_user_id: str) -> bool:
        await self.initialize()
        return await asyncio.to_thread(self._has_active_ancestral_hall_sync, platform, platform_user_id)

    def _has_active_ancestral_hall_sync(self, platform: str, platform_user_id: str) -> bool:
        with self._connect() as connection:
            player = self._require_player(connection, platform, platform_user_id, writable=False)
            return connection.execute(
                "SELECT 1 FROM ancestral_hall_runs WHERE player_id=? AND status IN ('routing','combat_pending','cleared') LIMIT 1",
                (player["id"],),
            ).fetchone() is not None

    async def has_latest_ancestral_hall(self, *, platform: str, platform_user_id: str) -> bool:
        await self.initialize()
        return await asyncio.to_thread(self._has_latest_ancestral_hall_sync, platform, platform_user_id)

    def _has_latest_ancestral_hall_sync(self, platform: str, platform_user_id: str) -> bool:
        with self._connect() as connection:
            player = self._require_player(connection, platform, platform_user_id, writable=False)
            hall = connection.execute(
                "SELECT starts_at FROM ancestral_hall_runs WHERE player_id=? ORDER BY id DESC LIMIT 1",
                (player["id"],),
            ).fetchone()
            if hall is None:
                return False
            other_runs = connection.execute(
                "SELECT MAX(created_at) AS latest FROM secret_realm_runs WHERE player_id=?",
                (player["id"],),
            ).fetchone()
            latest_other = str(other_runs["latest"] or "")
            other_party_instance = connection.execute(
                "SELECT MAX(starts_at) AS latest FROM ancient_domain_runs r "
                "JOIN ancient_domain_members m ON m.run_id=r.run_id WHERE m.player_id=?",
                (player["id"],),
            ).fetchone()
            latest_other = max(latest_other, str(other_party_instance["latest"] or ""))
            return not latest_other or str(hall["starts_at"]) >= latest_other

    async def has_ancestral_hall_settlement_operation(self, operation_id: str) -> bool:
        await self.initialize()
        return await asyncio.to_thread(self._has_ancestral_hall_settlement_operation_sync, operation_id)

    def _has_ancestral_hall_settlement_operation_sync(self, operation_id: str) -> bool:
        with self._connect() as connection:
            return connection.execute(
                "SELECT 1 FROM operations WHERE operation_id=? AND operation_name='ancestral_hall.settle'",
                (operation_id,),
            ).fetchone() is not None

    async def enter_ancestral_hall(
        self, *, platform: str, platform_user_id: str, operation_id: str
    ) -> AncestralHallRunRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._retry_sync, self._hall_enter_sync, platform, platform_user_id, operation_id
            )

    def _hall_enter_sync(self, platform: str, platform_user_id: str, operation_id: str) -> AncestralHallRunRecord:
        operation_name = "ancestral_hall.enter"
        request_hash = self._request_hash(operation_name, {
            "platform": platform, "platform_user_id": platform_user_id, "instance_key": ANCESTRAL_HALL_KEY,
        })
        now = self._now()
        now_text = serialize_datetime(now)
        quota_key = self._hall_week_key(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._hall_operation(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                replay["already_completed"] = True
                return self._hall_record(replay, replay=True)
            player = self._require_player(connection, platform, platform_user_id)
            if (
                str(player["location_key"]) != ANCESTRAL_HALL_LOCATION
                or not realm_at_least(str(player["realm_key"]), player_integer(player, "realm_layer"), "soul_transformation", 1)
            ):
                raise AncestralHallRequirementError("realm or location requirement is not met")
            faction = self._json_object(player["faction_reputation_json"], {})
            if int(faction.get("beast", 0)) < 3000 or player_integer(player, "bloodline_stability") < 50:
                raise AncestralHallRequirementError("beast reputation or bloodline stability is too low")
            if connection.execute(
                "SELECT 1 FROM ancestral_hall_runs WHERE player_id=? AND status IN ('routing','combat_pending','cleared') LIMIT 1",
                (player["id"],),
            ).fetchone():
                raise AncestralHallBusyError("ancestral-hall run is already active")
            if self._has_active_long_action(connection, int(player["id"])):
                raise AncestralHallBusyError("another long action is active")
            attempts = connection.execute(
                "SELECT COUNT(*) AS count FROM ancestral_hall_runs WHERE player_id=? AND quota_key=? AND status<>'system_aborted'",
                (player["id"], quota_key),
            ).fetchone()
            if int(attempts["count"]) >= 1:
                raise AncestralHallQuotaError("ancestral-hall weekly quota is exhausted")
            if player_integer(player, "stamina") < ANCESTRAL_HALL_STAMINA_COST:
                raise ResourceInsufficientError("stamina is insufficient")

            intro = self._json_object(player["intro_json"], {})
            run_id = f"ancestral-hall-{uuid4().hex}"
            expires_at = serialize_datetime(now + timedelta(seconds=ANCESTRAL_HALL_EXPIRY_SECONDS))
            snapshot = {
                "instance_key": ANCESTRAL_HALL_KEY,
                "location_key": ANCESTRAL_HALL_LOCATION,
                "realm_key": str(player["realm_key"]),
                "realm_layer": player_integer(player, "realm_layer"),
                "beast_reputation": int(faction.get("beast", 0)),
                "bloodline_stability": player_integer(player, "bloodline_stability"),
                "node_keys": list(ANCESTRAL_HALL_NODES),
                "first_clear": ANCESTRAL_HALL_STORY_FLAG not in set(intro.get("flags", [])),
            }
            try:
                change_player_state(
                    connection,
                    player,
                    updated_at=now_text,
                    value_delta={"stamina": -ANCESTRAL_HALL_STAMINA_COST},
                )
            except ValueError:
                raise ResourceInsufficientError("stamina changed during entry")
            connection.execute(
                "INSERT INTO ancestral_hall_runs(run_id, player_id, status, node_index, battle_id, quota_key, starts_at, expires_at, stamina_cost, snapshot_json, result_json, entry_operation_id, created_at, updated_at) "
                "VALUES (?, ?, 'routing', 0, NULL, ?, ?, ?, ?, ?, '{}', ?, ?, ?)",
                (run_id, player["id"], quota_key, now_text, expires_at, ANCESTRAL_HALL_STAMINA_COST,
                 json.dumps(snapshot, ensure_ascii=False, sort_keys=True), operation_id,
                 now_text, now_text),
            )
            run = connection.execute("SELECT * FROM ancestral_hall_runs WHERE run_id=?", (run_id,)).fetchone()
            payload = self._hall_payload(run, snapshot, {})
            self._hall_store_operation(connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text)
            return self._hall_record(payload)

    async def choose_ancestral_hall_node(
        self, *, platform: str, platform_user_id: str, node_key: str, operation_id: str
    ) -> AncestralHallRunRecord:
        await self.initialize()
        async with self._inflight:
            record = await asyncio.to_thread(
                self._retry_sync, self._hall_choose_sync, platform, platform_user_id, node_key, operation_id
            )
        if record.status == "expired":
            if record.battle_id:
                await self.expire_battle_session(battle_id=record.battle_id, reason="ancestral_hall_expired")
                await self.resolve_battle(battle_id=record.battle_id)
            return record
        if record.status != "combat_pending" or record.battle_id:
            return record
        try:
            battle = await self.start_quest_battle(
                platform=platform,
                platform_user_id=platform_user_id,
                enemy_key=ANCESTRAL_HALL_ENEMY,
                battle_type="pve.secret_realm.ancestral_hall",
                operation_id=f"ancestral_hall.battle.start:{record.run_id}",
                ignore_ancestral_hall_run_id=record.run_id,
            )
            return await asyncio.to_thread(
                self._hall_attach_battle, record.run_id, battle.battle_id, operation_id
            )
        except Exception:
            await self.compensate_ancestral_hall_system_failure(
                run_id=record.run_id,
                operation_id=f"ancestral_hall.system_abort:start:{record.run_id}",
            )
            raise

    def _hall_choose_sync(self, platform, platform_user_id, node_key, operation_id):
        operation_name = "ancestral_hall.choose_node"
        request_hash = self._request_hash(operation_name, {
            "platform": platform, "platform_user_id": platform_user_id, "node_key": node_key,
        })
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._hall_operation(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                if replay.get("status") == "combat_pending" and not replay.get("battle_id"):
                    player = self._require_player(connection, platform, platform_user_id)
                    run = self._hall_active_run(connection, int(player["id"]))
                    if run is not None:
                        return self._hall_record(self._hall_payload(
                            run, self._hall_json(run["snapshot_json"]), self._hall_json(run["result_json"])
                        ), replay=True)
                return self._hall_record(replay, replay=True)
            player = self._require_player(connection, platform, platform_user_id)
            run = self._hall_active_run(connection, int(player["id"]))
            if run is None:
                raise AncestralHallNotFoundError("no active ancestral-hall run")
            if self._hall_expired(run, now):
                connection.execute(
                    "UPDATE ancestral_hall_runs SET status='expired', result_json=?, updated_at=? WHERE id=?",
                    (json.dumps({"outcome": "expired"}, sort_keys=True), now_text, run["id"]),
                )
                expired = connection.execute("SELECT * FROM ancestral_hall_runs WHERE id=?", (run["id"],)).fetchone()
                payload = self._hall_payload(expired, self._hall_json(run["snapshot_json"]), {"outcome": "expired"})
                self._hall_store_operation(connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text)
                return self._hall_record(payload)
            if str(run["status"]) != "routing":
                raise AncestralHallNotReadyError("ancestral-hall run is not routing")
            snapshot = self._hall_json(run["snapshot_json"])
            nodes = tuple(str(item) for item in snapshot.get("node_keys", ANCESTRAL_HALL_NODES))
            index = int(run["node_index"])
            if index >= len(nodes) or nodes[index] != node_key:
                raise AncestralHallNodeError("node is not the current route node")
            status = "combat_pending" if node_key == "ancestral_spirit" else "cleared" if node_key == "founder_altar" else "routing"
            next_index = index if status == "combat_pending" else index + 1
            connection.execute(
                "UPDATE ancestral_hall_runs SET status=?, node_index=?, battle_id=NULL, updated_at=? WHERE id=?",
                (status, next_index, now_text, run["id"]),
            )
            updated = connection.execute("SELECT * FROM ancestral_hall_runs WHERE id=?", (run["id"],)).fetchone()
            result = self._hall_json(updated["result_json"])
            payload = self._hall_payload(updated, snapshot, result)
            self._hall_store_operation(connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text)
            return self._hall_record(payload)

    def _hall_attach_battle(self, run_id: str, battle_id: str, choose_operation_id: str) -> AncestralHallRunRecord:
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            run = connection.execute("SELECT * FROM ancestral_hall_runs WHERE run_id=?", (run_id,)).fetchone()
            if run is None or str(run["status"]) != "combat_pending":
                raise AncestralHallNotReadyError("ancestral-spirit battle is no longer pending")
            attached = str(run["battle_id"] or battle_id)
            connection.execute(
                "UPDATE ancestral_hall_runs SET battle_id=?, updated_at=? WHERE id=?",
                (attached, now_text, run["id"]),
            )
            updated = connection.execute("SELECT * FROM ancestral_hall_runs WHERE id=?", (run["id"],)).fetchone()
            payload = self._hall_payload(updated, self._hall_json(run["snapshot_json"]), self._hall_json(run["result_json"]))
            payload["battle_id"] = attached
            connection.execute(
                "UPDATE operations SET result_json=? WHERE operation_id=? AND operation_name='ancestral_hall.choose_node'",
                (json.dumps(payload, ensure_ascii=False, sort_keys=True), choose_operation_id),
            )
            return self._hall_record(payload)

    async def settle_ancestral_hall(
        self, *, platform: str, platform_user_id: str, operation_id: str
    ) -> AncestralHallRunRecord:
        await self.initialize()
        operation_name = "ancestral_hall.settle"
        request_hash = self._request_hash(operation_name, {"platform": platform, "platform_user_id": platform_user_id})
        replay = await asyncio.to_thread(self._hall_settle_replay, operation_id, operation_name, request_hash)
        if replay is not None:
            return self._hall_record(replay, replay=True)
        pending = await asyncio.to_thread(self._hall_pending_sync, platform, platform_user_id)
        if pending.expires_at and datetime.fromisoformat(pending.expires_at).astimezone(timezone.utc) <= self._now():
            if pending.battle_id:
                await self.expire_battle_session(battle_id=pending.battle_id, reason="ancestral_hall_expired")
                await self.resolve_battle(battle_id=pending.battle_id)
            await asyncio.to_thread(self._hall_mark_expired, pending.run_id)
        elif pending.status == "combat_pending":
            pending = await self._ensure_ancestral_hall_battle(pending, platform, platform_user_id, "")
            turn = None
            for expected_round in range(1, MAX_TURNS + 1):
                turn = await self.run_battle_turn(battle_id=str(pending.battle_id), expected_round=expected_round)
                if turn.status not in {"created", "running"}:
                    break
            if turn is None or turn.status in {"created", "running"}:
                raise AncestralHallNotReadyError("ancestral-spirit battle is still running")
            battle = await self.resolve_battle(battle_id=str(pending.battle_id))
            await asyncio.to_thread(self._hall_apply_battle_result, pending.run_id, battle.outcome)
            progress = await asyncio.to_thread(self._hall_pending_sync, platform, platform_user_id)
            if progress.status == "routing":
                return await asyncio.to_thread(self._hall_store_settlement_progress, progress.run_id, platform, platform_user_id, operation_id, operation_name, request_hash)
        async with self._inflight:
            return await asyncio.to_thread(
                self._retry_sync, self._hall_settle_sync, platform, platform_user_id, operation_id
            )

    async def _ensure_ancestral_hall_battle(self, record, platform, platform_user_id, choose_operation_id):
        if record.battle_id:
            return record
        battle = await self.start_quest_battle(
            platform=platform,
            platform_user_id=platform_user_id,
            enemy_key=ANCESTRAL_HALL_ENEMY,
            battle_type="pve.secret_realm.ancestral_hall",
            operation_id=f"ancestral_hall.battle.start:{record.run_id}",
            ignore_ancestral_hall_run_id=record.run_id,
        )
        return await asyncio.to_thread(self._hall_attach_battle, record.run_id, battle.battle_id, choose_operation_id)

    def _hall_settle_replay(self, operation_id, operation_name, request_hash):
        with self._connect() as connection:
            return self._hall_operation(connection, operation_id, operation_name, request_hash)

    def _hall_pending_sync(self, platform, platform_user_id):
        with self._connect() as connection:
            player = self._require_player(connection, platform, platform_user_id)
            run = connection.execute(
                "SELECT * FROM ancestral_hall_runs WHERE player_id=? ORDER BY id DESC LIMIT 1", (player["id"],)
            ).fetchone()
            if run is None:
                raise AncestralHallNotFoundError("no ancestral-hall run exists")
            return self._hall_record(self._hall_payload(
                run, self._hall_json(run["snapshot_json"]), self._hall_json(run["result_json"])
            ))

    def _hall_apply_battle_result(self, run_id: str, outcome: str) -> None:
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            run = connection.execute("SELECT * FROM ancestral_hall_runs WHERE run_id=?", (run_id,)).fetchone()
            if run is None or str(run["status"]) != "combat_pending":
                return
            snapshot = self._hall_json(run["snapshot_json"])
            result = self._hall_json(run["result_json"])
            result["battle"] = {"battle_id": str(run["battle_id"]), "outcome": outcome}
            if outcome == "won":
                next_status, next_index = "routing", int(run["node_index"]) + 1
            else:
                next_status, next_index = "failed", int(run["node_index"])
                result["outcome"] = "lost"
            connection.execute(
                "UPDATE ancestral_hall_runs SET status=?, node_index=?, result_json=?, updated_at=? WHERE id=?",
                (next_status, next_index, json.dumps(result, sort_keys=True), now_text, run["id"]),
            )

    def _hall_store_settlement_progress(self, run_id, platform, platform_user_id, operation_id, operation_name, request_hash):
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._hall_operation(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                return self._hall_record(replay, replay=True)
            player = self._require_player(connection, platform, platform_user_id)
            run = connection.execute(
                "SELECT * FROM ancestral_hall_runs WHERE run_id=? AND player_id=?", (run_id, player["id"])
            ).fetchone()
            if run is None:
                raise AncestralHallNotFoundError("ancestral-hall run does not exist")
            payload = self._hall_payload(run, self._hall_json(run["snapshot_json"]), self._hall_json(run["result_json"]))
            self._hall_store_operation(connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text)
            return self._hall_record(payload)

    def _hall_settle_sync(self, platform, platform_user_id, operation_id):
        operation_name = "ancestral_hall.settle"
        request_hash = self._request_hash(operation_name, {"platform": platform, "platform_user_id": platform_user_id})
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._hall_operation(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                return self._hall_record(replay, replay=True)
            player = self._require_player(connection, platform, platform_user_id)
            run = connection.execute(
                "SELECT * FROM ancestral_hall_runs WHERE player_id=? ORDER BY id DESC LIMIT 1", (player["id"],)
            ).fetchone()
            if run is None:
                raise AncestralHallNotFoundError("no ancestral-hall run exists")
            snapshot = self._hall_json(run["snapshot_json"])
            result = self._hall_json(run["result_json"])
            status = str(run["status"])
            if status in {"routing", "combat_pending"} and self._hall_expired(run, self._now()):
                status = "expired"
                result["outcome"] = "expired"
            if status == "cleared":
                intro = self._json_object(player["intro_json"], {})
                flags = list(intro.get("flags", []))
                first_clear = ANCESTRAL_HALL_STORY_FLAG not in flags
                if first_clear:
                    flags.append(ANCESTRAL_HALL_STORY_FLAG)
                    intro["flags"] = flags
                    change_player_state(
                        connection,
                        player,
                        updated_at=now_text,
                        player_values={"intro_json": json.dumps(intro, ensure_ascii=False, sort_keys=True)},
                    )
                    content = self.content or bundled_content()
                    content.require("codex_entry", ANCESTRAL_HALL_CODEX_ENTRY, include_locked=False)
                    record_codex_discovery(
                        connection,
                        player_id=int(player["id"]),
                        entry_key=ANCESTRAL_HALL_CODEX_ENTRY,
                        operation_id=operation_id,
                        occurred_at=now_text,
                        snapshot={"run_id": str(run["run_id"]), "location_key": ANCESTRAL_HALL_LOCATION},
                        content=content,
                    )
                result.update({"outcome": "won", "first_clear": first_clear, "story_flag_written": first_clear})
                status = "settled"
            elif status == "failed":
                result.update({"outcome": "lost", "first_clear": False, "story_flag_written": False})
                status = "settled"
            elif status == "expired":
                result.update({"outcome": "expired", "first_clear": False, "story_flag_written": False})
                status = "settled"
            else:
                raise AncestralHallNotReadyError("complete the route before settling")
            connection.execute(
                "UPDATE ancestral_hall_runs SET status='settled', result_json=?, updated_at=? WHERE id=?",
                (json.dumps(result, ensure_ascii=False, sort_keys=True), now_text, run["id"]),
            )
            settled = connection.execute("SELECT * FROM ancestral_hall_runs WHERE id=?", (run["id"],)).fetchone()
            payload = self._hall_payload(settled, snapshot, result)
            self._hall_store_operation(connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text)
            return self._hall_record(payload)

    async def compensate_ancestral_hall_system_failure(
        self, *, run_id: str, operation_id: str
    ) -> AncestralHallRunRecord:
        await self.initialize()
        battle_id = await asyncio.to_thread(self._hall_battle_for_run, run_id)
        if battle_id:
            await self.expire_battle_session(battle_id=battle_id, reason="ancestral_hall_system_abort")
            await self.resolve_battle(battle_id=battle_id)
        async with self._inflight:
            return await asyncio.to_thread(self._hall_compensate_sync, run_id, operation_id)

    def _hall_battle_for_run(self, run_id: str) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT battle_id FROM ancestral_hall_runs WHERE run_id=?", (run_id,)
            ).fetchone()
            if row is None:
                return None
            if row["battle_id"]:
                return str(row["battle_id"])
            detached = connection.execute(
                "SELECT battle_id FROM battle_sessions WHERE start_operation_id=?",
                (f"ancestral_hall.battle.start:{run_id}",),
            ).fetchone()
            return str(detached["battle_id"]) if detached is not None else None

    def _hall_compensate_sync(self, run_id: str, operation_id: str) -> AncestralHallRunRecord:
        operation_name = "ancestral_hall.system_abort"
        request_hash = self._request_hash(operation_name, {"run_id": run_id})
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._hall_operation(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                return self._hall_record(replay, replay=True)
            run = connection.execute("SELECT * FROM ancestral_hall_runs WHERE run_id=?", (run_id,)).fetchone()
            if run is None or str(run["status"]) not in ACTIVE_STATUSES:
                raise AncestralHallNotReadyError("only an unsettled ancestral-hall run can be compensated")
            if run["battle_id"]:
                battle = connection.execute("SELECT status FROM battle_sessions WHERE battle_id=?", (run["battle_id"],)).fetchone()
                if battle is not None and str(battle["status"]) in {"created", "running"}:
                    raise AncestralHallNotReadyError("active automatic battle was not terminated")
            player = connection.execute(
                "SELECT * FROM players WHERE id = ?", (run["player_id"],)
            ).fetchone()
            if player is not None:
                change_player_state(
                    connection,
                    player,
                    updated_at=now_text,
                    value_delta={"stamina": int(run["stamina_cost"])},
                    maximums={"stamina": player_integer(player, "stamina_max")},
                )
            result = {"outcome": "system_aborted", "stamina_refunded": int(run["stamina_cost"]), "quota_released": True}
            connection.execute(
                "UPDATE ancestral_hall_runs SET status='system_aborted', result_json=?, updated_at=? WHERE id=?",
                (json.dumps(result, ensure_ascii=False, sort_keys=True), now_text, run["id"]),
            )
            updated = connection.execute("SELECT * FROM ancestral_hall_runs WHERE id=?", (run["id"],)).fetchone()
            payload = self._hall_payload(updated, self._hall_json(run["snapshot_json"]), result)
            self._hall_store_operation(connection, operation_id, operation_name, int(run["player_id"]), request_hash, payload, now_text)
            return self._hall_record(payload)

    def _hall_mark_expired(self, run_id: str) -> None:
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            run = connection.execute("SELECT * FROM ancestral_hall_runs WHERE run_id=?", (run_id,)).fetchone()
            if run is None or str(run["status"]) not in ACTIVE_STATUSES:
                return
            result = self._hall_json(run["result_json"])
            result.update({"outcome": "expired", "first_clear": False, "story_flag_written": False})
            connection.execute(
                "UPDATE ancestral_hall_runs SET status='expired', result_json=?, updated_at=? WHERE id=?",
                (json.dumps(result, ensure_ascii=False, sort_keys=True), now_text, run["id"]),
            )

    def _hall_active_run(self, connection, player_id: int):
        return connection.execute(
            "SELECT * FROM ancestral_hall_runs WHERE player_id=? AND status IN ('routing','combat_pending','cleared') ORDER BY id DESC LIMIT 1",
            (player_id,),
        ).fetchone()

    @staticmethod
    def _hall_expired(run, now: datetime) -> bool:
        return now.astimezone(timezone.utc) >= datetime.fromisoformat(str(run["expires_at"])).astimezone(timezone.utc)

__all__ = ["AncestralHallRepositoryMixin"]
