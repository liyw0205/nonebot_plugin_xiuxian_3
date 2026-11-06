"""SQLite transactions for the 留界据点 (``settlement.dao_hall``).

One hall per founder, one membership row per player (``player_id`` is unique,
so a player can never join two halls), and every mutation runs inside a single
``BEGIN IMMEDIATE`` transaction with an ``operations`` row.  World merit is
consumed from the player, construction records who paid, and maintenance is
billed from the hall treasury into a contribution ledger so the weekly cost is
auditable instead of a silent counter.
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
    DaoHallCapacityError,
    DaoHallConstructionBusyError,
    DaoHallMaterialError,
    DaoHallMemberStateError,
    DaoHallNotFoundError,
    DaoHallProjectLockedError,
    DaoHallRebuildingError,
    DaoHallRequirementError,
    OperationConflictError,
    PlayerNotFoundError,
)
from ..stats.rules import COMBAT_STAT_KEYS  # noqa: F401  (keeps import parity with peer mixins)
from ..utils.assets import player_currency
from ..utils.player import change_player_state_actual, player_integer
from .dao_hall_models import DaoHallOperationRecord, DaoHallState
from .dao_hall_rules import (
    can_hold_core_seat,
    core_seat_available,
    dao_hall_definition,
    dao_hall_project,
    dao_hall_project_list,
    effective_core_capacity,
    founding_missing_requirements,
    maintenance_cost,
    maintenance_due_at,
    project_already_built,
    project_locked,
    rebuild_hours,
)


class DaoHallRepositoryMixin:
    """Persistence operations for the single-server dao hall."""

    def _dao_hall_content(self) -> ContentBundle:
        content = getattr(self, "content", None)
        return content if content is not None else bundled_content()

    # ---------------------------------------------------------------- queries

    async def dao_hall_status(self, *, platform: str, platform_user_id: str) -> DaoHallState:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._dao_hall_status_once, platform, platform_user_id)

    def _dao_hall_status_once(self, platform: str, platform_user_id: str) -> DaoHallState:
        content = self._dao_hall_content()
        definition = dao_hall_definition(content)
        with self._connect() as connection:
            row = self._require_player(connection, platform, platform_user_id, writable=False)
            membership = self._dao_hall_membership(connection, int(row["id"]))
            if membership is None:
                missing = founding_missing_requirements(
                    definition=definition,
                    ending_key=self._dao_hall_ending(connection, int(row["id"])),
                    world_merit=player_integer(row, "world_merit"),
                    spirit_stones=player_currency(row),
                    already_member=False,
                )
                return DaoHallState(
                    hall_id="",
                    name=definition.name,
                    status="none",
                    founder_player_id=0,
                    core_members=0,
                    core_capacity=definition.core_capacity,
                    treasury_spirit_stones=0,
                    contributed_world_merit=0,
                    built_project_keys=(),
                    rebuild_ends_at=None,
                    next_maintenance_at="",
                    maintenance_due=definition.maintenance_spirit_stones,
                    founding_cost_world_merit=definition.required_world_merit,
                    founding_cost_spirit_stones=definition.spirit_stones,
                    ending_key=self._dao_hall_ending(connection, int(row["id"])),
                    world_merit=player_integer(row, "world_merit"),
                    spirit_stones=player_currency(row),
                    is_member=False,
                    role=None,
                    qualified=not missing,
                    missing=tuple(missing),
                )
            hall = self._dao_hall_row(connection, str(membership["hall_id"]))
            if hall is None:
                raise DaoHallNotFoundError("dao hall row is missing")
            hall = self._dao_hall_recover_if_due(
                connection, hall, now_text=serialize_datetime(self._now())
            )
            now_text = serialize_datetime(self._now())
            self._dao_hall_complete_construction_if_due(
                connection, str(hall["hall_id"]), now_text
            )
            construction = self._dao_hall_construction(
                connection, str(hall["hall_id"])
            )
            built = self._dao_hall_built_projects(connection, str(hall["hall_id"]))
            core_members = self._dao_hall_core_count(connection, str(hall["hall_id"]))
            now = self._now()
            due_at = maintenance_due_at(
                last_maintained_at=datetime.fromisoformat(str(hall["last_maintained_at"])),
                definition=definition,
            )
            return DaoHallState(
                hall_id=str(hall["hall_id"]),
                name=str(hall["name"]),
                status=str(hall["status"]),
                founder_player_id=int(hall["founder_player_id"]),
                core_members=core_members,
                core_capacity=effective_core_capacity(
                    definition=definition, built=built, content=content
                ),
                treasury_spirit_stones=int(hall["treasury_spirit_stones"]),
                contributed_world_merit=int(hall["contributed_world_merit"]),
                built_project_keys=built,
                rebuild_ends_at=(
                    str(hall["rebuild_ends_at"]) if hall["rebuild_ends_at"] is not None else None
                ),
                next_maintenance_at=serialize_datetime(due_at),
                maintenance_due=maintenance_cost(
                    definition=definition, built=built, content=content
                ),
                founding_cost_world_merit=definition.required_world_merit,
                founding_cost_spirit_stones=definition.spirit_stones,
                ending_key=self._dao_hall_ending(connection, int(row["id"])),
                world_merit=player_integer(row, "world_merit"),
                spirit_stones=player_currency(row),
                is_member=True,
                role=str(membership["role"]),
                qualified=True,
                missing=(),
                construction_project_key=(
                    str(construction["project_key"]) if construction is not None else None
                ),
                construction_ends_at=(
                    str(construction["ends_at"]) if construction is not None else None
                ),
            )

    # ---------------------------------------------------------------- founding

    async def found_dao_hall(
        self, *, platform: str, platform_user_id: str, operation_id: str
    ) -> DaoHallOperationRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._found_dao_hall_once, platform, platform_user_id, operation_id
            )

    def _found_dao_hall_once(
        self, platform: str, platform_user_id: str, operation_id: str
    ) -> DaoHallOperationRecord:
        content = self._dao_hall_content()
        definition = dao_hall_definition(content)
        operation_name = "social.dao_hall_found"
        request_hash = self._request_hash(
            operation_name,
            {"platform": platform, "platform_user_id": platform_user_id, "hall": definition.name},
        )
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._dao_hall_operation(connection, operation_id, operation_name, request_hash)
            if existing is not None:
                return self._dao_hall_operation_from_payload(existing, replay=True)

            row = self._require_player(connection, platform, platform_user_id)
            player_id = int(row["id"])
            ending = self._dao_hall_ending(connection, player_id)
            missing = founding_missing_requirements(
                definition=definition,
                ending_key=ending,
                world_merit=player_integer(row, "world_merit"),
                spirit_stones=player_currency(row),
                already_member=self._dao_hall_membership(connection, player_id) is not None,
            )
            if missing:
                raise DaoHallRequirementError("dao hall founding requirements are missing")
            if player_currency(row) < definition.spirit_stones:
                raise DaoHallMaterialError("spirit stones cannot cover the founding cost")

            actual = change_player_state_actual(
                connection,
                row,
                updated_at=now_text,
                # ``spend`` takes non-negative costs and negates them itself,
                # while ``value_delta`` is signed.
                asset_values={"spirit_stones": definition.spirit_stones},
                asset_mode="spend",
                value_delta={"world_merit": -definition.required_world_merit},
            )
            if actual.get("spirit_stones", 0) != -definition.spirit_stones or actual.get(
                "world_merit", 0
            ) != -definition.required_world_merit:
                raise DaoHallMaterialError("founding cost could not be fully paid")

            hall_id = f"hall-{uuid4().hex}"
            connection.execute(
                """
                INSERT INTO dao_halls(
                    hall_id, name, status, founder_player_id, core_capacity,
                    treasury_spirit_stones, contributed_world_merit, rebuild_ends_at,
                    last_maintained_at, created_at, updated_at
                ) VALUES (?, ?, 'active', ?, ?, ?, 0, NULL, ?, ?, ?)
                """,
                (
                    hall_id,
                    definition.name,
                    player_id,
                    definition.core_capacity,
                    # The founding stones fund the hall instead of vanishing:
                    # the first weekly maintenance is paid from here.
                    definition.spirit_stones,
                    now_text,
                    now_text,
                    now_text,
                ),
            )
            connection.execute(
                "INSERT INTO dao_hall_members(hall_id, player_id, role, joined_at) "
                "VALUES (?, ?, 'founder', ?)",
                (hall_id, player_id, now_text),
            )
            self._dao_hall_ledger(
                connection,
                hall_id=hall_id,
                player_id=player_id,
                world_merit=definition.required_world_merit,
                spirit_stones=definition.spirit_stones,
                reason="dao_hall.found",
                operation_id=operation_id,
                now_text=now_text,
            )
            row = connection.execute("SELECT * FROM players WHERE id = ?", (player_id,)).fetchone()
            payload = self._dao_hall_payload(
                hall_id=hall_id,
                action="found",
                status="active",
                core_members=1,
                core_capacity=definition.core_capacity,
                treasury=definition.spirit_stones,
                world_merit=player_integer(row, "world_merit") - definition.required_world_merit,
                spirit_stones=player_currency(row) - definition.spirit_stones,
                project_key=None,
                world_merit_spent=definition.required_world_merit,
                spirit_stones_spent=definition.spirit_stones,
            )
            self._insert_operation(
                connection,
                operation_id=operation_id,
                operation_name=operation_name,
                player_id=player_id,
                request_hash=request_hash,
                payload=payload,
                now_text=now_text,
            )
            return self._dao_hall_operation_from_payload(payload)

    # ----------------------------------------------------------------- joining

    async def join_dao_hall(
        self, *, platform: str, platform_user_id: str, operation_id: str
    ) -> DaoHallOperationRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._join_dao_hall_once, platform, platform_user_id, operation_id
            )

    def _join_dao_hall_once(
        self, platform: str, platform_user_id: str, operation_id: str
    ) -> DaoHallOperationRecord:
        content = self._dao_hall_content()
        definition = dao_hall_definition(content)
        operation_name = "social.dao_hall_join"
        request_hash = self._request_hash(
            operation_name, {"platform": platform, "platform_user_id": platform_user_id}
        )
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._dao_hall_operation(connection, operation_id, operation_name, request_hash)
            if existing is not None:
                return self._dao_hall_operation_from_payload(existing, replay=True)

            row = self._require_player(connection, platform, platform_user_id)
            player_id = int(row["id"])
            if self._dao_hall_membership(connection, player_id) is not None:
                raise DaoHallMemberStateError("DAO_HALL_ALREADY_JOINED", "already a hall member")
            hall = self._dao_hall_first_row(connection)
            if hall is None:
                raise DaoHallNotFoundError("no dao hall exists yet")
            hall = self._dao_hall_recover_if_due(
                connection, hall, now_text=serialize_datetime(self._now())
            )
            hall_id = str(hall["hall_id"])
            if str(hall["status"]) == "rebuilding":
                raise DaoHallRebuildingError("the dao hall is rebuilding")

            built = self._dao_hall_built_projects(connection, hall_id)
            core_members = self._dao_hall_core_count(connection, hall_id)
            ending = self._dao_hall_ending(connection, player_id)
            core_eligible = can_hold_core_seat(
                definition=definition,
                realm_key=str(row["realm_key"]),
                realm_layer=player_integer(row, "realm_layer"),
                ending_key=ending,
            )
            if core_eligible:
                if not core_seat_available(
                    definition=definition,
                    built=built,
                    content=content,
                    core_members=core_members,
                ):
                    raise DaoHallCapacityError("the dao hall has no free core seat")
                role = "core"
                core_members += 1
            else:
                # Non-qualified players may visit but never occupy a core seat.
                role = "guest"
            connection.execute(
                "INSERT INTO dao_hall_members(hall_id, player_id, role, joined_at) VALUES (?, ?, ?, ?)",
                (hall_id, player_id, role, now_text),
            )
            payload = self._dao_hall_payload(
                hall_id=hall_id,
                action=f"join:{role}",
                status=str(hall["status"]),
                core_members=core_members,
                core_capacity=effective_core_capacity(
                    definition=definition, built=built, content=content
                ),
                treasury=int(hall["treasury_spirit_stones"]),
                world_merit=player_integer(row, "world_merit"),
                spirit_stones=player_currency(row),
                project_key=None,
                world_merit_spent=0,
                spirit_stones_spent=0,
            )
            self._insert_operation(
                connection,
                operation_id=operation_id,
                operation_name=operation_name,
                player_id=player_id,
                request_hash=request_hash,
                payload=payload,
                now_text=now_text,
            )
            return self._dao_hall_operation_from_payload(payload)

    async def leave_dao_hall(
        self, *, platform: str, platform_user_id: str, operation_id: str
    ) -> DaoHallOperationRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._leave_dao_hall_once, platform, platform_user_id, operation_id
            )

    def _leave_dao_hall_once(
        self, platform: str, platform_user_id: str, operation_id: str
    ) -> DaoHallOperationRecord:
        content = self._dao_hall_content()
        definition = dao_hall_definition(content)
        operation_name = "social.dao_hall_leave"
        request_hash = self._request_hash(
            operation_name, {"platform": platform, "platform_user_id": platform_user_id}
        )
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._dao_hall_operation(connection, operation_id, operation_name, request_hash)
            if existing is not None:
                return self._dao_hall_operation_from_payload(existing, replay=True)

            row = self._require_player(connection, platform, platform_user_id)
            player_id = int(row["id"])
            membership = self._dao_hall_membership(connection, player_id)
            if membership is None:
                raise DaoHallNotFoundError("the player is not a hall member")
            if str(membership["role"]) == "founder":
                raise DaoHallMemberStateError(
                    "DAO_HALL_FOUNDER_LOCKED", "the founder cannot leave the hall"
                )
            hall_id = str(membership["hall_id"])
            hall = self._dao_hall_row(connection, hall_id)
            if hall is None:
                raise DaoHallNotFoundError("dao hall row is missing")
            connection.execute(
                "DELETE FROM dao_hall_members WHERE hall_id = ? AND player_id = ?",
                (hall_id, player_id),
            )
            built = self._dao_hall_built_projects(connection, hall_id)
            payload = self._dao_hall_payload(
                hall_id=hall_id,
                action="leave",
                status=str(hall["status"]),
                core_members=self._dao_hall_core_count(connection, hall_id),
                core_capacity=effective_core_capacity(
                    definition=definition, built=built, content=content
                ),
                treasury=int(hall["treasury_spirit_stones"]),
                world_merit=player_integer(row, "world_merit"),
                spirit_stones=player_currency(row),
                project_key=None,
                world_merit_spent=0,
                spirit_stones_spent=0,
            )
            self._insert_operation(
                connection,
                operation_id=operation_id,
                operation_name=operation_name,
                player_id=player_id,
                request_hash=request_hash,
                payload=payload,
                now_text=now_text,
            )
            return self._dao_hall_operation_from_payload(payload)

    # ----------------------------------------------------------- construction

    async def build_dao_hall_project(
        self,
        *,
        platform: str,
        platform_user_id: str,
        project_key: str,
        operation_id: str,
    ) -> DaoHallOperationRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._build_dao_hall_project_once,
                platform,
                platform_user_id,
                project_key,
                operation_id,
            )

    def _build_dao_hall_project_once(
        self,
        platform: str,
        platform_user_id: str,
        project_key: str,
        operation_id: str,
    ) -> DaoHallOperationRecord:
        content = self._dao_hall_content()
        definition = dao_hall_definition(content)
        project = dao_hall_project(content, project_key)
        operation_name = "social.dao_hall_build"
        request_hash = self._request_hash(
            operation_name,
            {
                "platform": platform,
                "platform_user_id": platform_user_id,
                "project_key": project.key,
            },
        )
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._dao_hall_operation(connection, operation_id, operation_name, request_hash)
            if existing is not None:
                return self._dao_hall_operation_from_payload(existing, replay=True)

            row = self._require_player(connection, platform, platform_user_id)
            player_id = int(row["id"])
            membership = self._dao_hall_membership(connection, player_id)
            if membership is None:
                raise DaoHallNotFoundError("the player is not a hall member")
            hall_id = str(membership["hall_id"])
            hall = self._dao_hall_row(connection, hall_id)
            if hall is None:
                raise DaoHallNotFoundError("dao hall row is missing")
            hall = self._dao_hall_recover_if_due(
                connection, hall, now_text=serialize_datetime(self._now())
            )
            if str(hall["status"]) == "rebuilding":
                raise DaoHallRebuildingError("the dao hall is rebuilding")
            self._dao_hall_complete_construction_if_due(
                connection, hall_id, now_text
            )
            construction = self._dao_hall_construction(connection, hall_id)
            if construction is not None:
                raise DaoHallConstructionBusyError(
                    "the dao hall already has a construction in progress"
                )
            built = self._dao_hall_built_projects(connection, hall_id)
            if project_already_built(project=project, built=built):
                raise DaoHallMemberStateError("DAO_HALL_PROJECT_BUILT", "project already built")
            if project_locked(project=project, built=built):
                raise DaoHallProjectLockedError("a required project is not built yet")
            if player_integer(row, "world_merit") < project.world_merit:
                raise DaoHallMaterialError("world merit cannot cover the project cost")

            actual = change_player_state_actual(
                connection,
                row,
                updated_at=now_text,
                value_delta={"world_merit": -project.world_merit},
            )
            if actual.get("world_merit", 0) != -project.world_merit:
                raise DaoHallMaterialError("project cost could not be fully paid")

            connection.execute(
                "INSERT INTO dao_hall_constructions("
                "hall_id, project_key, world_merit, started_at, ends_at, operation_id"
                ") VALUES (?, ?, ?, ?, ?, ?)",
                (
                    hall_id,
                    project.key,
                    project.world_merit,
                    now_text,
                    serialize_datetime(
                        now
                        + timedelta(
                            seconds=self._dao_hall_build_seconds(
                                connection, player_id, project
                            )
                        )
                    ),
                    operation_id,
                ),
            )
            build_row = self._dao_hall_construction(connection, hall_id)
            assert build_row is not None
            build_ends_at = str(build_row["ends_at"])
            self._dao_hall_ledger(
                connection,
                hall_id=hall_id,
                player_id=player_id,
                world_merit=project.world_merit,
                spirit_stones=0,
                reason=f"dao_hall.build:{project.key}",
                operation_id=operation_id,
                now_text=now_text,
            )
            built = self._dao_hall_built_projects(connection, hall_id)
            row = connection.execute("SELECT * FROM players WHERE id = ?", (player_id,)).fetchone()
            payload = self._dao_hall_payload(
                hall_id=hall_id,
                action="build",
                status=str(hall["status"]),
                core_members=self._dao_hall_core_count(connection, hall_id),
                core_capacity=effective_core_capacity(
                    definition=definition, built=built, content=content
                ),
                treasury=int(hall["treasury_spirit_stones"]),
                world_merit=player_integer(row, "world_merit") - project.world_merit,
                spirit_stones=player_currency(row),
                project_key=project.key,
                world_merit_spent=project.world_merit,
                spirit_stones_spent=0,
                build_ends_at=build_ends_at,
            )
            self._insert_operation(
                connection,
                operation_id=operation_id,
                operation_name=operation_name,
                player_id=player_id,
                request_hash=request_hash,
                payload=payload,
                now_text=now_text,
            )
            return self._dao_hall_operation_from_payload(payload)

    # ----------------------------------------------------------- maintenance

    async def maintain_dao_hall(
        self, *, platform: str, platform_user_id: str, operation_id: str
    ) -> DaoHallOperationRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._maintain_dao_hall_once, platform, platform_user_id, operation_id
            )

    def _maintain_dao_hall_once(
        self, platform: str, platform_user_id: str, operation_id: str
    ) -> DaoHallOperationRecord:
        content = self._dao_hall_content()
        definition = dao_hall_definition(content)
        operation_name = "social.dao_hall_maintain"
        request_hash = self._request_hash(
            operation_name, {"platform": platform, "platform_user_id": platform_user_id}
        )
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._dao_hall_operation(connection, operation_id, operation_name, request_hash)
            if existing is not None:
                return self._dao_hall_operation_from_payload(existing, replay=True)

            row = self._require_player(connection, platform, platform_user_id)
            player_id = int(row["id"])
            membership = self._dao_hall_membership(connection, player_id)
            if membership is None:
                raise DaoHallNotFoundError("the player is not a hall member")
            hall_id = str(membership["hall_id"])
            hall = self._dao_hall_row(connection, hall_id)
            if hall is None:
                raise DaoHallNotFoundError("dao hall row is missing")
            self._dao_hall_complete_construction_if_due(connection, hall_id, now_text)
            built = self._dao_hall_built_projects(connection, hall_id)
            due_at = maintenance_due_at(
                last_maintained_at=datetime.fromisoformat(str(hall["last_maintained_at"])),
                definition=definition,
            )
            if now < due_at and str(hall["status"]) != "rebuilding":
                raise DaoHallMemberStateError("DAO_HALL_MAINTENANCE_NOT_DUE", "maintenance is not due")
            cost = 0 if str(hall["status"]) == "rebuilding" else maintenance_cost(
                definition=definition, built=built, content=content
            )
            treasury = int(hall["treasury_spirit_stones"])
            from_treasury = min(cost, treasury)
            shortfall = cost - from_treasury
            if shortfall and player_currency(row) < shortfall:
                raise DaoHallMaterialError("neither the treasury nor the player can cover maintenance")
            if shortfall:
                # A member topping up the hall pays from their own purse; the
                # ledger keeps both halves visible.
                change_player_state_actual(
                    connection,
                    row,
                    updated_at=now_text,
                    asset_values={"spirit_stones": shortfall},
                    asset_mode="spend",
                )
            if from_treasury:
                connection.execute(
                    "UPDATE dao_halls SET treasury_spirit_stones = treasury_spirit_stones - ? "
                    "WHERE hall_id = ?",
                    (from_treasury, hall_id),
                )
            # The player row is a pre-transaction snapshot, so re-read it before
            # reporting balances.
            row = connection.execute("SELECT * FROM players WHERE id = ?", (player_id,)).fetchone()
            if cost:
                connection.execute(
                    "UPDATE dao_halls SET last_maintained_at = ?, updated_at = ? WHERE hall_id = ?",
                    (now_text, now_text, hall_id),
                )
                self._dao_hall_ledger(
                    connection,
                    hall_id=hall_id,
                    player_id=player_id,
                    world_merit=0,
                    spirit_stones=cost,
                    reason="dao_hall.maintenance",
                    operation_id=operation_id,
                    now_text=now_text,
                )
            else:
                connection.execute(
                    "UPDATE dao_halls SET last_maintained_at = ?, updated_at = ? WHERE hall_id = ?",
                    (now_text, now_text, hall_id),
                )
            payload = self._dao_hall_payload(
                hall_id=hall_id,
                action="maintain",
                status=str(hall["status"]),
                core_members=self._dao_hall_core_count(connection, hall_id),
                core_capacity=effective_core_capacity(
                    definition=definition, built=built, content=content
                ),
                treasury=treasury - from_treasury,
                world_merit=player_integer(row, "world_merit"),
                spirit_stones=player_currency(row),
                project_key=None,
                world_merit_spent=0,
                spirit_stones_spent=cost,
            )
            self._insert_operation(
                connection,
                operation_id=operation_id,
                operation_name=operation_name,
                player_id=player_id,
                request_hash=request_hash,
                payload=payload,
                now_text=now_text,
            )
            return self._dao_hall_operation_from_payload(payload)
    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _dao_hall_membership(connection: sqlite3.Connection, player_id: int) -> sqlite3.Row | None:
        return connection.execute(
            "SELECT * FROM dao_hall_members WHERE player_id = ?", (player_id,)
        ).fetchone()

    @staticmethod
    def _dao_hall_row(connection: sqlite3.Connection, hall_id: str) -> sqlite3.Row | None:
        return connection.execute(
            "SELECT * FROM dao_halls WHERE hall_id = ?", (hall_id,)
        ).fetchone()

    @staticmethod
    def _dao_hall_first_row(connection: sqlite3.Connection) -> sqlite3.Row | None:
        return connection.execute(
            "SELECT * FROM dao_halls ORDER BY created_at, hall_id LIMIT 1"
        ).fetchone()

    @staticmethod
    def _dao_hall_built_projects(connection: sqlite3.Connection, hall_id: str) -> tuple[str, ...]:
        rows = connection.execute(
            "SELECT project_key FROM dao_hall_projects WHERE hall_id = ? ORDER BY built_at, project_key",
            (hall_id,),
        ).fetchall()
        return tuple(str(row["project_key"]) for row in rows)

    @staticmethod
    def _dao_hall_construction(
        connection: sqlite3.Connection, hall_id: str
    ) -> sqlite3.Row | None:
        return connection.execute(
            "SELECT * FROM dao_hall_constructions WHERE hall_id = ?", (hall_id,)
        ).fetchone()

    @staticmethod
    def _dao_hall_construction_bonus_bp(
        connection: sqlite3.Connection, player_id: int, content: ContentBundle
    ) -> int:
        sect = connection.execute(
            "SELECT s.sect_id FROM sect_members m JOIN sects s ON s.sect_id = m.sect_id "
            "WHERE m.player_id = ? AND m.status = 'active' AND s.status = 'active' "
            "ORDER BY s.sect_id LIMIT 1",
            (player_id,),
        ).fetchone()
        if sect is None:
            return 0
        state = connection.execute(
            "SELECT route_key FROM dao_route_state WHERE sect_id = ?",
            (str(sect["sect_id"]),),
        ).fetchone()
        if state is None or str(state["route_key"]) != "route.dao_settlement.remain":
            return 0
        route = content.get(
            "dao_route", "route.dao_settlement.remain", include_locked=False
        )
        if route is None:
            return 0
        bonus = route.get("bonus")
        if not isinstance(bonus, dict):
            return 0
        if bonus.get("key") != "hall_construction_bonus_bp":
            return 0
        value = bonus.get("value_bp")
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            return 0
        return int(value)

    def _dao_hall_build_seconds(
        self,
        connection: sqlite3.Connection,
        player_id: int,
        project,
    ) -> int:
        base = int(project.build_hours) * 3600
        bonus = self._dao_hall_construction_bonus_bp(
            connection, player_id, self._dao_hall_content()
        )
        return max(60, base * 10000 // (10000 + bonus))

    def _dao_hall_complete_construction_if_due(
        self,
        connection: sqlite3.Connection,
        hall_id: str,
        now_text: str,
    ) -> str | None:
        row = self._dao_hall_construction(connection, hall_id)
        if row is None:
            return None
        if datetime.fromisoformat(str(row["ends_at"])) > datetime.fromisoformat(now_text):
            return None
        project_key = str(row["project_key"])
        connection.execute(
            "INSERT OR IGNORE INTO dao_hall_projects(hall_id, project_key, world_merit, built_at) "
            "VALUES (?, ?, ?, ?)",
            (hall_id, project_key, int(row["world_merit"]), now_text),
        )
        connection.execute(
            "UPDATE dao_halls SET contributed_world_merit = contributed_world_merit + ?, "
            "updated_at = ? WHERE hall_id = ?",
            (int(row["world_merit"]), now_text, hall_id),
        )
        connection.execute(
            "DELETE FROM dao_hall_constructions WHERE hall_id = ?", (hall_id,)
        )
        return project_key

    @staticmethod
    def _dao_hall_core_count(connection: sqlite3.Connection, hall_id: str) -> int:
        return int(
            connection.execute(
                "SELECT COUNT(*) FROM dao_hall_members WHERE hall_id = ? AND role IN ('founder', 'core')",
                (hall_id,),
            ).fetchone()[0]
        )

    @staticmethod
    def _dao_hall_ending(connection: sqlite3.Connection, player_id: int) -> str | None:
        row = connection.execute(
            "SELECT ending_key FROM endgame_endings WHERE player_id = ?", (player_id,)
        ).fetchone()
        return str(row["ending_key"]) if row is not None else None

    def _dao_hall_ledger(
        self,
        connection: sqlite3.Connection,
        *,
        hall_id: str,
        player_id: int,
        world_merit: int,
        spirit_stones: int,
        reason: str,
        operation_id: str,
        now_text: str,
    ) -> None:
        """Record one hall-wide contribution or charge for audit."""

        connection.execute(
            """
            INSERT INTO dao_hall_contributions(
                contribution_id, hall_id, player_id, world_merit, spirit_stones,
                reason, operation_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"hall-entry-{uuid4().hex}",
                hall_id,
                player_id,
                max(0, int(world_merit)),
                max(0, int(spirit_stones)),
                reason,
                operation_id,
                now_text,
            ),
        )

    @staticmethod
    def _dao_hall_payload(
        *,
        hall_id: str,
        action: str,
        status: str,
        core_members: int,
        core_capacity: int,
        treasury: int,
        world_merit: int,
        spirit_stones: int,
        project_key: str | None,
        world_merit_spent: int,
        spirit_stones_spent: int,
        build_ends_at: str | None = None,
    ) -> dict[str, Any]:
        return {
            "hall_id": hall_id,
            "action": action,
            "status": status,
            "core_members": core_members,
            "core_capacity": core_capacity,
            "treasury_spirit_stones": treasury,
            "world_merit_after": world_merit,
            "spirit_stones_after": spirit_stones,
            "project_key": project_key,
            "world_merit_spent": world_merit_spent,
            "spirit_stones_spent": spirit_stones_spent,
            "build_ends_at": build_ends_at,
        }

    @staticmethod
    def _dao_hall_operation(
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

    @staticmethod
    def _dao_hall_operation_from_payload(
        payload: dict[str, Any], *, replay: bool = False
    ) -> DaoHallOperationRecord:
        return DaoHallOperationRecord(
            hall_id=str(payload["hall_id"]),
            action=str(payload["action"]),
            status=str(payload["status"]),
            core_members=int(payload["core_members"]),
            core_capacity=int(payload["core_capacity"]),
            treasury_spirit_stones=int(payload["treasury_spirit_stones"]),
            project_key=payload.get("project_key"),
            world_merit=int(payload["world_merit_after"]),
            world_merit_after=int(payload["world_merit_after"]),
            spirit_stones_after=int(payload["spirit_stones_after"]),
            world_merit_spent=int(payload.get("world_merit_spent", 0)),
            spirit_stones_spent=int(payload.get("spirit_stones_spent", 0)),
            build_ends_at=payload.get("build_ends_at"),
            rebuild_ends_at=payload.get("rebuild_ends_at"),
            already_completed=replay,
        )

    # -------------------------------------------------------------- rebuilding

    async def damage_dao_hall(
        self, *, platform: str, platform_user_id: str, operation_id: str
    ) -> DaoHallOperationRecord:
        """Put the hall into its 72-hour rebuild window.

        Destruction itself belongs to the (still closed) settlement war, so this
        entry point is what a war settlement will call later; it is also what
        makes the frozen rebuild semantics reachable and testable today.
        """

        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._damage_dao_hall_once, platform, platform_user_id, operation_id
            )

    def _damage_dao_hall_once(
        self, platform: str, platform_user_id: str, operation_id: str
    ) -> DaoHallOperationRecord:
        content = self._dao_hall_content()
        definition = dao_hall_definition(content)
        operation_name = "social.dao_hall_damage"
        request_hash = self._request_hash(
            operation_name, {"platform": platform, "platform_user_id": platform_user_id}
        )
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = self._dao_hall_operation(connection, operation_id, operation_name, request_hash)
            if existing is not None:
                return self._dao_hall_operation_from_payload(existing, replay=True)

            row = self._require_player(connection, platform, platform_user_id)
            membership = self._dao_hall_membership(connection, int(row["id"]))
            if membership is None:
                raise DaoHallNotFoundError("the player is not a hall member")
            if str(membership["role"]) not in {"founder", "core"}:
                raise DaoHallMemberStateError(
                    "DAO_HALL_CORE_REQUIRED", "only core members may record hall damage"
                )
            hall_id = str(membership["hall_id"])
            hall = self._dao_hall_row(connection, hall_id)
            if hall is None:
                raise DaoHallNotFoundError("dao hall row is missing")
            self._dao_hall_complete_construction_if_due(connection, hall_id, now_text)
            built = self._dao_hall_built_projects(connection, hall_id)
            hours = rebuild_hours(definition=definition, built=built, content=content)
            ends_at = serialize_datetime(now + timedelta(hours=hours))
            connection.execute(
                "UPDATE dao_halls SET status = 'rebuilding', rebuild_ends_at = ?, updated_at = ? "
                "WHERE hall_id = ?",
                (ends_at, now_text, hall_id),
            )
            payload = self._dao_hall_payload(
                hall_id=hall_id,
                action="damage",
                status="rebuilding",
                core_members=self._dao_hall_core_count(connection, hall_id),
                core_capacity=effective_core_capacity(
                    definition=definition, built=built, content=content
                ),
                treasury=int(hall["treasury_spirit_stones"]),
                world_merit=player_integer(row, "world_merit"),
                spirit_stones=player_currency(row),
                project_key=None,
                world_merit_spent=0,
                spirit_stones_spent=0,
            )
            payload["rebuild_ends_at"] = ends_at
            self._insert_operation(
                connection,
                operation_id=operation_id,
                operation_name=operation_name,
                player_id=int(row["id"]),
                request_hash=request_hash,
                payload=payload,
                now_text=now_text,
            )
            return self._dao_hall_operation_from_payload(payload)

    def _dao_hall_recover_if_due(
        self, connection: sqlite3.Connection, hall: sqlite3.Row, *, now_text: str
    ) -> sqlite3.Row:
        """Restore a hall whose rebuild window has elapsed and settle
        construction that has reached its finish time.

        Recovery is idempotent and keeps every member and built project, which
        is exactly what social v0.6 froze ("重建完成后恢复原路线").
        """

        if str(hall["status"]) != "rebuilding":
            self._dao_hall_complete_construction_if_due(
                connection, str(hall["hall_id"]), now_text
            )
            return hall
        ends_at = hall["rebuild_ends_at"]
        if ends_at is None or str(ends_at) > now_text:
            self._dao_hall_complete_construction_if_due(
                connection, str(hall["hall_id"]), now_text
            )
            return hall
        connection.execute(
            "UPDATE dao_halls SET status = 'active', rebuild_ends_at = NULL, updated_at = ? "
            "WHERE hall_id = ?",
            (now_text, str(hall["hall_id"])),
        )
        self._dao_hall_complete_construction_if_due(
            connection, str(hall["hall_id"]), now_text
        )
        return connection.execute(
            "SELECT * FROM dao_halls WHERE hall_id = ?", (str(hall["hall_id"]),)
        ).fetchone()
