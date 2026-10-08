"""Persistence for cloud routes and gated world introductions.

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
from ..utils.assets import player_currency
from ..utils.json_cache import decode_json_strict
from ..utils.operations import operation_replay, record_operation
from ..utils.player import (
    change_player_state,
    grant_player_reward_actual,
    player_integer,
    spend_player_state,
)
from ..rewards.rules import reward_grant_from_snapshot, reward_totals
from .cloud_models import (
    ArrayHallRecord,
    BeastHistoryRecord,
    BeastIntroRecord,
    CloudBoatSettlementRecord,
    CloudBoatStartRecord,
    DemonIntroRecord,
)
from .cloud_rules import (
    BEAST_INTRO_QUEST,
    CLOUD_ROUTES,
    DEMON_INTRO_QUEST,
    cloud_route_definition,
    world_intro_definition,
)
from .permissions import array_hall_permission
from ..utils.json import json_object


class CloudRepositoryMixin:
    """Transactional world operations.

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
            replay = operation_replay(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                player = self._require_player(connection, platform, platform_user_id, writable=False)
                self._validate_cloud_start_replay(connection, replay, operation_id, int(player["id"]))
                return self._cloud_start_from_payload(replay, replay=True)

            player = self._require_player(connection, platform, platform_user_id)
            player_id = int(player["id"])
            source = str(player["location_key"])
            if source not in definition.source_locations:
                raise LocationRequirementError("cloud route source is not available")
            if not self._cloud_meets_realm(str(player["realm_key"]), player_integer(player, "realm_layer"), definition.required_realm, definition.required_layer):
                raise CloudRouteLockedError("cloud route realm requirement is not met")
            if definition.required_quest and not self._cloud_quest_completed(connection, player_id, definition.required_quest):
                raise CloudRouteLockedError("cloud route quest requirement is not met")
            if self._has_active_long_action(connection, player_id):
                raise CloudBoatBusyError("another long action is active")

            stamina = player_integer(player, "stamina")
            if stamina < definition.stamina_cost:
                raise ResourceInsufficientError("stamina is insufficient")
            if player_currency(player) < definition.currency_cost:
                raise CloudFareInsufficientError("cloud fare is insufficient")
            asset_costs = {"spirit_stones": definition.currency_cost}
            if definition.pass_key:
                asset_costs[definition.pass_key] = definition.pass_quantity
            try:
                spend_player_state(
                    connection,
                    player,
                    updated_at=now_text,
                    costs=asset_costs,
                    value_delta={"stamina": -definition.stamina_cost},
                )
            except ValueError as exc:
                if definition.pass_key and "inventory" in str(exc):
                    raise AdvancedCavePassMissingError("advanced cave pass is missing") from exc
                raise CloudFareInsufficientError("cloud fare is insufficient") from exc
            session_id = uuid4().hex
            ends_at = now + timedelta(seconds=definition.duration_seconds)
            snapshot = {
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
            created = connection.execute(
                "SELECT * FROM cloud_boat_sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
            if created is None:
                raise ValueError("cloud session was not persisted")
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
            record_operation(connection, operation_id, operation_name, player_id, request_hash, payload, now_text)
            self._validate_cloud_session(connection, created, player_id)
            return self._cloud_start_from_payload(payload)

    async def settle_cloud_boat(
        self, *, platform: str, platform_user_id: str, operation_id: str
    ) -> CloudBoatSettlementRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._settle_cloud_boat_once, platform, platform_user_id, operation_id, False
            )

    async def recover_cloud_boat(
        self, *, platform: str, platform_user_id: str, operation_id: str
    ) -> CloudBoatSettlementRecord:
        """Recover a session that missed its normal settlement window."""

        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._settle_cloud_boat_once, platform, platform_user_id, operation_id, True
            )

    def _settle_cloud_boat_once(
        self, platform: str, platform_user_id: str, operation_id: str, recover: bool
    ) -> CloudBoatSettlementRecord:
        from ..repository import CloudBoatNotFoundError, CloudBoatNotReadyError

        operation_name = "world.recover_cloud_boat" if recover else "world.settle_cloud_boat"
        request_hash = self._request_hash(operation_name, {"platform": platform, "platform_user_id": platform_user_id})
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = operation_replay(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                player = self._require_player(connection, platform, platform_user_id, writable=False)
                self._validate_cloud_settlement_replay(
                    connection, replay, operation_name, int(player["id"])
                )
                return self._cloud_settlement_from_payload(replay, replay=True)
            player = self._require_player(connection, platform, platform_user_id, writable=False)
            session = connection.execute(
                "SELECT * FROM cloud_boat_sessions WHERE player_id = ? AND status = 'running' ORDER BY id DESC LIMIT 1",
                (player["id"],),
            ).fetchone()
            if session is None:
                raise CloudBoatNotFoundError("no running cloud boat")
            self._validate_cloud_session(connection, session, int(player["id"]))
            ready_at = datetime.fromisoformat(str(session["ends_at"]))
            if recover:
                ready_at += timedelta(hours=24)
            if now < ready_at:
                raise CloudBoatNotReadyError(
                    "cloud boat recovery window has not opened" if recover else "cloud boat is not ready"
                )
            change_player_state(
                connection,
                player,
                updated_at=now_text,
                player_values={"location_key": session["destination"]},
            )
            result = {
                "arrived": True,
                "settled_at": now_text,
                "destination": session["destination"],
                **({"recovered": True} if recover else {}),
            }
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
            record_operation(connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text)
            return self._cloud_settlement_from_payload(payload)

    @staticmethod
    def _strict_cloud_object(value: Any, label: str) -> dict[str, Any]:
        try:
            decoded = decode_json_strict(str(value))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError(f"{label} is malformed") from exc
        if not isinstance(decoded, dict):
            raise ValueError(f"{label} must be an object")
        return decoded

    @classmethod
    def _validate_cloud_session(cls, connection: Any, session: Any, player_id: int) -> dict[str, Any]:
        if int(session["player_id"]) != int(player_id):
            raise ValueError("cloud session owner does not match player")
        snapshot = cls._strict_cloud_object(session["snapshot_json"], "cloud session snapshot")
        required = {
            "route_key", "source", "destination", "stamina_cost", "currency_cost",
            "pass_key", "pass_quantity", "required_realm", "required_layer", "required_quest",
        }
        if set(snapshot) != required:
            raise ValueError("cloud session snapshot fields are invalid")
        for key in ("route_key", "source", "destination", "required_realm"):
            if not isinstance(snapshot[key], str) or not snapshot[key].strip():
                raise ValueError(f"cloud session snapshot {key} is invalid")
        for key in ("stamina_cost", "currency_cost", "pass_quantity", "required_layer"):
            value = snapshot[key]
            minimum = 1 if key in {"stamina_cost", "currency_cost", "required_layer"} else 0
            if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
                raise ValueError(f"cloud session snapshot {key} is invalid")
        if snapshot["pass_key"] is not None and (
            not isinstance(snapshot["pass_key"], str) or not snapshot["pass_key"].strip()
        ):
            raise ValueError("cloud session snapshot pass_key is invalid")
        if snapshot["required_quest"] is not None and (
            not isinstance(snapshot["required_quest"], str) or not snapshot["required_quest"].strip()
        ):
            raise ValueError("cloud session snapshot required_quest is invalid")
        expected = {
            "route_key": str(session["route_key"]),
            "source": str(session["source_location"]),
            "destination": str(session["destination"]),
            "stamina_cost": int(session["stamina_cost"]),
            "currency_cost": int(session["currency_cost"]),
            "pass_key": session["pass_key"],
            "pass_quantity": int(session["pass_quantity"]),
        }
        if any(snapshot[key] != value for key, value in expected.items()):
            raise ValueError("cloud session snapshot does not match persisted route")
        try:
            starts_at = datetime.fromisoformat(str(session["starts_at"]))
            ends_at = datetime.fromisoformat(str(session["ends_at"]))
        except (TypeError, ValueError) as exc:
            raise ValueError("cloud session timestamps are invalid") from exc
        if starts_at.tzinfo is None or ends_at.tzinfo is None:
            raise ValueError("cloud session timestamps are invalid")
        board = connection.execute(
            "SELECT operation_name, player_id, result_json FROM operations WHERE operation_id = ?",
            (str(session["operation_id"]),),
        ).fetchone()
        if board is None or str(board["operation_name"]) != "world.board_cloud_boat" or int(board["player_id"]) != int(player_id):
            raise ValueError("cloud session start operation does not match player")
        payload = cls._strict_cloud_object(board["result_json"], "cloud session start operation")
        cls._validate_cloud_payload_scalars(payload, "running", require_times=True)
        for key in (
            "player", "session_id", "route_key", "source", "destination", "status", "starts_at", "ends_at",
            "stamina_cost", "currency_cost", "pass_key", "pass_quantity",
        ):
            if key not in payload:
                raise ValueError("cloud session start operation fields are invalid")
        if not cls._cloud_player_payload_matches(connection, payload["player"], int(player_id)):
            raise ValueError("cloud session start operation player is invalid")
        if payload["session_id"] != str(session["session_id"]):
            raise ValueError("cloud session start operation session does not match")
        if payload["route_key"] != expected["route_key"] or payload["source"] != expected["source"] or payload["destination"] != expected["destination"]:
            raise ValueError("cloud session start operation route does not match")
        if any(
            payload[key] != expected[key]
            for key in ("stamina_cost", "currency_cost", "pass_key", "pass_quantity")
        ):
            raise ValueError("cloud session start operation costs do not match")
        if (
            payload["status"] != "running"
            or payload["starts_at"] != str(session["starts_at"])
            or payload["ends_at"] != str(session["ends_at"])
        ):
            raise ValueError("cloud session start operation timing is invalid")
        return snapshot

    @staticmethod
    def _cloud_player_payload_matches(connection: Any, payload: Any, player_id: int) -> bool:
        if not isinstance(payload, dict):
            return False
        row = connection.execute("SELECT player_id FROM players WHERE id = ?", (int(player_id),)).fetchone()
        if row is None:
            return False
        stable_id = str(row["player_id"])
        return payload.get("id") == stable_id and payload.get("player_id") == stable_id

    @classmethod
    def _validate_cloud_start_replay(
        cls, connection: Any, payload: dict[str, Any], operation_id: str, player_id: int
    ) -> None:
        cls._validate_cloud_payload_scalars(payload, "running", require_times=True)
        if not cls._cloud_player_payload_matches(connection, payload["player"], int(player_id)):
            raise ValueError("cloud start operation player is invalid")
        session = connection.execute(
            "SELECT * FROM cloud_boat_sessions WHERE session_id = ? AND player_id = ?",
            (payload["session_id"], int(player_id)),
        ).fetchone()
        if session is None or str(session["operation_id"]) != str(operation_id) or str(session["status"]) not in {"running", "arrived"}:
            raise ValueError("cloud start operation session is invalid")
        cls._validate_cloud_session(connection, session, int(player_id))
        expected = {
            "route_key": str(session["route_key"]),
            "source": str(session["source_location"]),
            "destination": str(session["destination"]),
            "stamina_cost": int(session["stamina_cost"]),
            "currency_cost": int(session["currency_cost"]),
            "pass_key": session["pass_key"],
            "pass_quantity": int(session["pass_quantity"]),
            "starts_at": str(session["starts_at"]),
            "ends_at": str(session["ends_at"]),
        }
        if any(payload.get(key) != value for key, value in expected.items()):
            raise ValueError("cloud start operation does not match session")

    @classmethod
    def _validate_cloud_settlement_replay(
        cls, connection: Any, payload: dict[str, Any], operation_name: str, player_id: int
    ) -> None:
        cls._validate_cloud_payload_scalars(payload, "arrived")
        for key in ("player", "session_id", "route_key", "source", "destination", "status", "arrived"):
            if key not in payload:
                raise ValueError("cloud settlement operation fields are invalid")
        if (
            not cls._cloud_player_payload_matches(connection, payload["player"], int(player_id))
            or payload["status"] != "arrived"
            or payload["arrived"] is not True
        ):
            raise ValueError("cloud settlement operation result is invalid")
        session = connection.execute(
            "SELECT * FROM cloud_boat_sessions WHERE session_id = ? AND player_id = ?",
            (str(payload["session_id"]), int(player_id)),
        ).fetchone()
        if session is None or str(session["status"]) != "arrived":
            raise ValueError("cloud settlement operation session is invalid")
        cls._validate_cloud_session(connection, session, int(player_id))
        result = cls._strict_cloud_object(session["result_json"], "cloud settlement result")
        expected_result_keys = {"arrived", "settled_at", "destination"}
        if operation_name == "world.recover_cloud_boat":
            expected_result_keys.add("recovered")
        if set(result) != expected_result_keys:
            raise ValueError("cloud settlement result fields are invalid")
        settled_at = result.get("settled_at")
        if (
            result.get("arrived") is not True
            or result.get("destination") != str(session["destination"])
            or not isinstance(settled_at, str)
        ):
            raise ValueError("cloud settlement result does not match session")
        try:
            settled_at_value = datetime.fromisoformat(settled_at)
        except (TypeError, ValueError) as exc:
            raise ValueError("cloud settlement result timestamp is invalid") from exc
        if settled_at_value.tzinfo is None:
            raise ValueError("cloud settlement result timestamp is invalid")
        if operation_name == "world.recover_cloud_boat" and result.get("recovered") is not True:
            raise ValueError("cloud recovery result is invalid")
        if operation_name == "world.settle_cloud_boat" and result.get("recovered") is not None:
            raise ValueError("cloud settlement result is invalid")
        expected = {
            "route_key": str(session["route_key"]),
            "source": str(session["source_location"]),
            "destination": str(session["destination"]),
            "status": "arrived",
            "stamina_cost": int(session["stamina_cost"]),
            "currency_cost": int(session["currency_cost"]),
            "pass_key": session["pass_key"],
            "pass_quantity": int(session["pass_quantity"]),
        }
        if any(payload.get(key) != value for key, value in expected.items()):
            raise ValueError("cloud settlement operation route does not match session")

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
            replay = operation_replay(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                return self._demon_intro_from_payload(replay, replay=True)
            player = self._require_player(connection, platform, platform_user_id)
            player_id = int(player["id"])
            definition = world_intro_definition(
                DEMON_INTRO_QUEST, self.content, expected_operation=operation_name
            )
            if str(player["location_key"]) != definition.required_location_key:
                raise DemonIntroRequirementError("demon introduction requires the arrived gate route")
            if not self._cloud_meets_realm(
                str(player["realm_key"]), player_integer(player, "realm_layer"),
                definition.required_realm_key, definition.required_realm_layer,
            ):
                raise DemonIntroRequirementError("demon introduction realm requirement is not met")
            if definition.arrival_route_key and not self._cloud_quest_route_arrived(
                connection, player_id, definition.arrival_route_key
            ):
                raise DemonIntroRequirementError("demon introduction requires the arrived gate route")
            progress = connection.execute(
                "SELECT status FROM quest_progress WHERE player_id = ? AND quest_key = ?",
                (player_id, DEMON_INTRO_QUEST),
            ).fetchone()
            if progress is not None and str(progress["status"]) in {"completed", "claimed"}:
                raise DemonIntroAlreadyCompletedError("demon introduction already completed")
            asset_costs, value_costs = self._world_intro_costs(definition.costs)
            intro = self._world_intro_state(player["intro_json"])
            flags = [str(item) for item in intro.get("flags", [])]
            for flag in (definition.key, definition.access_flag):
                if flag not in flags:
                    flags.append(flag)
            intro["flags"] = flags
            try:
                spend_player_state(
                    connection, player, updated_at=now_text, costs=asset_costs or None,
                    value_delta=value_costs or None,
                    player_values={"intro_json": json.dumps(intro, ensure_ascii=False, sort_keys=True)},
                )
            except ValueError as exc:
                raise ResourceInsufficientError("demon introduction costs are insufficient") from exc
            current_player = connection.execute("SELECT * FROM players WHERE id = ?", (player_id,)).fetchone()
            actual_reward = grant_player_reward_actual(
                connection, current_player, reward_totals(definition.reward), now_text
            )
            reward_snapshot = definition.reward.snapshot()
            self._insert_quest_event(
                connection,
                player_id=player_id,
                quest_key=DEMON_INTRO_QUEST,
                component_key="risk_confirmation",
                source_operation_id=operation_id,
                outcome="success",
                payload={"route": definition.arrival_route_key, "costs": definition.costs, "reward": actual_reward},
                now_text=now_text,
            )
            self._upsert_progress(
                connection,
                player_id,
                DEMON_INTRO_QUEST,
                "completed",
                {"risk_confirmation": 1},
                {"access_flag": definition.access_flag, "faction": "demon", "costs": definition.costs, "reward": reward_snapshot},
                operation_id,
                now_text,
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (player_id,)).fetchone()
            payload = {
                "player": self._player_payload(self._row_to_player(updated)),
                "quest_key": DEMON_INTRO_QUEST,
                "status": "completed",
                "reward": actual_reward,
                "reward_snapshot": reward_snapshot,
                "costs": dict(definition.costs),
            }
            record_operation(connection, operation_id, operation_name, player_id, request_hash, payload, now_text)
            return self._demon_intro_from_payload(payload)

    async def read_beast_history(
        self, *, platform: str, platform_user_id: str, operation_id: str
    ) -> BeastHistoryRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._read_beast_history_once, platform, platform_user_id, operation_id
            )

    def _read_beast_history_once(
        self, platform: str, platform_user_id: str, operation_id: str
    ) -> BeastHistoryRecord:
        from ..repository import OperationConflictError

        operation_name = "world.read_beast_history"
        request_hash = self._request_hash(
            operation_name, {"platform": platform, "platform_user_id": platform_user_id}
        )
        now_text = serialize_datetime(self._now())
        component_key = "beast_history_read"
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            payload = operation_replay(connection, operation_id, operation_name, request_hash)
            if payload is not None:
                return BeastHistoryRecord(
                    quest_key=str(payload["quest_key"]),
                    component_key=str(payload["component_key"]),
                    already_completed=True,
                )

            player = self._require_player(connection, platform, platform_user_id)
            player_id = int(player["id"])
            self._insert_quest_event(
                connection,
                player_id=player_id,
                quest_key=BEAST_INTRO_QUEST,
                component_key=component_key,
                source_operation_id=operation_id,
                outcome="read",
                payload={"source": "beast_history"},
                now_text=now_text,
            )
            progress = connection.execute(
                "SELECT status FROM quest_progress WHERE player_id = ? AND quest_key = ?",
                (player_id, BEAST_INTRO_QUEST),
            ).fetchone()
            if progress is None or str(progress["status"]) not in {"completed", "claimed"}:
                self._upsert_progress(
                    connection,
                    player_id,
                    BEAST_INTRO_QUEST,
                    "active",
                    {component_key: 1},
                    {"quest_key": BEAST_INTRO_QUEST},
                    operation_id,
                    now_text,
                )
            payload = {"quest_key": BEAST_INTRO_QUEST, "component_key": component_key}
            record_operation(connection, operation_id, operation_name, player_id, request_hash, payload, now_text)
            return BeastHistoryRecord(quest_key=BEAST_INTRO_QUEST, component_key=component_key)

    async def complete_beast_intro(
        self, *, platform: str, platform_user_id: str, operation_id: str
    ) -> BeastIntroRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._complete_beast_intro_once, platform, platform_user_id, operation_id
            )

    def _complete_beast_intro_once(
        self, platform: str, platform_user_id: str, operation_id: str
    ) -> BeastIntroRecord:
        from ..repository import (
            BeastIntroAlreadyCompletedError,
            BeastIntroRequirementError,
            OperationConflictError,
            ResourceInsufficientError,
        )

        operation_name = "world.complete_beast_intro"
        request_hash = self._request_hash(
            operation_name, {"platform": platform, "platform_user_id": platform_user_id}
        )
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = operation_replay(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                return self._beast_intro_from_payload(replay, replay=True)

            player = self._require_player(connection, platform, platform_user_id)
            player_id = int(player["id"])
            definition = world_intro_definition(
                BEAST_INTRO_QUEST, self.content, expected_operation=operation_name
            )
            progress = connection.execute(
                "SELECT status FROM quest_progress WHERE player_id = ? AND quest_key = ?",
                (player_id, BEAST_INTRO_QUEST),
            ).fetchone()
            if progress is not None and str(progress["status"]) in {"completed", "claimed"}:
                raise BeastIntroAlreadyCompletedError("beast introduction already completed")
            if not self._cloud_meets_realm(
                str(player["realm_key"]), player_integer(player, "realm_layer"),
                definition.required_realm_key, definition.required_realm_layer,
            ):
                raise BeastIntroRequirementError("beast introduction requires foundation")
            history = connection.execute(
                "SELECT 1 FROM quest_events WHERE player_id = ? AND quest_key = ? "
                "AND component_key = ? AND outcome = 'read' LIMIT 1",
                (player_id, BEAST_INTRO_QUEST, definition.required_read_component),
            ).fetchone()
            if definition.required_read_component and history is None:
                raise BeastIntroRequirementError("beast history has not been read")
            observation = self._valid_beast_observation(connection, player_id, definition.required_evidence)
            if observation is None:
                raise BeastIntroRequirementError("outskirts beast observation is incomplete")
            asset_costs, value_costs = self._world_intro_costs(definition.costs)

            intro = self._world_intro_state(player["intro_json"])
            flags = {str(item) for item in intro.get("flags", [])}
            flags.update({definition.key, definition.access_flag})
            intro["flags"] = sorted(flags)
            try:
                spend_player_state(
                    connection, player, updated_at=now_text, costs=asset_costs or None,
                    value_delta=value_costs or None,
                    player_values={"intro_json": json.dumps(intro, ensure_ascii=False, sort_keys=True)},
                )
            except ValueError as exc:
                raise ResourceInsufficientError("beast introduction costs are insufficient") from exc
            current_player = connection.execute("SELECT * FROM players WHERE id = ?", (player_id,)).fetchone()
            actual_reward = grant_player_reward_actual(
                connection, current_player, reward_totals(definition.reward), now_text
            )
            reward_snapshot = definition.reward.snapshot()
            self._insert_quest_event(
                connection,
                player_id=player_id,
                quest_key=BEAST_INTRO_QUEST,
                component_key="outskirts_beast_observation",
                source_operation_id=str(observation["settlement_operation_id"]),
                outcome="success",
                payload={"exploration_id": str(observation["exploration_id"]), "mode_key": str(observation["mode_key"])},
                now_text=now_text,
            )
            self._insert_quest_event(
                connection,
                player_id=player_id,
                quest_key=BEAST_INTRO_QUEST,
                component_key="submission",
                source_operation_id=operation_id,
                outcome="success",
                payload={"costs": definition.costs, "reward": actual_reward},
                now_text=now_text,
            )
            quest_snapshot = {
                "quest_key": BEAST_INTRO_QUEST,
                "access_flag": definition.access_flag,
                "costs": definition.costs,
                "reward": reward_snapshot,
                "exploration_id": str(observation["exploration_id"]),
                "exploration_operation_id": str(observation["settlement_operation_id"]),
                "exploration_start_operation_id": str(observation["start_operation_id"]),
                "exploration_mode": str(observation["mode_key"]),
            }
            self._upsert_progress(
                connection,
                player_id,
                BEAST_INTRO_QUEST,
                "completed",
                {"beast_history_read": 1, "outskirts_beast_observation": 1, "submission": 1},
                quest_snapshot,
                operation_id,
                now_text,
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (player_id,)).fetchone()
            payload = {
                "player": self._player_payload(self._row_to_player(updated)),
                "quest_key": BEAST_INTRO_QUEST,
                "status": "completed",
                "reward": actual_reward,
                "reward_snapshot": reward_snapshot,
                "costs": dict(definition.costs),
            }
            record_operation(connection, operation_id, operation_name, player_id, request_hash, payload, now_text)
            return self._beast_intro_from_payload(payload)

    @staticmethod
    def _valid_beast_observation(
        connection: Any, player_id: int, evidence: dict[str, Any] | None
    ) -> Any | None:
        if evidence is None:
            return None
        mode_keys = tuple(str(value) for value in evidence["mode_keys"])
        placeholders = ",".join("?" for _ in mode_keys)
        return connection.execute(
            f"""
            SELECT e.exploration_id, e.operation_id AS start_operation_id, e.mode_key,
                (
                    SELECT o.operation_id FROM operations AS o
                    WHERE o.player_id = e.player_id
                        AND o.operation_name IN ('exploration.settle', 'exploration.settle_combat')
                        AND json_extract(o.result_json, '$.exploration_id') = e.exploration_id
                        AND json_extract(o.result_json, '$.status') = 'settled'
                    ORDER BY o.created_at ASC LIMIT 1
                ) AS settlement_operation_id
            FROM exploration_sessions AS e
            WHERE e.player_id = ? AND e.location_key = ?
                AND e.mode_key IN ({placeholders})
                AND e.status = ?
                AND EXISTS (
                    SELECT 1 FROM operations AS o
                    WHERE o.player_id = e.player_id
                        AND o.operation_name IN ('exploration.settle', 'exploration.settle_combat')
                        AND json_extract(o.result_json, '$.exploration_id') = e.exploration_id
                        AND json_extract(o.result_json, '$.status') = 'settled'
                )
            ORDER BY e.id ASC
            LIMIT 1
            """,
            (player_id, evidence["location_key"], *mode_keys, evidence["status"]),
        ).fetchone()

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
            replay = operation_replay(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                return self._array_hall_from_payload(replay, replay=True)
            player = self._require_player(connection, platform, platform_user_id)
            if str(player["location_key"]) != "xuantian.array_hall":
                raise ArrayHallPermissionDeniedError("array hall location is required")
            if not self._cloud_meets_realm(str(player["realm_key"]), player_integer(player, "realm_layer"), "qi_gathering", 1):
                raise ArrayHallPermissionDeniedError("array hall requires qi gathering")
            permission = array_hall_permission(connection, player)
            if permission is None:
                raise ArrayHallPermissionDeniedError("array hall permission is not granted")
            if player_integer(player, "stamina") < 3:
                raise ResourceInsufficientError("array hall requires 3 stamina")
            change_player_state(
                connection,
                player,
                updated_at=now_text,
                value_delta={"stamina": -3},
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (player["id"],)).fetchone()
            payload = {
                "player": self._player_payload(self._row_to_player(updated)),
                "status": "authorized",
                "permission": permission,
                "action": "formation_learning_or_production_request",
            }
            record_operation(connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text)
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
        flags = json_object(intro["intro_json"], {}).get("flags", []) if intro else []
        return quest_key in {str(item) for item in flags}

    @staticmethod
    def _cloud_quest_route_arrived(connection: Any, player_id: int, route_key: str) -> bool:
        return connection.execute(
            "SELECT 1 FROM cloud_boat_sessions WHERE player_id = ? AND route_key = ? AND status = 'arrived' LIMIT 1",
            (player_id, route_key),
        ).fetchone() is not None

    @staticmethod
    def _world_intro_costs(costs: dict[str, int]) -> tuple[dict[str, int], dict[str, int]]:
        assets: dict[str, int] = {}
        values: dict[str, int] = {}
        for key, amount in costs.items():
            if key == "currency.spirit_stone":
                assets["spirit_stones"] = amount
            elif key.startswith("resource."):
                values[key.removeprefix("resource.")] = -amount
            else:
                raise ValueError(f"unsupported world introduction cost: {key}")
        return assets, values

    @staticmethod
    def _world_intro_state(raw: Any) -> dict[str, Any]:
        try:
            value = json.loads(raw) if isinstance(raw, str) else raw
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("player introduction state is malformed") from exc
        if not isinstance(value, dict):
            raise ValueError("player introduction state must be an object")
        flags = value.get("flags", [])
        if not isinstance(flags, list) or any(not isinstance(flag, str) for flag in flags):
            raise ValueError("player introduction flags are malformed")
        return dict(value)

    @staticmethod
    def _cloud_start_from_payload(payload: dict[str, Any], *, replay: bool = False) -> CloudBoatStartRecord:
        from ..repository import SQLitePlayerRepository

        CloudRepositoryMixin._validate_cloud_payload_scalars(payload, "running", require_times=True)
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

        CloudRepositoryMixin._validate_cloud_payload_scalars(payload, "arrived")
        if payload.get("arrived") is not True:
            raise ValueError("cloud settlement payload must be arrived")
        return CloudBoatSettlementRecord(
            player=SQLitePlayerRepository._row_to_player(payload["player"]),
            session_id=str(payload["session_id"]), route_key=str(payload["route_key"]),
            source=str(payload["source"]), destination=str(payload["destination"]), status=str(payload["status"]),
            arrived=bool(payload.get("arrived", False)), stamina_cost=int(payload.get("stamina_cost", 0)),
            currency_cost=int(payload.get("currency_cost", 0)), pass_key=payload.get("pass_key"),
            pass_quantity=int(payload.get("pass_quantity", 0)), already_completed=replay,
        )

    @staticmethod
    def _validate_cloud_payload_scalars(
        payload: dict[str, Any], status: str, *, require_times: bool = False
    ) -> None:
        required = (
            "player", "session_id", "route_key", "source", "destination", "status",
            "stamina_cost", "currency_cost", "pass_key", "pass_quantity",
        )
        expected_keys = set(required)
        if require_times:
            expected_keys.update(("starts_at", "ends_at"))
        if status == "arrived":
            expected_keys.add("arrived")
        if set(payload) != expected_keys:
            raise ValueError("cloud payload fields are invalid")
        if (
            not isinstance(payload["player"], dict)
            or not isinstance(payload["player"].get("id"), str)
            or not isinstance(payload["player"].get("player_id"), str)
            or payload["player"].get("id") != payload["player"].get("player_id")
        ):
            raise ValueError("cloud payload player is invalid")
        for key in ("session_id", "route_key", "source", "destination"):
            if not isinstance(payload[key], str) or not payload[key].strip():
                raise ValueError(f"cloud payload {key} is invalid")
        if payload["status"] != status:
            raise ValueError("cloud payload status is invalid")
        for key in ("stamina_cost", "currency_cost"):
            if isinstance(payload[key], bool) or not isinstance(payload[key], int) or payload[key] <= 0:
                raise ValueError(f"cloud payload {key} is invalid")
        if payload["pass_key"] is not None and (
            not isinstance(payload["pass_key"], str) or not payload["pass_key"].strip()
        ):
            raise ValueError("cloud payload pass_key is invalid")
        if isinstance(payload["pass_quantity"], bool) or not isinstance(payload["pass_quantity"], int) or payload["pass_quantity"] < 0:
            raise ValueError("cloud payload pass_quantity is invalid")
        if require_times:
            for key in ("starts_at", "ends_at"):
                if not isinstance(payload.get(key), str) or not payload[key].strip():
                    raise ValueError(f"cloud payload {key} is invalid")
            try:
                starts_at = datetime.fromisoformat(payload["starts_at"])
                ends_at = datetime.fromisoformat(payload["ends_at"])
            except (TypeError, ValueError) as exc:
                raise ValueError("cloud payload timestamps are invalid") from exc
            if starts_at.tzinfo is None or ends_at.tzinfo is None or ends_at <= starts_at:
                raise ValueError("cloud payload timestamps are invalid")

    @staticmethod
    def _demon_intro_from_payload(payload: dict[str, Any], *, replay: bool = False) -> DemonIntroRecord:
        from ..repository import SQLitePlayerRepository

        reward_grant_from_snapshot(payload["reward_snapshot"], operation="world.accept_demon_intro")
        return DemonIntroRecord(
            player=SQLitePlayerRepository._row_to_player(payload["player"]), quest_key=str(payload["quest_key"]),
            status=str(payload["status"]), reward={str(k): int(v) for k, v in payload.get("reward", {}).items()},
            already_completed=replay,
        )

    @staticmethod
    def _beast_intro_from_payload(payload: dict[str, Any], *, replay: bool = False) -> BeastIntroRecord:
        from ..repository import SQLitePlayerRepository

        reward_grant_from_snapshot(payload["reward_snapshot"], operation="world.complete_beast_intro")
        return BeastIntroRecord(
            player=SQLitePlayerRepository._row_to_player(payload["player"]),
            quest_key=str(payload["quest_key"]),
            status=str(payload["status"]),
            reward={str(k): int(v) for k, v in payload.get("reward", {}).items()},
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
