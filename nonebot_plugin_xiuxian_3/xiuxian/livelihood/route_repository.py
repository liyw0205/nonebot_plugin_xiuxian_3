"""SQLite transactions for the v0.1 short-haul livelihood route."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from ...contracts import serialize_datetime
from ..persistence.errors import (
    OperationConflictError,
    PlayerStageConflictError,
    ResourceInsufficientError,
    RouteAlreadySettledError,
    RouteBusyError,
    RouteCargoRequirementError,
    RouteContentClosedError,
    RouteLocationRequirementError,
    RouteNotFoundError,
    RouteNotReadyError,
    RouteQuotaError,
)
from ..player.rules import STAGE_MORTAL
from .route_models import RoutePreviewRecord, RouteSettlementRecord, RouteStartRecord
from .route_rules import (
    RouteDefinition,
    cargo_unit_value,
    route_delay_roll_bp,
    route_definition,
)


class RouteRepositoryMixin:
    """Own cargo locking, route sessions and route settlement."""

    async def preview_route(
        self,
        *,
        platform: str,
        platform_user_id: str,
        route_key: str,
        cargo_key: str,
        cargo_quantity: int,
    ) -> RoutePreviewRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._preview_route_once,
                platform,
                platform_user_id,
                route_key,
                cargo_key,
                cargo_quantity,
            )

    def _preview_route_once(
        self,
        platform: str,
        platform_user_id: str,
        route_key: str,
        cargo_key: str,
        cargo_quantity: int,
    ) -> RoutePreviewRecord:
        definition, cargo_value = self._validated_route(route_key, cargo_key, cargo_quantity)
        now = self._now()
        business_date = now.date().isoformat()
        with self._connect() as connection:
            player = self._require_player(connection, platform, platform_user_id, writable=False)
            inventory = self._route_json_object(player["inventory_json"])
            missing: list[str] = []
            if str(player["stage"]) not in {STAGE_MORTAL, "seeker", "cultivator"}:
                missing.append("入道")
            if str(player["location_key"]) != definition.source_location:
                missing.append("青石镇")
            if int(player["stamina"]) < definition.stamina_cost:
                missing.append("体力")
            if int(inventory.get(cargo_key, 0)) < cargo_quantity:
                missing.append("货物")
            used = connection.execute(
                "SELECT COUNT(*) AS count FROM livelihood_trade_routes WHERE player_id = ? AND business_date = ?",
                (player["id"], business_date),
            ).fetchone()
            daily_used = int(used["count"]) if used is not None else 0
            if daily_used >= definition.daily_limit:
                missing.append("今日运输次数")
            active = connection.execute(
                "SELECT 1 FROM livelihood_trade_routes WHERE player_id = ? AND status = 'in_transit' LIMIT 1",
                (player["id"],),
            ).fetchone()
            if active is not None:
                missing.append("进行中的运输")
            return RoutePreviewRecord(
                player=self._row_to_player(player),
                route_key=definition.key,
                route_name=definition.label,
                source_location=definition.source_location,
                destination_location=definition.destination_location,
                cargo_key=cargo_key,
                cargo_quantity=cargo_quantity,
                cargo_value=cargo_value,
                stamina_cost=definition.stamina_cost,
                duration_seconds=definition.duration_seconds,
                daily_used=daily_used,
                daily_limit=definition.daily_limit,
                ready=not missing,
                missing=tuple(missing),
            )

    async def start_route(
        self,
        *,
        platform: str,
        platform_user_id: str,
        route_key: str,
        cargo_key: str,
        cargo_quantity: int,
        operation_id: str,
    ) -> RouteStartRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._start_route_once,
                platform,
                platform_user_id,
                route_key,
                cargo_key,
                cargo_quantity,
                operation_id,
            )

    def _start_route_once(
        self,
        platform: str,
        platform_user_id: str,
        route_key: str,
        cargo_key: str,
        cargo_quantity: int,
        operation_id: str,
    ) -> RouteStartRecord:
        definition, cargo_value = self._validated_route(route_key, cargo_key, cargo_quantity)
        operation_name = "livelihood.start_route"
        request_hash = self._request_hash(
            operation_name,
            {
                "platform": platform,
                "platform_user_id": platform_user_id,
                "route_key": definition.key,
                "cargo_key": cargo_key,
                "cargo_quantity": cargo_quantity,
            },
        )
        now = self._now()
        now_text = serialize_datetime(now)
        business_date = now.date().isoformat()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._route_operation(connection, operation_id, operation_name, request_hash)
            if existing is not None:
                return self._start_from_payload(existing, replay=True)
            player = self._require_player(connection, platform, platform_user_id)
            if str(player["stage"]) not in {STAGE_MORTAL, "seeker", "cultivator"}:
                raise PlayerStageConflictError("player is not ready for transport")
            if str(player["location_key"]) != definition.source_location:
                raise RouteLocationRequirementError("route source location is not valid")
            if int(player["stamina"]) < definition.stamina_cost:
                raise ResourceInsufficientError("stamina is insufficient")
            used = connection.execute(
                "SELECT COUNT(*) AS count FROM livelihood_trade_routes WHERE player_id = ? AND business_date = ?",
                (player["id"], business_date),
            ).fetchone()
            if used is not None and int(used["count"]) >= definition.daily_limit:
                raise RouteQuotaError("route daily limit reached")
            self._check_route_busy(connection, int(player["id"]))
            inventory = self._route_json_object(player["inventory_json"])
            if int(inventory.get(cargo_key, 0)) < cargo_quantity:
                raise RouteCargoRequirementError("cargo is insufficient")
            remaining = int(inventory[cargo_key]) - cargo_quantity
            if remaining:
                inventory[cargo_key] = remaining
            else:
                inventory.pop(cargo_key, None)
            effects = self._public_project_effects(connection, now)
            delay_chance_bp = max(
                0,
                definition.delay_chance_bp
                - (1000 if "route.delay_weight_reduction" in effects else 0),
            )
            delay_roll = route_delay_roll_bp(operation_id)
            delay_seconds = definition.delay_seconds if delay_roll < delay_chance_bp else 0
            starts_at = now
            arrives_at = now + timedelta(seconds=definition.duration_seconds + delay_seconds)
            route_id = uuid4().hex
            snapshot = {
                "route_name": definition.label,
                "route_key": definition.key,
                "source_location": definition.source_location,
                "destination_location": definition.destination_location,
                "cargo": {cargo_key: cargo_quantity},
                "cargo_value": cargo_value,
                "stamina_cost": definition.stamina_cost,
                "reward_stones": definition.reward_stones,
                "local_reputation": definition.local_reputation,
                "random_pool": definition.random_pool,
                "random_seed": operation_id,
                "delay_roll_bp": delay_roll,
                "delay_chance_bp": delay_chance_bp,
                "delay_seconds": delay_seconds,
                "content_version": definition.content_version,
                "rule_version": definition.rule_version,
            }
            connection.execute(
                "UPDATE players SET stamina = ?, inventory_json = ?, updated_at = ? WHERE id = ?",
                (int(player["stamina"]) - definition.stamina_cost, json.dumps(inventory, ensure_ascii=False, sort_keys=True), now_text, player["id"]),
            )
            connection.execute(
                """
                INSERT INTO livelihood_trade_routes(
                    route_id, player_id, operation_id, route_key, business_date, status,
                    source_location, destination_location, cargo_json, cargo_value,
                    starts_at, arrives_at, stamina_cost, reward_stones, snapshot_json,
                    result_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'in_transit', ?, ?, ?, ?, ?, ?, ?, ?, ?, '{}', ?, ?)
                """,
                (
                    route_id,
                    player["id"],
                    operation_id,
                    definition.key,
                    business_date,
                    definition.source_location,
                    definition.destination_location,
                    json.dumps({cargo_key: cargo_quantity}, ensure_ascii=False, sort_keys=True),
                    cargo_value,
                    serialize_datetime(starts_at),
                    serialize_datetime(arrives_at),
                    definition.stamina_cost,
                    definition.reward_stones,
                    json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
                    now_text,
                    now_text,
                ),
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (player["id"],)).fetchone()
            if updated is None:
                raise RuntimeError("route start returned no player")
            payload = {
                "player": self._player_payload(self._row_to_player(updated)),
                "route_id": route_id,
                "route_key": definition.key,
                "route_name": definition.label,
                "cargo_key": cargo_key,
                "cargo_quantity": cargo_quantity,
                "cargo_value": cargo_value,
                "source_location": definition.source_location,
                "destination_location": definition.destination_location,
                "status": "in_transit",
                "starts_at": serialize_datetime(starts_at),
                "arrives_at": serialize_datetime(arrives_at),
                "stamina_cost": definition.stamina_cost,
                "reward_stones": definition.reward_stones,
                "delay_seconds": delay_seconds,
            }
            self._record_route_operation(connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text)
            return self._start_from_payload(payload)

    async def settle_route(
        self,
        *,
        platform: str,
        platform_user_id: str,
        route_id: str | None,
        operation_id: str,
    ) -> RouteSettlementRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._settle_route_once,
                platform,
                platform_user_id,
                route_id,
                operation_id,
            )

    def _settle_route_once(
        self,
        platform: str,
        platform_user_id: str,
        route_id: str | None,
        operation_id: str,
    ) -> RouteSettlementRecord:
        operation_name = "livelihood.settle_route"
        request_hash = self._request_hash(
            operation_name,
            {"platform": platform, "platform_user_id": platform_user_id, "route_id": route_id or ""},
        )
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._route_operation(connection, operation_id, operation_name, request_hash)
            if existing is not None:
                return self._route_settlement_from_payload(existing, replay=True)
            player = self._require_player(connection, platform, platform_user_id)
            if route_id:
                route = connection.execute(
                    "SELECT * FROM livelihood_trade_routes WHERE route_id = ? AND player_id = ?",
                    (route_id, player["id"]),
                ).fetchone()
            else:
                route = connection.execute(
                    "SELECT * FROM livelihood_trade_routes WHERE player_id = ? AND status = 'in_transit' ORDER BY id DESC LIMIT 1",
                    (player["id"],),
                ).fetchone()
            if route is None:
                raise RouteNotFoundError("route does not exist")
            if str(route["status"]) in {"settled", "failed", "expired"}:
                raise RouteAlreadySettledError("route is already settled")
            if str(route["status"]) != "in_transit":
                raise RouteNotFoundError("route is not awaiting settlement")
            if now < datetime.fromisoformat(str(route["arrives_at"])):
                raise RouteNotReadyError("route has not arrived")
            snapshot = self._route_json_object(route["snapshot_json"])
            cargo = self._route_json_object(route["cargo_json"])
            local_key = "local.xuantian.new_town"
            reputation = connection.execute(
                "SELECT local_json FROM player_reputations WHERE player_id = ?", (player["id"],)
            ).fetchone()
            local = self._route_json_object(reputation["local_json"]) if reputation is not None else {}
            local_before = int(local.get(local_key, 0))
            local_after = min(1000, local_before + int(snapshot.get("local_reputation", 0)))
            local[local_key] = local_after
            connection.execute(
                "UPDATE players SET location_key = ?, spirit_stones = spirit_stones + ?, updated_at = ? WHERE id = ?",
                (str(route["destination_location"]), int(snapshot.get("reward_stones", route["reward_stones"])), now_text, player["id"]),
            )
            connection.execute(
                """
                INSERT INTO player_reputations(player_id, local_json, service_reputation, updated_at)
                VALUES (?, ?, 0, ?)
                ON CONFLICT(player_id) DO UPDATE SET local_json = excluded.local_json, updated_at = excluded.updated_at
                """,
                (player["id"], json.dumps(local, ensure_ascii=False, sort_keys=True), now_text),
            )
            result = {
                "status": "settled",
                "cargo": cargo,
                "reward_stones": int(snapshot.get("reward_stones", route["reward_stones"])),
                "local_reputation_before": local_before,
                "local_reputation_after": local_after,
                "local_reputation_delta": local_after - local_before,
                "delay_seconds": int(snapshot.get("delay_seconds", 0)),
                "settled_at": now_text,
            }
            connection.execute(
                "UPDATE livelihood_trade_routes SET status = 'settled', settle_operation_id = ?, result_json = ?, settled_at = ?, updated_at = ? WHERE id = ? AND status = 'in_transit'",
                (operation_id, json.dumps(result, ensure_ascii=False, sort_keys=True), now_text, now_text, route["id"]),
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (player["id"],)).fetchone()
            if updated is None:
                raise RuntimeError("route settlement returned no player")
            payload = {
                "player": self._player_payload(self._row_to_player(updated)),
                "route_id": str(route["route_id"]),
                "route_key": str(route["route_key"]),
                "route_name": str(snapshot.get("route_name", route["route_key"])),
                "cargo_key": next(iter(cargo), ""),
                "cargo_quantity": int(next(iter(cargo.values()), 0)),
                **result,
            }
            self._record_route_operation(connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text)
            return self._route_settlement_from_payload(payload)

    @staticmethod
    def _validated_route(route_key: str, cargo_key: str, cargo_quantity: int) -> tuple[RouteDefinition, int]:
        try:
            definition = route_definition(route_key)
            unit_value = cargo_unit_value(cargo_key)
        except ValueError as exc:
            raise RouteContentClosedError("unsupported route or cargo") from exc
        try:
            quantity = int(cargo_quantity)
        except (TypeError, ValueError) as exc:
            raise RouteCargoRequirementError("cargo quantity is invalid") from exc
        if quantity <= 0 or unit_value * quantity > definition.max_cargo_value:
            raise RouteCargoRequirementError("cargo value is outside the route limit")
        return definition, unit_value * quantity

    @staticmethod
    def _check_route_busy(connection: Any, player_id: int) -> None:
        checks = (
            ("livelihood_trade_routes", "status = 'in_transit'"),
            ("travel_sessions", "status = 'running'"),
            ("cultivation_sessions", "status = 'running'"),
            ("production_orders", "status = 'processing'"),
            ("breakthrough_sessions", "status = 'preparing'"),
            ("exploration_sessions", "status IN ('created', 'running', 'combat_pending')"),
            ("retreat_sessions", "status = 'running'"),
        )
        for table, status_clause in checks:
            if connection.execute(f"SELECT 1 FROM {table} WHERE player_id = ? AND {status_clause} LIMIT 1", (player_id,)).fetchone() is not None:
                raise RouteBusyError("another player session is active")

    @staticmethod
    def _route_json_object(raw: Any) -> dict[str, Any]:
        value = json.loads(raw) if isinstance(raw, str) else raw
        return dict(value) if isinstance(value, dict) else {}

    @staticmethod
    def _route_operation(connection: Any, operation_id: str, operation_name: str, request_hash: str) -> dict[str, Any] | None:
        existing = connection.execute(
            "SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id = ?",
            (operation_id,),
        ).fetchone()
        if existing is None:
            return None
        if existing["operation_name"] != operation_name or existing["request_hash"] != request_hash:
            raise OperationConflictError("operation input differs from its original request")
        return json.loads(existing["result_json"])

    @staticmethod
    def _record_route_operation(connection: Any, operation_id: str, operation_name: str, player_id: int, request_hash: str, payload: dict[str, Any], now_text: str) -> None:
        connection.execute(
            "INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (operation_id, operation_name, player_id, request_hash, json.dumps(payload, ensure_ascii=False, sort_keys=True), now_text),
        )

    def _start_from_payload(self, payload: dict[str, Any], *, replay: bool = False) -> RouteStartRecord:
        return RouteStartRecord(
            player=self._row_to_player(payload["player"]),
            route_id=str(payload["route_id"]),
            route_key=str(payload["route_key"]),
            route_name=str(payload["route_name"]),
            cargo_key=str(payload["cargo_key"]),
            cargo_quantity=int(payload["cargo_quantity"]),
            cargo_value=int(payload["cargo_value"]),
            source_location=str(payload["source_location"]),
            destination_location=str(payload["destination_location"]),
            status=str(payload["status"]),
            starts_at=str(payload["starts_at"]),
            arrives_at=str(payload["arrives_at"]),
            stamina_cost=int(payload["stamina_cost"]),
            reward_stones=int(payload["reward_stones"]),
            delay_seconds=int(payload.get("delay_seconds", 0)),
            already_completed=replay,
        )

    def _route_settlement_from_payload(self, payload: dict[str, Any], *, replay: bool = False) -> RouteSettlementRecord:
        return RouteSettlementRecord(
            player=self._row_to_player(payload["player"]),
            route_id=str(payload["route_id"]),
            route_key=str(payload["route_key"]),
            route_name=str(payload["route_name"]),
            cargo_key=str(payload.get("cargo_key", "")),
            cargo_quantity=int(payload.get("cargo_quantity", 0)),
            status=str(payload["status"]),
            reward_stones=int(payload.get("reward_stones", 0)),
            local_reputation_delta=int(payload.get("local_reputation_delta", 0)),
            delay_seconds=int(payload.get("delay_seconds", 0)),
            already_completed=replay,
            cargo={str(key): int(value) for key, value in dict(payload.get("cargo", {})).items()},
        )


__all__ = ["RouteRepositoryMixin"]
