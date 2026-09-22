"""SQLite transactions for bounty boards and mainline adventures."""

from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
import time
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable
from uuid import uuid4

from ...contracts import PlayerView, serialize_datetime
from ..config import XiuxianSettings
from ..player.models import (
    CultivationRecord,
    IntroRecord,
    PlayerCreateRecord,
    RenameRecord,
    SeekingRecord,
    TravelRecord,
)
from ..player.rules import STAGE_MORTAL, STAGE_NEW_USER, qualification_for
from ..progression.models import (
    CultivationCancelRecord,
    CultivationRecoveryRecord,
    CultivationSessionRecord,
    CultivationSettlementRecord,
    LayerAdvanceRecord,
    LayerUnlock,
    ResourceRecoveryRecord,
)
from ..production.models import (
    ProductionOrderRecord,
    ProductionPreviewRecord,
    ProductionSettlementRecord,
)
from ..progression.breakthrough.models import (
    BreakthroughSettlementRecord,
    BreakthroughSessionRecord,
    HeartDemonResolutionRecord,
    NascentSoulPreparationRecord,
    SoulFatigueRecoveryRecord,
    WeaknessRecoveryRecord,
    DomainSelectionRecord,
)
from ..advancement.models import RetreatSessionRecord, RetreatSettlementRecord
from ..advancement.constitution_models import ConstitutionRecord
from ..advancement.talent_models import TalentNodeRecord, TalentProfileRecord
from ..advancement.skill_models import SkillMasteryRecord, SkillProfileRecord
from ..advancement.equipment_models import EquipmentRecord, RefinementRecord, TemperingRecord
from ..advancement.rules import (
    MAX_OFFLINE_SECONDS,
    MAX_SETTLEMENT_SECONDS,
    RETREAT_BASIC,
    RETREAT_RESTFUL,
    retreat_definition,
    retreat_reward,
)
from ..advancement.constitution_rules import (
    CONSTITUTION_RESET_ITEM,
    RESHAPE_COOLDOWN_SECONDS,
    constitution_definition,
)
from ..advancement.talent_rules import (
    CONTENT_VERSION as TALENT_CONTENT_VERSION,
    RULE_VERSION as TALENT_RULE_VERSION,
    TALENT_POINT_RESOURCE,
    talent_node_for_reference,
    talent_tree_nodes,
    tree_definition,
)
from ..advancement.skill_rules import (
    CONTENT_VERSION as SKILL_CONTENT_VERSION,
    MAX_SKILL_LEVEL,
    RULE_VERSION as SKILL_RULE_VERSION,
    SKILL_INSIGHT_RESOURCE,
    available_skill_keys,
    effective_skill_effect,
    skill_cost,
    skill_definition,
)
from ..advancement.equipment_rules import (
    CONTENT_VERSION as EQUIPMENT_CONTENT_VERSION,
    EQUIPMENT_DEFINITIONS,
    EQUIPMENT_ALIASES,
    MAX_TEMPER_LEVEL,
    REFINEMENT_MATERIAL,
    REFINEMENT_PITY_FAILURES,
    REFINEMENT_SUCCESS_BP,
    RULE_VERSION as EQUIPMENT_RULE_VERSION,
    TEMPER_MATERIAL,
    equipment_definition,
    refinement_affix,
    refinement_roll_bp,
    temper_cost,
    temper_roll_bp,
    temper_success_bp,
)
from ..livelihood.models import ResidenceRecord
from ..livelihood.rules import residence_definition
from ..world.models import TravelPreview, TravelSettlementRecord, TravelStartRecord
from ..world.void_models import VoidRouteSettlementRecord, VoidRouteStartRecord
from ..world.void_rules import (
    VOID_INSTABILITY_SECONDS,
    VOID_ROUTE_STORM_CHANCE_BP,
    navigation_anchor_cost,
    void_route_definition,
    void_route_roll_bp,
)
from ..progression.repository import ProgressionRepositoryMixin
from ..progression.endgame_repository import EndgameRepositoryMixin
from ..world.repository import WorldRepositoryMixin
from ..world.rules import destination_definition, meets_realm, RULE_VERSION
from ..exploration.models import ExplorationSettlementRecord, ExplorationStartRecord
from ..exploration.rules import (
    battle_roll_bp,
    exploration_definition,
    meets_realm as exploration_meets_realm,
    settlement_result,
)
from ..adventures.models import BountyAcceptRecord, BountyBoardRecord, BountyClaimRecord, BountyOfferView
from ..adventures.mainline_models import (
    MainlineClaimRecord,
    MainlineStageView,
    MainlineStartRecord,
    MainlineStatusRecord,
)
from ..adventures.mainline import (
    MAINLINE_CONTENT_VERSION,
    MAINLINE_DEFINITIONS,
    MAINLINE_LOCKED,
    MAINLINE_REWARD_PENDING,
    MAINLINE_RULE_VERSION,
    MAINLINE_STAGES,
    MAINLINE_STORY_KEY,
    mainline_definition,
    mainline_first_clear_key,
    mainline_prerequisites_met,
    mainline_reward,
    mainline_stage_status,
    resolve_mainline,
)
from ..adventures.rules import bounty_definition, DEFINITIONS as BOUNTY_DEFINITIONS, meets_realm as bounty_meets_realm, reward_map
from ..routine.models import (
    AchievementClaimRecord,
    AchievementView,
    HonorStatusRecord,
    HonorTitleEquipRecord,
    HonorTitleView,
    RedemptionCodeRecord,
    DaoContractActivationRecord,
    DaoContractClaimRecord,
    DaoContractStatusRecord,
    DaoContractView,
    FateDrawView,
    FateRollRecord,
    RoutineClaimRecord,
    WayfaringClaimRecord,
    WayfaringStatusRecord,
    SevenDayGoalRecord,
    SevenDayGoalView,
    SevenDayStatusRecord,
    SpiritTreeRecord,
)
from ..routine.wayfaring import (
    WAYFARING_CONTENT_VERSION,
    WAYFARING_DAILY_POINT_CAP,
    WAYFARING_LEVELS,
    WAYFARING_PASS_KEY,
    WAYFARING_POINTS_PER_LEVEL,
    WAYFARING_RULE_VERSION,
    WAYFARING_WEEKLY_POINT_CAP,
    wayfaring_free_reward,
    wayfaring_paid_reward,
    wayfaring_source_points,
    wayfaring_week_start,
)
from ..routine.billing import BillingReceiptError, verify_receipt
from ..routine.gacha import (
    FATE_CONTENT_VERSION,
    FATE_PITY_LIMIT,
    FATE_POOL_KEY,
    FATE_RULE_VERSION,
    FATE_SINGLE_COST,
    FATE_TEN_COST,
    FATE_TICKET,
    reward_totals,
    roll_fate_pool,
)
from ..routine.rules import (
    CHECKIN_ACTIVITY,
    CONTENT_VERSION as ROUTINE_CONTENT_VERSION,
    FATE_TICKET,
    MAKEUP_ACTIVITY,
    RULE_VERSION as ROUTINE_RULE_VERSION,
    checkin_reward,
    makeup_reward,
    parse_past_date,
    SEVEN_DAY_CONTENT_VERSION,
    SEVEN_DAY_GOALS,
    SEVEN_DAY_RULE_VERSION,
    ACHIEVEMENTS,
    HONOR_RULE_VERSION,
    HONOR_TITLES,
    achievement,
    achievement_reward,
    honor_title,
    dao_contract,
    redemption_code_hash,
    seven_day_goal,
    seven_day_reward,
    tree_harvest_reward,
    tree_status,
)

