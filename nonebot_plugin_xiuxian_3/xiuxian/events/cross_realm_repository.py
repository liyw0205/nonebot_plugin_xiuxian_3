"""Audited contribution projections for the public cross-realm events."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any

from ...contracts import serialize_datetime
from ..adventures.rules import meets_realm
from ..utils.assets import spend_player_items
from ..persistence.errors import (
    EventContributionInsufficientError,
    EventNotActiveError,
    EventRewardAlreadyClaimedError,
    EventRewardExpiredError,
    EventSourceNotEligibleError,
    OperationConflictError,
)
from .cross_realm_models import CrossRealmEventRecord
from .public_event_rules import (
    PublicEventDefinition,
    public_event_definition,
    public_event_snapshot,
    public_event_window,
)
from .reward_settlement import grant_public_event_reward


class CrossRealmEventRepositoryMixin:
    """Keep event source projection and reward settlement in one transaction."""

    async def get_cross_realm_event(
        self,
        *,
        event_key: str,
        platform: str,
        platform_user_id: str,
        round_id: str | None = None,
    ) -> CrossRealmEventRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._get_cross_realm_event_once,
                event_key,
                platform,
                platform_user_id,
                round_id,
            )

    async def record_cross_realm_contribution(
        self,
        *,
        event_key: str,
        platform: str,
        platform_user_id: str,
        action_key: str,
        source_operation_id: str | None,
        operation_id: str,
    ) -> CrossRealmEventRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._record_cross_realm_contribution_once,
                event_key,
                platform,
                platform_user_id,
                action_key,
                source_operation_id,
                operation_id,
            )

    async def claim_cross_realm_event(
        self,
        *,
        event_key: str,
        platform: str,
        platform_user_id: str,
        round_id: str,
        operation_id: str,
    ) -> CrossRealmEventRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._claim_cross_realm_event_once,
                event_key,
                platform,
                platform_user_id,
                round_id,
                operation_id,
            )

    def _get_cross_realm_event_once(
        self, event_key: str, platform: str, platform_user_id: str, round_id: str | None
    ) -> CrossRealmEventRecord:
        now = self._now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            player = self._require_player(connection, platform, platform_user_id, writable=False)
            event = self._cross_event_select_round(connection, event_key, round_id, now)
            if event is None:
                raise EventNotActiveError("no cross-realm event is available")
            event = self._cross_event_refresh_round(connection, event, now)
            return self._cross_event_record(connection, player["id"], event)

    def _record_cross_realm_contribution_once(
        self,
        event_key: str,
        platform: str,
        platform_user_id: str,
        action_key: str,
        source_operation_id: str | None,
        operation_id: str,
    ) -> CrossRealmEventRecord:
        operation_name = f"{event_key}.contribute"
        request_hash = self._request_hash(
            operation_name,
            {
                "event_key": event_key,
                "platform": platform,
                "platform_user_id": platform_user_id,
                "action_key": action_key,
                "source_operation_id": source_operation_id or "",
            },
        )
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._cross_event_operation_replay(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                return self._cross_event_record_from_payload(replay, replay=True)
            player = self._require_player(connection, platform, platform_user_id)
            event = self._cross_event_select_round(connection, event_key, None, now)
            if event is None:
                raise EventNotActiveError("no cross-realm event is available")
            event = self._cross_event_refresh_round(connection, event, now)
            if str(event["status"]) not in {"open", "running"} or now >= datetime.fromisoformat(str(event["ends_at"])):
                raise EventNotActiveError("cross-realm event is not open")
            definition = public_event_snapshot(str(event["event_key"]), str(event["result_json"]))
            if definition.required_realm_key is not None and not meets_realm(
                str(player["realm_key"]),
                int(player["realm_layer"]),
                definition.required_realm_key,
                definition.required_realm_layer,
                self.content,
            ):
                raise EventSourceNotEligibleError("event realm requirement is not met")
            source = self._cross_event_find_source(
                connection,
                event_key,
                int(player["id"]),
                action_key,
                source_operation_id,
                operation_id,
                str(event["round_id"]),
                str(event["starts_at"]),
                str(event["ends_at"]),
                definition,
            )
            source_id = str(source["source_operation_id"])
            if connection.execute(
                "SELECT 1 FROM world_event_contribution_events WHERE round_id=? AND player_id=? AND source_operation_id=?",
                (event["round_id"], player["id"], source_id),
            ).fetchone() is not None:
                raise EventSourceNotEligibleError("source operation already contributed")
            if source.get("consume_item"):
                item_key = str(source["consume_item"])
                try:
                    spend_player_items(
                        connection,
                        player,
                        {item_key: int(source["consume_quantity"])},
                        now_text,
                    )
                except ValueError as exc:
                    raise EventSourceNotEligibleError("required event item is missing") from exc
            quantity = int(source["quantity"])
            connection.execute(
                "INSERT INTO world_event_contribution_events(round_id, player_id, source_operation_id, quantity, applied_quantity, occurred_at) VALUES (?, ?, ?, ?, ?, ?)",
                (event["round_id"], player["id"], source_id, quantity, quantity, now_text),
            )
            connection.execute(
                "INSERT OR IGNORE INTO activity_events(player_id, event_key, source_operation_id, occurred_at, payload_json) VALUES (?, ?, ?, ?, ?)",
                (
                    player["id"],
                    event_key,
                    source_id,
                    now_text,
                    json.dumps({"round_id": event["round_id"], "action_key": action_key, "quantity": quantity}, ensure_ascii=False, sort_keys=True),
                ),
            )
            current = connection.execute(
                "SELECT contribution FROM world_event_contributions WHERE round_id=? AND player_id=?",
                (event["round_id"], player["id"]),
            ).fetchone()
            current_value = int(current["contribution"]) if current else 0
            connection.execute(
                "INSERT INTO world_event_contributions(round_id, player_id, contribution, updated_at) VALUES (?, ?, ?, ?) ON CONFLICT(round_id, player_id) DO UPDATE SET contribution=world_event_contributions.contribution + excluded.contribution, updated_at=excluded.updated_at",
                (event["round_id"], player["id"], quantity, now_text),
            )
            total = int(
                connection.execute(
                    "SELECT COALESCE(SUM(contribution), 0) AS total FROM world_event_contributions WHERE round_id=?",
                    (event["round_id"],),
                ).fetchone()["total"]
            )
            result = self._json_object(event["result_json"], {})
            result.update({"success": total >= int(event["target_quantity"])})
            connection.execute(
                "UPDATE world_event_rounds SET status='running', total_contribution=?, result_json=?, updated_at=? WHERE round_id=? AND status IN ('open','running')",
                (total, json.dumps(result, ensure_ascii=False, sort_keys=True), now_text, event["round_id"]),
            )
            event = connection.execute("SELECT * FROM world_event_rounds WHERE round_id=?", (event["round_id"],)).fetchone()
            payload = self._cross_event_payload(connection, int(player["id"]), event, current_value + quantity)
            payload.update({"action_key": action_key, "source_operation_id": source_id})
            self._cross_event_insert_operation(connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text)
            return self._cross_event_record_from_payload(payload)

    def _claim_cross_realm_event_once(
        self, event_key: str, platform: str, platform_user_id: str, round_id: str, operation_id: str
    ) -> CrossRealmEventRecord:
        operation_name = f"{event_key}.claim_reward"
        request_hash = self._request_hash(
            operation_name,
            {"event_key": event_key, "platform": platform, "platform_user_id": platform_user_id, "round_id": round_id},
        )
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._cross_event_operation_replay(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                return self._cross_event_record_from_payload(replay, replay=True)
            player = self._require_player(connection, platform, platform_user_id)
            event = self._cross_event_select_round(connection, event_key, round_id, now)
            if event is None:
                raise EventNotActiveError("cross-realm event round does not exist")
            event = self._cross_event_refresh_round(connection, event, now)
            if str(event["status"]) not in {"settled", "failed"}:
                raise EventNotActiveError("cross-realm event is not settled")
            if now >= datetime.fromisoformat(str(event["claim_expires_at"])):
                raise EventRewardExpiredError("cross-realm event reward window has closed")
            contribution_row = connection.execute(
                "SELECT contribution FROM world_event_contributions WHERE round_id=? AND player_id=?",
                (round_id, player["id"]),
            ).fetchone()
            contribution = int(contribution_row["contribution"]) if contribution_row else 0
            definition = public_event_snapshot(str(event["event_key"]), str(event["result_json"]))
            if contribution < definition.minimum_contribution:
                raise EventContributionInsufficientError("cross-realm event contribution is insufficient")
            if connection.execute(
                "SELECT 1 FROM world_event_claims WHERE round_id=? AND player_id=?", (round_id, player["id"])
            ).fetchone() is not None:
                raise EventRewardAlreadyClaimedError("cross-realm event reward already claimed")
            reward = grant_public_event_reward(
                connection,
                player,
                round_id=round_id,
                operation_id=operation_id,
                claimed_at=now_text,
                grant=definition.reward,
            )
            updated_event = connection.execute("SELECT * FROM world_event_rounds WHERE round_id=?", (round_id,)).fetchone()
            payload = self._cross_event_payload(connection, int(player["id"]), updated_event, contribution)
            payload["reward"] = reward
            self._cross_event_insert_operation(connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text)
            return self._cross_event_record_from_payload(payload)

    def _cross_event_find_source(
        self,
        connection: Any,
        event_key: str,
        player_id: int,
        action_key: str,
        source_operation_id: str | None,
        operation_id: str,
        round_id: str,
        starts_at: str,
        ends_at: str,
        definition: PublicEventDefinition,
    ) -> dict[str, object]:
        contribution = definition.contributions.get(action_key)
        if contribution is None:
            raise EventSourceNotEligibleError("unsupported cross-realm event contribution")
        source = str(contribution["source"])
        if source == "completed_cross_realm_trade":
            trade_keys = tuple(str(key) for key in contribution["trade_keys"])
            placeholders = ",".join("?" for _ in trade_keys)
            query = (
                "SELECT operation_id FROM cross_realm_trades WHERE player_id=? "
                f"AND status='completed' AND trade_key IN ({placeholders}) "
                "AND updated_at>=? AND updated_at<?"
            )
            params: list[object] = [player_id, *trade_keys, starts_at, ends_at]
            if source_operation_id:
                query += " AND operation_id=?"
                params.append(source_operation_id)
            else:
                query += " AND NOT EXISTS (SELECT 1 FROM world_event_contribution_events used WHERE used.round_id=? AND used.player_id=? AND used.source_operation_id=cross_realm_trades.operation_id)"
                params.extend([round_id, player_id])
            query += " ORDER BY id DESC LIMIT 1"
            row = connection.execute(query, tuple(params)).fetchone()
            if row is not None:
                return {"source_operation_id": str(row["operation_id"]), "quantity": int(contribution["quantity"])}
        elif source == "consume_item":
            source_id = source_operation_id or operation_id
            return {
                "source_operation_id": source_id,
                "quantity": int(contribution["quantity"]),
                "consume_item": str(contribution["item_key"]),
                "consume_quantity": int(contribution["item_quantity"]),
            }
        elif source == "settled_boundary_party_battle":
            party_types = tuple(str(key) for key in contribution["party_types"])
            placeholders = ",".join("?" for _ in party_types)
            query = (
                "SELECT party_battle_sessions.start_operation_id FROM party_battle_sessions "
                "JOIN parties ON parties.party_id=party_battle_sessions.party_id "
                f"WHERE parties.party_type IN ({placeholders}) "
                "AND party_battle_sessions.location_key=? AND party_battle_sessions.status='settled' "
                "AND party_battle_sessions.updated_at>=? AND party_battle_sessions.updated_at<? "
                "AND EXISTS (SELECT 1 FROM party_battle_members member "
                "WHERE member.battle_id=party_battle_sessions.battle_id AND member.player_id=?)"
            )
            params: list[object] = [*party_types, definition.location_key, starts_at, ends_at, player_id]
            if source_operation_id:
                query += " AND party_battle_sessions.start_operation_id=?"
                params.append(source_operation_id)
            else:
                query += " AND NOT EXISTS (SELECT 1 FROM world_event_contribution_events used WHERE used.round_id=? AND used.player_id=? AND used.source_operation_id=party_battle_sessions.start_operation_id)"
                params.extend([round_id, player_id])
            query += " AND json_extract(party_battle_sessions.result_json, '$.outcome')='won' ORDER BY party_battle_sessions.id DESC LIMIT 1"
            row = connection.execute(query, tuple(params)).fetchone()
            if row is not None:
                return {"source_operation_id": str(row["start_operation_id"]), "quantity": int(contribution["quantity"])}
        elif source == "completed_ancient_domain":
            query = (
                "SELECT operations.operation_id FROM operations "
                "JOIN ancient_domain_runs runs "
                "  ON runs.run_id=json_extract(operations.result_json, '$.run_id') "
                "JOIN ancient_domain_members members ON members.run_id=runs.run_id "
                "WHERE operations.operation_name='ancient_domain.settle' "
                "AND json_extract(operations.result_json, '$.outcome')='won' "
                "AND runs.status='settled' AND members.status='cleared' "
                "AND members.player_id=? "
                "AND operations.created_at>=? AND operations.created_at<?"
            )
            params: list[object] = [player_id, starts_at, ends_at]
            if source_operation_id:
                query += " AND operations.operation_id=?"
                params.append(source_operation_id)
            else:
                query += " AND NOT EXISTS (SELECT 1 FROM world_event_contribution_events used WHERE used.round_id=? AND used.player_id=? AND used.source_operation_id=operations.operation_id)"
                params.extend([round_id, player_id])
            query += " ORDER BY operations.created_at DESC LIMIT 1"
            row = connection.execute(query, tuple(params)).fetchone()
            if row is not None:
                return {"source_operation_id": str(row["operation_id"]), "quantity": int(contribution["quantity"])}
        raise EventSourceNotEligibleError("no eligible settled source operation")

    def _cross_event_select_round(self, connection: Any, event_key: str, round_id: str | None, now: datetime) -> Any:
        if round_id:
            return connection.execute(
                "SELECT * FROM world_event_rounds WHERE event_key=? AND round_id=?", (event_key, round_id)
            ).fetchone()
        definition = public_event_definition(event_key, self.content)
        window = public_event_window(definition, now)
        if window is None:
            return connection.execute(
                "SELECT * FROM world_event_rounds WHERE event_key=? AND claim_expires_at>? ORDER BY starts_at DESC LIMIT 1",
                (event_key, serialize_datetime(now)),
            ).fetchone()
        current_id, starts_at, ends_at, claim_expires_at = window
        now_text = serialize_datetime(now)
        connection.execute(
            "INSERT OR IGNORE INTO world_event_rounds(round_id,event_key,location_key,status,starts_at,ends_at,claim_expires_at,target_quantity,total_contribution,result_json,created_at,updated_at) VALUES (?, ?, ?, 'open', ?, ?, ?, ?, 0, ?, ?, ?)",
            (
                current_id,
                event_key,
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
                now_text,
                now_text,
            ),
        )
        return connection.execute("SELECT * FROM world_event_rounds WHERE round_id=?", (current_id,)).fetchone()

    def _cross_event_refresh_round(self, connection: Any, event: Any, now: datetime) -> Any:
        if str(event["status"]) in {"open", "running"} and now >= datetime.fromisoformat(str(event["ends_at"])):
            total = int(
                connection.execute(
                    "SELECT COALESCE(SUM(contribution),0) AS total FROM world_event_contributions WHERE round_id=?",
                    (event["round_id"],),
                ).fetchone()["total"]
            )
            result = self._json_object(event["result_json"], {})
            result.update({"success": total >= int(event["target_quantity"]), "settled_at": serialize_datetime(now)})
            connection.execute(
                "UPDATE world_event_rounds SET status='settled', total_contribution=?, result_json=?, updated_at=? WHERE round_id=? AND status IN ('open','running')",
                (total, json.dumps(result, ensure_ascii=False, sort_keys=True), serialize_datetime(now), event["round_id"]),
            )
            event = connection.execute("SELECT * FROM world_event_rounds WHERE round_id=?", (event["round_id"],)).fetchone()
        return event

    def _cross_event_record(self, connection: Any, player_id: int, event: Any) -> CrossRealmEventRecord:
        row = connection.execute(
            "SELECT contribution FROM world_event_contributions WHERE round_id=? AND player_id=?",
            (event["round_id"], player_id),
        ).fetchone()
        return self._cross_event_record_from_payload(
            self._cross_event_payload(connection, player_id, event, int(row["contribution"]) if row else 0)
        )

    def _cross_event_payload(self, connection: Any, player_id: int, event: Any, contribution: int) -> dict[str, object]:
        player = connection.execute("SELECT * FROM players WHERE id=?", (player_id,)).fetchone()
        result = self._json_object(event["result_json"], {})
        definition = public_event_snapshot(str(event["event_key"]), str(event["result_json"]))
        return {
            "player": self._player_payload(self._row_to_player(player)),
            "round_id": str(event["round_id"]),
            "event_key": str(event["event_key"]),
            "status": str(event["status"]),
            "starts_at": str(event["starts_at"]),
            "ends_at": str(event["ends_at"]),
            "claim_expires_at": str(event["claim_expires_at"]),
            "target_quantity": int(event["target_quantity"]),
            "minimum_contribution": definition.minimum_contribution,
            "total_contribution": int(event["total_contribution"]),
            "player_contribution": contribution,
            "success": result.get("success"),
            "reward": {},
        }

    @staticmethod
    def _cross_event_record_from_payload(payload: dict[str, object], replay: bool = False) -> CrossRealmEventRecord:
        return CrossRealmEventRecord(
            player=payload["player"],
            round_id=str(payload["round_id"]),
            event_key=str(payload["event_key"]),
            status=str(payload["status"]),
            starts_at=str(payload["starts_at"]),
            ends_at=str(payload["ends_at"]),
            claim_expires_at=str(payload["claim_expires_at"]),
            target_quantity=int(payload["target_quantity"]),
            minimum_contribution=int(payload["minimum_contribution"]),
            total_contribution=int(payload["total_contribution"]),
            player_contribution=int(payload["player_contribution"]),
            success=payload.get("success"),
            reward={str(key): int(value) for key, value in dict(payload.get("reward", {})).items()},
            already_completed=replay,
        )

    @staticmethod
    def _cross_event_operation_replay(connection: Any, operation_id: str, operation_name: str, request_hash: str) -> dict[str, object] | None:
        row = connection.execute("SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id=?", (operation_id,)).fetchone()
        if row is None:
            return None
        if row["operation_name"] != operation_name or row["request_hash"] != request_hash:
            raise OperationConflictError("event operation conflicts with its original input")
        return json.loads(row["result_json"])

    @staticmethod
    def _cross_event_insert_operation(connection: Any, operation_id: str, operation_name: str, player_id: int, request_hash: str, payload: dict[str, object], now_text: str) -> None:
        connection.execute(
            "INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (operation_id, operation_name, player_id, request_hash, json.dumps(payload, ensure_ascii=False, sort_keys=True), now_text),
        )


__all__ = ["CrossRealmEventRepositoryMixin"]
