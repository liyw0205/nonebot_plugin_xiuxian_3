"""Weekly arena settlement: freeze a closed week, then pay from the frozen row.

The board and the payout are computed from ``arena_matches`` (immutable history)
and then written to ``arena_season_settlements`` once.  Claims read only that
frozen row, so later matches, later rating changes or content edits can never
move a settled week's rank or reward.  A per-match acknowledgement still pays
nothing: assets move only here, once per player per week.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import timedelta
from typing import Any

from ...contracts import serialize_datetime
from ..utils.player import grant_player_honor_title, grant_player_state, player_integer
from ..persistence.errors import (
    ArenaSeasonAlreadyClaimedError,
    ArenaSeasonClaimExpiredError,
    ArenaSeasonNotClosedError,
    ArenaSeasonNotFoundError,
    ArenaSeasonRankOutOfBoardError,
)
from .arena_content import season_record
from .arena_rules import rating_band
from .arena_season import (
    MatchEvent,
    build_board,
    claim_deadline,
    claim_is_open,
    reward_for_rank,
    week_is_closed,
    week_key,
    week_start,
    week_window_for_key,
)


class ArenaSeasonRepositoryMixin:
    """Read-only weekly board plus one frozen settlement and one claim per week."""

    async def arena_season_board(
        self, *, platform: str, platform_user_id: str, week: str | None = None
    ) -> dict[str, Any]:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._arena_season_board_once, platform, platform_user_id, week
            )

    async def claim_arena_season_reward(
        self, *, platform: str, platform_user_id: str, week: str | None, operation_id: str
    ) -> dict[str, Any]:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._arena_season_claim_once, platform, platform_user_id, week, operation_id
            )

    # -- helpers ---------------------------------------------------------

    def _season_record(self) -> dict[str, Any]:
        return season_record(getattr(self, "content", None))

    def _season_week(
        self,
        record: dict[str, Any],
        week: str | None,
        now: Any,
        *,
        default_previous: bool = False,
    ) -> tuple[str, Any, Any]:
        anchor = record["week_anchor"]
        if week:
            try:
                start, end = week_window_for_key(week, anchor)
            except ValueError as exc:
                raise ArenaSeasonNotFoundError("unknown arena week") from exc
            return week, start, end
        start = week_start(now, anchor)
        if default_previous:
            # A bare claim collects last week: the current week is still open.
            start = start - timedelta(days=7)
        _start, end = week_window_for_key(week_key(start), anchor)
        return week_key(start), start, end

    @staticmethod
    def _season_events(connection: sqlite3.Connection, end: Any) -> list[MatchEvent]:
        rows = connection.execute(
            "SELECT challenger_id, defender_id, outcome, score_counted, settled_at, "
            "challenger_rating_delta, defender_rating_delta FROM arena_matches "
            "WHERE settled_at < ?",
            (serialize_datetime(end),),
        ).fetchall()
        events: list[MatchEvent] = []
        for row in rows:
            settled = _parse(row["settled_at"])
            counted = bool(int(row["score_counted"]))
            outcome = str(row["outcome"])
            for player_id, delta, won in (
                (int(row["challenger_id"]), int(row["challenger_rating_delta"]), outcome == "challenger_won"),
                (int(row["defender_id"]), int(row["defender_rating_delta"]), outcome == "defender_won"),
            ):
                events.append(
                    MatchEvent(
                        player_id=player_id,
                        rating_delta=delta,
                        counted=counted,
                        outcome="draw" if outcome == "draw" else ("won" if won else "lost"),
                        settled_at=settled,
                    )
                )
        return events

    def _frozen_rows(self, connection: sqlite3.Connection, key: str) -> list[sqlite3.Row]:
        return connection.execute(
            "SELECT * FROM arena_season_settlements WHERE week_key = ? ORDER BY rank",
            (key,),
        ).fetchall()

    def _freeze_week(
        self, connection: sqlite3.Connection, key: str, start: Any, end: Any, now_text: str
    ) -> list[sqlite3.Row]:
        existing = self._frozen_rows(connection, key)
        if existing:
            return existing
        record = self._season_record()
        board = build_board(self._season_events(connection, end), start=start, end=end)
        for entry in board[: int(record["board_size"])]:
            reward = reward_for_rank(record, entry.rank, board_size=int(record["board_size"]))
            connection.execute(
                "INSERT OR IGNORE INTO arena_season_settlements("
                "week_key, player_id, rank, rating, wins, losses, draws, tier, reward_json, frozen_at"
                ") VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    key,
                    entry.player_id,
                    entry.rank,
                    entry.rating,
                    entry.wins,
                    entry.losses,
                    entry.draws,
                    rating_band(entry.rating),
                    json.dumps(reward, ensure_ascii=False, sort_keys=True),
                    now_text,
                ),
            )
        return self._frozen_rows(connection, key)

    def _board_payload(
        self,
        rows: list[sqlite3.Row],
        *,
        key: str,
        start: Any,
        end: Any,
        closed: bool,
        player_id: int | None,
        claimed: bool,
        claimable: bool,
        deadline: Any,
        expired: bool,
    ) -> dict[str, Any]:
        board: list[dict[str, Any]] = []
        mine: dict[str, Any] | None = None
        for row in rows:
            entry = {
                "rank": int(row["rank"]),
                "rating": int(row["rating"]),
                "wins": int(row["wins"]),
                "losses": int(row["losses"]),
                "draws": int(row["draws"]),
                "tier": int(row["tier"]),
                "reward": json.loads(row["reward_json"] or "{}"),
            }
            board.append(entry)
            if player_id is not None and int(row["player_id"]) == int(player_id):
                mine = dict(entry)
        return {
            "week_key": key,
            "starts_at": serialize_datetime(start),
            "ends_at": serialize_datetime(end),
            "closed": closed,
            "board": board,
            "mine": mine,
            "claimable": bool(claimable and mine),
            "claimed": claimed,
            "claim_deadline": serialize_datetime(deadline),
            "claim_expired": bool(expired and mine),
        }

    # -- transactions ----------------------------------------------------

    def _arena_season_board_once(
        self, platform: str, platform_user_id: str, week: str | None
    ) -> dict[str, Any]:
        record = self._season_record()
        now = self._now()
        key, start, end = self._season_week(record, week, now)
        closed = week_is_closed(key, record["week_anchor"], now)
        with self._connect() as connection:
            player = self._arena_require_player(connection, platform, platform_user_id, writable=False)
            player_id = int(player["id"])
            rows = self._frozen_rows(connection, key)
            if not rows:
                # A live week shows its current standing; a closed-but-unfrozen
                # week shows exactly what settlement will freeze.  Either way the
                # read writes nothing.
                board = build_board(self._season_events(connection, end), start=start, end=end)
                rows = [
                    {
                        "player_id": entry.player_id,
                        "rank": entry.rank,
                        "rating": entry.rating,
                        "wins": entry.wins,
                        "losses": entry.losses,
                        "draws": entry.draws,
                        "tier": rating_band(entry.rating),
                        "reward_json": json.dumps(
                            reward_for_rank(record, entry.rank, board_size=int(record["board_size"])),
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                    }
                    for entry in board[: int(record["board_size"])]
                ]
            claimed = connection.execute(
                "SELECT 1 FROM arena_season_claims WHERE week_key = ? AND player_id = ?",
                (key, player_id),
            ).fetchone() is not None
            previous_key, previous_start, previous_end = self._season_week(
                record, None, now, default_previous=True
            )
            previous_rows = self._frozen_rows(connection, previous_key)
            if not previous_rows:
                previous_board = build_board(
                    self._season_events(connection, previous_end),
                    start=previous_start,
                    end=previous_end,
                )
                previous_rows = [
                    {
                        "player_id": entry.player_id,
                        "rank": entry.rank,
                        "rating": entry.rating,
                        "wins": entry.wins,
                        "losses": entry.losses,
                        "draws": entry.draws,
                        "tier": rating_band(entry.rating),
                        "reward_json": json.dumps(
                            reward_for_rank(record, entry.rank, board_size=int(record["board_size"])),
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                    }
                    for entry in previous_board[: int(record["board_size"])]
                ]
            previous_claimed = connection.execute(
                "SELECT 1 FROM arena_season_claims WHERE week_key = ? AND player_id = ?",
                (previous_key, player_id),
            ).fetchone() is not None
        still_open = claim_is_open(key, record["week_anchor"], now)
        payload = self._board_payload(
            rows,
            key=key,
            start=start,
            end=end,
            closed=closed,
            player_id=player_id,
            claimed=claimed,
            claimable=bool(closed and not claimed and still_open),
            deadline=claim_deadline(key, record["week_anchor"]),
            expired=bool(closed and not claimed and not still_open),
        )
        previous_open = claim_is_open(previous_key, record["week_anchor"], now)
        previous_payload = self._board_payload(
            previous_rows,
            key=previous_key,
            start=previous_start,
            end=previous_end,
            closed=True,
            player_id=player_id,
            claimed=previous_claimed,
            claimable=bool(not previous_claimed and previous_open),
            deadline=claim_deadline(previous_key, record["week_anchor"]),
            expired=bool(not previous_claimed and not previous_open),
        )
        payload["previous"] = {
            "week_key": previous_key,
            "mine": previous_payload["mine"],
            "claimable": previous_payload["claimable"],
            "claimed": previous_payload["claimed"],
        }
        return payload

    def _arena_season_claim_once(
        self, platform: str, platform_user_id: str, week: str | None, operation_id: str
    ) -> dict[str, Any]:
        operation_name = "specials.claim_arena_season"
        record = self._season_record()
        now = self._now()
        now_text = serialize_datetime(now)
        key, start, end = self._season_week(record, week, now, default_previous=True)
        request_hash = self._request_hash(
            operation_name,
            {"platform": platform, "platform_user_id": platform_user_id, "week_key": key},
        )
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._arena_operation(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                payload = dict(replay)
                payload["idempotent_replay"] = True
                return payload
            player = self._arena_require_player(connection, platform, platform_user_id)
            player_id = int(player["id"])
            if not week_is_closed(key, record["week_anchor"], now):
                raise ArenaSeasonNotClosedError("the arena week is still open")
            if not claim_is_open(key, record["week_anchor"], now):
                raise ArenaSeasonClaimExpiredError("the arena claim window has closed")
            rows = self._freeze_week(connection, key, start, end, now_text)
            mine = next((row for row in rows if int(row["player_id"]) == player_id), None)
            if mine is None or int(mine["rank"]) > int(record["board_size"]):
                raise ArenaSeasonRankOutOfBoardError("the player is outside the rewarded board")
            if connection.execute(
                "SELECT 1 FROM arena_season_claims WHERE week_key = ? AND player_id = ?",
                (key, player_id),
            ).fetchone() is not None:
                raise ArenaSeasonAlreadyClaimedError("the arena week reward is already claimed")

            reward = json.loads(mine["reward_json"] or "{}")
            rank = int(mine["rank"])
            items = {key_: int(value) for key_, value in reward.items() if key_.startswith("item.")}
            local = int(reward.get("local_reputation", 0))
            stones = int(reward.get("spirit_stones", 0))
            grant_player_state(
                connection,
                player,
                items or None,
                now_text,
                value_delta={"spirit_stones": stones} if stones else None,
                local_reputation_delta={record["local_reputation_key"]: local} if local else None,
            )
            title_granted = False
            if rank == 1:
                title_granted = grant_player_honor_title(
                    connection, player_id, str(record["title_key"]), operation_id, now_text
                )
            connection.execute(
                "INSERT INTO arena_season_claims(week_key, player_id, operation_id, rank, reward_json, claimed_at) "
                "VALUES (?,?,?,?,?,?)",
                (key, player_id, operation_id, rank, json.dumps(reward, ensure_ascii=False, sort_keys=True), now_text),
            )
            payload = {
                "week_key": key,
                "rank": rank,
                "rating": int(mine["rating"]),
                "reward": reward,
                "local_reputation_key": record["local_reputation_key"],
                "title_key": record["title_key"] if title_granted else None,
                "claimed_at": now_text,
            }
            self._arena_insert_operation(
                connection, operation_id, operation_name, player_id, request_hash, payload, now_text
            )
            return payload


def _parse(value: Any) -> Any:
    from datetime import datetime

    return datetime.fromisoformat(str(value))


__all__ = ["ArenaSeasonRepositoryMixin"]
