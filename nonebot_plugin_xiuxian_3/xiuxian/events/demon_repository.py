"""Server-audited contribution and reward transactions for demon invasion."""

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
from .demon_models import DemonInvasionEventRecord
from .demon_rules import (
    DEMON_ACTION_CONTRIBUTION,
    DEMON_EVENT_CONTENT_VERSION,
    DEMON_EVENT_KEY,
    DEMON_EVENT_LOCATION,
    DEMON_EVENT_RULE_VERSION,
    DEMON_EVENT_TARGET,
    DEMON_PERSONAL_REWARD_THRESHOLD,
    demon_event_times,
    demon_meets_realm,
    demon_round_id_for,
    demon_scheduled_start,
)


class DemonInvasionRepositoryMixin:
    """Keep v0.3 event evidence separate from the v0.1 spring event."""

    async def get_demon_invasion_event(
        self, *, platform: str, platform_user_id: str, round_id: str | None = None
    ) -> DemonInvasionEventRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._get_demon_invasion_event_once,
                platform,
                platform_user_id,
                round_id,
            )

    async def record_demon_invasion_contribution(
        self,
        *,
        platform: str,
        platform_user_id: str,
        action_key: str,
        source_operation_id: str | None,
        operation_id: str,
    ) -> DemonInvasionEventRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._record_demon_invasion_contribution_once,
                platform,
                platform_user_id,
                action_key,
                source_operation_id,
                operation_id,
            )

    async def claim_demon_invasion_event(
        self, *, platform: str, platform_user_id: str, round_id: str | None, operation_id: str
    ) -> DemonInvasionEventRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._claim_demon_invasion_event_once,
                platform,
                platform_user_id,
                round_id,
                operation_id,
            )

    def _get_demon_invasion_event_once(
        self, platform: str, platform_user_id: str, round_id: str | None
    ) -> DemonInvasionEventRecord:
        now = self._now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            player = self._require_player(connection, platform, platform_user_id, writable=False)
            event = self._demon_select_round(connection, round_id, now)
            if event is None:
                raise EventNotActiveError("no demon invasion event is available")
            event = self._demon_refresh_round(connection, event, now)
            return self._demon_record(connection, player, event)

    def _record_demon_invasion_contribution_once(
        self,
        platform: str,
        platform_user_id: str,
        action_key: str,
        source_operation_id: str | None,
        operation_id: str,
    ) -> DemonInvasionEventRecord:
        operation_name = "event.demon_invasion.contribute"
        request_hash = self._request_hash(
            operation_name,
            {
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
            replay = self._demon_operation_replay(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                return self._demon_record_from_payload(replay, replay=True)
            player = self._require_player(connection, platform, platform_user_id)
            if not demon_meets_realm(str(player["realm_key"]), int(player["realm_layer"])):
                raise EventSourceNotEligibleError("demon invasion requires nascent soul L1")
            event = self._demon_select_round(connection, None, now)
            if event is None:
                raise EventNotActiveError("no demon invasion event is active")
            event = self._demon_refresh_round(connection, event, now)
            if str(event["status"]) not in {"open", "running"} or now >= datetime.fromisoformat(str(event["ends_at"])):
                raise EventNotActiveError("demon invasion event is not open")
            source = self._demon_find_source(
                connection,
                int(player["id"]),
                action_key,
                source_operation_id,
                str(event["round_id"]),
            )
            quantity = int(source["quantity"])
            if quantity <= 0:
                raise EventSourceNotEligibleError("source operation has no event contribution")
            source_id = str(source["source_operation_id"])
            existing_source = connection.execute(
                "SELECT 1 FROM world_event_contribution_events WHERE round_id=? AND player_id=? AND source_operation_id=?",
                (event["round_id"], player["id"], source_id),
            ).fetchone()
            if existing_source is not None:
                raise EventSourceNotEligibleError("source operation already contributed")
            current = connection.execute(
                "SELECT contribution FROM world_event_contributions WHERE round_id=? AND player_id=?",
                (event["round_id"], player["id"]),
            ).fetchone()
            current_value = int(current["contribution"]) if current else 0
            applied = quantity
            connection.execute(
                "INSERT INTO world_event_contribution_events(round_id, player_id, source_operation_id, quantity, applied_quantity, occurred_at) VALUES (?, ?, ?, ?, ?, ?)",
                (event["round_id"], player["id"], source_id, quantity, applied, now_text),
            )
            connection.execute(
                "INSERT INTO world_event_contributions(round_id, player_id, contribution, updated_at) VALUES (?, ?, ?, ?) ON CONFLICT(round_id, player_id) DO UPDATE SET contribution=world_event_contributions.contribution + excluded.contribution, updated_at=excluded.updated_at",
                (event["round_id"], player["id"], applied, now_text),
            )
            total = int(
                connection.execute(
                    "SELECT COALESCE(SUM(contribution),0) AS total FROM world_event_contributions WHERE round_id=?",
                    (event["round_id"],),
                ).fetchone()["total"]
            )
            result = self._json_object(event["result_json"], {})
            result.update({"content_version": DEMON_EVENT_CONTENT_VERSION, "success": total >= int(event["target_quantity"])})
            connection.execute(
                "UPDATE world_event_rounds SET status='running', total_contribution=?, result_json=?, updated_at=? WHERE round_id=? AND status IN ('open','running')",
                (total, json.dumps(result, ensure_ascii=False, sort_keys=True), now_text, event["round_id"]),
            )
            event = connection.execute("SELECT * FROM world_event_rounds WHERE round_id=?", (event["round_id"],)).fetchone()
            payload = self._demon_payload(connection, player["id"], event, applied + current_value)
            payload["action_key"] = action_key
            payload["source_operation_id"] = source_id
            self._demon_insert_operation(connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text)
            return self._demon_record_from_payload(payload)

    def _claim_demon_invasion_event_once(
        self, platform: str, platform_user_id: str, round_id: str | None, operation_id: str
    ) -> DemonInvasionEventRecord:
        operation_name = "event.demon_invasion.claim_reward"
        request_hash = self._request_hash(
            operation_name,
            {"platform": platform, "platform_user_id": platform_user_id, "round_id": round_id or ""},
        )
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._demon_operation_replay(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                return self._demon_record_from_payload(replay, replay=True)
            player = self._require_player(connection, platform, platform_user_id)
            event = self._demon_select_round(connection, round_id, now)
            if event is None:
                raise EventNotActiveError("no demon invasion event is available")
            event = self._demon_refresh_round(connection, event, now)
            if str(event["status"]) not in {"settled", "failed"}:
                raise EventNotActiveError("demon invasion event is not settled")
            if now >= datetime.fromisoformat(str(event["claim_expires_at"])):
                raise EventRewardExpiredError("demon invasion reward window has closed")
            contribution_row = connection.execute(
                "SELECT contribution FROM world_event_contributions WHERE round_id=? AND player_id=?",
                (event["round_id"], player["id"]),
            ).fetchone()
            contribution = int(contribution_row["contribution"]) if contribution_row else 0
            if contribution < DEMON_PERSONAL_REWARD_THRESHOLD:
                raise EventContributionInsufficientError("demon invasion contribution is insufficient")
            if connection.execute(
                "SELECT 1 FROM world_event_claims WHERE round_id=? AND player_id=?",
                (event["round_id"], player["id"]),
            ).fetchone() is not None:
                raise EventRewardAlreadyClaimedError("demon invasion reward already claimed")
            reward = {"world_merit": 50, "faction_reputation.demon": 20}
            faction = self._json_object(player["faction_reputation_json"], {})
            faction["demon"] = int(faction.get("demon", 0)) + reward["faction_reputation.demon"]
            connection.execute(
                "UPDATE players SET world_merit=world_merit+?, faction_reputation_json=?, updated_at=? WHERE id=?",
                (reward["world_merit"], json.dumps(faction, ensure_ascii=False, sort_keys=True), now_text, player["id"]),
            )
            connection.execute(
                "INSERT INTO world_event_claims(round_id, player_id, operation_id, reward_json, claimed_at) VALUES (?, ?, ?, ?, ?)",
                (event["round_id"], player["id"], operation_id, json.dumps(reward, ensure_ascii=False, sort_keys=True), now_text),
            )
            updated = connection.execute("SELECT * FROM players WHERE id=?", (player["id"],)).fetchone()
            payload = self._demon_payload(connection, updated["id"], event, contribution)
            payload["reward"] = reward
            self._demon_insert_operation(connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text)
            return self._demon_record_from_payload(payload)

    def _demon_select_round(self, connection: Any, round_id: str | None, now: datetime) -> Any:
        if round_id:
            return connection.execute(
                "SELECT * FROM world_event_rounds WHERE event_key=? AND round_id=?",
                (DEMON_EVENT_KEY, round_id),
            ).fetchone()
        start = demon_scheduled_start(now)
        if start is not None:
            current_id = demon_round_id_for(start)
            self._demon_insert_round(connection, current_id, start)
            return connection.execute("SELECT * FROM world_event_rounds WHERE event_key=? AND round_id=?", (DEMON_EVENT_KEY, current_id)).fetchone()
        return connection.execute(
            "SELECT * FROM world_event_rounds WHERE event_key=? AND claim_expires_at>? ORDER BY starts_at DESC LIMIT 1",
            (DEMON_EVENT_KEY, serialize_datetime(now)),
        ).fetchone()

    @staticmethod
    def _demon_insert_round(connection: Any, round_id: str, start: datetime) -> None:
        starts_at, ends_at, claim_expires_at = demon_event_times(start)
        connection.execute(
            "INSERT OR IGNORE INTO world_event_rounds(round_id,event_key,location_key,status,starts_at,ends_at,claim_expires_at,target_quantity,total_contribution,result_json,rule_version,created_at,updated_at) VALUES (?, ?, ?, 'open', ?, ?, ?, ?, 0, ?, ?, ?, ?)",
            (
                round_id,
                DEMON_EVENT_KEY,
                DEMON_EVENT_LOCATION,
                serialize_datetime(starts_at),
                serialize_datetime(ends_at),
                serialize_datetime(claim_expires_at),
                DEMON_EVENT_TARGET,
                json.dumps({"content_version": DEMON_EVENT_CONTENT_VERSION, "success": False}, ensure_ascii=False, sort_keys=True),
                DEMON_EVENT_RULE_VERSION,
                serialize_datetime(start),
                serialize_datetime(start),
            ),
        )

    def _demon_refresh_round(self, connection: Any, event: Any, now: datetime) -> Any:
        if str(event["status"]) in {"open", "running"} and now >= datetime.fromisoformat(str(event["ends_at"])):
            total = int(connection.execute("SELECT COALESCE(SUM(contribution),0) AS total FROM world_event_contributions WHERE round_id=?", (event["round_id"],)).fetchone()["total"])
            result = self._json_object(event["result_json"], {})
            result.update({"content_version": DEMON_EVENT_CONTENT_VERSION, "success": total >= int(event["target_quantity"]), "settled_at": serialize_datetime(now)})
            connection.execute("UPDATE world_event_rounds SET status='settled', total_contribution=?, result_json=?, updated_at=? WHERE round_id=? AND status IN ('open','running')", (total, json.dumps(result, ensure_ascii=False, sort_keys=True), serialize_datetime(now), event["round_id"]))
            event = connection.execute("SELECT * FROM world_event_rounds WHERE round_id=?", (event["round_id"],)).fetchone()
        return event

    def _demon_find_source(
        self,
        connection: Any,
        player_id: int,
        action_key: str,
        source_operation_id: str | None,
        round_id: str,
    ) -> dict[str, object]:
        if action_key == "transport":
            query = "SELECT route.operation_id FROM livelihood_trade_routes AS route WHERE route.player_id=? AND route.status='settled'"
            params: tuple[object, ...] = (player_id,)
            if source_operation_id:
                query += " AND route.operation_id=?"
                params += (source_operation_id,)
            else:
                query += " AND NOT EXISTS (SELECT 1 FROM world_event_contribution_events AS used WHERE used.round_id=? AND used.player_id=? AND used.source_operation_id=route.operation_id)"
                params += (round_id, player_id)
            query += " ORDER BY route.id DESC LIMIT 1"
            row = connection.execute(query, params).fetchone()
            if row is not None:
                return {"source_operation_id": str(row["operation_id"]), "quantity": DEMON_ACTION_CONTRIBUTION[action_key]}
        elif action_key == "maintenance":
            query = "SELECT maintenance.operation_id FROM production_facility_maintenance AS maintenance WHERE maintenance.owner_type='personal' AND maintenance.owner_id=? AND maintenance.paid=1 AND maintenance.status='active'"
            params = (str(player_id),)
            if source_operation_id:
                query += " AND maintenance.operation_id=?"
                params += (source_operation_id,)
            else:
                query += " AND NOT EXISTS (SELECT 1 FROM world_event_contribution_events AS used WHERE used.round_id=? AND used.player_id=? AND used.source_operation_id=maintenance.operation_id)"
                params += (round_id, player_id)
            query += " ORDER BY maintenance.id DESC LIMIT 1"
            row = connection.execute(query, params).fetchone()
            if row is not None:
                return {"source_operation_id": str(row["operation_id"]), "quantity": DEMON_ACTION_CONTRIBUTION[action_key]}
        elif action_key == "battle":
            query = "SELECT battle.battle_id, battle.start_operation_id FROM battle_sessions AS battle WHERE battle.player_id=? AND battle.location_key=? AND battle.status='settled'"
            params = (player_id, DEMON_EVENT_LOCATION)
            if source_operation_id:
                query += " AND battle.start_operation_id=?"
                params += (source_operation_id,)
            else:
                query += " AND NOT EXISTS (SELECT 1 FROM world_event_contribution_events AS used WHERE used.round_id=? AND used.player_id=? AND used.source_operation_id=battle.start_operation_id)"
                params += (round_id, player_id)
            query += " ORDER BY battle.id DESC LIMIT 1"
            row = connection.execute(query, params).fetchone()
            if row is not None:
                damage = int(connection.execute("SELECT COALESCE(SUM(damage),0) AS damage FROM battle_actions WHERE battle_id=? AND actor_key='player'", (row["battle_id"],)).fetchone()["damage"])
                return {"source_operation_id": str(row["start_operation_id"]), "quantity": damage // 100}
        raise EventSourceNotEligibleError("no eligible settled source operation")

    def _demon_record(self, connection: Any, player: Any, event: Any) -> DemonInvasionEventRecord:
        row = connection.execute("SELECT contribution FROM world_event_contributions WHERE round_id=? AND player_id=?", (event["round_id"], player["id"])).fetchone()
        return self._demon_record_from_payload(self._demon_payload(connection, player["id"], event, int(row["contribution"]) if row else 0))

    def _demon_payload(self, connection: Any, player_id: int, event: Any, contribution: int) -> dict[str, object]:
        player = connection.execute("SELECT * FROM players WHERE id=?", (player_id,)).fetchone()
        result = self._json_object(event["result_json"], {})
        return {"player": self._player_payload(self._row_to_player(player)), "round_id": str(event["round_id"]), "event_key": DEMON_EVENT_KEY, "status": str(event["status"]), "starts_at": str(event["starts_at"]), "ends_at": str(event["ends_at"]), "claim_expires_at": str(event["claim_expires_at"]), "target_quantity": int(event["target_quantity"]), "total_contribution": int(event["total_contribution"]), "player_contribution": contribution, "success": result.get("success"), "reward": {}}

    @staticmethod
    def _demon_operation_replay(connection: Any, operation_id: str, operation_name: str, request_hash: str) -> dict[str, object] | None:
        existing = connection.execute("SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id=?", (operation_id,)).fetchone()
        if existing is None:
            return None
        if existing["operation_name"] != operation_name or existing["request_hash"] != request_hash:
            raise OperationConflictError("event operation conflicts with its original input")
        return json.loads(existing["result_json"])

    @staticmethod
    def _demon_insert_operation(connection: Any, operation_id: str, operation_name: str, player_id: int, request_hash: str, payload: dict[str, object], now_text: str) -> None:
        connection.execute("INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)", (operation_id, operation_name, player_id, request_hash, json.dumps(payload, ensure_ascii=False, sort_keys=True), now_text))

    @staticmethod
    def _demon_record_from_payload(payload: dict[str, object], replay: bool = False) -> DemonInvasionEventRecord:
        from ..persistence.sqlite_repository import SQLitePlayerRepository

        return DemonInvasionEventRecord(
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


__all__ = ["DemonInvasionRepositoryMixin"]
