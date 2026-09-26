"""SQLite transactions for world movement extensions.

The core repository owns connections, migrations and shared player mapping.
World-specific session state lives here so new routes do not grow that core
class indefinitely.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from uuid import uuid4

from ...contracts import serialize_datetime
from .void_models import VoidRouteSettlementRecord, VoidRouteStartRecord
from .void_rules import (
    CONTENT_VERSION,
    RULE_VERSION,
    VOID_INSTABILITY_SECONDS,
    VOID_ROUTE_STORM_CHANCE_BP,
    navigation_anchor_cost,
    void_route_definition,
    void_route_roll_bp,
)
from .rules import meets_realm


class WorldRepositoryMixin:
    """Persistence operations for world sessions.

    The mixin deliberately depends only on the repository's small storage
    protocol: ``_connect``, ``_now``, ``_require_player``, ``_json_object``,
    ``_request_hash``, ``_row_to_player`` and ``_player_payload``.
    """

    async def start_void_route(
        self, *, platform: str, platform_user_id: str, route_key: str, operation_id: str
    ) -> VoidRouteStartRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._start_void_route_once, platform, platform_user_id, route_key, operation_id
            )

    def _start_void_route_once(
        self, platform: str, platform_user_id: str, route_key: str, operation_id: str
    ) -> VoidRouteStartRecord:
        from ..repository import (
            OperationConflictError,
            ResourceInsufficientError,
            VoidAnchorInsufficientError,
            VoidRouteLockedError,
            VoidTravelBusyError,
        )

        try:
            definition = void_route_definition(route_key)
        except KeyError as exc:
            raise VoidRouteLockedError("void route is closed") from exc
        operation_name = "world.enter_void_route"
        request_payload = {"platform": platform, "platform_user_id": platform_user_id, "route_key": route_key}
        request_hash = self._request_hash(operation_name, request_payload)
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            if existing is not None:
                if existing["operation_name"] != operation_name or existing["request_hash"] != request_hash:
                    raise OperationConflictError("operation input differs from its original request")
                payload = json.loads(existing["result_json"])
                return VoidRouteStartRecord(
                    player=self._row_to_player(payload["player"]),
                    session_id=str(payload["session_id"]),
                    route_key=str(payload["route_key"]),
                    status=str(payload["status"]),
                    starts_at=str(payload["starts_at"]),
                    ends_at=str(payload["ends_at"]),
                    anchor_cost=int(payload["anchor_cost"]),
                    stamina_cost=int(payload["stamina_cost"]),
                    space_resistance_bp=int(payload["space_resistance_bp"]),
                    storm_roll_bp=int(payload["storm_roll_bp"]),
                    already_completed=True,
                )
            row = self._require_player(connection, platform, platform_user_id)
            realm_key = str(row["realm_key"])
            realm_layer = int(row["realm_layer"])
            if realm_key == "soul_transformation" and realm_layer >= 1:
                if route_key == "void.archive_ruins":
                    trial_count = connection.execute(
                        "SELECT COUNT(*) AS count FROM quest_events WHERE player_id = ? AND quest_key = 'quest.break_void' AND component_key = 'void_wall_trial'",
                        (row["id"],),
                    ).fetchone()
                    if int(trial_count["count"]) < 3:
                        raise VoidRouteLockedError("archive route requires three wall trials")
                else:
                    raise VoidRouteLockedError("void route requires void refining")
            elif not meets_realm(realm_key, realm_layer, "void_refining", 1):
                raise VoidRouteLockedError("void route requires void refining")
            instability_until = row["void_instability_until"]
            unstable = False
            if instability_until:
                try:
                    unstable = datetime.fromisoformat(str(instability_until)) > now
                except ValueError:
                    unstable = False
            if unstable and route_key == "void.archive_ruins":
                from ..repository import VoidInstabilityActiveError

                raise VoidInstabilityActiveError("void instability blocks this route")
            if connection.execute(
                "SELECT 1 FROM void_route_sessions WHERE player_id = ? AND status = 'running' LIMIT 1",
                (row["id"],),
            ).fetchone() is not None:
                raise VoidTravelBusyError("void travel is busy")
            if self._has_active_long_action(connection, int(row["id"])):
                raise VoidTravelBusyError("another long action is active")
            inventory = self._json_object(row["inventory_json"], {})
            anchor_cost = navigation_anchor_cost(definition.anchor_cost, int(row["space_resistance_bp"]), unstable)
            beacon_discount = 0
            if route_key == "void.sect_fortress":
                beacon_discount = int(self._active_void_beacon_discount(connection, int(row["id"]), now))
                anchor_cost = max(1, anchor_cost - beacon_discount)
            if int(inventory.get("item.void_anchor", 0)) < anchor_cost:
                raise VoidAnchorInsufficientError("void anchors are insufficient")
            if int(row["stamina"]) < definition.stamina_cost:
                raise ResourceInsufficientError("stamina is insufficient")
            inventory["item.void_anchor"] = int(inventory.get("item.void_anchor", 0)) - anchor_cost
            storm_roll = void_route_roll_bp(operation_id)
            session_id = uuid4().hex
            ends_at = serialize_datetime(now + timedelta(seconds=definition.duration_seconds))
            snapshot = {
                "route_key": route_key,
                "random_pool": definition.random_pool,
                "storm_roll_bp": storm_roll,
                "space_resistance_bp": int(row["space_resistance_bp"]),
                "void_instability_until": instability_until,
                "anchor_cost": anchor_cost,
                "beacon_discount": beacon_discount,
                "stamina_cost": definition.stamina_cost,
                "content_version": CONTENT_VERSION,
                "rule_version": RULE_VERSION,
            }
            connection.execute(
                "UPDATE players SET inventory_json = ?, stamina = stamina - ?, updated_at = ? WHERE id = ?",
                (json.dumps(inventory, ensure_ascii=False, sort_keys=True), definition.stamina_cost, now_text, row["id"]),
            )
            connection.execute(
                "INSERT INTO void_route_sessions(session_id, player_id, operation_id, route_key, status, starts_at, ends_at, anchor_cost, stamina_cost, snapshot_json, created_at, updated_at) VALUES (?, ?, ?, ?, 'running', ?, ?, ?, ?, ?, ?, ?)",
                (
                    session_id,
                    row["id"],
                    operation_id,
                    route_key,
                    now_text,
                    ends_at,
                    anchor_cost,
                    definition.stamina_cost,
                    json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
                    now_text,
                    now_text,
                ),
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (row["id"],)).fetchone()
            if updated is None:
                raise RuntimeError("void route start returned no player")
            player = self._row_to_player(updated)
            payload = {
                "player": self._player_payload(player),
                "session_id": session_id,
                "route_key": route_key,
                "status": "running",
                "starts_at": now_text,
                "ends_at": ends_at,
                "anchor_cost": anchor_cost,
                "stamina_cost": definition.stamina_cost,
                "space_resistance_bp": int(row["space_resistance_bp"]),
                "storm_roll_bp": storm_roll,
            }
            connection.execute(
                "INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (operation_id, operation_name, row["id"], request_hash, json.dumps(payload, ensure_ascii=False, sort_keys=True), now_text),
            )
            return VoidRouteStartRecord(
                player=player,
                session_id=session_id,
                route_key=route_key,
                status="running",
                starts_at=now_text,
                ends_at=ends_at,
                anchor_cost=anchor_cost,
                stamina_cost=definition.stamina_cost,
                space_resistance_bp=int(row["space_resistance_bp"]),
                storm_roll_bp=storm_roll,
            )

    async def settle_void_route(
        self, *, platform: str, platform_user_id: str, operation_id: str
    ) -> VoidRouteSettlementRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._settle_void_route_once, platform, platform_user_id, operation_id)

    def _settle_void_route_once(self, platform: str, platform_user_id: str, operation_id: str) -> VoidRouteSettlementRecord:
        from ..repository import OperationConflictError, VoidRouteNotFoundError, VoidRouteNotReadyError

        operation_name = "world.settle_void_route"
        request_hash = self._request_hash(operation_name, {"platform": platform, "platform_user_id": platform_user_id})
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id = ?", (operation_id,)
            ).fetchone()
            if existing is not None:
                if existing["operation_name"] != operation_name or existing["request_hash"] != request_hash:
                    raise OperationConflictError("operation input differs from its original request")
                return self._void_route_settlement_from_payload(json.loads(existing["result_json"]), replay=True)
            row = self._require_player(connection, platform, platform_user_id)
            session = connection.execute(
                "SELECT * FROM void_route_sessions WHERE player_id = ? AND status = 'running' ORDER BY id DESC LIMIT 1",
                (row["id"],),
            ).fetchone()
            if session is None:
                raise VoidRouteNotFoundError("no running void route")
            if now < datetime.fromisoformat(str(session["ends_at"])):
                raise VoidRouteNotReadyError("void route is not ready")
            snapshot = self._json_object(session["snapshot_json"], {})
            storm = int(snapshot.get("storm_roll_bp", 0)) < VOID_ROUTE_STORM_CHANCE_BP
            inventory = self._json_object(row["inventory_json"], {})
            extra_anchor_lost = 0
            if storm:
                extra_anchor_lost = min(1, int(inventory.get("item.void_anchor", 0)))
                inventory["item.void_anchor"] = int(inventory.get("item.void_anchor", 0)) - extra_anchor_lost
            reward = {"item.void_crystal": 1}
            for key, amount in reward.items():
                inventory[key] = int(inventory.get(key, 0)) + amount
            instability_until = (
                serialize_datetime(now + timedelta(seconds=VOID_INSTABILITY_SECONDS))
                if storm
                else row["void_instability_until"]
            )
            # A settled route is also a location transition.  Keep the route
            # key as the arrival location so downstream gates can require a
            # real archive arrival instead of a manually forged player state.
            arrival_location = str(session["route_key"])
            connection.execute(
                "UPDATE players SET location_key = ?, inventory_json = ?, void_route_count = void_route_count + 1, void_instability_until = ?, updated_at = ? WHERE id = ?",
                (
                    arrival_location,
                    json.dumps(inventory, ensure_ascii=False, sort_keys=True),
                    instability_until,
                    now_text,
                    row["id"],
                ),
            )
            result = {
                "reward": reward,
                "storm": storm,
                "extra_anchor_lost": extra_anchor_lost,
                "status": "settled",
                "route_key": session["route_key"],
                "location_key": arrival_location,
            }
            connection.execute(
                "UPDATE void_route_sessions SET status = 'settled', result_json = ?, updated_at = ? WHERE id = ?",
                (json.dumps(result, ensure_ascii=False, sort_keys=True), now_text, session["id"]),
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (row["id"],)).fetchone()
            if updated is None:
                raise RuntimeError("void route settlement returned no player")
            payload = {"player": self._player_payload(self._row_to_player(updated)), "session_id": session["session_id"], **result}
            connection.execute(
                "INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (operation_id, operation_name, row["id"], request_hash, json.dumps(payload, ensure_ascii=False, sort_keys=True), now_text),
            )
            return self._void_route_settlement_from_payload(payload, replay=False)

    @staticmethod
    def _void_route_settlement_from_payload(payload: dict, *, replay: bool) -> VoidRouteSettlementRecord:
        from ..repository import SQLitePlayerRepository

        return VoidRouteSettlementRecord(
            player=SQLitePlayerRepository._row_to_player(payload["player"]),
            session_id=str(payload["session_id"]),
            route_key=str(payload["route_key"]),
            status=str(payload.get("status", "settled")),
            reward={str(key): int(value) for key, value in dict(payload.get("reward", {})).items()},
            storm=bool(payload.get("storm", False)),
            extra_anchor_lost=int(payload.get("extra_anchor_lost", 0)),
            already_completed=replay,
        )


__all__ = ["WorldRepositoryMixin"]
