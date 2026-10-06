"""SQLite transactions for bounty boards and mainline adventures."""

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
    MAINLINE_NUMERIC_REWARD_KEYS,
    MAINLINE_REWARD_PREFIXES,
    MAINLINE_DEFINITIONS,
    MAINLINE_LOCKED,
    MAINLINE_REWARD_PENDING,
    MAINLINE_STAGES,
    MAINLINE_STORY_KEY,
    MAINLINE_TOWN_COMMISSION_DELIVERED,
    mainline_definition,
    mainline_definitions,
    mainline_first_clear_key,
    mainline_prerequisites_met,
    mainline_reward,
    mainline_stage_status,
    resolve_mainline,
    MainlineStageDefinition,
)
from ..adventures.rules import (
    bounty_definition,
    bounty_definitions,
    bounty_reward_labels,
    choose_bounty,
    default_content_bundle,
    meets_realm as bounty_meets_realm,
    reward_map,
)
from ..utils.equipment import create_equipment_instances, equipment_instance_template
from ..specials.codex_projection import record_codex_discovery
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
from ..utils.assets import grant_player_assets, inventory_amount
from ..utils.player import (
    change_player_state,
    grant_player_honor_title,
    grant_player_state,
    player_integer,
    player_inventory,
    player_reputation_state,
    split_player_rewards,
)
from ..rewards.rules import local_reputation_maximum


def _bounty_snapshot(raw_value: Any) -> dict[str, Any]:
    try:
        snapshot = json.loads(str(raw_value))
    except (TypeError, ValueError) as exc:
        raise ValueError("bounty snapshot is invalid JSON") from exc
    if not isinstance(snapshot, dict):
        raise ValueError("bounty snapshot must be an object")
    required = {
        "bounty_key",
        "label",
        "description",
        "reward_pool_key",
        "reward",
        "reward_labels",
        "reward_item_types",
        "equipment_instances",
        "codex_categories",
        "target_kind",
        "target_key",
        "target_amount",
        "reputation_key",
        "local_reputation_maximum",
        "consume_target",
        "baseline_quantity",
        "baseline_completed_orders",
        "baseline_exploration_battle_wins",
        "baseline_dispatch_assignment_ids",
        "selection",
    }
    missing = required - snapshot.keys()
    if missing:
        raise ValueError(f"bounty snapshot is missing fields: {sorted(missing)!r}")
    string_fields = (
        "bounty_key",
        "label",
        "description",
        "reward_pool_key",
        "target_kind",
        "reputation_key",
    )
    if any(
        not isinstance(snapshot[key], str) or not snapshot[key]
        for key in string_fields
    ):
        raise ValueError("bounty snapshot contains an invalid string field")
    if snapshot["target_kind"] not in {
        "inventory_gain",
        "production_completed",
        "exploration_battle_wins",
        "dispatch_successes",
    }:
        raise ValueError("bounty snapshot contains an invalid target kind")
    if snapshot["target_key"] is not None and (
        not isinstance(snapshot["target_key"], str) or not snapshot["target_key"]
    ):
        raise ValueError("bounty snapshot contains an invalid target key")
    for key in ("target_amount", "local_reputation_maximum"):
        if (
            isinstance(snapshot[key], bool)
            or not isinstance(snapshot[key], int)
            or snapshot[key] <= 0
        ):
            raise ValueError(f"bounty snapshot {key} must be positive")
    for key in ("baseline_quantity", "baseline_completed_orders", "baseline_exploration_battle_wins"):
        if (
            isinstance(snapshot[key], bool)
            or not isinstance(snapshot[key], int)
            or snapshot[key] < 0
        ):
            raise ValueError(f"bounty snapshot {key} must be non-negative")
    if not isinstance(snapshot["consume_target"], bool):
        raise ValueError("bounty snapshot consume_target must be a boolean")
    if snapshot["consume_target"] and snapshot["target_kind"] != "inventory_gain":
        raise ValueError("bounty snapshot cannot consume a non-inventory target")
    if snapshot["target_kind"] == "production_completed" and snapshot["target_key"] is not None:
        raise ValueError("production bounty snapshot cannot have a target key")
    if snapshot["target_kind"] != "production_completed" and snapshot["target_key"] is None:
        raise ValueError("bounty snapshot target key is required")
    reward = snapshot["reward"]
    if not isinstance(reward, dict) or not reward:
        raise ValueError("bounty snapshot reward must be a non-empty object")
    if any(
        not isinstance(key, str)
        or not key
        or isinstance(value, bool)
        or not isinstance(value, int)
        or value <= 0
        for key, value in reward.items()
    ):
        raise ValueError("bounty snapshot reward quantities must be positive integers")
    labels = snapshot["reward_labels"]
    if not isinstance(labels, dict) or any(
        not isinstance(key, str) or not isinstance(value, str)
        for key, value in labels.items()
    ):
        raise ValueError("bounty snapshot reward_labels must map strings to strings")
    item_reward_keys = {key for key in reward if key.startswith("item.")}
    item_types = snapshot["reward_item_types"]
    if (
        not isinstance(item_types, dict)
        or set(item_types) != item_reward_keys
        or any(
            not isinstance(value, str) or value not in {"equipment", "inventory"}
            for value in item_types.values()
        )
    ):
        raise ValueError("bounty snapshot item reward types are invalid")
    equipment = snapshot["equipment_instances"]
    equipment_keys = {key for key, value in item_types.items() if value == "equipment"}
    if not isinstance(equipment, dict) or set(equipment) != equipment_keys:
        raise ValueError("bounty snapshot equipment templates are invalid")
    for key, template in equipment.items():
        if (
            not isinstance(key, str)
            or not isinstance(template, dict)
            or template.get("item_key") != key
            or not isinstance(template.get("label"), str)
            or not template["label"]
            or not isinstance(template.get("slot"), str)
            or not template["slot"]
            or isinstance(template.get("durability_bp"), bool)
            or not isinstance(template.get("durability_bp"), int)
            or template["durability_bp"] < 0
            or isinstance(template.get("max_temper_level"), bool)
            or not isinstance(template.get("max_temper_level"), int)
            or template["max_temper_level"] <= 0
        ):
            raise ValueError("bounty snapshot equipment template is invalid")
    codex_keys = {key for key in reward if key.startswith("codex.")}
    codex_categories = snapshot["codex_categories"]
    if (
        not isinstance(codex_categories, dict)
        or set(codex_categories) != codex_keys
        or any(not isinstance(value, str) or not value for value in codex_categories.values())
    ):
        raise ValueError("bounty snapshot codex categories are invalid")
    assignments = snapshot["baseline_dispatch_assignment_ids"]
    if not isinstance(assignments, list) or any(
        not isinstance(item, str) or not item for item in assignments
    ):
        raise ValueError("bounty snapshot dispatch baseline must be a string list")
    selection = snapshot["selection"]
    if (
        not isinstance(selection, dict)
        or not isinstance(selection.get("reward_seed"), str)
        or not selection["reward_seed"]
        or (
            selection.get("bounty_choice_seed") is not None
            and (
                not isinstance(selection["bounty_choice_seed"], str)
                or not selection["bounty_choice_seed"]
            )
        )
        or not isinstance(selection.get("candidate_weights"), list)
        or any(
            not isinstance(candidate, dict)
            or not isinstance(candidate.get("bounty_key"), str)
            or not candidate["bounty_key"]
            or isinstance(candidate.get("weight"), bool)
            or not isinstance(candidate.get("weight"), int)
            or candidate["weight"] <= 0
            for candidate in selection["candidate_weights"]
        )
        or (selection["bounty_choice_seed"] is None and selection["candidate_weights"])
        or (selection["bounty_choice_seed"] is not None and not selection["candidate_weights"])
        or not isinstance(selection.get("realm_key"), str)
        or isinstance(selection.get("realm_layer"), bool)
        or not isinstance(selection.get("realm_layer"), int)
        or selection["realm_layer"] < 0
        or (
            selection.get("path_key") is not None
            and (
                not isinstance(selection["path_key"], str)
                or not selection["path_key"]
            )
        )
    ):
        raise ValueError("bounty snapshot selection evidence is invalid")
    candidate_keys = [item["bounty_key"] for item in selection["candidate_weights"]]
    if (
        len(set(candidate_keys)) != len(candidate_keys)
        or (
            selection["bounty_choice_seed"] is not None
            and snapshot["bounty_key"] not in candidate_keys
        )
    ):
        raise ValueError("bounty snapshot candidate selection is inconsistent")
    if "local_reputation" in reward and (
        not snapshot["reputation_key"].startswith("local.")
        or not snapshot["reputation_key"].removeprefix("local.")
    ):
        raise ValueError("bounty snapshot local reputation key is invalid")
    return snapshot


