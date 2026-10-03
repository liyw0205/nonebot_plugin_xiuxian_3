"""SQLite transactions for the short-haul livelihood route."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from ...contracts import serialize_datetime
from ..content import ContentError
from ..utils.player import (
    change_player_state,
    local_reputation_with_delta,
    player_requirements_missing,
    spend_player_state,
)
from ..utils.json import json_object
from ..persistence.errors import (
    OperationConflictError,
    PlayerStageConflictError,
    ResourceInsufficientError,
    RouteAlreadySettledError,
    RouteBusyError,
    RouteCargoRequirementError,
    RouteContentClosedError,
    RouteLocationRequirementError,
    RouteMountNotFoundError,
    RouteMountRequirementError,
    RouteNotFoundError,
    RouteNotReadyError,
    RouteQuotaError,
)
from .route_models import RoutePreviewRecord, RouteSettlementRecord, RouteStartRecord
from .route_rules import (
    RouteDefinition,
    cargo_label,
    cargo_unit_value,
    route_delay_roll_bp,
    route_definition,
)
from ..companions.rules import (
    companion_definition,
    mount_transport_duration,
    mount_transport_injury_roll_bp,
    mount_transport_stamina,
)


class RouteRepositoryMixin:
    """Own cargo locking, route sessions and route settlement."""

    async def preview_route(
        self,
        *,
        platform: str,
        platform_user_id: str,
        route_key: str,
        cargo_key: str | None,
        cargo_quantity: int,
        mount_ref: str | None = None,
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
                mount_ref,
            )

    def _preview_route_once(
        self,
        platform: str,
        platform_user_id: str,
        route_key: str,
        cargo_key: str | None,
        cargo_quantity: int,
        mount_ref: str | None = None,
    ) -> RoutePreviewRecord:
        definition, cargo_key, cargo_value = self._validated_route(route_key, cargo_key, cargo_quantity)
        now = self._now()
        business_date = now.date().isoformat()
        with self._connect() as connection:
            player = self._require_player(connection, platform, platform_user_id, writable=False)
            mount = self._route_mount(connection, int(player["id"]), mount_ref, definition) if mount_ref else None
            duration_seconds = int(mount["duration_seconds"]) if mount else definition.duration_seconds
            mount_stamina_cost = int(mount["stamina_cost"]) if mount else 0
            missing: list[str] = []
            if str(player["stage"]) not in definition.allowed_stages:
                missing.append("修行阶段")
            if str(player["location_key"]) != definition.source_location:
                missing.append(definition.source_name)
            stamina_cost = mount_stamina_cost or definition.stamina_cost
            requirements = player_requirements_missing(
                player,
                assets={cargo_key: cargo_quantity},
                values={"stamina": stamina_cost},
            )
            if "stamina" in requirements:
                missing.append("体力")
            if cargo_key in requirements:
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
                cargo_name=cargo_label(cargo_key, self.content),
                cargo_quantity=cargo_quantity,
                cargo_value=cargo_value,
                stamina_cost=stamina_cost,
                duration_seconds=duration_seconds,
                daily_used=daily_used,
                daily_limit=definition.daily_limit,
                ready=not missing,
                missing=tuple(missing),
                mount_instance_id=str(mount["instance_id"]) if mount else None,
                mount_name=str(mount["name"]) if mount else None,
                mount_level=int(mount["level"]) if mount else None,
                mount_stamina=int(mount["stamina"]) if mount else None,
                mount_stamina_cost=mount_stamina_cost,
                duration_seconds_with_mount=duration_seconds if mount else None,
            )

    async def start_route(
        self,
        *,
        platform: str,
        platform_user_id: str,
        route_key: str,
        cargo_key: str | None,
        cargo_quantity: int,
        operation_id: str,
        mount_ref: str | None = None,
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
                mount_ref,
                operation_id,
            )

    def _start_route_once(
        self,
        platform: str,
        platform_user_id: str,
        route_key: str,
        cargo_key: str | None,
        cargo_quantity: int,
        mount_ref: str | None,
        operation_id: str,
    ) -> RouteStartRecord:
        operation_name = "livelihood.start_route"
        request_hash = self._request_hash(
            operation_name,
            {
                "platform": platform,
                "platform_user_id": platform_user_id,
                "route_key": route_key,
                "cargo_key": cargo_key,
                "cargo_quantity": cargo_quantity,
                "mount_ref": mount_ref or "",
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
            definition, cargo_key, cargo_value = self._validated_route(route_key, cargo_key, cargo_quantity)
            player = self._require_player(connection, platform, platform_user_id)
            if str(player["stage"]) not in definition.allowed_stages:
                raise PlayerStageConflictError("player is not ready for transport")
            if str(player["location_key"]) != definition.source_location:
                raise RouteLocationRequirementError("route source location is not valid")
            mount = self._route_mount(connection, int(player["id"]), mount_ref, definition) if mount_ref else None
            route_stamina_cost = int(mount["stamina_cost"]) if mount else definition.stamina_cost
            duration_seconds = int(mount["duration_seconds"]) if mount else definition.duration_seconds
            if player_requirements_missing(player, values={"stamina": route_stamina_cost}):
                raise ResourceInsufficientError("stamina is insufficient")
            used = connection.execute(
                "SELECT COUNT(*) AS count FROM livelihood_trade_routes WHERE player_id = ? AND business_date = ?",
                (player["id"], business_date),
            ).fetchone()
            if used is not None and int(used["count"]) >= definition.daily_limit:
                raise RouteQuotaError("route daily limit reached")
            self._check_route_busy(connection, int(player["id"]))
            if player_requirements_missing(player, assets={cargo_key: cargo_quantity}):
                raise RouteCargoRequirementError("cargo is insufficient")
            effects = self._public_project_effects(connection, now)
            delay_chance_bp = max(
                0,
                definition.delay_chance_bp
                - (1000 if "route.delay_weight_reduction" in effects else 0),
            )
            delay_roll = route_delay_roll_bp(operation_id)
            delay_seconds = definition.delay_seconds if delay_roll < delay_chance_bp else 0
            starts_at = now
            arrives_at = now + timedelta(seconds=duration_seconds + delay_seconds)
            route_id = uuid4().hex
            snapshot = {
                "route_name": definition.label,
                "route_key": definition.key,
                "source_location": definition.source_location,
                "destination_location": definition.destination_location,
                "cargo": {cargo_key: cargo_quantity},
                "cargo_name": cargo_label(cargo_key, self.content),
                "cargo_value": cargo_value,
                "stamina_cost": route_stamina_cost,
                "duration_seconds": duration_seconds,
                "reward_stones": definition.reward_stones,
                "local_reputation": definition.local_reputation,
                "local_reputation_key": definition.local_reputation_key,
                "local_reputation_maximum": definition.local_reputation_maximum,
                "random_pool": definition.random_pool,
                "random_seed": operation_id,
                "delay_roll_bp": delay_roll,
                "delay_chance_bp": delay_chance_bp,
                "delay_seconds": delay_seconds,
                "mount": self._mount_snapshot(mount) if mount else None,
            }
            spend_player_state(
                connection,
                player,
                {cargo_key: cargo_quantity},
                now_text,
                value_delta={"stamina": -route_stamina_cost},
            )
            if mount is not None:
                connection.execute(
                    "UPDATE companion_instances SET stamina = ?, status = 'travelling', updated_at = ? WHERE id = ? AND status = 'available'",
                    (int(mount["stamina"]) - route_stamina_cost, now_text, mount["id"]),
                )
                if connection.execute("SELECT changes()").fetchone()[0] != 1:
                    raise RouteMountRequirementError("mount is no longer available")
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
                    route_stamina_cost,
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
                "cargo_name": snapshot["cargo_name"],
                "cargo_quantity": cargo_quantity,
                "cargo_value": cargo_value,
                "source_location": definition.source_location,
                "destination_location": definition.destination_location,
                "status": "in_transit",
                "starts_at": serialize_datetime(starts_at),
                "arrives_at": serialize_datetime(arrives_at),
                "stamina_cost": route_stamina_cost,
                "reward_stones": definition.reward_stones,
                "delay_seconds": delay_seconds,
                "mount_instance_id": str(mount["instance_id"]) if mount else None,
                "mount_name": str(mount["name"]) if mount else None,
                "mount_level": int(mount["level"]) if mount else None,
                "mount_stamina_cost": route_stamina_cost if mount else 0,
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
            snapshot = json_object(route["snapshot_json"])
            cargo = json_object(route["cargo_json"])
            mount_snapshot = snapshot.get("mount")
            mount_result: dict[str, Any] | None = None
            if isinstance(mount_snapshot, dict):
                mount_id = str(mount_snapshot["instance_id"])
                mount = connection.execute(
                    "SELECT * FROM companion_instances WHERE instance_id = ? AND player_id = ?",
                    (mount_id, player["id"]),
                ).fetchone()
                if mount is None:
                    raise RouteMountNotFoundError("mount does not exist")
                if (
                    str(mount["kind"]) != "mount"
                    or str(mount["status"]) != "travelling"
                    or str(mount["companion_key"]) != str(mount_snapshot["key"])
                ):
                    raise RouteMountRequirementError("mount is not travelling with this route")
                experience_before = int(mount["experience"])
                transport_experience = int(mount_snapshot["transport_experience"])
                experience_after = experience_before + transport_experience
                level_min = int(mount_snapshot["level_min"])
                level_max = int(mount_snapshot["level_max"])
                level_after = min(level_max, level_min + experience_after // 50)
                injury_roll_bp = mount_transport_injury_roll_bp(str(snapshot["random_seed"]))
                injury_chance_bp = int(mount_snapshot["injury_chance_bp"])
                injury_recovery_seconds = int(mount_snapshot["injury_recovery_seconds"])
                injured = injury_roll_bp < injury_chance_bp
                injury_until = (
                    serialize_datetime(now + timedelta(seconds=injury_recovery_seconds))
                    if injured and injury_recovery_seconds
                    else (now_text if injured else None)
                )
                mount_status = "injured" if injured else "available"
                connection.execute(
                    "UPDATE companion_instances SET status = ?, experience = ?, level = ?, injury_until = ?, updated_at = ? WHERE id = ? AND status = 'travelling'",
                    (mount_status, experience_after, level_after, injury_until, now_text, mount["id"]),
                )
                if connection.execute("SELECT changes()").fetchone()[0] != 1:
                    raise RouteMountRequirementError("mount settlement conflicted")
                mount_result = {
                    "instance_id": mount_id,
                    "name": str(mount_snapshot["name"]),
                    "level_before": int(mount_snapshot["level"]),
                    "level_after": level_after,
                    "experience_before": experience_before,
                    "experience_after": experience_after,
                    "experience_gained": transport_experience,
                    "status": mount_status,
                    "injury_roll_bp": injury_roll_bp,
                    "injury_chance_bp": injury_chance_bp,
                    "injury_until": injury_until,
                }
            local_key = str(snapshot["local_reputation_key"])
            local_delta = int(snapshot["local_reputation"])
            reward_stones = int(snapshot["reward_stones"])
            local_before = local_reputation_with_delta(connection, int(player["id"]), {}).get(local_key, 0)
            change_player_state(
                connection,
                player,
                updated_at=now_text,
                asset_values={"spirit_stones": reward_stones},
                asset_mode="grant",
                player_values={"location_key": str(route["destination_location"])},
                local_reputation_delta={local_key: local_delta} if local_delta else None,
                local_reputation_maximums=(
                    {local_key: int(snapshot["local_reputation_maximum"])} if local_delta else None
                ),
            )
            local_after = local_reputation_with_delta(connection, int(player["id"]), {}).get(local_key, 0)
            result = {
                "status": "settled",
                "cargo": cargo,
                "reward_stones": reward_stones,
                "local_reputation_key": local_key,
                "local_reputation_before": local_before,
                "local_reputation_after": local_after,
                "local_reputation_delta": local_after - local_before,
                "delay_seconds": int(snapshot["delay_seconds"]),
                "settled_at": now_text,
            }
            if mount_result is not None:
                result["mount"] = mount_result
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
                "route_name": str(snapshot["route_name"]),
                "cargo_key": next(iter(cargo), ""),
                "cargo_name": str(snapshot["cargo_name"]),
                "cargo_quantity": int(next(iter(cargo.values()), 0)),
                **result,
            }
            self._record_route_operation(connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text)
            return self._route_settlement_from_payload(payload)

    def _route_mount(
        self,
        connection: Any,
        player_id: int,
        mount_ref: str | None,
        route: RouteDefinition,
    ) -> dict[str, Any]:
        """Resolve and freeze the deployed, available mount for one route."""

        reference = str(mount_ref or "").strip()
        try:
            normalized_key = companion_definition(reference, getattr(self, "content", None)).key
        except ValueError:
            normalized_key = reference
        instance = connection.execute(
            "SELECT * FROM companion_instances WHERE player_id = ? AND (instance_id = ? OR companion_key = ?) AND status <> 'retired' ORDER BY id LIMIT 1",
            (player_id, reference, normalized_key),
        ).fetchone()
        if instance is None:
            raise RouteMountNotFoundError("mount does not exist")
        if str(instance["kind"]) != "mount":
            raise RouteMountRequirementError("selected companion is not a mount")
        if str(instance["status"]) != "available" or int(instance["deployed"]) != 1:
            raise RouteMountRequirementError("mount is not available")
        definition = companion_definition(str(instance["companion_key"]), getattr(self, "content", None))
        gear = tuple(self._gear_snapshot(connection, int(instance["id"])))
        stamina_cost = mount_transport_stamina(
            route.stamina_cost,
            gear,
            getattr(self, "content", None),
        )
        if int(instance["stamina"]) < stamina_cost:
            raise RouteMountRequirementError("mount stamina is insufficient")
        return {
            "id": int(instance["id"]),
            "instance_id": str(instance["instance_id"]),
            "key": definition.key,
            "name": definition.label,
            "level": int(instance["level"]),
            "stamina": int(instance["stamina"]),
            "stamina_cost": stamina_cost,
            "duration_seconds": mount_transport_duration(
                route.duration_seconds,
                definition,
                int(instance["level"]),
            ),
            "experience": int(instance["experience"]),
            "transport_experience": int(definition.transport_experience),
            "level_min": int(definition.level_min),
            "level_max": int(definition.level_max),
            "injury_chance_bp": int(definition.transport_injury_chance_bp),
            "injury_recovery_seconds": int(definition.transport_injury_recovery_seconds),
            "gear": [dict(item) for item in gear],
        }

    @staticmethod
    def _mount_snapshot(mount: dict[str, Any]) -> dict[str, Any]:
        return {
            "instance_id": mount["instance_id"],
            "key": mount["key"],
            "name": mount["name"],
            "level": mount["level"],
            "experience": mount["experience"],
            "transport_experience": mount["transport_experience"],
            "level_min": mount["level_min"],
            "level_max": mount["level_max"],
            "injury_chance_bp": mount["injury_chance_bp"],
            "injury_recovery_seconds": mount["injury_recovery_seconds"],
            "stamina_before": mount["stamina"],
            "stamina_cost": mount["stamina_cost"],
            "duration_seconds": mount["duration_seconds"],
            "gear": mount["gear"],
        }

    def _validated_route(self, route_key: str, cargo_key: str | None, cargo_quantity: int) -> tuple[RouteDefinition, str, int]:
        try:
            definition = route_definition(route_key, self.content)
            if cargo_key is None:
                cargo_key = definition.default_cargo_key
            unit_value = cargo_unit_value(cargo_key, definition)
        except (ContentError, ValueError) as exc:
            raise RouteContentClosedError("unsupported route or cargo") from exc
        if isinstance(cargo_quantity, bool) or not isinstance(cargo_quantity, int):
            raise RouteCargoRequirementError("cargo quantity is invalid")
        quantity = cargo_quantity
        if quantity <= 0 or unit_value * quantity > definition.max_cargo_value:
            raise RouteCargoRequirementError("cargo value is outside the route limit")
        return definition, cargo_key, unit_value * quantity

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
            ("idle_assignments", "status IN ('assigned', 'running')"),
            ("dispatch_assignments", "status IN ('accepted', 'running')"),
        )
        for table, status_clause in checks:
            if connection.execute(f"SELECT 1 FROM {table} WHERE player_id = ? AND {status_clause} LIMIT 1", (player_id,)).fetchone() is not None:
                raise RouteBusyError("another player session is active")

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
            cargo_name=str(payload["cargo_name"]),
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
            mount_instance_id=(str(payload["mount_instance_id"]) if payload.get("mount_instance_id") else None),
            mount_name=(str(payload["mount_name"]) if payload.get("mount_name") else None),
            mount_level=(int(payload["mount_level"]) if payload.get("mount_level") is not None else None),
            mount_stamina_cost=int(payload.get("mount_stamina_cost", 0)),
        )

    def _route_settlement_from_payload(self, payload: dict[str, Any], *, replay: bool = False) -> RouteSettlementRecord:
        return RouteSettlementRecord(
            player=self._row_to_player(payload["player"]),
            route_id=str(payload["route_id"]),
            route_key=str(payload["route_key"]),
            route_name=str(payload["route_name"]),
            cargo_key=str(payload.get("cargo_key", "")),
            cargo_name=str(payload["cargo_name"]),
            cargo_quantity=int(payload.get("cargo_quantity", 0)),
            status=str(payload["status"]),
            reward_stones=int(payload.get("reward_stones", 0)),
            local_reputation_delta=int(payload.get("local_reputation_delta", 0)),
            local_reputation_before=int(payload["local_reputation_before"]),
            local_reputation_after=int(payload["local_reputation_after"]),
            delay_seconds=int(payload.get("delay_seconds", 0)),
            already_completed=replay,
            cargo={str(key): int(value) for key, value in dict(payload.get("cargo", {})).items()},
            mount_instance_id=(str(payload["mount"]["instance_id"]) if isinstance(payload.get("mount"), dict) and payload["mount"].get("instance_id") else None),
            mount_name=(str(payload["mount"].get("name", "")) if isinstance(payload.get("mount"), dict) else None),
            mount_level=(int(payload["mount"].get("level_after")) if isinstance(payload.get("mount"), dict) and payload["mount"].get("level_after") is not None else None),
            mount_experience=int(payload.get("mount", {}).get("experience_gained", 0)) if isinstance(payload.get("mount"), dict) else 0,
            mount_level_after=(int(payload["mount"].get("level_after")) if isinstance(payload.get("mount"), dict) and payload["mount"].get("level_after") is not None else None),
        )


__all__ = ["RouteRepositoryMixin"]
