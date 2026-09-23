"""SQLite transactions for the v0.1 world-event slice."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any

from ...contracts import serialize_datetime
from ..persistence.errors import (
    EventContributionInsufficientError,
    EventNotActiveError,
    EventRewardAlreadyClaimedError,
    EventRewardExpiredError,
    OperationConflictError,
)
from .models import SpiritSpringEventRecord
from .rules import (
    EVENT_KEY,
    EVENT_LOCATION,
    EVENT_RULE_VERSION,
    EVENT_TARGET,
    PERSONAL_CONTRIBUTION_CAP,
    PERSONAL_REWARD_THRESHOLD,
    event_times,
    round_id_for,
    scheduled_start,
)


class EventsRepositoryMixin:
    """Own event rounds, contribution idempotency and event rewards."""

    async def get_spirit_spring_event(
        self,
        *,
        platform: str,
        platform_user_id: str,
        round_id: str | None = None,
    ) -> SpiritSpringEventRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._event_get_once,
                platform,
                platform_user_id,
                round_id,
            )

    async def claim_spirit_spring_event(
        self,
        *,
        platform: str,
        platform_user_id: str,
        round_id: str | None,
        operation_id: str,
    ) -> SpiritSpringEventRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._event_claim_once,
                platform,
                platform_user_id,
                round_id,
                operation_id,
            )

    def _event_get_once(
        self,
        platform: str,
        platform_user_id: str,
        round_id: str | None,
    ) -> SpiritSpringEventRecord:
        now = self._now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            player = self._require_player(connection, platform, platform_user_id, writable=False)
            event = self._event_select_round(connection, round_id, now)
            if event is None:
                raise EventNotActiveError("no spirit spring event is available")
            event = self._event_refresh_round(connection, event, now)
            return self._event_record(connection, player, event)

    def _event_claim_once(
        self,
        platform: str,
        platform_user_id: str,
        round_id: str | None,
        operation_id: str,
    ) -> SpiritSpringEventRecord:
        operation_name = "event.claim_reward"
        request_hash = self._request_hash(
            operation_name,
            {
                "platform": platform,
                "platform_user_id": platform_user_id,
                "round_id": round_id or "",
            },
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
                if existing["operation_name"] != operation_name or existing["request_hash"] != request_hash:
                    raise OperationConflictError("operation input differs from its original request")
                return self._event_record_from_payload(json.loads(existing["result_json"]), replay=True)
            player = self._require_player(connection, platform, platform_user_id)
            event = self._event_select_round(connection, round_id, now)
            if event is None:
                raise EventNotActiveError("no spirit spring event is available")
            event = self._event_refresh_round(connection, event, now)
            if str(event["status"]) not in {"settled", "failed"}:
                raise EventNotActiveError("the event is not settled")
            if now >= datetime.fromisoformat(str(event["claim_expires_at"])):
                raise EventRewardExpiredError("the event reward window has closed")
            contribution_row = connection.execute(
                "SELECT contribution FROM world_event_contributions WHERE round_id = ? AND player_id = ?",
                (event["round_id"], player["id"]),
            ).fetchone()
            contribution = int(contribution_row["contribution"]) if contribution_row else 0
            if contribution < PERSONAL_REWARD_THRESHOLD:
                raise EventContributionInsufficientError("event contribution is insufficient")
            claimed = connection.execute(
                "SELECT 1 FROM world_event_claims WHERE round_id = ? AND player_id = ?",
                (event["round_id"], player["id"]),
            ).fetchone()
            if claimed is not None:
                raise EventRewardAlreadyClaimedError("event reward has already been claimed")

            success = bool(self._json_object(event["result_json"], {}).get("success", False))
            reward: dict[str, int] = {"cultivation": 150, "spirit_stones": 100}
            faction = self._json_object(player["faction_reputation_json"], {})
            if success:
                reward["faction_reputation.xuantian"] = 10
            faction_before = int(faction.get("xuantian", 0))
            faction_after = faction_before + reward.get("faction_reputation.xuantian", 0)
            if success:
                faction["xuantian"] = faction_after
            connection.execute(
                """
                UPDATE players
                SET cultivation = cultivation + ?, total_cultivation = total_cultivation + ?,
                    spirit_stones = spirit_stones + ?, faction_reputation_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    reward["cultivation"],
                    reward["cultivation"],
                    reward["spirit_stones"],
                    json.dumps(faction, ensure_ascii=False, sort_keys=True),
                    now_text,
                    player["id"],
                ),
            )
            connection.execute(
                """
                INSERT INTO world_event_claims(
                    round_id, player_id, operation_id, reward_json, claimed_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    event["round_id"],
                    player["id"],
                    operation_id,
                    json.dumps(reward, ensure_ascii=False, sort_keys=True),
                    now_text,
                ),
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO activity_events(
                    player_id, event_key, source_operation_id, occurred_at, payload_json
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    player["id"],
                    "event.spirit_spring.claim",
                    operation_id,
                    now_text,
                    json.dumps({"round_id": event["round_id"], "reward": reward}, ensure_ascii=False, sort_keys=True),
                ),
            )
            updated_player = connection.execute("SELECT * FROM players WHERE id = ?", (player["id"],)).fetchone()
            payload = self._event_payload(
                connection,
                updated_player,
                event,
                contribution,
                reward,
            )
            connection.execute(
                """
                INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    operation_id,
                    operation_name,
                    player["id"],
                    request_hash,
                    json.dumps(payload, ensure_ascii=False, sort_keys=True),
                    now_text,
                ),
            )
            return self._event_record_from_payload(payload)

    def _event_select_round(
        self,
        connection: Any,
        round_id: str | None,
        now: datetime,
    ) -> Any:
        if round_id:
            return connection.execute(
                "SELECT * FROM world_event_rounds WHERE event_key = ? AND round_id = ?",
                (EVENT_KEY, round_id),
            ).fetchone()
        start = scheduled_start(now)
        if start is not None:
            current_id = round_id_for(start)
            self._event_insert_round(connection, current_id, start)
            row = connection.execute(
                "SELECT * FROM world_event_rounds WHERE event_key = ? AND round_id = ?",
                (EVENT_KEY, current_id),
            ).fetchone()
            if row is not None:
                return row
        return connection.execute(
            """
            SELECT * FROM world_event_rounds
            WHERE event_key = ? AND claim_expires_at > ?
            ORDER BY starts_at DESC LIMIT 1
            """,
            (EVENT_KEY, serialize_datetime(now)),
        ).fetchone()

    def _event_insert_round(self, connection: Any, round_id: str, start: datetime) -> None:
        starts_at, ends_at, claim_expires_at = event_times(start)
        connection.execute(
            """
            INSERT OR IGNORE INTO world_event_rounds(
                round_id, event_key, location_key, status, starts_at, ends_at,
                claim_expires_at, target_quantity, total_contribution, result_json,
                rule_version, created_at, updated_at
            ) VALUES (?, ?, ?, 'open', ?, ?, ?, ?, 0, '{}', ?, ?, ?)
            """,
            (
                round_id,
                EVENT_KEY,
                EVENT_LOCATION,
                serialize_datetime(starts_at),
                serialize_datetime(ends_at),
                serialize_datetime(claim_expires_at),
                EVENT_TARGET,
                EVENT_RULE_VERSION,
                serialize_datetime(start),
                serialize_datetime(start),
            ),
        )

    def _event_refresh_round(self, connection: Any, event: Any, now: datetime) -> Any:
        status = str(event["status"])
        ends_at = datetime.fromisoformat(str(event["ends_at"]))
        if status in {"open", "running"} and now >= ends_at:
            total_row = connection.execute(
                "SELECT COALESCE(SUM(contribution), 0) AS total FROM world_event_contributions WHERE round_id = ?",
                (event["round_id"],),
            ).fetchone()
            total = int(total_row["total"] if total_row else 0)
            success = total >= int(event["target_quantity"])
            connection.execute(
                """
                UPDATE world_event_rounds
                SET status = 'settled', total_contribution = ?, result_json = ?, updated_at = ?
                WHERE round_id = ? AND status IN ('open', 'running')
                """,
                (
                    total,
                    json.dumps({"success": success, "settled_at": serialize_datetime(now)}, ensure_ascii=False, sort_keys=True),
                    serialize_datetime(now),
                    event["round_id"],
                ),
            )
            event = connection.execute(
                "SELECT * FROM world_event_rounds WHERE round_id = ?", (event["round_id"],)
            ).fetchone()
        return event

    def _event_record(self, connection: Any, player: Any, event: Any) -> SpiritSpringEventRecord:
        contribution_row = connection.execute(
            "SELECT contribution FROM world_event_contributions WHERE round_id = ? AND player_id = ?",
            (event["round_id"], player["id"]),
        ).fetchone()
        contribution = int(contribution_row["contribution"]) if contribution_row else 0
        result = self._json_object(event["result_json"], {})
        return SpiritSpringEventRecord(
            player=self._row_to_player(player),
            round_id=str(event["round_id"]),
            event_key=str(event["event_key"]),
            status=str(event["status"]),
            starts_at=str(event["starts_at"]),
            ends_at=str(event["ends_at"]),
            claim_expires_at=str(event["claim_expires_at"]),
            target_quantity=int(event["target_quantity"]),
            total_contribution=int(event["total_contribution"]),
            player_contribution=contribution,
            success=result.get("success") if "success" in result else None,
            reward={},
        )

    def _event_payload(
        self,
        connection: Any,
        player: Any,
        event: Any,
        contribution: int,
        reward: dict[str, int],
    ) -> dict[str, Any]:
        result = self._json_object(event["result_json"], {})
        return {
            "player": self._player_payload(self._row_to_player(player)),
            "round_id": str(event["round_id"]),
            "event_key": str(event["event_key"]),
            "status": str(event["status"]),
            "starts_at": str(event["starts_at"]),
            "ends_at": str(event["ends_at"]),
            "claim_expires_at": str(event["claim_expires_at"]),
            "target_quantity": int(event["target_quantity"]),
            "total_contribution": int(event["total_contribution"]),
            "player_contribution": contribution,
            "success": result.get("success"),
            "reward": reward,
        }

    @staticmethod
    def _event_record_from_payload(payload: dict[str, Any], replay: bool = False) -> SpiritSpringEventRecord:
        from ..persistence.sqlite_repository import SQLitePlayerRepository

        return SpiritSpringEventRecord(
            player=SQLitePlayerRepository._row_to_player(payload["player"]),
            round_id=str(payload["round_id"]),
            event_key=str(payload["event_key"]),
            status=str(payload["status"]),
            starts_at=str(payload["starts_at"]),
            ends_at=str(payload["ends_at"]),
            claim_expires_at=str(payload["claim_expires_at"]),
            target_quantity=int(payload["target_quantity"]),
            total_contribution=int(payload["total_contribution"]),
            player_contribution=int(payload.get("player_contribution", 0)),
            success=payload.get("success"),
            reward={str(key): int(value) for key, value in dict(payload.get("reward", {})).items()},
            already_completed=replay,
        )

    def _record_spirit_spring_contribution(
        self,
        connection: Any,
        *,
        player_id: int,
        source_operation_id: str,
        quantity: int,
        occurred_at: datetime,
    ) -> None:
        """Project one settled spring exploration into its scheduled round."""

        if quantity <= 0 or not source_operation_id:
            return
        source_time = occurred_at.astimezone(timezone.utc)
        start = scheduled_start(source_time)
        if start is None:
            return
        self._event_insert_round(connection, round_id_for(start), start)
        event = connection.execute(
            "SELECT * FROM world_event_rounds WHERE event_key = ? AND round_id = ?",
            (EVENT_KEY, round_id_for(start)),
        ).fetchone()
        if event is None:
            return
        event_start = datetime.fromisoformat(str(event["starts_at"]))
        event_end = datetime.fromisoformat(str(event["ends_at"]))
        if source_time < event_start or source_time >= event_end:
            return
        current = connection.execute(
            "SELECT contribution FROM world_event_contributions WHERE round_id = ? AND player_id = ?",
            (event["round_id"], player_id),
        ).fetchone()
        current_value = int(current["contribution"]) if current else 0
        applied = max(0, min(int(quantity), PERSONAL_CONTRIBUTION_CAP - current_value))
        connection.execute(
            """
            INSERT OR IGNORE INTO world_event_contribution_events(
                round_id, player_id, source_operation_id, quantity, applied_quantity, occurred_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                event["round_id"],
                player_id,
                source_operation_id,
                quantity,
                applied,
                serialize_datetime(source_time),
            ),
        )
        if connection.execute("SELECT changes()").fetchone()[0] != 1 or applied <= 0:
            return
        connection.execute(
            """
            INSERT INTO world_event_contributions(round_id, player_id, contribution, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(round_id, player_id) DO UPDATE SET
                contribution = MIN(world_event_contributions.contribution + excluded.contribution, ?),
                updated_at = excluded.updated_at
            """,
            (event["round_id"], player_id, applied, serialize_datetime(source_time), PERSONAL_CONTRIBUTION_CAP),
        )
        total_row = connection.execute(
            "SELECT COALESCE(SUM(contribution), 0) AS total FROM world_event_contributions WHERE round_id = ?",
            (event["round_id"],),
        ).fetchone()
        total = int(total_row["total"] if total_row else 0)
        result = self._json_object(event["result_json"], {})
        if str(event["status"]) in {"settled", "failed"}:
            result["success"] = total >= int(event["target_quantity"])
        connection.execute(
            """
            UPDATE world_event_rounds
            SET status = CASE WHEN status = 'open' THEN 'running' ELSE status END,
                total_contribution = ?, result_json = ?, updated_at = ?
            WHERE round_id = ?
            """,
            (
                total,
                json.dumps(result, ensure_ascii=False, sort_keys=True),
                serialize_datetime(source_time),
                event["round_id"],
            ),
        )


__all__ = ["EventsRepositoryMixin"]
