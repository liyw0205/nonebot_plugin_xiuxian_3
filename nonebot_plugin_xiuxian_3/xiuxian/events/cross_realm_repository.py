"""Audited contribution projections for the v0.3 public cross-realm events."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any

from ...contracts import serialize_datetime
from ..persistence.errors import (
    EventContributionInsufficientError,
    EventNotActiveError,
    EventRewardAlreadyClaimedError,
    EventRewardExpiredError,
    EventSourceNotEligibleError,
    OperationConflictError,
)
from .cross_realm_models import CrossRealmEventRecord
from .cross_realm_rules import (
    BEAST_TRADE_EVENT_KEY,
    BOUNDARY_RIFT_EVENT_KEY,
    CONTENT_VERSION,
    EVENT_DEFINITIONS,
    RULE_VERSION,
    beast_trade_window,
    boundary_rift_window,
)


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
            source = self._cross_event_find_source(
                connection,
                event_key,
                int(player["id"]),
                action_key,
                source_operation_id,
                str(event["round_id"]),
                str(event["starts_at"]),
                str(event["ends_at"]),
            )
            source_id = str(source["source_operation_id"])
            if connection.execute(
                "SELECT 1 FROM world_event_contribution_events WHERE round_id=? AND player_id=? AND source_operation_id=?",
                (event["round_id"], player["id"], source_id),
            ).fetchone() is not None:
                raise EventSourceNotEligibleError("source operation already contributed")
            if source.get("consume_item"):
                inventory = self._json_object(player["inventory_json"], {})
                item_key = str(source["consume_item"])
                if int(inventory.get(item_key, 0)) < 1:
                    raise EventSourceNotEligibleError("required event item is missing")
                inventory[item_key] = int(inventory[item_key]) - 1
                if inventory[item_key] <= 0:
                    inventory.pop(item_key, None)
                connection.execute(
                    "UPDATE players SET inventory_json=?, updated_at=? WHERE id=?",
                    (json.dumps(inventory, ensure_ascii=False, sort_keys=True), now_text, player["id"]),
                )
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
            result.update({"content_version": CONTENT_VERSION, "success": total >= int(event["target_quantity"])})
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
            definition = EVENT_DEFINITIONS[event_key]
            if contribution < int(definition["threshold"]):
                raise EventContributionInsufficientError("cross-realm event contribution is insufficient")
            if connection.execute(
                "SELECT 1 FROM world_event_claims WHERE round_id=? AND player_id=?", (round_id, player["id"])
            ).fetchone() is not None:
                raise EventRewardAlreadyClaimedError("cross-realm event reward already claimed")
            reward = {str(key): int(value) for key, value in dict(definition["reward"]).items()}
            inventory = self._json_object(player["inventory_json"], {})
            faction = self._json_object(player["faction_reputation_json"], {})
            for key, value in reward.items():
                if key.startswith("item."):
                    inventory[key] = int(inventory.get(key, 0)) + value
                elif key.startswith("faction_reputation."):
                    faction_key = key.removeprefix("faction_reputation.")
                    faction[faction_key] = int(faction.get(faction_key, 0)) + value
            connection.execute(
                "UPDATE players SET inventory_json=?, faction_reputation_json=?, world_merit=world_merit+?, updated_at=? WHERE id=?",
                (
                    json.dumps(inventory, ensure_ascii=False, sort_keys=True),
                    json.dumps(faction, ensure_ascii=False, sort_keys=True),
                    int(reward.get("world_merit", 0)),
                    now_text,
                    player["id"],
                ),
            )
            connection.execute(
                "INSERT INTO world_event_claims(round_id, player_id, operation_id, reward_json, claimed_at) VALUES (?, ?, ?, ?, ?)",
                (round_id, player["id"], operation_id, json.dumps(reward, ensure_ascii=False, sort_keys=True), now_text),
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
        round_id: str,
        starts_at: str,
        ends_at: str,
    ) -> dict[str, object]:
        if event_key == BEAST_TRADE_EVENT_KEY:
            if action_key in {"trade", "贸易", "跨界贸易"}:
                query = "SELECT operation_id FROM cross_realm_trades WHERE player_id=? AND status='completed' AND trade_key IN ('trade.xuantian_to_demon','trade.xuantian_to_beast','trade.three_realms') AND updated_at>=? AND updated_at<?"
                params: list[object] = [player_id, starts_at, ends_at]
                if source_operation_id:
                    query += " AND operation_id=?"
                    params.append(source_operation_id)
                else:
                    query += " AND NOT EXISTS (SELECT 1 FROM world_event_contribution_events used WHERE used.round_id=? AND used.player_id=? AND used.source_operation_id=cross_realm_trades.operation_id)"
                    params.extend([round_id, player_id])
                query += " ORDER BY id DESC LIMIT 1"
                row = connection.execute(query, tuple(params)).fetchone()
                if row is not None:
                    return {"source_operation_id": str(row["operation_id"]), "quantity": 10}
            if action_key in {"blood", "妖血", "提交妖血"}:
                source_id = source_operation_id or f"{BEAST_TRADE_EVENT_KEY}:blood:{player_id}:{round_id}:{self._now().timestamp()}"
                return {"source_operation_id": source_id, "quantity": 5, "consume_item": "item.beast_blood"}
        if event_key == BOUNDARY_RIFT_EVENT_KEY:
            query = "SELECT party_battle_sessions.start_operation_id FROM party_battle_sessions JOIN parties ON parties.party_id=party_battle_sessions.party_id WHERE parties.party_type IN ('boundary_realm','party_boundary') AND party_battle_sessions.location_key=? AND party_battle_sessions.status='settled' AND party_battle_sessions.updated_at>=? AND party_battle_sessions.updated_at<? AND EXISTS (SELECT 1 FROM party_battle_members member WHERE member.battle_id=party_battle_sessions.battle_id AND member.player_id=?)"
            params = [EVENT_DEFINITIONS[event_key]["location_key"], starts_at, ends_at, player_id]
            if source_operation_id:
                query += " AND party_battle_sessions.start_operation_id=?"
                params.append(source_operation_id)
            else:
                query += " AND NOT EXISTS (SELECT 1 FROM world_event_contribution_events used WHERE used.round_id=? AND used.player_id=? AND used.source_operation_id=party_battle_sessions.start_operation_id)"
                params.extend([round_id, player_id])
            query += " AND json_extract(party_battle_sessions.result_json, '$.outcome')='won' ORDER BY party_battle_sessions.id DESC LIMIT 1"
            row = connection.execute(query, tuple(params)).fetchone()
            if row is not None:
                quantity = 30 if action_key == "boss" else 20 if action_key == "route" else 50
                return {"source_operation_id": str(row["start_operation_id"]), "quantity": quantity}
        raise EventSourceNotEligibleError("no eligible settled source operation")

    def _cross_event_select_round(self, connection: Any, event_key: str, round_id: str | None, now: datetime) -> Any:
        if event_key not in EVENT_DEFINITIONS:
            raise EventNotActiveError("unsupported cross-realm event")
        if round_id:
            return connection.execute(
                "SELECT * FROM world_event_rounds WHERE event_key=? AND round_id=?", (event_key, round_id)
            ).fetchone()
        window = beast_trade_window(now) if event_key == BEAST_TRADE_EVENT_KEY else boundary_rift_window(now)
        current_id, starts_at, ends_at, claim_expires_at = window
        definition = EVENT_DEFINITIONS[event_key]
        now_text = serialize_datetime(now)
        connection.execute(
            "INSERT OR IGNORE INTO world_event_rounds(round_id,event_key,location_key,status,starts_at,ends_at,claim_expires_at,target_quantity,total_contribution,result_json,rule_version,created_at,updated_at) VALUES (?, ?, ?, 'open', ?, ?, ?, ?, 0, ?, ?, ?, ?)",
            (
                current_id,
                event_key,
                definition["location_key"],
                serialize_datetime(starts_at),
                serialize_datetime(ends_at),
                serialize_datetime(claim_expires_at),
                int(definition["target"]),
                json.dumps({"content_version": CONTENT_VERSION, "success": False}, ensure_ascii=False, sort_keys=True),
                RULE_VERSION,
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
            result.update({"content_version": CONTENT_VERSION, "success": total >= int(event["target_quantity"]), "settled_at": serialize_datetime(now)})
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
