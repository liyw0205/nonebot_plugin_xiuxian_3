"""SQLite transactions for fixed cross-realm trades."""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from typing import Any
from uuid import uuid4

from ...contracts import serialize_datetime
from ..persistence.errors import (
    CrossRealmTradeCurrencyInsufficientError,
    CrossRealmTradeInputInsufficientError,
    CrossRealmTradePermissionDeniedError,
    OperationConflictError,
    PlayerNotFoundError,
    TradeWeeklyCapError,
)
from .cross_realm_trade_models import CrossRealmTradeRecord
from .cross_realm_trade_rules import trade_definition, week_start


class CrossRealmTradeRepositoryMixin:
    async def execute_cross_realm_trade(
        self,
        *,
        platform: str,
        platform_user_id: str,
        trade_key: str,
        operation_id: str,
    ) -> CrossRealmTradeRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._execute_cross_realm_trade_once,
                platform,
                platform_user_id,
                trade_key,
                operation_id,
            )

    def _execute_cross_realm_trade_once(
        self,
        platform: str,
        platform_user_id: str,
        trade_key: str,
        operation_id: str,
    ) -> CrossRealmTradeRecord:
        definition = trade_definition(trade_key)
        operation_name = "economy.cross_realm_trade"
        request_payload = {
            "platform": platform,
            "platform_user_id": platform_user_id,
            "trade_key": trade_key,
        }
        request_hash = self._request_hash(operation_name, request_payload)
        now = self._now()
        now_text = serialize_datetime(now)
        current_week = week_start(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            if existing is not None:
                if existing["operation_name"] != operation_name or existing["request_hash"] != request_hash:
                    raise OperationConflictError("operation input differs from its original request")
                return self._cross_realm_trade_from_payload(json.loads(existing["result_json"]), replay=True)

            player = self._require_player(connection, platform, platform_user_id)
            if str(player["location_key"]) != definition.location_key:
                raise CrossRealmTradePermissionDeniedError("trade must start at the demon abyss market")
            reputation = self._json_object(player["faction_reputation_json"], {})
            if int(reputation.get("demon", 0)) < 200:
                raise CrossRealmTradePermissionDeniedError("demon trade reputation permission is missing")
            weekly_count = connection.execute(
                """
                SELECT COUNT(*) AS count FROM cross_realm_trades
                WHERE player_id = ? AND trade_key = ? AND week_start = ? AND status = 'completed'
                """,
                (player["id"], trade_key, current_week),
            ).fetchone()
            if int(weekly_count["count"] if weekly_count else 0) >= definition.weekly_limit:
                raise TradeWeeklyCapError("cross-realm trade weekly cap is reached")

            inventory = self._json_object(player["inventory_json"], {})
            for item_key, quantity in definition.input_items.items():
                if int(inventory.get(item_key, 0)) < quantity:
                    raise CrossRealmTradeInputInsufficientError(f"missing trade input: {item_key}")
            if int(player["spirit_stones"]) < definition.currency_cost:
                raise CrossRealmTradeCurrencyInsufficientError("trade currency is insufficient")

            input_before = {key: int(inventory.get(key, 0)) for key in definition.input_items}
            for item_key, quantity in definition.input_items.items():
                remaining = input_before[item_key] - quantity
                if remaining:
                    inventory[item_key] = remaining
                else:
                    inventory.pop(item_key, None)
            output_before = {key: int(inventory.get(key, 0)) for key in definition.output_items}
            for item_key, quantity in definition.output_items.items():
                inventory[item_key] = output_before[item_key] + quantity
            binding_expires_at = serialize_datetime(now + timedelta(seconds=definition.binding_seconds))
            trade_id = f"trade-{uuid4().hex}"
            snapshot = {
                "content_version": definition.content_version,
                "currency_cost": definition.currency_cost,
                "input_items": definition.input_items,
                "location_key": definition.location_key,
                "output_items": definition.output_items,
                "rule_version": definition.rule_version,
                "trade_key": definition.key,
                "weekly_limit": definition.weekly_limit,
                "week_start": current_week,
                "demon_reputation": int(reputation.get("demon", 0)),
            }
            connection.execute(
                """
                UPDATE players
                SET inventory_json = ?, spirit_stones = spirit_stones - ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    json.dumps(inventory, ensure_ascii=False, sort_keys=True),
                    definition.currency_cost,
                    now_text,
                    player["id"],
                ),
            )
            connection.execute(
                """
                INSERT INTO cross_realm_trades(
                    trade_id, player_id, trade_key, week_start, location_key, status,
                    input_json, currency_cost, output_json, binding_expires_at,
                    snapshot_json, operation_id, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'completed', ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trade_id,
                    player["id"],
                    trade_key,
                    current_week,
                    definition.location_key,
                    json.dumps(definition.input_items, ensure_ascii=False, sort_keys=True),
                    definition.currency_cost,
                    json.dumps(definition.output_items, ensure_ascii=False, sort_keys=True),
                    binding_expires_at,
                    json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
                    operation_id,
                    now_text,
                    now_text,
                ),
            )
            for item_key, quantity in definition.output_items.items():
                connection.execute(
                    """
                    INSERT INTO item_bindings(
                        binding_id, player_id, item_key, quantity, bound_until,
                        source_trade_id, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (uuid4().hex, player["id"], item_key, quantity, binding_expires_at, trade_id, now_text, now_text),
                )
            for item_key, quantity in definition.input_items.items():
                self._cross_realm_ledger(
                    connection,
                    operation_id,
                    int(player["id"]),
                    "item",
                    item_key,
                    "cross_realm_trade.input",
                    "debit",
                    quantity,
                    input_before[item_key],
                    input_before[item_key] - quantity,
                    trade_id,
                    now_text,
                )
            self._cross_realm_ledger(
                connection,
                operation_id,
                int(player["id"]),
                "currency",
                "currency.spirit_stone",
                "cross_realm_trade.input",
                "debit",
                definition.currency_cost,
                int(player["spirit_stones"]),
                int(player["spirit_stones"]) - definition.currency_cost,
                trade_id,
                now_text,
            )
            for item_key, quantity in definition.output_items.items():
                self._cross_realm_ledger(
                    connection,
                    operation_id,
                    int(player["id"]),
                    "item",
                    item_key,
                    "cross_realm_trade.output",
                    "credit",
                    quantity,
                    output_before[item_key],
                    output_before[item_key] + quantity,
                    trade_id,
                    now_text,
                )
            payload = {
                "trade_id": trade_id,
                "trade_key": trade_key,
                "status": "completed",
                "week_start": current_week,
                "location_key": definition.location_key,
                "input_items": definition.input_items,
                "currency_cost": definition.currency_cost,
                "output_items": definition.output_items,
                "binding_expires_at": binding_expires_at,
                "content_version": definition.content_version,
                "rule_version": definition.rule_version,
            }
            connection.execute(
                "INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    operation_id,
                    operation_name,
                    player["id"],
                    request_hash,
                    json.dumps(payload, ensure_ascii=False, sort_keys=True),
                    now_text,
                ),
            )
            return self._cross_realm_trade_from_payload(payload)

    @staticmethod
    def _cross_realm_ledger(
        connection: Any,
        operation_id: str,
        player_id: int,
        asset_kind: str,
        asset_key: str,
        reason: str,
        direction: str,
        amount: int,
        before_value: int,
        after_value: int,
        source_id: str,
        created_at: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO economy_ledger_entries(
                operation_id, player_id, asset_kind, asset_key, reason, direction,
                amount, before_value, after_value, source_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                operation_id,
                player_id,
                asset_kind,
                asset_key,
                reason,
                direction,
                amount,
                before_value,
                after_value,
                source_id,
                created_at,
            ),
        )

    @staticmethod
    def _cross_realm_trade_from_payload(payload: dict[str, Any], replay: bool = False) -> CrossRealmTradeRecord:
        return CrossRealmTradeRecord(
            trade_id=str(payload["trade_id"]),
            trade_key=str(payload["trade_key"]),
            status=str(payload["status"]),
            week_start=str(payload["week_start"]),
            location_key=str(payload["location_key"]),
            input_items={str(key): int(value) for key, value in dict(payload.get("input_items", {})).items()},
            currency_cost=int(payload["currency_cost"]),
            output_items={str(key): int(value) for key, value in dict(payload.get("output_items", {})).items()},
            binding_expires_at=str(payload["binding_expires_at"]),
            content_version=str(payload["content_version"]),
            rule_version=str(payload["rule_version"]),
            already_completed=replay,
        )


__all__ = ["CrossRealmTradeRepositoryMixin"]
