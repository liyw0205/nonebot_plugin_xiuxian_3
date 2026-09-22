"""SQLite transactions for the v0.1 town commission loop."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from ...contracts import serialize_datetime
from ..persistence.errors import (
    CommissionAlreadyAcceptedError,
    CommissionAlreadyDeliveredError,
    CommissionExpiredError,
    CommissionMaterialInsufficientError,
    CommissionNotAcceptedError,
    CommissionNotFoundError,
    CommissionQuotaError,
    CommissionStockExhaustedError,
    OperationConflictError,
)
from .models import TownCommissionRecord, TownCommissionView
from .rules import TownCommissionDefinition, commission_definition, TOWN_COMMISSION_DEFINITIONS


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
            return tuple(self._commission_view(row) for row in rows)

    async def accept_commission(
        self,
        *,
        platform: str,
        platform_user_id: str,
        commission_key: str,
        operation_id: str,
    ) -> TownCommissionRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._accept_commission_once,
                platform,
                platform_user_id,
                commission_key,
                operation_id,
            )

    def _accept_commission_once(
        self,
        platform: str,
        platform_user_id: str,
        commission_key: str,
        operation_id: str,
    ) -> TownCommissionRecord:
        try:
            definition = commission_definition(commission_key)
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
                "commission_key": definition.key,
                "business_date": business_date,
            },
        )
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._operation(connection, operation_id, operation_name, request_hash)
            if existing is not None:
                return self._record_from_payload(existing, replay=True)
            player = self._require_player(connection, platform, platform_user_id)
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
    ) -> TownCommissionRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._deliver_commission_once,
                platform,
                platform_user_id,
                commission_key,
                operation_id,
            )

    def _deliver_commission_once(
        self,
        platform: str,
        platform_user_id: str,
        commission_key: str | None,
        operation_id: str,
    ) -> TownCommissionRecord:
        normalized_key = ""
        if commission_key:
            try:
                normalized_key = commission_definition(commission_key).key
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
            snapshot = self._json_object(claim["snapshot_json"], {})
            inventory = self._json_object(player["inventory_json"], {})
            inputs = {str(key): int(value) for key, value in dict(snapshot.get("inputs", {})).items()}
            missing = {
                key: quantity - int(inventory.get(key, 0))
                for key, quantity in inputs.items()
                if int(inventory.get(key, 0)) < quantity
            }
            if missing:
                raise CommissionMaterialInsufficientError("commission materials are insufficient")
            for item_key, quantity in inputs.items():
                inventory[item_key] = int(inventory.get(item_key, 0)) - quantity
            reward_stones = int(snapshot.get("reward_stones", 0))
            local_delta = int(snapshot.get("local_reputation", 0))
            service_delta = int(snapshot.get("service_reputation", 0))
            reputation = connection.execute(
                "SELECT local_json, service_reputation FROM player_reputations WHERE player_id = ?",
                (player["id"],),
            ).fetchone()
            local = self._json_object(reputation["local_json"], {}) if reputation is not None else {}
            service_before = int(reputation["service_reputation"]) if reputation is not None else 0
            local_key = "local.xuantian.new_town"
            local_before = int(local.get(local_key, 0))
            local_after = min(1000, local_before + local_delta)
            service_after = min(100, service_before + service_delta)
            local[local_key] = local_after
            connection.execute(
                "UPDATE players SET spirit_stones = spirit_stones + ?, inventory_json = ?, updated_at = ? WHERE id = ?",
                (reward_stones, json.dumps(inventory, ensure_ascii=False, sort_keys=True), now_text, player["id"]),
            )
            connection.execute(
                """
                INSERT INTO player_reputations(player_id, local_json, service_reputation, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(player_id) DO UPDATE SET local_json = excluded.local_json,
                    service_reputation = excluded.service_reputation, updated_at = excluded.updated_at
                """,
                (player["id"], json.dumps(local, ensure_ascii=False, sort_keys=True), service_after, now_text),
            )
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
            )
            self._record_operation(connection, operation_id, operation_name, player["id"], request_hash, payload, now_text)
            return self._record_from_payload(payload)

    def _ensure_commissions(self, connection: Any, business_date: str, now: datetime) -> None:
        day_start = datetime(now.year, now.month, now.day, tzinfo=now.tzinfo)
        starts_at = serialize_datetime(day_start)
        for definition in TOWN_COMMISSION_DEFINITIONS.values():
            expires = day_start + timedelta(seconds=definition.duration_seconds)
            status = "published" if now < expires else "expired"
            commission_id = f"town.new_town.{business_date}.{definition.key.rsplit('.', 1)[-1]}"
            snapshot = {
                "label": definition.label,
                "inputs": definition.inputs,
                "reward_stones": definition.reward_stones,
                "local_reputation": definition.local_reputation,
                "service_reputation": definition.service_reputation,
                "content_version": definition.content_version,
                "rule_version": definition.rule_version,
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
                    definition.stock,
                    definition.stock,
                    starts_at,
                    serialize_datetime(expires),
                    json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
                    starts_at,
                    starts_at,
                ),
            )

    @staticmethod
    def _expire_commissions(connection: Any, business_date: str, now: datetime, now_text: str) -> None:
        connection.execute(
            "UPDATE town_commissions SET status = 'expired', updated_at = ? WHERE business_date = ? AND status = 'published' AND expires_at <= ?",
            (now_text, business_date, now_text),
        )

    @staticmethod
    def _snapshot(definition: TownCommissionDefinition, offer: Any, now_text: str) -> dict[str, Any]:
        snapshot = CommissionRepositoryMixin._json_object(offer["snapshot_json"], {})
        snapshot["commission_key"] = definition.key
        snapshot["accepted_at"] = now_text
        snapshot["expires_at"] = str(offer["expires_at"])
        return snapshot

    @staticmethod
    def _commission_view(row: Any) -> TownCommissionView:
        snapshot = CommissionRepositoryMixin._json_object(row["snapshot_json"], {})
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

    def _payload(self, player: Any, offer: Any, *, snapshot: dict[str, Any], status: str, claim_id: str, stock_remaining: int, result: dict[str, Any] | None = None) -> dict[str, Any]:
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
            "reward_stones": int(snapshot.get("reward_stones", 0)),
            "local_reputation": int(snapshot.get("local_reputation", 0)),
            "service_reputation": int(snapshot.get("service_reputation", 0)),
            "expires_at": str(offer["expires_at"]),
            "result": result or {},
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
            reward_stones=int(payload.get("reward_stones", 0)),
            local_reputation=int(payload.get("local_reputation", 0)),
            service_reputation=int(payload.get("service_reputation", 0)),
            expires_at=str(payload.get("expires_at", "")),
            already_completed=replay,
        )

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
        return json.loads(existing["result_json"])

    @staticmethod
    def _record_operation(connection: Any, operation_id: str, operation_name: str, player_id: int, request_hash: str, payload: dict[str, Any], now_text: str) -> None:
        connection.execute(
            "INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (operation_id, operation_name, player_id, request_hash, json.dumps(payload, ensure_ascii=False, sort_keys=True), now_text),
        )

    @staticmethod
    def _json_object(raw: Any, default: dict[str, Any] | None = None) -> dict[str, Any]:
        value = json.loads(raw) if isinstance(raw, str) else raw
        return dict(value) if isinstance(value, dict) else dict(default or {})


__all__ = ["CommissionRepositoryMixin"]
