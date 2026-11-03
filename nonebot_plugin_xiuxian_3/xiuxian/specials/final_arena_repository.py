"""SQLite transactions for the endgame final arena.

A challenge freezes its tier, enemy, round window and gates into the row and
its snapshot, then runs the shared server-authoritative battle.  Settlement
only advances the character's ladder position and writes display records:
no assets, no tribulation debt and no endgame status are touched, so the
frozen "不影响飞升资格" promise stays true.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from ...contracts import serialize_datetime
from ..events.rules import final_heaven_season_window
from ..persistence.errors import (
    BattleBusyError,
    FinalArenaAttemptCapError,
    FinalArenaChallengeNotFoundError,
    FinalArenaLocationRequiredError,
    FinalArenaNotOpenError,
    FinalArenaTierLockedError,
    OperationConflictError,
    PlayerNotFoundError,
    RepositoryBusyError,
    ResourceInsufficientError,
)
from ..utils.player import change_player_state, grant_player_honor_title, player_integer
from .final_arena_models import (
    FinalArenaChallengeRecord,
    FinalArenaPreviewRecord,
    FinalArenaTierState,
)
from .final_arena_rules import (
    DEFINITIONS,
    FinalArenaDefinition,
    arena_missing_requirements,
    arena_window,
    final_arena_definition,
)

ACTIVITY_EVENT_KEY = "final_arena.challenge"


class FinalArenaRepositoryMixin:
    """Persistence operations for the endgame final arena."""

    async def preview_final_arena(
        self, *, platform: str, platform_user_id: str
    ) -> FinalArenaPreviewRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._preview_final_arena_once, platform, platform_user_id
            )

    def _preview_final_arena_once(
        self, platform: str, platform_user_id: str
    ) -> FinalArenaPreviewRecord:
        definition = self._final_arena_definition()
        now = self._now()
        round_id, starts_at, ends_at, claim_expires_at = arena_window(now, definition)
        season_id = final_heaven_season_window(now)[0]
        with self._connect() as connection:
            player = self._require_player(connection, platform, platform_user_id)
            progress = self._final_arena_progress_row(connection, int(player["id"]), season_id)
            best_tier = int(progress["best_tier"]) if progress is not None else 0
            summit_cleared = bool(progress["summit_cleared"]) if progress is not None else False
            attempts_used = self._final_arena_attempts_used(
                connection, int(player["id"]), round_id
            )
            missing = arena_missing_requirements(
                realm_key=str(player["realm_key"]),
                realm_layer=player_integer(player, "realm_layer"),
                definition=definition,
            )
            cleared_tiers = {
                int(row["tier_no"])
                for row in connection.execute(
                    "SELECT tier_no FROM final_arena_challenges "
                    "WHERE player_id=? AND status='won'",
                    (int(player["id"]),),
                ).fetchall()
            }
            return FinalArenaPreviewRecord(
                location_key=definition.location_key,
                round_id=round_id,
                starts_at=serialize_datetime(starts_at),
                ends_at=serialize_datetime(ends_at),
                claim_expires_at=serialize_datetime(claim_expires_at),
                open=starts_at <= now.astimezone(starts_at.tzinfo) < ends_at,
                at_location=str(player["location_key"]) == definition.location_key,
                qualified=not missing,
                missing=missing,
                attempt_limit=definition.attempt_limit_per_round,
                attempts_used=attempts_used,
                best_tier=best_tier,
                summit_cleared=summit_cleared,
                tiers=tuple(
                    FinalArenaTierState(
                        key=tier.key,
                        label=tier.label,
                        tier_no=tier.tier_index,
                        enemy_key=tier.enemy_key,
                        required_best_tier=tier.required_best_tier,
                        unlocked=best_tier >= tier.required_best_tier,
                        cleared=tier.tier_index in cleared_tiers,
                        title_key=tier.title_key,
                    )
                    for tier in definition.tiers
                ),
            )

    async def start_final_arena_challenge(
        self, *, platform: str, platform_user_id: str, tier_key: str, operation_id: str
    ) -> FinalArenaChallengeRecord:
        await self.initialize()
        async with self._inflight:
            record = await asyncio.to_thread(
                self._start_final_arena_once, platform, platform_user_id, tier_key, operation_id
            )
        if record.status != "open":
            return record
        battle_operation = f"specials.final_arena.battle.start:{record.challenge_id}"
        try:
            battle = await self.start_quest_battle(
                platform=platform,
                platform_user_id=platform_user_id,
                enemy_key=record.enemy_key,
                battle_type="pve.final_arena",
                operation_id=battle_operation,
            )
        except Exception:
            await asyncio.to_thread(self._abort_final_arena_challenge, record.challenge_id)
            raise
        attached = await asyncio.to_thread(
            self._attach_final_arena_battle, record.challenge_id, battle.battle_id
        )
        return await self._resolve_final_arena_challenge(attached)

    def _start_final_arena_once(
        self, platform: str, platform_user_id: str, tier_key: str, operation_id: str
    ) -> FinalArenaChallengeRecord:
        definition = self._final_arena_definition()
        try:
            tier = definition.tier(tier_key)
        except ValueError as exc:
            raise FinalArenaTierLockedError(str(exc)) from exc
        operation_name = "specials.start_final_arena_challenge"
        request_payload = {
            "platform": platform,
            "platform_user_id": platform_user_id,
            "tier_key": tier_key,
        }
        request_hash = self._request_hash(operation_name, request_payload)
        now = self._now()
        now_text = serialize_datetime(now)
        round_id, starts_at, ends_at, _ = arena_window(now, definition)
        season_id = final_heaven_season_window(now)[0]
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            if existing is not None:
                if existing["operation_name"] != operation_name or existing["request_hash"] != request_hash:
                    raise OperationConflictError("operation input differs from its original request")
                return self._final_arena_challenge_from_payload(
                    json.loads(existing["result_json"]), replay=True
                )

            player = self._require_player(connection, platform, platform_user_id)
            if not (starts_at <= now < ends_at):
                raise FinalArenaNotOpenError("final arena round is closed")
            if str(player["location_key"]) != definition.location_key:
                raise FinalArenaLocationRequiredError("the player is not at the final arena")
            if arena_missing_requirements(
                realm_key=str(player["realm_key"]),
                realm_layer=player_integer(player, "realm_layer"),
                definition=definition,
            ):
                raise FinalArenaLocationRequiredError("final arena realm gate is not met")

            unfinished = connection.execute(
                "SELECT 1 FROM final_arena_challenges WHERE player_id=? AND status='open' LIMIT 1",
                (int(player["id"]),),
            ).fetchone()
            if unfinished is not None:
                raise BattleBusyError("an unfinished final arena challenge must be settled first")

            progress = self._final_arena_progress_row(connection, int(player["id"]), season_id)
            best_tier = int(progress["best_tier"]) if progress is not None else 0
            if best_tier < tier.required_best_tier:
                raise FinalArenaTierLockedError("the previous final arena tier is not cleared")

            attempts_used = self._final_arena_attempts_used(connection, int(player["id"]), round_id)
            if attempts_used >= definition.attempt_limit_per_round:
                raise FinalArenaAttemptCapError("final arena round attempts are exhausted")

            if player_integer(player, "stamina") < definition.stamina_cost:
                raise ResourceInsufficientError("stamina is insufficient")

            challenge_id = uuid4().hex
            change_player_state(
                connection,
                player,
                updated_at=now_text,
                value_delta={"stamina": -definition.stamina_cost},
            )
            snapshot = {
                "tier_key": tier.key,
                "tier_no": tier.tier_index,
                "enemy_key": tier.enemy_key,
                "required_best_tier": tier.required_best_tier,
                "title_key": tier.title_key,
                "round_id": round_id,
                "starts_at": serialize_datetime(starts_at),
                "ends_at": serialize_datetime(ends_at),
                "season_id": season_id,
                "location_key": definition.location_key,
                "stamina_cost": definition.stamina_cost,
                "attempt_limit": definition.attempt_limit_per_round,
                "attempts_used_before": attempts_used,
            }
            connection.execute(
                """
                INSERT INTO final_arena_challenges(
                    challenge_id, player_id, round_id, starts_at, ends_at, tier_key, tier_no,
                    enemy_key, status, snapshot_json, operation_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, ?, ?)
                """,
                (
                    challenge_id,
                    int(player["id"]),
                    round_id,
                    serialize_datetime(starts_at),
                    serialize_datetime(ends_at),
                    tier.key,
                    tier.tier_index,
                    tier.enemy_key,
                    json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
                    operation_id,
                    now_text,
                ),
            )
            payload = {
                "challenge_id": challenge_id,
                "tier_key": tier.key,
                "label": tier.label,
                "tier_no": tier.tier_index,
                "enemy_key": tier.enemy_key,
                "round_id": round_id,
                "starts_at": serialize_datetime(starts_at),
                "ends_at": serialize_datetime(ends_at),
                "attempts_used": attempts_used + 1,
                "attempt_limit": definition.attempt_limit_per_round,
                "best_tier": best_tier,
                "status": "open",
                "outcome": "",
                "reason": "",
                "summit_cleared": False,
                "title_granted": None,
            }
            connection.execute(
                "INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    operation_id,
                    operation_name,
                    int(player["id"]),
                    request_hash,
                    json.dumps(payload, ensure_ascii=False, sort_keys=True),
                    now_text,
                ),
            )
            return self._final_arena_challenge_from_payload(payload)

    def _abort_final_arena_challenge(self, challenge_id: str) -> None:
        """Refund an open challenge whose battle could not be started."""

        definition = self._final_arena_definition()
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            challenge = connection.execute(
                "SELECT * FROM final_arena_challenges WHERE challenge_id=?", (challenge_id,)
            ).fetchone()
            if challenge is None or str(challenge["status"]) != "open":
                return
            player = connection.execute(
                "SELECT * FROM players WHERE id=?", (challenge["player_id"],)
            ).fetchone()
            if player is None:
                return
            snapshot = self._json_object(challenge["snapshot_json"], {})
            stamina = int(snapshot.get("stamina_cost", definition.stamina_cost))
            connection.execute(
                "UPDATE final_arena_challenges SET status='expired', result_json=?, settled_at=? WHERE id=?",
                (
                    json.dumps(
                        {
                            "status": "expired",
                            "outcome": "expired",
                            "reason": "start_failed",
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    now_text,
                    challenge["id"],
                ),
            )
            change_player_state(
                connection,
                player,
                updated_at=now_text,
                value_delta={"stamina": stamina},
            )

    def _attach_final_arena_battle(self, challenge_id: str, battle_id: str) -> FinalArenaChallengeRecord:
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            challenge = connection.execute(
                "SELECT * FROM final_arena_challenges WHERE challenge_id=?", (challenge_id,)
            ).fetchone()
            if challenge is None:
                raise FinalArenaChallengeNotFoundError("final arena challenge does not exist")
            if challenge["battle_id"] is None:
                connection.execute(
                    "UPDATE final_arena_challenges SET battle_id=? WHERE id=?",
                    (battle_id, challenge["id"]),
                )
            challenge = connection.execute(
                "SELECT * FROM final_arena_challenges WHERE challenge_id=?", (challenge_id,)
            ).fetchone()
            return self._final_arena_challenge_from_row(challenge)

    async def _resolve_final_arena_challenge(
        self, record: FinalArenaChallengeRecord
    ) -> FinalArenaChallengeRecord:
        if record.status != "open" or not record.challenge_id:
            return record
        challenge = await asyncio.to_thread(self._final_arena_battle_id, record.challenge_id)
        if challenge is None:
            return record
        turn = None
        for expected_round in range(1, 21):
            turn = await self.run_battle_turn(battle_id=challenge, expected_round=expected_round)
            if turn.status not in {"created", "running"}:
                break
        resolved = await self.resolve_battle(battle_id=challenge)
        return await asyncio.to_thread(
            self._record_final_arena_outcome,
            record.challenge_id,
            resolved.outcome,
            resolved.reason,
        )

    async def settle_final_arena_challenge(
        self, *, platform: str, platform_user_id: str, operation_id: str
    ) -> FinalArenaChallengeRecord:
        """Resume and settle an unfinished arena challenge after a restart.

        A challenge whose battle was never attached (the process stopped
        between the entry write and the battle start) is expired and refunded
        instead of being reported as a settled fight.
        """

        await self.initialize()
        async with self._inflight:
            record = await asyncio.to_thread(
                self._final_arena_open_challenge, platform, platform_user_id
            )
        if record is None:
            raise FinalArenaChallengeNotFoundError("no open final arena challenge")
        if await asyncio.to_thread(self._final_arena_battle_id, record.challenge_id) is None:
            await asyncio.to_thread(self._abort_final_arena_challenge, record.challenge_id)
            cancelled = await asyncio.to_thread(
                self._final_arena_challenge_by_id, record.challenge_id
            )
            if cancelled is None:
                raise FinalArenaChallengeNotFoundError("final arena challenge does not exist")
            return cancelled
        return await self._resolve_final_arena_challenge(record)

    def _final_arena_open_challenge(
        self, platform: str, platform_user_id: str
    ) -> FinalArenaChallengeRecord | None:
        with self._connect() as connection:
            player = self._require_player(connection, platform, platform_user_id)
            row = connection.execute(
                "SELECT * FROM final_arena_challenges WHERE player_id=? AND status='open' "
                "ORDER BY id DESC LIMIT 1",
                (int(player["id"]),),
            ).fetchone()
            return self._final_arena_challenge_from_row(row) if row is not None else None

    def _final_arena_challenge_by_id(self, challenge_id: str) -> FinalArenaChallengeRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM final_arena_challenges WHERE challenge_id=?", (challenge_id,)
            ).fetchone()
        return self._final_arena_challenge_from_row(row) if row is not None else None

    def _final_arena_battle_id(self, challenge_id: str) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT battle_id FROM final_arena_challenges WHERE challenge_id=?", (challenge_id,)
            ).fetchone()
        if row is None or not row["battle_id"]:
            return None
        return str(row["battle_id"])

    def _record_final_arena_outcome(
        self, challenge_id: str, outcome: str, reason: str
    ) -> FinalArenaChallengeRecord:
        definition = self._final_arena_definition()
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            challenge = connection.execute(
                "SELECT * FROM final_arena_challenges WHERE challenge_id=?", (challenge_id,)
            ).fetchone()
            if challenge is None:
                raise FinalArenaChallengeNotFoundError("final arena challenge does not exist")
            player = connection.execute(
                "SELECT * FROM players WHERE id=?", (challenge["player_id"],)
            ).fetchone()
            if player is None:
                raise PlayerNotFoundError("final arena player does not exist")
            snapshot = self._json_object(challenge["snapshot_json"], {})
            if str(challenge["status"]) == "open":
                status = "won" if outcome == "won" else "lost"
                connection.execute(
                    "UPDATE final_arena_challenges SET status=?, result_json=?, settled_at=? WHERE id=?",
                    (
                        status,
                        json.dumps(
                            {"status": status, "outcome": outcome, "reason": reason},
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                        now_text,
                        challenge["id"],
                    ),
                )
            challenge = connection.execute(
                "SELECT * FROM final_arena_challenges WHERE challenge_id=?", (challenge_id,)
            ).fetchone()

            season_id = str(snapshot.get("season_id") or final_heaven_season_window(now)[0])
            tier_no = int(challenge["tier_no"])
            progress = self._final_arena_progress_row(connection, int(player["id"]), season_id)
            best_tier = int(progress["best_tier"]) if progress is not None else 0
            summit_cleared = bool(progress["summit_cleared"]) if progress is not None else False
            title_key = snapshot.get("title_key")
            title_granted: str | None = None
            if outcome == "won":
                best_tier = max(best_tier, tier_no)
                if title_key and tier_no == len(definition.tiers):
                    grant_player_honor_title(
                        connection,
                        int(player["id"]),
                        str(title_key),
                        f"specials.final_arena:{challenge_id}",
                        now_text,
                    )
                    summit_cleared = True
                    title_granted = str(title_key)
            if progress is None:
                connection.execute(
                    "INSERT INTO final_arena_progress(player_id, season_id, best_tier, summit_cleared, round_id, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        int(player["id"]),
                        season_id,
                        best_tier,
                        1 if summit_cleared else 0,
                        str(challenge["round_id"]),
                        now_text,
                    ),
                )
            else:
                connection.execute(
                    "UPDATE final_arena_progress SET best_tier=?, summit_cleared=?, round_id=?, updated_at=? WHERE id=?",
                    (
                        best_tier,
                        1 if summit_cleared else 0,
                        str(challenge["round_id"]),
                        now_text,
                        progress["id"],
                    ),
                )
            connection.execute(
                "INSERT OR IGNORE INTO activity_events(player_id, event_key, source_operation_id, occurred_at, payload_json) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    int(player["id"]),
                    ACTIVITY_EVENT_KEY,
                    str(challenge["operation_id"]),
                    now_text,
                    json.dumps(
                        {
                            "challenge_id": challenge_id,
                            "tier_key": str(challenge["tier_key"]),
                            "tier_no": tier_no,
                            "round_id": str(challenge["round_id"]),
                            "season_id": season_id,
                            "outcome": outcome,
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                ),
            )
            payload = {
                "challenge_id": challenge_id,
                "tier_key": str(challenge["tier_key"]),
                "label": str(snapshot.get("label") or challenge["tier_key"]),
                "tier_no": tier_no,
                "enemy_key": str(challenge["enemy_key"]),
                "round_id": str(challenge["round_id"]),
                "starts_at": str(challenge["starts_at"]),
                "ends_at": str(challenge["ends_at"]),
                "attempts_used": self._final_arena_attempts_used(
                    connection, int(player["id"]), str(challenge["round_id"])
                ),
                "attempt_limit": definition.attempt_limit_per_round,
                "best_tier": best_tier,
                "status": str(challenge["status"]),
                "outcome": outcome,
                "reason": reason,
                "summit_cleared": summit_cleared,
                "title_granted": title_granted,
            }
            connection.execute(
                "UPDATE operations SET result_json=? WHERE operation_id=?",
                (
                    json.dumps(payload, ensure_ascii=False, sort_keys=True),
                    str(challenge["operation_id"]),
                ),
            )
            return self._final_arena_challenge_from_payload(payload)

    def _final_arena_definition(self) -> FinalArenaDefinition:
        return final_arena_definition(self.content) if self.content is not None else DEFINITIONS

    @staticmethod
    def _final_arena_progress_row(connection: Any, player_id: int, season_id: str):
        return connection.execute(
            "SELECT * FROM final_arena_progress WHERE player_id=? AND season_id=?",
            (player_id, season_id),
        ).fetchone()

    @staticmethod
    def _final_arena_attempts_used(connection: Any, player_id: int, round_id: str) -> int:
        row = connection.execute(
            "SELECT COUNT(*) AS count FROM final_arena_challenges "
            "WHERE player_id=? AND round_id=? AND status<>'expired'",
            (player_id, round_id),
        ).fetchone()
        return int(row["count"] if row is not None else 0)

    @staticmethod
    def _final_arena_challenge_from_payload(
        payload: dict[str, Any], replay: bool = False
    ) -> FinalArenaChallengeRecord:
        return FinalArenaChallengeRecord(
            challenge_id=str(payload["challenge_id"]),
            tier_key=str(payload["tier_key"]),
            label=str(payload.get("label") or payload["tier_key"]),
            tier_no=int(payload["tier_no"]),
            enemy_key=str(payload["enemy_key"]),
            round_id=str(payload["round_id"]),
            starts_at=str(payload["starts_at"]),
            ends_at=str(payload["ends_at"]),
            attempts_used=int(payload["attempts_used"]),
            attempt_limit=int(payload["attempt_limit"]),
            best_tier=int(payload["best_tier"]),
            status=str(payload["status"]),
            outcome=str(payload.get("outcome", "")),
            reason=str(payload.get("reason", "")),
            summit_cleared=bool(payload.get("summit_cleared", False)),
            title_granted=str(payload["title_granted"]) if payload.get("title_granted") else None,
            already_completed=replay,
        )

    def _final_arena_challenge_from_row(self, row: Any) -> FinalArenaChallengeRecord:
        definition = self._final_arena_definition()
        snapshot = self._json_object(row["snapshot_json"], {})
        result = self._json_object(row["result_json"], {})
        try:
            tier = definition.tier(str(row["tier_key"]))
            label = tier.label
        except ValueError:
            label = str(row["tier_key"])
        return FinalArenaChallengeRecord(
            challenge_id=str(row["challenge_id"]),
            tier_key=str(row["tier_key"]),
            label=label,
            tier_no=int(row["tier_no"]),
            enemy_key=str(row["enemy_key"]),
            round_id=str(row["round_id"]),
            starts_at=str(row["starts_at"]),
            ends_at=str(row["ends_at"]),
            attempts_used=int(snapshot.get("attempts_used_before", 0)) + 1,
            attempt_limit=int(snapshot.get("attempt_limit", definition.attempt_limit_per_round)),
            best_tier=int(snapshot.get("required_best_tier", 0)),
            status=str(row["status"]),
            outcome=str(result.get("outcome", "")),
            reason=str(result.get("reason", "")),
            summit_cleared=bool(result.get("summit_cleared", False)),
            title_granted=str(snapshot["title_key"]) if snapshot.get("title_key") else None,
        )


__all__ = ["ACTIVITY_EVENT_KEY", "FinalArenaRepositoryMixin"]
