"""SQLite transactions for production orders."""

from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
import time
from dataclasses import replace
from datetime import date, datetime, timedelta
from typing import Any, Callable
from uuid import uuid4

from ...contracts import PlayerView, serialize_datetime
from ..advancement.constitution_effects import constitution_effect_snapshot
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
from ..advancement.equipment_rules import equipment_definition, equipment_initial_durability_bp
from ..utils.equipment import create_equipment_instances
from ..utils.assets import grant_player_assets, inventory_amount, player_assets_missing
from ..utils.json_cache import decode_json_strict
from ..utils.operations import operation_replay, record_operation
from ..utils.player import player_inventory, player_integer, spend_player_state
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
from ..world.rules import destination_definition, meets_realm
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
    MAINLINE_DEFINITIONS,
    MAINLINE_LOCKED,
    MAINLINE_REWARD_PENDING,
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
from ..routine.billing import BillingReceiptError, verify_receipt
from ..routine.rules import (
    CHECKIN_ACTIVITY,
    FATE_TICKET,
    MAKEUP_ACTIVITY,
    checkin_reward,
    makeup_reward,
    parse_past_date,
    SEVEN_DAY_GOALS,
    ACHIEVEMENTS,
    HONOR_TITLES,
    achievement,
    achievement_reward,
    honor_title,
    dao_contract,
    redemption_code_hash,
    seven_day_goal,
    seven_day_reward,
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
            self._check_production_requirements(connection, row, recipe)
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
            duration_seconds = self._facility_duration_seconds(row, recipe)
            return ProductionPreviewRecord(
                player=self._row_to_player(row),
                recipe_key=recipe.key,
                recipe_name=recipe.name,
                energy_cost=recipe.energy_cost,
                duration_seconds=duration_seconds,
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
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = operation_replay(
                connection,
                operation_id,
                "production.start",
                request_hash,
            )
            if existing is not None:
                self._validate_production_start_replay(
                    connection,
                    existing,
                    operation_id=operation_id,
                    platform=platform,
                    platform_user_id=platform_user_id,
                )
                return self._production_order_from_payload(existing, replay=True)

            row = self._require_player(connection, platform, platform_user_id)
            if row["stage"] != "cultivator":
                raise PlayerStageConflictError("player is not ready for production")
            idle = connection.execute(
                "SELECT 1 FROM idle_assignments WHERE player_id = ? AND status IN ('assigned', 'running') LIMIT 1",
                (row["id"],),
            ).fetchone()
            if idle is not None:
                raise ProductionBusyError("idle assignment is still running")
            dispatch = connection.execute(
                "SELECT 1 FROM dispatch_assignments WHERE player_id = ? AND status IN ('accepted', 'running') LIMIT 1",
                (row["id"],),
            ).fetchone()
            if dispatch is not None:
                raise ProductionBusyError("dispatch assignment is still running")
            self._check_production_requirements(connection, row, recipe)
            self._check_production_special_requirements(connection, row, recipe, now)
            if recipe.key == "recipe.fruit.soul_seed":
                cooldown_start = serialize_datetime(now - timedelta(days=7))
                recent = connection.execute(
                    "SELECT 1 FROM production_orders WHERE player_id = ? AND recipe_key = ? AND starts_at >= ? LIMIT 1",
                    (row["id"], recipe.key, cooldown_start),
                ).fetchone()
                if recent is not None:
                    raise ProductionWeeklyLimitError("soul seed field is on cooldown")
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

            facility_slot = self._facility_reserve_for_recipe(connection, row, recipe)
            duration_seconds = self._facility_duration_seconds(row, recipe)

            inventory = player_inventory(row)
            missing_assets = player_assets_missing(
                row,
                {**recipe.inputs, "spirit_stones": recipe.currency_cost},
            )
            if missing_assets:
                raise MaterialInsufficientError("recipe inputs or spirit stones are insufficient")
            if player_integer(row, "energy") < recipe.energy_cost:
                raise EnergyInsufficientError("energy is insufficient")

            durability = self._production_json_object(row["durability_json"], "player durability")
            tool_durability_before: int | None = None
            if recipe.tool_key:
                if inventory_amount(inventory, recipe.tool_key) < 1:
                    raise ToolMissingError("production tool is missing")
                tool_durability_before = int(durability.get(recipe.tool_key, TOOL_MAX_DURABILITY_BP))
                if tool_durability_before < recipe.tool_cost_bp:
                    raise ToolDurabilityInsufficientError("production tool durability is insufficient")
                durability[recipe.tool_key] = tool_durability_before - recipe.tool_cost_bp
            order_id = uuid4().hex
            starts_at = now_text
            ends_at = serialize_datetime(now + timedelta(seconds=duration_seconds))
            snapshot = {
                "recipe_key": recipe.key,
                "recipe_name": recipe.name,
                "realm_key": row["realm_key"],
                "realm_layer": player_integer(row, "realm_layer"),
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
                "proficiency_bp": recipe.proficiency_bp,
                "random_quality_bp": random_quality_bp(operation_id),
                "location_quality_bonus_bp": self._production_location_quality_bonus(recipe, row),
                "failure_refund_bp": recipe.failure_refund_bp,
                "binding_kind": recipe.binding_kind,
                "binding_duration_seconds": recipe.binding_duration_seconds,
                "binding_slot_limit": recipe.binding_slot_limit,
                "currency_cost": recipe.currency_cost,
                "duration_seconds": duration_seconds,
                "facility_slot_key": facility_slot["slot_key"] if facility_slot is not None else None,
                "facility_slot_id": int(facility_slot["id"]) if facility_slot is not None else None,
                "constitution_effect": constitution_effect_snapshot(connection, int(row["id"])),
            }
            spend_player_state(
                connection,
                row,
                costs={"spirit_stones": recipe.currency_cost, **recipe.inputs},
                updated_at=now_text,
                value_delta={"energy": -recipe.energy_cost},
                player_values={"durability_json": json.dumps(durability, ensure_ascii=False, sort_keys=True)},
            )
            connection.execute(
                """
                INSERT INTO production_orders(
                    order_id, player_id, operation_id, recipe_key, status, starts_at, ends_at,
                    energy_cost, currency_cost, facility_slot_id, snapshot_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'processing', ?, ?, ?, ?, ?, ?, ?, ?)
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
                    int(facility_slot["id"]) if facility_slot is not None else None,
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
                "snapshot": snapshot,
            }
            record_operation(
                connection,
                operation_id,
                "production.start",
                int(row["id"]),
                request_hash,
                payload,
                now_text,
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
        operation_name = "production.recover" if recovery else "production.complete"
        operation_payload = {"platform": platform, "platform_user_id": platform_user_id}
        request_hash = self._request_hash(operation_name, operation_payload)
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = operation_replay(connection, operation_id, operation_name, request_hash)
            if existing is not None:
                self._validate_production_settlement_replay(
                    connection,
                    existing,
                    operation_id=operation_id,
                    operation_name=operation_name,
                    platform=platform,
                    platform_user_id=platform_user_id,
                )
                return self._production_settlement_from_payload(existing, replay=True)
            row = self._require_player(connection, platform, platform_user_id)
            if recovery:
                recovery_cutoff = serialize_datetime(now - timedelta(hours=24))
                order = connection.execute(
                    "SELECT * FROM production_orders WHERE player_id = ? AND "
                    "(status = 'expired' OR (status = 'processing' AND ends_at < ?)) "
                    "ORDER BY created_at ASC, id ASC LIMIT 1",
                    (row["id"], recovery_cutoff),
                ).fetchone()
                if order is None:
                    pending = connection.execute(
                        "SELECT 1 FROM production_orders WHERE player_id = ? "
                        "AND status IN ('processing', 'expired') LIMIT 1",
                        (row["id"],),
                    ).fetchone()
                    if pending is not None:
                        raise ProductionNotReadyError("production is not ready for recovery")
                    raise ProductionNotFoundError("no processing production order")
            else:
                order = connection.execute(
                    "SELECT * FROM production_orders WHERE player_id = ? AND status IN ('processing', 'expired') ORDER BY id DESC LIMIT 1",
                    (row["id"],),
                ).fetchone()
            if order is None:
                raise ProductionNotFoundError("no processing production order")
            ends_at = datetime.fromisoformat(str(order["ends_at"]))
            snapshot: dict[str, Any] | None = None
            if not recovery and order["status"] == "expired":
                raise ProductionExpiredError("production order expired")
            if not recovery and now < ends_at:
                raise ProductionNotReadyError("production is not ready")
            if not recovery and now > ends_at + timedelta(hours=24):
                snapshot = self._production_json_object(order["snapshot_json"], "order snapshot")
                self._validate_production_snapshot(snapshot, order)
                self._validate_production_start_snapshot(
                    connection,
                    order,
                    snapshot,
                    platform=platform,
                    platform_user_id=platform_user_id,
                )
                if self._production_json_object(order["result_json"], "order result"):
                    raise ValueError("unsettled production order already has a result")
                connection.execute(
                    "UPDATE production_orders SET status = 'expired', updated_at = ? WHERE id = ? AND status = 'processing'",
                    (now_text, order["id"]),
                )
                connection.commit()
                raise ProductionExpiredError("production order expired")
            if recovery and now <= ends_at + timedelta(hours=24):
                raise ProductionNotReadyError("production is not ready for recovery")
            if snapshot is None:
                snapshot = self._production_json_object(order["snapshot_json"], "order snapshot")
                self._validate_production_snapshot(snapshot, order)
                self._validate_production_start_snapshot(
                    connection,
                    order,
                    snapshot,
                    platform=platform,
                    platform_user_id=platform_user_id,
                )
            if self._production_json_object(order["result_json"], "order result"):
                raise ValueError("unsettled production order already has a result")
            recipe_name = str(snapshot["recipe_name"])
            currency_spent = int(snapshot["currency_cost"])
            quality = self._production_quality_from_snapshot(snapshot)
            success = quality >= int(snapshot["success_threshold_bp"])
            asset_rewards: dict[str, int] = {}
            durability = self._production_json_object(row["durability_json"], "player durability")
            outputs: dict[str, int] = {}
            refunds: dict[str, int] = {}
            if success:
                outputs.update(snapshot["outputs"])
                high_quality_threshold = int(snapshot["high_quality_threshold_bp"])
                if quality >= high_quality_threshold:
                    for item_key, quantity in snapshot["high_quality_bonus"].items():
                        outputs[item_key] = outputs.get(item_key, 0) + quantity
                for item_key, quantity in outputs.items():
                    try:
                        equipment = equipment_definition(item_key, self.content)
                    except ValueError:
                        asset_rewards[item_key] = asset_rewards.get(item_key, 0) + quantity
                        continue
                    durability_bp = equipment_initial_durability_bp(quality, equipment)
                    durability[item_key] = durability_bp
                    if not create_equipment_instances(
                        connection,
                        player_id=int(row["id"]),
                        item_key=item_key,
                        quantity=quantity,
                        now_text=now_text,
                        content=self.content,
                        durability_bp=durability_bp,
                    ):
                        raise RuntimeError(f"equipment definition disappeared: {item_key}")
            else:
                refund_bp = snapshot["failure_refund_bp"]
                if refund_bp is not None:
                    failure_refunds = {
                        str(item_key): (int(quantity) * int(refund_bp)) // 10000
                        for item_key, quantity in snapshot["inputs"].items()
                    }
                else:
                    failure_refunds = snapshot["failure_refunds"]
                for item_key, quantity in failure_refunds.items():
                    if quantity > 0:
                        refunds[item_key] = quantity
                        asset_rewards[item_key] = asset_rewards.get(item_key, 0) + quantity
            tool_durability = snapshot.get("tool_durability_after")
            binding_expires_at: str | None = None
            if success and snapshot["binding_kind"] and int(snapshot["binding_duration_seconds"]) > 0:
                binding_expires_at = serialize_datetime(
                    now + timedelta(seconds=int(snapshot["binding_duration_seconds"]))
                )
            status = "completed" if success else "failed"
            grant_player_assets(
                connection,
                row,
                asset_rewards,
                now_text,
                player_values={
                    "durability_json": json.dumps(durability, ensure_ascii=False, sort_keys=True),
                },
            )
            self._persist_production_bindings(
                connection,
                player_id=int(row["id"]),
                order_id=str(order["order_id"]),
                operation_id=operation_id,
                binding_kind=snapshot["binding_kind"],
                outputs=outputs,
                bound_until=binding_expires_at,
                snapshot=snapshot,
                now_text=now_text,
            )
            result = {
                "recipe_key": snapshot["recipe_key"],
                "recipe_name": recipe_name,
                "status": status,
                "quality_bp": quality,
                "random_quality_bp": int(snapshot["random_quality_bp"]),
                "success": success,
                "outputs": outputs,
                "refunds": refunds,
                "currency_spent": currency_spent,
                "tool_durability_bp": tool_durability,
                "binding_expires_at": binding_expires_at,
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
            record_operation(
                connection,
                operation_id,
                operation_name,
                int(row["id"]),
                request_hash,
                payload,
                now_text,
            )
            return ProductionSettlementRecord(
                player=player,
                order_id=str(order["order_id"]),
                recipe_key=str(snapshot["recipe_key"]),
                recipe_name=recipe_name,
                status=status,
                quality_bp=quality,
                random_quality_bp=int(snapshot["random_quality_bp"]),
                success=success,
                outputs=outputs,
                refunds=refunds,
                currency_spent=currency_spent,
                tool_durability_bp=int(tool_durability) if tool_durability is not None else None,
                binding_expires_at=binding_expires_at,
            )

    @staticmethod
    def _check_production_requirements(connection: sqlite3.Connection, row: sqlite3.Row, recipe) -> None:
        cross_realm = bool(getattr(recipe, "cross_realm_faction", None))
        required_paths = tuple(getattr(recipe, "required_paths", ()))
        if not required_paths and recipe.required_path:
            required_paths = (recipe.required_path,)
        if required_paths and str(row["path_key"] or "") not in required_paths:
            if cross_realm:
                raise CrossRealmAllianceMissingError("当前道途或契约盟约不满足这条跨界配方")
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
                (str(row["realm_key"]) == "qi_sensing" and player_integer(row, "realm_layer") >= recipe.min_realm_layer)
                or str(row["realm_key"]) == "qi_gathering"
            )
        else:
            realm_ok = str(row["realm_key"]) in (recipe.required_realm, *recipe.additional_realms) and player_integer(row, "realm_layer") >= recipe.min_realm_layer
        if not realm_ok:
            if cross_realm:
                raise CrossRealmRecipeLockedError("当前境界不满足这条跨界配方")
            raise RecipeRequirementError("当前境界不满足这条配方")
        if recipe.required_location and str(row["location_key"]) not in recipe.required_location:
            if cross_realm:
                raise CrossRealmRecipeLockedError("当前地点不满足这条跨界配方")
            raise RecipeRequirementError("当前地点不满足这条配方")
        if str(row["location_key"]) == "xuantian.array_hall":
            from ..world.permissions import array_hall_permission

            if array_hall_permission(connection, row) is None:
                raise RecipeRequirementError("阵堂权限不足")

    @staticmethod
    def _production_location_quality_bonus(recipe, row: sqlite3.Row) -> int:
        faction = getattr(recipe, "cross_realm_faction", None)
        if not faction:
            return 0
        return 500 if str(row["location_key"]).startswith(f"{faction}.") else -1000

    @staticmethod
    def _production_integer(value: Any, field: str, *, minimum: int = 0, maximum: int | None = None) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
            raise ValueError(f"production {field} is invalid")
        if maximum is not None and value > maximum:
            raise ValueError(f"production {field} is invalid")
        return value

    @classmethod
    def _production_asset_map(cls, value: Any, field: str, *, minimum: int = 0) -> dict[str, int]:
        if not isinstance(value, dict):
            raise ValueError(f"production {field} must be an object")
        result: dict[str, int] = {}
        for item_key, quantity in value.items():
            if not isinstance(item_key, str) or not item_key:
                raise ValueError(f"production {field} has an invalid item key")
            result[item_key] = cls._production_integer(quantity, field, minimum=minimum)
        return result

    @staticmethod
    def _production_json_object(value: Any, field: str) -> dict[str, Any]:
        try:
            decoded = decode_json_strict(str(value))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"production {field} is invalid JSON") from exc
        if not isinstance(decoded, dict):
            raise ValueError(f"production {field} must be an object")
        return decoded

    @classmethod
    def _validate_production_snapshot(cls, snapshot: dict[str, Any], order: sqlite3.Row) -> None:
        required = {
            "recipe_key", "recipe_name", "realm_key", "realm_layer", "path_key", "subprofession_key",
            "location_key", "inputs", "outputs", "high_quality_bonus", "failure_refunds",
            "success_threshold_bp", "high_quality_threshold_bp", "tool_key", "tool_durability_before",
            "tool_durability_after", "material_quality_bp", "proficiency_bp", "random_quality_bp",
            "location_quality_bonus_bp", "failure_refund_bp", "binding_kind", "binding_duration_seconds",
            "binding_slot_limit", "currency_cost", "duration_seconds", "facility_slot_key",
            "facility_slot_id", "constitution_effect",
        }
        if set(snapshot) != required:
            raise ValueError("production order snapshot fields are invalid")
        for field in ("recipe_key", "recipe_name", "location_key"):
            if not isinstance(snapshot[field], str) or not snapshot[field]:
                raise ValueError(f"production snapshot {field} is invalid")
        for field in ("realm_key", "path_key", "subprofession_key", "tool_key", "binding_kind", "facility_slot_key"):
            if snapshot[field] is not None and (not isinstance(snapshot[field], str) or not snapshot[field]):
                raise ValueError(f"production snapshot {field} is invalid")
        cls._production_integer(snapshot["realm_layer"], "realm layer")
        cls._production_integer(snapshot["currency_cost"], "currency cost")
        cls._production_integer(snapshot["duration_seconds"], "duration", minimum=1)
        cls._production_integer(snapshot["binding_duration_seconds"], "binding duration")
        cls._production_integer(snapshot["binding_slot_limit"], "binding slot limit")
        cls._production_integer(snapshot["material_quality_bp"], "material quality", maximum=10000)
        cls._production_integer(snapshot["proficiency_bp"], "proficiency")
        cls._production_integer(snapshot["random_quality_bp"], "random quality", maximum=10000)
        cls._production_integer(snapshot["location_quality_bonus_bp"], "location quality bonus", minimum=-10000)
        cls._production_integer(snapshot["success_threshold_bp"], "success threshold", maximum=10000)
        cls._production_integer(snapshot["high_quality_threshold_bp"], "high quality threshold")
        if snapshot["high_quality_threshold_bp"] < snapshot["success_threshold_bp"]:
            raise ValueError("production quality thresholds are inconsistent")
        for field in ("tool_durability_before", "tool_durability_after"):
            value = snapshot[field]
            if value is not None:
                cls._production_integer(value, field, maximum=10000)
        if (snapshot["tool_key"] is None) != (snapshot["tool_durability_before"] is None):
            raise ValueError("production tool snapshot is inconsistent")
        if (snapshot["tool_key"] is None) != (snapshot["tool_durability_after"] is None):
            raise ValueError("production tool snapshot is inconsistent")
        refund_bp = snapshot["failure_refund_bp"]
        if refund_bp is not None:
            cls._production_integer(refund_bp, "failure refund", maximum=10000)
        facility_slot_id = snapshot["facility_slot_id"]
        if facility_slot_id is not None:
            cls._production_integer(facility_slot_id, "facility slot id", minimum=1)
        if (snapshot["facility_slot_key"] is None) != (facility_slot_id is None):
            raise ValueError("production facility slot snapshot is inconsistent")
        for field in ("inputs", "outputs", "high_quality_bonus", "failure_refunds"):
            cls._production_asset_map(snapshot[field], field)
        effect = snapshot["constitution_effect"]
        if not isinstance(effect, dict):
            raise ValueError("production constitution effect is invalid")
        if effect:
            if set(effect) != {"type", "value"} or not isinstance(effect["type"], str) or not effect["type"]:
                raise ValueError("production constitution effect is invalid")
            cls._production_integer(effect["value"], "constitution effect")
        if snapshot["recipe_key"] != str(order["recipe_key"]):
            raise ValueError("production snapshot recipe does not match its order")
        if cls._production_integer(snapshot["currency_cost"], "currency cost") != int(order["currency_cost"]):
            raise ValueError("production snapshot cost does not match its order")
        if snapshot["facility_slot_id"] != (int(order["facility_slot_id"]) if order["facility_slot_id"] is not None else None):
            raise ValueError("production snapshot facility does not match its order")
    @classmethod
    def _validate_production_player_identity(
        cls,
        player: Any,
        *,
        platform: str,
        platform_user_id: str,
    ) -> str:
        if not isinstance(player, dict):
            raise ValueError("production operation player is invalid")
        player_id = player.get("player_id")
        if not isinstance(player_id, str) or not player_id:
            raise ValueError("production operation player id is invalid")
        if player.get("id") != player_id or player.get("platform") != platform or player.get("platform_user_id") != platform_user_id:
            raise ValueError("production operation player does not match its caller")
        for field in ("qualification_json", "inventory_json", "durability_json"):
            cls._production_asset_map(cls._production_json_object(player.get(field), field), field)
        reputation = cls._production_json_object(player.get("faction_reputation_json"), "faction reputation")
        if any(not isinstance(key, str) or not key or isinstance(value, bool) or not isinstance(value, int) for key, value in reputation.items()):
            raise ValueError("production operation player reputation is invalid")
        intro = cls._production_json_object(player.get("intro_json"), "player introduction")
        if not isinstance(intro.get("flags"), list) or any(not isinstance(flag, str) for flag in intro["flags"]):
            raise ValueError("production operation player introduction is invalid")
        return player_id

    @classmethod
    def _validate_production_start_replay(
        cls,
        connection: sqlite3.Connection,
        payload: dict[str, Any],
        *,
        operation_id: str,
        platform: str,
        platform_user_id: str,
        check_schedule: bool = True,
    ) -> None:
        expected = {
            "player", "order_id", "recipe_key", "recipe_name", "status", "starts_at", "ends_at",
            "energy_cost", "currency_cost", "snapshot",
        }
        if set(payload) != expected:
            raise ValueError("production start operation has unexpected fields")
        player_id = cls._validate_production_player_identity(
            payload["player"], platform=platform, platform_user_id=platform_user_id
        )
        if not isinstance(payload["order_id"], str) or not payload["order_id"] or payload["status"] != "processing":
            raise ValueError("production start operation is invalid")
        order = connection.execute(
            """SELECT o.*, p.player_id AS public_player_id, p.platform, p.platform_user_id,
                      op.player_id AS operation_player_id
               FROM production_orders AS o JOIN players AS p ON p.id = o.player_id
               JOIN operations AS op ON op.operation_id = o.operation_id
               WHERE o.order_id = ?""",
            (payload["order_id"],),
        ).fetchone()
        if (
            order is None
            or order["public_player_id"] != player_id
            or int(order["operation_player_id"]) != int(order["player_id"])
            or order["platform"] != platform
            or order["platform_user_id"] != platform_user_id
            or order["operation_id"] != operation_id
            or order["status"] not in {"processing", "expired", "completed", "failed"}
        ):
            raise ValueError("production start operation does not match its order")
        snapshot = cls._production_json_object(order["snapshot_json"], "order snapshot")
        cls._validate_production_snapshot(snapshot, order)
        operation_snapshot = payload["snapshot"]
        if not isinstance(operation_snapshot, dict):
            raise ValueError("production start operation snapshot is invalid")
        cls._validate_production_snapshot(operation_snapshot, order)
        if operation_snapshot != snapshot:
            raise ValueError("production start operation and order snapshots disagree")
        if (
            payload["recipe_key"] != snapshot["recipe_key"]
            or payload["recipe_name"] != snapshot["recipe_name"]
            or (check_schedule and payload["starts_at"] != order["starts_at"])
            or (check_schedule and payload["ends_at"] != order["ends_at"])
            or cls._production_integer(payload["energy_cost"], "energy cost") != int(order["energy_cost"])
            or cls._production_integer(payload["currency_cost"], "currency cost") != int(order["currency_cost"])
        ):
            raise ValueError("production start operation fields do not match its order")

    @classmethod
    def _validate_production_start_snapshot(
        cls,
        connection: sqlite3.Connection,
        order: sqlite3.Row,
        snapshot: dict[str, Any],
        *,
        platform: str,
        platform_user_id: str,
    ) -> None:
        operation = connection.execute(
            "SELECT operation_name, player_id, request_hash, result_json "
            "FROM operations WHERE operation_id = ?",
            (order["operation_id"],),
        ).fetchone()
        request_hash = cls._request_hash(
            "production.start",
            {
                "platform": platform,
                "platform_user_id": platform_user_id,
                "recipe_key": str(order["recipe_key"]),
            },
        )
        if (
            operation is None
            or operation["operation_name"] != "production.start"
            or int(operation["player_id"]) != int(order["player_id"])
            or operation["request_hash"] != request_hash
        ):
            raise ValueError("production start operation does not match its order")
        payload = cls._production_json_object(operation["result_json"], "start operation result")
        cls._validate_production_start_replay(
            connection,
            payload,
            operation_id=str(order["operation_id"]),
            platform=platform,
            platform_user_id=platform_user_id,
            check_schedule=False,
        )
        if payload["snapshot"] != snapshot:
            raise ValueError("production order snapshot differs from its start operation")

    @classmethod
    def _validate_production_settlement_payload(
        cls,
        payload: dict[str, Any],
        *,
        platform: str,
        platform_user_id: str,
    ) -> int:
        expected = {
            "player", "order_id", "recipe_key", "recipe_name", "status", "quality_bp",
            "random_quality_bp", "success", "outputs", "refunds", "currency_spent",
            "tool_durability_bp", "binding_expires_at", "recovered",
        }
        if set(payload) != expected:
            raise ValueError("production settlement operation has unexpected fields")
        player_id = cls._validate_production_player_identity(
            payload["player"], platform=platform, platform_user_id=platform_user_id
        )
        if not isinstance(payload["order_id"], str) or not payload["order_id"]:
            raise ValueError("production settlement operation has no order")
        for field in ("recipe_key", "recipe_name"):
            if not isinstance(payload[field], str) or not payload[field]:
                raise ValueError(f"production settlement {field} is invalid")
        if payload["status"] not in {"completed", "failed"}:
            raise ValueError("production settlement status is invalid")
        if not isinstance(payload["success"], bool) or payload["success"] != (payload["status"] == "completed"):
            raise ValueError("production settlement status and success disagree")
        cls._production_integer(payload["quality_bp"], "settlement quality", maximum=10000)
        cls._production_integer(payload["random_quality_bp"], "settlement random quality", maximum=10000)
        outputs = cls._production_asset_map(payload["outputs"], "settlement outputs")
        refunds = cls._production_asset_map(payload["refunds"], "settlement refunds")
        if payload["success"] and refunds or not payload["success"] and outputs:
            raise ValueError("production settlement assets disagree with its result")
        cls._production_integer(payload["currency_spent"], "settlement currency")
        durability = payload["tool_durability_bp"]
        if durability is not None:
            cls._production_integer(durability, "settlement tool durability", maximum=10000)
        if payload["binding_expires_at"] is not None:
            if not isinstance(payload["binding_expires_at"], str):
                raise ValueError("production settlement binding expiry is invalid")
            try:
                datetime.fromisoformat(payload["binding_expires_at"])
            except ValueError as exc:
                raise ValueError("production settlement binding expiry is invalid") from exc
        if not isinstance(payload["recovered"], bool):
            raise ValueError("production settlement recovery marker is invalid")
        return player_id

    @classmethod
    def _validate_production_settlement_replay(
        cls,
        connection: sqlite3.Connection,
        payload: dict[str, Any],
        *,
        operation_id: str,
        operation_name: str,
        platform: str,
        platform_user_id: str,
    ) -> None:
        player_id = cls._validate_production_settlement_payload(
            payload,
            platform=platform,
            platform_user_id=platform_user_id,
        )
        if payload["recovered"] != (operation_name == "production.recover"):
            raise ValueError("production settlement operation kind is inconsistent")
        owner = connection.execute(
            """SELECT o.player_id, o.created_at, p.player_id AS public_player_id,
                      p.platform, p.platform_user_id
               FROM operations AS o JOIN players AS p ON p.id = o.player_id
               WHERE o.operation_id = ?""",
            (operation_id,),
        ).fetchone()
        if (
            owner is None
            or owner["public_player_id"] != player_id
            or owner["platform"] != platform
            or owner["platform_user_id"] != platform_user_id
        ):
            raise ValueError("production settlement operation owner is invalid")
        order = connection.execute(
            """SELECT o.*, p.player_id AS public_player_id
               FROM production_orders AS o JOIN players AS p ON p.id = o.player_id
               WHERE o.order_id = ?""",
            (payload["order_id"],),
        ).fetchone()
        if (
            order is None
            or order["public_player_id"] != player_id
            or int(order["player_id"]) != int(owner["player_id"])
            or order["recipe_key"] != payload["recipe_key"]
            or order["status"] != payload["status"]
        ):
            raise ValueError("production settlement operation does not match its order")
        snapshot = cls._production_json_object(order["snapshot_json"], "order snapshot")
        cls._validate_production_snapshot(snapshot, order)
        cls._validate_production_start_snapshot(
            connection,
            order,
            snapshot,
            platform=platform,
            platform_user_id=platform_user_id,
        )
        stored_result = cls._production_json_object(order["result_json"], "order result")
        operation_result = {key: value for key, value in payload.items() if key not in {"player", "order_id"}}
        if stored_result != operation_result:
            raise ValueError("production order and operation results disagree")
        quality = cls._production_quality_from_snapshot(snapshot)
        success = quality >= snapshot["success_threshold_bp"]
        expected_outputs: dict[str, int] = {}
        expected_refunds: dict[str, int] = {}
        if success:
            expected_outputs.update(snapshot["outputs"])
            if quality >= snapshot["high_quality_threshold_bp"]:
                for item_key, quantity in snapshot["high_quality_bonus"].items():
                    expected_outputs[item_key] = expected_outputs.get(item_key, 0) + quantity
        elif snapshot["failure_refund_bp"] is not None:
            expected_refunds = {
                item_key: quantity * snapshot["failure_refund_bp"] // 10000
                for item_key, quantity in snapshot["inputs"].items()
                if quantity * snapshot["failure_refund_bp"] // 10000 > 0
            }
        else:
            expected_refunds = {
                item_key: quantity
                for item_key, quantity in snapshot["failure_refunds"].items()
                if quantity > 0
            }
        expected_binding_expiry = None
        if success and snapshot["binding_kind"] and snapshot["binding_duration_seconds"] > 0:
            try:
                settled_at = datetime.fromisoformat(str(owner["created_at"]))
            except (TypeError, ValueError) as exc:
                raise ValueError("production settlement operation time is invalid") from exc
            expected_binding_expiry = serialize_datetime(
                settled_at + timedelta(seconds=snapshot["binding_duration_seconds"])
            )
        expected_result = {
            "recipe_key": snapshot["recipe_key"],
            "recipe_name": snapshot["recipe_name"],
            "status": "completed" if success else "failed",
            "quality_bp": quality,
            "random_quality_bp": snapshot["random_quality_bp"],
            "success": success,
            "outputs": expected_outputs,
            "refunds": expected_refunds,
            "currency_spent": snapshot["currency_cost"],
            "tool_durability_bp": snapshot["tool_durability_after"],
            "binding_expires_at": expected_binding_expiry,
            "recovered": operation_name == "production.recover",
        }
        if operation_result != expected_result:
            raise ValueError("production settlement result does not match its snapshot")

    @staticmethod
    def _production_quality_from_snapshot(snapshot: dict[str, Any]) -> int:
        from ..production.rules import production_quality

        value = production_quality(
            material_quality_bp=int(snapshot["material_quality_bp"]),
            proficiency_bp=int(snapshot["proficiency_bp"]),
            tool_durability_bp=int(snapshot["tool_durability_before"] or 0),
            random_quality_bp_value=int(snapshot["random_quality_bp"]),
        ) + int(snapshot["location_quality_bonus_bp"])
        constitution_effect = snapshot["constitution_effect"]
        if isinstance(constitution_effect, dict) and constitution_effect.get("type") == "production_quality_bp":
            bonus = constitution_effect.get("value")
            if isinstance(bonus, bool) or not isinstance(bonus, int) or bonus < 0:
                raise ValueError("production snapshot has an invalid constitution effect")
            value += bonus
        return max(0, min(10000, value))
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
            binding_expires_at=(
                str(payload["binding_expires_at"])
                if payload.get("binding_expires_at") is not None
                else None
            ),
            already_completed=replay,
        )
