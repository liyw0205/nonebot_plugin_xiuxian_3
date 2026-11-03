"""SQLite transactions for 道统路线议事 (``dao.choose_route`` / ``dao.council_vote``).

A council cycle is one UTC ISO week per sect.  Votes are unique per
``(cycle, sect, player)``; the previous week is settled lazily the next time a
member of that sect votes, which keeps settlement deterministic and free of
background jobs.  Settlement is one transaction: majority (or tie carry-over),
1000 sect merit spent, route locked for seven days.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime
from typing import Any
from uuid import uuid4

from ...contracts import serialize_datetime
from ..content import ContentBundle, bundled_content
from ..persistence.errors import (
    DaoCouncilQuorumError,
    DaoRouteNotDueError,
    DaoRouteLockedError,
    DaoRouteRequirementError,
    DaoVoteAlreadyCastError,
    OperationConflictError,
)
from ..utils.player import player_integer
from .dao_route_models import (
    DaoRouteSettlementRecord,
    DaoRouteState,
    DaoRouteVoteRecord,
)
from .dao_route_rules import (
    cycle_bounds,
    dao_route_definition,
    dao_route_option,
    dao_route_option_list,
    lock_active,
    locked_until_at,
    resolve_settlement,
    vote_missing_requirements,
)


class DaoRouteRepositoryMixin:
    """Persistence for the weekly dao-route council."""

    def _dao_route_content(self) -> ContentBundle:
        content = getattr(self, "content", None)
        return content if content is not None else bundled_content()

    # ---------------------------------------------------------------- queries

    async def dao_route_status(self, *, platform: str, platform_user_id: str) -> DaoRouteState:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._dao_route_status_once, platform, platform_user_id)

    def _dao_route_status_once(self, platform: str, platform_user_id: str) -> DaoRouteState:
        content = self._dao_route_content()
        definition = dao_route_definition(content)
        options = dao_route_option_list(content)
        with self._connect() as connection:
            row = self._require_player(connection, platform, platform_user_id, writable=False)
            sect = self._dao_route_sect(connection, int(row["id"]))
            now = self._now()
            cycle_id, starts_at, ends_at = cycle_bounds(now)
            sect_id = str(sect["sect_id"]) if sect is not None else ""
            state = self._dao_route_state_row(connection, sect_id) if sect_id else None
            previous = self._dao_route_previous_cycle(connection, sect_id, cycle_id) if sect_id else None
            counts, my_vote = (
                self._dao_route_cycle_votes(connection, cycle_id, sect_id, int(row["id"]))
                if sect_id
                else ({}, None)
            )
            missing = vote_missing_requirements(
                definition=definition,
                realm_key=str(row["realm_key"]),
                realm_layer=player_integer(row, "realm_layer"),
                sect_id=sect_id or None,
                sect_level=int(sect["level"]) if sect is not None else 0,
                sect_status=str(sect["status"]) if sect is not None else "",
            )
            route_key = str(state["route_key"]) if state is not None and state["route_key"] else None
            locked_until = (
                str(state["locked_until"])
                if state is not None and state["locked_until"] is not None
                else None
            )
            return DaoRouteState(
                sect_id=sect_id,
                sect_name=str(sect["name"]) if sect is not None else "",
                sect_level=int(sect["level"]) if sect is not None else 0,
                sect_merit=int(sect["sect_merit"]) if sect is not None else 0,
                route_key=route_key,
                route_label=self._dao_route_label(content, route_key),
                locked_until=locked_until,
                locked=lock_active(locked_until=locked_until, now=now),
                cycle_id=cycle_id,
                cycle_starts_at=serialize_datetime(starts_at),
                cycle_ends_at=serialize_datetime(ends_at),
                settled=bool(previous is not None and str(previous["status"]) == "settled"),
                quorum=definition.required_voters,
                voter_count=sum(counts.values()),
                my_vote_key=my_vote,
                my_vote_label=self._dao_route_label(content, my_vote),
                eligible=not missing,
                missing=tuple(missing),
                options=options,
                tie_carryover=bool(
                    previous is not None and int(previous["tie_carryover"]) == 1
                ),
            )

    # ------------------------------------------------------------------ votes

    async def cast_dao_route_vote(
        self,
        *,
        platform: str,
        platform_user_id: str,
        route_key: str,
        operation_id: str,
    ) -> DaoRouteVoteRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._cast_dao_route_vote_once,
                platform,
                platform_user_id,
                route_key,
                operation_id,
            )

    def _cast_dao_route_vote_once(
        self, platform: str, platform_user_id: str, route_key: str, operation_id: str
    ) -> DaoRouteVoteRecord:
        content = self._dao_route_content()
        definition = dao_route_definition(content)
        option = dao_route_option(content, route_key)
        operation_name = "social.dao_route_vote"
        request_hash = self._request_hash(
            operation_name,
            {
                "platform": platform,
                "platform_user_id": platform_user_id,
                "route_key": option.key,
            },
        )
        now = self._now()
        now_text = serialize_datetime(now)
        cycle_id, starts_at, ends_at = cycle_bounds(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            if existing is not None:
                if (
                    existing["operation_name"] != operation_name
                    or existing["request_hash"] != request_hash
                ):
                    raise OperationConflictError("operation input differs from its original request")
                return self._dao_route_vote_from_payload(json.loads(existing["result_json"]), replay=True)

            row = self._require_player(connection, platform, platform_user_id)
            player_id = int(row["id"])
            sect = self._dao_route_sect(connection, player_id)
            if sect is None:
                raise DaoRouteRequirementError("the player is not an active sect member")
            missing = vote_missing_requirements(
                definition=definition,
                realm_key=str(row["realm_key"]),
                realm_layer=player_integer(row, "realm_layer"),
                sect_id=str(sect["sect_id"]),
                sect_level=int(sect["level"]),
                sect_status=str(sect["status"]),
            )
            if missing:
                raise DaoRouteRequirementError("council vote requirements are missing")
            sect_id = str(sect["sect_id"])

            # Settle the last closed cycle first: that is when the previous
            # week's majority becomes the route (and the merit is spent).
            self._settle_dao_route_cycle(
                connection,
                sect_id=sect_id,
                now=now,
                now_text=now_text,
                definition=definition,
                content=content,
            )

            self._dao_route_cycle_row(
                connection,
                cycle_id=cycle_id,
                sect_id=sect_id,
                starts_at=starts_at,
                ends_at=ends_at,
                now_text=now_text,
            )
            cast = connection.execute(
                "SELECT 1 FROM dao_route_votes WHERE cycle_id = ? AND sect_id = ? AND player_id = ?",
                (cycle_id, sect_id, player_id),
            ).fetchone()
            if cast is not None:
                raise DaoVoteAlreadyCastError("the player already voted in this cycle")

            connection.execute(
                "INSERT INTO dao_route_votes("
                " cycle_id, sect_id, player_id, route_key, operation_id, cast_at"
                ") VALUES (?, ?, ?, ?, ?, ?)",
                (cycle_id, sect_id, player_id, option.key, operation_id, now_text),
            )
            counts, _ = self._dao_route_cycle_votes(connection, cycle_id, sect_id, player_id)
            payload = {
                "sect_id": sect_id,
                "cycle_id": cycle_id,
                "route_key": option.key,
                "route_label": option.name,
                "voter_count": sum(counts.values()),
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
            return self._dao_route_vote_from_payload(payload)

    # ------------------------------------------------------------- settlement

    async def settle_dao_route(
        self, *, platform: str, platform_user_id: str, operation_id: str
    ) -> DaoRouteSettlementRecord:
        """Settle the last closed cycle on demand (also runs before each vote)."""

        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._settle_dao_route_once, platform, platform_user_id, operation_id
            )

    def _settle_dao_route_once(
        self, platform: str, platform_user_id: str, operation_id: str
    ) -> DaoRouteSettlementRecord:
        content = self._dao_route_content()
        definition = dao_route_definition(content)
        operation_name = "social.dao_route_settle"
        request_hash = self._request_hash(
            operation_name, {"platform": platform, "platform_user_id": platform_user_id}
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
                if (
                    existing["operation_name"] != operation_name
                    or existing["request_hash"] != request_hash
                ):
                    raise OperationConflictError("operation input differs from its original request")
                return self._dao_route_settlement_from_payload(
                    json.loads(existing["result_json"]), replay=True
                )

            row = self._require_player(connection, platform, platform_user_id)
            sect = self._dao_route_sect(connection, int(row["id"]))
            if sect is None:
                raise DaoRouteRequirementError("the player is not an active sect member")
            sect_id = str(sect["sect_id"])
            settled = self._settle_dao_route_cycle(
                connection,
                sect_id=sect_id,
                now=now,
                now_text=now_text,
                definition=definition,
                content=content,
            )
            if settled is None:
                # Nothing closed yet: either the route is still inside its
                # protection window, or this week simply is not over.
                state = self._dao_route_state_row(connection, sect_id)
                locked_until = (
                    str(state["locked_until"])
                    if state is not None and state["locked_until"] is not None
                    else None
                )
                if lock_active(locked_until=locked_until, now=now):
                    raise DaoRouteLockedError("the current dao route is still locked")
                raise DaoRouteNotDueError("no council cycle has closed yet")
            payload = dict(settled)
            payload["options"] = [
                {
                    "key": option.key,
                    "name": option.name,
                    "description": option.description,
                    "bonus_key": option.bonus_key,
                    "bonus_bp": option.bonus_bp,
                    "aliases": list(option.aliases),
                }
                for option in dao_route_option_list(content)
            ]
            self._insert_operation(
                connection,
                operation_id=operation_id,
                operation_name=operation_name,
                player_id=int(row["id"]),
                request_hash=request_hash,
                payload=payload,
                now_text=now_text,
            )
            return self._dao_route_settlement_from_payload(payload)

    def _settle_dao_route_cycle(
        self,
        connection: sqlite3.Connection,
        *,
        sect_id: str,
        now: datetime,
        now_text: str,
        definition,
        content: ContentBundle,
    ) -> dict[str, Any] | None:
        """Settle the most recent closed, still-open cycle of one sect."""

        cycle = connection.execute(
            "SELECT * FROM dao_route_cycles WHERE sect_id = ? AND status = 'open' "
            "ORDER BY ends_at DESC LIMIT 1",
            (sect_id,),
        ).fetchone()
        if cycle is None:
            return None
        if datetime.fromisoformat(str(cycle["ends_at"])) > now:
            return None

        cycle_id = str(cycle["cycle_id"])
        counts: dict[str, int] = {}
        for vote in connection.execute(
            "SELECT route_key, COUNT(*) AS total FROM dao_route_votes "
            "WHERE cycle_id = ? AND sect_id = ? GROUP BY route_key",
            (cycle_id, sect_id),
        ).fetchall():
            counts[str(vote["route_key"])] = int(vote["total"])
        voters = sum(counts.values())
        if voters < definition.required_voters:
            # A short council closes with no route: leaving the cycle open would
            # block every later vote behind a settlement that can never pass.
            connection.execute(
                "UPDATE dao_route_cycles SET status = 'settled', winner_route_key = NULL, "
                "tie_carryover = 0, sect_merit_spent = 0, settled_at = ? "
                "WHERE cycle_id = ? AND sect_id = ?",
                (now_text, cycle_id, sect_id),
            )
            return {
                "sect_id": sect_id,
                "cycle_id": cycle_id,
                "route_key": None,
                "route_label": None,
                "tie_carryover": False,
                "voter_count": voters,
                "sect_merit_spent": 0,
                "sect_merit_after": int(
                    connection.execute(
                        "SELECT sect_merit FROM sects WHERE sect_id = ?", (sect_id,)
                    ).fetchone()["sect_merit"]
                ),
                "locked_until": None,
                "quorum_missing": True,
            }

        state = self._dao_route_state_row(connection, sect_id)
        previous_route = (
            str(state["route_key"]) if state is not None and state["route_key"] else None
        )
        route_key, tie_carryover = resolve_settlement(
            definition=definition,
            counts=counts,
            previous_route_key=previous_route,
        )

        # A settled route stays locked for its window: a later cycle may not
        # flip it before the lock expires.
        locked_until_before = (
            str(state["locked_until"]) if state is not None and state["locked_until"] else None
        )
        if (
            route_key is not None
            and previous_route is not None
            and route_key != previous_route
            and lock_active(locked_until=locked_until_before, now=now)
        ):
            raise DaoRouteLockedError("the current dao route is still locked")

        sect = connection.execute("SELECT * FROM sects WHERE sect_id = ?", (sect_id,)).fetchone()
        merit_available = int(sect["sect_merit"]) if sect is not None else 0
        if route_key is not None and merit_available < definition.required_sect_merit:
            raise DaoRouteRequirementError("the sect cannot pay the council cost")
        spent = definition.required_sect_merit if route_key is not None else 0
        if spent:
            connection.execute(
                "UPDATE sects SET sect_merit = sect_merit - ?, updated_at = ? WHERE sect_id = ?",
                (spent, now_text, sect_id),
            )
        locked_until = (
            serialize_datetime(locked_until_at(settled_at=now, definition=definition))
            if route_key is not None
            else None
        )
        connection.execute(
            "UPDATE dao_route_cycles SET status = 'settled', winner_route_key = ?, "
            "tie_carryover = ?, sect_merit_spent = ?, settled_at = ? "
            "WHERE cycle_id = ? AND sect_id = ?",
            (
                route_key,
                1 if tie_carryover else 0,
                spent,
                now_text,
                cycle_id,
                sect_id,
            ),
        )
        connection.execute(
            """
            INSERT INTO dao_route_state(sect_id, route_key, cycle_id, locked_until, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(sect_id) DO UPDATE SET
                route_key = excluded.route_key,
                cycle_id = excluded.cycle_id,
                locked_until = excluded.locked_until,
                updated_at = excluded.updated_at
            """,
            (sect_id, route_key, cycle_id, locked_until, now_text),
        )
        after = connection.execute(
            "SELECT sect_merit FROM sects WHERE sect_id = ?", (sect_id,)
        ).fetchone()
        return {
            "sect_id": sect_id,
            "cycle_id": cycle_id,
            "route_key": route_key,
            "route_label": self._dao_route_label(content, route_key),
            "tie_carryover": tie_carryover,
            "voter_count": voters,
            "sect_merit_spent": spent,
            "sect_merit_after": int(after["sect_merit"]) if after is not None else 0,
            "locked_until": locked_until,
        }

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _dao_route_sect(connection: sqlite3.Connection, player_id: int) -> sqlite3.Row | None:
        return connection.execute(
            "SELECT s.* FROM sect_members m JOIN sects s ON s.sect_id = m.sect_id "
            "WHERE m.player_id = ? AND m.status = 'active' AND s.status = 'active' "
            "ORDER BY s.sect_id LIMIT 1",
            (player_id,),
        ).fetchone()

    @staticmethod
    def _dao_route_state_row(connection: sqlite3.Connection, sect_id: str) -> sqlite3.Row | None:
        if not sect_id:
            return None
        return connection.execute(
            "SELECT * FROM dao_route_state WHERE sect_id = ?", (sect_id,)
        ).fetchone()

    @staticmethod
    def _dao_route_previous_cycle(
        connection: sqlite3.Connection, sect_id: str, cycle_id: str
    ) -> sqlite3.Row | None:
        if not sect_id:
            return None
        return connection.execute(
            "SELECT * FROM dao_route_cycles WHERE sect_id = ? AND cycle_id <> ? "
            "ORDER BY ends_at DESC LIMIT 1",
            (sect_id, cycle_id),
        ).fetchone()

    @staticmethod
    def _dao_route_cycle_votes(
        connection: sqlite3.Connection, cycle_id: str, sect_id: str, player_id: int
    ) -> tuple[dict[str, int], str | None]:
        counts: dict[str, int] = {}
        for vote in connection.execute(
            "SELECT route_key, COUNT(*) AS total FROM dao_route_votes "
            "WHERE cycle_id = ? AND sect_id = ? GROUP BY route_key",
            (cycle_id, sect_id),
        ).fetchall():
            counts[str(vote["route_key"])] = int(vote["total"])
        mine = connection.execute(
            "SELECT route_key FROM dao_route_votes WHERE cycle_id = ? AND sect_id = ? "
            "AND player_id = ?",
            (cycle_id, sect_id, player_id),
        ).fetchone()
        return counts, (str(mine["route_key"]) if mine is not None else None)

    @staticmethod
    def _dao_route_cycle_row(
        connection: sqlite3.Connection,
        *,
        cycle_id: str,
        sect_id: str,
        starts_at: datetime,
        ends_at: datetime,
        now_text: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO dao_route_cycles(cycle_id, sect_id, starts_at, ends_at, status)
            VALUES (?, ?, ?, ?, 'open')
            ON CONFLICT(cycle_id, sect_id) DO NOTHING
            """,
            (
                cycle_id,
                sect_id,
                serialize_datetime(starts_at),
                serialize_datetime(ends_at),
            ),
        )

    def _dao_route_label(self, content: ContentBundle, route_key: str | None) -> str | None:
        if route_key is None:
            return None
        try:
            return dao_route_option(content, route_key).name
        except KeyError:
            return route_key

    @staticmethod
    def _dao_route_vote_from_payload(
        payload: dict[str, Any], *, replay: bool = False
    ) -> DaoRouteVoteRecord:
        return DaoRouteVoteRecord(
            sect_id=str(payload["sect_id"]),
            cycle_id=str(payload["cycle_id"]),
            route_key=str(payload["route_key"]),
            route_label=str(payload["route_label"]),
            voter_count=int(payload["voter_count"]),
            already_completed=replay,
        )

    @staticmethod
    def _dao_route_settlement_from_payload(
        payload: dict[str, Any], *, replay: bool = False
    ) -> DaoRouteSettlementRecord:
        from .dao_route_rules import DaoRouteOption

        return DaoRouteSettlementRecord(
            sect_id=str(payload["sect_id"]),
            cycle_id=str(payload["cycle_id"]),
            route_key=payload.get("route_key"),
            route_label=payload.get("route_label"),
            tie_carryover=bool(payload.get("tie_carryover")),
            voter_count=int(payload.get("voter_count", 0)),
            sect_merit_spent=int(payload.get("sect_merit_spent", 0)),
            sect_merit_after=int(payload.get("sect_merit_after", 0)),
            locked_until=payload.get("locked_until"),
            already_completed=replay,
            quorum_missing=bool(payload.get("quorum_missing")),
            options=tuple(
                DaoRouteOption(
                    key=str(raw["key"]),
                    name=str(raw["name"]),
                    description=str(raw["description"]),
                    bonus_key=str(raw["bonus_key"]),
                    bonus_bp=int(raw["bonus_bp"]),
                    aliases=tuple(raw.get("aliases", ())),
                )
                for raw in payload.get("options", ())
            ),
        )