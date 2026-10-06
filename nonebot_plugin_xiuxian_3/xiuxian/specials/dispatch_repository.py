"""Atomic SQLite operations for dispatch tasks."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from ...contracts import serialize_datetime
from ..content import bundled_content
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
from ..utils.assets import inventory_amount
from ..rewards.rules import local_reputation_maximum
from .dispatch_rules import (
    CANCEL_WINDOW_SECONDS,
    DispatchDefinition,
    choose_outcome,
    dispatch_definitions,
    resolve_dispatch,
    reward_for,
)
from .codex_projection import record_codex_discovery, record_material_discoveries
from ..utils.player import (
    change_player_state,
    grant_player_reward_actual,
    grant_player_state,
    player_integer,
    player_inventory,
    player_intro_flags,
    player_reputation_state,
    spend_player_state,
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
        definitions = dispatch_definitions(self.content)
        requested = (resolve_dispatch(dispatch_key, self.content),) if dispatch_key else tuple(definitions.values())
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
        intro_flags = set(player_intro_flags(player))
        if definition.required_intro_flag and definition.required_intro_flag not in intro_flags:
            missing.append("需要完成对应引导")
        if definition.required_realm and definition.required_layer is not None:
            service = player_reputation_state(connection, int(player["id"])).service
            meets_realm = self._meets_realm_values(
                str(player["realm_key"]),
                player_integer(player, "realm_layer"),
                definition.required_realm,
                definition.required_layer,
            )
            if definition.required_service_reputation is None or (
                service < definition.required_service_reputation and not meets_realm
            ):
                missing.append("需要满足道统境界或服务信誉要求")
        elif definition.required_service_reputation is not None:
            service = player_reputation_state(connection, int(player["id"])).service
            if service < definition.required_service_reputation:
                missing.append("服务信誉不足")
        if definition.required_permit and self._active_dispatch_permit(
            connection, int(player["id"]), definition.required_permit, now
        ) is None:
            missing.append("需要有效的贸易许可")
        costs = dict(definition.costs)
        if player_integer(player, "stamina") < costs.get("stamina", 0):
            missing.append("体力不足")
        if player_integer(player, "energy") < costs.get("energy", 0):
            missing.append("精力不足")
        inventory = player_inventory(player)
        for key, amount in costs.items():
            if key.startswith("item.") and inventory_amount(inventory, key) < amount:
                content = self.content or bundled_content()
                missing.append(f"{content.label('item', key)}不足")
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
            description=definition.description,
            duration_seconds=definition.duration_seconds,
            daily_limit=definition.daily_limit,
            daily_used=daily_used,
            costs=costs,
            ready=not missing,
            missing=tuple(missing),
        )

    @staticmethod
    def _active_dispatch_permit(
        connection: sqlite3.Connection, player_id: int, permit_key: str | None, now: datetime
    ) -> dict[str, str] | None:
        if permit_key is None:
            return None
        row = connection.execute(
            """
            SELECT permit_id, expires_at FROM trade_permits
            WHERE player_id = ? AND permit_key = ? AND expires_at > ?
            ORDER BY expires_at DESC, id DESC LIMIT 1
            """,
            (player_id, permit_key, serialize_datetime(now)),
        ).fetchone()
        if row is None:
            return None
        return {"permit_id": str(row["permit_id"]), "expires_at": str(row["expires_at"])}

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
        operation_name = "specials.accept_dispatch"
        request_payload = {
            "platform": platform,
            "platform_user_id": platform_user_id,
            "dispatch_key": dispatch_key.strip(),
        }
        request_hash = self._request_hash(operation_name, request_payload)
        now = self._now()
        now_text = serialize_datetime(now)
        running_at = now + timedelta(seconds=CANCEL_WINDOW_SECONDS)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._dispatch_operation(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                return self._dispatch_assignment_from_payload(replay, replay=True)
            try:
                definition = resolve_dispatch(dispatch_key, self.content)
            except ValueError as exc:
                raise DispatchRequirementError(str(exc)) from exc
            costs = dict(definition.costs)
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
            reward = reward_for(definition, seed, outcome, self.content)
            local_maximums = {
                key: local_reputation_maximum(key, self.content)
                for key in reward
                if key.startswith("local.")
            }
            permit_snapshot = self._active_dispatch_permit(
                connection, int(player["id"]), definition.required_permit, now
            )
            duration = definition.duration_seconds
            if outcome == "delayed":
                duration = duration * 3 // 2
            ends_at = now + timedelta(seconds=duration)
            assignment_id = f"dispatch:{uuid4().hex}"
            snapshot = {
                "dispatch_key": definition.key,
                "label": definition.label,
                "requirement": definition.requirement,
                "required_permit": definition.required_permit,
                "permit": permit_snapshot,
                "stage": str(player["stage"]),
                "realm_key": str(player["realm_key"]),
                "realm_layer": player_integer(player, "realm_layer"),
                "location_key": str(player["location_key"]),
                "path_key": player["path_key"],
                "selected_service": player["selected_service"],
                "costs": costs,
                "risk_pool": definition.risk_pool,
                "risk_weights": dict(definition.risk_weights),
                "failure_refunds": dict(definition.failure_refunds),
                "outcome": outcome,
                "reward": reward,
                "local_reputation_maximums": local_maximums,
                "random_seed": seed,
                "duration_seconds": definition.duration_seconds,
                "ends_at": serialize_datetime(ends_at),
            }
            spend_player_state(
                connection,
                player,
                updated_at=now_text,
                costs={key: amount for key, amount in costs.items() if str(key).startswith("item.")} or None,
                value_delta={
                    key: -int(amount)
                    for key, amount in costs.items()
                    if key in {"stamina", "energy"}
                },
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

    async def recover_expired_dispatches(self, *, batch_size: int = 100) -> int:
        if batch_size < 1:
            raise ValueError("dispatch recovery batch size must be positive")
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._recover_expired_dispatches_once, batch_size)

    def _recover_expired_dispatches_once(self, batch_size: int) -> int:
        cutoff = serialize_datetime(self._now() - timedelta(hours=24))
        with self._connect() as connection:
            assignments = connection.execute(
                """
                SELECT a.assignment_id, p.platform, p.platform_user_id
                FROM dispatch_assignments a
                JOIN players p ON p.id = a.player_id
                WHERE a.status IN ('accepted', 'running') AND a.ends_at <= ?
                ORDER BY a.ends_at, a.id
                LIMIT ?
                """,
                (cutoff, batch_size),
            ).fetchall()

        recovered = 0
        for assignment in assignments:
            assignment_id = str(assignment["assignment_id"])
            try:
                self._settle_dispatch_once(
                    str(assignment["platform"]),
                    str(assignment["platform_user_id"]),
                    assignment_id,
                    f"specials.dispatch.recovery:{assignment_id}",
                )
            except (DispatchAlreadySettledError, DispatchNotReadyError):
                continue
            recovered += 1
        return recovered

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
                if snapshot.get("failure_refunds"):
                    refunded.update(
                        {str(key): int(value) for key, value in dict(snapshot["failure_refunds"]).items()}
                    )
            settlement_reward = {
                str(key): int(amount)
                for key, amount in reward.items()
                if key == "spirit_stones" or key.startswith("item.")
            }
            for key, amount in reward.items():
                if amount <= 0:
                    continue
                if key == "spirit_stones" or key.startswith("item."):
                    continue
                if key == "service_reputation" or key.startswith("local."):
                    settlement_reward[key] = amount
                elif key.startswith("codex."):
                    record_codex_discovery(
                        connection,
                        player_id=int(player["id"]),
                        entry_key=key,
                        operation_id=operation_id,
                        occurred_at=now,
                        snapshot=snapshot,
                    )
                else:
                    raise RuntimeError(f"unsupported dispatch reward asset: {key}")
            record_material_discoveries(
                connection,
                player_id=int(player["id"]),
                operation_id=operation_id,
                occurred_at=now,
                reward=reward,
                snapshot=snapshot,
            )
            for key, amount in refunded.items():
                if key.startswith("item."):
                    settlement_reward[key] = settlement_reward.get(key, 0) + amount
            stamina_refund = min(int(costs.get("stamina", 0)), int(refunded.get("stamina", 0)))
            energy_refund = min(int(costs.get("energy", 0)), int(refunded.get("energy", 0)))
            actual_changes = grant_player_reward_actual(
                connection,
                player,
                settlement_reward,
                now_text,
                value_delta={"stamina": stamina_refund, "energy": energy_refund},
                maximums={"stamina": player["stamina_max"], "energy": player["energy_max"]},
                local_reputation_maximums={
                    key: int(value)
                    for key, value in dict(snapshot.get("local_reputation_maximums", {})).items()
                    if key in settlement_reward and key.startswith("local.")
                } or None,
            )
            actual_reward = {
                key: amount
                for key, amount in reward.items()
                if amount > 0
                and key.startswith("codex.")
            }
            actual_reward.update(
                {
                    key: actual_changes[key]
                    for key in reward
                    if key in actual_changes and actual_changes[key] > 0
                }
            )
            actual_refunded = {
                key: actual_changes.get(key, amount)
                for key, amount in refunded.items()
                if actual_changes.get(key, amount) > 0
            }
            result = {
                "outcome": outcome,
                "reward": actual_reward,
                "refunded": actual_refunded,
                "settled_at": now_text,
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
            connection.execute(
                """
                INSERT OR IGNORE INTO activity_events(
                    player_id, event_key, source_operation_id, occurred_at, payload_json
                ) VALUES (?, 'specials.dispatch.settled', ?, ?, ?)
                """,
                (
                    player["id"],
                    operation_id,
                    now_text,
                    json.dumps(
                        {
                            "assignment_id": str(assignment["assignment_id"]),
                            "dispatch_key": str(assignment["dispatch_key"]),
                            "outcome": outcome,
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
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
                "reward": actual_reward,
                "refunded": actual_refunded,
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
            grant_player_state(
                connection,
                player,
                updated_at=now_text,
                rewards={key: int(amount) for key, amount in costs.items() if str(key).startswith("item.")} or None,
                value_delta={
                    "stamina": int(costs.get("stamina", 0)),
                    "energy": int(costs.get("energy", 0)),
                },
                maximums={"stamina": player["stamina_max"], "energy": player["energy_max"]},
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
