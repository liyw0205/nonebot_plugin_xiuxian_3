"""SQLite transactions for the asynchronous 2v2 team arena slice."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from ...contracts import serialize_datetime
from ..persistence.errors import (
    OperationConflictError,
    TeamArenaBusyError,
    TeamArenaChallengeCapError,
    TeamArenaOpponentUnavailableError,
    TeamArenaPermissionError,
    TeamArenaSnapshotNotFoundError,
    TeamArenaSnapshotRequirementError,
)
from .team_arena_models import TeamArenaMatchRecord, TeamArenaReplayRecord, TeamArenaSnapshotRecord
from .team_arena_rules import (
    TEAM_ARENA_MODE_KEY,
    TEAM_DAILY_CHALLENGE_LIMIT,
    TEAM_LOSS_RATING_DELTA,
    MAX_TEAM_SIZE,
    MIN_TEAM_SIZE,
    TEAM_SNAPSHOT_MATCH_DELAY_SECONDS,
    TEAM_SNAPSHOT_VALID_DAYS,
    TEAM_WIN_RATING_DELTA,
    compatible_team_rating,
    simulate_team_match,
    team_public_summary,
    team_rating,
)


class TeamArenaRepositoryMixin:
    """Own immutable party snapshots, 2v2 matches and action replays."""

    async def publish_team_arena_snapshot(self, *, platform: str, platform_user_id: str, operation_id: str) -> TeamArenaSnapshotRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._retry_sync, self._publish_team_arena_snapshot_once, platform, platform_user_id, operation_id)

    async def list_team_arena_snapshots(self, *, platform: str, platform_user_id: str) -> tuple[TeamArenaSnapshotRecord, ...]:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._list_team_arena_snapshots_once, platform, platform_user_id)

    async def challenge_team_arena(self, *, platform: str, platform_user_id: str, snapshot_id: str | None, operation_id: str, request_id: str = "") -> TeamArenaMatchRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._retry_sync, self._challenge_team_arena_once, platform, platform_user_id, snapshot_id, operation_id, request_id)

    async def replay_team_arena(self, *, platform: str, platform_user_id: str, match_id: str | None = None) -> TeamArenaReplayRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._replay_team_arena_once, platform, platform_user_id, match_id)

    def _publish_team_arena_snapshot_once(self, platform: str, platform_user_id: str, operation_id: str) -> TeamArenaSnapshotRecord:
        operation_name = "specials.publish_team_arena_snapshot"
        request_payload = {"platform": platform, "platform_user_id": platform_user_id, "mode_key": TEAM_ARENA_MODE_KEY}
        request_hash = self._request_hash(operation_name, request_payload)
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._team_arena_operation(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                return self._team_snapshot_from_payload(replay, already_completed=True)
            leader = self._require_player(connection, platform, platform_user_id)
            party, members = self._team_arena_party(connection, int(leader["id"]), require_leader=True)
            self._team_arena_require_ready(party, members)
            if party["current_session_id"]:
                raise TeamArenaBusyError("party already has an active session")
            snapshot_id = f"arena.team.snapshot:{uuid4().hex}"
            snapshot = self._team_arena_build_snapshot(connection, party, members, snapshot_id)
            old = connection.execute(
                "SELECT snapshot_id FROM arena_team_snapshots WHERE party_id = ? AND status = 'published'", (party["party_id"],)
            ).fetchall()
            connection.execute(
                "UPDATE arena_team_snapshots SET status = 'revoked', revoked_at = ?, updated_at = ? WHERE party_id = ? AND status = 'published'",
                (now_text, now_text, party["party_id"]),
            )
            expires_at = now + timedelta(days=TEAM_SNAPSHOT_VALID_DAYS)
            matchable_at = now + timedelta(seconds=TEAM_SNAPSHOT_MATCH_DELAY_SECONDS)
            rating = team_rating(snapshot["members"])
            summary = team_public_summary(snapshot, snapshot_id=snapshot_id, rating=rating, created_at=now_text)
            connection.execute(
                "INSERT INTO arena_team_snapshots(snapshot_id, party_id, leader_id, status, rating, matchable_at, expires_at, snapshot_json, public_json, content_version, rule_version, created_at, updated_at) VALUES (?, ?, ?, 'published', ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (snapshot_id, party["party_id"], leader["id"], rating, serialize_datetime(matchable_at), serialize_datetime(expires_at), json.dumps(snapshot, ensure_ascii=False, sort_keys=True), json.dumps(summary, ensure_ascii=False, sort_keys=True), "content-0.6", "arena.team-0.1.0", now_text, now_text),
            )
            payload = {"snapshot_id": snapshot_id, "party_id": str(party["party_id"]), "status": "published", "public_summary": summary, "rating": rating, "matchable_at": serialize_datetime(matchable_at), "expires_at": serialize_datetime(expires_at), "replaced_snapshot_ids": [str(item["snapshot_id"]) for item in old]}
            self._team_arena_insert_operation(connection, operation_id, operation_name, int(leader["id"]), request_hash, payload, now_text)
            return self._team_snapshot_from_payload(payload)

    def _list_team_arena_snapshots_once(self, platform: str, platform_user_id: str) -> tuple[TeamArenaSnapshotRecord, ...]:
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            player = self._require_player(connection, platform, platform_user_id, writable=False)
            self._team_arena_expire_due(connection, now_text)
            rows = connection.execute(
                "SELECT * FROM arena_team_snapshots WHERE status = 'published' AND matchable_at <= ? AND expires_at > ? AND party_id NOT IN (SELECT party_id FROM party_members WHERE player_id = ? AND status = 'active') ORDER BY ABS(rating - ?), created_at",
                (now_text, now_text, player["id"], player["arena_rating"]),
            ).fetchall()
            return tuple(self._team_snapshot_from_row(row) for row in rows if compatible_team_rating(int(player["arena_rating"]), int(row["rating"])))

    def _challenge_team_arena_once(self, platform: str, platform_user_id: str, requested_snapshot_id: str | None, operation_id: str, request_id: str = "") -> TeamArenaMatchRecord:
        operation_name = "specials.challenge_team_arena"
        request_payload = {"platform": platform, "platform_user_id": platform_user_id, "snapshot_id": requested_snapshot_id, "mode_key": TEAM_ARENA_MODE_KEY}
        request_hash = self._request_hash(operation_name, request_payload)
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._team_arena_operation(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                return self._team_match_from_payload(replay, already_completed=True)
            leader = self._require_player(connection, platform, platform_user_id)
            party, members = self._team_arena_party(connection, int(leader["id"]), require_leader=True)
            self._team_arena_require_ready(party, members)
            if party["current_session_id"]:
                raise TeamArenaBusyError("party already has an active session")
            attempts = connection.execute(
                "SELECT COUNT(*) AS total FROM arena_team_matches m JOIN arena_team_snapshots s ON s.snapshot_id = m.challenger_snapshot_id WHERE s.party_id = ? AND m.created_at LIKE ?",
                (party["party_id"], now.date().isoformat() + "%"),
            ).fetchone()
            if int(attempts["total"]) >= TEAM_DAILY_CHALLENGE_LIMIT:
                raise TeamArenaChallengeCapError("team arena daily challenge cap has been reached")
            self._team_arena_expire_due(connection, now_text)
            if requested_snapshot_id:
                defender = connection.execute("SELECT * FROM arena_team_snapshots WHERE snapshot_id = ?", (requested_snapshot_id.strip(),)).fetchone()
            else:
                challenger_rating = team_rating(self._team_arena_build_snapshot(connection, party, members, "pending")["members"])
                candidates = connection.execute(
                    "SELECT * FROM arena_team_snapshots WHERE status = 'published' AND matchable_at <= ? AND expires_at > ? AND party_id <> ? ORDER BY ABS(rating - ?), created_at",
                    (now_text, now_text, party["party_id"], challenger_rating),
                ).fetchall()
                defender = next((candidate for candidate in candidates if compatible_team_rating(challenger_rating, int(candidate["rating"]))), None)
            if defender is None or str(defender["status"]) != "published" or str(defender["party_id"]) == str(party["party_id"]):
                raise TeamArenaSnapshotNotFoundError("team arena snapshot does not exist") if requested_snapshot_id else TeamArenaOpponentUnavailableError("no compatible team snapshot is available")
            if datetime.fromisoformat(str(defender["expires_at"])) <= now or datetime.fromisoformat(str(defender["matchable_at"])) > now:
                raise TeamArenaOpponentUnavailableError("team snapshot is not currently matchable")
            challenger_row = connection.execute(
                "SELECT * FROM arena_team_snapshots WHERE party_id = ? AND status = 'published' ORDER BY created_at DESC LIMIT 1",
                (party["party_id"],),
            ).fetchone()
            if challenger_row is None:
                raise TeamArenaSnapshotRequirementError("publish a team snapshot before challenging")
            challenger_snapshot = self._json_map(challenger_row["snapshot_json"])
            if not MIN_TEAM_SIZE <= len(challenger_snapshot.get("members", [])) <= MAX_TEAM_SIZE:
                raise TeamArenaSnapshotRequirementError("challenger team snapshot is invalid")
            defender_snapshot = self._json_map(defender["snapshot_json"])
            challenger_rating = team_rating(challenger_snapshot["members"])
            defender_rating = int(defender["rating"])
            if not compatible_team_rating(challenger_rating, defender_rating):
                raise TeamArenaOpponentUnavailableError("team snapshot is outside the compatible rating band")
            defender_members = list(defender_snapshot.get("members", []))
            if not MIN_TEAM_SIZE <= len(defender_members) <= MAX_TEAM_SIZE or {member.get("database_id") for member in challenger_snapshot["members"]} & {member.get("database_id") for member in defender_members}:
                raise TeamArenaSnapshotRequirementError("team snapshots must contain two or three distinct members")
            match_id = f"arena.team.match:{uuid4().hex}"
            outcome, rounds, actions = simulate_team_match(challenger_snapshot["members"], defender_members, seed=match_id)
            challenger_delta, defender_delta = self._team_rating_deltas(outcome)
            full_snapshot = {"mode_key": TEAM_ARENA_MODE_KEY, "challenger": challenger_snapshot, "defender": defender_snapshot}
            result = {"outcome": outcome, "rounds": rounds, "challenger_rating_delta": challenger_delta, "defender_rating_delta": defender_delta, "request_id": request_id, "operation_id": operation_id, "content_version": "content-0.6", "rule_version": "arena.team-0.1.0"}
            connection.execute(
                "INSERT INTO arena_team_matches(match_id, challenger_leader_id, defender_leader_id, challenger_snapshot_id, defender_snapshot_id, status, outcome, rounds, challenger_rating_delta, defender_rating_delta, snapshot_json, result_json, operation_id, created_at, settled_at) VALUES (?, ?, ?, ?, ?, 'settled', ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (match_id, leader["id"], defender["leader_id"], challenger_row["snapshot_id"], defender["snapshot_id"], outcome, rounds, challenger_delta, defender_delta, json.dumps(full_snapshot, ensure_ascii=False, sort_keys=True), json.dumps(result, ensure_ascii=False, sort_keys=True), operation_id, now_text, now_text),
            )
            for action in actions:
                connection.execute(
                    "INSERT INTO arena_team_actions(action_id, match_id, sequence_no, round_no, actor_key, strategy_key, skill_key, target_key, hit_roll_bp, damage, state_json, operation_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (uuid4().hex, match_id, action["sequence_no"], action["round_no"], action["actor_key"], action["strategy_key"], action["skill_key"], action["target_key"], action["hit_roll_bp"], action["damage"], json.dumps(action["state"], ensure_ascii=False, sort_keys=True), f"{operation_id}:{action['sequence_no']}", now_text),
                )
            self._team_arena_update_ratings(connection, challenger_snapshot["members"], challenger_delta, outcome == "challenger_won", outcome == "draw", now_text)
            self._team_arena_update_ratings(connection, defender_members, defender_delta, outcome == "defender_won", outcome == "draw", now_text)
            projection = self._project_arena_result(
                connection,
                match_id=match_id,
                operation_id=operation_id,
                mode_key=TEAM_ARENA_MODE_KEY,
                outcome=outcome,
                score_counted=True,
                settled_at=now_text,
                request_id=request_id,
                participants=(
                    *({"player_id": int(member["database_id"]), "side": "challenger"} for member in challenger_snapshot["members"]),
                    *({"player_id": int(member["database_id"]), "side": "defender"} for member in defender_members),
                ),
            )
            payload = {"match_id": match_id, "outcome": outcome, "rounds": rounds, "challenger_rating": challenger_rating + challenger_delta, "defender_rating": defender_rating + defender_delta, "challenger_rating_delta": challenger_delta, "defender_rating_delta": defender_delta, "opponent_summary": self._json_map(defender["public_json"]), "projection": projection}
            connection.execute(
                "UPDATE arena_team_matches SET result_json = ? WHERE match_id = ?",
                (json.dumps(payload, ensure_ascii=False, sort_keys=True), match_id),
            )
            self._team_arena_insert_operation(connection, operation_id, operation_name, int(leader["id"]), request_hash, payload, now_text)
            return self._team_match_from_payload(payload)

    def _replay_team_arena_once(self, platform: str, platform_user_id: str, match_id: str | None) -> TeamArenaReplayRecord:
        with self._connect() as connection:
            player = self._require_player(connection, platform, platform_user_id, writable=False)
            if match_id:
                row = connection.execute("SELECT * FROM arena_team_matches WHERE match_id = ?", (match_id.strip(),)).fetchone()
                if row is None:
                    raise TeamArenaSnapshotNotFoundError("team arena match does not exist")
                snapshot = self._json_map(row["snapshot_json"])
                member_ids = {int(member.get("database_id", -1)) for side in ("challenger", "defender") for member in snapshot.get(side, {}).get("members", [])}
                if int(player["id"]) not in member_ids:
                    raise TeamArenaPermissionError("only a team member can view this replay")
            else:
                rows = connection.execute("SELECT * FROM arena_team_matches ORDER BY id DESC LIMIT 50").fetchall()
                row = next((candidate for candidate in rows if self._team_arena_player_in_snapshot(candidate["snapshot_json"], int(player["id"]))), None)
                if row is None:
                    raise TeamArenaSnapshotNotFoundError("no team arena match exists")
                snapshot = self._json_map(row["snapshot_json"])
            actions = connection.execute("SELECT * FROM arena_team_actions WHERE match_id = ? ORDER BY sequence_no", (row["match_id"],)).fetchall()
            return TeamArenaReplayRecord(match_id=str(row["match_id"]), status=str(row["status"]), outcome=str(row["outcome"]), rounds=int(row["rounds"]), snapshot=snapshot, result=self._json_map(row["result_json"]), actions=tuple({"sequence_no": int(action["sequence_no"]), "round_no": int(action["round_no"]), "actor_key": str(action["actor_key"]), "skill_key": str(action["skill_key"]), "target_key": str(action["target_key"]), "damage": int(action["damage"]), "state": self._json_map(action["state_json"])} for action in actions))

    def _team_arena_party(self, connection, player_id: int, *, require_leader: bool):
        membership = connection.execute("SELECT * FROM party_members WHERE player_id = ? AND status = 'active' ORDER BY id DESC LIMIT 1", (player_id,)).fetchone()
        if membership is None:
            raise TeamArenaPermissionError("player is not in a ready party")
        if require_leader and str(membership["role"]) != "leader":
            raise TeamArenaPermissionError("only the party leader can operate team arena")
        party = connection.execute("SELECT * FROM parties WHERE party_id = ?", (membership["party_id"],)).fetchone()
        if party is None:
            raise TeamArenaPermissionError("party does not exist")
        members = connection.execute(
            "SELECT m.*, p.player_id AS stable_player_id, p.platform_user_id, p.dao_name, p.path_key, p.qualification_json, p.max_hp, p.initiative, p.realm_key, p.realm_layer, p.arena_rating, p.location_key, p.status AS player_status FROM party_members m JOIN players p ON p.id = m.player_id WHERE m.party_id = ? AND m.status = 'active' ORDER BY m.id",
            (party["party_id"],),
        ).fetchall()
        return party, members

    @staticmethod
    def _team_arena_require_ready(party, members) -> None:
        expected = {"exploration_pair": 2, "arena_trio": 3}.get(str(party["party_type"]))
        if expected is None or str(party["status"]) != "ready" or len(members) != expected or any(not member["confirmed_at"] or str(member["player_status"]) != "active" for member in members):
            raise TeamArenaSnapshotRequirementError("a confirmed active two- or three-player arena party is required")

    def _team_arena_build_snapshot(self, connection, party, members, snapshot_id: str) -> dict[str, object]:
        result: list[dict[str, object]] = []
        for member in members:
            player_row = dict(member)
            player_row["id"] = member["player_id"]
            player_snapshot = self._arena_player_snapshot(connection, player_row, snapshot_id + ":" + str(member["stable_player_id"]))
            player_snapshot.update({"player_id": str(member["stable_player_id"]), "database_id": int(member["player_id"]), "dao_name": str(member["dao_name"] or ""), "arena_rating": int(member["arena_rating"])})
            result.append(player_snapshot)
        return {"mode_key": TEAM_ARENA_MODE_KEY, "snapshot_id": snapshot_id, "party_id": str(party["party_id"]), "members": result}

    def _team_arena_update_ratings(self, connection, members, delta: int, won: bool, drawn: bool, now_text: str) -> None:
        for member in members:
            database_id = int(member["database_id"])
            row = connection.execute("SELECT arena_rating, arena_wins, arena_losses, arena_draws FROM players WHERE id = ?", (database_id,)).fetchone()
            if row is None:
                continue
            connection.execute("UPDATE players SET arena_rating = ?, arena_wins = ?, arena_losses = ?, arena_draws = ?, updated_at = ? WHERE id = ?", (max(0, int(row["arena_rating"]) + delta), int(row["arena_wins"]) + int(won), int(row["arena_losses"]) + int(not won and not drawn), int(row["arena_draws"]) + int(drawn), now_text, database_id))

    @staticmethod
    def _team_rating_deltas(outcome: str) -> tuple[int, int]:
        if outcome == "draw":
            return 4, 4
        return (TEAM_WIN_RATING_DELTA, TEAM_LOSS_RATING_DELTA) if outcome == "challenger_won" else (TEAM_LOSS_RATING_DELTA, TEAM_WIN_RATING_DELTA)

    @staticmethod
    def _team_arena_player_in_snapshot(raw: str, player_id: int) -> bool:
        snapshot = TeamArenaRepositoryMixin._json_map(raw)
        return any(int(member.get("database_id", -1)) == player_id for side in ("challenger", "defender") for member in snapshot.get(side, {}).get("members", []))

    @staticmethod
    def _team_arena_expire_due(connection, now_text: str) -> None:
        connection.execute("UPDATE arena_team_snapshots SET status = 'expired', updated_at = ? WHERE status = 'published' AND expires_at <= ?", (now_text, now_text))

    @staticmethod
    def _team_snapshot_from_payload(payload: dict[str, Any], *, already_completed: bool = False) -> TeamArenaSnapshotRecord:
        return TeamArenaSnapshotRecord(snapshot_id=str(payload["snapshot_id"]), party_id=str(payload["party_id"]), status=str(payload["status"]), public_summary=dict(payload["public_summary"]), rating=int(payload["rating"]), matchable_at=str(payload["matchable_at"]), expires_at=str(payload["expires_at"]), already_completed=already_completed)

    @staticmethod
    def _team_snapshot_from_row(row) -> TeamArenaSnapshotRecord:
        return TeamArenaSnapshotRecord(snapshot_id=str(row["snapshot_id"]), party_id=str(row["party_id"]), status=str(row["status"]), public_summary=TeamArenaRepositoryMixin._json_map(row["public_json"]), rating=int(row["rating"]), matchable_at=str(row["matchable_at"]), expires_at=str(row["expires_at"]))

    @staticmethod
    def _team_match_from_payload(payload: dict[str, Any], *, already_completed: bool = False) -> TeamArenaMatchRecord:
        return TeamArenaMatchRecord(match_id=str(payload["match_id"]), outcome=str(payload["outcome"]), rounds=int(payload["rounds"]), challenger_rating=int(payload["challenger_rating"]), defender_rating=int(payload["defender_rating"]), opponent_summary=dict(payload["opponent_summary"]), already_completed=already_completed)

    @staticmethod
    def _team_arena_operation(connection, operation_id: str, operation_name: str, request_hash: str) -> dict[str, Any] | None:
        existing = connection.execute("SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id = ?", (operation_id,)).fetchone()
        if existing is None:
            return None
        if existing["operation_name"] != operation_name or existing["request_hash"] != request_hash:
            raise OperationConflictError("operation input differs from its original request")
        return TeamArenaRepositoryMixin._json_map(existing["result_json"])

    @staticmethod
    def _team_arena_insert_operation(connection, operation_id: str, operation_name: str, player_id: int, request_hash: str, payload: dict[str, Any], now_text: str) -> None:
        connection.execute("INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)", (operation_id, operation_name, player_id, request_hash, json.dumps(payload, ensure_ascii=False, sort_keys=True), now_text))

    @staticmethod
    def _json_map(raw: Any) -> dict[str, Any]:
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except json.JSONDecodeError:
                return {}
        return dict(raw) if isinstance(raw, dict) else {}


__all__ = ["TeamArenaRepositoryMixin"]
