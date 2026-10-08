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
from ..specials.codex_projection import record_codex_discovery, record_material_discoveries
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
from ..utils.assets import grant_player_assets
from ..utils.json_cache import decode_json_strict
from ..utils.player import change_player_state, player_integer, player_inventory


_CULTIVATION_SNAPSHOT_FIELDS = {
    "realm_key",
    "realm_layer",
    "qualification",
    "location_key",
    "mode_key",
    "mode_label",
    "requested_mode_key",
    "requested_mode_reference",
    "duration_seconds",
    "stamina_cost",
    "energy_cost",
    "state_bp",
    "state_bonus_bp",
    "pending_state_bonus_bp",
    "base_cultivation",
    "environment_bp",
    "manual_cultivation_gain_bp",
    "soul_power_gain",
    "soul_power_max",
    "start_player_fingerprint",
}
_CULTIVATION_QUALIFICATION_FIELDS = {
    "body",
    "spirit",
    "insight",
    "root",
    "agility",
    "fortune",
}
_CULTIVATION_START_RESULT_FIELDS = {
    "player",
    "session_id",
    "mode_key",
    "mode_label",
    "duration_seconds",
    "status",
    "starts_at",
    "ends_at",
    "stamina_cost",
    "energy_cost",
    "state_bp",
    "state_bonus_bp",
    "snapshot_fingerprint",
}
_CULTIVATION_SETTLEMENT_RESULT_FIELDS = {
    "player",
    "session_id",
    "cultivation_gain",
    "soul_power_gain",
    "mode_key",
    "mode_label",
}
_CULTIVATION_CANCEL_RESULT_FIELDS = {
    "player",
    "session_id",
    "stamina_refund",
    "energy_refund",
}


