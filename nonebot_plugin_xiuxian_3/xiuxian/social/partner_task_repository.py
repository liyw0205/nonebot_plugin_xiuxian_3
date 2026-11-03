"""SQLite transactions for 道侣终局协作 (``partner.endgame_task``).

Progress is derived, never counted: it reads the shared final-battle table for
helped victories inside the task window, so a task cannot inflate its own
progress.  Rewards are paid per player with a unique ``(task_id, player_id)``
claim row, and the task never writes ``endgame_endings``.
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
    EndgamePartnerStateConflictError,
    OperationConflictError,
    PartnerTaskActiveError,
    PartnerTaskClaimedError,
    PartnerTaskNoPartnerError,
    PartnerTaskNotCompleteError,
)
from ..utils.assets import grant_player_assets
from .partner_task_content import partner_task_defaults

OPEN = "open"
COMPLETED = "completed"


class PartnerTaskRepositoryMixin:
    """Persistence for the shared partner endgame task."""

    def _partner_task_content(self) -> ContentBundle:
        content = getattr(self, "content", None)
        return content if content is not None else bundled_content()

    # ---------------------------------------------------------------- queries

    async def partner_task_status(
        self, *, platform: str, platform_user_id: str
    ) -> dict[str, Any]:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._partner_task_status_once, platform, platform_user_id
            )

    def _partner_task_status_once(
        self, platform: str, platform_user_id: str
    ) -> dict[str, Any]:
        content = self._partner_task_content()
        definition = partner_task_defaults(content)
        with self._connect() as connection:
            row = self._require_player(connection, platform, platform_user_id, writable=False)
            player_id = int(row["id"])
            relation = self._partner_active_relation(connection, player_id)
            partners_locked = self._partner_pair_ended(connection, relation)
            task = (
                self._partner_task_open_row(connection, str(relation["relation_id"]))
                if relation is not None
                else None
            )
            progress = (
                self._partner_task_progress(connection, task) if task is not None else 0
            )
            claimed = (
                self._partner_task_claim_row(connection, str(task["task_id"]), player_id)
                if task is not None
                else None
            )
            return {
                "has_partner": relation is not None,
                "relation_id": str(relation["relation_id"]) if relation is not None else "",
                "partner_locked": partners_locked,
                "name": str(definition["name"]),
                "description": str(definition["description"]),
                "target_kind": str(definition["target_kind"]),
                "target_amount": int(definition["target_amount"]),
                "window_days": int(definition["window_days"]),
                "reward_world_merit": int(definition["reward_world_merit"]),
                "reward_items": dict(definition["reward_items"]),
                "task_id": str(task["task_id"]) if task is not None else "",
                "task_status": str(task["status"]) if task is not None else "",
                "progress": progress,
                "complete": task is not None and progress >= int(task["target_amount"]),
                "claimed": claimed is not None,
            }

    # ------------------------------------------------------------------ start

    async def start_partner_task(
        self, *, platform: str, platform_user_id: str, operation_id: str
    ) -> dict[str, Any]:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._start_partner_task_once, platform, platform_user_id, operation_id
            )

    def _start_partner_task_once(
        self, platform: str, platform_user_id: str, operation_id: str
    ) -> dict[str, Any]:
        content = self._partner_task_content()
        definition = partner_task_defaults(content)
        operation_name = "social.partner_task_start"
        request_hash = self._request_hash(
            operation_name, {"platform": platform, "platform_user_id": platform_user_id}
        )
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._partner_task_operation(
                connection, operation_id, operation_name, request_hash
            )
            if existing is not None:
                return dict(existing, already_completed=True)

            row = self._require_player(connection, platform, platform_user_id)
            player_id = int(row["id"])
            relation = self._partner_active_relation(connection, player_id)
            if relation is None:
                raise PartnerTaskNoPartnerError("the player has no active partner")
            if self._partner_pair_ended(connection, relation):
                raise EndgamePartnerStateConflictError("one partner already recorded an ending")
            relation_id = str(relation["relation_id"])
            open_task = self._partner_task_open_row(connection, relation_id)
            if open_task is not None:
                raise PartnerTaskActiveError("this pair already has an open partner task")

            task_id = f"partner-task-{uuid4().hex}"
            connection.execute(
                "INSERT INTO partner_tasks(task_id, relation_id, player_a_id, player_b_id, "
                "target_amount, status, created_at) VALUES (?, ?, ?, ?, ?, 'open', ?)",
                (
                    task_id,
                    relation_id,
                    int(relation["player_a_id"]),
                    int(relation["player_b_id"]),
                    int(definition["target_amount"]),
                    now_text,
                ),
            )
            payload = {
                "task_id": task_id,
                "relation_id": relation_id,
                "action": "start",
                "target_amount": int(definition["target_amount"]),
                "expires_at": serialize_datetime(
                    now + timedelta(days=int(definition["window_days"]))
                ),
            }
            self._insert_operation(
                connection,
                operation_id=operation_id,
                operation_name=operation_name,
                player_id=player_id,
                request_hash=request_hash,
                payload=payload,
                now_text=now_text,
            )
            return dict(payload, already_completed=False)

    # ------------------------------------------------------------------ claim

    async def claim_partner_task(
        self, *, platform: str, platform_user_id: str, operation_id: str
    ) -> dict[str, Any]:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._claim_partner_task_once, platform, platform_user_id, operation_id
            )

    def _claim_partner_task_once(
        self, platform: str, platform_user_id: str, operation_id: str
    ) -> dict[str, Any]:
        content = self._partner_task_content()
        definition = partner_task_defaults(content)
        operation_name = "social.partner_task_claim"
        request_hash = self._request_hash(
            operation_name, {"platform": platform, "platform_user_id": platform_user_id}
        )
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._partner_task_operation(
                connection, operation_id, operation_name, request_hash
            )
            if existing is not None:
                return dict(existing, already_completed=True)

            row = self._require_player(connection, platform, platform_user_id)
            player_id = int(row["id"])
            relation = self._partner_active_relation(connection, player_id)
            if relation is None:
                raise PartnerTaskNoPartnerError("the player has no active partner")
            if self._partner_pair_ended(connection, relation):
                raise EndgamePartnerStateConflictError("one partner already recorded an ending")
            # Look at the latest task of any status: a completed task must
            # report "already claimed", not "nothing is running".
            task = self._partner_task_latest_row(connection, str(relation["relation_id"]))
            if task is None:
                raise PartnerTaskNotCompleteError("no partner task is running")
            task_id = str(task["task_id"])
            if self._partner_task_claim_row(connection, task_id, player_id) is not None:
                raise PartnerTaskClaimedError("the partner task reward is already claimed")
            if str(task["status"]) != "open":
                raise PartnerTaskClaimedError("the partner task is already settled")
            progress = self._partner_task_progress(connection, task)
            if progress < int(task["target_amount"]):
                raise PartnerTaskNotCompleteError("the partner task target is not reached")

            items: dict[str, Any] = dict(definition["reward_items"])
            merit = int(definition["reward_world_merit"])
            # ``world_merit`` is a player value, not an inventory asset: it must
            # travel through ``player_values`` or it would be stored as an item.
            grant_player_assets(
                connection, row, items, now_text, player_values={"world_merit": merit}
            )
            rewards = dict(items)
            rewards["world_merit"] = merit
            refreshed = connection.execute(
                "SELECT world_merit FROM players WHERE id = ?", (player_id,)
            ).fetchone()
            connection.execute(
                "INSERT INTO partner_task_claims(task_id, player_id, reward_json, "
                "operation_id, claimed_at) VALUES (?, ?, ?, ?, ?)",
                (
                    task_id,
                    player_id,
                    json.dumps(rewards, ensure_ascii=False, sort_keys=True),
                    operation_id,
                    now_text,
                ),
            )
            if self._partner_task_claim_count(connection, task_id) >= 2:
                connection.execute(
                    "UPDATE partner_tasks SET status = 'completed', completed_at = ? "
                    "WHERE task_id = ? AND status = 'open'",
                    (now_text, task_id),
                )
            payload = {
                "task_id": task_id,
                "relation_id": str(task["relation_id"]),
                "action": "claim",
                "progress": progress,
                "target_amount": int(task["target_amount"]),
                "reward": rewards,
                "world_merit_after": int(refreshed["world_merit"]) if refreshed else None,
            }
            self._insert_operation(
                connection,
                operation_id=operation_id,
                operation_name=operation_name,
                player_id=player_id,
                request_hash=request_hash,
                payload=payload,
                now_text=now_text,
            )
            return dict(payload, already_completed=False)

    # ---------------------------------------------------------------- helpers

    @staticmethod
    def _partner_active_relation(
        connection: sqlite3.Connection, player_id: int
    ) -> sqlite3.Row | None:
        return connection.execute(
            "SELECT * FROM partner_relations WHERE status = 'active' "
            "AND (player_a_id = ? OR player_b_id = ?) ORDER BY accepted_at DESC LIMIT 1",
            (player_id, player_id),
        ).fetchone()

    @staticmethod
    def _partner_pair_ended(connection: sqlite3.Connection, relation: Any) -> bool:
        if relation is None:
            return False
        ended = connection.execute(
            "SELECT 1 FROM endgame_endings WHERE player_id IN (?, ?) LIMIT 1",
            (int(relation["player_a_id"]), int(relation["player_b_id"])),
        ).fetchone()
        return ended is not None

    @staticmethod
    def _partner_task_open_row(
        connection: sqlite3.Connection, relation_id: str
    ) -> sqlite3.Row | None:
        if not relation_id:
            return None
        return connection.execute(
            "SELECT * FROM partner_tasks WHERE relation_id = ? AND status = 'open' "
            "ORDER BY created_at DESC LIMIT 1",
            (relation_id,),
        ).fetchone()

    @staticmethod
    def _partner_task_latest_row(
        connection: sqlite3.Connection, relation_id: str
    ) -> sqlite3.Row | None:
        if not relation_id:
            return None
        return connection.execute(
            "SELECT * FROM partner_tasks WHERE relation_id = ? "
            "ORDER BY created_at DESC LIMIT 1",
            (relation_id,),
        ).fetchone()

    @staticmethod
    def _partner_task_claim_row(
        connection: sqlite3.Connection, task_id: str, player_id: int
    ) -> sqlite3.Row | None:
        return connection.execute(
            "SELECT * FROM partner_task_claims WHERE task_id = ? AND player_id = ?",
            (task_id, player_id),
        ).fetchone()

    @staticmethod
    def _partner_task_claim_count(connection: sqlite3.Connection, task_id: str) -> int:
        return int(
            connection.execute(
                "SELECT COUNT(*) FROM partner_task_claims WHERE task_id = ?", (task_id,)
            ).fetchone()[0]
        )

    @staticmethod
    def _partner_task_progress(connection: sqlite3.Connection, task: Any) -> int:
        """Count helped final-battle victories by either partner since the task began."""

        row = connection.execute(
            "SELECT COUNT(*) FROM final_battle_members m "
            "JOIN final_battle_sessions s ON s.battle_id = m.battle_id "
            "WHERE m.player_id IN (?, ?) AND m.role = 'helper' "
            "AND s.status IN ('won', 'settled') AND s.created_at >= ?",
            (
                int(task["player_a_id"]),
                int(task["player_b_id"]),
                str(task["created_at"]),
            ),
        ).fetchone()
        return int(row[0])

    @staticmethod
    def _partner_task_operation(
        connection: sqlite3.Connection,
        operation_id: str,
        operation_name: str,
        request_hash: str,
    ) -> dict[str, Any] | None:
        existing = connection.execute(
            "SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id = ?",
            (operation_id,),
        ).fetchone()
        if existing is None:
            return None
        if existing["operation_name"] != operation_name or existing["request_hash"] != request_hash:
            raise OperationConflictError("operation input differs from its original request")
        return json.loads(existing["result_json"])