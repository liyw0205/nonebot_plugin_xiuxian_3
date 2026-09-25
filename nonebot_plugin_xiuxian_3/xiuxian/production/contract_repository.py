"""Persistence helpers for bound production outputs.

Contract outputs are player assets, but they are not market trades.  Keeping
their lifecycle in this mixin prevents the general production transaction from
turning into another cross-domain repository.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Any
from uuid import uuid4

from ...contracts import serialize_datetime
from ..persistence.errors import ContractSlotOccupiedError


class ContractProductionRepositoryMixin:
    """Own contract-slot checks and production binding rows."""

    @staticmethod
    def _expire_production_bindings(
        connection: sqlite3.Connection,
        *,
        player_id: int,
        now_text: str,
    ) -> None:
        connection.execute(
            """
            UPDATE production_item_bindings
            SET status = 'expired', updated_at = ?
            WHERE player_id = ? AND status = 'active' AND bound_until <= ?
            """,
            (now_text, player_id, now_text),
        )

    def _check_production_special_requirements(
        self,
        connection: sqlite3.Connection,
        row: sqlite3.Row,
        recipe: Any,
        now: datetime,
    ) -> None:
        binding_kind = getattr(recipe, "binding_kind", None)
        if not binding_kind or int(getattr(recipe, "binding_slot_limit", 0)) <= 0:
            return
        now_text = serialize_datetime(now)
        self._expire_production_bindings(connection, player_id=int(row["id"]), now_text=now_text)
        active = connection.execute(
            """
            SELECT COUNT(*) AS count
            FROM production_item_bindings
            WHERE player_id = ? AND binding_kind = ? AND status = 'active' AND bound_until > ?
            """,
            (row["id"], binding_kind, now_text),
        ).fetchone()
        if active is not None and int(active["count"]) >= int(recipe.binding_slot_limit):
            raise ContractSlotOccupiedError("the contract slot is occupied")

    def _persist_production_bindings(
        self,
        connection: sqlite3.Connection,
        *,
        player_id: int,
        order_id: str,
        operation_id: str,
        recipe: Any,
        outputs: dict[str, int],
        bound_until: str | None,
        snapshot: dict[str, Any],
        now_text: str,
    ) -> dict[str, str]:
        binding_kind = getattr(recipe, "binding_kind", None)
        if not binding_kind or not bound_until:
            return {}
        bindings: dict[str, str] = {}
        for item_key, quantity in outputs.items():
            if int(quantity) <= 0:
                continue
            connection.execute(
                """
                INSERT INTO production_item_bindings(
                    binding_id, player_id, item_key, quantity, binding_kind, status,
                    bound_until, source_order_id, source_operation_id, snapshot_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?)
                """,
                (
                    uuid4().hex,
                    player_id,
                    item_key,
                    int(quantity),
                    binding_kind,
                    bound_until,
                    order_id,
                    operation_id,
                    json.dumps(
                        {
                            "item_key": item_key,
                            "quantity": int(quantity),
                            "binding_kind": binding_kind,
                            "bound_until": bound_until,
                            "content_version": snapshot.get("content_version"),
                            "rule_version": snapshot.get("rule_version"),
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    now_text,
                    now_text,
                ),
            )
            bindings[item_key] = bound_until
        return bindings


__all__ = ["ContractProductionRepositoryMixin"]
