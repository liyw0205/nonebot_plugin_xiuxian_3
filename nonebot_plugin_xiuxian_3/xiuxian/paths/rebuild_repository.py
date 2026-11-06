"""SQLite transactions for the nascent-soul path rebuild (``path.rebuild.standard``).

The three-realms mainline already grants ``item.token.rebuild_path`` and the
faction reputations.  This module adds the missing item definition's consumer:
a 24-hour preview and a one-time confirm that spends 50,000 stones and the
token, freezes the old path in ``path_rebuilds`` and moves ``players.path_key``.

The old talent nodes stay in their original tree; the target tree receives free
``learned`` tiers up to ``max(1, old_level - 2)``.  No ``path_level`` column is
added: the shipped runtime already treats the highest learned tier as the path
level, and the target nodes use the same ``talent_node_states`` contract.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from ...contracts import serialize_datetime
from ..advancement.talent_rules import talent_tree_nodes, tree_definition
from ..content import ContentBundle, bundled_content
from ..persistence.errors import (
    OperationConflictError,
    PathRebuildConflictError,
    PathRebuildFundsError,
    PathRebuildInvalidError,
    PathRebuildLimitError,
    PathRebuildNotFoundError,
    PathRebuildPreviewExpiredError,
    PathRebuildQuestMissingError,
    PathRebuildRequirementError,
    PathRebuildStateError,
    PathRebuildTokenMissingError,
    PlayerNotFoundError,
    RepositoryBusyError,
)
from ..player.path_rules import (
    path_name,
    resolve_path,
    resolve_subprofession,
    subprofession_name,
)
from ..utils.assets import inventory_amount, player_currency
from ..utils.player import change_player_state, player_integer
from .rebuild_content import PathRebuildDefinition, path_rebuild_definition
from .rebuild_models import PathRebuildPlanRecord, PathRebuildResultRecord

_PREVIEW = "path.preview_rebuild"
_CONFIRM = "path.confirm_rebuild"
_CANCEL = "path.cancel_rebuild"


class PathRebuildRepositoryMixin:
    """Persistence for the one-time nascent-soul path rebuild."""

    def _rebuild_content(self) -> ContentBundle:
        content = getattr(self, "content", None)
        return content if content is not None else bundled_content()

    def _rebuild_definition(self) -> PathRebuildDefinition:
        return path_rebuild_definition(self._rebuild_content())

    def _rebuild_path_label(self, path_key: str) -> str:
        return path_name(path_key, self._rebuild_content())

    def _rebuild_subprofession_label(self, value: str | None) -> str | None:
        if not value:
            return None
        try:
            return subprofession_name(value, "support", self._rebuild_content())
        except Exception:
            return None

    def _rebuild_realm_ok(self, row: sqlite3.Row, definition: PathRebuildDefinition) -> bool:
        ranks = {
            str(item["key"]): int(item.get("rank", -1))
            for item in self._rebuild_content().list("realm")
        }
        current = ranks.get(str(row["realm_key"]), -1)
        required = ranks.get(definition.min_realm, 99)
        return (current, player_integer(row, "realm_layer")) >= (
            required,
            definition.min_layer,
        )

    def _rebuild_reputation_ok(self, row: sqlite3.Row, definition: PathRebuildDefinition) -> bool:
        reputation = self._json_object(row["faction_reputation_json"], {})
        for faction, minimum in definition.required_reputation.items():
            if int(reputation.get(faction, 0)) < minimum:
                return False
        return True

    def _rebuild_flag_ok(self, row: sqlite3.Row, definition: PathRebuildDefinition) -> bool:
        intro = self._json_object(row["intro_json"], {})
        flags = intro.get("flags")
        if not isinstance(flags, list):
            return False
        return definition.required_intro_flag in {str(flag) for flag in flags}

    def _rebuild_nodes(
        self, connection: sqlite3.Connection, player_id: int, tree_key: str
    ) -> list[dict[str, Any]]:
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
    def _rebuild_level(nodes: list[dict[str, Any]]) -> int:
        return max((int(node["tier"]) for node in nodes), default=0)

    @staticmethod
    def _rebuild_inherited_level(old_level: int, definition: PathRebuildDefinition) -> int:
        return max(1, int(old_level) - int(definition.level_deduction))

    def _rebuild_plan_payload(
        self, payload: dict[str, Any], *, replay: bool = False
    ) -> PathRebuildPlanRecord:
        snapshot = dict(payload.get("snapshot") or {})
        return PathRebuildPlanRecord(
            plan_id=str(payload["plan_id"]),
            status=str(payload["status"]),
            from_path_key=str(payload["from_path_key"]),
            from_path_label=str(payload.get("from_path_label", payload["from_path_key"])),
            to_path_key=str(payload["to_path_key"]),
            to_path_label=str(payload.get("to_path_label", payload["to_path_key"])),
            to_subprofession_key=payload.get("to_subprofession_key"),
            to_subprofession_label=payload.get("to_subprofession_label"),
            old_level=int(payload["old_level"]),
            inherited_level=int(payload["inherited_level"]),
            cost=dict(payload.get("cost") or {}),
            snapshot=snapshot,
            expires_at=str(payload["expires_at"]),
            already_completed=str(payload["status"]) != "pending",
            idempotent_replay=replay,
        )

    def _rebuild_result_payload(
        self, payload: dict[str, Any], *, replay: bool = False
    ) -> PathRebuildResultRecord:
        player_payload = payload.get("player")
        player = self._row_to_player(player_payload) if player_payload else None
        return PathRebuildResultRecord(
            rebuild_id=str(payload["rebuild_id"]),
            plan_id=str(payload["plan_id"]),
            from_path_key=str(payload["from_path_key"]),
            from_path_label=str(payload["from_path_label"]),
            to_path_key=str(payload["to_path_key"]),
            to_path_label=str(payload["to_path_label"]),
            to_subprofession_key=payload.get("to_subprofession_key"),
            to_subprofession_label=payload.get("to_subprofession_label"),
            old_level=int(payload["old_level"]),
            inherited_level=int(payload["inherited_level"]),
            spirit_stones_before=int(payload["spirit_stones_before"]),
            spirit_stones_after=int(payload["spirit_stones_after"]),
            token_quantity_before=int(payload["token_quantity_before"]),
            token_quantity_after=int(payload["token_quantity_after"]),
            from_nodes=tuple(payload.get("from_nodes") or ()),
            inherited_nodes=tuple(payload.get("inherited_nodes") or ()),
            player=player,
            already_completed=replay or bool(payload.get("already_completed", False)),
        )

    # -- preview --------------------------------------------------------

    async def preview_path_rebuild(
        self,
        *,
        platform: str,
        platform_user_id: str,
        target_reference: str,
        subprofession_reference: str | None,
        operation_id: str,
    ) -> PathRebuildPlanRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._preview_path_rebuild_once,
                platform,
                platform_user_id,
                target_reference,
                subprofession_reference,
                operation_id,
            )

    def _preview_path_rebuild_once(
        self,
        platform: str,
        platform_user_id: str,
        target_reference: str,
        subprofession_reference: str | None,
        operation_id: str,
    ) -> PathRebuildPlanRecord:
        definition = self._rebuild_definition()
        content = self._rebuild_content()
        target_key = resolve_path(target_reference, content)
        if target_key is None:
            raise PathRebuildInvalidError("unknown target path")
        request_hash = self._request_hash(
            _PREVIEW,
            {
                "platform": platform,
                "platform_user_id": platform_user_id,
                "target": target_key,
                "subprofession": subprofession_reference,
            },
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
                return self._rebuild_plan_payload(json.loads(existing["result_json"]), replay=True)

            row = self._require_player(connection, platform, platform_user_id)
            if not row["path_key"]:
                raise PathRebuildRequirementError("path rebuild requires a primary path")
            if not self._rebuild_realm_ok(row, definition):
                raise PathRebuildRequirementError("path rebuild requires a higher realm")
            if not self._rebuild_flag_ok(row, definition):
                raise PathRebuildQuestMissingError("path rebuild requires the three-realms story")
            if not self._rebuild_reputation_ok(row, definition):
                raise PathRebuildRequirementError("path rebuild requires three-realm reputation")
            existing_rebuild = connection.execute(
                "SELECT 1 FROM path_rebuilds WHERE player_id = ? LIMIT 1", (int(row["id"]),)
            ).fetchone()
            if existing_rebuild is not None:
                raise PathRebuildLimitError("character already completed a path rebuild")
            from_key = str(row["path_key"])
            if target_key == from_key:
                raise PathRebuildInvalidError("target path is the current path")
            if target_key == "support":
                subprofession_key = resolve_subprofession(
                    subprofession_reference or "", "support", content
                )
                if subprofession_key is None:
                    raise PathRebuildInvalidError("support path requires a sub-profession")
            else:
                if subprofession_reference:
                    raise PathRebuildInvalidError(
                        "only the support path takes a sub-profession"
                    )
                subprofession_key = None
            if row["domain_key"] or row["dao_fruit_key"]:
                raise PathRebuildConflictError("endgame state forbids path rebuild")
            if self._has_active_long_action(connection, int(row["id"])):
                raise PathRebuildConflictError("another long action is active")
            inventory = self._json_object(row["inventory_json"], {})
            if inventory_amount(inventory, definition.token_item_key) < definition.token_quantity:
                raise PathRebuildTokenMissingError("path rebuild token is missing")
            if player_currency(row) < definition.spirit_stone_cost:
                raise PathRebuildFundsError("spirit stones are insufficient")

            from_tree, _ = tree_definition(from_key, content)
            to_tree, to_tree_label = tree_definition(target_key, content)
            from_nodes = self._rebuild_nodes(connection, int(row["id"]), from_tree)
            old_level = self._rebuild_level(from_nodes)
            inherited_level = self._rebuild_inherited_level(old_level, definition)
            target_nodes = self._rebuild_nodes(connection, int(row["id"]), to_tree)
            existing_keys = {str(node["node_key"]) for node in target_nodes}
            inherited_nodes = [
                {"node_key": node.key, "tier": node.tier, "label": node.label}
                for node in talent_tree_nodes(to_tree, content)
                if node.tier <= inherited_level and node.key not in existing_keys
            ]
            connection.execute(
                "UPDATE path_rebuild_plans SET status = 'expired', updated_at = ? "
                "WHERE player_id = ? AND status = 'pending'",
                (now_text, int(row["id"])),
            )
            expires_at = serialize_datetime(
                now + timedelta(seconds=definition.preview_ttl_seconds)
            )
            cost = {
                definition.currency_key: definition.spirit_stone_cost,
                definition.token_item_key: definition.token_quantity,
            }
            snapshot = {
                "from_path_key": from_key,
                "from_path_label": self._rebuild_path_label(from_key),
                "to_path_key": target_key,
                "to_path_label": to_tree_label,
                "to_subprofession_key": subprofession_key,
                "to_subprofession_label": self._rebuild_subprofession_label(subprofession_key),
                "old_level": old_level,
                "inherited_level": inherited_level,
                "from_nodes": from_nodes,
                "inherited_nodes": inherited_nodes,
                "retained": [
                    "公共境界与修为",
                    "行囊、灵石、灵兽与灵骑",
                    f"旧道脉节点 {len(from_nodes)} 阶（旧道途冻结留档）",
                    "已学神通与装备实例",
                ],
                "frozen": [
                    "旧道途主动技能（切回旧道途后恢复）",
                    "旧道途专属装备效果（切回旧道途后恢复）",
                ],
                "cleared": (
                    ["生产辅修标记（已结算订单与产物不受影响）"]
                    if subprofession_key is None and row["subprofession_key"]
                    else []
                ),
                "preview_ttl_seconds": definition.preview_ttl_seconds,
                "level_deduction": definition.level_deduction,
            }
            plan_id = f"path-rebuild-{uuid4().hex}"
            connection.execute(
                """
                INSERT INTO path_rebuild_plans(
                    plan_id, player_id, preview_operation_id, from_path_key, to_path_key,
                    to_subprofession_key, old_level, inherited_level, status, cost_json,
                    snapshot_json, expires_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?)
                """,
                (
                    plan_id,
                    int(row["id"]),
                    operation_id,
                    from_key,
                    target_key,
                    subprofession_key,
                    old_level,
                    inherited_level,
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
                "from_path_key": from_key,
                "from_path_label": snapshot["from_path_label"],
                "to_path_key": target_key,
                "to_path_label": snapshot["to_path_label"],
                "to_subprofession_key": subprofession_key,
                "to_subprofession_label": snapshot["to_subprofession_label"],
                "old_level": old_level,
                "inherited_level": inherited_level,
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
            return self._rebuild_plan_payload(payload)

    # -- confirm / cancel ----------------------------------------------

    async def confirm_path_rebuild(
        self,
        *,
        platform: str,
        platform_user_id: str,
        plan_id: str | None,
        operation_id: str,
    ) -> PathRebuildResultRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._confirm_path_rebuild_once,
                platform,
                platform_user_id,
                plan_id,
                operation_id,
            )

    def _confirm_path_rebuild_once(
        self,
        platform: str,
        platform_user_id: str,
        plan_id: str | None,
        operation_id: str,
    ) -> PathRebuildResultRecord:
        definition = self._rebuild_definition()
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
                return self._rebuild_result_payload(json.loads(existing["result_json"]), replay=True)

            row = self._require_player(connection, platform, platform_user_id)
            plan = self._rebuild_plan_row(connection, int(row["id"]), plan_id)
            if plan is None:
                raise PathRebuildNotFoundError("no pending path rebuild plan")
            if str(plan["status"]) == "confirmed":
                raise PathRebuildStateError("path rebuild plan is already confirmed")
            if str(plan["status"]) != "pending":
                raise PathRebuildStateError("path rebuild plan is not pending")
            if now >= datetime.fromisoformat(str(plan["expires_at"])):
                connection.execute(
                    "UPDATE path_rebuild_plans SET status = 'expired', updated_at = ? WHERE plan_id = ?",
                    (now_text, str(plan["plan_id"])),
                )
                raise PathRebuildPreviewExpiredError("path rebuild preview expired")
            if str(row["path_key"] or "") != str(plan["from_path_key"]):
                raise PathRebuildConflictError("primary path changed after the preview")
            if not self._rebuild_realm_ok(row, definition):
                raise PathRebuildRequirementError("path rebuild requires a higher realm")
            if not self._rebuild_flag_ok(row, definition):
                raise PathRebuildQuestMissingError("path rebuild requires the three-realms story")
            if not self._rebuild_reputation_ok(row, definition):
                raise PathRebuildConflictError("three-realm reputation changed after the preview")
            if row["domain_key"] or row["dao_fruit_key"]:
                raise PathRebuildConflictError("endgame state forbids path rebuild")
            if self._has_active_long_action(connection, int(row["id"])):
                raise PathRebuildConflictError("another long action is active")
            existing_rebuild = connection.execute(
                "SELECT 1 FROM path_rebuilds WHERE player_id = ? LIMIT 1", (int(row["id"]),)
            ).fetchone()
            if existing_rebuild is not None:
                raise PathRebuildLimitError("character already completed a path rebuild")

            from_tree, _ = tree_definition(str(plan["from_path_key"]), self._rebuild_content())
            from_nodes = self._rebuild_nodes(connection, int(row["id"]), from_tree)
            if self._rebuild_level(from_nodes) != int(plan["old_level"]):
                raise PathRebuildConflictError("path level changed after the preview")

            inventory = self._json_object(row["inventory_json"], {})
            if inventory_amount(inventory, definition.token_item_key) < definition.token_quantity:
                raise PathRebuildTokenMissingError("path rebuild token is missing")
            stones_before = player_currency(row)
            token_before = inventory_amount(inventory, definition.token_item_key)
            if stones_before < definition.spirit_stone_cost:
                raise PathRebuildFundsError("spirit stones are insufficient")

            cost = self._json_object(plan["cost_json"], {})
            change = change_player_state(
                connection,
                row,
                updated_at=now_text,
                asset_values=cost,
                asset_mode="spend",
                player_values={
                    "path_key": str(plan["to_path_key"]),
                    "subprofession_key": (
                        str(plan["to_subprofession_key"]) if plan["to_subprofession_key"] else None
                    ),
                },
            )
            assets = change.assets
            if assets is None:
                raise PathRebuildStateError("path rebuild asset transition is missing")
            token_after = int(assets.inventory.get(definition.token_item_key, 0))
            rebuild_id = f"path-rebuild-{uuid4().hex}"
            try:
                connection.execute(
                    """
                    INSERT INTO path_rebuilds(
                        rebuild_id, player_id, plan_id, operation_id, from_path_key,
                        to_path_key, to_subprofession_key, old_level, inherited_level,
                        from_nodes_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        rebuild_id,
                        int(row["id"]),
                        str(plan["plan_id"]),
                        operation_id,
                        str(plan["from_path_key"]),
                        str(plan["to_path_key"]),
                        plan["to_subprofession_key"],
                        int(plan["old_level"]),
                        int(plan["inherited_level"]),
                        json.dumps(from_nodes, ensure_ascii=False, sort_keys=True),
                        now_text,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise PathRebuildLimitError("character already completed a path rebuild") from exc
            inherited: list[dict[str, Any]] = []
            target_tree, _ = tree_definition(str(plan["to_path_key"]), self._rebuild_content())
            existing_keys = {
                str(node["node_key"])
                for node in self._rebuild_nodes(connection, int(row["id"]), target_tree)
            }
            for node in talent_tree_nodes(target_tree, self._rebuild_content()):
                if node.tier > int(plan["inherited_level"]) or node.key in existing_keys:
                    continue
                snapshot = {
                    "reason": "path.rebuild.inherit",
                    "node_key": node.key,
                    "tree_key": target_tree,
                    "tier": node.tier,
                    "path_key": str(plan["to_path_key"]),
                    "inherited_level": int(plan["inherited_level"]),
                    "operation_id": operation_id,
                }
                connection.execute(
                    """
                    INSERT INTO talent_node_states(
                        node_id, player_id, operation_id, node_key, tree_key, tier,
                        status, cost_points, snapshot_json, unlocked_at, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, 'learned', 0, ?, ?, ?, ?)
                    """,
                    (
                        uuid4().hex,
                        int(row["id"]),
                        f"{operation_id}:inherit:{node.tier}",
                        node.key,
                        target_tree,
                        node.tier,
                        json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
                        now_text,
                        now_text,
                        now_text,
                    ),
                )
                inherited.append(
                    {"node_key": node.key, "tier": node.tier, "label": node.label}
                )
            updated = connection.execute(
                "SELECT * FROM players WHERE id = ?", (int(row["id"]),)
            ).fetchone()
            if updated is None:
                raise PlayerNotFoundError("player disappeared during path rebuild")
            connection.execute(
                "UPDATE path_rebuild_plans SET status = 'confirmed', confirm_operation_id = ?, "
                "confirmed_at = ?, updated_at = ? WHERE plan_id = ? AND status = 'pending'",
                (operation_id, now_text, now_text, str(plan["plan_id"])),
            )
            if connection.execute("SELECT changes()").fetchone()[0] != 1:
                raise PathRebuildStateError("path rebuild plan was not pending")
            payload = {
                "rebuild_id": rebuild_id,
                "plan_id": str(plan["plan_id"]),
                "from_path_key": str(plan["from_path_key"]),
                "from_path_label": self._rebuild_path_label(str(plan["from_path_key"])),
                "to_path_key": str(plan["to_path_key"]),
                "to_path_label": self._rebuild_path_label(str(plan["to_path_key"])),
                "to_subprofession_key": plan["to_subprofession_key"],
                "to_subprofession_label": self._rebuild_subprofession_label(
                    str(plan["to_subprofession_key"]) if plan["to_subprofession_key"] else None
                ),
                "old_level": int(plan["old_level"]),
                "inherited_level": int(plan["inherited_level"]),
                "spirit_stones_before": stones_before,
                "spirit_stones_after": int(assets.currency),
                "token_quantity_before": token_before,
                "token_quantity_after": token_after,
                "from_nodes": from_nodes,
                "inherited_nodes": inherited,
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
            return self._rebuild_result_payload(payload)

    def _rebuild_plan_row(
        self, connection: sqlite3.Connection, player_id: int, plan_id: str | None
    ) -> sqlite3.Row | None:
        if plan_id:
            return connection.execute(
                "SELECT * FROM path_rebuild_plans WHERE player_id = ? AND plan_id = ?",
                (player_id, plan_id),
            ).fetchone()
        pending = connection.execute(
            "SELECT * FROM path_rebuild_plans WHERE player_id = ? AND status = 'pending' "
            "ORDER BY created_at DESC, rowid DESC LIMIT 1",
            (player_id,),
        ).fetchone()
        if pending is not None:
            return pending
        return connection.execute(
            "SELECT * FROM path_rebuild_plans WHERE player_id = ? "
            "ORDER BY created_at DESC, rowid DESC LIMIT 1",
            (player_id,),
        ).fetchone()

    async def cancel_path_rebuild(
        self, *, platform: str, platform_user_id: str, operation_id: str
    ) -> PathRebuildPlanRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._cancel_path_rebuild_once, platform, platform_user_id, operation_id
            )

    def _cancel_path_rebuild_once(
        self, platform: str, platform_user_id: str, operation_id: str
    ) -> PathRebuildPlanRecord:
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
                return self._rebuild_plan_payload(json.loads(existing["result_json"]), replay=True)

            row = self._require_player(connection, platform, platform_user_id)
            plan = connection.execute(
                "SELECT * FROM path_rebuild_plans WHERE player_id = ? AND status = 'pending' "
                "ORDER BY created_at DESC, rowid DESC LIMIT 1",
                (int(row["id"]),),
            ).fetchone()
            if plan is None:
                raise PathRebuildNotFoundError("no pending path rebuild plan")
            connection.execute(
                "UPDATE path_rebuild_plans SET status = 'cancelled', updated_at = ? "
                "WHERE plan_id = ? AND status = 'pending'",
                (now_text, str(plan["plan_id"])),
            )
            snapshot = self._json_object(plan["snapshot_json"], {})
            payload = {
                "plan_id": str(plan["plan_id"]),
                "status": "cancelled",
                "from_path_key": str(plan["from_path_key"]),
                "from_path_label": str(snapshot.get("from_path_label", plan["from_path_key"])),
                "to_path_key": str(plan["to_path_key"]),
                "to_path_label": str(snapshot.get("to_path_label", plan["to_path_key"])),
                "to_subprofession_key": plan["to_subprofession_key"],
                "to_subprofession_label": snapshot.get("to_subprofession_label"),
                "old_level": int(plan["old_level"]),
                "inherited_level": int(plan["inherited_level"]),
                "cost": self._json_object(plan["cost_json"], {}),
                "snapshot": snapshot,
                "expires_at": str(plan["expires_at"]),
            }
            self._insert_operation(
                connection,
                operation_id=operation_id,
                operation_name=_CANCEL,
                player_id=int(row["id"]),
                request_hash=request_hash,
                payload=payload,
                now_text=now_text,
            )
            return self._rebuild_plan_payload(payload)


__all__ = ["PathRebuildRepositoryMixin"]
