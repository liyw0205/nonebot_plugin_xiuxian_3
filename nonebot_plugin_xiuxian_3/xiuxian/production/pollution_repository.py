"""Transactions for ordinary pollution purification."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from typing import Any

from ...contracts import serialize_datetime
from ..utils.assets import spend_player_assets
from ..utils.player import player_inventory, player_resource
from ..persistence.errors import (
    HeartDemonPendingError,
    MaterialInsufficientError,
    OperationConflictError,
    PollutionAlreadyClearError,
    SecretRealmBusyError,
)
from ..production.models import PollutionPurificationRecord


POLLUTION_PURIFICATION_ITEM = "item.pill.soul_restore"
POLLUTION_PURIFICATION_DELTA = 20


class PollutionRepositoryMixin:
    """Keep the normal pollution recovery transaction separate from orders."""

    async def purify_pollution(
        self,
        *,
        platform: str,
        platform_user_id: str,
        operation_id: str,
    ) -> PollutionPurificationRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._purify_pollution_sync,
                platform,
                platform_user_id,
                operation_id,
            )

    def _purify_pollution_sync(
        self,
        platform: str,
        platform_user_id: str,
        operation_id: str,
    ) -> PollutionPurificationRecord:
        operation_name = "production.purify_pollution"
        operation_payload = {
            "platform": platform,
            "platform_user_id": platform_user_id,
            "item_key": POLLUTION_PURIFICATION_ITEM,
            "pollution_delta": POLLUTION_PURIFICATION_DELTA,
        }
        request_hash = self._request_hash(operation_name, operation_payload)
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
                return self._pollution_purification_from_payload(
                    json.loads(existing["result_json"]), replay=True
                )

            row = self._require_player(connection, platform, platform_user_id)
            active_realm = connection.execute(
                "SELECT 1 FROM secret_realm_runs WHERE player_id=? "
                "AND status IN ('entered','routing','combat_pending','cleared','failed') LIMIT 1",
                (row["id"],),
            ).fetchone()
            if active_realm is not None:
                raise SecretRealmBusyError("pollution cannot change during a secret-realm run")
            pending = connection.execute(
                "SELECT 1 FROM heart_demon_sessions WHERE player_id = ? AND status = 'pending' LIMIT 1",
                (row["id"],),
            ).fetchone()
            if pending is not None:
                raise HeartDemonPendingError("heart demon must be resolved before pollution purification")

            pollution_before = player_resource(row, "pollution")
            if pollution_before <= 0:
                raise PollutionAlreadyClearError("pollution is already clear")
            inventory = player_inventory(row)
            quantity = int(inventory.get(POLLUTION_PURIFICATION_ITEM, 0))
            if quantity < 1:
                raise MaterialInsufficientError("soul restore pill is missing")

            pollution_after = max(0, pollution_before - POLLUTION_PURIFICATION_DELTA)
            spend_player_assets(
                connection,
                row,
                {POLLUTION_PURIFICATION_ITEM: 1},
                now_text,
                player_values={"pollution": pollution_after},
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO activity_events(
                    player_id, event_key, source_operation_id, occurred_at, payload_json
                ) VALUES (?, 'production.purify_pollution', ?, ?, ?)
                """,
                (
                    row["id"],
                    operation_id,
                    now_text,
                    json.dumps(
                        {
                            "pollution_before": pollution_before,
                            "pollution_after": pollution_after,
                            "item_key": POLLUTION_PURIFICATION_ITEM,
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                ),
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (row["id"],)).fetchone()
            if updated is None:
                raise RuntimeError("pollution purification returned no player")
            record = PollutionPurificationRecord(
                player=self._row_to_player(updated),
                item_key=POLLUTION_PURIFICATION_ITEM,
                pollution_before=pollution_before,
                pollution_after=pollution_after,
                pollution_reduced=pollution_before - pollution_after,
                item_quantity=quantity - 1,
            )
            payload = {
                "player": self._player_payload(record.player),
                "item_key": record.item_key,
                "pollution_before": record.pollution_before,
                "pollution_after": record.pollution_after,
                "pollution_reduced": record.pollution_reduced,
                "item_quantity": record.item_quantity,
            }
            connection.execute(
                """
                INSERT INTO operations(
                    operation_id, operation_name, player_id, request_hash, result_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    operation_id,
                    operation_name,
                    row["id"],
                    request_hash,
                    json.dumps(payload, ensure_ascii=False, sort_keys=True),
                    now_text,
                ),
            )
            return record

    def _pollution_purification_from_payload(
        self, payload: dict[str, Any], *, replay: bool
    ) -> PollutionPurificationRecord:
        return PollutionPurificationRecord(
            player=self._row_to_player(payload["player"]),
            item_key=str(payload["item_key"]),
            pollution_before=int(payload["pollution_before"]),
            pollution_after=int(payload["pollution_after"]),
            pollution_reduced=int(payload["pollution_reduced"]),
            item_quantity=int(payload["item_quantity"]),
            already_completed=replay,
        )


__all__ = [
    "POLLUTION_PURIFICATION_DELTA",
    "POLLUTION_PURIFICATION_ITEM",
    "PollutionRepositoryMixin",
]
