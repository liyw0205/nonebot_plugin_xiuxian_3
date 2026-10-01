"""SQLite transactions for breakthrough and soul transformation flows."""

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

from ....contracts import PlayerView, serialize_datetime
from ...config import XiuxianSettings
from ...player.models import (
    CultivationRecord,
    IntroRecord,
    PlayerCreateRecord,
    RenameRecord,
    SeekingRecord,
    TravelRecord,
)
from ...player.rules import STAGE_MORTAL, STAGE_NEW_USER, qualification_for
from ...progression.models import (
    CultivationCancelRecord,
    CultivationRecoveryRecord,
    CultivationSessionRecord,
    CultivationSettlementRecord,
    LayerAdvanceRecord,
    LayerUnlock,
    ResourceRecoveryRecord,
)
from ...production.models import (
    ProductionOrderRecord,
    ProductionPreviewRecord,
    ProductionSettlementRecord,
)
from ...progression.breakthrough.models import (
    BreakthroughSettlementRecord,
    BreakthroughSessionRecord,
    HeartDemonResolutionRecord,
    NascentSoulPreparationRecord,
    SoulFatigueRecoveryRecord,
    WeaknessRecoveryRecord,
    DomainSelectionRecord,
)
from ...advancement.models import RetreatSessionRecord, RetreatSettlementRecord
from ...advancement.constitution_models import ConstitutionRecord
from ...advancement.talent_models import TalentNodeRecord, TalentProfileRecord
from ...advancement.skill_models import SkillMasteryRecord, SkillProfileRecord
from ...advancement.equipment_models import EquipmentRecord, RefinementRecord, TemperingRecord
from ...items.manual_rules import manual_breakthrough_bonus
from ...specials.codex_projection import record_codex_discovery
from ...content import bundled_content
from ...advancement.rules import (
    MAX_OFFLINE_SECONDS,
    MAX_SETTLEMENT_SECONDS,
    RETREAT_BASIC,
    RETREAT_RESTFUL,
    retreat_definition,
    retreat_reward,
)
from ...livelihood.models import ResidenceRecord
from ...livelihood.rules import residence_definition
from ...world.models import TravelPreview, TravelSettlementRecord, TravelStartRecord
from ...world.void_models import VoidRouteSettlementRecord, VoidRouteStartRecord
from ...world.void_rules import (
    VOID_INSTABILITY_SECONDS,
    VOID_ROUTE_STORM_CHANCE_BP,
    navigation_anchor_cost,
    void_route_definition,
    void_route_roll_bp,
)
from ...progression.repository import ProgressionRepositoryMixin
from ...progression.endgame_repository import EndgameRepositoryMixin
from ...world.repository import WorldRepositoryMixin
from ...world.rules import destination_definition, meets_realm
from ...exploration.models import ExplorationSettlementRecord, ExplorationStartRecord
from ...exploration.rules import (
    battle_roll_bp,
    exploration_definition,
    meets_realm as exploration_meets_realm,
    settlement_result,
)
from ...adventures.models import BountyAcceptRecord, BountyBoardRecord, BountyClaimRecord, BountyOfferView
from ...utils.assets import inventory_value
from ...utils.player import change_player_state
from ...adventures.mainline_models import (
    MainlineClaimRecord,
    MainlineStageView,
    MainlineStartRecord,
    MainlineStatusRecord,
)
from ...adventures.mainline import (
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
from ...adventures.rules import bounty_definition, DEFINITIONS as BOUNTY_DEFINITIONS, meets_realm as bounty_meets_realm, reward_map
from ...routine.models import (
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
from ...routine.wayfaring import (
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
from ...routine.billing import BillingReceiptError, verify_receipt
from ...routine.gacha import (
    FATE_PITY_LIMIT,
    FATE_POOL_KEY,
    FATE_SINGLE_COST,
    FATE_TEN_COST,
    FATE_TICKET,
    reward_totals,
    roll_fate_pool,
)
from ...routine.rules import (
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

from ...persistence.errors import *  # noqa: F401,F403


class BreakthroughRepositoryMixin:
    async def prepare_nascent_soul(
        self,
        *,
        platform: str,
        platform_user_id: str,
        operation_id: str,
    ) -> NascentSoulPreparationRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._prepare_nascent_soul_sync, platform, platform_user_id, operation_id)

    def _prepare_nascent_soul_sync(self, platform: str, platform_user_id: str, operation_id: str) -> NascentSoulPreparationRecord:
        operation_name = "progression.prepare_nascent_soul"
        request_payload = {"platform": platform, "platform_user_id": platform_user_id}
        request_hash = self._request_hash(operation_name, request_payload)
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute("SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id = ?", (operation_id,)).fetchone()
            if existing is not None:
                if existing["operation_name"] != operation_name or existing["request_hash"] != request_hash:
                    raise OperationConflictError("operation input differs from its original request")
                payload = json.loads(existing["result_json"])
                return NascentSoulPreparationRecord(player=self._row_to_player(payload["player"]), already_completed=True)
            row = self._require_player(connection, platform, platform_user_id)
            if row["realm_key"] != "golden_core" or int(row["realm_layer"]) != 10 or int(row["total_cultivation"]) < 58960:
                raise BreakthroughRequirementError("golden core preparation requirement is missing")
            if int(row["foundation_quality"]) < 5500:
                raise FoundationQualityInsufficientError("foundation quality is insufficient")
            intro = self._json_object(row["intro_json"], {})
            flags = [str(item) for item in intro.get("flags", [])]
            if "quest.prepare_nascent_soul" not in flags:
                flags.append("quest.prepare_nascent_soul")
            intro["flags"] = flags
            change_player_state(
                connection,
                row,
                updated_at=now_text,
                player_values={"intro_json": json.dumps(intro, ensure_ascii=False, sort_keys=True)},
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (row["id"],)).fetchone()
            if updated is None:
                raise RuntimeError("nascent soul preparation returned no player")
            player = self._row_to_player(updated)
            payload = {"player": self._player_payload(player)}
            connection.execute("INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)", (operation_id, operation_name, row["id"], request_hash, json.dumps(payload, ensure_ascii=False, sort_keys=True), now_text))
            return NascentSoulPreparationRecord(player=player)

    async def start_breakthrough(
        self,
        *,
        platform: str,
        platform_user_id: str,
        target_realm: str,
        protection: bool,
        operation_id: str,
    ) -> BreakthroughSessionRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._start_breakthrough_sync,
                platform,
                platform_user_id,
                target_realm,
                protection,
                operation_id,
            )

    def _start_breakthrough_sync(
        self,
        platform: str,
        platform_user_id: str,
        target_realm: str,
        protection: bool,
        operation_id: str,
    ) -> BreakthroughSessionRecord:
        last_error: Exception | None = None
        for attempt in range(5):
            try:
                return self._start_breakthrough_once(
                    platform, platform_user_id, target_realm, protection, operation_id
                )
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).lower():
                    raise
                if attempt == 4:
                    raise RepositoryBusyError("database remained locked") from exc
                last_error = exc
                time.sleep(0.01 * (2**attempt))
        raise RepositoryBusyError("database remained locked") from last_error

    def _start_breakthrough_once(
        self,
        platform: str,
        platform_user_id: str,
        target_realm: str,
        protection: bool,
        operation_id: str,
    ) -> BreakthroughSessionRecord:
        from ...progression.breakthrough.rules import breakthrough_definition, success_bp

        try:
            definition = breakthrough_definition(target_realm)
        except ValueError as exc:
            raise BreakthroughRequirementError("target breakthrough is not open") from exc
        if target_realm == "nascent_soul":
            # A retry after the 24-hour window must settle the personal event first.
            self._expire_heart_demon_for_player(platform, platform_user_id)
        operation_name = definition.key
        operation_payload = {
            "platform": platform,
            "platform_user_id": platform_user_id,
            "target_realm": target_realm,
            "protection": protection,
        }
        request_hash = self._request_hash(operation_name, operation_payload)
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
                payload = json.loads(existing["result_json"])
                return BreakthroughSessionRecord(
                    player=self._row_to_player(payload["player"]),
                    session_id=str(payload["session_id"]),
                    target_realm=str(payload["target_realm"]),
                    status=str(payload["status"]),
                    starts_at=str(payload["starts_at"]),
                    ends_at=str(payload["ends_at"]),
                    success_bp=int(payload["success_bp"]),
                    protection_key=payload.get("protection_key"),
                    already_completed=True,
                )

            row = self._require_player(connection, platform, platform_user_id)
            if target_realm != definition.target_realm:
                raise BreakthroughRequirementError("target breakthrough is not open")
            if row["stage"] != "cultivator" or row["realm_key"] != definition.source_realm:
                if target_realm == "soul_transformation":
                    raise RealmMismatchError("current realm does not match the breakthrough")
                raise BreakthroughRequirementError("current realm does not match the breakthrough")
            if int(row["realm_layer"]) != 10:
                if target_realm == "soul_transformation":
                    raise RealmMismatchError("only the current realm's L10 can break through")
                raise BreakthroughRequirementError("only the current realm's L10 can break through")
            if int(row["total_cultivation"]) < definition.required_total_cultivation:
                if target_realm == "soul_transformation":
                    raise CultivationInsufficientError("total cultivation is insufficient")
                raise BreakthroughRequirementError("total cultivation is insufficient")
            if int(row["foundation_quality"]) < definition.required_foundation_quality:
                raise FoundationQualityInsufficientError("foundation quality is insufficient")
            is_nascent = target_realm == "nascent_soul"
            is_soul_transformation = target_realm == "soul_transformation"
            is_void_refining = target_realm == "void_refining"
            if is_soul_transformation:
                crack_until = row["domain_crack_until"]
                if crack_until:
                    try:
                        if datetime.fromisoformat(str(crack_until)) > now:
                            raise DomainCrackActiveError("domain crack is active")
                    except ValueError:
                        pass
                    change_player_state(
                        connection,
                        row,
                        updated_at=now_text,
                        player_values={"domain_crack_until": None},
                    )
            if is_nascent:
                pending = connection.execute(
                    "SELECT 1 FROM heart_demon_sessions WHERE player_id = ? AND status = 'pending' LIMIT 1",
                    (row["id"],),
                ).fetchone()
                if pending is not None:
                    raise HeartDemonPendingError("heart demon must be resolved first")
                fatigue_until = row["soul_fatigue_until"]
                if fatigue_until:
                    try:
                        if datetime.fromisoformat(str(fatigue_until)) > now:
                            raise SoulFatigueActiveError("soul fatigue is active")
                    except ValueError:
                        pass
                intro_state = self._json_object(row["intro_json"], {})
                flags = {str(item) for item in intro_state.get("flags", [])}
                if "quest.prepare_nascent_soul" not in flags:
                    raise QuestRequirementError("nascent soul preparation quest is missing")
                if int(row["world_merit"]) < 100:
                    raise CurrencyInsufficientError("world merit is insufficient")
            if is_soul_transformation:
                if int(row["soul_power"]) < 200:
                    raise SoulPowerInsufficientError("soul power is insufficient")
                if int(row["world_merit"]) < 500:
                    raise CurrencyInsufficientError("world merit is insufficient")
                intro_state = self._json_object(row["intro_json"], {})
                if "quest.soul_transformation" not in {str(item) for item in intro_state.get("flags", [])}:
                    raise QuestRequirementError("soul transformation quest is missing")
                reputation_row = connection.execute(
                    "SELECT local_json FROM player_reputations WHERE player_id = ?", (row["id"],)
                ).fetchone()
                faction = self._json_object(row["faction_reputation_json"], {})
                if reputation_row is not None:
                    local = self._json_object(reputation_row["local_json"], {})
                    for key, value in local.items():
                        if str(key).startswith("faction."):
                            faction[str(key).split(".", 1)[1]] = int(value)
                if max((int(value) for value in faction.values()), default=0) < 2000:
                    raise FactionReputationInsufficientError("faction reputation is insufficient")
            if is_void_refining:
                # A newly transformed player reaches the archive ruins through
                # the public permit route. Keep the first route/time garden
                # locations for established void characters, while accepting
                # the archive arrival as the documented pre-breakthrough
                # staging point.
                if str(row["location_key"]) not in {"void.first_route", "void.archive_ruins", "cave.time_garden"}:
                    raise VoidLocationRequiredError("void refining requires an approved void location")
                flags = {str(item) for item in self._json_object(row["intro_json"], {}).get("flags", [])}
                if "quest.break_void" not in flags:
                    raise VoidQuestMissingError("void refining quest is missing")
                if int(row["world_merit"]) < 500 or int(row["domain_charge"]) < 100:
                    raise VoidResourceInsufficientError("void refining resources are insufficient")
                if protection:
                    raise BreakthroughRequirementError("void refining has no protection item")
            weakness_until = row["weakness_until"]
            if weakness_until:
                try:
                    weak_time = datetime.fromisoformat(str(weakness_until))
                except ValueError:
                    weak_time = now
                if weak_time > now:
                    raise WeaknessActiveError("breakthrough weakness is active")
                change_player_state(
                    connection,
                    row,
                    updated_at=now_text,
                    player_values={"weakness_until": None},
                )
            active = connection.execute(
                "SELECT 1 FROM breakthrough_sessions WHERE player_id = ? AND status = 'preparing' LIMIT 1",
                (row["id"],),
            ).fetchone()
            if active is not None:
                raise BreakthroughBusyError("breakthrough is already preparing")
            cultivation = connection.execute(
                "SELECT status FROM cultivation_sessions WHERE player_id = ? AND status IN ('running', 'expired') ORDER BY id DESC LIMIT 1",
                (row["id"],),
            ).fetchone()
            if cultivation is not None:
                raise BreakthroughBusyError("cultivation session is active")
            production = connection.execute(
                "SELECT 1 FROM production_orders WHERE player_id = ? AND status = 'processing' LIMIT 1",
                (row["id"],),
            ).fetchone()
            if production is not None:
                raise BreakthroughBusyError("production order is active")
            exploration = connection.execute(
                "SELECT 1 FROM exploration_sessions WHERE player_id = ? AND status IN ('created', 'running', 'combat_pending') LIMIT 1",
                (row["id"],),
            ).fetchone()
            if exploration is not None:
                raise BreakthroughBusyError("exploration is active")
            retreat = connection.execute(
                "SELECT 1 FROM retreat_sessions WHERE player_id = ? AND status = 'running' LIMIT 1",
                (row["id"],),
            ).fetchone()
            if retreat is not None:
                raise BreakthroughBusyError("retreat is active")
            idle_or_dispatch = connection.execute(
                "SELECT 1 FROM idle_assignments WHERE player_id = ? AND status IN ('assigned', 'running') "
                "UNION ALL SELECT 1 FROM dispatch_assignments WHERE player_id = ? AND status IN ('accepted', 'running') LIMIT 1",
                (row["id"], row["id"]),
            ).fetchone()
            if idle_or_dispatch is not None:
                raise BreakthroughBusyError("another long action is active")

            inventory = inventory_value(row["inventory_json"])
            for item_key, quantity in definition.materials.items():
                if int(inventory.get(item_key, 0)) < quantity:
                    raise MaterialInsufficientError("breakthrough material is insufficient")
            alternative_material: str | None = None
            if is_nascent:
                for candidate in ("item.demon_core", "item.beast_blood"):
                    if int(inventory.get(candidate, 0)) >= 2:
                        alternative_material = candidate
                        break
                if alternative_material is None:
                    raise MaterialInsufficientError("nascent soul alternative material is insufficient")
            if protection and int(inventory.get(definition.protection_key, 0)) < 1:
                raise ProtectionItemInsufficientError("breakthrough protection item is missing")
            if int(row["spirit_stones"]) < definition.currency_cost:
                raise CurrencyInsufficientError("spirit stones are insufficient")

            pity_before = int(row["breakthrough_pity_bp"])
            foundation_quality = int(row["foundation_quality"])
            quality_bonus_bp = 0
            if definition.quality_bonus_divisor:
                quality_bonus_bp = min(
                    definition.quality_bonus_cap_bp,
                    foundation_quality // definition.quality_bonus_divisor,
                )
            technique_bonus_bp = manual_breakthrough_bonus(
                inventory,
                definition.target_realm,
                self.content,
            )
            formation_bonus_bp = (
                definition.formation_bonus_bp
                if definition.formation_bonus_bp and row["subprofession_key"] == "formation"
                else 0
            )
            location_bonus_bp = (
                definition.location_bonus_bp
                if definition.location_bonus_bp and row["location_key"] == "xuantian.cloud_city"
                else 0
            )
            support_bonus_bp = (
                definition.support_bonus_bp
                if definition.support_bonus_bp
                and definition.support_key
                and int(inventory.get(definition.support_key, 0)) > 0
                else 0
            )
            preparation_bp = quality_bonus_bp + technique_bonus_bp + formation_bonus_bp + location_bonus_bp + support_bonus_bp
            soul_prepare_bp = reputation_prepare_bp = quest_prepare_bp = 0
            heart_demon_bonus_bp = int(row["heart_demon_bonus_bp"]) if is_nascent else 0
            cross_realm_risk_bp = 0
            if is_nascent and not str(row["location_key"]).startswith("xuantian."):
                world = str(row["location_key"]).split(".", 1)[0]
                flags = {str(item) for item in self._json_object(row["intro_json"], {}).get("flags", [])}
                if f"alliance.{world}" not in flags:
                    cross_realm_risk_bp = 400
            if is_nascent:
                flags = {str(item) for item in self._json_object(row["intro_json"], {}).get("flags", [])}
                preparation_bp = 0
                preparation_bp += technique_bonus_bp
                if "preparation.nascent_soul.technique" in flags:
                    preparation_bp += 300
                if f"alliance.{str(row['location_key']).split('.', 1)[0]}" in flags:
                    preparation_bp += 300
                if {"sect.nascent_soul_ritual", "quest.nascent_soul_ritual"} & flags:
                    preparation_bp += 300
                if str(row["location_key"]).startswith("xuantian."):
                    preparation_bp += 300
                final_success_bp = max(5500, min(9000, 5500 + quality_bonus_bp + preparation_bp + pity_before + heart_demon_bonus_bp - cross_realm_risk_bp))
            elif is_soul_transformation:
                reputation_row = connection.execute(
                    "SELECT local_json FROM player_reputations WHERE player_id = ?", (row["id"],)
                ).fetchone()
                faction = self._json_object(row["faction_reputation_json"], {})
                if reputation_row is not None:
                    for key, value in self._json_object(reputation_row["local_json"], {}).items():
                        if str(key).startswith("faction."):
                            faction[str(key).split(".", 1)[1]] = int(value)
                soul_prepare_bp = min(1000, max(0, int(row["soul_power"]) - 200) * 4)
                reputation_prepare_bp = min(1000, max(0, max((int(value) for value in faction.values()), default=0) - 2000) // 2)
                quest_prepare_bp = 600 if "quest.soul_transformation" in {str(item) for item in self._json_object(row["intro_json"], {}).get("flags", [])} else 0
                preparation_bp = soul_prepare_bp + reputation_prepare_bp + quest_prepare_bp + technique_bonus_bp
                final_success_bp = max(6500, min(9000, 6500 + preparation_bp + pity_before))
            elif is_void_refining:
                route_bonus_bp = min(600, max(0, int(row["void_route_count"])) * 200)
                domain_bonus_bp = min(500, max(0, int(row["domain_power"])) // 10)
                preparation_bp = route_bonus_bp + domain_bonus_bp + technique_bonus_bp
                final_success_bp = max(7500, min(9200, 7500 + preparation_bp + min(750, pity_before)))
            else:
                final_success_bp = success_bp(definition, pity_before, preparation_bp)
            material_costs = {str(key): int(value) for key, value in definition.materials.items()}
            if alternative_material:
                material_costs[alternative_material] = material_costs.get(alternative_material, 0) + 2
            session_materials = dict(definition.materials)
            if alternative_material:
                session_materials[alternative_material] = 2
            session_id = uuid4().hex
            starts_at = now_text
            ends_at = serialize_datetime(now + timedelta(seconds=definition.duration_seconds))
            snapshot = {
                "target_realm": definition.target_realm,
                "source_realm": definition.source_realm,
                "realm_key": row["realm_key"],
                "realm_layer": int(row["realm_layer"]),
                "cultivation": int(row["cultivation"]),
                "total_cultivation": int(row["total_cultivation"]),
                "location_key": row["location_key"],
                "path_key": row["path_key"],
                "subprofession_key": row["subprofession_key"],
                "qualification": self._json_object(row["qualification_json"], {}),
                "random_pool": definition.random_pool,
                "base_success_bp": definition.base_success_bp,
                "required_foundation_quality": definition.required_foundation_quality,
                "foundation_quality": foundation_quality,
                "foundation_quality_on_success": max(foundation_quality, 5500) if target_realm == "foundation" else None,
                "quality_bonus_bp": quality_bonus_bp,
                "technique_bonus_bp": technique_bonus_bp,
                "formation_bonus_bp": formation_bonus_bp,
                "location_bonus_bp": location_bonus_bp,
                "support_bonus_bp": support_bonus_bp,
                "support_key": definition.support_key,
                "alternative_material": alternative_material,
                "preparation_bp": preparation_bp,
                "success_bp": final_success_bp,
                "pity_before_bp": pity_before,
                "protection_requested": protection,
                "protection_key": definition.protection_key if protection else None,
                "materials": session_materials,
                "currency_cost": definition.currency_cost,
                "random_seed": operation_id,
                "cross_realm_risk_bp": cross_realm_risk_bp,
                "heart_demon_bonus_bp": heart_demon_bonus_bp,
                "pollution": int(row["pollution"]),
                "cross_realm_penalty_bp": int(row["cross_realm_penalty_bp"]),
                "soul_power_before": int(row["soul_power"]),
                "world_merit_before": int(row["world_merit"]),
                "soul_prepare_bp": soul_prepare_bp,
                "reputation_prepare_bp": reputation_prepare_bp,
                "quest_prepare_bp": quest_prepare_bp,
                "route_count": int(row["void_route_count"]),
                "domain_power": int(row["domain_power"]),
                "domain_charge_before": int(row["domain_charge"]),
                "void_power_before": int(row["void_power"]),
                "space_resistance_bp": int(row["space_resistance_bp"]),
                "void_instability_until": row["void_instability_until"],
            }
            value_delta = {
                "world_merit": -(
                    100 if is_nascent else 500 if is_soul_transformation or is_void_refining else 0
                )
            }
            if is_soul_transformation:
                value_delta["soul_power"] = -200
            if is_void_refining:
                value_delta["domain_charge"] = -100
            change_player_state(
                connection,
                row,
                updated_at=now_text,
                asset_values={"spirit_stones": definition.currency_cost, **material_costs},
                asset_mode="spend",
                value_delta=value_delta,
                player_values={"heart_demon_bonus_bp": 0} if is_nascent else None,
                preserve_zero=is_void_refining,
            )
            connection.execute(
                """
                INSERT INTO breakthrough_sessions(
                    session_id, player_id, operation_id, target_realm, status,
                    starts_at, ends_at, snapshot_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'preparing', ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    row["id"],
                    operation_id,
                    definition.target_realm,
                    starts_at,
                    ends_at,
                    json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
                    starts_at,
                    starts_at,
                ),
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (row["id"],)).fetchone()
            if updated is None:
                raise RuntimeError("breakthrough start returned no player")
            player = self._row_to_player(updated)
            payload = {
                "player": self._player_payload(player),
                "session_id": session_id,
                "target_realm": definition.target_realm,
                "status": "preparing",
                "starts_at": starts_at,
                "ends_at": ends_at,
                "success_bp": final_success_bp,
                "protection_key": snapshot["protection_key"],
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
            return BreakthroughSessionRecord(
                player=player,
                session_id=session_id,
                target_realm=definition.target_realm,
                status="preparing",
                starts_at=starts_at,
                ends_at=ends_at,
                success_bp=final_success_bp,
                protection_key=snapshot["protection_key"],
            )

    async def choose_domain(
        self,
        *,
        platform: str,
        platform_user_id: str,
        path_key: str,
        operation_id: str,
    ) -> DomainSelectionRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._choose_domain_once, platform, platform_user_id, path_key, operation_id)

    def _choose_domain_once(self, platform: str, platform_user_id: str, path_key: str, operation_id: str) -> DomainSelectionRecord:
        from ...paths.rules import domain_definition

        definition = domain_definition(path_key)
        operation_name = "paths.choose_domain"
        request_hash = self._request_hash(operation_name, {"platform": platform, "platform_user_id": platform_user_id, "path_key": path_key})
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute("SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id = ?", (operation_id,)).fetchone()
            if existing is not None:
                if existing["operation_name"] != operation_name or existing["request_hash"] != request_hash:
                    raise OperationConflictError("operation input differs from its original request")
                payload = json.loads(existing["result_json"])
                return DomainSelectionRecord(player=self._row_to_player(payload["player"]), session_id=str(payload["session_id"]), domain_key=str(payload["domain_key"]), status=str(payload["status"]), ends_at=payload.get("ends_at"), energy_cost=int(payload.get("energy_cost", 0)), already_completed=True)
            row = self._require_player(connection, platform, platform_user_id)
            crack_until = row["domain_crack_until"]
            if crack_until:
                try:
                    if datetime.fromisoformat(str(crack_until)) > now:
                        raise DomainCrackActiveError("domain crack is active")
                except ValueError:
                    pass
                change_player_state(
                    connection,
                    row,
                    updated_at=now_text,
                    player_values={"domain_crack_until": None},
                )
            if str(row["realm_key"]) != "soul_transformation" or int(row["realm_layer"]) < 3:
                raise DomainNotEligibleError("domain requires soul transformation L3")
            if row["domain_key"]:
                raise DomainAlreadySelectedError("domain already selected")
            if str(row["path_key"] or "") != path_key:
                raise DomainNotEligibleError("domain does not match primary path")
            talent_level = connection.execute("SELECT COALESCE(MAX(tier), 0) AS level FROM talent_node_states WHERE player_id = ? AND tree_key = ? AND status = 'learned'", (row["id"], path_key)).fetchone()
            if max(int(row["domain_level"]), int(talent_level["level"] if talent_level else 0)) < 5:
                raise DomainNotEligibleError("primary path level is insufficient")
            pending = connection.execute("SELECT id, ends_at FROM domain_selection_sessions WHERE player_id = ? AND status = 'pending' ORDER BY id DESC LIMIT 1", (row["id"],)).fetchone()
            if pending is not None:
                if now < datetime.fromisoformat(str(pending["ends_at"])):
                    raise DomainSelectionBusyError("domain selection is already pending")
                connection.execute("UPDATE domain_selection_sessions SET status = 'expired', updated_at = ? WHERE id = ?", (now_text, pending["id"]))
            inventory = inventory_value(row["inventory_json"])
            if int(inventory.get("item.domain_core", 0)) < 1:
                raise MaterialInsufficientError("domain core is missing")
            if int(row["spirit_stones"]) < 10_000:
                raise CurrencyInsufficientError("domain selection requires spirit stones")
            session_id = uuid4().hex
            ends_at = serialize_datetime(now + timedelta(minutes=5))
            snapshot = {"domain_key": definition.domain_key, "path_key": path_key, "energy_cost": definition.energy_cost}
            connection.execute("INSERT INTO domain_selection_sessions(session_id, player_id, operation_id, domain_key, status, starts_at, ends_at, snapshot_json, created_at, updated_at) VALUES (?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?)", (session_id, row["id"], operation_id, definition.domain_key, now_text, ends_at, json.dumps(snapshot, ensure_ascii=False, sort_keys=True), now_text, now_text))
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (row["id"],)).fetchone()
            payload = {"player": self._player_payload(self._row_to_player(updated)), "session_id": session_id, "domain_key": definition.domain_key, "status": "pending", "ends_at": ends_at, "energy_cost": definition.energy_cost}
            connection.execute("INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)", (operation_id, operation_name, row["id"], request_hash, json.dumps(payload, ensure_ascii=False, sort_keys=True), now_text))
            return DomainSelectionRecord(player=self._row_to_player(updated), session_id=session_id, domain_key=definition.domain_key, status="pending", ends_at=ends_at, energy_cost=definition.energy_cost)

    async def cancel_domain(self, *, platform: str, platform_user_id: str, operation_id: str) -> DomainSelectionRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._cancel_domain_once, platform, platform_user_id, operation_id)

    def _cancel_domain_once(self, platform: str, platform_user_id: str, operation_id: str) -> DomainSelectionRecord:
        operation_name = "paths.cancel_domain"
        request_hash = self._request_hash(operation_name, {"platform": platform, "platform_user_id": platform_user_id})
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute("SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id = ?", (operation_id,)).fetchone()
            if existing is not None:
                if existing["operation_name"] != operation_name or existing["request_hash"] != request_hash:
                    raise OperationConflictError("operation input differs from its original request")
                payload = json.loads(existing["result_json"])
                return DomainSelectionRecord(player=self._row_to_player(payload["player"]), session_id=str(payload["session_id"]), domain_key=str(payload["domain_key"]), status="cancelled", already_completed=True)
            row = self._require_player(connection, platform, platform_user_id)
            session = connection.execute("SELECT * FROM domain_selection_sessions WHERE player_id = ? AND status = 'pending' ORDER BY id DESC LIMIT 1", (row["id"],)).fetchone()
            if session is None:
                raise DomainNotEligibleError("no pending domain selection")
            connection.execute("UPDATE domain_selection_sessions SET status = 'cancelled', updated_at = ? WHERE id = ?", (now_text, session["id"]))
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (row["id"],)).fetchone()
            payload = {"player": self._player_payload(self._row_to_player(updated)), "session_id": session["session_id"], "domain_key": session["domain_key"], "status": "cancelled"}
            connection.execute("INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)", (operation_id, operation_name, row["id"], request_hash, json.dumps(payload, ensure_ascii=False, sort_keys=True), now_text))
            return DomainSelectionRecord(player=self._row_to_player(updated), session_id=str(session["session_id"]), domain_key=str(session["domain_key"]), status="cancelled")

    async def confirm_domain(self, *, platform: str, platform_user_id: str, operation_id: str) -> DomainSelectionRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._confirm_domain_once, platform, platform_user_id, operation_id)

    def _confirm_domain_once(self, platform: str, platform_user_id: str, operation_id: str) -> DomainSelectionRecord:
        operation_name = "paths.confirm_domain"
        request_hash = self._request_hash(operation_name, {"platform": platform, "platform_user_id": platform_user_id})
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute("SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id = ?", (operation_id,)).fetchone()
            if existing is not None:
                if existing["operation_name"] != operation_name or existing["request_hash"] != request_hash:
                    raise OperationConflictError("operation input differs from its original request")
                payload = json.loads(existing["result_json"])
                return DomainSelectionRecord(player=self._row_to_player(payload["player"]), session_id=str(payload["session_id"]), domain_key=str(payload["domain_key"]), status="confirmed", confirmed=True, already_completed=True)
            row = self._require_player(connection, platform, platform_user_id)
            session = connection.execute("SELECT * FROM domain_selection_sessions WHERE player_id = ? AND status = 'pending' ORDER BY id DESC LIMIT 1", (row["id"],)).fetchone()
            if session is None:
                raise DomainNotEligibleError("no pending domain selection")
            if now >= datetime.fromisoformat(str(session["ends_at"])):
                connection.execute("UPDATE domain_selection_sessions SET status = 'expired', updated_at = ? WHERE id = ?", (now_text, session["id"]))
                raise DomainNotEligibleError("domain selection confirmation expired")
            crack_until = row["domain_crack_until"]
            if crack_until:
                try:
                    if datetime.fromisoformat(str(crack_until)) > now:
                        raise DomainCrackActiveError("domain crack is active")
                except ValueError:
                    pass
            if row["domain_key"]:
                raise DomainAlreadySelectedError("domain already selected")
            inventory = inventory_value(row["inventory_json"])
            if int(inventory.get("item.domain_core", 0)) < 1:
                raise MaterialInsufficientError("domain core is missing")
            if int(row["spirit_stones"]) < 10_000:
                raise CurrencyInsufficientError("domain selection requires spirit stones")
            snapshot = self._json_object(session["snapshot_json"], {})
            domain_key = str(session["domain_key"])
            pollution_delta = 15 if domain_key == "domain.abyss_shadow" else 0
            bloodline_delta = -10 if domain_key == "domain.ancestral_wild" else 0
            change_player_state(
                connection,
                row,
                updated_at=now_text,
                asset_values={"item.domain_core": 1, "spirit_stones": 10_000},
                asset_mode="spend",
                value_delta={"pollution": pollution_delta, "bloodline_stability": bloodline_delta},
                maximums={"pollution": 100},
                player_values={"domain_key": domain_key},
            )
            connection.execute("UPDATE domain_selection_sessions SET status = 'confirmed', result_json = ?, updated_at = ? WHERE id = ?", (json.dumps({"domain_key": domain_key, "pollution_delta": pollution_delta, "bloodline_delta": bloodline_delta}, ensure_ascii=False, sort_keys=True), now_text, session["id"]))
            content = self.content or bundled_content()
            path_key = str(snapshot["path_key"])
            path = content.require("path", path_key)
            codex_entry_key = path.get("codex_entry_key")
            if not isinstance(codex_entry_key, str):
                raise ValueError(f"path {path_key} has no configured domain codex entry")
            record_codex_discovery(
                connection,
                player_id=int(row["id"]),
                entry_key=codex_entry_key,
                operation_id=operation_id,
                occurred_at=now_text,
                snapshot={"domain_key": domain_key, "path_key": path_key},
                content=content,
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (row["id"],)).fetchone()
            payload = {"player": self._player_payload(self._row_to_player(updated)), "session_id": session["session_id"], "domain_key": domain_key, "status": "confirmed"}
            connection.execute("INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)", (operation_id, operation_name, row["id"], request_hash, json.dumps(payload, ensure_ascii=False, sort_keys=True), now_text))
            return DomainSelectionRecord(player=self._row_to_player(updated), session_id=str(session["session_id"]), domain_key=domain_key, status="confirmed", confirmed=True)

    async def recover_domain_crack(self, *, platform: str, platform_user_id: str, early: bool, operation_id: str) -> WeaknessRecoveryRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._recover_domain_crack_once, platform, platform_user_id, early, operation_id)

    def _recover_domain_crack_once(self, platform: str, platform_user_id: str, early: bool, operation_id: str) -> WeaknessRecoveryRecord:
        operation_name = "progression.recover_domain_crack"
        request_hash = self._request_hash(operation_name, {"platform": platform, "platform_user_id": platform_user_id, "early": early})
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute("SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id = ?", (operation_id,)).fetchone()
            if existing is not None:
                if existing["operation_name"] != operation_name or existing["request_hash"] != request_hash:
                    raise OperationConflictError("operation input differs from its original request")
                payload = json.loads(existing["result_json"])
                return WeaknessRecoveryRecord(player=self._row_to_player(payload["player"]), early=bool(payload["early"]), spirit_stones_spent=int(payload["spirit_stones_spent"]), medicine_consumed=bool(payload["medicine_consumed"]), medicine_key="item.pill.domain_restore", already_completed=True)
            row = self._require_player(connection, platform, platform_user_id)
            crack_until = row["domain_crack_until"]
            if not crack_until:
                raise WeaknessNotActiveError("no domain crack is active")
            expired = now >= datetime.fromisoformat(str(crack_until))
            inventory = inventory_value(row["inventory_json"])
            stones_spent = 0
            medicine_consumed = False
            if not expired and not early:
                raise WeaknessActiveError("domain crack has not expired")
            if not expired and early:
                if str(row["location_key"]) != "xuantian.domain_front":
                    raise BreakthroughRequirementError("early domain recovery requires domain front")
                if int(inventory.get("item.pill.domain_restore", 0)) < 1:
                    raise MaterialInsufficientError("domain restore pill is missing")
                if int(row["spirit_stones"]) < 2000:
                    raise CurrencyInsufficientError("early domain recovery requires spirit stones")
                stones_spent = 2000
                medicine_consumed = True
            change_player_state(
                connection,
                row,
                updated_at=now_text,
                asset_values=(
                    {"item.pill.domain_restore": 1, "spirit_stones": stones_spent}
                    if medicine_consumed
                    else None
                ),
                asset_mode="spend",
                player_values={"domain_crack_until": None},
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (row["id"],)).fetchone()
            payload = {"player": self._player_payload(self._row_to_player(updated)), "early": early, "spirit_stones_spent": stones_spent, "medicine_consumed": medicine_consumed}
            connection.execute("INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)", (operation_id, operation_name, row["id"], request_hash, json.dumps(payload, ensure_ascii=False, sort_keys=True), now_text))
            return WeaknessRecoveryRecord(player=self._row_to_player(updated), early=early, spirit_stones_spent=stones_spent, medicine_consumed=medicine_consumed, medicine_key="item.pill.domain_restore")

    async def settle_breakthrough(
        self,
        *,
        platform: str,
        platform_user_id: str,
        operation_id: str,
    ) -> BreakthroughSettlementRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._settle_breakthrough_sync, platform, platform_user_id, operation_id
            )

    def _settle_breakthrough_sync(self, platform: str, platform_user_id: str, operation_id: str) -> BreakthroughSettlementRecord:
        last_error: Exception | None = None
        for attempt in range(5):
            try:
                return self._settle_breakthrough_once(platform, platform_user_id, operation_id)
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).lower():
                    raise
                if attempt == 4:
                    raise RepositoryBusyError("database remained locked") from exc
                last_error = exc
                time.sleep(0.01 * (2**attempt))
        raise RepositoryBusyError("database remained locked") from last_error

    def _settle_breakthrough_once(self, platform: str, platform_user_id: str, operation_id: str) -> BreakthroughSettlementRecord:
        from ...progression.breakthrough.rules import (
            breakthrough_roll_bp,
            next_pity_bp,
            retained_cultivation,
        )
        operation_name = "progression.settle_breakthrough"
        request_payload = {"platform": platform, "platform_user_id": platform_user_id}
        request_hash = self._request_hash(operation_name, request_payload)
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
                return self._breakthrough_settlement_from_payload(json.loads(existing["result_json"]), replay=True)
            row = self._require_player(connection, platform, platform_user_id)
            session = connection.execute(
                "SELECT * FROM breakthrough_sessions WHERE player_id = ? AND status = 'preparing' ORDER BY id DESC LIMIT 1",
                (row["id"],),
            ).fetchone()
            if session is None:
                pending = connection.execute(
                    "SELECT 1 FROM heart_demon_sessions WHERE player_id = ? AND status = 'pending' LIMIT 1",
                    (row["id"],),
                ).fetchone()
                if pending is not None:
                    raise HeartDemonPendingError("heart demon is pending")
                raise BreakthroughNotFoundError("no preparing breakthrough")
            ends_at = datetime.fromisoformat(str(session["ends_at"]))
            if now < ends_at:
                raise BreakthroughNotReadyError("breakthrough is not ready")
            snapshot = self._json_object(session["snapshot_json"], {})
            from ...progression.breakthrough.rules import breakthrough_definition

            try:
                definition = breakthrough_definition(str(snapshot.get("target_realm", session["target_realm"])))
            except ValueError as exc:
                raise BreakthroughRequirementError("historical breakthrough rule is unavailable") from exc
            roll_bp = breakthrough_roll_bp(str(snapshot.get("random_seed", session["operation_id"])))
            final_success_bp = int(snapshot.get("success_bp", definition.base_success_bp))
            success = roll_bp < final_success_bp
            cultivation_before = int(snapshot.get("cultivation", row["cultivation"]))
            pity_before = int(snapshot.get("pity_before_bp", row["breakthrough_pity_bp"]))
            protection_requested = bool(snapshot.get("protection_requested", False))
            is_nascent = str(snapshot.get("target_realm", session["target_realm"])) == "nascent_soul"
            is_soul_transformation = str(snapshot.get("target_realm", session["target_realm"])) == "soul_transformation"
            is_void_refining = str(snapshot.get("target_realm", session["target_realm"])) == "void_refining"
            protection_key = str(snapshot.get("protection_key") or definition.protection_key)
            inventory = inventory_value(row["inventory_json"], keep_zero=is_void_refining)
            protection_consumed = bool(
                (not success)
                and not is_nascent
                and protection_requested
                and int(inventory.get(protection_key, 0)) > 0
            )
            pity_after = next_pity_bp(definition, pity_before, success)
            weakness_until: str | None = None
            heart_demon_pending = False
            if success:
                cultivation_after = 0
                stamina_after = min(
                    int(row["stamina_max"]),
                    int(row["stamina"]) + definition.reward_stamina,
                )
                reward_items = dict(definition.reward_items or {})
                player_values: dict[str, Any] = {
                    "realm_key": definition.target_realm,
                    "realm_layer": 1,
                    "cultivation": cultivation_after,
                    "breakthrough_pity_bp": 0,
                    "weakness_until": None,
                }
                value_delta = {
                    "stamina": stamina_after - int(row["stamina"]),
                    "world_merit": definition.reward_world_merit,
                }
                if is_nascent:
                    player_values.update(
                        {
                            "soul_power": 100,
                            "soul_power_max": 300,
                            "domain_charge": 100,
                            "domain_charge_max": 100,
                            "cross_realm_penalty_bp": 0 if str(row["location_key"]).startswith("xuantian.") else 1000,
                            "max_hp": int(row["max_hp"]) + 600,
                            "max_mp": int(row["max_mp"]) + 480,
                            "carry_capacity": int(row["carry_capacity"]) + 50,
                            "exploration_efficiency_bp": int(row["exploration_efficiency_bp"]) + 1500,
                            "heart_demon_bonus_bp": 0,
                            "soul_fatigue_until": None,
                        }
                    )
                elif is_soul_transformation:
                    player_values.update(
                        {
                            "stamina_max": int(row["stamina_max"]) + 20,
                            "domain_key": None,
                            "domain_power": 100,
                            "domain_charge": 150,
                            "domain_charge_max": 150,
                            "domain_charge_reset_date": now.date().isoformat(),
                            "realm_resistance_bp": 1000,
                            "domain_crack_until": None,
                            "max_hp": int(row["max_hp"]) + 1000,
                            "max_mp": int(row["max_mp"]) + 800,
                            "initiative": int(row["initiative"]) + 20,
                        }
                    )
                elif is_void_refining:
                    player_values.update(
                        {
                            "domain_crack_until": None,
                            "void_power": 200,
                            "void_power_max": 200,
                            "space_resistance_bp": 1500,
                            "void_instability_until": None,
                            "void_anchor_capacity": 20,
                            "void_power_reset_date": now.date().isoformat(),
                            "max_hp": int(row["max_hp"]) + 1500,
                            "max_mp": int(row["max_mp"]) + 1200,
                            "carry_capacity": int(row["carry_capacity"]) + 100,
                        }
                    )
                change_player_state(
                    connection,
                    row,
                    updated_at=now_text,
                    asset_values={"spirit_stones": definition.reward_currency, **reward_items},
                    asset_mode="grant",
                    value_delta=value_delta,
                    maximums={"stamina": row["stamina_max"]},
                    player_values=player_values,
                    preserve_zero=is_void_refining,
                )
                if definition.target_realm == "foundation":
                    change_player_state(
                        connection,
                        row,
                        updated_at=now_text,
                        player_values={
                            "foundation_quality": max(
                                int(row["foundation_quality"]),
                                int(snapshot.get("foundation_quality_on_success") or 5500),
                            )
                        },
                    )
                if definition.reward_local_reputation:
                    reputation = connection.execute(
                        "SELECT local_json, service_reputation FROM player_reputations WHERE player_id = ?",
                        (row["id"],),
                    ).fetchone()
                    local = self._json_object(reputation["local_json"], {}) if reputation is not None else {}
                    local["local.xuantian.new_town"] = int(local.get("local.xuantian.new_town", 0)) + definition.reward_local_reputation
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
                status = "succeeded"
            else:
                retention_bp = definition.protection_retention_bp if protection_consumed else definition.retention_bp
                weakness_seconds = definition.protection_weakness_seconds if protection_consumed else definition.weakness_seconds
                cultivation_after = retained_cultivation(
                    cultivation_before,
                    retention_bp,
                    definition.source_cultivation_cap,
                )
                if is_nascent:
                    pity_after = pity_before
                    heart_demon_pending = True
                    player_values = {"cultivation": cultivation_after, "weakness_until": None}
                elif is_soul_transformation:
                    domain_crack_until = serialize_datetime(now + timedelta(seconds=weakness_seconds or 24 * 60 * 60))
                    player_values = {"cultivation": cultivation_after, "domain_crack_until": domain_crack_until}
                    weakness_until = domain_crack_until
                elif is_void_refining:
                    weakness_until = serialize_datetime(now + timedelta(seconds=48 * 60 * 60))
                    player_values = {
                        "cultivation": cultivation_after,
                        "void_instability_until": weakness_until,
                        "weakness_until": None,
                    }
                else:
                    weakness_until = serialize_datetime(now + timedelta(seconds=weakness_seconds))
                    player_values = {"cultivation": cultivation_after, "weakness_until": weakness_until}
                change_player_state(
                    connection,
                    row,
                    updated_at=now_text,
                    asset_values={protection_key: 1} if protection_consumed else None,
                    asset_mode="spend",
                    value_delta={"breakthrough_pity_bp": pity_after - pity_before},
                    player_values=player_values,
                    preserve_zero=is_void_refining,
                )
                status = "failed"
            result = {
                "success": success,
                "roll_bp": roll_bp,
                "success_bp": final_success_bp,
                "cultivation_before": cultivation_before,
                "cultivation_after": cultivation_after,
                "pity_before_bp": pity_before,
                "pity_after_bp": pity_after,
                "protection_consumed": protection_consumed,
                "weakness_until": weakness_until,
                "currency_spent": int(snapshot.get("currency_cost", definition.currency_cost)),
                "materials": snapshot.get("materials", definition.materials),
                "random_pool": str(snapshot.get("random_pool", definition.random_pool)),
                "foundation_quality": int(snapshot.get("foundation_quality", 0)),
                "required_foundation_quality": int(snapshot.get("required_foundation_quality", definition.required_foundation_quality)),
                "preparation_bp": int(snapshot.get("preparation_bp", 0)),
                "soul_prepare_bp": int(snapshot.get("soul_prepare_bp", 0)),
                "reputation_prepare_bp": int(snapshot.get("reputation_prepare_bp", 0)),
                "quest_prepare_bp": int(snapshot.get("quest_prepare_bp", 0)),
                "location_bonus_bp": int(snapshot.get("location_bonus_bp", 0)),
                "support_bonus_bp": int(snapshot.get("support_bonus_bp", 0)),
                "cross_realm_risk_bp": int(snapshot.get("cross_realm_risk_bp", 0)),
                "heart_demon_bonus_bp": int(snapshot.get("heart_demon_bonus_bp", 0)),
                "reward_currency": definition.reward_currency if success else 0,
                "reward_stamina": definition.reward_stamina if success else 0,
                "reward_world_merit": definition.reward_world_merit if success else 0,
                "reward_local_reputation": definition.reward_local_reputation if success else 0,
                "reward_items": dict(definition.reward_items or {}) if success else {},
                "status": status,
                "heart_demon_pending": heart_demon_pending,
            }
            connection.execute(
                "UPDATE breakthrough_sessions SET status = ?, result_json = ?, updated_at = ? WHERE id = ?",
                (status, json.dumps(result, ensure_ascii=False, sort_keys=True), now_text, session["id"]),
            )
            if heart_demon_pending:
                demon_session_id = uuid4().hex
                demon_snapshot = {
                    "breakthrough_session_id": session["id"],
                    "breakthrough_operation_id": operation_id,
                    "target_realm": "nascent_soul",
                    "expires_at": serialize_datetime(now + timedelta(hours=24)),
                    "pollution_before": int(row["pollution"]),
                    "pity_before_bp": pity_before,
                }
                connection.execute(
                    "INSERT INTO heart_demon_sessions(session_id, player_id, breakthrough_session_id, operation_id, status, expires_at, snapshot_json, created_at, updated_at) VALUES (?, ?, ?, ?, 'pending', ?, ?, ?, ?)",
                    (
                        demon_session_id,
                        row["id"],
                        session["id"],
                        f"{session['operation_id']}:heart_demon",
                        demon_snapshot["expires_at"],
                        json.dumps(demon_snapshot, ensure_ascii=False, sort_keys=True),
                        now_text,
                        now_text,
                    ),
                )
                self._project_heart_demon_created(
                    connection,
                    event_id=demon_session_id,
                    player_id=int(row["id"]),
                    breakthrough_session_id=str(session["session_id"]),
                    breakthrough_operation_id=operation_id,
                    starts_at=now_text,
                    expires_at=demon_snapshot["expires_at"],
                    snapshot=demon_snapshot,
                    created_at=now_text,
                )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (row["id"],)).fetchone()
            if updated is None:
                raise RuntimeError("breakthrough settlement returned no player")
            player = self._row_to_player(updated)
            payload = {"player": self._player_payload(player), "session_id": session["session_id"], "target_realm": session["target_realm"], **result}
            connection.execute(
                "INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (operation_id, operation_name, row["id"], request_hash, json.dumps(payload, ensure_ascii=False, sort_keys=True), now_text),
            )
            return self._breakthrough_settlement_from_payload(payload, replay=False)

    async def resolve_heart_demon(
        self,
        *,
        platform: str,
        platform_user_id: str,
        choice_key: str,
        operation_id: str,
    ) -> HeartDemonResolutionRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._resolve_heart_demon_sync,
                platform,
                platform_user_id,
                choice_key,
                operation_id,
            )

    def _resolve_heart_demon_sync(
        self,
        platform: str,
        platform_user_id: str,
        choice_key: str,
        operation_id: str,
    ) -> HeartDemonResolutionRecord:
        if choice_key not in {"heart_demon.face", "heart_demon.purify", "heart_demon.bargain"}:
            raise BreakthroughRequirementError("invalid heart demon choice")
        operation_name = "event.resolve_heart_demon"
        request_payload = {"platform": platform, "platform_user_id": platform_user_id, "choice_key": choice_key}
        request_hash = self._request_hash(operation_name, request_payload)
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
                return self._heart_demon_from_payload(json.loads(existing["result_json"]), replay=True)
            row = self._require_player(connection, platform, platform_user_id)
            session = connection.execute(
                "SELECT * FROM heart_demon_sessions WHERE player_id = ? AND status = 'pending' ORDER BY id DESC LIMIT 1",
                (row["id"],),
            ).fetchone()
            if session is None:
                resolved = connection.execute(
                    "SELECT 1 FROM heart_demon_sessions WHERE player_id = ? AND status = 'resolved' ORDER BY id DESC LIMIT 1",
                    (row["id"],),
                ).fetchone()
                if resolved is not None:
                    raise HeartDemonAlreadyResolvedError("heart demon has already been resolved")
                raise HeartDemonPendingError("no pending heart demon")
            try:
                expired = now >= datetime.fromisoformat(str(session["expires_at"]))
            except ValueError:
                expired = False
            effective_choice = "heart_demon.face" if expired else choice_key
            if effective_choice == "heart_demon.bargain" and str(row["path_key"] or "") != "demonic" and int(row["pollution"]) < 20:
                raise BreakthroughRequirementError("bargain requires a demonic path or pollution 20")
            inventory = inventory_value(row["inventory_json"])
            if effective_choice == "heart_demon.purify":
                if int(inventory.get("item.pill.soul_restore", 0)) < 1:
                    raise MaterialInsufficientError("soul restore pill is missing")
            pollution_before = int(row["pollution"])
            pollution_after = pollution_before
            merit_gain = 0
            fatigue_hours = 8
            pity_after = min(1200, int(row["breakthrough_pity_bp"]) + 400)
            bonus_after = int(row["heart_demon_bonus_bp"])
            if effective_choice == "heart_demon.face":
                merit_gain = 50
            elif effective_choice == "heart_demon.purify":
                pollution_after = max(0, pollution_before - 10)
                fatigue_hours = 3
            else:
                pollution_after = min(100, pollution_before + 20)
                fatigue_hours = 12
                bonus_after = 600
            fatigue_until = serialize_datetime(now + timedelta(hours=fatigue_hours))
            change_player_state(
                connection,
                row,
                updated_at=now_text,
                asset_values={"item.pill.soul_restore": 1} if effective_choice == "heart_demon.purify" else None,
                asset_mode="spend",
                value_delta={
                    "pollution": pollution_after - pollution_before,
                    "world_merit": merit_gain,
                    "breakthrough_pity_bp": pity_after - int(row["breakthrough_pity_bp"]),
                },
                maximums={"pollution": 100, "breakthrough_pity_bp": 1200},
                player_values={"heart_demon_bonus_bp": bonus_after, "soul_fatigue_until": fatigue_until},
            )
            result = {
                "session_id": str(session["session_id"]),
                "choice_key": effective_choice,
                "status": "resolved",
                "pity_after_bp": pity_after,
                "fatigue_until": fatigue_until,
                "pollution_before": pollution_before,
                "pollution_after": pollution_after,
                "world_merit_gained": merit_gain,
            }
            connection.execute(
                "UPDATE heart_demon_sessions SET status = 'resolved', choice_key = ?, result_json = ?, updated_at = ? WHERE id = ?",
                (effective_choice, json.dumps(result, ensure_ascii=False, sort_keys=True), now_text, session["id"]),
            )
            self._project_heart_demon_resolved(
                connection,
                event_id=str(session["session_id"]),
                choice_key=effective_choice,
                result=result,
                resolved_at=now_text,
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (row["id"],)).fetchone()
            if updated is None:
                raise RuntimeError("heart demon resolution returned no player")
            payload = {"player": self._player_payload(self._row_to_player(updated)), **result}
            connection.execute(
                "INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (operation_id, operation_name, row["id"], request_hash, json.dumps(payload, ensure_ascii=False, sort_keys=True), now_text),
            )
            return self._heart_demon_from_payload(payload, replay=False)

    async def recover_soul_fatigue(
        self,
        *,
        platform: str,
        platform_user_id: str,
        operation_id: str,
    ) -> SoulFatigueRecoveryRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._recover_soul_fatigue_sync, platform, platform_user_id, operation_id)

    def _recover_soul_fatigue_sync(self, platform: str, platform_user_id: str, operation_id: str) -> SoulFatigueRecoveryRecord:
        operation_name = "progression.recover_soul_fatigue"
        request_payload = {"platform": platform, "platform_user_id": platform_user_id}
        request_hash = self._request_hash(operation_name, request_payload)
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute("SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id = ?", (operation_id,)).fetchone()
            if existing is not None:
                if existing["operation_name"] != operation_name or existing["request_hash"] != request_hash:
                    raise OperationConflictError("operation input differs from its original request")
                payload = json.loads(existing["result_json"])
                return SoulFatigueRecoveryRecord(player=self._row_to_player(payload["player"]), recovered=bool(payload["recovered"]), already_completed=True)
            row = self._require_player(connection, platform, platform_user_id)
            fatigue = row["soul_fatigue_until"]
            if fatigue:
                try:
                    if datetime.fromisoformat(str(fatigue)) > now:
                        raise SoulFatigueActiveError("soul fatigue is active")
                except ValueError:
                    pass
            change_player_state(
                connection,
                row,
                updated_at=now_text,
                player_values={"soul_fatigue_until": None},
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (row["id"],)).fetchone()
            if updated is None:
                raise RuntimeError("soul fatigue recovery returned no player")
            payload = {"player": self._player_payload(self._row_to_player(updated)), "recovered": True}
            connection.execute("INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)", (operation_id, operation_name, row["id"], request_hash, json.dumps(payload, ensure_ascii=False, sort_keys=True), now_text))
            return SoulFatigueRecoveryRecord(player=self._row_to_player(updated), recovered=True)

    async def recover_weakness(
        self,
        *,
        platform: str,
        platform_user_id: str,
        early: bool,
        operation_id: str,
    ) -> WeaknessRecoveryRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._recover_weakness_sync, platform, platform_user_id, early, operation_id, None
            )

    async def recover_foundation_shock(
        self,
        *,
        platform: str,
        platform_user_id: str,
        early: bool,
        operation_id: str,
    ) -> WeaknessRecoveryRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._recover_weakness_sync, platform, platform_user_id, early, operation_id, "foundation_shock"
            )

    def _recover_weakness_sync(
        self,
        platform: str,
        platform_user_id: str,
        early: bool,
        operation_id: str,
        recovery_kind: str | None = None,
    ) -> WeaknessRecoveryRecord:
        last_error: Exception | None = None
        for attempt in range(5):
            try:
                return self._recover_weakness_once(platform, platform_user_id, early, operation_id, recovery_kind)
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).lower():
                    raise
                if attempt == 4:
                    raise RepositoryBusyError("database remained locked") from exc
                last_error = exc
                time.sleep(0.01 * (2**attempt))
        raise RepositoryBusyError("database remained locked") from last_error

    def _recover_weakness_once(
        self,
        platform: str,
        platform_user_id: str,
        early: bool,
        operation_id: str,
        recovery_kind: str | None = None,
    ) -> WeaknessRecoveryRecord:
        operation_name = "progression.recover_foundation_shock" if recovery_kind == "foundation_shock" else "progression.recover_weakness"
        request_payload = {"platform": platform, "platform_user_id": platform_user_id, "early": early}
        request_hash = self._request_hash(operation_name, request_payload)
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
                payload = json.loads(existing["result_json"])
                return WeaknessRecoveryRecord(
                    player=self._row_to_player(payload["player"]),
                    early=bool(payload["early"]),
                    spirit_stones_spent=int(payload["spirit_stones_spent"]),
                    medicine_consumed=bool(payload["medicine_consumed"]),
                    medicine_key=str(payload.get("medicine_key", "item.pill.healing_low")),
                    already_completed=True,
                )
            row = self._require_player(connection, platform, platform_user_id)
            weakness_until = row["weakness_until"]
            if not weakness_until:
                raise WeaknessNotActiveError("no breakthrough weakness is active")
            until = datetime.fromisoformat(str(weakness_until))
            expired = now >= until
            inventory = inventory_value(row["inventory_json"])
            medicine_key = "item.pill.golden_core_restore" if recovery_kind == "foundation_shock" else "item.pill.healing_low"
            stones_cost = 200 if recovery_kind == "foundation_shock" else 50
            medicine_consumed = False
            stones_spent = 0
            if not expired and not early:
                raise WeaknessActiveError("weakness has not expired")
            if not expired and early:
                if int(inventory.get(medicine_key, 0)) < 1:
                    raise MaterialInsufficientError("early recovery requires a recovery pill")
                if int(row["spirit_stones"]) < stones_cost:
                    raise CurrencyInsufficientError("early recovery requires spirit stones")
                medicine_consumed = True
                stones_spent = stones_cost
            change_player_state(
                connection,
                row,
                updated_at=now_text,
                asset_values=(
                    {"spirit_stones": stones_cost, medicine_key: 1}
                    if medicine_consumed
                    else None
                ),
                asset_mode="spend",
                player_values={"weakness_until": None},
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (row["id"],)).fetchone()
            if updated is None:
                raise RuntimeError("weakness recovery returned no player")
            player = self._row_to_player(updated)
            payload = {
                "player": self._player_payload(player),
                "early": early,
                "spirit_stones_spent": stones_spent,
                "medicine_consumed": medicine_consumed,
                "medicine_key": medicine_key,
            }
            connection.execute(
                "INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (operation_id, operation_name, row["id"], request_hash, json.dumps(payload, ensure_ascii=False, sort_keys=True), now_text),
            )
            return WeaknessRecoveryRecord(
                player=player,
                early=early,
                spirit_stones_spent=stones_spent,
                medicine_consumed=medicine_consumed,
                medicine_key=medicine_key,
            )

    @staticmethod
    def _breakthrough_settlement_from_payload(payload: dict[str, Any], *, replay: bool) -> BreakthroughSettlementRecord:
        return BreakthroughSettlementRecord(
            player=SQLitePlayerRepository._row_to_player(payload["player"]),
            session_id=str(payload["session_id"]),
            target_realm=str(payload["target_realm"]),
            status=str(payload["status"]),
            success=bool(payload["success"]),
            roll_bp=int(payload["roll_bp"]),
            success_bp=int(payload["success_bp"]),
            cultivation_before=int(payload["cultivation_before"]),
            cultivation_after=int(payload["cultivation_after"]),
            pity_before_bp=int(payload["pity_before_bp"]),
            pity_after_bp=int(payload["pity_after_bp"]),
            protection_consumed=bool(payload["protection_consumed"]),
            weakness_until=payload.get("weakness_until"),
            currency_spent=int(payload.get("currency_spent", 0)),
            materials={str(key): int(value) for key, value in payload.get("materials", {}).items()},
            preparation_bp=int(payload.get("preparation_bp", 0)),
            reward_currency=int(payload.get("reward_currency", 0)),
            reward_stamina=int(payload.get("reward_stamina", 0)),
            reward_world_merit=int(payload.get("reward_world_merit", 0)),
            reward_local_reputation=int(payload.get("reward_local_reputation", 0)),
            reward_items={str(key): int(value) for key, value in payload.get("reward_items", {}).items()},
            already_completed=replay,
            heart_demon_pending=bool(payload.get("heart_demon_pending", False)),
            cross_realm_risk_bp=int(payload.get("cross_realm_risk_bp", 0)),
            heart_demon_bonus_bp=int(payload.get("heart_demon_bonus_bp", 0)),
            soul_prepare_bp=int(payload.get("soul_prepare_bp", 0)),
            reputation_prepare_bp=int(payload.get("reputation_prepare_bp", 0)),
            quest_prepare_bp=int(payload.get("quest_prepare_bp", 0)),
        )

    @staticmethod
    def _heart_demon_from_payload(payload: dict[str, Any], *, replay: bool) -> HeartDemonResolutionRecord:
        return HeartDemonResolutionRecord(
            player=SQLitePlayerRepository._row_to_player(payload["player"]),
            session_id=str(payload["session_id"]),
            choice_key=str(payload["choice_key"]),
            status=str(payload["status"]),
            pity_after_bp=int(payload.get("pity_after_bp", 0)),
            fatigue_until=payload.get("fatigue_until"),
            pollution_before=int(payload.get("pollution_before", 0)),
            pollution_after=int(payload.get("pollution_after", 0)),
            world_merit_gained=int(payload.get("world_merit_gained", 0)),
            already_completed=replay,
        )
