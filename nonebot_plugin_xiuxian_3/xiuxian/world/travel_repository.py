"""SQLite transactions for ordinary world travel sessions."""

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


class TravelRepositoryMixin:
    async def preview_travel(
        self,
        *,
        platform: str,
        platform_user_id: str,
        destination: str,
    ) -> TravelPreview:
        await self.initialize()
        player = await self.get_player(platform=platform, platform_user_id=platform_user_id)
        if player is None:
            raise PlayerNotFoundError("player does not exist")
        definition = destination_definition(destination)
        missing: list[str] = []
        if not meets_realm(player.realm_key, player.realm_layer, definition.required_realm, definition.required_layer):
            required = f"{definition.required_realm} L{definition.required_layer}"
            missing.append(f"境界要求（{required}）")
        if definition.source_locations and player.location_key not in definition.source_locations:
            missing.append("来源地点")
        if player.dao_fruit_progress < definition.required_dao_fruit_progress:
            missing.append("道果进度")
        if player.stamina < definition.stamina_cost:
            missing.append("体力")
        if player.spirit_stones < definition.currency_cost:
            missing.append("灵石")
        if definition.pass_key and player.inventory.get(definition.pass_key, 0) < definition.pass_quantity:
            missing.append("通行物品")
        endgame_status = player.endgame_status or "none"
        if definition.required_endgame_status:
            if endgame_status != definition.required_endgame_status:
                missing.append("终局状态")
        elif endgame_status in {"ascension_ready", "ascended", "remained_in_world"}:
            missing.append("当前状态")
        if definition.daily_start_limit:
            starts_today = await asyncio.to_thread(
                self._count_destination_starts_today,
                platform,
                platform_user_id,
                destination,
                self._now(),
            )
            if starts_today >= definition.daily_start_limit:
                missing.append("今日访问次数")
        ready = player.status == "active" and player.stage in {STAGE_MORTAL, "seeker", "cultivator"} and not missing
        return TravelPreview(
            player=player,
            destination=destination,
            source=player.location_key,
            duration_seconds=definition.duration_seconds,
            stamina_cost=definition.stamina_cost,
            currency_cost=definition.currency_cost,
            pass_key=definition.pass_key,
            pass_quantity=definition.pass_quantity,
            ready=ready,
            missing=tuple(missing),
        )

    def _count_destination_starts_today(
        self, platform: str, platform_user_id: str, destination: str, now: datetime
    ) -> int:
        with self._connect() as connection:
            player = self._require_player(connection, platform, platform_user_id, writable=False)
            return self._count_destination_starts_today_in(
                connection, player_id=int(player["id"]), destination=destination, now=now
            )

    @staticmethod
    def _count_destination_starts_today_in(
        connection: sqlite3.Connection, *, player_id: int, destination: str, now: datetime
    ) -> int:
        utc_now = now.astimezone(timezone.utc)
        day_start = serialize_datetime(utc_now.replace(hour=0, minute=0, second=0, microsecond=0))
        day_end = serialize_datetime(utc_now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1))
        row = connection.execute(
            "SELECT COUNT(*) AS count FROM travel_sessions "
            "WHERE player_id = ? AND destination = ? AND starts_at >= ? AND starts_at < ?",
            (player_id, destination, day_start, day_end),
        ).fetchone()
        return int(row["count"]) if row else 0
    async def start_travel(
        self,
        *,
        platform: str,
        platform_user_id: str,
        destination: str,
        operation_id: str,
    ) -> TravelStartRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._start_travel_sync,
                platform,
                platform_user_id,
                destination,
                operation_id,
            )

    def _start_travel_sync(self, platform: str, platform_user_id: str, destination: str, operation_id: str) -> TravelStartRecord:
        last_error: Exception | None = None
        for attempt in range(5):
            try:
                return self._start_travel_once(platform, platform_user_id, destination, operation_id)
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).lower():
                    raise
                if attempt == 4:
                    raise RepositoryBusyError("database remained locked") from exc
                last_error = exc
                time.sleep(0.01 * (2**attempt))
        raise RepositoryBusyError("database remained locked") from last_error

    def _start_travel_once(self, platform: str, platform_user_id: str, destination: str, operation_id: str) -> TravelStartRecord:
        definition = destination_definition(destination)
        operation_name = "world.start_travel"
        request_payload = {
            "platform": platform,
            "platform_user_id": platform_user_id,
            "destination": destination,
        }
        request_hash = self._request_hash(operation_name, request_payload)
        now = self._now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            if existing is not None:
                if existing["operation_name"] != operation_name or existing["request_hash"] != request_hash:
                    raise OperationConflictError("operation input differs from its original request")
                return self._travel_start_from_payload(json.loads(existing["result_json"]), replay=True)

            row = self._require_player(connection, platform, platform_user_id, writable=False)
            endgame_status = str(row["endgame_status"] or "none")
            if definition.required_endgame_status:
                if endgame_status != definition.required_endgame_status:
                    raise LocationRequirementError("endgame status is not ready for this destination")
            elif endgame_status in {"ascension_ready", "ascended", "remained_in_world"}:
                raise PlayerStageConflictError("endgame state has frozen ordinary travel")
            if row["stage"] not in {STAGE_MORTAL, "seeker", "cultivator"}:
                raise PlayerStageConflictError("player is not ready for travel")
            weakness_until = row["weakness_until"]
            if weakness_until and now < datetime.fromisoformat(str(weakness_until)):
                raise WeaknessActiveError("breakthrough weakness blocks travel")
            current = str(row["location_key"])
            if definition.source_locations and current not in definition.source_locations:
                raise LocationRequirementError("source location is not valid")
            if not meets_realm(str(row["realm_key"]), int(row["realm_layer"]), definition.required_realm, definition.required_layer):
                raise LocationRequirementError("realm requirement is not met")
            if int(row["dao_fruit_progress"]) < definition.required_dao_fruit_progress:
                raise LocationRequirementError("dao fruit progress is insufficient")

            player_id = int(row["id"])
            active = connection.execute(
                "SELECT 1 FROM travel_sessions WHERE player_id = ? AND status = 'running' LIMIT 1", (player_id,)
            ).fetchone()
            if active is not None:
                raise TravelBusyError("travel is already running")
            for table, status in (
                ("cultivation_sessions", "running"),
                ("production_orders", "processing"),
                ("breakthrough_sessions", "preparing"),
                ("endgame_sessions", "preparing"),
                ("final_battle_members", "asset_lock_status = 'locked'"),
                ("tribulation_trial_sessions", "preparing"),
            ):
                if table == "final_battle_members":
                    busy = connection.execute(
                        "SELECT 1 FROM final_battle_members WHERE player_id = ? AND asset_lock_status = 'locked' LIMIT 1",
                        (player_id,),
                    ).fetchone()
                else:
                    busy = connection.execute(
                        f"SELECT 1 FROM {table} WHERE player_id = ? AND status = ? LIMIT 1", (player_id, status)
                    ).fetchone()
                if busy is not None:
                    raise TravelBusyError("another action is already running")
            exploration = connection.execute(
                "SELECT 1 FROM exploration_sessions WHERE player_id = ? AND status IN ('created', 'running', 'combat_pending') LIMIT 1",
                (player_id,),
            ).fetchone()
            if exploration is not None:
                raise TravelBusyError("exploration is already running")
            retreat = connection.execute(
                "SELECT 1 FROM retreat_sessions WHERE player_id = ? AND status = 'running' LIMIT 1",
                (player_id,),
            ).fetchone()
            if retreat is not None:
                raise TravelBusyError("retreat is already running")

            stamina = int(row["stamina"])
            stones = int(row["spirit_stones"])
            inventory = self._json_object(row["inventory_json"], {})
            if stamina < definition.stamina_cost:
                raise ResourceInsufficientError("stamina is insufficient")
            if stones < definition.currency_cost:
                raise CurrencyInsufficientError("spirit stones are insufficient")
            if definition.pass_key and inventory.get(definition.pass_key, 0) < definition.pass_quantity:
                raise LocationRequirementError("travel pass is missing")
            if definition.daily_start_limit and self._count_destination_starts_today_in(
                connection, player_id=player_id, destination=destination, now=now
            ) >= definition.daily_start_limit:
                raise LocationRequirementError("destination daily visit limit is reached")

            if definition.pass_key and not definition.consume_pass_on_arrival:
                remaining = inventory.get(definition.pass_key, 0) - definition.pass_quantity
                if remaining:
                    inventory[definition.pass_key] = remaining
                else:
                    inventory.pop(definition.pass_key, None)
            session_id = uuid4().hex
            ends_at = now + timedelta(seconds=definition.duration_seconds)
            snapshot = {
                "rule_version": definition.rule_version,
                "content_version": definition.content_version,
                "source": current,
                "destination": destination,
                "stamina_cost": definition.stamina_cost,
                "currency_cost": definition.currency_cost,
                "pass_key": definition.pass_key,
                "pass_quantity": definition.pass_quantity,
                "required_dao_fruit_progress": definition.required_dao_fruit_progress,
                "daily_start_limit": definition.daily_start_limit,
                "required_endgame_status": definition.required_endgame_status,
                "consume_pass_on_arrival": definition.consume_pass_on_arrival,
            }
            connection.execute(
                """
                UPDATE players
                SET stamina = ?, spirit_stones = ?, inventory_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (stamina - definition.stamina_cost, stones - definition.currency_cost,
                 json.dumps(inventory, ensure_ascii=False, sort_keys=True), serialize_datetime(now), player_id),
            )
            connection.execute(
                """
                INSERT INTO travel_sessions(
                    session_id, player_id, operation_id, source_location, destination, status,
                    starts_at, ends_at, stamina_cost, currency_cost, pass_key, pass_quantity,
                    snapshot_json, result_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'running', ?, ?, ?, ?, ?, ?, ?, '{}', ?, ?)
                """,
                (session_id, player_id, operation_id, current, destination, serialize_datetime(now),
                 serialize_datetime(ends_at), definition.stamina_cost, definition.currency_cost,
                 definition.pass_key, definition.pass_quantity, json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
                 serialize_datetime(now), serialize_datetime(now)),
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (player_id,)).fetchone()
            player = self._row_to_player(updated)
            payload = {
                "player": self._player_payload(player), "session_id": session_id,
                "source": current, "destination": destination, "status": "running",
                "starts_at": serialize_datetime(now), "ends_at": serialize_datetime(ends_at),
                "stamina_cost": definition.stamina_cost, "currency_cost": definition.currency_cost,
                "pass_key": definition.pass_key, "pass_quantity": definition.pass_quantity,
            }
            connection.execute(
                "INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (operation_id, operation_name, player_id, request_hash, json.dumps(payload, ensure_ascii=False, sort_keys=True), serialize_datetime(now)),
            )
            return self._travel_start_from_payload(payload)

    @staticmethod
    def _travel_start_from_payload(payload: dict[str, Any], replay: bool = False) -> TravelStartRecord:
        return TravelStartRecord(
            player=SQLitePlayerRepository._row_to_player(payload["player"]),
            session_id=str(payload["session_id"]), source=str(payload["source"]),
            destination=str(payload["destination"]), status=str(payload["status"]),
            starts_at=str(payload["starts_at"]), ends_at=str(payload["ends_at"]),
            stamina_cost=int(payload["stamina_cost"]), currency_cost=int(payload["currency_cost"]),
            pass_key=payload.get("pass_key"), pass_quantity=int(payload.get("pass_quantity", 0)),
            already_completed=replay,
        )
    async def settle_travel(self, *, platform: str, platform_user_id: str, operation_id: str) -> TravelSettlementRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._settle_travel_sync, platform, platform_user_id, operation_id)

    def _settle_travel_sync(self, platform: str, platform_user_id: str, operation_id: str) -> TravelSettlementRecord:
        last_error: Exception | None = None
        for attempt in range(5):
            try:
                return self._settle_travel_once(platform, platform_user_id, operation_id)
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).lower():
                    raise
                if attempt == 4:
                    raise RepositoryBusyError("database remained locked") from exc
                last_error = exc
                time.sleep(0.01 * (2**attempt))
        raise RepositoryBusyError("database remained locked") from last_error

    def _settle_travel_once(self, platform: str, platform_user_id: str, operation_id: str) -> TravelSettlementRecord:
        operation_name = "world.settle_travel"
        request_payload = {"platform": platform, "platform_user_id": platform_user_id}
        request_hash = self._request_hash(operation_name, request_payload)
        now = self._now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id = ?", (operation_id,)
            ).fetchone()
            if existing is not None:
                if existing["operation_name"] != operation_name or existing["request_hash"] != request_hash:
                    raise OperationConflictError("operation input differs from its original request")
                return self._travel_settlement_from_payload(json.loads(existing["result_json"]), replay=True)
            row = self._require_player(connection, platform, platform_user_id, writable=False)
            session = connection.execute(
                "SELECT * FROM travel_sessions WHERE player_id = ? AND status = 'running' ORDER BY id DESC LIMIT 1", (row["id"],)
            ).fetchone()
            if session is None:
                raise TravelNotFoundError("no running travel")
            ends_at = datetime.fromisoformat(str(session["ends_at"]))
            if now < ends_at:
                raise TravelNotReadyError("travel is not ready")
            snapshot = self._json_object(session["snapshot_json"], {})
            pass_key = str(snapshot.get("pass_key") or session["pass_key"] or "") or None
            pass_quantity = int(snapshot.get("pass_quantity", session["pass_quantity"] or 0))
            consume_pass_on_arrival = bool(snapshot.get("consume_pass_on_arrival", False))
            inventory = self._json_object(row["inventory_json"], {})
            pass_consumed = False
            if consume_pass_on_arrival and pass_key and pass_quantity:
                available = int(inventory.get(pass_key, 0))
                if available < pass_quantity:
                    raise LocationRequirementError("travel pass is missing at arrival")
                remaining = available - pass_quantity
                if remaining:
                    inventory[pass_key] = remaining
                else:
                    inventory.pop(pass_key, None)
                pass_consumed = True
            updated_at = serialize_datetime(now)
            if pass_consumed:
                connection.execute(
                    "UPDATE players SET location_key = ?, inventory_json = ?, updated_at = ? WHERE id = ?",
                    (session["destination"], json.dumps(inventory, ensure_ascii=False, sort_keys=True), updated_at, row["id"]),
                )
            else:
                connection.execute(
                    "UPDATE players SET location_key = ?, updated_at = ? WHERE id = ?",
                    (session["destination"], updated_at, row["id"]),
                )
            connection.execute(
                "UPDATE travel_sessions SET status = 'arrived', result_json = ?, updated_at = ? WHERE id = ? AND status = 'running'",
                (json.dumps({"arrived": True, "pass_consumed": pass_consumed, "settled_at": updated_at}, ensure_ascii=False, sort_keys=True), updated_at, session["id"]),
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (row["id"],)).fetchone()
            player = self._row_to_player(updated)
            payload = {
                "player": self._player_payload(player), "session_id": session["session_id"],
                "source": session["source_location"], "destination": session["destination"], "status": "arrived",
                "arrived": True, "stamina_cost": int(session["stamina_cost"]), "currency_cost": int(session["currency_cost"]),
                "pass_key": session["pass_key"], "pass_quantity": int(session["pass_quantity"]),
                "pass_consumed": pass_consumed,
            }
            connection.execute(
                "INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (operation_id, operation_name, row["id"], request_hash, json.dumps(payload, ensure_ascii=False, sort_keys=True), serialize_datetime(now)),
            )
            return self._travel_settlement_from_payload(payload)

    @staticmethod
    def _travel_settlement_from_payload(payload: dict[str, Any], replay: bool = False) -> TravelSettlementRecord:
        return TravelSettlementRecord(
            player=SQLitePlayerRepository._row_to_player(payload["player"]),
            session_id=str(payload["session_id"]), source=str(payload["source"]),
            destination=str(payload["destination"]), status=str(payload["status"]),
            arrived=bool(payload.get("arrived", False)), stamina_cost=int(payload.get("stamina_cost", 0)),
            currency_cost=int(payload.get("currency_cost", 0)), pass_key=payload.get("pass_key"),
            pass_quantity=int(payload.get("pass_quantity", 0)), pass_consumed=bool(payload.get("pass_consumed", False)),
            already_completed=replay,
        )
