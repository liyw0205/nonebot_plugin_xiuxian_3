"""SQLite transactions for server-timed idle assignments."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from ...contracts import serialize_datetime
from ..persistence.errors import (
    IdleAlreadySettledError,
    IdleBusyError,
    IdleCancellationExpiredError,
    IdleClaimTooEarlyError,
    IdleDailyLimitError,
    IdleNotFoundError,
    IdleRequirementError,
)
from .idle_models import (
    IdleAssignmentRecord,
    IdleCancelRecord,
    IdleRoutePreviewRecord,
    IdleSettlementRecord,
)
from .idle_rules import (
    ABSOLUTE_MAX_SECONDS,
    CANCEL_WINDOW_SECONDS,
    CONTENT_VERSION,
    MAX_CLAIM_EXTENSION_SECONDS,
    ROUTES,
    RULE_VERSION,
    IdleRouteDefinition,
    reward_for,
    resolve_route,
)


class IdleRepositoryMixin:
    async def preview_idle(
        self, *, platform: str, platform_user_id: str, route_key: str | None
    ) -> tuple[IdleRoutePreviewRecord, ...]:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._preview_idle_once, platform, platform_user_id, route_key
            )

    def _preview_idle_once(
        self, platform: str, platform_user_id: str, route_key: str | None
    ) -> tuple[IdleRoutePreviewRecord, ...]:
        requested = (resolve_route(route_key),) if route_key else tuple(ROUTES.values())
        now = self._now()
        with self._connect() as connection:
            player = self._require_player(connection, platform, platform_user_id, writable=False)
            return tuple(self._idle_preview(connection, player, definition, now) for definition in requested)

    def _idle_preview(
        self,
        connection: sqlite3.Connection,
        player: sqlite3.Row,
        definition: IdleRouteDefinition,
        now: datetime,
    ) -> IdleRoutePreviewRecord:
        missing: list[str] = []
        stage_order = {"new_user": 0, "mortal": 1, "seeker": 2, "cultivator": 3, "suspended": -1}
        if stage_order.get(str(player["stage"]), -1) < stage_order.get(definition.required_stage, 1):
            missing.append("角色尚未完成入道")
        if definition.required_location and str(player["location_key"]) != definition.required_location:
            missing.append("所在地点不符")
        local_reputation = self._idle_local_reputation(connection, int(player["id"]))
        if definition.required_reputation and local_reputation < definition.required_reputation:
            missing.append(f"地方名望不足（需要 {definition.required_reputation}）")
        if definition.required_residence:
            residence = connection.execute(
                "SELECT 1 FROM residences WHERE player_id = ? AND status = 'active' AND ends_at > ? LIMIT 1",
                (player["id"], serialize_datetime(now)),
            ).fetchone()
            if residence is None:
                missing.append("需要有效居所或地块")
        selected_tool = self._idle_select_tool(connection, player, definition, None)
        facility = self._idle_select_facility(connection, player, definition, None)
        if definition.required_tool_keys and selected_tool is None and facility is None:
            missing.append("需要基础工具或作坊槽")
        active = connection.execute(
            "SELECT 1 FROM idle_assignments WHERE player_id = ? AND status IN ('assigned', 'running') LIMIT 1",
            (player["id"],),
        ).fetchone()
        if active is not None:
            missing.append("已有进行中的挂机")
        if self._has_active_long_action(connection, int(player["id"])):
            missing.append("已有进行中的长时行动")
        used = connection.execute(
            "SELECT COUNT(*) AS count FROM idle_assignments WHERE player_id = ? AND business_date = ? AND status IN ('claimed', 'expired')",
            (player["id"], now.date().isoformat()),
        ).fetchone()
        daily_used = int(used["count"]) if used is not None else 0
        if daily_used >= definition.daily_limit:
            missing.append("今日挂机结算次数已用尽")
        return IdleRoutePreviewRecord(
            route_key=definition.key,
            label=definition.label,
            duration_seconds=definition.duration_seconds,
            stamina_cost=definition.stamina_cost,
            energy_cost=definition.energy_cost,
            daily_limit=definition.daily_limit,
            daily_used=daily_used,
            ready=not missing,
            missing=tuple(missing),
            requirements={
                "required_location": definition.required_location,
                "required_reputation": definition.required_reputation,
                "required_residence": definition.required_residence,
                "required_tool_keys": list(definition.required_tool_keys),
                "facility_kind": definition.facility_kind,
                "pool_key": definition.pool_key,
                "content_version": definition.content_version,
                "rule_version": definition.rule_version,
            },
        )

    async def start_idle(
        self,
        *,
        platform: str,
        platform_user_id: str,
        route_key: str,
        tool_or_facility: str | None,
        operation_id: str,
    ) -> IdleAssignmentRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._start_idle_once,
                platform,
                platform_user_id,
                route_key,
                tool_or_facility,
                operation_id,
            )

    def _start_idle_once(
        self,
        platform: str,
        platform_user_id: str,
        route_key: str,
        tool_or_facility: str | None,
        operation_id: str,
    ) -> IdleAssignmentRecord:
        try:
            definition = resolve_route(route_key)
        except ValueError as exc:
            raise IdleRequirementError(str(exc)) from exc
        operation_name = "specials.assign_idle"
        request_payload = {
            "platform": platform,
            "platform_user_id": platform_user_id,
            "route_key": definition.key,
            "tool_or_facility": tool_or_facility or "",
        }
        request_hash = self._request_hash(operation_name, request_payload)
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._idle_operation(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                return self._assignment_from_payload(replay, replay=True)
            player = self._require_player(connection, platform, platform_user_id)
            self._idle_validate(connection, player, definition, tool_or_facility, now)
            tool = self._idle_select_tool(connection, player, definition, tool_or_facility)
            facility = None
            if tool is None:
                facility = self._idle_select_facility(connection, player, definition, tool_or_facility)
            cost = {
                "stamina": definition.stamina_cost,
                "energy": definition.energy_cost,
            }
            starts_at = now
            claim_at = now + timedelta(seconds=definition.duration_seconds)
            max_claim_at = now + timedelta(
                seconds=min(definition.duration_seconds + MAX_CLAIM_EXTENSION_SECONDS, ABSOLUTE_MAX_SECONDS)
            )
            assignment_id = f"idle:{uuid4().hex}"
            snapshot = {
                "route_key": definition.key,
                "label": definition.label,
                "pool_key": definition.pool_key,
                "duration_seconds": definition.duration_seconds,
                "cost": cost,
                "tool_key": str(tool["tool_key"]) if tool else None,
                "tool_durability_before": int(tool["durability"]) if tool else None,
                "facility_slot_key": str(facility["slot_key"]) if facility else None,
                "location_key": str(player["location_key"]),
                "random_seed": uuid4().hex,
                "content_version": CONTENT_VERSION,
                "rule_version": RULE_VERSION,
            }
            inventory = self._json_object(player["inventory_json"], {})
            if tool:
                remaining = int(inventory[str(tool["tool_key"])]) - 1
                if remaining:
                    inventory[str(tool["tool_key"])] = remaining
                else:
                    inventory.pop(str(tool["tool_key"]), None)
            connection.execute(
                "UPDATE players SET stamina = stamina - ?, energy = energy - ?, inventory_json = ?, updated_at = ? WHERE id = ?",
                (definition.stamina_cost, definition.energy_cost, json.dumps(inventory, ensure_ascii=False, sort_keys=True), now_text, player["id"]),
            )
            connection.execute(
                """
                INSERT INTO idle_assignments(
                    assignment_id, player_id, operation_id, route_key, status, business_date,
                    starts_at, claim_at, max_claim_at, cancel_until, facility_slot_key, cost_json, snapshot_json,
                    result_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'running', ?, ?, ?, ?, ?, ?, ?, ?, '{}', ?, ?)
                """,
                (
                    assignment_id,
                    player["id"],
                    operation_id,
                    definition.key,
                    now.date().isoformat(),
                    serialize_datetime(starts_at),
                    serialize_datetime(claim_at),
                    serialize_datetime(max_claim_at),
                    serialize_datetime(starts_at + timedelta(seconds=CANCEL_WINDOW_SECONDS)),
                    snapshot["facility_slot_key"],
                    json.dumps(cost, ensure_ascii=False, sort_keys=True),
                    json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
                    now_text,
                    now_text,
                ),
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (player["id"],)).fetchone()
            if updated is None:
                raise RuntimeError("idle start returned no player")
            payload = {
                "player": self._player_payload(self._row_to_player(updated)),
                "assignment_id": assignment_id,
                "route_key": definition.key,
                "status": "running",
                "starts_at": serialize_datetime(starts_at),
                "claim_at": serialize_datetime(claim_at),
                "max_claim_at": serialize_datetime(max_claim_at),
                "cancel_until": serialize_datetime(starts_at + timedelta(seconds=CANCEL_WINDOW_SECONDS)),
                "cost": cost,
                "tool_key": snapshot["tool_key"],
                "facility_slot_key": snapshot["facility_slot_key"],
            }
            self._record_idle_operation(connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text)
            return self._assignment_from_payload(payload)

    async def claim_idle(
        self,
        *,
        platform: str,
        platform_user_id: str,
        assignment_id: str | None,
        operation_id: str,
    ) -> IdleSettlementRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._claim_idle_once, platform, platform_user_id, assignment_id, operation_id
            )

    def _claim_idle_once(
        self, platform: str, platform_user_id: str, assignment_id: str | None, operation_id: str
    ) -> IdleSettlementRecord:
        operation_name = "specials.claim_idle"
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
            replay = self._idle_operation(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                return IdleRepositoryMixin._settlement_from_payload(replay, replay=True)
            player = self._require_player(connection, platform, platform_user_id)
            assignment = self._idle_assignment(connection, int(player["id"]), assignment_id)
            status = str(assignment["status"])
            if status != "running":
                raise IdleAlreadySettledError("idle assignment is not running")
            snapshot = self._json_object(assignment["snapshot_json"], {})
            starts_at = datetime.fromisoformat(str(assignment["starts_at"]))
            expected_claim_at = starts_at + timedelta(seconds=int(snapshot.get("duration_seconds", 0)))
            expected_max_claim_at = starts_at + timedelta(
                seconds=min(int(snapshot.get("duration_seconds", 0)) + MAX_CLAIM_EXTENSION_SECONDS, ABSOLUTE_MAX_SECONDS)
            )
            if now < expected_claim_at:
                raise IdleClaimTooEarlyError("idle assignment is not ready")
            fallback = now > expected_max_claim_at
            definition = resolve_route(str(assignment["route_key"]))
            reward = reward_for(definition, str(snapshot.get("random_seed", assignment["operation_id"])), fallback=fallback)
            inventory = self._json_object(player["inventory_json"], {})
            tool_key = snapshot.get("tool_key")
            if tool_key:
                inventory[str(tool_key)] = int(inventory.get(str(tool_key), 0)) + 1
            for key, quantity in reward.items():
                if key.startswith("item."):
                    inventory[key] = int(inventory.get(key, 0)) + int(quantity)
            stones = int(reward.get("spirit_stones", 0))
            local_map = self._idle_local_map(connection, int(player["id"]))
            local = int(local_map.get("local.xuantian.new_town", 0))
            if definition.reputation_key:
                delta = definition.reputation_fallback if fallback else definition.reputation_full
                local = min(1000, max(0, local + delta))
            durability_before = snapshot.get("tool_durability_before")
            durability_after = durability_before
            durability = self._json_object(player["durability_json"], {})
            tool_key = snapshot.get("tool_key")
            if tool_key and definition.durability_cost_bp and not fallback:
                durability_after = max(0, int(durability_before or 10000) - definition.durability_cost_bp)
                durability[str(tool_key)] = durability_after
            if definition.reputation_key:
                rep_row = connection.execute(
                    "SELECT service_reputation FROM player_reputations WHERE player_id = ?", (player["id"],)
                ).fetchone()
                service = int(rep_row["service_reputation"]) if rep_row is not None else 0
                connection.execute(
                    """
                    INSERT INTO player_reputations(player_id, local_json, service_reputation, updated_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(player_id) DO UPDATE SET local_json = excluded.local_json, updated_at = excluded.updated_at
                    """,
                    (player["id"], json.dumps({**local_map, definition.reputation_key: local}, ensure_ascii=False, sort_keys=True), service, now_text),
                )
            connection.execute(
                "UPDATE players SET spirit_stones = spirit_stones + ?, inventory_json = ?, durability_json = ?, updated_at = ? WHERE id = ?",
                (stones, json.dumps(inventory, ensure_ascii=False, sort_keys=True), json.dumps(durability, ensure_ascii=False, sort_keys=True), now_text, player["id"]),
            )
            if "codex.route.town_road" in reward:
                self._record_idle_codex(connection, int(player["id"]), "codex.route.town_road", operation_id, now_text, snapshot)
            for key in reward:
                if key.startswith("item."):
                    self._record_idle_codex(connection, int(player["id"]), f"codex.material.{key.split('.', 2)[-1]}", operation_id, now_text, snapshot)
            result = {
                **reward,
                "fallback": fallback,
                "claimed_at": now_text,
                "tool_durability_before": durability_before,
                "tool_durability_after": durability_after,
                "content_version": CONTENT_VERSION,
                "rule_version": RULE_VERSION,
            }
            settled_status = "expired" if fallback else "claimed"
            connection.execute(
                "UPDATE idle_assignments SET status = ?, claim_operation_id = ?, result_json = ?, updated_at = ? WHERE id = ? AND status = 'running'",
                (settled_status, operation_id, json.dumps(result, ensure_ascii=False, sort_keys=True), now_text, assignment["id"]),
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (player["id"],)).fetchone()
            if updated is None:
                raise RuntimeError("idle claim returned no player")
            payload = {
                "player": self._player_payload(self._row_to_player(updated)),
                "assignment_id": str(assignment["assignment_id"]),
                "route_key": str(assignment["route_key"]),
                "status": settled_status,
                "reward": reward,
                "fallback": fallback,
                "tool_durability_before": durability_before,
                "tool_durability_after": durability_after,
            }
            self._record_idle_operation(connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text)
            return IdleRepositoryMixin._settlement_from_payload(payload)

    async def cancel_idle(
        self,
        *,
        platform: str,
        platform_user_id: str,
        assignment_id: str | None,
        operation_id: str,
    ) -> IdleCancelRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._cancel_idle_once, platform, platform_user_id, assignment_id, operation_id
            )

    def _cancel_idle_once(
        self, platform: str, platform_user_id: str, assignment_id: str | None, operation_id: str
    ) -> IdleCancelRecord:
        operation_name = "specials.cancel_idle"
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
            replay = self._idle_operation(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                return IdleRepositoryMixin._cancel_from_payload(replay, replay=True)
            player = self._require_player(connection, platform, platform_user_id)
            assignment = self._idle_assignment(connection, int(player["id"]), assignment_id)
            if str(assignment["status"]) != "running":
                raise IdleAlreadySettledError("idle assignment is not running")
            if now > datetime.fromisoformat(str(assignment["cancel_until"])):
                raise IdleCancellationExpiredError("idle cancellation window expired")
            cost = self._json_object(assignment["cost_json"], {})
            snapshot = self._json_object(assignment["snapshot_json"], {})
            inventory = self._json_object(player["inventory_json"], {})
            tool_key = snapshot.get("tool_key")
            if tool_key:
                inventory[str(tool_key)] = int(inventory.get(str(tool_key), 0)) + 1
            connection.execute(
                "UPDATE players SET stamina = MIN(stamina_max, stamina + ?), energy = MIN(energy_max, energy + ?), inventory_json = ?, updated_at = ? WHERE id = ?",
                (int(cost.get("stamina", 0)), int(cost.get("energy", 0)), json.dumps(inventory, ensure_ascii=False, sort_keys=True), now_text, player["id"]),
            )
            connection.execute(
                "UPDATE idle_assignments SET status = 'cancelled', cancel_operation_id = ?, result_json = ?, updated_at = ? WHERE id = ? AND status = 'running'",
                (operation_id, json.dumps({"refunded": cost}, ensure_ascii=False, sort_keys=True), now_text, assignment["id"]),
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (player["id"],)).fetchone()
            if updated is None:
                raise RuntimeError("idle cancellation returned no player")
            payload = {
                "player": self._player_payload(self._row_to_player(updated)),
                "assignment_id": str(assignment["assignment_id"]),
                "route_key": str(assignment["route_key"]),
                "status": "cancelled",
                "refunded": cost,
                "returned_tool_key": str(tool_key) if tool_key else None,
            }
            self._record_idle_operation(connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text)
            return IdleRepositoryMixin._cancel_from_payload(payload)

    def _idle_validate(
        self,
        connection: sqlite3.Connection,
        player: sqlite3.Row,
        definition: IdleRouteDefinition,
        tool_or_facility: str | None,
        now: datetime,
    ) -> None:
        preview = self._idle_preview(connection, player, definition, now)
        if preview.daily_used >= definition.daily_limit:
            raise IdleDailyLimitError("idle daily limit reached")
        if self._has_active_long_action(connection, int(player["id"])):
            raise IdleBusyError("another long action is active")
            if not preview.ready:
                if "已有进行中的挂机" in preview.missing or "已有进行中的长时行动" in preview.missing:
                    raise IdleBusyError("another long action is active")
                raise IdleRequirementError("; ".join(preview.missing))
        if definition.energy_cost and int(player["energy"]) < definition.energy_cost:
            raise IdleRequirementError("energy is insufficient")
        if definition.stamina_cost and int(player["stamina"]) < definition.stamina_cost:
            raise IdleRequirementError("stamina is insufficient")
        selected_tool = self._idle_select_tool(connection, player, definition, tool_or_facility)
        selected_facility = self._idle_select_facility(connection, player, definition, tool_or_facility)
        if tool_or_facility and selected_tool is None and selected_facility is None:
            raise IdleRequirementError("requested tool or facility is unavailable")
        if definition.required_tool_keys and selected_tool is None and selected_facility is None:
            raise IdleRequirementError("tool or facility is unavailable")

    @staticmethod
    def _idle_local_reputation(connection: sqlite3.Connection, player_id: int) -> int:
        return int(IdleRepositoryMixin._idle_local_map(connection, player_id).get("local.xuantian.new_town", 0))

    @staticmethod
    def _idle_local_map(connection: sqlite3.Connection, player_id: int) -> dict[str, Any]:
        row = connection.execute("SELECT local_json FROM player_reputations WHERE player_id = ?", (player_id,)).fetchone()
        if row is None:
            return {}
        value = json.loads(row["local_json"]) if isinstance(row["local_json"], str) else row["local_json"]
        return dict(value) if isinstance(value, dict) else {}

    @staticmethod
    def _idle_select_tool(connection: sqlite3.Connection, player: sqlite3.Row, definition: IdleRouteDefinition, requested: str | None) -> dict[str, object] | None:
        if not definition.required_tool_keys:
            return None
        raw_inventory = json.loads(player["inventory_json"]) if isinstance(player["inventory_json"], str) else player["inventory_json"]
        inventory = dict(raw_inventory) if isinstance(raw_inventory, dict) else {}
        if requested and requested.startswith("facility."):
            return None
        if requested and requested not in definition.required_tool_keys:
            return None
        candidates = (requested,) if requested else definition.required_tool_keys
        for key in candidates:
            if int(inventory.get(key, 0)) > 0:
                raw_durability = json.loads(player["durability_json"]) if isinstance(player["durability_json"], str) else player["durability_json"]
                durability_map = dict(raw_durability) if isinstance(raw_durability, dict) else {}
                durability = durability_map.get(key, 10000)
                if int(durability) >= definition.durability_cost_bp:
                    return {"tool_key": key, "durability": int(durability)}
        return None

    @staticmethod
    def _idle_select_facility(connection: sqlite3.Connection, player: sqlite3.Row, definition: IdleRouteDefinition, requested: str | None) -> sqlite3.Row | None:
        if not definition.facility_kind:
            return None
        if requested and not requested.startswith("facility."):
            return None
        predicates = [
            "owner_type = 'personal'",
            "owner_id = ?",
            "status = 'active'",
            "facility_kind = ?",
            "location_key = ?",
        ]
        values: list[object] = [str(player["id"]), definition.facility_kind, str(player["location_key"])]
        if requested and requested.startswith("facility."):
            predicates.append("slot_key = ?")
            values.append(requested)
        predicates.extend(
            (
                "NOT EXISTS (SELECT 1 FROM production_orders p WHERE p.facility_slot_id = production_facility_slots.id AND p.status = 'processing')",
                "NOT EXISTS (SELECT 1 FROM idle_assignments i WHERE i.facility_slot_key = production_facility_slots.slot_key AND i.status IN ('assigned', 'running'))",
            )
        )
        return connection.execute(
            f"SELECT * FROM production_facility_slots WHERE {' AND '.join(predicates)} ORDER BY slot_index LIMIT 1",
            tuple(values),
        ).fetchone()

    @staticmethod
    def _idle_assignment(connection: sqlite3.Connection, player_id: int, assignment_id: str | None) -> sqlite3.Row:
        if assignment_id:
            row = connection.execute("SELECT * FROM idle_assignments WHERE assignment_id = ? AND player_id = ?", (assignment_id, player_id)).fetchone()
        else:
            row = connection.execute("SELECT * FROM idle_assignments WHERE player_id = ? AND status = 'running' ORDER BY id DESC LIMIT 1", (player_id,)).fetchone()
        if row is None:
            raise IdleNotFoundError("idle assignment does not exist")
        return row

    @staticmethod
    def _idle_operation(connection: sqlite3.Connection, operation_id: str, operation_name: str, request_hash: str) -> dict[str, Any] | None:
        row = connection.execute("SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id = ?", (operation_id,)).fetchone()
        if row is None:
            return None
        if str(row["operation_name"]) != operation_name or str(row["request_hash"]) != request_hash:
            from ..persistence.errors import OperationConflictError
            raise OperationConflictError("operation input differs from its original request")
        value = json.loads(row["result_json"]) if isinstance(row["result_json"], str) else row["result_json"]
        return dict(value) if isinstance(value, dict) else {}

    @staticmethod
    def _record_idle_operation(connection: sqlite3.Connection, operation_id: str, operation_name: str, player_id: int, request_hash: str, payload: dict[str, Any], now_text: str) -> None:
        connection.execute(
            "INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (operation_id, operation_name, player_id, request_hash, json.dumps(payload, ensure_ascii=False, sort_keys=True), now_text),
        )

    @staticmethod
    def _record_idle_codex(connection: sqlite3.Connection, player_id: int, entry_key: str, operation_id: str, now_text: str, snapshot: dict[str, Any]) -> None:
        category = "route" if entry_key.startswith("codex.route.") else "material"
        connection.execute(
            """
            INSERT INTO codex_entries(player_id, entry_key, category, first_seen_operation_id, first_seen_at, payload_json, content_version, rule_version, last_seen_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(player_id, entry_key) DO UPDATE SET last_seen_at = excluded.last_seen_at
            """,
            (player_id, entry_key, category, operation_id, now_text, json.dumps(snapshot, ensure_ascii=False, sort_keys=True), CONTENT_VERSION, RULE_VERSION, now_text),
        )

    @staticmethod
    def _assignment_from_payload(payload: dict[str, Any], *, replay: bool = False) -> IdleAssignmentRecord:
        return IdleAssignmentRecord(
            player=SQLitePlayerRepository._row_to_player(payload["player"]),
            assignment_id=str(payload["assignment_id"]),
            route_key=str(payload["route_key"]),
            status=str(payload["status"]),
            starts_at=str(payload["starts_at"]),
            claim_at=str(payload["claim_at"]),
            max_claim_at=str(payload["max_claim_at"]),
            cancel_until=str(payload["cancel_until"]),
            cost={str(key): int(value) for key, value in dict(payload.get("cost", {})).items()},
            tool_key=payload.get("tool_key"),
            facility_slot_key=payload.get("facility_slot_key"),
            already_completed=replay,
        )

    @staticmethod
    def _settlement_from_payload(payload: dict[str, Any], *, replay: bool = False) -> IdleSettlementRecord:
        return IdleSettlementRecord(
            player=SQLitePlayerRepository._row_to_player(payload["player"]),
            assignment_id=str(payload["assignment_id"]),
            route_key=str(payload["route_key"]),
            status=str(payload["status"]),
            reward={str(key): int(value) for key, value in dict(payload.get("reward", {})).items()},
            fallback=bool(payload.get("fallback", False)),
            tool_durability_before=(int(payload["tool_durability_before"]) if payload.get("tool_durability_before") is not None else None),
            tool_durability_after=(int(payload["tool_durability_after"]) if payload.get("tool_durability_after") is not None else None),
            already_completed=replay,
        )

    @staticmethod
    def _cancel_from_payload(payload: dict[str, Any], *, replay: bool = False) -> IdleCancelRecord:
        return IdleCancelRecord(
            player=SQLitePlayerRepository._row_to_player(payload["player"]),
            assignment_id=str(payload["assignment_id"]),
            route_key=str(payload["route_key"]),
            status=str(payload["status"]),
            refunded={str(key): int(value) for key, value in dict(payload.get("refunded", {})).items()},
            returned_tool_key=(str(payload["returned_tool_key"]) if payload.get("returned_tool_key") else None),
            already_completed=replay,
        )


# Runtime composition binds the concrete repository after all mixins are loaded.
SQLitePlayerRepository: Any = None


__all__ = ["IdleRepositoryMixin"]
