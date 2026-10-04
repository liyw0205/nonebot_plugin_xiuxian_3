"""SQLite transactions for player-to-player livelihood service orders."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from ...contracts import serialize_datetime
from ..utils.assets import player_currency
from ..utils.player import (
    change_player_state_actual,
    player_reputation_state,
    player_requirements_missing,
    spend_player_state,
)
from ..utils.json import json_object
from ..persistence.errors import (
    OperationConflictError,
    PlayerNotFoundError,
    ResourceInsufficientError,
    ServiceAlreadySettledError,
    ServiceDailyLimitError,
    ServiceLocationConflictError,
    ServiceNotFoundError,
    ServiceOrderConflictError,
    ServiceReputationInsufficientError,
    ServiceRequirementError,
    ServiceSelfAcceptError,
)
from .service_models import ServiceOrderRecord, ServiceSettlementRecord
from .service_rules import ServiceDefinition, service_definition, service_reward


class ServiceRepositoryMixin:
    """Own the cross-player lock and settlement transactions for services."""

    async def publish_service(
        self,
        *,
        platform: str,
        platform_user_id: str,
        service_key: str,
        reward_stones: int | None,
        operation_id: str,
    ) -> ServiceOrderRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._publish_service_once,
                platform,
                platform_user_id,
                service_key,
                reward_stones,
                operation_id,
            )

    def _publish_service_once(
        self,
        platform: str,
        platform_user_id: str,
        service_key: str,
        reward_stones: int | None,
        operation_id: str,
    ) -> ServiceOrderRecord:
        try:
            definition = service_definition(service_key, self.content)
            reward = service_reward(definition, reward_stones)
        except ValueError as exc:
            raise ServiceRequirementError("unsupported service or reward") from exc
        operation_name = "livelihood.publish_service"
        request_hash = self._request_hash(
            operation_name,
            {
                "platform": platform,
                "platform_user_id": platform_user_id,
                "service_key": definition.key,
                "reward_stones": reward,
            },
        )
        now = self._now()
        now_text = serialize_datetime(now)
        expires_at = serialize_datetime(now + timedelta(seconds=definition.duration_seconds))
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._operation(connection, operation_id, operation_name, request_hash)
            if existing is not None:
                return self._order_from_payload(existing, replay=True)
            publisher = self._require_player(connection, platform, platform_user_id)
            if player_currency(publisher) < reward:
                raise ResourceInsufficientError("publisher reward is insufficient")
            spend_player_state(
                connection,
                publisher,
                {"spirit_stones": reward},
                now_text,
            )
            order_id = uuid4().hex
            snapshot = self._service_snapshot(definition, reward, publisher, now_text, expires_at)
            connection.execute(
                """
                INSERT INTO livelihood_service_orders(
                    order_id, publish_operation_id, publisher_id, provider_id, service_key, status,
                    reward_stones, starts_at, expires_at, snapshot_json,
                    accepted_at, settled_at, result_json, created_at, updated_at
                ) VALUES (?, ?, ?, NULL, ?, 'published', ?, ?, ?, ?, NULL, NULL, '{}', ?, ?)
                """,
                (
                    order_id,
                    operation_id,
                    publisher["id"],
                    definition.key,
                    reward,
                    now_text,
                    expires_at,
                    json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
                    now_text,
                    now_text,
                ),
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (publisher["id"],)).fetchone()
            if updated is None:
                raise RuntimeError("service publish returned no publisher")
            payload = self._order_payload(
                updated,
                order_id,
                definition.key,
                definition.label,
                definition.description,
                reward,
                now_text,
                expires_at,
                snapshot,
                status="published",
            )
            self._record_operation(connection, operation_id, operation_name, publisher["id"], request_hash, payload, now_text)
            return self._order_from_payload(payload)

    async def cancel_service(
        self,
        *,
        platform: str,
        platform_user_id: str,
        order_id: str,
        operation_id: str,
    ) -> ServiceOrderRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._cancel_service_once,
                platform,
                platform_user_id,
                order_id,
                operation_id,
            )

    def _cancel_service_once(
        self,
        platform: str,
        platform_user_id: str,
        order_id: str,
        operation_id: str,
    ) -> ServiceOrderRecord:
        operation_name = "livelihood.cancel_service"
        request_hash = self._request_hash(
            operation_name,
            {"platform": platform, "platform_user_id": platform_user_id, "order_id": order_id},
        )
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._operation(connection, operation_id, operation_name, request_hash)
            if existing is not None:
                return self._order_from_payload(existing, replay=True)
            publisher = self._require_player(connection, platform, platform_user_id)
            order = connection.execute(
                "SELECT * FROM livelihood_service_orders WHERE order_id = ? AND publisher_id = ?",
                (order_id, publisher["id"]),
            ).fetchone()
            if order is None:
                raise ServiceNotFoundError("service order does not exist for publisher")
            if str(order["status"]) != "published":
                raise ServiceOrderConflictError("only published service orders can be cancelled")
            snapshot = self._service_snapshot_object(order["snapshot_json"])
            self._validate_snapshot_row(snapshot, order)
            service_name = str(snapshot["service_name"])
            connection.execute(
                "UPDATE livelihood_service_orders SET status = 'cancelled', updated_at = ? WHERE id = ? AND status = 'published'",
                (now_text, order["id"]),
            )
            change_player_state_actual(
                connection,
                publisher,
                updated_at=now_text,
                asset_values={"spirit_stones": int(order["reward_stones"])},
                asset_mode="grant",
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (publisher["id"],)).fetchone()
            if updated is None:
                raise RuntimeError("service cancellation returned no publisher")
            payload = self._order_payload(
                updated,
                str(order["order_id"]),
                str(order["service_key"]),
                service_name,
                str(snapshot["service_description"]),
                int(order["reward_stones"]),
                str(order["starts_at"]),
                str(order["expires_at"]),
                snapshot,
                status="cancelled",
            )
            self._record_operation(connection, operation_id, operation_name, publisher["id"], request_hash, payload, now_text)
            return self._order_from_payload(payload)

    async def accept_service(
        self,
        *,
        platform: str,
        platform_user_id: str,
        order_id: str,
        operation_id: str,
    ) -> ServiceOrderRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._accept_service_once,
                platform,
                platform_user_id,
                order_id,
                operation_id,
            )

    def _accept_service_once(
        self,
        platform: str,
        platform_user_id: str,
        order_id: str,
        operation_id: str,
    ) -> ServiceOrderRecord:
        operation_name = "livelihood.accept_service"
        request_hash = self._request_hash(
            operation_name,
            {"platform": platform, "platform_user_id": platform_user_id, "order_id": order_id},
        )
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._operation(connection, operation_id, operation_name, request_hash)
            if existing is not None:
                return self._order_from_payload(existing, replay=True)
            provider = self._require_player(connection, platform, platform_user_id)
            order = connection.execute(
                "SELECT * FROM livelihood_service_orders WHERE order_id = ?", (order_id,)
            ).fetchone()
            if order is None:
                raise ServiceNotFoundError("service order does not exist")
            if int(order["publisher_id"]) == int(provider["id"]):
                raise ServiceSelfAcceptError("publisher cannot accept their own service")
            if str(order["status"]) != "published":
                raise ServiceOrderConflictError("service order is no longer published")
            snapshot = self._service_snapshot_object(order["snapshot_json"])
            self._validate_snapshot_row(snapshot, order)
            if now >= datetime.fromisoformat(str(order["expires_at"])):
                connection.execute(
                    "UPDATE livelihood_service_orders SET status = 'expired', updated_at = ? WHERE id = ? AND status = 'published'",
                    (now_text, order["id"]),
                )
                expired_publisher = connection.execute(
                    "SELECT * FROM players WHERE id = ?", (order["publisher_id"],)
                ).fetchone()
                if expired_publisher is None:
                    raise PlayerNotFoundError("publisher does not exist")
                change_player_state_actual(
                    connection,
                    expired_publisher,
                    updated_at=now_text,
                    asset_values={"spirit_stones": int(order["reward_stones"])},
                    asset_mode="grant",
                )
                updated = connection.execute(
                    "SELECT * FROM players WHERE id = ?", (provider["id"],)
                ).fetchone()
                if updated is None:
                    raise RuntimeError("expired service returned no provider")
                payload = self._order_payload(
                    updated,
                    str(order["order_id"]),
                    str(order["service_key"]),
                    str(snapshot["service_name"]),
                    str(snapshot["service_description"]),
                    int(order["reward_stones"]),
                    str(order["starts_at"]),
                    str(order["expires_at"]),
                    snapshot,
                    status="expired",
                )
                self._record_operation(
                    connection,
                    operation_id,
                    operation_name,
                    int(provider["id"]),
                    request_hash,
                    payload,
                    now_text,
                )
                return self._order_from_payload(payload)
            publisher = connection.execute("SELECT * FROM players WHERE id = ?", (order["publisher_id"],)).fetchone()
            if publisher is None:
                raise PlayerNotFoundError("publisher does not exist")
            if str(publisher["status"]) != "active":
                raise ServiceRequirementError("publisher is not active")
            required_service_reputation = int(snapshot["required_service_reputation"])
            if required_service_reputation:
                current = player_reputation_state(connection, int(provider["id"])).service
                if current < required_service_reputation:
                    raise ServiceReputationInsufficientError("service reputation is insufficient")
            required_teaching_flag = snapshot["required_teaching_flag"]
            if required_teaching_flag:
                intro = json_object(provider["intro_json"], {})
                selected_service = str(intro.get("selected_service") or provider["selected_service"] or "")
                if (
                    str(required_teaching_flag) not in {str(item) for item in intro.get("flags", [])}
                    or (
                        snapshot["required_teaching_service"] is not None
                        and selected_service != str(snapshot["required_teaching_service"])
                    )
                ):
                    raise ServiceRequirementError("cooking teaching is required")
            if bool(snapshot["requires_same_location"]) and provider["location_key"] != publisher["location_key"]:
                raise ServiceLocationConflictError("service participants are not at the same location")
            self._check_provider_daily_limit(
                connection,
                provider["id"],
                str(order["service_key"]),
                int(snapshot["daily_limit"]),
                now,
            )
            inputs = dict(snapshot["provider_inputs"])
            provider_stamina = int(snapshot["provider_stamina"])
            provider_energy = int(snapshot["provider_energy"])
            missing = player_requirements_missing(
                provider,
                assets=inputs,
                values={
                    "stamina": provider_stamina,
                    "energy": provider_energy,
                },
            )
            if missing:
                raise ResourceInsufficientError("service resources are insufficient")
            spend_player_state(
                connection,
                provider,
                inputs,
                now_text,
                value_delta={
                    "stamina": -provider_stamina,
                    "energy": -provider_energy,
                },
            )
            connection.execute(
                "UPDATE livelihood_service_orders SET provider_id = ?, accept_operation_id = ?, status = 'accepted', accepted_at = ?, updated_at = ? WHERE id = ? AND status = 'published'",
                (provider["id"], operation_id, now_text, now_text, order["id"]),
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (provider["id"],)).fetchone()
            if updated is None:
                raise RuntimeError("service acceptance returned no provider")
            payload = self._order_payload(
                updated,
                str(order["order_id"]),
                str(order["service_key"]),
                str(snapshot["service_name"]),
                str(snapshot["service_description"]),
                int(order["reward_stones"]),
                str(order["starts_at"]),
                str(order["expires_at"]),
                snapshot,
                status="accepted",
            )
            self._record_operation(connection, operation_id, operation_name, provider["id"], request_hash, payload, now_text)
            return self._order_from_payload(payload)

    async def settle_service(
        self,
        *,
        platform: str,
        platform_user_id: str,
        order_id: str | None,
        operation_id: str,
    ) -> ServiceSettlementRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._settle_service_once,
                platform,
                platform_user_id,
                order_id,
                operation_id,
            )

    def _settle_service_once(
        self,
        platform: str,
        platform_user_id: str,
        order_id: str | None,
        operation_id: str,
    ) -> ServiceSettlementRecord:
        operation_name = "livelihood.settle_service"
        request_hash = self._request_hash(
            operation_name,
            {"platform": platform, "platform_user_id": platform_user_id, "order_id": order_id or ""},
        )
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._operation(connection, operation_id, operation_name, request_hash)
            if existing is not None:
                return self._settlement_from_payload(existing, replay=True)
            provider = self._require_player(connection, platform, platform_user_id)
            if order_id:
                order = connection.execute(
                    "SELECT * FROM livelihood_service_orders WHERE order_id = ? AND provider_id = ?",
                    (order_id, provider["id"]),
                ).fetchone()
            else:
                order = connection.execute(
                    "SELECT * FROM livelihood_service_orders WHERE provider_id = ? AND status = 'accepted' ORDER BY id DESC LIMIT 1",
                    (provider["id"],),
                ).fetchone()
            if order is None:
                raise ServiceNotFoundError("accepted service order does not exist")
            if str(order["status"]) in {"delivered", "failed", "expired"}:
                raise ServiceAlreadySettledError("service order has already settled")
            if str(order["status"]) != "accepted":
                raise ServiceOrderConflictError("service order is not accepted")
            snapshot = self._service_snapshot_object(order["snapshot_json"])
            self._validate_snapshot_row(snapshot, order)
            publisher = connection.execute("SELECT * FROM players WHERE id = ?", (order["publisher_id"],)).fetchone()
            if publisher is None:
                raise PlayerNotFoundError("publisher does not exist")
            expired = now >= datetime.fromisoformat(str(order["expires_at"]))
            same_location = provider["location_key"] == publisher["location_key"]
            successful = not expired and (same_location or not bool(snapshot["requires_same_location"]))
            if successful:
                outputs_requested = dict(snapshot["publisher_outputs"])
                provider_payment = (int(order["reward_stones"]) * 9800) // 10000
                publisher_refund = 0
                provider_actual = change_player_state_actual(
                    connection,
                    provider,
                    updated_at=now_text,
                    asset_values={"spirit_stones": provider_payment},
                    asset_mode="grant",
                )
                publisher_actual = change_player_state_actual(
                    connection,
                    publisher,
                    updated_at=now_text,
                    asset_values=outputs_requested,
                    asset_mode="grant",
                )
                provider_payment = provider_actual.get("spirit_stones", 0)
                outputs = {
                    key: amount for key, amount in publisher_actual.items() if key.startswith("item.")
                }
                status = "delivered"
                provider_refunds: dict[str, int] = {}
                stamina_refund = 0
            else:
                outputs = {}
                provider_payment = 0
                publisher_refund = (int(order["reward_stones"]) * 8000) // 10000
                provider_refunds_requested = (
                    dict(snapshot["provider_inputs"])
                    if expired
                    else dict(snapshot["failure_provider_refund"])
                )
                stamina_refund = (
                    int(snapshot.get("provider_stamina", 0))
                    if expired
                    else int(snapshot.get("failure_stamina_refund", 0))
                )
                publisher_actual = change_player_state_actual(
                    connection,
                    publisher,
                    updated_at=now_text,
                    asset_values={"spirit_stones": publisher_refund},
                    asset_mode="grant",
                )
                provider_actual = change_player_state_actual(
                    connection,
                    provider,
                    updated_at=now_text,
                    asset_values=provider_refunds_requested,
                    asset_mode="grant",
                    value_delta={
                        "stamina": stamina_refund,
                        "energy": int(snapshot.get("provider_energy", 0)) if expired else 0,
                    },
                )
                publisher_refund = publisher_actual.get("spirit_stones", 0)
                provider_refunds = {
                    key: amount for key, amount in provider_actual.items() if key.startswith("item.")
                }
                stamina_refund = provider_actual.get("stamina", 0)
                status = "expired" if expired else "failed"
            result = {
                "status": status,
                "outputs": outputs,
                "provider_payment": provider_payment,
                "publisher_refund": publisher_refund,
                "platform_fee": int(order["reward_stones"]) - provider_payment - publisher_refund,
                "provider_refunds": provider_refunds,
                "stamina_refund": stamina_refund,
                "settled_at": now_text,
            }
            connection.execute(
                "UPDATE livelihood_service_orders SET settle_operation_id = ?, status = ?, settled_at = ?, result_json = ?, updated_at = ? WHERE id = ? AND status = 'accepted'",
                (operation_id, status, now_text, json.dumps(result, ensure_ascii=False, sort_keys=True), now_text, order["id"]),
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (provider["id"],)).fetchone()
            if updated is None:
                raise RuntimeError("service settlement returned no provider")
            payload = {
                "player": self._player_payload(self._row_to_player(updated)),
                "order_id": str(order["order_id"]),
                "service_key": str(order["service_key"]),
                "service_name": str(snapshot.get("service_name", order["service_key"])),
                "service_description": str(snapshot["service_description"]),
                "status": status,
                "reward_stones": int(order["reward_stones"]),
                **result,
            }
            self._record_operation(connection, operation_id, operation_name, provider["id"], request_hash, payload, now_text)
            return self._settlement_from_payload(payload)

    @staticmethod
    def _check_provider_daily_limit(
        connection: Any,
        provider_id: int,
        service_key: str,
        daily_limit: int,
        now: datetime,
    ) -> None:
        day_start = serialize_datetime(now.replace(hour=0, minute=0, second=0, microsecond=0))
        day_end = serialize_datetime(now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1))
        row = connection.execute(
            "SELECT COUNT(*) AS count FROM livelihood_service_orders WHERE provider_id = ? AND service_key = ? AND accepted_at >= ? AND accepted_at < ?",
            (provider_id, service_key, day_start, day_end),
        ).fetchone()
        if row is not None and int(row["count"]) >= daily_limit:
            raise ServiceDailyLimitError("service daily limit reached")

    @staticmethod
    def _service_snapshot(definition: ServiceDefinition, reward: int, publisher: Any, starts_at: str, expires_at: str) -> dict[str, Any]:
        return {
            "service_name": definition.label,
            "service_description": definition.description,
            "provider_stamina": definition.provider_stamina,
            "provider_energy": definition.provider_energy,
            "provider_inputs": dict(definition.provider_inputs or {}),
            "publisher_outputs": dict(definition.publisher_outputs or {}),
            "failure_provider_refund": dict(definition.failure_provider_refund or {}),
            "failure_stamina_refund": definition.failure_stamina_refund,
            "required_service_reputation": definition.required_service_reputation,
            "required_teaching_flag": definition.required_teaching_flag,
            "required_teaching_service": definition.required_teaching_service,
            "daily_limit": definition.daily_limit,
            "requires_same_location": definition.requires_same_location,
            "reward_stones": reward,
            "reward_locked": True,
            "publisher_location": str(publisher["location_key"]),
            "starts_at": starts_at,
            "expires_at": expires_at,
        }

    @staticmethod
    def _service_snapshot_object(value: Any) -> dict[str, Any]:
        """Decode one service snapshot without silently accepting old shapes."""

        try:
            snapshot = json.loads(value) if isinstance(value, str) else value
        except (TypeError, ValueError) as exc:
            raise ServiceOrderConflictError("service snapshot is invalid") from exc
        if not isinstance(snapshot, dict):
            raise ServiceOrderConflictError("service snapshot is invalid")
        expected = {
            "service_name",
            "service_description",
            "provider_stamina",
            "provider_energy",
            "provider_inputs",
            "publisher_outputs",
            "failure_provider_refund",
            "failure_stamina_refund",
            "required_service_reputation",
            "required_teaching_flag",
            "required_teaching_service",
            "daily_limit",
            "requires_same_location",
            "reward_stones",
            "reward_locked",
            "publisher_location",
            "starts_at",
            "expires_at",
        }
        if set(snapshot) != expected:
            raise ServiceOrderConflictError("service snapshot is incomplete")

        def non_negative_int(key: str) -> int:
            item = snapshot[key]
            if isinstance(item, bool) or not isinstance(item, int) or item < 0:
                raise ServiceOrderConflictError("service snapshot has invalid numeric data")
            return item

        for key in (
            "provider_stamina",
            "provider_energy",
            "failure_stamina_refund",
            "required_service_reputation",
        ):
            non_negative_int(key)
        for key in ("daily_limit", "reward_stones"):
            item = snapshot[key]
            if isinstance(item, bool) or not isinstance(item, int) or item <= 0:
                raise ServiceOrderConflictError("service snapshot has invalid numeric data")
        for key in ("service_name", "service_description", "publisher_location", "starts_at", "expires_at"):
            if not isinstance(snapshot[key], str) or not snapshot[key].strip():
                raise ServiceOrderConflictError("service snapshot has invalid text data")
        try:
            starts_at = datetime.fromisoformat(snapshot["starts_at"])
            expires_at = datetime.fromisoformat(snapshot["expires_at"])
        except ValueError as exc:
            raise ServiceOrderConflictError("service snapshot has invalid timestamps") from exc
        if expires_at <= starts_at:
            raise ServiceOrderConflictError("service snapshot has invalid duration")
        for key in ("provider_inputs", "publisher_outputs", "failure_provider_refund"):
            assets = snapshot[key]
            if not isinstance(assets, dict):
                raise ServiceOrderConflictError("service snapshot has invalid asset data")
            for item_key, amount in assets.items():
                if (
                    not isinstance(item_key, str)
                    or not item_key.startswith("item.")
                    or isinstance(amount, bool)
                    or not isinstance(amount, int)
                    or amount <= 0
                ):
                    raise ServiceOrderConflictError("service snapshot has invalid asset data")
        if not isinstance(snapshot["reward_locked"], bool) or not snapshot["reward_locked"]:
            raise ServiceOrderConflictError("service snapshot reward is not locked")
        if not isinstance(snapshot["requires_same_location"], bool):
            raise ServiceOrderConflictError("service snapshot has invalid location rule")
        for key in ("required_teaching_flag", "required_teaching_service"):
            item = snapshot[key]
            if item is not None and (not isinstance(item, str) or not item.strip()):
                raise ServiceOrderConflictError("service snapshot has invalid teaching rule")
        return {
            **snapshot,
            "provider_inputs": dict(snapshot["provider_inputs"]),
            "publisher_outputs": dict(snapshot["publisher_outputs"]),
            "failure_provider_refund": dict(snapshot["failure_provider_refund"]),
        }

    @staticmethod
    def _validate_snapshot_row(snapshot: dict[str, Any], order: Any) -> None:
        if (
            int(snapshot["reward_stones"]) != int(order["reward_stones"])
            or str(snapshot["starts_at"]) != str(order["starts_at"])
            or str(snapshot["expires_at"]) != str(order["expires_at"])
        ):
            raise ServiceOrderConflictError("service snapshot does not match the order")

    def _order_payload(
        self,
        player: Any,
        order_id: str,
        service_key: str,
        service_name: str,
        service_description: str,
        reward: int,
        starts_at: str,
        expires_at: str,
        snapshot: dict[str, Any],
        *,
        status: str,
    ) -> dict[str, Any]:
        return {
            "player": self._player_payload(self._row_to_player(player)),
            "order_id": order_id,
            "service_key": service_key,
            "service_name": service_name,
            "service_description": service_description,
            "status": status,
            "reward_stones": reward,
            "starts_at": starts_at,
            "expires_at": expires_at,
            "publisher_outputs": dict(snapshot.get("publisher_outputs", {})),
        }

    def _order_from_payload(self, payload: dict[str, Any], *, replay: bool = False) -> ServiceOrderRecord:
        return ServiceOrderRecord(
            player=self._row_to_player(payload["player"]),
            order_id=str(payload["order_id"]),
            service_key=str(payload["service_key"]),
            service_name=str(payload["service_name"]),
            service_description=str(payload["service_description"]),
            status=str(payload["status"]),
            reward_stones=int(payload["reward_stones"]),
            starts_at=str(payload["starts_at"]),
            expires_at=str(payload["expires_at"]),
            publisher_outputs={str(key): int(value) for key, value in dict(payload.get("publisher_outputs", {})).items()},
            already_completed=replay,
        )

    def _settlement_from_payload(self, payload: dict[str, Any], *, replay: bool = False) -> ServiceSettlementRecord:
        return ServiceSettlementRecord(
            player=self._row_to_player(payload["player"]),
            order_id=str(payload["order_id"]),
            service_key=str(payload["service_key"]),
            service_name=str(payload["service_name"]),
            service_description=str(payload["service_description"]),
            status=str(payload["status"]),
            reward_stones=int(payload["reward_stones"]),
            provider_payment=int(payload.get("provider_payment", 0)),
            publisher_refund=int(payload.get("publisher_refund", 0)),
            platform_fee=int(payload.get("platform_fee", 0)),
            outputs={str(key): int(value) for key, value in dict(payload.get("outputs", {})).items()},
            provider_refunds={str(key): int(value) for key, value in dict(payload.get("provider_refunds", {})).items()},
            stamina_refund=int(payload.get("stamina_refund", 0)),
            already_completed=replay,
        )

    @staticmethod
    def _operation(connection: Any, operation_id: str, operation_name: str, request_hash: str) -> dict[str, Any] | None:
        existing = connection.execute(
            "SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id = ?", (operation_id,)
        ).fetchone()
        if existing is None:
            return None
        if existing["operation_name"] != operation_name or existing["request_hash"] != request_hash:
            raise OperationConflictError("operation input differs from its original request")
        return json.loads(existing["result_json"])

    @staticmethod
    def _record_operation(connection: Any, operation_id: str, operation_name: str, player_id: int, request_hash: str, payload: dict[str, Any], now_text: str) -> None:
        connection.execute(
            "INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (operation_id, operation_name, player_id, request_hash, json.dumps(payload, ensure_ascii=False, sort_keys=True), now_text),
        )

__all__ = ["ServiceRepositoryMixin"]
