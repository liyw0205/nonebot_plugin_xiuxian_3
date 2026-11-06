"""SQLite transactions for the standalone support sub-profession switch.

The shipped runtime only writes ``players.subprofession_key`` during path
selection, path switch and path rebuild.  This mixin adds the missing
standalone command pair: a 15-minute preview and a confirmed 2,000-stone
switch with a seven-day cooldown, recorded in ``subprofession_switches``.

Old production orders keep the sub-profession captured in their own snapshot;
new orders read the updated ``players.subprofession_key``.  Production
proficiency is stored per sub-profession, so switching back restores it.
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
    SubprofessionSwitchConflictError,
    SubprofessionSwitchCooldownError,
    SubprofessionSwitchFundsError,
    SubprofessionSwitchInvalidError,
    SubprofessionSwitchNotFoundError,
    SubprofessionSwitchNotSupportError,
    SubprofessionSwitchPreviewExpiredError,
    SubprofessionSwitchStateError,
)
from ..player.path_rules import resolve_subprofession, subprofession_name
from ..utils.assets import player_currency
from ..utils.player import change_player_state, player_integer
from .subprofession_switch_content import (
    SubprofessionSwitchDefinition,
    subprofession_switch_definition,
)
from .subprofession_switch_models import (
    SubprofessionSwitchPlanRecord,
    SubprofessionSwitchResultRecord,
)

_PREVIEW = "subprofession.preview_switch"
_CONFIRM = "subprofession.confirm_switch"
_CANCEL = "subprofession.cancel_switch"


class SubprofessionSwitchRepositoryMixin:
    """Persistence for the standalone support sub-profession switch."""

    def _subprofession_content(self) -> ContentBundle:
        content = getattr(self, "content", None)
        return content if content is not None else bundled_content()

    def _subprofession_definition(self) -> SubprofessionSwitchDefinition:
        return subprofession_switch_definition(self._subprofession_content())

    def _subprofession_label(self, key: str) -> str:
        try:
            return subprofession_name(key, "support", self._subprofession_content())
        except Exception:
            return key

    def _subprofession_realm_ok(
        self, row: sqlite3.Row, definition: SubprofessionSwitchDefinition
    ) -> bool:
        ranks = {
            str(item["key"]): int(item.get("rank", -1))
            for item in self._subprofession_content().list("realm")
        }
        current = ranks.get(str(row["realm_key"]), -1)
        required = ranks.get(definition.min_realm, 99)
        return (current, player_integer(row, "realm_layer")) >= (
            required,
            definition.min_layer,
        )

    def _subprofession_cooldown_remaining(
        self,
        connection: sqlite3.Connection,
        player_id: int,
        definition: SubprofessionSwitchDefinition,
    ) -> int:
        row = connection.execute(
            "SELECT created_at FROM subprofession_switches WHERE player_id = ? "
            "ORDER BY created_at DESC, rowid DESC LIMIT 1",
            (player_id,),
        ).fetchone()
        if row is None:
            return 0
        last = datetime.fromisoformat(str(row["created_at"]))
        until = last + timedelta(seconds=definition.cooldown_seconds)
        return max(0, int((until - self._now()).total_seconds()))

    def _subprofession_plan_payload(
        self, payload: dict[str, Any], *, replay: bool = False
    ) -> SubprofessionSwitchPlanRecord:
        snapshot = dict(payload.get("snapshot") or {})
        return SubprofessionSwitchPlanRecord(
            plan_id=str(payload["plan_id"]),
            status=str(payload["status"]),
            from_subprofession_key=str(payload["from_subprofession_key"]),
            from_subprofession_label=str(
                payload.get("from_subprofession_label", payload["from_subprofession_key"])
            ),
            to_subprofession_key=str(payload["to_subprofession_key"]),
            to_subprofession_label=str(
                payload.get("to_subprofession_label", payload["to_subprofession_key"])
            ),
            cost=dict(payload.get("cost") or {}),
            snapshot=snapshot,
            expires_at=str(payload["expires_at"]),
            idempotent_replay=replay,
        )

    def _subprofession_result_payload(
        self, payload: dict[str, Any], *, replay: bool = False
    ) -> SubprofessionSwitchResultRecord:
        player_payload = payload.get("player")
        player = self._row_to_player(player_payload) if player_payload else None
        return SubprofessionSwitchResultRecord(
            switch_id=str(payload["switch_id"]),
            plan_id=str(payload["plan_id"]),
            from_subprofession_key=str(payload["from_subprofession_key"]),
            from_subprofession_label=str(payload["from_subprofession_label"]),
            to_subprofession_key=str(payload["to_subprofession_key"]),
            to_subprofession_label=str(payload["to_subprofession_label"]),
            spirit_stones_before=int(payload["spirit_stones_before"]),
            spirit_stones_after=int(payload["spirit_stones_after"]),
            player=player,
            already_completed=replay or bool(payload.get("already_completed", False)),
        )

    # -- preview --------------------------------------------------------

    async def preview_subprofession_switch(
        self,
        *,
        platform: str,
        platform_user_id: str,
        target_reference: str,
        operation_id: str,
    ) -> SubprofessionSwitchPlanRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._preview_subprofession_switch_once,
                platform,
                platform_user_id,
                target_reference,
                operation_id,
            )

    def _preview_subprofession_switch_once(
        self,
        platform: str,
        platform_user_id: str,
        target_reference: str,
        operation_id: str,
    ) -> SubprofessionSwitchPlanRecord:
        definition = self._subprofession_definition()
        content = self._subprofession_content()
        target_key = resolve_subprofession(target_reference, "support", content)
        if target_key is None:
            raise SubprofessionSwitchInvalidError("unknown support sub-profession")
        request_hash = self._request_hash(
            _PREVIEW,
            {
                "platform": platform,
                "platform_user_id": platform_user_id,
                "target": target_key,
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
                return self._subprofession_plan_payload(
                    json.loads(existing["result_json"]), replay=True
                )

            row = self._require_player(connection, platform, platform_user_id)
            if str(row["path_key"] or "") != "support":
                raise SubprofessionSwitchNotSupportError(
                    "only the support path can switch sub-professions"
                )
            if not self._subprofession_realm_ok(row, definition):
                raise SubprofessionSwitchInvalidError(
                    "sub-profession switch requires foundation L1"
                )
            from_key = str(row["subprofession_key"] or "")
            if not from_key:
                raise SubprofessionSwitchInvalidError(
                    "current sub-profession is missing"
                )
            if target_key == from_key:
                raise SubprofessionSwitchInvalidError(
                    "target sub-profession is the current one"
                )
            if not self._subprofession_label(from_key):
                raise SubprofessionSwitchInvalidError("current sub-profession is unknown")
            if self._has_active_long_action(connection, int(row["id"])):
                raise SubprofessionSwitchConflictError(
                    "another long action is active"
                )
            remaining = self._subprofession_cooldown_remaining(
                connection, int(row["id"]), definition
            )
            if remaining > 0:
                raise SubprofessionSwitchCooldownError(f"cooldown {remaining}")
            if player_currency(row) < definition.spirit_stone_cost:
                raise SubprofessionSwitchFundsError("spirit stones are insufficient")

            connection.execute(
                "UPDATE subprofession_switch_plans SET status = 'expired', updated_at = ? "
                "WHERE player_id = ? AND status = 'pending'",
                (now_text, int(row["id"])),
            )
            expires_at = serialize_datetime(
                now + timedelta(seconds=definition.preview_ttl_seconds)
            )
            cost = {"currency.spirit_stone": definition.spirit_stone_cost}
            snapshot = {
                "from_subprofession_key": from_key,
                "from_subprofession_label": self._subprofession_label(from_key),
                "to_subprofession_key": target_key,
                "to_subprofession_label": self._subprofession_label(target_key),
                "cost": cost,
                "preview_ttl_seconds": definition.preview_ttl_seconds,
                "cooldown_seconds": definition.cooldown_seconds,
                "retained": [
                    "公共境界、修为与道途",
                    "旧辅修的生产熟练度（切回时恢复）",
                    "已结算订单、产物与库存",
                    "道脉节点、神通与装备",
                ],
            }
            plan_id = f"subprofession-switch-{uuid4().hex}"
            connection.execute(
                """
                INSERT INTO subprofession_switch_plans(
                    plan_id, player_id, preview_operation_id, from_subprofession_key,
                    to_subprofession_key, status, cost_json, snapshot_json,
                    expires_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?)
                """,
                (
                    plan_id,
                    int(row["id"]),
                    operation_id,
                    from_key,
                    target_key,
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
                "from_subprofession_key": from_key,
                "from_subprofession_label": snapshot["from_subprofession_label"],
                "to_subprofession_key": target_key,
                "to_subprofession_label": snapshot["to_subprofession_label"],
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
            return self._subprofession_plan_payload(payload)

    # -- confirm / cancel ----------------------------------------------

    async def confirm_subprofession_switch(
        self,
        *,
        platform: str,
        platform_user_id: str,
        plan_id: str | None,
        operation_id: str,
    ) -> SubprofessionSwitchResultRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._confirm_subprofession_switch_once,
                platform,
                platform_user_id,
                plan_id,
                operation_id,
            )

    def _confirm_subprofession_switch_once(
        self,
        platform: str,
        platform_user_id: str,
        plan_id: str | None,
        operation_id: str,
    ) -> SubprofessionSwitchResultRecord:
        definition = self._subprofession_definition()
        request_hash = self._request_hash(
            _CONFIRM,
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
                if existing["operation_name"] != _CONFIRM or existing["request_hash"] != request_hash:
                    raise OperationConflictError("operation input differs from its original request")
                return self._subprofession_result_payload(
                    json.loads(existing["result_json"]), replay=True
                )

            row = self._require_player(connection, platform, platform_user_id)
            plan = self._subprofession_plan_row(connection, int(row["id"]), plan_id)
            if plan is None:
                raise SubprofessionSwitchNotFoundError(
                    "no pending sub-profession switch plan"
                )
            if str(plan["status"]) == "confirmed":
                raise SubprofessionSwitchStateError(
                    "sub-profession switch plan is already confirmed"
                )
            if str(plan["status"]) != "pending":
                raise SubprofessionSwitchStateError(
                    "sub-profession switch plan is not pending"
                )
            if now >= datetime.fromisoformat(str(plan["expires_at"])):
                connection.execute(
                    "UPDATE subprofession_switch_plans SET status = 'expired', updated_at = ? "
                    "WHERE plan_id = ?",
                    (now_text, str(plan["plan_id"])),
                )
                raise SubprofessionSwitchPreviewExpiredError(
                    "sub-profession switch preview expired"
                )
            if str(row["path_key"] or "") != "support":
                raise SubprofessionSwitchConflictError(
                    "primary path changed after the preview"
                )
            if str(row["subprofession_key"] or "") != str(plan["from_subprofession_key"]):
                raise SubprofessionSwitchConflictError(
                    "sub-profession changed after the preview"
                )
            if not self._subprofession_realm_ok(row, definition):
                raise SubprofessionSwitchInvalidError(
                    "sub-profession switch requires foundation L1"
                )
            if self._has_active_long_action(connection, int(row["id"])):
                raise SubprofessionSwitchConflictError(
                    "another long action is active"
                )
            remaining = self._subprofession_cooldown_remaining(
                connection, int(row["id"]), definition
            )
            if remaining > 0:
                raise SubprofessionSwitchCooldownError(f"cooldown {remaining}")
            stones_before = player_currency(row)
            if stones_before < definition.spirit_stone_cost:
                raise SubprofessionSwitchFundsError("spirit stones are insufficient")

            cost = self._json_object(plan["cost_json"], {})
            change = change_player_state(
                connection,
                row,
                updated_at=now_text,
                asset_values=cost,
                asset_mode="spend",
                player_values={"subprofession_key": str(plan["to_subprofession_key"])},
            )
            assets = change.assets
            if assets is None:
                raise SubprofessionSwitchStateError(
                    "sub-profession switch asset transition is missing"
                )
            switch_id = f"subprofession-switch-{uuid4().hex}"
            connection.execute(
                """
                INSERT INTO subprofession_switches(
                    switch_id, player_id, plan_id, operation_id,
                    from_subprofession_key, to_subprofession_key, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    switch_id,
                    int(row["id"]),
                    str(plan["plan_id"]),
                    operation_id,
                    str(plan["from_subprofession_key"]),
                    str(plan["to_subprofession_key"]),
                    now_text,
                ),
            )
            updated = connection.execute(
                "SELECT * FROM players WHERE id = ?", (int(row["id"]),)
            ).fetchone()
            if updated is None:
                raise PlayerNotFoundError(
                    "player disappeared during sub-profession switch"
                )
            connection.execute(
                "UPDATE subprofession_switch_plans SET status = 'confirmed', "
                "confirm_operation_id = ?, confirmed_at = ?, updated_at = ? "
                "WHERE plan_id = ? AND status = 'pending'",
                (operation_id, now_text, now_text, str(plan["plan_id"])),
            )
            if connection.execute("SELECT changes()").fetchone()[0] != 1:
                raise SubprofessionSwitchStateError(
                    "sub-profession switch plan was not pending"
                )
            payload = {
                "switch_id": switch_id,
                "plan_id": str(plan["plan_id"]),
                "from_subprofession_key": str(plan["from_subprofession_key"]),
                "from_subprofession_label": self._subprofession_label(
                    str(plan["from_subprofession_key"])
                ),
                "to_subprofession_key": str(plan["to_subprofession_key"]),
                "to_subprofession_label": self._subprofession_label(
                    str(plan["to_subprofession_key"])
                ),
                "spirit_stones_before": stones_before,
                "spirit_stones_after": int(assets.currency),
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
            return self._subprofession_result_payload(payload)

    def _subprofession_plan_row(
        self, connection: sqlite3.Connection, player_id: int, plan_id: str | None
    ) -> sqlite3.Row | None:
        if plan_id:
            return connection.execute(
                "SELECT * FROM subprofession_switch_plans WHERE player_id = ? AND plan_id = ?",
                (player_id, plan_id),
            ).fetchone()
        pending = connection.execute(
            "SELECT * FROM subprofession_switch_plans WHERE player_id = ? AND status = 'pending' "
            "ORDER BY created_at DESC, rowid DESC LIMIT 1",
            (player_id,),
        ).fetchone()
        if pending is not None:
            return pending
        return connection.execute(
            "SELECT * FROM subprofession_switch_plans WHERE player_id = ? "
            "ORDER BY created_at DESC, rowid DESC LIMIT 1",
            (player_id,),
        ).fetchone()

    async def cancel_subprofession_switch(
        self, *, platform: str, platform_user_id: str, operation_id: str
    ) -> SubprofessionSwitchPlanRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._cancel_subprofession_switch_once,
                platform,
                platform_user_id,
                operation_id,
            )

    def _cancel_subprofession_switch_once(
        self, platform: str, platform_user_id: str, operation_id: str
    ) -> SubprofessionSwitchPlanRecord:
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
                return self._subprofession_plan_payload(
                    json.loads(existing["result_json"]), replay=True
                )

            row = self._require_player(connection, platform, platform_user_id)
            plan = connection.execute(
                "SELECT * FROM subprofession_switch_plans WHERE player_id = ? AND status = 'pending' "
                "ORDER BY created_at DESC, rowid DESC LIMIT 1",
                (int(row["id"]),),
            ).fetchone()
            if plan is None:
                raise SubprofessionSwitchNotFoundError(
                    "no pending sub-profession switch plan"
                )
            connection.execute(
                "UPDATE subprofession_switch_plans SET status = 'cancelled', updated_at = ? "
                "WHERE plan_id = ? AND status = 'pending'",
                (now_text, str(plan["plan_id"])),
            )
            snapshot = self._json_object(plan["snapshot_json"], {})
            payload = {
                "plan_id": str(plan["plan_id"]),
                "status": "cancelled",
                "from_subprofession_key": str(plan["from_subprofession_key"]),
                "from_subprofession_label": snapshot.get(
                    "from_subprofession_label", plan["from_subprofession_key"]
                ),
                "to_subprofession_key": str(plan["to_subprofession_key"]),
                "to_subprofession_label": snapshot.get(
                    "to_subprofession_label", plan["to_subprofession_key"]
                ),
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
            return self._subprofession_plan_payload(payload)


__all__ = ["SubprofessionSwitchRepositoryMixin"]
