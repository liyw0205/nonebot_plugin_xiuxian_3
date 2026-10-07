"""SQLite transactions for world events."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any

from ...contracts import serialize_datetime
from ..content import bundled_content
from ..persistence.errors import (
    EventContributionInsufficientError,
    EventNotActiveError,
    EventRewardAlreadyClaimedError,
    EventRewardExpiredError,
    OperationConflictError,
    OperationResultMalformedError,
)
from ..utils.operations import operation_replay, record_operation
from .models import SpiritSpringEventRecord
from .reward_settlement import grant_public_event_reward
from .spirit_spring_rules import (
    SPIRIT_SPRING_EVENT_KEY,
    SpiritSpringDefinition,
    spirit_spring_definition,
    spirit_spring_result,
    spirit_spring_window,
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
            player = self._require_player(connection, platform, platform_user_id)
            existing = connection.execute(
                "SELECT 1 FROM operations WHERE operation_id = ?", (operation_id,)
            ).fetchone()
            if existing is not None:
                replay = operation_replay(
                    connection,
                    operation_id,
                    operation_name,
                    request_hash,
                    player_id=int(player["id"]),
                )
                if replay is None:
                    raise OperationConflictError("operation result is unavailable")
                return self._event_record_from_payload(replay, replay=True)
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
            result, definition = spirit_spring_result(str(event["result_json"]))
            total = int(
                connection.execute(
                    "SELECT COALESCE(SUM(contribution), 0) AS total FROM world_event_contributions WHERE round_id = ?",
                    (event["round_id"],),
                ).fetchone()["total"]
            )
            self._validate_event_snapshot(event, result, definition, total_contribution=total)
            if int(event["total_contribution"]) != total:
                raise ValueError("spirit spring total contribution differs from ledger")
            if contribution < definition.minimum_contribution:
                raise EventContributionInsufficientError("event contribution is insufficient")
            claimed = connection.execute(
                "SELECT 1 FROM world_event_claims WHERE round_id = ? AND player_id = ?",
                (event["round_id"], player["id"]),
            ).fetchone()
            if claimed is not None:
                raise EventRewardAlreadyClaimedError("event reward has already been claimed")

            success = result["success"]
            reward_grant, reward_snapshot = self._event_reward_grant(event, success=success)
            reward = grant_public_event_reward(
                connection,
                player,
                round_id=str(event["round_id"]),
                operation_id=operation_id,
                claimed_at=now_text,
                grant=reward_grant,
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
                    json.dumps(
                        {
                            "round_id": event["round_id"],
                            "reward": reward,
                            "reward_snapshot": reward_snapshot,
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                ),
            )
            updated_player = connection.execute("SELECT * FROM players WHERE id = ?", (player["id"],)).fetchone()
            payload = self._event_payload(
                connection,
                updated_player,
                event,
                contribution,
                reward,
                reward_snapshot,
            )
            record_operation(
                connection,
                operation_id,
                operation_name,
                int(player["id"]),
                request_hash,
                payload,
                now_text,
            )
            return self._event_record_from_payload(payload)

    def _event_reward_grant(self, event: Any, *, success: bool):
        _, definition = spirit_spring_result(str(event["result_json"]))
        grants = [definition.base_reward]
        completion = definition.completion_reward if success else None
        if completion is not None:
            grants.append(completion)
        from ..rewards.rules import combine_reward_grants

        final_grant = combine_reward_grants(*grants)
        return final_grant, {
            "base": definition.base_reward.snapshot(),
            "completion": completion.snapshot() if completion else None,
            "final": final_grant.snapshot(),
        }

    def _event_select_round(
        self,
        connection: Any,
        round_id: str | None,
        now: datetime,
    ) -> Any:
        if round_id:
            return connection.execute(
                "SELECT * FROM world_event_rounds WHERE event_key = ? AND round_id = ?",
                (SPIRIT_SPRING_EVENT_KEY, round_id),
            ).fetchone()
        content = self.content or bundled_content()
        raw_event = content.get("event", SPIRIT_SPRING_EVENT_KEY, include_locked=True)
        if raw_event is not None and raw_event.get("status") in {"open", "active"}:
            definition = spirit_spring_definition(content)
            window = spirit_spring_window(definition, now)
        else:
            window = None
        if window is not None:
            self._event_insert_round(connection, definition, window)
            row = connection.execute(
                "SELECT * FROM world_event_rounds WHERE event_key = ? AND round_id = ?",
                (SPIRIT_SPRING_EVENT_KEY, window[0]),
            ).fetchone()
            if row is not None:
                return row
        return connection.execute(
            """
            SELECT * FROM world_event_rounds
            WHERE event_key = ? AND claim_expires_at > ?
            ORDER BY starts_at DESC LIMIT 1
            """,
            (SPIRIT_SPRING_EVENT_KEY, serialize_datetime(now)),
        ).fetchone()

    @staticmethod
    def _event_insert_round(
        connection: Any,
        definition: SpiritSpringDefinition,
        window: tuple[str, datetime, datetime, datetime],
    ) -> None:
        round_id, starts_at, ends_at, claim_expires_at = window
        connection.execute(
            """
            INSERT OR IGNORE INTO world_event_rounds(
                round_id, event_key, location_key, status, starts_at, ends_at,
                claim_expires_at, target_quantity, total_contribution, result_json,
                created_at, updated_at
            ) VALUES (?, ?, ?, 'open', ?, ?, ?, ?, 0, ?, ?, ?)
            """,
            (
                round_id,
                SPIRIT_SPRING_EVENT_KEY,
                definition.location_key,
                serialize_datetime(starts_at),
                serialize_datetime(ends_at),
                serialize_datetime(claim_expires_at),
                definition.target_quantity,
                json.dumps(
                    {"success": False, "configuration": definition.snapshot()},
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                serialize_datetime(starts_at),
                serialize_datetime(starts_at),
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
            result, definition = spirit_spring_result(str(event["result_json"]))
            self._validate_event_snapshot(event, result, definition)
            total = int(total_row["total"] if total_row else 0)
            success = total >= definition.target_quantity
            result = dict(result)
            result.update({"success": success, "settled_at": serialize_datetime(now)})
            connection.execute(
                """
                UPDATE world_event_rounds
                SET status = 'settled', total_contribution = ?, result_json = ?, updated_at = ?
                WHERE round_id = ? AND status IN ('open', 'running')
                """,
                (
                    total,
                    json.dumps(result, ensure_ascii=False, sort_keys=True),
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
        result, definition = spirit_spring_result(str(event["result_json"]))
        total = int(
            connection.execute(
                "SELECT COALESCE(SUM(contribution), 0) AS total FROM world_event_contributions WHERE round_id = ?",
                (event["round_id"],),
            ).fetchone()["total"]
        )
        self._validate_event_snapshot(event, result, definition, total_contribution=total)
        if int(event["total_contribution"]) != total:
            raise ValueError("spirit spring total contribution differs from ledger")
        return SpiritSpringEventRecord(
            player=self._row_to_player(player),
            round_id=str(event["round_id"]),
            event_key=str(event["event_key"]),
            status=str(event["status"]),
            starts_at=str(event["starts_at"]),
            ends_at=str(event["ends_at"]),
            claim_expires_at=str(event["claim_expires_at"]),
            target_quantity=definition.target_quantity,
            minimum_contribution=definition.minimum_contribution,
            contribution_cap=definition.contribution_cap,
            source_item_key=definition.source_item_key,
            source_item_name=definition.source_item_name,
            event_name=definition.name,
            event_description=definition.description,
            total_contribution=int(event["total_contribution"]),
            player_contribution=contribution,
            success=result.get("success") if "success" in result else None,
            reward={},
            reward_snapshot={},
        )

    def _event_payload(
        self,
        connection: Any,
        player: Any,
        event: Any,
        contribution: int,
        reward: dict[str, int],
        reward_snapshot: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        result, definition = spirit_spring_result(str(event["result_json"]))
        self._validate_event_snapshot(event, result, definition)
        return {
            "player": self._player_payload(self._row_to_player(player)),
            "round_id": str(event["round_id"]),
            "event_key": str(event["event_key"]),
            "status": str(event["status"]),
            "starts_at": str(event["starts_at"]),
            "ends_at": str(event["ends_at"]),
            "claim_expires_at": str(event["claim_expires_at"]),
            "target_quantity": definition.target_quantity,
            "minimum_contribution": definition.minimum_contribution,
            "contribution_cap": definition.contribution_cap,
            "source_item_key": definition.source_item_key,
            "source_item_name": definition.source_item_name,
            "event_name": definition.name,
            "event_description": definition.description,
            "total_contribution": int(event["total_contribution"]),
            "player_contribution": contribution,
            "success": result.get("success"),
            "reward": reward,
            "reward_snapshot": reward_snapshot or {},
        }

    @staticmethod
    def _event_record_from_payload(payload: dict[str, Any], replay: bool = False) -> SpiritSpringEventRecord:
        from ..persistence.sqlite_repository import SQLitePlayerRepository

        EventsRepositoryMixin._validate_event_payload(payload)

        return SpiritSpringEventRecord(
            player=SQLitePlayerRepository._row_to_player(payload["player"]),
            round_id=str(payload["round_id"]),
            event_key=str(payload["event_key"]),
            status=str(payload["status"]),
            starts_at=str(payload["starts_at"]),
            ends_at=str(payload["ends_at"]),
            claim_expires_at=str(payload["claim_expires_at"]),
            target_quantity=int(payload["target_quantity"]),
            minimum_contribution=int(payload["minimum_contribution"]),
            contribution_cap=int(payload["contribution_cap"]),
            source_item_key=str(payload["source_item_key"]),
            source_item_name=str(payload["source_item_name"]),
            event_name=str(payload["event_name"]),
            event_description=str(payload["event_description"]),
            total_contribution=int(payload["total_contribution"]),
            player_contribution=int(payload.get("player_contribution", 0)),
            success=payload.get("success"),
            reward={str(key): int(value) for key, value in dict(payload.get("reward", {})).items()},
            reward_snapshot=dict(payload.get("reward_snapshot", {})),
            already_completed=replay,
        )

    @staticmethod
    def _validate_event_payload(payload: dict[str, Any]) -> None:
        expected = {
            "player", "round_id", "event_key", "status", "starts_at", "ends_at", "claim_expires_at",
            "target_quantity", "minimum_contribution", "contribution_cap", "source_item_key",
            "source_item_name", "event_name", "event_description", "total_contribution",
            "player_contribution", "success", "reward", "reward_snapshot",
        }
        if not isinstance(payload, dict) or set(payload) != expected:
            raise OperationResultMalformedError("spirit spring operation result has invalid fields")
        if not isinstance(payload["player"], dict):
            raise OperationResultMalformedError("spirit spring operation player snapshot is invalid")
        if payload["event_key"] != SPIRIT_SPRING_EVENT_KEY:
            raise OperationResultMalformedError("spirit spring operation event key is invalid")
        for field in (
            "round_id", "status", "starts_at", "ends_at", "claim_expires_at", "source_item_key",
            "source_item_name", "event_name", "event_description",
        ):
            if not isinstance(payload[field], str) or not payload[field].strip():
                raise OperationResultMalformedError(f"spirit spring operation {field} is invalid")
        for field in ("target_quantity", "minimum_contribution", "contribution_cap"):
            if isinstance(payload[field], bool) or not isinstance(payload[field], int) or payload[field] <= 0:
                raise OperationResultMalformedError(f"spirit spring operation {field} is invalid")
        for field in ("total_contribution", "player_contribution"):
            if isinstance(payload[field], bool) or not isinstance(payload[field], int) or payload[field] < 0:
                raise OperationResultMalformedError(f"spirit spring operation {field} is invalid")
        if not isinstance(payload["success"], bool):
            raise OperationResultMalformedError("spirit spring operation success is invalid")
        reward = payload["reward"]
        if not isinstance(reward, dict) or any(
            not isinstance(key, str) or not key or isinstance(value, bool) or not isinstance(value, int) or value <= 0
            for key, value in reward.items()
        ):
            raise OperationResultMalformedError("spirit spring operation reward is invalid")
        reward_snapshot = payload["reward_snapshot"]
        if not isinstance(reward_snapshot, dict) or set(reward_snapshot) != {"base", "completion", "final"}:
            raise OperationResultMalformedError("spirit spring operation reward snapshot is invalid")
        from ..rewards.rules import (
            RewardContentError,
            combine_reward_grants,
            reward_grant_from_snapshot,
            reward_totals,
        )

        try:
            base = reward_grant_from_snapshot(reward_snapshot["base"], operation="event.claim_reward")
            completion_value = reward_snapshot["completion"]
            completion = (
                reward_grant_from_snapshot(completion_value, operation="event.claim_reward")
                if completion_value is not None else None
            )
            final = reward_grant_from_snapshot(reward_snapshot["final"], operation="event.claim_reward")
            expected_final = combine_reward_grants(base, completion) if completion is not None else base
        except (RewardContentError, TypeError, ValueError, KeyError) as exc:
            raise OperationResultMalformedError("spirit spring operation reward snapshot is malformed") from exc
        if final.snapshot() != expected_final.snapshot() or reward_totals(final) != reward:
            raise OperationResultMalformedError("spirit spring operation reward does not match snapshot")
        if payload["success"] is not (completion is not None):
            raise OperationResultMalformedError("spirit spring operation completion reward is inconsistent")

    @staticmethod
    def _validate_event_snapshot(
        event: Any,
        result: dict[str, Any],
        definition: SpiritSpringDefinition,
        *,
        total_contribution: int | None = None,
    ) -> None:
        if str(event["event_key"]) != SPIRIT_SPRING_EVENT_KEY:
            raise ValueError("spirit spring event key is invalid")
        if str(event["location_key"]) != definition.location_key:
            raise ValueError("spirit spring location snapshot differs from round")
        if int(event["target_quantity"]) != definition.target_quantity:
            raise ValueError("spirit spring target snapshot differs from round")
        if str(event["status"]) in {"settled", "failed"}:
            if "settled_at" not in result:
                raise ValueError("spirit spring settled result is missing settled time")
            expected_total = int(event["total_contribution"]) if total_contribution is None else total_contribution
            expected_success = expected_total >= definition.target_quantity
            if result["success"] is not expected_success:
                raise ValueError("spirit spring success does not match contribution total")

__all__ = ["EventsRepositoryMixin"]