def _strict_progression_object(raw_value: Any, label: str) -> dict[str, Any]:
    try:
        value = decode_json_strict(raw_value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _require_progression_integer(value: Any, label: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ValueError(f"{label} must be an integer of at least {minimum}")
    return value


class CultivationRepositoryMixin:
    @staticmethod
    def _validate_cultivation_snapshot_fields(
        snapshot: dict[str, Any], *, allow_unbound_start: bool = False
    ) -> None:
        expected_fields = _CULTIVATION_SNAPSHOT_FIELDS
        if allow_unbound_start:
            expected_fields = expected_fields - {"start_player_fingerprint"}
        if set(snapshot) != expected_fields:
            raise ValueError("cultivation snapshot fields are invalid")
        for key in (
            "realm_key",
            "location_key",
            "mode_key",
            "mode_label",
            "requested_mode_key",
        ):
            if not isinstance(snapshot[key], str) or not snapshot[key]:
                raise ValueError(f"cultivation snapshot {key} is invalid")
        if not isinstance(snapshot["requested_mode_reference"], str):
            raise ValueError("cultivation snapshot requested mode reference is invalid")
        if not allow_unbound_start and (
            not isinstance(snapshot["start_player_fingerprint"], str)
            or len(snapshot["start_player_fingerprint"]) != 64
        ):
            raise ValueError("cultivation start player fingerprint is invalid")
        _require_progression_integer(snapshot["realm_layer"], "cultivation realm layer", minimum=1)
        qualification = snapshot["qualification"]
        if (
            not isinstance(qualification, dict)
            or set(qualification) != _CULTIVATION_QUALIFICATION_FIELDS
            or any(type(value) is not int or value < 0 for value in qualification.values())
        ):
            raise ValueError("cultivation snapshot qualification is invalid")
        for key in (
            "duration_seconds",
            "stamina_cost",
            "state_bp",
            "base_cultivation",
            "environment_bp",
        ):
            _require_progression_integer(snapshot[key], f"cultivation snapshot {key}", minimum=1)
        for key in (
            "energy_cost",
            "state_bonus_bp",
            "pending_state_bonus_bp",
            "manual_cultivation_gain_bp",
            "soul_power_gain",
            "soul_power_max",
        ):
            _require_progression_integer(snapshot[key], f"cultivation snapshot {key}")
        if (
            snapshot["state_bonus_bp"] != snapshot["pending_state_bonus_bp"]
            or snapshot["soul_power_gain"] > snapshot["soul_power_max"]
        ):
            raise ValueError("cultivation snapshot values are inconsistent")

    def _cultivation_result_player(
        self, payload: dict[str, Any], platform: str, platform_user_id: str
    ) -> PlayerView:
        player = payload.get("player")
        if (
            not isinstance(player, dict)
            or player.get("platform") != platform
            or player.get("platform_user_id") != platform_user_id
            or not isinstance(player.get("id"), str)
            or not player.get("id")
            or player.get("id") != player.get("player_id")
        ):
            raise ValueError("cultivation operation player does not match its request")
        for key in (
            "qualification_json",
            "inventory_json",
            "durability_json",
            "intro_json",
            "faction_reputation_json",
        ):
            if key in player:
                _strict_progression_object(player[key], f"cultivation operation player {key}")
        return self._row_to_player(player)

    def _cultivation_operation_result(
        self,
        connection: sqlite3.Connection,
        operation: sqlite3.Row,
        platform: str,
        platform_user_id: str,
        expected_name: str,
        expected_fields: set[str],
    ) -> tuple[dict[str, Any], PlayerView]:
        if operation["operation_name"] != expected_name:
            raise ValueError("cultivation operation name is invalid")
        payload = _strict_progression_object(operation["result_json"], "cultivation operation result")
        if set(payload) != expected_fields:
            raise ValueError("cultivation operation result fields are invalid")
        player = self._cultivation_result_player(payload, platform, platform_user_id)
        owner = connection.execute(
            "SELECT player_id, platform, platform_user_id FROM players WHERE id = ?",
            (operation["player_id"],),
        ).fetchone()
        if (
            owner is None
            or owner["player_id"] != player.player_id
            or owner["platform"] != platform
            or owner["platform_user_id"] != platform_user_id
        ):
            raise ValueError("cultivation operation player id is invalid")
        return payload, player

    @staticmethod
    def _cultivation_session_result(
        raw_value: Any, status: str
    ) -> tuple[dict[str, Any], bool]:
        result = _strict_progression_object(raw_value, "cultivation session result")
        if status == "running":
            if result:
                raise ValueError("running cultivation result must be empty")
            return result, False
        if status == "settled":
            if set(result) != {
                "cultivation_gain",
                "soul_power_gain",
                "terminal_operation_id",
                "operation_result_fingerprint",
            }:
                raise ValueError("settled cultivation result fields are invalid")
            _require_progression_integer(result["cultivation_gain"], "cultivation gain")
            _require_progression_integer(result["soul_power_gain"], "soul power gain")
            if not isinstance(result["terminal_operation_id"], str) or not result["terminal_operation_id"]:
                raise ValueError("settled cultivation operation id is invalid")
            if not isinstance(result["operation_result_fingerprint"], str) or len(result["operation_result_fingerprint"]) != 64:
                raise ValueError("settled cultivation result fingerprint is invalid")
            return result, True
        if status == "cancelled":
            if set(result) != {
                "stamina_refund",
                "energy_refund",
                "terminal_operation_id",
                "operation_result_fingerprint",
            }:
                raise ValueError("cancelled cultivation result fields are invalid")
            _require_progression_integer(result["stamina_refund"], "stamina refund")
            _require_progression_integer(result["energy_refund"], "energy refund")
            if not isinstance(result["terminal_operation_id"], str) or not result["terminal_operation_id"]:
                raise ValueError("cancelled cultivation operation id is invalid")
            if not isinstance(result["operation_result_fingerprint"], str) or len(result["operation_result_fingerprint"]) != 64:
                raise ValueError("cancelled cultivation result fingerprint is invalid")
            return result, True
        if status != "expired":
            raise ValueError("cultivation session state is invalid")
        if set(result) == {"expired_at", "recovery_pending"}:
            if result["recovery_pending"] is not True or not isinstance(result["expired_at"], str):
                raise ValueError("expired cultivation result is invalid")
            try:
                expired_at = datetime.fromisoformat(result["expired_at"])
            except ValueError as exc:
                raise ValueError("expired cultivation result time is invalid") from exc
            if expired_at.tzinfo is None:
                raise ValueError("expired cultivation result time must include a timezone")
            return result, False
        if set(result) == {
            "cultivation_gain",
            "soul_power_gain",
            "recovered_after_expiry",
            "terminal_operation_id",
            "operation_result_fingerprint",
        }:
            _require_progression_integer(result["cultivation_gain"], "cultivation gain")
            _require_progression_integer(result["soul_power_gain"], "soul power gain")
            if result["recovered_after_expiry"] is not True:
                raise ValueError("recovered cultivation result is invalid")
            if not isinstance(result["terminal_operation_id"], str) or not result["terminal_operation_id"]:
                raise ValueError("recovered cultivation operation id is invalid")
            if not isinstance(result["operation_result_fingerprint"], str) or len(result["operation_result_fingerprint"]) != 64:
                raise ValueError("recovered cultivation result fingerprint is invalid")
            return result, True
        raise ValueError("expired cultivation result fields are invalid")

    def _cultivation_terminal_operation(
        self,
        connection: sqlite3.Connection,
        session: sqlite3.Row,
        snapshot: dict[str, Any],
        result: dict[str, Any],
        status: str,
        platform: str,
        platform_user_id: str,
    ) -> None:
        if status == "settled":
            operation_name = "progression.settle_cultivation"
            fingerprint_name = "progression.settle_cultivation.result"
            expected_fields = _CULTIVATION_SETTLEMENT_RESULT_FIELDS
        elif status == "cancelled":
            operation_name = "progression.cancel_cultivation"
            fingerprint_name = "progression.cancel_cultivation.result"
            expected_fields = _CULTIVATION_CANCEL_RESULT_FIELDS
        elif status == "expired" and result.get("recovered_after_expiry") is True:
            operation_name = "progression.recover_cultivation"
            fingerprint_name = "progression.recover_cultivation.result"
            expected_fields = _CULTIVATION_SETTLEMENT_RESULT_FIELDS
        else:
            return
        operation_id = result.get("terminal_operation_id")
        if not isinstance(operation_id, str) or not operation_id:
            raise ValueError("cultivation terminal operation id is invalid")
        operation = connection.execute(
            "SELECT operation_name, player_id, request_hash, result_json FROM operations WHERE operation_id = ?",
            (operation_id,),
        ).fetchone()
        if (
            operation is None
            or operation["player_id"] != session["player_id"]
            or operation["request_hash"]
            != self._request_hash(
                operation_name,
                {"platform": platform, "platform_user_id": platform_user_id},
            )
        ):
            raise ValueError("cultivation terminal operation does not match its session")
        payload, _ = self._cultivation_operation_result(
            connection,
            operation,
            platform,
            platform_user_id,
            operation_name,
            expected_fields,
        )
        if payload.get("session_id") != str(session["session_id"]):
            raise ValueError("cultivation terminal operation session is invalid")
        if status == "cancelled":
            _require_progression_integer(payload["stamina_refund"], "stamina refund")
            _require_progression_integer(payload["energy_refund"], "energy refund")
            if (
                payload["stamina_refund"] != result["stamina_refund"]
                or payload["energy_refund"] != result["energy_refund"]
                or payload["stamina_refund"] != snapshot["stamina_cost"]
                or payload["energy_refund"] != snapshot["energy_cost"]
            ):
                raise ValueError("cultivation cancellation result does not match its operation")
        else:
            _require_progression_integer(payload["cultivation_gain"], "cultivation gain")
            _require_progression_integer(payload["soul_power_gain"], "soul power gain")
            if (
                payload["cultivation_gain"] != result["cultivation_gain"]
                or payload["soul_power_gain"] != result["soul_power_gain"]
                or payload["mode_key"] != snapshot["mode_key"]
                or payload["mode_label"] != snapshot["mode_label"]
            ):
                raise ValueError("cultivation settlement result does not match its operation")
        if result["operation_result_fingerprint"] != self._request_hash(fingerprint_name, payload):
            raise ValueError("cultivation terminal result fingerprint is invalid")

    def _cultivation_expiry_operation(
        self,
        connection: sqlite3.Connection,
        session: sqlite3.Row,
        platform: str,
        platform_user_id: str,
    ) -> None:
        operation_id = f"progression.expire_cultivation:{session['session_id']}"
        request_payload = {
            "platform": platform,
            "platform_user_id": platform_user_id,
            "session_id": str(session["session_id"]),
        }
        operation = connection.execute(
            "SELECT operation_name, player_id, request_hash, result_json FROM operations WHERE operation_id = ?",
            (operation_id,),
        ).fetchone()
        if (
            operation is None
            or operation["operation_name"] != "progression.expire_cultivation"
            or operation["player_id"] != session["player_id"]
            or operation["request_hash"]
            != self._request_hash("progression.expire_cultivation", request_payload)
        ):
            raise ValueError("cultivation expiry operation does not match its session")
        result = _strict_progression_object(operation["result_json"], "cultivation expiry operation")
        if result != {"session_id": str(session["session_id"]), "status": "expired"}:
            raise ValueError("cultivation expiry operation result is invalid")

    def _record_cultivation_expiry(
        self,
        connection: sqlite3.Connection,
        session: sqlite3.Row,
        platform: str,
        platform_user_id: str,
        created_at: str,
    ) -> None:
        request_payload = {
            "platform": platform,
            "platform_user_id": platform_user_id,
            "session_id": str(session["session_id"]),
        }
        connection.execute(
            "INSERT OR IGNORE INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (
                f"progression.expire_cultivation:{session['session_id']}",
                "progression.expire_cultivation",
                session["player_id"],
                self._request_hash("progression.expire_cultivation", request_payload),
                json.dumps(
                    {"session_id": session["session_id"], "status": "expired"},
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                created_at,
            ),
        )
        self._cultivation_expiry_operation(connection, session, platform, platform_user_id)

    def _cultivation_snapshot(
        self, connection: sqlite3.Connection, session: sqlite3.Row
    ) -> dict[str, Any]:
        snapshot = _strict_progression_object(session["snapshot_json"], "cultivation snapshot")
        self._validate_cultivation_snapshot_fields(snapshot)

        operation = connection.execute(
            "SELECT operation_name, player_id, request_hash, result_json FROM operations WHERE operation_id = ?",
            (session["operation_id"],),
        ).fetchone()
        if (
            operation is None
            or operation["operation_name"] != "progression.start_cultivation"
            or operation["player_id"] != session["player_id"]
        ):
            raise ValueError("cultivation start operation does not match its session")
        start = _strict_progression_object(operation["result_json"], "cultivation start operation")
        if set(start) != _CULTIVATION_START_RESULT_FIELDS:
            raise ValueError("cultivation start operation fields are invalid")
        for key in ("session_id", "mode_key", "mode_label", "status", "starts_at", "ends_at", "snapshot_fingerprint"):
            if not isinstance(start[key], str) or not start[key]:
                raise ValueError(f"cultivation start operation {key} is invalid")
        if start["status"] != "running" or len(start["snapshot_fingerprint"]) != 64:
            raise ValueError("cultivation start operation state is invalid")
        for key in ("duration_seconds", "stamina_cost", "energy_cost", "state_bp", "state_bonus_bp"):
            _require_progression_integer(start[key], f"cultivation start operation {key}")
        start_player = start["player"]
        if not isinstance(start_player, dict):
            raise ValueError("cultivation start operation player is invalid")
        owner = connection.execute(
            "SELECT id, player_id, platform, platform_user_id FROM players WHERE id = ?",
            (session["player_id"],),
        ).fetchone()
        start_view = self._cultivation_result_player(
            start, str(owner["platform"]) if owner is not None else "", str(owner["platform_user_id"]) if owner is not None else ""
        ) if owner is not None else None
        if (
            owner is None
            or start_view is None
            or start_view.player_id != owner["player_id"]
            or owner["id"] != session["player_id"]
            or operation["request_hash"]
            != self._request_hash(
                "progression.start_cultivation",
                {
                    "platform": owner["platform"],
                    "platform_user_id": owner["platform_user_id"],
                    "mode_key": snapshot["requested_mode_key"],
                    "mode_reference": snapshot["requested_mode_reference"],
                },
            )
            or snapshot["realm_key"] != start_player.get("realm_key")
            or snapshot["realm_layer"] != start_player.get("realm_layer")
            or snapshot["location_key"] != start_player.get("location_key")
            or snapshot["qualification"]
            != _strict_progression_object(start_player.get("qualification_json"), "cultivation start qualification")
            or snapshot["start_player_fingerprint"]
            != self._request_hash("progression.cultivation.start_player", start_player)
        ):
            raise ValueError("cultivation start operation does not match its snapshot")
        try:
            starts_at = datetime.fromisoformat(str(session["starts_at"]))
            ends_at = datetime.fromisoformat(str(session["ends_at"]))
        except ValueError as exc:
            raise ValueError("cultivation session time is invalid") from exc
        if (
            starts_at.tzinfo is None
            or ends_at.tzinfo is None
            or ends_at - starts_at != timedelta(seconds=snapshot["duration_seconds"])
            or str(session["session_id"]) != start["session_id"]
            or str(session["mode_key"]) != snapshot["mode_key"]
            or str(session["mode_key"]) != start["mode_key"]
            or str(session["starts_at"]) != start["starts_at"]
            or str(session["ends_at"]) != start["ends_at"]
            or type(session["stamina_cost"]) is not int
            or session["stamina_cost"] != snapshot["stamina_cost"]
            or start["mode_label"] != snapshot["mode_label"]
            or start["duration_seconds"] != snapshot["duration_seconds"]
            or start["stamina_cost"] != snapshot["stamina_cost"]
            or start["energy_cost"] != snapshot["energy_cost"]
            or start["state_bp"] != snapshot["state_bp"]
            or start["state_bonus_bp"] != snapshot["state_bonus_bp"]
            or start["snapshot_fingerprint"]
            != self._request_hash("progression.cultivation.snapshot", snapshot)
        ):
            raise ValueError("cultivation session and frozen snapshot do not match")
        return snapshot

    async def enter_cultivation(
        self,
        *,
        platform: str,
        platform_user_id: str,
        path_key: str,
        subprofession_key: str | None,
        request_args: tuple[str, ...],
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
                request_args,
                operation_id,
            )

    async def replay_cultivation_entry(
        self,
        *,
        platform: str,
        platform_user_id: str,
        path_key: str | None,
        subprofession_key: str | None,
        request_args: tuple[str, ...],
        operation_id: str,
    ) -> CultivationRecord | None:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._replay_cultivation_entry,
                platform,
                platform_user_id,
                path_key,
                subprofession_key,
                request_args,
                operation_id,
            )

    def _replay_cultivation_entry(
        self,
        platform: str,
        platform_user_id: str,
        path_key: str | None,
        subprofession_key: str | None,
        request_args: tuple[str, ...],
        operation_id: str,
    ) -> CultivationRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT o.operation_name, o.request_hash, o.result_json,
                       p.platform, p.platform_user_id
                FROM operations AS o
                LEFT JOIN players AS p ON p.id = o.player_id
                WHERE o.operation_id = ?
                """,
                (operation_id,),
            ).fetchone()
            if row is None:
                return None
            if (
                row["operation_name"] != "player.enter_cultivation"
                or row["platform"] != platform
                or row["platform_user_id"] != platform_user_id
            ):
                raise OperationConflictError("operation input differs from its original request")
            payload, record = self._decode_cultivation_entry_result(row["result_json"])

            matches_current_key = False
            if path_key is not None:
                request_hash = self._request_hash(
                    "player.enter_cultivation",
                    {
                        "platform": platform,
                        "platform_user_id": platform_user_id,
                        "path_key": path_key,
                        "subprofession_key": subprofession_key,
                    },
                )
                matches_current_key = row["request_hash"] == request_hash
            if not matches_current_key and payload["request_args"] != list(request_args):
                raise OperationConflictError("operation input differs from its original request")
            return record

    def _decode_cultivation_entry_result(
        self, result_json: str
    ) -> tuple[dict[str, Any], CultivationRecord]:
        try:
            payload = decode_json_strict(result_json)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise OperationResultMalformedError("cultivation entry result is malformed") from exc
        if (
            not isinstance(payload, dict)
            or not isinstance(payload.get("player"), dict)
            or not isinstance(payload.get("changed"), bool)
        ):
            raise OperationResultMalformedError("cultivation entry result is incomplete")
        request_args = payload.get("request_args")
        if not isinstance(request_args, list) or any(
            not isinstance(value, str) for value in request_args
        ):
            raise OperationResultMalformedError("cultivation entry selectors are malformed")
        player = self._row_to_player(payload["player"])
        if not player.path_key:
            raise OperationResultMalformedError("cultivation entry result has no path")
        return payload, CultivationRecord(
            player=player,
            path_key=player.path_key,
            subprofession_key=player.subprofession_key,
            changed=payload["changed"],
            already_completed=True,
        )

    def _enter_cultivation_sync(
        self,
        platform: str,
        platform_user_id: str,
        path_key: str,
        subprofession_key: str | None,
        request_args: tuple[str, ...],
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
                    request_args,
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
        request_args: tuple[str, ...],
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
        now = self._now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing_operation = connection.execute(
                "SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            if existing_operation is not None:
                if existing_operation["operation_name"] != "player.enter_cultivation":
                    raise OperationConflictError("operation input differs from its original request")
                payload, replay = self._decode_cultivation_entry_result(
                    existing_operation["result_json"]
                )
                if (
                    existing_operation["request_hash"] != request_hash
                    and payload["request_args"] != list(request_args)
                ):
                    raise OperationConflictError("operation input differs from its original request")
                return replay

            row = self._require_player(connection, platform, platform_user_id)
            if row["stage"] != "seeker":
                raise PlayerStageConflictError("player is not ready to enter cultivation")
            if row["path_key"]:
                raise PathAlreadySelectedError("path is already selected")
            if path_key == "support" and not subprofession_key:
                raise SubprofessionRequiredError("support path needs a sub-profession")

            reward = {
                "spirit_stones": 200,
                **{
                    item_key: quantity
                    for item_key, quantity in reward_items(path_key, subprofession_key, self.content)
                },
            }
            grant_player_assets(
                connection,
                row,
                reward,
                serialize_datetime(now),
                player_values={
                    "stage": "cultivator",
                    "path_key": path_key,
                    "subprofession_key": subprofession_key,
                    "realm_key": "qi_sensing",
                    "realm_layer": 1,
                    "cultivation": 0,
                    "total_cultivation": 0,
                },
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (row["id"],)).fetchone()
            if updated is None:
                raise RuntimeError("cultivation entry returned no row")
            player = self._row_to_player(updated)
            payload = {
                "player": self._player_payload(player),
                "changed": True,
                "request_args": list(request_args),
            }
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
            record_codex_discovery(
                connection,
                player_id=int(row["id"]),
                entry_key=f"codex.path.{path_key}",
                operation_id=operation_id,
                occurred_at=now,
                snapshot={"source": "player.enter_cultivation", "path_key": path_key},
            )
            record_material_discoveries(
                connection,
                player_id=int(row["id"]),
                operation_id=operation_id,
                occurred_at=now,
                reward={
                    key: quantity
                    for key, quantity in reward_items(path_key, subprofession_key, self.content)
                },
                snapshot={"source": "player.enter_cultivation", "path_key": path_key},
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
        mode_reference: str | None = None,
        operation_id: str,
    ) -> CultivationSessionRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._start_cultivation_sync,
                platform,
                platform_user_id,
                mode_key,
                mode_reference,
                operation_id,
            )

    def _start_cultivation_sync(
        self,
        platform: str,
        platform_user_id: str,
        mode_key: str,
        mode_reference: str | None,
        operation_id: str,
    ) -> CultivationSessionRecord:
        last_error: Exception | None = None
        for attempt in range(5):
            try:
                return self._start_cultivation_once(platform, platform_user_id, mode_key, mode_reference, operation_id)
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
        mode_reference: str | None,
        operation_id: str,
    ) -> CultivationSessionRecord:
        from ..progression.rules import cultivation_mode, formal_realms, resolve_cultivation_mode
        from ..items.manual_rules import manual_effect_totals

        operation_payload = {
            "platform": platform,
            "platform_user_id": platform_user_id,
            "mode_key": mode_key,
            "mode_reference": mode_reference if mode_reference is not None else "",
        }
        request_hash = self._request_hash("progression.start_cultivation", operation_payload)
        now = self._now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing_operation = connection.execute(
                "SELECT operation_name, player_id, request_hash, result_json FROM operations WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            if existing_operation is not None:
                if (
                    existing_operation["operation_name"] != "progression.start_cultivation"
                    or existing_operation["request_hash"] != request_hash
                ):
                    raise OperationConflictError("operation input differs from its original request")
                payload, _ = self._cultivation_operation_result(
                    connection,
                    existing_operation,
                    platform,
                    platform_user_id,
                    "progression.start_cultivation",
                    _CULTIVATION_START_RESULT_FIELDS,
                )
                _require_progression_integer(payload["duration_seconds"], "cultivation duration", minimum=1)
                _require_progression_integer(payload["stamina_cost"], "cultivation stamina cost", minimum=1)
                _require_progression_integer(payload["energy_cost"], "cultivation energy cost")
                _require_progression_integer(payload["state_bp"], "cultivation state")
                _require_progression_integer(payload["state_bonus_bp"], "cultivation state bonus")
                if payload["status"] != "running":
                    raise ValueError("cultivation start operation status is invalid")
                session = connection.execute(
                    "SELECT * FROM cultivation_sessions WHERE operation_id = ?",
                    (operation_id,),
                ).fetchone()
                if session is None or str(session["session_id"]) != payload["session_id"]:
                    raise ValueError("cultivation start operation has no matching session")
                session_result, terminal = self._cultivation_session_result(
                    session["result_json"], str(session["status"])
                )
                snapshot = self._cultivation_snapshot(connection, session)
                if terminal:
                    self._cultivation_terminal_operation(
                        connection,
                        session,
                        snapshot,
                        session_result,
                        str(session["status"]),
                        platform,
                        platform_user_id,
                    )
                if session["status"] == "expired":
                    self._cultivation_expiry_operation(
                        connection, session, platform, platform_user_id
                    )
                return CultivationSessionRecord(
                    player=self._row_to_player(payload["player"]),
                    session_id=str(payload["session_id"]),
                    mode_key=str(payload["mode_key"]),
                    status=str(payload["status"]),
                    starts_at=str(payload["starts_at"]),
                    ends_at=str(payload["ends_at"]),
                    stamina_cost=int(payload["stamina_cost"]),
                    energy_cost=int(payload["energy_cost"]),
                    mode_label=str(payload["mode_label"]),
                    duration_seconds=int(payload["duration_seconds"]),
                    state_bp=int(payload["state_bp"]),
                    state_bonus_bp=int(payload["state_bonus_bp"]),
                    already_completed=True,
                )

            row = self._require_player(connection, platform, platform_user_id)
            if row["stage"] != "cultivator" or row["realm_key"] not in formal_realms(self.content):
                raise PlayerStageConflictError("player is not ready for cultivation")
            try:
                selected_mode_key = mode_key if not mode_reference else resolve_cultivation_mode(mode_reference, self.content)
                mode = cultivation_mode(selected_mode_key, self.content)
            except ValueError as exc:
                raise InvalidCultivationModeError("unsupported cultivation mode") from exc
            if mode.required_location and row["location_key"] != mode.required_location:
                raise LocationRequiredError("selected cultivation mode requires a specific location")
            if not meets_realm(
                str(row["realm_key"]),
                player_integer(row, "realm_layer"),
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
            party_battle = connection.execute(
                "SELECT 1 FROM party_battle_members WHERE player_id = ? AND asset_lock_status = 'locked' LIMIT 1",
                (row["id"],),
            ).fetchone()
            if party_battle is not None:
                raise CultivationBusyError("party battle assets are locked")
            final_battle = connection.execute(
                "SELECT 1 FROM final_battle_members WHERE player_id = ? AND asset_lock_status = 'locked' LIMIT 1",
                (row["id"],),
            ).fetchone()
            if final_battle is not None:
                raise CultivationBusyError("final battle assets are locked")
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
                "SELECT * FROM cultivation_sessions WHERE player_id = ? AND status IN ('running', 'expired') ORDER BY id DESC LIMIT 1",
                (row["id"],),
            ).fetchone()
            if pending is not None:
                self._cultivation_snapshot(connection, pending)
                _, recovered = self._cultivation_session_result(
                    pending["result_json"], str(pending["status"])
                )
                if pending["status"] == "running":
                    raise CultivationBusyError("player already has a running cultivation")
                self._cultivation_expiry_operation(
                    connection, pending, platform, platform_user_id
                )
                if not recovered:
                    raise CultivationRecoveryRequiredError("expired cultivation requires recovery")
            if mode.daily_limit is not None:
                day_start = serialize_datetime(now.replace(hour=0, minute=0, second=0, microsecond=0))
                used = connection.execute(
                    "SELECT COUNT(*) AS count FROM cultivation_sessions WHERE player_id = ? AND mode_key = ? AND starts_at >= ?",
                    (row["id"], mode.key, day_start),
                ).fetchone()
                if used is not None and int(used["count"]) >= mode.daily_limit:
                    raise CultivationDailyLimitError("cultivation mode reached its daily limit")
            if player_integer(row, "stamina") < mode.stamina_cost or player_integer(row, "energy") < mode.energy_cost:
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
            item_effects = self._json_object(row["item_effects_json"], {})
            pending_effect = item_effects.pop("pending", None)
            state_bonus_bp = 0
            if pending_effect is not None:
                if not isinstance(pending_effect, dict) or pending_effect.get("type") != "next_cultivation_state_bonus_bp":
                    raise ValueError("player has an invalid pending cultivation effect")
                raw_value = pending_effect.get("value")
                if isinstance(raw_value, bool) or not isinstance(raw_value, int) or raw_value <= 0:
                    raise ValueError("pending cultivation effect value must be positive")
                state_bonus_bp = raw_value
                state_bp += state_bonus_bp
            manual_effects = manual_effect_totals(player_inventory(row), self.content)
            snapshot = {
                "realm_key": row["realm_key"],
                "realm_layer": player_integer(row, "realm_layer"),
                "qualification": _strict_progression_object(
                    row["qualification_json"], "cultivation player qualification"
                ),
                "location_key": row["location_key"],
                "mode_key": mode.key,
                "mode_label": mode.label,
                "requested_mode_key": mode_key,
                "requested_mode_reference": mode_reference if mode_reference is not None else "",
                "duration_seconds": mode.duration_seconds,
                "stamina_cost": mode.stamina_cost,
                "energy_cost": mode.energy_cost,
                "state_bp": state_bp,
                "state_bonus_bp": state_bonus_bp,
                "pending_state_bonus_bp": state_bonus_bp,
                "base_cultivation": mode.base_cultivation,
                "environment_bp": mode.environment_bp,
                "manual_cultivation_gain_bp": int(manual_effects["cultivation_gain_bp"]),
                "soul_power_gain": mode.soul_power_gain,
                "soul_power_max": mode.soul_power_max,
            }
            self._validate_cultivation_snapshot_fields(snapshot, allow_unbound_start=True)
            change_player_state(
                connection,
                row,
                updated_at=serialize_datetime(now),
                value_delta={
                    "stamina": -mode.stamina_cost,
                    "energy": -mode.energy_cost,
                },
                player_values={
                    "soul_power_max": max(
                        player_integer(row, "soul_power_max"),
                        player_integer(row, "soul_power"),
                        mode.soul_power_max,
                    ),
                    "item_effects_json": json.dumps(item_effects, ensure_ascii=False, sort_keys=True),
                },
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (row["id"],)).fetchone()
            if updated is None:
                raise RuntimeError("cultivation start returned no player")
            player = self._row_to_player(updated)
            player_payload = self._player_payload(player)
            snapshot["start_player_fingerprint"] = self._request_hash(
                "progression.cultivation.start_player", player_payload
            )
            payload = {
                "player": player_payload,
                "session_id": session_id,
                "mode_key": mode.key,
                "mode_label": mode.label,
                "duration_seconds": mode.duration_seconds,
                "status": "running",
                "starts_at": starts_at,
                "ends_at": ends_at,
                "stamina_cost": mode.stamina_cost,
                "energy_cost": mode.energy_cost,
                "state_bp": state_bp,
                "state_bonus_bp": state_bonus_bp,
                "snapshot_fingerprint": self._request_hash("progression.cultivation.snapshot", snapshot),
            }
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
                    mode.key,
                    starts_at,
                    ends_at,
                    mode.stamina_cost,
                    json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
                    starts_at,
                    starts_at,
                ),
            )
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
                mode_label=mode.label,
                duration_seconds=mode.duration_seconds,
                state_bp=state_bp,
                state_bonus_bp=state_bonus_bp,
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
                "SELECT operation_name, player_id, request_hash, result_json FROM operations WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            if existing_operation is not None:
                if (
                    existing_operation["operation_name"] != "progression.settle_cultivation"
                    or existing_operation["request_hash"] != request_hash
                ):
                    raise OperationConflictError("operation input differs from its original request")
                payload, player = self._cultivation_operation_result(
                    connection,
                    existing_operation,
                    platform,
                    platform_user_id,
                    "progression.settle_cultivation",
                    _CULTIVATION_SETTLEMENT_RESULT_FIELDS,
                )
                _require_progression_integer(payload["cultivation_gain"], "cultivation gain")
                _require_progression_integer(payload["soul_power_gain"], "soul power gain")
                if not isinstance(payload["session_id"], str) or not payload["session_id"]:
                    raise ValueError("cultivation settlement session id is invalid")
                session = connection.execute(
                    "SELECT * FROM cultivation_sessions WHERE session_id = ? AND player_id = ?",
                    (payload["session_id"], existing_operation["player_id"]),
                ).fetchone()
                if session is None or session["status"] != "settled":
                    raise ValueError("cultivation settlement operation has no settled session")
                snapshot = self._cultivation_snapshot(connection, session)
                result, recovered = self._cultivation_session_result(session["result_json"], "settled")
                if (
                    not recovered
                    or result["terminal_operation_id"] != operation_id
                    or payload["cultivation_gain"] != result["cultivation_gain"]
                    or payload["soul_power_gain"] != result["soul_power_gain"]
                    or payload["mode_key"] != snapshot["mode_key"]
                    or payload["mode_label"] != snapshot["mode_label"]
                    or result["operation_result_fingerprint"]
                    != self._request_hash("progression.settle_cultivation.result", payload)
                ):
                    raise ValueError("cultivation settlement operation does not match its session")
                return CultivationSettlementRecord(
                    player=player,
                    session_id=str(payload["session_id"]),
                    cultivation_gain=int(payload["cultivation_gain"]),
                    mode_key=str(payload["mode_key"]),
                    soul_power_gain=int(payload["soul_power_gain"]),
                    mode_label=str(payload["mode_label"]),
                    already_completed=True,
                )

            row = self._require_player(connection, platform, platform_user_id)
            session = connection.execute(
                "SELECT * FROM cultivation_sessions WHERE player_id = ? AND status IN ('running', 'expired') ORDER BY id DESC LIMIT 1",
                (row["id"],),
            ).fetchone()
            if session is None:
                raise CultivationNotFoundError("no running cultivation")
            snapshot = self._cultivation_snapshot(connection, session)
            _, recovered = self._cultivation_session_result(
                session["result_json"], str(session["status"])
            )
            if session["status"] == "expired":
                self._cultivation_expiry_operation(connection, session, platform, platform_user_id)
                raise CultivationExpiredError("cultivation requires recovery")
            ends_at = datetime.fromisoformat(str(session["ends_at"]))
            if now < ends_at:
                raise CultivationNotReadyError("cultivation is not ready")
            if now > ends_at + timedelta(seconds=CULTIVATION_SETTLEMENT_GRACE_SECONDS):
                connection.execute(
                    "UPDATE cultivation_sessions SET status = 'expired', result_json = ?, updated_at = ? WHERE id = ?",
                    (
                        json.dumps({"expired_at": now_text, "recovery_pending": True}, ensure_ascii=False, sort_keys=True),
                        now_text,
                        session["id"],
                    ),
                )
                expired_session = connection.execute(
                    "SELECT * FROM cultivation_sessions WHERE id = ?", (session["id"],)
                ).fetchone()
                if expired_session is None:
                    raise RuntimeError("expired cultivation session was not saved")
                self._record_cultivation_expiry(
                    connection, expired_session, platform, platform_user_id, now_text
                )
                connection.commit()
                raise CultivationExpiredError("cultivation settlement window expired")
            qualification = snapshot["qualification"]
            gain = cultivation_gain(
                int(snapshot["base_cultivation"]),
                qualification,
                environment_bp=int(snapshot["environment_bp"]),
                state_bp=int(snapshot["state_bp"]),
                manual_bonus_bp=int(snapshot["manual_cultivation_gain_bp"]),
            )
            soul_power_gain = int(snapshot["soul_power_gain"])
            change_player_state(
                connection,
                row,
                updated_at=now_text,
                value_delta={
                    "cultivation": gain,
                    "total_cultivation": gain,
                    "soul_power": soul_power_gain,
                },
                maximums={"soul_power": max(player_integer(row, "soul_power_max"), int(snapshot["soul_power_max"]))},
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (row["id"],)).fetchone()
            if updated is None:
                raise RuntimeError("cultivation settlement returned no player")
            player = self._row_to_player(updated)
            payload = {
                "player": self._player_payload(player),
                "session_id": session["session_id"],
                "cultivation_gain": gain,
                "soul_power_gain": soul_power_gain,
                "mode_key": str(snapshot["mode_key"]),
                "mode_label": str(snapshot["mode_label"]),
            }
            settlement_result = {
                "cultivation_gain": gain,
                "soul_power_gain": soul_power_gain,
                "terminal_operation_id": operation_id,
                "operation_result_fingerprint": self._request_hash(
                    "progression.settle_cultivation.result", payload
                ),
            }
            connection.execute(
                "UPDATE cultivation_sessions SET status = 'settled', result_json = ?, updated_at = ? WHERE id = ?",
                (json.dumps(settlement_result, ensure_ascii=False, sort_keys=True), now_text, session["id"]),
            )
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
                mode_key=str(snapshot["mode_key"]),
                soul_power_gain=soul_power_gain,
                mode_label=str(snapshot["mode_label"]),
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
                "SELECT operation_name, player_id, request_hash, result_json FROM operations WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            if existing_operation is not None:
                if (
                    existing_operation["operation_name"] != "progression.recover_cultivation"
                    or existing_operation["request_hash"] != request_hash
                ):
                    raise OperationConflictError("operation input differs from its original request")
                payload, player = self._cultivation_operation_result(
                    connection,
                    existing_operation,
                    platform,
                    platform_user_id,
                    "progression.recover_cultivation",
                    _CULTIVATION_SETTLEMENT_RESULT_FIELDS,
                )
                _require_progression_integer(payload["cultivation_gain"], "cultivation gain")
                _require_progression_integer(payload["soul_power_gain"], "soul power gain")
                if not isinstance(payload["session_id"], str) or not payload["session_id"]:
                    raise ValueError("cultivation recovery session id is invalid")
                session = connection.execute(
                    "SELECT * FROM cultivation_sessions WHERE session_id = ? AND player_id = ?",
                    (payload["session_id"], existing_operation["player_id"]),
                ).fetchone()
                if session is None or session["status"] != "expired":
                    raise ValueError("cultivation recovery operation has no expired session")
                snapshot = self._cultivation_snapshot(connection, session)
                result, recovered = self._cultivation_session_result(session["result_json"], "expired")
                if (
                    not recovered
                    or result.get("recovered_after_expiry") is not True
                    or result["terminal_operation_id"] != operation_id
                    or payload["cultivation_gain"] != result["cultivation_gain"]
                    or payload["soul_power_gain"] != result["soul_power_gain"]
                    or payload["mode_key"] != snapshot["mode_key"]
                    or payload["mode_label"] != snapshot["mode_label"]
                    or result["operation_result_fingerprint"]
                    != self._request_hash("progression.recover_cultivation.result", payload)
                ):
                    raise ValueError("cultivation recovery operation does not match its session")
                self._cultivation_expiry_operation(connection, session, platform, platform_user_id)
                return CultivationRecoveryRecord(
                    player=player,
                    session_id=str(payload["session_id"]),
                    cultivation_gain=int(payload["cultivation_gain"]),
                    mode_key=str(payload["mode_key"]),
                    soul_power_gain=int(payload["soul_power_gain"]),
                    mode_label=str(payload["mode_label"]),
                    already_completed=True,
                )

            row = self._require_player(connection, platform, platform_user_id)
            session = connection.execute(
                "SELECT * FROM cultivation_sessions WHERE player_id = ? AND status IN ('running', 'expired') ORDER BY id DESC LIMIT 1",
                (row["id"],),
            ).fetchone()
            if session is None:
                raise CultivationNotFoundError("no expired cultivation")
            snapshot = self._cultivation_snapshot(connection, session)
            session_result, recovered = self._cultivation_session_result(
                session["result_json"], str(session["status"])
            )
            if recovered:
                raise CultivationAlreadyRecoveredError("cultivation was already recovered")
            if session["status"] == "expired":
                self._cultivation_expiry_operation(connection, session, platform, platform_user_id)
            ends_at = datetime.fromisoformat(str(session["ends_at"]))
            if now < ends_at:
                raise CultivationNotReadyError("cultivation is not ready")
            if now <= ends_at + timedelta(seconds=CULTIVATION_SETTLEMENT_GRACE_SECONDS):
                raise CultivationNotReadyError("cultivation is still within the normal settlement window")
            if session["status"] == "running":
                self._record_cultivation_expiry(
                    connection, session, platform, platform_user_id, now_text
                )
            qualification = snapshot["qualification"]
            gain = cultivation_gain(
                int(snapshot["base_cultivation"]),
                qualification,
                environment_bp=int(snapshot["environment_bp"]),
                state_bp=int(snapshot["state_bp"]),
                manual_bonus_bp=int(snapshot["manual_cultivation_gain_bp"]),
            )
            soul_power_gain = int(snapshot["soul_power_gain"])
            change_player_state(
                connection,
                row,
                updated_at=now_text,
                value_delta={
                    "cultivation": gain,
                    "total_cultivation": gain,
                    "soul_power": soul_power_gain,
                },
                maximums={"soul_power": max(player_integer(row, "soul_power_max"), int(snapshot["soul_power_max"]))},
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (row["id"],)).fetchone()
            if updated is None:
                raise RuntimeError("cultivation recovery returned no player")
            player = self._row_to_player(updated)
            payload = {
                "player": self._player_payload(player),
                "session_id": session["session_id"],
                "cultivation_gain": gain,
                "soul_power_gain": soul_power_gain,
                "mode_key": str(snapshot["mode_key"]),
                "mode_label": str(snapshot["mode_label"]),
            }
            recovery_result = {
                "cultivation_gain": gain,
                "soul_power_gain": soul_power_gain,
                "recovered_after_expiry": True,
                "terminal_operation_id": operation_id,
                "operation_result_fingerprint": self._request_hash(
                    "progression.recover_cultivation.result", payload
                ),
            }
            connection.execute(
                "UPDATE cultivation_sessions SET status = 'expired', result_json = ?, updated_at = ? WHERE id = ?",
                (json.dumps(recovery_result, ensure_ascii=False, sort_keys=True), now_text, session["id"]),
            )
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
                mode_key=str(snapshot["mode_key"]),
                soul_power_gain=soul_power_gain,
                mode_label=str(snapshot["mode_label"]),
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
                "SELECT operation_name, player_id, request_hash, result_json FROM operations WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            if existing_operation is not None:
                if (
                    existing_operation["operation_name"] != "progression.cancel_cultivation"
                    or existing_operation["request_hash"] != request_hash
                ):
                    raise OperationConflictError("operation input differs from its original request")
                payload, player = self._cultivation_operation_result(
                    connection,
                    existing_operation,
                    platform,
                    platform_user_id,
                    "progression.cancel_cultivation",
                    _CULTIVATION_CANCEL_RESULT_FIELDS,
                )
                _require_progression_integer(payload["stamina_refund"], "stamina refund")
                _require_progression_integer(payload["energy_refund"], "energy refund")
                if not isinstance(payload["session_id"], str) or not payload["session_id"]:
                    raise ValueError("cultivation cancellation session id is invalid")
                session = connection.execute(
                    "SELECT * FROM cultivation_sessions WHERE session_id = ? AND player_id = ?",
                    (payload["session_id"], existing_operation["player_id"]),
                ).fetchone()
                if session is None or session["status"] != "cancelled":
                    raise ValueError("cultivation cancellation operation has no cancelled session")
                snapshot = self._cultivation_snapshot(connection, session)
                result, _ = self._cultivation_session_result(session["result_json"], "cancelled")
                if (
                    result["terminal_operation_id"] != operation_id
                    or payload["stamina_refund"] != result["stamina_refund"]
                    or payload["energy_refund"] != result["energy_refund"]
                    or payload["stamina_refund"] != snapshot["stamina_cost"]
                    or payload["energy_refund"] != snapshot["energy_cost"]
                    or result["operation_result_fingerprint"]
                    != self._request_hash("progression.cancel_cultivation.result", payload)
                ):
                    raise ValueError("cultivation cancellation operation does not match its session")
                return CultivationCancelRecord(
                    player=player,
                    session_id=str(payload["session_id"]),
                    stamina_refund=int(payload["stamina_refund"]),
                    energy_refund=int(payload["energy_refund"]),
                    already_completed=True,
                )
            row = self._require_player(connection, platform, platform_user_id)
            session = connection.execute(
                "SELECT * FROM cultivation_sessions WHERE player_id = ? AND status = 'running' ORDER BY id DESC LIMIT 1",
                (row["id"],),
            ).fetchone()
            if session is None:
                raise CultivationNotFoundError("no running cultivation")
            snapshot = self._cultivation_snapshot(connection, session)
            self._cultivation_session_result(session["result_json"], str(session["status"]))
            ends_at = datetime.fromisoformat(str(session["ends_at"]))
            if now >= ends_at:
                if now > ends_at + timedelta(seconds=CULTIVATION_SETTLEMENT_GRACE_SECONDS):
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
                    expired_session = connection.execute(
                        "SELECT * FROM cultivation_sessions WHERE id = ?", (session["id"],)
                    ).fetchone()
                    if expired_session is None:
                        raise RuntimeError("expired cultivation session was not saved")
                    self._record_cultivation_expiry(
                        connection, expired_session, platform, platform_user_id, now_text
                    )
                    connection.commit()
                    raise CultivationExpiredError("cultivation cancellation window expired")
                raise CultivationAlreadyReadyError("cultivation must be settled")
            refund = int(snapshot["stamina_cost"])
            energy_refund = int(snapshot["energy_cost"])
            change_player_state(
                connection,
                row,
                updated_at=now_text,
                value_delta={"stamina": refund, "energy": energy_refund},
                maximums={"stamina": row["stamina_max"], "energy": row["energy_max"]},
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
            cancellation_result = {
                "stamina_refund": refund,
                "energy_refund": energy_refund,
                "terminal_operation_id": operation_id,
                "operation_result_fingerprint": self._request_hash(
                    "progression.cancel_cultivation.result", payload
                ),
            }
            connection.execute(
                "UPDATE cultivation_sessions SET status = 'cancelled', result_json = ?, updated_at = ? WHERE id = ?",
                (json.dumps(cancellation_result, ensure_ascii=False, sort_keys=True), now_text, session["id"]),
            )
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
    def _has_active_long_action(
        connection: sqlite3.Connection,
        player_id: int,
        *,
        ignore_exploration_id: str | None = None,
        ignore_secret_realm_run_id: str | None = None,
        ignore_boundary_rift_run_id: str | None = None,
        ignore_ancient_domain_run_id: str | None = None,
        ignore_void_ruins_run_id: str | None = None,
        ignore_time_fort_run_id: str | None = None,
        ignore_ancestral_hall_run_id: str | None = None,
        ignore_tower_run_id: str | None = None,
        ignore_void_spire_run_id: str | None = None,
    ) -> bool:
        """Return whether a player has any session that locks another action."""

        checks = (
            ("cultivation_sessions", "status = 'running'"),
            ("retreat_sessions", "status = 'running'"),
            ("production_orders", "status = 'processing'"),
            ("breakthrough_sessions", "status = 'preparing'"),
            ("travel_sessions", "status = 'running'"),
            ("cloud_boat_sessions", "status IN ('created', 'running')"),
            ("exploration_sessions", "status IN ('created', 'running', 'combat_pending')"),
            ("battle_sessions", "status IN ('created', 'running')"),
            ("party_battle_members", "asset_lock_status = 'locked'"),
            ("final_battle_members", "asset_lock_status = 'locked'"),
            ("void_route_sessions", "status = 'running'"),
            ("idle_assignments", "status IN ('assigned', 'running')"),
            ("dispatch_assignments", "status IN ('accepted', 'running')"),
            ("tower_runs", "status IN ('battle_running', 'reward_pending')"),
            ("void_spire_runs", "status IN ('battle_running', 'reward_pending')"),
            ("livelihood_trade_routes", "status = 'in_transit'"),
            ("secret_realm_runs", "status IN ('entered', 'routing', 'combat_pending', 'cleared', 'failed')"),
            ("boundary_rift_members", "status = 'active'"),
            ("ancient_domain_members", "status = 'active'"),
            ("void_ruins_members", "status = 'active'"),
            ("time_fort_members", "status = 'active'"),
            ("ancestral_hall_runs", "status IN ('routing', 'combat_pending', 'cleared')"),
            ("dao_origin_runs", "status IN ('routing', 'cleared')"),
            ("heaven_echo_runs", "status IN ('routing', 'cleared')"),
            ("legacy_manor_runs", "status IN ('routing', 'cleared')"),
        )
        for table, predicate in checks:
            if table == "exploration_sessions" and ignore_exploration_id is not None:
                active = connection.execute(
                    "SELECT 1 FROM exploration_sessions WHERE player_id = ? AND status IN ('created', 'running', 'combat_pending') AND exploration_id != ? LIMIT 1",
                    (player_id, ignore_exploration_id),
                ).fetchone()
            elif table == "secret_realm_runs" and ignore_secret_realm_run_id is not None:
                active = connection.execute(
                    "SELECT 1 FROM secret_realm_runs WHERE player_id = ? AND status IN ('entered', 'routing', 'combat_pending', 'cleared', 'failed') AND run_id != ? LIMIT 1",
                    (player_id, ignore_secret_realm_run_id),
                ).fetchone()
            elif table == "boundary_rift_members" and ignore_boundary_rift_run_id is not None:
                active = connection.execute(
                    "SELECT 1 FROM boundary_rift_members m JOIN boundary_rift_runs r ON r.run_id=m.run_id "
                    "WHERE m.player_id=? AND m.status='active' AND r.status IN ('routing','combat_pending','cleared') "
                    "AND r.run_id<>? LIMIT 1",
                    (player_id, ignore_boundary_rift_run_id),
                ).fetchone()
            elif table == "boundary_rift_members":
                active = connection.execute(
                    "SELECT 1 FROM boundary_rift_members m JOIN boundary_rift_runs r ON r.run_id=m.run_id "
                    "WHERE m.player_id=? AND m.status='active' AND r.status IN ('routing','combat_pending','cleared') LIMIT 1",
                    (player_id,),
                ).fetchone()
            elif table == "ancient_domain_members" and ignore_ancient_domain_run_id is not None:
                active = connection.execute(
                    "SELECT 1 FROM ancient_domain_members m JOIN ancient_domain_runs r ON r.run_id=m.run_id "
                    "WHERE m.player_id=? AND m.status='active' AND r.status IN ('routing','combat_pending','cleared') "
                    "AND r.run_id<>? LIMIT 1",
                    (player_id, ignore_ancient_domain_run_id),
                ).fetchone()
            elif table == "ancient_domain_members":
                active = connection.execute(
                    "SELECT 1 FROM ancient_domain_members m JOIN ancient_domain_runs r ON r.run_id=m.run_id "
                    "WHERE m.player_id=? AND m.status='active' AND r.status IN ('routing','combat_pending','cleared') LIMIT 1",
                    (player_id,),
                ).fetchone()
            elif table == "void_ruins_members" and ignore_void_ruins_run_id is not None:
                active = connection.execute(
                    "SELECT 1 FROM void_ruins_members m JOIN void_ruins_runs r ON r.run_id=m.run_id "
                    "WHERE m.player_id=? AND m.status='active' AND r.status IN ('routing','combat_pending','cleared') "
                    "AND r.run_id<>? LIMIT 1",
                    (player_id, ignore_void_ruins_run_id),
                ).fetchone()
            elif table == "void_ruins_members":
                active = connection.execute(
                    "SELECT 1 FROM void_ruins_members m JOIN void_ruins_runs r ON r.run_id=m.run_id "
                    "WHERE m.player_id=? AND m.status='active' AND r.status IN ('routing','combat_pending','cleared') LIMIT 1",
                    (player_id,),
                ).fetchone()
            elif table == "time_fort_members" and ignore_time_fort_run_id is not None:
                active = connection.execute(
                    "SELECT 1 FROM time_fort_members m JOIN time_fort_runs r ON r.run_id=m.run_id "
                    "WHERE m.player_id=? AND m.status='active' AND r.status IN ('routing','combat_pending','cleared') "
                    "AND r.run_id<>? LIMIT 1",
                    (player_id, ignore_time_fort_run_id),
                ).fetchone()
            elif table == "time_fort_members":
                active = connection.execute(
                    "SELECT 1 FROM time_fort_members m JOIN time_fort_runs r ON r.run_id=m.run_id "
                    "WHERE m.player_id=? AND m.status='active' AND r.status IN ('routing','combat_pending','cleared') LIMIT 1",
                    (player_id,),
                ).fetchone()
            elif table == "ancestral_hall_runs" and ignore_ancestral_hall_run_id is not None:
                active = connection.execute(
                    "SELECT 1 FROM ancestral_hall_runs WHERE player_id=? "
                    "AND status IN ('routing','combat_pending','cleared') AND run_id<>? LIMIT 1",
                    (player_id, ignore_ancestral_hall_run_id),
                ).fetchone()
            elif table == "dao_origin_runs":
                active = connection.execute(
                    "SELECT 1 FROM dao_origin_runs WHERE player_id=? AND status IN ('routing', 'cleared') LIMIT 1",
                    (player_id,),
                ).fetchone()
            elif table == "heaven_echo_runs":
                active = connection.execute(
                    "SELECT 1 FROM heaven_echo_runs WHERE player_id=? AND status IN ('routing', 'cleared') LIMIT 1",
                    (player_id,),
                ).fetchone()
            elif table == "legacy_manor_runs":
                active = connection.execute(
                    "SELECT 1 FROM legacy_manor_runs WHERE player_id=? AND status IN ('routing', 'cleared') LIMIT 1",
                    (player_id,),
                ).fetchone()
            elif table == "tower_runs" and ignore_tower_run_id is not None:
                active = connection.execute(
                    "SELECT 1 FROM tower_runs WHERE player_id=? AND status IN ('battle_running','reward_pending') AND run_id<>? LIMIT 1",
                    (player_id, ignore_tower_run_id),
                ).fetchone()
            elif table == "void_spire_runs" and ignore_void_spire_run_id is not None:
                active = connection.execute(
                    "SELECT 1 FROM void_spire_runs WHERE player_id=? AND status IN ('battle_running','reward_pending') AND run_id<>? LIMIT 1",
                    (player_id, ignore_void_spire_run_id),
                ).fetchone()
            else:
                active = connection.execute(
                    f"SELECT 1 FROM {table} WHERE player_id = ? AND {predicate} LIMIT 1",
                    (player_id,),
                ).fetchone()
            if active is not None:
                return True
        return False

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
        from ..progression.endgame_rules import trial_definition, tribulation_definition
        tribulation_trials = tribulation_definition(self.content)

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
            layer = player_integer(row, "realm_layer")
            realm_key = str(row["realm_key"])
            if next_layer_threshold(realm_key, layer, self.content) is None:
                raise RealmLayerInvalidError("realm is already at its maximum layer")
            if not can_advance_layer(realm_key, layer, player_integer(row, "cultivation"), self.content):
                raise RealmCultivationInsufficientError("realm cultivation is insufficient")
            trial_layers = {trial_definition(key, self.content).required_layer for key in tribulation_trials.trial_order}
            if realm_key == "tribulation" and layer in trial_layers:
                completed = {
                    str(item["trial_key"])
                    for item in connection.execute(
                        "SELECT trial_key FROM tribulation_trial_sessions WHERE player_id = ? AND status = 'succeeded'",
                        (row["id"],),
                    ).fetchall()
                }
                required = tuple(
                    key
                    for key in tribulation_trials.trial_order
                    if trial_definition(key, self.content).required_layer <= layer
                )
                if any(item not in completed for item in required):
                    raise TrialSequenceError("the required tribulation trial has not succeeded")
                if layer == 9:
                    from ..quests.rules import DAO_ORIGIN_TASKS

                    task_seasons: list[set[str]] = []
                    for task_key in DAO_ORIGIN_TASKS:
                        seasons = self._dao_origin_task_seasons(connection, int(row["id"]), task_key)
                        task_seasons.append(
                            {
                                season_id
                                for season_id, (count, snapshot) in seasons.items()
                                if count >= snapshot["target"]
                            }
                        )
                    eligible_seasons = set.intersection(*task_seasons) if task_seasons else set()
                    if not eligible_seasons:
                        raise TrialSequenceError("dao origin tasks are incomplete")
            layer_unlocks_reached = layer_unlocks(realm_key, layer + 1, self.content)
            change_player_state(
                connection,
                row,
                updated_at=now_text,
                value_delta={"realm_layer": 1},
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
                content=self.content,
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
