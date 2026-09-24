"""Persistence and idempotent settlement for final-heaven seasons."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any

from ...contracts import serialize_datetime
from ..persistence.errors import (
    FinalHeavenRankingNotFinalizedError,
    FinalHeavenRewardAlreadyClaimedError,
    FinalHeavenRewardNotEligibleError,
    OperationConflictError,
)
from ..routine.rules import honor_title
from .season_models import FinalHeavenClaimRecord, FinalHeavenSeasonRecord, FinalHeavenStanding
from .season_rules import (
    FINAL_HEAVEN_BOARDS,
    FINAL_HEAVEN_CHAPTER_ENTITLEMENT,
    FINAL_HEAVEN_RANKED_PLACES,
    FINAL_HEAVEN_RULE_VERSION,
    final_heaven_claim_expiry,
    final_heaven_tie_breaker,
    final_heaven_window_for_id,
)
from .rules import FINAL_HEAVEN_SEASON_ANCHOR, final_heaven_season_window


class FinalHeavenSeasonRepositoryMixin:
    """Own season snapshots, anonymous standings and their display rewards."""

    async def get_final_heaven_season(
        self,
        *,
        platform: str,
        platform_user_id: str,
        season_id: str | None = None,
        board_key: str | None = None,
    ) -> FinalHeavenSeasonRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._final_heaven_get_once,
                platform,
                platform_user_id,
                season_id,
                board_key,
            )

    async def claim_final_heaven_rewards(
        self,
        *,
        platform: str,
        platform_user_id: str,
        season_id: str,
        operation_id: str,
    ) -> FinalHeavenClaimRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._final_heaven_claim_once,
                platform,
                platform_user_id,
                season_id,
                operation_id,
            )

    def _final_heaven_get_once(
        self,
        platform: str,
        platform_user_id: str,
        requested_season_id: str | None,
        board_key: str | None,
    ) -> FinalHeavenSeasonRecord:
        now = self._now()
        if requested_season_id is None:
            season_id, starts_at, ends_at = final_heaven_season_window(now)
        else:
            season_id, starts_at, ends_at = final_heaven_window_for_id(requested_season_id)
        claim_expires_at = final_heaven_claim_expiry(ends_at)
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            player = self._require_player(connection, platform, platform_user_id, writable=False)
            self._ensure_final_heaven_season(
                connection,
                season_id,
                starts_at,
                ends_at,
                claim_expires_at,
                now_text,
            )
            self._materialize_due_final_heaven_seasons(connection, now, now_text)
            season = connection.execute(
                "SELECT * FROM final_heaven_seasons WHERE season_id = ?", (season_id,)
            ).fetchone()
            if season is None:
                raise RuntimeError("final-heaven season was not created")
            return self._final_heaven_record(
                connection,
                season,
                int(player["id"]),
                board_key=board_key,
                starts_at=starts_at,
                ends_at=ends_at,
                claim_expires_at=claim_expires_at,
            )

    def _final_heaven_claim_once(
        self,
        platform: str,
        platform_user_id: str,
        season_id: str,
        operation_id: str,
    ) -> FinalHeavenClaimRecord:
        operation_name = "event.final_heaven.claim"
        request_hash = self._request_hash(
            operation_name,
            {"platform": platform, "platform_user_id": platform_user_id, "season_id": season_id},
        )
        now = self._now()
        now_text = serialize_datetime(now)
        canonical_id, starts_at, ends_at = final_heaven_window_for_id(season_id)
        claim_expires_at = final_heaven_claim_expiry(ends_at)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            if existing is not None:
                if existing["operation_name"] != operation_name or existing["request_hash"] != request_hash:
                    raise OperationConflictError("operation input differs from its original request")
                return self._final_heaven_claim_from_payload(
                    json.loads(existing["result_json"]), replay=True
                )

            player = self._require_player(connection, platform, platform_user_id, writable=False)
            self._ensure_final_heaven_season(
                connection,
                canonical_id,
                starts_at,
                ends_at,
                claim_expires_at,
                now_text,
            )
            self._materialize_due_final_heaven_seasons(connection, now, now_text)
            season = connection.execute(
                "SELECT * FROM final_heaven_seasons WHERE season_id = ?", (season_id,)
            ).fetchone()
            if str(season["status"]) != "frozen":
                raise FinalHeavenRankingNotFinalizedError("season ranking is not finalized")
            if now >= claim_expires_at:
                payload = {
                    "season_id": season_id,
                    "title_keys": [],
                    "entitlements": [],
                    "claimed_at": now_text,
                    "expired": True,
                }
                connection.execute(
                    "INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (operation_id, operation_name, player["id"], request_hash, json.dumps(payload, sort_keys=True), now_text),
                )
                return FinalHeavenClaimRecord(
                    season_id=season_id,
                    title_keys=(),
                    entitlements=(),
                    claimed_at=now_text,
                    expired=True,
                )

            claimed = connection.execute(
                "SELECT 1 FROM final_heaven_claims WHERE season_id = ? AND player_id = ?",
                (season_id, player["id"]),
            ).fetchone()
            if claimed is not None:
                raise FinalHeavenRewardAlreadyClaimedError("season reward has already been claimed")
            rankings = connection.execute(
                "SELECT board_key, rank, title_key FROM final_heaven_rankings "
                "WHERE season_id = ? AND player_id = ? AND rank <= ? ORDER BY board_key",
                (season_id, player["id"], FINAL_HEAVEN_RANKED_PLACES),
            ).fetchall()
            if not rankings:
                raise FinalHeavenRewardNotEligibleError("player has no final-heaven ranking reward")

            titles: list[str] = []
            entitlements: list[str] = []
            for ranking in rankings:
                board_key = str(ranking["board_key"])
                title_key = str(ranking["title_key"])
                honor_title(title_key)
                source_operation_id = f"season.final_heaven:{season_id}:{board_key}:{player['id']}"
                connection.execute(
                    "INSERT OR IGNORE INTO honor_titles(player_id, title_key, source_operation_id, acquired_at, content_version, rule_version) "
                    "VALUES (?, ?, ?, ?, 'content-0.6', ?)",
                    (player["id"], title_key, source_operation_id, now_text, FINAL_HEAVEN_RULE_VERSION),
                )
                title_event_operation = f"{operation_id}:{board_key}:title"
                connection.execute(
                    "INSERT OR IGNORE INTO activity_events(player_id, event_key, source_operation_id, occurred_at, payload_json) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        player["id"],
                        f"season.final_heaven.claim.{board_key}",
                        title_event_operation,
                        now_text,
                        json.dumps(
                            {"season_id": season_id, "board_key": board_key, "title_key": title_key},
                            sort_keys=True,
                        ),
                    ),
                )
                titles.append(title_key)
                if int(ranking["rank"]) == 1:
                    connection.execute(
                        "INSERT OR IGNORE INTO final_heaven_entitlements(season_id, player_id, entitlement_key, operation_id, created_at) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (season_id, player["id"], FINAL_HEAVEN_CHAPTER_ENTITLEMENT, operation_id, now_text),
                    )
                    entitlement_operation = f"{operation_id}:{board_key}:chapter"
                    connection.execute(
                        "INSERT OR IGNORE INTO activity_events(player_id, event_key, source_operation_id, occurred_at, payload_json) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (
                            player["id"],
                            "season.final_heaven.chapter_eligibility",
                            entitlement_operation,
                            now_text,
                            json.dumps({"season_id": season_id, "board_key": board_key, "entitlement_key": FINAL_HEAVEN_CHAPTER_ENTITLEMENT}, sort_keys=True),
                        ),
                    )
                    entitlements.append(FINAL_HEAVEN_CHAPTER_ENTITLEMENT)

            title_keys = tuple(sorted(set(titles)))
            entitlement_keys = tuple(sorted(set(entitlements)))
            payload = {
                "season_id": season_id,
                "title_keys": list(title_keys),
                "entitlements": list(entitlement_keys),
                "claimed_at": now_text,
            }
            connection.execute(
                "INSERT INTO final_heaven_claims(season_id, player_id, operation_id, reward_json, claimed_at) VALUES (?, ?, ?, ?, ?)",
                (season_id, player["id"], operation_id, json.dumps(payload, sort_keys=True), now_text),
            )
            connection.execute(
                "UPDATE final_heaven_rankings SET claimed_at = ? WHERE season_id = ? AND player_id = ? AND rank <= ?",
                (now_text, season_id, player["id"], FINAL_HEAVEN_RANKED_PLACES),
            )
            connection.execute(
                "INSERT INTO activity_events(player_id, event_key, source_operation_id, occurred_at, payload_json) VALUES (?, ?, ?, ?, ?)",
                (player["id"], "season.final_heaven.claim", operation_id, now_text, json.dumps({"season_id": season_id, "title_keys": list(title_keys), "entitlements": list(entitlement_keys)}, sort_keys=True)),
            )
            connection.execute(
                "INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (operation_id, operation_name, player["id"], request_hash, json.dumps(payload, sort_keys=True), now_text),
            )
            return self._final_heaven_claim_from_payload(payload)

    def _materialize_due_final_heaven_seasons(
        self, connection: Any, now: datetime, now_text: str
    ) -> None:
        season_ids: set[str] = set()
        anchor_text = serialize_datetime(FINAL_HEAVEN_SEASON_ANCHOR)
        now_text = serialize_datetime(now)
        for row in connection.execute(
            "SELECT created_at FROM endgame_endings WHERE created_at >= ? AND created_at < ?",
            (anchor_text, now_text),
        ).fetchall():
            try:
                season_ids.add(final_heaven_season_window(datetime.fromisoformat(str(row["created_at"])))[0])
            except ValueError:
                continue

        sessions = connection.execute(
            "SELECT result_json FROM final_battle_sessions WHERE status = 'settled' AND updated_at >= ? AND updated_at < ?",
            (anchor_text, now_text),
        ).fetchall()
        for row in sessions:
            result = self._json_object(row["result_json"], {})
            if str(result.get("outcome", "")) not in {"won", "remained"}:
                continue
            settled_at = result.get("settled_at")
            if not settled_at:
                continue
            try:
                settled_time = datetime.fromisoformat(str(settled_at))
            except ValueError:
                continue
            if settled_time.tzinfo is None:
                settled_time = settled_time.replace(tzinfo=FINAL_HEAVEN_SEASON_ANCHOR.tzinfo)
            else:
                settled_time = settled_time.astimezone(FINAL_HEAVEN_SEASON_ANCHOR.tzinfo)
            if FINAL_HEAVEN_SEASON_ANCHOR <= settled_time < now:
                season_ids.add(final_heaven_season_window(settled_time)[0])

        season_ids.update(
            str(row["season_id"])
            for row in connection.execute("SELECT season_id FROM final_heaven_seasons").fetchall()
        )
        windows: list[tuple[str, datetime, datetime]] = []
        for season_id in season_ids:
            try:
                windows.append(final_heaven_window_for_id(season_id))
            except ValueError:
                continue
        for season_id, starts_at, ends_at in sorted(windows, key=lambda value: value[1]):
            if starts_at > now:
                continue
            claim_expires_at = final_heaven_claim_expiry(ends_at)
            self._ensure_final_heaven_season(
                connection,
                season_id,
                starts_at,
                ends_at,
                claim_expires_at,
                now_text,
            )
            season = connection.execute(
                "SELECT * FROM final_heaven_seasons WHERE season_id = ?", (season_id,)
            ).fetchone()
            if str(season["status"]) == "collecting" and now >= ends_at:
                self._freeze_final_heaven_season(connection, season, now_text)
                season = connection.execute(
                    "SELECT * FROM final_heaven_seasons WHERE season_id = ?", (season_id,)
                ).fetchone()
            if str(season["status"]) == "frozen" and now >= claim_expires_at:
                self._auto_grant_final_heaven_titles(connection, season_id, now_text)

    @staticmethod
    def _ensure_final_heaven_season(
        connection: Any,
        season_id: str,
        starts_at: datetime,
        ends_at: datetime,
        claim_expires_at: datetime,
        now_text: str,
    ) -> None:
        connection.execute(
            "INSERT OR IGNORE INTO final_heaven_seasons(season_id, starts_at, ends_at, claim_expires_at, status, snapshot_json, rule_version, frozen_at, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, 'collecting', '{}', ?, NULL, ?, ?)",
            (
                season_id,
                serialize_datetime(starts_at),
                serialize_datetime(ends_at),
                serialize_datetime(claim_expires_at),
                FINAL_HEAVEN_RULE_VERSION,
                now_text,
                now_text,
            ),
        )

    def _freeze_final_heaven_season(self, connection: Any, season: Any, frozen_at: str) -> None:
        season_id = str(season["season_id"])
        starts_at = datetime.fromisoformat(str(season["starts_at"]))
        ends_at = datetime.fromisoformat(str(season["ends_at"]))
        board_snapshots: dict[str, list[dict[str, Any]]] = {}
        for board_key in FINAL_HEAVEN_BOARDS:
            ranked = self._final_heaven_rank_candidates(
                connection, season_id, board_key, starts_at, ends_at
            )
            public_rows: list[dict[str, Any]] = []
            for item in ranked:
                connection.execute(
                    "INSERT INTO final_heaven_rankings(season_id, board_key, player_id, rank, score, achieved_at, anonymous_label, title_key) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        season_id,
                        board_key,
                        item["player_id"],
                        item["rank"],
                        item["score"],
                        item["achieved_at"],
                        item["anonymous_label"],
                        item["title_key"],
                    ),
                )
                if int(item["rank"]) <= FINAL_HEAVEN_RANKED_PLACES:
                    public_rows.append(
                        {
                            "rank": item["rank"],
                            "anonymous_label": item["anonymous_label"],
                            "score": item["score"],
                            "achieved_at": item["achieved_at"],
                        }
                    )
            board_snapshots[board_key] = public_rows
        snapshot = json.dumps(
            {"boards": board_snapshots, "frozen_at": frozen_at},
            ensure_ascii=False,
            sort_keys=True,
        )
        connection.execute(
            "UPDATE final_heaven_seasons SET status = 'frozen', snapshot_json = ?, frozen_at = ?, updated_at = ? WHERE season_id = ? AND status = 'collecting'",
            (snapshot, frozen_at, frozen_at, season_id),
        )

    @staticmethod
    def _final_heaven_rank_candidates(
        connection: Any,
        season_id: str,
        board_key: str,
        starts_at: datetime,
        ends_at: datetime,
    ) -> list[dict[str, Any]]:
        candidates: dict[int, dict[str, Any]] = {}
        start_text = serialize_datetime(starts_at)
        end_text = serialize_datetime(ends_at)
        if board_key in {"ascension", "dao"}:
            ending_key = "ascend" if board_key == "ascension" else "remain_in_world"
            rows = connection.execute(
                "SELECT player_id, created_at FROM endgame_endings "
                "WHERE ending_key = ? AND created_at >= ? AND created_at < ?",
                (ending_key, start_text, end_text),
            ).fetchall()
            score = int(FINAL_HEAVEN_BOARDS[board_key]["score"])
            for row in rows:
                candidates[int(row["player_id"])] = {
                    "score": score,
                    "achieved_at": str(row["created_at"]),
                }
        else:
            sessions = connection.execute(
                "SELECT battle_id, result_json FROM final_battle_sessions "
                "WHERE status = 'settled' AND updated_at >= ? AND updated_at < ?",
                (start_text, end_text),
            ).fetchall()
            for session in sessions:
                result = json.loads(str(session["result_json"] or "{}"))
                outcome = str(result.get("outcome", ""))
                if outcome not in {"won", "remained"}:
                    continue
                settled_at = str(result.get("settled_at", ""))
                if not settled_at:
                    continue
                settled_time = datetime.fromisoformat(settled_at)
                if settled_time < starts_at or settled_time >= ends_at:
                    continue
                members = connection.execute(
                    "SELECT player_id FROM final_battle_members WHERE battle_id = ? ORDER BY id",
                    (session["battle_id"],),
                ).fetchall()
                if len(members) < 2:
                    continue
                for member in members:
                    player_id = int(member["player_id"])
                    candidate = candidates.setdefault(
                        player_id, {"score": 0, "achieved_at": settled_at}
                    )
                    candidate["score"] += int(FINAL_HEAVEN_BOARDS[board_key]["score"])
                    candidate["achieved_at"] = max(str(candidate["achieved_at"]), settled_at)

        board = FINAL_HEAVEN_BOARDS[board_key]
        ordered = sorted(
            candidates.items(),
            key=lambda item: (
                -int(item[1]["score"]),
                str(item[1]["achieved_at"]),
                final_heaven_tie_breaker(season_id, item[0]),
            ),
        )
        return [
            {
                "player_id": player_id,
                "rank": rank,
                "score": int(value["score"]),
                "achieved_at": str(value["achieved_at"]),
                "anonymous_label": f"匿名道友 {rank:03d}",
                "title_key": str(board["title_key"]) if rank <= FINAL_HEAVEN_RANKED_PLACES else None,
            }
            for rank, (player_id, value) in enumerate(ordered, start=1)
        ]

    def _auto_grant_final_heaven_titles(self, connection: Any, season_id: str, now_text: str) -> None:
        rows = connection.execute(
            "SELECT board_key, player_id, title_key FROM final_heaven_rankings "
            "WHERE season_id = ? AND title_key IS NOT NULL AND auto_granted_at IS NULL AND claimed_at IS NULL",
            (season_id,),
        ).fetchall()
        for row in rows:
            board_key = str(row["board_key"])
            player_id = int(row["player_id"])
            title_key = str(row["title_key"])
            source_operation_id = f"season.final_heaven:auto:{season_id}:{board_key}:{player_id}"
            operation_id = f"event.final_heaven.auto_grant:{season_id}:{board_key}:{player_id}"
            operation_name = "event.final_heaven.auto_grant"
            operation_result = {
                "season_id": season_id,
                "board_key": board_key,
                "title_key": title_key,
                "auto_granted_at": now_text,
            }
            request_hash = self._request_hash(
                operation_name,
                {
                    "season_id": season_id,
                    "board_key": board_key,
                    "player_id": player_id,
                    "title_key": title_key,
                },
            )
            connection.execute(
                "INSERT OR IGNORE INTO honor_titles(player_id, title_key, source_operation_id, acquired_at, content_version, rule_version) "
                "VALUES (?, ?, ?, ?, 'content-0.6', ?)",
                (player_id, title_key, source_operation_id, now_text, FINAL_HEAVEN_RULE_VERSION),
            )
            connection.execute(
                "INSERT OR IGNORE INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    operation_id,
                    operation_name,
                    player_id,
                    request_hash,
                    json.dumps(operation_result, sort_keys=True),
                    now_text,
                ),
            )
            connection.execute(
                "INSERT OR IGNORE INTO activity_events(player_id, event_key, source_operation_id, occurred_at, payload_json) "
                "VALUES (?, 'season.final_heaven.title.auto_granted', ?, ?, ?)",
                (player_id, source_operation_id, now_text, json.dumps({"season_id": season_id, "board_key": board_key, "title_key": title_key}, sort_keys=True)),
            )
            connection.execute(
                "UPDATE final_heaven_rankings SET auto_granted_at = ? WHERE season_id = ? AND board_key = ? AND player_id = ? AND auto_granted_at IS NULL",
                (now_text, season_id, board_key, player_id),
            )

    def _final_heaven_record(
        self,
        connection: Any,
        season: Any,
        player_id: int,
        *,
        board_key: str | None,
        starts_at: datetime,
        ends_at: datetime,
        claim_expires_at: datetime,
    ) -> FinalHeavenSeasonRecord:
        season_id = str(season["season_id"])
        status = str(season["status"])
        rows: list[dict[str, Any]]
        personal_rows: list[dict[str, Any]] = []
        if status == "frozen":
            selected_keys = (board_key,) if board_key else tuple(FINAL_HEAVEN_BOARDS)
            rows = []
            for key in selected_keys:
                stored = connection.execute(
                    "SELECT board_key, rank, anonymous_label, score, achieved_at, title_key, player_id "
                    "FROM final_heaven_rankings WHERE season_id = ? AND board_key = ? AND rank <= ? ORDER BY rank",
                    (season_id, key, FINAL_HEAVEN_RANKED_PLACES),
                ).fetchall()
                for row in stored:
                    value = dict(row)
                    value["board_label"] = str(FINAL_HEAVEN_BOARDS[key]["label"])
                    rows.append(value)
                personal = connection.execute(
                    "SELECT board_key, rank, anonymous_label, score, achieved_at, title_key "
                    "FROM final_heaven_rankings WHERE season_id = ? AND board_key = ? AND player_id = ?",
                    (season_id, key, player_id),
                ).fetchone()
                if personal is not None:
                    value = dict(personal)
                    value["board_label"] = str(FINAL_HEAVEN_BOARDS[key]["label"])
                    personal_rows.append(value)
        else:
            selected_keys = (board_key,) if board_key else tuple(FINAL_HEAVEN_BOARDS)
            rows = []
            for key in selected_keys:
                ranked = self._final_heaven_rank_candidates(
                    connection, season_id, key, starts_at, ends_at
                )
                for item in ranked[:FINAL_HEAVEN_RANKED_PLACES]:
                    item["board_key"] = key
                    item["board_label"] = str(FINAL_HEAVEN_BOARDS[key]["label"])
                    rows.append(item)
                own = next((item for item in ranked if item["player_id"] == player_id), None)
                if own is not None:
                    own = dict(own)
                    own["board_key"] = key
                    own["board_label"] = str(FINAL_HEAVEN_BOARDS[key]["label"])
                    personal_rows.append(own)

        def standing(value: dict[str, Any]) -> FinalHeavenStanding:
            return FinalHeavenStanding(
                board_key=str(value["board_key"]),
                board_label=str(value["board_label"]),
                rank=int(value["rank"]),
                anonymous_label=str(value["anonymous_label"]),
                score=int(value["score"]),
                achieved_at=str(value["achieved_at"]),
                title_key=str(value["title_key"]) if value.get("title_key") else None,
            )

        return FinalHeavenSeasonRecord(
            season_id=season_id,
            status=status,
            starts_at=serialize_datetime(starts_at),
            ends_at=serialize_datetime(ends_at),
            claim_expires_at=serialize_datetime(claim_expires_at),
            frozen_at=str(season["frozen_at"]) if season["frozen_at"] else None,
            standings=tuple(standing(value) for value in rows),
            personal_standings=tuple(standing(value) for value in personal_rows),
        )

    @staticmethod
    def _final_heaven_claim_from_payload(
        payload: dict[str, Any], replay: bool = False
    ) -> FinalHeavenClaimRecord:
        return FinalHeavenClaimRecord(
            season_id=str(payload["season_id"]),
            title_keys=tuple(str(value) for value in payload.get("title_keys", [])),
            entitlements=tuple(str(value) for value in payload.get("entitlements", [])),
            claimed_at=str(payload["claimed_at"]),
            already_completed=replay,
            expired=bool(payload.get("expired", False)),
        )


__all__ = ["FinalHeavenSeasonRepositoryMixin"]
