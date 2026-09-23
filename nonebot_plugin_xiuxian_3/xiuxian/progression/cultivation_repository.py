"""SQLite transactions for cultivation sessions and layer advancement."""

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


class CultivationRepositoryMixin:
    async def enter_cultivation(
        self,
        *,
        platform: str,
        platform_user_id: str,
        path_key: str,
        subprofession_key: str | None,
        operation_id: str,
    ) -> CultivationRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._enter_cultivation_sync,
                platform,
                platform_user_id,
                path_key,
                subprofession_key,
                operation_id,
            )

    def _enter_cultivation_sync(
        self,
        platform: str,
        platform_user_id: str,
        path_key: str,
        subprofession_key: str | None,
        operation_id: str,
    ) -> CultivationRecord:
        last_error: Exception | None = None
        for attempt in range(5):
            try:
                return self._enter_cultivation_once(
                    platform,
                    platform_user_id,
                    path_key,
                    subprofession_key,
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

    def _enter_cultivation_once(
        self,
        platform: str,
        platform_user_id: str,
        path_key: str,
        subprofession_key: str | None,
        operation_id: str,
    ) -> CultivationRecord:
        from ..player.path_rules import reward_items

        operation_payload = {
            "platform": platform,
            "platform_user_id": platform_user_id,
            "path_key": path_key,
            "subprofession_key": subprofession_key,
        }
        request_hash = self._request_hash("player.enter_cultivation", operation_payload)
        now = datetime.now(timezone.utc)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing_operation = connection.execute(
                "SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            if existing_operation is not None:
                if (
                    existing_operation["operation_name"] != "player.enter_cultivation"
                    or existing_operation["request_hash"] != request_hash
                ):
                    raise OperationConflictError("operation input differs from its original request")
                payload = json.loads(existing_operation["result_json"])
                return CultivationRecord(
                    player=self._row_to_player(payload["player"]),
                    path_key=path_key,
                    subprofession_key=subprofession_key,
                    changed=bool(payload.get("changed", False)),
                    already_completed=True,
                )

            row = self._require_player(connection, platform, platform_user_id)
            if row["stage"] != "seeker":
                raise PlayerStageConflictError("player is not ready to enter cultivation")
            if row["path_key"]:
                raise PathAlreadySelectedError("path is already selected")
            if path_key == "support" and not subprofession_key:
                raise SubprofessionRequiredError("support path needs a sub-profession")

            inventory = self._json_object(row["inventory_json"], {})
            for item_key, quantity in reward_items(path_key, subprofession_key):
                inventory[item_key] = int(inventory.get(item_key, 0)) + quantity
            connection.execute(
                """
                UPDATE players
                SET stage = 'cultivator', path_key = ?, subprofession_key = ?,
                    realm_key = 'qi_sensing', realm_layer = 1, cultivation = 0, total_cultivation = 0,
                    spirit_stones = spirit_stones + 200, inventory_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    path_key,
                    subprofession_key,
                    json.dumps(inventory, ensure_ascii=False, sort_keys=True),
                    serialize_datetime(now),
                    row["id"],
                ),
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (row["id"],)).fetchone()
            if updated is None:
                raise RuntimeError("cultivation entry returned no row")
            player = self._row_to_player(updated)
            payload = {"player": self._player_payload(player), "changed": True}
            connection.execute(
                """
                INSERT INTO operations(
                    operation_id, operation_name, player_id, request_hash, result_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    operation_id,
                    "player.enter_cultivation",
                    row["id"],
                    request_hash,
                    json.dumps(payload, ensure_ascii=False, sort_keys=True),
                    serialize_datetime(now),
                ),
            )
            return CultivationRecord(
                player=player,
                path_key=path_key,
                subprofession_key=subprofession_key,
                changed=True,
            )

    async def start_cultivation(
        self,
        *,
        platform: str,
        platform_user_id: str,
        mode_key: str,
        operation_id: str,
    ) -> CultivationSessionRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._start_cultivation_sync,
                platform,
                platform_user_id,
                mode_key,
                operation_id,
            )

    def _start_cultivation_sync(
        self,
        platform: str,
        platform_user_id: str,
        mode_key: str,
        operation_id: str,
    ) -> CultivationSessionRecord:
        last_error: Exception | None = None
        for attempt in range(5):
            try:
                return self._start_cultivation_once(platform, platform_user_id, mode_key, operation_id)
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).lower():
                    raise
                if attempt == 4:
                    raise RepositoryBusyError("database remained locked") from exc
                last_error = exc
                time.sleep(0.01 * (2**attempt))
        raise RepositoryBusyError("database remained locked") from last_error

    def _start_cultivation_once(
        self,
        platform: str,
        platform_user_id: str,
        mode_key: str,
        operation_id: str,
    ) -> CultivationSessionRecord:
        from ..progression.rules import FORMAL_REALMS, cultivation_mode

        operation_payload = {
            "platform": platform,
            "platform_user_id": platform_user_id,
            "mode_key": mode_key,
        }
        request_hash = self._request_hash("progression.start_cultivation", operation_payload)
        now = self._now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing_operation = connection.execute(
                "SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            if existing_operation is not None:
                if (
                    existing_operation["operation_name"] != "progression.start_cultivation"
                    or existing_operation["request_hash"] != request_hash
                ):
                    raise OperationConflictError("operation input differs from its original request")
                payload = json.loads(existing_operation["result_json"])
                return CultivationSessionRecord(
                    player=self._row_to_player(payload["player"]),
                    session_id=str(payload["session_id"]),
                    mode_key=str(payload["mode_key"]),
                    status=str(payload["status"]),
                    starts_at=str(payload["starts_at"]),
                    ends_at=str(payload["ends_at"]),
                    stamina_cost=int(payload["stamina_cost"]),
                    energy_cost=int(payload.get("energy_cost", 0)),
                    already_completed=True,
                )

            row = self._require_player(connection, platform, platform_user_id)
            if row["stage"] != "cultivator" or row["realm_key"] not in FORMAL_REALMS:
                raise PlayerStageConflictError("player is not ready for cultivation")
            try:
                mode = cultivation_mode(mode_key)
            except ValueError as exc:
                raise ValueError("unsupported cultivation mode") from exc
            if mode.required_location and row["location_key"] != mode.required_location:
                raise LocationRequiredError("selected cultivation mode requires a specific location")
            if not meets_realm(
                str(row["realm_key"]),
                int(row["realm_layer"]),
                mode.required_realm,
                mode.required_layer,
            ):
                raise CultivationRequirementError("cultivation realm requirement is not met")
            if mode.required_location:
                intro_state = self._json_object(row["intro_json"], {})
                from ..player.intro_rules import GUIDE_GATHER_BLOOD_GRASS

                if GUIDE_GATHER_BLOOD_GRASS not in set(intro_state.get("flags", [])):
                    raise LocationRequirementError("spirit cultivation requires the gathering lesson")
            exploration = connection.execute(
                "SELECT 1 FROM exploration_sessions WHERE player_id = ? AND status IN ('created', 'running', 'combat_pending') LIMIT 1",
                (row["id"],),
            ).fetchone()
            if exploration is not None:
                raise CultivationBusyError("exploration is still running")
            retreat = connection.execute(
                "SELECT 1 FROM retreat_sessions WHERE player_id = ? AND status = 'running' LIMIT 1",
                (row["id"],),
            ).fetchone()
            if retreat is not None:
                raise CultivationBusyError("retreat is still running")
            if mode.requires_solitude:
                party = connection.execute(
                    "SELECT 1 FROM party_members WHERE player_id = ? AND status IN ('invited', 'active') LIMIT 1",
                    (row["id"],),
                ).fetchone()
                if party is not None:
                    raise CultivationBusyError("seclusion requires no active party")
                production = connection.execute(
                    "SELECT 1 FROM production_orders WHERE player_id = ? AND status = 'processing' LIMIT 1",
                    (row["id"],),
                ).fetchone()
                if production is not None:
                    raise CultivationBusyError("seclusion requires no active production")
            pending = connection.execute(
                "SELECT status, result_json FROM cultivation_sessions WHERE player_id = ? AND status IN ('running', 'expired') ORDER BY id DESC LIMIT 1",
                (row["id"],),
            ).fetchone()
            if pending is not None and pending["status"] == "running":
                raise CultivationBusyError("player already has a running cultivation")
            if pending is not None:
                pending_result = self._json_object(pending["result_json"], {})
                if "cultivation_gain" not in pending_result:
                    raise CultivationRecoveryRequiredError("expired cultivation requires recovery")
            if mode.daily_limit is not None:
                day_start = serialize_datetime(now.replace(hour=0, minute=0, second=0, microsecond=0))
                used = connection.execute(
                    "SELECT COUNT(*) AS count FROM cultivation_sessions WHERE player_id = ? AND mode_key = ? AND starts_at >= ?",
                    (row["id"], mode.key, day_start),
                ).fetchone()
                if used is not None and int(used["count"]) >= mode.daily_limit:
                    raise CultivationDailyLimitError("cultivation mode reached its daily limit")
            if int(row["stamina"]) < mode.stamina_cost or int(row["energy"]) < mode.energy_cost:
                raise ResourceInsufficientError("cultivation resources are insufficient")

            session_id = uuid4().hex
            starts_at = serialize_datetime(now)
            ends_at = serialize_datetime(now + timedelta(seconds=mode.duration_seconds))
            state_bp = 10000
            if row["weakness_until"]:
                try:
                    weakness_until = datetime.fromisoformat(str(row["weakness_until"]))
                except ValueError:
                    weakness_until = now
                if weakness_until > now:
                    state_bp = 8000
            if row["domain_crack_until"]:
                try:
                    domain_crack_until = datetime.fromisoformat(str(row["domain_crack_until"]))
                except ValueError:
                    domain_crack_until = now
                if domain_crack_until > now:
                    state_bp = min(state_bp, 8500)
            snapshot = {
                "realm_key": row["realm_key"],
                "realm_layer": int(row["realm_layer"]),
                "qualification": self._json_object(row["qualification_json"], {}),
                "location_key": row["location_key"],
                "rule_version": mode.rule_version,
                "mode_key": mode.key,
                "stamina_cost": mode.stamina_cost,
                "energy_cost": mode.energy_cost,
                "base_cultivation": mode.base_cultivation,
                "environment_bp": mode.environment_bp,
                "state_bp": state_bp,
            }
            connection.execute(
                "UPDATE players SET stamina = stamina - ?, energy = energy - ?, updated_at = ? WHERE id = ?",
                (mode.stamina_cost, mode.energy_cost, serialize_datetime(now), row["id"]),
            )
            connection.execute(
                """
                INSERT INTO cultivation_sessions(
                    session_id, player_id, operation_id, mode_key, status,
                    starts_at, ends_at, stamina_cost, snapshot_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'running', ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    row["id"],
                    operation_id,
                    mode_key,
                    starts_at,
                    ends_at,
                    mode.stamina_cost,
                    json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
                    starts_at,
                    starts_at,
                ),
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (row["id"],)).fetchone()
            if updated is None:
                raise RuntimeError("cultivation start returned no player")
            player = self._row_to_player(updated)
            payload = {
                "player": self._player_payload(player),
                "session_id": session_id,
                "mode_key": mode.key,
                "status": "running",
                "starts_at": starts_at,
                "ends_at": ends_at,
                "stamina_cost": mode.stamina_cost,
                "energy_cost": mode.energy_cost,
            }
            connection.execute(
                """
                INSERT INTO operations(
                    operation_id, operation_name, player_id, request_hash, result_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    operation_id,
                    "progression.start_cultivation",
                    row["id"],
                    request_hash,
                    json.dumps(payload, ensure_ascii=False, sort_keys=True),
                    starts_at,
                ),
            )
            return CultivationSessionRecord(
                player=player,
                session_id=session_id,
                mode_key=mode.key,
                status="running",
                starts_at=starts_at,
                ends_at=ends_at,
                stamina_cost=mode.stamina_cost,
                energy_cost=mode.energy_cost,
            )

    async def settle_cultivation(
        self,
        *,
        platform: str,
        platform_user_id: str,
        operation_id: str,
    ) -> CultivationSettlementRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._settle_cultivation_sync,
                platform,
                platform_user_id,
                operation_id,
            )

    def _settle_cultivation_sync(self, platform: str, platform_user_id: str, operation_id: str) -> CultivationSettlementRecord:
        last_error: Exception | None = None
        for attempt in range(5):
            try:
                return self._settle_cultivation_once(platform, platform_user_id, operation_id)
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).lower():
                    raise
                if attempt == 4:
                    raise RepositoryBusyError("database remained locked") from exc
                last_error = exc
                time.sleep(0.01 * (2**attempt))
        raise RepositoryBusyError("database remained locked") from last_error

    def _settle_cultivation_once(self, platform: str, platform_user_id: str, operation_id: str) -> CultivationSettlementRecord:
        from ..progression.rules import CULTIVATION_SETTLEMENT_GRACE_SECONDS, cultivation_gain

        operation_payload = {"platform": platform, "platform_user_id": platform_user_id}
        request_hash = self._request_hash("progression.settle_cultivation", operation_payload)
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing_operation = connection.execute(
                "SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            if existing_operation is not None:
                if (
                    existing_operation["operation_name"] != "progression.settle_cultivation"
                    or existing_operation["request_hash"] != request_hash
                ):
                    raise OperationConflictError("operation input differs from its original request")
                payload = json.loads(existing_operation["result_json"])
                return CultivationSettlementRecord(
                    player=self._row_to_player(payload["player"]),
                    session_id=str(payload["session_id"]),
                    cultivation_gain=int(payload["cultivation_gain"]),
                    mode_key=str(payload.get("mode_key", "cultivate.breathing")),
                    already_completed=True,
                )

            row = self._require_player(connection, platform, platform_user_id)
            session = connection.execute(
                "SELECT * FROM cultivation_sessions WHERE player_id = ? AND status IN ('running', 'expired') ORDER BY id DESC LIMIT 1",
                (row["id"],),
            ).fetchone()
            if session is None:
                raise CultivationNotFoundError("no running cultivation")
            if session["status"] == "expired":
                raise CultivationExpiredError("cultivation requires recovery")
            ends_at = datetime.fromisoformat(str(session["ends_at"]))
            if now < ends_at:
                raise CultivationNotReadyError("cultivation is not ready")
            if now > ends_at + timedelta(seconds=CULTIVATION_SETTLEMENT_GRACE_SECONDS):
                expiry_payload = {
                    "platform": platform,
                    "platform_user_id": platform_user_id,
                    "session_id": str(session["session_id"]),
                }
                connection.execute(
                    "UPDATE cultivation_sessions SET status = 'expired', result_json = ?, updated_at = ? WHERE id = ?",
                    (
                        json.dumps({"expired_at": now_text, "recovery_pending": True}, ensure_ascii=False, sort_keys=True),
                        now_text,
                        session["id"],
                    ),
                )
                connection.execute(
                    "INSERT OR IGNORE INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        f"progression.expire_cultivation:{session['session_id']}",
                        "progression.expire_cultivation",
                        row["id"],
                        self._request_hash("progression.expire_cultivation", expiry_payload),
                        json.dumps(
                            {"session_id": session["session_id"], "status": "expired"},
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                        now_text,
                    ),
                )
                connection.commit()
                raise CultivationExpiredError("cultivation settlement window expired")
            snapshot = self._json_object(session["snapshot_json"], {})
            qualification = self._json_object(snapshot.get("qualification", {}), {})
            gain = cultivation_gain(
                int(snapshot.get("base_cultivation", 40)),
                qualification,
                environment_bp=int(snapshot.get("environment_bp", 10000)),
                state_bp=int(snapshot.get("state_bp", 10000)),
            )
            connection.execute(
                "UPDATE players SET cultivation = cultivation + ?, total_cultivation = total_cultivation + ?, updated_at = ? WHERE id = ?",
                (gain, gain, now_text, row["id"]),
            )
            connection.execute(
                "UPDATE cultivation_sessions SET status = 'settled', result_json = ?, updated_at = ? WHERE id = ?",
                (json.dumps({"cultivation_gain": gain}, ensure_ascii=False, sort_keys=True), now_text, session["id"]),
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (row["id"],)).fetchone()
            if updated is None:
                raise RuntimeError("cultivation settlement returned no player")
            player = self._row_to_player(updated)
            payload = {
                "player": self._player_payload(player),
                "session_id": session["session_id"],
                "cultivation_gain": gain,
                "mode_key": str(snapshot.get("mode_key", session["mode_key"])),
            }
            connection.execute(
                "INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    operation_id,
                    "progression.settle_cultivation",
                    row["id"],
                    request_hash,
                    json.dumps(payload, ensure_ascii=False, sort_keys=True),
                    now_text,
                ),
            )
            return CultivationSettlementRecord(
                player=player,
                session_id=session["session_id"],
                cultivation_gain=gain,
                mode_key=str(snapshot.get("mode_key", session["mode_key"])),
            )

    async def recover_cultivation(
        self,
        *,
        platform: str,
        platform_user_id: str,
        operation_id: str,
    ) -> CultivationRecoveryRecord:
        """Recover one expired cultivation session using its original snapshot."""

        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._recover_cultivation_sync,
                platform,
                platform_user_id,
                operation_id,
            )

    def _recover_cultivation_sync(
        self,
        platform: str,
        platform_user_id: str,
        operation_id: str,
    ) -> CultivationRecoveryRecord:
        last_error: Exception | None = None
        for attempt in range(5):
            try:
                return self._recover_cultivation_once(platform, platform_user_id, operation_id)
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).lower():
                    raise
                if attempt == 4:
                    raise RepositoryBusyError("database remained locked") from exc
                last_error = exc
                time.sleep(0.01 * (2**attempt))
        raise RepositoryBusyError("database remained locked") from last_error

    def _recover_cultivation_once(
        self,
        platform: str,
        platform_user_id: str,
        operation_id: str,
    ) -> CultivationRecoveryRecord:
        from ..progression.rules import CULTIVATION_SETTLEMENT_GRACE_SECONDS, cultivation_gain

        operation_payload = {"platform": platform, "platform_user_id": platform_user_id}
        request_hash = self._request_hash("progression.recover_cultivation", operation_payload)
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing_operation = connection.execute(
                "SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            if existing_operation is not None:
                if (
                    existing_operation["operation_name"] != "progression.recover_cultivation"
                    or existing_operation["request_hash"] != request_hash
                ):
                    raise OperationConflictError("operation input differs from its original request")
                payload = json.loads(existing_operation["result_json"])
                return CultivationRecoveryRecord(
                    player=self._row_to_player(payload["player"]),
                    session_id=str(payload["session_id"]),
                    cultivation_gain=int(payload["cultivation_gain"]),
                    mode_key=str(payload.get("mode_key", "cultivate.breathing")),
                    already_completed=True,
                )

            row = self._require_player(connection, platform, platform_user_id)
            session = connection.execute(
                "SELECT * FROM cultivation_sessions WHERE player_id = ? AND status IN ('running', 'expired') ORDER BY id DESC LIMIT 1",
                (row["id"],),
            ).fetchone()
            if session is None:
                raise CultivationNotFoundError("no expired cultivation")
            session_result = self._json_object(session["result_json"], {})
            if "cultivation_gain" in session_result:
                raise CultivationAlreadyRecoveredError("cultivation was already recovered")
            ends_at = datetime.fromisoformat(str(session["ends_at"]))
            if now < ends_at:
                raise CultivationNotReadyError("cultivation is not ready")
            if now <= ends_at + timedelta(seconds=CULTIVATION_SETTLEMENT_GRACE_SECONDS):
                raise CultivationNotReadyError("cultivation is still within the normal settlement window")
            snapshot = self._json_object(session["snapshot_json"], {})
            qualification = self._json_object(snapshot.get("qualification", {}), {})
            gain = cultivation_gain(
                int(snapshot.get("base_cultivation", 40)),
                qualification,
                environment_bp=int(snapshot.get("environment_bp", 10000)),
                state_bp=int(snapshot.get("state_bp", 10000)),
            )
            connection.execute(
                "UPDATE players SET cultivation = cultivation + ?, total_cultivation = total_cultivation + ?, updated_at = ? WHERE id = ?",
                (gain, gain, now_text, row["id"]),
            )
            connection.execute(
                "UPDATE cultivation_sessions SET status = 'expired', result_json = ?, updated_at = ? WHERE id = ?",
                (
                    json.dumps(
                        {"cultivation_gain": gain, "recovered_after_expiry": True},
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    now_text,
                    session["id"],
                ),
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (row["id"],)).fetchone()
            if updated is None:
                raise RuntimeError("cultivation recovery returned no player")
            player = self._row_to_player(updated)
            payload = {
                "player": self._player_payload(player),
                "session_id": session["session_id"],
                "cultivation_gain": gain,
                "mode_key": str(snapshot.get("mode_key", session["mode_key"])),
            }
            connection.execute(
                "INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    operation_id,
                    "progression.recover_cultivation",
                    row["id"],
                    request_hash,
                    json.dumps(payload, ensure_ascii=False, sort_keys=True),
                    now_text,
                ),
            )
            return CultivationRecoveryRecord(
                player=player,
                session_id=session["session_id"],
                cultivation_gain=gain,
                mode_key=str(snapshot.get("mode_key", session["mode_key"])),
            )

    async def cancel_cultivation(
        self,
        *,
        platform: str,
        platform_user_id: str,
        operation_id: str,
    ) -> CultivationCancelRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._cancel_cultivation_sync,
                platform,
                platform_user_id,
                operation_id,
            )

    def _cancel_cultivation_sync(self, platform: str, platform_user_id: str, operation_id: str) -> CultivationCancelRecord:
        last_error: Exception | None = None
        for attempt in range(5):
            try:
                return self._cancel_cultivation_once(platform, platform_user_id, operation_id)
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).lower():
                    raise
                if attempt == 4:
                    raise RepositoryBusyError("database remained locked") from exc
                last_error = exc
                time.sleep(0.01 * (2**attempt))
        raise RepositoryBusyError("database remained locked") from last_error

    def _cancel_cultivation_once(self, platform: str, platform_user_id: str, operation_id: str) -> CultivationCancelRecord:
        from ..progression.rules import CULTIVATION_SETTLEMENT_GRACE_SECONDS

        operation_payload = {"platform": platform, "platform_user_id": platform_user_id}
        request_hash = self._request_hash("progression.cancel_cultivation", operation_payload)
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing_operation = connection.execute(
                "SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            if existing_operation is not None:
                if (
                    existing_operation["operation_name"] != "progression.cancel_cultivation"
                    or existing_operation["request_hash"] != request_hash
                ):
                    raise OperationConflictError("operation input differs from its original request")
                payload = json.loads(existing_operation["result_json"])
                return CultivationCancelRecord(
                    player=self._row_to_player(payload["player"]),
                    session_id=str(payload["session_id"]),
                    stamina_refund=int(payload["stamina_refund"]),
                    energy_refund=int(payload.get("energy_refund", 0)),
                    already_completed=True,
                )
            row = self._require_player(connection, platform, platform_user_id)
            session = connection.execute(
                "SELECT * FROM cultivation_sessions WHERE player_id = ? AND status = 'running' ORDER BY id DESC LIMIT 1",
                (row["id"],),
            ).fetchone()
            if session is None:
                raise CultivationNotFoundError("no running cultivation")
            ends_at = datetime.fromisoformat(str(session["ends_at"]))
            if now >= ends_at:
                if now > ends_at + timedelta(seconds=CULTIVATION_SETTLEMENT_GRACE_SECONDS):
                    expiry_payload = {
                        "platform": platform,
                        "platform_user_id": platform_user_id,
                        "session_id": str(session["session_id"]),
                    }
                    connection.execute(
                        "UPDATE cultivation_sessions SET status = 'expired', result_json = ?, updated_at = ? WHERE id = ?",
                        (
                            json.dumps(
                                {"expired_at": serialize_datetime(now), "recovery_pending": True},
                                ensure_ascii=False,
                                sort_keys=True,
                            ),
                            serialize_datetime(now),
                            session["id"],
                        ),
                    )
                    connection.execute(
                        "INSERT OR IGNORE INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                        (
                            f"progression.expire_cultivation:{session['session_id']}",
                            "progression.expire_cultivation",
                            row["id"],
                            self._request_hash("progression.expire_cultivation", expiry_payload),
                            json.dumps(
                                {"session_id": session["session_id"], "status": "expired"},
                                ensure_ascii=False,
                                sort_keys=True,
                            ),
                            serialize_datetime(now),
                        ),
                    )
                    connection.commit()
                    raise CultivationExpiredError("cultivation cancellation window expired")
                raise CultivationAlreadyReadyError("cultivation must be settled")
            snapshot = self._json_object(session["snapshot_json"], {})
            refund = int(session["stamina_cost"])
            energy_refund = int(snapshot.get("energy_cost", 0))
            connection.execute(
                "UPDATE players SET stamina = MIN(stamina_max, stamina + ?), energy = MIN(energy_max, energy + ?), updated_at = ? WHERE id = ?",
                (refund, energy_refund, now_text, row["id"]),
            )
            connection.execute(
                "UPDATE cultivation_sessions SET status = 'cancelled', result_json = ?, updated_at = ? WHERE id = ?",
                (
                    json.dumps(
                        {"stamina_refund": refund, "energy_refund": energy_refund},
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    now_text,
                    session["id"],
                ),
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (row["id"],)).fetchone()
            if updated is None:
                raise RuntimeError("cultivation cancellation returned no player")
            player = self._row_to_player(updated)
            payload = {
                "player": self._player_payload(player),
                "session_id": session["session_id"],
                "stamina_refund": refund,
                "energy_refund": energy_refund,
            }
            connection.execute(
                "INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    operation_id,
                    "progression.cancel_cultivation",
                    row["id"],
                    request_hash,
                    json.dumps(payload, ensure_ascii=False, sort_keys=True),
                    now_text,
                ),
            )
            return CultivationCancelRecord(
                player=player,
                session_id=session["session_id"],
                stamina_refund=refund,
                energy_refund=energy_refund,
            )

    @staticmethod
    def _has_active_long_action(connection: sqlite3.Connection, player_id: int) -> bool:
        """Return whether a player has any session that locks another action."""

        checks = (
            ("cultivation_sessions", "status = 'running'"),
            ("retreat_sessions", "status = 'running'"),
            ("production_orders", "status = 'processing'"),
            ("breakthrough_sessions", "status = 'preparing'"),
            ("travel_sessions", "status = 'running'"),
            ("exploration_sessions", "status IN ('created', 'running', 'combat_pending')"),
            ("void_route_sessions", "status = 'running'"),
        )
        return any(
            connection.execute(
                f"SELECT 1 FROM {table} WHERE player_id = ? AND {predicate} LIMIT 1",
                (player_id,),
            ).fetchone()
            is not None
            for table, predicate in checks
        )

    @staticmethod
    def _retreat_start_from_payload(payload: dict[str, Any], *, replay: bool = False) -> RetreatSessionRecord:
        return RetreatSessionRecord(
            player=SQLitePlayerRepository._row_to_player(payload["player"]),
            session_id=str(payload["session_id"]),
            retreat_key=str(payload["retreat_key"]),
            status=str(payload["status"]),
            starts_at=str(payload["starts_at"]),
            ends_at=str(payload["ends_at"]),
            energy_cost=int(payload["energy_cost"]),
            item_cost={str(key): int(value) for key, value in dict(payload.get("item_cost", {})).items()},
            already_completed=replay,
        )

    @staticmethod
    def _retreat_settlement_from_payload(payload: dict[str, Any], *, replay: bool = False) -> RetreatSettlementRecord:
        return RetreatSettlementRecord(
            player=SQLitePlayerRepository._row_to_player(payload["player"]),
            session_id=str(payload["session_id"]),
            retreat_key=str(payload["retreat_key"]),
            status=str(payload["status"]),
            result={str(key): int(value) for key, value in dict(payload.get("result", {})).items()},
            cycles=int(payload.get("cycles", 1)),
            expired=bool(payload.get("expired", False)),
            already_completed=replay,
        )

    async def advance_layer(
        self,
        *,
        platform: str,
        platform_user_id: str,
        operation_id: str,
    ) -> LayerAdvanceRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._advance_layer_sync, platform, platform_user_id, operation_id)

    def _advance_layer_sync(self, platform: str, platform_user_id: str, operation_id: str) -> LayerAdvanceRecord:
        last_error: Exception | None = None
        for attempt in range(5):
            try:
                return self._advance_layer_once(platform, platform_user_id, operation_id)
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).lower():
                    raise
                if attempt == 4:
                    raise RepositoryBusyError("database remained locked") from exc
                last_error = exc
                time.sleep(0.01 * (2**attempt))
        raise RepositoryBusyError("database remained locked") from last_error

    def _advance_layer_once(self, platform: str, platform_user_id: str, operation_id: str) -> LayerAdvanceRecord:
        from ..progression.rules import can_advance_layer, layer_unlocks, next_layer_threshold
        from ..progression.endgame_rules import TRIAL_ORDER

        operation_payload = {"platform": platform, "platform_user_id": platform_user_id}
        request_hash = self._request_hash("progression.advance_layer", operation_payload)
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing_operation = connection.execute(
                "SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            if existing_operation is not None:
                if (
                    existing_operation["operation_name"] != "progression.advance_layer"
                    or existing_operation["request_hash"] != request_hash
                ):
                    raise OperationConflictError("operation input differs from its original request")
                payload = json.loads(existing_operation["result_json"])
                unlocks = tuple(
                    LayerUnlock(
                        key=str(item.get("key", "")),
                        title=str(item.get("title", "")),
                        description=str(item.get("description", "")),
                        status=str(item.get("status", "preview")),
                    )
                    for item in payload.get("unlocks", [])
                    if isinstance(item, dict)
                )
                return LayerAdvanceRecord(
                    player=self._row_to_player(payload["player"]),
                    changed=True,
                    already_completed=True,
                    unlocks=unlocks,
                )
            row = self._require_player(connection, platform, platform_user_id)
            if row["stage"] != "cultivator":
                raise PlayerStageConflictError("player is not ready to advance")
            running = connection.execute(
                "SELECT 1 FROM cultivation_sessions WHERE player_id = ? AND status = 'running' LIMIT 1",
                (row["id"],),
            ).fetchone()
            if running is not None:
                raise CultivationBusyError("cultivation is still running")
            retreat = connection.execute(
                "SELECT 1 FROM retreat_sessions WHERE player_id = ? AND status = 'running' LIMIT 1",
                (row["id"],),
            ).fetchone()
            if retreat is not None:
                raise CultivationBusyError("retreat is still running")
            layer = int(row["realm_layer"])
            realm_key = str(row["realm_key"])
            if layer >= 10 or next_layer_threshold(realm_key, layer) is None:
                raise RealmLayerInvalidError("realm is already at its maximum layer")
            if not can_advance_layer(realm_key, layer, int(row["cultivation"])):
                raise RealmCultivationInsufficientError("realm cultivation is insufficient")
            if realm_key == "tribulation" and layer in {3, 6, 9}:
                completed = {
                    str(item["trial_key"])
                    for item in connection.execute(
                        "SELECT trial_key FROM tribulation_trial_sessions WHERE player_id = ? AND status = 'succeeded'",
                        (row["id"],),
                    ).fetchall()
                }
                required = {3: TRIAL_ORDER[:1], 6: TRIAL_ORDER[:2], 9: TRIAL_ORDER}[layer]
                if any(item not in completed for item in required):
                    raise TrialSequenceError("the required tribulation trial has not succeeded")
                if layer == 9:
                    flags = set(str(item) for item in self._json_object(row["intro_json"], {}).get("flags", []))
                    if not {"task.dao_origin.guard", "task.dao_origin.build", "task.dao_origin.teach"}.issubset(flags):
                        raise TrialSequenceError("dao origin tasks are incomplete")
            layer_unlocks_reached = layer_unlocks(realm_key, layer + 1)
            connection.execute(
                "UPDATE players SET realm_layer = realm_layer + 1, updated_at = ? WHERE id = ?",
                (now_text, row["id"]),
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (row["id"],)).fetchone()
            if updated is None:
                raise RuntimeError("layer advancement returned no player")
            from ..progression.milestone_repository import record_due_milestones

            milestone_unlocks = record_due_milestones(
                connection,
                player=updated,
                source_operation_id=operation_id,
                now_text=now_text,
            )
            unlocks = (*layer_unlocks_reached, *milestone_unlocks)
            player = self._row_to_player(updated)
            payload = {
                "player": self._player_payload(player),
                "unlocks": [
                    {
                        "key": item.key,
                        "title": item.title,
                        "description": item.description,
                        "status": item.status,
                    }
                    for item in unlocks
                ],
            }
            connection.execute(
                "INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    operation_id,
                    "progression.advance_layer",
                    row["id"],
                    request_hash,
                    json.dumps(payload, ensure_ascii=False, sort_keys=True),
                    now_text,
                ),
            )
            return LayerAdvanceRecord(player=player, changed=True, unlocks=unlocks)
