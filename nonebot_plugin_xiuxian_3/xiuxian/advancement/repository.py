"""SQLite transactions for retreat and character build progression."""

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
from ..content import ContentError
from ..content import bundled_content
from ..items.manual_rules import manual_grants_permission
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
    constitution_definition,
    constitution_reshape_rules,
)
from ..advancement.talent_rules import (
    talent_node_for_reference,
    talent_tree_nodes,
    tree_definition,
)
from ..advancement.skill_rules import (
    available_skill_keys,
    effective_skill_effect,
    skill_cost,
    skill_definition,
    skill_mastery_rules,
    skill_resource_definition,
)
from ..advancement.equipment_rules import (
    EQUIPMENT_DEFINITIONS,
    equipment_definition,
    equipment_meets_path,
    equipment_meets_realm,
    refinement_affix,
    refinement_cost,
    refinement_pity_failures,
    refinement_roll_bp,
    refinement_success_bp,
    temper_cost,
    temper_roll_bp,
    temper_success_bp,
)
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
from ..routine.wayfaring import (
    WAYFARING_DAILY_POINT_CAP,
    WAYFARING_LEVELS,
    WAYFARING_PASS_KEY,
    WAYFARING_POINTS_PER_LEVEL,
    WAYFARING_WEEKLY_POINT_CAP,
    wayfaring_free_reward,
    wayfaring_paid_reward,
    wayfaring_source_points,
    wayfaring_week_start,
)
from ..routine.billing import BillingReceiptError, verify_receipt
from ..routine.gacha import (
    FATE_PITY_LIMIT,
    FATE_POOL_KEY,
    FATE_SINGLE_COST,
    FATE_TEN_COST,
    FATE_TICKET,
    reward_totals,
    roll_fate_pool,
)
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
    tree_harvest_reward,
    tree_status,
)

from ..persistence.errors import *  # noqa: F401,F403
from ..utils.assets import (
    inventory_json,
    spend_player_items,
    spend_player_assets,
    assets_spend,
    player_asset_amount,
)
from ..utils.player import change_player_state, player_integer, player_inventory


