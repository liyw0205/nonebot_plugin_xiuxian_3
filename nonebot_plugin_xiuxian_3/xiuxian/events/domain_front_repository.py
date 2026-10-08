"""SQLite transactions for the domain-front activity and season.

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
from ..content import bundled_content
from ..utils.json_cache import decode_json_strict
from ..utils.assets import change_player_assets
from ..utils.player import change_player_state, grant_player_reward_actual, player_integer
from ..specials.codex_projection import record_codex_discovery
from ..persistence.errors import (
    DomainCrackActiveError,
    DomainCoreRedeemAlreadyUsedError,
    DomainCoreFragmentInsufficientError,
    DomainCoreRedeemRequirementError,
    DomainEventAlreadyJoinedError,
    DomainEventParticipantCapError,
    DomainEventPointMinutesError,
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
    anonymous_label,
    claim_expiry,
    domain_front_definition,
    domain_front_definition_from_snapshot,
    domain_war_season_definition,
    domain_war_season_definition_from_snapshot,
    meets_domain_front_realm,
    round_window,
    season_window,
    season_window_for_id,
    ACTION_VALUES,
)
from ..rewards.rules import reward_totals


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

    async def record_domain_front_battle(
        self,
        *,
        platform: str,
        platform_user_id: str,
        battle_id: str,
        operation_id: str,
    ) -> dict[str, object]:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._record_domain_front_battle_once,
                platform,
                platform_user_id,
                battle_id,
                operation_id,
            )

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
            rules = self._domain_round_rules(event)
            sect, membership = self._domain_requirements(connection, player, now, rules)
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
            if member_count >= rules.participant_cap:
                raise DomainEventParticipantCapError("sect participant cap reached")
            if player_integer(player, "stamina") < rules.join_stamina_cost:
                raise ResourceInsufficientError("domain-front stamina is insufficient")
            snapshot = {
                "realm_key": str(player["realm_key"]),
                "realm_layer": player_integer(player, "realm_layer"),
                "domain_key": str(player["domain_key"]),
                "domain_power": player_integer(player, "domain_power"),
                "sect_id": str(sect["sect_id"]),
                "sect_level": int(sect["level"]),
            }
            connection.execute(
                "INSERT INTO domain_front_participants(round_id,player_id,sect_id,domain_key,stamina_cost,contribution,status,snapshot_json,joined_at) VALUES (?, ?, ?, ?, ?, 0, 'active', ?, ?)",
                (event["round_id"], player["id"], sect["sect_id"], player["domain_key"], rules.join_stamina_cost, json.dumps(snapshot, sort_keys=True), now_text),
            )
            change_player_state(
                connection,
                player,
                updated_at=now_text,
                value_delta={"stamina": -rules.join_stamina_cost},
            )
            payload = self._domain_payload(connection, int(player["id"]), event)
            self._domain_insert_operation(connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text)
            return self._domain_record_from_payload(payload)

    def _record_domain_front_battle_once(
        self,
        platform: str,
        platform_user_id: str,
        battle_id: str,
        operation_id: str,
    ) -> dict[str, object]:
        operation_name = "event.domain_front.battle"
        request_hash = self._request_hash(
            operation_name,
            {
                "platform": platform,
                "platform_user_id": platform_user_id,
                "battle_id": battle_id,
            },
        )
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._domain_operation_replay(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                return {**replay, "idempotent_replay": True}
            player = self._require_player(connection, platform, platform_user_id)
            battle = connection.execute(
                """
                SELECT links.round_id, links.player_id, links.event_operation_id,
                       links.combat_operation_id, sessions.battle_id,
                       sessions.start_operation_id, sessions.battle_type,
                       sessions.status, sessions.result_json
                FROM domain_front_battle_links AS links
                JOIN battle_sessions AS sessions ON sessions.battle_id = links.battle_id
                WHERE links.battle_id = ? AND links.event_operation_id = ?
                """,
                (battle_id, operation_id),
            ).fetchone()
            if battle is None or int(battle["player_id"]) != int(player["id"]):
                raise DomainEventSourceInvalidError("formal domain-front battle link is missing")
            if (
                str(battle["battle_type"]) != "pve.domain_front"
                or str(battle["combat_operation_id"])
                != str(battle["start_operation_id"])
            ):
                raise DomainEventSourceInvalidError("formal domain-front battle identity is invalid")
            if str(battle["status"]) != "settled":
                raise DomainEventRoundNotActiveError("domain-front battle has not settled")
            try:
                result = self._domain_strict_object(battle["result_json"])
            except ValueError as exc:
                raise DomainEventSourceInvalidError("formal domain-front battle result is invalid") from exc
            outcome = str(result.get("outcome", ""))
            if outcome not in {"won", "lost"}:
                raise DomainEventSourceInvalidError("formal domain-front battle has no final outcome")
            event = connection.execute("SELECT * FROM domain_front_rounds WHERE round_id=?", (battle["round_id"],)).fetchone()
            rules = self._domain_round_rules(event)
            payload = {
                "battle_id": str(battle["battle_id"]),
                "round_id": str(battle["round_id"]),
                "outcome": outcome,
                "contribution": rules.battle_contribution if outcome == "won" else 0,
                "source_operation_id": operation_id,
                "idempotent_replay": False,
            }
            self._domain_insert_operation(connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text)
            return payload

    def _create_domain_front_point_once(self, platform: str, platform_user_id: str, minutes: int, operation_id: str) -> dict[str, object]:
        operation_name = "event.domain_front.point"
        request_hash = self._request_hash(operation_name, {"platform": platform, "platform_user_id": platform_user_id, "minutes": minutes})
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
            rules = self._domain_round_rules(event)
            if minutes < rules.point_minutes_min or minutes > rules.point_minutes_max:
                raise DomainEventPointMinutesError(rules.point_minutes_min, rules.point_minutes_max)
            self._domain_require_participant(connection, int(player["id"]), str(event["round_id"]))
            point_id = f"domain-front-point:{uuid4().hex}"
            connection.execute(
                "INSERT INTO domain_front_point_operations(point_id,round_id,player_id,operation_id,minutes,status,created_at) VALUES (?, ?, ?, ?, ?, 'settled', ?)",
                (point_id, event["round_id"], player["id"], operation_id, minutes, now_text),
            )
            payload = {"point_id": point_id, "round_id": str(event["round_id"]), "minutes": minutes, "contribution": minutes * rules.point_contribution_per_minute, "source_operation_id": operation_id}
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
            rules = self._domain_round_rules(event)
            participant = self._domain_require_participant(connection, int(player["id"]), str(event["round_id"]))
            source = self._domain_find_source(connection, int(player["id"]), str(event["round_id"]), action, source_operation_id, rules)
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
                return DomainFrontClaimRecord(str(replay["round_id"]), {str(k): int(v) for k, v in dict(replay["reward"]).items()}, str(replay["reward_name"]), True)
            player = self._require_player(connection, platform, platform_user_id)
            event = self._domain_refresh_round(connection, self._domain_select_round(connection, round_id, now), now)
            if event is None or str(event["status"]) != "settled":
                raise DomainEventRoundNotActiveError("domain-front round is not settled")
            if now >= datetime.fromisoformat(str(event["claim_expires_at"])):
                raise DomainEventRoundNotActiveError("domain-front claim window closed")
            participant = connection.execute("SELECT contribution, domain_key FROM domain_front_participants WHERE round_id=? AND player_id=?", (round_id, player["id"])).fetchone()
            rules = self._domain_round_rules(event)
            if participant is None or int(participant["contribution"]) < rules.personal_claim_threshold:
                raise DomainEventRewardNotEligibleError("domain-front personal contribution is insufficient")
            if connection.execute("SELECT 1 FROM domain_front_claims WHERE round_id=? AND player_id=?", (round_id, player["id"])).fetchone() is not None:
                raise DomainEventRewardAlreadyClaimedError("domain-front reward already claimed")
            reward_grant = rules.reward
            reward = grant_player_reward_actual(
                connection,
                player,
                reward_totals(reward_grant),
                now_text,
                local_reputation_maximums=dict(rules.reward_local_reputation_maximums) or None,
            )
            reward = {key: amount for key, amount in reward.items() if amount}
            connection.execute("INSERT INTO domain_front_claims(round_id,player_id,operation_id,reward_json,claimed_at) VALUES (?, ?, ?, ?, ?)", (round_id, player["id"], operation_id, json.dumps(reward, sort_keys=True), now_text))
            record_codex_discovery(
                connection,
                player_id=int(player["id"]),
                entry_key=rules.codex_entry_key,
                operation_id=operation_id,
                occurred_at=now_text,
                snapshot={
                    "round_id": round_id,
                    "domain_key": participant["domain_key"],
                    "contribution": int(participant["contribution"]),
                    "result": self._domain_strict_object(event["result_json"]),
                },
                content=self.content or bundled_content(),
            )
            payload = {"round_id": round_id, "reward": reward, "reward_name": rules.reward_name}
            self._domain_insert_operation(connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text)
            return DomainFrontClaimRecord(round_id, reward, rules.reward_name)

    def _get_domain_war_season_once(self, platform: str, platform_user_id: str, season_id: str | None) -> DomainFrontSeasonRecord:
        now = self._now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            player = self._require_player(connection, platform, platform_user_id, writable=False)
            if season_id is None:
                rules = domain_war_season_definition(self.content)
                season_id, starts_at, ends_at = season_window(now, rules)
            else:
                existing = connection.execute("SELECT * FROM domain_war_seasons WHERE season_id=?", (season_id,)).fetchone()
                rules = self._domain_season_rules(existing) if existing is not None else domain_war_season_definition(self.content)
                season_id, starts_at, ends_at = season_window_for_id(season_id, rules)
            season = self._domain_get_or_create_season(connection, season_id, starts_at, ends_at, now, rules)
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
                return DomainFrontSeasonClaimRecord(str(replay["season_id"]), {str(k): int(v) for k, v in dict(replay["reward"]).items()}, int(replay["rank"]), str(replay["reward_name"]), True, bool(replay.get("expired", False)))
            player = self._require_player(connection, platform, platform_user_id)
            existing = connection.execute("SELECT * FROM domain_war_seasons WHERE season_id=?", (season_id,)).fetchone()
            current_rules = self._domain_season_rules(existing) if existing is not None else domain_war_season_definition(self.content)
            canonical_id, starts_at, ends_at = season_window_for_id(season_id, current_rules)
            season = self._domain_get_or_create_season(connection, canonical_id, starts_at, ends_at, now, current_rules)
            if str(season["status"]) == "collecting" and now >= ends_at:
                self._domain_freeze_season(connection, season, now)
                season = connection.execute("SELECT * FROM domain_war_seasons WHERE season_id=?", (canonical_id,)).fetchone()
            if str(season["status"]) != "frozen":
                raise DomainSeasonRankingNotFinalizedError("domain-war ranking is not finalized")
            if now >= datetime.fromisoformat(str(season["claim_expires_at"])):
                raise DomainSeasonRewardExpiredError("domain-war claim window closed")
            standing = connection.execute("SELECT * FROM domain_war_rankings WHERE season_id=? AND player_id=?", (canonical_id, player["id"])).fetchone()
            standing_reward = self._domain_strict_object(standing["reward_json"]) if standing is not None else {}
            if standing is None or not standing_reward:
                raise DomainSeasonRewardNotEligibleError("player has no domain-war ranking reward")
            if connection.execute("SELECT 1 FROM domain_war_claims WHERE season_id=? AND player_id=?", (canonical_id, player["id"])).fetchone() is not None:
                raise DomainSeasonRewardAlreadyClaimedError("domain-war reward already claimed")
            season_rules = self._domain_season_rules(season)
            reward = season_rules.reward_for_rank(int(standing["rank"]))
            if reward != {str(k): int(v) for k, v in standing_reward.items()}:
                raise DomainSeasonRankingNotFinalizedError("domain-war ranking reward does not match frozen rules")
            _, _, _, reward_grant, reward_name, _, reward_caps = next(
                row for row in season_rules.rank_rewards if row[0] <= int(standing["rank"]) <= row[1]
            )
            reward = grant_player_reward_actual(
                connection,
                player,
                reward_totals(reward_grant),
                now_text,
                local_reputation_maximums=dict(reward_caps) or None,
            )
            reward = {key: amount for key, amount in reward.items() if amount}
            connection.execute("INSERT INTO domain_war_claims(season_id,player_id,operation_id,reward_json,claimed_at) VALUES (?, ?, ?, ?, ?)", (canonical_id, player["id"], operation_id, json.dumps(reward, sort_keys=True), now_text))
            payload = {"season_id": canonical_id, "rank": int(standing["rank"]), "reward": reward, "reward_name": reward_name}
            self._domain_insert_operation(connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text)
            return DomainFrontSeasonClaimRecord(canonical_id, reward, int(standing["rank"]), reward_name)

    def _redeem_domain_core_once(self, platform: str, platform_user_id: str, season_id: str, operation_id: str) -> DomainCoreRedeemRecord:
        operation_name = "event.redeem.domain_core"
        request_hash = self._request_hash(operation_name, {"platform": platform, "platform_user_id": platform_user_id, "season_id": season_id})
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            replay = self._domain_operation_replay(connection, operation_id, operation_name, request_hash)
            if replay is not None:
                return DomainCoreRedeemRecord(str(replay["season_id"]), str(replay["item_key"]), int(replay["quantity"]), True)
            player = self._require_player(connection, platform, platform_user_id)
            existing = connection.execute("SELECT * FROM domain_war_seasons WHERE season_id=?", (season_id,)).fetchone()
            current_rules = self._domain_season_rules(existing) if existing is not None else domain_war_season_definition(self.content)
            canonical_id, starts_at, ends_at = season_window_for_id(season_id, current_rules)
            season = self._domain_get_or_create_season(connection, canonical_id, starts_at, ends_at, now, current_rules)
            if str(season["status"]) == "collecting" and now >= ends_at:
                self._domain_freeze_season(connection, season, now)
                season = connection.execute("SELECT * FROM domain_war_seasons WHERE season_id=?", (canonical_id,)).fetchone()
            if str(season["status"]) != "frozen" or now < ends_at or now >= datetime.fromisoformat(str(season["claim_expires_at"])):
                raise DomainCoreRedeemRequirementError("domain core redemption requires a closed season")
            if connection.execute("SELECT 1 FROM domain_core_redemptions WHERE season_id=? AND player_id=?", (canonical_id, player["id"])).fetchone() is not None:
                raise DomainCoreRedeemAlreadyUsedError("domain core already redeemed")
            try:
                change_player_assets(
                    connection,
                    player,
                    {current_rules.fragment_item_key: -current_rules.fragment_quantity, current_rules.reward_item_key: current_rules.reward_quantity},
                    now_text,
                )
            except ValueError as exc:
                raise DomainCoreFragmentInsufficientError("domain core fragments are insufficient") from exc
            connection.execute("INSERT INTO domain_core_redemptions(season_id,player_id,operation_id,redeemed_at) VALUES (?, ?, ?, ?)", (canonical_id, player["id"], operation_id, now_text))
            payload = {"season_id": canonical_id, "item_key": current_rules.reward_item_key, "quantity": current_rules.reward_quantity}
            self._domain_insert_operation(connection, operation_id, operation_name, int(player["id"]), request_hash, payload, now_text)
            return DomainCoreRedeemRecord(canonical_id, current_rules.reward_item_key, current_rules.reward_quantity)

    def _domain_select_round(self, connection: Any, round_id: str | None, now: datetime) -> Any:
        if round_id:
            return connection.execute("SELECT * FROM domain_front_rounds WHERE round_id=?", (round_id,)).fetchone()
        definition = domain_front_definition(self.content)
        rid, activity_id, activity_start, activity_end, starts_at, ends_at = round_window(now, definition)
        now_text = serialize_datetime(now)
        connection.execute(
            "INSERT OR IGNORE INTO domain_front_rounds(round_id,activity_id,location_key,status,activity_starts_at,activity_ends_at,starts_at,ends_at,claim_expires_at,target_quantity,rules_snapshot_json,total_contribution,result_json,created_at,updated_at) VALUES (?, ?, ?, 'open', ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?)",
            (rid, activity_id, definition.location_key, serialize_datetime(activity_start), serialize_datetime(activity_end), serialize_datetime(starts_at), serialize_datetime(ends_at), serialize_datetime(ends_at + timedelta(days=definition.claim_days)), definition.target_quantity, json.dumps(definition.snapshot(), ensure_ascii=False, sort_keys=True), json.dumps({"success": False}, sort_keys=True), now_text, now_text),
        )
        return connection.execute("SELECT * FROM domain_front_rounds WHERE round_id=?", (rid,)).fetchone()

    def _domain_refresh_round(self, connection: Any, event: Any, now: datetime) -> Any:
        if event is None:
            raise DomainEventRoundNotActiveError("domain-front round does not exist")
        self._domain_round_rules(event)
        if str(event["status"]) in {"open", "running"} and now >= datetime.fromisoformat(str(event["ends_at"])):
            total = int(connection.execute("SELECT COALESCE(SUM(quantity),0) AS total FROM domain_front_contributions WHERE round_id=?", (event["round_id"],)).fetchone()["total"])
            winner = connection.execute("SELECT domain_key, SUM(quantity) AS score FROM domain_front_contributions WHERE round_id=? GROUP BY domain_key ORDER BY score DESC, domain_key ASC LIMIT 1", (event["round_id"],)).fetchone()
            result = self._domain_strict_object(event["result_json"])
            rules = self._domain_round_rules(event)
            result.update({"success": total >= rules.target_quantity, "winner_domain": winner["domain_key"] if winner else None, "settled_at": serialize_datetime(now)})
            connection.execute("UPDATE domain_front_rounds SET status='settled', total_contribution=?, result_json=?, updated_at=? WHERE round_id=? AND status IN ('open','running')", (total, json.dumps(result, sort_keys=True), serialize_datetime(now), event["round_id"]))
            event = connection.execute("SELECT * FROM domain_front_rounds WHERE round_id=?", (event["round_id"],)).fetchone()
        return event

    def _domain_require_open(self, event: Any, now: datetime) -> None:
        if event is None or str(event["status"]) not in {"open", "running"} or now >= datetime.fromisoformat(str(event["ends_at"])):
            raise DomainEventRoundNotActiveError("domain-front round is not active")

    @staticmethod
    def _domain_round_rules(event: Any) -> Any:
        if event is None:
            raise DomainEventRoundNotActiveError("domain-front round does not exist")
        try:
            snapshot = decode_json_strict(str(event["rules_snapshot_json"]))
        except Exception as exc:
            raise DomainEventRoundNotActiveError("domain-front round rules are invalid") from exc
        try:
            return domain_front_definition_from_snapshot(snapshot)
        except Exception as exc:
            raise DomainEventRoundNotActiveError("domain-front round rules are invalid") from exc

    def _domain_requirements(self, connection: Any, player: Any, now: datetime, rules: Any) -> tuple[Any, Any]:
        if not meets_domain_front_realm(str(player["realm_key"]), player_integer(player, "realm_layer"), rules.required_realm_rank, rules.required_realm_layer, self.content) or not player["domain_key"]:
            raise DomainEventRequirementError("domain-front requires a selected soul-transformation domain")
        crack = player["domain_crack_until"]
        if crack and now < datetime.fromisoformat(str(crack)):
            raise DomainCrackActiveError("domain crack is active")
        if str(player["location_key"]) != rules.location_key:
            raise DomainEventRequirementError("player is not at the domain front")
        membership = connection.execute("SELECT * FROM sect_members WHERE player_id=? AND status='active'", (player["id"],)).fetchone()
        if membership is None:
            raise DomainEventRequirementError("domain-front requires an active sect")
        sect = connection.execute("SELECT * FROM sects WHERE sect_id=? AND status='active'", (membership["sect_id"],)).fetchone()
        if sect is None or int(sect["level"]) < rules.sect_level_min:
            raise DomainEventRequirementError("domain-front requires the configured sect level")
        return sect, membership

    @staticmethod
    def _domain_require_participant(connection: Any, player_id: int, round_id: str) -> Any:
        row = connection.execute("SELECT * FROM domain_front_participants WHERE round_id=? AND player_id=? AND status='active'", (round_id, player_id)).fetchone()
        if row is None:
            raise DomainEventRequirementError("player has not joined this domain-front round")
        return row

    def _domain_find_source(self, connection: Any, player_id: int, round_id: str, action: str, source_operation_id: str | None, rules: Any) -> dict[str, object]:
        if action == "battle":
            query = """
                SELECT links.event_operation_id AS operation_id
                FROM domain_front_battle_links AS links
                JOIN battle_sessions AS sessions ON sessions.battle_id = links.battle_id
                WHERE links.round_id = ? AND links.player_id = ?
                  AND sessions.player_id = links.player_id
                  AND sessions.battle_type = 'pve.domain_front'
                  AND sessions.status = 'settled'
                  AND json_extract(sessions.result_json, '$.outcome') = 'won'
            """
            params: list[object] = [round_id, player_id]
            if source_operation_id:
                query += " AND links.event_operation_id=?"
                params.append(source_operation_id)
            else:
                query += " AND NOT EXISTS (SELECT 1 FROM domain_front_contributions used WHERE used.round_id=links.round_id AND used.player_id=links.player_id AND used.source_operation_id=links.event_operation_id)"
            query += " ORDER BY links.created_at DESC LIMIT 1"
            row = connection.execute(query, tuple(params)).fetchone()
            if row is not None:
                return {"source_operation_id": str(row["operation_id"]), "quantity": rules.battle_contribution}
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
                return {"source_operation_id": str(row["operation_id"]), "quantity": int(row["minutes"]) * rules.point_contribution_per_minute}
        raise DomainEventSourceInvalidError("no eligible settled domain-front source operation")

    def _domain_payload(self, connection: Any, player_id: int, event: Any) -> dict[str, object]:
        participant = connection.execute("SELECT * FROM domain_front_participants WHERE round_id=? AND player_id=?", (event["round_id"], player_id)).fetchone()
        result = self._domain_strict_object(event["result_json"])
        return {"round_id": str(event["round_id"]), "activity_id": str(event["activity_id"]), "status": str(event["status"]), "activity_starts_at": str(event["activity_starts_at"]), "activity_ends_at": str(event["activity_ends_at"]), "starts_at": str(event["starts_at"]), "ends_at": str(event["ends_at"]), "claim_expires_at": str(event["claim_expires_at"]), "total_contribution": int(event["total_contribution"]), "player_contribution": int(participant["contribution"]) if participant else 0, "participant": participant is not None and participant["status"] == "active", "sect_id": str(participant["sect_id"]) if participant else None, "domain_key": str(participant["domain_key"]) if participant else None, "winner_domain": result.get("winner_domain"), "success": result.get("success")}

    def _domain_record(self, connection: Any, player_id: int, event: Any) -> DomainFrontRecord:
        return self._domain_record_from_payload(self._domain_payload(connection, player_id, event))

    @staticmethod
    def _domain_record_from_payload(payload: dict[str, object], replay: bool = False) -> DomainFrontRecord:
        return DomainFrontRecord(str(payload["round_id"]), str(payload["activity_id"]), str(payload["status"]), str(payload["activity_starts_at"]), str(payload["activity_ends_at"]), str(payload["starts_at"]), str(payload["ends_at"]), str(payload["claim_expires_at"]), int(payload["total_contribution"]), int(payload["player_contribution"]), bool(payload["participant"]), payload.get("sect_id") and str(payload["sect_id"]), payload.get("domain_key") and str(payload["domain_key"]), payload.get("winner_domain") and str(payload["winner_domain"]), payload.get("success") if payload.get("success") is None else bool(payload["success"]), {str(k): int(v) for k, v in dict(payload.get("reward", {})).items()}, replay or bool(payload.get("idempotent_replay", False)), int(payload["quantity"]) if payload.get("quantity") is not None else None)

    def _domain_get_or_create_season(self, connection: Any, season_id: str, starts_at: datetime, ends_at: datetime, now: datetime, rules: Any) -> Any:
        now_text = serialize_datetime(now)
        connection.execute("INSERT OR IGNORE INTO domain_war_seasons(season_id,starts_at,ends_at,claim_expires_at,status,frozen_at,rules_snapshot_json,snapshot_json,created_at,updated_at) VALUES (?, ?, ?, ?, 'collecting', NULL, ?, '{}', ?, ?)", (season_id, serialize_datetime(starts_at), serialize_datetime(ends_at), serialize_datetime(claim_expiry(ends_at, rules)), json.dumps(rules.snapshot(), ensure_ascii=False, sort_keys=True), now_text, now_text))
        return connection.execute("SELECT * FROM domain_war_seasons WHERE season_id=?", (season_id,)).fetchone()

    def _domain_freeze_season(self, connection: Any, season: Any, now: datetime) -> None:
        if str(season["status"]) == "frozen":
            return
        rules = self._domain_season_rules(season)
        scores: dict[int, dict[str, object]] = {}
        rows = connection.execute("SELECT player_id, occurred_at, quantity FROM domain_front_contributions c JOIN domain_front_rounds r ON r.round_id=c.round_id WHERE r.starts_at>=? AND r.starts_at<? AND quantity>0", (season["starts_at"], season["ends_at"])).fetchall()
        for row in rows:
            entry = scores.setdefault(int(row["player_id"]), {"score": 0, "achieved_at": str(row["occurred_at"])})
            entry["score"] = int(entry["score"]) + int(row["quantity"]) * rules.domain_multiplier
            entry["achieved_at"] = min(str(entry["achieved_at"]), str(row["occurred_at"]))
        sect_rows = connection.execute("SELECT player_id, occurred_at, quantity FROM sect_contribution_events WHERE occurred_at>=? AND occurred_at<? AND quantity>0", (season["starts_at"], season["ends_at"])).fetchall()
        for row in sect_rows:
            entry = scores.setdefault(int(row["player_id"]), {"score": 0, "achieved_at": str(row["occurred_at"])})
            entry["score"] = int(entry["score"]) + int(row["quantity"]) * rules.sect_multiplier
            entry["achieved_at"] = min(str(entry["achieved_at"]), str(row["occurred_at"]))
        production_rows = connection.execute(
            "SELECT player_id, updated_at FROM production_orders "
            "WHERE status='completed' AND updated_at>=? AND updated_at<? "
            "AND (substr(recipe_key, 1, ?) = ? OR json_extract(snapshot_json,'$.realm_key') = ?)",
            (
                season["starts_at"],
                season["ends_at"],
                len(rules.production_recipe_key_prefix),
                rules.production_recipe_key_prefix,
                rules.production_snapshot_realm_key,
            ),
        ).fetchall()
        for row in production_rows:
            entry = scores.setdefault(int(row["player_id"]), {"score": 0, "achieved_at": str(row["updated_at"])})
            entry["score"] = int(entry["score"]) + rules.production_multiplier
            entry["achieved_at"] = min(str(entry["achieved_at"]), str(row["updated_at"]))
        rows = [{"player_id": player_id, **value} for player_id, value in scores.items() if int(value["score"]) > 0]
        rows.sort(key=lambda row: int(row["player_id"]), reverse=rules.identity_tiebreak == "player_id_desc")
        rows.sort(key=lambda row: str(row["achieved_at"]), reverse=rules.achieved_at_order == "desc")
        rows.sort(key=lambda row: int(row["score"]), reverse=rules.score_order == "desc")
        snapshot = []
        for rank, row in enumerate(rows[: rules.rank_limit], 1):
            reward = rules.reward_for_rank(rank)
            label = anonymous_label(str(season["season_id"]), int(row["player_id"]))
            connection.execute("INSERT OR IGNORE INTO domain_war_rankings(season_id,player_id,rank,score,achieved_at,anonymous_label,reward_json) VALUES (?, ?, ?, ?, ?, ?, ?)", (season["season_id"], row["player_id"], rank, row["score"], row["achieved_at"], label, json.dumps(reward, sort_keys=True)))
            snapshot.append({"rank": rank, "anonymous_label": label, "score": int(row["score"]), "achieved_at": str(row["achieved_at"]), "reward": reward})
        connection.execute("UPDATE domain_war_seasons SET status='frozen', frozen_at=?, snapshot_json=?, updated_at=? WHERE season_id=? AND status='collecting'", (serialize_datetime(now), json.dumps({"rules": rules.snapshot(), "standings": snapshot}, ensure_ascii=False, sort_keys=True), serialize_datetime(now), season["season_id"]))

    def _domain_season_record(self, connection: Any, player_id: int, season: Any) -> DomainFrontSeasonRecord:
        rows = connection.execute("SELECT * FROM domain_war_rankings WHERE season_id=? ORDER BY rank", (season["season_id"],)).fetchall()
        standings = tuple(DomainFrontSeasonStanding(int(row["rank"]), str(row["anonymous_label"]), int(row["score"]), str(row["achieved_at"]), self._domain_strict_object(row["reward_json"])) for row in rows)
        own_row = connection.execute("SELECT * FROM domain_war_rankings WHERE season_id=? AND player_id=?", (season["season_id"], player_id)).fetchone()
        own = DomainFrontSeasonStanding(int(own_row["rank"]), str(own_row["anonymous_label"]), int(own_row["score"]), str(own_row["achieved_at"]), self._domain_strict_object(own_row["reward_json"])) if own_row else None
        return DomainFrontSeasonRecord(str(season["season_id"]), str(season["status"]), str(season["starts_at"]), str(season["ends_at"]), str(season["claim_expires_at"]), season["frozen_at"] and str(season["frozen_at"]), standings, own)

    @staticmethod
    def _domain_season_rules(season: Any) -> Any:
        try:
            snapshot = decode_json_strict(str(season["rules_snapshot_json"]))
            return domain_war_season_definition_from_snapshot(snapshot)
        except Exception as exc:
            raise DomainSeasonRankingNotFinalizedError("domain-war season rules are invalid") from exc

    def _domain_operation_replay(self, connection: Any, operation_id: str, operation_name: str, request_hash: str) -> dict[str, object] | None:
        row = connection.execute("SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id=?", (operation_id,)).fetchone()
        if row is None:
            return None
        if str(row["operation_name"]) != operation_name or str(row["request_hash"]) != request_hash:
            raise OperationConflictError("operation id was reused with different input")
        return self._domain_strict_object(row["result_json"])

    @staticmethod
    def _domain_strict_object(value: Any) -> dict[str, object]:
        decoded = decode_json_strict(str(value))
        if not isinstance(decoded, dict):
            raise ValueError("domain-front JSON payload must be an object")
        return {str(key): item for key, item in decoded.items()}

    def _domain_insert_operation(self, connection: Any, operation_id: str, operation_name: str, player_id: int, request_hash: str, payload: dict[str, object], now_text: str) -> None:
        connection.execute("INSERT INTO operations(operation_id,operation_name,player_id,request_hash,result_json,created_at) VALUES (?, ?, ?, ?, ?, ?)", (operation_id, operation_name, player_id, request_hash, json.dumps(payload, ensure_ascii=False, sort_keys=True), now_text))

    @staticmethod
    def _domain_record_from_payload_with_reward(payload: dict[str, object]) -> DomainFrontRecord:
        return DomainFrontRepositoryMixin._domain_record_from_payload(payload)


__all__ = ["DomainFrontRepositoryMixin"]
