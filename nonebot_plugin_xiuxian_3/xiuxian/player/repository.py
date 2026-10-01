"""SQLite transactions for player identity, onboarding and projections."""

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
from ..specials.codex_projection import record_location_discovery, record_material_discoveries
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
from ..utils.assets import inventory_json
from ..utils.player import change_player_state, grant_player_state, player_integer
from ..utils.json import json_object
from ..utils.player import player_field, player_reputation, player_values


class PlayerRepositoryMixin:
    async def create_player(
        self,
        *,
        platform: str,
        platform_user_id: str,
        scene_id: str,
        nickname: str,
        dao_name: str,
        operation_id: str,
    ) -> PlayerCreateRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._create_player_sync,
                platform,
                platform_user_id,
                scene_id,
                nickname,
                dao_name,
                operation_id,
            )

    def _create_player_sync(
        self,
        platform: str,
        platform_user_id: str,
        scene_id: str,
        nickname: str,
        dao_name: str,
        operation_id: str,
    ) -> PlayerCreateRecord:
        last_error: Exception | None = None
        for attempt in range(5):
            try:
                return self._create_player_once(
                    platform,
                    platform_user_id,
                    scene_id,
                    nickname,
                    dao_name,
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

    def _create_player_once(
        self,
        platform: str,
        platform_user_id: str,
        scene_id: str,
        nickname: str,
        dao_name: str,
        operation_id: str,
    ) -> PlayerCreateRecord:
        operation_payload = {
            "platform": platform,
            "platform_user_id": platform_user_id,
            "scene_id": scene_id,
            "nickname": nickname,
            "dao_name": dao_name,
        }
        request_hash = self._request_hash("player.create", operation_payload)
        now = self._now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing_operation = connection.execute(
                "SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            if existing_operation is not None:
                if (
                    existing_operation["operation_name"] != "player.create"
                    or existing_operation["request_hash"] != request_hash
                ):
                    raise OperationConflictError("operation input differs from its original request")
                payload = json.loads(existing_operation["result_json"])
                return PlayerCreateRecord(
                    player=self._row_to_player(payload["player"]),
                    created=bool(payload.get("created", False)),
                    already_completed=True,
                )

            row = connection.execute(
                "SELECT * FROM players WHERE platform = ? AND platform_user_id = ?",
                (platform, platform_user_id),
            ).fetchone()
            if row is not None:
                if row["status"] != "active":
                    raise PlayerSuspendedError("player is not writable")
                player = self._row_to_player(row)
                created = False
            else:
                if dao_name:
                    taken = connection.execute(
                        "SELECT 1 FROM players WHERE dao_name = ? LIMIT 1",
                        (dao_name,),
                    ).fetchone()
                    if taken is not None:
                        raise DaoNameTakenError("dao name is already used")
                public_id = uuid4().hex
                connection.execute(
                    """
                    INSERT INTO players (
                        player_id, platform, platform_user_id, scene_id, nickname, dao_name, stage,
                        status, location_key, qualification_json,
                        spirit_stones, stamina, stamina_max, energy, energy_max,
                        inventory_json, intro_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'active', 'xuantian.new_town',
                              '{}', 0, 0, 0, 0, 0, '{}', '{}', ?, ?)
                    """,
                    (
                        public_id,
                        platform,
                        platform_user_id,
                        scene_id,
                        nickname,
                        dao_name,
                        STAGE_NEW_USER,
                        serialize_datetime(now),
                        serialize_datetime(now),
                    ),
                )
                row = connection.execute(
                    "SELECT * FROM players WHERE player_id = ?", (public_id,)
                ).fetchone()
                if row is None:
                    raise RuntimeError("player insert returned no row")
                player = self._row_to_player(row)
                created = True

            payload = {"created": created, "player": self._player_payload(player)}
            connection.execute(
                """
                INSERT INTO operations(
                    operation_id, operation_name, player_id, request_hash, result_json, created_at
                ) VALUES (?, ?, (SELECT id FROM players WHERE player_id = ?), ?, ?, ?)
                """,
                (
                    operation_id,
                    "player.create",
                    player.player_id,
                    request_hash,
                    json.dumps(payload, ensure_ascii=False, sort_keys=True),
                    serialize_datetime(now),
                ),
            )
            return PlayerCreateRecord(player=player, created=created, already_completed=False)

    async def start_seeking(
        self,
        *,
        platform: str,
        platform_user_id: str,
        scene_id: str,
        nickname: str,
        root_affinity: str = "",
        operation_id: str,
    ) -> SeekingRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._start_seeking_sync,
                platform,
                platform_user_id,
                scene_id,
                nickname,
                root_affinity,
                operation_id,
            )

    def _start_seeking_sync(
        self,
        platform: str,
        platform_user_id: str,
        scene_id: str,
        nickname: str,
        root_affinity: str,
        operation_id: str,
    ) -> SeekingRecord:
        last_error: Exception | None = None
        for attempt in range(5):
            try:
                return self._start_seeking_once(
                    platform,
                    platform_user_id,
                    scene_id,
                    nickname,
                    root_affinity,
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

    def _start_seeking_once(
        self,
        platform: str,
        platform_user_id: str,
        scene_id: str,
        nickname: str,
        root_affinity: str,
        operation_id: str,
    ) -> SeekingRecord:
        operation_payload = {
            "platform": platform,
            "platform_user_id": platform_user_id,
            "root_affinity": root_affinity,
        }
        request_hash = self._request_hash("player.start_seeking", operation_payload)
        now = self._now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing_operation = connection.execute(
                "SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            if existing_operation is not None:
                if (
                    existing_operation["operation_name"] != "player.start_seeking"
                    or existing_operation["request_hash"] != request_hash
                ):
                    raise OperationConflictError("operation input differs from its original request")
                payload = json.loads(existing_operation["result_json"])
                player = self._row_to_player(payload["player"])
                return SeekingRecord(
                    player=player,
                    created=False,
                    already_completed=True,
                )

            row = self._require_player(connection, platform, platform_user_id)

            created = row["stage"] == STAGE_NEW_USER
            if created:
                qualification = qualification_for(platform, platform_user_id)
                grant_player_state(
                    connection,
                    row,
                    updated_at=serialize_datetime(now),
                    rewards={
                        "spirit_stones": 100,
                        "item.food.coarse_spirit_rice": 3,
                        "item.herb.blood_grass": 3,
                    },
                    player_values={
                        "stage": STAGE_MORTAL,
                        "realm_key": "mortal",
                        "realm_layer": 0,
                        "cultivation": 0,
                        "total_cultivation": 0,
                        "qualification_json": json.dumps(
                            qualification, ensure_ascii=False, sort_keys=True
                        ),
                        "stamina": 30,
                        "stamina_max": 30,
                        "energy": 30,
                        "energy_max": 30,
                    },
                )
                row = connection.execute("SELECT * FROM players WHERE id = ?", (row["id"],)).fetchone()
            else:
                return SeekingRecord(player=self._row_to_player(row), created=False, already_completed=False)
            player = self._row_to_player(row)
            payload = {"created": created, "player": self._player_payload(player)}
            connection.execute(
                """
                INSERT INTO operations(
                    operation_id, operation_name, player_id, request_hash, result_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    operation_id,
                    "player.start_seeking",
                    row["id"],
                    request_hash,
                    json.dumps(payload, ensure_ascii=False, sort_keys=True),
                    serialize_datetime(now),
                ),
            )
            record_location_discovery(
                connection,
                player_id=int(row["id"]),
                location_key="xuantian.new_town",
                operation_id=operation_id,
                occurred_at=now,
                snapshot={"source": "player.start_seeking", "location_key": "xuantian.new_town"},
                content=self.content,
            )
            record_material_discoveries(
                connection,
                player_id=int(row["id"]),
                operation_id=operation_id,
                occurred_at=now,
                reward={"item.herb.blood_grass": 3},
                snapshot={"source": "player.start_seeking"},
            )
            return SeekingRecord(player=player, created=created, already_completed=False)

    async def complete_intro(
        self,
        *,
        platform: str,
        platform_user_id: str,
        guide_key: str,
        service_key: str | None,
        operation_id: str,
    ) -> IntroRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._complete_intro_sync,
                platform,
                platform_user_id,
                guide_key,
                service_key,
                operation_id,
            )

    def _complete_intro_sync(
        self,
        platform: str,
        platform_user_id: str,
        guide_key: str,
        service_key: str | None,
        operation_id: str,
    ) -> IntroRecord:
        last_error: Exception | None = None
        for attempt in range(5):
            try:
                return self._complete_intro_once(
                    platform,
                    platform_user_id,
                    guide_key,
                    service_key,
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

    def _complete_intro_once(
        self,
        platform: str,
        platform_user_id: str,
        guide_key: str,
        service_key: str | None,
        operation_id: str,
    ) -> IntroRecord:
        operation_payload = {
            "platform": platform,
            "platform_user_id": platform_user_id,
            "guide_key": guide_key,
            "service_key": service_key,
        }
        request_hash = self._request_hash("player.complete_intro", operation_payload)
        now = self._now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing_operation = connection.execute(
                "SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            if existing_operation is not None:
                if (
                    existing_operation["operation_name"] != "player.complete_intro"
                    or existing_operation["request_hash"] != request_hash
                ):
                    raise OperationConflictError("operation input differs from its original request")
                payload = json.loads(existing_operation["result_json"])
                return IntroRecord(
                    player=self._row_to_player(payload["player"]),
                    guide_key=guide_key,
                    changed=bool(payload.get("changed", False)),
                    stage_advanced=bool(payload.get("stage_advanced", False)),
                    item_quantity=int(payload.get("item_quantity", 0)),
                    selected_service=payload.get("selected_service"),
                    already_completed=True,
                )

            row = self._require_player(connection, platform, platform_user_id)
            if row["stage"] not in {STAGE_MORTAL, "seeker"}:
                raise PlayerStageConflictError("player is not ready for mortal introduction")

            intro_state = self._json_object(row["intro_json"], {})
            flags = [str(item) for item in intro_state.get("flags", [])]
            selected = str(intro_state.get("selected_service") or row["selected_service"] or "") or None
            changed = guide_key not in flags
            if not changed and guide_key == "guide.choose_service" and selected != service_key:
                raise OperationConflictError("teaching service differs from the completed choice")

            item_quantity = 0
            stamina = player_integer(row, "stamina")
            energy = player_integer(row, "energy")
            if changed:
                if guide_key == "guide.gather_blood_grass":
                    if row["location_key"] != "xuantian.outskirts":
                        raise LocationRequiredError("gathering lesson requires the outskirts")
                    if stamina < 2:
                        raise ResourceInsufficientError("stamina is insufficient")
                    stamina -= 2
                    item_quantity = 1 + (hashlib.blake2b(operation_id.encode("utf-8"), digest_size=1).digest()[0] % 2)
                elif guide_key == "guide.choose_service":
                    if energy < 2:
                        raise ResourceInsufficientError("energy is insufficient")
                    energy -= 2
                    selected = service_key
                elif guide_key == "guide.read_world":
                    pass
                else:
                    raise ValueError("unsupported introduction guide")
                flags.append(guide_key)

            from ..player.intro_rules import intro_complete

            stage_advanced = row["stage"] == STAGE_MORTAL and intro_complete(flags)
            stage = "seeker" if stage_advanced else row["stage"]
            intro_state = {"flags": sorted(set(flags)), "selected_service": selected}
            grant_player_state(
                connection,
                row,
                updated_at=serialize_datetime(now),
                rewards=(
                    {"item.herb.blood_grass": item_quantity}
                    if item_quantity
                    else None
                ),
                value_delta={
                    "stamina": stamina - player_integer(row, "stamina"),
                    "energy": energy - player_integer(row, "energy"),
                },
                player_values={
                    "stage": stage,
                    "intro_json": json.dumps(intro_state, ensure_ascii=False, sort_keys=True),
                    "selected_service": selected,
                },
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (row["id"],)).fetchone()
            if updated is None:
                raise RuntimeError("intro completion returned no row")
            player = self._row_to_player(updated)
            payload = {
                "player": self._player_payload(player),
                "changed": changed,
                "stage_advanced": stage_advanced,
                "item_quantity": item_quantity,
                "selected_service": selected,
            }
            connection.execute(
                """
                INSERT INTO operations(
                    operation_id, operation_name, player_id, request_hash, result_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    operation_id,
                    "player.complete_intro",
                    row["id"],
                    request_hash,
                    json.dumps(payload, ensure_ascii=False, sort_keys=True),
                    serialize_datetime(now),
                ),
            )
            if changed and guide_key == "guide.gather_blood_grass":
                record_material_discoveries(
                    connection,
                    player_id=int(row["id"]),
                    operation_id=operation_id,
                    occurred_at=now,
                    reward={"item.herb.blood_grass": item_quantity},
                    snapshot={"source": "player.complete_intro", "guide_key": guide_key},
                )
            return IntroRecord(
                player=player,
                guide_key=guide_key,
                changed=changed,
                stage_advanced=stage_advanced,
                item_quantity=item_quantity,
                selected_service=selected,
            )

    async def travel_player(
        self,
        *,
        platform: str,
        platform_user_id: str,
        destination: str,
        operation_id: str,
    ) -> TravelRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._travel_player_sync,
                platform,
                platform_user_id,
                destination,
                operation_id,
            )

    def _travel_player_sync(
        self,
        platform: str,
        platform_user_id: str,
        destination: str,
        operation_id: str,
    ) -> TravelRecord:
        last_error: Exception | None = None
        for attempt in range(5):
            try:
                return self._travel_player_once(platform, platform_user_id, destination, operation_id)
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).lower():
                    raise
                if attempt == 4:
                    raise RepositoryBusyError("database remained locked") from exc
                last_error = exc
                time.sleep(0.01 * (2**attempt))
        raise RepositoryBusyError("database remained locked") from last_error

    def _travel_player_once(
        self,
        platform: str,
        platform_user_id: str,
        destination: str,
        operation_id: str,
    ) -> TravelRecord:
        from ..player.intro_rules import GUIDE_GATHER_BLOOD_GRASS, TRAVEL_COSTS
        from ..progression.rules import REALM_QI_SENSING, SPIRIT_FIELD_LOCATION

        operation_payload = {
            "platform": platform,
            "platform_user_id": platform_user_id,
            "destination": destination,
        }
        request_hash = self._request_hash("world.travel_intro", operation_payload)
        now = self._now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing_operation = connection.execute(
                "SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            if existing_operation is not None:
                if (
                    existing_operation["operation_name"] != "world.travel_intro"
                    or existing_operation["request_hash"] != request_hash
                ):
                    raise OperationConflictError("operation input differs from its original request")
                payload = json.loads(existing_operation["result_json"])
                return TravelRecord(
                    player=self._row_to_player(payload["player"]),
                    destination=destination,
                    changed=bool(payload.get("changed", False)),
                    stamina_cost=int(payload.get("stamina_cost", 0)),
                    already_completed=True,
                )

            row = self._require_player(connection, platform, platform_user_id)
            if row["stage"] not in {STAGE_MORTAL, "seeker", "cultivator"}:
                raise PlayerStageConflictError("player is not ready for travel")
            if destination not in TRAVEL_COSTS:
                raise LocationRequirementError("destination is not available")
            if destination == SPIRIT_FIELD_LOCATION:
                if row["realm_key"] != REALM_QI_SENSING or player_integer(row, "realm_layer") < 2:
                    raise LocationRequirementError("spirit field requires qi sensing layer 2")
                intro_state = self._json_object(row["intro_json"], {})
                if GUIDE_GATHER_BLOOD_GRASS not in set(intro_state.get("flags", [])):
                    raise LocationRequirementError("spirit field requires the gathering lesson")

            current = str(row["location_key"])
            moving_session = connection.execute(
                "SELECT 1 FROM cultivation_sessions WHERE player_id = ? AND status = 'running' LIMIT 1",
                (row["id"],),
            ).fetchone()
            if moving_session is not None:
                raise CultivationBusyError("cultivation must be settled before moving")
            for table, status in (
                ("production_orders", "processing"),
                ("breakthrough_sessions", "preparing"),
                ("travel_sessions", "running"),
            ):
                occupied = connection.execute(
                    f"SELECT 1 FROM {table} WHERE player_id = ? AND status = ? LIMIT 1",
                    (row["id"], status),
                ).fetchone()
                if occupied is not None:
                    raise CultivationBusyError("another action must be settled before moving")
            exploration = connection.execute(
                "SELECT 1 FROM exploration_sessions WHERE player_id = ? AND status IN ('created', 'running', 'combat_pending') LIMIT 1",
                (row["id"],),
            ).fetchone()
            if exploration is not None:
                raise CultivationBusyError("exploration must be settled before moving")
            retreat = connection.execute(
                "SELECT 1 FROM retreat_sessions WHERE player_id = ? AND status = 'running' LIMIT 1",
                (row["id"],),
            ).fetchone()
            if retreat is not None:
                raise CultivationBusyError("retreat must be settled before moving")
            weakness_until = row["weakness_until"]
            if weakness_until and now < datetime.fromisoformat(str(weakness_until)):
                raise WeaknessActiveError("breakthrough weakness blocks travel")
            if destination == SPIRIT_FIELD_LOCATION and current not in {
                "xuantian.new_town",
                "xuantian.outskirts",
            }:
                raise LocationRequirementError("spirit field can only be entered from the starting area")
            changed = current != destination
            cost = TRAVEL_COSTS[destination] if changed else 0
            stamina = player_integer(row, "stamina")
            if changed and stamina < cost:
                raise ResourceInsufficientError("stamina is insufficient")
            if changed:
                stamina -= cost
                change_player_state(
                    connection,
                    row,
                    updated_at=serialize_datetime(now),
                    value_delta={"stamina": stamina - player_integer(row, "stamina")},
                    player_values={"location_key": destination},
                )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (row["id"],)).fetchone()
            if updated is None:
                raise RuntimeError("travel returned no row")
            player = self._row_to_player(updated)
            payload = {"player": self._player_payload(player), "changed": changed, "stamina_cost": cost}
            connection.execute(
                """
                INSERT INTO operations(
                    operation_id, operation_name, player_id, request_hash, result_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    operation_id,
                    "world.travel_intro",
                    row["id"],
                    request_hash,
                    json.dumps(payload, ensure_ascii=False, sort_keys=True),
                    serialize_datetime(now),
                ),
            )
            if changed:
                record_location_discovery(
                    connection,
                    player_id=int(row["id"]),
                    location_key=destination,
                    operation_id=operation_id,
                    occurred_at=now,
                    snapshot={"source": "world.travel_intro", "destination": destination},
                    content=self.content,
                )
            return TravelRecord(player=player, destination=destination, changed=changed, stamina_cost=cost)


    async def rename_player(
        self,
        *,
        platform: str,
        platform_user_id: str,
        dao_name: str,
        operation_id: str,
    ) -> RenameRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._rename_player_sync,
                platform,
                platform_user_id,
                dao_name,
                operation_id,
            )

    def _rename_player_sync(
        self,
        platform: str,
        platform_user_id: str,
        dao_name: str,
        operation_id: str,
    ) -> RenameRecord:
        last_error: Exception | None = None
        for attempt in range(5):
            try:
                return self._rename_player_once(
                    platform,
                    platform_user_id,
                    dao_name,
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

    def _rename_player_once(
        self,
        platform: str,
        platform_user_id: str,
        dao_name: str,
        operation_id: str,
    ) -> RenameRecord:
        operation_payload = {
            "platform": platform,
            "platform_user_id": platform_user_id,
            "dao_name": dao_name,
        }
        request_hash = self._request_hash("player.rename", operation_payload)
        now = self._now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing_operation = connection.execute(
                "SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            if existing_operation is not None:
                if (
                    existing_operation["operation_name"] != "player.rename"
                    or existing_operation["request_hash"] != request_hash
                ):
                    raise OperationConflictError("operation input differs from its original request")
                payload = json.loads(existing_operation["result_json"])
                return RenameRecord(
                    player=self._row_to_player(payload["player"]),
                    changed=bool(payload.get("changed", False)),
                    already_completed=True,
                )

            row = self._require_player(connection, platform, platform_user_id)

            current_name = str(row["dao_name"] or "")
            if current_name:
                if current_name != dao_name:
                    raise RenameCardRequiredError("rename card is required")
                player = self._row_to_player(row)
                changed = False
            else:
                taken = connection.execute(
                    "SELECT 1 FROM players WHERE dao_name = ? AND id <> ? LIMIT 1",
                    (dao_name, row["id"]),
                ).fetchone()
                if taken is not None:
                    raise DaoNameTakenError("dao name is already used")
                change_player_state(
                    connection,
                    row,
                    updated_at=serialize_datetime(now),
                    player_values={"dao_name": dao_name},
                )
                updated = connection.execute(
                    "SELECT * FROM players WHERE id = ?", (row["id"],)
                ).fetchone()
                if updated is None:
                    raise RuntimeError("player rename returned no row")
                player = self._row_to_player(updated)
                changed = True

            payload = {"changed": changed, "player": self._player_payload(player)}
            connection.execute(
                """
                INSERT INTO operations(
                    operation_id, operation_name, player_id, request_hash, result_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    operation_id,
                    "player.rename",
                    row["id"],
                    request_hash,
                    json.dumps(payload, ensure_ascii=False, sort_keys=True),
                    serialize_datetime(now),
                ),
            )
            return RenameRecord(player=player, changed=changed, already_completed=False)


    async def get_player(self, *, platform: str, platform_user_id: str) -> PlayerView | None:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._get_player_sync, platform, platform_user_id)

    def _get_player_sync(self, platform: str, platform_user_id: str) -> PlayerView | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM players WHERE platform = ? AND platform_user_id = ?",
                (platform, platform_user_id),
            ).fetchone()
            if row is None:
                return None
            if str(row["realm_key"]) == "soul_transformation" and player_integer(row, "domain_charge_max") > 0:
                business_date = self._now().date().isoformat()
                if str(row["domain_charge_reset_date"] or "") != business_date:
                    change_player_state(
                        connection,
                        row,
                        updated_at=serialize_datetime(self._now()),
                        player_values={
                            "domain_charge": player_integer(row, "domain_charge_max"),
                            "domain_charge_reset_date": business_date,
                        },
                    )
                    row = connection.execute("SELECT * FROM players WHERE id = ?", (row["id"],)).fetchone()
            if row["domain_crack_until"]:
                try:
                    if self._now() >= datetime.fromisoformat(str(row["domain_crack_until"])):
                        change_player_state(
                            connection,
                            row,
                            updated_at=serialize_datetime(self._now()),
                            player_values={"domain_crack_until": None},
                        )
                        row = connection.execute("SELECT * FROM players WHERE id = ?", (row["id"],)).fetchone()
                except ValueError:
                    pass
            reputation = connection.execute(
                "SELECT local_json FROM player_reputations WHERE player_id = ?", (row["id"],)
            ).fetchone()
        player = self._row_to_player(row)
        if reputation is not None:
            faction = dict(player.faction_reputation)
            for key, value in self._json_object(reputation["local_json"], {}).items():
                if str(key).startswith("faction."):
                    faction[str(key).split(".", 1)[1]] = int(value)
            player = replace(player, faction_reputation=faction)
        return player

    @staticmethod
    def _json_object(raw: Any, default: dict[str, Any]) -> dict[str, Any]:
        return json_object(raw, default)

    @staticmethod
    def _row_to_player(row: sqlite3.Row | dict[str, Any]) -> PlayerView:
        normalized = player_values(row)
        qualification = normalized["qualification"]
        inventory = normalized["inventory"]
        intro_state = {"flags": normalized["intro_flags"]}
        return PlayerView(
            player_id=normalized["player_id"],
            platform=normalized["platform"],
            platform_user_id=normalized["platform_user_id"],
            scene_id=normalized["scene_id"],
            nickname=normalized["nickname"],
            dao_name=normalized["dao_name"],
            stage=normalized["stage"] or STAGE_NEW_USER,
            spirit_stones=normalized["spirit_stones"],
            qualification={str(key): int(value) for key, value in qualification.items()},
            created_at=datetime.fromisoformat(str(player_field(row, "created_at"))),
            updated_at=datetime.fromisoformat(str(player_field(row, "updated_at"))),
            status=normalized["status"],
            location_key=normalized["location_key"],
            path_key=player_field(row, "path_key"),
            subprofession_key=player_field(row, "subprofession_key"),
            stamina=normalized["stamina"],
            stamina_max=normalized["stamina_max"],
            energy=normalized["energy"],
            energy_max=normalized["energy_max"],
            inventory={str(key): int(item) for key, item in inventory.items()},
            durability={
                str(key): int(item)
                for key, item in json_object(player_field(row, "durability_json", "{}"), {}).items()
            },
            intro_flags=tuple(str(item) for item in intro_state.get("flags", [])),
            selected_service=normalized["selected_service"],
            realm_key=normalized["realm_key"],
            realm_layer=normalized["realm_layer"],
            cultivation=normalized["cultivation"],
            total_cultivation=normalized["total_cultivation"],
            foundation_quality=normalized["foundation_quality"],
            world_merit=normalized["world_merit"],
            void_merit=normalized["void_merit"],
            alliance_points=normalized["alliance_points"],
            arena_rating=normalized["arena_rating"],
            arena_wins=normalized["arena_wins"],
            arena_losses=normalized["arena_losses"],
            arena_draws=normalized["arena_draws"],
            talent_points=normalized["talent_points"],
            skill_insights=normalized["skill_insights"],
            weakness_until=(
                datetime.fromisoformat(str(player_field(row, "weakness_until")))
                if player_field(row, "weakness_until")
                else None
            ),
            battle_defeat_until=(
                datetime.fromisoformat(str(player_field(row, "battle_defeat_until")))
                if player_field(row, "battle_defeat_until")
                else None
            ),
            breakthrough_pity_bp=normalized["breakthrough_pity_bp"],
            soul_power=normalized["soul_power"],
            soul_power_max=normalized["soul_power_max"],
            domain_charge=normalized["domain_charge"],
            domain_charge_max=normalized["domain_charge_max"],
            pollution=normalized["pollution"],
            bloodline_stability=normalized["bloodline_stability"],
            cross_realm_penalty_bp=normalized["cross_realm_penalty_bp"],
            soul_fatigue_until=(
                datetime.fromisoformat(str(player_field(row, "soul_fatigue_until")))
                if player_field(row, "soul_fatigue_until")
                else None
            ),
            heart_demon_bonus_bp=normalized["heart_demon_bonus_bp"],
            max_hp=normalized["max_hp"],
            max_mp=normalized["max_mp"],
            carry_capacity=normalized["carry_capacity"],
            exploration_efficiency_bp=normalized["exploration_efficiency_bp"],
            domain_key=normalized["domain_key"],
            domain_power=normalized["domain_power"],
            realm_resistance_bp=normalized["realm_resistance_bp"],
            domain_crack_until=(
                datetime.fromisoformat(str(player_field(row, "domain_crack_until")))
                if player_field(row, "domain_crack_until") else None
            ),
            initiative=normalized["initiative"],
            faction_reputation=player_reputation(row),
            domain_level=normalized["domain_level"],
            void_power=normalized["void_power"],
            void_power_max=normalized["void_power_max"],
            space_resistance_bp=normalized["space_resistance_bp"],
            void_instability_until=(
                datetime.fromisoformat(str(player_field(row, "void_instability_until")))
                if player_field(row, "void_instability_until") else None
            ),
            void_route_count=normalized["void_route_count"],
            void_anchor_capacity=normalized["void_anchor_capacity"],
            dao_fruit_progress=normalized["dao_fruit_progress"],
            ascension_merit=normalized["ascension_merit"],
            tribulation_debt=normalized["tribulation_debt"],
            dao_fruit_key=normalized["dao_fruit_key"],
            endgame_status=normalized["endgame_status"],
            ending_key=normalized["ending_key"],
        )

    @staticmethod
    def _player_payload(player: PlayerView) -> dict[str, Any]:
        return {
            "id": player.player_id,
            "player_id": player.player_id,
            "platform": player.platform,
            "platform_user_id": player.platform_user_id,
            "scene_id": player.scene_id,
            "nickname": player.nickname,
            "dao_name": player.dao_name,
            "stage": player.stage,
            "spirit_stones": player.spirit_stones,
            "void_merit": player.void_merit,
            "alliance_points": player.alliance_points,
            "qualification_json": json.dumps(player.qualification, ensure_ascii=False, sort_keys=True),
            "created_at": serialize_datetime(player.created_at),
            "updated_at": serialize_datetime(player.updated_at),
            "status": player.status,
            "location_key": player.location_key,
            "path_key": player.path_key,
            "subprofession_key": player.subprofession_key,
            "stamina": player.stamina,
            "stamina_max": player.stamina_max,
            "energy": player.energy,
            "energy_max": player.energy_max,
            "inventory_json": inventory_json(player.inventory),
            "durability_json": json.dumps(player.durability, ensure_ascii=False, sort_keys=True),
            "intro_json": json.dumps(
                {"flags": list(player.intro_flags), "selected_service": player.selected_service},
                ensure_ascii=False,
                sort_keys=True,
            ),
            "selected_service": player.selected_service,
            "realm_key": player.realm_key,
            "realm_layer": player.realm_layer,
            "cultivation": player.cultivation,
            "total_cultivation": player.total_cultivation,
            "foundation_quality": player.foundation_quality,
            "world_merit": player.world_merit,
            "arena_rating": player.arena_rating,
            "arena_wins": player.arena_wins,
            "arena_losses": player.arena_losses,
            "arena_draws": player.arena_draws,
            "talent_points": player.talent_points,
            "skill_insights": player.skill_insights,
            "weakness_until": serialize_datetime(player.weakness_until) if player.weakness_until else None,
            "battle_defeat_until": serialize_datetime(player.battle_defeat_until) if player.battle_defeat_until else None,
            "breakthrough_pity_bp": player.breakthrough_pity_bp,
            "soul_power": player.soul_power,
            "soul_power_max": player.soul_power_max,
            "domain_charge": player.domain_charge,
            "domain_charge_max": player.domain_charge_max,
            "pollution": player.pollution,
            "bloodline_stability": player.bloodline_stability,
            "cross_realm_penalty_bp": player.cross_realm_penalty_bp,
            "soul_fatigue_until": serialize_datetime(player.soul_fatigue_until) if player.soul_fatigue_until else None,
            "heart_demon_bonus_bp": player.heart_demon_bonus_bp,
            "max_hp": player.max_hp,
            "max_mp": player.max_mp,
            "carry_capacity": player.carry_capacity,
            "exploration_efficiency_bp": player.exploration_efficiency_bp,
            "domain_key": player.domain_key,
            "domain_power": player.domain_power,
            "realm_resistance_bp": player.realm_resistance_bp,
            "domain_crack_until": serialize_datetime(player.domain_crack_until) if player.domain_crack_until else None,
            "initiative": player.initiative,
            "faction_reputation_json": json.dumps(player.faction_reputation, ensure_ascii=False, sort_keys=True),
            "domain_level": player.domain_level,
            "void_power": player.void_power,
            "void_power_max": player.void_power_max,
            "space_resistance_bp": player.space_resistance_bp,
            "void_instability_until": serialize_datetime(player.void_instability_until) if player.void_instability_until else None,
            "void_route_count": player.void_route_count,
            "void_anchor_capacity": player.void_anchor_capacity,
            "dao_fruit_progress": player.dao_fruit_progress,
            "ascension_merit": player.ascension_merit,
            "tribulation_debt": player.tribulation_debt,
            "dao_fruit_key": player.dao_fruit_key,
            "endgame_status": player.endgame_status,
            "ending_key": player.ending_key,
        }