def _bounty_recorded_progress(raw_value: Any, target: int) -> int:
    try:
        result = json.loads(str(raw_value))
    except (TypeError, ValueError) as exc:
        raise ValueError("bounty result is invalid JSON") from exc
    if not isinstance(result, dict):
        raise ValueError("bounty result must be an object")
    progress = result.get("progress")
    if isinstance(progress, bool) or not isinstance(progress, int) or not 0 <= progress <= target:
        raise ValueError("bounty result progress is invalid")
    return progress


def _bounty_daily_counts(
    connection: sqlite3.Connection, player_id: int, business_date: str
) -> dict[str, int]:
    rows = connection.execute(
        """
        SELECT bounty_key, COUNT(*) AS count
        FROM bounty_offers
        WHERE player_id = ? AND business_date = ?
        GROUP BY bounty_key
        """,
        (player_id, business_date),
    ).fetchall()
    return {str(row["bounty_key"]): int(row["count"]) for row in rows}


class AdventuresRepositoryMixin:
    async def get_bounty_board(
        self,
        *,
        platform: str,
        platform_user_id: str,
    ) -> BountyBoardRecord:
        await self.initialize()
        return await asyncio.to_thread(self._get_bounty_board_sync, platform, platform_user_id)

    def _get_bounty_board_sync(self, platform: str, platform_user_id: str) -> BountyBoardRecord:
        now = self._now()
        business_date = now.date().isoformat()
        with self._connect() as connection:
            row = self._require_player(connection, platform, platform_user_id, writable=False)
            accepted = connection.execute(
                """SELECT * FROM bounty_offers
                   WHERE player_id = ? AND business_date = ?
                   ORDER BY accepted_at DESC, id DESC LIMIT 1""",
                (row["id"], business_date),
            ).fetchone()
            if accepted is None:
                accepted = connection.execute(
                    """
                    SELECT * FROM bounty_offers
                    WHERE player_id = ? AND status IN ('accepted', 'completed') AND expires_at > ?
                    ORDER BY accepted_at DESC, id DESC LIMIT 1
                    """,
                    (row["id"], serialize_datetime(now)),
                ).fetchone()
            daily_counts = _bounty_daily_counts(connection, int(row["id"]), business_date)
            offers: list[BountyOfferView] = []
            accepted_snapshot = _bounty_snapshot(accepted["snapshot_json"]) if accepted is not None else None
            for definition in bounty_definitions(self.content):
                is_accepted = accepted is not None and accepted["bounty_key"] == definition.key
                if is_accepted:
                    assert accepted_snapshot is not None
                    label = accepted_snapshot["label"]
                    description = accepted_snapshot["description"]
                    target = accepted_snapshot["target_amount"]
                    reward = accepted_snapshot["reward"]
                    reward_labels = accepted_snapshot["reward_labels"]
                else:
                    label = definition.label
                    description = definition.description
                    target = definition.target_amount
                    reward = reward_map(
                        definition,
                        self.content,
                        seed=f"{row['id']}:{business_date}:{definition.key}",
                        path_key=str(row["path_key"]) if row["path_key"] else None,
                        realm_key=str(row["realm_key"]),
                        realm_layer=player_integer(row, "realm_layer"),
                    )
                    reward_labels = bounty_reward_labels(definition, reward, self.content)
                progress = 0
                expires_at: str | None = None
                if is_accepted:
                    assert accepted_snapshot is not None
                    progress = self._bounty_progress(connection, row, accepted, accepted_snapshot)
                    if accepted["status"] in {"claimed", "expired"}:
                        progress = _bounty_recorded_progress(
                            accepted["result_json"], accepted_snapshot["target_amount"]
                        )
                    expires_at = str(accepted["expires_at"])
                    if accepted["status"] in {"claimed", "expired"}:
                        status = str(accepted["status"])
                    elif now > datetime.fromisoformat(str(accepted["expires_at"])):
                        status = "expired"
                    elif progress >= accepted_snapshot["target_amount"]:
                        status = "completed"
                    else:
                        status = "accepted"
                elif (
                    accepted is not None
                    and accepted["status"] in {"accepted", "completed"}
                    and now <= datetime.fromisoformat(str(accepted["expires_at"]))
                ):
                    status = "daily_limit"
                elif definition.runtime_status != "open":
                    status = "locked"
                elif not self._bounty_player_eligible(connection, row, definition, now):
                    status = "requirement"
                elif daily_counts.get(definition.key, 0) >= definition.daily_limit:
                    status = "daily_limit"
                else:
                    status = "available"
                offers.append(
                    BountyOfferView(
                        key=definition.key,
                        label=label,
                        description=description,
                        status=status,
                        progress=progress,
                        target=target,
                        reward=reward,
                        reward_labels=reward_labels,
                        expires_at=expires_at,
                    )
                )
            if accepted is not None and not any(item.key == accepted["bounty_key"] for item in offers):
                assert accepted_snapshot is not None
                if accepted["status"] in {"claimed", "expired"}:
                    progress = _bounty_recorded_progress(
                        accepted["result_json"], accepted_snapshot["target_amount"]
                    )
                else:
                    progress = self._bounty_progress(connection, row, accepted, accepted_snapshot)
                status = str(accepted["status"])
                if status not in {"claimed", "expired"}:
                    status = "expired" if now > datetime.fromisoformat(str(accepted["expires_at"])) else (
                        "completed" if progress >= accepted_snapshot["target_amount"] else "accepted"
                    )
                offers.append(
                    BountyOfferView(
                        key=accepted_snapshot["bounty_key"],
                        label=accepted_snapshot["label"],
                        description=accepted_snapshot["description"],
                        status=status,
                        progress=progress,
                        target=accepted_snapshot["target_amount"],
                        reward=accepted_snapshot["reward"],
                        reward_labels=accepted_snapshot["reward_labels"],
                        expires_at=str(accepted["expires_at"]),
                    )
                )
            return BountyBoardRecord(
                player=self._row_to_player(row),
                business_date=business_date,
                offers=tuple(offers),
            )

    def _bounty_player_eligible(
        self,
        connection: sqlite3.Connection,
        row: sqlite3.Row | dict[str, Any],
        definition,
        now: datetime,
    ) -> bool:
        stage = str(row["stage"] if isinstance(row, sqlite3.Row) else row.get("stage", ""))
        if stage not in {STAGE_MORTAL, "seeker", "cultivator"}:
            return False
        realm_key = str(row["realm_key"] if isinstance(row, sqlite3.Row) else row.get("realm_key", "mortal"))
        layer = player_integer(row, "realm_layer")
        path_key = row["path_key"] if isinstance(row, sqlite3.Row) else row.get("path_key")
        if definition.path_keys and path_key not in definition.path_keys:
            return False
        if definition.required_intro_flag:
            intro_raw = row["intro_json"] if isinstance(row, sqlite3.Row) else row.get("intro_json", {})
            intro = SQLitePlayerRepository._json_object(intro_raw, {})
            flags = {str(flag) for flag in intro.get("flags", [])}
            if definition.required_intro_flag not in flags:
                return False
        if definition.required_permit:
            player_id = int(row["id"] if isinstance(row, sqlite3.Row) else row.get("id", 0))
            if not connection.execute(
                "SELECT 1 FROM trade_permits WHERE player_id=? AND permit_key=? AND expires_at>? LIMIT 1",
                (player_id, definition.required_permit, serialize_datetime(now)),
            ).fetchone():
                return False
        if bounty_meets_realm(
            realm_key,
            layer,
            definition.required_realm,
            definition.required_layer,
            self.content,
        ):
            return True
        return any(
            self._bounty_access_condition_met(connection, row, condition, now)
            for condition in definition.access_any
        )

    @staticmethod
    def _bounty_access_condition_met(
        connection: sqlite3.Connection,
        row: sqlite3.Row | dict[str, Any],
        condition: dict[str, Any],
        now: datetime,
    ) -> bool:
        condition_type = condition.get("type")
        if condition_type == "subprofession":
            value = row["subprofession_key"] if isinstance(row, sqlite3.Row) else row.get("subprofession_key")
            return str(value or "") == str(condition.get("value", ""))
        if condition_type == "intro_flag":
            intro_raw = row["intro_json"] if isinstance(row, sqlite3.Row) else row.get("intro_json", {})
            flags = SQLitePlayerRepository._json_object(intro_raw, {}).get("flags", [])
            return str(condition.get("value", "")) in {str(flag) for flag in flags}
        if condition_type == "inventory_item":
            inventory = player_inventory(row)
            item_key = str(condition.get("item_key", ""))
            quantity = int(condition.get("quantity", 1))
            return bool(item_key) and inventory_amount(inventory, item_key) >= quantity
        if condition_type == "permit":
            player_id = int(row["id"] if isinstance(row, sqlite3.Row) else row.get("id", 0))
            return bool(
                connection.execute(
                    "SELECT 1 FROM trade_permits WHERE player_id=? AND permit_key=? AND expires_at>? LIMIT 1",
                    (player_id, str(condition.get("permit_key", "")), serialize_datetime(now)),
                ).fetchone()
            )
        return False

    @staticmethod
    def _bounty_progress(
        connection: sqlite3.Connection,
        row: sqlite3.Row,
        offer: sqlite3.Row,
        snapshot: dict[str, Any],
    ) -> int:
        target_amount = int(snapshot["target_amount"])
        if snapshot["target_kind"] == "inventory_gain":
            inventory = player_inventory(row)
            current = inventory_amount(inventory, str(snapshot["target_key"]))
            baseline = int(snapshot["baseline_quantity"])
            return max(0, min(target_amount, current - baseline))
        if snapshot["target_kind"] == "production_completed":
            current = connection.execute(
                "SELECT COUNT(*) AS count FROM production_orders WHERE player_id = ? AND status = 'completed'",
                (row["id"],),
            ).fetchone()
            baseline = int(snapshot["baseline_completed_orders"])
            return max(0, min(target_amount, int(current["count"]) - baseline))
        if snapshot["target_kind"] == "exploration_battle_wins":
            current = connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM battle_sessions
                WHERE player_id = ?
                  AND battle_type = 'pve.exploration'
                  AND enemy_key = ?
                  AND status = 'settled'
                  AND json_extract(result_json, '$.outcome') = 'won'
                """,
                (row["id"], snapshot["target_key"]),
            ).fetchone()
            baseline = int(snapshot["baseline_exploration_battle_wins"])
            return max(0, min(target_amount, int(current["count"]) - baseline))
        if snapshot["target_kind"] == "dispatch_successes":
            rows = connection.execute(
                """
                SELECT d.assignment_id
                FROM activity_events e
                JOIN dispatch_assignments d ON d.settle_operation_id = e.source_operation_id
                WHERE e.player_id = ? AND e.event_key = 'specials.dispatch.settled'
                  AND e.occurred_at > ? AND d.dispatch_key = ? AND d.status = 'settled'
                  AND json_extract(e.payload_json, '$.outcome') = 'success'
                """,
                (row["id"], str(offer["accepted_at"]), str(snapshot["target_key"])),
            ).fetchall()
            baseline = set(snapshot["baseline_dispatch_assignment_ids"])
            completed = sum(
                str(item["assignment_id"]) not in baseline for item in rows
            )
            return max(0, min(target_amount, completed))
        raise ValueError("bounty snapshot has an unsupported target kind")

    async def accept_bounty(
        self,
        *,
        platform: str,
        platform_user_id: str,
        bounty_key: str | None,
        operation_id: str,
    ) -> BountyAcceptRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._accept_bounty_sync,
                platform,
                platform_user_id,
                bounty_key,
                operation_id,
            )

    def _accept_bounty_sync(
        self,
        platform: str,
        platform_user_id: str,
        bounty_key: str,
        operation_id: str,
    ) -> BountyAcceptRecord:
        operation_name = "bounty.accept"
        request_payload = {
            "platform": platform,
            "platform_user_id": platform_user_id,
            "bounty_key": bounty_key if bounty_key is not None else "$random",
        }
        request_hash = self._request_hash(operation_name, request_payload)
        now = self._now()
        business_date = now.date().isoformat()
        starts_at = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            if existing is not None:
                if existing["operation_name"] != operation_name or existing["request_hash"] != request_hash:
                    raise OperationConflictError("operation input differs from its original request")
                return self._bounty_accept_from_payload(json.loads(existing["result_json"]), replay=True)
            row = self._require_player(connection, platform, platform_user_id)
            active = connection.execute(
                """
                SELECT 1 FROM bounty_offers
                WHERE player_id = ? AND status IN ('accepted', 'completed') AND expires_at > ?
                LIMIT 1
                """,
                (row["id"], starts_at),
            ).fetchone()
            if active is not None:
                raise BountyDailyLimitError("player already has an active bounty")

            daily_counts = _bounty_daily_counts(
                connection, int(row["id"]), business_date
            )
            bounty_choice_seed: str | None = None
            candidate_weights: list[dict[str, Any]] = []
            if bounty_key is None:
                eligible = [
                    definition
                    for definition in bounty_definitions(self.content)
                    if definition.runtime_status == "open"
                    and self._bounty_player_eligible(connection, row, definition, now)
                ]
                candidates = [
                    definition
                    for definition in eligible
                    if daily_counts.get(definition.key, 0) < definition.daily_limit
                ]
                if not candidates:
                    if eligible:
                        raise BountyDailyLimitError("daily bounty limit reached")
                    raise BountyRequirementError("no eligible bounty candidates")
                bounty_choice_seed = uuid4().hex
                candidate_weights = [
                    {"bounty_key": item.key, "weight": item.weight}
                    for item in candidates
                ]
                definition = choose_bounty(
                    candidates,
                    seed=bounty_choice_seed,
                )
            else:
                definition = bounty_definition(bounty_key, self.content)
            expires_at = serialize_datetime(now + timedelta(seconds=definition.duration_seconds))
            if definition.runtime_status != "open":
                raise BountyContentClosedError("bounty runtime is closed")
            if not self._bounty_player_eligible(connection, row, definition, now):
                raise BountyRequirementError("bounty requirements are not met")
            if daily_counts.get(definition.key, 0) >= definition.daily_limit:
                raise BountyDailyLimitError("daily bounty limit reached")
            inventory = player_inventory(row)
            completed_orders = connection.execute(
                "SELECT COUNT(*) AS count FROM production_orders WHERE player_id = ? AND status = 'completed'",
                (row["id"],),
            ).fetchone()
            if definition.target_kind == "exploration_battle_wins":
                battle_type = "pve.exploration"
                battle_wins = connection.execute(
                    """
                    SELECT COUNT(*) AS count
                    FROM battle_sessions
                    WHERE player_id = ?
                      AND battle_type = ?
                      AND enemy_key = ?
                      AND status = 'settled'
                      AND json_extract(result_json, '$.outcome') = 'won'
                    """,
                    (row["id"], battle_type, definition.target_key),
                ).fetchone()
            else:
                battle_wins = {"count": 0}
            baseline_dispatch_ids: list[str] = []
            if definition.target_kind == "dispatch_successes":
                baseline_dispatch_ids = [
                    str(item["assignment_id"])
                    for item in connection.execute(
                        "SELECT assignment_id FROM dispatch_assignments WHERE player_id=? AND dispatch_key=? AND status IN ('accepted', 'running')",
                        (row["id"], definition.target_key),
                    ).fetchall()
                ]
            selection_seed = uuid4().hex
            selected_reward = reward_map(
                definition,
                self.content,
                seed=selection_seed,
                path_key=str(row["path_key"]) if row["path_key"] else None,
                realm_key=str(row["realm_key"]),
                realm_layer=player_integer(row, "realm_layer"),
            )
            reward_item_types: dict[str, str] = {}
            equipment_instances: dict[str, dict[str, Any]] = {}
            for reward_key in selected_reward:
                if not reward_key.startswith("item."):
                    continue
                template = equipment_instance_template(reward_key, self.content)
                reward_item_types[reward_key] = "equipment" if template else "inventory"
                if template is not None:
                    equipment_instances[reward_key] = template
            codex_categories: dict[str, str] = {}
            for reward_key in selected_reward:
                if not reward_key.startswith("codex."):
                    continue
                content = self.content or default_content_bundle()
                codex_entry = content.require(
                    "codex_entry", reward_key, include_locked=False
                )
                category = codex_entry.get("category")
                if not isinstance(category, str) or not category:
                    raise ValueError(f"codex entry {reward_key} has an invalid category")
                codex_categories[reward_key] = category
            reputation_maximum = local_reputation_maximum(
                definition.reputation_key, self.content
            )
            snapshot = {
                "bounty_key": definition.key,
                "label": definition.label,
                "description": definition.description,
                "reward_pool_key": definition.reward_pool_key,
                "reward": selected_reward,
                "reward_labels": bounty_reward_labels(
                    definition, selected_reward, self.content
                ),
                "reward_item_types": reward_item_types,
                "equipment_instances": equipment_instances,
                "codex_categories": codex_categories,
                "target_kind": definition.target_kind,
                "target_key": definition.target_key,
                "target_amount": definition.target_amount,
                "reputation_key": definition.reputation_key,
                "local_reputation_maximum": reputation_maximum,
                "required_intro_flag": definition.required_intro_flag,
                "consume_target": definition.consume_target,
                "baseline_quantity": inventory_amount(inventory, str(definition.target_key)) if definition.target_key else 0,
                "baseline_completed_orders": int(completed_orders["count"]),
                "baseline_exploration_battle_wins": int(battle_wins["count"]),
                "baseline_dispatch_assignment_ids": baseline_dispatch_ids,
                "selection": {
                    "reward_seed": selection_seed,
                    "bounty_choice_seed": bounty_choice_seed,
                    "candidate_weights": candidate_weights,
                    "path_key": str(row["path_key"]) if row["path_key"] else None,
                    "realm_key": str(row["realm_key"]),
                    "realm_layer": player_integer(row, "realm_layer"),
                },
            }
            offer_id = uuid4().hex
            connection.execute(
                """
                INSERT INTO bounty_offers(
                    offer_id, player_id, operation_id, bounty_key, business_date, status,
                    accepted_at, expires_at, snapshot_json, result_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'accepted', ?, ?, ?, '{}', ?, ?)
                """,
                (
                    offer_id,
                    row["id"],
                    operation_id,
                    definition.key,
                    business_date,
                    starts_at,
                    expires_at,
                    json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
                    starts_at,
                    starts_at,
                ),
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (row["id"],)).fetchone()
            player = self._row_to_player(updated)
            payload = {
                "player": self._player_payload(player),
                "bounty_key": definition.key,
                "label": definition.label,
                "status": "accepted",
                "progress": 0,
                "target": definition.target_amount,
                "starts_at": starts_at,
                "expires_at": expires_at,
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
            return self._bounty_accept_from_payload(payload)

    @staticmethod
    def _bounty_accept_from_payload(payload: dict[str, Any], replay: bool = False) -> BountyAcceptRecord:
        return BountyAcceptRecord(
            player=SQLitePlayerRepository._row_to_player(payload["player"]),
            bounty_key=str(payload["bounty_key"]),
            label=str(payload["label"]),
            status=str(payload["status"]),
            progress=int(payload.get("progress", 0)),
            target=int(payload["target"]),
            starts_at=str(payload["starts_at"]),
            expires_at=str(payload["expires_at"]),
            already_completed=replay,
        )
    async def claim_bounty(
        self,
        *,
        platform: str,
        platform_user_id: str,
        operation_id: str,
    ) -> BountyClaimRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._claim_bounty_sync,
                platform,
                platform_user_id,
                operation_id,
            )

    def _claim_bounty_sync(
        self, platform: str, platform_user_id: str, operation_id: str
    ) -> BountyClaimRecord:
        operation_name = "bounty.claim"
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
                payload = json.loads(existing["result_json"])
                if payload.get("status") == "expired":
                    raise BountyExpiredError("bounty has expired")
                return self._bounty_claim_from_payload(payload, replay=True)
            row = self._require_player(connection, platform, platform_user_id)
            offer = connection.execute(
                "SELECT * FROM bounty_offers WHERE player_id = ? AND status IN ('accepted', 'completed') ORDER BY id DESC LIMIT 1",
                (row["id"],),
            ).fetchone()
            if offer is None:
                claimed = connection.execute(
                    "SELECT 1 FROM bounty_offers WHERE player_id = ? AND status = 'claimed' ORDER BY id DESC LIMIT 1",
                    (row["id"],),
                ).fetchone()
                if claimed is not None:
                    raise BountyAlreadyClaimedError("bounty reward was already claimed")
                raise BountyNotFoundError("no bounty is waiting for a claim")
            snapshot = _bounty_snapshot(offer["snapshot_json"])
            progress = self._bounty_progress(connection, row, offer, snapshot)
            if now > datetime.fromisoformat(str(offer["expires_at"])):
                expired_payload = {
                    "player": self._player_payload(self._row_to_player(row)),
                    "bounty_key": snapshot["bounty_key"],
                    "label": snapshot["label"],
                    "status": "expired",
                    "progress": progress,
                    "target": snapshot["target_amount"],
                    "rewards": {},
                    "reward_labels": snapshot["reward_labels"],
                }
                connection.execute(
                    "UPDATE bounty_offers SET status = 'expired', result_json = ?, updated_at = ? WHERE id = ? AND status IN ('accepted', 'completed')",
                    (
                        json.dumps({"status": "expired", "progress": progress}, ensure_ascii=False, sort_keys=True),
                        now_text,
                        offer["id"],
                    ),
                )
                connection.execute(
                    "INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        operation_id,
                        operation_name,
                        row["id"],
                        request_hash,
                        json.dumps(expired_payload, ensure_ascii=False, sort_keys=True),
                        now_text,
                    ),
                )
                connection.commit()
                raise BountyExpiredError("bounty has expired")
            if progress < snapshot["target_amount"]:
                raise BountyIncompleteError("bounty target is incomplete")

            consumed_target: tuple[str, int] | None = None
            if snapshot["consume_target"] and snapshot["target_key"]:
                inventory = player_inventory(row)
                quantity = inventory_amount(inventory, snapshot["target_key"])
                if quantity < snapshot["target_amount"]:
                    raise BountyIncompleteError("delivery inventory is insufficient")
                consumed_target = (snapshot["target_key"], snapshot["target_amount"])
            rewards = snapshot["reward"]
            state_rewards: dict[str, int] = {}
            for key, quantity in rewards.items():
                if key == "local_reputation":
                    state_rewards[snapshot["reputation_key"]] = quantity
                elif key.startswith("codex."):
                    recorded = record_codex_discovery(
                        connection,
                        player_id=int(row["id"]),
                        entry_key=key,
                        operation_id=operation_id,
                        occurred_at=now,
                        snapshot=snapshot,
                        content=self.content,
                        category_snapshot=snapshot["codex_categories"][key],
                    )
                    if not recorded:
                        raise ValueError(f"bounty codex reward {key} could not be recorded")
                elif key.startswith("item."):
                    if snapshot["reward_item_types"][key] == "equipment":
                        created = create_equipment_instances(
                            connection,
                            player_id=int(row["id"]),
                            item_key=key,
                            quantity=quantity,
                            now_text=now_text,
                            frozen_template=snapshot["equipment_instances"][key],
                        )
                        if not created:
                            raise ValueError(f"bounty equipment reward {key} could not be created")
                    else:
                        state_rewards[key] = quantity
                    continue
                else:
                    state_rewards[key] = quantity

            state_parts = split_player_rewards(state_rewards)
            asset_delta = dict(state_parts.assets)
            if consumed_target is not None:
                target_key, target_amount = consumed_target
                asset_delta[target_key] = asset_delta.get(target_key, 0) - target_amount
            reputation_before = (
                player_reputation_state(connection, int(row["id"]))
                if state_parts.local_reputation or state_parts.service_reputation is not None
                else None
            )
            energy_before = player_integer(row, "energy")
            if (
                asset_delta
                or state_parts.value_delta
                or state_parts.reputation
                or state_parts.local_reputation
                or state_parts.service_reputation is not None
            ):
                change_player_state(
                    connection,
                    row,
                    updated_at=now_text,
                    asset_values=asset_delta or None,
                    asset_mode="delta",
                    value_delta=state_parts.value_delta or None,
                    maximums=(
                        {"energy": player_integer(row, "energy_max")}
                        if "energy" in state_parts.value_delta
                        else None
                    ),
                    reputation_delta=state_parts.reputation or None,
                    local_reputation_delta=state_parts.local_reputation or None,
                    local_reputation_maximums=(
                        {snapshot["reputation_key"]: snapshot["local_reputation_maximum"]}
                        if "local_reputation" in rewards
                        else None
                    ),
                    service_reputation_delta=state_parts.service_reputation,
                )
            actual_rewards: dict[str, int] = {}
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (row["id"],)).fetchone()
            reputation_after = (
                player_reputation_state(connection, int(row["id"]))
                if reputation_before is not None
                else None
            )
            for key, quantity in rewards.items():
                if key == "local_reputation":
                    assert reputation_before is not None and reputation_after is not None
                    amount = (
                        reputation_after.local.get(snapshot["reputation_key"], 0)
                        - reputation_before.local.get(snapshot["reputation_key"], 0)
                    )
                elif key == "service_reputation":
                    assert reputation_before is not None and reputation_after is not None
                    amount = reputation_after.service - reputation_before.service
                elif key == "energy":
                    amount = player_integer(updated, "energy") - energy_before
                else:
                    amount = quantity
                if amount:
                    actual_rewards[key] = amount
            result_json = {
                "status": "claimed",
                "progress": progress,
                "target": snapshot["target_amount"],
                "rewards": actual_rewards,
            }
            connection.execute(
                "UPDATE bounty_offers SET status = 'claimed', result_json = ?, updated_at = ? WHERE id = ? AND status IN ('accepted', 'completed')",
                (json.dumps(result_json, ensure_ascii=False, sort_keys=True), now_text, offer["id"]),
            )
            player = self._row_to_player(updated)
            payload = {
                "player": self._player_payload(player),
                "bounty_key": snapshot["bounty_key"],
                "label": snapshot["label"],
                "status": "claimed",
                "progress": progress,
                "target": snapshot["target_amount"],
                "rewards": actual_rewards,
                "reward_labels": snapshot["reward_labels"],
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
            return self._bounty_claim_from_payload(payload)

    @staticmethod
    def _bounty_claim_from_payload(payload: dict[str, Any], replay: bool = False) -> BountyClaimRecord:
        return BountyClaimRecord(
            player=SQLitePlayerRepository._row_to_player(payload["player"]),
            bounty_key=str(payload["bounty_key"]),
            label=str(payload["label"]),
            status=str(payload["status"]),
            progress=int(payload.get("progress", 0)),
            target=int(payload["target"]),
            rewards={str(key): int(value) for key, value in dict(payload.get("rewards", {})).items()},
            reward_labels={str(key): str(value) for key, value in dict(payload["reward_labels"]).items()},
            already_completed=replay,
        )
    async def get_mainline_status(
        self,
        *,
        platform: str,
        platform_user_id: str,
        story_key: str = MAINLINE_STORY_KEY,
    ) -> MainlineStatusRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._get_mainline_status_sync,
                platform,
                platform_user_id,
                story_key,
            )

    def _get_mainline_status_sync(
        self,
        platform: str,
        platform_user_id: str,
        story_key: str,
    ) -> MainlineStatusRecord:
        with self._connect() as connection:
            row = self._require_player(connection, platform, platform_user_id, writable=False)
            return self._mainline_status_from_connection(
                connection,
                row,
                story_key=story_key,
                content=self.content,
                now=self._now(),
            )

    @staticmethod
    def _mainline_completed_events(
        connection: sqlite3.Connection,
        player: sqlite3.Row,
        *,
        now: datetime | None = None,
    ) -> set[str]:
        """Build server-owned evidence shared by status and start checks."""

        intro = SQLitePlayerRepository._json_object(player["intro_json"], {})
        # The time-fort story flag is only a projection of a first clear.  It
        # must be rebuilt from the settlement table so a stale flag cannot
        # unlock the returner's route by itself.
        events = {
            str(item)
            for item in intro.get("flags", [])
            if str(item) != "story.mainline.void_archive.time_fort"
        }
        if str(player["stage"]) != STAGE_NEW_USER:
            events.add("player.start_seeking")
        if connection.execute(
            """
            SELECT 1
            FROM town_commission_claims
            WHERE player_id = ? AND status = 'delivered'
            LIMIT 1
            """,
            (player["id"],),
        ).fetchone() is not None:
            events.add(MAINLINE_TOWN_COMMISSION_DELIVERED)
        if connection.execute(
            "SELECT 1 FROM domain_front_participants WHERE player_id = ? LIMIT 1",
            (player["id"],),
        ).fetchone() is not None:
            events.add("event.domain_front.joined")
        if connection.execute(
            """
            SELECT 1
            FROM domain_front_battle_links AS links
            JOIN battle_sessions AS sessions ON sessions.battle_id = links.battle_id
            WHERE links.player_id = ?
              AND sessions.player_id = links.player_id
              AND sessions.battle_type = 'pve.domain_front'
              AND sessions.status = 'settled'
              AND json_extract(sessions.result_json, '$.outcome') = 'won'
            LIMIT 1
            """,
            (player["id"],),
        ).fetchone() is not None:
            events.add("event.domain_front.battle")
        if connection.execute(
            "SELECT 1 FROM domain_front_contributions WHERE player_id = ? LIMIT 1",
            (player["id"],),
        ).fetchone() is not None:
            events.add("event.domain_front.contribution")
        if connection.execute(
            "SELECT 1 FROM domain_front_claims WHERE player_id = ? LIMIT 1",
            (player["id"],),
        ).fetchone() is not None:
            events.add("event.domain_front.claimed")
        unlock_query = (
            "SELECT 1 FROM void_archive_unlocks "
            "WHERE player_id = ? AND event_key = ?"
        )
        unlock_params: tuple[Any, ...] = (player["id"], "event.archive_unlock")
        if now is not None:
            unlock_query += " AND ends_at > ?"
            unlock_params += (serialize_datetime(now),)
        if connection.execute(unlock_query, unlock_params).fetchone() is not None:
            events.add("event.archive_unlock")
        if connection.execute(
            "SELECT 1 FROM void_archive_runs WHERE player_id = ? AND outcome = 'won' LIMIT 1",
            (player["id"],),
        ).fetchone() is not None:
            events.add("event.archive_guard.won")
        if connection.execute(
            "SELECT 1 FROM time_fort_members WHERE player_id = ? AND status = 'settled' AND first_clear = 1 LIMIT 1",
            (player["id"],),
        ).fetchone() is not None:
            events.add("story.mainline.void_archive.time_fort")
        project_rows = connection.execute(
            """
            SELECT DISTINCT p.project_key
            FROM livelihood_project_rewards r
            JOIN livelihood_projects p ON p.project_id = r.project_id
            WHERE r.player_id = ? AND r.eligible = 1
            """,
            (player["id"],),
        ).fetchall()
        for project in project_rows:
            events.add(f"livelihood.project.{project['project_key']}.completed")
        return events

    @staticmethod
    def _mainline_status_from_connection(
        connection: sqlite3.Connection,
        player: sqlite3.Row,
        *,
        story_key: str = MAINLINE_STORY_KEY,
        content=None,
        replay: bool = False,
        now: datetime | None = None,
    ) -> MainlineStatusRecord:
        runs = {
            str(item["stage_key"]): item
            for item in connection.execute(
                "SELECT * FROM mainline_runs WHERE player_id = ? AND story_key = ?",
                (player["id"], story_key),
            ).fetchall()
        }
        completed_stages = {
            str(item["stage_key"])
            for item in runs.values()
            if bool(item["first_clear_claimed"])
        }
        completed_events = AdventuresRepositoryMixin._mainline_completed_events(connection, player, now=now)
        views: list[MainlineStageView] = []
        for current_definition in mainline_definitions(content, story_key=story_key):
            run = runs.get(current_definition.key)
            definition = (
                AdventuresRepositoryMixin._mainline_definition_from_snapshot(run, current_definition)
                if run is not None
                else None
            ) or current_definition
            prerequisites_met = mainline_prerequisites_met(
                definition,
                completed_stages=completed_stages,
                completed_events=completed_events,
                flags=completed_events,
                realm_key=str(player["realm_key"]),
                realm_layer=player_integer(player, "realm_layer"),
                content=content,
            )
            run_status = str(run["status"]) if run is not None else ""
            status = mainline_stage_status(
                definition,
                prerequisites_met=prerequisites_met,
                running=run_status == "running",
                cleared=run_status == "cleared",
                reward_pending=run_status == MAINLINE_REWARD_PENDING,
                claimed=run_status == "claimed",
            )
            views.append(
                MainlineStageView(
                    key=definition.key,
                    story_key=definition.story_key,
                    chapter=definition.chapter,
                    stage=definition.stage,
                    label=definition.label,
                    description=definition.description,
                    status=status,
                    first_clear_reward=definition.first_clear_reward_map(),
                    repeat_reward=definition.repeat_reward_map(),
                    completed=bool(run and run["status"] in {"cleared", "reward_pending", "claimed"}),
                    claimed=bool(run and run["status"] == "claimed"),
                )
            )
        current = next((item for item in views if not item.claimed), views[-1])
        overall = current.status
        if any(item.status == "running" for item in views):
            overall = "running"
        elif any(item.status == MAINLINE_REWARD_PENDING for item in views):
            overall = MAINLINE_REWARD_PENDING
        return MainlineStatusRecord(
            player=SQLitePlayerRepository._row_to_player(player),
            story_key=story_key,
            chapter=current.chapter,
            current_stage=current.stage,
            status=overall,
            stages=tuple(views),
            already_completed=replay,
        )

    async def start_mainline(
        self,
        *,
        platform: str,
        platform_user_id: str,
        stage_key: str,
        operation_id: str,
        story_key: str = MAINLINE_STORY_KEY,
    ) -> MainlineStartRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._start_mainline_sync,
                platform,
                platform_user_id,
                stage_key,
                operation_id,
                story_key,
            )

    def _start_mainline_sync(
        self,
        platform: str,
        platform_user_id: str,
        stage_key: str,
        operation_id: str,
        story_key: str,
    ) -> MainlineStartRecord:
        last_error: Exception | None = None
        for attempt in range(5):
            try:
                return self._start_mainline_once(
                    platform,
                    platform_user_id,
                    stage_key,
                    operation_id,
                    story_key,
                )
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).lower():
                    raise
                if attempt == 4:
                    raise RepositoryBusyError("database remained locked") from exc
                last_error = exc
                time.sleep(0.01 * (2**attempt))
        raise RepositoryBusyError("database remained locked") from last_error

    def _start_mainline_once(
        self,
        platform: str,
        platform_user_id: str,
        stage_key: str,
        operation_id: str,
        story_key: str,
    ) -> MainlineStartRecord:
        definition = mainline_definition(stage_key, story_key=story_key, content=self.content)
        operation_name = "mainline.start_stage"
        request_hash = self._request_hash(
            operation_name,
            {
                "platform": platform,
                "platform_user_id": platform_user_id,
                "stage_key": definition.key,
                "story_key": story_key,
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
                return self._mainline_start_from_payload(
                    json.loads(existing["result_json"]), replay=True
                )
            if definition.runtime_status != "open":
                raise MainlineContentClosedError("mainline stage is not open")
            row = self._require_player(connection, platform, platform_user_id)
            status_record = self._mainline_status_from_connection(
                connection,
                row,
                story_key=story_key,
                content=self.content,
                now=now,
            )
            stage_view = next(item for item in status_record.stages if item.key == definition.key)
            completed_events = self._mainline_completed_events(connection, row, now=now)
            if not mainline_prerequisites_met(
                definition,
                completed_stages={
                    item.key for item in status_record.stages if item.completed
                },
                completed_events=completed_events,
                flags=completed_events,
                realm_key=str(row["realm_key"]),
                realm_layer=player_integer(row, "realm_layer"),
                content=self.content,
            ):
                raise MainlineRequirementError("mainline prerequisites are not met")
            run = connection.execute(
                "SELECT * FROM mainline_runs WHERE player_id = ? AND story_key = ? AND stage_key = ?",
                (row["id"], story_key, definition.key),
            ).fetchone()
            if run is not None and str(run["status"]) == "running":
                raise MainlineAlreadyRunningError("mainline stage is already running")
            first_key = (
                str(run["first_clear_key"])
                if run is not None
                else mainline_first_clear_key(definition.chapter, definition.stage, str(row["player_id"]), story_key=story_key)
            )
            has_local_reputation_reward = any(
                "local_reputation" in reward
                for reward in (
                    definition.first_clear_reward_map(),
                    definition.repeat_reward_map(),
                )
            )
            if has_local_reputation_reward and not definition.reputation_key:
                raise ValueError("mainline local reputation requires a configured reputation key")
            reputation_maximum = (
                local_reputation_maximum(definition.reputation_key, self.content)
                if has_local_reputation_reward
                else None
            )
            snapshot = {
                "stage": str(row["stage"]),
                "realm_key": str(row["realm_key"]),
                "realm_layer": player_integer(row, "realm_layer"),
                "location_key": str(row["location_key"]),
                "intro_flags": list(SQLitePlayerRepository._json_object(row["intro_json"], {}).get("flags", [])),
                "definition": {
                    "key": definition.key,
                    "story_key": definition.story_key,
                    "chapter": definition.chapter,
                    "stage": definition.stage,
                    "label": definition.label,
                    "description": definition.description,
                    "first_clear_reward": definition.first_clear_reward_map(),
                    "repeat_reward": definition.repeat_reward_map(),
                    "reputation_key": definition.reputation_key,
                    "local_reputation_maximum": reputation_maximum,
                },
            }
            if run is None:
                connection.execute(
                    """
                    INSERT INTO mainline_runs(
                        player_id, story_key, chapter, stage, stage_key, status,
                        attempt_count, first_clear_claimed, first_clear_key,
                        start_operation_id, snapshot_json,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, 'running', 1, 0, ?, ?, ?, ?, ?)
                    """,
                    (
                        row["id"], story_key, definition.chapter, definition.stage,
                        definition.key, first_key, operation_id,
                        json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
                        now_text, now_text,
                    ),
                )
                first_clear = True
            else:
                connection.execute(
                    """
                    UPDATE mainline_runs
                    SET status = 'running', attempt_count = attempt_count + 1,
                        start_operation_id = ?, claim_operation_id = NULL,
                        snapshot_json = ?, result_json = '{}', updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        operation_id,
                        json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
                        now_text,
                        run["id"],
                    ),
                )
                first_clear = not bool(run["first_clear_claimed"])
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (row["id"],)).fetchone()
            if updated is None:
                raise RuntimeError("mainline start returned no player")
            payload = {
                "player": self._player_payload(self._row_to_player(updated)),
                "story_key": story_key,
                "chapter": definition.chapter,
                "stage": definition.stage,
                "stage_key": definition.key,
                "status": "running",
                "first_clear": first_clear,
                "label": definition.label,
                "description": definition.description,
            }
            connection.execute(
                """
                INSERT INTO operations(
                    operation_id, operation_name, player_id, request_hash, result_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    operation_id, operation_name, row["id"], request_hash,
                    json.dumps(payload, ensure_ascii=False, sort_keys=True), now_text,
                ),
            )
            return self._mainline_start_from_payload(payload)

    async def claim_mainline(
        self,
        *,
        platform: str,
        platform_user_id: str,
        stage_key: str,
        operation_id: str,
        story_key: str = MAINLINE_STORY_KEY,
    ) -> MainlineClaimRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._claim_mainline_sync,
                platform,
                platform_user_id,
                stage_key,
                operation_id,
                story_key,
            )

    def _claim_mainline_sync(
        self,
        platform: str,
        platform_user_id: str,
        stage_key: str,
        operation_id: str,
        story_key: str,
    ) -> MainlineClaimRecord:
        last_error: Exception | None = None
        for attempt in range(5):
            try:
                return self._claim_mainline_once(
                    platform,
                    platform_user_id,
                    stage_key,
                    operation_id,
                    story_key,
                )
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).lower():
                    raise
                if attempt == 4:
                    raise RepositoryBusyError("database remained locked") from exc
                last_error = exc
                time.sleep(0.01 * (2**attempt))
        raise RepositoryBusyError("database remained locked") from last_error

    def _claim_mainline_once(
        self,
        platform: str,
        platform_user_id: str,
        stage_key: str,
        operation_id: str,
        story_key: str,
    ) -> MainlineClaimRecord:
        definition = mainline_definition(stage_key, story_key=story_key, content=self.content)
        operation_name = "mainline.claim_first_clear"
        request_hash = self._request_hash(
            operation_name,
            {
                "platform": platform,
                "platform_user_id": platform_user_id,
                "stage_key": definition.key,
                "story_key": story_key,
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
                return self._mainline_claim_from_payload(
                    json.loads(existing["result_json"]), replay=True
                )
            row = self._require_player(connection, platform, platform_user_id)
            run = connection.execute(
                "SELECT * FROM mainline_runs WHERE player_id = ? AND story_key = ? AND stage_key = ?",
                (row["id"], story_key, definition.key),
            ).fetchone()
            if run is None or str(run["status"]) != "running":
                raise MainlineNotStartedError("mainline stage has not been started")
            frozen = self._mainline_definition_from_snapshot(run, definition)
            if frozen is None:
                raise ValueError("mainline run snapshot is invalid")
            definition = frozen
            first_clear = not bool(run["first_clear_claimed"])
            reward = mainline_reward(definition, first_clear=first_clear, content=self.content)
            connection.execute(
                "UPDATE mainline_runs SET status = ?, updated_at = ? WHERE id = ?",
                (MAINLINE_REWARD_PENDING, now_text, run["id"]),
            )
            actual_reward = self._apply_mainline_reward(
                connection,
                row,
                reward,
                operation_id,
                now_text,
                definition,
            )
            result = {
                "status": "claimed",
                "reward": actual_reward,
                "first_clear": first_clear,
                "stage_key": definition.key,
            }
            connection.execute(
                """
                UPDATE mainline_runs
                SET status = 'claimed', first_clear_claimed = CASE WHEN ? THEN 1 ELSE first_clear_claimed END,
                    claim_operation_id = ?, result_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    1 if first_clear else 0,
                    operation_id,
                    json.dumps(result, ensure_ascii=False, sort_keys=True),
                    now_text,
                    run["id"],
                ),
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (row["id"],)).fetchone()
            if updated is None:
                raise RuntimeError("mainline claim returned no player")
            payload = {
                "player": self._player_payload(self._row_to_player(updated)),
                "story_key": story_key,
                "chapter": definition.chapter,
                "stage": definition.stage,
                "stage_key": definition.key,
                "status": "claimed",
                "reward": actual_reward,
                "first_clear": first_clear,
                "label": definition.label,
                "source_operation_id": operation_id,
            }
            connection.execute(
                """
                INSERT INTO operations(
                    operation_id, operation_name, player_id, request_hash, result_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    operation_id, operation_name, row["id"], request_hash,
                    json.dumps(payload, ensure_ascii=False, sort_keys=True), now_text,
                ),
            )
            return self._mainline_claim_from_payload(payload)

    @staticmethod
    def _mainline_definition_from_snapshot(
        run: sqlite3.Row,
        current: MainlineStageDefinition,
    ) -> MainlineStageDefinition | None:
        try:
            snapshot = json.loads(run["snapshot_json"] or "{}")
            payload = snapshot.get("definition")
            if not isinstance(payload, dict):
                return None
            first_clear = payload["first_clear_reward"]
            repeat = payload["repeat_reward"]
            reputation_maximum = payload["local_reputation_maximum"]
            def valid_reward(reward: object) -> bool:
                if not isinstance(reward, dict) or not reward:
                    return False
                for reward_key, value in reward.items():
                    if not isinstance(reward_key, str) or not reward_key:
                        return False
                    if reward_key == "title_key":
                        if not isinstance(value, str) or not value.strip():
                            return False
                    elif reward_key in MAINLINE_NUMERIC_REWARD_KEYS or (
                        reward_key.startswith(MAINLINE_REWARD_PREFIXES)
                        and reward_key not in MAINLINE_REWARD_PREFIXES
                    ):
                        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                            return False
                    else:
                        return False
                return True
            if (
                payload.get("key") != current.key
                or payload.get("story_key") != current.story_key
                or payload.get("chapter") != current.chapter
                or payload.get("stage") != current.stage
                or not isinstance(payload.get("label"), str)
                or not isinstance(payload.get("description"), str)
                or not valid_reward(first_clear)
                or not valid_reward(repeat)
                or (
                    ("local_reputation" in first_clear or "local_reputation" in repeat)
                    and (
                        isinstance(reputation_maximum, bool)
                        or not isinstance(reputation_maximum, int)
                        or reputation_maximum <= 0
                    )
                )
                or (
                    "local_reputation" not in first_clear
                    and "local_reputation" not in repeat
                    and reputation_maximum is not None
                )
                or (
                    payload.get("reputation_key") is not None
                    and not isinstance(payload.get("reputation_key"), str)
                )
            ):
                return None
            return MainlineStageDefinition(
                key=current.key,
                story_key=current.story_key,
                chapter=current.chapter,
                stage=current.stage,
                label=payload["label"].strip(),
                description=payload["description"].strip(),
                prerequisites=current.prerequisites,
                alternative_prerequisites=current.alternative_prerequisites,
                required_realm=current.required_realm,
                required_layer=current.required_layer,
                first_clear_reward=tuple((str(key), value) for key, value in first_clear.items()),
                repeat_reward=tuple((str(key), value) for key, value in repeat.items()),
                runtime_status="open",
                aliases=current.aliases,
                reputation_key=payload.get("reputation_key"),
                local_reputation_maximum=reputation_maximum,
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return None

    @staticmethod
    def _apply_mainline_reward(
        connection: sqlite3.Connection,
        player: sqlite3.Row,
        reward: dict[str, int | str],
        operation_id: str,
        now_text: str,
        definition: Any,
    ) -> dict[str, int | str]:
        asset_rewards: dict[str, int] = {}
        local_delta = 0
        service_delta = 0
        actual: dict[str, int | str] = {}
        event_keys: list[str] = [
            f"{definition.story_key}:chapter.{definition.chapter}.stage.{definition.stage}"
        ]
        for key, raw_value in reward.items():
            key = str(key)
            if key == "spirit_stones":
                quantity = int(raw_value)
                asset_rewards[key] = quantity
                actual[key] = quantity
            elif key == "local_reputation":
                local_delta += int(raw_value)
            elif key == "service_reputation":
                service_delta += int(raw_value)
            elif key == "title_key":
                title_key = str(raw_value)
                title = honor_title(title_key)
                if title.closed:
                    raise MainlineContentClosedError("mainline title is not open")
                grant_player_honor_title(
                    connection,
                    int(player["id"]),
                    title_key,
                    operation_id,
                    now_text,
                )
                actual[key] = title_key
            elif key.startswith("item."):
                quantity = int(raw_value)
                asset_rewards[key] = quantity
                actual[key] = quantity
            elif key.startswith("access.") or key.startswith("codex."):
                quantity = int(raw_value)
                actual[key] = quantity
                event_keys.append(key)
            else:
                raise ValueError(f"unsupported mainline reward: {key}")
        reputation_before = (
            player_reputation_state(connection, int(player["id"]))
            if local_delta or service_delta
            else None
        )
        local_delta_map = None
        local_maximums = None
        if local_delta:
            if not definition.reputation_key or definition.local_reputation_maximum is None:
                raise ValueError("mainline local reputation requires a frozen location maximum")
            local_delta_map = {definition.reputation_key: local_delta}
            local_maximums = {
                definition.reputation_key: definition.local_reputation_maximum
            }
        if asset_rewards or local_delta or service_delta:
            grant_player_state(
                connection,
                player,
                asset_rewards or None,
                now_text,
                local_reputation_delta=local_delta_map,
                local_reputation_maximums=local_maximums,
                service_reputation_delta=service_delta if service_delta else None,
            )
        if reputation_before is not None:
            reputation_after = player_reputation_state(connection, int(player["id"]))
            if local_delta_map:
                reputation_key = definition.reputation_key
                assert reputation_key is not None
                local_actual = (
                    reputation_after.local.get(reputation_key, 0)
                    - reputation_before.local.get(reputation_key, 0)
                )
                if local_actual:
                    actual["local_reputation"] = local_actual
            if service_delta:
                service_actual = reputation_after.service - reputation_before.service
                if service_actual:
                    actual["service_reputation"] = service_actual
        for event_key in event_keys:
            connection.execute(
                """
                INSERT OR IGNORE INTO activity_events(
                    player_id, event_key, source_operation_id, occurred_at, payload_json
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    player["id"], event_key, operation_id, now_text,
                    json.dumps({"stage_key": definition.key}, ensure_ascii=False, sort_keys=True),
                ),
            )
        return actual

    @staticmethod
    def _mainline_start_from_payload(
        payload: dict[str, Any], replay: bool = False
    ) -> MainlineStartRecord:
        return MainlineStartRecord(
            player=SQLitePlayerRepository._row_to_player(payload["player"]),
            story_key=str(payload["story_key"]),
            chapter=int(payload["chapter"]),
            stage=int(payload["stage"]),
            stage_key=str(payload["stage_key"]),
            status=str(payload["status"]),
            first_clear=bool(payload.get("first_clear", True)),
            label=str(payload.get("label", "")),
            description=str(payload.get("description", "")),
            already_completed=replay,
        )

    @staticmethod
    def _mainline_claim_from_payload(
        payload: dict[str, Any], replay: bool = False
    ) -> MainlineClaimRecord:
        return MainlineClaimRecord(
            player=SQLitePlayerRepository._row_to_player(payload["player"]),
            story_key=str(payload["story_key"]),
            chapter=int(payload["chapter"]),
            stage=int(payload["stage"]),
            stage_key=str(payload["stage_key"]),
            status=str(payload["status"]),
            reward=dict(payload.get("reward", {})),
            first_clear=bool(payload.get("first_clear", True)),
            label=str(payload.get("label", "")),
            source_operation_id=payload.get("source_operation_id"),
            already_completed=replay,
        )
