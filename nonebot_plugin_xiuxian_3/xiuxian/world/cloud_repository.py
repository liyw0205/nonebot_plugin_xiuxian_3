"""Persistence for v0.2 cloud routes and gated world introductions.

This module owns only the cloud-boat session and two short world actions. The
ordinary travel repository remains responsible for the base map movement.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from ...contracts import serialize_datetime
from .cloud_models import ArrayHallRecord, CloudBoatSettlementRecord, CloudBoatStartRecord, DemonIntroRecord
from .cloud_rules import (
    ARRAY_HALL_INVITE_FLAG,
    CLOUD_ROUTES,
    CONTENT_VERSION,
    DEMON_INTRO_FLAG,
    DEMON_INTRO_QUEST,
    RULE_VERSION,
    cloud_route_definition,
)


class CloudRepositoryMixin:
    """Transactional v0.2 world operations.

    The mixin relies on the storage protocol supplied by ``SQLitePlayerRepository``.
    Keeping these methods separate prevents route-specific state from growing
    the generic travel repository.
    """

    async def board_cloud_boat(
        self, *, platform: str, platform_user_id: str, route_key: str, operation_id: str
    ) -> CloudBoatStartRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._board_cloud_boat_once, platform, platform_user_id, route_key, operation_id
            )

    def _board_cloud_boat_once(
        self, platform: str, platform_user_id: str, route_key: str, operation_id: str
    ) -> CloudBoatStartRecord:
        from ..repository import (
            AdvancedCavePassMissingError,
            CloudBoatBusyError,
            CloudFareInsufficientError,
            CloudRouteLockedError,
            CurrencyInsufficientError,
            LocationRequirementError,
            OperationConflictError,
            ResourceInsufficientError,
        )

        try:
            definition = cloud_route_definition(route_key)
        except ValueError as exc:
            raise CloudRouteLockedError("cloud route is closed") from exc
        operation_name = "world.board_cloud_boat"
        request_hash = self._request_hash(
            operation_name,
            {"platform": platform, "platform_user_id": platform_user_id, "route_key": route_key},
        )
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
                return self._cloud_start_from_payload(json.loads(existing["result_json"]), replay=True)

            player = self._require_player(connection, platform, platform_user_id)
            player_id = int(player["id"])
            source = str(player["location_key"])
            if source not in definition.source_locations:
                raise LocationRequirementError("cloud route source is not available")
            if not self._cloud_meets_realm(str(player["realm_key"]), int(player["realm_layer"]), definition.required_realm, definition.required_layer):
                raise CloudRouteLockedError("cloud route realm requirement is not met")
            if definition.required_quest and not self._cloud_quest_completed(connection, player_id, definition.required_quest):
                raise CloudRouteLockedError("cloud route quest requirement is not met")
            if self._has_active_long_action(connection, player_id):
                raise CloudBoatBusyError("another long action is active")

            stamina = int(player["stamina"])
            stones = int(player["spirit_stones"])
            inventory = self._json_object(player["inventory_json"], {})
            if stamina < definition.stamina_cost:
                raise ResourceInsufficientError("stamina is insufficient")
            if stones < definition.currency_cost:
                raise CloudFareInsufficientError("cloud fare is insufficient")
            if definition.pass_key and int(inventory.get(definition.pass_key, 0)) < definition.pass_quantity:
                raise AdvancedCavePassMissingError("advanced cave pass is missing")

            if definition.pass_key:
                remaining = int(inventory.get(definition.pass_key, 0)) - definition.pass_quantity
                if remaining:
                    inventory[definition.pass_key] = remaining
                else:
                    inventory.pop(definition.pass_key, None)
            session_id = uuid4().hex
            ends_at = now + timedelta(seconds=definition.duration_seconds)
            snapshot = {
                "content_version": definition.content_version,
                "rule_version": definition.rule_version,
                "route_key": definition.key,
                "source": source,
                "destination": definition.destination,
                "stamina_cost": definition.stamina_cost,
                "currency_cost": definition.currency_cost,
                "pass_key": definition.pass_key,
                "pass_quantity": definition.pass_quantity,
                "required_realm": definition.required_realm,
                "required_layer": definition.required_layer,
                "required_quest": definition.required_quest,
            }
            connection.execute(
                "UPDATE players SET stamina = ?, spirit_stones = ?, inventory_json = ?, updated_at = ? WHERE id = ?",
                (
                    stamina - definition.stamina_cost,
                    stones - definition.currency_cost,
                    json.dumps(inventory, ensure_ascii=False, sort_keys=True),
                    now_text,
                    player_id,
                ),
            )
            connection.execute(
                """
                INSERT INTO cloud_boat_sessions(
                    session_id, player_id, operation_id, route_key, source_location,
                    destination, status, starts_at, ends_at, stamina_cost, currency_cost,
                    pass_key, pass_quantity, snapshot_json, result_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'running', ?, ?, ?, ?, ?, ?, ?, '{}', ?, ?)
                """,
                (
                    session_id,
                    player_id,
                    operation_id,
                    definition.key,
                    source,
                    definition.destination,
                    now_text,
                    serialize_datetime(ends_at),
                    definition.stamina_cost,
                    definition.currency_cost,
                    definition.pass_key,
                    definition.pass_quantity,
                    json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
                    now_text,
                    now_text,
                ),
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (player_id,)).fetchone()
            payload = {
                "player": self._player_payload(self._row_to_player(updated)),
                "session_id": session_id,
                "route_key": definition.key,
                "source": source,
                "destination": definition.destination,
                "status": "running",
                "starts_at": now_text,
                "ends_at": serialize_datetime(ends_at),
                "stamina_cost": definition.stamina_cost,
                "currency_cost": definition.currency_cost,
                "pass_key": definition.pass_key,
                "pass_quantity": definition.pass_quantity,
            }
            self._cloud_insert_operation(connection, operation_id, operation_name, player_id, request_hash, payload, now_text)
            return self._cloud_start_from_payload(payload)

    async def settle_cloud_boat(
        self, *, platform: str, platform_user_id: str, operation_id: str
    ) -> CloudBoatSettlementRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._settle_cloud_boat_once, platform, platform_user_id, operation_id
            )

    async def recover_cloud_boat(
        self, *, platform: str, platform_user_id: str, operation_id: str
    ) -> CloudBoatSettlementRecord:
        """Recover a session that missed its normal settlement window."""

        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._recover_cloud_boat_once, platform, platform_user_id, operation_id
            )

    def _settle_cloud_boat_once(
        self, platform: str, platform_user_id: str, operation_id: str
    ) -> CloudBoatSettlementRecord:
        from ..repository import CloudBoatNotFoundError, CloudBoatNotReadyError, OperationConflictError

        operation_name = "world.settle_cloud_boat"
        request_hash = self._request_hash(operation_name, {"platform": platform, "platform_user_id": platform_user_id})
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
                return self._cloud_settlement_from_payload(json.loads(existing["result_json"]), replay=True)
            player = self._require_player(connection, platform, platform_user_id, writable=False)
            session = connection.execute(
                "SELECT * FROM cloud_boat_sessions WHERE player_id = ? AND status = 'running' ORDER BY id DESC LIMIT 1",
                (player["id"],),
            ).fetchone()
            if session is None:
                raise CloudBoatNotFoundError("no running cloud boat")
            if now < datetime.fromisoformat(str(session["ends_at"])):
                raise CloudBoatNotReadyError("cloud boat is not ready")
            connection.execute(
                "UPDATE players SET location_key = ?, updated_at = ? WHERE id = ?",
                (session["destination"], now_text, player["id"]),
            )
            result = {"arrived": True, "settled_at": now_text, "destination": session["destination"]}
            connection.execute(
                "UPDATE cloud_boat_sessions SET status = 'arrived', result_json = ?, updated_at = ? WHERE id = ? AND status = 'running'",
                (json.dumps(result, ensure_ascii=False, sort_keys=True), now_text, session["id"]),
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (player["id"],)).fetchone()
            payload = {
                "player": self._player_payload(self._row_to_player(updated)),
                "session_id": session["session_id"],
                "route_key": session["route_key"],
                "source": session["source_location"],
                "destination": session["destination"],
                "status": "arrived",
                "arrived": True,
                "stamina_cost": int(session["stamina_cost"]),
                "currency_cost": int(session["currency_cost"]),
                "pass_key": session["pass_key"],
                "pass_quantity": int(session["pass_quantity"]),
            }
            self._cloud_insert_operation(connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text)
            return self._cloud_settlement_from_payload(payload)

    def _recover_cloud_boat_once(
        self, platform: str, platform_user_id: str, operation_id: str
    ) -> CloudBoatSettlementRecord:
        from ..repository import CloudBoatNotFoundError, CloudBoatNotReadyError, OperationConflictError

        operation_name = "world.recover_cloud_boat"
        request_hash = self._request_hash(operation_name, {"platform": platform, "platform_user_id": platform_user_id})
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
                return self._cloud_settlement_from_payload(json.loads(existing["result_json"]), replay=True)
            player = self._require_player(connection, platform, platform_user_id, writable=False)
            session = connection.execute(
                "SELECT * FROM cloud_boat_sessions WHERE player_id = ? AND status = 'running' ORDER BY id DESC LIMIT 1",
                (player["id"],),
            ).fetchone()
            if session is None:
                raise CloudBoatNotFoundError("no running cloud boat")
            recovery_deadline = datetime.fromisoformat(str(session["ends_at"])) + timedelta(hours=24)
            if now < recovery_deadline:
                raise CloudBoatNotReadyError("cloud boat recovery window has not opened")
            connection.execute(
                "UPDATE players SET location_key = ?, updated_at = ? WHERE id = ?",
                (session["destination"], now_text, player["id"]),
            )
            result = {"arrived": True, "recovered": True, "settled_at": now_text, "destination": session["destination"]}
            connection.execute(
                "UPDATE cloud_boat_sessions SET status = 'arrived', result_json = ?, updated_at = ? WHERE id = ? AND status = 'running'",
                (json.dumps(result, ensure_ascii=False, sort_keys=True), now_text, session["id"]),
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (player["id"],)).fetchone()
            payload = {
                "player": self._player_payload(self._row_to_player(updated)),
                "session_id": session["session_id"], "route_key": session["route_key"],
                "source": session["source_location"], "destination": session["destination"],
                "status": "arrived", "arrived": True,
                "stamina_cost": int(session["stamina_cost"]), "currency_cost": int(session["currency_cost"]),
                "pass_key": session["pass_key"], "pass_quantity": int(session["pass_quantity"]),
            }
            self._cloud_insert_operation(connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text)
            return self._cloud_settlement_from_payload(payload)

    async def accept_demon_intro(
        self, *, platform: str, platform_user_id: str, operation_id: str
    ) -> DemonIntroRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._accept_demon_intro_once, platform, platform_user_id, operation_id
            )

    def _accept_demon_intro_once(
        self, platform: str, platform_user_id: str, operation_id: str
    ) -> DemonIntroRecord:
        from ..repository import (
            DemonIntroAlreadyCompletedError,
            DemonIntroRequirementError,
            OperationConflictError,
            ResourceInsufficientError,
        )

        operation_name = "world.accept_demon_intro"
        request_hash = self._request_hash(operation_name, {"platform": platform, "platform_user_id": platform_user_id})
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            if existing is not None:
                if existing["operation_name"] != operation_name or existing["request_hash"] != request_hash:
                    raise OperationConflictError("operation input differs from its original request")
                return self._demon_intro_from_payload(json.loads(existing["result_json"]), replay=True)
            player = self._require_player(connection, platform, platform_user_id)
            player_id = int(player["id"])
            if str(player["location_key"]) != "demon.abyss_gate" or not self._cloud_quest_route_arrived(connection, player_id):
                raise DemonIntroRequirementError("demon introduction requires the arrived gate route")
            progress = connection.execute(
                "SELECT status FROM quest_progress WHERE player_id = ? AND quest_key = ?",
                (player_id, DEMON_INTRO_QUEST),
            ).fetchone()
            if progress is not None and str(progress["status"]) in {"completed", "claimed"}:
                raise DemonIntroAlreadyCompletedError("demon introduction already completed")
            if int(player["spirit_stones"]) < 100:
                raise ResourceInsufficientError("demon introduction requires 100 spirit stones")
            faction = self._json_object(player["faction_reputation_json"], {})
            faction["demon"] = int(faction.get("demon", 0)) + 20
            intro = self._json_object(player["intro_json"], {})
            flags = [str(item) for item in intro.get("flags", [])]
            for flag in (DEMON_INTRO_QUEST, DEMON_INTRO_FLAG):
                if flag not in flags:
                    flags.append(flag)
            intro["flags"] = flags
            connection.execute(
                "UPDATE players SET spirit_stones = spirit_stones - 100, faction_reputation_json = ?, intro_json = ?, updated_at = ? WHERE id = ?",
                (json.dumps(faction, ensure_ascii=False, sort_keys=True), json.dumps(intro, ensure_ascii=False, sort_keys=True), now_text, player_id),
            )
            self._insert_quest_event(
                connection,
                player_id=player_id,
                quest_key=DEMON_INTRO_QUEST,
                component_key="risk_confirmation",
                source_operation_id=operation_id,
                outcome="success",
                payload={"route": "route.cloud_to_abyss_intro", "submitted_stones": 100, "reputation": 20},
                now_text=now_text,
                content_version=CONTENT_VERSION,
                rule_version=RULE_VERSION,
            )
            self._upsert_progress(
                connection,
                player_id,
                DEMON_INTRO_QUEST,
                "completed",
                {"risk_confirmation": 1},
                {"access_flag": DEMON_INTRO_FLAG, "faction": "demon"},
                operation_id,
                now_text,
                content_version=CONTENT_VERSION,
                rule_version=RULE_VERSION,
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (player_id,)).fetchone()
            payload = {
                "player": self._player_payload(self._row_to_player(updated)),
                "quest_key": DEMON_INTRO_QUEST,
                "status": "completed",
                "reward": {"faction_reputation.demon": 20},
            }
            self._cloud_insert_operation(connection, operation_id, operation_name, player_id, request_hash, payload, now_text)
            return self._demon_intro_from_payload(payload)

    async def use_array_hall(
        self, *, platform: str, platform_user_id: str, operation_id: str
    ) -> ArrayHallRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._use_array_hall_once, platform, platform_user_id, operation_id
            )

    def _use_array_hall_once(
        self, platform: str, platform_user_id: str, operation_id: str
    ) -> ArrayHallRecord:
        from ..repository import (
            ArrayHallPermissionDeniedError,
            OperationConflictError,
            ResourceInsufficientError,
        )

        operation_name = "world.use_array_hall"
        request_hash = self._request_hash(operation_name, {"platform": platform, "platform_user_id": platform_user_id})
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            if existing is not None:
                if existing["operation_name"] != operation_name or existing["request_hash"] != request_hash:
                    raise OperationConflictError("operation input differs from its original request")
                return self._array_hall_from_payload(json.loads(existing["result_json"]), replay=True)
            player = self._require_player(connection, platform, platform_user_id)
            if str(player["location_key"]) != "xuantian.array_hall":
                raise ArrayHallPermissionDeniedError("array hall location is required")
            if not self._cloud_meets_realm(str(player["realm_key"]), int(player["realm_layer"]), "qi_gathering", 1):
                raise ArrayHallPermissionDeniedError("array hall requires qi gathering")
            intro = self._json_object(player["intro_json"], {})
            flags = {str(item) for item in intro.get("flags", [])}
            membership = connection.execute(
                "SELECT 1 FROM sect_members WHERE player_id = ? AND status = 'active' LIMIT 1", (player["id"],)
            ).fetchone()
            if membership is None and not ({ARRAY_HALL_INVITE_FLAG, "array_hall_invite"} & flags):
                raise ArrayHallPermissionDeniedError("array hall permission is not granted")
            if int(player["stamina"]) < 3:
                raise ResourceInsufficientError("array hall requires 3 stamina")
            connection.execute(
                "UPDATE players SET stamina = stamina - 3, updated_at = ? WHERE id = ?", (now_text, player["id"])
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (player["id"],)).fetchone()
            payload = {
                "player": self._player_payload(self._row_to_player(updated)),
                "status": "authorized",
                "permission": "sect_member" if membership is not None else "teaching_invite",
                "action": "formation_learning_or_production_request",
            }
            self._cloud_insert_operation(connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text)
            return self._array_hall_from_payload(payload)

    @staticmethod
    def _cloud_meets_realm(realm_key: str, layer: int, required_realm: str, required_layer: int) -> bool:
        ranks = {
            "mortal": 0, "qi_sensing": 1, "qi_gathering": 2, "foundation": 3,
            "golden_core": 4, "nascent_soul": 5, "soul_transformation": 6,
            "void_refining": 7, "dao_union": 8, "tribulation": 9,
        }
        return (ranks.get(realm_key, -1), int(layer)) >= (ranks.get(required_realm, -1), required_layer)

    @staticmethod
    def _cloud_quest_completed(connection: Any, player_id: int, quest_key: str) -> bool:
        progress = connection.execute(
            "SELECT status FROM quest_progress WHERE player_id = ? AND quest_key = ?", (player_id, quest_key)
        ).fetchone()
        if progress is not None and str(progress["status"]) in {"completed", "claimed"}:
            return True
        intro = connection.execute("SELECT intro_json FROM players WHERE id = ?", (player_id,)).fetchone()
        flags = CloudRepositoryMixin._json_object(intro["intro_json"], {}).get("flags", []) if intro else []
        return quest_key in {str(item) for item in flags}

    @staticmethod
    def _cloud_quest_route_arrived(connection: Any, player_id: int) -> bool:
        return connection.execute(
            "SELECT 1 FROM cloud_boat_sessions WHERE player_id = ? AND route_key = 'route.cloud_to_abyss_intro' AND status = 'arrived' LIMIT 1",
            (player_id,),
        ).fetchone() is not None

    @staticmethod
    def _cloud_insert_operation(connection: Any, operation_id: str, operation_name: str, player_id: int, request_hash: str, payload: dict[str, Any], now_text: str) -> None:
        connection.execute(
            "INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (operation_id, operation_name, player_id, request_hash, json.dumps(payload, ensure_ascii=False, sort_keys=True), now_text),
        )

    @staticmethod
    def _cloud_start_from_payload(payload: dict[str, Any], *, replay: bool = False) -> CloudBoatStartRecord:
        from ..repository import SQLitePlayerRepository

        return CloudBoatStartRecord(
            player=SQLitePlayerRepository._row_to_player(payload["player"]),
            session_id=str(payload["session_id"]), route_key=str(payload["route_key"]),
            source=str(payload["source"]), destination=str(payload["destination"]), status=str(payload["status"]),
            starts_at=str(payload["starts_at"]), ends_at=str(payload["ends_at"]),
            stamina_cost=int(payload["stamina_cost"]), currency_cost=int(payload["currency_cost"]),
            pass_key=payload.get("pass_key"), pass_quantity=int(payload.get("pass_quantity", 0)),
            already_completed=replay,
        )

    @staticmethod
    def _cloud_settlement_from_payload(payload: dict[str, Any], *, replay: bool = False) -> CloudBoatSettlementRecord:
        from ..repository import SQLitePlayerRepository

        return CloudBoatSettlementRecord(
            player=SQLitePlayerRepository._row_to_player(payload["player"]),
            session_id=str(payload["session_id"]), route_key=str(payload["route_key"]),
            source=str(payload["source"]), destination=str(payload["destination"]), status=str(payload["status"]),
            arrived=bool(payload.get("arrived", False)), stamina_cost=int(payload.get("stamina_cost", 0)),
            currency_cost=int(payload.get("currency_cost", 0)), pass_key=payload.get("pass_key"),
            pass_quantity=int(payload.get("pass_quantity", 0)), already_completed=replay,
        )

    @staticmethod
    def _demon_intro_from_payload(payload: dict[str, Any], *, replay: bool = False) -> DemonIntroRecord:
        from ..repository import SQLitePlayerRepository

        return DemonIntroRecord(
            player=SQLitePlayerRepository._row_to_player(payload["player"]), quest_key=str(payload["quest_key"]),
            status=str(payload["status"]), reward={str(k): int(v) for k, v in payload.get("reward", {}).items()},
            already_completed=replay,
        )

    @staticmethod
    def _array_hall_from_payload(payload: dict[str, Any], *, replay: bool = False) -> ArrayHallRecord:
        from ..repository import SQLitePlayerRepository

        return ArrayHallRecord(
            player=SQLitePlayerRepository._row_to_player(payload["player"]), status=str(payload["status"]),
            permission=str(payload["permission"]), action=str(payload["action"]), already_completed=replay,
        )


__all__ = ["CloudRepositoryMixin"]
