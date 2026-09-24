"""SQLite transactions for exploration sessions.

The exploration repository owns session and reward state. Encounter execution
delegates to the shared automatic-combat repository and only commits frozen
exploration rewards after that battle reaches a terminal result.
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
    CLOUD_BOAT_STORM_CHANCE_BP,
    CLOUD_BOAT_STORM_CHOICES,
    CLOUD_BOAT_STORM_PAY_COST,
    CLOUD_BOAT_STORM_WAIT_SECONDS,
    cloud_boat_storm_roll_bp,
    has_cloud_mine_access,
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


class ExplorationRepositoryMixin:
    async def start_exploration(
        self,
        *,
        platform: str,
        platform_user_id: str,
        mode_key: str,
        operation_id: str,
    ) -> ExplorationStartRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._start_exploration_sync,
                platform,
                platform_user_id,
                mode_key,
                operation_id,
            )

    def _start_exploration_sync(self, platform: str, platform_user_id: str, mode_key: str, operation_id: str) -> ExplorationStartRecord:
        last_error: Exception | None = None
        for attempt in range(5):
            try:
                return self._start_exploration_once(platform, platform_user_id, mode_key, operation_id)
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).lower():
                    raise
                if attempt == 4:
                    raise RepositoryBusyError("database remained locked") from exc
                last_error = exc
                time.sleep(0.01 * (2**attempt))
        raise RepositoryBusyError("database remained locked") from last_error

    def _start_exploration_once(self, platform: str, platform_user_id: str, mode_key: str, operation_id: str) -> ExplorationStartRecord:
        definition = exploration_definition(mode_key)
        operation_name = "exploration.start"
        request_payload = {
            "platform": platform,
            "platform_user_id": platform_user_id,
            "mode_key": definition.key,
        }
        request_hash = self._request_hash(operation_name, request_payload)
        now = self._now()
        business_date = now.date().isoformat()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            if existing is not None:
                if existing["operation_name"] != operation_name or existing["request_hash"] != request_hash:
                    raise OperationConflictError("operation input differs from its original request")
                return self._exploration_start_from_payload(json.loads(existing["result_json"]), replay=True)

            row = self._require_player(connection, platform, platform_user_id)
            if row["stage"] not in {STAGE_MORTAL, "seeker", "cultivator"}:
                raise PlayerStageConflictError("player is not ready for exploration")
            if str(row["location_key"]) != definition.location_key:
                raise LocationRequirementError("exploration requires a specific location")
            if not exploration_meets_realm(
                str(row["realm_key"]), int(row["realm_layer"]), definition.required_realm, definition.required_layer
            ):
                raise LocationRequirementError("realm requirement is not met")
            if definition.key == "explore.spring_gather":
                intro_state = self._json_object(row["intro_json"], {})
                if "guide.gather_blood_grass" not in set(intro_state.get("flags", [])):
                    raise LocationRequirementError("spring gathering requires the gathering lesson")

            inventory = self._json_object(row["inventory_json"], {})
            intro_state = self._json_object(row["intro_json"], {})
            if definition.key == "explore.cloud_mine" and not has_cloud_mine_access(
                subprofession_key=row["subprofession_key"],
                inventory=inventory,
                intro_flags={str(flag) for flag in intro_state.get("flags", [])},
            ):
                raise LocationRequirementError("cloud mine access is missing")

            player_id = int(row["id"])
            active = connection.execute(
                "SELECT 1 FROM exploration_sessions WHERE player_id = ? AND status IN ('created', 'running', 'combat_pending') LIMIT 1",
                (player_id,),
            ).fetchone()
            if active is not None:
                raise ExplorationBusyError("exploration is already active")
            for table, statuses in (
                ("travel_sessions", ("running",)),
                ("cultivation_sessions", ("running",)),
                ("production_orders", ("processing",)),
                ("breakthrough_sessions", ("preparing",)),
                ("cloud_boat_sessions", ("created", "running")),
            ):
                placeholders = ", ".join("?" for _ in statuses)
                busy = connection.execute(
                    f"SELECT 1 FROM {table} WHERE player_id = ? AND status IN ({placeholders}) LIMIT 1",
                    (player_id, *statuses),
                ).fetchone()
                if busy is not None:
                    raise ExplorationBusyError("another action is already running")
            retreat = connection.execute(
                "SELECT 1 FROM retreat_sessions WHERE player_id = ? AND status = 'running' LIMIT 1",
                (player_id,),
            ).fetchone()
            if retreat is not None:
                raise ExplorationBusyError("retreat is already running")
            used = connection.execute(
                "SELECT COUNT(*) AS count FROM exploration_sessions WHERE player_id = ? AND mode_key = ? AND business_date = ?",
                (player_id, definition.key, business_date),
            ).fetchone()
            if used is not None and int(used["count"]) >= definition.daily_limit:
                raise ExplorationQuotaExhaustedError("exploration mode reached its daily limit")
            stamina = int(row["stamina"])
            if stamina < definition.stamina_cost:
                raise ResourceInsufficientError("stamina is insufficient")
            energy = int(row["energy"])
            if energy < definition.energy_cost:
                raise EnergyInsufficientError("energy is insufficient")

            exploration_id = uuid4().hex
            starts_at = serialize_datetime(now)
            ends_at = serialize_datetime(now + timedelta(seconds=definition.duration_seconds))
            snapshot = {
                "mode_key": definition.key,
                "location_key": definition.location_key,
                "realm_key": row["realm_key"],
                "realm_layer": int(row["realm_layer"]),
                "qualification": self._json_object(row["qualification_json"], {}),
                "path_key": row["path_key"],
                "rule_version": definition.rule_version,
                "random_pool": definition.random_pool,
                "random_seed": operation_id,
                "battle_chance_bp": definition.battle_chance_bp,
                "business_date": business_date,
                "stamina_cost": definition.stamina_cost,
                "energy_cost": definition.energy_cost,
                "content_version": definition.content_version,
                "storm_chance_bp": (
                    CLOUD_BOAT_STORM_CHANCE_BP if definition.key == "explore.cloud_boat_trial" else 0
                ),
                "storm_roll_bp": (
                    cloud_boat_storm_roll_bp(operation_id) if definition.key == "explore.cloud_boat_trial" else None
                ),
                "max_hp": int(row["max_hp"]),
                "initiative": int(row["initiative"]),
                "equipment": list(self._battle_equipment_snapshot(connection, player_id)),
            }
            connection.execute(
                "UPDATE players SET stamina = ?, energy = ?, updated_at = ? WHERE id = ?",
                (stamina - definition.stamina_cost, energy - definition.energy_cost, starts_at, player_id),
            )
            connection.execute(
                """
                INSERT INTO exploration_sessions(
                    exploration_id, player_id, operation_id, mode_key, location_key, status,
                    starts_at, ends_at, stamina_cost, daily_limit, business_date,
                    snapshot_json, result_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'created', ?, ?, ?, ?, ?, ?, '{}', ?, ?)
                """,
                (
                    exploration_id,
                    player_id,
                    operation_id,
                    definition.key,
                    definition.location_key,
                    starts_at,
                    ends_at,
                    definition.stamina_cost,
                    definition.daily_limit,
                    business_date,
                    json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
                    starts_at,
                    starts_at,
                ),
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (player_id,)).fetchone()
            player = self._row_to_player(updated)
            payload = {
                "player": self._player_payload(player),
                "exploration_id": exploration_id,
                "mode_key": definition.key,
                "location_key": definition.location_key,
                "status": "created",
                "starts_at": starts_at,
                "ends_at": ends_at,
                "stamina_cost": definition.stamina_cost,
                "energy_cost": definition.energy_cost,
                "content_version": definition.content_version,
                "daily_limit": definition.daily_limit,
            }
            connection.execute(
                "INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    operation_id,
                    operation_name,
                    player_id,
                    request_hash,
                    json.dumps(payload, ensure_ascii=False, sort_keys=True),
                    starts_at,
                ),
            )
            return self._exploration_start_from_payload(payload)

    @staticmethod
    def _exploration_start_from_payload(payload: dict[str, Any], replay: bool = False) -> ExplorationStartRecord:
        return ExplorationStartRecord(
            player=SQLitePlayerRepository._row_to_player(payload["player"]),
            exploration_id=str(payload["exploration_id"]),
            mode_key=str(payload["mode_key"]),
            location_key=str(payload["location_key"]),
            status=str(payload["status"]),
            starts_at=str(payload["starts_at"]),
            ends_at=str(payload["ends_at"]),
            stamina_cost=int(payload["stamina_cost"]),
            daily_limit=int(payload["daily_limit"]),
            energy_cost=int(payload.get("energy_cost", 0)),
            already_completed=replay,
        )

    async def settle_exploration(
        self,
        *,
        platform: str,
        platform_user_id: str,
        operation_id: str,
    ) -> ExplorationSettlementRecord:
        await self.initialize()
        async with self._inflight:
            record = await asyncio.to_thread(
                self._settle_exploration_sync,
                platform,
                platform_user_id,
                operation_id,
            )
        if record.status != "combat_pending":
            return record
        battle = await self.start_exploration_battle(
            platform=platform,
            platform_user_id=platform_user_id,
            exploration_id=record.exploration_id,
            mode_key=record.mode_key,
            operation_id=f"exploration.battle:{record.exploration_id}",
        )
        resolved = await self._run_exploration_battle(battle.battle_id, battle.round_no)
        return await self.settle_exploration_combat(
            platform=platform,
            platform_user_id=platform_user_id,
            exploration_id=record.exploration_id,
            battle_id=resolved.battle_id,
            operation_id=f"{operation_id}:combat",
        )

    async def _run_exploration_battle(self, battle_id: str, completed_round: int):
        turn = None
        for expected_round in range(completed_round + 1, 21):
            turn = await self.run_battle_turn(
                battle_id=battle_id,
                expected_round=expected_round,
            )
            if turn.status not in {"created", "running"}:
                break
        if turn is None or turn.status in {"created", "running"}:
            from ..persistence.errors import BattleNotReadyError

            raise BattleNotReadyError("automatic exploration battle did not reach a terminal state")
        return await self.resolve_battle(battle_id=battle_id)

    async def settle_exploration_combat(
        self,
        *,
        platform: str,
        platform_user_id: str,
        exploration_id: str,
        battle_id: str,
        operation_id: str,
    ) -> ExplorationSettlementRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._retry_sync,
                self._settle_exploration_combat_once,
                platform,
                platform_user_id,
                exploration_id,
                battle_id,
                operation_id,
            )

    def _settle_exploration_combat_once(
        self,
        platform: str,
        platform_user_id: str,
        exploration_id: str,
        battle_id: str,
        operation_id: str,
    ) -> ExplorationSettlementRecord:
        operation_name = "exploration.settle_combat"
        request_hash = self._request_hash(
            operation_name,
            {
                "platform": platform,
                "platform_user_id": platform_user_id,
                "exploration_id": exploration_id,
                "battle_id": battle_id,
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
                return self._exploration_settlement_from_payload(json.loads(existing["result_json"]), replay=True)
            row = self._require_player(connection, platform, platform_user_id)
            session = connection.execute(
                "SELECT * FROM exploration_sessions WHERE exploration_id = ? AND player_id = ?",
                (exploration_id, row["id"]),
            ).fetchone()
            if session is None:
                raise ExplorationNotFoundError("exploration does not exist")
            if str(session["status"]) != "combat_pending":
                stored = self._json_object(session["result_json"], {})
                payload = {
                    "player": self._player_payload(self._row_to_player(row)),
                    "exploration_id": exploration_id,
                    "mode_key": session["mode_key"],
                    "location_key": session["location_key"],
                    "status": session["status"],
                    "result": self._json_object(stored.get("result"), {}),
                    "battle_pending": False,
                    "expired": str(session["status"]) == "expired",
                    "stamina_cost": int(session["stamina_cost"]),
                    "energy_cost": int(self._json_object(session["snapshot_json"], {}).get("energy_cost", 0)),
                    "content_version": self._json_object(session["snapshot_json"], {}).get("content_version", "content-0.1"),
                    "battle_id": stored.get("battle_id"),
                    "battle_outcome": stored.get("battle_outcome"),
                }
                connection.execute(
                    "INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (operation_id, operation_name, row["id"], request_hash, json.dumps(payload, ensure_ascii=False, sort_keys=True), now_text),
                )
                return self._exploration_settlement_from_payload(payload, replay=True)
            battle = connection.execute(
                "SELECT status, result_json FROM battle_sessions WHERE battle_id = ? AND player_id = ?",
                (battle_id, row["id"]),
            ).fetchone()
            if battle is None or str(battle["status"]) != "settled":
                raise ExplorationCombatPendingError("exploration battle is not settled")
            battle_result = self._json_object(battle["result_json"], {})
            battle_outcome = str(battle_result.get("outcome", ""))
            frozen = self._json_object(session["result_json"], {})
            frozen_result = {
                str(key): int(value) for key, value in dict(frozen.get("result", {})).items()
            }
            result = frozen_result if battle_outcome == "won" else {}
            inventory = self._json_object(row["inventory_json"], {})
            stones = int(row["spirit_stones"])
            cultivation = int(row["cultivation"])
            total_cultivation = int(row["total_cultivation"])
            for key, quantity in result.items():
                if key == "spirit_stones":
                    stones += quantity
                elif key == "cultivation":
                    cultivation += quantity
                    total_cultivation += quantity
                else:
                    inventory[key] = int(inventory.get(key, 0)) + quantity
            connection.execute(
                "UPDATE players SET spirit_stones=?, cultivation=?, total_cultivation=?, inventory_json=?, updated_at=? WHERE id=?",
                (stones, cultivation, total_cultivation, json.dumps(inventory, ensure_ascii=False, sort_keys=True), now_text, row["id"]),
            )
            result_json = {
                "status": "settled",
                "result": result,
                "frozen_result": frozen_result,
                "battle_pending": False,
                "battle_id": battle_id,
                "battle_outcome": battle_outcome,
                "expired": False,
                "settled_at": now_text,
            }
            connection.execute(
                "UPDATE exploration_sessions SET status='settled', result_json=?, updated_at=? WHERE id=? AND status='combat_pending'",
                (json.dumps(result_json, ensure_ascii=False, sort_keys=True), now_text, session["id"]),
            )
            if str(session["mode_key"]) == "explore.spring_gather":
                self._record_spirit_spring_contribution(
                    connection,
                    player_id=int(row["id"]),
                    source_operation_id=str(session["operation_id"]),
                    quantity=int(result.get("item.herb.spirit_leaf", 0)),
                    occurred_at=datetime.fromisoformat(str(session["starts_at"])),
                )
            updated = connection.execute("SELECT * FROM players WHERE id=?", (row["id"],)).fetchone()
            payload = {
                "player": self._player_payload(self._row_to_player(updated)),
                "exploration_id": exploration_id,
                "mode_key": session["mode_key"],
                "location_key": session["location_key"],
                "status": "settled",
                "result": result,
                "battle_pending": False,
                "expired": False,
                "stamina_cost": int(session["stamina_cost"]),
                "energy_cost": int(self._json_object(session["snapshot_json"], {}).get("energy_cost", 0)),
                "content_version": self._json_object(session["snapshot_json"], {}).get("content_version", "content-0.1"),
                "battle_id": battle_id,
                "battle_outcome": battle_outcome,
            }
            connection.execute(
                "INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (operation_id, operation_name, row["id"], request_hash, json.dumps(payload, ensure_ascii=False, sort_keys=True), now_text),
            )
            return self._exploration_settlement_from_payload(payload)

    def _settle_exploration_sync(self, platform: str, platform_user_id: str, operation_id: str) -> ExplorationSettlementRecord:
        last_error: Exception | None = None
        for attempt in range(5):
            try:
                return self._settle_exploration_once(platform, platform_user_id, operation_id)
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).lower():
                    raise
                if attempt == 4:
                    raise RepositoryBusyError("database remained locked") from exc
                last_error = exc
                time.sleep(0.01 * (2**attempt))
        raise RepositoryBusyError("database remained locked") from last_error

    def _settle_exploration_once(self, platform: str, platform_user_id: str, operation_id: str) -> ExplorationSettlementRecord:
        operation_name = "exploration.settle"
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
                return self._exploration_settlement_from_payload(json.loads(existing["result_json"]), replay=True)
            row = self._require_player(connection, platform, platform_user_id)
            session = connection.execute(
                "SELECT * FROM exploration_sessions WHERE player_id = ? AND status IN ('created', 'running', 'combat_pending') ORDER BY id DESC LIMIT 1",
                (row["id"],),
            ).fetchone()
            if session is None:
                raise ExplorationNotFoundError("no active exploration")
            if session["status"] == "combat_pending":
                stored_result = self._json_object(session["result_json"], {})
                result = {
                    str(key): int(value)
                    for key, value in dict(stored_result.get("result", {})).items()
                }
                payload = {
                    "player": self._player_payload(self._row_to_player(row)),
                    "exploration_id": session["exploration_id"],
                    "mode_key": session["mode_key"],
                    "location_key": session["location_key"],
                    "status": "combat_pending",
                    "result": result,
                    "battle_pending": True,
                    "expired": False,
                    "stamina_cost": int(session["stamina_cost"]),
                    "energy_cost": int(self._json_object(session["snapshot_json"], {}).get("energy_cost", 0)),
                    "content_version": self._json_object(session["snapshot_json"], {}).get("content_version", "content-0.1"),
                    "battle_id": stored_result.get("battle_id"),
                    "battle_outcome": stored_result.get("battle_outcome"),
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
                return self._exploration_settlement_from_payload(payload)
            snapshot = self._json_object(session["snapshot_json"], {})
            stored_result = self._json_object(session["result_json"], {})
            if (
                str(session["mode_key"]) == "explore.cloud_boat_trial"
                and bool(stored_result.get("storm_pending"))
            ):
                storm_deadline = datetime.fromisoformat(str(stored_result["storm_deadline"]))
                frozen_result = {
                    str(key): int(value)
                    for key, value in dict(stored_result.get("frozen_result", {})).items()
                }
                if now < storm_deadline:
                    payload = {
                        "player": self._player_payload(self._row_to_player(row)),
                        "exploration_id": session["exploration_id"],
                        "mode_key": session["mode_key"],
                        "location_key": session["location_key"],
                        "status": "storm_pending",
                        "result": {},
                        "battle_pending": False,
                        "expired": False,
                        "stamina_cost": int(session["stamina_cost"]),
                        "energy_cost": int(snapshot.get("energy_cost", 0)),
                        "content_version": snapshot.get("content_version", "content-0.1"),
                        "storm_pending": True,
                        "storm_options": list(CLOUD_BOAT_STORM_CHOICES),
                        "storm_deadline": stored_result["storm_deadline"],
                        "storm_preview": frozen_result,
                    }
                    connection.execute(
                        "INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                        (operation_id, operation_name, row["id"], request_hash, json.dumps(payload, ensure_ascii=False, sort_keys=True), now_text),
                    )
                    return self._exploration_settlement_from_payload(payload)
                # A missed prompt defaults to waiting, preserving the frozen reward.
                new_ends_at = now + timedelta(seconds=CLOUD_BOAT_STORM_WAIT_SECONDS)
                stored_result.update(
                    {
                        "storm_pending": False,
                        "storm_choice": "wait",
                        "storm_resolved": True,
                        "storm_deadline": serialize_datetime(new_ends_at),
                    }
                )
                connection.execute(
                    "UPDATE exploration_sessions SET ends_at = ?, result_json = ?, updated_at = ? WHERE id = ? AND status IN ('created', 'running')",
                    (serialize_datetime(new_ends_at), json.dumps(stored_result, ensure_ascii=False, sort_keys=True), now_text, session["id"]),
                )
                updated = connection.execute("SELECT * FROM players WHERE id = ?", (row["id"],)).fetchone()
                payload = {
                    "player": self._player_payload(self._row_to_player(updated)),
                    "exploration_id": session["exploration_id"],
                    "mode_key": session["mode_key"],
                    "location_key": session["location_key"],
                    "status": "running",
                    "result": {},
                    "battle_pending": False,
                    "expired": False,
                    "stamina_cost": int(session["stamina_cost"]),
                    "energy_cost": int(snapshot.get("energy_cost", 0)),
                    "content_version": snapshot.get("content_version", "content-0.1"),
                    "storm_pending": False,
                    "storm_options": [],
                    "storm_deadline": serialize_datetime(new_ends_at),
                    "storm_choice": "wait",
                }
                connection.execute(
                    "INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (operation_id, operation_name, row["id"], request_hash, json.dumps(payload, ensure_ascii=False, sort_keys=True), now_text),
                )
                return self._exploration_settlement_from_payload(payload)
            ends_at = datetime.fromisoformat(str(session["ends_at"]))
            if now < ends_at:
                raise ExplorationNotReadyError("exploration is not ready")
            expired = now > ends_at + timedelta(hours=24)
            result: dict[str, int] = {}
            battle_pending = False
            status = "expired" if expired else "settled"
            if not expired:
                seed = str(snapshot.get("random_seed", session["operation_id"]))
                battle_pending = battle_roll_bp(seed + ":battle") < int(snapshot.get("battle_chance_bp", 0))
                result = settlement_result(str(session["mode_key"]), seed)
                storm_hit = (
                    str(session["mode_key"]) == "explore.cloud_boat_trial"
                    and not bool(stored_result.get("storm_resolved"))
                    and int(snapshot.get("storm_roll_bp", 10000)) < int(snapshot.get("storm_chance_bp", 0))
                )
                if storm_hit:
                    storm_deadline = serialize_datetime(now + timedelta(seconds=CLOUD_BOAT_STORM_WAIT_SECONDS))
                    pending_result = {
                        "status": "storm_pending",
                        "result": {},
                        "frozen_result": result,
                        "storm_pending": True,
                        "storm_options": list(CLOUD_BOAT_STORM_CHOICES),
                        "storm_deadline": storm_deadline,
                        "energy_cost": int(snapshot.get("energy_cost", 0)),
                        "content_version": snapshot.get("content_version", "content-0.1"),
                    }
                    connection.execute(
                        "UPDATE exploration_sessions SET result_json = ?, updated_at = ? WHERE id = ? AND status IN ('created', 'running')",
                        (json.dumps(pending_result, ensure_ascii=False, sort_keys=True), now_text, session["id"]),
                    )
                    updated = connection.execute("SELECT * FROM players WHERE id = ?", (row["id"],)).fetchone()
                    payload = {
                        "player": self._player_payload(self._row_to_player(updated)),
                        "exploration_id": session["exploration_id"],
                        "mode_key": session["mode_key"],
                        "location_key": session["location_key"],
                        "status": "storm_pending",
                        "result": {},
                        "battle_pending": False,
                        "expired": False,
                        "stamina_cost": int(session["stamina_cost"]),
                        "energy_cost": int(snapshot.get("energy_cost", 0)),
                        "content_version": snapshot.get("content_version", "content-0.1"),
                        "storm_pending": True,
                        "storm_options": list(CLOUD_BOAT_STORM_CHOICES),
                        "storm_deadline": storm_deadline,
                        "storm_preview": result,
                    }
                    connection.execute(
                        "INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                        (operation_id, operation_name, row["id"], request_hash, json.dumps(payload, ensure_ascii=False, sort_keys=True), now_text),
                    )
                    return self._exploration_settlement_from_payload(payload)
                if battle_pending:
                    status = "combat_pending"

            inventory = self._json_object(row["inventory_json"], {})
            stones = int(row["spirit_stones"])
            cultivation = int(row["cultivation"])
            total_cultivation = int(row["total_cultivation"])
            if status == "settled":
                for key, quantity in result.items():
                    if key == "spirit_stones":
                        stones += int(quantity)
                    elif key == "cultivation":
                        cultivation += int(quantity)
                        total_cultivation += int(quantity)
                    else:
                        inventory[key] = int(inventory.get(key, 0)) + int(quantity)
                connection.execute(
                    """
                    UPDATE players
                    SET spirit_stones = ?, cultivation = ?, total_cultivation = ?, inventory_json = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        stones,
                        cultivation,
                        total_cultivation,
                        json.dumps(inventory, ensure_ascii=False, sort_keys=True),
                        now_text,
                        row["id"],
                    ),
                )
            result_json = {
                "status": status,
                "result": result,
                "frozen_result": result,
                "battle_pending": battle_pending,
                "expired": expired,
                "storm_pending": False,
                "storm_choice": stored_result.get("storm_choice"),
                "energy_cost": int(snapshot.get("energy_cost", 0)),
                "content_version": snapshot.get("content_version", "content-0.1"),
                "settled_at": now_text,
            }
            connection.execute(
                "UPDATE exploration_sessions SET status = ?, result_json = ?, updated_at = ? WHERE id = ? AND status IN ('created', 'running')",
                (status, json.dumps(result_json, ensure_ascii=False, sort_keys=True), now_text, session["id"]),
            )
            if status == "settled" and str(session["mode_key"]) == "explore.spring_gather":
                self._record_spirit_spring_contribution(
                    connection,
                    player_id=int(row["id"]),
                    source_operation_id=str(session["operation_id"]),
                    quantity=int(result.get("item.herb.spirit_leaf", 0)),
                    occurred_at=datetime.fromisoformat(str(session["starts_at"])),
                )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (row["id"],)).fetchone()
            player = self._row_to_player(updated)
            payload = {
                "player": self._player_payload(player),
                "exploration_id": session["exploration_id"],
                "mode_key": session["mode_key"],
                "location_key": session["location_key"],
                "status": status,
                "result": result,
                "battle_pending": battle_pending,
                "expired": expired,
                "stamina_cost": int(session["stamina_cost"]),
                "energy_cost": int(snapshot.get("energy_cost", 0)),
                "content_version": snapshot.get("content_version", "content-0.1"),
                "battle_id": result_json.get("battle_id"),
                "battle_outcome": result_json.get("battle_outcome"),
                "storm_pending": False,
                "storm_options": [],
                "storm_deadline": None,
                "storm_choice": result_json.get("storm_choice"),
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
            return self._exploration_settlement_from_payload(payload)
    @staticmethod
    def _exploration_settlement_from_payload(payload: dict[str, Any], replay: bool = False) -> ExplorationSettlementRecord:
        return ExplorationSettlementRecord(
            player=SQLitePlayerRepository._row_to_player(payload["player"]),
            exploration_id=str(payload["exploration_id"]),
            mode_key=str(payload["mode_key"]),
            location_key=str(payload["location_key"]),
            status=str(payload["status"]),
            result={str(key): int(value) for key, value in dict(payload.get("result", {})).items()},
            battle_pending=bool(payload.get("battle_pending", False)),
            expired=bool(payload.get("expired", False)),
            stamina_cost=int(payload.get("stamina_cost", 0)),
            energy_cost=int(payload.get("energy_cost", 0)),
            content_version=str(payload.get("content_version", "content-0.1")),
            battle_id=str(payload["battle_id"]) if payload.get("battle_id") else None,
            battle_outcome=str(payload["battle_outcome"]) if payload.get("battle_outcome") else None,
            storm_pending=bool(payload.get("storm_pending", False)),
            storm_options=tuple(str(item) for item in payload.get("storm_options", ())),
            storm_deadline=str(payload["storm_deadline"]) if payload.get("storm_deadline") else None,
            storm_choice=str(payload["storm_choice"]) if payload.get("storm_choice") else None,
            already_completed=replay,
        )

    async def choose_exploration_storm(
        self,
        *,
        platform: str,
        platform_user_id: str,
        choice: str,
        operation_id: str,
    ) -> ExplorationSettlementRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._choose_exploration_storm_once,
                platform,
                platform_user_id,
                choice,
                operation_id,
            )

    def _choose_exploration_storm_once(
        self,
        platform: str,
        platform_user_id: str,
        choice: str,
        operation_id: str,
    ) -> ExplorationSettlementRecord:
        from ..persistence.errors import (
            CurrencyInsufficientError,
            ExplorationStormChoiceError,
            ExplorationStormNotPendingError,
        )

        normalized = str(choice).strip()
        aliases = {
            "wait": "wait",
            "等待": "wait",
            "等候": "wait",
            "pay": "pay",
            "支付": "pay",
            "付费": "pay",
            "turn_back": "turn_back",
            "返航": "turn_back",
            "返回": "turn_back",
        }
        normalized = aliases.get(normalized, normalized)
        if normalized not in CLOUD_BOAT_STORM_CHOICES:
            raise ExplorationStormChoiceError("unsupported storm choice")
        operation_name = "exploration.storm"
        request_hash = self._request_hash(
            operation_name,
            {"platform": platform, "platform_user_id": platform_user_id, "choice": normalized},
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
                return self._exploration_settlement_from_payload(json.loads(existing["result_json"]), replay=True)
            row = self._require_player(connection, platform, platform_user_id)
            session = connection.execute(
                "SELECT * FROM exploration_sessions WHERE player_id = ? AND status IN ('created', 'running') ORDER BY id DESC LIMIT 1",
                (row["id"],),
            ).fetchone()
            if session is None:
                raise ExplorationStormNotPendingError("no active cloud boat trial")
            snapshot = self._json_object(session["snapshot_json"], {})
            stored = self._json_object(session["result_json"], {})
            if str(session["mode_key"]) != "explore.cloud_boat_trial" or not stored.get("storm_pending"):
                raise ExplorationStormNotPendingError("storm choice is not pending")
            effective_choice = normalized
            deadline = datetime.fromisoformat(str(stored["storm_deadline"]))
            if now >= deadline:
                effective_choice = "wait"
            frozen_result = {
                str(key): int(value)
                for key, value in dict(stored.get("frozen_result", {})).items()
            }
            result: dict[str, int] = {}
            status = "settled"
            ends_at = str(session["ends_at"])
            stones = int(row["spirit_stones"])
            cultivation = int(row["cultivation"])
            total_cultivation = int(row["total_cultivation"])
            stamina = int(row["stamina"])
            inventory = self._json_object(row["inventory_json"], {})
            if effective_choice == "wait":
                status = "running"
                ends_at = serialize_datetime(now + timedelta(seconds=CLOUD_BOAT_STORM_WAIT_SECONDS))
                result_json = {
                    **stored,
                    "status": status,
                    "storm_pending": False,
                    "storm_resolved": True,
                    "storm_choice": "wait",
                    "storm_deadline": ends_at,
                }
            elif effective_choice == "pay":
                if stones < CLOUD_BOAT_STORM_PAY_COST:
                    raise CurrencyInsufficientError("cloud boat storm payment requires spirit stones")
                stones -= CLOUD_BOAT_STORM_PAY_COST
                result = dict(frozen_result)
                result["cultivation"] = int(result.get("cultivation", 0)) + 200
                status = "settled"
                for key, quantity in result.items():
                    if key == "cultivation":
                        cultivation += int(quantity)
                        total_cultivation += int(quantity)
                    elif key == "spirit_stones":
                        stones += int(quantity)
                    else:
                        inventory[key] = int(inventory.get(key, 0)) + int(quantity)
                result_json = {
                    **stored,
                    "status": status,
                    "result": result,
                    "storm_pending": False,
                    "storm_resolved": True,
                    "storm_choice": "pay",
                    "settled_at": now_text,
                }
            else:
                refund = min(int(session["stamina_cost"]) // 2, max(0, int(row["stamina_max"]) - stamina))
                stamina += refund
                result = {"stamina_refund": refund}
                result_json = {
                    **stored,
                    "status": status,
                    "result": result,
                    "storm_pending": False,
                    "storm_resolved": True,
                    "storm_choice": "turn_back",
                    "settled_at": now_text,
                }
            connection.execute(
                "UPDATE players SET spirit_stones = ?, cultivation = ?, total_cultivation = ?, stamina = ?, inventory_json = ?, updated_at = ? WHERE id = ?",
                (stones, cultivation, total_cultivation, stamina, json.dumps(inventory, ensure_ascii=False, sort_keys=True), now_text, row["id"]),
            )
            connection.execute(
                "UPDATE exploration_sessions SET status = ?, ends_at = ?, result_json = ?, updated_at = ? WHERE id = ? AND status IN ('created', 'running')",
                (status, ends_at, json.dumps(result_json, ensure_ascii=False, sort_keys=True), now_text, session["id"]),
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (row["id"],)).fetchone()
            payload = {
                "player": self._player_payload(self._row_to_player(updated)),
                "exploration_id": session["exploration_id"],
                "mode_key": session["mode_key"],
                "location_key": session["location_key"],
                "status": status,
                "result": result,
                "battle_pending": False,
                "expired": False,
                "stamina_cost": int(session["stamina_cost"]),
                "energy_cost": int(snapshot.get("energy_cost", 0)),
                "content_version": snapshot.get("content_version", "content-0.1"),
                "storm_pending": False,
                "storm_options": [],
                "storm_deadline": ends_at if effective_choice == "wait" else None,
                "storm_choice": effective_choice,
            }
            connection.execute(
                "INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (operation_id, operation_name, row["id"], request_hash, json.dumps(payload, ensure_ascii=False, sort_keys=True), now_text),
            )
            return self._exploration_settlement_from_payload(payload)

    async def cancel_exploration(
        self,
        *,
        platform: str,
        platform_user_id: str,
        operation_id: str,
    ) -> ExplorationSettlementRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._cancel_exploration_sync, platform, platform_user_id, operation_id)

    def _cancel_exploration_sync(self, platform: str, platform_user_id: str, operation_id: str) -> ExplorationSettlementRecord:
        operation_name = "exploration.cancel"
        request_payload = {"platform": platform, "platform_user_id": platform_user_id}
        request_hash = self._request_hash(operation_name, request_payload)
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id = ?", (operation_id,)
            ).fetchone()
            if existing is not None:
                if existing["operation_name"] != operation_name or existing["request_hash"] != request_hash:
                    raise OperationConflictError("operation input differs from its original request")
                return self._exploration_settlement_from_payload(json.loads(existing["result_json"]), replay=True)
            row = self._require_player(connection, platform, platform_user_id)
            session = connection.execute(
                "SELECT * FROM exploration_sessions WHERE player_id = ? AND status = 'created' ORDER BY id DESC LIMIT 1", (row["id"],)
            ).fetchone()
            if session is None:
                raise ExplorationNotFoundError("exploration cannot be cancelled")
            snapshot = self._json_object(session["snapshot_json"], {})
            stamina_refund = int(session["stamina_cost"])
            energy_refund = int(snapshot.get("energy_cost", 0))
            stamina = min(int(row["stamina_max"]), int(row["stamina"]) + stamina_refund)
            energy = min(int(row["energy_max"]), int(row["energy"]) + energy_refund)
            connection.execute(
                "UPDATE players SET stamina = ?, energy = ?, updated_at = ? WHERE id = ?",
                (stamina, energy, now_text, row["id"]),
            )
            connection.execute(
                "UPDATE exploration_sessions SET status = 'cancelled', result_json = ?, updated_at = ? WHERE id = ? AND status = 'created'",
                (json.dumps({"status": "cancelled", "stamina_refund": stamina_refund, "energy_refund": energy_refund}, ensure_ascii=False), now_text, session["id"]),
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (row["id"],)).fetchone()
            player = self._row_to_player(updated)
            payload = {
                "player": self._player_payload(player),
                "exploration_id": session["exploration_id"],
                "mode_key": session["mode_key"],
                "location_key": session["location_key"],
                "status": "cancelled",
                "result": {"stamina_refund": stamina_refund, "energy_refund": energy_refund},
                "battle_pending": False,
                "expired": False,
                "stamina_cost": int(session["stamina_cost"]),
                "energy_cost": energy_refund,
                "content_version": snapshot.get("content_version", "content-0.1"),
            }
            connection.execute(
                "INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (operation_id, operation_name, row["id"], request_hash, json.dumps(payload, ensure_ascii=False, sort_keys=True), now_text),
            )
            return self._exploration_settlement_from_payload(payload)
