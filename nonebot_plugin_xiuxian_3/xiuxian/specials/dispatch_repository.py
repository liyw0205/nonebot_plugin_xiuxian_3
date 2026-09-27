"""Atomic SQLite operations for v0.1 dispatch tasks."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from ...contracts import serialize_datetime
from ..persistence.errors import (
    DispatchAlreadySettledError,
    DispatchBusyError,
    DispatchCancellationExpiredError,
    DispatchDailyLimitError,
    DispatchNotFoundError,
    DispatchNotReadyError,
    DispatchRequirementError,
    OperationConflictError,
)
from .dispatch_models import (
    DispatchAssignmentRecord,
    DispatchCancelRecord,
    DispatchPreviewRecord,
    DispatchSettlementRecord,
)
from .dispatch_rules import (
    CANCEL_WINDOW_SECONDS,
    CONTENT_VERSION,
    DISPATCHES,
    HERB_SEARCH,
    RULE_VERSION,
    TOWN_DELIVERY,
    WORKSHOP_HELP,
    DispatchDefinition,
    choose_outcome,
    resolve_dispatch,
    reward_for,
)


class DispatchRepositoryMixin:
    async def preview_dispatch(
        self, *, platform: str, platform_user_id: str, dispatch_key: str | None
    ) -> tuple[DispatchPreviewRecord, ...]:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._preview_dispatch_once, platform, platform_user_id, dispatch_key
            )

    def _preview_dispatch_once(
        self, platform: str, platform_user_id: str, dispatch_key: str | None
    ) -> tuple[DispatchPreviewRecord, ...]:
        requested = (resolve_dispatch(dispatch_key),) if dispatch_key else tuple(DISPATCHES.values())
        now = self._now()
        with self._connect() as connection:
            player = self._require_player(connection, platform, platform_user_id, writable=False)
            return tuple(
                self._dispatch_preview(connection, player, definition, now) for definition in requested
            )

    def _dispatch_preview(
        self,
        connection: sqlite3.Connection,
        player: sqlite3.Row,
        definition: DispatchDefinition,
        now: datetime,
    ) -> DispatchPreviewRecord:
        missing: list[str] = []
        stage_order = {"new_user": 0, "mortal": 1, "seeker": 2, "cultivator": 3, "suspended": -1}
        if stage_order.get(str(player["stage"]), 0) < stage_order["mortal"]:
            missing.append("需要凡人角色")
        if definition.key == HERB_SEARCH:
            intro = self._json_object(player["intro_json"], {})
            flags = {str(value) for value in intro.get("flags", [])}
            if "guide.gather_blood_grass" not in flags:
                missing.append("需要完成教学采集")
        if definition.key == WORKSHOP_HELP:
            intro = self._json_object(player["intro_json"], {})
            flags = {str(value) for value in intro.get("flags", [])}
            if "guide.choose_service" not in flags:
                missing.append("需要完成任一教学服务")
        costs = dict(definition.costs)
        if int(player["stamina"]) < costs.get("stamina", 0):
            missing.append("体力不足")
        if int(player["energy"]) < costs.get("energy", 0):
            missing.append("精力不足")
        inventory = self._json_object(player["inventory_json"], {})
        for key, amount in costs.items():
            if key.startswith("item.") and int(inventory.get(key, 0)) < amount:
                missing.append(f"{key} 不足")
        if self._has_active_long_action(connection, int(player["id"])):
            missing.append("已有进行中的长时行动")
        used_row = connection.execute(
            "SELECT COUNT(*) AS count FROM dispatch_assignments WHERE player_id = ? AND dispatch_key = ? AND business_date = ?",
            (player["id"], definition.key, now.date().isoformat()),
        ).fetchone()
        daily_used = int(used_row["count"]) if used_row is not None else 0
        if daily_used >= definition.daily_limit:
            missing.append("今日接受次数已用尽")
        return DispatchPreviewRecord(
            dispatch_key=definition.key,
            label=definition.label,
            duration_seconds=definition.duration_seconds,
            daily_limit=definition.daily_limit,
            daily_used=daily_used,
            costs=costs,
            ready=not missing,
            missing=tuple(missing),
        )

    async def accept_dispatch(
        self,
        *,
        platform: str,
        platform_user_id: str,
        dispatch_key: str,
        operation_id: str,
    ) -> DispatchAssignmentRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._accept_dispatch_once, platform, platform_user_id, dispatch_key, operation_id
            )

    def _accept_dispatch_once(
        self, platform: str, platform_user_id: str, dispatch_key: str, operation_id: str
    ) -> DispatchAssignmentRecord:
        try:
            definition = resolve_dispatch(dispatch_key)
        except ValueError as exc:
            raise DispatchRequirementError(str(exc)) from exc
        operation_name = "specials.accept_dispatch"
        request_payload = {
            "platform": platform,
            "platform_user_id": platform_user_id,
            "dispatch_key": definition.key,
        }
        request_hash = self._request_hash(operation_name, request_payload)
        now = self._now()
        now_text = serialize_datetime(now)
        running_at = now + timedelta(seconds=CANCEL_WINDOW_SECONDS)
        costs = dict(definition.costs)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._dispatch_operation(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                return self._dispatch_assignment_from_payload(replay, replay=True)
            player = self._require_player(connection, platform, platform_user_id)
            self._dispatch_promote_confirmations(connection, int(player["id"]), now)
            preview = self._dispatch_preview(connection, player, definition, now)
            used = preview.daily_used
            if used >= definition.daily_limit:
                raise DispatchDailyLimitError("dispatch daily limit reached")
            if self._has_active_long_action(connection, int(player["id"])):
                raise DispatchBusyError("another long action is active")
            if not preview.ready:
                raise DispatchRequirementError("; ".join(preview.missing))

            seed = uuid4().hex
            outcome = choose_outcome(definition, seed)
            reward = reward_for(definition, seed, outcome)
            duration = definition.duration_seconds
            if outcome == "delayed":
                duration = duration * 3 // 2
            ends_at = now + timedelta(seconds=duration)
            assignment_id = f"dispatch:{uuid4().hex}"
            snapshot = {
                "dispatch_key": definition.key,
                "label": definition.label,
                "requirement": definition.requirement,
                "stage": str(player["stage"]),
                "realm_key": str(player["realm_key"]),
                "realm_layer": int(player["realm_layer"]),
                "location_key": str(player["location_key"]),
                "path_key": player["path_key"],
                "selected_service": player["selected_service"],
                "costs": costs,
                "risk_pool": definition.risk_pool,
                "risk_weights": dict(definition.risk_weights),
                "outcome": outcome,
                "reward": reward,
                "random_seed": seed,
                "duration_seconds": definition.duration_seconds,
                "ends_at": serialize_datetime(ends_at),
                "content_version": CONTENT_VERSION,
                "rule_version": RULE_VERSION,
            }
            inventory = self._json_object(player["inventory_json"], {})
            for key, amount in costs.items():
                if key.startswith("item."):
                    left = int(inventory.get(key, 0)) - amount
                    if left:
                        inventory[key] = left
                    else:
                        inventory.pop(key, None)
            connection.execute(
                "UPDATE players SET stamina = stamina - ?, energy = energy - ?, inventory_json = ?, updated_at = ? WHERE id = ?",
                (
                    costs.get("stamina", 0),
                    costs.get("energy", 0),
                    json.dumps(inventory, ensure_ascii=False, sort_keys=True),
                    now_text,
                    player["id"],
                ),
            )
            connection.execute(
                """
                INSERT INTO dispatch_assignments(
                    assignment_id, player_id, operation_id, dispatch_key, status, outcome,
                    business_date, accepted_at, running_at, ends_at, cancel_until,
                    costs_json, snapshot_json, result_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'accepted', ?, ?, ?, ?, ?, ?, ?, ?, '{}', ?, ?)
                """,
                (
                    assignment_id,
                    player["id"],
                    operation_id,
                    definition.key,
                    outcome,
                    now.date().isoformat(),
                    now_text,
                    serialize_datetime(running_at),
                    serialize_datetime(ends_at),
                    serialize_datetime(running_at),
                    json.dumps(costs, ensure_ascii=False, sort_keys=True),
                    json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
                    now_text,
                    now_text,
                ),
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (player["id"],)).fetchone()
            if updated is None:
                raise RuntimeError("dispatch acceptance returned no player")
            payload = {
                "player": self._player_payload(self._row_to_player(updated)),
                "assignment_id": assignment_id,
                "dispatch_key": definition.key,
                "status": "accepted",
                "outcome": outcome,
                "accepted_at": now_text,
                "running_at": serialize_datetime(running_at),
                "ends_at": serialize_datetime(ends_at),
                "cancel_until": serialize_datetime(running_at),
                "costs": costs,
            }
            self._record_dispatch_operation(
                connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text
            )
            return self._dispatch_assignment_from_payload(payload)

    async def settle_dispatch(
        self,
        *,
        platform: str,
        platform_user_id: str,
        assignment_id: str | None,
        operation_id: str,
    ) -> DispatchSettlementRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._settle_dispatch_once, platform, platform_user_id, assignment_id, operation_id
            )

    def _settle_dispatch_once(
        self, platform: str, platform_user_id: str, assignment_id: str | None, operation_id: str
    ) -> DispatchSettlementRecord:
        operation_name = "specials.settle_dispatch"
        request_payload = {
            "platform": platform,
            "platform_user_id": platform_user_id,
            "assignment_id": assignment_id or "",
        }
        request_hash = self._request_hash(operation_name, request_payload)
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._dispatch_operation(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                return self._dispatch_settlement_from_payload(replay, replay=True)
            player = self._require_player(connection, platform, platform_user_id)
            self._dispatch_promote_confirmations(connection, int(player["id"]), now)
            assignment = self._dispatch_assignment(connection, int(player["id"]), assignment_id)
            if str(assignment["status"]) == "settled":
                raise DispatchAlreadySettledError("dispatch already settled")
            if str(assignment["status"]) == "cancelled":
                raise DispatchAlreadySettledError("dispatch was cancelled")
            ends_at = datetime.fromisoformat(str(assignment["ends_at"]))
            if now < ends_at:
                raise DispatchNotReadyError("dispatch is not ready")

            snapshot = self._json_object(assignment["snapshot_json"], {})
            outcome = str(snapshot.get("outcome", assignment["outcome"]))
            reward = {str(key): int(value) for key, value in self._json_object(snapshot.get("reward"), {}).items()}
            refunded: dict[str, int] = {}
            costs = self._json_object(assignment["costs_json"], {})
            if outcome == "failed":
                if str(assignment["dispatch_key"]) == HERB_SEARCH:
                    refunded["stamina"] = 2
                elif str(assignment["dispatch_key"]) == WORKSHOP_HELP:
                    refunded["item.mat.wood"] = 1
            inventory = self._json_object(player["inventory_json"], {})
            stones = int(player["spirit_stones"])
            local_map = self._dispatch_local_map(connection, int(player["id"]))
            local_updates: dict[str, int] = {}
            service_reputation_delta = int(reward.get("service_reputation", 0))
            for key, amount in reward.items():
                if amount <= 0:
                    continue
                if key == "spirit_stones":
                    stones += amount
                elif key == "service_reputation":
                    continue
                elif key.startswith("item."):
                    inventory[key] = int(inventory.get(key, 0)) + amount
                elif key.startswith("local."):
                    local_map[key] = min(1000, max(0, int(local_map.get(key, 0)) + amount))
                    local_updates[key] = amount
                elif key.startswith("codex."):
                    self._record_dispatch_codex(
                        connection, int(player["id"]), key, operation_id, now_text, snapshot
                    )
                else:
                    raise RuntimeError(f"unsupported dispatch reward asset: {key}")
            for key, amount in refunded.items():
                if key.startswith("item."):
                    inventory[key] = int(inventory.get(key, 0)) + amount
            stamina_refund = min(int(costs.get("stamina", 0)), int(refunded.get("stamina", 0)))
            energy_refund = min(int(costs.get("energy", 0)), int(refunded.get("energy", 0)))
            updated_stamina = min(int(player["stamina_max"]), int(player["stamina"]) + stamina_refund)
            updated_energy = min(int(player["energy_max"]), int(player["energy"]) + energy_refund)
            rep = connection.execute(
                "SELECT service_reputation FROM player_reputations WHERE player_id = ?", (player["id"],)
            ).fetchone()
            service_reputation = int(rep["service_reputation"]) if rep is not None else 0
            service_reputation = min(100, service_reputation + service_reputation_delta)
            if local_updates or service_reputation_delta:
                connection.execute(
                    """
                    INSERT INTO player_reputations(player_id, local_json, service_reputation, updated_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(player_id) DO UPDATE SET
                        local_json = excluded.local_json,
                        service_reputation = excluded.service_reputation,
                        updated_at = excluded.updated_at
                    """,
                    (
                        player["id"],
                        json.dumps(local_map, ensure_ascii=False, sort_keys=True),
                        service_reputation,
                        now_text,
                    ),
                )
            connection.execute(
                "UPDATE players SET stamina = ?, energy = ?, spirit_stones = ?, inventory_json = ?, updated_at = ? WHERE id = ?",
                (
                    updated_stamina,
                    updated_energy,
                    stones,
                    json.dumps(inventory, ensure_ascii=False, sort_keys=True),
                    now_text,
                    player["id"],
                ),
            )
            result = {
                "outcome": outcome,
                "reward": reward,
                "refunded": refunded,
                "settled_at": now_text,
                "content_version": CONTENT_VERSION,
                "rule_version": RULE_VERSION,
            }
            connection.execute(
                "UPDATE dispatch_assignments SET status = 'settled', settle_operation_id = ?, result_json = ?, settled_at = ?, updated_at = ? WHERE id = ? AND status IN ('accepted', 'running')",
                (
                    operation_id,
                    json.dumps(result, ensure_ascii=False, sort_keys=True),
                    now_text,
                    now_text,
                    assignment["id"],
                ),
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (player["id"],)).fetchone()
            if updated is None:
                raise RuntimeError("dispatch settlement returned no player")
            payload = {
                "player": self._player_payload(self._row_to_player(updated)),
                "assignment_id": str(assignment["assignment_id"]),
                "dispatch_key": str(assignment["dispatch_key"]),
                "status": "settled",
                "outcome": outcome,
                "reward": reward,
                "refunded": refunded,
            }
            self._record_dispatch_operation(
                connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text
            )
            return self._dispatch_settlement_from_payload(payload)

    async def cancel_dispatch(
        self,
        *,
        platform: str,
        platform_user_id: str,
        assignment_id: str | None,
        operation_id: str,
    ) -> DispatchCancelRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._cancel_dispatch_once, platform, platform_user_id, assignment_id, operation_id
            )

    def _cancel_dispatch_once(
        self, platform: str, platform_user_id: str, assignment_id: str | None, operation_id: str
    ) -> DispatchCancelRecord:
        operation_name = "specials.cancel_dispatch"
        request_payload = {
            "platform": platform,
            "platform_user_id": platform_user_id,
            "assignment_id": assignment_id or "",
        }
        request_hash = self._request_hash(operation_name, request_payload)
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._dispatch_operation(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                return self._dispatch_cancel_from_payload(replay, replay=True)
            player = self._require_player(connection, platform, platform_user_id)
            assignment = self._dispatch_assignment(connection, int(player["id"]), assignment_id)
            if str(assignment["status"]) != "accepted":
                raise DispatchAlreadySettledError("dispatch is no longer cancellable")
            if now > datetime.fromisoformat(str(assignment["cancel_until"])):
                raise DispatchCancellationExpiredError("dispatch confirmation window expired")
            costs = self._json_object(assignment["costs_json"], {})
            inventory = self._json_object(player["inventory_json"], {})
            for key, amount in costs.items():
                if str(key).startswith("item."):
                    inventory[str(key)] = int(inventory.get(str(key), 0)) + int(amount)
            connection.execute(
                "UPDATE players SET stamina = MIN(stamina_max, stamina + ?), energy = MIN(energy_max, energy + ?), inventory_json = ?, updated_at = ? WHERE id = ?",
                (
                    int(costs.get("stamina", 0)),
                    int(costs.get("energy", 0)),
                    json.dumps(inventory, ensure_ascii=False, sort_keys=True),
                    now_text,
                    player["id"],
                ),
            )
            connection.execute(
                "UPDATE dispatch_assignments SET status = 'cancelled', cancel_operation_id = ?, result_json = ?, updated_at = ? WHERE id = ? AND status = 'accepted'",
                (
                    operation_id,
                    json.dumps({"refunded": costs}, ensure_ascii=False, sort_keys=True),
                    now_text,
                    assignment["id"],
                ),
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (player["id"],)).fetchone()
            if updated is None:
                raise RuntimeError("dispatch cancellation returned no player")
            payload = {
                "player": self._player_payload(self._row_to_player(updated)),
                "assignment_id": str(assignment["assignment_id"]),
                "dispatch_key": str(assignment["dispatch_key"]),
                "status": "cancelled",
                "refunded": costs,
            }
            self._record_dispatch_operation(
                connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text
            )
            return self._dispatch_cancel_from_payload(payload)

    @staticmethod
    def _dispatch_promote_confirmations(
        connection: sqlite3.Connection, player_id: int, now: datetime
    ) -> None:
        connection.execute(
            "UPDATE dispatch_assignments SET status = 'running', updated_at = ? WHERE player_id = ? AND status = 'accepted' AND running_at <= ?",
            (serialize_datetime(now), player_id, serialize_datetime(now)),
        )

    @staticmethod
    def _dispatch_assignment(
        connection: sqlite3.Connection, player_id: int, assignment_id: str | None
    ) -> sqlite3.Row:
        if assignment_id:
            row = connection.execute(
                "SELECT * FROM dispatch_assignments WHERE assignment_id = ? AND player_id = ?",
                (assignment_id, player_id),
            ).fetchone()
        else:
            row = connection.execute(
                "SELECT * FROM dispatch_assignments WHERE player_id = ? AND status IN ('accepted', 'running') ORDER BY id DESC LIMIT 1",
                (player_id,),
            ).fetchone()
        if row is None:
            raise DispatchNotFoundError("dispatch assignment does not exist")
        return row

    @staticmethod
    def _dispatch_operation(
        connection: sqlite3.Connection, operation_id: str, operation_name: str, request_hash: str
    ) -> dict[str, Any] | None:
        row = connection.execute(
            "SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id = ?",
            (operation_id,),
        ).fetchone()
        if row is None:
            return None
        if str(row["operation_name"]) != operation_name or str(row["request_hash"]) != request_hash:
            raise OperationConflictError("operation input differs from its original request")
        value = json.loads(row["result_json"])
        return dict(value) if isinstance(value, dict) else {}

    @staticmethod
    def _record_dispatch_operation(
        connection: sqlite3.Connection,
        operation_id: str,
        operation_name: str,
        player_id: int,
        request_hash: str,
        payload: dict[str, Any],
        now_text: str,
    ) -> None:
        connection.execute(
            "INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (operation_id, operation_name, player_id, request_hash, json.dumps(payload, ensure_ascii=False, sort_keys=True), now_text),
        )

    def _dispatch_local_map(self, connection: sqlite3.Connection, player_id: int) -> dict[str, Any]:
        row = connection.execute(
            "SELECT local_json FROM player_reputations WHERE player_id = ?", (player_id,)
        ).fetchone()
        return self._json_object(row["local_json"], {}) if row is not None else {}

    @staticmethod
    def _record_dispatch_codex(
        connection: sqlite3.Connection,
        player_id: int,
        entry_key: str,
        operation_id: str,
        now_text: str,
        snapshot: dict[str, Any],
    ) -> None:
        connection.execute(
            """
            INSERT INTO codex_entries(
                player_id, entry_key, category, first_seen_operation_id, first_seen_at,
                payload_json, content_version, rule_version, last_seen_at
            ) VALUES (?, ?, 'dispatch', ?, ?, ?, ?, ?, ?)
            ON CONFLICT(player_id, entry_key) DO UPDATE SET last_seen_at = excluded.last_seen_at
            """,
            (
                player_id,
                entry_key,
                operation_id,
                now_text,
                json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
                CONTENT_VERSION,
                RULE_VERSION,
                now_text,
            ),
        )

    @staticmethod
    def _dispatch_assignment_from_payload(
        payload: dict[str, Any], *, replay: bool = False
    ) -> DispatchAssignmentRecord:
        return DispatchAssignmentRecord(
            player=SQLitePlayerRepository._row_to_player(payload["player"]),
            assignment_id=str(payload["assignment_id"]),
            dispatch_key=str(payload["dispatch_key"]),
            status=str(payload["status"]),
            outcome=str(payload["outcome"]),
            accepted_at=str(payload["accepted_at"]),
            running_at=str(payload["running_at"]),
            ends_at=str(payload["ends_at"]),
            cancel_until=str(payload["cancel_until"]),
            costs={str(key): int(value) for key, value in dict(payload.get("costs", {})).items()},
            already_completed=replay,
        )

    @staticmethod
    def _dispatch_settlement_from_payload(
        payload: dict[str, Any], *, replay: bool = False
    ) -> DispatchSettlementRecord:
        return DispatchSettlementRecord(
            player=SQLitePlayerRepository._row_to_player(payload["player"]),
            assignment_id=str(payload["assignment_id"]),
            dispatch_key=str(payload["dispatch_key"]),
            status=str(payload["status"]),
            outcome=str(payload["outcome"]),
            reward={str(key): int(value) for key, value in dict(payload.get("reward", {})).items()},
            refunded={str(key): int(value) for key, value in dict(payload.get("refunded", {})).items()},
            already_completed=replay,
        )

    @staticmethod
    def _dispatch_cancel_from_payload(payload: dict[str, Any], *, replay: bool = False) -> DispatchCancelRecord:
        return DispatchCancelRecord(
            player=SQLitePlayerRepository._row_to_player(payload["player"]),
            assignment_id=str(payload["assignment_id"]),
            dispatch_key=str(payload["dispatch_key"]),
            status=str(payload["status"]),
            refunded={str(key): int(value) for key, value in dict(payload.get("refunded", {})).items()},
            already_completed=replay,
        )


SQLitePlayerRepository: Any = None


__all__ = ["DispatchRepositoryMixin"]
