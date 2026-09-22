"""SQLite transactions for routine and live-service progression.

The mixin is composed into :class:`SQLitePlayerRepository`.  The temporary
``SQLitePlayerRepository`` module global is bound by the composition root after
the concrete class is defined; this keeps replay helpers compatible while the
legacy repository is being decomposed.
"""

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


class RoutineRepositoryMixin:
    async def claim_daily(
        self,
        *,
        platform: str,
        platform_user_id: str,
        operation_id: str,
    ) -> RoutineClaimRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._claim_daily_sync, platform, platform_user_id, operation_id
            )

    def _claim_daily_sync(
        self, platform: str, platform_user_id: str, operation_id: str
    ) -> RoutineClaimRecord:
        operation_name = "routine.checkin.daily"
        request_payload = {
            "platform": platform,
            "platform_user_id": platform_user_id,
            "content_version": ROUTINE_CONTENT_VERSION,
            "rule_version": ROUTINE_RULE_VERSION,
        }
        request_hash = self._request_hash(operation_name, request_payload)
        for attempt in range(5):
            try:
                return self._claim_daily_once(
                    platform,
                    platform_user_id,
                    operation_id,
                    operation_name,
                    request_hash,
                )
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).lower():
                    raise
                if attempt == 4:
                    raise RepositoryBusyError("database remained locked") from exc
                time.sleep(0.01 * (2**attempt))
        raise RepositoryBusyError("database remained locked")

    def _claim_daily_once(
        self,
        platform: str,
        platform_user_id: str,
        operation_id: str,
        operation_name: str,
        request_hash: str,
    ) -> RoutineClaimRecord:
        now = self._now()
        today = now.date()
        target_date = today.isoformat()
        month_key = today.strftime("%Y-%m")
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
                return self._routine_claim_from_payload(
                    json.loads(existing["result_json"]), replay=True
                )

            row = self._require_player(connection, platform, platform_user_id)
            duplicate = connection.execute(
                "SELECT 1 FROM routine_checkins WHERE player_id = ? AND target_date = ? LIMIT 1",
                (row["id"], target_date),
            ).fetchone()
            if duplicate is not None:
                raise CheckinAlreadyClaimedError("daily check-in already claimed")

            previous = connection.execute(
                "SELECT target_date FROM routine_checkins "
                "WHERE player_id = ? AND claim_kind = 'daily' AND target_date < ? "
                "ORDER BY target_date DESC",
                (row["id"], target_date),
            ).fetchall()
            previous_dates = {str(item["target_date"]) for item in previous}
            streak_before = 0
            cursor = today - timedelta(days=1)
            while cursor.isoformat() in previous_dates:
                streak_before += 1
                cursor -= timedelta(days=1)
            streak_after = streak_before + 1
            requested_reward = checkin_reward(streak_after)
            inventory = self._json_object(row["inventory_json"], {})
            stones = int(row["spirit_stones"]) + int(requested_reward.get("spirit_stones", 0))
            current_energy = int(row["energy"])
            energy_gain = min(
                int(requested_reward.get("energy", 0)),
                max(0, int(row["energy_max"]) - current_energy),
            )
            energy = current_energy + energy_gain
            applied_reward: dict[str, int] = {"spirit_stones": int(requested_reward.get("spirit_stones", 0))}
            applied_reward["energy"] = energy_gain
            for key, quantity in requested_reward.items():
                if key in {"spirit_stones", "energy"}:
                    continue
                inventory[key] = int(inventory.get(key, 0)) + int(quantity)
                applied_reward[key] = int(quantity)

            connection.execute(
                "UPDATE players SET spirit_stones = ?, energy = ?, inventory_json = ?, updated_at = ? WHERE id = ?",
                (stones, energy, json.dumps(inventory, ensure_ascii=False, sort_keys=True), now_text, row["id"]),
            )
            connection.execute(
                """
                INSERT INTO routine_checkins(
                    player_id, activity_key, target_date, claim_kind, month_key, operation_id,
                    status, cost_json, reward_json, streak_before, streak_after,
                    content_version, rule_version, created_at, settled_at
                ) VALUES (?, ?, ?, 'daily', ?, ?, 'claimed', '{}', ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["id"], CHECKIN_ACTIVITY, target_date, month_key, operation_id,
                    json.dumps(applied_reward, ensure_ascii=False, sort_keys=True),
                    streak_before, streak_after, ROUTINE_CONTENT_VERSION, ROUTINE_RULE_VERSION,
                    now_text, now_text,
                ),
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (row["id"],)).fetchone()
            if updated is None:
                raise RuntimeError("daily check-in returned no player")
            payload = {
                "player": self._player_payload(self._row_to_player(updated)),
                "activity_key": CHECKIN_ACTIVITY,
                "target_date": target_date,
                "reward": applied_reward,
                "requested_reward": requested_reward,
                "energy_spent": 0,
                "consecutive_days": streak_after,
                "streak_before": streak_before,
                "makeup": False,
                "content_version": ROUTINE_CONTENT_VERSION,
                "rule_version": ROUTINE_RULE_VERSION,
            }
            connection.execute(
                "INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    operation_id, operation_name, row["id"], request_hash,
                    json.dumps(payload, ensure_ascii=False, sort_keys=True), now_text,
                ),
            )
            return self._routine_claim_from_payload(payload)

    async def makeup_daily(
        self,
        *,
        platform: str,
        platform_user_id: str,
        target_date: str,
        operation_id: str,
    ) -> RoutineClaimRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._makeup_daily_sync,
                platform,
                platform_user_id,
                target_date,
                operation_id,
            )

    def _makeup_daily_sync(
        self, platform: str, platform_user_id: str, target_date: str, operation_id: str
    ) -> RoutineClaimRecord:
        operation_name = "routine.makeup.daily"
        request_payload = {
            "platform": platform,
            "platform_user_id": platform_user_id,
            "target_date": target_date,
            "content_version": ROUTINE_CONTENT_VERSION,
            "rule_version": ROUTINE_RULE_VERSION,
        }
        request_hash = self._request_hash(operation_name, request_payload)
        for attempt in range(5):
            try:
                return self._makeup_daily_once(
                    platform,
                    platform_user_id,
                    target_date,
                    operation_id,
                    operation_name,
                    request_hash,
                )
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).lower():
                    raise
                if attempt == 4:
                    raise RepositoryBusyError("database remained locked") from exc
                time.sleep(0.01 * (2**attempt))
        raise RepositoryBusyError("database remained locked")

    def _makeup_daily_once(
        self,
        platform: str,
        platform_user_id: str,
        target_date: str,
        operation_id: str,
        operation_name: str,
        request_hash: str,
    ) -> RoutineClaimRecord:
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
                return self._routine_claim_from_payload(
                    json.loads(existing["result_json"]), replay=True
                )

            try:
                parsed_target = parse_past_date(target_date, now.date())
            except ValueError as exc:
                raise RoutineMakeupDateError(str(exc)) from exc
            canonical_target = parsed_target.isoformat()
            month_key = now.date().strftime("%Y-%m")
            row = self._require_player(connection, platform, platform_user_id)
            duplicate = connection.execute(
                "SELECT 1 FROM routine_checkins WHERE player_id = ? AND target_date = ? LIMIT 1",
                (row["id"], canonical_target),
            ).fetchone()
            if duplicate is not None:
                raise RoutineMakeupNotEligibleError("date was already claimed")
            used = connection.execute(
                "SELECT COUNT(*) AS count FROM routine_checkins WHERE player_id = ? AND claim_kind = 'makeup' AND month_key = ?",
                (row["id"], month_key),
            ).fetchone()
            if int(used["count"]) >= 2:
                raise RoutineMakeupLimitError("monthly makeup limit reached")
            if int(row["spirit_stones"]) < 30:
                raise CurrencyInsufficientError("makeup requires 30 spirit stones")

            requested_reward = makeup_reward()
            current_energy = int(row["energy"])
            energy_gain = min(
                int(requested_reward.get("energy", 0)),
                max(0, int(row["energy_max"]) - current_energy),
            )
            applied_reward = {
                "spirit_stones": int(requested_reward.get("spirit_stones", 0)),
                "energy": energy_gain,
            }
            stones = int(row["spirit_stones"]) - 30 + applied_reward["spirit_stones"]
            connection.execute(
                "UPDATE players SET spirit_stones = ?, energy = ?, updated_at = ? WHERE id = ?",
                (stones, current_energy + energy_gain, now_text, row["id"]),
            )
            connection.execute(
                """
                INSERT INTO routine_checkins(
                    player_id, activity_key, target_date, claim_kind, month_key, operation_id,
                    status, cost_json, reward_json, streak_before, streak_after,
                    content_version, rule_version, created_at, settled_at
                ) VALUES (?, ?, ?, 'makeup', ?, ?, 'claimed', ?, ?, 0, 0, ?, ?, ?, ?)
                """,
                (
                    row["id"], MAKEUP_ACTIVITY, canonical_target, month_key, operation_id,
                    json.dumps({"spirit_stones": 30}, ensure_ascii=False, sort_keys=True),
                    json.dumps(applied_reward, ensure_ascii=False, sort_keys=True),
                    ROUTINE_CONTENT_VERSION, ROUTINE_RULE_VERSION, now_text, now_text,
                ),
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (row["id"],)).fetchone()
            if updated is None:
                raise RuntimeError("makeup check-in returned no player")
            payload = {
                "player": self._player_payload(self._row_to_player(updated)),
                "activity_key": MAKEUP_ACTIVITY,
                "target_date": canonical_target,
                "reward": applied_reward,
                "requested_reward": requested_reward,
                "energy_spent": 0,
                "spirit_stones_spent": 30,
                "consecutive_days": 0,
                "streak_before": 0,
                "makeup": True,
                "content_version": ROUTINE_CONTENT_VERSION,
                "rule_version": ROUTINE_RULE_VERSION,
            }
            connection.execute(
                "INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    operation_id, operation_name, row["id"], request_hash,
                    json.dumps(payload, ensure_ascii=False, sort_keys=True), now_text,
                ),
            )
            return self._routine_claim_from_payload(payload)

    @staticmethod
    def _routine_claim_from_payload(
        payload: dict[str, Any], replay: bool = False
    ) -> RoutineClaimRecord:
        return RoutineClaimRecord(
            player=SQLitePlayerRepository._row_to_player(payload["player"]),
            activity_key=str(payload.get("activity_key", CHECKIN_ACTIVITY)),
            target_date=str(payload["target_date"]),
            reward={str(k): int(v) for k, v in dict(payload.get("reward", {})).items()},
            energy_spent=int(payload.get("energy_spent", 0)),
            spirit_stones_spent=int(payload.get("spirit_stones_spent", 0)),
            consecutive_days=int(payload.get("consecutive_days", 0)),
            makeup=bool(payload.get("makeup", False)),
            already_completed=replay,
        )

    async def water_spirit_tree(
        self,
        *,
        platform: str,
        platform_user_id: str,
        operation_id: str,
    ) -> SpiritTreeRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._water_spirit_tree_sync, platform, platform_user_id, operation_id
            )

    def _water_spirit_tree_sync(
        self, platform: str, platform_user_id: str, operation_id: str
    ) -> SpiritTreeRecord:
        operation_name = "routine.spirit_tree.water"
        request_hash = self._request_hash(
            operation_name,
            {
                "platform": platform,
                "platform_user_id": platform_user_id,
                "content_version": ROUTINE_CONTENT_VERSION,
                "rule_version": ROUTINE_RULE_VERSION,
            },
        )
        for attempt in range(5):
            try:
                return self._water_spirit_tree_once(
                    platform, platform_user_id, operation_id, operation_name, request_hash
                )
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).lower():
                    raise
                if attempt == 4:
                    raise RepositoryBusyError("database remained locked") from exc
                time.sleep(0.01 * (2**attempt))
        raise RepositoryBusyError("database remained locked")

    def _water_spirit_tree_once(
        self,
        platform: str,
        platform_user_id: str,
        operation_id: str,
        operation_name: str,
        request_hash: str,
    ) -> SpiritTreeRecord:
        now = self._now()
        today = now.date().isoformat()
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
                return self._spirit_tree_from_payload(
                    json.loads(existing["result_json"]), replay=True
                )
            row = self._require_player(connection, platform, platform_user_id)
            tree = connection.execute(
                "SELECT * FROM spirit_trees WHERE player_id = ?", (row["id"],)
            ).fetchone()
            if tree is None:
                connection.execute(
                    "INSERT INTO spirit_trees(player_id, cycle_no, water_count, content_version, rule_version, updated_at) VALUES (?, 1, 0, ?, ?, ?)",
                    (row["id"], ROUTINE_CONTENT_VERSION, ROUTINE_RULE_VERSION, now_text),
                )
                tree = connection.execute(
                    "SELECT * FROM spirit_trees WHERE player_id = ?", (row["id"],)
                ).fetchone()
            if tree is None:
                raise RuntimeError("spirit tree initialization failed")
            cooldown_until = tree["cooldown_until"]
            if cooldown_until and now_text < str(cooldown_until):
                raise SpiritTreeCooldownError("spirit tree is cooling down")
            cycle_no = int(tree["cycle_no"])
            if int(tree["water_count"]) >= 7:
                raise SpiritTreeWateredError("spirit tree is ready for harvest")
            duplicate = connection.execute(
                "SELECT 1 FROM spirit_tree_waterings WHERE player_id = ? AND cycle_no = ? AND business_date = ? LIMIT 1",
                (row["id"], cycle_no, today),
            ).fetchone()
            if duplicate is not None:
                raise SpiritTreeWateredError("spirit tree already watered today")
            if int(row["energy"]) < 2:
                raise ResourceInsufficientError("watering requires two energy")
            water_count = int(tree["water_count"]) + 1
            cycle_started_at = tree["cycle_started_at"] or now_text
            connection.execute(
                "UPDATE players SET energy = energy - 2, updated_at = ? WHERE id = ?",
                (now_text, row["id"]),
            )
            connection.execute(
                "INSERT INTO spirit_tree_waterings(player_id, cycle_no, business_date, operation_id, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    row["id"], cycle_no, today, operation_id,
                    json.dumps({"water_count": water_count, "energy_spent": 2, "content_version": ROUTINE_CONTENT_VERSION, "rule_version": ROUTINE_RULE_VERSION}, ensure_ascii=False, sort_keys=True),
                    now_text,
                ),
            )
            connection.execute(
                "UPDATE spirit_trees SET water_count = ?, last_water_date = ?, cycle_started_at = ?, snapshot_json = ?, result_json = ?, updated_at = ? WHERE player_id = ?",
                (
                    water_count, today, cycle_started_at,
                    json.dumps({"cycle_no": cycle_no}, ensure_ascii=False, sort_keys=True),
                    json.dumps({"water_count": water_count}, ensure_ascii=False, sort_keys=True),
                    now_text, row["id"],
                ),
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (row["id"],)).fetchone()
            player = self._row_to_player(updated) if updated is not None else None
            if player is None:
                raise RuntimeError("watering returned no player")
            status = tree_status(water_count, None, now_text)
            payload = {
                "player": self._player_payload(player),
                "status": status,
                "water_count": water_count,
                "energy_spent": 2,
                "reward": {},
                "cooldown_until": None,
                "cycle_no": cycle_no,
                "content_version": ROUTINE_CONTENT_VERSION,
                "rule_version": ROUTINE_RULE_VERSION,
            }
            connection.execute(
                "INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    operation_id, operation_name, row["id"], request_hash,
                    json.dumps(payload, ensure_ascii=False, sort_keys=True), now_text,
                ),
            )
            return self._spirit_tree_from_payload(payload)

    async def harvest_spirit_tree(
        self,
        *,
        platform: str,
        platform_user_id: str,
        operation_id: str,
    ) -> SpiritTreeRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._harvest_spirit_tree_sync, platform, platform_user_id, operation_id
            )

    def _harvest_spirit_tree_sync(
        self, platform: str, platform_user_id: str, operation_id: str
    ) -> SpiritTreeRecord:
        operation_name = "routine.spirit_tree.harvest"
        request_hash = self._request_hash(
            operation_name,
            {
                "platform": platform,
                "platform_user_id": platform_user_id,
                "content_version": ROUTINE_CONTENT_VERSION,
                "rule_version": ROUTINE_RULE_VERSION,
            },
        )
        for attempt in range(5):
            try:
                return self._harvest_spirit_tree_once(
                    platform, platform_user_id, operation_id, operation_name, request_hash
                )
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).lower():
                    raise
                if attempt == 4:
                    raise RepositoryBusyError("database remained locked") from exc
                time.sleep(0.01 * (2**attempt))
        raise RepositoryBusyError("database remained locked")

    def _harvest_spirit_tree_once(
        self,
        platform: str,
        platform_user_id: str,
        operation_id: str,
        operation_name: str,
        request_hash: str,
    ) -> SpiritTreeRecord:
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
                return self._spirit_tree_from_payload(
                    json.loads(existing["result_json"]), replay=True
                )
            row = self._require_player(connection, platform, platform_user_id)
            tree = connection.execute(
                "SELECT * FROM spirit_trees WHERE player_id = ?", (row["id"],)
            ).fetchone()
            if tree is None:
                raise SpiritTreeNotReadyError("spirit tree is not ready")
            cooldown_until = tree["cooldown_until"]
            if cooldown_until and now_text < str(cooldown_until):
                raise SpiritTreeCooldownError("spirit tree is cooling down")
            if int(tree["water_count"]) < 7:
                raise SpiritTreeNotReadyError("spirit tree is not ready")
            cycle_no = int(tree["cycle_no"])
            reward = tree_harvest_reward(operation_id)
            digest = hashlib.blake2b(
                f"tree.harvest.v0.1:{operation_id}".encode("utf-8"), digest_size=16
            ).hexdigest()
            inventory = self._json_object(row["inventory_json"], {})
            stones = int(row["spirit_stones"]) + int(reward.get("spirit_stones", 0))
            actual_reward: dict[str, int] = {}
            for key, quantity in reward.items():
                quantity = int(quantity)
                if key == "spirit_stones":
                    actual_reward[key] = quantity
                elif key == "local_reputation":
                    actual_reward[key] = quantity
                else:
                    inventory[key] = int(inventory.get(key, 0)) + quantity
                    actual_reward[key] = quantity
            reputation = connection.execute(
                "SELECT local_json, service_reputation FROM player_reputations WHERE player_id = ?",
                (row["id"],),
            ).fetchone()
            local = self._json_object(reputation["local_json"], {}) if reputation is not None else {}
            local["local.xuantian.new_town"] = int(local.get("local.xuantian.new_town", 0)) + int(reward.get("local_reputation", 0))
            service_reputation = int(reputation["service_reputation"]) if reputation is not None else 0
            connection.execute(
                """
                INSERT INTO player_reputations(player_id, local_json, service_reputation, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(player_id) DO UPDATE SET local_json = excluded.local_json,
                    service_reputation = excluded.service_reputation, updated_at = excluded.updated_at
                """,
                (row["id"], json.dumps(local, ensure_ascii=False, sort_keys=True), service_reputation, now_text),
            )
            cooldown = now + timedelta(hours=24)
            cooldown_text = serialize_datetime(cooldown)
            connection.execute(
                "UPDATE players SET spirit_stones = ?, inventory_json = ?, updated_at = ? WHERE id = ?",
                (stones, json.dumps(inventory, ensure_ascii=False, sort_keys=True), now_text, row["id"]),
            )
            result = {
                "pool_key": "tree.harvest.v0.1",
                "seed": digest,
                "reward": actual_reward,
                "content_version": ROUTINE_CONTENT_VERSION,
                "rule_version": ROUTINE_RULE_VERSION,
            }
            connection.execute(
                "INSERT INTO spirit_tree_harvests(player_id, cycle_no, operation_id, pool_key, seed, reward_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (row["id"], cycle_no, operation_id, result["pool_key"], digest, json.dumps(actual_reward, ensure_ascii=False, sort_keys=True), now_text),
            )
            connection.execute(
                "UPDATE spirit_trees SET cycle_no = ?, water_count = 0, last_water_date = NULL, cycle_started_at = NULL, cooldown_until = ?, result_json = ?, updated_at = ? WHERE player_id = ?",
                (cycle_no + 1, cooldown_text, json.dumps(result, ensure_ascii=False, sort_keys=True), now_text, row["id"]),
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (row["id"],)).fetchone()
            player = self._row_to_player(updated) if updated is not None else None
            if player is None:
                raise RuntimeError("harvest returned no player")
            payload = {
                "player": self._player_payload(player),
                "status": "cooldown",
                "water_count": 0,
                "energy_spent": 0,
                "reward": actual_reward,
                "cooldown_until": cooldown_text,
                "cycle_no": cycle_no,
                **result,
            }
            connection.execute(
                "INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    operation_id, operation_name, row["id"], request_hash,
                    json.dumps(payload, ensure_ascii=False, sort_keys=True), now_text,
                ),
            )
            return self._spirit_tree_from_payload(payload)

    @staticmethod
    def _spirit_tree_from_payload(
        payload: dict[str, Any], replay: bool = False
    ) -> SpiritTreeRecord:
        return SpiritTreeRecord(
            player=SQLitePlayerRepository._row_to_player(payload["player"]),
            status=str(payload.get("status", "dormant")),
            water_count=int(payload.get("water_count", 0)),
            energy_spent=int(payload.get("energy_spent", 0)),
            reward={str(k): int(v) for k, v in dict(payload.get("reward", {})).items()},
            cooldown_until=payload.get("cooldown_until"),
            already_completed=replay,
        )

    async def get_seven_day_status(
        self,
        *,
        platform: str,
        platform_user_id: str,
    ) -> SevenDayStatusRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._get_seven_day_status_sync, platform, platform_user_id
            )

    def _get_seven_day_status_sync(
        self, platform: str, platform_user_id: str
    ) -> SevenDayStatusRecord:
        now = self._now()
        with self._connect() as connection:
            row = self._require_player(connection, platform, platform_user_id)
            campaign = self._ensure_seven_day_campaign(
                connection, row, serialize_datetime(now)
            )
            return self._seven_day_status_from_connection(connection, row, campaign, now)

    @staticmethod
    def _ensure_seven_day_campaign(
        connection: sqlite3.Connection,
        player: sqlite3.Row,
        now_text: str,
    ) -> sqlite3.Row:
        campaign = connection.execute(
            "SELECT * FROM seven_day_campaigns WHERE player_id = ?",
            (player["id"],),
        ).fetchone()
        if campaign is not None:
            return campaign
        seeking = connection.execute(
            """
            SELECT created_at FROM operations
            WHERE player_id = ? AND operation_name = 'player.start_seeking'
            ORDER BY created_at ASC LIMIT 1
            """,
            (player["id"],),
        ).fetchone()
        if seeking is None:
            raise SevenDayNotStartedError("seven-day campaign has not started")
        try:
            start_date = datetime.fromisoformat(str(seeking["created_at"])).date().isoformat()
        except ValueError as exc:
            raise SevenDayNotStartedError("invalid seeking timestamp") from exc
        connection.execute(
            """
            INSERT INTO seven_day_campaigns(
                player_id, start_date, status, content_version, rule_version,
                created_at, updated_at
            ) VALUES (?, ?, 'active', ?, ?, ?, ?)
            """,
            (
                player["id"], start_date, SEVEN_DAY_CONTENT_VERSION,
                SEVEN_DAY_RULE_VERSION, now_text, now_text,
            ),
        )
        created = connection.execute(
            "SELECT * FROM seven_day_campaigns WHERE player_id = ?",
            (player["id"],),
        ).fetchone()
        if created is None:
            raise RuntimeError("seven-day campaign initialization failed")
        return created

    @staticmethod
    def _seven_day_source_operation(
        connection: sqlite3.Connection,
        player_id: int,
        goal,
        target_date: str,
    ) -> str | None:
        used = {
            str(item["source_operation_id"])
            for item in connection.execute(
                "SELECT source_operation_id FROM seven_day_goal_claims WHERE player_id = ?",
                (player_id,),
            ).fetchall()
        }
        if goal.event_key == "routine.checkin.daily":
            candidates = connection.execute(
                """
                SELECT operation_id FROM routine_checkins
                WHERE player_id = ? AND claim_kind = 'daily' AND target_date >= ?
                ORDER BY target_date ASC, id ASC
                """,
                (player_id, target_date),
            ).fetchall()
        elif goal.event_key == "explore.gather_outskirts":
            candidates = connection.execute(
                """
                SELECT operation_id FROM exploration_sessions
                WHERE player_id = ? AND mode_key = ? AND status = 'settled'
                ORDER BY id ASC
                """,
                (player_id, goal.event_key),
            ).fetchall()
        elif goal.event_key == "production.preview":
            candidates = connection.execute(
                """
                SELECT source_operation_id FROM activity_events
                WHERE player_id = ? AND event_key = 'production.preview'
                ORDER BY occurred_at ASC, id ASC
                """,
                (player_id,),
            ).fetchall()
            if not candidates:
                # Older rows may predate preview activity auditing; a started
                # order remains a compatible durable fallback.
                candidates = connection.execute(
                    """
                    SELECT operation_id FROM production_orders
                    WHERE player_id = ? AND status IN ('processing', 'completed', 'failed')
                    ORDER BY starts_at ASC, id ASC
                    """,
                    (player_id,),
                ).fetchall()
        elif goal.event_key == "bounty.accept":
            candidates = connection.execute(
                """
                SELECT operation_id FROM bounty_offers
                WHERE player_id = ?
                ORDER BY accepted_at ASC, id ASC
                """,
                (player_id,),
            ).fetchall()
        elif goal.event_key == "player.enter_cultivation":
            candidates = connection.execute(
                """
                SELECT operation_id FROM operations
                WHERE player_id = ? AND operation_name = ?
                ORDER BY created_at ASC
                """,
                (player_id, goal.event_key),
            ).fetchall()
        else:
            candidates = connection.execute(
                """
                SELECT source_operation_id FROM activity_events
                WHERE player_id = ? AND event_key = ? AND occurred_at >= ?
                ORDER BY occurred_at ASC, id ASC
                """,
                (player_id, goal.event_key, f"{target_date}T00:00:00+00:00"),
            ).fetchall()
        for candidate in candidates:
            value = str(candidate["operation_id"] if "operation_id" in candidate.keys() else candidate["source_operation_id"])
            if value not in used:
                return value
        return None

    def _seven_day_status_from_connection(
        self,
        connection: sqlite3.Connection,
        player: sqlite3.Row,
        campaign: sqlite3.Row,
        now: datetime,
    ) -> SevenDayStatusRecord:
        start = date.fromisoformat(str(campaign["start_date"]))
        current_day = (now.date() - start).days + 1
        current_day = max(0, min(len(SEVEN_DAY_GOALS), current_day))
        claims = {
            int(item["day_number"]): item
            for item in connection.execute(
                "SELECT * FROM seven_day_goal_claims WHERE player_id = ?",
                (player["id"],),
            ).fetchall()
        }
        goals: list[SevenDayGoalView] = []
        for definition in SEVEN_DAY_GOALS:
            target_date = (start + timedelta(days=definition.day_number - 1)).isoformat()
            claim = claims.get(definition.day_number)
            if claim is not None:
                state = "claimed"
                source = str(claim["source_operation_id"])
            elif current_day < definition.day_number:
                state = "locked"
                source = None
            elif definition.closed:
                state = "content_closed"
                source = None
            else:
                source = self._seven_day_source_operation(
                    connection, int(player["id"]), definition, target_date
                )
                state = "claimable" if source else "pending"
            goals.append(
                SevenDayGoalView(
                    day_number=definition.day_number,
                    goal_key=definition.key,
                    label=definition.label,
                    target_date=target_date,
                    state=state,
                    reward=seven_day_reward(definition),
                    source_operation_id=source,
                )
            )
        status = "completed" if all(goal.state == "claimed" for goal in goals) else str(campaign["status"])
        if status != campaign["status"]:
            connection.execute(
                "UPDATE seven_day_campaigns SET status = ?, updated_at = ? WHERE player_id = ?",
                (status, serialize_datetime(now), player["id"]),
            )
        return SevenDayStatusRecord(
            player=self._row_to_player(player),
            start_date=str(campaign["start_date"]),
            current_day=current_day,
            status=status,
            goals=tuple(goals),
        )

    async def claim_seven_day_goal(
        self,
        *,
        platform: str,
        platform_user_id: str,
        day_number: int,
        operation_id: str,
    ) -> SevenDayGoalRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._claim_seven_day_goal_sync,
                platform,
                platform_user_id,
                day_number,
                operation_id,
            )

    def _claim_seven_day_goal_sync(
        self,
        platform: str,
        platform_user_id: str,
        day_number: int,
        operation_id: str,
    ) -> SevenDayGoalRecord:
        operation_name = "routine.claim_seven_day_goal"
        request_payload = {
            "platform": platform,
            "platform_user_id": platform_user_id,
            "day_number": day_number,
            "content_version": SEVEN_DAY_CONTENT_VERSION,
            "rule_version": SEVEN_DAY_RULE_VERSION,
        }
        request_hash = self._request_hash(operation_name, request_payload)
        for attempt in range(5):
            try:
                return self._claim_seven_day_goal_once(
                    platform, platform_user_id, day_number, operation_id,
                    operation_name, request_hash,
                )
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).lower():
                    raise
                if attempt == 4:
                    raise RepositoryBusyError("database remained locked") from exc
                time.sleep(0.01 * (2**attempt))
        raise RepositoryBusyError("database remained locked")

    def _claim_seven_day_goal_once(
        self,
        platform: str,
        platform_user_id: str,
        day_number: int,
        operation_id: str,
        operation_name: str,
        request_hash: str,
    ) -> SevenDayGoalRecord:
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
                return self._seven_day_goal_from_payload(
                    json.loads(existing["result_json"]), replay=True
                )
            try:
                definition = seven_day_goal(day_number)
            except ValueError as exc:
                raise SevenDayGoalInvalidError(str(exc)) from exc
            row = self._require_player(connection, platform, platform_user_id)
            campaign = self._ensure_seven_day_campaign(connection, row, now_text)
            start = date.fromisoformat(str(campaign["start_date"]))
            target_date = (start + timedelta(days=day_number - 1)).isoformat()
            if now.date() < start + timedelta(days=day_number - 1):
                raise SevenDayGoalNotOpenError("seven-day goal is not open")
            claimed = connection.execute(
                "SELECT 1 FROM seven_day_goal_claims WHERE player_id = ? AND day_number = ?",
                (row["id"], day_number),
            ).fetchone()
            if claimed is not None:
                raise SevenDayGoalAlreadyClaimedError("seven-day goal was already claimed")
            if definition.closed:
                raise SevenDayGoalNotCompletedError("seven-day goal depends on closed content")
            source_operation_id = self._seven_day_source_operation(
                connection, int(row["id"]), definition, target_date
            )
            if source_operation_id is None:
                raise SevenDayGoalNotCompletedError("seven-day goal is not completed")
            reward = seven_day_reward(definition)
            inventory = self._json_object(row["inventory_json"], {})
            stones = int(row["spirit_stones"])
            local_reputation = 0
            for key, quantity in reward.items():
                if key == "spirit_stones":
                    stones += int(quantity)
                elif key == "local_reputation":
                    local_reputation += int(quantity)
                else:
                    inventory[key] = int(inventory.get(key, 0)) + int(quantity)
            reputation = connection.execute(
                "SELECT local_json, service_reputation FROM player_reputations WHERE player_id = ?",
                (row["id"],),
            ).fetchone()
            local = self._json_object(reputation["local_json"], {}) if reputation is not None else {}
            local["local.xuantian.new_town"] = int(local.get("local.xuantian.new_town", 0)) + local_reputation
            service_reputation = int(reputation["service_reputation"]) if reputation is not None else 0
            if local_reputation:
                connection.execute(
                    """
                    INSERT INTO player_reputations(player_id, local_json, service_reputation, updated_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(player_id) DO UPDATE SET local_json = excluded.local_json,
                        service_reputation = excluded.service_reputation, updated_at = excluded.updated_at
                    """,
                    (row["id"], json.dumps(local, ensure_ascii=False, sort_keys=True), service_reputation, now_text),
                )
            connection.execute(
                "UPDATE players SET spirit_stones = ?, inventory_json = ?, updated_at = ? WHERE id = ?",
                (stones, json.dumps(inventory, ensure_ascii=False, sort_keys=True), now_text, row["id"]),
            )
            connection.execute(
                """
                INSERT INTO seven_day_goal_claims(
                    player_id, day_number, goal_key, target_date, source_operation_id,
                    operation_id, reward_json, content_version, rule_version, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["id"], day_number, definition.key, target_date, source_operation_id,
                    operation_id, json.dumps(reward, ensure_ascii=False, sort_keys=True),
                    SEVEN_DAY_CONTENT_VERSION, SEVEN_DAY_RULE_VERSION, now_text,
                ),
            )
            total_claimed = connection.execute(
                "SELECT COUNT(*) AS count FROM seven_day_goal_claims WHERE player_id = ?",
                (row["id"],),
            ).fetchone()
            campaign_complete = int(total_claimed["count"]) == len(SEVEN_DAY_GOALS)
            if campaign_complete:
                connection.execute(
                    "UPDATE seven_day_campaigns SET status = 'completed', updated_at = ? WHERE player_id = ?",
                    (now_text, row["id"]),
                )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (row["id"],)).fetchone()
            if updated is None:
                raise RuntimeError("seven-day goal returned no player")
            payload = {
                "player": self._player_payload(self._row_to_player(updated)),
                "day_number": day_number,
                "goal_key": definition.key,
                "target_date": target_date,
                "reward": reward,
                "source_operation_id": source_operation_id,
                "campaign_complete": campaign_complete,
                "content_version": SEVEN_DAY_CONTENT_VERSION,
                "rule_version": SEVEN_DAY_RULE_VERSION,
            }
            connection.execute(
                "INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    operation_id, operation_name, row["id"], request_hash,
                    json.dumps(payload, ensure_ascii=False, sort_keys=True), now_text,
                ),
            )
            return self._seven_day_goal_from_payload(payload)

    @staticmethod
    def _seven_day_goal_from_payload(
        payload: dict[str, Any], replay: bool = False
    ) -> SevenDayGoalRecord:
        return SevenDayGoalRecord(
            player=SQLitePlayerRepository._row_to_player(payload["player"]),
            day_number=int(payload["day_number"]),
            goal_key=str(payload["goal_key"]),
            target_date=str(payload["target_date"]),
            reward={str(key): int(value) for key, value in dict(payload.get("reward", {})).items()},
            source_operation_id=str(payload["source_operation_id"]),
            campaign_complete=bool(payload.get("campaign_complete", False)),
            already_completed=replay,
        )

    @staticmethod
    def _honor_source_operation(
        connection: sqlite3.Connection,
        player_id: int,
        source_event: str,
    ) -> str | None:
        if source_event == "player.start_seeking":
            row = connection.execute(
                """
                SELECT operation_id FROM operations
                WHERE player_id = ? AND operation_name = ?
                ORDER BY created_at ASC LIMIT 1
                """,
                (player_id, source_event),
            ).fetchone()
        elif source_event == "routine.checkin.daily":
            row = connection.execute(
                """
                SELECT operation_id FROM routine_checkins
                WHERE player_id = ? AND claim_kind = 'daily'
                ORDER BY target_date ASC, id ASC LIMIT 1
                """,
                (player_id,),
            ).fetchone()
        elif source_event == "routine.checkin.daily:3":
            row = connection.execute(
                """
                SELECT operation_id FROM routine_checkins
                WHERE player_id = ? AND claim_kind = 'daily'
                ORDER BY target_date ASC, id ASC LIMIT 1 OFFSET 2
                """,
                (player_id,),
            ).fetchone()
        elif source_event == "production.complete":
            row = connection.execute(
                """
                SELECT operation_id FROM production_orders
                WHERE player_id = ? AND status = 'completed'
                ORDER BY updated_at ASC, id ASC LIMIT 1
                """,
                (player_id,),
            ).fetchone()
        else:
            row = connection.execute(
                """
                SELECT source_operation_id FROM activity_events
                WHERE player_id = ? AND event_key = ?
                ORDER BY occurred_at ASC, id ASC LIMIT 1
                """,
                (player_id, source_event),
            ).fetchone()
        if row is None:
            return None
        key = "operation_id" if "operation_id" in row.keys() else "source_operation_id"
        return str(row[key])

    @staticmethod
    def _materialize_honor_titles(
        connection: sqlite3.Connection,
        player_id: int,
        now_text: str,
    ) -> None:
        for definition in HONOR_TITLES:
            if definition.closed:
                continue
            source_operation_id = SQLitePlayerRepository._honor_source_operation(
                connection, player_id, definition.source_event
            )
            if source_operation_id is None:
                continue
            connection.execute(
                """
                INSERT OR IGNORE INTO honor_titles(
                    player_id, title_key, source_operation_id, acquired_at,
                    content_version, rule_version
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    player_id,
                    definition.key,
                    source_operation_id,
                    now_text,
                    ROUTINE_CONTENT_VERSION,
                    HONOR_RULE_VERSION,
                ),
            )

    @staticmethod
    def _honor_status_from_connection(
        connection: sqlite3.Connection,
        player: sqlite3.Row,
        now_text: str,
    ) -> HonorStatusRecord:
        SQLitePlayerRepository._materialize_honor_titles(connection, int(player["id"]), now_text)
        state = connection.execute(
            "SELECT equipped_title_key FROM honor_states WHERE player_id = ?",
            (player["id"],),
        ).fetchone()
        equipped = str(state["equipped_title_key"]) if state and state["equipped_title_key"] else None
        title_rows = {
            str(item["title_key"]): item
            for item in connection.execute(
                "SELECT title_key, source_operation_id FROM honor_titles WHERE player_id = ?",
                (player["id"],),
            ).fetchall()
        }
        titles = tuple(
            HonorTitleView(
                title_key=definition.key,
                label=definition.label,
                acquired=definition.key in title_rows,
                equipped=definition.key == equipped,
                source_operation_id=(
                    str(title_rows[definition.key]["source_operation_id"])
                    if definition.key in title_rows
                    else None
                ),
            )
            for definition in HONOR_TITLES
        )
        claim_rows = {
            str(item["achievement_key"]): item
            for item in connection.execute(
                "SELECT achievement_key, source_operation_id, reward_json FROM achievement_claims WHERE player_id = ?",
                (player["id"],),
            ).fetchall()
        }
        achievements: list[AchievementView] = []
        for definition in ACHIEVEMENTS:
            claim = claim_rows.get(definition.key)
            source = SQLitePlayerRepository._honor_source_operation(
                connection, int(player["id"]), definition.source_event
            )
            if claim is not None:
                state_name = "claimed"
                source = str(claim["source_operation_id"])
                reward = SQLitePlayerRepository._json_object(claim["reward_json"], {})
            elif definition.closed:
                state_name = "content_closed"
                reward = achievement_reward(definition)
                source = None
            elif source is not None:
                state_name = "claimable"
                reward = achievement_reward(definition)
            else:
                state_name = "pending"
                reward = achievement_reward(definition)
            achievements.append(
                AchievementView(
                    achievement_key=definition.key,
                    label=definition.label,
                    state=state_name,
                    reward=reward,
                    source_operation_id=source,
                )
            )
        return HonorStatusRecord(
            player=SQLitePlayerRepository._row_to_player(player),
            equipped_title_key=equipped,
            titles=titles,
            achievements=tuple(achievements),
        )

    async def get_honor_status(
        self,
        *,
        platform: str,
        platform_user_id: str,
    ) -> HonorStatusRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._get_honor_status_sync, platform, platform_user_id
            )

    def _get_honor_status_sync(
        self, platform: str, platform_user_id: str
    ) -> HonorStatusRecord:
        with self._connect() as connection:
            row = self._require_player(connection, platform, platform_user_id)
            return self._honor_status_from_connection(
                connection, row, serialize_datetime(self._now())
            )

    async def claim_achievement(
        self,
        *,
        platform: str,
        platform_user_id: str,
        achievement_key: str,
        operation_id: str,
    ) -> AchievementClaimRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._claim_achievement_sync,
                platform,
                platform_user_id,
                achievement_key,
                operation_id,
            )

    def _claim_achievement_sync(
        self,
        platform: str,
        platform_user_id: str,
        achievement_key: str,
        operation_id: str,
    ) -> AchievementClaimRecord:
        operation_name = "routine.claim_achievement"
        request_hash = self._request_hash(
            operation_name,
            {
                "platform": platform,
                "platform_user_id": platform_user_id,
                "achievement_key": achievement_key,
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
                return self._achievement_claim_from_payload(
                    json.loads(existing["result_json"]), replay=True
                )
            try:
                definition = achievement(achievement_key)
            except ValueError as exc:
                raise AchievementInvalidError(str(exc)) from exc
            row = self._require_player(connection, platform, platform_user_id)
            claimed = connection.execute(
                "SELECT 1 FROM achievement_claims WHERE player_id = ? AND achievement_key = ?",
                (row["id"], definition.key),
            ).fetchone()
            if claimed is not None:
                raise AchievementAlreadyClaimedError("achievement was already claimed")
            if definition.closed:
                raise HonorTitleClosedError("achievement content is closed")
            source_operation_id = self._honor_source_operation(
                connection, int(row["id"]), definition.source_event
            )
            if source_operation_id is None:
                raise AchievementNotCompletedError("achievement is not completed")
            reward = achievement_reward(definition)
            local_reputation = int(reward.get("local_reputation", 0))
            service_reputation_delta = int(reward.get("service_reputation", 0))
            reputation = connection.execute(
                "SELECT local_json, service_reputation FROM player_reputations WHERE player_id = ?",
                (row["id"],),
            ).fetchone()
            local = self._json_object(reputation["local_json"], {}) if reputation is not None else {}
            local["local.xuantian.new_town"] = int(local.get("local.xuantian.new_town", 0)) + local_reputation
            service_reputation = int(reputation["service_reputation"]) if reputation is not None else 0
            service_reputation = min(100, service_reputation + service_reputation_delta)
            if local_reputation or service_reputation_delta:
                connection.execute(
                    """
                    INSERT INTO player_reputations(player_id, local_json, service_reputation, updated_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(player_id) DO UPDATE SET local_json = excluded.local_json,
                        service_reputation = excluded.service_reputation, updated_at = excluded.updated_at
                    """,
                    (
                        row["id"],
                        json.dumps(local, ensure_ascii=False, sort_keys=True),
                        service_reputation,
                        now_text,
                    ),
                )
            title_key = reward.get("title_key")
            if title_key:
                title_definition = honor_title(str(title_key))
                connection.execute(
                    """
                    INSERT OR IGNORE INTO honor_titles(
                        player_id, title_key, source_operation_id, acquired_at,
                        content_version, rule_version
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row["id"], str(title_key), source_operation_id, now_text,
                        ROUTINE_CONTENT_VERSION, HONOR_RULE_VERSION,
                    ),
                )
                del title_definition
            connection.execute(
                """
                INSERT INTO achievement_claims(
                    player_id, achievement_key, source_operation_id, operation_id,
                    reward_json, content_version, rule_version, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["id"], definition.key, source_operation_id, operation_id,
                    json.dumps(reward, ensure_ascii=False, sort_keys=True),
                    ROUTINE_CONTENT_VERSION, HONOR_RULE_VERSION, now_text,
                ),
            )
            updated = connection.execute(
                "SELECT * FROM players WHERE id = ?", (row["id"],)
            ).fetchone()
            if updated is None:
                raise RuntimeError("achievement claim returned no player")
            payload = {
                "player": self._player_payload(self._row_to_player(updated)),
                "achievement_key": definition.key,
                "label": definition.label,
                "reward": reward,
                "source_operation_id": source_operation_id,
                "content_version": ROUTINE_CONTENT_VERSION,
                "rule_version": HONOR_RULE_VERSION,
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
            return self._achievement_claim_from_payload(payload)

    @staticmethod
    def _achievement_claim_from_payload(
        payload: dict[str, Any], replay: bool = False
    ) -> AchievementClaimRecord:
        return AchievementClaimRecord(
            player=SQLitePlayerRepository._row_to_player(payload["player"]),
            achievement_key=str(payload["achievement_key"]),
            label=str(payload["label"]),
            reward=dict(payload.get("reward", {})),
            source_operation_id=str(payload["source_operation_id"]),
            already_completed=replay,
        )

    async def equip_title(
        self,
        *,
        platform: str,
        platform_user_id: str,
        title_key: str,
        operation_id: str,
    ) -> HonorTitleEquipRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._equip_title_sync,
                platform,
                platform_user_id,
                title_key,
                operation_id,
            )

    def _equip_title_sync(
        self,
        platform: str,
        platform_user_id: str,
        title_key: str,
        operation_id: str,
    ) -> HonorTitleEquipRecord:
        operation_name = "routine.equip_title"
        request_hash = self._request_hash(
            operation_name,
            {"platform": platform, "platform_user_id": platform_user_id, "title_key": title_key},
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
                return self._title_equip_from_payload(json.loads(existing["result_json"]), replay=True)
            try:
                definition = honor_title(title_key)
            except ValueError as exc:
                raise HonorTitleNotFoundError(str(exc)) from exc
            row = self._require_player(connection, platform, platform_user_id)
            self._materialize_honor_titles(connection, int(row["id"]), now_text)
            owned = connection.execute(
                "SELECT 1 FROM honor_titles WHERE player_id = ? AND title_key = ?",
                (row["id"], definition.key),
            ).fetchone()
            if owned is None:
                raise HonorTitleNotFoundError("title is not owned")
            connection.execute(
                """
                INSERT INTO honor_states(player_id, equipped_title_key, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(player_id) DO UPDATE SET equipped_title_key = excluded.equipped_title_key,
                    updated_at = excluded.updated_at
                """,
                (row["id"], definition.key, now_text),
            )
            updated = connection.execute(
                "SELECT * FROM players WHERE id = ?", (row["id"],)
            ).fetchone()
            if updated is None:
                raise RuntimeError("title equip returned no player")
            payload = {
                "player": self._player_payload(self._row_to_player(updated)),
                "title_key": definition.key,
                "label": definition.label,
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
            return self._title_equip_from_payload(payload)

    @staticmethod
    def _title_equip_from_payload(
        payload: dict[str, Any], replay: bool = False
    ) -> HonorTitleEquipRecord:
        return HonorTitleEquipRecord(
            player=SQLitePlayerRepository._row_to_player(payload["player"]),
            title_key=str(payload["title_key"]),
            label=str(payload["label"]),
            already_completed=replay,
        )

    async def redeem_code(
        self,
        *,
        platform: str,
        platform_user_id: str,
        code: str,
        operation_id: str,
    ) -> RedemptionCodeRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._redeem_code_sync,
                platform,
                platform_user_id,
                code,
                operation_id,
            )

    def _redeem_code_sync(
        self,
        platform: str,
        platform_user_id: str,
        code: str,
        operation_id: str,
    ) -> RedemptionCodeRecord:
        operation_name = "routine.redeem_code"
        try:
            code_hash = redemption_code_hash(code)
        except ValueError as exc:
            raise RedemptionCodeInvalidError(str(exc)) from exc
        request_hash = self._request_hash(
            operation_name,
            {
                "platform": platform,
                "platform_user_id": platform_user_id,
                "code_hash": code_hash,
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
                return self._redemption_from_payload(json.loads(existing["result_json"]), replay=True)
            code_row = connection.execute(
                "SELECT * FROM redemption_codes WHERE code_hash = ?",
                (code_hash,),
            ).fetchone()
            if code_row is None:
                raise RedemptionCodeInvalidError("redemption code is not configured")
            if code_row["status"] == "revoked":
                raise RedemptionCodeRevokedError("redemption code was revoked")
            business_date = now.date()
            starts_on = code_row["starts_on"]
            ends_on = code_row["ends_on"]
            if (starts_on and business_date < date.fromisoformat(str(starts_on))) or (
                ends_on and business_date > date.fromisoformat(str(ends_on))
            ):
                raise RedemptionCodeExpiredError("redemption code is outside its validity window")
            row = self._require_player(connection, platform, platform_user_id)
            claimed = connection.execute(
                "SELECT 1 FROM redemption_claims WHERE player_id = ? AND code_id = ?",
                (row["id"], code_row["id"]),
            ).fetchone()
            if claimed is not None:
                raise RedemptionCodeAlreadyClaimedError("redemption code was already claimed")
            if int(code_row["claimed_count"]) >= int(code_row["max_claims"]):
                raise RedemptionCodeExhaustedError("redemption code has no remaining claims")

            reward = self._json_object(code_row["reward_json"], {})
            inventory = self._json_object(row["inventory_json"], {})
            stones = int(row["spirit_stones"])
            energy = int(row["energy"])
            actual_reward: dict[str, int] = {}
            local_reputation = 0
            service_reputation = 0
            for key, raw_quantity in reward.items():
                quantity = int(raw_quantity)
                if key == "spirit_stones":
                    stones += quantity
                    actual_reward[key] = quantity
                elif key == "energy":
                    gained = min(quantity, max(0, int(row["energy_max"]) - energy))
                    energy += gained
                    actual_reward[key] = gained
                elif key == "local_reputation":
                    local_reputation += quantity
                    actual_reward[key] = quantity
                elif key == "service_reputation":
                    service_reputation += quantity
                    actual_reward[key] = quantity
                else:
                    inventory[key] = int(inventory.get(key, 0)) + quantity
                    actual_reward[key] = quantity

            if local_reputation or service_reputation:
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
                SET spirit_stones = ?, energy = ?, inventory_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (stones, energy, json.dumps(inventory, ensure_ascii=False, sort_keys=True), now_text, row["id"]),
            )
            connection.execute(
                """
                INSERT INTO redemption_claims(
                    player_id, code_id, code_key, operation_id, reward_json,
                    content_version, rule_version, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["id"], code_row["id"], code_row["code_key"], operation_id,
                    json.dumps(actual_reward, ensure_ascii=False, sort_keys=True),
                    code_row["content_version"], code_row["rule_version"], now_text,
                ),
            )
            connection.execute(
                "UPDATE redemption_codes SET claimed_count = claimed_count + 1, updated_at = ? WHERE id = ?",
                (now_text, code_row["id"]),
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (row["id"],)).fetchone()
            if updated is None:
                raise RuntimeError("redemption returned no player")
            payload = {
                "player": self._player_payload(self._row_to_player(updated)),
                "code_key": str(code_row["code_key"]),
                "reward": actual_reward,
                "content_version": str(code_row["content_version"]),
                "rule_version": str(code_row["rule_version"]),
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
            return self._redemption_from_payload(payload)

    @staticmethod
    def _redemption_from_payload(
        payload: dict[str, Any], replay: bool = False
    ) -> RedemptionCodeRecord:
        return RedemptionCodeRecord(
            player=SQLitePlayerRepository._row_to_player(payload["player"]),
            code_key=str(payload["code_key"]),
            reward={str(key): int(value) for key, value in dict(payload.get("reward", {})).items()},
            already_completed=replay,
        )

    async def roll_fate_pool(
        self,
        *,
        platform: str,
        platform_user_id: str,
        draw_count: int,
        operation_id: str,
    ) -> FateRollRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._roll_fate_pool_sync,
                platform,
                platform_user_id,
                draw_count,
                operation_id,
            )

    def _roll_fate_pool_sync(
        self,
        platform: str,
        platform_user_id: str,
        draw_count: int,
        operation_id: str,
    ) -> FateRollRecord:
        operation_name = "routine.roll_fate_pool"
        if draw_count not in {1, 10}:
            raise FatePoolInvalidError("unsupported fate draw count")
        request_hash = self._request_hash(
            operation_name,
            {
                "platform": platform,
                "platform_user_id": platform_user_id,
                "pool_key": FATE_POOL_KEY,
                "draw_count": draw_count,
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
                return self._fate_roll_from_payload(json.loads(existing["result_json"]), replay=True)
            row = self._require_player(connection, platform, platform_user_id)
            pool = connection.execute(
                "SELECT * FROM fate_pools WHERE player_id = ? AND pool_key = ?",
                (row["id"], FATE_POOL_KEY),
            ).fetchone()
            pity_before = int(pool["pity_count"]) if pool is not None else 0
            if pity_before < 0 or pity_before >= FATE_PITY_LIMIT:
                raise FatePoolNotOpenError("fate pity state is invalid")

            inventory = self._json_object(row["inventory_json"], {})
            stones = int(row["spirit_stones"])
            if draw_count == 1 and int(inventory.get(FATE_TICKET, 0)) > 0:
                cost_kind = "ticket"
                cost_quantity = 1
                remaining_ticket = int(inventory[FATE_TICKET]) - 1
                if remaining_ticket:
                    inventory[FATE_TICKET] = remaining_ticket
                else:
                    inventory.pop(FATE_TICKET, None)
            else:
                cost_kind = "spirit_stones"
                cost_quantity = FATE_SINGLE_COST if draw_count == 1 else FATE_TEN_COST
                if stones < cost_quantity:
                    raise FateDrawInsufficientError("fate draw cost is insufficient")
                stones -= cost_quantity

            draws, pity_after, seed_hash = roll_fate_pool(
                operation_id,
                draw_count=draw_count,
                pity_before=pity_before,
            )
            reward = reward_totals(draws)
            for key, quantity in reward.items():
                if key == "spirit_stones":
                    stones += quantity
                else:
                    inventory[key] = int(inventory.get(key, 0)) + quantity
            connection.execute(
                """
                UPDATE players
                SET spirit_stones = ?, inventory_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    stones,
                    json.dumps(inventory, ensure_ascii=False, sort_keys=True),
                    now_text,
                    row["id"],
                ),
            )
            total_draws = (int(pool["total_draws"]) if pool is not None else 0) + draw_count
            connection.execute(
                """
                INSERT INTO fate_pools(
                    player_id, pool_key, pity_count, total_draws,
                    content_version, rule_version, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(player_id, pool_key) DO UPDATE SET
                    pity_count = excluded.pity_count,
                    total_draws = excluded.total_draws,
                    content_version = excluded.content_version,
                    rule_version = excluded.rule_version,
                    updated_at = excluded.updated_at
                """,
                (
                    row["id"],
                    FATE_POOL_KEY,
                    pity_after,
                    total_draws,
                    FATE_CONTENT_VERSION,
                    FATE_RULE_VERSION,
                    now_text,
                ),
            )
            draws_payload = [
                {
                    "key": draw.key,
                    "label": draw.label,
                    "rarity": draw.rarity,
                    "quantity": draw.quantity,
                    "guaranteed": draw.guaranteed,
                }
                for draw in draws
            ]
            connection.execute(
                """
                INSERT INTO fate_rolls(
                    player_id, pool_key, operation_id, draw_count, cost_kind,
                    cost_quantity, pity_before, pity_after, seed_hash, reward_json,
                    draws_json, content_version, rule_version, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["id"],
                    FATE_POOL_KEY,
                    operation_id,
                    draw_count,
                    cost_kind,
                    cost_quantity,
                    pity_before,
                    pity_after,
                    seed_hash,
                    json.dumps(reward, ensure_ascii=False, sort_keys=True),
                    json.dumps(draws_payload, ensure_ascii=False, sort_keys=True),
                    FATE_CONTENT_VERSION,
                    FATE_RULE_VERSION,
                    now_text,
                ),
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (row["id"],)).fetchone()
            if updated is None:
                raise RuntimeError("fate roll returned no player")
            payload = {
                "player": self._player_payload(self._row_to_player(updated)),
                "pool_key": FATE_POOL_KEY,
                "draw_count": draw_count,
                "cost_kind": cost_kind,
                "cost_quantity": cost_quantity,
                "pity_before": pity_before,
                "pity_after": pity_after,
                "seed_hash": seed_hash,
                "draws": draws_payload,
                "reward": reward,
                "content_version": FATE_CONTENT_VERSION,
                "rule_version": FATE_RULE_VERSION,
            }
            connection.execute(
                """
                INSERT INTO operations(
                    operation_id, operation_name, player_id, request_hash,
                    result_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    operation_id,
                    operation_name,
                    row["id"],
                    request_hash,
                    json.dumps(payload, ensure_ascii=False, sort_keys=True),
                    now_text,
                ),
            )
            return self._fate_roll_from_payload(payload)

    @staticmethod
    def _fate_roll_from_payload(
        payload: dict[str, Any], replay: bool = False
    ) -> FateRollRecord:
        draws = tuple(
            FateDrawView(
                key=str(item["key"]),
                label=str(item["label"]),
                rarity=str(item["rarity"]),
                quantity=int(item["quantity"]),
                guaranteed=bool(item.get("guaranteed", False)),
            )
            for item in payload.get("draws", [])
        )
        return FateRollRecord(
            player=SQLitePlayerRepository._row_to_player(payload["player"]),
            pool_key=str(payload["pool_key"]),
            draw_count=int(payload["draw_count"]),
            cost_kind=str(payload["cost_kind"]),
            cost_quantity=int(payload["cost_quantity"]),
            pity_before=int(payload["pity_before"]),
            pity_after=int(payload["pity_after"]),
            seed_hash=str(payload["seed_hash"]),
            draws=draws,
            reward={str(key): int(value) for key, value in dict(payload.get("reward", {})).items()},
            already_completed=replay,
        )

    async def start_wayfaring(
        self,
        *,
        platform: str,
        platform_user_id: str,
        operation_id: str,
    ) -> WayfaringStatusRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._start_wayfaring_sync, platform, platform_user_id, operation_id
            )

    def _start_wayfaring_sync(
        self, platform: str, platform_user_id: str, operation_id: str
    ) -> WayfaringStatusRecord:
        operation_name = "pass.wayfaring.start"
        request_hash = self._request_hash(
            operation_name,
            {
                "platform": platform,
                "platform_user_id": platform_user_id,
                "pass_key": WAYFARING_PASS_KEY,
                "content_version": WAYFARING_CONTENT_VERSION,
                "rule_version": WAYFARING_RULE_VERSION,
            },
        )
        now = self._now()
        now_text = serialize_datetime(now)
        cycle_start, cycle_end = now.date(), now.date() + timedelta(days=27)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            if existing is not None:
                if existing["operation_name"] != operation_name or existing["request_hash"] != request_hash:
                    raise OperationConflictError("operation input differs from its original request")
                return self._wayfaring_status_from_payload(
                    json.loads(existing["result_json"]), replay=True
                )
            player = self._require_player(connection, platform, platform_user_id)
            current = connection.execute(
                "SELECT * FROM wayfaring_passes WHERE player_id = ? AND pass_key = ? ORDER BY cycle_start DESC LIMIT 1",
                (player["id"], WAYFARING_PASS_KEY),
            ).fetchone()
            if current is not None and str(current["status"]) in {"active", "completed"}:
                if date.fromisoformat(str(current["cycle_end"])) >= now.date():
                    raise WayfaringAlreadyStartedError("wayfaring pass is already active")
                connection.execute(
                    "UPDATE wayfaring_passes SET status = 'closed', updated_at = ? WHERE id = ?",
                    (now_text, current["id"]),
                )
            connection.execute(
                """
                INSERT INTO wayfaring_passes(
                    player_id, pass_key, cycle_start, cycle_end, status,
                    total_points, daily_date, daily_points, week_start, weekly_points,
                    claimed_free_json, claimed_paid_json, content_version, rule_version,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'active', 0, ?, 0, ?, 0, '[]', '[]', ?, ?, ?, ?)
                """,
                (
                    player["id"], WAYFARING_PASS_KEY, cycle_start.isoformat(), cycle_end.isoformat(),
                    cycle_start.isoformat(), wayfaring_week_start(cycle_start).isoformat(),
                    WAYFARING_CONTENT_VERSION, WAYFARING_RULE_VERSION, now_text, now_text,
                ),
            )
            pass_row = connection.execute(
                "SELECT * FROM wayfaring_passes WHERE player_id = ? AND pass_key = ? AND cycle_start = ?",
                (player["id"], WAYFARING_PASS_KEY, cycle_start.isoformat()),
            ).fetchone()
            if pass_row is None:
                raise RuntimeError("wayfaring pass initialization failed")
            payload = self._wayfaring_status_payload(connection, player, pass_row, now)
            connection.execute(
                "INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    operation_id, operation_name, player["id"], request_hash,
                    json.dumps(payload, ensure_ascii=False, sort_keys=True), now_text,
                ),
            )
            return self._wayfaring_status_from_payload(payload)

    async def get_wayfaring_status(
        self, *, platform: str, platform_user_id: str
    ) -> WayfaringStatusRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._get_wayfaring_status_sync, platform, platform_user_id
            )

    def _get_wayfaring_status_sync(
        self, platform: str, platform_user_id: str
    ) -> WayfaringStatusRecord:
        now = self._now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            player = self._require_player(connection, platform, platform_user_id)
            pass_row = connection.execute(
                "SELECT * FROM wayfaring_passes WHERE player_id = ? AND pass_key = ? ORDER BY cycle_start DESC LIMIT 1",
                (player["id"], WAYFARING_PASS_KEY),
            ).fetchone()
            if pass_row is None:
                raise WayfaringNotStartedError("wayfaring pass has not started")
            if str(pass_row["status"]) == "active" and now.date() > date.fromisoformat(str(pass_row["cycle_end"])):
                connection.execute(
                    "UPDATE wayfaring_passes SET status = 'closed', updated_at = ? WHERE id = ?",
                    (serialize_datetime(now), pass_row["id"]),
                )
                pass_row = connection.execute(
                    "SELECT * FROM wayfaring_passes WHERE id = ?", (pass_row["id"],)
                ).fetchone()
            if pass_row is None:
                raise RuntimeError("wayfaring pass disappeared")
            self._sync_wayfaring_points(connection, player, pass_row, now)
            pass_row = connection.execute(
                "SELECT * FROM wayfaring_passes WHERE id = ?", (pass_row["id"],)
            ).fetchone()
            if pass_row is None:
                raise RuntimeError("wayfaring pass disappeared")
            return self._wayfaring_status_from_payload(
                self._wayfaring_status_payload(connection, player, pass_row, now)
            )

    async def claim_wayfaring_level(
        self,
        *,
        platform: str,
        platform_user_id: str,
        level: int,
        track: str,
        operation_id: str,
    ) -> WayfaringClaimRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._claim_wayfaring_level_sync,
                platform,
                platform_user_id,
                level,
                track,
                operation_id,
            )

    def _claim_wayfaring_level_sync(
        self,
        platform: str,
        platform_user_id: str,
        level: int,
        track: str,
        operation_id: str,
    ) -> WayfaringClaimRecord:
        if isinstance(level, bool):
            raise WayfaringLevelInvalidError("invalid wayfaring level")
        try:
            level = int(level)
        except (TypeError, ValueError) as exc:
            raise WayfaringLevelInvalidError("invalid wayfaring level") from exc
        if level not in WAYFARING_LEVELS or track not in {"free", "paid"}:
            raise WayfaringLevelInvalidError("invalid wayfaring level or track")
        operation_name = "pass.wayfaring.claim"
        request_hash = self._request_hash(
            operation_name,
            {
                "platform": platform,
                "platform_user_id": platform_user_id,
                "pass_key": WAYFARING_PASS_KEY,
                "level": level,
                "track": track,
                "content_version": WAYFARING_CONTENT_VERSION,
                "rule_version": WAYFARING_RULE_VERSION,
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
                return self._wayfaring_claim_from_payload(
                    json.loads(existing["result_json"]), replay=True
                )
            player = self._require_player(connection, platform, platform_user_id)
            pass_row = connection.execute(
                "SELECT * FROM wayfaring_passes WHERE player_id = ? AND pass_key = ? ORDER BY cycle_start DESC LIMIT 1",
                (player["id"], WAYFARING_PASS_KEY),
            ).fetchone()
            if pass_row is None:
                raise WayfaringNotStartedError("wayfaring pass has not started")
            if str(pass_row["status"]) == "active" and now.date() > date.fromisoformat(str(pass_row["cycle_end"])):
                connection.execute(
                    "UPDATE wayfaring_passes SET status = 'closed', updated_at = ? WHERE id = ?",
                    (now_text, pass_row["id"]),
                )
                pass_row = connection.execute("SELECT * FROM wayfaring_passes WHERE id = ?", (pass_row["id"],)).fetchone()
            if pass_row is None:
                raise WayfaringNotStartedError("wayfaring pass has not started")
            self._sync_wayfaring_points(connection, player, pass_row, now)
            pass_row = connection.execute("SELECT * FROM wayfaring_passes WHERE id = ?", (pass_row["id"],)).fetchone()
            if pass_row is None or str(pass_row["status"]) == "closed":
                raise WayfaringLevelLockedError("wayfaring cycle is closed")
            current_level = min(WAYFARING_LEVELS[-1], int(pass_row["total_points"]) // WAYFARING_POINTS_PER_LEVEL)
            if level > current_level:
                raise WayfaringLevelLockedError("wayfaring level is not unlocked")
            claimed_key = "claimed_free_json" if track == "free" else "claimed_paid_json"
            claimed = {int(item) for item in self._json_array(pass_row[claimed_key])}
            if level in claimed:
                raise WayfaringClaimAlreadyExistsError("wayfaring reward already claimed")
            if track == "paid":
                active_contract = connection.execute(
                    """
                    SELECT id, starts_on, ends_on, content_version, rule_version
                    FROM dao_contracts
                    WHERE player_id = ? AND contract_key = 'dao_contract.monthly'
                      AND status = 'active' AND starts_on <= ? AND ends_on >= ?
                    LIMIT 1
                    """,
                    (player["id"], now.date().isoformat(), now.date().isoformat()),
                ).fetchone()
                if active_contract is None:
                    raise WayfaringPaidTrackInactiveError("monthly dao contract is required")
                reward = wayfaring_paid_reward(level)
            else:
                reward = wayfaring_free_reward(level)
            entitlement_snapshot = None
            if track == "paid" and active_contract is not None:
                entitlement_snapshot = {
                    "contract_id": int(active_contract["id"]),
                    "contract_key": "dao_contract.monthly",
                    "starts_on": str(active_contract["starts_on"]),
                    "ends_on": str(active_contract["ends_on"]),
                    "content_version": str(active_contract["content_version"]),
                    "rule_version": str(active_contract["rule_version"]),
                }
            actual_reward = self._apply_dao_reward(connection, player, reward, now_text)
            claimed.add(level)
            connection.execute(
                f"UPDATE wayfaring_passes SET {claimed_key} = ?, updated_at = ? WHERE id = ?",
                (json.dumps(sorted(claimed), ensure_ascii=False), now_text, pass_row["id"]),
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (player["id"],)).fetchone()
            if updated is None:
                raise RuntimeError("wayfaring claim returned no player")
            connection.execute(
                """
                INSERT INTO wayfaring_claims(
                    player_id, pass_id, level, track, operation_id, reward_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (player["id"], pass_row["id"], level, track, operation_id,
                 json.dumps(actual_reward, ensure_ascii=False, sort_keys=True), now_text),
            )
            payload = {
                "player": self._player_payload(self._row_to_player(updated)),
                "pass_key": WAYFARING_PASS_KEY,
                "level": level,
                "track": track,
                "reward": actual_reward,
                "total_points": int(pass_row["total_points"]),
                "entitlement_snapshot": entitlement_snapshot,
                "content_version": WAYFARING_CONTENT_VERSION,
                "rule_version": WAYFARING_RULE_VERSION,
            }
            connection.execute(
                "INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (operation_id, operation_name, player["id"], request_hash,
                 json.dumps(payload, ensure_ascii=False, sort_keys=True), now_text),
            )
            return self._wayfaring_claim_from_payload(payload)

    @staticmethod
    def _json_array(value: Any) -> list[Any]:
        if isinstance(value, list):
            return value
        try:
            parsed = json.loads(value or "[]")
        except (TypeError, json.JSONDecodeError):
            return []
        return parsed if isinstance(parsed, list) else []

    @staticmethod
    def _wayfaring_status_payload(
        connection: sqlite3.Connection,
        player: sqlite3.Row,
        pass_row: sqlite3.Row,
        now: datetime,
    ) -> dict[str, Any]:
        total = min(
            WAYFARING_LEVELS[-1] * WAYFARING_POINTS_PER_LEVEL,
            int(pass_row["total_points"]),
        )
        return {
            "player": SQLitePlayerRepository._player_payload(SQLitePlayerRepository._row_to_player(player)),
            "pass_key": str(pass_row["pass_key"]),
            "status": str(pass_row["status"]),
            "cycle_start": str(pass_row["cycle_start"]),
            "cycle_end": str(pass_row["cycle_end"]),
            "total_points": total,
            "current_level": min(WAYFARING_LEVELS[-1], total // WAYFARING_POINTS_PER_LEVEL),
            "daily_points": int(pass_row["daily_points"]),
            "weekly_points": int(pass_row["weekly_points"]),
            "claimed_free": [int(item) for item in SQLitePlayerRepository._json_array(pass_row["claimed_free_json"])],
            "claimed_paid": [int(item) for item in SQLitePlayerRepository._json_array(pass_row["claimed_paid_json"])],
            "content_version": WAYFARING_CONTENT_VERSION,
            "rule_version": WAYFARING_RULE_VERSION,
        }

    @staticmethod
    def _wayfaring_status_from_payload(
        payload: dict[str, Any], replay: bool = False
    ) -> WayfaringStatusRecord:
        return WayfaringStatusRecord(
            player=SQLitePlayerRepository._row_to_player(payload["player"]),
            pass_key=str(payload["pass_key"]),
            status=str(payload["status"]),
            cycle_start=str(payload["cycle_start"]),
            cycle_end=str(payload["cycle_end"]),
            total_points=int(payload.get("total_points", 0)),
            current_level=int(payload.get("current_level", 0)),
            daily_points=int(payload.get("daily_points", 0)),
            weekly_points=int(payload.get("weekly_points", 0)),
            claimed_free=tuple(int(item) for item in payload.get("claimed_free", [])),
            claimed_paid=tuple(int(item) for item in payload.get("claimed_paid", [])),
            already_completed=replay,
        )

    @staticmethod
    def _wayfaring_claim_from_payload(
        payload: dict[str, Any], replay: bool = False
    ) -> WayfaringClaimRecord:
        return WayfaringClaimRecord(
            player=SQLitePlayerRepository._row_to_player(payload["player"]),
            pass_key=str(payload["pass_key"]),
            level=int(payload["level"]),
            track=str(payload["track"]),
            reward={str(key): int(value) for key, value in dict(payload.get("reward", {})).items()},
            total_points=int(payload.get("total_points", 0)),
            already_completed=replay,
        )

    @staticmethod
    def _sync_wayfaring_points(
        connection: sqlite3.Connection,
        player: sqlite3.Row,
        pass_row: sqlite3.Row,
        now: datetime,
    ) -> None:
        if str(pass_row["status"]) != "active":
            return
        start = str(pass_row["cycle_start"])
        end = str(pass_row["cycle_end"])
        sources = {
            "player.start_seeking": "player.start_seeking",
            "routine.checkin.daily": "routine.checkin.daily",
            "routine.spirit_tree.water": "routine.spirit_tree.water",
            "routine.spirit_tree.harvest": "routine.spirit_tree.harvest",
            "production.complete": "production.complete",
            "bounty.claim": "bounty.claim",
            "exploration.settle": "exploration.settle",
            "routine.claim_dao_contract": "dao_contract.daily",
        }
        placeholders = ",".join("?" for _ in sources)
        candidates = connection.execute(
            f"""
            SELECT operation_id, operation_name, created_at FROM operations
            WHERE player_id = ? AND operation_name IN ({placeholders})
              AND substr(created_at, 1, 10) >= ? AND substr(created_at, 1, 10) <= ?
            ORDER BY created_at ASC, operation_id ASC
            """,
            (player["id"], *sources.keys(), start, end),
        ).fetchall()
        existing = {
            str(item["source_operation_id"])
            for item in connection.execute(
                "SELECT source_operation_id FROM wayfaring_point_events WHERE pass_id = ?",
                (pass_row["id"],),
            ).fetchall()
        }
        day_totals: dict[str, int] = {}
        week_totals: dict[str, int] = {}
        for item in connection.execute(
            "SELECT business_date, week_start, points FROM wayfaring_point_events WHERE pass_id = ?",
            (pass_row["id"],),
        ).fetchall():
            day_totals[str(item["business_date"])] = day_totals.get(str(item["business_date"]), 0) + int(item["points"])
            week_totals[str(item["week_start"])] = week_totals.get(str(item["week_start"]), 0) + int(item["points"])
        total = int(pass_row["total_points"])
        for item in candidates:
            source_operation_id = str(item["operation_id"])
            if source_operation_id in existing:
                continue
            source_key = sources[str(item["operation_name"])]
            try:
                raw_points = wayfaring_source_points(source_key)
            except ValueError:
                continue
            try:
                business_date = datetime.fromisoformat(str(item["created_at"])).date()
            except ValueError:
                business_date = now.date()
            business_date_text = business_date.isoformat()
            week_text = wayfaring_week_start(business_date).isoformat()
            remaining = min(
                WAYFARING_DAILY_POINT_CAP - day_totals.get(business_date_text, 0),
                WAYFARING_WEEKLY_POINT_CAP - week_totals.get(week_text, 0),
            )
            points = max(0, min(raw_points, remaining))
            connection.execute(
                """
                INSERT INTO wayfaring_point_events(
                    player_id, pass_id, source_key, source_operation_id,
                    business_date, week_start, points, created_at, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    player["id"], pass_row["id"], source_key, source_operation_id,
                    business_date_text, week_text, points, serialize_datetime(now),
                    json.dumps({"raw_points": raw_points, "capped": points != raw_points}, ensure_ascii=False, sort_keys=True),
                ),
            )
            existing.add(source_operation_id)
            day_totals[business_date_text] = day_totals.get(business_date_text, 0) + points
            week_totals[week_text] = week_totals.get(week_text, 0) + points
            total = min(
                WAYFARING_LEVELS[-1] * WAYFARING_POINTS_PER_LEVEL,
                total + points,
            )
        today_text = now.date().isoformat()
        week_text = wayfaring_week_start(now.date()).isoformat()
        status = str(pass_row["status"])
        if total >= WAYFARING_LEVELS[-1] * WAYFARING_POINTS_PER_LEVEL:
            status = "completed"
        connection.execute(
            """
            UPDATE wayfaring_passes
            SET total_points = ?, daily_date = ?, daily_points = ?,
                week_start = ?, weekly_points = ?, status = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                total, today_text, day_totals.get(today_text, 0), week_text,
                week_totals.get(week_text, 0), status, serialize_datetime(now), pass_row["id"],
            ),
        )

    @staticmethod
    def _apply_dao_reward(
        connection: sqlite3.Connection,
        player: sqlite3.Row,
        reward: dict[str, int],
        now_text: str,
    ) -> dict[str, int]:
        inventory = SQLitePlayerRepository._json_object(player["inventory_json"], {})
        stones = int(player["spirit_stones"])
        energy = int(player["energy"])
        actual: dict[str, int] = {}
        local_reputation = 0
        service_reputation = 0
        for key, raw_quantity in reward.items():
            quantity = int(raw_quantity)
            if key == "spirit_stones":
                stones += quantity
                actual[key] = quantity
            elif key == "energy":
                gained = min(quantity, max(0, int(player["energy_max"]) - energy))
                energy += gained
                actual[key] = gained
            elif key == "local_reputation":
                local_reputation += quantity
                actual[key] = quantity
            elif key == "service_reputation":
                service_reputation += quantity
                actual[key] = quantity
            else:
                inventory[key] = int(inventory.get(key, 0)) + quantity
                actual[key] = quantity
        if local_reputation or service_reputation:
            reputation = connection.execute(
                "SELECT local_json, service_reputation FROM player_reputations WHERE player_id = ?",
                (player["id"],),
            ).fetchone()
            local = SQLitePlayerRepository._json_object(reputation["local_json"], {}) if reputation is not None else {}
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
                (player["id"], json.dumps(local, ensure_ascii=False, sort_keys=True), current_service, now_text),
            )
        connection.execute(
            """
            UPDATE players
            SET spirit_stones = ?, energy = ?, inventory_json = ?, updated_at = ?
            WHERE id = ?
            """,
            (stones, energy, json.dumps(inventory, ensure_ascii=False, sort_keys=True), now_text, player["id"]),
        )
        return actual

    @staticmethod
    def _dao_status_from_connection(
        connection: sqlite3.Connection,
        player: sqlite3.Row,
        business_date: date,
    ) -> DaoContractStatusRecord:
        rows = connection.execute(
            """
            SELECT contract_key, starts_on, ends_on, status
            FROM dao_contracts
            WHERE player_id = ?
            ORDER BY starts_on DESC, id DESC
            """,
            (player["id"],),
        ).fetchall()
        views: list[DaoContractView] = []
        for row in rows:
            try:
                definition = dao_contract(str(row["contract_key"]))
            except ValueError:
                continue
            status = str(row["status"])
            if status == "active" and business_date > date.fromisoformat(str(row["ends_on"])):
                status = "expired"
            views.append(
                DaoContractView(
                    contract_key=definition.key,
                    label=definition.label,
                    status=status,
                    starts_on=str(row["starts_on"]),
                    ends_on=str(row["ends_on"]),
                    daily_reward=definition.daily_reward_map(),
                )
            )
        return DaoContractStatusRecord(
            player=SQLitePlayerRepository._row_to_player(player),
            contracts=tuple(views),
        )

    async def get_dao_contract_status(
        self,
        *,
        platform: str,
        platform_user_id: str,
    ) -> DaoContractStatusRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._get_dao_contract_status_sync,
                platform,
                platform_user_id,
            )

    def _get_dao_contract_status_sync(
        self,
        platform: str,
        platform_user_id: str,
    ) -> DaoContractStatusRecord:
        with self._connect() as connection:
            row = self._require_player(connection, platform, platform_user_id)
            return self._dao_status_from_connection(connection, row, self._now().date())

    async def activate_dao_contract(
        self,
        *,
        platform: str,
        platform_user_id: str,
        receipt_token: str,
        operation_id: str,
    ) -> DaoContractActivationRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._activate_dao_contract_sync,
                platform,
                platform_user_id,
                receipt_token,
                operation_id,
            )

    def _activate_dao_contract_sync(
        self,
        platform: str,
        platform_user_id: str,
        receipt_token: str,
        operation_id: str,
    ) -> DaoContractActivationRecord:
        try:
            receipt = verify_receipt(receipt_token, self.settings.billing_public_key)
        except BillingReceiptError as exc:
            raise BillingReceiptInvalidError(str(exc)) from exc
        try:
            definition = dao_contract(receipt.contract_key)
        except ValueError as exc:
            raise BillingReceiptInvalidError("receipt contract is not registered") from exc
        subject = f"{platform}:{platform_user_id}"
        now = self._now()
        if receipt.subject != subject:
            raise BillingReceiptInvalidError("receipt subject does not match the player")
        if receipt.currency != "spirit_stones" or receipt.amount != definition.price:
            raise BillingReceiptInvalidError("receipt price does not match the contract")
        if receipt.issued_at > now:
            raise BillingReceiptInvalidError("receipt was issued in the future")
        if receipt.valid_until is not None and receipt.valid_until < now:
            raise BillingReceiptInvalidError("receipt is expired")
        request_hash = self._request_hash(
            "routine.activate_dao_contract",
            {
                "platform": platform,
                "platform_user_id": platform_user_id,
                "receipt_hash": receipt.payload_hash,
            },
        )
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            if existing is not None:
                if existing["operation_name"] != "routine.activate_dao_contract" or existing["request_hash"] != request_hash:
                    raise OperationConflictError("operation input differs from its original request")
                return self._dao_activation_from_payload(json.loads(existing["result_json"]), replay=True)
            row = self._require_player(connection, platform, platform_user_id)
            used = connection.execute(
                "SELECT 1 FROM dao_contracts WHERE receipt_id = ? OR receipt_hash = ?",
                (receipt.receipt_id, receipt.payload_hash),
            ).fetchone()
            if used is not None:
                raise BillingReceiptAlreadyUsedError("receipt was already consumed")
            today = now.date()
            active = connection.execute(
                """
                SELECT ends_on FROM dao_contracts
                WHERE player_id = ? AND contract_key = ? AND status = 'active'
                ORDER BY ends_on DESC LIMIT 1
                """,
                (row["id"], definition.key),
            ).fetchone()
            if active is not None and date.fromisoformat(str(active["ends_on"])) >= today:
                starts = date.fromisoformat(str(active["ends_on"])) + timedelta(days=1)
            else:
                starts = today
            ends = starts + timedelta(days=definition.duration_days - 1)
            activation_reward = self._apply_dao_reward(
                connection, row, definition.activation_reward_map(), now_text
            )
            connection.execute(
                """
                INSERT INTO dao_contracts(
                    player_id, contract_key, receipt_id, receipt_hash, subject,
                    starts_on, ends_on, status, content_version, rule_version,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?)
                """,
                (
                    row["id"], definition.key, receipt.receipt_id, receipt.payload_hash,
                    receipt.subject, starts.isoformat(), ends.isoformat(),
                    definition.content_version, definition.rule_version, now_text, now_text,
                ),
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (row["id"],)).fetchone()
            if updated is None:
                raise RuntimeError("contract activation returned no player")
            payload = {
                "player": self._player_payload(self._row_to_player(updated)),
                "contract_key": definition.key,
                "label": definition.label,
                "receipt_id": receipt.receipt_id,
                "starts_on": starts.isoformat(),
                "ends_on": ends.isoformat(),
                "activation_reward": activation_reward,
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
                    operation_id, "routine.activate_dao_contract", row["id"], request_hash,
                    json.dumps(payload, ensure_ascii=False, sort_keys=True), now_text,
                ),
            )
            return self._dao_activation_from_payload(payload)

    @staticmethod
    def _dao_activation_from_payload(
        payload: dict[str, Any], replay: bool = False
    ) -> DaoContractActivationRecord:
        return DaoContractActivationRecord(
            player=SQLitePlayerRepository._row_to_player(payload["player"]),
            contract_key=str(payload["contract_key"]),
            label=str(payload["label"]),
            receipt_id=str(payload["receipt_id"]),
            starts_on=str(payload["starts_on"]),
            ends_on=str(payload["ends_on"]),
            activation_reward={str(key): int(value) for key, value in dict(payload.get("activation_reward", {})).items()},
            already_completed=replay,
        )

    async def claim_dao_contract(
        self,
        *,
        platform: str,
        platform_user_id: str,
        contract_key: str,
        operation_id: str,
    ) -> DaoContractClaimRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._claim_dao_contract_sync,
                platform,
                platform_user_id,
                contract_key,
                operation_id,
            )

    def _claim_dao_contract_sync(
        self,
        platform: str,
        platform_user_id: str,
        contract_key: str,
        operation_id: str,
    ) -> DaoContractClaimRecord:
        try:
            definition = dao_contract(contract_key)
        except ValueError as exc:
            raise DaoContractInvalidError(str(exc)) from exc
        today = self._now().date()
        operation_name = "routine.claim_dao_contract"
        request_hash = self._request_hash(
            operation_name,
            {"platform": platform, "platform_user_id": platform_user_id, "contract_key": contract_key, "business_date": today.isoformat()},
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
                return self._dao_claim_from_payload(json.loads(existing["result_json"]), replay=True)
            row = self._require_player(connection, platform, platform_user_id)
            contract_row = connection.execute(
                """
                SELECT * FROM dao_contracts
                WHERE player_id = ? AND contract_key = ? AND status = 'active'
                  AND starts_on <= ? AND ends_on >= ?
                ORDER BY starts_on DESC LIMIT 1
                """,
                (row["id"], contract_key, today.isoformat(), today.isoformat()),
            ).fetchone()
            if contract_row is None:
                raise DaoContractNotActiveError("dao contract is not active")
            claimed = connection.execute(
                "SELECT 1 FROM dao_contract_claims WHERE contract_id = ? AND business_date = ?",
                (contract_row["id"], today.isoformat()),
            ).fetchone()
            if claimed is not None:
                raise DaoContractAlreadyClaimedError("dao contract was already claimed today")
            reward = definition.daily_reward_map()
            offset = (today - date.fromisoformat(str(contract_row["starts_on"]))).days
            if definition.reputation_every_days and offset % definition.reputation_every_days == 0:
                reward["local_reputation"] = reward.get("local_reputation", 0) + definition.reputation_reward
            actual_reward = self._apply_dao_reward(connection, row, reward, now_text)
            connection.execute(
                """
                INSERT INTO dao_contract_claims(
                    player_id, contract_id, contract_key, business_date, operation_id,
                    reward_json, content_version, rule_version, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["id"], contract_row["id"], definition.key, today.isoformat(), operation_id,
                    json.dumps(actual_reward, ensure_ascii=False, sort_keys=True),
                    definition.content_version, definition.rule_version, now_text,
                ),
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (row["id"],)).fetchone()
            if updated is None:
                raise RuntimeError("contract claim returned no player")
            payload = {
                "player": self._player_payload(self._row_to_player(updated)),
                "contract_key": definition.key,
                "label": definition.label,
                "business_date": today.isoformat(),
                "reward": actual_reward,
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
            return self._dao_claim_from_payload(payload)

    @staticmethod
    def _dao_claim_from_payload(
        payload: dict[str, Any], replay: bool = False
    ) -> DaoContractClaimRecord:
        return DaoContractClaimRecord(
            player=SQLitePlayerRepository._row_to_player(payload["player"]),
            contract_key=str(payload["contract_key"]),
            label=str(payload["label"]),
            business_date=str(payload["business_date"]),
            reward={str(key): int(value) for key, value in dict(payload.get("reward", {})).items()},
            already_completed=replay,
        )

    async def revoke_dao_contract(
        self,
        *,
        player_id: str,
        contract_key: str,
        reason: str,
        operation_id: str,
    ) -> bool:
        """Admin/billing port: stop future claims without clawing back rewards."""

        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._revoke_dao_contract_sync,
                player_id,
                contract_key,
                reason,
                operation_id,
            )

    def _revoke_dao_contract_sync(
        self,
        player_id: str,
        contract_key: str,
        reason: str,
        operation_id: str,
    ) -> bool:
        if not reason.strip() or len(reason) > 256:
            raise DaoContractAlreadyRevokedError("revoke reason is required")
        request_hash = self._request_hash(
            "routine.revoke_dao_contract",
            {"player_id": player_id, "contract_key": contract_key, "reason": reason.strip()},
        )
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            if existing is not None:
                if existing["operation_name"] != "routine.revoke_dao_contract" or existing["request_hash"] != request_hash:
                    raise OperationConflictError("operation input differs from its original request")
                return bool(json.loads(existing["result_json"]).get("revoked", False))
            row = connection.execute(
                """
                SELECT dc.id, p.id AS player_db_id
                FROM dao_contracts AS dc
                JOIN players AS p ON p.id = dc.player_id
                WHERE p.player_id = ? AND dc.contract_key = ? AND dc.status = 'active'
                ORDER BY dc.ends_on DESC LIMIT 1
                """,
                (player_id, contract_key),
            ).fetchone()
            if row is None:
                raise DaoContractAlreadyRevokedError("dao contract is not active")
            connection.execute(
                "UPDATE dao_contracts SET status = 'revoked', revoke_reason = ?, updated_at = ? WHERE id = ?",
                (reason.strip(), now_text, row["id"]),
            )
            connection.execute(
                "INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (operation_id, "routine.revoke_dao_contract", row["player_db_id"], request_hash, json.dumps({"revoked": True}), now_text),
            )
            return True