from ..persistence.errors import *  # noqa: F401,F403


class AdventuresRepositoryMixin:
    async def get_bounty_board(
        self,
        *,
        platform: str,
        platform_user_id: str,
    ) -> BountyBoardRecord:
        await self.initialize()
        return await asyncio.to_thread(self._get_bounty_board_sync, platform, platform_user_id)

    def _get_bounty_board_sync(self, platform: str, platform_user_id: str) -> BountyBoardRecord:
        now = datetime.now(timezone.utc)
        business_date = now.date().isoformat()
        with self._connect() as connection:
            row = self._require_player(connection, platform, platform_user_id, writable=False)
            accepted = connection.execute(
                "SELECT * FROM bounty_offers WHERE player_id = ? AND business_date = ?",
                (row["id"], business_date),
            ).fetchone()
            offers: list[BountyOfferView] = []
            for definition in BOUNTY_DEFINITIONS.values():
                progress = 0
                expires_at: str | None = None
                if accepted is not None and accepted["bounty_key"] == definition.key:
                    progress = self._bounty_progress(connection, row, accepted, definition)
                    expires_at = str(accepted["expires_at"])
                    if accepted["status"] == "claimed":
                        status = "claimed"
                    elif now > datetime.fromisoformat(str(accepted["expires_at"])):
                        status = "expired"
                    elif progress >= definition.target_amount:
                        status = "completed"
                    else:
                        status = "accepted"
                elif accepted is not None:
                    status = "daily_limit"
                elif definition.runtime_status != "open":
                    status = "locked"
                elif not self._bounty_player_eligible(row, definition):
                    status = "requirement"
                else:
                    status = "available"
                offers.append(
                    BountyOfferView(
                        key=definition.key,
                        label=definition.label,
                        description=definition.description,
                        status=status,
                        progress=progress,
                        target=definition.target_amount,
                        reward=reward_map(definition),
                        expires_at=expires_at,
                    )
                )
            return BountyBoardRecord(
                player=self._row_to_player(row),
                business_date=business_date,
                offers=tuple(offers),
            )

    @staticmethod
    def _bounty_player_eligible(row: sqlite3.Row | dict[str, Any], definition) -> bool:
        stage = str(row["stage"] if isinstance(row, sqlite3.Row) else row.get("stage", ""))
        if stage not in {STAGE_MORTAL, "seeker", "cultivator"}:
            return False
        realm_key = str(row["realm_key"] if isinstance(row, sqlite3.Row) else row.get("realm_key", "mortal"))
        layer = int(row["realm_layer"] if isinstance(row, sqlite3.Row) else row.get("realm_layer", 0))
        return bounty_meets_realm(realm_key, layer, definition.required_realm, definition.required_layer)

    @staticmethod
    def _bounty_progress(connection: sqlite3.Connection, row: sqlite3.Row, offer: sqlite3.Row, definition) -> int:
        snapshot = SQLitePlayerRepository._json_object(offer["snapshot_json"], {})
        if definition.target_kind == "inventory_gain":
            inventory = SQLitePlayerRepository._json_object(row["inventory_json"], {})
            current = int(inventory.get(str(definition.target_key), 0))
            baseline = int(snapshot.get("baseline_quantity", 0))
            return max(0, min(definition.target_amount, current - baseline))
        if definition.target_kind == "production_completed":
            current = connection.execute(
                "SELECT COUNT(*) AS count FROM production_orders WHERE player_id = ? AND status = 'completed'",
                (row["id"],),
            ).fetchone()
            baseline = int(snapshot.get("baseline_completed_orders", 0))
            return max(0, min(definition.target_amount, int(current["count"]) - baseline))
        result = SQLitePlayerRepository._json_object(offer["result_json"], {})
        return max(0, min(definition.target_amount, int(result.get("progress", 0))))

    async def accept_bounty(
        self,
        *,
        platform: str,
        platform_user_id: str,
        bounty_key: str,
        operation_id: str,
    ) -> BountyAcceptRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._accept_bounty_sync,
                platform,
                platform_user_id,
                bounty_key,
                operation_id,
            )

    def _accept_bounty_sync(
        self,
        platform: str,
        platform_user_id: str,
        bounty_key: str,
        operation_id: str,
    ) -> BountyAcceptRecord:
        definition = bounty_definition(bounty_key)
        operation_name = "bounty.accept"
        request_payload = {
            "platform": platform,
            "platform_user_id": platform_user_id,
            "bounty_key": definition.key,
        }
        request_hash = self._request_hash(operation_name, request_payload)
        now = datetime.now(timezone.utc)
        business_date = now.date().isoformat()
        starts_at = serialize_datetime(now)
        expires_at = serialize_datetime(now + timedelta(seconds=definition.duration_seconds))
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            if existing is not None:
                if existing["operation_name"] != operation_name or existing["request_hash"] != request_hash:
                    raise OperationConflictError("operation input differs from its original request")
                return self._bounty_accept_from_payload(json.loads(existing["result_json"]), replay=True)
            row = self._require_player(connection, platform, platform_user_id)
            if definition.runtime_status != "open":
                raise BountyContentClosedError("bounty runtime is closed")
            if not self._bounty_player_eligible(row, definition):
                raise BountyRequirementError("bounty requirements are not met")
            accepted = connection.execute(
                "SELECT 1 FROM bounty_offers WHERE player_id = ? AND business_date = ? LIMIT 1",
                (row["id"], business_date),
            ).fetchone()
            if accepted is not None:
                raise BountyDailyLimitError("player already accepted a bounty today")
            inventory = self._json_object(row["inventory_json"], {})
            completed_orders = connection.execute(
                "SELECT COUNT(*) AS count FROM production_orders WHERE player_id = ? AND status = 'completed'",
                (row["id"],),
            ).fetchone()
            snapshot = {
                "bounty_key": definition.key,
                "content_version": definition.content_version,
                "rule_version": definition.rule_version,
                "target_kind": definition.target_kind,
                "target_key": definition.target_key,
                "target_amount": definition.target_amount,
                "baseline_quantity": int(inventory.get(str(definition.target_key), 0)) if definition.target_key else 0,
                "baseline_completed_orders": int(completed_orders["count"]),
            }
            offer_id = uuid4().hex
            connection.execute(
                """
                INSERT INTO bounty_offers(
                    offer_id, player_id, operation_id, bounty_key, business_date, status,
                    accepted_at, expires_at, snapshot_json, result_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'accepted', ?, ?, ?, '{}', ?, ?)
                """,
                (
                    offer_id,
                    row["id"],
                    operation_id,
                    definition.key,
                    business_date,
                    starts_at,
                    expires_at,
                    json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
                    starts_at,
                    starts_at,
                ),
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (row["id"],)).fetchone()
            player = self._row_to_player(updated)
            payload = {
                "player": self._player_payload(player),
                "bounty_key": definition.key,
                "label": definition.label,
                "status": "accepted",
                "progress": 0,
                "target": definition.target_amount,
                "starts_at": starts_at,
                "expires_at": expires_at,
            }
            connection.execute(
                "INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    operation_id,
                    operation_name,
                    row["id"],
                    request_hash,
                    json.dumps(payload, ensure_ascii=False, sort_keys=True),
                    starts_at,
                ),
            )
            return self._bounty_accept_from_payload(payload)

    @staticmethod
    def _bounty_accept_from_payload(payload: dict[str, Any], replay: bool = False) -> BountyAcceptRecord:
        return BountyAcceptRecord(
            player=SQLitePlayerRepository._row_to_player(payload["player"]),
            bounty_key=str(payload["bounty_key"]),
            label=str(payload["label"]),
            status=str(payload["status"]),
            progress=int(payload.get("progress", 0)),
            target=int(payload["target"]),
            starts_at=str(payload["starts_at"]),
            expires_at=str(payload["expires_at"]),
            already_completed=replay,
        )
    async def claim_bounty(
        self,
        *,
        platform: str,
        platform_user_id: str,
        operation_id: str,
    ) -> BountyClaimRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._claim_bounty_sync,
                platform,
                platform_user_id,
                operation_id,
            )

    def _claim_bounty_sync(self, platform: str, platform_user_id: str, operation_id: str) -> BountyClaimRecord:
        operation_name = "bounty.claim"
        request_payload = {"platform": platform, "platform_user_id": platform_user_id}
        request_hash = self._request_hash(operation_name, request_payload)
        now = datetime.now(timezone.utc)
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
                return self._bounty_claim_from_payload(json.loads(existing["result_json"]), replay=True)
            row = self._require_player(connection, platform, platform_user_id)
            offer = connection.execute(
                "SELECT * FROM bounty_offers WHERE player_id = ? AND status IN ('accepted', 'completed') ORDER BY id DESC LIMIT 1",
                (row["id"],),
            ).fetchone()
            if offer is None:
                claimed = connection.execute(
                    "SELECT 1 FROM bounty_offers WHERE player_id = ? AND status = 'claimed' ORDER BY id DESC LIMIT 1",
                    (row["id"],),
                ).fetchone()
                if claimed is not None:
                    raise BountyAlreadyClaimedError("bounty reward was already claimed")
                raise BountyNotFoundError("no bounty is waiting for a claim")
            definition = bounty_definition(str(offer["bounty_key"]))
            progress = self._bounty_progress(connection, row, offer, definition)
            if now > datetime.fromisoformat(str(offer["expires_at"])):
                connection.execute(
                    "UPDATE bounty_offers SET status = 'expired', result_json = ?, updated_at = ? WHERE id = ? AND status IN ('accepted', 'completed')",
                    (
                        json.dumps({"status": "expired", "progress": progress}, ensure_ascii=False, sort_keys=True),
                        now_text,
                        offer["id"],
                    ),
                )
                connection.commit()
                raise BountyExpiredError("bounty has expired")
            if progress < definition.target_amount:
                raise BountyIncompleteError("bounty target is incomplete")

            inventory = self._json_object(row["inventory_json"], {})
            stones = int(row["spirit_stones"])
            cultivation = int(row["cultivation"])
            total_cultivation = int(row["total_cultivation"])
            energy = int(row["energy"])
            rewards = reward_map(definition)
            actual_rewards: dict[str, int] = {}
            local_reputation = 0
            service_reputation = 0
            for key, quantity in rewards.items():
                quantity = int(quantity)
                if key == "spirit_stones":
                    stones += quantity
                    actual_rewards[key] = quantity
                elif key == "cultivation":
                    cultivation += quantity
                    total_cultivation += quantity
                    actual_rewards[key] = quantity
                elif key == "energy":
                    gained = min(quantity, max(0, int(row["energy_max"]) - energy))
                    energy += gained
                    actual_rewards[key] = gained
                elif key == "local_reputation":
                    local_reputation += quantity
                    actual_rewards[key] = quantity
                elif key == "service_reputation":
                    service_reputation += quantity
                    actual_rewards[key] = quantity
                else:
                    inventory[key] = int(inventory.get(key, 0)) + quantity
                    actual_rewards[key] = quantity

            reputation = connection.execute(
                "SELECT local_json, service_reputation FROM player_reputations WHERE player_id = ?",
                (row["id"],),
            ).fetchone()
            local = self._json_object(reputation["local_json"], {}) if reputation is not None else {}
            local["local.xuantian.new_town"] = int(local.get("local.xuantian.new_town", 0)) + local_reputation
            current_service = int(reputation["service_reputation"]) if reputation is not None else 0
            current_service = min(100, current_service + service_reputation)
            connection.execute(
                """
                INSERT INTO player_reputations(player_id, local_json, service_reputation, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(player_id) DO UPDATE SET local_json = excluded.local_json,
                    service_reputation = excluded.service_reputation, updated_at = excluded.updated_at
                """,
                (row["id"], json.dumps(local, ensure_ascii=False, sort_keys=True), current_service, now_text),
            )
            connection.execute(
                """
                UPDATE players
                SET spirit_stones = ?, cultivation = ?, total_cultivation = ?, energy = ?,
                    inventory_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    stones,
                    cultivation,
                    total_cultivation,
                    energy,
                    json.dumps(inventory, ensure_ascii=False, sort_keys=True),
                    now_text,
                    row["id"],
                ),
            )
            result_json = {
                "status": "claimed",
                "progress": progress,
                "target": definition.target_amount,
                "rewards": actual_rewards,
            }
            connection.execute(
                "UPDATE bounty_offers SET status = 'claimed', result_json = ?, updated_at = ? WHERE id = ? AND status IN ('accepted', 'completed')",
                (json.dumps(result_json, ensure_ascii=False, sort_keys=True), now_text, offer["id"]),
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (row["id"],)).fetchone()
            player = self._row_to_player(updated)
            payload = {
                "player": self._player_payload(player),
                "bounty_key": definition.key,
                "label": definition.label,
                "status": "claimed",
                "progress": progress,
                "target": definition.target_amount,
                "rewards": actual_rewards,
            }
            connection.execute(
                "INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    operation_id,
                    operation_name,
                    row["id"],
                    request_hash,
                    json.dumps(payload, ensure_ascii=False, sort_keys=True),
                    now_text,
                ),
            )
            return self._bounty_claim_from_payload(payload)

    @staticmethod
    def _bounty_claim_from_payload(payload: dict[str, Any], replay: bool = False) -> BountyClaimRecord:
        return BountyClaimRecord(
            player=SQLitePlayerRepository._row_to_player(payload["player"]),
            bounty_key=str(payload["bounty_key"]),
            label=str(payload["label"]),
            status=str(payload["status"]),
            progress=int(payload.get("progress", 0)),
            target=int(payload["target"]),
            rewards={str(key): int(value) for key, value in dict(payload.get("rewards", {})).items()},
            already_completed=replay,
        )
    async def get_mainline_status(
        self,
        *,
        platform: str,
        platform_user_id: str,
    ) -> MainlineStatusRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._get_mainline_status_sync,
                platform,
                platform_user_id,
            )

    def _get_mainline_status_sync(
        self,
        platform: str,
        platform_user_id: str,
    ) -> MainlineStatusRecord:
        with self._connect() as connection:
            row = self._require_player(connection, platform, platform_user_id, writable=False)
            return self._mainline_status_from_connection(connection, row)

    @staticmethod
    def _mainline_status_from_connection(
        connection: sqlite3.Connection,
        player: sqlite3.Row,
        *,
        replay: bool = False,
    ) -> MainlineStatusRecord:
        runs = {
            str(item["stage_key"]): item
            for item in connection.execute(
                "SELECT * FROM mainline_runs WHERE player_id = ? AND story_key = ?",
                (player["id"], MAINLINE_STORY_KEY),
            ).fetchall()
        }
        completed_stages = {
            str(item["stage_key"])
            for item in runs.values()
            if bool(item["first_clear_claimed"])
        }
        intro_state = SQLitePlayerRepository._json_object(player["intro_json"], {})
        flags = {str(item) for item in intro_state.get("flags", [])}
        completed_events = {"player.start_seeking"} if str(player["stage"]) != STAGE_NEW_USER else set()
        views: list[MainlineStageView] = []
        for definition in MAINLINE_STAGES:
            run = runs.get(definition.key)
            prerequisites_met = mainline_prerequisites_met(
                definition,
                completed_stages=completed_stages,
                completed_events=completed_events,
                flags=flags,
                realm_key=str(player["realm_key"]),
                realm_layer=int(player["realm_layer"]),
            )
            run_status = str(run["status"]) if run is not None else ""
            status = mainline_stage_status(
                definition,
                prerequisites_met=prerequisites_met,
                running=run_status == "running",
                cleared=run_status == "cleared",
                reward_pending=run_status == MAINLINE_REWARD_PENDING,
                claimed=run_status == "claimed",
            )
            views.append(
                MainlineStageView(
                    key=definition.key,
                    story_key=definition.story_key,
                    chapter=definition.chapter,
                    stage=definition.stage,
                    label=definition.label,
                    description=definition.description,
                    status=status,
                    first_clear_reward=definition.first_clear_reward_map(),
                    repeat_reward=definition.repeat_reward_map(),
                    completed=bool(run and run["status"] in {"cleared", "reward_pending", "claimed"}),
                    claimed=bool(run and run["status"] == "claimed"),
                )
            )
        current = next((item for item in views if not item.claimed), views[-1])
        overall = current.status
        if any(item.status == "running" for item in views):
            overall = "running"
        elif any(item.status == MAINLINE_REWARD_PENDING for item in views):
            overall = MAINLINE_REWARD_PENDING
        return MainlineStatusRecord(
            player=SQLitePlayerRepository._row_to_player(player),
            story_key=MAINLINE_STORY_KEY,
            chapter=current.chapter,
            current_stage=current.stage,
            status=overall,
            stages=tuple(views),
            content_version=MAINLINE_CONTENT_VERSION,
            rule_version=MAINLINE_RULE_VERSION,
            already_completed=replay,
        )

    async def start_mainline(
        self,
        *,
        platform: str,
        platform_user_id: str,
        stage_key: str,
        operation_id: str,
    ) -> MainlineStartRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._start_mainline_sync,
                platform,
                platform_user_id,
                stage_key,
                operation_id,
            )

    def _start_mainline_sync(
        self,
        platform: str,
        platform_user_id: str,
        stage_key: str,
        operation_id: str,
    ) -> MainlineStartRecord:
        last_error: Exception | None = None
        for attempt in range(5):
            try:
                return self._start_mainline_once(
                    platform,
                    platform_user_id,
                    stage_key,
                    operation_id,
                )
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).lower():
                    raise
                if attempt == 4:
                    raise RepositoryBusyError("database remained locked") from exc
                last_error = exc
                time.sleep(0.01 * (2**attempt))
        raise RepositoryBusyError("database remained locked") from last_error

    def _start_mainline_once(
        self,
        platform: str,
        platform_user_id: str,
        stage_key: str,
        operation_id: str,
    ) -> MainlineStartRecord:
        definition = mainline_definition(stage_key)
        operation_name = "mainline.start_stage"
        request_hash = self._request_hash(
            operation_name,
            {
                "platform": platform,
                "platform_user_id": platform_user_id,
                "stage_key": definition.key,
                "content_version": definition.content_version,
                "rule_version": definition.rule_version,
            },
        )
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            if existing is not None:
                if existing["operation_name"] != operation_name or existing["request_hash"] != request_hash:
                    raise OperationConflictError("operation input differs from its original request")
                return self._mainline_start_from_payload(
                    json.loads(existing["result_json"]), replay=True
                )
            if definition.runtime_status != "open":
                raise MainlineContentClosedError("mainline stage is not open")
            row = self._require_player(connection, platform, platform_user_id)
            status_record = self._mainline_status_from_connection(connection, row)
            stage_view = next(item for item in status_record.stages if item.key == definition.key)
            if not mainline_prerequisites_met(
                definition,
                completed_stages={
                    item.key for item in status_record.stages if item.completed
                },
                completed_events=(
                    {"player.start_seeking"}
                    if str(row["stage"]) != STAGE_NEW_USER
                    else set()
                ),
                flags=SQLitePlayerRepository._json_object(row["intro_json"], {}).get("flags", []),
                realm_key=str(row["realm_key"]),
                realm_layer=int(row["realm_layer"]),
            ):
                raise MainlineRequirementError("mainline prerequisites are not met")
            run = connection.execute(
                "SELECT * FROM mainline_runs WHERE player_id = ? AND story_key = ? AND stage_key = ?",
                (row["id"], MAINLINE_STORY_KEY, definition.key),
            ).fetchone()
            if run is not None and str(run["status"]) == "running":
                raise MainlineAlreadyRunningError("mainline stage is already running")
            first_key = (
                str(run["first_clear_key"])
                if run is not None
                else mainline_first_clear_key(definition.chapter, definition.stage, str(row["player_id"]))
            )
            snapshot = {
                "stage": str(row["stage"]),
                "realm_key": str(row["realm_key"]),
                "realm_layer": int(row["realm_layer"]),
                "location_key": str(row["location_key"]),
                "intro_flags": list(SQLitePlayerRepository._json_object(row["intro_json"], {}).get("flags", [])),
                "content_version": definition.content_version,
                "rule_version": definition.rule_version,
            }
            if run is None:
                connection.execute(
                    """
                    INSERT INTO mainline_runs(
                        player_id, story_key, chapter, stage, stage_key, status,
                        attempt_count, first_clear_claimed, first_clear_key,
                        start_operation_id, snapshot_json, content_version, rule_version,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, 'running', 1, 0, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row["id"], MAINLINE_STORY_KEY, definition.chapter, definition.stage,
                        definition.key, first_key, operation_id,
                        json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
                        definition.content_version, definition.rule_version, now_text, now_text,
                    ),
                )
                first_clear = True
            else:
                connection.execute(
                    """
                    UPDATE mainline_runs
                    SET status = 'running', attempt_count = attempt_count + 1,
                        start_operation_id = ?, claim_operation_id = NULL,
                        snapshot_json = ?, result_json = '{}', updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        operation_id,
                        json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
                        now_text,
                        run["id"],
                    ),
                )
                first_clear = not bool(run["first_clear_claimed"])
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (row["id"],)).fetchone()
            if updated is None:
                raise RuntimeError("mainline start returned no player")
            payload = {
                "player": self._player_payload(self._row_to_player(updated)),
                "story_key": MAINLINE_STORY_KEY,
                "chapter": definition.chapter,
                "stage": definition.stage,
                "stage_key": definition.key,
                "status": "running",
                "first_clear": first_clear,
                "label": definition.label,
                "description": definition.description,
                "content_version": definition.content_version,
                "rule_version": definition.rule_version,
            }
            connection.execute(
                """
                INSERT INTO operations(
                    operation_id, operation_name, player_id, request_hash, result_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    operation_id, operation_name, row["id"], request_hash,
                    json.dumps(payload, ensure_ascii=False, sort_keys=True), now_text,
                ),
            )
            return self._mainline_start_from_payload(payload)

    async def claim_mainline(
        self,
        *,
        platform: str,
        platform_user_id: str,
        stage_key: str,
        operation_id: str,
    ) -> MainlineClaimRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._claim_mainline_sync,
                platform,
                platform_user_id,
                stage_key,
                operation_id,
            )

    def _claim_mainline_sync(
        self,
        platform: str,
        platform_user_id: str,
        stage_key: str,
        operation_id: str,
    ) -> MainlineClaimRecord:
        last_error: Exception | None = None
        for attempt in range(5):
            try:
                return self._claim_mainline_once(
                    platform,
                    platform_user_id,
                    stage_key,
                    operation_id,
                )
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).lower():
                    raise
                if attempt == 4:
                    raise RepositoryBusyError("database remained locked") from exc
                last_error = exc
                time.sleep(0.01 * (2**attempt))
        raise RepositoryBusyError("database remained locked") from last_error

    def _claim_mainline_once(
        self,
        platform: str,
        platform_user_id: str,
        stage_key: str,
        operation_id: str,
    ) -> MainlineClaimRecord:
        definition = mainline_definition(stage_key)
        operation_name = "mainline.claim_first_clear"
        request_hash = self._request_hash(
            operation_name,
            {
                "platform": platform,
                "platform_user_id": platform_user_id,
                "stage_key": definition.key,
                "content_version": definition.content_version,
                "rule_version": definition.rule_version,
            },
        )
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            if existing is not None:
                if existing["operation_name"] != operation_name or existing["request_hash"] != request_hash:
                    raise OperationConflictError("operation input differs from its original request")
                return self._mainline_claim_from_payload(
                    json.loads(existing["result_json"]), replay=True
                )
            if definition.runtime_status != "open":
                raise MainlineContentClosedError("mainline stage is not open")
            row = self._require_player(connection, platform, platform_user_id)
            run = connection.execute(
                "SELECT * FROM mainline_runs WHERE player_id = ? AND story_key = ? AND stage_key = ?",
                (row["id"], MAINLINE_STORY_KEY, definition.key),
            ).fetchone()
            if run is None or str(run["status"]) != "running":
                raise MainlineNotStartedError("mainline stage has not been started")
            first_clear = not bool(run["first_clear_claimed"])
            reward = mainline_reward(definition, first_clear=first_clear)
            connection.execute(
                "UPDATE mainline_runs SET status = ?, updated_at = ? WHERE id = ?",
                (MAINLINE_REWARD_PENDING, now_text, run["id"]),
            )
            actual_reward = self._apply_mainline_reward(
                connection,
                row,
                reward,
                operation_id,
                now_text,
                definition,
            )
            result = {
                "status": "claimed",
                "reward": actual_reward,
                "first_clear": first_clear,
                "stage_key": definition.key,
            }
            connection.execute(
                """
                UPDATE mainline_runs
                SET status = 'claimed', first_clear_claimed = CASE WHEN ? THEN 1 ELSE first_clear_claimed END,
                    claim_operation_id = ?, result_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    1 if first_clear else 0,
                    operation_id,
                    json.dumps(result, ensure_ascii=False, sort_keys=True),
                    now_text,
                    run["id"],
                ),
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (row["id"],)).fetchone()
            if updated is None:
                raise RuntimeError("mainline claim returned no player")
            payload = {
                "player": self._player_payload(self._row_to_player(updated)),
                "story_key": MAINLINE_STORY_KEY,
                "chapter": definition.chapter,
                "stage": definition.stage,
                "stage_key": definition.key,
                "status": "claimed",
                "reward": actual_reward,
                "first_clear": first_clear,
                "label": definition.label,
                "source_operation_id": operation_id,
                "content_version": definition.content_version,
                "rule_version": definition.rule_version,
            }
            connection.execute(
                """
                INSERT INTO operations(
                    operation_id, operation_name, player_id, request_hash, result_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    operation_id, operation_name, row["id"], request_hash,
                    json.dumps(payload, ensure_ascii=False, sort_keys=True), now_text,
                ),
            )
            return self._mainline_claim_from_payload(payload)

    @staticmethod
    def _apply_mainline_reward(
        connection: sqlite3.Connection,
        player: sqlite3.Row,
        reward: dict[str, int | str],
        operation_id: str,
        now_text: str,
        definition: Any,
    ) -> dict[str, int | str]:
        inventory = SQLitePlayerRepository._json_object(player["inventory_json"], {})
        stones = int(player["spirit_stones"])
        local_delta = 0
        service_delta = 0
        actual: dict[str, int | str] = {}
        event_keys: list[str] = [
            f"{definition.story_key}:chapter.{definition.chapter}.stage.{definition.stage}"
        ]
        for key, raw_value in reward.items():
            key = str(key)
            if key == "spirit_stones":
                quantity = int(raw_value)
                stones += quantity
                actual[key] = quantity
            elif key == "local_reputation":
                local_delta += int(raw_value)
                actual[key] = int(raw_value)
            elif key == "service_reputation":
                service_delta += int(raw_value)
                actual[key] = int(raw_value)
            elif key == "title_key":
                title_key = str(raw_value)
                title = honor_title(title_key)
                if title.closed:
                    raise MainlineContentClosedError("mainline title is not open")
                connection.execute(
                    """
                    INSERT OR IGNORE INTO honor_titles(
                        player_id, title_key, source_operation_id, acquired_at,
                        content_version, rule_version
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        player["id"], title_key, operation_id, now_text,
                        MAINLINE_CONTENT_VERSION, MAINLINE_RULE_VERSION,
                    ),
                )
                actual[key] = title_key
            elif key.startswith("item."):
                quantity = int(raw_value)
                inventory[key] = int(inventory.get(key, 0)) + quantity
                actual[key] = quantity
            elif key.startswith("access.") or key.startswith("codex."):
                quantity = int(raw_value)
                actual[key] = quantity
                event_keys.append(key)
            else:
                raise ValueError(f"unsupported mainline reward: {key}")
        if local_delta or service_delta:
            reputation = connection.execute(
                "SELECT local_json, service_reputation FROM player_reputations WHERE player_id = ?",
                (player["id"],),
            ).fetchone()
            local = SQLitePlayerRepository._json_object(reputation["local_json"], {}) if reputation else {}
            local["local.xuantian.new_town"] = int(local.get("local.xuantian.new_town", 0)) + local_delta
            service = int(reputation["service_reputation"]) if reputation else 0
            service = min(100, service + service_delta)
            connection.execute(
                """
                INSERT INTO player_reputations(player_id, local_json, service_reputation, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(player_id) DO UPDATE SET local_json = excluded.local_json,
                    service_reputation = excluded.service_reputation, updated_at = excluded.updated_at
                """,
                (player["id"], json.dumps(local, ensure_ascii=False, sort_keys=True), service, now_text),
            )
        connection.execute(
            "UPDATE players SET spirit_stones = ?, inventory_json = ?, updated_at = ? WHERE id = ?",
            (stones, json.dumps(inventory, ensure_ascii=False, sort_keys=True), now_text, player["id"]),
        )
        for event_key in event_keys:
            connection.execute(
                """
                INSERT OR IGNORE INTO activity_events(
                    player_id, event_key, source_operation_id, occurred_at, payload_json
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    player["id"], event_key, operation_id, now_text,
                    json.dumps({"stage_key": definition.key}, ensure_ascii=False, sort_keys=True),
                ),
            )
        return actual

    @staticmethod
    def _mainline_start_from_payload(
        payload: dict[str, Any], replay: bool = False
    ) -> MainlineStartRecord:
        return MainlineStartRecord(
            player=SQLitePlayerRepository._row_to_player(payload["player"]),
            story_key=str(payload["story_key"]),
            chapter=int(payload["chapter"]),
            stage=int(payload["stage"]),
            stage_key=str(payload["stage_key"]),
            status=str(payload["status"]),
            first_clear=bool(payload.get("first_clear", True)),
            label=str(payload.get("label", "")),
            description=str(payload.get("description", "")),
            already_completed=replay,
        )

    @staticmethod
    def _mainline_claim_from_payload(
        payload: dict[str, Any], replay: bool = False
    ) -> MainlineClaimRecord:
        return MainlineClaimRecord(
            player=SQLitePlayerRepository._row_to_player(payload["player"]),
            story_key=str(payload["story_key"]),
            chapter=int(payload["chapter"]),
            stage=int(payload["stage"]),
            stage_key=str(payload["stage_key"]),
            status=str(payload["status"]),
            reward=dict(payload.get("reward", {})),
            first_clear=bool(payload.get("first_clear", True)),
            label=str(payload.get("label", "")),
            source_operation_id=payload.get("source_operation_id"),
            already_completed=replay,
        )
