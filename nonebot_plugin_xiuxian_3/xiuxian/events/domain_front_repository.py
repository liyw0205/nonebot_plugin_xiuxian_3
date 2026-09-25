"""SQLite transactions for the v0.4 domain-front activity and season.

The activity has its own tables because participation snapshots, source
operations, and season freezes are materially different from the older spring
event contract.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from ...contracts import serialize_datetime
from ..persistence.errors import (
    DomainCrackActiveError,
    DomainCoreRedeemAlreadyUsedError,
    DomainCoreFragmentInsufficientError,
    DomainCoreRedeemRequirementError,
    DomainEventAlreadyJoinedError,
    DomainEventParticipantCapError,
    DomainEventRequirementError,
    DomainEventRewardAlreadyClaimedError,
    DomainEventRewardNotEligibleError,
    DomainEventRoundNotActiveError,
    DomainEventSourceInvalidError,
    DomainSeasonRankingNotFinalizedError,
    DomainSeasonRewardAlreadyClaimedError,
    DomainSeasonRewardExpiredError,
    DomainSeasonRewardNotEligibleError,
    OperationConflictError,
    ResourceInsufficientError,
)
from .domain_front_models import (
    DomainFrontClaimRecord,
    DomainFrontRecord,
    DomainFrontSeasonClaimRecord,
    DomainCoreRedeemRecord,
    DomainFrontSeasonRecord,
    DomainFrontSeasonStanding,
)
from .domain_front_rules import (
    ACTION_VALUES,
    BATTLE_CONTRIBUTION,
    CLAIM_DAYS,
    CONTENT_VERSION,
    EVENT_KEY,
    EVENT_TARGET,
    JOIN_STAMINA_COST,
    LOCATION_KEY,
    PARTICIPANT_CAP,
    PERSONAL_THRESHOLD,
    POINT_CONTRIBUTION_PER_MINUTE,
    RULE_VERSION,
    anonymous_label,
    claim_expiry,
    meets_domain_front_realm,
    reward_for_rank,
    round_window,
    season_window,
    season_window_for_id,
)


class DomainFrontRepositoryMixin:
    """Own domain-front participation, evidence projection, and season UoW."""

    async def get_domain_front(self, *, platform: str, platform_user_id: str, round_id: str | None = None) -> DomainFrontRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._get_domain_front_once, platform, platform_user_id, round_id)

    async def join_domain_front(self, *, platform: str, platform_user_id: str, operation_id: str) -> DomainFrontRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._join_domain_front_once, platform, platform_user_id, operation_id)

    async def start_domain_front_battle(self, *, platform: str, platform_user_id: str, operation_id: str) -> dict[str, object]:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._start_domain_front_battle_once, platform, platform_user_id, operation_id)

    async def create_domain_front_point(self, *, platform: str, platform_user_id: str, minutes: int, operation_id: str) -> dict[str, object]:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._create_domain_front_point_once, platform, platform_user_id, minutes, operation_id)

    async def record_domain_front_contribution(
        self,
        *,
        platform: str,
        platform_user_id: str,
        action_key: str,
        source_operation_id: str | None,
        operation_id: str,
    ) -> DomainFrontRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._record_domain_front_contribution_once,
                platform,
                platform_user_id,
                action_key,
                source_operation_id,
                operation_id,
            )

    async def claim_domain_front_reward(self, *, platform: str, platform_user_id: str, round_id: str, operation_id: str) -> DomainFrontClaimRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._claim_domain_front_reward_once, platform, platform_user_id, round_id, operation_id)

    async def get_domain_war_season(self, *, platform: str, platform_user_id: str, season_id: str | None = None) -> DomainFrontSeasonRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._get_domain_war_season_once, platform, platform_user_id, season_id)

    async def claim_domain_war_reward(self, *, platform: str, platform_user_id: str, season_id: str, operation_id: str) -> DomainFrontSeasonClaimRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._claim_domain_war_reward_once, platform, platform_user_id, season_id, operation_id)

    async def redeem_domain_core(self, *, platform: str, platform_user_id: str, season_id: str, operation_id: str) -> DomainCoreRedeemRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._redeem_domain_core_once, platform, platform_user_id, season_id, operation_id)

    def _get_domain_front_once(self, platform: str, platform_user_id: str, round_id: str | None) -> DomainFrontRecord:
        now = self._now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            player = self._require_player(connection, platform, platform_user_id, writable=False)
            event = self._domain_select_round(connection, round_id, now)
            event = self._domain_refresh_round(connection, event, now)
            return self._domain_record(connection, int(player["id"]), event)

    def _join_domain_front_once(self, platform: str, platform_user_id: str, operation_id: str) -> DomainFrontRecord:
        operation_name = "event.domain_front.join"
        request_hash = self._request_hash(operation_name, {"platform": platform, "platform_user_id": platform_user_id})
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._domain_operation_replay(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                return self._domain_record_from_payload(replay, replay=True)
            player = self._require_player(connection, platform, platform_user_id)
            event = self._domain_refresh_round(connection, self._domain_select_round(connection, None, now), now)
            self._domain_require_open(event, now)
            sect, membership = self._domain_requirements(connection, player, now)
            existing = connection.execute(
                "SELECT 1 FROM domain_front_participants WHERE round_id=? AND player_id=? AND status='active'",
                (event["round_id"], player["id"]),
            ).fetchone()
            if existing is not None:
                raise DomainEventAlreadyJoinedError("player already joined this round")
            member_count = int(
                connection.execute(
                    "SELECT COUNT(*) AS count FROM domain_front_participants WHERE round_id=? AND sect_id=? AND status='active'",
                    (event["round_id"], sect["sect_id"]),
                ).fetchone()["count"]
            )
            if member_count >= PARTICIPANT_CAP:
                raise DomainEventParticipantCapError("sect participant cap reached")
            if int(player["stamina"]) < JOIN_STAMINA_COST:
                raise ResourceInsufficientError("domain-front stamina is insufficient")
            snapshot = {
                "realm_key": str(player["realm_key"]),
                "realm_layer": int(player["realm_layer"]),
                "domain_key": str(player["domain_key"]),
                "domain_power": int(player["domain_power"]),
                "sect_id": str(sect["sect_id"]),
                "sect_level": int(sect["level"]),
                "content_version": CONTENT_VERSION,
                "rule_version": RULE_VERSION,
            }
            connection.execute(
                "INSERT INTO domain_front_participants(round_id,player_id,sect_id,domain_key,stamina_cost,contribution,status,snapshot_json,joined_at) VALUES (?, ?, ?, ?, ?, 0, 'active', ?, ?)",
                (event["round_id"], player["id"], sect["sect_id"], player["domain_key"], JOIN_STAMINA_COST, json.dumps(snapshot, sort_keys=True), now_text),
            )
            connection.execute("UPDATE players SET stamina=stamina-?, updated_at=? WHERE id=?", (JOIN_STAMINA_COST, now_text, player["id"]))
            payload = self._domain_payload(connection, int(player["id"]), event)
            self._domain_insert_operation(connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text)
            return self._domain_record_from_payload(payload)

    def _start_domain_front_battle_once(self, platform: str, platform_user_id: str, operation_id: str) -> dict[str, object]:
        operation_name = "event.domain_front.battle"
        request_hash = self._request_hash(operation_name, {"platform": platform, "platform_user_id": platform_user_id})
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._domain_operation_replay(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                return {**replay, "idempotent_replay": True}
            player = self._require_player(connection, platform, platform_user_id)
            event = self._domain_refresh_round(connection, self._domain_select_round(connection, None, now), now)
            self._domain_require_open(event, now)
            participant = self._domain_require_participant(connection, int(player["id"]), str(event["round_id"]))
            battle_id = f"domain-front-battle:{uuid4().hex}"
            result = {"outcome": "won", "contribution": BATTLE_CONTRIBUTION, "enemy_key": "enemy.domain_front_guardian"}
            snapshot = self._json_object(participant["snapshot_json"], {})
            connection.execute(
                "INSERT INTO domain_front_battles(battle_id,round_id,player_id,operation_id,status,outcome,snapshot_json,result_json,created_at) VALUES (?, ?, ?, ?, 'settled', 'won', ?, ?, ?)",
                (battle_id, event["round_id"], player["id"], operation_id, json.dumps(snapshot, sort_keys=True), json.dumps(result, sort_keys=True), now_text),
            )
            payload = {"battle_id": battle_id, "round_id": str(event["round_id"]), "outcome": "won", "contribution": BATTLE_CONTRIBUTION, "source_operation_id": operation_id}
            self._domain_insert_operation(connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text)
            return payload

    def _create_domain_front_point_once(self, platform: str, platform_user_id: str, minutes: int, operation_id: str) -> dict[str, object]:
        operation_name = "event.domain_front.point"
        request_hash = self._request_hash(operation_name, {"platform": platform, "platform_user_id": platform_user_id, "minutes": minutes})
        if minutes < 1 or minutes > 30:
            raise ValueError("minutes must be between 1 and 30")
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._domain_operation_replay(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                return {**replay, "idempotent_replay": True}
            player = self._require_player(connection, platform, platform_user_id)
            event = self._domain_refresh_round(connection, self._domain_select_round(connection, None, now), now)
            self._domain_require_open(event, now)
            self._domain_require_participant(connection, int(player["id"]), str(event["round_id"]))
            point_id = f"domain-front-point:{uuid4().hex}"
            connection.execute(
                "INSERT INTO domain_front_point_operations(point_id,round_id,player_id,operation_id,minutes,status,created_at) VALUES (?, ?, ?, ?, ?, 'settled', ?)",
                (point_id, event["round_id"], player["id"], operation_id, minutes, now_text),
            )
            payload = {"point_id": point_id, "round_id": str(event["round_id"]), "minutes": minutes, "contribution": minutes * POINT_CONTRIBUTION_PER_MINUTE, "source_operation_id": operation_id}
            self._domain_insert_operation(connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text)
            return payload

    def _record_domain_front_contribution_once(self, platform: str, platform_user_id: str, action_key: str, source_operation_id: str | None, operation_id: str) -> DomainFrontRecord:
        action = ACTION_VALUES.get(action_key, action_key)
        if action not in {"battle", "point"}:
            raise DomainEventSourceInvalidError("unsupported domain-front action")
        operation_name = "event.domain_front.contribute"
        request_hash = self._request_hash(operation_name, {"platform": platform, "platform_user_id": platform_user_id, "action_key": action, "source_operation_id": source_operation_id or ""})
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._domain_operation_replay(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                return self._domain_record_from_payload(replay, replay=True)
            player = self._require_player(connection, platform, platform_user_id)
            event = self._domain_refresh_round(connection, self._domain_select_round(connection, None, now), now)
            self._domain_require_open(event, now)
            participant = self._domain_require_participant(connection, int(player["id"]), str(event["round_id"]))
            source = self._domain_find_source(connection, int(player["id"]), str(event["round_id"]), action, source_operation_id)
            source_id = str(source["source_operation_id"])
            if connection.execute("SELECT 1 FROM domain_front_contributions WHERE round_id=? AND player_id=? AND source_operation_id=?", (event["round_id"], player["id"], source_id)).fetchone() is not None:
                raise DomainEventSourceInvalidError("domain-front source already contributed")
            quantity = int(source["quantity"])
            connection.execute(
                "INSERT INTO domain_front_contributions(round_id,player_id,sect_id,domain_key,source_operation_id,action_key,quantity,operation_id,occurred_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (event["round_id"], player["id"], participant["sect_id"], participant["domain_key"], source_id, action, quantity, operation_id, now_text),
            )
            connection.execute("UPDATE domain_front_participants SET contribution=contribution+? WHERE round_id=? AND player_id=?", (quantity, event["round_id"], player["id"]))
            total = int(connection.execute("SELECT COALESCE(SUM(quantity),0) AS total FROM domain_front_contributions WHERE round_id=?", (event["round_id"],)).fetchone()["total"])
            connection.execute("UPDATE domain_front_rounds SET status='running', total_contribution=?, updated_at=? WHERE round_id=? AND status='open'", (total, now_text, event["round_id"]))
            event = connection.execute("SELECT * FROM domain_front_rounds WHERE round_id=?", (event["round_id"],)).fetchone()
            payload = self._domain_payload(connection, int(player["id"]), event)
            payload.update({"action_key": action, "source_operation_id": source_id, "quantity": quantity})
            self._domain_insert_operation(connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text)
            return self._domain_record_from_payload(payload)

    def _claim_domain_front_reward_once(self, platform: str, platform_user_id: str, round_id: str, operation_id: str) -> DomainFrontClaimRecord:
        operation_name = "event.domain_front.claim"
        request_hash = self._request_hash(operation_name, {"platform": platform, "platform_user_id": platform_user_id, "round_id": round_id})
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._domain_operation_replay(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                return DomainFrontClaimRecord(str(replay["round_id"]), {str(k): int(v) for k, v in dict(replay["reward"]).items()}, True)
            player = self._require_player(connection, platform, platform_user_id)
            event = self._domain_refresh_round(connection, self._domain_select_round(connection, round_id, now), now)
            if event is None or str(event["status"]) != "settled":
                raise DomainEventRoundNotActiveError("domain-front round is not settled")
            if now >= datetime.fromisoformat(str(event["claim_expires_at"])):
                raise DomainEventRoundNotActiveError("domain-front claim window closed")
            participant = connection.execute("SELECT contribution FROM domain_front_participants WHERE round_id=? AND player_id=?", (round_id, player["id"])).fetchone()
            if participant is None or int(participant["contribution"]) < PERSONAL_THRESHOLD:
                raise DomainEventRewardNotEligibleError("domain-front personal contribution is insufficient")
            if connection.execute("SELECT 1 FROM domain_front_claims WHERE round_id=? AND player_id=?", (round_id, player["id"])).fetchone() is not None:
                raise DomainEventRewardAlreadyClaimedError("domain-front reward already claimed")
            reward = {"item.domain_core_fragment": 5, "world_merit": 100}
            inventory = self._json_object(player["inventory_json"], {})
            inventory["item.domain_core_fragment"] = int(inventory.get("item.domain_core_fragment", 0)) + 5
            connection.execute("UPDATE players SET inventory_json=?, world_merit=world_merit+?, updated_at=? WHERE id=?", (json.dumps(inventory, sort_keys=True), reward["world_merit"], now_text, player["id"]))
            connection.execute("INSERT INTO domain_front_claims(round_id,player_id,operation_id,reward_json,claimed_at) VALUES (?, ?, ?, ?, ?)", (round_id, player["id"], operation_id, json.dumps(reward, sort_keys=True), now_text))
            payload = {"round_id": round_id, "reward": reward}
            self._domain_insert_operation(connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text)
            return DomainFrontClaimRecord(round_id, reward)

    def _get_domain_war_season_once(self, platform: str, platform_user_id: str, season_id: str | None) -> DomainFrontSeasonRecord:
        now = self._now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            player = self._require_player(connection, platform, platform_user_id, writable=False)
            if season_id is None:
                season_id, starts_at, ends_at = season_window(now)
            else:
                season_id, starts_at, ends_at = season_window_for_id(season_id)
            season = self._domain_get_or_create_season(connection, season_id, starts_at, ends_at, now)
            if str(season["status"]) == "collecting" and now >= ends_at:
                self._domain_freeze_season(connection, season, now)
                season = connection.execute("SELECT * FROM domain_war_seasons WHERE season_id=?", (season_id,)).fetchone()
            return self._domain_season_record(connection, int(player["id"]), season)

    def _claim_domain_war_reward_once(self, platform: str, platform_user_id: str, season_id: str, operation_id: str) -> DomainFrontSeasonClaimRecord:
        operation_name = "event.domain_war.claim"
        request_hash = self._request_hash(operation_name, {"platform": platform, "platform_user_id": platform_user_id, "season_id": season_id})
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._domain_operation_replay(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                return DomainFrontSeasonClaimRecord(str(replay["season_id"]), {str(k): int(v) for k, v in dict(replay["reward"]).items()}, int(replay["rank"]), True, bool(replay.get("expired", False)))
            player = self._require_player(connection, platform, platform_user_id)
            canonical_id, starts_at, ends_at = season_window_for_id(season_id)
            season = self._domain_get_or_create_season(connection, canonical_id, starts_at, ends_at, now)
            if str(season["status"]) == "collecting" and now >= ends_at:
                self._domain_freeze_season(connection, season, now)
                season = connection.execute("SELECT * FROM domain_war_seasons WHERE season_id=?", (canonical_id,)).fetchone()
            if str(season["status"]) != "frozen":
                raise DomainSeasonRankingNotFinalizedError("domain-war ranking is not finalized")
            if now >= datetime.fromisoformat(str(season["claim_expires_at"])):
                raise DomainSeasonRewardExpiredError("domain-war claim window closed")
            standing = connection.execute("SELECT * FROM domain_war_rankings WHERE season_id=? AND player_id=?", (canonical_id, player["id"])).fetchone()
            if standing is None or not self._json_object(standing["reward_json"], {}):
                raise DomainSeasonRewardNotEligibleError("player has no domain-war ranking reward")
            if connection.execute("SELECT 1 FROM domain_war_claims WHERE season_id=? AND player_id=?", (canonical_id, player["id"])).fetchone() is not None:
                raise DomainSeasonRewardAlreadyClaimedError("domain-war reward already claimed")
            reward = {str(k): int(v) for k, v in self._json_object(standing["reward_json"], {}).items()}
            inventory = self._json_object(player["inventory_json"], {})
            for key, value in reward.items():
                if key.startswith("item."):
                    inventory[key] = int(inventory.get(key, 0)) + value
            connection.execute("UPDATE players SET inventory_json=?, world_merit=world_merit+?, updated_at=? WHERE id=?", (json.dumps(inventory, sort_keys=True), reward.get("world_merit", 0), now_text, player["id"]))
            connection.execute("INSERT INTO domain_war_claims(season_id,player_id,operation_id,reward_json,claimed_at) VALUES (?, ?, ?, ?, ?)", (canonical_id, player["id"], operation_id, json.dumps(reward, sort_keys=True), now_text))
            payload = {"season_id": canonical_id, "rank": int(standing["rank"]), "reward": reward}
            self._domain_insert_operation(connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text)
            return DomainFrontSeasonClaimRecord(canonical_id, reward, int(standing["rank"]))

    def _redeem_domain_core_once(self, platform: str, platform_user_id: str, season_id: str, operation_id: str) -> DomainCoreRedeemRecord:
        operation_name = "event.redeem.domain_core"
        request_hash = self._request_hash(operation_name, {"platform": platform, "platform_user_id": platform_user_id, "season_id": season_id})
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._domain_operation_replay(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                return DomainCoreRedeemRecord(str(replay["season_id"]), "item.domain_core", 1, True)
            player = self._require_player(connection, platform, platform_user_id)
            canonical_id, starts_at, ends_at = season_window_for_id(season_id)
            season = self._domain_get_or_create_season(connection, canonical_id, starts_at, ends_at, now)
            if str(season["status"]) == "collecting" and now >= ends_at:
                self._domain_freeze_season(connection, season, now)
                season = connection.execute("SELECT * FROM domain_war_seasons WHERE season_id=?", (canonical_id,)).fetchone()
            if str(season["status"]) != "frozen" or now < ends_at or now >= datetime.fromisoformat(str(season["claim_expires_at"])):
                raise DomainCoreRedeemRequirementError("domain core redemption requires a closed season")
            if connection.execute("SELECT 1 FROM domain_core_redemptions WHERE season_id=? AND player_id=?", (canonical_id, player["id"])).fetchone() is not None:
                raise DomainCoreRedeemAlreadyUsedError("domain core already redeemed")
            inventory = self._json_object(player["inventory_json"], {})
            if int(inventory.get("item.domain_core_fragment", 0)) < 20:
                raise DomainCoreFragmentInsufficientError("domain core fragments are insufficient")
            inventory["item.domain_core_fragment"] = int(inventory["item.domain_core_fragment"]) - 20
            if inventory["item.domain_core_fragment"] <= 0:
                inventory.pop("item.domain_core_fragment", None)
            inventory["item.domain_core"] = int(inventory.get("item.domain_core", 0)) + 1
            connection.execute("UPDATE players SET inventory_json=?, updated_at=? WHERE id=?", (json.dumps(inventory, sort_keys=True), now_text, player["id"]))
            connection.execute("INSERT INTO domain_core_redemptions(season_id,player_id,operation_id,redeemed_at) VALUES (?, ?, ?, ?)", (canonical_id, player["id"], operation_id, now_text))
            payload = {"season_id": canonical_id, "item_key": "item.domain_core", "quantity": 1}
            self._domain_insert_operation(connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text)
            return DomainCoreRedeemRecord(canonical_id, "item.domain_core", 1)

    def _domain_select_round(self, connection: Any, round_id: str | None, now: datetime) -> Any:
        if round_id:
            return connection.execute("SELECT * FROM domain_front_rounds WHERE round_id=?", (round_id,)).fetchone()
        rid, activity_id, activity_start, activity_end, starts_at, ends_at = round_window(now)
        now_text = serialize_datetime(now)
        connection.execute(
            "INSERT OR IGNORE INTO domain_front_rounds(round_id,activity_id,location_key,status,activity_starts_at,activity_ends_at,starts_at,ends_at,claim_expires_at,target_quantity,total_contribution,result_json,rule_version,created_at,updated_at) VALUES (?, ?, ?, 'open', ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?)",
            (rid, activity_id, LOCATION_KEY, serialize_datetime(activity_start), serialize_datetime(activity_end), serialize_datetime(starts_at), serialize_datetime(ends_at), serialize_datetime(ends_at + timedelta(days=CLAIM_DAYS)), EVENT_TARGET, json.dumps({"content_version": CONTENT_VERSION, "success": False}, sort_keys=True), RULE_VERSION, now_text, now_text),
        )
        return connection.execute("SELECT * FROM domain_front_rounds WHERE round_id=?", (rid,)).fetchone()

    def _domain_refresh_round(self, connection: Any, event: Any, now: datetime) -> Any:
        if event is None:
            raise DomainEventRoundNotActiveError("domain-front round does not exist")
        if str(event["status"]) in {"open", "running"} and now >= datetime.fromisoformat(str(event["ends_at"])):
            total = int(connection.execute("SELECT COALESCE(SUM(quantity),0) AS total FROM domain_front_contributions WHERE round_id=?", (event["round_id"],)).fetchone()["total"])
            winner = connection.execute("SELECT domain_key, SUM(quantity) AS score FROM domain_front_contributions WHERE round_id=? GROUP BY domain_key ORDER BY score DESC, domain_key ASC LIMIT 1", (event["round_id"],)).fetchone()
            result = self._json_object(event["result_json"], {})
            result.update({"content_version": CONTENT_VERSION, "success": total >= int(event["target_quantity"]), "winner_domain": winner["domain_key"] if winner else None, "settled_at": serialize_datetime(now)})
            connection.execute("UPDATE domain_front_rounds SET status='settled', total_contribution=?, result_json=?, updated_at=? WHERE round_id=? AND status IN ('open','running')", (total, json.dumps(result, sort_keys=True), serialize_datetime(now), event["round_id"]))
            event = connection.execute("SELECT * FROM domain_front_rounds WHERE round_id=?", (event["round_id"],)).fetchone()
        return event

    def _domain_require_open(self, event: Any, now: datetime) -> None:
        if event is None or str(event["status"]) not in {"open", "running"} or now >= datetime.fromisoformat(str(event["ends_at"])):
            raise DomainEventRoundNotActiveError("domain-front round is not active")

    def _domain_requirements(self, connection: Any, player: Any, now: datetime) -> tuple[Any, Any]:
        if not meets_domain_front_realm(str(player["realm_key"]), int(player["realm_layer"])) or not player["domain_key"]:
            raise DomainEventRequirementError("domain-front requires a selected soul-transformation domain")
        crack = player["domain_crack_until"]
        if crack and now < datetime.fromisoformat(str(crack)):
            raise DomainCrackActiveError("domain crack is active")
        if str(player["location_key"]) != LOCATION_KEY:
            raise DomainEventRequirementError("player is not at the domain front")
        membership = connection.execute("SELECT * FROM sect_members WHERE player_id=? AND status='active'", (player["id"],)).fetchone()
        if membership is None:
            raise DomainEventRequirementError("domain-front requires an active sect")
        sect = connection.execute("SELECT * FROM sects WHERE sect_id=? AND status='active'", (membership["sect_id"],)).fetchone()
        if sect is None or int(sect["level"]) < 4:
            raise DomainEventRequirementError("domain-front requires sect level 4")
        return sect, membership

    @staticmethod
    def _domain_require_participant(connection: Any, player_id: int, round_id: str) -> Any:
        row = connection.execute("SELECT * FROM domain_front_participants WHERE round_id=? AND player_id=? AND status='active'", (round_id, player_id)).fetchone()
        if row is None:
            raise DomainEventRequirementError("player has not joined this domain-front round")
        return row

    def _domain_find_source(self, connection: Any, player_id: int, round_id: str, action: str, source_operation_id: str | None) -> dict[str, object]:
        if action == "battle":
            query = "SELECT operation_id FROM domain_front_battles WHERE round_id=? AND player_id=? AND status='settled' AND outcome='won'"
            params: list[object] = [round_id, player_id]
            if source_operation_id:
                query += " AND operation_id=?"
                params.append(source_operation_id)
            else:
                query += " AND NOT EXISTS (SELECT 1 FROM domain_front_contributions used WHERE used.round_id=? AND used.player_id=? AND used.source_operation_id=domain_front_battles.operation_id)"
                params.extend([round_id, player_id])
            query += " ORDER BY created_at DESC LIMIT 1"
            row = connection.execute(query, tuple(params)).fetchone()
            if row is None:
                # A settled combat session is accepted as server evidence too.
                query = "SELECT start_operation_id AS operation_id FROM battle_sessions WHERE player_id=? AND location_key=? AND status IN ('won','settled') AND json_extract(result_json,'$.outcome')='won'"
                params = [player_id, LOCATION_KEY]
                if source_operation_id:
                    query += " AND start_operation_id=?"
                    params.append(source_operation_id)
                query += " ORDER BY updated_at DESC LIMIT 1"
                row = connection.execute(query, tuple(params)).fetchone()
            if row is not None:
                return {"source_operation_id": str(row["operation_id"]), "quantity": BATTLE_CONTRIBUTION}
        if action == "point":
            query = "SELECT operation_id, minutes FROM domain_front_point_operations WHERE round_id=? AND player_id=? AND status='settled'"
            params = [round_id, player_id]
            if source_operation_id:
                query += " AND operation_id=?"
                params.append(source_operation_id)
            else:
                query += " AND NOT EXISTS (SELECT 1 FROM domain_front_contributions used WHERE used.round_id=? AND used.player_id=? AND used.source_operation_id=domain_front_point_operations.operation_id)"
                params.extend([round_id, player_id])
            query += " ORDER BY created_at DESC LIMIT 1"
            row = connection.execute(query, tuple(params)).fetchone()
            if row is not None:
                return {"source_operation_id": str(row["operation_id"]), "quantity": int(row["minutes"]) * POINT_CONTRIBUTION_PER_MINUTE}
        raise DomainEventSourceInvalidError("no eligible settled domain-front source operation")

    def _domain_payload(self, connection: Any, player_id: int, event: Any) -> dict[str, object]:
        participant = connection.execute("SELECT * FROM domain_front_participants WHERE round_id=? AND player_id=?", (event["round_id"], player_id)).fetchone()
        result = self._json_object(event["result_json"], {})
        return {"round_id": str(event["round_id"]), "activity_id": str(event["activity_id"]), "status": str(event["status"]), "activity_starts_at": str(event["activity_starts_at"]), "activity_ends_at": str(event["activity_ends_at"]), "starts_at": str(event["starts_at"]), "ends_at": str(event["ends_at"]), "claim_expires_at": str(event["claim_expires_at"]), "total_contribution": int(event["total_contribution"]), "player_contribution": int(participant["contribution"]) if participant else 0, "participant": participant is not None and participant["status"] == "active", "sect_id": str(participant["sect_id"]) if participant else None, "domain_key": str(participant["domain_key"]) if participant else None, "winner_domain": result.get("winner_domain"), "success": result.get("success")}

    def _domain_record(self, connection: Any, player_id: int, event: Any) -> DomainFrontRecord:
        return self._domain_record_from_payload(self._domain_payload(connection, player_id, event))

    @staticmethod
    def _domain_record_from_payload(payload: dict[str, object], replay: bool = False) -> DomainFrontRecord:
        return DomainFrontRecord(str(payload["round_id"]), str(payload["activity_id"]), str(payload["status"]), str(payload["activity_starts_at"]), str(payload["activity_ends_at"]), str(payload["starts_at"]), str(payload["ends_at"]), str(payload["claim_expires_at"]), int(payload["total_contribution"]), int(payload["player_contribution"]), bool(payload["participant"]), payload.get("sect_id") and str(payload["sect_id"]), payload.get("domain_key") and str(payload["domain_key"]), payload.get("winner_domain") and str(payload["winner_domain"]), payload.get("success") if payload.get("success") is None else bool(payload["success"]), {str(k): int(v) for k, v in dict(payload.get("reward", {})).items()}, replay or bool(payload.get("idempotent_replay", False)))

    def _domain_get_or_create_season(self, connection: Any, season_id: str, starts_at: datetime, ends_at: datetime, now: datetime) -> Any:
        now_text = serialize_datetime(now)
        connection.execute("INSERT OR IGNORE INTO domain_war_seasons(season_id,starts_at,ends_at,claim_expires_at,status,frozen_at,snapshot_json,rule_version,created_at,updated_at) VALUES (?, ?, ?, ?, 'collecting', NULL, '{}', ?, ?, ?)", (season_id, serialize_datetime(starts_at), serialize_datetime(ends_at), serialize_datetime(claim_expiry(ends_at)), RULE_VERSION, now_text, now_text))
        return connection.execute("SELECT * FROM domain_war_seasons WHERE season_id=?", (season_id,)).fetchone()

    def _domain_freeze_season(self, connection: Any, season: Any, now: datetime) -> None:
        if str(season["status"]) == "frozen":
            return
        scores: dict[int, dict[str, object]] = {}
        rows = connection.execute("SELECT player_id, occurred_at, quantity FROM domain_front_contributions c JOIN domain_front_rounds r ON r.round_id=c.round_id WHERE r.starts_at>=? AND r.starts_at<? AND quantity>0", (season["starts_at"], season["ends_at"])).fetchall()
        for row in rows:
            entry = scores.setdefault(int(row["player_id"]), {"score": 0, "achieved_at": str(row["occurred_at"])})
            entry["score"] = int(entry["score"]) + int(row["quantity"])
            entry["achieved_at"] = min(str(entry["achieved_at"]), str(row["occurred_at"]))
        sect_rows = connection.execute("SELECT player_id, occurred_at, quantity FROM sect_contribution_events WHERE occurred_at>=? AND occurred_at<? AND quantity>0", (season["starts_at"], season["ends_at"])).fetchall()
        for row in sect_rows:
            entry = scores.setdefault(int(row["player_id"]), {"score": 0, "achieved_at": str(row["occurred_at"])})
            entry["score"] = int(entry["score"]) + int(row["quantity"]) * 2
            entry["achieved_at"] = min(str(entry["achieved_at"]), str(row["occurred_at"]))
        production_rows = connection.execute("SELECT player_id, updated_at FROM production_orders WHERE status='completed' AND updated_at>=? AND updated_at<? AND (recipe_key LIKE 'recipe.domain.%' OR json_extract(snapshot_json,'$.realm_key')='soul_transformation')", (season["starts_at"], season["ends_at"])).fetchall()
        for row in production_rows:
            entry = scores.setdefault(int(row["player_id"]), {"score": 0, "achieved_at": str(row["updated_at"])})
            entry["score"] = int(entry["score"]) + 5
            entry["achieved_at"] = min(str(entry["achieved_at"]), str(row["updated_at"]))
        rows = sorted(({"player_id": player_id, **value} for player_id, value in scores.items() if int(value["score"]) > 0), key=lambda row: (-int(row["score"]), str(row["achieved_at"]), int(row["player_id"])))
        snapshot = []
        for rank, row in enumerate(rows[:50], 1):
            reward = reward_for_rank(rank)
            label = anonymous_label(str(season["season_id"]), int(row["player_id"]))
            connection.execute("INSERT OR IGNORE INTO domain_war_rankings(season_id,player_id,rank,score,achieved_at,anonymous_label,reward_json) VALUES (?, ?, ?, ?, ?, ?, ?)", (season["season_id"], row["player_id"], rank, row["score"], row["achieved_at"], label, json.dumps(reward, sort_keys=True)))
            snapshot.append({"rank": rank, "anonymous_label": label, "score": int(row["score"]), "achieved_at": str(row["achieved_at"]), "reward": reward})
        connection.execute("UPDATE domain_war_seasons SET status='frozen', frozen_at=?, snapshot_json=?, updated_at=? WHERE season_id=? AND status='collecting'", (serialize_datetime(now), json.dumps(snapshot, sort_keys=True), serialize_datetime(now), season["season_id"]))

    def _domain_season_record(self, connection: Any, player_id: int, season: Any) -> DomainFrontSeasonRecord:
        rows = connection.execute("SELECT * FROM domain_war_rankings WHERE season_id=? ORDER BY rank", (season["season_id"],)).fetchall()
        standings = tuple(DomainFrontSeasonStanding(int(row["rank"]), str(row["anonymous_label"]), int(row["score"]), str(row["achieved_at"]), self._json_object(row["reward_json"], {})) for row in rows)
        own_row = connection.execute("SELECT * FROM domain_war_rankings WHERE season_id=? AND player_id=?", (season["season_id"], player_id)).fetchone()
        own = DomainFrontSeasonStanding(int(own_row["rank"]), str(own_row["anonymous_label"]), int(own_row["score"]), str(own_row["achieved_at"]), self._json_object(own_row["reward_json"], {})) if own_row else None
        return DomainFrontSeasonRecord(str(season["season_id"]), str(season["status"]), str(season["starts_at"]), str(season["ends_at"]), str(season["claim_expires_at"]), season["frozen_at"] and str(season["frozen_at"]), standings, own)

    def _domain_operation_replay(self, connection: Any, operation_id: str, operation_name: str, request_hash: str) -> dict[str, object] | None:
        row = connection.execute("SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id=?", (operation_id,)).fetchone()
        if row is None:
            return None
        if str(row["operation_name"]) != operation_name or str(row["request_hash"]) != request_hash:
            raise OperationConflictError("operation id was reused with different input")
        return self._json_object(row["result_json"], {})

    def _domain_insert_operation(self, connection: Any, operation_id: str, operation_name: str, player_id: int, request_hash: str, payload: dict[str, object], now_text: str) -> None:
        connection.execute("INSERT INTO operations(operation_id,operation_name,player_id,request_hash,result_json,created_at) VALUES (?, ?, ?, ?, ?, ?)", (operation_id, operation_name, player_id, request_hash, json.dumps(payload, ensure_ascii=False, sort_keys=True), now_text))

    @staticmethod
    def _domain_record_from_payload_with_reward(payload: dict[str, object]) -> DomainFrontRecord:
        return DomainFrontRepositoryMixin._domain_record_from_payload(payload)


__all__ = ["DomainFrontRepositoryMixin"]
