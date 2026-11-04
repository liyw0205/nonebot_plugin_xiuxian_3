"""SQLite transactions for the talent-tree reset (``talent.reset.standard``).

The v0.1 advancement contract registered ``talent.reset_tree`` but never froze
its cost or refund, so no command existed.  This first version keeps the
two-phase shape used by the path switch: a preview freezes the learned nodes,
the confirm spends spirit stones, snapshots those nodes into
``talent_reset_records``, deletes them and refunds their spent points.

Deleting the rows is deliberate: ``talent_node_states.status`` only accepts
``learned``, and the profile consumer treats every row as active.  The separate
history table is the audit trail, so the reset cannot be mistaken for "the
player never learned those tiers".
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from ...contracts import serialize_datetime
from ..content import ContentBundle, bundled_content
from ..persistence.errors import (
    OperationConflictError,
    PlayerNotFoundError,
    PlayerSuspendedError,
    RepositoryBusyError,
    ResourceInsufficientError,
    TalentResetBusyError,
    TalentResetCooldownError,
    TalentResetConflictError,
    TalentResetEmptyError,
    TalentResetNotFoundError,
    TalentResetPreviewExpiredError,
    TalentResetRequirementError,
    TalentResetStateError,
)
from ..utils.assets import player_currency
from ..utils.player import change_player_state, player_integer
from .reset_content import TalentResetDefinition, talent_reset_definition
from .reset_models import TalentResetPlanRecord, TalentResetResultRecord
from .talent_rules import tree_definition

_PREVIEW = "talent.preview_reset"
_CONFIRM = "talent.confirm_reset"
_CANCEL = "talent.cancel_reset"


class TalentResetRepositoryMixin:
    """Persistence for previewing, confirming and cancelling a talent reset."""

    def _reset_content(self) -> ContentBundle:
        content = getattr(self, "content", None)
        return content if content is not None else bundled_content()

    def _reset_definition(self) -> TalentResetDefinition:
        return talent_reset_definition(self._reset_content())

    def _reset_realm_ok(self, row: sqlite3.Row, definition: TalentResetDefinition) -> bool:
        ranks = {
            str(item["key"]): int(item.get("rank", -1))
            for item in self._reset_content().list("realm")
        }
        current = ranks.get(str(row["realm_key"]), -1)
        required = ranks.get(definition.min_realm, 99)
        return (current, player_integer(row, "realm_layer")) >= (
            required,
            definition.min_layer,
        )

    @staticmethod
    def _reset_nodes(connection: sqlite3.Connection, player_id: int, tree_key: str) -> list[dict[str, Any]]:
        rows = connection.execute(
            "SELECT node_key, tier, cost_points, unlocked_at FROM talent_node_states "
            "WHERE player_id = ? AND tree_key = ? ORDER BY tier, node_key",
            (player_id, tree_key),
        ).fetchall()
        return [
            {
                "node_key": str(row["node_key"]),
                "tier": int(row["tier"]),
                "cost_points": int(row["cost_points"]),
                "unlocked_at": str(row["unlocked_at"]),
            }
            for row in rows
        ]

    @staticmethod
    def _reset_refund(nodes: list[dict[str, Any]], definition: TalentResetDefinition) -> int:
        spent = sum(int(node["cost_points"]) for node in nodes)
        return spent * definition.refund_bp // 10_000

    @staticmethod
    def _reset_signature(nodes: list[dict[str, Any]]) -> list[tuple[str, int, int]]:
        return sorted(
            (str(node["node_key"]), int(node["tier"]), int(node["cost_points"]))
            for node in nodes
        )

    def _reset_plan_payload(self, payload: dict[str, Any], *, replay: bool = False) -> TalentResetPlanRecord:
        snapshot = dict(payload.get("snapshot") or {})
        return TalentResetPlanRecord(
            plan_id=str(payload["plan_id"]),
            status=str(payload["status"]),
            path_key=str(payload["path_key"]),
            path_label=str(payload["path_label"]),
            tree_key=str(payload["tree_key"]),
            tree_label=str(payload["tree_label"]),
            nodes=tuple(snapshot.get("nodes") or ()),
            refund_points=int(payload["refund_points"]),
            cost=dict(payload.get("cost") or {}),
            snapshot=snapshot,
            expires_at=str(payload["expires_at"]),
            already_completed=str(payload["status"]) != "pending",
            idempotent_replay=replay,
        )

    def _reset_result_payload(self, payload: dict[str, Any], *, replay: bool = False) -> TalentResetResultRecord:
        player_payload = payload.get("player")
        player = self._row_to_player(player_payload) if player_payload else None
        return TalentResetResultRecord(
            plan_id=str(payload["plan_id"]),
            path_key=str(payload["path_key"]),
            path_label=str(payload["path_label"]),
            tree_key=str(payload["tree_key"]),
            tree_label=str(payload["tree_label"]),
            nodes=tuple(payload.get("nodes") or ()),
            refund_points=int(payload["refund_points"]),
            spirit_stones_before=int(payload["spirit_stones_before"]),
            spirit_stones_after=int(payload["spirit_stones_after"]),
            talent_points_before=int(payload["talent_points_before"]),
            talent_points_after=int(payload["talent_points_after"]),
            player=player,
            already_completed=replay or bool(payload.get("already_completed", False)),
        )

    def _reset_cooldown_remaining(
        self, connection: sqlite3.Connection, player_id: int, definition: TalentResetDefinition
    ) -> int:
        row = connection.execute(
            "SELECT MAX(confirmed_at) AS last_confirmed FROM talent_reset_plans "
            "WHERE player_id = ? AND status = 'confirmed'",
            (player_id,),
        ).fetchone()
        value = row["last_confirmed"] if row is not None else None
        if not value:
            return 0
        elapsed = (self._now() - datetime.fromisoformat(str(value))).total_seconds()
        return max(0, int(definition.cooldown_seconds - elapsed))

    # -- preview --------------------------------------------------------

    async def preview_talent_reset(
        self, *, platform: str, platform_user_id: str, operation_id: str
    ) -> TalentResetPlanRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._preview_talent_reset_once, platform, platform_user_id, operation_id
            )

    def _preview_talent_reset_once(
        self, platform: str, platform_user_id: str, operation_id: str
    ) -> TalentResetPlanRecord:
        definition = self._reset_definition()
        request_hash = self._request_hash(
            _PREVIEW, {"platform": platform, "platform_user_id": platform_user_id}
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
                if existing["operation_name"] != _PREVIEW or existing["request_hash"] != request_hash:
                    raise OperationConflictError("operation input differs from its original request")
                return self._reset_plan_payload(json.loads(existing["result_json"]), replay=True)

            row = self._require_player(connection, platform, platform_user_id)
            if str(row["stage"]) != "cultivator" or not row["path_key"]:
                raise TalentResetRequirementError("talent reset requires a primary path")
            if not self._reset_realm_ok(row, definition):
                raise TalentResetRequirementError("talent reset requires a higher realm")
            tree_key, tree_label = tree_definition(str(row["path_key"]), self._reset_content())
            nodes = self._reset_nodes(connection, int(row["id"]), tree_key)
            if not nodes:
                raise TalentResetEmptyError("no learned talent nodes on this path")
            if self._has_active_long_action(connection, int(row["id"])):
                raise TalentResetBusyError("another long action is active")
            remaining = self._reset_cooldown_remaining(connection, int(row["id"]), definition)
            if remaining > 0:
                raise TalentResetCooldownError(remaining)

            connection.execute(
                "UPDATE talent_reset_plans SET status = 'expired', updated_at = ? "
                "WHERE player_id = ? AND status = 'pending'",
                (now_text, int(row["id"])),
            )
            refund = self._reset_refund(nodes, definition)
            expires_at = serialize_datetime(
                now + timedelta(seconds=definition.preview_ttl_seconds)
            )
            snapshot = {
                "path_key": str(row["path_key"]),
                "tree_key": tree_key,
                "tree_label": tree_label,
                "nodes": nodes,
                "refund_points": refund,
                "refund_bp": definition.refund_bp,
                "cooldown_seconds": definition.cooldown_seconds,
                "preview_ttl_seconds": definition.preview_ttl_seconds,
            }
            cost = {definition.currency_key: definition.spirit_stone_cost}
            plan_id = f"talent-reset-{uuid4().hex}"
            connection.execute(
                """
                INSERT INTO talent_reset_plans(
                    plan_id, player_id, preview_operation_id, path_key, tree_key,
                    status, cost_json, snapshot_json, expires_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?)
                """,
                (
                    plan_id,
                    int(row["id"]),
                    operation_id,
                    str(row["path_key"]),
                    tree_key,
                    json.dumps(cost, ensure_ascii=False, sort_keys=True),
                    json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
                    expires_at,
                    now_text,
                    now_text,
                ),
            )
            payload = {
                "plan_id": plan_id,
                "status": "pending",
                "path_key": str(row["path_key"]),
                "path_label": tree_label,
                "tree_key": tree_key,
                "tree_label": tree_label,
                "refund_points": refund,
                "cost": cost,
                "snapshot": snapshot,
                "expires_at": expires_at,
            }
            self._insert_operation(
                connection,
                operation_id=operation_id,
                operation_name=_PREVIEW,
                player_id=int(row["id"]),
                request_hash=request_hash,
                payload=payload,
                now_text=now_text,
            )
            return self._reset_plan_payload(payload)

    # -- confirm / cancel ----------------------------------------------

    async def confirm_talent_reset(
        self,
        *,
        platform: str,
        platform_user_id: str,
        plan_id: str | None,
        operation_id: str,
    ) -> TalentResetResultRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._confirm_talent_reset_once,
                platform,
                platform_user_id,
                plan_id,
                operation_id,
            )

    def _confirm_talent_reset_once(
        self,
        platform: str,
        platform_user_id: str,
        plan_id: str | None,
        operation_id: str,
    ) -> TalentResetResultRecord:
        definition = self._reset_definition()
        request_hash = self._request_hash(
            _CONFIRM,
            {"platform": platform, "platform_user_id": platform_user_id, "plan_id": plan_id},
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
                if existing["operation_name"] != _CONFIRM or existing["request_hash"] != request_hash:
                    raise OperationConflictError("operation input differs from its original request")
                return self._reset_result_payload(json.loads(existing["result_json"]), replay=True)

            row = self._require_player(connection, platform, platform_user_id)
            plan = self._reset_plan_row(connection, int(row["id"]), plan_id)
            if plan is None:
                raise TalentResetNotFoundError("no pending talent reset plan")
            if str(plan["status"]) == "confirmed":
                raise TalentResetStateError("talent reset plan is already confirmed")
            if str(plan["status"]) != "pending":
                raise TalentResetStateError("talent reset plan is not pending")
            if now >= datetime.fromisoformat(str(plan["expires_at"])):
                connection.execute(
                    "UPDATE talent_reset_plans SET status = 'expired', updated_at = ? WHERE plan_id = ?",
                    (now_text, str(plan["plan_id"])),
                )
                raise TalentResetPreviewExpiredError("talent reset preview expired")
            if str(row["path_key"] or "") != str(plan["path_key"]):
                raise TalentResetConflictError("primary path changed after the preview")
            tree_key = str(plan["tree_key"])
            nodes = self._reset_nodes(connection, int(row["id"]), tree_key)
            snapshot = self._json_object(plan["snapshot_json"], {})
            expected = [
                {
                    "node_key": str(node["node_key"]),
                    "tier": int(node["tier"]),
                    "cost_points": int(node["cost_points"]),
                }
                for node in (snapshot.get("nodes") or [])
            ]
            if self._reset_signature(nodes) != self._reset_signature(expected):
                raise TalentResetConflictError("learned talent nodes changed after the preview")
            if self._has_active_long_action(connection, int(row["id"])):
                raise TalentResetBusyError("another long action is active")
            stones_before = player_currency(row)
            cost = self._json_object(plan["cost_json"], {})
            if stones_before < definition.spirit_stone_cost:
                raise ResourceInsufficientError("spirit stones are insufficient")
            refund = self._reset_refund(nodes, definition)
            points_before = player_integer(row, "talent_points")

            change = change_player_state(
                connection,
                row,
                updated_at=now_text,
                asset_values=cost,
                asset_mode="spend",
                value_delta={"talent_points": refund} if refund else None,
            )
            assets = change.assets
            if assets is None:
                raise TalentResetStateError("talent reset asset transition is missing")

            connection.execute(
                """
                INSERT INTO talent_reset_records(
                    record_id, player_id, plan_id, operation_id, path_key, tree_key,
                    refund_points, node_snapshot_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    uuid4().hex,
                    int(row["id"]),
                    str(plan["plan_id"]),
                    operation_id,
                    str(plan["path_key"]),
                    tree_key,
                    refund,
                    json.dumps(nodes, ensure_ascii=False, sort_keys=True),
                    now_text,
                ),
            )
            connection.execute(
                "DELETE FROM talent_node_states WHERE player_id = ? AND tree_key = ?",
                (int(row["id"]), tree_key),
            )
            if connection.execute("SELECT changes()").fetchone()[0] != len(nodes):
                raise TalentResetStateError("talent nodes changed during reset")
            if refund:
                connection.execute(
                    """
                    INSERT INTO talent_point_events(
                        event_id, player_id, operation_id, delta, balance_before,
                        balance_after, reason, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        uuid4().hex,
                        int(row["id"]),
                        f"{operation_id}:reset-points",
                        refund,
                        points_before,
                        points_before + refund,
                        f"talent.reset:{plan['plan_id']}",
                        now_text,
                    ),
                )
            updated = connection.execute(
                "SELECT * FROM players WHERE id = ?", (int(row["id"]),)
            ).fetchone()
            if updated is None:
                raise PlayerNotFoundError("player disappeared during talent reset")
            connection.execute(
                "UPDATE talent_reset_plans SET status = 'confirmed', confirm_operation_id = ?, "
                "confirmed_at = ?, updated_at = ? WHERE plan_id = ? AND status = 'pending'",
                (operation_id, now_text, now_text, str(plan["plan_id"])),
            )
            if connection.execute("SELECT changes()").fetchone()[0] != 1:
                raise TalentResetStateError("talent reset plan was not pending")
            payload = {
                "plan_id": str(plan["plan_id"]),
                "path_key": str(plan["path_key"]),
                "path_label": str(snapshot.get("tree_label", plan["path_key"])),
                "tree_key": tree_key,
                "tree_label": str(snapshot.get("tree_label", tree_key)),
                "nodes": nodes,
                "refund_points": refund,
                "spirit_stones_before": stones_before,
                "spirit_stones_after": int(assets.currency),
                "talent_points_before": points_before,
                "talent_points_after": points_before + refund,
                "player": self._player_payload(self._row_to_player(updated)),
            }
            self._insert_operation(
                connection,
                operation_id=operation_id,
                operation_name=_CONFIRM,
                player_id=int(row["id"]),
                request_hash=request_hash,
                payload=payload,
                now_text=now_text,
            )
            return self._reset_result_payload(payload)

    def _reset_plan_row(
        self, connection: sqlite3.Connection, player_id: int, plan_id: str | None
    ) -> sqlite3.Row | None:
        if plan_id:
            return connection.execute(
                "SELECT * FROM talent_reset_plans WHERE player_id = ? AND plan_id = ?",
                (player_id, plan_id),
            ).fetchone()
        return connection.execute(
            "SELECT * FROM talent_reset_plans WHERE player_id = ? AND status = 'pending' "
            "ORDER BY created_at DESC, rowid DESC LIMIT 1",
            (player_id,),
        ).fetchone()

    async def cancel_talent_reset(
        self, *, platform: str, platform_user_id: str, operation_id: str
    ) -> TalentResetPlanRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._cancel_talent_reset_once, platform, platform_user_id, operation_id
            )

    def _cancel_talent_reset_once(
        self, platform: str, platform_user_id: str, operation_id: str
    ) -> TalentResetPlanRecord:
        request_hash = self._request_hash(
            _CANCEL, {"platform": platform, "platform_user_id": platform_user_id}
        )
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            if existing is not None:
                if existing["operation_name"] != _CANCEL or existing["request_hash"] != request_hash:
                    raise OperationConflictError("operation input differs from its original request")
                return self._reset_plan_payload(json.loads(existing["result_json"]), replay=True)

            row = self._require_player(connection, platform, platform_user_id)
            plan = connection.execute(
                "SELECT * FROM talent_reset_plans WHERE player_id = ? AND status = 'pending' "
                "ORDER BY created_at DESC, rowid DESC LIMIT 1",
                (int(row["id"]),),
            ).fetchone()
            if plan is None:
                raise TalentResetNotFoundError("no pending talent reset plan")
            connection.execute(
                "UPDATE talent_reset_plans SET status = 'cancelled', updated_at = ? "
                "WHERE plan_id = ? AND status = 'pending'",
                (now_text, str(plan["plan_id"])),
            )
            record = self._reset_plan_payload(
                {
                    "plan_id": plan["plan_id"],
                    "status": "cancelled",
                    "path_key": plan["path_key"],
                    "path_label": self._json_object(plan["snapshot_json"], {}).get(
                        "tree_label", plan["path_key"]
                    ),
                    "tree_key": plan["tree_key"],
                    "tree_label": self._json_object(plan["snapshot_json"], {}).get(
                        "tree_label", plan["tree_key"]
                    ),
                    "refund_points": self._json_object(plan["snapshot_json"], {}).get(
                        "refund_points", 0
                    ),
                    "cost": self._json_object(plan["cost_json"], {}),
                    "snapshot": self._json_object(plan["snapshot_json"], {}),
                    "expires_at": plan["expires_at"],
                }
            )
            self._insert_operation(
                connection,
                operation_id=operation_id,
                operation_name=_CANCEL,
                player_id=int(row["id"]),
                request_hash=request_hash,
                payload={
                    "plan_id": record.plan_id,
                    "status": "cancelled",
                    "path_key": record.path_key,
                    "path_label": record.path_label,
                    "tree_key": record.tree_key,
                    "tree_label": record.tree_label,
                    "refund_points": record.refund_points,
                    "cost": record.cost,
                    "snapshot": record.snapshot,
                    "expires_at": record.expires_at,
                },
                now_text=now_text,
            )
            return record


__all__ = ["TalentResetRepositoryMixin"]
