"""SQLite transactions for the asynchronous snapshot arena.

The arena deliberately owns its own snapshots and replay tables.  It never
creates or mutates the single-player ``battle_sessions`` records.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from ...contracts import serialize_datetime
from ..persistence.errors import (
    ArenaChallengeCapError,
    ArenaMatchNotFoundError,
    ArenaMatchRequirementError,
    ArenaOpponentUnavailableError,
    ArenaPlayerBusyError,
    ArenaRewardAlreadyClaimedError,
    ArenaRewardNotAvailableError,
    ArenaSnapshotExpiredError,
    ArenaSnapshotNotFoundError,
    ArenaSnapshotRequirementError,
    OperationConflictError,
    PlayerNotFoundError,
)
from .arena_models import (
    ArenaClaimRecord,
    ArenaMatchRecord,
    ArenaReplayRecord,
    ArenaSnapshotRecord,
)
from .arena_rules import (
    ARENA_MODE_KEY,
    ARENA_PRACTICE_MODE_KEY,
    ARENA_RANK_MODE_KEY,
    CONTENT_VERSION,
    DAILY_CHALLENGE_LIMIT,
    DAILY_COUNTED_OPPONENT_LIMIT,
    RULE_VERSION,
    SNAPSHOT_MATCH_DELAY_SECONDS,
    SNAPSHOT_VALID_DAYS,
    compatible_rating,
    mode_attempt_limit,
    mode_period_prefix,
    public_summary,
    rating_band,
    rating_delta,
    simulate_match,
)


class ArenaRepositoryMixin:
    """Own immutable defense snapshots, matches, actions and claims."""

    async def publish_arena_snapshot(
        self, *, platform: str, platform_user_id: str, operation_id: str
    ) -> ArenaSnapshotRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._retry_sync,
                self._publish_arena_snapshot_once,
                platform,
                platform_user_id,
                operation_id,
            )

    async def revoke_arena_snapshot(
        self,
        *,
        platform: str,
        platform_user_id: str,
        snapshot_id: str | None,
        operation_id: str,
    ) -> ArenaSnapshotRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._retry_sync,
                self._revoke_arena_snapshot_once,
                platform,
                platform_user_id,
                snapshot_id,
                operation_id,
            )

    async def list_arena_snapshots(
        self, *, platform: str, platform_user_id: str
    ) -> tuple[ArenaSnapshotRecord, ...]:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._list_arena_snapshots_once, platform, platform_user_id
            )

    async def challenge_arena(
        self,
        *,
        platform: str,
        platform_user_id: str,
        snapshot_id: str | None,
        operation_id: str,
        mode_key: str = ARENA_MODE_KEY,
    ) -> ArenaMatchRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._retry_sync,
                self._challenge_arena_once,
                platform,
                platform_user_id,
                snapshot_id,
                operation_id,
                mode_key,
            )

    async def grant_arena_practice_consent(
        self,
        *,
        platform: str,
        platform_user_id: str,
        snapshot_id: str,
        challenger_identity: str,
        operation_id: str,
    ) -> None:
        await self.initialize()
        async with self._inflight:
            await asyncio.to_thread(
                self._retry_sync,
                self._grant_arena_practice_consent_once,
                platform,
                platform_user_id,
                snapshot_id,
                challenger_identity,
                operation_id,
            )

    def _grant_arena_practice_consent_once(
        self,
        platform: str,
        platform_user_id: str,
        snapshot_id: str,
        challenger_identity: str,
        operation_id: str,
    ) -> None:
        operation_name = "specials.grant_arena_practice_consent"
        request_payload = {
            "platform": platform,
            "platform_user_id": platform_user_id,
            "snapshot_id": snapshot_id,
            "challenger_identity": challenger_identity,
        }
        request_hash = self._request_hash(operation_name, request_payload)
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._arena_operation(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                return
            owner = self._arena_require_player(connection, platform, platform_user_id)
            snapshot = self._find_owned_snapshot(connection, int(owner["id"]), snapshot_id)
            self._expire_snapshot_row(connection, snapshot, now)
            if str(snapshot["status"]) != "published":
                raise ArenaSnapshotExpiredError("snapshot is not available for practice")
            target = connection.execute(
                "SELECT * FROM players WHERE status = 'active' AND stage = 'cultivator' AND "
                "(platform_user_id = ? OR player_id = ?)",
                (challenger_identity, challenger_identity),
            ).fetchone()
            if target is None or int(target["id"]) == int(owner["id"]):
                raise ArenaMatchRequirementError("practice challenger is not eligible")
            expires_at = min(datetime.fromisoformat(str(snapshot["expires_at"])), now + timedelta(days=SNAPSHOT_VALID_DAYS))
            connection.execute(
                "INSERT INTO arena_practice_consents(snapshot_id, owner_id, challenger_id, operation_id, expires_at, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(snapshot_id, challenger_id) DO UPDATE SET operation_id = excluded.operation_id, expires_at = excluded.expires_at, created_at = excluded.created_at",
                (snapshot_id, owner["id"], target["id"], operation_id, serialize_datetime(expires_at), now_text),
            )
            self._arena_insert_operation(
                connection,
                operation_id,
                operation_name,
                int(owner["id"]),
                request_hash,
                {"snapshot_id": snapshot_id, "challenger_id": int(target["id"]), "expires_at": serialize_datetime(expires_at)},
                now_text,
            )

    async def replay_arena(
        self, *, platform: str, platform_user_id: str, match_id: str | None = None
    ) -> ArenaReplayRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._replay_arena_once, platform, platform_user_id, match_id
            )

    async def claim_arena_result(
        self,
        *,
        platform: str,
        platform_user_id: str,
        match_id: str | None,
        operation_id: str,
    ) -> ArenaClaimRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._retry_sync,
                self._claim_arena_result_once,
                platform,
                platform_user_id,
                match_id,
                operation_id,
            )

    def _publish_arena_snapshot_once(
        self, platform: str, platform_user_id: str, operation_id: str
    ) -> ArenaSnapshotRecord:
        operation_name = "specials.publish_arena_snapshot"
        request_payload = {
            "platform": platform,
            "platform_user_id": platform_user_id,
            "arena_mode_key": ARENA_MODE_KEY,
            "content_version": CONTENT_VERSION,
            "rule_version": RULE_VERSION,
        }
        request_hash = self._request_hash(operation_name, request_payload)
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._arena_operation(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                return self._snapshot_from_payload(replay, already_completed=True)
            player = self._arena_require_player(connection, platform, platform_user_id)
            self._arena_require_free(connection, int(player["id"]))
            old = connection.execute(
                "SELECT snapshot_id FROM arena_snapshots WHERE player_id = ? AND status = 'published'",
                (player["id"],),
            ).fetchall()
            connection.execute(
                "UPDATE arena_snapshots SET status = 'revoked', revoked_at = ?, updated_at = ? "
                "WHERE player_id = ? AND status = 'published'",
                (now_text, now_text, player["id"]),
            )
            snapshot_id = f"arena.snapshot:{uuid4().hex}"
            snapshot = self._arena_player_snapshot(connection, player, snapshot_id)
            expires_at = now + timedelta(days=SNAPSHOT_VALID_DAYS)
            matchable_at = now + timedelta(seconds=SNAPSHOT_MATCH_DELAY_SECONDS)
            summary = public_summary(
                snapshot,
                snapshot_id=snapshot_id,
                rating=int(player["arena_rating"]),
                created_at=now_text,
            )
            connection.execute(
                "INSERT INTO arena_snapshots("
                "snapshot_id, player_id, status, arena_mode_key, rating, matchable_at, expires_at, "
                "snapshot_json, public_json, content_version, rule_version, created_at, updated_at) "
                "VALUES (?, ?, 'published', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    snapshot_id,
                    player["id"],
                    ARENA_MODE_KEY,
                    player["arena_rating"],
                    serialize_datetime(matchable_at),
                    serialize_datetime(expires_at),
                    json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
                    json.dumps(summary, ensure_ascii=False, sort_keys=True),
                    CONTENT_VERSION,
                    RULE_VERSION,
                    now_text,
                    now_text,
                ),
            )
            payload = {
                "snapshot_id": snapshot_id,
                "status": "published",
                "public_summary": summary,
                "rating": int(player["arena_rating"]),
                "matchable_at": serialize_datetime(matchable_at),
                "expires_at": serialize_datetime(expires_at),
                "replaced_snapshot_ids": [str(item["snapshot_id"]) for item in old],
            }
            self._arena_insert_operation(
                connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text
            )
            return self._snapshot_from_payload(payload)

    def _revoke_arena_snapshot_once(
        self,
        platform: str,
        platform_user_id: str,
        requested_snapshot_id: str | None,
        operation_id: str,
    ) -> ArenaSnapshotRecord:
        operation_name = "specials.revoke_arena_snapshot"
        request_payload = {
            "platform": platform,
            "platform_user_id": platform_user_id,
            "snapshot_id": requested_snapshot_id,
        }
        request_hash = self._request_hash(operation_name, request_payload)
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._arena_operation(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                return self._snapshot_from_payload(replay, already_completed=True)
            player = self._arena_require_player(connection, platform, platform_user_id)
            snapshot = self._find_owned_snapshot(connection, int(player["id"]), requested_snapshot_id)
            self._expire_snapshot_row(connection, snapshot, now)
            if str(snapshot["status"]) != "published":
                raise ArenaSnapshotExpiredError("snapshot is not published")
            connection.execute(
                "UPDATE arena_snapshots SET status = 'revoked', revoked_at = ?, updated_at = ? WHERE snapshot_id = ?",
                (now_text, now_text, snapshot["snapshot_id"]),
            )
            current = connection.execute(
                "SELECT * FROM arena_snapshots WHERE snapshot_id = ?", (snapshot["snapshot_id"],)
            ).fetchone()
            payload = self._snapshot_payload_from_row(current)
            self._arena_insert_operation(
                connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text
            )
            return self._snapshot_from_payload(payload)

    def _list_arena_snapshots_once(
        self, platform: str, platform_user_id: str
    ) -> tuple[ArenaSnapshotRecord, ...]:
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            player = self._arena_require_player(connection, platform, platform_user_id, writable=False)
            connection.execute(
                "UPDATE arena_snapshots SET status = 'expired', updated_at = ? "
                "WHERE status = 'published' AND expires_at <= ?",
                (now_text, now_text),
            )
            rows = connection.execute(
                "SELECT * FROM arena_snapshots WHERE status = 'published' AND player_id <> ? "
                "ORDER BY ABS(rating - ?), created_at, id LIMIT 50",
                (player["id"], player["arena_rating"]),
            ).fetchall()
            return tuple(self._snapshot_from_row(row) for row in rows)

    def _challenge_arena_once(
        self,
        platform: str,
        platform_user_id: str,
        requested_snapshot_id: str | None,
        operation_id: str,
        mode_key: str,
    ) -> ArenaMatchRecord:
        if mode_key not in {ARENA_MODE_KEY, ARENA_RANK_MODE_KEY, ARENA_PRACTICE_MODE_KEY}:
            raise ArenaMatchRequirementError("unsupported arena mode")
        operation_name = "specials.challenge_arena"
        request_payload = {
            "platform": platform,
            "platform_user_id": platform_user_id,
            "snapshot_id": requested_snapshot_id,
            "arena_mode_key": mode_key,
            "content_version": CONTENT_VERSION,
            "rule_version": RULE_VERSION,
        }
        request_hash = self._request_hash(operation_name, request_payload)
        now = self._now()
        now_text = serialize_datetime(now)
        period_prefix = mode_period_prefix(mode_key, now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._arena_operation(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                return self._match_from_payload(replay, already_completed=True)
            challenger = self._arena_require_player(connection, platform, platform_user_id)
            challenger_id = int(challenger["id"])
            self._arena_require_free(connection, challenger_id)
            attempts = connection.execute(
                "SELECT COUNT(*) AS total FROM arena_matches WHERE challenger_id = ? AND arena_mode_key = ? AND created_at LIKE ?",
                (challenger_id, mode_key, period_prefix),
            ).fetchone()
            if int(attempts["total"]) >= mode_attempt_limit(mode_key):
                raise ArenaChallengeCapError("arena mode attempt cap has been reached")
            connection.execute(
                "UPDATE arena_snapshots SET status = 'expired', updated_at = ? WHERE status = 'published' AND expires_at <= ?",
                (now_text, now_text),
            )
            defender_snapshot = self._select_opponent_snapshot(
                connection,
                challenger_id,
                int(challenger["arena_rating"]),
                requested_snapshot_id,
                now_text,
                mode_key,
            )
            defender = connection.execute(
                "SELECT * FROM players WHERE id = ? AND status = 'active'", (defender_snapshot["player_id"],)
            ).fetchone()
            if defender is None or str(defender["stage"]) != "cultivator":
                raise ArenaOpponentUnavailableError("opponent is no longer eligible")
            match_id = f"arena.match:{uuid4().hex}"
            challenger_snapshot_id = f"arena.match_snapshot:{uuid4().hex}"
            challenger_snapshot = self._arena_player_snapshot(connection, challenger, challenger_snapshot_id)
            defender_snapshot_data = self._json_map(defender_snapshot["snapshot_json"])
            outcome, rounds, actions = simulate_match(
                challenger_snapshot,
                defender_snapshot_data,
                seed=operation_id,
            )
            counted_row = connection.execute(
                "SELECT COUNT(*) AS total FROM arena_matches WHERE challenger_id = ? AND defender_snapshot_id = ? "
                "AND score_counted = 1 AND created_at LIKE ?",
                (challenger_id, defender_snapshot["snapshot_id"], now.date().isoformat() + "%"),
            ).fetchone()
            score_counted = mode_key != ARENA_PRACTICE_MODE_KEY and int(counted_row["total"]) < DAILY_COUNTED_OPPONENT_LIMIT
            challenger_delta = rating_delta(outcome, challenger=True) if score_counted else 0
            defender_delta = rating_delta(outcome, challenger=False) if score_counted else 0
            challenger_rating = max(0, int(challenger["arena_rating"]) + challenger_delta)
            defender_rating = max(0, int(defender["arena_rating"]) + defender_delta)
            if score_counted:
                connection.execute(
                    "UPDATE players SET arena_rating = ?, arena_wins = arena_wins + ?, arena_losses = arena_losses + ?, arena_draws = arena_draws + ?, updated_at = ? WHERE id = ?",
                    (
                        challenger_rating,
                        1 if outcome == "challenger_won" else 0,
                        1 if outcome == "defender_won" else 0,
                        1 if outcome == "draw" else 0,
                        now_text,
                        challenger_id,
                    ),
                )
                connection.execute(
                    "UPDATE players SET arena_rating = ?, arena_wins = arena_wins + ?, arena_losses = arena_losses + ?, arena_draws = arena_draws + ?, updated_at = ? WHERE id = ?",
                    (
                        defender_rating,
                        1 if outcome == "defender_won" else 0,
                        1 if outcome == "challenger_won" else 0,
                        1 if outcome == "draw" else 0,
                        now_text,
                        defender["id"],
                    ),
                )
            else:
                challenger_rating = int(challenger["arena_rating"])
                defender_rating = int(defender["arena_rating"])
            snapshot = {
                "challenger": challenger_snapshot,
                "defender": defender_snapshot_data,
                "arena_mode_key": mode_key,
                "content_version": CONTENT_VERSION,
                "rule_version": RULE_VERSION,
            }
            result = {
                "outcome": outcome,
                "rounds": rounds,
                "score_counted": score_counted,
                "challenger_rating": challenger_rating,
                "defender_rating": defender_rating,
                "challenger_rating_delta": challenger_delta,
                "defender_rating_delta": defender_delta,
                "mode_key": mode_key,
                "opponent_summary": self._json_map(defender_snapshot["public_json"]),
            }
            connection.execute(
                "INSERT INTO arena_snapshots(snapshot_id, player_id, status, arena_mode_key, rating, matchable_at, expires_at, snapshot_json, public_json, content_version, rule_version, created_at, updated_at) "
                "VALUES (?, ?, 'expired', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    challenger_snapshot_id,
                    challenger_id,
                    ARENA_MODE_KEY,
                    challenger["arena_rating"],
                    now_text,
                    now_text,
                    json.dumps(challenger_snapshot, ensure_ascii=False, sort_keys=True),
                    json.dumps(public_summary(challenger_snapshot, snapshot_id=challenger_snapshot_id, rating=int(challenger["arena_rating"]), created_at=now_text), ensure_ascii=False, sort_keys=True),
                    CONTENT_VERSION,
                    RULE_VERSION,
                    now_text,
                    now_text,
                ),
            )
            connection.execute(
                "INSERT INTO arena_matches(match_id, challenger_id, defender_id, challenger_snapshot_id, defender_snapshot_id, arena_mode_key, status, outcome, rounds, score_counted, challenger_rating_delta, defender_rating_delta, snapshot_json, result_json, operation_id, created_at, settled_at) "
                "VALUES (?, ?, ?, ?, ?, ?, 'settled', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    match_id,
                    challenger_id,
                    defender["id"],
                    challenger_snapshot_id,
                    defender_snapshot["snapshot_id"],
                    mode_key,
                    outcome,
                    rounds,
                    1 if score_counted else 0,
                    challenger_delta,
                    defender_delta,
                    json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
                    json.dumps(result, ensure_ascii=False, sort_keys=True),
                    operation_id,
                    now_text,
                    now_text,
                ),
            )
            for action in actions:
                connection.execute(
                    "INSERT INTO arena_actions(action_id, match_id, sequence_no, round_no, actor_key, strategy_key, skill_key, target_key, hit_roll_bp, damage, state_json, operation_id, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        uuid4().hex,
                        match_id,
                        action["sequence_no"],
                        action["round_no"],
                        action["actor_key"],
                        action["strategy_key"],
                        action["skill_key"],
                        action["target_key"],
                        action["hit_roll_bp"],
                        action["damage"],
                        json.dumps(action["state"], ensure_ascii=False, sort_keys=True),
                        operation_id,
                        now_text,
                    ),
                )
            projection = self._project_arena_result(
                connection,
                match_id=match_id,
                operation_id=operation_id,
                mode_key=mode_key,
                outcome=outcome,
                score_counted=score_counted,
                settled_at=now_text,
                participants=(
                    {"player_id": challenger_id, "side": "challenger"},
                    {"player_id": int(defender["id"]), "side": "defender"},
                ),
            )
            result["projection"] = projection
            connection.execute(
                "UPDATE arena_matches SET result_json = ? WHERE match_id = ?",
                (json.dumps(result, ensure_ascii=False, sort_keys=True), match_id),
            )
            self._arena_insert_operation(
                connection,
                operation_id,
                operation_name,
                challenger_id,
                request_hash,
                {"match_id": match_id, **result},
                now_text,
            )
            return self._match_from_payload({"match_id": match_id, **result})

    def _replay_arena_once(
        self, platform: str, platform_user_id: str, requested_match_id: str | None
    ) -> ArenaReplayRecord:
        with self._connect() as connection:
            player = self._arena_require_player(connection, platform, platform_user_id, writable=False)
            if requested_match_id:
                match = connection.execute(
                    "SELECT * FROM arena_matches WHERE match_id = ? AND (challenger_id = ? OR defender_id = ?)",
                    (requested_match_id, player["id"], player["id"]),
                ).fetchone()
            else:
                match = connection.execute(
                    "SELECT * FROM arena_matches WHERE challenger_id = ? OR defender_id = ? ORDER BY created_at DESC LIMIT 1",
                    (player["id"], player["id"]),
                ).fetchone()
            if match is None:
                raise ArenaMatchNotFoundError("arena match does not exist")
            actions = connection.execute(
                "SELECT * FROM arena_actions WHERE match_id = ? ORDER BY sequence_no", (match["match_id"],)
            ).fetchall()
            return ArenaReplayRecord(
                match_id=str(match["match_id"]),
                status=str(match["status"]),
                outcome=str(match["outcome"]),
                rounds=int(match["rounds"]),
                score_counted=bool(match["score_counted"]),
                snapshot=self._json_map(match["snapshot_json"]),
                result=self._json_map(match["result_json"]),
                actions=tuple(
                    {
                        "sequence_no": int(item["sequence_no"]),
                        "round_no": int(item["round_no"]),
                        "actor_key": str(item["actor_key"]),
                        "strategy_key": str(item["strategy_key"]),
                        "skill_key": str(item["skill_key"]),
                        "target_key": str(item["target_key"]),
                        "hit_roll_bp": int(item["hit_roll_bp"]),
                        "damage": int(item["damage"]),
                        "state": self._json_map(item["state_json"]),
                    }
                    for item in actions
                ),
            )

    def _claim_arena_result_once(
        self,
        platform: str,
        platform_user_id: str,
        requested_match_id: str | None,
        operation_id: str,
    ) -> ArenaClaimRecord:
        operation_name = "specials.claim_arena_result"
        request_payload = {
            "platform": platform,
            "platform_user_id": platform_user_id,
            "match_id": requested_match_id,
        }
        request_hash = self._request_hash(operation_name, request_payload)
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._arena_operation(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                return self._arena_claim_from_payload(replay, already_completed=True)
            player = self._arena_require_player(connection, platform, platform_user_id)
            if requested_match_id:
                match = connection.execute(
                    "SELECT * FROM arena_matches WHERE match_id = ? AND (challenger_id = ? OR defender_id = ?)",
                    (requested_match_id, player["id"], player["id"]),
                ).fetchone()
            else:
                match = connection.execute(
                    "SELECT * FROM arena_matches WHERE (challenger_id = ? OR defender_id = ?) "
                    "AND NOT EXISTS (SELECT 1 FROM arena_reward_claims c WHERE c.match_id = arena_matches.match_id) "
                    "ORDER BY created_at DESC LIMIT 1",
                    (player["id"], player["id"]),
                ).fetchone()
            if match is None:
                raise ArenaRewardNotAvailableError("no arena result is available")
            existing = connection.execute(
                "SELECT reward_json FROM arena_reward_claims WHERE match_id = ?", (match["match_id"],)
            ).fetchone()
            if existing is not None:
                raise ArenaRewardAlreadyClaimedError("arena result is already acknowledged")
            reward: dict[str, int] = {}
            connection.execute(
                "INSERT INTO arena_reward_claims(match_id, player_id, operation_id, reward_json, claimed_at) VALUES (?, ?, ?, ?, ?)",
                (match["match_id"], player["id"], operation_id, "{}", now_text),
            )
            payload = {"match_id": str(match["match_id"]), "reward": reward}
            self._arena_insert_operation(
                connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text
            )
            return self._arena_claim_from_payload(payload)

    def _select_opponent_snapshot(
        self,
        connection: sqlite3.Connection,
        challenger_id: int,
        challenger_rating: int,
        requested_snapshot_id: str | None,
        now_text: str,
        mode_key: str,
    ) -> sqlite3.Row:
        if requested_snapshot_id:
            row = connection.execute(
                "SELECT * FROM arena_snapshots WHERE snapshot_id = ? AND player_id <> ?",
                (requested_snapshot_id, challenger_id),
            ).fetchone()
            if row is None:
                raise ArenaSnapshotNotFoundError("arena snapshot does not exist")
            if str(row["status"]) != "published" or str(row["expires_at"]) <= now_text:
                raise ArenaSnapshotExpiredError("arena snapshot is not matchable")
            if str(row["matchable_at"]) > now_text:
                raise ArenaMatchRequirementError("arena snapshot is still in its publication delay")
            if mode_key == ARENA_RANK_MODE_KEY and rating_band(challenger_rating) != rating_band(int(row["rating"])):
                raise ArenaMatchRequirementError("rank snapshot is outside the same rating band")
            if mode_key != ARENA_RANK_MODE_KEY and not compatible_rating(challenger_rating, int(row["rating"])):
                raise ArenaMatchRequirementError("arena snapshot is outside the adjacent rating bands")
            owner = connection.execute(
                "SELECT stage, status FROM players WHERE id = ?", (row["player_id"],)
            ).fetchone()
            if owner is None or owner["status"] != "active" or owner["stage"] != "cultivator":
                raise ArenaOpponentUnavailableError("opponent is not currently eligible")
            if mode_key == ARENA_PRACTICE_MODE_KEY:
                consent = connection.execute(
                    "SELECT 1 FROM arena_practice_consents WHERE snapshot_id = ? AND challenger_id = ? AND expires_at > ?",
                    (row["snapshot_id"], challenger_id, now_text),
                ).fetchone()
                if consent is None:
                    raise ArenaMatchRequirementError("practice requires the snapshot owner's consent")
            return row
        rows = connection.execute(
            "SELECT s.* FROM arena_snapshots s JOIN players p ON p.id = s.player_id "
            "WHERE s.status = 'published' AND s.player_id <> ? AND s.matchable_at <= ? AND s.expires_at > ? "
            "AND p.status = 'active' AND p.stage = 'cultivator' ORDER BY ABS(s.rating - ?), s.created_at, s.id",
            (challenger_id, now_text, now_text, challenger_rating),
        ).fetchall()
        for row in rows:
            if mode_key == ARENA_PRACTICE_MODE_KEY:
                consent = connection.execute(
                    "SELECT 1 FROM arena_practice_consents WHERE snapshot_id = ? AND challenger_id = ? AND expires_at > ?",
                    (row["snapshot_id"], challenger_id, now_text),
                ).fetchone()
                if consent is None:
                    continue
            if (
                (mode_key == ARENA_RANK_MODE_KEY and rating_band(challenger_rating) == rating_band(int(row["rating"])))
                or (mode_key != ARENA_RANK_MODE_KEY and compatible_rating(challenger_rating, int(row["rating"])))
            ):
                return row
        raise ArenaOpponentUnavailableError("no compatible arena snapshot is available")

    def _arena_require_player(
        self, connection: sqlite3.Connection, platform: str, platform_user_id: str, *, writable: bool = True
    ) -> sqlite3.Row:
        player = self._require_player(connection, platform, platform_user_id, writable=writable)
        if writable and str(player["stage"]) != "cultivator":
            raise ArenaSnapshotRequirementError("arena requires an active cultivator")
        return player

    @staticmethod
    def _arena_require_free(connection: sqlite3.Connection, player_id: int) -> None:
        checks = (
            ("cultivation_sessions", "status = 'running'"),
            ("retreat_sessions", "status = 'running'"),
            ("production_orders", "status = 'processing'"),
            ("breakthrough_sessions", "status = 'preparing'"),
            ("travel_sessions", "status = 'running'"),
            ("exploration_sessions", "status IN ('created', 'running', 'combat_pending')"),
            ("battle_sessions", "status IN ('created', 'running')"),
            ("party_battle_members", "asset_lock_status = 'locked'"),
            ("final_battle_members", "asset_lock_status = 'locked'"),
            ("void_route_sessions", "status = 'running'"),
        )
        for table, predicate in checks:
            if connection.execute(
                f"SELECT 1 FROM {table} WHERE player_id = ? AND {predicate} LIMIT 1", (player_id,)
            ).fetchone() is not None:
                raise ArenaPlayerBusyError("player has another asset-locking session")

    @staticmethod
    def _find_owned_snapshot(
        connection: sqlite3.Connection, player_id: int, snapshot_id: str | None
    ) -> sqlite3.Row:
        if snapshot_id:
            row = connection.execute(
                "SELECT * FROM arena_snapshots WHERE snapshot_id = ? AND player_id = ?",
                (snapshot_id, player_id),
            ).fetchone()
        else:
            row = connection.execute(
                "SELECT * FROM arena_snapshots WHERE player_id = ? ORDER BY created_at DESC LIMIT 1",
                (player_id,),
            ).fetchone()
        if row is None:
            raise ArenaSnapshotNotFoundError("arena snapshot does not exist")
        return row

    @staticmethod
    def _expire_snapshot_row(connection: sqlite3.Connection, row: sqlite3.Row, now: datetime) -> None:
        if str(row["status"]) == "published" and datetime.fromisoformat(str(row["expires_at"])) <= now:
            connection.execute(
                "UPDATE arena_snapshots SET status = 'expired', updated_at = ? WHERE snapshot_id = ?",
                (serialize_datetime(now), row["snapshot_id"]),
            )

    def _arena_player_snapshot(
        self, connection: sqlite3.Connection, player: sqlite3.Row, snapshot_id: str
    ) -> dict[str, object]:
        qualification = self._json_map(player["qualification_json"])
        equipment = []
        attack_bonus = 0
        equipment_rows = connection.execute(
            "SELECT instance_id, item_key, slot, durability_bp, temper_level, affixes_json FROM equipment_instances "
            "WHERE player_id = ? AND status = 'active' AND durability_bp > 0 ORDER BY id",
            (player["id"],),
        ).fetchall()
        for item in equipment_rows:
            affixes = self._json_map(item["affixes_json"])
            attack_bonus += max(0, int(affixes.get("damage", 0)))
            attack_bonus += max(0, int(item["temper_level"])) * 4 if str(item["slot"]) == "weapon" else 0
            equipment.append(
                {
                    "item_key": str(item["item_key"]),
                    "slot": str(item["slot"]),
                    "durability_bp": int(item["durability_bp"]),
                    "temper_level": int(item["temper_level"]),
                    "affixes": {str(key): int(value) for key, value in affixes.items()},
                }
            )
        skills = tuple(
            str(row["skill_key"])
            for row in connection.execute(
                "SELECT skill_key FROM skill_masteries WHERE player_id = ? ORDER BY skill_key", (player["id"],)
            ).fetchall()
        )
        return {
            "snapshot_id": snapshot_id,
            "dao_name": str(player["dao_name"] or ""),
            "qualification": {str(key): int(value) for key, value in qualification.items()},
            "max_hp": int(player["max_hp"]),
            "initiative": int(player["initiative"]),
            "attack_bonus": attack_bonus,
            "path_key": player["path_key"],
            "realm_key": str(player["realm_key"]),
            "realm_layer": int(player["realm_layer"]),
            "skills": list(skills),
            "equipment": equipment,
        }

    @staticmethod
    def _json_map(raw: Any) -> dict[str, Any]:
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except json.JSONDecodeError:
                return {}
        return dict(raw) if isinstance(raw, dict) else {}

    @staticmethod
    def _arena_operation(
        connection: sqlite3.Connection, operation_id: str, operation_name: str, request_hash: str
    ) -> dict[str, Any] | None:
        existing = connection.execute(
            "SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id = ?",
            (operation_id,),
        ).fetchone()
        if existing is None:
            return None
        if existing["operation_name"] != operation_name or existing["request_hash"] != request_hash:
            raise OperationConflictError("operation input differs from its original request")
        return ArenaRepositoryMixin._json_map(existing["result_json"])

    @staticmethod
    def _arena_insert_operation(
        connection: sqlite3.Connection,
        operation_id: str,
        operation_name: str,
        player_id: int,
        request_hash: str,
        payload: dict[str, Any],
        now_text: str,
    ) -> None:
        connection.execute(
            "INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (operation_id, operation_name, player_id, request_hash, json.dumps(payload, ensure_ascii=False, sort_keys=True), now_text),
        )

    @staticmethod
    def _snapshot_payload_from_row(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "snapshot_id": str(row["snapshot_id"]),
            "status": str(row["status"]),
            "public_summary": ArenaRepositoryMixin._json_map(row["public_json"]),
            "rating": int(row["rating"]),
            "matchable_at": str(row["matchable_at"]),
            "expires_at": str(row["expires_at"]),
        }

    @staticmethod
    def _snapshot_from_payload(payload: dict[str, Any], *, already_completed: bool = False) -> ArenaSnapshotRecord:
        return ArenaSnapshotRecord(
            snapshot_id=str(payload["snapshot_id"]),
            status=str(payload["status"]),
            public_summary=ArenaRepositoryMixin._json_map(payload.get("public_summary", {})),
            rating=int(payload.get("rating", 0)),
            matchable_at=str(payload.get("matchable_at", "")),
            expires_at=str(payload.get("expires_at", "")),
            already_completed=already_completed,
        )

    @staticmethod
    def _snapshot_from_row(row: sqlite3.Row) -> ArenaSnapshotRecord:
        return ArenaSnapshotRecord(
            snapshot_id=str(row["snapshot_id"]),
            status=str(row["status"]),
            public_summary=ArenaRepositoryMixin._json_map(row["public_json"]),
            rating=int(row["rating"]),
            matchable_at=str(row["matchable_at"]),
            expires_at=str(row["expires_at"]),
        )

    @staticmethod
    def _match_from_payload(payload: dict[str, Any], *, already_completed: bool = False) -> ArenaMatchRecord:
        return ArenaMatchRecord(
            match_id=str(payload["match_id"]),
            mode_key=str(payload.get("mode_key", ARENA_MODE_KEY)),
            outcome=str(payload["outcome"]),
            rounds=int(payload["rounds"]),
            score_counted=bool(payload.get("score_counted", False)),
            challenger_rating=int(payload.get("challenger_rating", 0)),
            defender_rating=int(payload.get("defender_rating", 0)),
            challenger_rating_delta=int(payload.get("challenger_rating_delta", 0)),
            defender_rating_delta=int(payload.get("defender_rating_delta", 0)),
            opponent_summary=ArenaRepositoryMixin._json_map(payload.get("opponent_summary", {})),
            already_completed=already_completed,
        )

    @staticmethod
    def _arena_claim_from_payload(payload: dict[str, Any], *, already_completed: bool = False) -> ArenaClaimRecord:
        return ArenaClaimRecord(
            match_id=str(payload["match_id"]),
            reward={str(key): int(value) for key, value in ArenaRepositoryMixin._json_map(payload.get("reward", {})).items()},
            already_completed=already_completed,
        )


__all__ = ["ArenaRepositoryMixin"]