class AdvancementRepositoryMixin:
    async def start_retreat(
        self,
        *,
        platform: str,
        platform_user_id: str,
        retreat_key: str,
        operation_id: str,
    ) -> RetreatSessionRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._start_retreat_sync,
                platform,
                platform_user_id,
                retreat_key,
                operation_id,
            )

    def _start_retreat_sync(
        self,
        platform: str,
        platform_user_id: str,
        retreat_key: str,
        operation_id: str,
    ) -> RetreatSessionRecord:
        last_error: Exception | None = None
        for attempt in range(5):
            try:
                return self._start_retreat_once(platform, platform_user_id, retreat_key, operation_id)
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).lower():
                    raise
                if attempt == 4:
                    raise RepositoryBusyError("database remained locked") from exc
                last_error = exc
                time.sleep(0.01 * (2**attempt))
        raise RepositoryBusyError("database remained locked") from last_error

    def _start_retreat_once(
        self,
        platform: str,
        platform_user_id: str,
        retreat_key: str,
        operation_id: str,
    ) -> RetreatSessionRecord:
        try:
            definition = retreat_definition(retreat_key)
        except ValueError as exc:
            raise RetreatContentClosedError("unsupported retreat") from exc
        operation_name = "progression.start_retreat"
        request_hash = self._request_hash(
            operation_name,
            {
                "platform": platform,
                "platform_user_id": platform_user_id,
                "retreat_key": definition.key,
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
                return self._retreat_start_from_payload(json.loads(existing["result_json"]), replay=True)

            row = self._require_player(connection, platform, platform_user_id)
            if definition.key == RETREAT_BASIC:
                if str(row["stage"]) != "cultivator":
                    raise PlayerStageConflictError("basic retreat requires entry into cultivation")
            elif str(row["stage"]) not in {STAGE_MORTAL, "seeker", "cultivator"}:
                raise PlayerStageConflictError("restful retreat requires a mortal-stage player")

            if self._has_active_long_action(connection, int(row["id"])):
                raise RetreatBusyError("another long action is active")

            active_residence = connection.execute(
                "SELECT * FROM residences WHERE player_id = ? AND status = 'active' ORDER BY id DESC LIMIT 1",
                (row["id"],),
            ).fetchone()
            if active_residence is not None and now >= datetime.fromisoformat(str(active_residence["ends_at"])):
                connection.execute(
                    "UPDATE residences SET status = 'expired', updated_at = ? WHERE id = ? AND status = 'active'",
                    (now_text, active_residence["id"]),
                )
                active_residence = None
            if definition.key == RETREAT_RESTFUL and active_residence is None:
                raise ResidenceRequiredError("restful retreat requires an active residence")

            day_start = serialize_datetime(now.replace(hour=0, minute=0, second=0, microsecond=0))
            used = connection.execute(
                "SELECT COUNT(*) AS count FROM retreat_sessions WHERE player_id = ? AND retreat_key = ? AND starts_at >= ?",
                (row["id"], definition.key, day_start),
            ).fetchone()
            if used is not None and int(used["count"]) >= definition.daily_limit:
                raise RetreatDailyLimitError("retreat daily limit reached")

            inventory = player_inventory(row)
            item_cost = definition.item_cost_map()
            if definition.required_item:
                content = self.content or bundled_content()
                manual = content.require("item", definition.required_item, include_locked=False)
                permissions = [
                    effect.get("target")
                    for effect in manual.get("effects", [])
                    if isinstance(effect, dict) and effect.get("type") == "cultivation_permission"
                ]
                if not permissions or not manual_grants_permission(inventory, str(permissions[0]), content):
                    raise ResourceInsufficientError("retreat cultivation manual is missing")
            for item_key, quantity in item_cost.items():
                if int(inventory.get(item_key, 0)) < quantity:
                    raise ResourceInsufficientError("retreat item is insufficient")
            if player_integer(row, "energy") < definition.energy_cost:
                raise ResourceInsufficientError("energy is insufficient")
            seed = f"{definition.random_pool or definition.key}:{operation_id}"
            snapshot = {
                "retreat_key": definition.key,
                "random_pool": definition.random_pool,
                "random_seed": seed,
                "realm_key": str(row["realm_key"]),
                "realm_layer": player_integer(row, "realm_layer"),
                "path_key": row["path_key"],
                "subprofession_key": row["subprofession_key"],
                "qualification": self._json_object(row["qualification_json"], {}),
                "residence_key": active_residence["residence_key"] if active_residence is not None else None,
                "energy_before": player_integer(row, "energy"),
                "item_cost": item_cost,
            }
            session_id = uuid4().hex
            starts_at = now_text
            ends_at = serialize_datetime(now + timedelta(seconds=definition.duration_seconds))
            change_player_state(
                connection,
                row,
                updated_at=now_text,
                asset_values=item_cost,
                asset_mode="spend",
                value_delta={"energy": -definition.energy_cost},
            )
            connection.execute(
                """
                INSERT INTO retreat_sessions(
                    session_id, player_id, operation_id, retreat_key, status,
                    starts_at, ends_at, energy_cost, item_cost_json, snapshot_json,
                    result_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'running', ?, ?, ?, ?, ?, '{}', ?, ?)
                """,
                (
                    session_id,
                    row["id"],
                    operation_id,
                    definition.key,
                    starts_at,
                    ends_at,
                    definition.energy_cost,
                    json.dumps(item_cost, ensure_ascii=False, sort_keys=True),
                    json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
                    starts_at,
                    starts_at,
                ),
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (row["id"],)).fetchone()
            if updated is None:
                raise RuntimeError("retreat start returned no player")
            payload = {
                "player": self._player_payload(self._row_to_player(updated)),
                "session_id": session_id,
                "retreat_key": definition.key,
                "status": "running",
                "starts_at": starts_at,
                "ends_at": ends_at,
                "energy_cost": definition.energy_cost,
                "item_cost": item_cost,
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
            return self._retreat_start_from_payload(payload)

    async def settle_retreat(
        self,
        *,
        platform: str,
        platform_user_id: str,
        operation_id: str,
        recover: bool = False,
    ) -> RetreatSettlementRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._settle_retreat_sync,
                platform,
                platform_user_id,
                operation_id,
                recover,
            )

    def _settle_retreat_sync(
        self,
        platform: str,
        platform_user_id: str,
        operation_id: str,
        recover: bool,
    ) -> RetreatSettlementRecord:
        last_error: Exception | None = None
        for attempt in range(5):
            try:
                return self._settle_retreat_once(platform, platform_user_id, operation_id, recover)
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).lower():
                    raise
                if attempt == 4:
                    raise RepositoryBusyError("database remained locked") from exc
                last_error = exc
                time.sleep(0.01 * (2**attempt))
        raise RepositoryBusyError("database remained locked") from last_error

    def _settle_retreat_once(
        self,
        platform: str,
        platform_user_id: str,
        operation_id: str,
        recover: bool,
    ) -> RetreatSettlementRecord:
        operation_name = "progression.recover_retreat" if recover else "progression.settle_retreat"
        request_hash = self._request_hash(operation_name, {"platform": platform, "platform_user_id": platform_user_id})
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
                return self._retreat_settlement_from_payload(json.loads(existing["result_json"]), replay=True)
            row = self._require_player(connection, platform, platform_user_id)
            session = connection.execute(
                "SELECT * FROM retreat_sessions WHERE player_id = ? AND status IN ('running', 'expired') ORDER BY id DESC LIMIT 1",
                (row["id"],),
            ).fetchone()
            if session is None:
                latest = connection.execute(
                    "SELECT status FROM retreat_sessions WHERE player_id = ? ORDER BY id DESC LIMIT 1",
                    (row["id"],),
                ).fetchone()
                if latest is not None and str(latest["status"]) == "settled":
                    raise RetreatAlreadySettledError("retreat already settled")
                raise RetreatNotFoundError("no active retreat")
            if session["status"] == "expired" and not recover:
                raise RetreatExpiredError("retreat requires recovery")
            starts_at = datetime.fromisoformat(str(session["starts_at"]))
            ends_at = datetime.fromisoformat(str(session["ends_at"]))
            if session["status"] == "running" and now < ends_at:
                raise RetreatNotReadyError("retreat is not ready")
            if session["status"] == "running" and now > ends_at + timedelta(seconds=MAX_OFFLINE_SECONDS):
                connection.execute(
                    "UPDATE retreat_sessions SET status = 'expired', result_json = ?, updated_at = ? WHERE id = ? AND status = 'running'",
                    (
                        json.dumps({"expired_at": now_text, "recovery_pending": True}, ensure_ascii=False, sort_keys=True),
                        now_text,
                        session["id"],
                    ),
                )
                connection.commit()
                raise RetreatExpiredError("retreat settlement window expired")
            snapshot = self._json_object(session["snapshot_json"], {})
            definition = retreat_definition(str(snapshot.get("retreat_key", session["retreat_key"])))
            elapsed = max(definition.duration_seconds, int((now - starts_at).total_seconds()))
            capped = min(MAX_SETTLEMENT_SECONDS, elapsed)
            cycles = max(1, min(4, capped // definition.duration_seconds))
            result = retreat_reward(definition.key, str(snapshot.get("random_seed", operation_id)))
            result = {key: int(value) * cycles for key, value in result.items()}
            cultivation_gain = int(result.get("cultivation", 0))
            energy_gain = int(result.get("energy", 0))
            change_player_state(
                connection,
                row,
                updated_at=now_text,
                value_delta={
                    "cultivation": cultivation_gain,
                    "total_cultivation": cultivation_gain,
                    "energy": energy_gain,
                },
                maximums={"energy": row["energy_max"]},
            )
            result_payload = {"result": result, "cycles": cycles, "expired": bool(recover), "settled_at": now_text}
            connection.execute(
                "UPDATE retreat_sessions SET status = 'settled', result_json = ?, updated_at = ? WHERE id = ? AND status IN ('running', 'expired')",
                (json.dumps(result_payload, ensure_ascii=False, sort_keys=True), now_text, session["id"]),
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (row["id"],)).fetchone()
            if updated is None:
                raise RuntimeError("retreat settlement returned no player")
            payload = {
                "player": self._player_payload(self._row_to_player(updated)),
                "session_id": session["session_id"],
                "retreat_key": definition.key,
                "status": "settled",
                "result": result,
                "cycles": cycles,
                "expired": bool(recover),
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
            return self._retreat_settlement_from_payload(payload)

    @staticmethod
    def _constitution_from_payload(payload: dict[str, Any], *, replay: bool = False) -> ConstitutionRecord:
        return ConstitutionRecord(
            player=SQLitePlayerRepository._row_to_player(payload["player"]),
            constitution_key=str(payload["constitution_key"]),
            label=str(payload["label"]),
            description=str(payload["description"]),
            effect={str(key): value for key, value in dict(payload.get("effect", {})).items()},
            status=str(payload.get("status", "selected")),
            selected_at=str(payload.get("selected_at", "")),
            last_reshaped_at=payload.get("last_reshaped_at"),
            reshape_count=int(payload.get("reshape_count", 0)),
            already_completed=replay,
        )

    def _constitution_from_row(
        self,
        player_row: sqlite3.Row,
        profile_row: sqlite3.Row,
        *,
        replay: bool = False,
    ) -> ConstitutionRecord:
        definition = constitution_definition(str(profile_row["constitution_key"]), self.content)
        return ConstitutionRecord(
            player=SQLitePlayerRepository._row_to_player(player_row),
            constitution_key=definition.key,
            label=definition.label,
            description=definition.description,
            effect=dict(definition.effect),
            status=str(profile_row["status"]),
            selected_at=str(profile_row["selected_at"]),
            last_reshaped_at=(
                str(profile_row["last_reshaped_at"])
                if profile_row["last_reshaped_at"]
                else None
            ),
            reshape_count=int(profile_row["reshape_count"]),
            already_completed=replay,
        )

    async def select_constitution(
        self,
        *,
        platform: str,
        platform_user_id: str,
        constitution_key: str,
        operation_id: str,
    ) -> ConstitutionRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._select_constitution_sync,
                platform,
                platform_user_id,
                constitution_key,
                operation_id,
            )

    def _select_constitution_sync(
        self,
        platform: str,
        platform_user_id: str,
        constitution_key: str,
        operation_id: str,
    ) -> ConstitutionRecord:
        last_error: Exception | None = None
        for attempt in range(5):
            try:
                return self._select_constitution_once(
                    platform,
                    platform_user_id,
                    constitution_key,
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

    def _select_constitution_once(
        self,
        platform: str,
        platform_user_id: str,
        constitution_key: str,
        operation_id: str,
    ) -> ConstitutionRecord:
        try:
            definition = constitution_definition(constitution_key, self.content)
        except ValueError as exc:
            raise ValueError("unsupported constitution") from exc
        operation_name = "constitution.select"
        request_hash = self._request_hash(
            operation_name,
            {
                "platform": platform,
                "platform_user_id": platform_user_id,
                "constitution_key": definition.key,
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
                return self._constitution_from_payload(json.loads(existing["result_json"]), replay=True)

            row = self._require_player(connection, platform, platform_user_id)
            if str(row["stage"]) != "cultivator" or not row["path_key"]:
                raise PlayerStageConflictError("constitution requires entry into cultivation")
            if self._has_active_long_action(connection, int(row["id"])):
                raise ConstitutionBusyError("another long action is active")
            profile = connection.execute(
                "SELECT 1 FROM constitution_profiles WHERE player_id = ? LIMIT 1",
                (row["id"],),
            ).fetchone()
            if profile is not None:
                raise ConstitutionAlreadySelectedError("constitution is already selected")

            snapshot = {
                "constitution_key": definition.key,
                "effect": dict(definition.effect),
                "qualification": self._json_object(row["qualification_json"], {}),
                "path_key": row["path_key"],
                "subprofession_key": row["subprofession_key"],
                "realm_key": row["realm_key"],
                "realm_layer": player_integer(row, "realm_layer"),
                "location_key": row["location_key"],
            }
            profile_id = uuid4().hex
            connection.execute(
                """
                INSERT INTO constitution_profiles(
                    profile_id, player_id, operation_id, constitution_key, status,
                    selected_at, last_reshaped_at, reshape_count, snapshot_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'selected', ?, NULL, 0, ?, ?, ?)
                """,
                (
                    profile_id,
                    row["id"],
                    operation_id,
                    definition.key,
                    now_text,
                    json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
                    now_text,
                    now_text,
                ),
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (row["id"],)).fetchone()
            if updated is None:
                raise RuntimeError("constitution selection returned no player")
            payload = {
                "player": self._player_payload(self._row_to_player(updated)),
                "constitution_key": definition.key,
                "label": definition.label,
                "description": definition.description,
                "effect": dict(definition.effect),
                "status": "selected",
                "selected_at": now_text,
                "last_reshaped_at": None,
                "reshape_count": 0,
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
            return self._constitution_from_payload(payload)

    async def get_constitution(self, *, platform: str, platform_user_id: str) -> ConstitutionRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._get_constitution_sync, platform, platform_user_id)

    def _get_constitution_sync(self, platform: str, platform_user_id: str) -> ConstitutionRecord:
        with self._connect() as connection:
            row = self._require_player(connection, platform, platform_user_id, writable=False)
            profile = connection.execute(
                "SELECT * FROM constitution_profiles WHERE player_id = ? LIMIT 1",
                (row["id"],),
            ).fetchone()
            if profile is None:
                raise ConstitutionNotFoundError("constitution is not selected")
            return self._constitution_from_row(row, profile)

    async def reshape_constitution(
        self,
        *,
        platform: str,
        platform_user_id: str,
        constitution_key: str,
        operation_id: str,
    ) -> ConstitutionRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._reshape_constitution_sync,
                platform,
                platform_user_id,
                constitution_key,
                operation_id,
            )

    def _reshape_constitution_sync(
        self,
        platform: str,
        platform_user_id: str,
        constitution_key: str,
        operation_id: str,
    ) -> ConstitutionRecord:
        last_error: Exception | None = None
        for attempt in range(5):
            try:
                return self._reshape_constitution_once(
                    platform,
                    platform_user_id,
                    constitution_key,
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

    def _reshape_constitution_once(
        self,
        platform: str,
        platform_user_id: str,
        constitution_key: str,
        operation_id: str,
    ) -> ConstitutionRecord:
        try:
            definition = constitution_definition(constitution_key, self.content)
        except ValueError as exc:
            raise ValueError("unsupported constitution") from exc
        operation_name = "constitution.reshape"
        request_hash = self._request_hash(
            operation_name,
            {
                "platform": platform,
                "platform_user_id": platform_user_id,
                "constitution_key": definition.key,
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
                return self._constitution_from_payload(json.loads(existing["result_json"]), replay=True)

            row = self._require_player(connection, platform, platform_user_id)
            if str(row["stage"]) != "cultivator" or not row["path_key"]:
                raise PlayerStageConflictError("constitution requires entry into cultivation")
            if self._has_active_long_action(connection, int(row["id"])):
                raise ConstitutionBusyError("another long action is active")
            profile = connection.execute(
                "SELECT * FROM constitution_profiles WHERE player_id = ? LIMIT 1",
                (row["id"],),
            ).fetchone()
            if profile is None:
                raise ConstitutionNotFoundError("constitution is not selected")
            if str(profile["constitution_key"]) == definition.key:
                raise ConstitutionSameError("constitution target is already active")
            if profile["last_reshaped_at"]:
                last_reshaped_at = datetime.fromisoformat(str(profile["last_reshaped_at"]))
                reshape_rules = constitution_reshape_rules(self.content)
                if now < last_reshaped_at + timedelta(seconds=int(reshape_rules["cooldown_seconds"])):
                    raise ConstitutionCooldownError("constitution reshape cooldown is active")
            inventory = player_inventory(row)
            reset_item_key = str(constitution_reshape_rules(self.content)["reset_item_key"])
            if int(inventory.get(reset_item_key, 0)) < 1:
                raise ResourceInsufficientError("constitution reset token is missing")
            snapshot = {
                "constitution_key": definition.key,
                "effect": dict(definition.effect),
                "qualification": self._json_object(row["qualification_json"], {}),
                "path_key": row["path_key"],
                "subprofession_key": row["subprofession_key"],
                "realm_key": row["realm_key"],
                "realm_layer": player_integer(row, "realm_layer"),
                "location_key": row["location_key"],
            }
            reshape_count = int(profile["reshape_count"]) + 1
            connection.execute(
                """
                UPDATE constitution_profiles
                SET constitution_key = ?, last_reshaped_at = ?, reshape_count = ?,
                    snapshot_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    definition.key,
                    now_text,
                    reshape_count,
                    json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
                    now_text,
                    profile["id"],
                ),
            )
            spend_player_assets(connection, row, {reset_item_key: 1}, now_text)
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (row["id"],)).fetchone()
            if updated is None:
                raise RuntimeError("constitution reshape returned no player")
            payload = {
                "player": self._player_payload(self._row_to_player(updated)),
                "constitution_key": definition.key,
                "label": definition.label,
                "description": definition.description,
                "effect": dict(definition.effect),
                "status": "selected",
                "selected_at": str(profile["selected_at"]),
                "last_reshaped_at": now_text,
                "reshape_count": reshape_count,
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
            return self._constitution_from_payload(payload)

    @staticmethod
    def _talent_node_from_payload(
        payload: dict[str, Any], *, replay: bool = False
    ) -> TalentNodeRecord:
        return TalentNodeRecord(
            node_key=str(payload["node_key"]),
            tree_key=str(payload["tree_key"]),
            tier=int(payload["tier"]),
            label=str(payload["label"]),
            description=str(payload["description"]),
            effect={str(key): value for key, value in dict(payload.get("effect", {})).items()},
            cost_points=int(payload.get("cost_points", 0)),
            status=str(payload.get("status", "learned")),
            unlocked_at=str(payload.get("unlocked_at", "")),
            already_completed=replay,
            player=(SQLitePlayerRepository._row_to_player(payload["player"]) if payload.get("player") else None),
        )

    def _talent_node_from_row(
        self, node_row: sqlite3.Row, *, replay: bool = False
    ) -> TalentNodeRecord:
        definition = talent_node_for_reference(str(node_row["node_key"]), content=self.content)
        return TalentNodeRecord(
            node_key=definition.key,
            tree_key=definition.tree_key,
            tier=definition.tier,
            label=definition.label,
            description=definition.description,
            effect=dict(definition.effect),
            cost_points=int(node_row["cost_points"]),
            status=str(node_row["status"]),
            unlocked_at=str(node_row["unlocked_at"]),
            already_completed=replay,
        )

    async def get_talent_profile(
        self,
        *,
        platform: str,
        platform_user_id: str,
    ) -> TalentProfileRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._get_talent_profile_sync,
                platform,
                platform_user_id,
            )

    def _get_talent_profile_sync(
        self,
        platform: str,
        platform_user_id: str,
    ) -> TalentProfileRecord:
        with self._connect() as connection:
            row = self._require_player(connection, platform, platform_user_id, writable=False)
            if str(row["stage"]) != "cultivator" or not row["path_key"]:
                raise PlayerStageConflictError("talent profile requires entry into cultivation")
            tree_key, tree_label = tree_definition(str(row["path_key"]), self.content)
            node_rows = connection.execute(
                "SELECT * FROM talent_node_states WHERE player_id = ? AND tree_key = ? ORDER BY tier",
                (row["id"], tree_key),
            ).fetchall()
            nodes = tuple(self._talent_node_from_row(node) for node in node_rows)
            spent = sum(node.cost_points for node in nodes)
            return TalentProfileRecord(
                player=self._row_to_player(row),
                tree_key=tree_key,
                tree_label=tree_label,
                nodes=nodes,
                points_available=int(row["talent_points"]),
                points_spent=spent,
            )

    async def unlock_talent(
        self,
        *,
        platform: str,
        platform_user_id: str,
        node_reference: str,
        operation_id: str,
    ) -> TalentNodeRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._unlock_talent_sync,
                platform,
                platform_user_id,
                node_reference,
                operation_id,
            )

    def _unlock_talent_sync(
        self,
        platform: str,
        platform_user_id: str,
        node_reference: str,
        operation_id: str,
    ) -> TalentNodeRecord:
        last_error: Exception | None = None
        for attempt in range(5):
            try:
                return self._unlock_talent_once(
                    platform,
                    platform_user_id,
                    node_reference,
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

    def _unlock_talent_once(
        self,
        platform: str,
        platform_user_id: str,
        node_reference: str,
        operation_id: str,
    ) -> TalentNodeRecord:
        normalized_reference = node_reference.strip()
        operation_name = "talent.unlock_node"
        request_hash = self._request_hash(
            operation_name,
            {
                "platform": platform,
                "platform_user_id": platform_user_id,
                "node_reference": normalized_reference,
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
                return self._talent_node_from_payload(json.loads(existing["result_json"]), replay=True)

            row = self._require_player(connection, platform, platform_user_id)
            if str(row["stage"]) != "cultivator" or not row["path_key"]:
                raise PlayerStageConflictError("talent requires entry into cultivation")
            tree_key, _ = tree_definition(str(row["path_key"]), self.content)
            if normalized_reference.startswith("talent.tree."):
                definition = talent_node_for_reference(normalized_reference, content=self.content)
                if definition.tree_key != tree_key:
                    raise TalentPathMismatchError("talent tree does not match primary path")
            else:
                definition = talent_node_for_reference(
                    normalized_reference,
                    tree_key=tree_key,
                    content=self.content,
                )
            if self._has_active_long_action(connection, int(row["id"])):
                raise TalentBusyError("another long action is active")
            existing_node = connection.execute(
                "SELECT 1 FROM talent_node_states WHERE player_id = ? AND node_key = ? LIMIT 1",
                (row["id"], definition.key),
            ).fetchone()
            if existing_node is not None:
                raise TalentNodeAlreadyLearnedError("talent node is already learned")
            for prerequisite_key in definition.prerequisites:
                prerequisite = connection.execute(
                    "SELECT 1 FROM talent_node_states WHERE player_id = ? AND node_key = ? LIMIT 1",
                    (row["id"], prerequisite_key),
                ).fetchone()
                if prerequisite is None:
                    raise TalentPrerequisiteError("talent prerequisites are not learned")

            points_before = int(row["talent_points"])
            if points_before < definition.cost_points:
                raise ResourceInsufficientError("talent points are insufficient")
            points_after = points_before - definition.cost_points
            constitution = connection.execute(
                "SELECT constitution_key, snapshot_json FROM constitution_profiles WHERE player_id = ? LIMIT 1",
                (row["id"],),
            ).fetchone()
            snapshot = {
                "node_key": definition.key,
                "tree_key": definition.tree_key,
                "tier": definition.tier,
                "effect": dict(definition.effect),
                "qualification": self._json_object(row["qualification_json"], {}),
                "path_key": row["path_key"],
                "subprofession_key": row["subprofession_key"],
                "realm_key": row["realm_key"],
                "realm_layer": player_integer(row, "realm_layer"),
                "location_key": row["location_key"],
                "constitution_key": str(constitution["constitution_key"]) if constitution else None,
            }
            node_id = uuid4().hex
            connection.execute(
                """
                INSERT INTO talent_node_states(
                    node_id, player_id, operation_id, node_key, tree_key, tier,
                    status, cost_points, snapshot_json, unlocked_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'learned', ?, ?, ?, ?, ?)
                """,
                (
                    node_id,
                    row["id"],
                    operation_id,
                    definition.key,
                    definition.tree_key,
                    definition.tier,
                    definition.cost_points,
                    json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
                    now_text,
                    now_text,
                    now_text,
                ),
            )
            if definition.cost_points:
                change_player_state(
                    connection,
                    row,
                    updated_at=now_text,
                    player_values={"talent_points": points_after},
                )
                connection.execute(
                    """
                    INSERT INTO talent_point_events(
                        event_id, player_id, operation_id, delta, balance_before,
                        balance_after, reason, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        uuid4().hex,
                        row["id"],
                        f"{operation_id}:talent-point",
                        -definition.cost_points,
                        points_before,
                        points_after,
                        f"unlock:{definition.key}",
                        now_text,
                    ),
                )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (row["id"],)).fetchone()
            if updated is None:
                raise RuntimeError("talent unlock returned no player")
            payload = {
                "player": self._player_payload(self._row_to_player(updated)),
                "node_key": definition.key,
                "tree_key": definition.tree_key,
                "tier": definition.tier,
                "label": definition.label,
                "description": definition.description,
                "effect": dict(definition.effect),
                "cost_points": definition.cost_points,
                "unlocked_at": now_text,
                "talent_points_before": points_before,
                "talent_points_after": points_after,
                "status": "learned",
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
            return self._talent_node_from_payload(payload)

    @staticmethod
    def _skill_mastery_from_payload(
        payload: dict[str, Any], *, replay: bool = False
    ) -> SkillMasteryRecord:
        return SkillMasteryRecord(
            player=(SQLitePlayerRepository._row_to_player(payload["player"]) if payload.get("player") else None),
            skill_key=str(payload["skill_key"]),
            label=str(payload["label"]),
            path_key=payload.get("path_key"),
            level=int(payload["level"]),
            max_level=int(payload["max_level"]),
            base_effect={str(key): value for key, value in dict(payload.get("base_effect", {})).items()},
            effective_effect={str(key): value for key, value in dict(payload.get("effective_effect", {})).items()},
            resource_costs={str(key): int(value) for key, value in dict(payload["resource_costs"]).items()},
            trained_at=str(payload.get("trained_at", "")),
            already_completed=replay,
        )

    def _skill_mastery_from_row(
        self,
        mastery_row: sqlite3.Row,
        *,
        replay: bool = False,
    ) -> SkillMasteryRecord:
        definition = skill_definition(str(mastery_row["skill_key"]), self.content)
        snapshot = SQLitePlayerRepository._json_object(mastery_row["snapshot_json"], {})
        return SkillMasteryRecord(
            player=None,
            skill_key=str(mastery_row["skill_key"]),
            label=definition.label,
            path_key=definition.path_key,
            level=int(mastery_row["level"]),
            max_level=definition.max_level,
            base_effect={str(key): value for key, value in dict(snapshot.get("base_effect", definition.effect)).items()},
            effective_effect={
                str(key): value
                for key, value in dict(
                    snapshot.get(
                        "effective_effect",
                        effective_skill_effect(definition, int(mastery_row["level"])),
                    )
                ).items()
            },
            trained_at=str(mastery_row["trained_at"]),
            already_completed=replay,
        )

    @staticmethod
    def _equipment_from_payload(
        payload: dict[str, Any], *, replay: bool = False
    ) -> EquipmentRecord:
        return EquipmentRecord(
            instance_id=str(payload["instance_id"]),
            item_key=str(payload["item_key"]),
            label=str(payload["label"]),
            slot=str(payload["slot"]),
            status=str(payload.get("status", "active")),
            durability_bp=int(payload.get("durability_bp", 10000)),
            temper_level=int(payload.get("temper_level", 0)),
            max_temper_level=int(payload["max_temper_level"]),
            affixes={str(key): int(value) for key, value in dict(payload.get("affixes", {})).items()},
            refinement_failure_streak=int(payload.get("refinement_failure_streak", 0)),
        )

    @staticmethod
    def _equipment_from_row(row: sqlite3.Row, *, replay: bool = False) -> EquipmentRecord:
        definition = EQUIPMENT_DEFINITIONS.get(str(row["item_key"]))
        return EquipmentRecord(
            instance_id=str(row["instance_id"]),
            item_key=str(row["item_key"]),
            label=str(row["label"] or (definition.label if definition else row["item_key"])),
            slot=str(row["slot"] or (definition.slot if definition else "unknown")),
            status=str(row["status"]),
            durability_bp=int(row["durability_bp"]),
            temper_level=int(row["temper_level"]),
            max_temper_level=int(row["max_temper_level"]),
            affixes={
                str(key): int(value)
                for key, value in SQLitePlayerRepository._json_object(row["affixes_json"], {}).items()
            },
            refinement_failure_streak=int(row["refinement_failure_streak"]),
        )

    @staticmethod
    def _tempering_from_payload(
        payload: dict[str, Any], *, replay: bool = False
    ) -> TemperingRecord:
        return TemperingRecord(
            player=SQLitePlayerRepository._row_to_player(payload["player"]),
            equipment=SQLitePlayerRepository._equipment_from_payload(payload["equipment"]),
            from_level=int(payload["from_level"]),
            to_level=int(payload["to_level"]),
            success=bool(payload["success"]),
            roll_bp=int(payload["roll_bp"]),
            success_bp=int(payload["success_bp"]),
            costs_spent={str(key): int(value) for key, value in dict(payload["costs_spent"]).items()},
            already_completed=replay,
        )

    @staticmethod
    def _refinement_from_payload(
        payload: dict[str, Any], *, replay: bool = False
    ) -> RefinementRecord:
        return RefinementRecord(
            player=SQLitePlayerRepository._row_to_player(payload["player"]),
            equipment=SQLitePlayerRepository._equipment_from_payload(payload["equipment"]),
            old_affixes={str(key): int(value) for key, value in dict(payload.get("old_affixes", {})).items()},
            new_affixes={str(key): int(value) for key, value in dict(payload.get("new_affixes", {})).items()},
            success=bool(payload["success"]),
            roll_bp=int(payload["roll_bp"]),
            success_bp=int(payload["success_bp"]),
            costs_spent={str(key): int(value) for key, value in dict(payload["costs_spent"]).items()},
            failure_streak_before=int(payload["failure_streak_before"]),
            failure_streak_after=int(payload["failure_streak_after"]),
            already_completed=replay,
        )

    @staticmethod
    def _materialize_equipment(
        connection: sqlite3.Connection,
        player: sqlite3.Row,
        definition: Any,
        now_text: str,
    ) -> sqlite3.Row:
        """Convert legacy unique-item inventory entries into stable instances."""

        rows = connection.execute(
            "SELECT * FROM equipment_instances WHERE player_id = ? AND item_key = ? AND status = 'active' ORDER BY id",
            (player["id"], definition.key),
        ).fetchall()
        if rows:
            return rows[0] if len(rows) == 1 else player
        inventory = player_inventory(player)
        quantity = int(inventory.get(definition.key, 0))
        if quantity <= 0:
            return player
        durability = SQLitePlayerRepository._json_object(player["durability_json"], {})
        durability_bp = int(durability.get(definition.key, 10000))
        for _ in range(quantity):
            connection.execute(
                """
                INSERT INTO equipment_instances(
                    instance_id, player_id, item_key, label, slot, status,
                    durability_bp, temper_level, max_temper_level, affixes_json,
                    refinement_failure_streak, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'active', ?, 0, ?, '{}', 0, ?, ?)
                """,
                (
                    uuid4().hex,
                    player["id"],
                    definition.key,
                    definition.label,
                    definition.slot,
                    max(0, durability_bp),
                    definition.max_temper_level,
                    now_text,
                    now_text,
                ),
            )
        spend_player_items(connection, player, {definition.key: quantity}, now_text)
        return connection.execute(
            "SELECT * FROM equipment_instances WHERE player_id = ? AND item_key = ? AND status = 'active' ORDER BY id LIMIT 1",
            (player["id"], definition.key),
        ).fetchone()

    def _resolve_equipment(
        self,
        connection: sqlite3.Connection,
        player: sqlite3.Row,
        equipment_reference: str,
        now_text: str,
    ) -> sqlite3.Row:
        definition = equipment_definition(equipment_reference, self.content)
        self._materialize_equipment(connection, player, definition, now_text)
        rows = connection.execute(
            "SELECT * FROM equipment_instances WHERE player_id = ? AND item_key = ? AND status = 'active' ORDER BY id",
            (player["id"], definition.key),
        ).fetchall()
        if not rows:
            raise EquipmentNotOwnedError("equipment is not owned")
        if len(rows) > 1:
            raise EquipmentAmbiguousError("multiple equipment instances match")
        return rows[0]

    @staticmethod
    def _equipment_source_exists(
        connection: sqlite3.Connection,
        player: sqlite3.Row,
        definition: Any,
    ) -> bool:
        instance = connection.execute(
            "SELECT 1 FROM equipment_instances WHERE player_id = ? AND item_key = ? AND status = 'active' LIMIT 1",
            (player["id"], definition.key),
        ).fetchone()
        if instance is not None:
            return True
        inventory = player_inventory(player)
        return int(inventory.get(definition.key, 0)) > 0

    @staticmethod
    def _consume_equipment_costs(
        player: sqlite3.Row,
        inventory: dict[str, Any],
        costs: dict[str, int],
    ) -> tuple[dict[str, Any], int, str, int, int]:
        item_keys = sorted(key for key in costs if key.startswith("item."))
        item_total = sum(int(costs[key]) for key in item_keys)
        stones_spent = int(costs.get("currency.spirit_stone", 0))

        if any(key != "currency.spirit_stone" and not key.startswith("item.") for key in costs):
            raise RuntimeError("unsupported configured equipment resource")
        try:
            remaining = assets_spend(
                player_asset_amount(player, "spirit_stones"),
                inventory,
                costs,
                currency_key="currency.spirit_stone",
            )
        except ValueError as exc:
            raise ResourceInsufficientError("equipment materials are insufficient") from exc

        material_key = item_keys[0] if item_keys else ""
        return remaining.inventory, remaining.currency, material_key, item_total, stones_spent

    async def temper_equipment(
        self,
        *,
        platform: str,
        platform_user_id: str,
        equipment_reference: str,
        operation_id: str,
    ) -> TemperingRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._temper_equipment_sync,
                platform,
                platform_user_id,
                equipment_reference,
                operation_id,
            )

    def _temper_equipment_sync(
        self,
        platform: str,
        platform_user_id: str,
        equipment_reference: str,
        operation_id: str,
    ) -> TemperingRecord:
        last_error: Exception | None = None
        for attempt in range(5):
            try:
                return self._temper_equipment_once(platform, platform_user_id, equipment_reference, operation_id)
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).lower():
                    raise
                if attempt == 4:
                    raise RepositoryBusyError("database remained locked") from exc
                last_error = exc
                time.sleep(0.01 * (2**attempt))
        raise RepositoryBusyError("database remained locked") from last_error

    def _temper_equipment_once(
        self,
        platform: str,
        platform_user_id: str,
        equipment_reference: str,
        operation_id: str,
    ) -> TemperingRecord:
        definition = equipment_definition(equipment_reference, self.content)
        operation_name = "item.tempering"
        request_hash = self._request_hash(
            operation_name,
            {
                "platform": platform,
                "platform_user_id": platform_user_id,
                "equipment_reference": equipment_reference.strip(),
                "item_key": definition.key,
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
                return self._tempering_from_payload(json.loads(existing["result_json"]), replay=True)
            player = self._require_player(connection, platform, platform_user_id)
            if str(player["stage"]) != "cultivator":
                raise PlayerStageConflictError("equipment tempering requires entry into cultivation")
            if not equipment_meets_path(definition, player["path_key"]):
                raise EquipmentRequirementError("equipment is restricted to another path")
            if not equipment_meets_realm(
                definition,
                str(player["realm_key"]),
                player_integer(player, "realm_layer"),
                self.content,
            ):
                raise EquipmentRequirementError("player realm does not meet equipment requirement")
            if self._has_active_long_action(connection, int(player["id"])):
                raise EquipmentBusyError("another long action is active")
            if not self._equipment_source_exists(connection, player, definition):
                raise EquipmentNotOwnedError("equipment is not owned")
            candidates = connection.execute(
                "SELECT * FROM equipment_instances WHERE player_id = ? AND item_key = ? AND status = 'active' ORDER BY id",
                (player["id"], definition.key),
            ).fetchall()
            if len(candidates) > 1:
                raise EquipmentAmbiguousError("multiple equipment instances match")
            candidate = candidates[0] if candidates else None
            from_level = int(candidate["temper_level"]) if candidate is not None else 0
            max_level = int(candidate["max_temper_level"]) if candidate is not None else definition.max_temper_level
            if from_level >= max_level:
                raise EquipmentTemperingMaxedError("equipment has reached maximum temper level")
            target_level = from_level + 1
            costs = temper_cost(target_level, definition)
            equipment = self._resolve_equipment(connection, player, equipment_reference, now_text)
            player = connection.execute("SELECT * FROM players WHERE id = ?", (player["id"],)).fetchone()
            if player is None:
                raise PlayerNotFoundError("player disappeared during equipment resolution")
            inventory = player_inventory(player)
            inventory, stones_after, material_key, material_spent, stones_spent = self._consume_equipment_costs(
                player, inventory, costs
            )
            roll_bp = temper_roll_bp(f"{operation_id}:{equipment['instance_id']}:{target_level}")
            success_bp = temper_success_bp(target_level, definition)
            success = roll_bp < success_bp
            level_after = target_level if success else from_level
            spend_player_assets(
                connection,
                player,
                costs,
                now_text,
            )
            connection.execute(
                "UPDATE equipment_instances SET temper_level = ?, updated_at = ? WHERE id = ?",
                (level_after, now_text, equipment["id"]),
            )
            snapshot = {
                "item_key": definition.key,
                "from_level": from_level,
                "to_level": target_level,
                "level_after": level_after,
                "success": success,
                "roll_bp": roll_bp,
                "success_bp": success_bp,
                "costs_spent": costs,
                "material_key": material_key,
                "material_spent": material_spent,
                "spirit_stones_spent": stones_spent,
            }
            connection.execute(
                """
                INSERT INTO equipment_tempering_events(
                    event_id, player_id, equipment_id, operation_id, from_level,
                    to_level, success, roll_bp, success_bp, material_key,
                    material_spent, spirit_stones_spent, snapshot_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    uuid4().hex,
                    player["id"],
                    equipment["id"],
                    operation_id,
                    from_level,
                    target_level,
                    int(success),
                    roll_bp,
                    success_bp,
                    material_key,
                    material_spent,
                    stones_spent,
                    json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
                    now_text,
                ),
            )
            updated_equipment = connection.execute("SELECT * FROM equipment_instances WHERE id = ?", (equipment["id"],)).fetchone()
            updated_player = connection.execute("SELECT * FROM players WHERE id = ?", (player["id"],)).fetchone()
            if updated_equipment is None or updated_player is None:
                raise RuntimeError("equipment tempering returned no state")
            payload = {
                "player": self._player_payload(self._row_to_player(updated_player)),
                "equipment": {
                    "instance_id": updated_equipment["instance_id"],
                    "item_key": updated_equipment["item_key"],
                    "label": updated_equipment["label"],
                    "slot": updated_equipment["slot"],
                    "status": updated_equipment["status"],
                    "durability_bp": updated_equipment["durability_bp"],
                    "temper_level": updated_equipment["temper_level"],
                    "max_temper_level": updated_equipment["max_temper_level"],
                    "affixes": self._json_object(updated_equipment["affixes_json"], {}),
                    "refinement_failure_streak": updated_equipment["refinement_failure_streak"],
                },
                "from_level": from_level,
                "to_level": target_level,
                "success": success,
                "roll_bp": roll_bp,
                "success_bp": success_bp,
                "costs_spent": costs,
            }
            connection.execute(
                "INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (operation_id, operation_name, player["id"], request_hash, json.dumps(payload, ensure_ascii=False, sort_keys=True), now_text),
            )
            return self._tempering_from_payload(payload)

    async def refine_equipment(
        self,
        *,
        platform: str,
        platform_user_id: str,
        equipment_reference: str,
        operation_id: str,
    ) -> RefinementRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._refine_equipment_sync,
                platform,
                platform_user_id,
                equipment_reference,
                operation_id,
            )

    def _refine_equipment_sync(
        self,
        platform: str,
        platform_user_id: str,
        equipment_reference: str,
        operation_id: str,
    ) -> RefinementRecord:
        last_error: Exception | None = None
        for attempt in range(5):
            try:
                return self._refine_equipment_once(platform, platform_user_id, equipment_reference, operation_id)
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).lower():
                    raise
                if attempt == 4:
                    raise RepositoryBusyError("database remained locked") from exc
                last_error = exc
                time.sleep(0.01 * (2**attempt))
        raise RepositoryBusyError("database remained locked") from last_error

    def _refine_equipment_once(
        self,
        platform: str,
        platform_user_id: str,
        equipment_reference: str,
        operation_id: str,
    ) -> RefinementRecord:
        definition = equipment_definition(equipment_reference, self.content)
        operation_name = "item.refinement"
        request_hash = self._request_hash(
            operation_name,
            {
                "platform": platform,
                "platform_user_id": platform_user_id,
                "equipment_reference": equipment_reference.strip(),
                "item_key": definition.key,
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
                return self._refinement_from_payload(json.loads(existing["result_json"]), replay=True)
            player = self._require_player(connection, platform, platform_user_id)
            if str(player["stage"]) != "cultivator":
                raise PlayerStageConflictError("equipment refinement requires entry into cultivation")
            if not equipment_meets_path(definition, player["path_key"]):
                raise EquipmentRequirementError("equipment is restricted to another path")
            if not equipment_meets_realm(
                definition,
                str(player["realm_key"]),
                player_integer(player, "realm_layer"),
                self.content,
            ):
                raise EquipmentRequirementError("player realm does not meet equipment requirement")
            if self._has_active_long_action(connection, int(player["id"])):
                raise EquipmentBusyError("another long action is active")
            if not self._equipment_source_exists(connection, player, definition):
                raise EquipmentNotOwnedError("equipment is not owned")
            costs = refinement_cost(definition)
            equipment = self._resolve_equipment(connection, player, equipment_reference, now_text)
            player = connection.execute("SELECT * FROM players WHERE id = ?", (player["id"],)).fetchone()
            if player is None:
                raise PlayerNotFoundError("player disappeared during equipment resolution")
            inventory = player_inventory(player)
            inventory, stones_after, material_key, material_spent, stones_spent = self._consume_equipment_costs(
                player, inventory, costs
            )
            old_affixes = {
                str(key): int(value)
                for key, value in self._json_object(equipment["affixes_json"], {}).items()
            }
            streak_before = int(equipment["refinement_failure_streak"])
            roll_bp = refinement_roll_bp(f"{operation_id}:{equipment['instance_id']}:{streak_before}")
            success_bp = refinement_success_bp(definition)
            pity_failures = refinement_pity_failures(definition)
            success = streak_before >= pity_failures or roll_bp < success_bp
            new_affixes = dict(old_affixes)
            if success:
                affix_key, affix_value = refinement_affix(
                    f"{operation_id}:{equipment['instance_id']}:{streak_before}", definition
                )
                new_affixes = {affix_key: affix_value}
            streak_after = 0 if success else streak_before + 1
            spend_player_assets(
                connection,
                player,
                costs,
                now_text,
            )
            connection.execute(
                "UPDATE equipment_instances SET affixes_json = ?, refinement_failure_streak = ?, updated_at = ? WHERE id = ?",
                (json.dumps(new_affixes, ensure_ascii=False, sort_keys=True), streak_after, now_text, equipment["id"]),
            )
            snapshot = {
                "item_key": definition.key,
                "old_affixes": old_affixes,
                "new_affixes": new_affixes,
                "success": success,
                "roll_bp": roll_bp,
                "success_bp": success_bp,
                "failure_streak_before": streak_before,
                "failure_streak_after": streak_after,
                "costs_spent": costs,
            }
            connection.execute(
                """
                INSERT INTO equipment_refinement_events(
                    event_id, player_id, equipment_id, operation_id, success,
                    roll_bp, success_bp, material_key, material_spent,
                    spirit_stones_spent, old_affixes_json, new_affixes_json,
                    failure_streak_before, failure_streak_after, snapshot_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    uuid4().hex,
                    player["id"],
                    equipment["id"],
                    operation_id,
                    int(success),
                    roll_bp,
                    10000 if streak_before >= pity_failures else success_bp,
                    material_key,
                    material_spent,
                    stones_spent,
                    json.dumps(old_affixes, ensure_ascii=False, sort_keys=True),
                    json.dumps(new_affixes, ensure_ascii=False, sort_keys=True),
                    streak_before,
                    streak_after,
                    json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
                    now_text,
                ),
            )
            updated_equipment = connection.execute("SELECT * FROM equipment_instances WHERE id = ?", (equipment["id"],)).fetchone()
            updated_player = connection.execute("SELECT * FROM players WHERE id = ?", (player["id"],)).fetchone()
            if updated_equipment is None or updated_player is None:
                raise RuntimeError("equipment refinement returned no state")
            actual_success_bp = 10000 if streak_before >= pity_failures else success_bp
            payload = {
                "player": self._player_payload(self._row_to_player(updated_player)),
                "equipment": {
                    "instance_id": updated_equipment["instance_id"],
                    "item_key": updated_equipment["item_key"],
                    "label": updated_equipment["label"],
                    "slot": updated_equipment["slot"],
                    "status": updated_equipment["status"],
                    "durability_bp": updated_equipment["durability_bp"],
                    "temper_level": updated_equipment["temper_level"],
                    "max_temper_level": updated_equipment["max_temper_level"],
                    "affixes": self._json_object(updated_equipment["affixes_json"], {}),
                    "refinement_failure_streak": updated_equipment["refinement_failure_streak"],
                },
                "old_affixes": old_affixes,
                "new_affixes": new_affixes,
                "success": success,
                "roll_bp": roll_bp,
                "success_bp": actual_success_bp,
                "costs_spent": costs,
                "failure_streak_before": streak_before,
                "failure_streak_after": streak_after,
            }
            connection.execute(
                "INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (operation_id, operation_name, player["id"], request_hash, json.dumps(payload, ensure_ascii=False, sort_keys=True), now_text),
            )
            return self._refinement_from_payload(payload)

    async def get_skill_profile(
        self,
        *,
        platform: str,
        platform_user_id: str,
    ) -> SkillProfileRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._get_skill_profile_sync,
                platform,
                platform_user_id,
            )

    def _get_skill_profile_sync(
        self,
        platform: str,
        platform_user_id: str,
    ) -> SkillProfileRecord:
        with self._connect() as connection:
            row = self._require_player(connection, platform, platform_user_id, writable=False)
            if str(row["stage"]) != "cultivator" or not row["path_key"]:
                raise PlayerStageConflictError("skill profile requires entry into cultivation")
            mastery_rows = connection.execute(
                "SELECT * FROM skill_masteries WHERE player_id = ? ORDER BY skill_key",
                (row["id"],),
            ).fetchall()
            insight_rules = skill_mastery_rules(self.content)
            insight_resource = skill_resource_definition(insight_rules["insight_resource_key"], self.content)
            insight_storage = str(insight_resource["storage"])
            if insight_storage not in row.keys():
                raise ContentError(f"skill insight storage column is missing: {insight_storage}")
            return SkillProfileRecord(
                player=self._row_to_player(row),
                skills=tuple(self._skill_mastery_from_row(item) for item in mastery_rows),
                insight_balance=int(row[insight_storage]),
            )

    async def train_skill(
        self,
        *,
        platform: str,
        platform_user_id: str,
        skill_reference: str,
        operation_id: str,
    ) -> SkillMasteryRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._train_skill_sync,
                platform,
                platform_user_id,
                skill_reference,
                operation_id,
            )

    def _train_skill_sync(
        self,
        platform: str,
        platform_user_id: str,
        skill_reference: str,
        operation_id: str,
    ) -> SkillMasteryRecord:
        last_error: Exception | None = None
        for attempt in range(5):
            try:
                return self._train_skill_once(
                    platform,
                    platform_user_id,
                    skill_reference,
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

    def _train_skill_once(
        self,
        platform: str,
        platform_user_id: str,
        skill_reference: str,
        operation_id: str,
    ) -> SkillMasteryRecord:
        definition = skill_definition(skill_reference, self.content)
        normalized_reference = skill_reference.strip()
        operation_name = "skill.train"
        request_hash = self._request_hash(
            operation_name,
            {
                "platform": platform,
                "platform_user_id": platform_user_id,
                "skill_reference": normalized_reference,
                "skill_key": definition.key,
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
                return self._skill_mastery_from_payload(json.loads(existing["result_json"]), replay=True)

            row = self._require_player(connection, platform, platform_user_id)
            if str(row["stage"]) != "cultivator" or not row["path_key"]:
                raise PlayerStageConflictError("skill training requires entry into cultivation")
            if self._has_active_long_action(connection, int(row["id"])):
                raise SkillBusyError("another long action is active")

            mastery = connection.execute(
                "SELECT * FROM skill_masteries WHERE player_id = ? AND skill_key = ? LIMIT 1",
                (row["id"], definition.key),
            ).fetchone()
            inventory = player_inventory(row)
            if definition.key not in available_skill_keys(
                str(row["path_key"]),
                self.content,
                realm_key=str(row["realm_key"]),
                realm_layer=player_integer(row, "realm_layer"),
                inventory=inventory,
                mastered_keys=(definition.key,) if mastery is not None else (),
            ):
                raise SkillNotAvailableError("skill is outside the current path, realm or acquisition requirements")
            asset_costs: dict[str, int] = {}
            if mastery is None and definition.acquisition_item_key:
                quantity = int(inventory.get(definition.acquisition_item_key, 0))
                if quantity <= 0:
                    raise SkillNotAvailableError("skill inheritance item is missing")
                asset_costs[definition.acquisition_item_key] = 1
            current_level = int(mastery["level"]) if mastery is not None else 0
            if current_level >= definition.max_level:
                raise SkillAlreadyMaxedError("skill is already at maximum level")
            target_level = current_level + 1
            resource_costs = skill_cost(target_level, definition)
            resource_balances: dict[str, tuple[str, int, int]] = {}
            asset_resource_costs: dict[str, int] = {}
            available_columns = set(row.keys())
            used_storage: set[str] = set()
            for resource_key, amount in resource_costs.items():
                resource = skill_resource_definition(resource_key, self.content)
                storage = str(resource["storage"])
                if storage not in available_columns:
                    raise ContentError(f"resource {resource_key} storage column is missing: {storage}")
                if storage in used_storage:
                    raise ContentError(f"multiple skill resources use the same storage column: {storage}")
                used_storage.add(storage)
                balance_before = int(row[storage])
                if balance_before < amount:
                    raise ResourceInsufficientError("skill resources are insufficient")
                resource_balances[resource_key] = (storage, balance_before, balance_before - amount)
                if storage == "spirit_stones":
                    asset_resource_costs["currency.spirit_stone"] = (
                        asset_resource_costs.get("currency.spirit_stone", 0) + int(amount)
                    )
            effective_effect = effective_skill_effect(definition, target_level)
            snapshot = {
                "skill_key": definition.key,
                "level": target_level,
                "base_effect": dict(definition.effect),
                "effective_effect": dict(effective_effect),
                "combat_style": {
                    "key": definition.style_key,
                    "effect": definition.combat_effect or {},
                },
                "acquisition_item_key": definition.acquisition_item_key,
                "qualification": self._json_object(row["qualification_json"], {}),
                "realm_key": row["realm_key"],
                "realm_layer": player_integer(row, "realm_layer"),
                "location_key": row["location_key"],
            }
            snapshot_json = json.dumps(snapshot, ensure_ascii=False, sort_keys=True)
            if mastery is None:
                connection.execute(
                    """
                    INSERT INTO skill_masteries(
                        mastery_id, player_id, operation_id, skill_key, level,
                        snapshot_json, trained_at, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        uuid4().hex,
                        row["id"],
                        operation_id,
                        definition.key,
                        target_level,
                        snapshot_json,
                        now_text,
                        now_text,
                        now_text,
                    ),
                )
            else:
                connection.execute(
                    """
                    UPDATE skill_masteries
                    SET operation_id = ?, level = ?, snapshot_json = ?, trained_at = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (operation_id, target_level, snapshot_json, now_text, now_text, mastery["id"]),
                )
            change_player_state(
                connection,
                row,
                updated_at=now_text,
                asset_values={**asset_costs, **asset_resource_costs},
                asset_mode="spend",
                value_delta={
                    storage: after - before
                    for storage, before, after in resource_balances.values()
                    if storage != "spirit_stones"
                },
            )
            for resource_key, (storage, balance_before, balance_after) in resource_balances.items():
                amount = resource_costs[resource_key]
                if amount == 0:
                    continue
                connection.execute(
                    """
                    INSERT INTO skill_resource_events(
                        event_id, player_id, operation_id, resource_key, delta,
                        balance_before, balance_after, reason, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        uuid4().hex,
                        row["id"],
                        operation_id,
                        resource_key,
                        -amount,
                        balance_before,
                        balance_after,
                        f"train:{definition.key}",
                        now_text,
                    ),
                )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (row["id"],)).fetchone()
            if updated is None:
                raise RuntimeError("skill training returned no player")
            payload = {
                "player": self._player_payload(self._row_to_player(updated)),
                "skill_key": definition.key,
                "label": definition.label,
                "path_key": definition.path_key,
                "level": target_level,
                "max_level": definition.max_level,
                "base_effect": dict(definition.effect),
                "effective_effect": dict(effective_effect),
                "resource_costs": resource_costs,
                "trained_at": now_text,
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
            return self._skill_mastery_from_payload(payload)
