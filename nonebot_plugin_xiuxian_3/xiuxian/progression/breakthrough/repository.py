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
from ...rewards.rules import local_reputation_maximum, reward_definition, reward_grant_from_snapshot
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
from ...utils.assets import inventory_amount, player_currency
from ...utils.json_cache import decode_json_strict
from ...utils.player import (
    change_player_state,
    grant_player_state,
    player_integer,
    player_inventory,
    player_object,
    player_reputation,
    player_reputation_state,
    spend_player_state,
)
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
from ...routine.billing import BillingReceiptError, verify_receipt
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
    tree_status,
)

from ...persistence.errors import *  # noqa: F401,F403


class BreakthroughRepositoryMixin:
    _BREAKTHROUGH_SNAPSHOT_KEYS = frozenset(
        {
            "target_realm",
            "source_realm",
            "realm_key",
            "realm_layer",
            "cultivation",
            "total_cultivation",
            "location_key",
            "path_key",
            "subprofession_key",
            "qualification",
            "random_pool",
            "base_success_bp",
            "required_foundation_quality",
            "foundation_quality",
            "foundation_quality_on_success",
            "quality_bonus_bp",
            "technique_bonus_bp",
            "formation_bonus_bp",
            "location_bonus_bp",
            "support_bonus_bp",
            "support_key",
            "alternative_material",
            "preparation_bp",
            "success_bp",
            "pity_before_bp",
            "protection_requested",
            "protection_key",
            "materials",
            "currency_cost",
            "random_seed",
            "cross_realm_risk_bp",
            "heart_demon_bonus_bp",
            "pollution",
            "cross_realm_penalty_bp",
            "soul_power_before",
            "world_merit_before",
            "soul_prepare_bp",
            "reputation_prepare_bp",
            "quest_prepare_bp",
            "route_count",
            "domain_power",
            "domain_charge_before",
            "void_power_before",
            "space_resistance_bp",
            "void_instability_until",
            "success_reward",
            "success_reward_local_reputation_maximums",
            "starts_at",
            "ends_at",
            "snapshot_digest",
        }
    )

    @staticmethod
    def _breakthrough_object(value: Any, field: str) -> dict[str, Any]:
        try:
            decoded = decode_json_strict(value) if isinstance(value, str) else value
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid {field} JSON") from exc
        if not isinstance(decoded, dict) or not decoded:
            raise ValueError(f"invalid {field} object")
        return decoded

    @staticmethod
    def _breakthrough_digest(value: dict[str, Any], digest_field: str) -> str:
        unsigned = dict(value)
        unsigned.pop(digest_field, None)
        encoded = json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    @classmethod
    def _validate_breakthrough_snapshot_integrity(cls, snapshot: dict[str, Any]) -> None:
        if set(snapshot) != cls._BREAKTHROUGH_SNAPSHOT_KEYS:
            raise ValueError("breakthrough snapshot fields are incomplete")
        digest = snapshot["snapshot_digest"]
        if not isinstance(digest, str) or digest != cls._breakthrough_digest(snapshot, "snapshot_digest"):
            raise ValueError("breakthrough snapshot digest is invalid")
        if not isinstance(snapshot["target_realm"], str) or not isinstance(snapshot["source_realm"], str):
            raise ValueError("breakthrough snapshot realms are invalid")
        if not isinstance(snapshot["random_seed"], str) or not snapshot["random_seed"]:
            raise ValueError("breakthrough snapshot seed is invalid")
        if not isinstance(snapshot["protection_requested"], bool):
            raise ValueError("breakthrough snapshot protection flag is invalid")
        if snapshot["protection_key"] is not None and not isinstance(snapshot["protection_key"], str):
            raise ValueError("breakthrough snapshot protection key is invalid")
        if snapshot["support_key"] is not None and not isinstance(snapshot["support_key"], str):
            raise ValueError("breakthrough snapshot support key is invalid")
        if snapshot["alternative_material"] is not None and not isinstance(snapshot["alternative_material"], str):
            raise ValueError("breakthrough snapshot alternative material is invalid")
        if snapshot["foundation_quality_on_success"] is not None and (
            isinstance(snapshot["foundation_quality_on_success"], bool)
            or not isinstance(snapshot["foundation_quality_on_success"], int)
        ):
            raise ValueError("breakthrough snapshot foundation quality is invalid")
        for field in (
            "realm_layer",
            "cultivation",
            "total_cultivation",
            "base_success_bp",
            "required_foundation_quality",
            "foundation_quality",
            "quality_bonus_bp",
            "technique_bonus_bp",
            "formation_bonus_bp",
            "location_bonus_bp",
            "support_bonus_bp",
            "preparation_bp",
            "success_bp",
            "pity_before_bp",
            "currency_cost",
            "cross_realm_risk_bp",
            "heart_demon_bonus_bp",
            "pollution",
            "cross_realm_penalty_bp",
            "soul_power_before",
            "world_merit_before",
            "soul_prepare_bp",
            "reputation_prepare_bp",
            "quest_prepare_bp",
            "route_count",
            "domain_power",
            "domain_charge_before",
            "void_power_before",
            "space_resistance_bp",
        ):
            value = snapshot[field]
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"breakthrough snapshot {field} is invalid")
        if not isinstance(snapshot["qualification"], dict):
            raise ValueError("breakthrough snapshot qualification is invalid")
        materials = snapshot["materials"]
        if not isinstance(materials, dict) or any(
            not isinstance(key, str)
            or isinstance(quantity, bool)
            or not isinstance(quantity, int)
            or quantity <= 0
            for key, quantity in materials.items()
        ):
            raise ValueError("breakthrough snapshot materials are invalid")
        if not isinstance(snapshot["success_reward_local_reputation_maximums"], dict):
            raise ValueError("breakthrough snapshot reputation caps are invalid")
        if snapshot["void_instability_until"] is not None and not isinstance(snapshot["void_instability_until"], str):
            raise ValueError("breakthrough snapshot instability is invalid")
        if not isinstance(snapshot["starts_at"], str) or not isinstance(snapshot["ends_at"], str):
            raise ValueError("breakthrough snapshot timing is invalid")

    @classmethod
    def _validate_breakthrough_snapshot(
        cls,
        snapshot: dict[str, Any],
        session: sqlite3.Row,
        definition: Any,
    ) -> None:
        cls._validate_breakthrough_snapshot_integrity(snapshot)
        if snapshot["target_realm"] != session["target_realm"]:
            raise ValueError("breakthrough snapshot target does not match session")
        if snapshot["random_seed"] != session["operation_id"]:
            raise ValueError("breakthrough snapshot operation does not match session")
        if snapshot["starts_at"] != session["starts_at"]:
            raise ValueError("breakthrough snapshot timing does not match session")
        try:
            snapshot_end = datetime.fromisoformat(snapshot["ends_at"])
            session_end = datetime.fromisoformat(str(session["ends_at"]))
        except ValueError as exc:
            raise ValueError("breakthrough snapshot timing is invalid") from exc
        if session_end > snapshot_end:
            raise ValueError("breakthrough session was extended beyond its frozen end")
        if snapshot["source_realm"] != definition.source_realm or snapshot["target_realm"] != definition.target_realm:
            raise ValueError("breakthrough snapshot realm does not match definition")
        if snapshot["random_pool"] != definition.random_pool or snapshot["currency_cost"] != definition.currency_cost:
            raise ValueError("breakthrough snapshot rule does not match definition")
        if snapshot["base_success_bp"] != definition.base_success_bp:
            raise ValueError("breakthrough snapshot base success does not match definition")
        if not definition.minimum_success_bp <= snapshot["success_bp"] <= definition.maximum_success_bp:
            raise ValueError("breakthrough snapshot success rate is out of range")
        expected_materials = dict(definition.materials)
        alternative = snapshot["alternative_material"]
        if alternative is not None:
            if snapshot["target_realm"] != "nascent_soul" or alternative not in {"item.demon_core", "item.beast_blood"}:
                raise ValueError("breakthrough snapshot alternative material is invalid")
            expected_materials[alternative] = 2
        if snapshot["materials"] != expected_materials:
            raise ValueError("breakthrough snapshot materials do not match definition")
        expected_protection = definition.protection_key if snapshot["protection_requested"] else None
        if snapshot["protection_key"] != expected_protection:
            raise ValueError("breakthrough snapshot protection does not match definition")

    @classmethod
    def _validate_breakthrough_result(
        cls,
        result: dict[str, Any],
        *,
        session_id: str,
        target_realm: str,
        player_id: str | None = None,
    ) -> None:
        if not isinstance(result, dict) or not result:
            raise ValueError("breakthrough result is invalid")
        digest = result.get("result_digest")
        digest_source = dict(result)
        digest_source.pop("session_id", None)
        digest_source.pop("target_realm", None)
        digest_source.pop("player", None)
        if not isinstance(digest, str) or digest != cls._breakthrough_digest(digest_source, "result_digest"):
            raise ValueError("breakthrough result digest is invalid")
        if result.get("session_id") != session_id or result.get("target_realm") != target_realm:
            raise ValueError("breakthrough result identity is invalid")
        if player_id is not None:
            player_payload = result.get("player")
            if (
                not isinstance(player_payload, dict)
                or player_payload.get("id") != player_id
                or player_payload.get("player_id") != player_id
            ):
                raise ValueError("breakthrough result player is invalid")
        for field in (
            "roll_bp",
            "success_bp",
            "cultivation_before",
            "cultivation_after",
            "pity_before_bp",
            "pity_after_bp",
            "currency_spent",
            "preparation_bp",
            "reward_currency",
            "reward_stamina",
            "reward_world_merit",
            "reward_local_reputation",
            "foundation_quality",
            "required_foundation_quality",
            "soul_prepare_bp",
            "reputation_prepare_bp",
            "quest_prepare_bp",
            "location_bonus_bp",
            "support_bonus_bp",
            "cross_realm_risk_bp",
            "heart_demon_bonus_bp",
        ):
            value = result.get(field)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"breakthrough result {field} is invalid")
        for field in ("success", "protection_consumed", "heart_demon_pending"):
            if not isinstance(result.get(field), bool):
                raise ValueError(f"breakthrough result {field} is invalid")
        if result.get("status") not in {"succeeded", "failed"}:
            raise ValueError("breakthrough result status is invalid")
        if result.get("materials") is not None and not isinstance(result["materials"], dict):
            raise ValueError("breakthrough result materials are invalid")
        if result.get("reward_items") is not None and not isinstance(result["reward_items"], dict):
            raise ValueError("breakthrough result rewards are invalid")
        if result.get("weakness_until") is not None and not isinstance(result["weakness_until"], str):
            raise ValueError("breakthrough result weakness is invalid")

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
            if row["realm_key"] != "golden_core" or player_integer(row, "realm_layer") != 10 or player_integer(row, "total_cultivation") < 58960:
                raise BreakthroughRequirementError("golden core preparation requirement is missing")
            if player_integer(row, "foundation_quality") < 5500:
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
                "SELECT operation_name, request_hash, player_id, result_json FROM operations WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            if existing is not None:
                if existing["operation_name"] != operation_name or existing["request_hash"] != request_hash:
                    raise OperationConflictError("operation input differs from its original request")
                row = self._require_player(connection, platform, platform_user_id, writable=False)
                if int(existing["player_id"]) != int(row["id"]):
                    raise OperationConflictError("operation does not belong to this player")
                payload = self._breakthrough_object(existing["result_json"], "breakthrough start operation")
                snapshot = self._breakthrough_object(payload.get("snapshot"), "breakthrough start snapshot")
                self._validate_breakthrough_snapshot_integrity(snapshot)
                if (
                    payload.get("session_id") is None
                    or payload.get("target_realm") != snapshot["target_realm"]
                    or payload.get("starts_at") != snapshot["starts_at"]
                    or payload.get("ends_at") != snapshot["ends_at"]
                    or payload.get("success_bp") != snapshot["success_bp"]
                ):
                    raise ValueError("breakthrough start operation does not match snapshot")
                player_payload = payload.get("player")
                if (
                    not isinstance(player_payload, dict)
                    or player_payload.get("id") != row["player_id"]
                    or player_payload.get("player_id") != row["player_id"]
                ):
                    raise ValueError("breakthrough start operation player is invalid")
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
            if player_integer(row, "realm_layer") != 10:
                if target_realm == "soul_transformation":
                    raise RealmMismatchError("only the current realm's L10 can break through")
                raise BreakthroughRequirementError("only the current realm's L10 can break through")
            if player_integer(row, "total_cultivation") < definition.required_total_cultivation:
                if target_realm == "soul_transformation":
                    raise CultivationInsufficientError("total cultivation is insufficient")
                raise BreakthroughRequirementError("total cultivation is insufficient")
            if player_integer(row, "foundation_quality") < definition.required_foundation_quality:
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
                if player_integer(row, "world_merit") < 100:
                    raise CurrencyInsufficientError("world merit is insufficient")
            if is_soul_transformation:
                if player_integer(row, "soul_power") < 200:
                    raise SoulPowerInsufficientError("soul power is insufficient")
                if player_integer(row, "world_merit") < 500:
                    raise CurrencyInsufficientError("world merit is insufficient")
                intro_state = self._json_object(row["intro_json"], {})
                if "quest.soul_transformation" not in {str(item) for item in intro_state.get("flags", [])}:
                    raise QuestRequirementError("soul transformation quest is missing")
                faction = player_reputation(row)
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
                if player_integer(row, "world_merit") < 500 or player_integer(row, "domain_charge") < 100:
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

            inventory = player_inventory(row)
            for item_key, quantity in definition.materials.items():
                if inventory_amount(inventory, item_key) < quantity:
                    raise MaterialInsufficientError("breakthrough material is insufficient")
            alternative_material: str | None = None
            if is_nascent:
                for candidate in ("item.demon_core", "item.beast_blood"):
                    if inventory_amount(inventory, candidate) >= 2:
                        alternative_material = candidate
                        break
                if alternative_material is None:
                    raise MaterialInsufficientError("nascent soul alternative material is insufficient")
            if protection and inventory_amount(inventory, definition.protection_key) < 1:
                raise ProtectionItemInsufficientError("breakthrough protection item is missing")
            if player_currency(row) < definition.currency_cost:
                raise CurrencyInsufficientError("spirit stones are insufficient")

            pity_before = player_integer(row, "breakthrough_pity_bp")
            foundation_quality = player_integer(row, "foundation_quality")
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
                and inventory_amount(inventory, definition.support_key) > 0
                else 0
            )
            preparation_bp = quality_bonus_bp + technique_bonus_bp + formation_bonus_bp + location_bonus_bp + support_bonus_bp
            soul_prepare_bp = reputation_prepare_bp = quest_prepare_bp = 0
            heart_demon_bonus_bp = player_integer(row, "heart_demon_bonus_bp") if is_nascent else 0
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
                faction = player_reputation(row)
                soul_prepare_bp = min(1000, max(0, player_integer(row, "soul_power") - 200) * 4)
                reputation_prepare_bp = min(1000, max(0, max((int(value) for value in faction.values()), default=0) - 2000) // 2)
                quest_prepare_bp = 600 if "quest.soul_transformation" in {str(item) for item in self._json_object(row["intro_json"], {}).get("flags", [])} else 0
                preparation_bp = soul_prepare_bp + reputation_prepare_bp + quest_prepare_bp + technique_bonus_bp
                final_success_bp = max(6500, min(9000, 6500 + preparation_bp + pity_before))
            elif is_void_refining:
                route_bonus_bp = min(600, max(0, player_integer(row, "void_route_count")) * 200)
                domain_bonus_bp = min(500, max(0, player_integer(row, "domain_power")) // 10)
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
            success_reward = None
            success_reward_local_reputation_maximums: dict[str, int] = {}
            if definition.reward_key is not None:
                reward = reward_definition(
                    definition.reward_key,
                    self.content,
                    operation="progression.settle_breakthrough",
                )
                if reward.assets or reward.value_delta or reward.set_values or reward.reputation:
                    raise ValueError("breakthrough reward must contain only local reputation")
                if len(reward.local_reputation) > 1:
                    raise ValueError("breakthrough reward must name at most one location")
                success_reward = reward.snapshot()
                success_reward_local_reputation_maximums = {
                    key: local_reputation_maximum(key, self.content)
                    for key in reward.local_reputation
                }
            snapshot = {
                "target_realm": definition.target_realm,
                "source_realm": definition.source_realm,
                "realm_key": row["realm_key"],
                "realm_layer": player_integer(row, "realm_layer"),
                "cultivation": player_integer(row, "cultivation"),
                "total_cultivation": player_integer(row, "total_cultivation"),
                "location_key": row["location_key"],
                "path_key": row["path_key"],
                "subprofession_key": row["subprofession_key"],
                "qualification": player_object(row, "qualification_json"),
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
                "pollution": player_integer(row, "pollution"),
                "cross_realm_penalty_bp": player_integer(row, "cross_realm_penalty_bp"),
                "soul_power_before": player_integer(row, "soul_power"),
                "world_merit_before": player_integer(row, "world_merit"),
                "soul_prepare_bp": soul_prepare_bp,
                "reputation_prepare_bp": reputation_prepare_bp,
                "quest_prepare_bp": quest_prepare_bp,
                "route_count": player_integer(row, "void_route_count"),
                "domain_power": player_integer(row, "domain_power"),
                "domain_charge_before": player_integer(row, "domain_charge"),
                "void_power_before": player_integer(row, "void_power"),
                "space_resistance_bp": player_integer(row, "space_resistance_bp"),
                "void_instability_until": row["void_instability_until"],
                "success_reward": success_reward,
                "success_reward_local_reputation_maximums": success_reward_local_reputation_maximums,
                "starts_at": starts_at,
                "ends_at": ends_at,
            }
            snapshot["snapshot_digest"] = self._breakthrough_digest(snapshot, "snapshot_digest")
            value_delta = {
                "world_merit": -(
                    100 if is_nascent else 500 if is_soul_transformation or is_void_refining else 0
                )
            }
            if is_soul_transformation:
                value_delta["soul_power"] = -200
            if is_void_refining:
                value_delta["domain_charge"] = -100
            spend_player_state(
                connection,
                row,
                updated_at=now_text,
                costs={"spirit_stones": definition.currency_cost, **material_costs},
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
                "snapshot": snapshot,
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
            if str(row["realm_key"]) != "soul_transformation" or player_integer(row, "realm_layer") < 3:
                raise DomainNotEligibleError("domain requires soul transformation L3")
            if row["domain_key"]:
                raise DomainAlreadySelectedError("domain already selected")
            if str(row["path_key"] or "") != path_key:
                raise DomainNotEligibleError("domain does not match primary path")
            talent_level = connection.execute("SELECT COALESCE(MAX(tier), 0) AS level FROM talent_node_states WHERE player_id = ? AND tree_key = ? AND status = 'learned'", (row["id"], path_key)).fetchone()
            if max(player_integer(row, "domain_level"), int(talent_level["level"] if talent_level else 0)) < 5:
                raise DomainNotEligibleError("primary path level is insufficient")
            pending = connection.execute("SELECT id, ends_at FROM domain_selection_sessions WHERE player_id = ? AND status = 'pending' ORDER BY id DESC LIMIT 1", (row["id"],)).fetchone()
            if pending is not None:
                if now < datetime.fromisoformat(str(pending["ends_at"])):
                    raise DomainSelectionBusyError("domain selection is already pending")
                connection.execute("UPDATE domain_selection_sessions SET status = 'expired', updated_at = ? WHERE id = ?", (now_text, pending["id"]))
            inventory = player_inventory(row)
            if inventory_amount(inventory, "item.domain_core") < 1:
                raise MaterialInsufficientError("domain core is missing")
            if player_currency(row) < 10_000:
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
            inventory = player_inventory(row)
            if inventory_amount(inventory, "item.domain_core") < 1:
                raise MaterialInsufficientError("domain core is missing")
            if player_currency(row) < 10_000:
                raise CurrencyInsufficientError("domain selection requires spirit stones")
            snapshot = self._json_object(session["snapshot_json"], {})
            domain_key = str(session["domain_key"])
            pollution_delta = 15 if domain_key == "domain.abyss_shadow" else 0
            bloodline_delta = -10 if domain_key == "domain.ancestral_wild" else 0
            spend_player_state(
                connection,
                row,
                updated_at=now_text,
                costs={"item.domain_core": 1, "spirit_stones": 10_000},
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
            inventory = player_inventory(row)
            stones_spent = 0
            medicine_consumed = False
            if not expired and not early:
                raise WeaknessActiveError("domain crack has not expired")
            if not expired and early:
                if str(row["location_key"]) != "xuantian.domain_front":
                    raise BreakthroughRequirementError("early domain recovery requires domain front")
            if inventory_amount(inventory, "item.pill.domain_restore") < 1:
                raise MaterialInsufficientError("domain restore pill is missing")
                if player_currency(row) < 2000:
                    raise CurrencyInsufficientError("early domain recovery requires spirit stones")
                stones_spent = 2000
                medicine_consumed = True
            spend_player_state(
                connection,
                row,
                updated_at=now_text,
                costs=(
                    {"item.pill.domain_restore": 1, "spirit_stones": stones_spent}
                    if medicine_consumed
                    else None
                ),
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
                "SELECT operation_name, request_hash, player_id, result_json FROM operations WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            if existing is not None:
                if existing["operation_name"] != operation_name or existing["request_hash"] != request_hash:
                    raise OperationConflictError("operation input differs from its original request")
                row = self._require_player(connection, platform, platform_user_id, writable=False)
                if int(existing["player_id"]) != int(row["id"]):
                    raise OperationConflictError("operation does not belong to this player")
                payload = self._breakthrough_object(existing["result_json"], "breakthrough settlement operation")
                session_id = payload.get("session_id")
                if not isinstance(session_id, str) or not session_id:
                    raise ValueError("breakthrough settlement operation has no session")
                session = connection.execute(
                    "SELECT * FROM breakthrough_sessions WHERE session_id = ? AND player_id = ? LIMIT 1",
                    (session_id, row["id"]),
                ).fetchone()
                if session is None or session["status"] not in {"succeeded", "failed"}:
                    raise ValueError("breakthrough settlement operation has no terminal session")
                stored_result = self._breakthrough_object(session["result_json"], "breakthrough settlement result")
                stored_payload = {
                    "session_id": str(session["session_id"]),
                    "target_realm": str(session["target_realm"]),
                    **stored_result,
                }
                self._validate_breakthrough_result(
                    stored_payload,
                    session_id=str(session["session_id"]),
                    target_realm=str(session["target_realm"]),
                )
                self._validate_breakthrough_result(
                    payload,
                    session_id=str(session["session_id"]),
                    target_realm=str(session["target_realm"]),
                    player_id=str(row["player_id"]),
                )
                if {key: value for key, value in payload.items() if key != "player"} != stored_payload:
                    raise ValueError("breakthrough settlement operation does not match session result")
                return self._breakthrough_settlement_from_payload(payload, replay=True)
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
            snapshot = self._breakthrough_object(session["snapshot_json"], "breakthrough snapshot")
            from ...progression.breakthrough.rules import breakthrough_definition

            try:
                definition = breakthrough_definition(str(snapshot["target_realm"]))
            except ValueError as exc:
                raise BreakthroughRequirementError("historical breakthrough rule is unavailable") from exc
            self._validate_breakthrough_snapshot(snapshot, session, definition)
            start_operation = connection.execute(
                "SELECT operation_name, player_id, result_json FROM operations WHERE operation_id = ?",
                (session["operation_id"],),
            ).fetchone()
            if start_operation is None or start_operation["operation_name"] != definition.key:
                raise ValueError("breakthrough start operation is missing")
            if int(start_operation["player_id"]) != int(row["id"]):
                raise ValueError("breakthrough start operation player is invalid")
            start_payload = self._breakthrough_object(start_operation["result_json"], "breakthrough start operation")
            start_snapshot = self._breakthrough_object(start_payload.get("snapshot"), "breakthrough start snapshot")
            self._validate_breakthrough_snapshot_integrity(start_snapshot)
            if start_snapshot != snapshot:
                raise ValueError("breakthrough start snapshot does not match session")
            success_reward = None
            success_reward_local_reputation_maximums: dict[str, int] = {}
            if definition.reward_key is not None:
                success_reward = reward_grant_from_snapshot(
                    snapshot.get("success_reward"),
                    operation="progression.settle_breakthrough",
                )
                if success_reward.key != definition.reward_key:
                    raise ValueError("breakthrough reward snapshot does not match its definition")
                if success_reward.assets or success_reward.value_delta or success_reward.set_values or success_reward.reputation:
                    raise ValueError("breakthrough reward snapshot must contain only local reputation")
                raw_maximums = snapshot.get("success_reward_local_reputation_maximums")
                if not isinstance(raw_maximums, dict) or set(raw_maximums) != set(success_reward.local_reputation):
                    raise ValueError("breakthrough reward snapshot has invalid local reputation maximums")
                for key, maximum in raw_maximums.items():
                    if isinstance(maximum, bool) or not isinstance(maximum, int) or maximum <= 0:
                        raise ValueError("breakthrough reward snapshot has an invalid local reputation maximum")
                    success_reward_local_reputation_maximums[key] = maximum
            elif snapshot.get("success_reward") is not None or snapshot.get("success_reward_local_reputation_maximums") != {}:
                raise ValueError("breakthrough has an unexpected reward snapshot")
            roll_bp = breakthrough_roll_bp(str(snapshot.get("random_seed", session["operation_id"])))
            final_success_bp = int(snapshot.get("success_bp", definition.base_success_bp))
            success = roll_bp < final_success_bp
            cultivation_before = int(snapshot.get("cultivation", player_integer(row, "cultivation")))
            pity_before = int(snapshot.get("pity_before_bp", player_integer(row, "breakthrough_pity_bp")))
            protection_requested = bool(snapshot.get("protection_requested", False))
            is_nascent = str(snapshot.get("target_realm", session["target_realm"])) == "nascent_soul"
            is_soul_transformation = str(snapshot.get("target_realm", session["target_realm"])) == "soul_transformation"
            is_void_refining = str(snapshot.get("target_realm", session["target_realm"])) == "void_refining"
            protection_key = str(snapshot.get("protection_key") or definition.protection_key)
            inventory = player_inventory(row, keep_zero=is_void_refining)
            protection_consumed = bool(
                (not success)
                and not is_nascent
                and protection_requested
                and inventory_amount(inventory, protection_key) > 0
            )
            pity_after = next_pity_bp(definition, pity_before, success)
            weakness_until: str | None = None
            heart_demon_pending = False
            reward_local_reputation = 0
            if success:
                cultivation_after = 0
                stamina_after = min(
                    player_integer(row, "stamina_max"),
                    player_integer(row, "stamina") + definition.reward_stamina,
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
                    "stamina": stamina_after - player_integer(row, "stamina"),
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
                            "max_hp": player_integer(row, "max_hp") + 600,
                            "max_mp": player_integer(row, "max_mp") + 480,
                            "carry_capacity": player_integer(row, "carry_capacity") + 50,
                            "exploration_efficiency_bp": player_integer(row, "exploration_efficiency_bp") + 1500,
                            "heart_demon_bonus_bp": 0,
                            "soul_fatigue_until": None,
                        }
                    )
                elif is_soul_transformation:
                    player_values.update(
                        {
                            "stamina_max": player_integer(row, "stamina_max") + 20,
                            "domain_key": None,
                            "domain_power": 100,
                            "domain_charge": 150,
                            "domain_charge_max": 150,
                            "domain_charge_reset_date": now.date().isoformat(),
                            "realm_resistance_bp": 1000,
                            "domain_crack_until": None,
                            "max_hp": player_integer(row, "max_hp") + 1000,
                            "max_mp": player_integer(row, "max_mp") + 800,
                            "initiative": player_integer(row, "initiative") + 20,
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
                            "max_hp": player_integer(row, "max_hp") + 1500,
                            "max_mp": player_integer(row, "max_mp") + 1200,
                            "carry_capacity": player_integer(row, "carry_capacity") + 100,
                        }
                    )
                local_reputation_before = (
                    player_reputation_state(connection, int(row["id"])).local
                    if success_reward is not None and success_reward.local_reputation
                    else {}
                )
                grant_player_state(
                    connection,
                    row,
                    updated_at=now_text,
                    rewards={"spirit_stones": definition.reward_currency, **reward_items},
                    value_delta=value_delta,
                    maximums={"stamina": player_integer(row, "stamina_max")},
                    player_values=player_values,
                    preserve_zero=is_void_refining,
                    local_reputation_delta=(
                        success_reward.local_reputation
                        if success_reward is not None
                        else None
                    ),
                    local_reputation_maximums=(
                        success_reward_local_reputation_maximums
                        if success_reward is not None and success_reward.local_reputation
                        else None
                    ),
                )
                if success_reward is not None and success_reward.local_reputation:
                    local_reputation_after = player_reputation_state(connection, int(row["id"])).local
                    reward_local_reputation = sum(
                        local_reputation_after.get(key, 0) - local_reputation_before.get(key, 0)
                        for key in success_reward.local_reputation
                    )
                if definition.target_realm == "foundation":
                    change_player_state(
                        connection,
                        row,
                        updated_at=now_text,
                        player_values={
                            "foundation_quality": max(
                                player_integer(row, "foundation_quality"),
                                int(snapshot.get("foundation_quality_on_success") or 5500),
                            )
                        },
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
                spend_player_state(
                    connection,
                    row,
                    updated_at=now_text,
                    costs={protection_key: 1} if protection_consumed else None,
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
                "reward_local_reputation": reward_local_reputation,
                "reward_items": dict(definition.reward_items or {}) if success else {},
                "status": status,
                "heart_demon_pending": heart_demon_pending,
            }
            result["result_digest"] = self._breakthrough_digest(result, "result_digest")
            result_payload = {
                "session_id": str(session["session_id"]),
                "target_realm": str(session["target_realm"]),
                **result,
            }
            self._validate_breakthrough_result(
                result_payload,
                session_id=str(session["session_id"]),
                target_realm=str(session["target_realm"]),
            )
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
                    "pollution_before": player_integer(row, "pollution"),
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
            payload = {"player": self._player_payload(player), **result_payload}
            self._validate_breakthrough_result(
                payload,
                session_id=str(session["session_id"]),
                target_realm=str(session["target_realm"]),
                player_id=str(row["player_id"]),
            )
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
            if effective_choice == "heart_demon.bargain" and str(row["path_key"] or "") != "demonic" and player_integer(row, "pollution") < 20:
                raise BreakthroughRequirementError("bargain requires a demonic path or pollution 20")
            inventory = player_inventory(row)
            if effective_choice == "heart_demon.purify":
                if inventory_amount(inventory, "item.pill.soul_restore") < 1:
                    raise MaterialInsufficientError("soul restore pill is missing")
            pollution_before = player_integer(row, "pollution")
            pollution_after = pollution_before
            merit_gain = 0
            fatigue_hours = 8
            pity_after = min(1200, player_integer(row, "breakthrough_pity_bp") + 400)
            bonus_after = player_integer(row, "heart_demon_bonus_bp")
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
            spend_player_state(
                connection,
                row,
                updated_at=now_text,
                costs={"item.pill.soul_restore": 1} if effective_choice == "heart_demon.purify" else None,
                value_delta={
                    "pollution": pollution_after - pollution_before,
                    "world_merit": merit_gain,
                    "breakthrough_pity_bp": pity_after - player_integer(row, "breakthrough_pity_bp"),
                },
                maximums={"pollution": 100, "breakthrough_pity_bp": 1200},
                preserve_zero=True,
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
            inventory = player_inventory(row)
            medicine_key = "item.pill.golden_core_restore" if recovery_kind == "foundation_shock" else "item.pill.healing_low"
            stones_cost = 200 if recovery_kind == "foundation_shock" else 50
            medicine_consumed = False
            stones_spent = 0
            if not expired and not early:
                raise WeaknessActiveError("weakness has not expired")
            if not expired and early:
                if inventory_amount(inventory, medicine_key) < 1:
                    raise MaterialInsufficientError("early recovery requires a recovery pill")
                if player_currency(row) < stones_cost:
                    raise CurrencyInsufficientError("early recovery requires spirit stones")
                medicine_consumed = True
                stones_spent = stones_cost
            spend_player_state(
                connection,
                row,
                updated_at=now_text,
                costs=(
                    {"spirit_stones": stones_cost, medicine_key: 1}
                    if medicine_consumed
                    else None
                ),
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
