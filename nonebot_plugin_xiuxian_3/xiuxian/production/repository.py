"""SQLite transactions for production orders."""

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


class ProductionRepositoryMixin:
    async def preview_production(
        self,
        *,
        platform: str,
        platform_user_id: str,
        recipe_key: str,
        operation_id: str = "",
    ) -> ProductionPreviewRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._preview_production_sync,
                platform,
                platform_user_id,
                recipe_key,
                operation_id,
            )

    def _preview_production_sync(
        self,
        platform: str,
        platform_user_id: str,
        recipe_key: str,
        operation_id: str,
    ) -> ProductionPreviewRecord:
        from ..production.rules import recipe_definition

        recipe = recipe_definition(recipe_key)
        now = self._now()
        with self._connect() as connection:
            row = self._require_player(connection, platform, platform_user_id)
            self._check_production_requirements(row, recipe)
            day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            day_end = day_start + timedelta(days=1)
            used = connection.execute(
                """
                SELECT COUNT(*) AS count FROM production_orders
                WHERE player_id = ? AND recipe_key = ? AND starts_at >= ? AND starts_at < ?
                """,
                (row["id"], recipe.key, serialize_datetime(day_start), serialize_datetime(day_end)),
            ).fetchone()
            if operation_id:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO activity_events(
                        player_id, event_key, source_operation_id, occurred_at, payload_json
                    ) VALUES (?, 'production.preview', ?, ?, ?)
                    """,
                    (
                        row["id"], operation_id, serialize_datetime(now),
                        json.dumps({"recipe_key": recipe.key}, ensure_ascii=False, sort_keys=True),
                    ),
                )
            return ProductionPreviewRecord(
                player=self._row_to_player(row),
                recipe_key=recipe.key,
                recipe_name=recipe.name,
                energy_cost=recipe.energy_cost,
                duration_seconds=recipe.duration_seconds,
                daily_limit=recipe.daily_limit,
                daily_used=int(used["count"] if used is not None else 0),
                inputs=dict(recipe.inputs),
                tool_key=recipe.tool_key,
                currency_cost=recipe.currency_cost,
            )

    async def start_production(
        self,
        *,
        platform: str,
        platform_user_id: str,
        recipe_key: str,
        operation_id: str,
    ) -> ProductionOrderRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._start_production_with_retry,
                platform,
                platform_user_id,
                recipe_key,
                operation_id,
            )

    def _start_production_with_retry(
        self,
        platform: str,
        platform_user_id: str,
        recipe_key: str,
        operation_id: str,
    ) -> ProductionOrderRecord:
        last_error: Exception | None = None
        for attempt in range(5):
            try:
                return self._start_production_once(platform, platform_user_id, recipe_key, operation_id)
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).lower():
                    raise
                if attempt == 4:
                    raise RepositoryBusyError("database remained locked") from exc
                last_error = exc
                time.sleep(0.01 * (2**attempt))
        raise RepositoryBusyError("database remained locked") from last_error

    def _start_production_once(
        self,
        platform: str,
        platform_user_id: str,
        recipe_key: str,
        operation_id: str,
    ) -> ProductionOrderRecord:
        from ..production.rules import TOOL_MAX_DURABILITY_BP, random_quality_bp, recipe_definition

        recipe = recipe_definition(recipe_key)
        operation_payload = {
            "platform": platform,
            "platform_user_id": platform_user_id,
            "recipe_key": recipe.key,
        }
        request_hash = self._request_hash("production.start", operation_payload)
        now = datetime.now(timezone.utc)
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            if existing is not None:
                if existing["operation_name"] != "production.start" or existing["request_hash"] != request_hash:
                    raise OperationConflictError("operation input differs from its original request")
                return self._production_order_from_payload(json.loads(existing["result_json"]), replay=True)

            row = self._require_player(connection, platform, platform_user_id)
            if row["stage"] != "cultivator":
                raise PlayerStageConflictError("player is not ready for production")
            self._check_production_requirements(row, recipe)
            active = connection.execute(
                "SELECT 1 FROM production_orders WHERE player_id = ? AND status = 'processing' LIMIT 1",
                (row["id"],),
            ).fetchone()
            if active is not None:
                raise ProductionBusyError("production order is already processing")
            cultivation = connection.execute(
                "SELECT 1 FROM cultivation_sessions WHERE player_id = ? AND status = 'running' LIMIT 1",
                (row["id"],),
            ).fetchone()
            if cultivation is not None:
                raise ProductionBusyError("cultivation is still running")
            exploration = connection.execute(
                "SELECT 1 FROM exploration_sessions WHERE player_id = ? AND status IN ('created', 'running', 'combat_pending') LIMIT 1",
                (row["id"],),
            ).fetchone()
            if exploration is not None:
                raise ProductionBusyError("exploration is still running")
            retreat = connection.execute(
                "SELECT 1 FROM retreat_sessions WHERE player_id = ? AND status = 'running' LIMIT 1",
                (row["id"],),
            ).fetchone()
            if retreat is not None:
                raise ProductionBusyError("retreat is still running")
            day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            day_end = day_start + timedelta(days=1)
            used = connection.execute(
                """
                SELECT COUNT(*) AS count FROM production_orders
                WHERE player_id = ? AND recipe_key = ? AND starts_at >= ? AND starts_at < ?
                """,
                (row["id"], recipe.key, serialize_datetime(day_start), serialize_datetime(day_end)),
            ).fetchone()
            if used is not None and int(used["count"]) >= recipe.daily_limit:
                raise ProductionDailyLimitError("recipe daily cap reached")

            inventory = self._json_object(row["inventory_json"], {})
            for item_key, quantity in recipe.inputs.items():
                if int(inventory.get(item_key, 0)) < quantity:
                    raise MaterialInsufficientError("recipe inputs are insufficient")
            if int(row["energy"]) < recipe.energy_cost:
                raise EnergyInsufficientError("energy is insufficient")
            if int(row["spirit_stones"]) < recipe.currency_cost:
                raise MaterialInsufficientError("spirit stones are insufficient")

            durability = self._json_object(row["durability_json"], {})
            tool_durability_before: int | None = None
            if recipe.tool_key:
                if int(inventory.get(recipe.tool_key, 0)) < 1:
                    raise ToolMissingError("production tool is missing")
                tool_durability_before = int(durability.get(recipe.tool_key, TOOL_MAX_DURABILITY_BP))
                if tool_durability_before < recipe.tool_cost_bp:
                    raise ToolDurabilityInsufficientError("production tool durability is insufficient")
                durability[recipe.tool_key] = tool_durability_before - recipe.tool_cost_bp
            for item_key, quantity in recipe.inputs.items():
                inventory[item_key] = int(inventory[item_key]) - quantity
            order_id = uuid4().hex
            starts_at = now_text
            ends_at = serialize_datetime(now + timedelta(seconds=recipe.duration_seconds))
            snapshot = {
                "recipe_key": recipe.key,
                "recipe_name": recipe.name,
                "content_version": recipe.content_version,
                "rule_version": recipe.rule_version,
                "realm_key": row["realm_key"],
                "realm_layer": int(row["realm_layer"]),
                "path_key": row["path_key"],
                "subprofession_key": row["subprofession_key"],
                "location_key": row["location_key"],
                "inputs": dict(recipe.inputs),
                "outputs": dict(recipe.outputs),
                "high_quality_bonus": dict(recipe.high_quality_bonus),
                "failure_refunds": dict(recipe.failure_refunds),
                "success_threshold_bp": recipe.success_threshold_bp,
                "high_quality_threshold_bp": recipe.high_quality_threshold_bp,
                "tool_key": recipe.tool_key,
                "tool_durability_before": tool_durability_before,
                "tool_durability_after": durability.get(recipe.tool_key) if recipe.tool_key else None,
                "material_quality_bp": 10000,
                "proficiency_bp": 0,
                "random_quality_bp": random_quality_bp(operation_id),
                "currency_cost": recipe.currency_cost,
            }
            connection.execute(
                """
                UPDATE players
                SET energy = energy - ?, spirit_stones = spirit_stones - ?,
                    inventory_json = ?, durability_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    recipe.energy_cost,
                    recipe.currency_cost,
                    json.dumps(inventory, ensure_ascii=False, sort_keys=True),
                    json.dumps(durability, ensure_ascii=False, sort_keys=True),
                    now_text,
                    row["id"],
                ),
            )
            connection.execute(
                """
                INSERT INTO production_orders(
                    order_id, player_id, operation_id, recipe_key, status, starts_at, ends_at,
                    energy_cost, currency_cost, snapshot_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'processing', ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    order_id,
                    row["id"],
                    operation_id,
                    recipe.key,
                    starts_at,
                    ends_at,
                    recipe.energy_cost,
                    recipe.currency_cost,
                    json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
                    now_text,
                    now_text,
                ),
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (row["id"],)).fetchone()
            if updated is None:
                raise RuntimeError("production start returned no player")
            player = self._row_to_player(updated)
            payload = {
                "player": self._player_payload(player),
                "order_id": order_id,
                "recipe_key": recipe.key,
                "recipe_name": recipe.name,
                "status": "processing",
                "starts_at": starts_at,
                "ends_at": ends_at,
                "energy_cost": recipe.energy_cost,
                "currency_cost": recipe.currency_cost,
            }
            connection.execute(
                """
                INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at)
                VALUES (?, 'production.start', ?, ?, ?, ?)
                """,
                (operation_id, row["id"], request_hash, json.dumps(payload, ensure_ascii=False, sort_keys=True), now_text),
            )
            return ProductionOrderRecord(
                player=player,
                order_id=order_id,
                recipe_key=recipe.key,
                recipe_name=recipe.name,
                status="processing",
                starts_at=starts_at,
                ends_at=ends_at,
                energy_cost=recipe.energy_cost,
                currency_cost=recipe.currency_cost,
            )

    async def complete_production(
        self,
        *,
        platform: str,
        platform_user_id: str,
        operation_id: str,
    ) -> ProductionSettlementRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._settle_production_with_retry,
                platform,
                platform_user_id,
                operation_id,
                False,
            )

    async def recover_production(
        self,
        *,
        platform: str,
        platform_user_id: str,
        operation_id: str,
    ) -> ProductionSettlementRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._settle_production_with_retry,
                platform,
                platform_user_id,
                operation_id,
                True,
            )

    def _settle_production_with_retry(
        self,
        platform: str,
        platform_user_id: str,
        operation_id: str,
        recovery: bool,
    ) -> ProductionSettlementRecord:
        last_error: Exception | None = None
        for attempt in range(5):
            try:
                return self._settle_production_once(platform, platform_user_id, operation_id, recovery)
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).lower():
                    raise
                if attempt == 4:
                    raise RepositoryBusyError("database remained locked") from exc
                last_error = exc
                time.sleep(0.01 * (2**attempt))
        raise RepositoryBusyError("database remained locked") from last_error

    def _settle_production_once(
        self,
        platform: str,
        platform_user_id: str,
        operation_id: str,
        recovery: bool,
    ) -> ProductionSettlementRecord:
        from ..production.rules import HIGH_QUALITY_THRESHOLD_BP, QUALITY_SUCCESS_THRESHOLD_BP, recipe_definition

        operation_name = "production.recover" if recovery else "production.complete"
        operation_payload = {"platform": platform, "platform_user_id": platform_user_id}
        request_hash = self._request_hash(operation_name, operation_payload)
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
                return self._production_settlement_from_payload(json.loads(existing["result_json"]), replay=True)
            row = self._require_player(connection, platform, platform_user_id)
            order = connection.execute(
                "SELECT * FROM production_orders WHERE player_id = ? AND status IN ('processing', 'expired') ORDER BY id DESC LIMIT 1",
                (row["id"],),
            ).fetchone()
            if order is None:
                raise ProductionNotFoundError("no processing production order")
            ends_at = datetime.fromisoformat(str(order["ends_at"]))
            if not recovery and order["status"] == "expired":
                raise ProductionExpiredError("production order expired")
            if not recovery and now < ends_at:
                raise ProductionNotReadyError("production is not ready")
            if not recovery and now > ends_at + timedelta(hours=24):
                connection.execute(
                    "UPDATE production_orders SET status = 'expired', updated_at = ? WHERE id = ? AND status = 'processing'",
                    (now_text, order["id"]),
                )
                connection.commit()
                raise ProductionExpiredError("production order expired")
            if recovery and now <= ends_at + timedelta(hours=24):
                raise ProductionNotReadyError("production is not ready for recovery")
            recipe = recipe_definition(str(order["recipe_key"]))
            snapshot = self._json_object(order["snapshot_json"], {})
            recipe_name = str(snapshot.get("recipe_name", recipe.name))
            currency_spent = int(snapshot.get("currency_cost", recipe.currency_cost))
            quality = self._production_quality_from_snapshot(snapshot)
            success = quality >= int(snapshot.get("success_threshold_bp", QUALITY_SUCCESS_THRESHOLD_BP))
            inventory = self._json_object(row["inventory_json"], {})
            durability = self._json_object(row["durability_json"], {})
            outputs: dict[str, int] = {}
            refunds: dict[str, int] = {}
            if success:
                outputs.update(
                    {str(key): int(value) for key, value in dict(snapshot.get("outputs", recipe.outputs)).items()}
                )
                high_quality_threshold = int(
                    snapshot.get("high_quality_threshold_bp", HIGH_QUALITY_THRESHOLD_BP)
                )
                if quality >= high_quality_threshold:
                    for item_key, quantity in dict(
                        snapshot.get("high_quality_bonus", recipe.high_quality_bonus)
                    ).items():
                        outputs[item_key] = outputs.get(item_key, 0) + quantity
                for item_key, quantity in outputs.items():
                    inventory[item_key] = int(inventory.get(item_key, 0)) + quantity
                if recipe.key == "recipe.weapon.wood_sword":
                    durability["item.weapon.wood_sword"] = max(8000, min(10000, 8000 + quality // 5))
            else:
                for item_key, quantity in dict(
                    snapshot.get("failure_refunds", recipe.failure_refunds)
                ).items():
                    if quantity > 0:
                        refunds[item_key] = quantity
                        inventory[item_key] = int(inventory.get(item_key, 0)) + quantity
            tool_durability = snapshot.get("tool_durability_after")
            status = "completed" if success else "failed"
            connection.execute(
                """
                UPDATE players SET inventory_json = ?, durability_json = ?, updated_at = ? WHERE id = ?
                """,
                (
                    json.dumps(inventory, ensure_ascii=False, sort_keys=True),
                    json.dumps(durability, ensure_ascii=False, sort_keys=True),
                    now_text,
                    row["id"],
                ),
            )
            result = {
                "recipe_key": recipe.key,
                "recipe_name": recipe_name,
                "status": status,
                "quality_bp": quality,
                "random_quality_bp": int(snapshot.get("random_quality_bp", 0)),
                "success": success,
                "outputs": outputs,
                "refunds": refunds,
                "currency_spent": currency_spent,
                "tool_durability_bp": tool_durability,
                "recovered": recovery,
            }
            connection.execute(
                "UPDATE production_orders SET status = ?, result_json = ?, updated_at = ? WHERE id = ? AND status IN ('processing', 'expired')",
                (status, json.dumps(result, ensure_ascii=False, sort_keys=True), now_text, order["id"]),
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (row["id"],)).fetchone()
            if updated is None:
                raise RuntimeError("production settlement returned no player")
            player = self._row_to_player(updated)
            payload = {
                "player": self._player_payload(player),
                "order_id": order["order_id"],
                **result,
            }
            connection.execute(
                """
                INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (operation_id, operation_name, row["id"], request_hash, json.dumps(payload, ensure_ascii=False, sort_keys=True), now_text),
            )
            return ProductionSettlementRecord(
                player=player,
                order_id=str(order["order_id"]),
                recipe_key=recipe.key,
                recipe_name=recipe_name,
                status=status,
                quality_bp=quality,
                random_quality_bp=int(snapshot.get("random_quality_bp", 0)),
                success=success,
                outputs=outputs,
                refunds=refunds,
                currency_spent=currency_spent,
                tool_durability_bp=int(tool_durability) if tool_durability is not None else None,
            )

    @staticmethod
    def _check_production_requirements(row: sqlite3.Row, recipe) -> None:
        if recipe.required_path and str(row["path_key"] or "") != recipe.required_path:
            raise RecipeRequirementError("当前道途不满足这条配方")
        if recipe.required_subprofession and str(row["subprofession_key"] or "") not in recipe.required_subprofession:
            raise RecipeRequirementError("当前辅修不满足这条配方")
        teaching = (
            recipe.teaching_allowed
            and recipe.profession is not None
            and str(row["selected_service"] or "") == recipe.profession
        )
        profession_ok = (
            recipe.profession is None
            or str(row["subprofession_key"] or "") == recipe.profession
            or teaching
        )
        if not profession_ok:
            raise RecipeRequirementError("当前道途或生产教学不满足这条配方")
        if teaching and recipe.required_realm == "qi_sensing":
            realm_ok = (
                (str(row["realm_key"]) == "qi_sensing" and int(row["realm_layer"]) >= recipe.min_realm_layer)
                or str(row["realm_key"]) == "qi_gathering"
            )
        else:
            realm_ok = str(row["realm_key"]) == recipe.required_realm and int(row["realm_layer"]) >= recipe.min_realm_layer
        if not realm_ok:
            raise RecipeRequirementError("当前境界不满足这条配方")
        if recipe.required_location and str(row["location_key"]) not in recipe.required_location:
            raise RecipeRequirementError("当前地点不满足这条配方")

    @staticmethod
    def _production_quality_from_snapshot(snapshot: dict[str, Any]) -> int:
        from ..production.rules import production_quality

        return production_quality(
            material_quality_bp=int(snapshot.get("material_quality_bp", 10000)),
            proficiency_bp=int(snapshot.get("proficiency_bp", 0)),
            tool_durability_bp=int(snapshot.get("tool_durability_before", 0) or 0),
            random_quality_bp_value=int(snapshot.get("random_quality_bp", 0)),
        )
    @staticmethod
    def _production_order_from_payload(payload: dict[str, Any], *, replay: bool) -> ProductionOrderRecord:
        return ProductionOrderRecord(
            player=SQLitePlayerRepository._row_to_player(payload["player"]),
            order_id=str(payload["order_id"]),
            recipe_key=str(payload["recipe_key"]),
            recipe_name=str(payload["recipe_name"]),
            status=str(payload["status"]),
            starts_at=str(payload["starts_at"]),
            ends_at=str(payload["ends_at"]),
            energy_cost=int(payload["energy_cost"]),
            currency_cost=int(payload["currency_cost"]),
            already_completed=replay,
        )
    @staticmethod
    def _production_settlement_from_payload(payload: dict[str, Any], *, replay: bool) -> ProductionSettlementRecord:
        return ProductionSettlementRecord(
            player=SQLitePlayerRepository._row_to_player(payload["player"]),
            order_id=str(payload["order_id"]),
            recipe_key=str(payload["recipe_key"]),
            recipe_name=str(payload["recipe_name"]),
            status=str(payload["status"]),
            quality_bp=int(payload["quality_bp"]),
            random_quality_bp=int(payload.get("random_quality_bp", 0)),
            success=bool(payload["success"]),
            outputs={str(key): int(value) for key, value in payload.get("outputs", {}).items()},
            refunds={str(key): int(value) for key, value in payload.get("refunds", {}).items()},
            currency_spent=int(payload.get("currency_spent", 0)),
            tool_durability_bp=(
                int(payload["tool_durability_bp"])
                if payload.get("tool_durability_bp") is not None
                else None
            ),
            already_completed=replay,
        )
