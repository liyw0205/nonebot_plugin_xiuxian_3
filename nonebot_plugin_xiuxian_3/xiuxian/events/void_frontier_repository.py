"""SQLite transactions for the independent v0.5 void-frontier season.

The season is a projection of server-owned records.  It does not accept a
client supplied score and it does not reuse the cross-server war reward box,
because its seven-day conversion and anonymous ranking have different
lifecycles.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from typing import Any, Mapping

from ...contracts import serialize_datetime
from ..persistence.errors import (
    OperationConflictError,
    PlayerNotFoundError,
    VoidFrontierRewardAlreadyClaimedError,
    VoidFrontierRewardExpiredError,
    VoidFrontierRewardNotEligibleError,
    VoidFrontierSeasonNotFinalizedError,
    VoidFrontierWeeklyNotAvailableError,
)
from .void_frontier_models import (
    VoidFrontierClaimRecord,
    VoidFrontierSeasonRecord,
    VoidFrontierStanding,
    VoidFrontierWeeklyRecord,
)
from .void_frontier_rules import (
    CLAIM_DAYS,
    CONTENT_VERSION,
    RANKED_PLACES,
    RULE_VERSION,
    SCORE_VALUES,
    SEASON_KEY,
    WEEKLY_CAP,
    anonymous_label,
    claim_expiry,
    reward_for_rank,
    season_window,
    season_window_for_id,
    week_id,
)


class VoidFrontierRepositoryMixin:
    """Own score projection, season freeze, weekly boxes, and claims."""

    async def get_void_frontier_season(
        self, *, platform: str, platform_user_id: str, season_id: str | None = None
    ) -> VoidFrontierSeasonRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._vf_get_once, platform, platform_user_id, season_id)

    async def claim_void_frontier_weekly(
        self,
        *,
        platform: str,
        platform_user_id: str,
        operation_id: str,
        week_id_value: str | None = None,
    ) -> VoidFrontierWeeklyRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._vf_claim_weekly_once,
                platform,
                platform_user_id,
                operation_id,
                week_id_value,
            )

    async def claim_void_frontier_reward(
        self,
        *,
        platform: str,
        platform_user_id: str,
        season_id: str,
        operation_id: str,
    ) -> VoidFrontierClaimRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._vf_claim_reward_once,
                platform,
                platform_user_id,
                season_id,
                operation_id,
            )

    # Stable names for adapters and operational jobs.
    get_season_void_frontier = get_void_frontier_season
    claim_void_frontier_weekly_task = claim_void_frontier_weekly
    claim_season_void_frontier_reward = claim_void_frontier_reward

    def _vf_get_once(self, platform: str, platform_user_id: str, requested_id: str | None) -> VoidFrontierSeasonRecord:
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            player = self._require_player(connection, platform, platform_user_id, writable=False)
            season = self._vf_get_or_create(connection, requested_id, now)
            self._vf_project_sources(connection, season, now)
            self._vf_convert_expired(connection, now)
            season = connection.execute("SELECT * FROM void_frontier_seasons WHERE season_id=?", (season["season_id"],)).fetchone()
            if str(season["status"]) == "collecting" and now >= datetime.fromisoformat(str(season["ends_at"])):
                self._vf_freeze(connection, season, now)
                season = connection.execute("SELECT * FROM void_frontier_seasons WHERE season_id=?", (season["season_id"],)).fetchone()
            # A late first read can both freeze a season and cross its claim
            # deadline; convert pending boxes in the same transaction.
            self._vf_convert_expired(connection, now)
            return self._vf_record(connection, season, int(player["id"]), now_text)

    def _vf_claim_weekly_once(
        self,
        platform: str,
        platform_user_id: str,
        operation_id: str,
        requested_week_id: str | None,
    ) -> VoidFrontierWeeklyRecord:
        operation_name = "event.void_frontier.weekly.claim"
        request_hash = self._request_hash(
            operation_name,
            {"platform": platform, "platform_user_id": platform_user_id, "week_id": requested_week_id or ""},
        )
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._vf_operation(connection, operation_id, operation_name, request_hash)
            player = self._require_player(connection, platform, platform_user_id)
            current_id, starts_at, ends_at = season_window(now)
            season = self._vf_get_or_create(connection, current_id, now)
            self._vf_project_sources(connection, season, now)
            self._vf_convert_expired(connection, now)
            selected_week = requested_week_id or week_id(now)
            if replay is not None:
                return self._vf_weekly_from_payload(replay, already_completed=True)
            pending = connection.execute(
                """
                SELECT * FROM void_frontier_weekly_rewards
                WHERE player_id=? AND week_id=? AND status='pending'
                ORDER BY id ASC LIMIT 1
                """,
                (player["id"], selected_week),
            ).fetchone()
            if pending is None:
                raise VoidFrontierWeeklyNotAvailableError("no pending void-frontier weekly reward")
            reward = self._json_object(pending["reward_json"], {"void_merit": 20, "alliance_points": 10})
            connection.execute(
                "UPDATE players SET void_merit=void_merit+?, alliance_points=alliance_points+?, updated_at=? WHERE id=?",
                (int(reward.get("void_merit", 20)), int(reward.get("alliance_points", 10)), now_text, player["id"]),
            )
            connection.execute(
                "UPDATE void_frontier_weekly_rewards SET status='claimed', claim_operation_id=?, claimed_at=? WHERE id=?",
                (operation_id, now_text, pending["id"]),
            )
            payload = {
                "week_id": str(pending["week_id"]),
                "season_id": str(pending["season_id"]),
                "reward": {str(key): int(value) for key, value in reward.items() if key != "bound"},
                "status": "claimed",
                "source_key": str(pending["source_key"]),
            }
            self._vf_insert_operation(connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text)
            return self._vf_weekly_from_payload(payload)

    def _vf_claim_reward_once(
        self,
        platform: str,
        platform_user_id: str,
        season_id: str,
        operation_id: str,
    ) -> VoidFrontierClaimRecord:
        operation_name = "event.void_frontier.season.claim"
        request_hash = self._request_hash(
            operation_name,
            {"platform": platform, "platform_user_id": platform_user_id, "season_id": season_id},
        )
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._vf_operation(connection, operation_id, operation_name, request_hash)
            player = self._require_player(connection, platform, platform_user_id)
            season = self._vf_get_or_create(connection, season_id, now)
            self._vf_project_sources(connection, season, now)
            if str(season["status"]) == "collecting" and now >= datetime.fromisoformat(str(season["ends_at"])):
                self._vf_freeze(connection, season, now)
                season = connection.execute("SELECT * FROM void_frontier_seasons WHERE season_id=?", (season_id,)).fetchone()
            self._vf_convert_expired(connection, now)
            if replay is not None:
                return self._vf_claim_from_payload(replay, already_completed=True)
            if str(season["status"]) != "frozen":
                raise VoidFrontierSeasonNotFinalizedError("void-frontier season is not frozen")
            if now >= datetime.fromisoformat(str(season["claim_expires_at"])):
                raise VoidFrontierRewardExpiredError("void-frontier reward window expired")
            ranking = connection.execute(
                "SELECT rank FROM void_frontier_rankings WHERE season_id=? AND board_key='player_score' AND player_id=?",
                (season_id, player["id"]),
            ).fetchone()
            if ranking is None or int(ranking["rank"]) > RANKED_PLACES:
                raise VoidFrontierRewardNotEligibleError("player is not ranked")
            if connection.execute("SELECT 1 FROM void_frontier_claims WHERE season_id=? AND player_id=?", (season_id, player["id"])).fetchone() is not None:
                raise VoidFrontierRewardAlreadyClaimedError("void-frontier reward already claimed")
            rank = int(ranking["rank"])
            reward = reward_for_rank(rank)
            inventory = self._json_object(player["inventory_json"], {})
            inventory["item.void_crystal"] = int(inventory.get("item.void_crystal", 0)) + int(reward.get("item.void_crystal", 0))
            connection.execute(
                "UPDATE players SET inventory_json=?, void_merit=void_merit+?, updated_at=? WHERE id=?",
                (json.dumps(inventory, ensure_ascii=False, sort_keys=True), int(reward.get("void_merit", 0)), now_text, player["id"]),
            )
            connection.execute(
                "INSERT INTO void_frontier_claims(season_id,player_id,operation_id,reward_json,rank,claimed_at) VALUES (?,?,?,?,?,?)",
                (season_id, player["id"], operation_id, json.dumps(reward, sort_keys=True), rank, now_text),
            )
            payload = {"season_id": season_id, "rewards": reward, "rank": rank, "claimed_at": now_text}
            self._vf_insert_operation(connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text)
            return self._vf_claim_from_payload(payload)

    def _vf_get_or_create(self, connection: Any, requested_id: str | None, now: datetime) -> Any:
        if requested_id is None:
            season_id, starts_at, ends_at = season_window(now)
        else:
            season_id, starts_at, ends_at = season_window_for_id(requested_id)
        row = connection.execute("SELECT * FROM void_frontier_seasons WHERE season_id=?", (season_id,)).fetchone()
        if row is None:
            now_text = serialize_datetime(now)
            connection.execute(
                "INSERT INTO void_frontier_seasons(season_id,starts_at,ends_at,claim_expires_at,status,frozen_at,snapshot_json,content_version,rule_version,created_at,updated_at) VALUES (?,?,?,?, 'collecting',NULL,'{}',?,?,?,?)",
                (season_id, serialize_datetime(starts_at), serialize_datetime(ends_at), serialize_datetime(claim_expiry(ends_at)), CONTENT_VERSION, RULE_VERSION, now_text, now_text),
            )
            row = connection.execute("SELECT * FROM void_frontier_seasons WHERE season_id=?", (season_id,)).fetchone()
        return row

    def _vf_project_sources(self, connection: Any, season: Any, now: datetime) -> None:
        if str(season["status"]) != "collecting":
            return
        starts = str(season["starts_at"])
        ends = str(season["ends_at"])
        season_id = str(season["season_id"])
        route_rows = connection.execute(
            "SELECT player_id,operation_id,updated_at FROM void_route_sessions WHERE status='settled' AND route_key LIKE 'void.%' AND updated_at>=? AND updated_at<?",
            (starts, ends),
        ).fetchall()
        for row in route_rows:
            self._vf_add_score_event(connection, season_id, int(row["player_id"]), "route_completed", str(row["operation_id"]), f"route:{row['operation_id']}", str(row["updated_at"]), now)

        exploration_rows = connection.execute(
            "SELECT player_id,operation_id,result_json,snapshot_json,updated_at FROM exploration_sessions WHERE status='settled' AND updated_at>=? AND updated_at<?",
            (starts, ends),
        ).fetchall()
        for row in exploration_rows:
            result = self._json_object(row["result_json"], {})
            snapshot = self._json_object(row["snapshot_json"], {})
            storm_event = str(snapshot.get("event_key", "")) == "event.void_storm" or str(snapshot.get("event_pool", "")) == "event.void_storm"
            rescued = bool(result.get("storm_rescued")) or str(result.get("storm_choice", "")) == "rescue"
            if storm_event and rescued:
                self._vf_add_score_event(connection, season_id, int(row["player_id"]), "storm_rescue", str(row["operation_id"]), f"storm:{row['operation_id']}", str(row["updated_at"]), now)

        storm_operations = connection.execute(
            "SELECT operation_id,player_id,created_at,result_json FROM operations WHERE operation_name IN ('event.void_storm.rescue','void_storm.rescue','exploration.storm') AND created_at>=? AND created_at<?",
            (starts, ends),
        ).fetchall()
        for row in storm_operations:
            result = self._json_object(row["result_json"], {})
            if str(row["operation_id"]).startswith("event.void_storm") or bool(result.get("storm_rescued")) or bool(result.get("void_storm_rescue")) or str(result.get("storm_choice", "")) == "rescue":
                self._vf_add_score_event(connection, season_id, int(row["player_id"]), "storm_rescue", str(row["operation_id"]), f"storm:{row['operation_id']}", str(row["created_at"]), now)

        victory_rows = connection.execute(
            """
            SELECT m.player_id,m.sect_id,r.round_id,r.operation_id,r.settled_at
            FROM sect_cross_server_war_registrations r
            JOIN sect_cross_server_war_members m ON m.round_id=r.round_id AND m.sect_id=r.sect_id
            WHERE r.winner=1 AND r.settled_at>=? AND r.settled_at<?
            """,
            (starts, ends),
        ).fetchall()
        for row in victory_rows:
            source = f"cross-server:{row['round_id']}:{row['player_id']}"
            self._vf_add_score_event(connection, season_id, int(row["player_id"]), "cross_server_victory", str(row["operation_id"]), source, str(row["settled_at"]), now, sect_id=str(row["sect_id"]))

        alliance_rows = connection.execute(
            """
            SELECT a.alliance_id,a.ends_at,a.sect_a_id,a.sect_b_id,
                   sa.leader_id AS leader_a,sb.leader_id AS leader_b
            FROM sect_alliance_contracts a
            JOIN sects sa ON sa.sect_id=a.sect_a_id
            JOIN sects sb ON sb.sect_id=a.sect_b_id
            WHERE a.ends_at>=? AND a.ends_at<?
              AND (a.status IN ('active','expired') OR (a.status='ended' AND a.breach_fee_operation_id IS NULL))
            """,
            (starts, ends),
        ).fetchall()
        for row in alliance_rows:
            for player_id, sect_id in ((row["leader_a"], row["sect_a_id"]), (row["leader_b"], row["sect_b_id"])):
                source = f"alliance:{row['alliance_id']}:{player_id}"
                self._vf_add_score_event(connection, season_id, int(player_id), "alliance_contract", f"alliance:{row['alliance_id']}", source, str(row["ends_at"]), now, sect_id=str(sect_id))

    def _vf_add_score_event(
        self,
        connection: Any,
        season_id: str,
        player_id: int,
        score_key: str,
        source_operation_id: str,
        source_key: str,
        occurred_at: str,
        now: datetime,
        *,
        sect_id: str | None = None,
    ) -> None:
        points = int(SCORE_VALUES[score_key])
        if sect_id is None:
            membership = connection.execute(
                "SELECT sect_id FROM sect_members WHERE player_id=? AND status='active' ORDER BY id DESC LIMIT 1",
                (player_id,),
            ).fetchone()
            sect_id = str(membership["sect_id"]) if membership is not None else None
        connection.execute(
            "INSERT OR IGNORE INTO void_frontier_score_events(season_id,player_id,sect_id,score_key,points,source_operation_id,source_key,occurred_at) VALUES (?,?,?,?,?,?,?,?)",
            (season_id, player_id, sect_id, score_key, points, source_operation_id, source_key, occurred_at),
        )
        if connection.execute("SELECT changes()").fetchone()[0] != 1:
            return
        current_week = week_id(datetime.fromisoformat(occurred_at))
        count = int(connection.execute("SELECT COUNT(*) FROM void_frontier_weekly_rewards WHERE week_id=? AND player_id=?", (current_week, player_id)).fetchone()[0])
        if count >= WEEKLY_CAP:
            return
        connection.execute(
            "INSERT OR IGNORE INTO void_frontier_weekly_rewards(season_id,week_id,player_id,source_key,source_operation_id,reward_json,status,created_at) VALUES (?,?,?,?,?,?, 'pending', ?)",
            (season_id, current_week, player_id, source_key, source_operation_id, json.dumps({"void_merit": 20, "alliance_points": 10}, sort_keys=True), serialize_datetime(now)),
        )

    def _vf_freeze(self, connection: Any, season: Any, now: datetime) -> None:
        season_id = str(season["season_id"])
        now_text = serialize_datetime(now)
        player_rows = connection.execute(
            "SELECT player_id,COALESCE(MAX(occurred_at),'') AS achieved_at,SUM(points) AS score FROM void_frontier_score_events WHERE season_id=? GROUP BY player_id ORDER BY score DESC, achieved_at ASC, player_id ASC",
            (season_id,),
        ).fetchall()
        for rank, row in enumerate(player_rows[:RANKED_PLACES], start=1):
            connection.execute(
                "INSERT OR IGNORE INTO void_frontier_rankings(season_id,board_key,player_id,sect_id,rank,score,achieved_at,anonymous_label) VALUES (?,?,?,?,?,?,?,?)",
                (season_id, "player_score", row["player_id"], None, rank, int(row["score"]), str(row["achieved_at"]), anonymous_label(f"{season_id}:player", row["player_id"])),
            )
        sect_rows = connection.execute(
            "SELECT sect_id,COALESCE(MAX(occurred_at),'') AS achieved_at,SUM(points) AS score FROM void_frontier_score_events WHERE season_id=? AND sect_id IS NOT NULL GROUP BY sect_id ORDER BY score DESC, achieved_at ASC, sect_id ASC",
            (season_id,),
        ).fetchall()
        for rank, row in enumerate(sect_rows[:RANKED_PLACES], start=1):
            connection.execute(
                "INSERT OR IGNORE INTO void_frontier_rankings(season_id,board_key,player_id,sect_id,rank,score,achieved_at,anonymous_label) VALUES (?,?,?,?,?,?,?,?)",
                (season_id, "sect_score", None, row["sect_id"], rank, int(row["score"]), str(row["achieved_at"]), anonymous_label(f"{season_id}:sect", row["sect_id"])),
            )
            if rank <= 3:
                connection.execute(
                    "INSERT OR IGNORE INTO void_frontier_sect_priorities(season_id,sect_id,rank,starts_at,ends_at) VALUES (?,?,?,?,?)",
                    (season_id, row["sect_id"], rank, str(season["ends_at"]), serialize_datetime(datetime.fromisoformat(str(season["ends_at"])) + timedelta(days=7))),
                )
        connection.execute(
            "UPDATE void_frontier_seasons SET status='frozen',frozen_at=?,snapshot_json=?,updated_at=? WHERE season_id=? AND status='collecting'",
            (now_text, json.dumps({"score_events": len(player_rows), "rule_version": RULE_VERSION}, sort_keys=True), now_text, season_id),
        )

    def _vf_convert_expired(self, connection: Any, now: datetime) -> None:
        now_text = serialize_datetime(now)
        seasons = connection.execute("SELECT season_id FROM void_frontier_seasons WHERE status='frozen' AND claim_expires_at<=?", (now_text,)).fetchall()
        for season in seasons:
            rows = connection.execute("SELECT id,player_id,reward_json FROM void_frontier_weekly_rewards WHERE season_id=? AND status='pending'", (season["season_id"],)).fetchall()
            for row in rows:
                reward = self._json_object(row["reward_json"], {})
                merit = int(reward.get("void_merit", 20))
                connection.execute("UPDATE players SET void_merit=void_merit+?,updated_at=? WHERE id=?", (merit, now_text, row["player_id"]))
                reward["bound"] = True
                reward.pop("alliance_points", None)
                connection.execute("UPDATE void_frontier_weekly_rewards SET status='converted',reward_json=?,claimed_at=? WHERE id=?", (json.dumps(reward, sort_keys=True), now_text, row["id"]))

    def _vf_record(self, connection: Any, season: Any, player_id: int, now_text: str) -> VoidFrontierSeasonRecord:
        status = str(season["status"])
        if status == "frozen":
            rows = connection.execute("SELECT board_key,player_id,sect_id,rank,anonymous_label,score,achieved_at FROM void_frontier_rankings WHERE season_id=? ORDER BY board_key,rank", (season["season_id"],)).fetchall()
            personal_rows = connection.execute("SELECT board_key,player_id,sect_id,rank,anonymous_label,score,achieved_at FROM void_frontier_rankings WHERE season_id=? AND board_key='player_score' AND player_id=?", (season["season_id"], player_id)).fetchall()
            sect_rows = [row for row in rows if row["board_key"] == "sect_score"]
        else:
            rows = self._vf_live_rows(connection, str(season["season_id"]))
            personal_rows = [row for row in rows if row["board_key"] == "player_score" and row["entity_id"] == str(player_id)]
            sect_rows = [row for row in rows if row["board_key"] == "sect_score"]
        priority_rows = connection.execute(
            "SELECT r.board_key,r.rank,r.anonymous_label,r.score,r.achieved_at FROM void_frontier_sect_priorities p JOIN void_frontier_rankings r ON r.season_id=p.season_id AND r.board_key='sect_score' AND r.sect_id=p.sect_id WHERE p.season_id=? ORDER BY p.rank",
            (season["season_id"],),
        ).fetchall()
        def standing(row: Any) -> VoidFrontierStanding:
            return VoidFrontierStanding(str(row["board_key"]), int(row["rank"]), str(row["anonymous_label"]), int(row["score"]), str(row["achieved_at"]))
        current_week = week_id(self._now())
        counts = connection.execute("SELECT status,COUNT(*) AS count FROM void_frontier_weekly_rewards WHERE player_id=? AND week_id=? GROUP BY status", (player_id, current_week)).fetchall()
        count_map = {str(row["status"]): int(row["count"]) for row in counts}
        return VoidFrontierSeasonRecord(
            str(season["season_id"]), status, str(season["starts_at"]), str(season["ends_at"]), str(season["claim_expires_at"]), str(season["frozen_at"]) if season["frozen_at"] else None,
            tuple(standing(row) for row in rows), tuple(standing(row) for row in personal_rows), tuple(standing(row) for row in sect_rows), tuple(standing(row) for row in priority_rows), count_map.get("pending", 0), count_map.get("claimed", 0),
        )

    def _vf_live_rows(self, connection: Any, season_id: str) -> list[dict[str, object]]:
        result: list[dict[str, object]] = []
        for board, entity_column, limit in (("player_score", "player_id", RANKED_PLACES), ("sect_score", "sect_id", RANKED_PLACES)):
            rows = connection.execute(f"SELECT {entity_column} AS entity_id,COALESCE(MAX(occurred_at),'') AS achieved_at,SUM(points) AS score FROM void_frontier_score_events WHERE season_id=? AND {entity_column} IS NOT NULL GROUP BY {entity_column} ORDER BY score DESC, achieved_at ASC, entity_id ASC LIMIT ?", (season_id, limit)).fetchall()
            result.extend({"board_key": board, "entity_id": str(row["entity_id"]), "rank": rank, "anonymous_label": anonymous_label(f"{season_id}:{board[:-6]}", row["entity_id"]), "score": int(row["score"]), "achieved_at": str(row["achieved_at"])} for rank, row in enumerate(rows, start=1))
        return result

    @staticmethod
    def _json_object(value: Any, default: Mapping[str, object] | None = None) -> dict[str, object]:
        try:
            parsed = json.loads(str(value)) if isinstance(value, str) else value
            return dict(parsed) if isinstance(parsed, dict) else dict(default or {})
        except (TypeError, ValueError, json.JSONDecodeError):
            return dict(default or {})

    @staticmethod
    def _vf_operation(connection: Any, operation_id: str, operation_name: str, request_hash: str) -> dict[str, object] | None:
        existing = connection.execute("SELECT operation_name,request_hash,result_json FROM operations WHERE operation_id=?", (operation_id,)).fetchone()
        if existing is None:
            return None
        if str(existing["operation_name"]) != operation_name or str(existing["request_hash"]) != request_hash:
            raise OperationConflictError("operation input differs from its original request")
        return VoidFrontierRepositoryMixin._json_object(existing["result_json"], {})

    @staticmethod
    def _vf_insert_operation(connection: Any, operation_id: str, operation_name: str, player_id: int, request_hash: str, payload: Mapping[str, object], now_text: str) -> None:
        connection.execute("INSERT INTO operations(operation_id,operation_name,player_id,request_hash,result_json,created_at) VALUES (?,?,?,?,?,?)", (operation_id, operation_name, player_id, request_hash, json.dumps(dict(payload), ensure_ascii=False, sort_keys=True), now_text))

    @staticmethod
    def _vf_weekly_from_payload(payload: Mapping[str, object], *, already_completed: bool = False) -> VoidFrontierWeeklyRecord:
        return VoidFrontierWeeklyRecord(str(payload["week_id"]), str(payload["season_id"]), {str(k): int(v) for k, v in dict(payload.get("reward", {})).items() if isinstance(v, (int, float))}, str(payload.get("status", "claimed")), str(payload.get("source_key", "")), already_completed)

    @staticmethod
    def _vf_claim_from_payload(payload: Mapping[str, object], *, already_completed: bool = False) -> VoidFrontierClaimRecord:
        return VoidFrontierClaimRecord(str(payload["season_id"]), {str(k): int(v) for k, v in dict(payload.get("rewards", {})).items()}, int(payload["rank"]), str(payload.get("claimed_at", "")), already_completed)


__all__ = ["VoidFrontierRepositoryMixin"]
