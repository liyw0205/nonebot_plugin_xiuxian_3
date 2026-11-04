"""SQLite transactions for the first-stage path switch (``path.switch.standard``).

The v0.1 contract keeps the switch two-phase: a preview freezes the plan, a
separate confirm consumes the token and spirit stones.  ``path_switch_plans``
is the durable plan row; every write goes through one ``BEGIN IMMEDIATE``
transaction with an ``operations`` row so a retried request replays its frozen
result instead of charging twice.

Only ``players.path_key`` / ``subprofession_key`` change.  Talents, mastered
skills, equipment instances and historical operations are deliberately left in
place: the existing consumers already filter them by the *current* path, so
switching back restores them without a second copy of the rules.
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
    PathSwitchBusyError,
    PathSwitchCooldownError,
    PathSwitchConflictError,
    PathSwitchInvalidError,
    PathSwitchNotFoundError,
    PathSwitchPreviewExpiredError,
    PathSwitchRequirementError,
    PathSwitchStateError,
    PathSwitchTokenClaimedError,
    PathSwitchTokenMissingError,
    PlayerNotFoundError,
    PlayerStageConflictError,
    PlayerSuspendedError,
    RepositoryBusyError,
    ResourceInsufficientError,
)
from ..player.path_rules import (
    path_name,
    resolve_path,
    resolve_subprofession,
    subprofession_name,
)
from ..utils.assets import inventory_amount, player_currency
from ..utils.player import change_player_state, player_integer
from .switch_content import PathSwitchDefinition, path_switch_definition
from .switch_models import (
    PathSwitchPlanRecord,
    PathSwitchResultRecord,
    PathSwitchTokenRecord,
)

_OPERATION_CLAIM = "path.claim_switch_token"
_OPERATION_PREVIEW = "path.preview_switch"
_OPERATION_CONFIRM = "path.confirm_switch"
_OPERATION_CANCEL = "path.cancel_switch"


class PathSwitchRepositoryMixin:
    """Persistence for the one-time token and the two-phase path switch."""

    # -- shared helpers -------------------------------------------------

    def _switch_content(self) -> ContentBundle:
        content = getattr(self, "content", None)
        return content if content is not None else bundled_content()

    def _switch_definition(self) -> PathSwitchDefinition:
        return path_switch_definition(self._switch_content())

    def _switch_path_label(self, path_key: str) -> str:
        return path_name(path_key, self._switch_content())

    def _switch_subprofession_label(self, value: str | None) -> str | None:
        if not value:
            return None
        try:
            return subprofession_name(value, "support", self._switch_content())
        except Exception:
            return None

    def _switch_plan_payload(
        self, plan: sqlite3.Row | dict[str, Any], *, replay: bool = False
    ) -> PathSwitchPlanRecord:
        snapshot = self._json_object(plan["snapshot_json"], {})
        return PathSwitchPlanRecord(
            plan_id=str(plan["plan_id"]),
            status=str(plan["status"]),
            from_path_key=str(plan["from_path_key"]),
            from_path_label=str(snapshot.get("from_path_label", plan["from_path_key"])),
            to_path_key=str(plan["to_path_key"]),
            to_path_label=str(snapshot.get("to_path_label", plan["to_path_key"])),
            to_subprofession_key=(
                str(plan["to_subprofession_key"]) if plan["to_subprofession_key"] else None
            ),
            to_subprofession_label=snapshot.get("to_subprofession_label"),
            cost=dict(self._json_object(plan["cost_json"], {})),
            snapshot=snapshot,
            expires_at=str(plan["expires_at"]),
            already_completed=str(plan["status"]) != "pending",
            idempotent_replay=replay,
        )

    def _switch_plan_from_payload(
        self, payload: dict[str, Any], *, replay: bool = False
    ) -> PathSwitchPlanRecord:
        return PathSwitchPlanRecord(
            plan_id=str(payload["plan_id"]),
            status=str(payload["status"]),
            from_path_key=str(payload["from_path_key"]),
            from_path_label=str(payload["from_path_label"]),
            to_path_key=str(payload["to_path_key"]),
            to_path_label=str(payload["to_path_label"]),
            to_subprofession_key=payload.get("to_subprofession_key"),
            to_subprofession_label=payload.get("to_subprofession_label"),
            cost=dict(payload.get("cost") or {}),
            snapshot=dict(payload.get("snapshot") or {}),
            expires_at=str(payload["expires_at"]),
            already_completed=bool(payload.get("already_completed", replay)),
            idempotent_replay=replay,
        )

    def _switch_result_from_payload(
        self, payload: dict[str, Any], *, replay: bool = False
    ) -> PathSwitchResultRecord:
        player_payload = payload.get("player")
        player = self._row_to_player(player_payload) if player_payload else None
        return PathSwitchResultRecord(
            plan_id=str(payload["plan_id"]),
            from_path_key=str(payload["from_path_key"]),
            from_path_label=str(payload["from_path_label"]),
            to_path_key=str(payload["to_path_key"]),
            to_path_label=str(payload["to_path_label"]),
            to_subprofession_key=payload.get("to_subprofession_key"),
            to_subprofession_label=payload.get("to_subprofession_label"),
            spirit_stones_before=int(payload["spirit_stones_before"]),
            spirit_stones_after=int(payload["spirit_stones_after"]),
            token_quantity_before=int(payload["token_quantity_before"]),
            token_quantity_after=int(payload["token_quantity_after"]),
            retained=tuple(payload.get("retained") or ()),
            frozen=tuple(payload.get("frozen") or ()),
            cleared=tuple(payload.get("cleared") or ()),
            player=player,
            already_completed=replay or bool(payload.get("already_completed", False)),
        )

    def _switch_realm_ok(self, row: sqlite3.Row, definition: PathSwitchDefinition) -> bool:
        content = self._switch_content()
        rank = {str(item["key"]): int(item.get("rank", -1)) for item in content.list("realm")}
        current = rank.get(str(row["realm_key"]), -1)
        required = rank.get(definition.min_realm, 99)
        layer = player_integer(row, "realm_layer")
        return (current, layer) >= (required, definition.min_layer)

    def _switch_claim_realm_ok(
        self, row: sqlite3.Row, definition: PathSwitchDefinition
    ) -> bool:
        content = self._switch_content()
        rank = {str(item["key"]): int(item.get("rank", -1)) for item in content.list("realm")}
        current = rank.get(str(row["realm_key"]), -1)
        required = rank.get(definition.token_claim_realm, 99)
        layer = player_integer(row, "realm_layer")
        return (current, layer) >= (required, definition.token_claim_layer)

    def _switch_conflict(self, row: sqlite3.Row) -> str | None:
        if row["domain_key"]:
            return "已选择领域"
        if row["dao_fruit_key"]:
            return "已得道果"
        return None

    def _switch_last_confirmed(self, connection: sqlite3.Connection, player_id: int) -> datetime | None:
        row = connection.execute(
            "SELECT MAX(confirmed_at) AS last_confirmed FROM path_switch_plans "
            "WHERE player_id = ? AND status = 'confirmed'",
            (player_id,),
        ).fetchone()
        value = row["last_confirmed"] if row is not None else None
        return datetime.fromisoformat(str(value)) if value else None

    def _switch_cooldown_remaining(
        self, connection: sqlite3.Connection, player_id: int, definition: PathSwitchDefinition
    ) -> int:
        last = self._switch_last_confirmed(connection, player_id)
        if last is None:
            return 0
        elapsed = (self._now() - last).total_seconds()
        return max(0, int(definition.cooldown_seconds - elapsed))

    # -- one-time token -------------------------------------------------

    async def claim_path_switch_token(
        self, *, platform: str, platform_user_id: str, operation_id: str
    ) -> PathSwitchTokenRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._claim_path_switch_token_once, platform, platform_user_id, operation_id
            )

    def _claim_path_switch_token_once(
        self, platform: str, platform_user_id: str, operation_id: str
    ) -> PathSwitchTokenRecord:
        definition = self._switch_definition()
        request_hash = self._request_hash(
            _OPERATION_CLAIM,
            {"platform": platform, "platform_user_id": platform_user_id},
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
                if existing["operation_name"] != _OPERATION_CLAIM or existing["request_hash"] != request_hash:
                    raise OperationConflictError("operation input differs from its original request")
                payload = json.loads(existing["result_json"])
                return PathSwitchTokenRecord(
                    item_key=str(payload["item_key"]),
                    item_label=str(payload["item_label"]),
                    quantity=int(payload["quantity"]),
                    player=self._row_to_player(payload["player"]),
                    claimed_at=str(payload["claimed_at"]),
                    already_completed=True,
                )

            row = self._require_player(connection, platform, platform_user_id)
            if str(row["stage"]) != "cultivator":
                raise PathSwitchRequirementError("path switch requires entry into cultivation")
            if not self._switch_claim_realm_ok(row, definition):
                raise PathSwitchRequirementError("path switch token requires a higher realm")
            inventory = self._json_object(row["inventory_json"], {})
            if inventory_amount(inventory, definition.token_item_key) >= definition.token_quantity:
                raise PathSwitchTokenClaimedError("path switch token is already held")
            last_claim = connection.execute(
                "SELECT MAX(created_at) AS last_claim FROM operations "
                "WHERE player_id = ? AND operation_name = ?",
                (int(row["id"]), _OPERATION_CLAIM),
            ).fetchone()
            last_value = last_claim["last_claim"] if last_claim is not None else None
            if last_value:
                elapsed = (now - datetime.fromisoformat(str(last_value))).total_seconds()
                remaining = int(definition.cooldown_seconds - elapsed)
                if remaining > 0:
                    raise PathSwitchCooldownError(remaining, "switch token claim cooldown")

            self._apply_token_grant(connection, row, definition, now_text)
            updated = connection.execute(
                "SELECT * FROM players WHERE id = ?", (int(row["id"]),)
            ).fetchone()
            if updated is None:
                raise PlayerNotFoundError("player disappeared during token claim")
            payload = {
                "item_key": definition.token_item_key,
                "item_label": self._switch_content().label("item", definition.token_item_key),
                "quantity": definition.token_quantity,
                "claimed_at": now_text,
                "player": self._player_payload(self._row_to_player(updated)),
            }
            self._insert_operation(
                connection,
                operation_id=operation_id,
                operation_name=_OPERATION_CLAIM,
                player_id=int(row["id"]),
                request_hash=request_hash,
                payload=payload,
                now_text=now_text,
            )
            return PathSwitchTokenRecord(
                item_key=str(payload["item_key"]),
                item_label=str(payload["item_label"]),
                quantity=int(payload["quantity"]),
                player=self._row_to_player(updated),
                claimed_at=now_text,
            )

    def _apply_token_grant(
        self,
        connection: sqlite3.Connection,
        row: sqlite3.Row,
        definition: PathSwitchDefinition,
        now_text: str,
    ) -> None:
        change_player_state(
            connection,
            row,
            updated_at=now_text,
            asset_values={definition.token_item_key: definition.token_quantity},
            asset_mode="grant",
        )

    # -- preview --------------------------------------------------------

    async def preview_path_switch(
        self,
        *,
        platform: str,
        platform_user_id: str,
        target_reference: str,
        subprofession_reference: str | None,
        operation_id: str,
    ) -> PathSwitchPlanRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._preview_path_switch_once,
                platform,
                platform_user_id,
                target_reference,
                subprofession_reference,
                operation_id,
            )

    def _preview_path_switch_once(
        self,
        platform: str,
        platform_user_id: str,
        target_reference: str,
        subprofession_reference: str | None,
        operation_id: str,
    ) -> PathSwitchPlanRecord:
        definition = self._switch_definition()
        content = self._switch_content()
        target_key = resolve_path(target_reference, content)
        if target_key is None:
            raise PathSwitchInvalidError("unknown target path")
        request_hash = self._request_hash(
            _OPERATION_PREVIEW,
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
                if existing["operation_name"] != _OPERATION_PREVIEW or existing["request_hash"] != request_hash:
                    raise OperationConflictError("operation input differs from its original request")
                return self._switch_plan_from_payload(json.loads(existing["result_json"]), replay=True)

            row = self._require_player(connection, platform, platform_user_id)
            if str(row["stage"]) != "cultivator" or not row["path_key"]:
                raise PathSwitchRequirementError("path switch requires a primary path")
            if not self._switch_realm_ok(row, definition):
                raise PathSwitchRequirementError("path switch requires a higher realm")
            from_key = str(row["path_key"])
            if target_key == from_key:
                raise PathSwitchInvalidError("target path is the current path")
            if target_key == "support":
                subprofession_key = resolve_subprofession(
                    subprofession_reference or "", "support", content
                )
                if subprofession_key is None:
                    raise PathSwitchInvalidError("support path requires a sub-profession")
            else:
                if subprofession_reference:
                    raise PathSwitchInvalidError(
                        "only the support path takes a sub-profession"
                    )
                subprofession_key = None
            conflict = self._switch_conflict(row)
            if conflict is not None:
                raise PathSwitchConflictError(conflict)
            if self._has_active_long_action(connection, int(row["id"])):
                raise PathSwitchBusyError("another long action is active")
            remaining = self._switch_cooldown_remaining(connection, int(row["id"]), definition)
            if remaining > 0:
                raise PathSwitchCooldownError(remaining)

            connection.execute(
                "UPDATE path_switch_plans SET status = 'expired', updated_at = ? "
                "WHERE player_id = ? AND status = 'pending'",
                (now_text, int(row["id"])),
            )
            expires_at = serialize_datetime(
                now + timedelta(seconds=definition.preview_ttl_seconds)
            )
            snapshot = self._switch_snapshot(connection, row, definition, target_key, subprofession_key)
            plan_id = f"path-switch-{uuid4().hex}"
            connection.execute(
                """
                INSERT INTO path_switch_plans(
                    plan_id, player_id, preview_operation_id, from_path_key, to_path_key,
                    to_subprofession_key, status, cost_json, snapshot_json, expires_at,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?)
                """,
                (
                    plan_id,
                    int(row["id"]),
                    operation_id,
                    from_key,
                    target_key,
                    subprofession_key,
                    json.dumps(definition_cost(definition), ensure_ascii=False, sort_keys=True),
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
                "cost": definition_cost(definition),
                "snapshot": snapshot,
                "expires_at": expires_at,
            }
            self._insert_operation(
                connection,
                operation_id=operation_id,
                operation_name=_OPERATION_PREVIEW,
                player_id=int(row["id"]),
                request_hash=request_hash,
                payload=payload,
                now_text=now_text,
            )
            return self._switch_plan_from_payload(payload)

    def _switch_snapshot(
        self,
        connection: sqlite3.Connection,
        row: sqlite3.Row,
        definition: PathSwitchDefinition,
        target_key: str,
        subprofession_key: str | None,
    ) -> dict[str, Any]:
        player_id = int(row["id"])
        talent_count = connection.execute(
            "SELECT COUNT(*) FROM talent_node_states WHERE player_id = ? AND tree_key = ?",
            (player_id, str(row["path_key"])),
        ).fetchone()[0]
        skill_count = connection.execute(
            "SELECT COUNT(*) FROM skill_masteries WHERE player_id = ?", (player_id,)
        ).fetchone()[0]
        equipment_count = connection.execute(
            "SELECT COUNT(*) FROM equipment_instances WHERE player_id = ?", (player_id,)
        ).fetchone()[0]
        retained = [
            f"公共境界与修为",
            f"已学神通 {int(skill_count)} 项",
            f"装备实例 {int(equipment_count)} 件",
            f"旧道脉节点 {int(talent_count)} 阶",
            "行囊、灵石、灵兽与灵骑",
        ]
        frozen = [
            "旧道途主动技能（回到旧道途后恢复）",
            "旧道途专属装备效果（回到旧道途后恢复）",
        ]
        cleared = []
        if subprofession_key is None and row["subprofession_key"]:
            cleared.append("生产辅修标记（已结算订单与产物不受影响）")
        return {
            "from_path_key": str(row["path_key"]),
            "from_path_label": self._switch_path_label(str(row["path_key"])),
            "to_path_key": target_key,
            "to_path_label": self._switch_path_label(target_key),
            "to_subprofession_key": subprofession_key,
            "to_subprofession_label": self._switch_subprofession_label(subprofession_key),
            "retained": retained,
            "frozen": frozen,
            "cleared": cleared,
            "talent_nodes": int(talent_count),
            "retained_skill_count": int(skill_count),
            "retained_equipment_count": int(equipment_count),
            "cooldown_seconds": definition.cooldown_seconds,
            "preview_ttl_seconds": definition.preview_ttl_seconds,
            "status_label": definition.status_label,
        }

    # -- confirm / cancel ----------------------------------------------

    async def confirm_path_switch(
        self,
        *,
        platform: str,
        platform_user_id: str,
        plan_id: str | None,
        operation_id: str,
    ) -> PathSwitchResultRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._confirm_path_switch_once, platform, platform_user_id, plan_id, operation_id
            )

    def _confirm_path_switch_once(
        self,
        platform: str,
        platform_user_id: str,
        plan_id: str | None,
        operation_id: str,
    ) -> PathSwitchResultRecord:
        definition = self._switch_definition()
        request_hash = self._request_hash(
            _OPERATION_CONFIRM,
            {
                "platform": platform,
                "platform_user_id": platform_user_id,
                "plan_id": plan_id,
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
                if existing["operation_name"] != _OPERATION_CONFIRM or existing["request_hash"] != request_hash:
                    raise OperationConflictError("operation input differs from its original request")
                return self._switch_result_from_payload(
                    json.loads(existing["result_json"]), replay=True
                )

            row = self._require_player(connection, platform, platform_user_id)
            plan = self._switch_plan_row(connection, int(row["id"]), plan_id)
            if plan is None:
                raise PathSwitchNotFoundError("no pending path switch plan")
            if str(plan["status"]) == "confirmed":
                raise PathSwitchStateError("path switch plan is already confirmed")
            if str(plan["status"]) != "pending":
                raise PathSwitchStateError("path switch plan is not pending")
            if now >= datetime.fromisoformat(str(plan["expires_at"])):
                connection.execute(
                    "UPDATE path_switch_plans SET status = 'expired', updated_at = ? WHERE plan_id = ?",
                    (now_text, str(plan["plan_id"])),
                )
                raise PathSwitchPreviewExpiredError("path switch preview expired")

            if str(row["path_key"] or "") != str(plan["from_path_key"]):
                raise PathSwitchConflictError("primary path changed after the preview")
            if not self._switch_realm_ok(row, definition):
                raise PathSwitchRequirementError("path switch requires a higher realm")
            conflict = self._switch_conflict(row)
            if conflict is not None:
                raise PathSwitchConflictError(conflict)
            if self._has_active_long_action(connection, int(row["id"])):
                raise PathSwitchBusyError("another long action is active")

            inventory = self._json_object(row["inventory_json"], {})
            if inventory_amount(inventory, definition.token_item_key) < definition.token_quantity:
                raise PathSwitchTokenMissingError("path switch token is missing")
            stones_before = player_currency(row)
            token_before = inventory_amount(inventory, definition.token_item_key)
            if stones_before < definition.spirit_stone_cost:
                raise ResourceInsufficientError("spirit stones are insufficient")

            before = self._switch_snapshot(
                connection,
                row,
                definition,
                str(plan["to_path_key"]),
                str(plan["to_subprofession_key"]) if plan["to_subprofession_key"] else None,
            )
            costs = definition_cost(definition)
            change = change_player_state(
                connection,
                row,
                updated_at=now_text,
                asset_values=costs,
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
                raise PathSwitchStateError("path switch asset transition is missing")
            token_after = int(assets.inventory.get(definition.token_item_key, 0))
            updated = connection.execute(
                "SELECT * FROM players WHERE id = ?", (int(row["id"]),)
            ).fetchone()
            if updated is None:
                raise PlayerNotFoundError("player disappeared during path switch")
            connection.execute(
                "UPDATE path_switch_plans SET status = 'confirmed', confirm_operation_id = ?, "
                "confirmed_at = ?, updated_at = ? WHERE plan_id = ? AND status = 'pending'",
                (operation_id, now_text, now_text, str(plan["plan_id"])),
            )
            if connection.execute("SELECT changes()").fetchone()[0] != 1:
                raise PathSwitchStateError("path switch plan was not pending")
            payload = {
                "plan_id": str(plan["plan_id"]),
                "from_path_key": str(plan["from_path_key"]),
                "from_path_label": before["from_path_label"],
                "to_path_key": str(plan["to_path_key"]),
                "to_path_label": before["to_path_label"],
                "to_subprofession_key": plan["to_subprofession_key"],
                "to_subprofession_label": before["to_subprofession_label"],
                "spirit_stones_before": stones_before,
                "spirit_stones_after": int(assets.currency),
                "token_quantity_before": token_before,
                "token_quantity_after": token_after,
                "retained": list(before["retained"]),
                "frozen": list(before["frozen"]),
                "cleared": list(before["cleared"]),
                "player": self._player_payload(self._row_to_player(updated)),
            }
            self._insert_operation(
                connection,
                operation_id=operation_id,
                operation_name=_OPERATION_CONFIRM,
                player_id=int(row["id"]),
                request_hash=request_hash,
                payload=payload,
                now_text=now_text,
            )
            return self._switch_result_from_payload(payload)

    def _switch_plan_row(
        self, connection: sqlite3.Connection, player_id: int, plan_id: str | None
    ) -> sqlite3.Row | None:
        if plan_id:
            return connection.execute(
                "SELECT * FROM path_switch_plans WHERE player_id = ? AND plan_id = ?",
                (player_id, plan_id),
            ).fetchone()
        return connection.execute(
            "SELECT * FROM path_switch_plans WHERE player_id = ? AND status = 'pending' "
            "ORDER BY created_at DESC, rowid DESC LIMIT 1",
            (player_id,),
        ).fetchone()

    async def cancel_path_switch(
        self,
        *,
        platform: str,
        platform_user_id: str,
        operation_id: str,
    ) -> PathSwitchPlanRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._cancel_path_switch_once, platform, platform_user_id, operation_id
            )

    def _cancel_path_switch_once(
        self, platform: str, platform_user_id: str, operation_id: str
    ) -> PathSwitchPlanRecord:
        request_hash = self._request_hash(
            _OPERATION_CANCEL,
            {"platform": platform, "platform_user_id": platform_user_id},
        )
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            if existing is not None:
                if existing["operation_name"] != _OPERATION_CANCEL or existing["request_hash"] != request_hash:
                    raise OperationConflictError("operation input differs from its original request")
                return self._switch_plan_from_payload(json.loads(existing["result_json"]), replay=True)

            row = self._require_player(connection, platform, platform_user_id)
            plan = connection.execute(
                "SELECT * FROM path_switch_plans WHERE player_id = ? AND status = 'pending' "
                "ORDER BY created_at DESC, rowid DESC LIMIT 1",
                (int(row["id"]),),
            ).fetchone()
            if plan is None:
                raise PathSwitchNotFoundError("no pending path switch plan")
            connection.execute(
                "UPDATE path_switch_plans SET status = 'cancelled', updated_at = ? "
                "WHERE plan_id = ? AND status = 'pending'",
                (now_text, str(plan["plan_id"])),
            )
            payload = self._switch_plan_payload(plan)
            result = {
                "plan_id": payload.plan_id,
                "status": "cancelled",
                "from_path_key": payload.from_path_key,
                "from_path_label": payload.from_path_label,
                "to_path_key": payload.to_path_key,
                "to_path_label": payload.to_path_label,
                "to_subprofession_key": payload.to_subprofession_key,
                "to_subprofession_label": payload.to_subprofession_label,
                "cost": payload.cost,
                "snapshot": payload.snapshot,
                "expires_at": payload.expires_at,
                "already_completed": False,
                "player": self._player_payload(self._row_to_player(row)),
            }
            self._insert_operation(
                connection,
                operation_id=operation_id,
                operation_name=_OPERATION_CANCEL,
                player_id=int(row["id"]),
                request_hash=request_hash,
                payload=result,
                now_text=now_text,
            )
            return PathSwitchPlanRecord(
                plan_id=payload.plan_id,
                status="cancelled",
                from_path_key=payload.from_path_key,
                from_path_label=payload.from_path_label,
                to_path_key=payload.to_path_key,
                to_path_label=payload.to_path_label,
                to_subprofession_key=payload.to_subprofession_key,
                to_subprofession_label=payload.to_subprofession_label,
                cost=payload.cost,
                snapshot=payload.snapshot,
                expires_at=payload.expires_at,
            )


def definition_cost(definition: PathSwitchDefinition) -> dict[str, Any]:
    return {
        definition.currency_key: definition.spirit_stone_cost,
        definition.token_item_key: definition.token_quantity,
    }


__all__ = ["PathSwitchRepositoryMixin", "definition_cost"]
