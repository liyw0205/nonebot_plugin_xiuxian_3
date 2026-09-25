"""Persistence and frozen rankings for the v0.3 three-realms season."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any

from ...contracts import serialize_datetime
from ..persistence.errors import (
    OperationConflictError,
    ThreeRealmsRankingNotFinalizedError,
    ThreeRealmsRewardAlreadyClaimedError,
    ThreeRealmsRewardNotEligibleError,
)
from .three_realms_models import ThreeRealmsClaimRecord, ThreeRealmsSeasonRecord, ThreeRealmsStanding
from .three_realms_rules import (
    BOARDS,
    CONTENT_VERSION,
    RANKED_PLACES,
    RULE_VERSION,
    claim_expiry,
    reward_for_rank,
    season_window,
    season_window_for_id,
    tie_breaker,
)


class ThreeRealmsSeasonRepositoryMixin:
    async def get_three_realms_season(
        self, *, platform: str, platform_user_id: str, season_id: str | None = None, board_key: str | None = None
    ) -> ThreeRealmsSeasonRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._three_realms_get_once, platform, platform_user_id, season_id, board_key)

    async def claim_three_realms_rewards(
        self, *, platform: str, platform_user_id: str, season_id: str, operation_id: str
    ) -> ThreeRealmsClaimRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._three_realms_claim_once, platform, platform_user_id, season_id, operation_id)

    def _three_realms_get_once(self, platform: str, platform_user_id: str, requested_id: str | None, board_key: str | None) -> ThreeRealmsSeasonRecord:
        now = self._now()
        season_id, starts_at, ends_at = season_window(now) if requested_id is None else season_window_for_id(requested_id)
        claim_until = claim_expiry(ends_at)
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            player = self._require_player(connection, platform, platform_user_id, writable=False)
            self._three_realms_ensure(connection, season_id, starts_at, ends_at, claim_until, now_text)
            self._three_realms_materialize(connection, now, now_text)
            season = connection.execute("SELECT * FROM three_realms_seasons WHERE season_id=?", (season_id,)).fetchone()
            return self._three_realms_record(connection, season, int(player["id"]), board_key, starts_at, ends_at, claim_until)

    def _three_realms_claim_once(self, platform: str, platform_user_id: str, season_id: str, operation_id: str) -> ThreeRealmsClaimRecord:
        operation_name = "event.three_realms.claim"
        request_hash = self._request_hash(operation_name, {"platform": platform, "platform_user_id": platform_user_id, "season_id": season_id})
        now = self._now()
        now_text = serialize_datetime(now)
        canonical_id, starts_at, ends_at = season_window_for_id(season_id)
        claim_until = claim_expiry(ends_at)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute("SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id=?", (operation_id,)).fetchone()
            if existing is not None:
                if existing["operation_name"] != operation_name or existing["request_hash"] != request_hash:
                    raise OperationConflictError("operation input differs from its original request")
                return self._three_realms_claim_from_payload(json.loads(existing["result_json"]), replay=True)
            player = self._require_player(connection, platform, platform_user_id, writable=False)
            self._three_realms_ensure(connection, canonical_id, starts_at, ends_at, claim_until, now_text)
            self._three_realms_materialize(connection, now, now_text)
            season = connection.execute("SELECT * FROM three_realms_seasons WHERE season_id=?", (canonical_id,)).fetchone()
            if str(season["status"]) != "frozen":
                raise ThreeRealmsRankingNotFinalizedError("three-realms season is not finalized")
            if now >= claim_until:
                payload = {"season_id": canonical_id, "rewards": {}, "boards": [], "claimed_at": now_text, "expired": True}
                self._three_realms_insert_operation(connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text)
                return self._three_realms_claim_from_payload(payload)
            rows = connection.execute("SELECT board_key, rank FROM three_realms_rankings WHERE season_id=? AND player_id=? AND rank<=? ORDER BY board_key", (canonical_id, player["id"], RANKED_PLACES)).fetchall()
            if not rows:
                raise ThreeRealmsRewardNotEligibleError("player has no three-realms ranking reward")
            if connection.execute("SELECT 1 FROM three_realms_claims WHERE season_id=? AND player_id=?", (canonical_id, player["id"])).fetchone() is not None:
                raise ThreeRealmsRewardAlreadyClaimedError("three-realms reward already claimed")
            reward: dict[str, int] = {}
            boards: list[str] = []
            for row in rows:
                boards.append(str(row["board_key"]))
                for key, value in reward_for_rank(int(row["rank"])).items():
                    reward[key] = reward.get(key, 0) + value
            inventory = self._json_object(player["inventory_json"], {})
            for key, value in reward.items():
                if key.startswith("item."):
                    inventory[key] = int(inventory.get(key, 0)) + value
            connection.execute(
                "UPDATE players SET inventory_json=?, world_merit=world_merit+?, updated_at=? WHERE id=?",
                (json.dumps(inventory, ensure_ascii=False, sort_keys=True), reward.get("world_merit", 0), now_text, player["id"]),
            )
            binding_until = "9999-12-31T23:59:59+00:00"
            for item_key, value in reward.items():
                if item_key.startswith("item.") and int(value) > 0:
                    connection.execute(
                        "INSERT INTO season_item_bindings(binding_id, player_id, item_key, quantity, bound_until, season_id, source_operation_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            f"three-realms:{canonical_id}:{player['id']}:{item_key}",
                            player["id"], item_key, int(value), binding_until, canonical_id,
                            f"{operation_id}:{item_key}", now_text, now_text,
                        ),
                    )
            connection.execute("INSERT INTO three_realms_claims(season_id, player_id, operation_id, reward_json, claimed_at) VALUES (?, ?, ?, ?, ?)", (canonical_id, player["id"], operation_id, json.dumps(reward, sort_keys=True), now_text))
            connection.execute("UPDATE three_realms_rankings SET claimed_at=? WHERE season_id=? AND player_id=?", (now_text, canonical_id, player["id"]))
            payload = {"season_id": canonical_id, "rewards": reward, "boards": sorted(set(boards)), "claimed_at": now_text, "expired": False}
            self._three_realms_insert_operation(connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text)
            return self._three_realms_claim_from_payload(payload)

    @staticmethod
    def _three_realms_ensure(connection: Any, season_id: str, starts_at: datetime, ends_at: datetime, claim_until: datetime, now_text: str) -> None:
        connection.execute(
            "INSERT OR IGNORE INTO three_realms_seasons(season_id, starts_at, ends_at, claim_expires_at, status, snapshot_json, rule_version, created_at, updated_at) VALUES (?, ?, ?, ?, 'collecting', '{}', ?, ?, ?)",
            (season_id, serialize_datetime(starts_at), serialize_datetime(ends_at), serialize_datetime(claim_until), RULE_VERSION, now_text, now_text),
        )

    def _three_realms_materialize(self, connection: Any, now: datetime, now_text: str) -> None:
        season_ids = [str(row["season_id"]) for row in connection.execute("SELECT season_id FROM three_realms_seasons").fetchall()]
        current_id, current_start, current_end = season_window(now)
        if current_id not in season_ids:
            self._three_realms_ensure(connection, current_id, current_start, current_end, claim_expiry(current_end), now_text)
            season_ids.append(current_id)
        for season_id in season_ids:
            _, starts_at, ends_at = season_window_for_id(season_id)
            season = connection.execute("SELECT * FROM three_realms_seasons WHERE season_id=?", (season_id,)).fetchone()
            if str(season["status"]) == "collecting" and now >= ends_at:
                self._three_realms_freeze(connection, season, starts_at, ends_at, now_text)

    def _three_realms_freeze(self, connection: Any, season: Any, starts_at: datetime, ends_at: datetime, frozen_at: str) -> None:
        season_id = str(season["season_id"])
        board_snapshots: dict[str, list[dict[str, object]]] = {}
        for board_key in BOARDS:
            candidates = self._three_realms_candidates(connection, season_id, board_key, starts_at, ends_at)
            public: list[dict[str, object]] = []
            for rank, candidate in enumerate(candidates, start=1):
                connection.execute("INSERT INTO three_realms_rankings(season_id, board_key, player_id, rank, score, achieved_at, anonymous_label) VALUES (?, ?, ?, ?, ?, ?, ?)", (season_id, board_key, candidate["player_id"], rank, candidate["score"], candidate["achieved_at"], f"匿名道友 {rank:03d}"))
                if rank <= RANKED_PLACES:
                    public.append({"rank": rank, "anonymous_label": f"匿名道友 {rank:03d}", "score": candidate["score"], "achieved_at": candidate["achieved_at"]})
            board_snapshots[board_key] = public
        connection.execute("UPDATE three_realms_seasons SET status='frozen', snapshot_json=?, frozen_at=?, updated_at=? WHERE season_id=? AND status='collecting'", (json.dumps({"boards": board_snapshots, "frozen_at": frozen_at}, ensure_ascii=False, sort_keys=True), frozen_at, frozen_at, season_id))

    @staticmethod
    def _three_realms_candidates(connection: Any, season_id: str, board_key: str, starts_at: datetime, ends_at: datetime) -> list[dict[str, object]]:
        start_text, end_text = serialize_datetime(starts_at), serialize_datetime(ends_at)
        scores: dict[int, dict[str, object]] = {}
        if board_key == "faction_merit":
            rows = connection.execute(
                "SELECT contribution_events.player_id, SUM(contribution_events.applied_quantity) AS score, "
                "MAX(contribution_events.occurred_at) AS achieved_at "
                "FROM world_event_contribution_events AS contribution_events "
                "JOIN world_event_rounds AS rounds ON rounds.round_id=contribution_events.round_id "
                "WHERE rounds.event_key IN ('event.demon_invasion','event.beast_trade','event.boundary_rift') "
                "AND contribution_events.occurred_at>=? AND contribution_events.occurred_at<? "
                "GROUP BY contribution_events.player_id",
                (start_text, end_text),
            ).fetchall()
        elif board_key == "party_contribution":
            rows = connection.execute(
                "SELECT result_json, updated_at FROM party_battle_sessions "
                "WHERE status='settled' AND updated_at>=? AND updated_at<?",
                (start_text, end_text),
            ).fetchall()
            party_scores: dict[int, dict[str, object]] = {}
            for row in rows:
                result = json.loads(str(row["result_json"] or "{}"))
                for player_key, value in dict(result.get("contribution", {})).items():
                    player_id = int(player_key)
                    score = int(value or 0)
                    if score <= 0:
                        continue
                    current = party_scores.setdefault(player_id, {"score": 0, "achieved_at": str(row["updated_at"])})
                    current["score"] = int(current["score"]) + score
                    current["achieved_at"] = max(str(current["achieved_at"]), str(row["updated_at"]))
            rows = [{"player_id": player_id, **value} for player_id, value in party_scores.items()]
        else:
            rows = connection.execute(
                "SELECT player_id, SUM(quantity) AS score, MAX(occurred_at) AS achieved_at "
                "FROM sect_contribution_events WHERE occurred_at>=? AND occurred_at<? GROUP BY player_id",
                (start_text, end_text),
            ).fetchall()
        for row in rows:
            score = int(row["score"] or 0)
            if score > 0:
                scores[int(row["player_id"])] = {"score": score, "achieved_at": str(row["achieved_at"])}
        ordered = sorted(scores.items(), key=lambda item: (-int(item[1]["score"]), str(item[1]["achieved_at"]), tie_breaker(season_id, item[0])))
        return [{"player_id": player_id, **value} for player_id, value in ordered]

    def _three_realms_record(self, connection: Any, season: Any, player_id: int, board_key: str | None, starts_at: datetime, ends_at: datetime, claim_until: datetime) -> ThreeRealmsSeasonRecord:
        if board_key is not None and board_key not in BOARDS:
            raise ValueError("invalid three-realms board")
        keys = (board_key,) if board_key else tuple(BOARDS)
        rows: list[Any] = []
        personal: list[Any] = []
        for key in keys:
            if str(season["status"]) == "frozen":
                rows.extend(connection.execute("SELECT board_key, rank, anonymous_label, score, achieved_at FROM three_realms_rankings WHERE season_id=? AND board_key=? AND rank<=? ORDER BY rank", (season["season_id"], key, RANKED_PLACES)).fetchall())
                own = connection.execute("SELECT board_key, rank, anonymous_label, score, achieved_at FROM three_realms_rankings WHERE season_id=? AND board_key=? AND player_id=?", (season["season_id"], key, player_id)).fetchone()
                if own is not None:
                    personal.append(own)
            else:
                candidates = self._three_realms_candidates(connection, str(season["season_id"]), key, starts_at, ends_at)
                for rank, value in enumerate(candidates[:RANKED_PLACES], start=1):
                    rows.append({"board_key": key, "rank": rank, "anonymous_label": f"匿名道友 {rank:03d}", **value})
                for rank, value in enumerate(candidates, start=1):
                    if int(value["player_id"]) == player_id:
                        personal.append({"board_key": key, "rank": rank, "anonymous_label": f"匿名道友 {rank:03d}", **value})
                        break
        def standing(row: Any) -> ThreeRealmsStanding:
            return ThreeRealmsStanding(str(row["board_key"]), str(BOARDS[str(row["board_key"])] ["label"]), int(row["rank"]), str(row["anonymous_label"]), int(row["score"]), str(row["achieved_at"]))
        return ThreeRealmsSeasonRecord(str(season["season_id"]), str(season["status"]), serialize_datetime(starts_at), serialize_datetime(ends_at), serialize_datetime(claim_until), str(season["frozen_at"]) if season["frozen_at"] else None, tuple(standing(row) for row in rows), tuple(standing(row) for row in personal))

    @staticmethod
    def _three_realms_claim_from_payload(payload: dict[str, object], replay: bool = False) -> ThreeRealmsClaimRecord:
        return ThreeRealmsClaimRecord(str(payload["season_id"]), {str(k): int(v) for k, v in dict(payload.get("rewards", {})).items()}, tuple(str(value) for value in payload.get("boards", [])), str(payload["claimed_at"]), replay, bool(payload.get("expired", False)))

    @staticmethod
    def _three_realms_insert_operation(connection: Any, operation_id: str, operation_name: str, player_id: int, request_hash: str, payload: dict[str, object], now_text: str) -> None:
        connection.execute("INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)", (operation_id, operation_name, player_id, request_hash, json.dumps(payload, ensure_ascii=False, sort_keys=True), now_text))


__all__ = ["ThreeRealmsSeasonRepositoryMixin"]
