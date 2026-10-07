"""SQLite transactions for the town commission loop."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from ...contracts import serialize_datetime
from ..utils.assets import player_assets_missing
from ..utils.json_cache import decode_json_strict
from ..utils.player import change_player_state_actual, player_integer, player_reputation_state
from ..content import bundled_content
from ..rewards.rules import local_reputation_maximum
from ..persistence.errors import (
    CommissionAlreadyAcceptedError,
    CommissionAlreadyDeliveredError,
    CommissionExpiredError,
    CommissionMaterialInsufficientError,
    CommissionNotAcceptedError,
    CommissionNotFoundError,
    CommissionRequirementError,
    CommissionQuotaError,
    CommissionStockExhaustedError,
    OperationConflictError,
)
from .models import TownCommissionRecord, TownCommissionView
from .rules import (
    TownCommissionDefinition,
    commission_definition,
    resolve_commission_key,
    town_commission_definitions,
)


class CommissionRepositoryMixin:
    """Own daily town stock, player acceptance slots and delivery settlement."""

    async def list_commissions(self, *, platform: str, platform_user_id: str) -> tuple[TownCommissionView, ...]:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._list_commissions_sync, platform, platform_user_id)

    def _list_commissions_sync(self, platform: str, platform_user_id: str) -> tuple[TownCommissionView, ...]:
        now = self._now()
        now_text = serialize_datetime(now)
        business_date = now.date().isoformat()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            player = self._require_player(connection, platform, platform_user_id, writable=False)
            self._ensure_commissions(connection, business_date, now)
            self._expire_commissions(connection, business_date, now, now_text)
            rows = connection.execute(
                """
                SELECT c.*, cl.status AS claim_status
                FROM town_commissions c
                LEFT JOIN town_commission_claims cl
                  ON cl.commission_id = c.commission_id AND cl.player_id = ?
                WHERE c.business_date = ?
                ORDER BY c.id
                """,
                (player["id"], business_date),
            ).fetchall()
            definitions = town_commission_definitions(self.content)
            return tuple(
                self._commission_view(row)
                for row in rows
                if (definition := definitions.get(str(row["commission_key"]))) is not None
                and (
                    not definition.unlock_key
                    or self._has_codex_unlock(connection, int(player["id"]), definition.unlock_key)
                )
            )

    async def accept_commission(
        self,
        *,
        platform: str,
        platform_user_id: str,
        commission_key: str,
        operation_id: str,
        request_args: tuple[str, ...],
    ) -> TownCommissionRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._accept_commission_once,
                platform,
                platform_user_id,
                commission_key,
                operation_id,
                request_args,
            )

    async def replay_commission_accept(
        self,
        *,
        platform: str,
        platform_user_id: str,
        operation_id: str,
        request_args: tuple[str, ...],
    ) -> TownCommissionRecord | None:
        """Replay an acceptance before resolving its selector from current content."""

        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._replay_commission_once,
                platform,
                platform_user_id,
                operation_id,
                request_args,
                "livelihood.accept_commission",
                "accepted",
            )

    def _accept_commission_once(
        self,
        platform: str,
        platform_user_id: str,
        commission_key: str,
        operation_id: str,
        request_args: tuple[str, ...],
    ) -> TownCommissionRecord:
        request_args = self._coerce_request_args(request_args)
        if len(request_args) != 1 or not request_args[0].strip():
            raise ValueError("commission acceptance request shape is invalid")
        replay = self._replay_commission_once(
            platform,
            platform_user_id,
            operation_id,
            request_args,
            "livelihood.accept_commission",
            "accepted",
        )
        if replay is not None:
            return replay
        try:
            normalized_key = resolve_commission_key(commission_key, self.content)
        except ValueError as exc:
            raise CommissionNotFoundError("unsupported commission") from exc
        operation_name = "livelihood.accept_commission"
        now = self._now()
        now_text = serialize_datetime(now)
        business_date = now.date().isoformat()
        request_hash = self._request_hash(
            operation_name,
            {
                "platform": platform,
                "platform_user_id": platform_user_id,
                "commission_key": normalized_key,
            },
        )
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._operation(connection, operation_id, operation_name, request_hash)
            if existing is not None:
                self._validate_payload(existing, "accepted")
                if not self._commission_request_matches(existing, request_args, "accepted"):
                    raise OperationConflictError("operation input differs from its original request")
                return self._record_from_payload(existing, replay=True)
            try:
                definition = commission_definition(normalized_key, self.content)
            except ValueError as exc:
                raise CommissionNotFoundError("unsupported commission") from exc
            player = self._require_player(connection, platform, platform_user_id)
            if definition.unlock_key and not self._has_codex_unlock(
                connection, int(player["id"]), definition.unlock_key
            ):
                raise CommissionNotFoundError("codex milestone has not unlocked this commission")
            if not self._commission_requirements_met(connection, player, definition):
                raise CommissionRequirementError("commission prerequisites are not met")
            self._ensure_commissions(connection, business_date, now)
            self._expire_commissions(connection, business_date, now, now_text)
            offer = connection.execute(
                "SELECT * FROM town_commissions WHERE commission_key = ? AND business_date = ?",
                (definition.key, business_date),
            ).fetchone()
            if offer is None:
                raise CommissionNotFoundError("commission is not published")
            if str(offer["status"]) != "published" or now >= datetime.fromisoformat(str(offer["expires_at"])):
                raise CommissionExpiredError("commission has expired")
            prior = connection.execute(
                "SELECT status FROM town_commission_claims WHERE player_id = ? AND commission_id = ?",
                (player["id"], offer["commission_id"]),
            ).fetchone()
            if prior is not None and str(prior["status"]) in {"accepted", "delivered"}:
                raise CommissionAlreadyAcceptedError("commission already accepted")
            accepted_count = connection.execute(
                """
                SELECT COUNT(*) AS count FROM town_commission_claims
                WHERE player_id = ? AND business_date = ? AND status IN ('accepted', 'delivered')
                """,
                (player["id"], business_date),
            ).fetchone()
            if accepted_count is not None and int(accepted_count["count"]) >= 2:
                raise CommissionQuotaError("daily commission quota reached")
            updated = connection.execute(
                """
                UPDATE town_commissions
                SET stock_remaining = stock_remaining - 1, updated_at = ?
                WHERE commission_id = ? AND status = 'published' AND stock_remaining > 0
                """,
                (now_text, offer["commission_id"]),
            )
            if updated.rowcount != 1:
                raise CommissionStockExhaustedError("commission stock exhausted")
            claim_id = uuid4().hex
            snapshot = self._snapshot(definition, offer, now_text)
            connection.execute(
                """
                INSERT INTO town_commission_claims(
                    claim_id, commission_id, player_id, business_date, status,
                    accept_operation_id, accepted_at, snapshot_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'accepted', ?, ?, ?, ?, ?)
                """,
                (
                    claim_id,
                    offer["commission_id"],
                    player["id"],
                    business_date,
                    operation_id,
                    now_text,
                    json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
                    now_text,
                    now_text,
                ),
            )
            updated_player = connection.execute("SELECT * FROM players WHERE id = ?", (player["id"],)).fetchone()
            if updated_player is None:
                raise RuntimeError("commission acceptance returned no player")
            payload = self._payload(
                updated_player,
                offer,
                snapshot=snapshot,
                status="accepted",
                claim_id=claim_id,
                stock_remaining=int(offer["stock_remaining"]) - 1,
                request_args=request_args,
            )
            self._record_operation(connection, operation_id, operation_name, player["id"], request_hash, payload, now_text)
            return self._record_from_payload(payload)

    async def deliver_commission(
        self,
        *,
        platform: str,
        platform_user_id: str,
        commission_key: str | None,
        operation_id: str,
        request_args: tuple[str, ...],
    ) -> TownCommissionRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._deliver_commission_once,
                platform,
                platform_user_id,
                commission_key,
                operation_id,
                request_args,
            )

    async def replay_commission_deliver(
        self,
        *,
        platform: str,
        platform_user_id: str,
        operation_id: str,
        request_args: tuple[str, ...],
    ) -> TownCommissionRecord | None:
        """Replay a delivery before resolving its optional selector from current content."""

        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._replay_commission_once,
                platform,
                platform_user_id,
                operation_id,
                request_args,
                "livelihood.deliver_commission",
                "delivered",
            )

    def _deliver_commission_once(
        self,
        platform: str,
        platform_user_id: str,
        commission_key: str | None,
        operation_id: str,
        request_args: tuple[str, ...],
    ) -> TownCommissionRecord:
        request_args = self._coerce_request_args(request_args)
        if len(request_args) > 1 or any(not value.strip() for value in request_args):
            raise ValueError("commission delivery request shape is invalid")
        replay = self._replay_commission_once(
            platform,
            platform_user_id,
            operation_id,
            request_args,
            "livelihood.deliver_commission",
            "delivered",
        )
        if replay is not None:
            return replay
        normalized_key = ""
        if commission_key:
            try:
                normalized_key = resolve_commission_key(commission_key, self.content)
            except ValueError as exc:
                raise CommissionNotFoundError("unsupported commission") from exc
        operation_name = "livelihood.deliver_commission"
        now = self._now()
        now_text = serialize_datetime(now)
        request_hash = self._request_hash(
            operation_name,
            {"platform": platform, "platform_user_id": platform_user_id, "commission_key": normalized_key},
        )
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._operation(connection, operation_id, operation_name, request_hash)
            if existing is not None:
                self._validate_payload(existing, "delivered")
                if not self._commission_request_matches(existing, request_args, "delivered"):
                    raise OperationConflictError("operation input differs from its original request")
                return self._record_from_payload(existing, replay=True)
            player = self._require_player(connection, platform, platform_user_id)
            if normalized_key:
                claim = connection.execute(
                    """
                    SELECT cl.*, c.* FROM town_commission_claims cl
                    JOIN town_commissions c ON c.commission_id = cl.commission_id
                    WHERE cl.player_id = ? AND c.commission_key = ? ORDER BY cl.id DESC LIMIT 1
                    """,
                    (player["id"], normalized_key),
                ).fetchone()
            else:
                claim = connection.execute(
                    """
                    SELECT cl.*, c.* FROM town_commission_claims cl
                    JOIN town_commissions c ON c.commission_id = cl.commission_id
                    WHERE cl.player_id = ? AND cl.status = 'accepted' ORDER BY cl.id DESC LIMIT 1
                    """,
                    (player["id"],),
                ).fetchone()
            if claim is None:
                raise CommissionNotAcceptedError("no accepted commission")
            claim_status = str(claim["status"])
            if claim_status == "delivered":
                raise CommissionAlreadyDeliveredError("commission already delivered")
            if claim_status != "accepted":
                raise CommissionNotAcceptedError("commission is not accepted")
            if now >= datetime.fromisoformat(str(claim["expires_at"])):
                connection.execute(
                    "UPDATE town_commission_claims SET status = 'expired', updated_at = ? WHERE id = ? AND status = 'accepted'",
                    (now_text, claim["id"]),
                )
                raise CommissionExpiredError("commission has expired")
            snapshot = self._snapshot_object(claim["snapshot_json"])
            inputs = {str(key): int(value) for key, value in dict(snapshot.get("inputs", {})).items()}
            missing = player_assets_missing(player, inputs)
            if missing:
                raise CommissionMaterialInsufficientError("commission materials are insufficient")
            reward_stones = int(snapshot.get("reward_stones", 0))
            local_delta = int(snapshot.get("local_reputation", 0))
            service_delta = int(snapshot.get("service_reputation", 0))
            reputation_before = player_reputation_state(connection, int(player["id"]))
            local_key = str(snapshot["local_reputation_key"])
            local_before = reputation_before.local.get(local_key, 0)
            actual = change_player_state_actual(
                connection,
                player,
                updated_at=now_text,
                asset_values={
                    "spirit_stones": reward_stones,
                    **{str(key): -int(value) for key, value in inputs.items()},
                },
                local_reputation_delta={local_key: local_delta} if local_delta else None,
                service_reputation_delta=service_delta,
                local_reputation_maximums=(
                    {local_key: int(snapshot["local_reputation_maximum"])}
                    if local_delta
                    else None
                ),
            )
            local_after = local_before + actual.get(local_key, 0)
            service_before = reputation_before.service
            service_after = service_before + actual.get("service_reputation", 0)
            result = {
                "inputs": inputs,
                "reward_stones": reward_stones,
                "local_reputation_before": local_before,
                "local_reputation_after": local_after,
                "service_reputation_before": service_before,
                "service_reputation_after": service_after,
                "delivered_at": now_text,
            }
            connection.execute(
                """
                UPDATE town_commission_claims
                SET status = 'delivered', deliver_operation_id = ?, delivered_at = ?, result_json = ?, updated_at = ?
                WHERE id = ? AND status = 'accepted'
                """,
                (operation_id, now_text, json.dumps(result, ensure_ascii=False, sort_keys=True), now_text, claim["id"]),
            )
            updated_player = connection.execute("SELECT * FROM players WHERE id = ?", (player["id"],)).fetchone()
            if updated_player is None:
                raise RuntimeError("commission delivery returned no player")
            payload = self._payload(
                updated_player,
                claim,
                snapshot=snapshot,
                status="delivered",
                claim_id=str(claim["claim_id"]),
                stock_remaining=int(claim["stock_remaining"]),
                result=result,
                request_args=request_args,
            )
            self._record_operation(connection, operation_id, operation_name, player["id"], request_hash, payload, now_text)
            return self._record_from_payload(payload)

    def _ensure_commissions(self, connection: Any, business_date: str, now: datetime) -> None:
        day_start = datetime(now.year, now.month, now.day, tzinfo=now.tzinfo)
        starts_at = serialize_datetime(day_start)
        effects = self._public_project_effects(connection, now)
        for definition in town_commission_definitions(self.content).values():
            stock_multiplier = 120 if definition.stock_bonus_key in effects else 100
            reward_multiplier = 110 if definition.reward_bonus_key in effects else 100
            expires = day_start + timedelta(seconds=definition.duration_seconds)
            status = "published" if now < expires else "expired"
            commission_id = f"town.new_town.{business_date}.{definition.key.rsplit('.', 1)[-1]}"
            stock = definition.stock * stock_multiplier // 100
            reward_stones = definition.reward_stones * reward_multiplier // 100
            snapshot = {
                "commission_key": definition.key,
                "commission_references": [definition.key, definition.label, *definition.aliases],
                "label": definition.label,
                "inputs": definition.inputs,
                "input_labels": {
                    key: (self.content or bundled_content()).label("item", key)
                    for key in definition.inputs
                },
                "reward_stones": reward_stones,
                "local_reputation": definition.local_reputation,
                "local_reputation_key": definition.local_reputation_key,
                "local_reputation_maximum": local_reputation_maximum(
                    definition.local_reputation_key, self.content
                ),
                "service_reputation": definition.service_reputation,
            }
            connection.execute(
                """
                INSERT OR IGNORE INTO town_commissions(
                    commission_id, commission_key, business_date, status, stock_total,
                    stock_remaining, starts_at, expires_at, snapshot_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    commission_id,
                    definition.key,
                    business_date,
                    status,
                    stock,
                    stock,
                    starts_at,
                    serialize_datetime(expires),
                    json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
                    starts_at,
                    starts_at,
                ),
            )
            if stock_multiplier > 100 or reward_multiplier > 100:
                current = connection.execute(
                    "SELECT id, stock_total, stock_remaining, snapshot_json FROM town_commissions WHERE commission_id = ?",
                    (commission_id,),
                ).fetchone()
                if current is None:
                    continue
                additional_stock = max(0, stock - int(current["stock_total"]))
                current_snapshot = self._snapshot_object(current["snapshot_json"])
                if reward_multiplier > 100:
                    current_snapshot["reward_stones"] = reward_stones
                connection.execute(
                    """
                    UPDATE town_commissions
                    SET stock_total = ?, stock_remaining = stock_remaining + ?,
                        snapshot_json = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        max(int(current["stock_total"]), stock),
                        additional_stock,
                        json.dumps(current_snapshot, ensure_ascii=False, sort_keys=True),
                        serialize_datetime(now),
                        current["id"],
                    ),
                )

    @staticmethod
    def _expire_commissions(connection: Any, business_date: str, now: datetime, now_text: str) -> None:
        connection.execute(
            "UPDATE town_commissions SET status = 'expired', updated_at = ? WHERE business_date = ? AND status = 'published' AND expires_at <= ?",
            (now_text, business_date, now_text),
        )

    @staticmethod
    def _has_codex_unlock(connection: Any, player_id: int, unlock_key: str) -> bool:
        rows = connection.execute(
            "SELECT unlocks_json FROM codex_milestone_claims WHERE player_id = ?",
            (player_id,),
        ).fetchall()
        for row in rows:
            try:
                unlocks = json.loads(str(row["unlocks_json"]))
            except (TypeError, json.JSONDecodeError):
                continue
            if isinstance(unlocks, list) and unlock_key in unlocks:
                return True
        return False

    def _commission_requirements_met(
        self,
        connection: Any,
        player: Any,
        definition: TownCommissionDefinition,
    ) -> bool:
        if not definition.requirements_any:
            return True
        realm_order = {
            str(row["key"]): index
            for index, row in enumerate(
                (self.content or bundled_content()).list("realm", include_locked=False)
            )
        }
        local_reputation: dict[str, int] | None = None
        for requirement in definition.requirements_any:
            if requirement.get("type") == "realm":
                current_rank = realm_order.get(str(player["realm_key"]), -1)
                required_rank = realm_order.get(str(requirement["realm_key"]), -1)
                if (current_rank, player_integer(player, "realm_layer")) >= (
                    required_rank,
                    int(requirement["min_layer"]),
                ):
                    return True
            elif requirement.get("type") == "local_reputation":
                if local_reputation is None:
                    local_reputation = player_reputation_state(connection, int(player["id"])).local
                if local_reputation.get(str(requirement["reputation_key"]), 0) >= int(
                    requirement["minimum"]
                ):
                    return True
        return False

    @staticmethod
    def _snapshot(definition: TownCommissionDefinition, offer: Any, now_text: str) -> dict[str, Any]:
        snapshot = CommissionRepositoryMixin._snapshot_object(offer["snapshot_json"])
        snapshot["commission_key"] = definition.key
        snapshot["commission_references"] = [definition.key, definition.label, *definition.aliases]
        snapshot["accepted_at"] = now_text
        snapshot["expires_at"] = str(offer["expires_at"])
        CommissionRepositoryMixin._validated_snapshot(snapshot, claim=True)
        return snapshot

    @staticmethod
    def _commission_view(row: Any) -> TownCommissionView:
        snapshot = CommissionRepositoryMixin._snapshot_object(row["snapshot_json"])
        claim_status = str(row["claim_status"]) if row["claim_status"] else ""
        return TownCommissionView(
            commission_id=str(row["commission_id"]),
            commission_key=str(row["commission_key"]),
            label=str(snapshot.get("label", row["commission_key"])),
            business_date=str(row["business_date"]),
            status=str(row["status"]),
            stock_remaining=int(row["stock_remaining"]),
            stock_total=int(row["stock_total"]),
            inputs={str(key): int(value) for key, value in dict(snapshot.get("inputs", {})).items()},
            reward_stones=int(snapshot.get("reward_stones", 0)),
            local_reputation=int(snapshot.get("local_reputation", 0)),
            service_reputation=int(snapshot.get("service_reputation", 0)),
            expires_at=str(row["expires_at"]),
            accepted=claim_status in {"accepted", "delivered"},
            delivered=claim_status == "delivered",
        )

    @staticmethod
    def _snapshot_object(value: Any) -> dict[str, Any]:
        try:
            decoded = decode_json_strict(value) if isinstance(value, str) else value
        except (TypeError, ValueError) as exc:
            raise ValueError("commission snapshot is invalid JSON") from exc
        if not isinstance(decoded, dict):
            raise ValueError("commission snapshot must be an object")
        snapshot = dict(decoded)
        return CommissionRepositoryMixin._validated_snapshot(
            snapshot,
            claim={"accepted_at", "expires_at"}.issubset(snapshot),
        )

    @staticmethod
    def _validated_snapshot(snapshot: dict[str, Any], *, claim: bool = False) -> dict[str, Any]:
        """Validate a persisted commission snapshot before exposing or settling it."""

        base_fields = {
            "commission_key",
            "commission_references",
            "label",
            "inputs",
            "input_labels",
            "reward_stones",
            "local_reputation",
            "local_reputation_key",
            "local_reputation_maximum",
            "service_reputation",
        }
        required = base_fields | ({"accepted_at", "expires_at"} if claim else set())
        if set(snapshot) != required:
            raise ValueError("commission snapshot fields are incomplete")
        for key in ("commission_key", "label", "local_reputation_key"):
            if not isinstance(snapshot[key], str) or not snapshot[key].strip():
                raise ValueError("commission snapshot identity is invalid")
        references = snapshot["commission_references"]
        if (
            not isinstance(references, list)
            or not references
            or any(not isinstance(value, str) or not value.strip() for value in references)
            or snapshot["commission_key"] not in references
            or snapshot["label"] not in references
        ):
            raise ValueError("commission snapshot references are invalid")
        inputs = snapshot["inputs"]
        if (
            not isinstance(inputs, dict)
            or not inputs
            or any(
                not isinstance(key, str)
                or not key.startswith("item.")
                or isinstance(value, bool)
                or not isinstance(value, int)
                or value <= 0
                for key, value in inputs.items()
            )
        ):
            raise ValueError("commission snapshot inputs are invalid")
        input_labels = snapshot["input_labels"]
        if (
            not isinstance(input_labels, dict)
            or set(input_labels) != set(inputs)
            or any(
                not isinstance(key, str)
                or not isinstance(value, str)
                or not value.strip()
                for key, value in input_labels.items()
            )
        ):
            raise ValueError("commission snapshot input labels are invalid")
        for key, minimum in (
            ("reward_stones", 0),
            ("local_reputation", 0),
            ("service_reputation", 0),
            ("local_reputation_maximum", 1),
        ):
            value = snapshot[key]
            if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
                raise ValueError("commission snapshot numeric value is invalid")
        if not snapshot["local_reputation_key"].startswith("local."):
            raise ValueError("commission snapshot reputation key is invalid")
        if claim:
            for key in ("accepted_at", "expires_at"):
                try:
                    datetime.fromisoformat(snapshot[key])
                except (TypeError, ValueError) as exc:
                    raise ValueError("commission snapshot timestamp is invalid") from exc
        return snapshot

    def _payload(
        self,
        player: Any,
        offer: Any,
        *,
        snapshot: dict[str, Any],
        status: str,
        claim_id: str,
        stock_remaining: int,
        request_args: tuple[str, ...],
        result: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        result = result or {}
        local_reputation = int(snapshot["local_reputation"])
        service_reputation = int(snapshot["service_reputation"])
        if status == "delivered":
            local_reputation = result["local_reputation_after"] - result["local_reputation_before"]
            service_reputation = result["service_reputation_after"] - result["service_reputation_before"]
        return {
            "player": self._player_payload(self._row_to_player(player)),
            "claim_id": claim_id,
            "commission_id": str(offer["commission_id"]),
            "commission_key": str(offer["commission_key"]),
            "label": str(snapshot.get("label", offer["commission_key"])),
            "business_date": str(offer["business_date"]),
            "status": status,
            "stock_remaining": stock_remaining,
            "inputs": {str(key): int(value) for key, value in dict(snapshot.get("inputs", {})).items()},
            "input_labels": {str(key): str(value) for key, value in dict(snapshot["input_labels"]).items()},
            "reward_stones": int(snapshot.get("reward_stones", 0)),
            "local_reputation": local_reputation,
            "service_reputation": service_reputation,
            "expires_at": str(offer["expires_at"]),
            "request_args": list(request_args),
            "commission_references": list(snapshot["commission_references"]),
            "result": result,
        }

    def _record_from_payload(self, payload: dict[str, Any], *, replay: bool = False) -> TownCommissionRecord:
        return TownCommissionRecord(
            player=self._row_to_player(payload["player"]),
            claim_id=str(payload["claim_id"]),
            commission_id=str(payload["commission_id"]),
            commission_key=str(payload["commission_key"]),
            label=str(payload["label"]),
            business_date=str(payload["business_date"]),
            status=str(payload["status"]),
            stock_remaining=int(payload["stock_remaining"]),
            inputs={str(key): int(value) for key, value in dict(payload.get("inputs", {})).items()},
            input_labels={str(key): str(value) for key, value in dict(payload.get("input_labels", {})).items()},
            reward_stones=int(payload.get("reward_stones", 0)),
            local_reputation=int(payload.get("local_reputation", 0)),
            service_reputation=int(payload.get("service_reputation", 0)),
            expires_at=str(payload.get("expires_at", "")),
            already_completed=replay,
        )

    @staticmethod
    def _coerce_request_args(
        request_args: tuple[str, ...],
    ) -> tuple[str, ...]:
        if not isinstance(request_args, tuple) or any(not isinstance(value, str) for value in request_args):
            raise ValueError("commission request arguments must be strings")
        return request_args

    def _replay_commission_once(
        self,
        platform: str,
        platform_user_id: str,
        operation_id: str,
        request_args: tuple[str, ...],
        operation_name: str,
        status: str,
    ) -> TownCommissionRecord | None:
        request_args = self._coerce_request_args(request_args)
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT o.operation_name, o.player_id, o.request_hash, o.result_json,
                       p.player_id AS external_player_id, p.platform, p.platform_user_id
                FROM operations AS o
                JOIN players AS p ON p.id = o.player_id
                WHERE o.operation_id = ?
                """,
                (operation_id,),
            ).fetchone()
        if row is None:
            return None
        if (
            row["operation_name"] != operation_name
            or row["platform"] != platform
            or row["platform_user_id"] != platform_user_id
        ):
            raise OperationConflictError("operation input differs from its original request")
        try:
            payload = decode_json_strict(str(row["result_json"]))
        except (TypeError, ValueError) as exc:
            raise ValueError("commission operation snapshot is invalid") from exc
        if not isinstance(payload, dict):
            raise ValueError("commission operation snapshot must be an object")
        self._validate_payload(payload, status)
        player_payload = payload["player"]
        raw_player_id = player_payload.get("player_id")
        raw_id = player_payload.get("id")
        try:
            payload_player_id = str(raw_player_id)
            payload_id = str(raw_id)
        except (TypeError, ValueError):
            raise ValueError("commission operation player identity is invalid") from None
        if (
            isinstance(raw_player_id, bool)
            or isinstance(raw_id, bool)
            or not payload_player_id.strip()
            or payload_player_id != str(row["external_player_id"])
            or payload_id != payload_player_id
            or player_payload.get("platform") != platform
            or player_payload.get("platform_user_id") != platform_user_id
        ):
            raise ValueError("commission operation player identity is invalid")
        request_key = payload["commission_key"] if status == "accepted" or payload["request_args"] else ""
        expected_hash = self._request_hash(
            operation_name,
            {
                "platform": platform,
                "platform_user_id": platform_user_id,
                "commission_key": request_key,
            },
        )
        if row["request_hash"] != expected_hash:
            raise OperationConflictError("operation input differs from its original request")
        if not self._commission_request_matches(payload, request_args, status):
            raise OperationConflictError("operation input differs from its original request")
        try:
            return self._record_from_payload(payload, replay=True)
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            raise ValueError("commission operation snapshot is invalid") from exc

    @staticmethod
    def _commission_request_matches(
        payload: dict[str, Any],
        request_args: tuple[str, ...],
        status: str,
    ) -> bool:
        stored = payload["request_args"]
        if len(stored) != len(request_args):
            return False
        if status == "accepted" and len(stored) != 1:
            return False
        if status == "delivered" and len(stored) > 1:
            return False
        if not stored:
            return not request_args
        return request_args[0] in set(payload["commission_references"])

    @staticmethod
    def _validate_payload(payload: dict[str, Any], status: str) -> None:
        required = {
            "player",
            "claim_id",
            "commission_id",
            "commission_key",
            "label",
            "business_date",
            "status",
            "stock_remaining",
            "inputs",
            "input_labels",
            "reward_stones",
            "local_reputation",
            "service_reputation",
            "expires_at",
            "request_args",
            "commission_references",
            "result",
        }
        if set(payload) != required:
            raise ValueError("commission operation snapshot is incomplete")
        if not isinstance(payload["player"], dict):
            raise ValueError("commission operation player is invalid")
        for key in ("claim_id", "commission_id", "commission_key", "label", "business_date", "expires_at"):
            if not isinstance(payload[key], str) or not payload[key].strip():
                raise ValueError("commission operation identity is invalid")
        if payload["status"] != status:
            raise ValueError("commission operation status is invalid")
        for key, minimum in (
            ("stock_remaining", 0),
            ("reward_stones", 0),
            ("local_reputation", 0),
            ("service_reputation", 0),
        ):
            value = payload[key]
            if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
                raise ValueError("commission operation numeric value is invalid")
        inputs = payload["inputs"]
        if not isinstance(inputs, dict) or not inputs or any(
            not isinstance(key, str)
            or not key
            or isinstance(value, bool)
            or not isinstance(value, int)
            or value <= 0
            for key, value in inputs.items()
        ):
            raise ValueError("commission operation inputs are invalid")
        input_labels = payload["input_labels"]
        if (
            not isinstance(input_labels, dict)
            or set(input_labels) != set(inputs)
            or any(
                not isinstance(key, str)
                or not isinstance(value, str)
                or not value.strip()
                for key, value in input_labels.items()
            )
        ):
            raise ValueError("commission operation input labels are invalid")
        references = payload["commission_references"]
        if (
            not isinstance(references, list)
            or not references
            or any(not isinstance(value, str) or not value.strip() for value in references)
            or payload["commission_key"] not in references
            or payload["label"] not in references
        ):
            raise ValueError("commission operation references are invalid")
        request_args = payload["request_args"]
        if (
            not isinstance(request_args, list)
            or len(request_args) > 1
            or any(not isinstance(value, str) or not value.strip() for value in request_args)
            or status == "accepted" and len(request_args) != 1
            or request_args and request_args[0] not in references
        ):
            raise ValueError("commission operation request arguments are invalid")
        result = payload["result"]
        if not isinstance(result, dict):
            raise ValueError("commission operation result is invalid")
        if status == "accepted" and result:
            raise ValueError("commission acceptance result is invalid")
        if status == "delivered":
            result_required = {
                "inputs",
                "reward_stones",
                "local_reputation_before",
                "local_reputation_after",
                "service_reputation_before",
                "service_reputation_after",
                "delivered_at",
            }
            if set(result) != result_required:
                raise ValueError("commission delivery result is incomplete")
            if result["inputs"] != inputs or any(
                isinstance(result[key], bool) or not isinstance(result[key], int) or result[key] < 0
                for key in (
                    "reward_stones",
                    "local_reputation_before",
                    "local_reputation_after",
                    "service_reputation_before",
                    "service_reputation_after",
                )
            ):
                raise ValueError("commission delivery result is invalid")
            if (
                result["reward_stones"] != payload["reward_stones"]
                or result["local_reputation_after"] - result["local_reputation_before"]
                != payload["local_reputation"]
                or result["service_reputation_after"] - result["service_reputation_before"]
                != payload["service_reputation"]
            ):
                raise ValueError("commission delivery result is inconsistent")
            try:
                datetime.fromisoformat(result["delivered_at"])
            except (TypeError, ValueError) as exc:
                raise ValueError("commission delivery timestamp is invalid") from exc
        try:
            datetime.fromisoformat(payload["expires_at"])
        except ValueError as exc:
            raise ValueError("commission operation timestamp is invalid") from exc

    @staticmethod
    def _operation(connection: Any, operation_id: str, operation_name: str, request_hash: str) -> dict[str, Any] | None:
        existing = connection.execute(
            "SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id = ?",
            (operation_id,),
        ).fetchone()
        if existing is None:
            return None
        if existing["operation_name"] != operation_name or existing["request_hash"] != request_hash:
            raise OperationConflictError("operation input differs from its original request")
        try:
            payload = decode_json_strict(str(existing["result_json"]))
        except (TypeError, ValueError) as exc:
            raise ValueError("commission operation result is invalid") from exc
        if not isinstance(payload, dict):
            raise ValueError("commission operation result must be an object")
        return payload

    @staticmethod
    def _record_operation(connection: Any, operation_id: str, operation_name: str, player_id: int, request_hash: str, payload: dict[str, Any], now_text: str) -> None:
        connection.execute(
            "INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (operation_id, operation_name, player_id, request_hash, json.dumps(payload, ensure_ascii=False, sort_keys=True), now_text),
        )

__all__ = ["CommissionRepositoryMixin"]
