"""Transactional secret-realm runs, separate from the general adventure repository."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from ...contracts import serialize_datetime
from ..utils.json import json_object
from ..utils.assets import grant_player_items, inventory_amount
from ..utils.player import (
    grant_player_reward,
    change_player_state,
    spend_player_state,
    player_integer,
    player_inventory,
    player_reputation_state,
)
from ..rewards.rules import local_reputation_maximum
from ..specials.codex_projection import record_codex_discovery
from ..specials.codex_rules import category_for_entry
from ..utils.equipment import create_equipment_instances
from .secret_realm_models import SecretRealmPreviewRecord, SecretRealmRunRecord
from .secret_realm_rules import (
    DEFINITIONS,
    realm_at_least,
    secret_realm_definition,
)
from ..persistence.errors import (
    OperationConflictError,
    ResourceInsufficientError,
    SecretRealmAlreadySettledError,
    SecretRealmBusyError,
    SecretRealmCombatPendingError,
    SecretRealmNodeError,
    SecretRealmNotFoundError,
    SecretRealmNotReadyError,
    SecretRealmQuotaError,
    SecretRealmRequirementError,
)


class SecretRealmRepositoryMixin:
    """Persist the server-owned route and resource locks for one run."""

    async def preview_secret_realms(self, *, platform: str, platform_user_id: str) -> SecretRealmPreviewRecord:
        await self.initialize()
        return await asyncio.to_thread(self._preview_secret_realms_sync, platform, platform_user_id)

    def _preview_secret_realms_sync(self, platform: str, platform_user_id: str) -> SecretRealmPreviewRecord:
        with self._connect() as connection:
            player = self._require_player(connection, platform, platform_user_id, writable=False)
            active = connection.execute(
                "SELECT run_id FROM secret_realm_runs WHERE player_id=? AND status IN ('entered','routing','combat_pending','cleared','failed') ORDER BY id DESC LIMIT 1",
                (player["id"],),
            ).fetchone()
            return SecretRealmPreviewRecord(
                player=self._row_to_player(player),
                definitions=tuple(DEFINITIONS.values()),
                active_run_id=str(active["run_id"]) if active else None,
            )

    async def enter_secret_realm(
        self, *, platform: str, platform_user_id: str, instance_key: str, operation_id: str
    ) -> SecretRealmRunRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._enter_secret_realm_sync, platform, platform_user_id, instance_key, operation_id
            )

    def _enter_secret_realm_sync(
        self, platform: str, platform_user_id: str, instance_key: str, operation_id: str
    ) -> SecretRealmRunRecord:
        definition = secret_realm_definition(instance_key)
        operation_name = "secret_realm.enter"
        request_hash = self._request_hash(
            operation_name,
            {"platform": platform, "platform_user_id": platform_user_id, "instance_key": definition.key},
        )
        now = self._now()
        now_text = serialize_datetime(now)
        quota_key = self._quota_key(now, definition.quota_period)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._secret_realm_operation(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                return self._run_from_payload(replay, replay=True)
            player = self._require_player(connection, platform, platform_user_id)
            if str(player["location_key"]) != definition.location_key or not realm_at_least(
                str(player["realm_key"]), player_integer(player, "realm_layer"), definition.required_realm, definition.required_layer
            ):
                raise SecretRealmRequirementError("realm or location requirement is not met")
            active = connection.execute(
                "SELECT 1 FROM secret_realm_runs WHERE player_id=? AND status IN ('entered','routing','combat_pending','cleared','failed') LIMIT 1",
                (player["id"],),
            ).fetchone()
            if active is not None:
                raise SecretRealmBusyError("another secret-realm run is active")
            if self._has_active_long_action(connection, int(player["id"])):
                raise SecretRealmBusyError("another long action is active")
            count = connection.execute(
                "SELECT COUNT(*) AS count FROM secret_realm_runs WHERE player_id=? AND instance_key=? AND quota_key=?",
                (player["id"], definition.key, quota_key),
            ).fetchone()
            if int(count["count"]) >= definition.quota_limit:
                raise SecretRealmQuotaError("secret-realm quota is exhausted")
            inventory = player_inventory(player)
            ticket = inventory_amount(inventory, definition.ticket_key) if definition.ticket_key else 0
            if definition.ticket_key and ticket < definition.ticket_quantity:
                raise SecretRealmRequirementError("secret-realm ticket is missing")
            if player_integer(player, "stamina") < definition.stamina_cost:
                raise ResourceInsufficientError("stamina is insufficient")
            spend_player_state(
                connection,
                player,
                updated_at=now_text,
                costs=(
                    {definition.ticket_key: definition.ticket_quantity}
                    if definition.ticket_key
                    else None
                ),
                value_delta={"stamina": -definition.stamina_cost},
                maximums={"stamina": player_integer(player, "stamina_max")},
            )
            run_id = uuid4().hex
            snapshot = {
                "instance_key": definition.key,
                "location_key": definition.location_key,
                "realm_key": str(player["realm_key"]),
                "realm_layer": player_integer(player, "realm_layer"),
                "node_keys": list(definition.node_keys),
                "first_clear": self._is_first_clear(connection, int(player["id"]), definition.key),
                "resource_roll": self._resource_roll(definition.key, run_id),
            }
            reward_snapshot = {
                "first": dict(definition.first_reward),
                "repeat": dict(snapshot["resource_roll"]),
            }
            local_keys = {
                key
                for reward in reward_snapshot.values()
                for key in reward
                if key.startswith("local.")
            }
            if len(local_keys) > 1:
                raise ValueError("secret realm rewards must use one local reputation key")
            local_key = next(iter(local_keys), None)
            if local_key != definition.reputation_key:
                raise ValueError("secret realm reward reputation key does not match its definition")
            local_maximum = (
                local_reputation_maximum(local_key, self.content)
                if local_key is not None
                else None
            )
            codex_categories = {
                key: category_for_entry(key, self.content)
                for reward in reward_snapshot.values()
                for key in reward
                if key.startswith("codex.")
            }
            if any(not category for category in codex_categories.values()):
                raise ValueError("secret realm reward references an unknown codex entry")
            snapshot.update(
                {
                    "reward_snapshot": reward_snapshot,
                    "local_reputation_key": local_key,
                    "local_reputation_maximum": local_maximum,
                    "codex_categories": codex_categories,
                }
            )
            expires_at = serialize_datetime(now + timedelta(seconds=definition.expiry_seconds))
            connection.execute(
                """
                INSERT INTO secret_realm_runs(
                    run_id, player_id, instance_key, status, node_index, starts_at, expires_at,
                    quota_period, quota_key, ticket_key, ticket_locked, stamina_locked,
                    snapshot_json, result_json, created_at, updated_at
                ) VALUES (?, ?, ?, 'entered', 0, ?, ?, ?, ?, ?, ?, ?, ?, '{}', ?, ?)
                """,
                (
                    run_id,
                    player["id"],
                    definition.key,
                    now_text,
                    expires_at,
                    definition.quota_period,
                    quota_key,
                    definition.ticket_key,
                    definition.ticket_quantity,
                    definition.stamina_cost,
                    json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
                    now_text,
                    now_text,
                ),
            )
            updated = connection.execute("SELECT * FROM players WHERE id=?", (player["id"],)).fetchone()
            payload = self._run_payload(
                updated,
                definition,
                run_id=run_id,
                status="routing",
                node_index=0,
                snapshot=snapshot,
                ticket_locked=definition.ticket_quantity,
                stamina_locked=definition.stamina_cost,
            )
            connection.execute(
                "UPDATE secret_realm_runs SET status='routing' WHERE run_id=?",
                (run_id,),
            )
            self._insert_secret_operation(connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text)
            return self._run_from_payload(payload)

    async def choose_secret_realm_node(
        self, *, platform: str, platform_user_id: str, node_key: str, operation_id: str
    ) -> SecretRealmRunRecord:
        await self.initialize()
        async with self._inflight:
            record = await asyncio.to_thread(
                self._choose_secret_realm_node_sync, platform, platform_user_id, node_key, operation_id
            )
        if record.status != "combat_pending":
            return record
        # The node index differentiates repeated encounter nodes while still
        # making retries of the same node replay the original battle.
        battle_operation = f"secret_realm.battle.start:{record.run_id}:{record.node_index}"
        try:
            battle = await self.start_quest_battle(
                platform=platform,
                platform_user_id=platform_user_id,
                enemy_key=secret_realm_definition(record.instance_key).enemy_key,
                battle_type="pve.secret_realm",
                operation_id=battle_operation,
                ignore_secret_realm_run_id=record.run_id,
            )
        except Exception:
            await asyncio.to_thread(self._mark_secret_realm_failed, record.run_id, "battle_start_failed")
            raise
        return await asyncio.to_thread(self._attach_secret_realm_battle, record.run_id, battle.battle_id, operation_id)

    def _choose_secret_realm_node_sync(
        self, platform: str, platform_user_id: str, node_key: str, operation_id: str
    ) -> SecretRealmRunRecord:
        operation_name = "secret_realm.choose_node"
        request_hash = self._request_hash(
            operation_name, {"platform": platform, "platform_user_id": platform_user_id, "node_key": node_key}
        )
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._secret_realm_operation(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                return self._run_from_payload(replay, replay=True)
            player = self._require_player(connection, platform, platform_user_id)
            run = connection.execute(
                "SELECT * FROM secret_realm_runs WHERE player_id=? AND status IN ('routing','combat_pending','cleared','failed') ORDER BY id DESC LIMIT 1",
                (player["id"],),
            ).fetchone()
            if run is None:
                raise SecretRealmNotFoundError("no active secret realm")
            definition = secret_realm_definition(str(run["instance_key"]))
            if self._expired(run):
                raise SecretRealmNotReadyError("secret realm has expired")
            snapshot = json_object(run["snapshot_json"], {})
            node_index = int(run["node_index"])
            nodes = tuple(str(item) for item in snapshot.get("node_keys", definition.node_keys))
            if str(run["status"]) != "routing" or node_index >= len(nodes) or node_key != nodes[node_index]:
                raise SecretRealmNodeError("node is not the server-authorized next node")
            if node_key == "resource":
                snapshot["resource_selected"] = True
                status = "routing"
                next_index = node_index + 1
                battle_id = None
            elif node_key == "encounter":
                if not snapshot.get("resource_selected"):
                    raise SecretRealmNodeError("resource node must be completed first")
                if node_index > 1 and snapshot.get("node_history", [])[-1:] != ["choice"]:
                    raise SecretRealmNodeError("encounter node must follow a completed choice")
                status = "combat_pending"
                next_index = node_index
                battle_id = None
            else:
                if not snapshot.get("encounter_won"):
                    raise SecretRealmNodeError("encounter must be cleared first")
                status = "cleared" if node_index + 1 >= len(nodes) else "routing"
                next_index = node_index + 1
                battle_id = None
            snapshot["node_history"] = [*snapshot.get("node_history", []), node_key]
            connection.execute(
                "UPDATE secret_realm_runs SET status=?, node_index=?, snapshot_json=?, updated_at=? WHERE id=?",
                (status, next_index, json.dumps(snapshot, ensure_ascii=False, sort_keys=True), now_text, run["id"]),
            )
            updated = connection.execute("SELECT * FROM players WHERE id=?", (player["id"],)).fetchone()
            payload = self._run_payload(
                updated,
                definition,
                run_id=str(run["run_id"]),
                status=status,
                node_index=next_index,
                snapshot=snapshot,
                battle_id=battle_id,
                ticket_locked=int(run["ticket_locked"]),
                stamina_locked=int(run["stamina_locked"]),
            )
            self._insert_secret_operation(connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text)
            return self._run_from_payload(payload)

    async def settle_secret_realm(
        self, *, platform: str, platform_user_id: str, operation_id: str
    ) -> SecretRealmRunRecord:
        await self.initialize()
        operation_name = "secret_realm.settle"
        request_hash = self._request_hash(operation_name, {"platform": platform, "platform_user_id": platform_user_id})
        replay = await asyncio.to_thread(self._get_secret_settle_replay, operation_id, operation_name, request_hash)
        if replay is not None:
            return self._run_from_payload(replay, replay=True)
        async with self._inflight:
            pending = await asyncio.to_thread(self._get_secret_realm_pending, platform, platform_user_id)
        if pending.status == "combat_pending":
            battle_id = pending.battle_id
            if battle_id is None:
                raise SecretRealmCombatPendingError("secret realm battle is not attached")
            turn = None
            for expected_round in range(1, 21):
                turn = await self.run_battle_turn(battle_id=battle_id, expected_round=expected_round)
                if turn.status not in {"created", "running"}:
                    break
            if turn is None or turn.status in {"created", "running"}:
                raise SecretRealmCombatPendingError("secret realm battle is still running")
            resolved = await self.resolve_battle(battle_id=battle_id)
            await asyncio.to_thread(self._apply_secret_battle_result, pending.run_id, resolved.outcome)
            progress = await asyncio.to_thread(self._get_secret_realm_pending, platform, platform_user_id)
            if progress.status == "routing":
                return await asyncio.to_thread(
                    self._record_secret_realm_progress,
                    progress,
                    operation_id,
                    operation_name,
                    request_hash,
                )
        async with self._inflight:
            return await asyncio.to_thread(
                self._settle_secret_realm_sync, platform, platform_user_id, operation_id
            )

    def _get_secret_realm_pending(self, platform: str, platform_user_id: str) -> SecretRealmRunRecord:
        with self._connect() as connection:
            player = self._require_player(connection, platform, platform_user_id)
            run = connection.execute(
                "SELECT * FROM secret_realm_runs WHERE player_id=? AND status IN ('routing','combat_pending','cleared','failed') ORDER BY id DESC LIMIT 1",
                (player["id"],),
            ).fetchone()
            if run is None:
                raise SecretRealmNotFoundError("no active secret realm")
            definition = secret_realm_definition(str(run["instance_key"]))
            snapshot = json_object(run["snapshot_json"], {})
            return self._run_from_payload(
                self._run_payload(
                    player,
                    definition,
                    run_id=str(run["run_id"]),
                    status=str(run["status"]),
                    node_index=int(run["node_index"]),
                    snapshot=snapshot,
                    battle_id=run["battle_id"],
                    reward=json_object(run["result_json"], {}).get("reward", {}),
                    first_clear=bool(snapshot.get("first_clear")),
                    ticket_locked=int(run["ticket_locked"]),
                    stamina_locked=int(run["stamina_locked"]),
                )
            )

    def _record_secret_realm_progress(
        self,
        record: SecretRealmRunRecord,
        operation_id: str,
        operation_name: str,
        request_hash: str,
    ) -> SecretRealmRunRecord:
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._secret_realm_operation(connection, operation_id, operation_name, request_hash)
            if existing is not None:
                return self._run_from_payload(existing, replay=True)
            player = connection.execute("SELECT * FROM players WHERE player_id=?", (record.player.player_id,)).fetchone()
            if player is None:
                raise SecretRealmNotFoundError("secret realm player does not exist")
            definition = secret_realm_definition(record.instance_key)
            payload = self._run_payload(
                player,
                definition,
                run_id=record.run_id,
                status=record.status,
                node_index=record.node_index,
                snapshot={"node_keys": list(definition.node_keys), "first_clear": record.first_clear},
                battle_id=record.battle_id,
                ticket_locked=record.ticket_locked,
                stamina_locked=record.stamina_locked,
            )
            self._insert_secret_operation(connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text)
            return self._run_from_payload(payload)

    def _settle_secret_realm_sync(self, platform: str, platform_user_id: str, operation_id: str) -> SecretRealmRunRecord:
        operation_name = "secret_realm.settle"
        request_hash = self._request_hash(operation_name, {"platform": platform, "platform_user_id": platform_user_id})
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._secret_realm_operation(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                return self._run_from_payload(replay, replay=True)
            player = self._require_player(connection, platform, platform_user_id)
            run = connection.execute(
                "SELECT * FROM secret_realm_runs WHERE player_id=? ORDER BY id DESC LIMIT 1", (player["id"],)
            ).fetchone()
            if run is None:
                raise SecretRealmNotFoundError("no secret realm run")
            status = str(run["status"])
            definition = secret_realm_definition(str(run["instance_key"]))
            snapshot = json_object(run["snapshot_json"], {})
            result = json_object(run["result_json"], {})
            if status in {"routing", "combat_pending"}:
                if self._expired(run):
                    status = "expired"
                else:
                    raise SecretRealmNotReadyError("secret realm is not at a settlement state")
            if status == "failed":
                self._refund_ticket(connection, player, run, now_text)
                result = {"reward": {}, "outcome": "lost", "ticket_refunded": bool(run["ticket_key"])}
            elif status == "expired":
                self._refund_ticket(connection, player, run, now_text)
                result = {"reward": {}, "outcome": "expired", "ticket_refunded": bool(run["ticket_key"]), "stamina_refunded": int(run["stamina_locked"])}
                change_player_state(
                    connection,
                    player,
                    updated_at=now_text,
                    value_delta={"stamina": int(run["stamina_locked"])},
                    maximums={"stamina": player["stamina_max"]},
                )
            elif status == "cleared":
                first_clear = bool(snapshot.get("first_clear"))
                # Roll the resource node once at entry and keep that result in
                # the frozen snapshot for deterministic settlement/replay.
                reward_snapshot = snapshot.get("reward_snapshot")
                if (
                    not isinstance(reward_snapshot, dict)
                    or set(reward_snapshot) != {"first", "repeat"}
                    or any(not isinstance(value, dict) for value in reward_snapshot.values())
                ):
                    raise ValueError("secret realm reward snapshot is missing")
                local_keys = {
                    key
                    for value in reward_snapshot.values()
                    for key in value
                    if isinstance(key, str) and key.startswith("local.")
                }
                if (
                    local_keys != ({definition.reputation_key} if definition.reputation_key else set())
                    or snapshot.get("local_reputation_key") != definition.reputation_key
                ):
                    raise ValueError("secret realm reputation snapshot does not match its definition")
                reputation_maximum = snapshot.get("local_reputation_maximum")
                if definition.reputation_key is None:
                    if reputation_maximum is not None:
                        raise ValueError("secret realm reputation maximum has no matching key")
                elif (
                    isinstance(reputation_maximum, bool)
                    or not isinstance(reputation_maximum, int)
                    or reputation_maximum <= 0
                ):
                    raise ValueError("secret realm reputation maximum snapshot is invalid")
                expected_categories = {
                    key
                    for value in reward_snapshot.values()
                    for key in value
                    if isinstance(key, str) and key.startswith("codex.")
                }
                categories = snapshot.get("codex_categories")
                if (
                    not isinstance(categories, dict)
                    or set(categories) != expected_categories
                    or any(not isinstance(value, str) or not value for value in categories.values())
                ):
                    raise ValueError("secret realm codex snapshot is invalid")
                for reward_map in reward_snapshot.values():
                    for key, quantity in reward_map.items():
                        if (
                            not isinstance(key, str)
                            or not key
                            or isinstance(quantity, bool)
                            or not isinstance(quantity, int)
                            or quantity < 0
                        ):
                            raise ValueError("secret realm reward snapshot contains an invalid amount")
                reward = dict(reward_snapshot["first" if first_clear else "repeat"])
                reward = self._apply_reward(
                    connection,
                    player,
                    reward,
                    now_text,
                    operation_id=operation_id,
                    snapshot=snapshot,
                )
                result = {"reward": reward, "outcome": "won", "first_clear": first_clear}
            elif status == "settled":
                raise SecretRealmAlreadySettledError("secret realm is already settled")
            else:
                raise SecretRealmNotReadyError("secret realm is not ready to settle")
            connection.execute(
                "UPDATE secret_realm_runs SET status='settled', result_json=?, updated_at=? WHERE id=?",
                (json.dumps(result, ensure_ascii=False, sort_keys=True), now_text, run["id"]),
            )
            updated = connection.execute("SELECT * FROM players WHERE id=?", (player["id"],)).fetchone()
            payload = self._run_payload(
                updated,
                definition,
                run_id=str(run["run_id"]),
                status="settled",
                node_index=int(run["node_index"]),
                snapshot=snapshot,
                battle_id=run["battle_id"],
                reward=result.get("reward", {}),
                first_clear=bool(result.get("first_clear", False)),
                ticket_locked=int(run["ticket_locked"]),
                stamina_locked=int(run["stamina_locked"]),
            )
            payload["outcome"] = result.get("outcome")
            payload["ticket_refunded"] = result.get("ticket_refunded", False)
            payload["stamina_refunded"] = result.get("stamina_refunded", 0)
            self._insert_secret_operation(connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text)
            return self._run_from_payload(payload)

    def _apply_secret_battle_result(self, run_id: str, outcome: str) -> None:
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            run = connection.execute("SELECT * FROM secret_realm_runs WHERE run_id=?", (run_id,)).fetchone()
            if run is None or str(run["status"]) != "combat_pending":
                return
            snapshot = json_object(run["snapshot_json"], {})
            snapshot["encounter_outcome"] = outcome
            snapshot["encounter_won"] = outcome == "won"
            if outcome == "won":
                next_status = "routing" if int(run["node_index"]) + 1 < len(snapshot.get("node_keys", [])) else "cleared"
                next_index = int(run["node_index"]) + 1
            else:
                next_status = "failed"
                next_index = int(run["node_index"])
            connection.execute(
                "UPDATE secret_realm_runs SET status=?, node_index=?, snapshot_json=?, updated_at=? WHERE id=?",
                (next_status, next_index, json.dumps(snapshot, ensure_ascii=False, sort_keys=True), now_text, run["id"]),
            )

    def _attach_secret_realm_battle(self, run_id: str, battle_id: str, choose_operation_id: str) -> SecretRealmRunRecord:
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            run = connection.execute("SELECT * FROM secret_realm_runs WHERE run_id=?", (run_id,)).fetchone()
            if run is None:
                raise SecretRealmNotFoundError("secret realm run does not exist")
            connection.execute("UPDATE secret_realm_runs SET battle_id=?, updated_at=? WHERE id=?", (battle_id, now_text, run["id"]))
            player = connection.execute("SELECT * FROM players WHERE id=?", (run["player_id"],)).fetchone()
            definition = secret_realm_definition(str(run["instance_key"]))
            payload = self._run_payload(
                player, definition, run_id=run_id, status=str(run["status"]), node_index=int(run["node_index"]),
                snapshot=json_object(run["snapshot_json"], {}), battle_id=battle_id,
                ticket_locked=int(run["ticket_locked"]), stamina_locked=int(run["stamina_locked"]),
            )
            connection.execute(
                "UPDATE operations SET result_json=? WHERE operation_id=? AND operation_name='secret_realm.choose_node'",
                (json.dumps(payload, ensure_ascii=False, sort_keys=True), choose_operation_id),
            )
            return self._run_from_payload(payload)

    def _mark_secret_realm_failed(self, run_id: str, reason: str) -> None:
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            connection.execute("UPDATE secret_realm_runs SET status='failed', result_json=?, updated_at=? WHERE run_id=? AND status='combat_pending'", (json.dumps({"outcome": "lost", "reason": reason}, ensure_ascii=False), now_text, run_id))

    @staticmethod
    def _quota_key(now: datetime, period: str) -> str:
        if period == "day":
            return now.date().isoformat()
        return (now.date() - timedelta(days=now.weekday())).isoformat()

    @staticmethod
    def _resource_roll(instance_key: str, run_id: str) -> dict[str, int]:
        quantity = int(run_id[-1], 16) % 2
        if instance_key.endswith("mist_grotto"):
            return {"item.material.mist_core": quantity}
        if instance_key.endswith("spring_path"):
            return {"item.herb.spirit_leaf": quantity}
        if instance_key.endswith("mist_depth_2"):
            return {"item.material.cloud_iron": quantity}
        if instance_key.endswith("cloud_boat"):
            return {"item.ticket.cloud_boat_fragment": quantity}
        raise ValueError(f"unsupported secret-realm resource roll: {instance_key}")

    @staticmethod
    def _is_first_clear(connection: sqlite3.Connection, player_id: int, instance_key: str) -> bool:
        row = connection.execute(
            "SELECT 1 FROM secret_realm_runs WHERE player_id=? AND instance_key=? AND status='settled' AND json_extract(result_json, '$.first_clear') = 1 LIMIT 1",
            (player_id, instance_key),
        ).fetchone()
        return row is None

    def _expired(self, run: sqlite3.Row) -> bool:
        return self._now() >= datetime.fromisoformat(str(run["expires_at"]))

    @staticmethod
    def _refund_ticket(connection: sqlite3.Connection, player: sqlite3.Row, run: sqlite3.Row, now_text: str) -> None:
        key = run["ticket_key"]
        if not key:
            return
        grant_player_items(
            connection,
            player,
            {str(key): int(run["ticket_locked"])},
            now_text,
        )

    def _apply_reward(
        self,
        connection: sqlite3.Connection,
        player: sqlite3.Row,
        reward: dict[str, int],
        now_text: str,
        *,
        operation_id: str,
        snapshot: dict[str, Any],
    ) -> dict[str, int]:
        state_reward: dict[str, int] = {}
        codex_reward: dict[str, int] = {}
        reputation_key = snapshot.get("local_reputation_key")
        reputation_maximum = snapshot.get("local_reputation_maximum")
        for key, value in reward.items():
            if key.startswith("codex."):
                codex_reward[key] = int(value)
            elif key.startswith(("item.weapon.", "item.armor.", "item.accessory.")):
                if not create_equipment_instances(
                    connection,
                    player_id=int(player["id"]),
                    item_key=key,
                    quantity=int(value),
                    now_text=now_text,
                    durability_bp=10_000,
                ):
                    raise RuntimeError(f"equipment definition disappeared: {key}")
            else:
                state_reward[key] = int(value)

        maximums = None
        before = None
        if reputation_key is not None:
            if not isinstance(reputation_maximum, int) or reputation_maximum <= 0:
                raise ValueError("secret realm local reputation snapshot is invalid")
            local_amount = int(state_reward.get(reputation_key, 0))
            if local_amount:
                before = player_reputation_state(connection, int(player["id"]))
                maximums = {reputation_key: reputation_maximum}
        if state_reward:
            grant_player_reward(
                connection,
                player,
                state_reward,
                now_text,
                local_reputation_maximums=maximums,
            )
        if before is not None:
            after = player_reputation_state(connection, int(player["id"]))
            reward[reputation_key] = after.local.get(reputation_key, 0) - before.local.get(reputation_key, 0)

        categories = snapshot.get("codex_categories")
        if not isinstance(categories, dict) or any(key not in categories for key in codex_reward):
            raise ValueError("secret realm codex snapshot is invalid")
        for key, quantity in codex_reward.items():
            if quantity <= 0 or not record_codex_discovery(
                connection,
                player_id=int(player["id"]),
                entry_key=key,
                operation_id=f"{operation_id}:codex:{key}",
                occurred_at=now_text,
                snapshot={"instance_key": snapshot.get("instance_key")},
                category_snapshot=categories[key],
            ):
                raise ValueError(f"secret realm codex reward could not be recorded: {key}")
        return reward

    def _run_payload(self, player: sqlite3.Row, definition, *, run_id: str, status: str, node_index: int, snapshot: dict[str, Any], battle_id: str | None = None, reward: dict[str, int] | None = None, first_clear: bool | None = None, ticket_locked: int = 0, stamina_locked: int = 0) -> dict[str, Any]:
        nodes = tuple(str(item) for item in snapshot.get("node_keys", definition.node_keys))
        return {
            "player": self._player_payload(self._row_to_player(player)),
            "run_id": run_id,
            "instance_key": definition.key,
            "label": definition.label,
            "status": status,
            "node_index": node_index,
            "current_node": nodes[node_index] if status == "routing" and node_index < len(nodes) else None,
            "allowed_nodes": (nodes[node_index],) if status == "routing" and node_index < len(nodes) else (),
            "battle_id": battle_id,
            "reward": reward or {},
            "first_clear": bool(snapshot.get("first_clear")) if first_clear is None else first_clear,
            "ticket_locked": ticket_locked,
            "stamina_locked": stamina_locked,
        }

    @staticmethod
    def _run_from_payload(payload: dict[str, Any], replay: bool = False) -> SecretRealmRunRecord:
        from ..persistence.sqlite_repository import SQLitePlayerRepository

        return SecretRealmRunRecord(
            player=SQLitePlayerRepository._row_to_player(payload["player"]),
            run_id=str(payload["run_id"]), instance_key=str(payload["instance_key"]), label=str(payload["label"]),
            status=str(payload["status"]), node_index=int(payload["node_index"]), current_node=payload.get("current_node"),
            allowed_nodes=tuple(str(item) for item in payload.get("allowed_nodes", ())), battle_id=payload.get("battle_id"),
            reward={str(key): int(value) for key, value in dict(payload.get("reward", {})).items()},
            first_clear=bool(payload.get("first_clear", False)), ticket_locked=int(payload.get("ticket_locked", 0)),
            stamina_locked=int(payload.get("stamina_locked", 0)), outcome=payload.get("outcome"),
            ticket_refunded=bool(payload.get("ticket_refunded", False)),
            stamina_refunded=int(payload.get("stamina_refunded", 0)), already_completed=replay,
        )

    def _get_secret_settle_replay(self, operation_id: str, operation_name: str, request_hash: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            return self._secret_realm_operation(connection, operation_id, operation_name, request_hash)

    @staticmethod
    def _secret_realm_operation(connection: sqlite3.Connection, operation_id: str, operation_name: str, request_hash: str) -> dict[str, Any] | None:
        existing = connection.execute("SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id=?", (operation_id,)).fetchone()
        if existing is None:
            return None
        if existing["operation_name"] != operation_name or existing["request_hash"] != request_hash:
            raise OperationConflictError("operation input differs from its original request")
        return json.loads(existing["result_json"])

    @staticmethod
    def _insert_secret_operation(connection: sqlite3.Connection, operation_id: str, operation_name: str, player_id: int, request_hash: str, payload: dict[str, Any], now_text: str) -> None:
        connection.execute("INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)", (operation_id, operation_name, player_id, request_hash, json.dumps(payload, ensure_ascii=False, sort_keys=True), now_text))


__all__ = ["SecretRealmRepositoryMixin"]
