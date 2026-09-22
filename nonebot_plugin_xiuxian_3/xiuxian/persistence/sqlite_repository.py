"""SQLite persistence for player identity and the first idempotent operation."""

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


SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS players (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id TEXT NOT NULL UNIQUE,
    platform TEXT NOT NULL,
    platform_user_id TEXT NOT NULL,
    scene_id TEXT NOT NULL DEFAULT '',
    nickname TEXT NOT NULL DEFAULT '',
    dao_name TEXT NOT NULL DEFAULT '',
    stage TEXT NOT NULL CHECK (stage IN ('new_user', 'mortal', 'seeker', 'cultivator', 'suspended')),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'suspended', 'deleted')),
    location_key TEXT NOT NULL DEFAULT 'xuantian.new_town',
    rule_version TEXT NOT NULL DEFAULT 'player-onboarding-v0.1.0',
    path_key TEXT,
    subprofession_key TEXT,
    qualification_json TEXT NOT NULL DEFAULT '{}',
    spirit_stones INTEGER NOT NULL DEFAULT 0 CHECK (spirit_stones >= 0),
    stamina INTEGER NOT NULL DEFAULT 0 CHECK (stamina >= 0),
    stamina_max INTEGER NOT NULL DEFAULT 0 CHECK (stamina_max >= 0),
    energy INTEGER NOT NULL DEFAULT 0 CHECK (energy >= 0),
    energy_max INTEGER NOT NULL DEFAULT 0 CHECK (energy_max >= 0),
    inventory_json TEXT NOT NULL DEFAULT '{}',
    intro_json TEXT NOT NULL DEFAULT '{}',
    selected_service TEXT,
    realm_key TEXT NOT NULL DEFAULT 'mortal',
    realm_layer INTEGER NOT NULL DEFAULT 0 CHECK (realm_layer >= 0),
    cultivation INTEGER NOT NULL DEFAULT 0 CHECK (cultivation >= 0),
    total_cultivation INTEGER NOT NULL DEFAULT 0 CHECK (total_cultivation >= 0),
    foundation_quality INTEGER NOT NULL DEFAULT 0 CHECK (foundation_quality >= 0),
    world_merit INTEGER NOT NULL DEFAULT 0 CHECK (world_merit >= 0),
    talent_points INTEGER NOT NULL DEFAULT 0 CHECK (talent_points >= 0),
    skill_insights INTEGER NOT NULL DEFAULT 0 CHECK (skill_insights >= 0),
    weakness_until TEXT,
    breakthrough_pity_bp INTEGER NOT NULL DEFAULT 0 CHECK (breakthrough_pity_bp >= 0),
    soul_power INTEGER NOT NULL DEFAULT 0 CHECK (soul_power >= 0),
    soul_power_max INTEGER NOT NULL DEFAULT 0 CHECK (soul_power_max >= 0),
    domain_charge INTEGER NOT NULL DEFAULT 0 CHECK (domain_charge >= 0),
    domain_charge_max INTEGER NOT NULL DEFAULT 0 CHECK (domain_charge_max >= 0),
    pollution INTEGER NOT NULL DEFAULT 0 CHECK (pollution >= 0),
    bloodline_stability INTEGER NOT NULL DEFAULT 0 CHECK (bloodline_stability >= 0),
    cross_realm_penalty_bp INTEGER NOT NULL DEFAULT 0 CHECK (cross_realm_penalty_bp >= 0),
    soul_fatigue_until TEXT,
    heart_demon_bonus_bp INTEGER NOT NULL DEFAULT 0 CHECK (heart_demon_bonus_bp >= 0),
    max_hp INTEGER NOT NULL DEFAULT 0 CHECK (max_hp >= 0),
    max_mp INTEGER NOT NULL DEFAULT 0 CHECK (max_mp >= 0),
    carry_capacity INTEGER NOT NULL DEFAULT 0 CHECK (carry_capacity >= 0),
    exploration_efficiency_bp INTEGER NOT NULL DEFAULT 0 CHECK (exploration_efficiency_bp >= 0),
    domain_key TEXT,
    domain_power INTEGER NOT NULL DEFAULT 0 CHECK (domain_power >= 0),
    realm_resistance_bp INTEGER NOT NULL DEFAULT 0 CHECK (realm_resistance_bp >= 0),
    domain_crack_until TEXT,
    initiative INTEGER NOT NULL DEFAULT 0 CHECK (initiative >= 0),
    faction_reputation_json TEXT NOT NULL DEFAULT '{}',
    domain_charge_reset_date TEXT,
    void_power INTEGER NOT NULL DEFAULT 0 CHECK (void_power >= 0),
    void_power_max INTEGER NOT NULL DEFAULT 0 CHECK (void_power_max >= 0),
    space_resistance_bp INTEGER NOT NULL DEFAULT 0 CHECK (space_resistance_bp >= 0),
    void_instability_until TEXT,
    void_route_count INTEGER NOT NULL DEFAULT 0 CHECK (void_route_count >= 0),
    void_anchor_capacity INTEGER NOT NULL DEFAULT 0 CHECK (void_anchor_capacity >= 0),
    void_power_reset_date TEXT,
    dao_fruit_progress INTEGER NOT NULL DEFAULT 0 CHECK (dao_fruit_progress >= 0),
    ascension_merit INTEGER NOT NULL DEFAULT 0 CHECK (ascension_merit >= 0),
    tribulation_debt INTEGER NOT NULL DEFAULT 0 CHECK (tribulation_debt >= 0),
    dao_fruit_key TEXT,
    endgame_status TEXT NOT NULL DEFAULT 'none',
    ending_key TEXT,
    durability_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (platform, platform_user_id)
);

CREATE TABLE IF NOT EXISTS operations (
    operation_id TEXT PRIMARY KEY,
    operation_name TEXT NOT NULL,
    player_id INTEGER NOT NULL REFERENCES players(id),
    request_hash TEXT NOT NULL DEFAULT '',
    result_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_players_scene ON players(scene_id);
CREATE INDEX IF NOT EXISTS idx_operations_player ON operations(player_id);

CREATE TABLE IF NOT EXISTS cultivation_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL UNIQUE,
    player_id INTEGER NOT NULL REFERENCES players(id),
    operation_id TEXT NOT NULL UNIQUE,
    mode_key TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('running', 'settled', 'cancelled', 'expired')),
    starts_at TEXT NOT NULL,
    ends_at TEXT NOT NULL,
    stamina_cost INTEGER NOT NULL DEFAULT 0 CHECK (stamina_cost >= 0),
    snapshot_json TEXT NOT NULL DEFAULT '{}',
    result_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_cultivation_sessions_player ON cultivation_sessions(player_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_cultivation_sessions_active
    ON cultivation_sessions(player_id) WHERE status = 'running';

CREATE TABLE IF NOT EXISTS retreat_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL UNIQUE,
    player_id INTEGER NOT NULL REFERENCES players(id),
    operation_id TEXT NOT NULL UNIQUE,
    retreat_key TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('running', 'settled', 'expired')),
    starts_at TEXT NOT NULL,
    ends_at TEXT NOT NULL,
    energy_cost INTEGER NOT NULL DEFAULT 0 CHECK (energy_cost >= 0),
    item_cost_json TEXT NOT NULL DEFAULT '{}',
    snapshot_json TEXT NOT NULL DEFAULT '{}',
    result_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_retreat_sessions_player
    ON retreat_sessions(player_id, retreat_key, starts_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_retreat_sessions_active
    ON retreat_sessions(player_id) WHERE status = 'running';

CREATE TABLE IF NOT EXISTS residences (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    residence_id TEXT NOT NULL UNIQUE,
    player_id INTEGER NOT NULL REFERENCES players(id),
    operation_id TEXT NOT NULL UNIQUE,
    residence_key TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('active', 'expired')),
    starts_at TEXT NOT NULL,
    ends_at TEXT NOT NULL,
    rent_cost INTEGER NOT NULL CHECK (rent_cost >= 0),
    snapshot_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_residences_player ON residences(player_id, ends_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_residences_active ON residences(player_id) WHERE status = 'active';

CREATE TABLE IF NOT EXISTS constitution_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id TEXT NOT NULL UNIQUE,
    player_id INTEGER NOT NULL UNIQUE REFERENCES players(id),
    operation_id TEXT NOT NULL UNIQUE,
    constitution_key TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('selected')),
    selected_at TEXT NOT NULL,
    last_reshaped_at TEXT,
    reshape_count INTEGER NOT NULL DEFAULT 0 CHECK (reshape_count >= 0),
    snapshot_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_constitution_profiles_player
    ON constitution_profiles(player_id, updated_at);

CREATE TABLE IF NOT EXISTS talent_node_states (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id TEXT NOT NULL UNIQUE,
    player_id INTEGER NOT NULL REFERENCES players(id),
    operation_id TEXT NOT NULL UNIQUE,
    node_key TEXT NOT NULL,
    tree_key TEXT NOT NULL,
    tier INTEGER NOT NULL CHECK (tier BETWEEN 1 AND 5),
    status TEXT NOT NULL CHECK (status IN ('learned')),
    cost_points INTEGER NOT NULL CHECK (cost_points >= 0),
    snapshot_json TEXT NOT NULL DEFAULT '{}',
    unlocked_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (player_id, node_key)
);

CREATE INDEX IF NOT EXISTS idx_talent_node_states_player
    ON talent_node_states(player_id, tree_key, tier);
CREATE UNIQUE INDEX IF NOT EXISTS idx_talent_node_states_one_per_tier
    ON talent_node_states(player_id, tree_key, tier) WHERE status = 'learned';

CREATE TABLE IF NOT EXISTS talent_point_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    player_id INTEGER NOT NULL REFERENCES players(id),
    operation_id TEXT NOT NULL UNIQUE,
    delta INTEGER NOT NULL CHECK (delta <> 0),
    balance_before INTEGER NOT NULL CHECK (balance_before >= 0),
    balance_after INTEGER NOT NULL CHECK (balance_after >= 0),
    reason TEXT NOT NULL,
    content_version TEXT NOT NULL,
    rule_version TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_talent_point_events_player
    ON talent_point_events(player_id, created_at);

CREATE TABLE IF NOT EXISTS skill_masteries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mastery_id TEXT NOT NULL UNIQUE,
    player_id INTEGER NOT NULL REFERENCES players(id),
    operation_id TEXT NOT NULL UNIQUE,
    skill_key TEXT NOT NULL,
    path_key TEXT,
    level INTEGER NOT NULL CHECK (level BETWEEN 1 AND 3),
    max_level INTEGER NOT NULL CHECK (max_level = 3),
    snapshot_json TEXT NOT NULL DEFAULT '{}',
    trained_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (player_id, skill_key)
);

CREATE INDEX IF NOT EXISTS idx_skill_masteries_player
    ON skill_masteries(player_id, skill_key);

CREATE TABLE IF NOT EXISTS skill_insight_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    player_id INTEGER NOT NULL REFERENCES players(id),
    operation_id TEXT NOT NULL UNIQUE,
    delta INTEGER NOT NULL CHECK (delta <> 0),
    balance_before INTEGER NOT NULL CHECK (balance_before >= 0),
    balance_after INTEGER NOT NULL CHECK (balance_after >= 0),
    reason TEXT NOT NULL,
    content_version TEXT NOT NULL,
    rule_version TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_skill_insight_events_player
    ON skill_insight_events(player_id, created_at);

CREATE TABLE IF NOT EXISTS equipment_instances (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    instance_id TEXT NOT NULL UNIQUE,
    player_id INTEGER NOT NULL REFERENCES players(id),
    item_key TEXT NOT NULL,
    label TEXT NOT NULL,
    slot TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('active', 'broken', 'archived')),
    durability_bp INTEGER NOT NULL CHECK (durability_bp >= 0),
    temper_level INTEGER NOT NULL CHECK (temper_level BETWEEN 0 AND 3),
    max_temper_level INTEGER NOT NULL CHECK (max_temper_level = 3),
    affixes_json TEXT NOT NULL DEFAULT '{}',
    refinement_failure_streak INTEGER NOT NULL DEFAULT 0 CHECK (refinement_failure_streak >= 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (player_id, instance_id)
);

CREATE INDEX IF NOT EXISTS idx_equipment_instances_player
    ON equipment_instances(player_id, item_key, status);

CREATE TABLE IF NOT EXISTS equipment_tempering_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    player_id INTEGER NOT NULL REFERENCES players(id),
    equipment_id INTEGER NOT NULL REFERENCES equipment_instances(id),
    operation_id TEXT NOT NULL UNIQUE,
    from_level INTEGER NOT NULL CHECK (from_level >= 0),
    to_level INTEGER NOT NULL CHECK (to_level >= 1),
    success INTEGER NOT NULL CHECK (success IN (0, 1)),
    roll_bp INTEGER NOT NULL CHECK (roll_bp BETWEEN 0 AND 9999),
    success_bp INTEGER NOT NULL CHECK (success_bp BETWEEN 0 AND 10000),
    material_key TEXT NOT NULL,
    material_spent INTEGER NOT NULL CHECK (material_spent >= 0),
    spirit_stones_spent INTEGER NOT NULL CHECK (spirit_stones_spent >= 0),
    snapshot_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_equipment_tempering_events_player
    ON equipment_tempering_events(player_id, created_at);

CREATE TABLE IF NOT EXISTS equipment_refinement_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    player_id INTEGER NOT NULL REFERENCES players(id),
    equipment_id INTEGER NOT NULL REFERENCES equipment_instances(id),
    operation_id TEXT NOT NULL UNIQUE,
    success INTEGER NOT NULL CHECK (success IN (0, 1)),
    roll_bp INTEGER NOT NULL CHECK (roll_bp BETWEEN 0 AND 9999),
    success_bp INTEGER NOT NULL CHECK (success_bp BETWEEN 0 AND 10000),
    material_key TEXT NOT NULL,
    material_spent INTEGER NOT NULL CHECK (material_spent >= 0),
    spirit_stones_spent INTEGER NOT NULL CHECK (spirit_stones_spent >= 0),
    old_affixes_json TEXT NOT NULL DEFAULT '{}',
    new_affixes_json TEXT NOT NULL DEFAULT '{}',
    failure_streak_before INTEGER NOT NULL CHECK (failure_streak_before >= 0),
    failure_streak_after INTEGER NOT NULL CHECK (failure_streak_after >= 0),
    snapshot_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_equipment_refinement_events_player
    ON equipment_refinement_events(player_id, created_at);

CREATE TABLE IF NOT EXISTS production_orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id TEXT NOT NULL UNIQUE,
    player_id INTEGER NOT NULL REFERENCES players(id),
    operation_id TEXT NOT NULL UNIQUE,
    recipe_key TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('processing', 'completed', 'failed', 'cancelled', 'expired')),
    starts_at TEXT NOT NULL,
    ends_at TEXT NOT NULL,
    energy_cost INTEGER NOT NULL DEFAULT 0 CHECK (energy_cost >= 0),
    currency_cost INTEGER NOT NULL DEFAULT 0 CHECK (currency_cost >= 0),
    snapshot_json TEXT NOT NULL DEFAULT '{}',
    result_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_production_orders_player ON production_orders(player_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_production_orders_active
    ON production_orders(player_id) WHERE status = 'processing';

CREATE TABLE IF NOT EXISTS breakthrough_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL UNIQUE,
    player_id INTEGER NOT NULL REFERENCES players(id),
    operation_id TEXT NOT NULL UNIQUE,
    target_realm TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('preparing', 'succeeded', 'failed', 'expired')),
    starts_at TEXT NOT NULL,
    ends_at TEXT NOT NULL,
    snapshot_json TEXT NOT NULL DEFAULT '{}',
    result_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_breakthrough_sessions_player ON breakthrough_sessions(player_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_breakthrough_sessions_active
    ON breakthrough_sessions(player_id) WHERE status = 'preparing';

CREATE TABLE IF NOT EXISTS heart_demon_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL UNIQUE,
    player_id INTEGER NOT NULL REFERENCES players(id),
    breakthrough_session_id INTEGER NOT NULL REFERENCES breakthrough_sessions(id),
    operation_id TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL CHECK (status IN ('pending', 'resolved')),
    choice_key TEXT,
    expires_at TEXT NOT NULL,
    snapshot_json TEXT NOT NULL DEFAULT '{}',
    result_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_heart_demon_sessions_player
    ON heart_demon_sessions(player_id, status);

CREATE TABLE IF NOT EXISTS domain_selection_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL UNIQUE,
    player_id INTEGER NOT NULL REFERENCES players(id),
    operation_id TEXT NOT NULL UNIQUE,
    domain_key TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'confirmed', 'cancelled', 'expired')),
    starts_at TEXT NOT NULL,
    ends_at TEXT NOT NULL,
    snapshot_json TEXT NOT NULL DEFAULT '{}',
    result_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_domain_selection_sessions_player
    ON domain_selection_sessions(player_id, status);
CREATE UNIQUE INDEX IF NOT EXISTS idx_domain_selection_sessions_active
    ON domain_selection_sessions(player_id) WHERE status = 'pending';

CREATE TABLE IF NOT EXISTS travel_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL UNIQUE,
    player_id INTEGER NOT NULL REFERENCES players(id),
    operation_id TEXT NOT NULL UNIQUE,
    source_location TEXT NOT NULL,
    destination TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('running', 'arrived', 'cancelled', 'expired')),
    starts_at TEXT NOT NULL,
    ends_at TEXT NOT NULL,
    stamina_cost INTEGER NOT NULL DEFAULT 0 CHECK (stamina_cost >= 0),
    currency_cost INTEGER NOT NULL DEFAULT 0 CHECK (currency_cost >= 0),
    pass_key TEXT,
    pass_quantity INTEGER NOT NULL DEFAULT 0 CHECK (pass_quantity >= 0),
    snapshot_json TEXT NOT NULL DEFAULT '{}',
    result_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_travel_sessions_player ON travel_sessions(player_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_travel_sessions_active
    ON travel_sessions(player_id) WHERE status = 'running';

CREATE TABLE IF NOT EXISTS exploration_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    exploration_id TEXT NOT NULL UNIQUE,
    player_id INTEGER NOT NULL REFERENCES players(id),
    operation_id TEXT NOT NULL UNIQUE,
    mode_key TEXT NOT NULL,
    location_key TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('created', 'running', 'settled', 'cancelled', 'expired', 'combat_pending')),
    starts_at TEXT NOT NULL,
    ends_at TEXT NOT NULL,
    stamina_cost INTEGER NOT NULL DEFAULT 0 CHECK (stamina_cost >= 0),
    daily_limit INTEGER NOT NULL DEFAULT 0 CHECK (daily_limit >= 0),
    business_date TEXT NOT NULL,
    snapshot_json TEXT NOT NULL DEFAULT '{}',
    result_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_exploration_sessions_player ON exploration_sessions(player_id);
CREATE INDEX IF NOT EXISTS idx_exploration_sessions_quota
    ON exploration_sessions(player_id, mode_key, business_date);
CREATE UNIQUE INDEX IF NOT EXISTS idx_exploration_sessions_active
    ON exploration_sessions(player_id) WHERE status IN ('created', 'running', 'combat_pending');

CREATE TABLE IF NOT EXISTS player_reputations (
    player_id INTEGER PRIMARY KEY REFERENCES players(id),
    local_json TEXT NOT NULL DEFAULT '{}',
    service_reputation INTEGER NOT NULL DEFAULT 0 CHECK (service_reputation >= 0 AND service_reputation <= 100),
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS bounty_offers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    offer_id TEXT NOT NULL UNIQUE,
    player_id INTEGER NOT NULL REFERENCES players(id),
    operation_id TEXT NOT NULL UNIQUE,
    bounty_key TEXT NOT NULL,
    business_date TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('accepted', 'completed', 'claimed', 'expired')),
    accepted_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    snapshot_json TEXT NOT NULL DEFAULT '{}',
    result_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (player_id, business_date)
);

CREATE INDEX IF NOT EXISTS idx_bounty_offers_player ON bounty_offers(player_id, business_date);
CREATE INDEX IF NOT EXISTS idx_bounty_offers_status ON bounty_offers(player_id, status);

CREATE TABLE IF NOT EXISTS routine_checkins (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES players(id),
    activity_key TEXT NOT NULL,
    target_date TEXT NOT NULL,
    claim_kind TEXT NOT NULL CHECK (claim_kind IN ('daily', 'makeup')),
    month_key TEXT NOT NULL,
    operation_id TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL CHECK (status IN ('claimed', 'expired')),
    cost_json TEXT NOT NULL DEFAULT '{}',
    reward_json TEXT NOT NULL DEFAULT '{}',
    streak_before INTEGER NOT NULL DEFAULT 0 CHECK (streak_before >= 0),
    streak_after INTEGER NOT NULL DEFAULT 0 CHECK (streak_after >= 0),
    content_version TEXT NOT NULL,
    rule_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    settled_at TEXT NOT NULL,
    UNIQUE (player_id, target_date)
);

CREATE INDEX IF NOT EXISTS idx_routine_checkins_player_date
    ON routine_checkins(player_id, target_date);
CREATE INDEX IF NOT EXISTS idx_routine_checkins_makeup_month
    ON routine_checkins(player_id, claim_kind, month_key);

CREATE TABLE IF NOT EXISTS spirit_trees (
    player_id INTEGER PRIMARY KEY REFERENCES players(id),
    cycle_no INTEGER NOT NULL DEFAULT 1 CHECK (cycle_no >= 1),
    water_count INTEGER NOT NULL DEFAULT 0 CHECK (water_count >= 0 AND water_count <= 7),
    last_water_date TEXT,
    cycle_started_at TEXT,
    cooldown_until TEXT,
    snapshot_json TEXT NOT NULL DEFAULT '{}',
    result_json TEXT NOT NULL DEFAULT '{}',
    content_version TEXT NOT NULL,
    rule_version TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS spirit_tree_waterings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES players(id),
    cycle_no INTEGER NOT NULL CHECK (cycle_no >= 1),
    business_date TEXT NOT NULL,
    operation_id TEXT NOT NULL UNIQUE,
    result_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    UNIQUE (player_id, cycle_no, business_date)
);

CREATE TABLE IF NOT EXISTS spirit_tree_harvests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES players(id),
    cycle_no INTEGER NOT NULL CHECK (cycle_no >= 1),
    operation_id TEXT NOT NULL UNIQUE,
    pool_key TEXT NOT NULL,
    seed TEXT NOT NULL,
    reward_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    UNIQUE (player_id, cycle_no)
);

CREATE INDEX IF NOT EXISTS idx_spirit_tree_waterings_player
    ON spirit_tree_waterings(player_id, cycle_no, business_date);

CREATE TABLE IF NOT EXISTS activity_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES players(id),
    event_key TEXT NOT NULL,
    source_operation_id TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE (player_id, event_key, source_operation_id)
);

CREATE INDEX IF NOT EXISTS idx_activity_events_player_key
    ON activity_events(player_id, event_key, occurred_at);

CREATE TABLE IF NOT EXISTS seven_day_campaigns (
    player_id INTEGER PRIMARY KEY REFERENCES players(id),
    start_date TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('active', 'completed', 'closed')),
    content_version TEXT NOT NULL,
    rule_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS seven_day_goal_claims (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES players(id),
    day_number INTEGER NOT NULL CHECK (day_number BETWEEN 1 AND 7),
    goal_key TEXT NOT NULL,
    target_date TEXT NOT NULL,
    source_operation_id TEXT NOT NULL,
    operation_id TEXT NOT NULL UNIQUE,
    reward_json TEXT NOT NULL DEFAULT '{}',
    content_version TEXT NOT NULL,
    rule_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (player_id, day_number),
    UNIQUE (player_id, source_operation_id)
);

CREATE INDEX IF NOT EXISTS idx_seven_day_claims_player
    ON seven_day_goal_claims(player_id, day_number);

CREATE TABLE IF NOT EXISTS honor_titles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES players(id),
    title_key TEXT NOT NULL,
    source_operation_id TEXT NOT NULL,
    acquired_at TEXT NOT NULL,
    content_version TEXT NOT NULL,
    rule_version TEXT NOT NULL,
    UNIQUE (player_id, title_key),
    UNIQUE (player_id, source_operation_id)
);

CREATE INDEX IF NOT EXISTS idx_honor_titles_player
    ON honor_titles(player_id, acquired_at);

CREATE TABLE IF NOT EXISTS honor_states (
    player_id INTEGER PRIMARY KEY REFERENCES players(id),
    equipped_title_key TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS achievement_claims (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES players(id),
    achievement_key TEXT NOT NULL,
    source_operation_id TEXT NOT NULL,
    operation_id TEXT NOT NULL UNIQUE,
    reward_json TEXT NOT NULL DEFAULT '{}',
    content_version TEXT NOT NULL,
    rule_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (player_id, achievement_key),
    UNIQUE (player_id, source_operation_id)
);

CREATE INDEX IF NOT EXISTS idx_achievement_claims_player
    ON achievement_claims(player_id, created_at);

CREATE TABLE IF NOT EXISTS redemption_codes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code_key TEXT NOT NULL UNIQUE,
    code_hash TEXT NOT NULL UNIQUE,
    max_claims INTEGER NOT NULL CHECK (max_claims > 0),
    claimed_count INTEGER NOT NULL DEFAULT 0 CHECK (claimed_count >= 0),
    starts_on TEXT,
    ends_on TEXT,
    status TEXT NOT NULL CHECK (status IN ('active', 'revoked')),
    reward_json TEXT NOT NULL DEFAULT '{}',
    content_version TEXT NOT NULL,
    rule_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS redemption_claims (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES players(id),
    code_id INTEGER NOT NULL REFERENCES redemption_codes(id),
    code_key TEXT NOT NULL,
    operation_id TEXT NOT NULL UNIQUE,
    reward_json TEXT NOT NULL DEFAULT '{}',
    content_version TEXT NOT NULL,
    rule_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (player_id, code_id)
);

CREATE INDEX IF NOT EXISTS idx_redemption_claims_player
    ON redemption_claims(player_id, created_at);

CREATE TABLE IF NOT EXISTS fate_pools (
    player_id INTEGER NOT NULL REFERENCES players(id),
    pool_key TEXT NOT NULL,
    pity_count INTEGER NOT NULL DEFAULT 0 CHECK (pity_count >= 0 AND pity_count < 10),
    total_draws INTEGER NOT NULL DEFAULT 0 CHECK (total_draws >= 0),
    content_version TEXT NOT NULL,
    rule_version TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (player_id, pool_key)
);

CREATE TABLE IF NOT EXISTS fate_rolls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES players(id),
    pool_key TEXT NOT NULL,
    operation_id TEXT NOT NULL UNIQUE,
    draw_count INTEGER NOT NULL CHECK (draw_count IN (1, 10)),
    cost_kind TEXT NOT NULL CHECK (cost_kind IN ('spirit_stones', 'ticket')),
    cost_quantity INTEGER NOT NULL CHECK (cost_quantity > 0),
    pity_before INTEGER NOT NULL CHECK (pity_before >= 0 AND pity_before < 10),
    pity_after INTEGER NOT NULL CHECK (pity_after >= 0 AND pity_after < 10),
    seed_hash TEXT NOT NULL,
    reward_json TEXT NOT NULL DEFAULT '{}',
    draws_json TEXT NOT NULL DEFAULT '[]',
    content_version TEXT NOT NULL,
    rule_version TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_fate_rolls_player
    ON fate_rolls(player_id, pool_key, created_at);

CREATE TABLE IF NOT EXISTS wayfaring_passes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES players(id),
    pass_key TEXT NOT NULL,
    cycle_start TEXT NOT NULL,
    cycle_end TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('active', 'completed', 'closed')),
    total_points INTEGER NOT NULL DEFAULT 0 CHECK (total_points >= 0),
    daily_date TEXT NOT NULL,
    daily_points INTEGER NOT NULL DEFAULT 0 CHECK (daily_points >= 0),
    week_start TEXT NOT NULL,
    weekly_points INTEGER NOT NULL DEFAULT 0 CHECK (weekly_points >= 0),
    claimed_free_json TEXT NOT NULL DEFAULT '[]',
    claimed_paid_json TEXT NOT NULL DEFAULT '[]',
    content_version TEXT NOT NULL,
    rule_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (player_id, pass_key, cycle_start)
);

CREATE INDEX IF NOT EXISTS idx_wayfaring_passes_player
    ON wayfaring_passes(player_id, pass_key, cycle_start);

CREATE TABLE IF NOT EXISTS wayfaring_point_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES players(id),
    pass_id INTEGER NOT NULL REFERENCES wayfaring_passes(id),
    source_key TEXT NOT NULL,
    source_operation_id TEXT NOT NULL,
    business_date TEXT NOT NULL,
    week_start TEXT NOT NULL,
    points INTEGER NOT NULL CHECK (points >= 0),
    created_at TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE (player_id, pass_id, source_operation_id)
);

CREATE INDEX IF NOT EXISTS idx_wayfaring_point_events_pass
    ON wayfaring_point_events(pass_id, business_date, week_start);

CREATE TABLE IF NOT EXISTS wayfaring_claims (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES players(id),
    pass_id INTEGER NOT NULL REFERENCES wayfaring_passes(id),
    level INTEGER NOT NULL CHECK (level BETWEEN 1 AND 30),
    track TEXT NOT NULL CHECK (track IN ('free', 'paid')),
    operation_id TEXT NOT NULL UNIQUE,
    reward_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    UNIQUE (player_id, pass_id, level, track)
);

CREATE INDEX IF NOT EXISTS idx_wayfaring_claims_player
    ON wayfaring_claims(player_id, pass_id, level);

CREATE TABLE IF NOT EXISTS dao_contracts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES players(id),
    contract_key TEXT NOT NULL,
    receipt_id TEXT NOT NULL UNIQUE,
    receipt_hash TEXT NOT NULL UNIQUE,
    subject TEXT NOT NULL,
    starts_on TEXT NOT NULL,
    ends_on TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('active', 'revoked', 'expired')),
    revoke_reason TEXT,
    content_version TEXT NOT NULL,
    rule_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (player_id, contract_key, starts_on)
);

CREATE INDEX IF NOT EXISTS idx_dao_contracts_player
    ON dao_contracts(player_id, status, ends_on);

CREATE TABLE IF NOT EXISTS dao_contract_claims (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES players(id),
    contract_id INTEGER NOT NULL REFERENCES dao_contracts(id),
    contract_key TEXT NOT NULL,
    business_date TEXT NOT NULL,
    operation_id TEXT NOT NULL UNIQUE,
    reward_json TEXT NOT NULL DEFAULT '{}',
    content_version TEXT NOT NULL,
    rule_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (contract_id, business_date)
);

CREATE INDEX IF NOT EXISTS idx_dao_contract_claims_player
    ON dao_contract_claims(player_id, business_date);

CREATE TABLE IF NOT EXISTS mainline_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL REFERENCES players(id),
    story_key TEXT NOT NULL,
    chapter INTEGER NOT NULL CHECK (chapter >= 1),
    stage INTEGER NOT NULL CHECK (stage >= 1),
    stage_key TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('locked', 'available', 'running', 'cleared', 'reward_pending', 'claimed')),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    first_clear_claimed INTEGER NOT NULL DEFAULT 0 CHECK (first_clear_claimed IN (0, 1)),
    first_clear_key TEXT NOT NULL UNIQUE,
    start_operation_id TEXT,
    claim_operation_id TEXT,
    snapshot_json TEXT NOT NULL DEFAULT '{}',
    result_json TEXT NOT NULL DEFAULT '{}',
    content_version TEXT NOT NULL,
    rule_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (player_id, story_key, stage_key)
);

CREATE INDEX IF NOT EXISTS idx_mainline_runs_player
    ON mainline_runs(player_id, story_key, chapter, stage);
CREATE INDEX IF NOT EXISTS idx_mainline_runs_status
    ON mainline_runs(player_id, status);

CREATE TABLE IF NOT EXISTS void_route_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL UNIQUE,
    player_id INTEGER NOT NULL REFERENCES players(id),
    operation_id TEXT NOT NULL UNIQUE,
    route_key TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('running', 'settled', 'failed')),
    starts_at TEXT NOT NULL,
    ends_at TEXT NOT NULL,
    anchor_cost INTEGER NOT NULL CHECK (anchor_cost >= 1),
    stamina_cost INTEGER NOT NULL CHECK (stamina_cost >= 0),
    snapshot_json TEXT NOT NULL DEFAULT '{}',
    result_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_void_route_sessions_player ON void_route_sessions(player_id, status);
CREATE UNIQUE INDEX IF NOT EXISTS idx_void_route_sessions_active
    ON void_route_sessions(player_id) WHERE status = 'running';

CREATE TABLE IF NOT EXISTS tribulation_trial_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL UNIQUE,
    player_id INTEGER NOT NULL REFERENCES players(id),
    operation_id TEXT NOT NULL UNIQUE,
    trial_key TEXT NOT NULL,
    choice_key TEXT,
    status TEXT NOT NULL CHECK (status IN ('preparing', 'succeeded', 'failed', 'expired')),
    starts_at TEXT NOT NULL,
    ends_at TEXT NOT NULL,
    snapshot_json TEXT NOT NULL DEFAULT '{}',
    result_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tribulation_trial_sessions_player
    ON tribulation_trial_sessions(player_id, trial_key, status);
CREATE UNIQUE INDEX IF NOT EXISTS idx_tribulation_trial_sessions_active
    ON tribulation_trial_sessions(player_id) WHERE status = 'preparing';

CREATE TABLE IF NOT EXISTS endgame_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL UNIQUE,
    player_id INTEGER NOT NULL REFERENCES players(id),
    operation_id TEXT NOT NULL UNIQUE,
    session_type TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('preparing', 'succeeded', 'failed')),
    starts_at TEXT NOT NULL,
    ends_at TEXT NOT NULL,
    snapshot_json TEXT NOT NULL DEFAULT '{}',
    result_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_endgame_sessions_player
    ON endgame_sessions(player_id, session_type, status);
CREATE UNIQUE INDEX IF NOT EXISTS idx_endgame_sessions_active
    ON endgame_sessions(player_id) WHERE status = 'preparing';

"""


class RepositoryBusyError(RuntimeError):
    """The database did not become available before the retry budget ended."""


class OperationConflictError(RuntimeError):
    """An operation ID was reused with a different actor or input."""


class PlayerNotFoundError(RuntimeError):
    """The requested platform identity has no player record."""


class PlayerSuspendedError(RuntimeError):
    """A suspended or deleted player cannot perform a write operation."""


class DaoNameTakenError(RuntimeError):
    """The requested dao name is already used by another player."""


class RenameCardRequiredError(RuntimeError):
    """A named player needs a rename card before changing dao name again."""


class PlayerStageConflictError(RuntimeError):
    """The player is not in the stage required by an onboarding action."""


class LocationRequiredError(RuntimeError):
    """The player must be at a specific location before an action can run."""


class LocationRequirementError(RuntimeError):
    """The player does not satisfy a destination's realm or quest gate."""


class VoidQuestMissingError(RuntimeError):
    """The player has not earned the void refining permit."""


class VoidLocationRequiredError(RuntimeError):
    """Void refining must be prepared at an approved void location."""


class VoidResourceInsufficientError(RuntimeError):
    """The player lacks a void-specific resource for the operation."""


class VoidInstabilityActiveError(RuntimeError):
    """A failed void operation is still imposing instability."""


class VoidRouteLockedError(RuntimeError):
    """The requested route is not available in the current content."""


class VoidTravelBusyError(RuntimeError):
    """Another movement or void session is active."""


class VoidAnchorInsufficientError(RuntimeError):
    """The player lacks enough anchors for a route."""


class VoidRouteNotFoundError(RuntimeError):
    """The player has no route session to settle."""


class VoidRouteNotReadyError(RuntimeError):
    """The route has not reached its arrival time."""


class ResourceInsufficientError(RuntimeError):
    """A player does not have enough of a spendable resource."""


class EnergyInsufficientError(RuntimeError):
    """A player does not have enough energy for production."""


class MaterialInsufficientError(RuntimeError):
    """A player does not have enough recipe inputs."""


class ToolMissingError(RuntimeError):
    """The recipe's required production tool is not owned."""


class ToolDurabilityInsufficientError(RuntimeError):
    """The recipe's required tool cannot pay its durability cost."""


class RecipeRequirementError(RuntimeError):
    """The player does not satisfy a recipe's profession, realm or location gate."""


class ProductionBusyError(RuntimeError):
    """The player already has a processing production order."""


class ProductionDailyLimitError(RuntimeError):
    """The recipe reached its business-day cap."""


class ProductionNotFoundError(RuntimeError):
    """The player has no production order to settle."""


class ProductionNotReadyError(RuntimeError):
    """A production order has not reached its completion time."""


class ProductionExpiredError(RuntimeError):
    """A production order missed its normal completion window."""


class PathAlreadySelectedError(RuntimeError):
    """The player already has a first path and cannot select another one."""


class SubprofessionRequiredError(RuntimeError):
    """The support path requires a sub-profession choice."""


class CultivationBusyError(RuntimeError):
    """The player already has a running cultivation session."""


class CultivationRecoveryRequiredError(RuntimeError):
    """An expired session must be recovered before another one can start."""


class CultivationDailyLimitError(RuntimeError):
    """The selected cultivation mode reached its business-day quota."""


class CultivationNotFoundError(RuntimeError):
    """The player has no running cultivation session."""


class CultivationNotReadyError(RuntimeError):
    """A cultivation session has not reached its end time."""


class CultivationAlreadyReadyError(RuntimeError):
    """A cultivation session reached its end and must be settled, not cancelled."""


class CultivationExpiredError(RuntimeError):
    """A session missed its normal settlement window and needs recovery."""


class CultivationAlreadyRecoveredError(RuntimeError):
    """An expired session already received its one allowed recovery result."""


class RetreatContentClosedError(RuntimeError):
    """The requested retreat mode is registered but not open."""


class RetreatBusyError(RuntimeError):
    """The player already has a long-running action or retreat."""


class RetreatDailyLimitError(RuntimeError):
    """The player reached the retreat mode's business-day quota."""


class RetreatNotFoundError(RuntimeError):
    """The player has no active retreat to settle."""


class RetreatNotReadyError(RuntimeError):
    """The retreat has not reached its end time."""


class RetreatExpiredError(RuntimeError):
    """The retreat is outside its normal settlement window."""


class RetreatAlreadySettledError(RuntimeError):
    """The active retreat already has a settled result."""


class ResidenceContentClosedError(RuntimeError):
    """The requested residence is registered but not open."""


class ResidenceAlreadyActiveError(RuntimeError):
    """The player already has an active residence."""


class ResidenceNotFoundError(RuntimeError):
    """The player has no active residence."""


class ResidenceRequiredError(RuntimeError):
    """The requested action requires an active residence."""


class ConstitutionAlreadySelectedError(RuntimeError):
    """The player already has a main constitution."""


class ConstitutionSameError(RuntimeError):
    """The requested reshape target is already active."""


class ConstitutionNotFoundError(RuntimeError):
    """The player has not selected a constitution."""


class ConstitutionCooldownError(RuntimeError):
    """The constitution reshape cooldown is still active."""


class ConstitutionBusyError(RuntimeError):
    """A long-running action prevents constitution mutation."""


class TalentNodeAlreadyLearnedError(RuntimeError):
    """The requested talent node is already learned."""


class TalentPathMismatchError(RuntimeError):
    """The requested tree does not match the player's primary path."""


class TalentPrerequisiteError(RuntimeError):
    """The previous talent tier has not been learned."""


class TalentBusyError(RuntimeError):
    """A long-running action prevents talent mutation."""


class SkillAlreadyMaxedError(RuntimeError):
    """The requested skill has reached the current mastery cap."""


class SkillNotAvailableError(RuntimeError):
    """The requested skill is not available to the player's primary path."""


class SkillBusyError(RuntimeError):
    """A long-running action prevents skill mutation."""


class EquipmentNotOwnedError(RuntimeError):
    """The player does not own the requested equipment."""


class EquipmentAmbiguousError(RuntimeError):
    """More than one matching equipment instance needs an explicit selector."""


class EquipmentTemperingMaxedError(RuntimeError):
    """The equipment has reached the current tempering cap."""


class EquipmentBusyError(RuntimeError):
    """A long-running action prevents equipment mutation."""


class RealmCultivationInsufficientError(RuntimeError):
    """The player has not reached the next layer threshold."""


class RealmLayerInvalidError(RuntimeError):
    """The player cannot advance beyond the current realm."""


class BreakthroughBusyError(RuntimeError):
    """The player already has a preparing breakthrough."""


class BreakthroughNotFoundError(RuntimeError):
    """The player has no breakthrough session to settle."""


class BreakthroughNotReadyError(RuntimeError):
    """The breakthrough session has not reached its end time."""


class BreakthroughExpiredError(RuntimeError):
    """The breakthrough session is outside its settlement window."""


class BreakthroughRequirementError(RuntimeError):
    """The player is not eligible for the requested breakthrough."""


class FoundationQualityInsufficientError(RuntimeError):
    """The player's foundation quality is below a breakthrough requirement."""


class WeaknessActiveError(RuntimeError):
    """A temporary breakthrough weakness blocks high-risk actions."""


class WeaknessNotActiveError(RuntimeError):
    """There is no breakthrough weakness to recover."""


class DomainCrackActiveError(RuntimeError):
    """The player cannot use domain-bound progression while cracked."""


class DomainSelectionBusyError(RuntimeError):
    """The player already has a pending domain confirmation."""


class DomainAlreadySelectedError(RuntimeError):
    """The player already selected a domain."""


class DomainNotEligibleError(RuntimeError):
    """The player does not meet domain selection prerequisites."""


class DomainEnergyInsufficientError(RuntimeError):
    """The requested domain activation has insufficient charge."""


class DomainConflictError(RuntimeError):
    """The requested domain conflicts with the current party state."""


class SoulPowerInsufficientError(RuntimeError):
    """The player lacks the soul power required for soul transformation."""


class FactionReputationInsufficientError(RuntimeError):
    """No faction reputation reached the soul transformation threshold."""


class CultivationInsufficientError(RuntimeError):
    """The player lacks the total cultivation for soul transformation."""


class RealmMismatchError(RuntimeError):
    """The source realm or layer does not match the requested breakthrough."""


class CurrencyInsufficientError(RuntimeError):
    """The player does not have enough spirit stones."""


class ProtectionItemInsufficientError(RuntimeError):
    """The requested breakthrough protection item is missing."""


class QuestRequirementError(RuntimeError):
    """A progression quest flag is required before an action can start."""


class HeartDemonPendingError(RuntimeError):
    """The player has an unresolved heart-demon session."""


class SoulFatigueActiveError(RuntimeError):
    """The player's soul fatigue window is still active."""


class TravelBusyError(RuntimeError):
    """The player has another active movement or long-running action."""


class TravelNotFoundError(RuntimeError):
    """The player has no movement session to settle."""


class TravelNotReadyError(RuntimeError):
    """The movement session has not reached its arrival time."""


class ExplorationBusyError(RuntimeError):
    """The player already has an active exploration or another locked action."""


class ExplorationNotFoundError(RuntimeError):
    """The player has no exploration session to settle or cancel."""


class ExplorationNotReadyError(RuntimeError):
    """The exploration session has not reached its end time."""


class ExplorationExpiredError(RuntimeError):
    """The exploration session exceeded its normal settlement window."""


class ExplorationCombatPendingError(RuntimeError):
    """The exploration rolled a combat encounter that is still locked."""


class ExplorationQuotaExhaustedError(RuntimeError):
    """The mode reached its business-day quota."""


class BountyDailyLimitError(RuntimeError):
    """The player already accepted a bounty for this business day."""


class BountyNotFoundError(RuntimeError):
    """The player has no current bounty to claim."""


class BountyContentClosedError(RuntimeError):
    """The bounty depends on a runtime that is still closed."""


class BountyRequirementError(RuntimeError):
    """The player does not satisfy a bounty's realm or stage gate."""


class BountyIncompleteError(RuntimeError):
    """The accepted bounty target has not been completed."""


class BountyExpiredError(RuntimeError):
    """The accepted bounty passed its deadline without a claim."""


class BountyAlreadyClaimedError(RuntimeError):
    """The current bounty reward has already been claimed."""


class MainlineContentClosedError(RuntimeError):
    """The requested mainline stage is documented but not open yet."""


class MainlineRequirementError(RuntimeError):
    """The player does not satisfy a mainline stage prerequisite."""


class MainlineNotStartedError(RuntimeError):
    """The requested mainline stage has no running attempt."""


class MainlineAlreadyRunningError(RuntimeError):
    """The requested mainline stage already has a running attempt."""


class CheckinAlreadyClaimedError(RuntimeError):
    """The player already completed today's daily check-in."""


class RoutineMakeupDateError(RuntimeError):
    """The requested makeup date is outside the allowed window."""


class RoutineMakeupNotEligibleError(RuntimeError):
    """The requested date was already claimed or is otherwise ineligible."""


class RoutineMakeupLimitError(RuntimeError):
    """The player reached the monthly makeup limit."""


class SpiritTreeWateredError(RuntimeError):
    """The spirit tree was already watered for this business day."""


class SpiritTreeCooldownError(RuntimeError):
    """The spirit tree is in its post-harvest cooldown."""


class SpiritTreeNotReadyError(RuntimeError):
    """The spirit tree has not reached seven waterings."""


class SevenDayNotStartedError(RuntimeError):
    """The player has not started the seven-day onboarding campaign."""


class SevenDayGoalInvalidError(RuntimeError):
    """The requested seven-day goal number is invalid."""


class SevenDayGoalNotOpenError(RuntimeError):
    """The requested seven-day goal is still in a future business day."""


class SevenDayGoalNotCompletedError(RuntimeError):
    """The requested seven-day goal has no qualifying activity yet."""


class SevenDayGoalAlreadyClaimedError(RuntimeError):
    """The requested seven-day goal reward was already claimed."""


class AchievementInvalidError(RuntimeError):
    """The requested achievement is not registered."""


class AchievementNotCompletedError(RuntimeError):
    """The requested achievement has no qualifying source event yet."""


class AchievementAlreadyClaimedError(RuntimeError):
    """The requested achievement reward was already claimed."""


class HonorTitleNotFoundError(RuntimeError):
    """The requested title is not owned by the player."""


class HonorTitleClosedError(RuntimeError):
    """The requested title or achievement is not open in the current content."""


class RedemptionCodeInvalidError(RuntimeError):
    """The submitted code is not configured."""


class RedemptionCodeExpiredError(RuntimeError):
    """The configured code is outside its validity window."""


class RedemptionCodeRevokedError(RuntimeError):
    """The configured code was revoked before redemption."""


class RedemptionCodeExhaustedError(RuntimeError):
    """The configured code has no remaining claims."""


class RedemptionCodeAlreadyClaimedError(RuntimeError):
    """The player already redeemed this code."""


class FatePoolInvalidError(RuntimeError):
    """The requested fate pool or draw count is not registered."""


class FatePoolNotOpenError(RuntimeError):
    """The requested fate pool is not available in the current content."""


class FateDrawInsufficientError(RuntimeError):
    """The player lacks the ticket or spirit stones required for a draw."""


class BillingReceiptInvalidError(RuntimeError):
    """The external billing receipt failed signature or contract validation."""


class BillingReceiptAlreadyUsedError(RuntimeError):
    """A signed receipt was already consumed by another operation."""


class DaoContractInvalidError(RuntimeError):
    """The requested contract is not registered."""


class DaoContractAlreadyClaimedError(RuntimeError):
    """The daily entitlement was already claimed for the business date."""


class DaoContractNotActiveError(RuntimeError):
    """The contract is not active for the requested business date."""


class DaoContractAlreadyRevokedError(RuntimeError):
    """The contract is already revoked or cannot be revoked."""


class WayfaringNotStartedError(RuntimeError):
    """The player has not started the current wayfaring pass."""


class WayfaringAlreadyStartedError(RuntimeError):
    """The current wayfaring cycle is already active."""


class WayfaringLevelInvalidError(RuntimeError):
    """The requested wayfaring level is outside the configured range."""


class WayfaringLevelLockedError(RuntimeError):
    """The player has not earned enough points for the requested level."""


class WayfaringClaimAlreadyExistsError(RuntimeError):
    """The requested wayfaring track was already claimed."""


class WayfaringPaidTrackInactiveError(RuntimeError):
    """The monthly dao contract is not active for the paid track."""


class DaoUnionRequirementError(RuntimeError):
    """The player does not satisfy the 合道 entry contract."""


class TribulationEntryRequirementError(RuntimeError):
    """The player does not satisfy the 渡劫 entry contract."""


class TrialSequenceError(RuntimeError):
    """The requested tribulation trial is unavailable or out of order."""


class TribulationTrialBusyError(RuntimeError):
    """Another tribulation trial is already preparing."""


class TribulationTrialNotFoundError(RuntimeError):
    """There is no preparing tribulation trial to settle."""


class TribulationTrialNotReadyError(RuntimeError):
    """The preparing tribulation trial has not reached its end time."""


class TribulationCooldownError(RuntimeError):
    """The requested trial is still in its failure cooldown."""


class TribulationDebtBlockedError(RuntimeError):
    """Tribulation debt is too high to start another trial."""


class TribulationTokenInsufficientError(RuntimeError):
    """The player lacks the token required by a tribulation trial."""


class ThreeRealmReputationInsufficientError(RuntimeError):
    """The player lacks the three realm reputation needed by trial two."""


class DaoFruitChoiceError(RuntimeError):
    """The chosen dao fruit is invalid or already locked."""


class SQLitePlayerRepository(EndgameRepositoryMixin, WorldRepositoryMixin, ProgressionRepositoryMixin):
    """Short-transaction repository safe for concurrent asyncio requests.

    Each operation uses a thread-local SQLite connection through ``to_thread``.
    WAL allows readers to proceed while a writer commits, and the semaphore
    prevents an unbounded burst from creating more connections than useful.
    """

    def __init__(self, settings: XiuxianSettings, *, clock: Callable[[], datetime] | None = None):
        self.settings = settings
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._initialized = False
        self._initialize_lock = asyncio.Lock()
        self._inflight = asyncio.Semaphore(settings.max_inflight)

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def business_today(self) -> date:
        """Return the injected UTC business date used by routine commands."""

        return self._now().date()

    async def initialize(self) -> None:
        if self._initialized:
            return
        async with self._initialize_lock:
            if self._initialized:
                return
            await asyncio.to_thread(self._initialize_sync)
            self._initialized = True

    def _connect(self) -> sqlite3.Connection:
        self.settings.data_dir.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(
            self.settings.database_path,
            timeout=self.settings.busy_timeout_ms / 1000,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute(f"PRAGMA busy_timeout = {self.settings.busy_timeout_ms}")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @staticmethod
    def _require_player(
        connection: sqlite3.Connection,
        platform: str,
        platform_user_id: str,
        *,
        writable: bool = True,
    ) -> sqlite3.Row:
        """Load one platform identity inside the caller's transaction.

        Every mutating repository operation must use this helper after it has
        opened its transaction. Keeping lookup and status validation together
        prevents feature modules from drifting in their identity semantics.
        """

        row = connection.execute(
            "SELECT * FROM players WHERE platform = ? AND platform_user_id = ?",
            (platform, platform_user_id),
        ).fetchone()
        if row is None:
            raise PlayerNotFoundError("player does not exist")
        if row["status"] != "active":
            detail = "player is not writable" if writable else "player is not readable"
            raise PlayerSuspendedError(detail)
        return row

    def _initialize_sync(self) -> None:
        with self._connect() as connection:
            connection.executescript(SCHEMA)
            self._migrate_legacy_schema(connection)
            self._migrate_cultivation_session_status(connection)
            connection.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                "migration_key TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
            )
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(migration_key, applied_at) VALUES (?, ?)",
                ("routine.v0.1", serialize_datetime(self._now())),
            )
            self._materialize_redemption_codes(connection, serialize_datetime(self._now()))
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(migration_key, applied_at) VALUES (?, ?)",
                ("routine.redemption.v0.1", serialize_datetime(self._now())),
            )
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(migration_key, applied_at) VALUES (?, ?)",
                ("routine.wayfaring.v0.1", serialize_datetime(self._now())),
            )
            connection.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_players_dao_name "
                "ON players(dao_name) WHERE dao_name <> ''"
            )

    def _materialize_redemption_codes(
        self,
        connection: sqlite3.Connection,
        now_text: str,
    ) -> None:
        for definition in self.settings.redemption_codes:
            status = "revoked" if definition.revoked else "active"
            connection.execute(
                """
                INSERT OR IGNORE INTO redemption_codes(
                    code_key, code_hash, max_claims, starts_on, ends_on, status,
                    reward_json, content_version, rule_version, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    definition.code_key,
                    definition.code_hash,
                    definition.max_claims,
                    definition.starts_on,
                    definition.ends_on,
                    status,
                    json.dumps(definition.reward_map(), ensure_ascii=False, sort_keys=True),
                    definition.content_version,
                    definition.rule_version,
                    now_text,
                    now_text,
                ),
            )
            if definition.revoked:
                connection.execute(
                    "UPDATE redemption_codes SET status = 'revoked', updated_at = ? WHERE code_key = ?",
                    (now_text, definition.code_key),
                )

    @staticmethod
    def _migrate_legacy_schema(connection: sqlite3.Connection) -> None:
        """Add P3.1 identity fields without rewriting existing player rows."""

        player_columns = {row["name"] for row in connection.execute("PRAGMA table_info(players)")}
        if "player_id" not in player_columns:
            connection.execute("ALTER TABLE players ADD COLUMN player_id TEXT")
            connection.execute(
                "UPDATE players SET player_id = 'legacy-' || id WHERE player_id IS NULL"
            )
            connection.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_players_player_id ON players(player_id)"
            )
        for column, definition in (
            ("dao_name", "TEXT NOT NULL DEFAULT ''"),
            ("status", "TEXT NOT NULL DEFAULT 'active'"),
            ("location_key", "TEXT NOT NULL DEFAULT 'xuantian.new_town'"),
            ("rule_version", "TEXT NOT NULL DEFAULT 'player-onboarding-v0.1.0'"),
            ("path_key", "TEXT"),
            ("subprofession_key", "TEXT"),
            ("stamina", "INTEGER NOT NULL DEFAULT 0"),
            ("stamina_max", "INTEGER NOT NULL DEFAULT 0"),
            ("energy", "INTEGER NOT NULL DEFAULT 0"),
            ("energy_max", "INTEGER NOT NULL DEFAULT 0"),
            ("inventory_json", "TEXT NOT NULL DEFAULT '{}'"),
            ("durability_json", "TEXT NOT NULL DEFAULT '{}'"),
            ("intro_json", "TEXT NOT NULL DEFAULT '{}'"),
            ("selected_service", "TEXT"),
            ("realm_key", "TEXT NOT NULL DEFAULT 'mortal'"),
            ("realm_layer", "INTEGER NOT NULL DEFAULT 0"),
            ("cultivation", "INTEGER NOT NULL DEFAULT 0"),
            ("total_cultivation", "INTEGER NOT NULL DEFAULT 0"),
            ("foundation_quality", "INTEGER NOT NULL DEFAULT 0"),
            ("world_merit", "INTEGER NOT NULL DEFAULT 0"),
            ("talent_points", "INTEGER NOT NULL DEFAULT 0"),
            ("skill_insights", "INTEGER NOT NULL DEFAULT 0"),
            ("weakness_until", "TEXT"),
            ("breakthrough_pity_bp", "INTEGER NOT NULL DEFAULT 0"),
            ("soul_power", "INTEGER NOT NULL DEFAULT 0"),
            ("soul_power_max", "INTEGER NOT NULL DEFAULT 0"),
            ("domain_charge", "INTEGER NOT NULL DEFAULT 0"),
            ("domain_charge_max", "INTEGER NOT NULL DEFAULT 0"),
            ("pollution", "INTEGER NOT NULL DEFAULT 0"),
            ("bloodline_stability", "INTEGER NOT NULL DEFAULT 0"),
            ("cross_realm_penalty_bp", "INTEGER NOT NULL DEFAULT 0"),
            ("soul_fatigue_until", "TEXT"),
            ("heart_demon_bonus_bp", "INTEGER NOT NULL DEFAULT 0"),
            ("max_hp", "INTEGER NOT NULL DEFAULT 0"),
            ("max_mp", "INTEGER NOT NULL DEFAULT 0"),
            ("carry_capacity", "INTEGER NOT NULL DEFAULT 0"),
            ("exploration_efficiency_bp", "INTEGER NOT NULL DEFAULT 0"),
            ("domain_key", "TEXT"),
            ("domain_power", "INTEGER NOT NULL DEFAULT 0"),
            ("realm_resistance_bp", "INTEGER NOT NULL DEFAULT 0"),
            ("domain_crack_until", "TEXT"),
            ("initiative", "INTEGER NOT NULL DEFAULT 0"),
            ("faction_reputation_json", "TEXT NOT NULL DEFAULT '{}'"),
            ("domain_level", "INTEGER NOT NULL DEFAULT 0"),
            ("domain_charge_reset_date", "TEXT"),
            ("void_power", "INTEGER NOT NULL DEFAULT 0"),
            ("void_power_max", "INTEGER NOT NULL DEFAULT 0"),
            ("space_resistance_bp", "INTEGER NOT NULL DEFAULT 0"),
            ("void_instability_until", "TEXT"),
            ("void_route_count", "INTEGER NOT NULL DEFAULT 0"),
            ("void_anchor_capacity", "INTEGER NOT NULL DEFAULT 0"),
            ("void_power_reset_date", "TEXT"),
            ("dao_fruit_progress", "INTEGER NOT NULL DEFAULT 0"),
            ("ascension_merit", "INTEGER NOT NULL DEFAULT 0"),
            ("tribulation_debt", "INTEGER NOT NULL DEFAULT 0"),
            ("dao_fruit_key", "TEXT"),
            ("endgame_status", "TEXT NOT NULL DEFAULT 'none'"),
            ("ending_key", "TEXT"),
        ):
            if column not in player_columns:
                connection.execute(f"ALTER TABLE players ADD COLUMN {column} {definition}")
        operation_columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(operations)")
        }
        if "request_hash" not in operation_columns:
            connection.execute("ALTER TABLE operations ADD COLUMN request_hash TEXT NOT NULL DEFAULT ''")

    @staticmethod
    def _migrate_cultivation_session_status(connection: sqlite3.Connection) -> None:
        """Rebuild the early session table so old databases accept ``expired``.

        SQLite cannot alter a CHECK constraint in place.  The migration keeps
        every existing session and operation reference while replacing only
        the table definition and its indexes.
        """

        table = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'cultivation_sessions'"
        ).fetchone()
        schema_sql = str(table[0]) if table and table[0] else ""
        if "'expired'" in schema_sql:
            return
        connection.execute("DROP INDEX IF EXISTS idx_cultivation_sessions_active")
        connection.execute("DROP INDEX IF EXISTS idx_cultivation_sessions_player")
        connection.execute("ALTER TABLE cultivation_sessions RENAME TO cultivation_sessions_legacy")
        connection.execute(
            """
            CREATE TABLE cultivation_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL UNIQUE,
                player_id INTEGER NOT NULL REFERENCES players(id),
                operation_id TEXT NOT NULL UNIQUE,
                mode_key TEXT NOT NULL,
                status TEXT NOT NULL CHECK (status IN ('running', 'settled', 'cancelled', 'expired')),
                starts_at TEXT NOT NULL,
                ends_at TEXT NOT NULL,
                stamina_cost INTEGER NOT NULL DEFAULT 0 CHECK (stamina_cost >= 0),
                snapshot_json TEXT NOT NULL DEFAULT '{}',
                result_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO cultivation_sessions(
                id, session_id, player_id, operation_id, mode_key, status,
                starts_at, ends_at, stamina_cost, snapshot_json, result_json,
                created_at, updated_at
            )
            SELECT id, session_id, player_id, operation_id, mode_key, status,
                   starts_at, ends_at, stamina_cost, snapshot_json, result_json,
                   created_at, updated_at
            FROM cultivation_sessions_legacy
            """
        )
        connection.execute("DROP TABLE cultivation_sessions_legacy")
        connection.execute("CREATE INDEX idx_cultivation_sessions_player ON cultivation_sessions(player_id)")
        connection.execute(
            "CREATE UNIQUE INDEX idx_cultivation_sessions_active "
            "ON cultivation_sessions(player_id) WHERE status = 'running'"
        )

    @staticmethod
    def _request_hash(operation_name: str, payload: dict[str, Any]) -> str:
        canonical = json.dumps(
            {"operation_name": operation_name, "payload": payload},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

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
        now = datetime.now(timezone.utc)
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
                        status, location_key, rule_version, qualification_json,
                        spirit_stones, stamina, stamina_max, energy, energy_max,
                        inventory_json, intro_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'active', 'xuantian.new_town',
                              'player-onboarding-v0.1.0', '{}', 0, 0, 0, 0, 0, '{}', '{}', ?, ?)
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
                connection.execute(
                    """
                    UPDATE players
                    SET stage = ?, realm_key = 'mortal', realm_layer = 0, cultivation = 0, total_cultivation = 0,
                        qualification_json = ?, spirit_stones = spirit_stones + 100,
                        stamina = 30, stamina_max = 30, energy = 30, energy_max = 30,
                        inventory_json = ?, updated_at = ?
                    WHERE id = ? AND stage = ?
                    """,
                    (
                        STAGE_MORTAL,
                        json.dumps(qualification, ensure_ascii=False, sort_keys=True),
                        json.dumps(
                            {
                                "item.food.coarse_spirit_rice": 3,
                                "item.herb.blood_grass": 3,
                            },
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                        serialize_datetime(now),
                        row["id"],
                        STAGE_NEW_USER,
                    ),
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
        now = datetime.now(timezone.utc)
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
            stamina = int(row["stamina"])
            energy = int(row["energy"])
            inventory = self._json_object(row["inventory_json"], {})
            if changed:
                if guide_key == "guide.gather_blood_grass":
                    if row["location_key"] != "xuantian.outskirts":
                        raise LocationRequiredError("gathering lesson requires the outskirts")
                    if stamina < 2:
                        raise ResourceInsufficientError("stamina is insufficient")
                    stamina -= 2
                    item_quantity = 1 + (hashlib.blake2b(operation_id.encode("utf-8"), digest_size=1).digest()[0] % 2)
                    inventory["item.herb.blood_grass"] = int(inventory.get("item.herb.blood_grass", 0)) + item_quantity
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
            connection.execute(
                """
                UPDATE players
                SET stage = ?, stamina = ?, energy = ?, inventory_json = ?, intro_json = ?,
                    selected_service = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    stage,
                    stamina,
                    energy,
                    json.dumps(inventory, ensure_ascii=False, sort_keys=True),
                    json.dumps(intro_state, ensure_ascii=False, sort_keys=True),
                    selected,
                    serialize_datetime(now),
                    row["id"],
                ),
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
        now = datetime.now(timezone.utc)
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
                if row["realm_key"] != REALM_QI_SENSING or int(row["realm_layer"]) < 2:
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
            stamina = int(row["stamina"])
            if changed and stamina < cost:
                raise ResourceInsufficientError("stamina is insufficient")
            if changed:
                stamina -= cost
                connection.execute(
                    "UPDATE players SET location_key = ?, stamina = ?, updated_at = ? WHERE id = ?",
                    (destination, stamina, serialize_datetime(now), row["id"]),
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
            return TravelRecord(player=player, destination=destination, changed=changed, stamina_cost=cost)

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
        if player.stamina < definition.stamina_cost:
            missing.append("体力")
        if player.spirit_stones < definition.currency_cost:
            missing.append("灵石")
        if definition.pass_key and player.inventory.get(definition.pass_key, 0) < definition.pass_quantity:
            missing.append("洞天凭证")
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
        now = datetime.now(timezone.utc)
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

            row = self._require_player(connection, platform, platform_user_id)
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
            ):
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

            if definition.pass_key:
                remaining = inventory.get(definition.pass_key, 0) - definition.pass_quantity
                if remaining:
                    inventory[definition.pass_key] = remaining
                else:
                    inventory.pop(definition.pass_key, None)
            session_id = uuid4().hex
            ends_at = now + timedelta(seconds=definition.duration_seconds)
            snapshot = {
                "rule_version": RULE_VERSION,
                "content_version": definition.content_version,
                "source": current,
                "destination": destination,
                "stamina_cost": definition.stamina_cost,
                "currency_cost": definition.currency_cost,
                "pass_key": definition.pass_key,
                "pass_quantity": definition.pass_quantity,
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
        now = datetime.now(timezone.utc)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id = ?", (operation_id,)
            ).fetchone()
            if existing is not None:
                if existing["operation_name"] != operation_name or existing["request_hash"] != request_hash:
                    raise OperationConflictError("operation input differs from its original request")
                return self._travel_settlement_from_payload(json.loads(existing["result_json"]), replay=True)
            row = self._require_player(connection, platform, platform_user_id)
            session = connection.execute(
                "SELECT * FROM travel_sessions WHERE player_id = ? AND status = 'running' ORDER BY id DESC LIMIT 1", (row["id"],)
            ).fetchone()
            if session is None:
                raise TravelNotFoundError("no running travel")
            ends_at = datetime.fromisoformat(str(session["ends_at"]))
            if now < ends_at:
                raise TravelNotReadyError("travel is not ready")
            connection.execute(
                "UPDATE players SET location_key = ?, updated_at = ? WHERE id = ?",
                (session["destination"], serialize_datetime(now), row["id"]),
            )
            connection.execute(
                "UPDATE travel_sessions SET status = 'arrived', result_json = ?, updated_at = ? WHERE id = ? AND status = 'running'",
                (json.dumps({"arrived": True, "settled_at": serialize_datetime(now)}, ensure_ascii=False, sort_keys=True), serialize_datetime(now), session["id"]),
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (row["id"],)).fetchone()
            player = self._row_to_player(updated)
            payload = {
                "player": self._player_payload(player), "session_id": session["session_id"],
                "source": session["source_location"], "destination": session["destination"], "status": "arrived",
                "arrived": True, "stamina_cost": int(session["stamina_cost"]), "currency_cost": int(session["currency_cost"]),
                "pass_key": session["pass_key"], "pass_quantity": int(session["pass_quantity"]),
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
            pass_quantity=int(payload.get("pass_quantity", 0)), already_completed=replay,
        )

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
        now = datetime.now(timezone.utc)
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
            }
            connection.execute(
                "UPDATE players SET stamina = ?, updated_at = ? WHERE id = ?",
                (stamina - definition.stamina_cost, starts_at, player_id),
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
            return await asyncio.to_thread(self._settle_exploration_sync, platform, platform_user_id, operation_id)

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
        now = datetime.now(timezone.utc)
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
            ends_at = datetime.fromisoformat(str(session["ends_at"]))
            if now < ends_at:
                raise ExplorationNotReadyError("exploration is not ready")
            snapshot = self._json_object(session["snapshot_json"], {})
            expired = now > ends_at + timedelta(hours=24)
            result: dict[str, int] = {}
            battle_pending = False
            status = "expired" if expired else "settled"
            if not expired:
                seed = str(snapshot.get("random_seed", session["operation_id"]))
                battle_pending = battle_roll_bp(seed + ":battle") < int(snapshot.get("battle_chance_bp", 0))
                if battle_pending:
                    status = "combat_pending"
                else:
                    result = settlement_result(str(session["mode_key"]), seed)

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
                "battle_pending": battle_pending,
                "expired": expired,
                "settled_at": now_text,
            }
            connection.execute(
                "UPDATE exploration_sessions SET status = ?, result_json = ?, updated_at = ? WHERE id = ? AND status IN ('created', 'running')",
                (status, json.dumps(result_json, ensure_ascii=False, sort_keys=True), now_text, session["id"]),
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
            already_completed=replay,
        )

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
        now_text = serialize_datetime(datetime.now(timezone.utc))
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
            stamina = int(row["stamina"]) + int(session["stamina_cost"])
            connection.execute("UPDATE players SET stamina = ?, updated_at = ? WHERE id = ?", (stamina, now_text, row["id"]))
            connection.execute(
                "UPDATE exploration_sessions SET status = 'cancelled', result_json = ?, updated_at = ? WHERE id = ? AND status = 'created'",
                (json.dumps({"status": "cancelled", "stamina_refund": int(session["stamina_cost"])}, ensure_ascii=False), now_text, session["id"]),
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (row["id"],)).fetchone()
            player = self._row_to_player(updated)
            payload = {
                "player": self._player_payload(player),
                "exploration_id": session["exploration_id"],
                "mode_key": session["mode_key"],
                "location_key": session["location_key"],
                "status": "cancelled",
                "result": {"stamina_refund": int(session["stamina_cost"])},
                "battle_pending": False,
                "expired": False,
                "stamina_cost": int(session["stamina_cost"]),
            }
            connection.execute(
                "INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (operation_id, operation_name, row["id"], request_hash, json.dumps(payload, ensure_ascii=False, sort_keys=True), now_text),
            )
            return self._exploration_settlement_from_payload(payload)

    async def get_bounty_board(
        self,
        *,
        platform: str,
        platform_user_id: str,
    ) -> BountyBoardRecord:
        await self.initialize()
        return await asyncio.to_thread(self._get_bounty_board_sync, platform, platform_user_id)

    def _get_bounty_board_sync(self, platform: str, platform_user_id: str) -> BountyBoardRecord:
        now = datetime.now(timezone.utc)
        business_date = now.date().isoformat()
        with self._connect() as connection:
            row = self._require_player(connection, platform, platform_user_id, writable=False)
            accepted = connection.execute(
                "SELECT * FROM bounty_offers WHERE player_id = ? AND business_date = ?",
                (row["id"], business_date),
            ).fetchone()
            offers: list[BountyOfferView] = []
            for definition in BOUNTY_DEFINITIONS.values():
                progress = 0
                expires_at: str | None = None
                if accepted is not None and accepted["bounty_key"] == definition.key:
                    progress = self._bounty_progress(connection, row, accepted, definition)
                    expires_at = str(accepted["expires_at"])
                    if accepted["status"] == "claimed":
                        status = "claimed"
                    elif now > datetime.fromisoformat(str(accepted["expires_at"])):
                        status = "expired"
                    elif progress >= definition.target_amount:
                        status = "completed"
                    else:
                        status = "accepted"
                elif accepted is not None:
                    status = "daily_limit"
                elif definition.runtime_status != "open":
                    status = "locked"
                elif not self._bounty_player_eligible(row, definition):
                    status = "requirement"
                else:
                    status = "available"
                offers.append(
                    BountyOfferView(
                        key=definition.key,
                        label=definition.label,
                        description=definition.description,
                        status=status,
                        progress=progress,
                        target=definition.target_amount,
                        reward=reward_map(definition),
                        expires_at=expires_at,
                    )
                )
            return BountyBoardRecord(
                player=self._row_to_player(row),
                business_date=business_date,
                offers=tuple(offers),
            )

    @staticmethod
    def _bounty_player_eligible(row: sqlite3.Row | dict[str, Any], definition) -> bool:
        stage = str(row["stage"] if isinstance(row, sqlite3.Row) else row.get("stage", ""))
        if stage not in {STAGE_MORTAL, "seeker", "cultivator"}:
            return False
        realm_key = str(row["realm_key"] if isinstance(row, sqlite3.Row) else row.get("realm_key", "mortal"))
        layer = int(row["realm_layer"] if isinstance(row, sqlite3.Row) else row.get("realm_layer", 0))
        return bounty_meets_realm(realm_key, layer, definition.required_realm, definition.required_layer)

    @staticmethod
    def _bounty_progress(connection: sqlite3.Connection, row: sqlite3.Row, offer: sqlite3.Row, definition) -> int:
        snapshot = SQLitePlayerRepository._json_object(offer["snapshot_json"], {})
        if definition.target_kind == "inventory_gain":
            inventory = SQLitePlayerRepository._json_object(row["inventory_json"], {})
            current = int(inventory.get(str(definition.target_key), 0))
            baseline = int(snapshot.get("baseline_quantity", 0))
            return max(0, min(definition.target_amount, current - baseline))
        if definition.target_kind == "production_completed":
            current = connection.execute(
                "SELECT COUNT(*) AS count FROM production_orders WHERE player_id = ? AND status = 'completed'",
                (row["id"],),
            ).fetchone()
            baseline = int(snapshot.get("baseline_completed_orders", 0))
            return max(0, min(definition.target_amount, int(current["count"]) - baseline))
        result = SQLitePlayerRepository._json_object(offer["result_json"], {})
        return max(0, min(definition.target_amount, int(result.get("progress", 0))))

    async def accept_bounty(
        self,
        *,
        platform: str,
        platform_user_id: str,
        bounty_key: str,
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
        definition = bounty_definition(bounty_key)
        operation_name = "bounty.accept"
        request_payload = {
            "platform": platform,
            "platform_user_id": platform_user_id,
            "bounty_key": definition.key,
        }
        request_hash = self._request_hash(operation_name, request_payload)
        now = datetime.now(timezone.utc)
        business_date = now.date().isoformat()
        starts_at = serialize_datetime(now)
        expires_at = serialize_datetime(now + timedelta(seconds=definition.duration_seconds))
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
            if definition.runtime_status != "open":
                raise BountyContentClosedError("bounty runtime is closed")
            if not self._bounty_player_eligible(row, definition):
                raise BountyRequirementError("bounty requirements are not met")
            accepted = connection.execute(
                "SELECT 1 FROM bounty_offers WHERE player_id = ? AND business_date = ? LIMIT 1",
                (row["id"], business_date),
            ).fetchone()
            if accepted is not None:
                raise BountyDailyLimitError("player already accepted a bounty today")
            inventory = self._json_object(row["inventory_json"], {})
            completed_orders = connection.execute(
                "SELECT COUNT(*) AS count FROM production_orders WHERE player_id = ? AND status = 'completed'",
                (row["id"],),
            ).fetchone()
            snapshot = {
                "bounty_key": definition.key,
                "content_version": definition.content_version,
                "rule_version": definition.rule_version,
                "target_kind": definition.target_kind,
                "target_key": definition.target_key,
                "target_amount": definition.target_amount,
                "baseline_quantity": int(inventory.get(str(definition.target_key), 0)) if definition.target_key else 0,
                "baseline_completed_orders": int(completed_orders["count"]),
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

    def _claim_bounty_sync(self, platform: str, platform_user_id: str, operation_id: str) -> BountyClaimRecord:
        operation_name = "bounty.claim"
        request_payload = {"platform": platform, "platform_user_id": platform_user_id}
        request_hash = self._request_hash(operation_name, request_payload)
        now = datetime.now(timezone.utc)
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
                return self._bounty_claim_from_payload(json.loads(existing["result_json"]), replay=True)
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
            definition = bounty_definition(str(offer["bounty_key"]))
            progress = self._bounty_progress(connection, row, offer, definition)
            if now > datetime.fromisoformat(str(offer["expires_at"])):
                connection.execute(
                    "UPDATE bounty_offers SET status = 'expired', result_json = ?, updated_at = ? WHERE id = ? AND status IN ('accepted', 'completed')",
                    (
                        json.dumps({"status": "expired", "progress": progress}, ensure_ascii=False, sort_keys=True),
                        now_text,
                        offer["id"],
                    ),
                )
                connection.commit()
                raise BountyExpiredError("bounty has expired")
            if progress < definition.target_amount:
                raise BountyIncompleteError("bounty target is incomplete")

            inventory = self._json_object(row["inventory_json"], {})
            stones = int(row["spirit_stones"])
            cultivation = int(row["cultivation"])
            total_cultivation = int(row["total_cultivation"])
            energy = int(row["energy"])
            rewards = reward_map(definition)
            actual_rewards: dict[str, int] = {}
            local_reputation = 0
            service_reputation = 0
            for key, quantity in rewards.items():
                quantity = int(quantity)
                if key == "spirit_stones":
                    stones += quantity
                    actual_rewards[key] = quantity
                elif key == "cultivation":
                    cultivation += quantity
                    total_cultivation += quantity
                    actual_rewards[key] = quantity
                elif key == "energy":
                    gained = min(quantity, max(0, int(row["energy_max"]) - energy))
                    energy += gained
                    actual_rewards[key] = gained
                elif key == "local_reputation":
                    local_reputation += quantity
                    actual_rewards[key] = quantity
                elif key == "service_reputation":
                    service_reputation += quantity
                    actual_rewards[key] = quantity
                else:
                    inventory[key] = int(inventory.get(key, 0)) + quantity
                    actual_rewards[key] = quantity

            reputation = connection.execute(
                "SELECT local_json, service_reputation FROM player_reputations WHERE player_id = ?",
                (row["id"],),
            ).fetchone()
            local = self._json_object(reputation["local_json"], {}) if reputation is not None else {}
            local["local.xuantian.new_town"] = int(local.get("local.xuantian.new_town", 0)) + local_reputation
            current_service = int(reputation["service_reputation"]) if reputation is not None else 0
            current_service = min(100, current_service + service_reputation)
            connection.execute(
                """
                INSERT INTO player_reputations(player_id, local_json, service_reputation, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(player_id) DO UPDATE SET local_json = excluded.local_json,
                    service_reputation = excluded.service_reputation, updated_at = excluded.updated_at
                """,
                (row["id"], json.dumps(local, ensure_ascii=False, sort_keys=True), current_service, now_text),
            )
            connection.execute(
                """
                UPDATE players
                SET spirit_stones = ?, cultivation = ?, total_cultivation = ?, energy = ?,
                    inventory_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    stones,
                    cultivation,
                    total_cultivation,
                    energy,
                    json.dumps(inventory, ensure_ascii=False, sort_keys=True),
                    now_text,
                    row["id"],
                ),
            )
            result_json = {
                "status": "claimed",
                "progress": progress,
                "target": definition.target_amount,
                "rewards": actual_rewards,
            }
            connection.execute(
                "UPDATE bounty_offers SET status = 'claimed', result_json = ?, updated_at = ? WHERE id = ? AND status IN ('accepted', 'completed')",
                (json.dumps(result_json, ensure_ascii=False, sort_keys=True), now_text, offer["id"]),
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (row["id"],)).fetchone()
            player = self._row_to_player(updated)
            payload = {
                "player": self._player_payload(player),
                "bounty_key": definition.key,
                "label": definition.label,
                "status": "claimed",
                "progress": progress,
                "target": definition.target_amount,
                "rewards": actual_rewards,
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
            already_completed=replay,
        )

    async def get_mainline_status(
        self,
        *,
        platform: str,
        platform_user_id: str,
    ) -> MainlineStatusRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._get_mainline_status_sync,
                platform,
                platform_user_id,
            )

    def _get_mainline_status_sync(
        self,
        platform: str,
        platform_user_id: str,
    ) -> MainlineStatusRecord:
        with self._connect() as connection:
            row = self._require_player(connection, platform, platform_user_id, writable=False)
            return self._mainline_status_from_connection(connection, row)

    @staticmethod
    def _mainline_status_from_connection(
        connection: sqlite3.Connection,
        player: sqlite3.Row,
        *,
        replay: bool = False,
    ) -> MainlineStatusRecord:
        runs = {
            str(item["stage_key"]): item
            for item in connection.execute(
                "SELECT * FROM mainline_runs WHERE player_id = ? AND story_key = ?",
                (player["id"], MAINLINE_STORY_KEY),
            ).fetchall()
        }
        completed_stages = {
            str(item["stage_key"])
            for item in runs.values()
            if bool(item["first_clear_claimed"])
        }
        intro_state = SQLitePlayerRepository._json_object(player["intro_json"], {})
        flags = {str(item) for item in intro_state.get("flags", [])}
        completed_events = {"player.start_seeking"} if str(player["stage"]) != STAGE_NEW_USER else set()
        views: list[MainlineStageView] = []
        for definition in MAINLINE_STAGES:
            run = runs.get(definition.key)
            prerequisites_met = mainline_prerequisites_met(
                definition,
                completed_stages=completed_stages,
                completed_events=completed_events,
                flags=flags,
                realm_key=str(player["realm_key"]),
                realm_layer=int(player["realm_layer"]),
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
            story_key=MAINLINE_STORY_KEY,
            chapter=current.chapter,
            current_stage=current.stage,
            status=overall,
            stages=tuple(views),
            content_version=MAINLINE_CONTENT_VERSION,
            rule_version=MAINLINE_RULE_VERSION,
            already_completed=replay,
        )

    async def start_mainline(
        self,
        *,
        platform: str,
        platform_user_id: str,
        stage_key: str,
        operation_id: str,
    ) -> MainlineStartRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._start_mainline_sync,
                platform,
                platform_user_id,
                stage_key,
                operation_id,
            )

    def _start_mainline_sync(
        self,
        platform: str,
        platform_user_id: str,
        stage_key: str,
        operation_id: str,
    ) -> MainlineStartRecord:
        last_error: Exception | None = None
        for attempt in range(5):
            try:
                return self._start_mainline_once(
                    platform,
                    platform_user_id,
                    stage_key,
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

    def _start_mainline_once(
        self,
        platform: str,
        platform_user_id: str,
        stage_key: str,
        operation_id: str,
    ) -> MainlineStartRecord:
        definition = mainline_definition(stage_key)
        operation_name = "mainline.start_stage"
        request_hash = self._request_hash(
            operation_name,
            {
                "platform": platform,
                "platform_user_id": platform_user_id,
                "stage_key": definition.key,
                "content_version": definition.content_version,
                "rule_version": definition.rule_version,
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
                return self._mainline_start_from_payload(
                    json.loads(existing["result_json"]), replay=True
                )
            if definition.runtime_status != "open":
                raise MainlineContentClosedError("mainline stage is not open")
            row = self._require_player(connection, platform, platform_user_id)
            status_record = self._mainline_status_from_connection(connection, row)
            stage_view = next(item for item in status_record.stages if item.key == definition.key)
            if not mainline_prerequisites_met(
                definition,
                completed_stages={
                    item.key for item in status_record.stages if item.completed
                },
                completed_events=(
                    {"player.start_seeking"}
                    if str(row["stage"]) != STAGE_NEW_USER
                    else set()
                ),
                flags=SQLitePlayerRepository._json_object(row["intro_json"], {}).get("flags", []),
                realm_key=str(row["realm_key"]),
                realm_layer=int(row["realm_layer"]),
            ):
                raise MainlineRequirementError("mainline prerequisites are not met")
            run = connection.execute(
                "SELECT * FROM mainline_runs WHERE player_id = ? AND story_key = ? AND stage_key = ?",
                (row["id"], MAINLINE_STORY_KEY, definition.key),
            ).fetchone()
            if run is not None and str(run["status"]) == "running":
                raise MainlineAlreadyRunningError("mainline stage is already running")
            first_key = (
                str(run["first_clear_key"])
                if run is not None
                else mainline_first_clear_key(definition.chapter, definition.stage, str(row["player_id"]))
            )
            snapshot = {
                "stage": str(row["stage"]),
                "realm_key": str(row["realm_key"]),
                "realm_layer": int(row["realm_layer"]),
                "location_key": str(row["location_key"]),
                "intro_flags": list(SQLitePlayerRepository._json_object(row["intro_json"], {}).get("flags", [])),
                "content_version": definition.content_version,
                "rule_version": definition.rule_version,
            }
            if run is None:
                connection.execute(
                    """
                    INSERT INTO mainline_runs(
                        player_id, story_key, chapter, stage, stage_key, status,
                        attempt_count, first_clear_claimed, first_clear_key,
                        start_operation_id, snapshot_json, content_version, rule_version,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, 'running', 1, 0, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row["id"], MAINLINE_STORY_KEY, definition.chapter, definition.stage,
                        definition.key, first_key, operation_id,
                        json.dumps(snapshot, ensure_ascii=False, sort_keys=True),
                        definition.content_version, definition.rule_version, now_text, now_text,
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
                "story_key": MAINLINE_STORY_KEY,
                "chapter": definition.chapter,
                "stage": definition.stage,
                "stage_key": definition.key,
                "status": "running",
                "first_clear": first_clear,
                "label": definition.label,
                "description": definition.description,
                "content_version": definition.content_version,
                "rule_version": definition.rule_version,
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
    ) -> MainlineClaimRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._claim_mainline_sync,
                platform,
                platform_user_id,
                stage_key,
                operation_id,
            )

    def _claim_mainline_sync(
        self,
        platform: str,
        platform_user_id: str,
        stage_key: str,
        operation_id: str,
    ) -> MainlineClaimRecord:
        last_error: Exception | None = None
        for attempt in range(5):
            try:
                return self._claim_mainline_once(
                    platform,
                    platform_user_id,
                    stage_key,
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

    def _claim_mainline_once(
        self,
        platform: str,
        platform_user_id: str,
        stage_key: str,
        operation_id: str,
    ) -> MainlineClaimRecord:
        definition = mainline_definition(stage_key)
        operation_name = "mainline.claim_first_clear"
        request_hash = self._request_hash(
            operation_name,
            {
                "platform": platform,
                "platform_user_id": platform_user_id,
                "stage_key": definition.key,
                "content_version": definition.content_version,
                "rule_version": definition.rule_version,
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
            if definition.runtime_status != "open":
                raise MainlineContentClosedError("mainline stage is not open")
            row = self._require_player(connection, platform, platform_user_id)
            run = connection.execute(
                "SELECT * FROM mainline_runs WHERE player_id = ? AND story_key = ? AND stage_key = ?",
                (row["id"], MAINLINE_STORY_KEY, definition.key),
            ).fetchone()
            if run is None or str(run["status"]) != "running":
                raise MainlineNotStartedError("mainline stage has not been started")
            first_clear = not bool(run["first_clear_claimed"])
            reward = mainline_reward(definition, first_clear=first_clear)
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
                "story_key": MAINLINE_STORY_KEY,
                "chapter": definition.chapter,
                "stage": definition.stage,
                "stage_key": definition.key,
                "status": "claimed",
                "reward": actual_reward,
                "first_clear": first_clear,
                "label": definition.label,
                "source_operation_id": operation_id,
                "content_version": definition.content_version,
                "rule_version": definition.rule_version,
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
    def _apply_mainline_reward(
        connection: sqlite3.Connection,
        player: sqlite3.Row,
        reward: dict[str, int | str],
        operation_id: str,
        now_text: str,
        definition: Any,
    ) -> dict[str, int | str]:
        inventory = SQLitePlayerRepository._json_object(player["inventory_json"], {})
        stones = int(player["spirit_stones"])
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
                stones += quantity
                actual[key] = quantity
            elif key == "local_reputation":
                local_delta += int(raw_value)
                actual[key] = int(raw_value)
            elif key == "service_reputation":
                service_delta += int(raw_value)
                actual[key] = int(raw_value)
            elif key == "title_key":
                title_key = str(raw_value)
                title = honor_title(title_key)
                if title.closed:
                    raise MainlineContentClosedError("mainline title is not open")
                connection.execute(
                    """
                    INSERT OR IGNORE INTO honor_titles(
                        player_id, title_key, source_operation_id, acquired_at,
                        content_version, rule_version
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        player["id"], title_key, operation_id, now_text,
                        MAINLINE_CONTENT_VERSION, MAINLINE_RULE_VERSION,
                    ),
                )
                actual[key] = title_key
            elif key.startswith("item."):
                quantity = int(raw_value)
                inventory[key] = int(inventory.get(key, 0)) + quantity
                actual[key] = quantity
            elif key.startswith("access.") or key.startswith("codex."):
                quantity = int(raw_value)
                actual[key] = quantity
                event_keys.append(key)
            else:
                raise ValueError(f"unsupported mainline reward: {key}")
        if local_delta or service_delta:
            reputation = connection.execute(
                "SELECT local_json, service_reputation FROM player_reputations WHERE player_id = ?",
                (player["id"],),
            ).fetchone()
            local = SQLitePlayerRepository._json_object(reputation["local_json"], {}) if reputation else {}
            local["local.xuantian.new_town"] = int(local.get("local.xuantian.new_town", 0)) + local_delta
            service = int(reputation["service_reputation"]) if reputation else 0
            service = min(100, service + service_delta)
            connection.execute(
                """
                INSERT INTO player_reputations(player_id, local_json, service_reputation, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(player_id) DO UPDATE SET local_json = excluded.local_json,
                    service_reputation = excluded.service_reputation, updated_at = excluded.updated_at
                """,
                (player["id"], json.dumps(local, ensure_ascii=False, sort_keys=True), service, now_text),
            )
        connection.execute(
            "UPDATE players SET spirit_stones = ?, inventory_json = ?, updated_at = ? WHERE id = ?",
            (stones, json.dumps(inventory, ensure_ascii=False, sort_keys=True), now_text, player["id"]),
        )
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
        now = datetime.now(timezone.utc)
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
            if mode.required_location:
                if int(row["realm_layer"]) < 2:
                    raise LocationRequirementError("spirit cultivation requires qi sensing layer 2")
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
            if int(row["stamina"]) < mode.stamina_cost:
                raise ResourceInsufficientError("stamina is insufficient")

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
                "base_cultivation": mode.base_cultivation,
                "environment_bp": mode.environment_bp,
                "state_bp": state_bp,
            }
            connection.execute(
                "UPDATE players SET stamina = stamina - ?, updated_at = ? WHERE id = ?",
                (mode.stamina_cost, serialize_datetime(now), row["id"]),
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
        now = datetime.now(timezone.utc)
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
        now = datetime.now(timezone.utc)
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
        now_text = serialize_datetime(datetime.now(timezone.utc))
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
            now = datetime.now(timezone.utc)
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
            refund = int(session["stamina_cost"])
            connection.execute(
                "UPDATE players SET stamina = MIN(stamina_max, stamina + ?), updated_at = ? WHERE id = ?",
                (refund, now_text, row["id"]),
            )
            connection.execute(
                "UPDATE cultivation_sessions SET status = 'cancelled', result_json = ?, updated_at = ? WHERE id = ?",
                (json.dumps({"stamina_refund": refund}, ensure_ascii=False, sort_keys=True), now_text, session["id"]),
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (row["id"],)).fetchone()
            if updated is None:
                raise RuntimeError("cultivation cancellation returned no player")
            player = self._row_to_player(updated)
            payload = {
                "player": self._player_payload(player),
                "session_id": session["session_id"],
                "stamina_refund": refund,
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
            return CultivationCancelRecord(player=player, session_id=session["session_id"], stamina_refund=refund)

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
                "content_version": definition.content_version,
                "rule_version": definition.rule_version,
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

            inventory = self._json_object(row["inventory_json"], {})
            item_cost = definition.item_cost_map()
            if definition.required_item and int(inventory.get(definition.required_item, 0)) < 1:
                raise ResourceInsufficientError("retreat required manual is missing")
            for item_key, quantity in item_cost.items():
                if int(inventory.get(item_key, 0)) < quantity:
                    raise ResourceInsufficientError("retreat item is insufficient")
            if int(row["energy"]) < definition.energy_cost:
                raise ResourceInsufficientError("energy is insufficient")
            for item_key, quantity in item_cost.items():
                inventory[item_key] = int(inventory.get(item_key, 0)) - quantity
            seed = f"{definition.random_pool or definition.key}:{definition.rule_version}:{operation_id}"
            snapshot = {
                "retreat_key": definition.key,
                "content_version": definition.content_version,
                "rule_version": definition.rule_version,
                "random_pool": definition.random_pool,
                "random_seed": seed,
                "realm_key": str(row["realm_key"]),
                "realm_layer": int(row["realm_layer"]),
                "path_key": row["path_key"],
                "subprofession_key": row["subprofession_key"],
                "qualification": self._json_object(row["qualification_json"], {}),
                "residence_key": active_residence["residence_key"] if active_residence is not None else None,
                "energy_before": int(row["energy"]),
                "item_cost": item_cost,
            }
            session_id = uuid4().hex
            starts_at = now_text
            ends_at = serialize_datetime(now + timedelta(seconds=definition.duration_seconds))
            connection.execute(
                "UPDATE players SET energy = energy - ?, inventory_json = ?, updated_at = ? WHERE id = ?",
                (
                    definition.energy_cost,
                    json.dumps(inventory, ensure_ascii=False, sort_keys=True),
                    now_text,
                    row["id"],
                ),
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
            inventory = self._json_object(row["inventory_json"], {})
            cultivation = int(row["cultivation"])
            total_cultivation = int(row["total_cultivation"])
            energy = int(row["energy"])
            if "cultivation" in result:
                cultivation += int(result["cultivation"])
                total_cultivation += int(result["cultivation"])
            if "energy" in result:
                energy = min(int(row["energy_max"]), energy + int(result["energy"]))
            connection.execute(
                "UPDATE players SET cultivation = ?, total_cultivation = ?, energy = ?, updated_at = ? WHERE id = ?",
                (cultivation, total_cultivation, energy, now_text, row["id"]),
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

    async def lease_residence(
        self,
        *,
        platform: str,
        platform_user_id: str,
        residence_key: str,
        operation_id: str,
    ) -> ResidenceRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._lease_residence_once,
                platform,
                platform_user_id,
                residence_key,
                operation_id,
            )

    def _lease_residence_once(
        self,
        platform: str,
        platform_user_id: str,
        residence_key: str,
        operation_id: str,
    ) -> ResidenceRecord:
        try:
            definition = residence_definition(residence_key)
        except ValueError as exc:
            raise ResidenceContentClosedError("unsupported residence") from exc
        operation_name = "livelihood.lease_residence"
        request_hash = self._request_hash(operation_name, {"platform": platform, "platform_user_id": platform_user_id, "residence_key": definition.key})
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
                return ResidenceRecord(
                    player=self._row_to_player(payload["player"]),
                    residence_id=str(payload["residence_id"]),
                    residence_key=str(payload["residence_key"]),
                    status=str(payload["status"]),
                    starts_at=str(payload["starts_at"]),
                    ends_at=str(payload["ends_at"]),
                    rent_cost=int(payload["rent_cost"]),
                    already_completed=True,
                )
            row = self._require_player(connection, platform, platform_user_id)
            if str(row["stage"]) not in {STAGE_MORTAL, "seeker", "cultivator"}:
                raise PlayerStageConflictError("residence requires a mortal-stage player")
            active = connection.execute(
                "SELECT * FROM residences WHERE player_id = ? AND status = 'active' ORDER BY id DESC LIMIT 1",
                (row["id"],),
            ).fetchone()
            if active is not None:
                if now < datetime.fromisoformat(str(active["ends_at"])):
                    raise ResidenceAlreadyActiveError("residence is already active")
                connection.execute("UPDATE residences SET status = 'expired', updated_at = ? WHERE id = ?", (now_text, active["id"]))
            if int(row["spirit_stones"]) < definition.rent_cost:
                raise CurrencyInsufficientError("rent is insufficient")
            residence_id = uuid4().hex
            starts_at = now_text
            ends_at = serialize_datetime(now + timedelta(days=definition.lease_days))
            connection.execute(
                "UPDATE players SET spirit_stones = spirit_stones - ?, updated_at = ? WHERE id = ?",
                (definition.rent_cost, now_text, row["id"]),
            )
            connection.execute(
                """
                INSERT INTO residences(
                    residence_id, player_id, operation_id, residence_key, status,
                    starts_at, ends_at, rent_cost, snapshot_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?)
                """,
                (
                    residence_id,
                    row["id"],
                    operation_id,
                    definition.key,
                    starts_at,
                    ends_at,
                    definition.rent_cost,
                    json.dumps({"content_version": definition.content_version, "rule_version": definition.rule_version}, ensure_ascii=False, sort_keys=True),
                    starts_at,
                    starts_at,
                ),
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (row["id"],)).fetchone()
            if updated is None:
                raise RuntimeError("residence lease returned no player")
            payload = {
                "player": self._player_payload(self._row_to_player(updated)),
                "residence_id": residence_id,
                "residence_key": definition.key,
                "status": "active",
                "starts_at": starts_at,
                "ends_at": ends_at,
                "rent_cost": definition.rent_cost,
            }
            connection.execute(
                "INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (operation_id, operation_name, row["id"], request_hash, json.dumps(payload, ensure_ascii=False, sort_keys=True), now_text),
            )
            return ResidenceRecord(
                player=self._row_to_player(updated),
                residence_id=residence_id,
                residence_key=definition.key,
                status="active",
                starts_at=starts_at,
                ends_at=ends_at,
                rent_cost=definition.rent_cost,
            )

    async def get_residence(self, *, platform: str, platform_user_id: str) -> ResidenceRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._get_residence_sync, platform, platform_user_id)

    def _get_residence_sync(self, platform: str, platform_user_id: str) -> ResidenceRecord:
        now = self._now()
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            row = self._require_player(connection, platform, platform_user_id, writable=False)
            residence = connection.execute(
                "SELECT * FROM residences WHERE player_id = ? AND status = 'active' ORDER BY id DESC LIMIT 1",
                (row["id"],),
            ).fetchone()
            if residence is None:
                raise ResidenceNotFoundError("no residence")
            if now >= datetime.fromisoformat(str(residence["ends_at"])):
                connection.execute("UPDATE residences SET status = 'expired', updated_at = ? WHERE id = ?", (now_text, residence["id"]))
                raise ResidenceNotFoundError("residence expired")
            return ResidenceRecord(
                player=self._row_to_player(row),
                residence_id=str(residence["residence_id"]),
                residence_key=str(residence["residence_key"]),
                status="active",
                starts_at=str(residence["starts_at"]),
                ends_at=str(residence["ends_at"]),
                rent_cost=int(residence["rent_cost"]),
            )

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

    @staticmethod
    def _constitution_from_row(
        player_row: sqlite3.Row,
        profile_row: sqlite3.Row,
        *,
        replay: bool = False,
    ) -> ConstitutionRecord:
        definition = constitution_definition(str(profile_row["constitution_key"]))
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
            definition = constitution_definition(constitution_key)
        except ValueError as exc:
            raise ValueError("unsupported constitution") from exc
        operation_name = "constitution.select"
        request_hash = self._request_hash(
            operation_name,
            {
                "platform": platform,
                "platform_user_id": platform_user_id,
                "constitution_key": definition.key,
                "content_version": definition.content_version,
                "rule_version": definition.rule_version,
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
                "content_version": definition.content_version,
                "rule_version": definition.rule_version,
                "effect": dict(definition.effect),
                "qualification": self._json_object(row["qualification_json"], {}),
                "path_key": row["path_key"],
                "subprofession_key": row["subprofession_key"],
                "realm_key": row["realm_key"],
                "realm_layer": int(row["realm_layer"]),
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
            definition = constitution_definition(constitution_key)
        except ValueError as exc:
            raise ValueError("unsupported constitution") from exc
        operation_name = "constitution.reshape"
        request_hash = self._request_hash(
            operation_name,
            {
                "platform": platform,
                "platform_user_id": platform_user_id,
                "constitution_key": definition.key,
                "content_version": definition.content_version,
                "rule_version": definition.rule_version,
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
                if now < last_reshaped_at + timedelta(seconds=RESHAPE_COOLDOWN_SECONDS):
                    raise ConstitutionCooldownError("constitution reshape cooldown is active")
            inventory = self._json_object(row["inventory_json"], {})
            if int(inventory.get(CONSTITUTION_RESET_ITEM, 0)) < 1:
                raise ResourceInsufficientError("constitution reset token is missing")
            inventory[CONSTITUTION_RESET_ITEM] = int(inventory[CONSTITUTION_RESET_ITEM]) - 1
            if inventory[CONSTITUTION_RESET_ITEM] <= 0:
                inventory.pop(CONSTITUTION_RESET_ITEM, None)
            snapshot = {
                "constitution_key": definition.key,
                "content_version": definition.content_version,
                "rule_version": definition.rule_version,
                "effect": dict(definition.effect),
                "qualification": self._json_object(row["qualification_json"], {}),
                "path_key": row["path_key"],
                "subprofession_key": row["subprofession_key"],
                "realm_key": row["realm_key"],
                "realm_layer": int(row["realm_layer"]),
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
            connection.execute(
                "UPDATE players SET inventory_json = ?, updated_at = ? WHERE id = ?",
                (json.dumps(inventory, ensure_ascii=False, sort_keys=True), now_text, row["id"]),
            )
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

    @staticmethod
    def _talent_node_from_row(
        node_row: sqlite3.Row, *, replay: bool = False
    ) -> TalentNodeRecord:
        definition = talent_node_for_reference(str(node_row["node_key"]))
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
            tree_key, tree_label = tree_definition(str(row["path_key"]))
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
                "content_version": TALENT_CONTENT_VERSION,
                "rule_version": TALENT_RULE_VERSION,
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
            tree_key, _ = tree_definition(str(row["path_key"]))
            if normalized_reference.startswith("talent.tree."):
                definition = talent_node_for_reference(normalized_reference)
                if definition.tree_key != tree_key:
                    raise TalentPathMismatchError("talent tree does not match primary path")
            else:
                definition = talent_node_for_reference(normalized_reference, tree_key=tree_key)
            if self._has_active_long_action(connection, int(row["id"])):
                raise TalentBusyError("another long action is active")
            existing_node = connection.execute(
                "SELECT 1 FROM talent_node_states WHERE player_id = ? AND node_key = ? LIMIT 1",
                (row["id"], definition.key),
            ).fetchone()
            if existing_node is not None:
                raise TalentNodeAlreadyLearnedError("talent node is already learned")
            if definition.tier > 1:
                prerequisite_key = f"talent.tree.{tree_key}.tier{definition.tier - 1}"
                prerequisite = connection.execute(
                    "SELECT 1 FROM talent_node_states WHERE player_id = ? AND node_key = ? LIMIT 1",
                    (row["id"], prerequisite_key),
                ).fetchone()
                if prerequisite is None:
                    raise TalentPrerequisiteError("previous talent tier is not learned")

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
                "content_version": definition.content_version,
                "rule_version": definition.rule_version,
                "qualification": self._json_object(row["qualification_json"], {}),
                "path_key": row["path_key"],
                "subprofession_key": row["subprofession_key"],
                "realm_key": row["realm_key"],
                "realm_layer": int(row["realm_layer"]),
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
                connection.execute(
                    "UPDATE players SET talent_points = ?, updated_at = ? WHERE id = ?",
                    (points_after, now_text, row["id"]),
                )
                connection.execute(
                    """
                    INSERT INTO talent_point_events(
                        event_id, player_id, operation_id, delta, balance_before,
                        balance_after, reason, content_version, rule_version, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        uuid4().hex,
                        row["id"],
                        f"{operation_id}:talent-point",
                        -definition.cost_points,
                        points_before,
                        points_after,
                        f"unlock:{definition.key}",
                        definition.content_version,
                        definition.rule_version,
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
            max_level=int(payload.get("max_level", MAX_SKILL_LEVEL)),
            base_effect={str(key): value for key, value in dict(payload.get("base_effect", {})).items()},
            effective_effect={str(key): value for key, value in dict(payload.get("effective_effect", {})).items()},
            insight_cost=int(payload.get("insight_cost", 0)),
            spirit_stone_cost=int(payload.get("spirit_stone_cost", 0)),
            trained_at=str(payload.get("trained_at", "")),
            already_completed=replay,
        )

    @staticmethod
    def _skill_mastery_from_row(
        mastery_row: sqlite3.Row, *, replay: bool = False
    ) -> SkillMasteryRecord:
        definition = skill_definition(str(mastery_row["skill_key"]))
        snapshot = SQLitePlayerRepository._json_object(mastery_row["snapshot_json"], {})
        return SkillMasteryRecord(
            player=None,
            skill_key=str(mastery_row["skill_key"]),
            label=definition.label,
            path_key=mastery_row["path_key"],
            level=int(mastery_row["level"]),
            max_level=int(mastery_row["max_level"]),
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
            max_temper_level=int(payload.get("max_temper_level", MAX_TEMPER_LEVEL)),
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
            material_key=str(payload["material_key"]),
            material_spent=int(payload["material_spent"]),
            spirit_stones_spent=int(payload["spirit_stones_spent"]),
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
            material_key=str(payload["material_key"]),
            material_spent=int(payload["material_spent"]),
            spirit_stones_spent=int(payload["spirit_stones_spent"]),
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
        inventory = SQLitePlayerRepository._json_object(player["inventory_json"], {})
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
        inventory.pop(definition.key, None)
        connection.execute(
            "UPDATE players SET inventory_json = ?, updated_at = ? WHERE id = ?",
            (json.dumps(inventory, ensure_ascii=False, sort_keys=True), now_text, player["id"]),
        )
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
        definition = equipment_definition(equipment_reference)
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
        inventory = SQLitePlayerRepository._json_object(player["inventory_json"], {})
        return int(inventory.get(definition.key, 0)) > 0

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
        definition = equipment_definition(equipment_reference)
        operation_name = "item.tempering"
        request_hash = self._request_hash(
            operation_name,
            {
                "platform": platform,
                "platform_user_id": platform_user_id,
                "equipment_reference": equipment_reference.strip(),
                "item_key": definition.key,
                "content_version": EQUIPMENT_CONTENT_VERSION,
                "rule_version": EQUIPMENT_RULE_VERSION,
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
            material_spent, stones_spent = temper_cost(target_level)
            inventory = self._json_object(player["inventory_json"], {})
            if int(inventory.get(TEMPER_MATERIAL, 0)) < material_spent or int(player["spirit_stones"]) < stones_spent:
                raise ResourceInsufficientError("tempering resources are insufficient")
            equipment = self._resolve_equipment(connection, player, equipment_reference, now_text)
            player = connection.execute("SELECT * FROM players WHERE id = ?", (player["id"],)).fetchone()
            if player is None:
                raise PlayerNotFoundError("player disappeared during equipment resolution")
            inventory = self._json_object(player["inventory_json"], {})
            inventory[TEMPER_MATERIAL] = int(inventory.get(TEMPER_MATERIAL, 0)) - material_spent
            roll_bp = temper_roll_bp(f"{operation_id}:{equipment['instance_id']}:{target_level}")
            success_bp = temper_success_bp(target_level)
            success = roll_bp < success_bp
            level_after = target_level if success else from_level
            connection.execute(
                "UPDATE players SET spirit_stones = spirit_stones - ?, inventory_json = ?, updated_at = ? WHERE id = ?",
                (stones_spent, json.dumps(inventory, ensure_ascii=False, sort_keys=True), now_text, player["id"]),
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
                "material_key": TEMPER_MATERIAL,
                "material_spent": material_spent,
                "spirit_stones_spent": stones_spent,
                "content_version": EQUIPMENT_CONTENT_VERSION,
                "rule_version": EQUIPMENT_RULE_VERSION,
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
                    TEMPER_MATERIAL,
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
                "material_key": TEMPER_MATERIAL,
                "material_spent": material_spent,
                "spirit_stones_spent": stones_spent,
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
        definition = equipment_definition(equipment_reference)
        operation_name = "item.refinement"
        request_hash = self._request_hash(
            operation_name,
            {
                "platform": platform,
                "platform_user_id": platform_user_id,
                "equipment_reference": equipment_reference.strip(),
                "item_key": definition.key,
                "content_version": EQUIPMENT_CONTENT_VERSION,
                "rule_version": EQUIPMENT_RULE_VERSION,
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
            if self._has_active_long_action(connection, int(player["id"])):
                raise EquipmentBusyError("another long action is active")
            if not self._equipment_source_exists(connection, player, definition):
                raise EquipmentNotOwnedError("equipment is not owned")
            material_spent, stones_spent = 2, 30
            inventory = self._json_object(player["inventory_json"], {})
            if int(inventory.get(REFINEMENT_MATERIAL, 0)) < material_spent or int(player["spirit_stones"]) < stones_spent:
                raise ResourceInsufficientError("refinement resources are insufficient")
            equipment = self._resolve_equipment(connection, player, equipment_reference, now_text)
            player = connection.execute("SELECT * FROM players WHERE id = ?", (player["id"],)).fetchone()
            if player is None:
                raise PlayerNotFoundError("player disappeared during equipment resolution")
            inventory = self._json_object(player["inventory_json"], {})
            inventory[REFINEMENT_MATERIAL] = int(inventory.get(REFINEMENT_MATERIAL, 0)) - material_spent
            old_affixes = {
                str(key): int(value)
                for key, value in self._json_object(equipment["affixes_json"], {}).items()
            }
            streak_before = int(equipment["refinement_failure_streak"])
            roll_bp = refinement_roll_bp(f"{operation_id}:{equipment['instance_id']}:{streak_before}")
            success_bp = REFINEMENT_SUCCESS_BP
            success = streak_before >= REFINEMENT_PITY_FAILURES or roll_bp < success_bp
            new_affixes = dict(old_affixes)
            if success:
                affix_key, affix_value = refinement_affix(f"{operation_id}:{equipment['instance_id']}:{streak_before}")
                new_affixes = {affix_key: affix_value}
            streak_after = 0 if success else streak_before + 1
            connection.execute(
                "UPDATE players SET spirit_stones = spirit_stones - ?, inventory_json = ?, updated_at = ? WHERE id = ?",
                (stones_spent, json.dumps(inventory, ensure_ascii=False, sort_keys=True), now_text, player["id"]),
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
                "content_version": EQUIPMENT_CONTENT_VERSION,
                "rule_version": EQUIPMENT_RULE_VERSION,
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
                    10000 if streak_before >= REFINEMENT_PITY_FAILURES else success_bp,
                    REFINEMENT_MATERIAL,
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
            actual_success_bp = 10000 if streak_before >= REFINEMENT_PITY_FAILURES else success_bp
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
                "material_key": REFINEMENT_MATERIAL,
                "material_spent": material_spent,
                "spirit_stones_spent": stones_spent,
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
            return SkillProfileRecord(
                player=self._row_to_player(row),
                skills=tuple(self._skill_mastery_from_row(item) for item in mastery_rows),
                skill_insights=int(row["skill_insights"]),
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
        definition = skill_definition(skill_reference)
        normalized_reference = skill_reference.strip()
        operation_name = "skill.train"
        request_hash = self._request_hash(
            operation_name,
            {
                "platform": platform,
                "platform_user_id": platform_user_id,
                "skill_reference": normalized_reference,
                "skill_key": definition.key,
                "content_version": SKILL_CONTENT_VERSION,
                "rule_version": SKILL_RULE_VERSION,
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
            if definition.key not in available_skill_keys(str(row["path_key"])):
                raise SkillNotAvailableError("skill does not belong to the primary path")
            if self._has_active_long_action(connection, int(row["id"])):
                raise SkillBusyError("another long action is active")

            mastery = connection.execute(
                "SELECT * FROM skill_masteries WHERE player_id = ? AND skill_key = ? LIMIT 1",
                (row["id"], definition.key),
            ).fetchone()
            current_level = int(mastery["level"]) if mastery is not None else 0
            if current_level >= MAX_SKILL_LEVEL:
                raise SkillAlreadyMaxedError("skill is already at maximum level")
            target_level = current_level + 1
            insight_cost, stone_cost = skill_cost(target_level)
            insights_before = int(row["skill_insights"])
            stones_before = int(row["spirit_stones"])
            if insights_before < insight_cost or stones_before < stone_cost:
                raise ResourceInsufficientError("skill resources are insufficient")
            insights_after = insights_before - insight_cost
            stones_after = stones_before - stone_cost
            effective_effect = effective_skill_effect(definition, target_level)
            snapshot = {
                "skill_key": definition.key,
                "path_key": definition.path_key,
                "level": target_level,
                "max_level": MAX_SKILL_LEVEL,
                "base_effect": dict(definition.effect),
                "effective_effect": dict(effective_effect),
                "content_version": definition.content_version,
                "rule_version": definition.rule_version,
                "qualification": self._json_object(row["qualification_json"], {}),
                "realm_key": row["realm_key"],
                "realm_layer": int(row["realm_layer"]),
                "location_key": row["location_key"],
            }
            snapshot_json = json.dumps(snapshot, ensure_ascii=False, sort_keys=True)
            if mastery is None:
                connection.execute(
                    """
                    INSERT INTO skill_masteries(
                        mastery_id, player_id, operation_id, skill_key, path_key, level,
                        max_level, snapshot_json, trained_at, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        uuid4().hex,
                        row["id"],
                        operation_id,
                        definition.key,
                        definition.path_key,
                        target_level,
                        MAX_SKILL_LEVEL,
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
            connection.execute(
                "UPDATE players SET skill_insights = ?, spirit_stones = ?, updated_at = ? WHERE id = ?",
                (insights_after, stones_after, now_text, row["id"]),
            )
            connection.execute(
                """
                INSERT INTO skill_insight_events(
                    event_id, player_id, operation_id, delta, balance_before,
                    balance_after, reason, content_version, rule_version, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    uuid4().hex,
                    row["id"],
                    f"{operation_id}:skill-insight",
                    -insight_cost,
                    insights_before,
                    insights_after,
                    f"train:{definition.key}",
                    SKILL_CONTENT_VERSION,
                    SKILL_RULE_VERSION,
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
                "max_level": MAX_SKILL_LEVEL,
                "base_effect": dict(definition.effect),
                "effective_effect": dict(effective_effect),
                "insight_cost": insight_cost,
                "spirit_stone_cost": stone_cost,
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
        now_text = serialize_datetime(datetime.now(timezone.utc))
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
            unlocks = layer_unlocks(realm_key, layer + 1)
            connection.execute(
                "UPDATE players SET realm_layer = realm_layer + 1, updated_at = ? WHERE id = ?",
                (now_text, row["id"]),
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (row["id"],)).fetchone()
            if updated is None:
                raise RuntimeError("layer advancement returned no player")
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
            self._check_production_requirements(row, recipe)
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
            return ProductionPreviewRecord(
                player=self._row_to_player(row),
                recipe_key=recipe.key,
                recipe_name=recipe.name,
                energy_cost=recipe.energy_cost,
                duration_seconds=recipe.duration_seconds,
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
        from ..production.rules import RECIPE_RULE_VERSION, TOOL_MAX_DURABILITY_BP, random_quality_bp, recipe_definition

        recipe = recipe_definition(recipe_key)
        operation_payload = {
            "platform": platform,
            "platform_user_id": platform_user_id,
            "recipe_key": recipe.key,
        }
        request_hash = self._request_hash("production.start", operation_payload)
        now = datetime.now(timezone.utc)
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            if existing is not None:
                if existing["operation_name"] != "production.start" or existing["request_hash"] != request_hash:
                    raise OperationConflictError("operation input differs from its original request")
                return self._production_order_from_payload(json.loads(existing["result_json"]), replay=True)

            row = self._require_player(connection, platform, platform_user_id)
            if row["stage"] != "cultivator":
                raise PlayerStageConflictError("player is not ready for production")
            self._check_production_requirements(row, recipe)
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

            inventory = self._json_object(row["inventory_json"], {})
            for item_key, quantity in recipe.inputs.items():
                if int(inventory.get(item_key, 0)) < quantity:
                    raise MaterialInsufficientError("recipe inputs are insufficient")
            if int(row["energy"]) < recipe.energy_cost:
                raise EnergyInsufficientError("energy is insufficient")
            if int(row["spirit_stones"]) < recipe.currency_cost:
                raise MaterialInsufficientError("spirit stones are insufficient")

            durability = self._json_object(row["durability_json"], {})
            tool_durability_before: int | None = None
            if recipe.tool_key:
                if int(inventory.get(recipe.tool_key, 0)) < 1:
                    raise ToolMissingError("production tool is missing")
                tool_durability_before = int(durability.get(recipe.tool_key, TOOL_MAX_DURABILITY_BP))
                if tool_durability_before < recipe.tool_cost_bp:
                    raise ToolDurabilityInsufficientError("production tool durability is insufficient")
                durability[recipe.tool_key] = tool_durability_before - recipe.tool_cost_bp
            for item_key, quantity in recipe.inputs.items():
                inventory[item_key] = int(inventory[item_key]) - quantity
            order_id = uuid4().hex
            starts_at = now_text
            ends_at = serialize_datetime(now + timedelta(seconds=recipe.duration_seconds))
            snapshot = {
                "recipe_key": recipe.key,
                "recipe_name": recipe.name,
                "rule_version": RECIPE_RULE_VERSION,
                "realm_key": row["realm_key"],
                "realm_layer": int(row["realm_layer"]),
                "location_key": row["location_key"],
                "inputs": dict(recipe.inputs),
                "tool_key": recipe.tool_key,
                "tool_durability_before": tool_durability_before,
                "tool_durability_after": durability.get(recipe.tool_key) if recipe.tool_key else None,
                "material_quality_bp": 10000,
                "proficiency_bp": 0,
                "random_quality_bp": random_quality_bp(operation_id),
                "currency_cost": recipe.currency_cost,
            }
            connection.execute(
                """
                UPDATE players
                SET energy = energy - ?, spirit_stones = spirit_stones - ?,
                    inventory_json = ?, durability_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    recipe.energy_cost,
                    recipe.currency_cost,
                    json.dumps(inventory, ensure_ascii=False, sort_keys=True),
                    json.dumps(durability, ensure_ascii=False, sort_keys=True),
                    now_text,
                    row["id"],
                ),
            )
            connection.execute(
                """
                INSERT INTO production_orders(
                    order_id, player_id, operation_id, recipe_key, status, starts_at, ends_at,
                    energy_cost, currency_cost, snapshot_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'processing', ?, ?, ?, ?, ?, ?, ?)
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
            }
            connection.execute(
                """
                INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at)
                VALUES (?, 'production.start', ?, ?, ?, ?)
                """,
                (operation_id, row["id"], request_hash, json.dumps(payload, ensure_ascii=False, sort_keys=True), now_text),
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
        from ..production.rules import HIGH_QUALITY_THRESHOLD_BP, QUALITY_SUCCESS_THRESHOLD_BP, recipe_definition

        operation_name = "production.recover" if recovery else "production.complete"
        operation_payload = {"platform": platform, "platform_user_id": platform_user_id}
        request_hash = self._request_hash(operation_name, operation_payload)
        now = datetime.now(timezone.utc)
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
                return self._production_settlement_from_payload(json.loads(existing["result_json"]), replay=True)
            row = self._require_player(connection, platform, platform_user_id)
            order = connection.execute(
                "SELECT * FROM production_orders WHERE player_id = ? AND status IN ('processing', 'expired') ORDER BY id DESC LIMIT 1",
                (row["id"],),
            ).fetchone()
            if order is None:
                raise ProductionNotFoundError("no processing production order")
            ends_at = datetime.fromisoformat(str(order["ends_at"]))
            if not recovery and order["status"] == "expired":
                raise ProductionExpiredError("production order expired")
            if not recovery and now < ends_at:
                raise ProductionNotReadyError("production is not ready")
            if not recovery and now > ends_at + timedelta(hours=24):
                connection.execute(
                    "UPDATE production_orders SET status = 'expired', updated_at = ? WHERE id = ? AND status = 'processing'",
                    (now_text, order["id"]),
                )
                connection.commit()
                raise ProductionExpiredError("production order expired")
            if recovery and now <= ends_at + timedelta(hours=24):
                raise ProductionNotReadyError("production is not ready for recovery")
            recipe = recipe_definition(str(order["recipe_key"]))
            snapshot = self._json_object(order["snapshot_json"], {})
            quality = self._production_quality_from_snapshot(snapshot)
            success = quality >= QUALITY_SUCCESS_THRESHOLD_BP
            inventory = self._json_object(row["inventory_json"], {})
            durability = self._json_object(row["durability_json"], {})
            outputs: dict[str, int] = {}
            refunds: dict[str, int] = {}
            if success:
                outputs.update(recipe.outputs)
                if quality >= HIGH_QUALITY_THRESHOLD_BP:
                    for item_key, quantity in recipe.high_quality_bonus.items():
                        outputs[item_key] = outputs.get(item_key, 0) + quantity
                for item_key, quantity in outputs.items():
                    inventory[item_key] = int(inventory.get(item_key, 0)) + quantity
                if recipe.key == "recipe.weapon.wood_sword":
                    durability["item.weapon.wood_sword"] = max(8000, min(10000, 8000 + quality // 5))
            else:
                for item_key, quantity in recipe.failure_refunds.items():
                    if quantity > 0:
                        refunds[item_key] = quantity
                        inventory[item_key] = int(inventory.get(item_key, 0)) + quantity
            tool_durability = snapshot.get("tool_durability_after")
            status = "completed" if success else "failed"
            connection.execute(
                """
                UPDATE players SET inventory_json = ?, durability_json = ?, updated_at = ? WHERE id = ?
                """,
                (
                    json.dumps(inventory, ensure_ascii=False, sort_keys=True),
                    json.dumps(durability, ensure_ascii=False, sort_keys=True),
                    now_text,
                    row["id"],
                ),
            )
            result = {
                "recipe_key": recipe.key,
                "recipe_name": recipe.name,
                "status": status,
                "quality_bp": quality,
                "random_quality_bp": int(snapshot.get("random_quality_bp", 0)),
                "success": success,
                "outputs": outputs,
                "refunds": refunds,
                "currency_spent": recipe.currency_cost,
                "tool_durability_bp": tool_durability,
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
            connection.execute(
                """
                INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (operation_id, operation_name, row["id"], request_hash, json.dumps(payload, ensure_ascii=False, sort_keys=True), now_text),
            )
            return ProductionSettlementRecord(
                player=player,
                order_id=str(order["order_id"]),
                recipe_key=recipe.key,
                recipe_name=recipe.name,
                status=status,
                quality_bp=quality,
                random_quality_bp=int(snapshot.get("random_quality_bp", 0)),
                success=success,
                outputs=outputs,
                refunds=refunds,
                currency_spent=recipe.currency_cost,
                tool_durability_bp=int(tool_durability) if tool_durability is not None else None,
            )

    @staticmethod
    def _check_production_requirements(row: sqlite3.Row, recipe) -> None:
        teaching = recipe.teaching_allowed and str(row["selected_service"] or "") == recipe.profession
        profession_ok = str(row["subprofession_key"] or "") == recipe.profession or teaching
        if not profession_ok:
            raise RecipeRequirementError("当前道途或生产教学不满足这条配方")
        if teaching and recipe.required_realm == "qi_sensing":
            realm_ok = (
                (str(row["realm_key"]) == "qi_sensing" and int(row["realm_layer"]) >= recipe.min_realm_layer)
                or str(row["realm_key"]) == "qi_gathering"
            )
        else:
            realm_ok = str(row["realm_key"]) == recipe.required_realm and int(row["realm_layer"]) >= recipe.min_realm_layer
        if not realm_ok:
            raise RecipeRequirementError("当前境界不满足这条配方")
        if recipe.required_location and str(row["location_key"]) not in recipe.required_location:
            raise RecipeRequirementError("当前地点不满足这条配方")

    @staticmethod
    def _production_quality_from_snapshot(snapshot: dict[str, Any]) -> int:
        from ..production.rules import production_quality

        return production_quality(
            material_quality_bp=int(snapshot.get("material_quality_bp", 10000)),
            proficiency_bp=int(snapshot.get("proficiency_bp", 0)),
            tool_durability_bp=int(snapshot.get("tool_durability_before", 0) or 0),
            random_quality_bp_value=int(snapshot.get("random_quality_bp", 0)),
        )

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
            already_completed=replay,
        )

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
        now_text = serialize_datetime(datetime.now(timezone.utc))
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
            connection.execute("UPDATE players SET intro_json = ?, updated_at = ? WHERE id = ?", (json.dumps(intro, ensure_ascii=False, sort_keys=True), now_text, row["id"]))
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
        from ..progression.breakthrough.rules import breakthrough_definition, success_bp

        try:
            definition = breakthrough_definition(target_realm)
        except ValueError as exc:
            raise BreakthroughRequirementError("target breakthrough is not open") from exc
        operation_name = definition.key
        operation_payload = {
            "platform": platform,
            "platform_user_id": platform_user_id,
            "target_realm": target_realm,
            "protection": protection,
        }
        request_hash = self._request_hash(operation_name, operation_payload)
        now = datetime.now(timezone.utc)
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
                    connection.execute("UPDATE players SET domain_crack_until = NULL WHERE id = ?", (row["id"],))
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
                if str(row["location_key"]) not in {"void.first_route", "cave.time_garden"}:
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
                connection.execute("UPDATE players SET weakness_until = NULL WHERE id = ?", (row["id"],))
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

            inventory = self._json_object(row["inventory_json"], {})
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
            technique_bonus_bp = (
                definition.technique_bonus_bp
                if definition.technique_bonus_bp and inventory.get("item.manual.basic_qi", 0) > 0
                else 0
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
                if int(inventory.get("item.manual.basic_qi", 0)) > 0 or "preparation.nascent_soul.technique" in flags:
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
                preparation_bp = soul_prepare_bp + reputation_prepare_bp + quest_prepare_bp
                final_success_bp = max(6500, min(9000, 6500 + preparation_bp + pity_before))
            elif is_void_refining:
                route_bonus_bp = min(600, max(0, int(row["void_route_count"])) * 200)
                domain_bonus_bp = min(500, max(0, int(row["domain_power"])) // 10)
                preparation_bp = route_bonus_bp + domain_bonus_bp
                final_success_bp = max(7500, min(9200, 7500 + preparation_bp + min(750, pity_before)))
            else:
                final_success_bp = success_bp(definition, pity_before, preparation_bp)
            for item_key, quantity in definition.materials.items():
                inventory[item_key] = int(inventory.get(item_key, 0)) - quantity
            if alternative_material:
                inventory[alternative_material] = int(inventory.get(alternative_material, 0)) - 2
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
                "rule_version": definition.rule_version,
                "content_version": definition.content_version,
                "random_pool": definition.random_pool,
                "base_success_bp": definition.base_success_bp,
                "required_foundation_quality": definition.required_foundation_quality,
                "foundation_quality": foundation_quality,
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
            connection.execute(
                "UPDATE players SET inventory_json = ?, spirit_stones = spirit_stones - ?, world_merit = world_merit - ?, heart_demon_bonus_bp = CASE WHEN ? = 1 THEN 0 ELSE heart_demon_bonus_bp END, updated_at = ? WHERE id = ?",
                (
                    json.dumps(inventory, ensure_ascii=False, sort_keys=True),
                    definition.currency_cost,
                    100 if is_nascent else (500 if is_soul_transformation or is_void_refining else 0),
                    1 if is_nascent else 0,
                    now_text,
                    row["id"],
                ),
            )
            if is_soul_transformation:
                connection.execute(
                    "UPDATE players SET soul_power = soul_power - 200 WHERE id = ?", (row["id"],)
                )
            if is_void_refining:
                connection.execute(
                    "UPDATE players SET domain_charge = domain_charge - 100 WHERE id = ?", (row["id"],)
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
        from ..paths.rules import domain_definition

        definition = domain_definition(path_key)
        operation_name = "paths.choose_domain"
        request_hash = self._request_hash(operation_name, {"platform": platform, "platform_user_id": platform_user_id, "path_key": path_key})
        now = datetime.now(timezone.utc)
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
                connection.execute("UPDATE players SET domain_crack_until = NULL WHERE id = ?", (row["id"],))
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
            inventory = self._json_object(row["inventory_json"], {})
            if int(inventory.get("item.domain_core", 0)) < 1:
                raise MaterialInsufficientError("domain core is missing")
            if int(row["spirit_stones"]) < 10_000:
                raise CurrencyInsufficientError("domain selection requires spirit stones")
            session_id = uuid4().hex
            ends_at = serialize_datetime(now + timedelta(minutes=5))
            snapshot = {"domain_key": definition.domain_key, "path_key": path_key, "energy_cost": definition.energy_cost, "content_version": "content-0.4", "rule_version": "paths-0.4.0"}
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
        now_text = serialize_datetime(datetime.now(timezone.utc))
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
        now = datetime.now(timezone.utc)
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
            inventory = self._json_object(row["inventory_json"], {})
            if int(inventory.get("item.domain_core", 0)) < 1:
                raise MaterialInsufficientError("domain core is missing")
            if int(row["spirit_stones"]) < 10_000:
                raise CurrencyInsufficientError("domain selection requires spirit stones")
            inventory["item.domain_core"] = int(inventory.get("item.domain_core", 0)) - 1
            snapshot = self._json_object(session["snapshot_json"], {})
            domain_key = str(session["domain_key"])
            pollution_delta = 15 if domain_key == "domain.abyss_shadow" else 0
            bloodline_delta = -10 if domain_key == "domain.ancestral_wild" else 0
            connection.execute("UPDATE players SET domain_key = ?, inventory_json = ?, spirit_stones = spirit_stones - 10000, pollution = pollution + ?, bloodline_stability = MAX(0, bloodline_stability + ?), updated_at = ? WHERE id = ?", (domain_key, json.dumps(inventory, ensure_ascii=False, sort_keys=True), pollution_delta, bloodline_delta, now_text, row["id"]))
            connection.execute("UPDATE domain_selection_sessions SET status = 'confirmed', result_json = ?, updated_at = ? WHERE id = ?", (json.dumps({"domain_key": domain_key, "pollution_delta": pollution_delta, "bloodline_delta": bloodline_delta}, ensure_ascii=False, sort_keys=True), now_text, session["id"]))
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
        now = datetime.now(timezone.utc)
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
            inventory = self._json_object(row["inventory_json"], {})
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
                inventory["item.pill.domain_restore"] = int(inventory.get("item.pill.domain_restore", 0)) - 1
                stones_spent = 2000
                medicine_consumed = True
            connection.execute("UPDATE players SET domain_crack_until = NULL, inventory_json = ?, spirit_stones = spirit_stones - ?, updated_at = ? WHERE id = ?", (json.dumps(inventory, ensure_ascii=False, sort_keys=True), stones_spent, now_text, row["id"]))
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
        from ..progression.breakthrough.rules import (
            breakthrough_roll_bp,
            next_pity_bp,
            retained_cultivation,
        )

        operation_name = "progression.settle_breakthrough"
        request_payload = {"platform": platform, "platform_user_id": platform_user_id}
        request_hash = self._request_hash(operation_name, request_payload)
        now = datetime.now(timezone.utc)
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
            from ..progression.breakthrough.rules import breakthrough_definition

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
            inventory = self._json_object(row["inventory_json"], {})
            protection_consumed = bool(
                (not success)
                and not is_nascent
                and protection_requested
                and int(inventory.get(protection_key, 0)) > 0
            )
            if protection_consumed:
                inventory[protection_key] = int(inventory.get(protection_key, 0)) - 1
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
                for item_key, quantity in reward_items.items():
                    inventory[item_key] = int(inventory.get(item_key, 0)) + quantity
                if is_nascent:
                    connection.execute(
                        "UPDATE players SET realm_key = ?, realm_layer = 1, cultivation = 0, spirit_stones = spirit_stones + ?, stamina = ?, world_merit = world_merit + ?, breakthrough_pity_bp = 0, inventory_json = ?, weakness_until = NULL, soul_power = 100, soul_power_max = 100, domain_charge = 100, domain_charge_max = 100, cross_realm_penalty_bp = ?, max_hp = max_hp + 600, max_mp = max_mp + 480, carry_capacity = carry_capacity + 50, exploration_efficiency_bp = exploration_efficiency_bp + 1500, heart_demon_bonus_bp = 0, soul_fatigue_until = NULL, updated_at = ? WHERE id = ?",
                        (
                            definition.target_realm,
                            definition.reward_currency,
                            stamina_after,
                            definition.reward_world_merit,
                            json.dumps(inventory, ensure_ascii=False, sort_keys=True),
                            0 if str(row["location_key"]).startswith("xuantian.") else 1000,
                            now_text,
                            row["id"],
                        ),
                    )
                elif is_soul_transformation:
                    connection.execute(
                        "UPDATE players SET realm_key = ?, realm_layer = 1, cultivation = 0, spirit_stones = spirit_stones + ?, stamina = ?, world_merit = world_merit + ?, breakthrough_pity_bp = 0, inventory_json = ?, weakness_until = NULL, domain_key = NULL, domain_power = 100, domain_charge = 150, domain_charge_max = 150, domain_charge_reset_date = ?, realm_resistance_bp = 1000, domain_crack_until = NULL, max_hp = max_hp + 1000, max_mp = max_mp + 800, initiative = initiative + 20, updated_at = ? WHERE id = ?",
                        (
                            definition.target_realm,
                            definition.reward_currency,
                            stamina_after,
                            definition.reward_world_merit,
                            json.dumps(inventory, ensure_ascii=False, sort_keys=True),
                            now.date().isoformat(),
                            now_text,
                            row["id"],
                        ),
                    )
                elif is_void_refining:
                    connection.execute(
                        "UPDATE players SET realm_key = ?, realm_layer = 1, cultivation = 0, spirit_stones = spirit_stones + ?, stamina = ?, world_merit = world_merit + ?, breakthrough_pity_bp = 0, inventory_json = ?, weakness_until = NULL, domain_crack_until = NULL, void_power = 200, void_power_max = 200, space_resistance_bp = 1500, void_instability_until = NULL, void_anchor_capacity = 20, void_power_reset_date = ?, max_hp = max_hp + 1500, max_mp = max_mp + 1200, carry_capacity = carry_capacity + 100, updated_at = ? WHERE id = ?",
                        (
                            definition.target_realm,
                            definition.reward_currency,
                            stamina_after,
                            definition.reward_world_merit,
                            json.dumps(inventory, ensure_ascii=False, sort_keys=True),
                            now.date().isoformat(),
                            now_text,
                            row["id"],
                        ),
                    )
                else:
                    connection.execute(
                        "UPDATE players SET realm_key = ?, realm_layer = 1, cultivation = 0, spirit_stones = spirit_stones + ?, stamina = ?, world_merit = world_merit + ?, breakthrough_pity_bp = 0, inventory_json = ?, weakness_until = NULL, updated_at = ? WHERE id = ?",
                        (
                            definition.target_realm,
                            definition.reward_currency,
                            stamina_after,
                            definition.reward_world_merit,
                            json.dumps(inventory, ensure_ascii=False, sort_keys=True),
                            now_text,
                            row["id"],
                        ),
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
                    connection.execute(
                        "UPDATE players SET cultivation = ?, breakthrough_pity_bp = ?, inventory_json = ?, weakness_until = NULL, updated_at = ? WHERE id = ?",
                        (
                            cultivation_after,
                            pity_after,
                            json.dumps(inventory, ensure_ascii=False, sort_keys=True),
                            now_text,
                            row["id"],
                        ),
                    )
                elif is_soul_transformation:
                    domain_crack_until = serialize_datetime(now + timedelta(seconds=weakness_seconds or 24 * 60 * 60))
                    connection.execute(
                        "UPDATE players SET cultivation = ?, breakthrough_pity_bp = ?, inventory_json = ?, domain_crack_until = ?, updated_at = ? WHERE id = ?",
                        (
                            cultivation_after,
                            pity_after,
                            json.dumps(inventory, ensure_ascii=False, sort_keys=True),
                            domain_crack_until,
                            now_text,
                            row["id"],
                        ),
                    )
                    weakness_until = domain_crack_until
                elif is_void_refining:
                    weakness_until = serialize_datetime(now + timedelta(seconds=48 * 60 * 60))
                    connection.execute(
                        "UPDATE players SET cultivation = ?, breakthrough_pity_bp = ?, inventory_json = ?, void_instability_until = ?, weakness_until = NULL, updated_at = ? WHERE id = ?",
                        (
                            cultivation_after,
                            pity_after,
                            json.dumps(inventory, ensure_ascii=False, sort_keys=True),
                            weakness_until,
                            now_text,
                            row["id"],
                        ),
                    )
                else:
                    weakness_until = serialize_datetime(now + timedelta(seconds=weakness_seconds))
                    connection.execute(
                        "UPDATE players SET cultivation = ?, breakthrough_pity_bp = ?, inventory_json = ?, weakness_until = ?, updated_at = ? WHERE id = ?",
                        (
                            cultivation_after,
                            pity_after,
                            json.dumps(inventory, ensure_ascii=False, sort_keys=True),
                            weakness_until,
                            now_text,
                            row["id"],
                        ),
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
                "content_version": str(snapshot.get("content_version", definition.content_version)),
                "rule_version": str(snapshot.get("rule_version", definition.rule_version)),
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
                    "target_realm": "nascent_soul",
                    "expires_at": serialize_datetime(now + timedelta(hours=24)),
                    "content_version": result["content_version"],
                    "rule_version": result["rule_version"],
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
        now = datetime.now(timezone.utc)
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
                raise HeartDemonPendingError("no pending heart demon")
            try:
                expired = now >= datetime.fromisoformat(str(session["expires_at"]))
            except ValueError:
                expired = False
            effective_choice = "heart_demon.face" if expired else choice_key
            if effective_choice == "heart_demon.bargain" and str(row["path_key"] or "") != "demonic" and int(row["pollution"]) < 20:
                raise BreakthroughRequirementError("bargain requires a demonic path or pollution 20")
            inventory = self._json_object(row["inventory_json"], {})
            if effective_choice == "heart_demon.purify":
                if int(inventory.get("item.pill.soul_restore", 0)) < 1:
                    raise MaterialInsufficientError("soul restore pill is missing")
                inventory["item.pill.soul_restore"] = int(inventory.get("item.pill.soul_restore", 0)) - 1
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
            connection.execute(
                "UPDATE players SET inventory_json = ?, pollution = ?, world_merit = world_merit + ?, breakthrough_pity_bp = ?, heart_demon_bonus_bp = ?, soul_fatigue_until = ?, updated_at = ? WHERE id = ?",
                (
                    json.dumps(inventory, ensure_ascii=False, sort_keys=True),
                    pollution_after,
                    merit_gain,
                    pity_after,
                    bonus_after,
                    fatigue_until,
                    now_text,
                    row["id"],
                ),
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
        now = datetime.now(timezone.utc)
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
            connection.execute("UPDATE players SET soul_fatigue_until = NULL, updated_at = ? WHERE id = ?", (now_text, row["id"]))
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
        now = datetime.now(timezone.utc)
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
            inventory = self._json_object(row["inventory_json"], {})
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
                inventory[medicine_key] = int(inventory.get(medicine_key, 0)) - 1
                medicine_consumed = True
                stones_spent = stones_cost
            connection.execute(
                "UPDATE players SET weakness_until = NULL, inventory_json = ?, spirit_stones = spirit_stones - ?, updated_at = ? WHERE id = ?",
                (json.dumps(inventory, ensure_ascii=False, sort_keys=True), stones_spent, now_text, row["id"]),
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
        now = datetime.now(timezone.utc)
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
                connection.execute(
                    "UPDATE players SET dao_name = ?, updated_at = ? WHERE id = ?",
                    (dao_name, serialize_datetime(now), row["id"]),
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

    async def claim_daily(
        self,
        *,
        platform: str,
        platform_user_id: str,
        operation_id: str,
    ) -> RoutineClaimRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._claim_daily_sync, platform, platform_user_id, operation_id
            )

    def _claim_daily_sync(
        self, platform: str, platform_user_id: str, operation_id: str
    ) -> RoutineClaimRecord:
        operation_name = "routine.checkin.daily"
        request_payload = {
            "platform": platform,
            "platform_user_id": platform_user_id,
            "content_version": ROUTINE_CONTENT_VERSION,
            "rule_version": ROUTINE_RULE_VERSION,
        }
        request_hash = self._request_hash(operation_name, request_payload)
        for attempt in range(5):
            try:
                return self._claim_daily_once(
                    platform,
                    platform_user_id,
                    operation_id,
                    operation_name,
                    request_hash,
                )
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).lower():
                    raise
                if attempt == 4:
                    raise RepositoryBusyError("database remained locked") from exc
                time.sleep(0.01 * (2**attempt))
        raise RepositoryBusyError("database remained locked")

    def _claim_daily_once(
        self,
        platform: str,
        platform_user_id: str,
        operation_id: str,
        operation_name: str,
        request_hash: str,
    ) -> RoutineClaimRecord:
        now = self._now()
        today = now.date()
        target_date = today.isoformat()
        month_key = today.strftime("%Y-%m")
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
                return self._routine_claim_from_payload(
                    json.loads(existing["result_json"]), replay=True
                )

            row = self._require_player(connection, platform, platform_user_id)
            duplicate = connection.execute(
                "SELECT 1 FROM routine_checkins WHERE player_id = ? AND target_date = ? LIMIT 1",
                (row["id"], target_date),
            ).fetchone()
            if duplicate is not None:
                raise CheckinAlreadyClaimedError("daily check-in already claimed")

            previous = connection.execute(
                "SELECT target_date FROM routine_checkins "
                "WHERE player_id = ? AND claim_kind = 'daily' AND target_date < ? "
                "ORDER BY target_date DESC",
                (row["id"], target_date),
            ).fetchall()
            previous_dates = {str(item["target_date"]) for item in previous}
            streak_before = 0
            cursor = today - timedelta(days=1)
            while cursor.isoformat() in previous_dates:
                streak_before += 1
                cursor -= timedelta(days=1)
            streak_after = streak_before + 1
            requested_reward = checkin_reward(streak_after)
            inventory = self._json_object(row["inventory_json"], {})
            stones = int(row["spirit_stones"]) + int(requested_reward.get("spirit_stones", 0))
            current_energy = int(row["energy"])
            energy_gain = min(
                int(requested_reward.get("energy", 0)),
                max(0, int(row["energy_max"]) - current_energy),
            )
            energy = current_energy + energy_gain
            applied_reward: dict[str, int] = {"spirit_stones": int(requested_reward.get("spirit_stones", 0))}
            applied_reward["energy"] = energy_gain
            for key, quantity in requested_reward.items():
                if key in {"spirit_stones", "energy"}:
                    continue
                inventory[key] = int(inventory.get(key, 0)) + int(quantity)
                applied_reward[key] = int(quantity)

            connection.execute(
                "UPDATE players SET spirit_stones = ?, energy = ?, inventory_json = ?, updated_at = ? WHERE id = ?",
                (stones, energy, json.dumps(inventory, ensure_ascii=False, sort_keys=True), now_text, row["id"]),
            )
            connection.execute(
                """
                INSERT INTO routine_checkins(
                    player_id, activity_key, target_date, claim_kind, month_key, operation_id,
                    status, cost_json, reward_json, streak_before, streak_after,
                    content_version, rule_version, created_at, settled_at
                ) VALUES (?, ?, ?, 'daily', ?, ?, 'claimed', '{}', ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["id"], CHECKIN_ACTIVITY, target_date, month_key, operation_id,
                    json.dumps(applied_reward, ensure_ascii=False, sort_keys=True),
                    streak_before, streak_after, ROUTINE_CONTENT_VERSION, ROUTINE_RULE_VERSION,
                    now_text, now_text,
                ),
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (row["id"],)).fetchone()
            if updated is None:
                raise RuntimeError("daily check-in returned no player")
            payload = {
                "player": self._player_payload(self._row_to_player(updated)),
                "activity_key": CHECKIN_ACTIVITY,
                "target_date": target_date,
                "reward": applied_reward,
                "requested_reward": requested_reward,
                "energy_spent": 0,
                "consecutive_days": streak_after,
                "streak_before": streak_before,
                "makeup": False,
                "content_version": ROUTINE_CONTENT_VERSION,
                "rule_version": ROUTINE_RULE_VERSION,
            }
            connection.execute(
                "INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    operation_id, operation_name, row["id"], request_hash,
                    json.dumps(payload, ensure_ascii=False, sort_keys=True), now_text,
                ),
            )
            return self._routine_claim_from_payload(payload)

    async def makeup_daily(
        self,
        *,
        platform: str,
        platform_user_id: str,
        target_date: str,
        operation_id: str,
    ) -> RoutineClaimRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._makeup_daily_sync,
                platform,
                platform_user_id,
                target_date,
                operation_id,
            )

    def _makeup_daily_sync(
        self, platform: str, platform_user_id: str, target_date: str, operation_id: str
    ) -> RoutineClaimRecord:
        operation_name = "routine.makeup.daily"
        request_payload = {
            "platform": platform,
            "platform_user_id": platform_user_id,
            "target_date": target_date,
            "content_version": ROUTINE_CONTENT_VERSION,
            "rule_version": ROUTINE_RULE_VERSION,
        }
        request_hash = self._request_hash(operation_name, request_payload)
        for attempt in range(5):
            try:
                return self._makeup_daily_once(
                    platform,
                    platform_user_id,
                    target_date,
                    operation_id,
                    operation_name,
                    request_hash,
                )
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).lower():
                    raise
                if attempt == 4:
                    raise RepositoryBusyError("database remained locked") from exc
                time.sleep(0.01 * (2**attempt))
        raise RepositoryBusyError("database remained locked")

    def _makeup_daily_once(
        self,
        platform: str,
        platform_user_id: str,
        target_date: str,
        operation_id: str,
        operation_name: str,
        request_hash: str,
    ) -> RoutineClaimRecord:
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
                return self._routine_claim_from_payload(
                    json.loads(existing["result_json"]), replay=True
                )

            try:
                parsed_target = parse_past_date(target_date, now.date())
            except ValueError as exc:
                raise RoutineMakeupDateError(str(exc)) from exc
            canonical_target = parsed_target.isoformat()
            month_key = now.date().strftime("%Y-%m")
            row = self._require_player(connection, platform, platform_user_id)
            duplicate = connection.execute(
                "SELECT 1 FROM routine_checkins WHERE player_id = ? AND target_date = ? LIMIT 1",
                (row["id"], canonical_target),
            ).fetchone()
            if duplicate is not None:
                raise RoutineMakeupNotEligibleError("date was already claimed")
            used = connection.execute(
                "SELECT COUNT(*) AS count FROM routine_checkins WHERE player_id = ? AND claim_kind = 'makeup' AND month_key = ?",
                (row["id"], month_key),
            ).fetchone()
            if int(used["count"]) >= 2:
                raise RoutineMakeupLimitError("monthly makeup limit reached")
            if int(row["spirit_stones"]) < 30:
                raise CurrencyInsufficientError("makeup requires 30 spirit stones")

            requested_reward = makeup_reward()
            current_energy = int(row["energy"])
            energy_gain = min(
                int(requested_reward.get("energy", 0)),
                max(0, int(row["energy_max"]) - current_energy),
            )
            applied_reward = {
                "spirit_stones": int(requested_reward.get("spirit_stones", 0)),
                "energy": energy_gain,
            }
            stones = int(row["spirit_stones"]) - 30 + applied_reward["spirit_stones"]
            connection.execute(
                "UPDATE players SET spirit_stones = ?, energy = ?, updated_at = ? WHERE id = ?",
                (stones, current_energy + energy_gain, now_text, row["id"]),
            )
            connection.execute(
                """
                INSERT INTO routine_checkins(
                    player_id, activity_key, target_date, claim_kind, month_key, operation_id,
                    status, cost_json, reward_json, streak_before, streak_after,
                    content_version, rule_version, created_at, settled_at
                ) VALUES (?, ?, ?, 'makeup', ?, ?, 'claimed', ?, ?, 0, 0, ?, ?, ?, ?)
                """,
                (
                    row["id"], MAKEUP_ACTIVITY, canonical_target, month_key, operation_id,
                    json.dumps({"spirit_stones": 30}, ensure_ascii=False, sort_keys=True),
                    json.dumps(applied_reward, ensure_ascii=False, sort_keys=True),
                    ROUTINE_CONTENT_VERSION, ROUTINE_RULE_VERSION, now_text, now_text,
                ),
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (row["id"],)).fetchone()
            if updated is None:
                raise RuntimeError("makeup check-in returned no player")
            payload = {
                "player": self._player_payload(self._row_to_player(updated)),
                "activity_key": MAKEUP_ACTIVITY,
                "target_date": canonical_target,
                "reward": applied_reward,
                "requested_reward": requested_reward,
                "energy_spent": 0,
                "spirit_stones_spent": 30,
                "consecutive_days": 0,
                "streak_before": 0,
                "makeup": True,
                "content_version": ROUTINE_CONTENT_VERSION,
                "rule_version": ROUTINE_RULE_VERSION,
            }
            connection.execute(
                "INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    operation_id, operation_name, row["id"], request_hash,
                    json.dumps(payload, ensure_ascii=False, sort_keys=True), now_text,
                ),
            )
            return self._routine_claim_from_payload(payload)

    @staticmethod
    def _routine_claim_from_payload(
        payload: dict[str, Any], replay: bool = False
    ) -> RoutineClaimRecord:
        return RoutineClaimRecord(
            player=SQLitePlayerRepository._row_to_player(payload["player"]),
            activity_key=str(payload.get("activity_key", CHECKIN_ACTIVITY)),
            target_date=str(payload["target_date"]),
            reward={str(k): int(v) for k, v in dict(payload.get("reward", {})).items()},
            energy_spent=int(payload.get("energy_spent", 0)),
            spirit_stones_spent=int(payload.get("spirit_stones_spent", 0)),
            consecutive_days=int(payload.get("consecutive_days", 0)),
            makeup=bool(payload.get("makeup", False)),
            already_completed=replay,
        )

    async def water_spirit_tree(
        self,
        *,
        platform: str,
        platform_user_id: str,
        operation_id: str,
    ) -> SpiritTreeRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._water_spirit_tree_sync, platform, platform_user_id, operation_id
            )

    def _water_spirit_tree_sync(
        self, platform: str, platform_user_id: str, operation_id: str
    ) -> SpiritTreeRecord:
        operation_name = "routine.spirit_tree.water"
        request_hash = self._request_hash(
            operation_name,
            {
                "platform": platform,
                "platform_user_id": platform_user_id,
                "content_version": ROUTINE_CONTENT_VERSION,
                "rule_version": ROUTINE_RULE_VERSION,
            },
        )
        for attempt in range(5):
            try:
                return self._water_spirit_tree_once(
                    platform, platform_user_id, operation_id, operation_name, request_hash
                )
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).lower():
                    raise
                if attempt == 4:
                    raise RepositoryBusyError("database remained locked") from exc
                time.sleep(0.01 * (2**attempt))
        raise RepositoryBusyError("database remained locked")

    def _water_spirit_tree_once(
        self,
        platform: str,
        platform_user_id: str,
        operation_id: str,
        operation_name: str,
        request_hash: str,
    ) -> SpiritTreeRecord:
        now = self._now()
        today = now.date().isoformat()
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
                return self._spirit_tree_from_payload(
                    json.loads(existing["result_json"]), replay=True
                )
            row = self._require_player(connection, platform, platform_user_id)
            tree = connection.execute(
                "SELECT * FROM spirit_trees WHERE player_id = ?", (row["id"],)
            ).fetchone()
            if tree is None:
                connection.execute(
                    "INSERT INTO spirit_trees(player_id, cycle_no, water_count, content_version, rule_version, updated_at) VALUES (?, 1, 0, ?, ?, ?)",
                    (row["id"], ROUTINE_CONTENT_VERSION, ROUTINE_RULE_VERSION, now_text),
                )
                tree = connection.execute(
                    "SELECT * FROM spirit_trees WHERE player_id = ?", (row["id"],)
                ).fetchone()
            if tree is None:
                raise RuntimeError("spirit tree initialization failed")
            cooldown_until = tree["cooldown_until"]
            if cooldown_until and now_text < str(cooldown_until):
                raise SpiritTreeCooldownError("spirit tree is cooling down")
            cycle_no = int(tree["cycle_no"])
            if int(tree["water_count"]) >= 7:
                raise SpiritTreeWateredError("spirit tree is ready for harvest")
            duplicate = connection.execute(
                "SELECT 1 FROM spirit_tree_waterings WHERE player_id = ? AND cycle_no = ? AND business_date = ? LIMIT 1",
                (row["id"], cycle_no, today),
            ).fetchone()
            if duplicate is not None:
                raise SpiritTreeWateredError("spirit tree already watered today")
            if int(row["energy"]) < 2:
                raise ResourceInsufficientError("watering requires two energy")
            water_count = int(tree["water_count"]) + 1
            cycle_started_at = tree["cycle_started_at"] or now_text
            connection.execute(
                "UPDATE players SET energy = energy - 2, updated_at = ? WHERE id = ?",
                (now_text, row["id"]),
            )
            connection.execute(
                "INSERT INTO spirit_tree_waterings(player_id, cycle_no, business_date, operation_id, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    row["id"], cycle_no, today, operation_id,
                    json.dumps({"water_count": water_count, "energy_spent": 2, "content_version": ROUTINE_CONTENT_VERSION, "rule_version": ROUTINE_RULE_VERSION}, ensure_ascii=False, sort_keys=True),
                    now_text,
                ),
            )
            connection.execute(
                "UPDATE spirit_trees SET water_count = ?, last_water_date = ?, cycle_started_at = ?, snapshot_json = ?, result_json = ?, updated_at = ? WHERE player_id = ?",
                (
                    water_count, today, cycle_started_at,
                    json.dumps({"cycle_no": cycle_no}, ensure_ascii=False, sort_keys=True),
                    json.dumps({"water_count": water_count}, ensure_ascii=False, sort_keys=True),
                    now_text, row["id"],
                ),
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (row["id"],)).fetchone()
            player = self._row_to_player(updated) if updated is not None else None
            if player is None:
                raise RuntimeError("watering returned no player")
            status = tree_status(water_count, None, now_text)
            payload = {
                "player": self._player_payload(player),
                "status": status,
                "water_count": water_count,
                "energy_spent": 2,
                "reward": {},
                "cooldown_until": None,
                "cycle_no": cycle_no,
                "content_version": ROUTINE_CONTENT_VERSION,
                "rule_version": ROUTINE_RULE_VERSION,
            }
            connection.execute(
                "INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    operation_id, operation_name, row["id"], request_hash,
                    json.dumps(payload, ensure_ascii=False, sort_keys=True), now_text,
                ),
            )
            return self._spirit_tree_from_payload(payload)

    async def harvest_spirit_tree(
        self,
        *,
        platform: str,
        platform_user_id: str,
        operation_id: str,
    ) -> SpiritTreeRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._harvest_spirit_tree_sync, platform, platform_user_id, operation_id
            )

    def _harvest_spirit_tree_sync(
        self, platform: str, platform_user_id: str, operation_id: str
    ) -> SpiritTreeRecord:
        operation_name = "routine.spirit_tree.harvest"
        request_hash = self._request_hash(
            operation_name,
            {
                "platform": platform,
                "platform_user_id": platform_user_id,
                "content_version": ROUTINE_CONTENT_VERSION,
                "rule_version": ROUTINE_RULE_VERSION,
            },
        )
        for attempt in range(5):
            try:
                return self._harvest_spirit_tree_once(
                    platform, platform_user_id, operation_id, operation_name, request_hash
                )
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).lower():
                    raise
                if attempt == 4:
                    raise RepositoryBusyError("database remained locked") from exc
                time.sleep(0.01 * (2**attempt))
        raise RepositoryBusyError("database remained locked")

    def _harvest_spirit_tree_once(
        self,
        platform: str,
        platform_user_id: str,
        operation_id: str,
        operation_name: str,
        request_hash: str,
    ) -> SpiritTreeRecord:
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
                return self._spirit_tree_from_payload(
                    json.loads(existing["result_json"]), replay=True
                )
            row = self._require_player(connection, platform, platform_user_id)
            tree = connection.execute(
                "SELECT * FROM spirit_trees WHERE player_id = ?", (row["id"],)
            ).fetchone()
            if tree is None:
                raise SpiritTreeNotReadyError("spirit tree is not ready")
            cooldown_until = tree["cooldown_until"]
            if cooldown_until and now_text < str(cooldown_until):
                raise SpiritTreeCooldownError("spirit tree is cooling down")
            if int(tree["water_count"]) < 7:
                raise SpiritTreeNotReadyError("spirit tree is not ready")
            cycle_no = int(tree["cycle_no"])
            reward = tree_harvest_reward(operation_id)
            digest = hashlib.blake2b(
                f"tree.harvest.v0.1:{operation_id}".encode("utf-8"), digest_size=16
            ).hexdigest()
            inventory = self._json_object(row["inventory_json"], {})
            stones = int(row["spirit_stones"]) + int(reward.get("spirit_stones", 0))
            actual_reward: dict[str, int] = {}
            for key, quantity in reward.items():
                quantity = int(quantity)
                if key == "spirit_stones":
                    actual_reward[key] = quantity
                elif key == "local_reputation":
                    actual_reward[key] = quantity
                else:
                    inventory[key] = int(inventory.get(key, 0)) + quantity
                    actual_reward[key] = quantity
            reputation = connection.execute(
                "SELECT local_json, service_reputation FROM player_reputations WHERE player_id = ?",
                (row["id"],),
            ).fetchone()
            local = self._json_object(reputation["local_json"], {}) if reputation is not None else {}
            local["local.xuantian.new_town"] = int(local.get("local.xuantian.new_town", 0)) + int(reward.get("local_reputation", 0))
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
            cooldown = now + timedelta(hours=24)
            cooldown_text = serialize_datetime(cooldown)
            connection.execute(
                "UPDATE players SET spirit_stones = ?, inventory_json = ?, updated_at = ? WHERE id = ?",
                (stones, json.dumps(inventory, ensure_ascii=False, sort_keys=True), now_text, row["id"]),
            )
            result = {
                "pool_key": "tree.harvest.v0.1",
                "seed": digest,
                "reward": actual_reward,
                "content_version": ROUTINE_CONTENT_VERSION,
                "rule_version": ROUTINE_RULE_VERSION,
            }
            connection.execute(
                "INSERT INTO spirit_tree_harvests(player_id, cycle_no, operation_id, pool_key, seed, reward_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (row["id"], cycle_no, operation_id, result["pool_key"], digest, json.dumps(actual_reward, ensure_ascii=False, sort_keys=True), now_text),
            )
            connection.execute(
                "UPDATE spirit_trees SET cycle_no = ?, water_count = 0, last_water_date = NULL, cycle_started_at = NULL, cooldown_until = ?, result_json = ?, updated_at = ? WHERE player_id = ?",
                (cycle_no + 1, cooldown_text, json.dumps(result, ensure_ascii=False, sort_keys=True), now_text, row["id"]),
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (row["id"],)).fetchone()
            player = self._row_to_player(updated) if updated is not None else None
            if player is None:
                raise RuntimeError("harvest returned no player")
            payload = {
                "player": self._player_payload(player),
                "status": "cooldown",
                "water_count": 0,
                "energy_spent": 0,
                "reward": actual_reward,
                "cooldown_until": cooldown_text,
                "cycle_no": cycle_no,
                **result,
            }
            connection.execute(
                "INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    operation_id, operation_name, row["id"], request_hash,
                    json.dumps(payload, ensure_ascii=False, sort_keys=True), now_text,
                ),
            )
            return self._spirit_tree_from_payload(payload)

    @staticmethod
    def _spirit_tree_from_payload(
        payload: dict[str, Any], replay: bool = False
    ) -> SpiritTreeRecord:
        return SpiritTreeRecord(
            player=SQLitePlayerRepository._row_to_player(payload["player"]),
            status=str(payload.get("status", "dormant")),
            water_count=int(payload.get("water_count", 0)),
            energy_spent=int(payload.get("energy_spent", 0)),
            reward={str(k): int(v) for k, v in dict(payload.get("reward", {})).items()},
            cooldown_until=payload.get("cooldown_until"),
            already_completed=replay,
        )

    async def get_seven_day_status(
        self,
        *,
        platform: str,
        platform_user_id: str,
    ) -> SevenDayStatusRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._get_seven_day_status_sync, platform, platform_user_id
            )

    def _get_seven_day_status_sync(
        self, platform: str, platform_user_id: str
    ) -> SevenDayStatusRecord:
        now = self._now()
        with self._connect() as connection:
            row = self._require_player(connection, platform, platform_user_id)
            campaign = self._ensure_seven_day_campaign(
                connection, row, serialize_datetime(now)
            )
            return self._seven_day_status_from_connection(connection, row, campaign, now)

    @staticmethod
    def _ensure_seven_day_campaign(
        connection: sqlite3.Connection,
        player: sqlite3.Row,
        now_text: str,
    ) -> sqlite3.Row:
        campaign = connection.execute(
            "SELECT * FROM seven_day_campaigns WHERE player_id = ?",
            (player["id"],),
        ).fetchone()
        if campaign is not None:
            return campaign
        seeking = connection.execute(
            """
            SELECT created_at FROM operations
            WHERE player_id = ? AND operation_name = 'player.start_seeking'
            ORDER BY created_at ASC LIMIT 1
            """,
            (player["id"],),
        ).fetchone()
        if seeking is None:
            raise SevenDayNotStartedError("seven-day campaign has not started")
        try:
            start_date = datetime.fromisoformat(str(seeking["created_at"])).date().isoformat()
        except ValueError as exc:
            raise SevenDayNotStartedError("invalid seeking timestamp") from exc
        connection.execute(
            """
            INSERT INTO seven_day_campaigns(
                player_id, start_date, status, content_version, rule_version,
                created_at, updated_at
            ) VALUES (?, ?, 'active', ?, ?, ?, ?)
            """,
            (
                player["id"], start_date, SEVEN_DAY_CONTENT_VERSION,
                SEVEN_DAY_RULE_VERSION, now_text, now_text,
            ),
        )
        created = connection.execute(
            "SELECT * FROM seven_day_campaigns WHERE player_id = ?",
            (player["id"],),
        ).fetchone()
        if created is None:
            raise RuntimeError("seven-day campaign initialization failed")
        return created

    @staticmethod
    def _seven_day_source_operation(
        connection: sqlite3.Connection,
        player_id: int,
        goal,
        target_date: str,
    ) -> str | None:
        used = {
            str(item["source_operation_id"])
            for item in connection.execute(
                "SELECT source_operation_id FROM seven_day_goal_claims WHERE player_id = ?",
                (player_id,),
            ).fetchall()
        }
        if goal.event_key == "routine.checkin.daily":
            candidates = connection.execute(
                """
                SELECT operation_id FROM routine_checkins
                WHERE player_id = ? AND claim_kind = 'daily' AND target_date >= ?
                ORDER BY target_date ASC, id ASC
                """,
                (player_id, target_date),
            ).fetchall()
        elif goal.event_key == "explore.gather_outskirts":
            candidates = connection.execute(
                """
                SELECT operation_id FROM exploration_sessions
                WHERE player_id = ? AND mode_key = ? AND status = 'settled'
                ORDER BY id ASC
                """,
                (player_id, goal.event_key),
            ).fetchall()
        elif goal.event_key == "production.preview":
            candidates = connection.execute(
                """
                SELECT source_operation_id FROM activity_events
                WHERE player_id = ? AND event_key = 'production.preview'
                ORDER BY occurred_at ASC, id ASC
                """,
                (player_id,),
            ).fetchall()
            if not candidates:
                # Older rows may predate preview activity auditing; a started
                # order remains a compatible durable fallback.
                candidates = connection.execute(
                    """
                    SELECT operation_id FROM production_orders
                    WHERE player_id = ? AND status IN ('processing', 'completed', 'failed')
                    ORDER BY starts_at ASC, id ASC
                    """,
                    (player_id,),
                ).fetchall()
        elif goal.event_key == "bounty.accept":
            candidates = connection.execute(
                """
                SELECT operation_id FROM bounty_offers
                WHERE player_id = ?
                ORDER BY accepted_at ASC, id ASC
                """,
                (player_id,),
            ).fetchall()
        elif goal.event_key == "player.enter_cultivation":
            candidates = connection.execute(
                """
                SELECT operation_id FROM operations
                WHERE player_id = ? AND operation_name = ?
                ORDER BY created_at ASC
                """,
                (player_id, goal.event_key),
            ).fetchall()
        else:
            candidates = connection.execute(
                """
                SELECT source_operation_id FROM activity_events
                WHERE player_id = ? AND event_key = ? AND occurred_at >= ?
                ORDER BY occurred_at ASC, id ASC
                """,
                (player_id, goal.event_key, f"{target_date}T00:00:00+00:00"),
            ).fetchall()
        for candidate in candidates:
            value = str(candidate["operation_id"] if "operation_id" in candidate.keys() else candidate["source_operation_id"])
            if value not in used:
                return value
        return None

    def _seven_day_status_from_connection(
        self,
        connection: sqlite3.Connection,
        player: sqlite3.Row,
        campaign: sqlite3.Row,
        now: datetime,
    ) -> SevenDayStatusRecord:
        start = date.fromisoformat(str(campaign["start_date"]))
        current_day = (now.date() - start).days + 1
        current_day = max(0, min(len(SEVEN_DAY_GOALS), current_day))
        claims = {
            int(item["day_number"]): item
            for item in connection.execute(
                "SELECT * FROM seven_day_goal_claims WHERE player_id = ?",
                (player["id"],),
            ).fetchall()
        }
        goals: list[SevenDayGoalView] = []
        for definition in SEVEN_DAY_GOALS:
            target_date = (start + timedelta(days=definition.day_number - 1)).isoformat()
            claim = claims.get(definition.day_number)
            if claim is not None:
                state = "claimed"
                source = str(claim["source_operation_id"])
            elif current_day < definition.day_number:
                state = "locked"
                source = None
            elif definition.closed:
                state = "content_closed"
                source = None
            else:
                source = self._seven_day_source_operation(
                    connection, int(player["id"]), definition, target_date
                )
                state = "claimable" if source else "pending"
            goals.append(
                SevenDayGoalView(
                    day_number=definition.day_number,
                    goal_key=definition.key,
                    label=definition.label,
                    target_date=target_date,
                    state=state,
                    reward=seven_day_reward(definition),
                    source_operation_id=source,
                )
            )
        status = "completed" if all(goal.state == "claimed" for goal in goals) else str(campaign["status"])
        if status != campaign["status"]:
            connection.execute(
                "UPDATE seven_day_campaigns SET status = ?, updated_at = ? WHERE player_id = ?",
                (status, serialize_datetime(now), player["id"]),
            )
        return SevenDayStatusRecord(
            player=self._row_to_player(player),
            start_date=str(campaign["start_date"]),
            current_day=current_day,
            status=status,
            goals=tuple(goals),
        )

    async def claim_seven_day_goal(
        self,
        *,
        platform: str,
        platform_user_id: str,
        day_number: int,
        operation_id: str,
    ) -> SevenDayGoalRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._claim_seven_day_goal_sync,
                platform,
                platform_user_id,
                day_number,
                operation_id,
            )

    def _claim_seven_day_goal_sync(
        self,
        platform: str,
        platform_user_id: str,
        day_number: int,
        operation_id: str,
    ) -> SevenDayGoalRecord:
        operation_name = "routine.claim_seven_day_goal"
        request_payload = {
            "platform": platform,
            "platform_user_id": platform_user_id,
            "day_number": day_number,
            "content_version": SEVEN_DAY_CONTENT_VERSION,
            "rule_version": SEVEN_DAY_RULE_VERSION,
        }
        request_hash = self._request_hash(operation_name, request_payload)
        for attempt in range(5):
            try:
                return self._claim_seven_day_goal_once(
                    platform, platform_user_id, day_number, operation_id,
                    operation_name, request_hash,
                )
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).lower():
                    raise
                if attempt == 4:
                    raise RepositoryBusyError("database remained locked") from exc
                time.sleep(0.01 * (2**attempt))
        raise RepositoryBusyError("database remained locked")

    def _claim_seven_day_goal_once(
        self,
        platform: str,
        platform_user_id: str,
        day_number: int,
        operation_id: str,
        operation_name: str,
        request_hash: str,
    ) -> SevenDayGoalRecord:
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
                return self._seven_day_goal_from_payload(
                    json.loads(existing["result_json"]), replay=True
                )
            try:
                definition = seven_day_goal(day_number)
            except ValueError as exc:
                raise SevenDayGoalInvalidError(str(exc)) from exc
            row = self._require_player(connection, platform, platform_user_id)
            campaign = self._ensure_seven_day_campaign(connection, row, now_text)
            start = date.fromisoformat(str(campaign["start_date"]))
            target_date = (start + timedelta(days=day_number - 1)).isoformat()
            if now.date() < start + timedelta(days=day_number - 1):
                raise SevenDayGoalNotOpenError("seven-day goal is not open")
            claimed = connection.execute(
                "SELECT 1 FROM seven_day_goal_claims WHERE player_id = ? AND day_number = ?",
                (row["id"], day_number),
            ).fetchone()
            if claimed is not None:
                raise SevenDayGoalAlreadyClaimedError("seven-day goal was already claimed")
            if definition.closed:
                raise SevenDayGoalNotCompletedError("seven-day goal depends on closed content")
            source_operation_id = self._seven_day_source_operation(
                connection, int(row["id"]), definition, target_date
            )
            if source_operation_id is None:
                raise SevenDayGoalNotCompletedError("seven-day goal is not completed")
            reward = seven_day_reward(definition)
            inventory = self._json_object(row["inventory_json"], {})
            stones = int(row["spirit_stones"])
            local_reputation = 0
            for key, quantity in reward.items():
                if key == "spirit_stones":
                    stones += int(quantity)
                elif key == "local_reputation":
                    local_reputation += int(quantity)
                else:
                    inventory[key] = int(inventory.get(key, 0)) + int(quantity)
            reputation = connection.execute(
                "SELECT local_json, service_reputation FROM player_reputations WHERE player_id = ?",
                (row["id"],),
            ).fetchone()
            local = self._json_object(reputation["local_json"], {}) if reputation is not None else {}
            local["local.xuantian.new_town"] = int(local.get("local.xuantian.new_town", 0)) + local_reputation
            service_reputation = int(reputation["service_reputation"]) if reputation is not None else 0
            if local_reputation:
                connection.execute(
                    """
                    INSERT INTO player_reputations(player_id, local_json, service_reputation, updated_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(player_id) DO UPDATE SET local_json = excluded.local_json,
                        service_reputation = excluded.service_reputation, updated_at = excluded.updated_at
                    """,
                    (row["id"], json.dumps(local, ensure_ascii=False, sort_keys=True), service_reputation, now_text),
                )
            connection.execute(
                "UPDATE players SET spirit_stones = ?, inventory_json = ?, updated_at = ? WHERE id = ?",
                (stones, json.dumps(inventory, ensure_ascii=False, sort_keys=True), now_text, row["id"]),
            )
            connection.execute(
                """
                INSERT INTO seven_day_goal_claims(
                    player_id, day_number, goal_key, target_date, source_operation_id,
                    operation_id, reward_json, content_version, rule_version, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["id"], day_number, definition.key, target_date, source_operation_id,
                    operation_id, json.dumps(reward, ensure_ascii=False, sort_keys=True),
                    SEVEN_DAY_CONTENT_VERSION, SEVEN_DAY_RULE_VERSION, now_text,
                ),
            )
            total_claimed = connection.execute(
                "SELECT COUNT(*) AS count FROM seven_day_goal_claims WHERE player_id = ?",
                (row["id"],),
            ).fetchone()
            campaign_complete = int(total_claimed["count"]) == len(SEVEN_DAY_GOALS)
            if campaign_complete:
                connection.execute(
                    "UPDATE seven_day_campaigns SET status = 'completed', updated_at = ? WHERE player_id = ?",
                    (now_text, row["id"]),
                )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (row["id"],)).fetchone()
            if updated is None:
                raise RuntimeError("seven-day goal returned no player")
            payload = {
                "player": self._player_payload(self._row_to_player(updated)),
                "day_number": day_number,
                "goal_key": definition.key,
                "target_date": target_date,
                "reward": reward,
                "source_operation_id": source_operation_id,
                "campaign_complete": campaign_complete,
                "content_version": SEVEN_DAY_CONTENT_VERSION,
                "rule_version": SEVEN_DAY_RULE_VERSION,
            }
            connection.execute(
                "INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    operation_id, operation_name, row["id"], request_hash,
                    json.dumps(payload, ensure_ascii=False, sort_keys=True), now_text,
                ),
            )
            return self._seven_day_goal_from_payload(payload)

    @staticmethod
    def _seven_day_goal_from_payload(
        payload: dict[str, Any], replay: bool = False
    ) -> SevenDayGoalRecord:
        return SevenDayGoalRecord(
            player=SQLitePlayerRepository._row_to_player(payload["player"]),
            day_number=int(payload["day_number"]),
            goal_key=str(payload["goal_key"]),
            target_date=str(payload["target_date"]),
            reward={str(key): int(value) for key, value in dict(payload.get("reward", {})).items()},
            source_operation_id=str(payload["source_operation_id"]),
            campaign_complete=bool(payload.get("campaign_complete", False)),
            already_completed=replay,
        )

    @staticmethod
    def _honor_source_operation(
        connection: sqlite3.Connection,
        player_id: int,
        source_event: str,
    ) -> str | None:
        if source_event == "player.start_seeking":
            row = connection.execute(
                """
                SELECT operation_id FROM operations
                WHERE player_id = ? AND operation_name = ?
                ORDER BY created_at ASC LIMIT 1
                """,
                (player_id, source_event),
            ).fetchone()
        elif source_event == "routine.checkin.daily":
            row = connection.execute(
                """
                SELECT operation_id FROM routine_checkins
                WHERE player_id = ? AND claim_kind = 'daily'
                ORDER BY target_date ASC, id ASC LIMIT 1
                """,
                (player_id,),
            ).fetchone()
        elif source_event == "routine.checkin.daily:3":
            row = connection.execute(
                """
                SELECT operation_id FROM routine_checkins
                WHERE player_id = ? AND claim_kind = 'daily'
                ORDER BY target_date ASC, id ASC LIMIT 1 OFFSET 2
                """,
                (player_id,),
            ).fetchone()
        elif source_event == "production.complete":
            row = connection.execute(
                """
                SELECT operation_id FROM production_orders
                WHERE player_id = ? AND status = 'completed'
                ORDER BY updated_at ASC, id ASC LIMIT 1
                """,
                (player_id,),
            ).fetchone()
        else:
            row = connection.execute(
                """
                SELECT source_operation_id FROM activity_events
                WHERE player_id = ? AND event_key = ?
                ORDER BY occurred_at ASC, id ASC LIMIT 1
                """,
                (player_id, source_event),
            ).fetchone()
        if row is None:
            return None
        key = "operation_id" if "operation_id" in row.keys() else "source_operation_id"
        return str(row[key])

    @staticmethod
    def _materialize_honor_titles(
        connection: sqlite3.Connection,
        player_id: int,
        now_text: str,
    ) -> None:
        for definition in HONOR_TITLES:
            if definition.closed:
                continue
            source_operation_id = SQLitePlayerRepository._honor_source_operation(
                connection, player_id, definition.source_event
            )
            if source_operation_id is None:
                continue
            connection.execute(
                """
                INSERT OR IGNORE INTO honor_titles(
                    player_id, title_key, source_operation_id, acquired_at,
                    content_version, rule_version
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    player_id,
                    definition.key,
                    source_operation_id,
                    now_text,
                    ROUTINE_CONTENT_VERSION,
                    HONOR_RULE_VERSION,
                ),
            )

    @staticmethod
    def _honor_status_from_connection(
        connection: sqlite3.Connection,
        player: sqlite3.Row,
        now_text: str,
    ) -> HonorStatusRecord:
        SQLitePlayerRepository._materialize_honor_titles(connection, int(player["id"]), now_text)
        state = connection.execute(
            "SELECT equipped_title_key FROM honor_states WHERE player_id = ?",
            (player["id"],),
        ).fetchone()
        equipped = str(state["equipped_title_key"]) if state and state["equipped_title_key"] else None
        title_rows = {
            str(item["title_key"]): item
            for item in connection.execute(
                "SELECT title_key, source_operation_id FROM honor_titles WHERE player_id = ?",
                (player["id"],),
            ).fetchall()
        }
        titles = tuple(
            HonorTitleView(
                title_key=definition.key,
                label=definition.label,
                acquired=definition.key in title_rows,
                equipped=definition.key == equipped,
                source_operation_id=(
                    str(title_rows[definition.key]["source_operation_id"])
                    if definition.key in title_rows
                    else None
                ),
            )
            for definition in HONOR_TITLES
        )
        claim_rows = {
            str(item["achievement_key"]): item
            for item in connection.execute(
                "SELECT achievement_key, source_operation_id, reward_json FROM achievement_claims WHERE player_id = ?",
                (player["id"],),
            ).fetchall()
        }
        achievements: list[AchievementView] = []
        for definition in ACHIEVEMENTS:
            claim = claim_rows.get(definition.key)
            source = SQLitePlayerRepository._honor_source_operation(
                connection, int(player["id"]), definition.source_event
            )
            if claim is not None:
                state_name = "claimed"
                source = str(claim["source_operation_id"])
                reward = SQLitePlayerRepository._json_object(claim["reward_json"], {})
            elif definition.closed:
                state_name = "content_closed"
                reward = achievement_reward(definition)
                source = None
            elif source is not None:
                state_name = "claimable"
                reward = achievement_reward(definition)
            else:
                state_name = "pending"
                reward = achievement_reward(definition)
            achievements.append(
                AchievementView(
                    achievement_key=definition.key,
                    label=definition.label,
                    state=state_name,
                    reward=reward,
                    source_operation_id=source,
                )
            )
        return HonorStatusRecord(
            player=SQLitePlayerRepository._row_to_player(player),
            equipped_title_key=equipped,
            titles=titles,
            achievements=tuple(achievements),
        )

    async def get_honor_status(
        self,
        *,
        platform: str,
        platform_user_id: str,
    ) -> HonorStatusRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._get_honor_status_sync, platform, platform_user_id
            )

    def _get_honor_status_sync(
        self, platform: str, platform_user_id: str
    ) -> HonorStatusRecord:
        with self._connect() as connection:
            row = self._require_player(connection, platform, platform_user_id)
            return self._honor_status_from_connection(
                connection, row, serialize_datetime(self._now())
            )

    async def claim_achievement(
        self,
        *,
        platform: str,
        platform_user_id: str,
        achievement_key: str,
        operation_id: str,
    ) -> AchievementClaimRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._claim_achievement_sync,
                platform,
                platform_user_id,
                achievement_key,
                operation_id,
            )

    def _claim_achievement_sync(
        self,
        platform: str,
        platform_user_id: str,
        achievement_key: str,
        operation_id: str,
    ) -> AchievementClaimRecord:
        operation_name = "routine.claim_achievement"
        request_hash = self._request_hash(
            operation_name,
            {
                "platform": platform,
                "platform_user_id": platform_user_id,
                "achievement_key": achievement_key,
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
                return self._achievement_claim_from_payload(
                    json.loads(existing["result_json"]), replay=True
                )
            try:
                definition = achievement(achievement_key)
            except ValueError as exc:
                raise AchievementInvalidError(str(exc)) from exc
            row = self._require_player(connection, platform, platform_user_id)
            claimed = connection.execute(
                "SELECT 1 FROM achievement_claims WHERE player_id = ? AND achievement_key = ?",
                (row["id"], definition.key),
            ).fetchone()
            if claimed is not None:
                raise AchievementAlreadyClaimedError("achievement was already claimed")
            if definition.closed:
                raise HonorTitleClosedError("achievement content is closed")
            source_operation_id = self._honor_source_operation(
                connection, int(row["id"]), definition.source_event
            )
            if source_operation_id is None:
                raise AchievementNotCompletedError("achievement is not completed")
            reward = achievement_reward(definition)
            local_reputation = int(reward.get("local_reputation", 0))
            service_reputation_delta = int(reward.get("service_reputation", 0))
            reputation = connection.execute(
                "SELECT local_json, service_reputation FROM player_reputations WHERE player_id = ?",
                (row["id"],),
            ).fetchone()
            local = self._json_object(reputation["local_json"], {}) if reputation is not None else {}
            local["local.xuantian.new_town"] = int(local.get("local.xuantian.new_town", 0)) + local_reputation
            service_reputation = int(reputation["service_reputation"]) if reputation is not None else 0
            service_reputation = min(100, service_reputation + service_reputation_delta)
            if local_reputation or service_reputation_delta:
                connection.execute(
                    """
                    INSERT INTO player_reputations(player_id, local_json, service_reputation, updated_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(player_id) DO UPDATE SET local_json = excluded.local_json,
                        service_reputation = excluded.service_reputation, updated_at = excluded.updated_at
                    """,
                    (
                        row["id"],
                        json.dumps(local, ensure_ascii=False, sort_keys=True),
                        service_reputation,
                        now_text,
                    ),
                )
            title_key = reward.get("title_key")
            if title_key:
                title_definition = honor_title(str(title_key))
                connection.execute(
                    """
                    INSERT OR IGNORE INTO honor_titles(
                        player_id, title_key, source_operation_id, acquired_at,
                        content_version, rule_version
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row["id"], str(title_key), source_operation_id, now_text,
                        ROUTINE_CONTENT_VERSION, HONOR_RULE_VERSION,
                    ),
                )
                del title_definition
            connection.execute(
                """
                INSERT INTO achievement_claims(
                    player_id, achievement_key, source_operation_id, operation_id,
                    reward_json, content_version, rule_version, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["id"], definition.key, source_operation_id, operation_id,
                    json.dumps(reward, ensure_ascii=False, sort_keys=True),
                    ROUTINE_CONTENT_VERSION, HONOR_RULE_VERSION, now_text,
                ),
            )
            updated = connection.execute(
                "SELECT * FROM players WHERE id = ?", (row["id"],)
            ).fetchone()
            if updated is None:
                raise RuntimeError("achievement claim returned no player")
            payload = {
                "player": self._player_payload(self._row_to_player(updated)),
                "achievement_key": definition.key,
                "label": definition.label,
                "reward": reward,
                "source_operation_id": source_operation_id,
                "content_version": ROUTINE_CONTENT_VERSION,
                "rule_version": HONOR_RULE_VERSION,
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
            return self._achievement_claim_from_payload(payload)

    @staticmethod
    def _achievement_claim_from_payload(
        payload: dict[str, Any], replay: bool = False
    ) -> AchievementClaimRecord:
        return AchievementClaimRecord(
            player=SQLitePlayerRepository._row_to_player(payload["player"]),
            achievement_key=str(payload["achievement_key"]),
            label=str(payload["label"]),
            reward=dict(payload.get("reward", {})),
            source_operation_id=str(payload["source_operation_id"]),
            already_completed=replay,
        )

    async def equip_title(
        self,
        *,
        platform: str,
        platform_user_id: str,
        title_key: str,
        operation_id: str,
    ) -> HonorTitleEquipRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._equip_title_sync,
                platform,
                platform_user_id,
                title_key,
                operation_id,
            )

    def _equip_title_sync(
        self,
        platform: str,
        platform_user_id: str,
        title_key: str,
        operation_id: str,
    ) -> HonorTitleEquipRecord:
        operation_name = "routine.equip_title"
        request_hash = self._request_hash(
            operation_name,
            {"platform": platform, "platform_user_id": platform_user_id, "title_key": title_key},
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
                return self._title_equip_from_payload(json.loads(existing["result_json"]), replay=True)
            try:
                definition = honor_title(title_key)
            except ValueError as exc:
                raise HonorTitleNotFoundError(str(exc)) from exc
            row = self._require_player(connection, platform, platform_user_id)
            self._materialize_honor_titles(connection, int(row["id"]), now_text)
            owned = connection.execute(
                "SELECT 1 FROM honor_titles WHERE player_id = ? AND title_key = ?",
                (row["id"], definition.key),
            ).fetchone()
            if owned is None:
                raise HonorTitleNotFoundError("title is not owned")
            connection.execute(
                """
                INSERT INTO honor_states(player_id, equipped_title_key, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(player_id) DO UPDATE SET equipped_title_key = excluded.equipped_title_key,
                    updated_at = excluded.updated_at
                """,
                (row["id"], definition.key, now_text),
            )
            updated = connection.execute(
                "SELECT * FROM players WHERE id = ?", (row["id"],)
            ).fetchone()
            if updated is None:
                raise RuntimeError("title equip returned no player")
            payload = {
                "player": self._player_payload(self._row_to_player(updated)),
                "title_key": definition.key,
                "label": definition.label,
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
            return self._title_equip_from_payload(payload)

    @staticmethod
    def _title_equip_from_payload(
        payload: dict[str, Any], replay: bool = False
    ) -> HonorTitleEquipRecord:
        return HonorTitleEquipRecord(
            player=SQLitePlayerRepository._row_to_player(payload["player"]),
            title_key=str(payload["title_key"]),
            label=str(payload["label"]),
            already_completed=replay,
        )

    async def redeem_code(
        self,
        *,
        platform: str,
        platform_user_id: str,
        code: str,
        operation_id: str,
    ) -> RedemptionCodeRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._redeem_code_sync,
                platform,
                platform_user_id,
                code,
                operation_id,
            )

    def _redeem_code_sync(
        self,
        platform: str,
        platform_user_id: str,
        code: str,
        operation_id: str,
    ) -> RedemptionCodeRecord:
        operation_name = "routine.redeem_code"
        try:
            code_hash = redemption_code_hash(code)
        except ValueError as exc:
            raise RedemptionCodeInvalidError(str(exc)) from exc
        request_hash = self._request_hash(
            operation_name,
            {
                "platform": platform,
                "platform_user_id": platform_user_id,
                "code_hash": code_hash,
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
                return self._redemption_from_payload(json.loads(existing["result_json"]), replay=True)
            code_row = connection.execute(
                "SELECT * FROM redemption_codes WHERE code_hash = ?",
                (code_hash,),
            ).fetchone()
            if code_row is None:
                raise RedemptionCodeInvalidError("redemption code is not configured")
            if code_row["status"] == "revoked":
                raise RedemptionCodeRevokedError("redemption code was revoked")
            business_date = now.date()
            starts_on = code_row["starts_on"]
            ends_on = code_row["ends_on"]
            if (starts_on and business_date < date.fromisoformat(str(starts_on))) or (
                ends_on and business_date > date.fromisoformat(str(ends_on))
            ):
                raise RedemptionCodeExpiredError("redemption code is outside its validity window")
            row = self._require_player(connection, platform, platform_user_id)
            claimed = connection.execute(
                "SELECT 1 FROM redemption_claims WHERE player_id = ? AND code_id = ?",
                (row["id"], code_row["id"]),
            ).fetchone()
            if claimed is not None:
                raise RedemptionCodeAlreadyClaimedError("redemption code was already claimed")
            if int(code_row["claimed_count"]) >= int(code_row["max_claims"]):
                raise RedemptionCodeExhaustedError("redemption code has no remaining claims")

            reward = self._json_object(code_row["reward_json"], {})
            inventory = self._json_object(row["inventory_json"], {})
            stones = int(row["spirit_stones"])
            energy = int(row["energy"])
            actual_reward: dict[str, int] = {}
            local_reputation = 0
            service_reputation = 0
            for key, raw_quantity in reward.items():
                quantity = int(raw_quantity)
                if key == "spirit_stones":
                    stones += quantity
                    actual_reward[key] = quantity
                elif key == "energy":
                    gained = min(quantity, max(0, int(row["energy_max"]) - energy))
                    energy += gained
                    actual_reward[key] = gained
                elif key == "local_reputation":
                    local_reputation += quantity
                    actual_reward[key] = quantity
                elif key == "service_reputation":
                    service_reputation += quantity
                    actual_reward[key] = quantity
                else:
                    inventory[key] = int(inventory.get(key, 0)) + quantity
                    actual_reward[key] = quantity

            if local_reputation or service_reputation:
                reputation = connection.execute(
                    "SELECT local_json, service_reputation FROM player_reputations WHERE player_id = ?",
                    (row["id"],),
                ).fetchone()
                local = self._json_object(reputation["local_json"], {}) if reputation is not None else {}
                local["local.xuantian.new_town"] = int(local.get("local.xuantian.new_town", 0)) + local_reputation
                current_service = int(reputation["service_reputation"]) if reputation is not None else 0
                current_service = min(100, current_service + service_reputation)
                connection.execute(
                    """
                    INSERT INTO player_reputations(player_id, local_json, service_reputation, updated_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(player_id) DO UPDATE SET local_json = excluded.local_json,
                        service_reputation = excluded.service_reputation, updated_at = excluded.updated_at
                    """,
                    (row["id"], json.dumps(local, ensure_ascii=False, sort_keys=True), current_service, now_text),
                )
            connection.execute(
                """
                UPDATE players
                SET spirit_stones = ?, energy = ?, inventory_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (stones, energy, json.dumps(inventory, ensure_ascii=False, sort_keys=True), now_text, row["id"]),
            )
            connection.execute(
                """
                INSERT INTO redemption_claims(
                    player_id, code_id, code_key, operation_id, reward_json,
                    content_version, rule_version, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["id"], code_row["id"], code_row["code_key"], operation_id,
                    json.dumps(actual_reward, ensure_ascii=False, sort_keys=True),
                    code_row["content_version"], code_row["rule_version"], now_text,
                ),
            )
            connection.execute(
                "UPDATE redemption_codes SET claimed_count = claimed_count + 1, updated_at = ? WHERE id = ?",
                (now_text, code_row["id"]),
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (row["id"],)).fetchone()
            if updated is None:
                raise RuntimeError("redemption returned no player")
            payload = {
                "player": self._player_payload(self._row_to_player(updated)),
                "code_key": str(code_row["code_key"]),
                "reward": actual_reward,
                "content_version": str(code_row["content_version"]),
                "rule_version": str(code_row["rule_version"]),
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
            return self._redemption_from_payload(payload)

    @staticmethod
    def _redemption_from_payload(
        payload: dict[str, Any], replay: bool = False
    ) -> RedemptionCodeRecord:
        return RedemptionCodeRecord(
            player=SQLitePlayerRepository._row_to_player(payload["player"]),
            code_key=str(payload["code_key"]),
            reward={str(key): int(value) for key, value in dict(payload.get("reward", {})).items()},
            already_completed=replay,
        )

    async def roll_fate_pool(
        self,
        *,
        platform: str,
        platform_user_id: str,
        draw_count: int,
        operation_id: str,
    ) -> FateRollRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._roll_fate_pool_sync,
                platform,
                platform_user_id,
                draw_count,
                operation_id,
            )

    def _roll_fate_pool_sync(
        self,
        platform: str,
        platform_user_id: str,
        draw_count: int,
        operation_id: str,
    ) -> FateRollRecord:
        operation_name = "routine.roll_fate_pool"
        if draw_count not in {1, 10}:
            raise FatePoolInvalidError("unsupported fate draw count")
        request_hash = self._request_hash(
            operation_name,
            {
                "platform": platform,
                "platform_user_id": platform_user_id,
                "pool_key": FATE_POOL_KEY,
                "draw_count": draw_count,
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
                return self._fate_roll_from_payload(json.loads(existing["result_json"]), replay=True)
            row = self._require_player(connection, platform, platform_user_id)
            pool = connection.execute(
                "SELECT * FROM fate_pools WHERE player_id = ? AND pool_key = ?",
                (row["id"], FATE_POOL_KEY),
            ).fetchone()
            pity_before = int(pool["pity_count"]) if pool is not None else 0
            if pity_before < 0 or pity_before >= FATE_PITY_LIMIT:
                raise FatePoolNotOpenError("fate pity state is invalid")

            inventory = self._json_object(row["inventory_json"], {})
            stones = int(row["spirit_stones"])
            if draw_count == 1 and int(inventory.get(FATE_TICKET, 0)) > 0:
                cost_kind = "ticket"
                cost_quantity = 1
                remaining_ticket = int(inventory[FATE_TICKET]) - 1
                if remaining_ticket:
                    inventory[FATE_TICKET] = remaining_ticket
                else:
                    inventory.pop(FATE_TICKET, None)
            else:
                cost_kind = "spirit_stones"
                cost_quantity = FATE_SINGLE_COST if draw_count == 1 else FATE_TEN_COST
                if stones < cost_quantity:
                    raise FateDrawInsufficientError("fate draw cost is insufficient")
                stones -= cost_quantity

            draws, pity_after, seed_hash = roll_fate_pool(
                operation_id,
                draw_count=draw_count,
                pity_before=pity_before,
            )
            reward = reward_totals(draws)
            for key, quantity in reward.items():
                if key == "spirit_stones":
                    stones += quantity
                else:
                    inventory[key] = int(inventory.get(key, 0)) + quantity
            connection.execute(
                """
                UPDATE players
                SET spirit_stones = ?, inventory_json = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    stones,
                    json.dumps(inventory, ensure_ascii=False, sort_keys=True),
                    now_text,
                    row["id"],
                ),
            )
            total_draws = (int(pool["total_draws"]) if pool is not None else 0) + draw_count
            connection.execute(
                """
                INSERT INTO fate_pools(
                    player_id, pool_key, pity_count, total_draws,
                    content_version, rule_version, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(player_id, pool_key) DO UPDATE SET
                    pity_count = excluded.pity_count,
                    total_draws = excluded.total_draws,
                    content_version = excluded.content_version,
                    rule_version = excluded.rule_version,
                    updated_at = excluded.updated_at
                """,
                (
                    row["id"],
                    FATE_POOL_KEY,
                    pity_after,
                    total_draws,
                    FATE_CONTENT_VERSION,
                    FATE_RULE_VERSION,
                    now_text,
                ),
            )
            draws_payload = [
                {
                    "key": draw.key,
                    "label": draw.label,
                    "rarity": draw.rarity,
                    "quantity": draw.quantity,
                    "guaranteed": draw.guaranteed,
                }
                for draw in draws
            ]
            connection.execute(
                """
                INSERT INTO fate_rolls(
                    player_id, pool_key, operation_id, draw_count, cost_kind,
                    cost_quantity, pity_before, pity_after, seed_hash, reward_json,
                    draws_json, content_version, rule_version, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["id"],
                    FATE_POOL_KEY,
                    operation_id,
                    draw_count,
                    cost_kind,
                    cost_quantity,
                    pity_before,
                    pity_after,
                    seed_hash,
                    json.dumps(reward, ensure_ascii=False, sort_keys=True),
                    json.dumps(draws_payload, ensure_ascii=False, sort_keys=True),
                    FATE_CONTENT_VERSION,
                    FATE_RULE_VERSION,
                    now_text,
                ),
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (row["id"],)).fetchone()
            if updated is None:
                raise RuntimeError("fate roll returned no player")
            payload = {
                "player": self._player_payload(self._row_to_player(updated)),
                "pool_key": FATE_POOL_KEY,
                "draw_count": draw_count,
                "cost_kind": cost_kind,
                "cost_quantity": cost_quantity,
                "pity_before": pity_before,
                "pity_after": pity_after,
                "seed_hash": seed_hash,
                "draws": draws_payload,
                "reward": reward,
                "content_version": FATE_CONTENT_VERSION,
                "rule_version": FATE_RULE_VERSION,
            }
            connection.execute(
                """
                INSERT INTO operations(
                    operation_id, operation_name, player_id, request_hash,
                    result_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    operation_id,
                    operation_name,
                    row["id"],
                    request_hash,
                    json.dumps(payload, ensure_ascii=False, sort_keys=True),
                    now_text,
                ),
            )
            return self._fate_roll_from_payload(payload)

    @staticmethod
    def _fate_roll_from_payload(
        payload: dict[str, Any], replay: bool = False
    ) -> FateRollRecord:
        draws = tuple(
            FateDrawView(
                key=str(item["key"]),
                label=str(item["label"]),
                rarity=str(item["rarity"]),
                quantity=int(item["quantity"]),
                guaranteed=bool(item.get("guaranteed", False)),
            )
            for item in payload.get("draws", [])
        )
        return FateRollRecord(
            player=SQLitePlayerRepository._row_to_player(payload["player"]),
            pool_key=str(payload["pool_key"]),
            draw_count=int(payload["draw_count"]),
            cost_kind=str(payload["cost_kind"]),
            cost_quantity=int(payload["cost_quantity"]),
            pity_before=int(payload["pity_before"]),
            pity_after=int(payload["pity_after"]),
            seed_hash=str(payload["seed_hash"]),
            draws=draws,
            reward={str(key): int(value) for key, value in dict(payload.get("reward", {})).items()},
            already_completed=replay,
        )

    async def start_wayfaring(
        self,
        *,
        platform: str,
        platform_user_id: str,
        operation_id: str,
    ) -> WayfaringStatusRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._start_wayfaring_sync, platform, platform_user_id, operation_id
            )

    def _start_wayfaring_sync(
        self, platform: str, platform_user_id: str, operation_id: str
    ) -> WayfaringStatusRecord:
        operation_name = "pass.wayfaring.start"
        request_hash = self._request_hash(
            operation_name,
            {
                "platform": platform,
                "platform_user_id": platform_user_id,
                "pass_key": WAYFARING_PASS_KEY,
                "content_version": WAYFARING_CONTENT_VERSION,
                "rule_version": WAYFARING_RULE_VERSION,
            },
        )
        now = self._now()
        now_text = serialize_datetime(now)
        cycle_start, cycle_end = now.date(), now.date() + timedelta(days=27)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            if existing is not None:
                if existing["operation_name"] != operation_name or existing["request_hash"] != request_hash:
                    raise OperationConflictError("operation input differs from its original request")
                return self._wayfaring_status_from_payload(
                    json.loads(existing["result_json"]), replay=True
                )
            player = self._require_player(connection, platform, platform_user_id)
            current = connection.execute(
                "SELECT * FROM wayfaring_passes WHERE player_id = ? AND pass_key = ? ORDER BY cycle_start DESC LIMIT 1",
                (player["id"], WAYFARING_PASS_KEY),
            ).fetchone()
            if current is not None and str(current["status"]) in {"active", "completed"}:
                if date.fromisoformat(str(current["cycle_end"])) >= now.date():
                    raise WayfaringAlreadyStartedError("wayfaring pass is already active")
                connection.execute(
                    "UPDATE wayfaring_passes SET status = 'closed', updated_at = ? WHERE id = ?",
                    (now_text, current["id"]),
                )
            connection.execute(
                """
                INSERT INTO wayfaring_passes(
                    player_id, pass_key, cycle_start, cycle_end, status,
                    total_points, daily_date, daily_points, week_start, weekly_points,
                    claimed_free_json, claimed_paid_json, content_version, rule_version,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'active', 0, ?, 0, ?, 0, '[]', '[]', ?, ?, ?, ?)
                """,
                (
                    player["id"], WAYFARING_PASS_KEY, cycle_start.isoformat(), cycle_end.isoformat(),
                    cycle_start.isoformat(), wayfaring_week_start(cycle_start).isoformat(),
                    WAYFARING_CONTENT_VERSION, WAYFARING_RULE_VERSION, now_text, now_text,
                ),
            )
            pass_row = connection.execute(
                "SELECT * FROM wayfaring_passes WHERE player_id = ? AND pass_key = ? AND cycle_start = ?",
                (player["id"], WAYFARING_PASS_KEY, cycle_start.isoformat()),
            ).fetchone()
            if pass_row is None:
                raise RuntimeError("wayfaring pass initialization failed")
            payload = self._wayfaring_status_payload(connection, player, pass_row, now)
            connection.execute(
                "INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    operation_id, operation_name, player["id"], request_hash,
                    json.dumps(payload, ensure_ascii=False, sort_keys=True), now_text,
                ),
            )
            return self._wayfaring_status_from_payload(payload)

    async def get_wayfaring_status(
        self, *, platform: str, platform_user_id: str
    ) -> WayfaringStatusRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._get_wayfaring_status_sync, platform, platform_user_id
            )

    def _get_wayfaring_status_sync(
        self, platform: str, platform_user_id: str
    ) -> WayfaringStatusRecord:
        now = self._now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            player = self._require_player(connection, platform, platform_user_id)
            pass_row = connection.execute(
                "SELECT * FROM wayfaring_passes WHERE player_id = ? AND pass_key = ? ORDER BY cycle_start DESC LIMIT 1",
                (player["id"], WAYFARING_PASS_KEY),
            ).fetchone()
            if pass_row is None:
                raise WayfaringNotStartedError("wayfaring pass has not started")
            if str(pass_row["status"]) == "active" and now.date() > date.fromisoformat(str(pass_row["cycle_end"])):
                connection.execute(
                    "UPDATE wayfaring_passes SET status = 'closed', updated_at = ? WHERE id = ?",
                    (serialize_datetime(now), pass_row["id"]),
                )
                pass_row = connection.execute(
                    "SELECT * FROM wayfaring_passes WHERE id = ?", (pass_row["id"],)
                ).fetchone()
            if pass_row is None:
                raise RuntimeError("wayfaring pass disappeared")
            self._sync_wayfaring_points(connection, player, pass_row, now)
            pass_row = connection.execute(
                "SELECT * FROM wayfaring_passes WHERE id = ?", (pass_row["id"],)
            ).fetchone()
            if pass_row is None:
                raise RuntimeError("wayfaring pass disappeared")
            return self._wayfaring_status_from_payload(
                self._wayfaring_status_payload(connection, player, pass_row, now)
            )

    async def claim_wayfaring_level(
        self,
        *,
        platform: str,
        platform_user_id: str,
        level: int,
        track: str,
        operation_id: str,
    ) -> WayfaringClaimRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._claim_wayfaring_level_sync,
                platform,
                platform_user_id,
                level,
                track,
                operation_id,
            )

    def _claim_wayfaring_level_sync(
        self,
        platform: str,
        platform_user_id: str,
        level: int,
        track: str,
        operation_id: str,
    ) -> WayfaringClaimRecord:
        if isinstance(level, bool):
            raise WayfaringLevelInvalidError("invalid wayfaring level")
        try:
            level = int(level)
        except (TypeError, ValueError) as exc:
            raise WayfaringLevelInvalidError("invalid wayfaring level") from exc
        if level not in WAYFARING_LEVELS or track not in {"free", "paid"}:
            raise WayfaringLevelInvalidError("invalid wayfaring level or track")
        operation_name = "pass.wayfaring.claim"
        request_hash = self._request_hash(
            operation_name,
            {
                "platform": platform,
                "platform_user_id": platform_user_id,
                "pass_key": WAYFARING_PASS_KEY,
                "level": level,
                "track": track,
                "content_version": WAYFARING_CONTENT_VERSION,
                "rule_version": WAYFARING_RULE_VERSION,
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
                return self._wayfaring_claim_from_payload(
                    json.loads(existing["result_json"]), replay=True
                )
            player = self._require_player(connection, platform, platform_user_id)
            pass_row = connection.execute(
                "SELECT * FROM wayfaring_passes WHERE player_id = ? AND pass_key = ? ORDER BY cycle_start DESC LIMIT 1",
                (player["id"], WAYFARING_PASS_KEY),
            ).fetchone()
            if pass_row is None:
                raise WayfaringNotStartedError("wayfaring pass has not started")
            if str(pass_row["status"]) == "active" and now.date() > date.fromisoformat(str(pass_row["cycle_end"])):
                connection.execute(
                    "UPDATE wayfaring_passes SET status = 'closed', updated_at = ? WHERE id = ?",
                    (now_text, pass_row["id"]),
                )
                pass_row = connection.execute("SELECT * FROM wayfaring_passes WHERE id = ?", (pass_row["id"],)).fetchone()
            if pass_row is None:
                raise WayfaringNotStartedError("wayfaring pass has not started")
            self._sync_wayfaring_points(connection, player, pass_row, now)
            pass_row = connection.execute("SELECT * FROM wayfaring_passes WHERE id = ?", (pass_row["id"],)).fetchone()
            if pass_row is None or str(pass_row["status"]) == "closed":
                raise WayfaringLevelLockedError("wayfaring cycle is closed")
            current_level = min(WAYFARING_LEVELS[-1], int(pass_row["total_points"]) // WAYFARING_POINTS_PER_LEVEL)
            if level > current_level:
                raise WayfaringLevelLockedError("wayfaring level is not unlocked")
            claimed_key = "claimed_free_json" if track == "free" else "claimed_paid_json"
            claimed = {int(item) for item in self._json_array(pass_row[claimed_key])}
            if level in claimed:
                raise WayfaringClaimAlreadyExistsError("wayfaring reward already claimed")
            if track == "paid":
                active_contract = connection.execute(
                    """
                    SELECT id, starts_on, ends_on, content_version, rule_version
                    FROM dao_contracts
                    WHERE player_id = ? AND contract_key = 'dao_contract.monthly'
                      AND status = 'active' AND starts_on <= ? AND ends_on >= ?
                    LIMIT 1
                    """,
                    (player["id"], now.date().isoformat(), now.date().isoformat()),
                ).fetchone()
                if active_contract is None:
                    raise WayfaringPaidTrackInactiveError("monthly dao contract is required")
                reward = wayfaring_paid_reward(level)
            else:
                reward = wayfaring_free_reward(level)
            entitlement_snapshot = None
            if track == "paid" and active_contract is not None:
                entitlement_snapshot = {
                    "contract_id": int(active_contract["id"]),
                    "contract_key": "dao_contract.monthly",
                    "starts_on": str(active_contract["starts_on"]),
                    "ends_on": str(active_contract["ends_on"]),
                    "content_version": str(active_contract["content_version"]),
                    "rule_version": str(active_contract["rule_version"]),
                }
            actual_reward = self._apply_dao_reward(connection, player, reward, now_text)
            claimed.add(level)
            connection.execute(
                f"UPDATE wayfaring_passes SET {claimed_key} = ?, updated_at = ? WHERE id = ?",
                (json.dumps(sorted(claimed), ensure_ascii=False), now_text, pass_row["id"]),
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (player["id"],)).fetchone()
            if updated is None:
                raise RuntimeError("wayfaring claim returned no player")
            connection.execute(
                """
                INSERT INTO wayfaring_claims(
                    player_id, pass_id, level, track, operation_id, reward_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (player["id"], pass_row["id"], level, track, operation_id,
                 json.dumps(actual_reward, ensure_ascii=False, sort_keys=True), now_text),
            )
            payload = {
                "player": self._player_payload(self._row_to_player(updated)),
                "pass_key": WAYFARING_PASS_KEY,
                "level": level,
                "track": track,
                "reward": actual_reward,
                "total_points": int(pass_row["total_points"]),
                "entitlement_snapshot": entitlement_snapshot,
                "content_version": WAYFARING_CONTENT_VERSION,
                "rule_version": WAYFARING_RULE_VERSION,
            }
            connection.execute(
                "INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (operation_id, operation_name, player["id"], request_hash,
                 json.dumps(payload, ensure_ascii=False, sort_keys=True), now_text),
            )
            return self._wayfaring_claim_from_payload(payload)

    @staticmethod
    def _json_array(value: Any) -> list[Any]:
        if isinstance(value, list):
            return value
        try:
            parsed = json.loads(value or "[]")
        except (TypeError, json.JSONDecodeError):
            return []
        return parsed if isinstance(parsed, list) else []

    @staticmethod
    def _wayfaring_status_payload(
        connection: sqlite3.Connection,
        player: sqlite3.Row,
        pass_row: sqlite3.Row,
        now: datetime,
    ) -> dict[str, Any]:
        total = min(
            WAYFARING_LEVELS[-1] * WAYFARING_POINTS_PER_LEVEL,
            int(pass_row["total_points"]),
        )
        return {
            "player": SQLitePlayerRepository._player_payload(SQLitePlayerRepository._row_to_player(player)),
            "pass_key": str(pass_row["pass_key"]),
            "status": str(pass_row["status"]),
            "cycle_start": str(pass_row["cycle_start"]),
            "cycle_end": str(pass_row["cycle_end"]),
            "total_points": total,
            "current_level": min(WAYFARING_LEVELS[-1], total // WAYFARING_POINTS_PER_LEVEL),
            "daily_points": int(pass_row["daily_points"]),
            "weekly_points": int(pass_row["weekly_points"]),
            "claimed_free": [int(item) for item in SQLitePlayerRepository._json_array(pass_row["claimed_free_json"])],
            "claimed_paid": [int(item) for item in SQLitePlayerRepository._json_array(pass_row["claimed_paid_json"])],
            "content_version": WAYFARING_CONTENT_VERSION,
            "rule_version": WAYFARING_RULE_VERSION,
        }

    @staticmethod
    def _wayfaring_status_from_payload(
        payload: dict[str, Any], replay: bool = False
    ) -> WayfaringStatusRecord:
        return WayfaringStatusRecord(
            player=SQLitePlayerRepository._row_to_player(payload["player"]),
            pass_key=str(payload["pass_key"]),
            status=str(payload["status"]),
            cycle_start=str(payload["cycle_start"]),
            cycle_end=str(payload["cycle_end"]),
            total_points=int(payload.get("total_points", 0)),
            current_level=int(payload.get("current_level", 0)),
            daily_points=int(payload.get("daily_points", 0)),
            weekly_points=int(payload.get("weekly_points", 0)),
            claimed_free=tuple(int(item) for item in payload.get("claimed_free", [])),
            claimed_paid=tuple(int(item) for item in payload.get("claimed_paid", [])),
            already_completed=replay,
        )

    @staticmethod
    def _wayfaring_claim_from_payload(
        payload: dict[str, Any], replay: bool = False
    ) -> WayfaringClaimRecord:
        return WayfaringClaimRecord(
            player=SQLitePlayerRepository._row_to_player(payload["player"]),
            pass_key=str(payload["pass_key"]),
            level=int(payload["level"]),
            track=str(payload["track"]),
            reward={str(key): int(value) for key, value in dict(payload.get("reward", {})).items()},
            total_points=int(payload.get("total_points", 0)),
            already_completed=replay,
        )

    @staticmethod
    def _sync_wayfaring_points(
        connection: sqlite3.Connection,
        player: sqlite3.Row,
        pass_row: sqlite3.Row,
        now: datetime,
    ) -> None:
        if str(pass_row["status"]) != "active":
            return
        start = str(pass_row["cycle_start"])
        end = str(pass_row["cycle_end"])
        sources = {
            "player.start_seeking": "player.start_seeking",
            "routine.checkin.daily": "routine.checkin.daily",
            "routine.spirit_tree.water": "routine.spirit_tree.water",
            "routine.spirit_tree.harvest": "routine.spirit_tree.harvest",
            "production.complete": "production.complete",
            "bounty.claim": "bounty.claim",
            "exploration.settle": "exploration.settle",
            "routine.claim_dao_contract": "dao_contract.daily",
        }
        placeholders = ",".join("?" for _ in sources)
        candidates = connection.execute(
            f"""
            SELECT operation_id, operation_name, created_at FROM operations
            WHERE player_id = ? AND operation_name IN ({placeholders})
              AND substr(created_at, 1, 10) >= ? AND substr(created_at, 1, 10) <= ?
            ORDER BY created_at ASC, operation_id ASC
            """,
            (player["id"], *sources.keys(), start, end),
        ).fetchall()
        existing = {
            str(item["source_operation_id"])
            for item in connection.execute(
                "SELECT source_operation_id FROM wayfaring_point_events WHERE pass_id = ?",
                (pass_row["id"],),
            ).fetchall()
        }
        day_totals: dict[str, int] = {}
        week_totals: dict[str, int] = {}
        for item in connection.execute(
            "SELECT business_date, week_start, points FROM wayfaring_point_events WHERE pass_id = ?",
            (pass_row["id"],),
        ).fetchall():
            day_totals[str(item["business_date"])] = day_totals.get(str(item["business_date"]), 0) + int(item["points"])
            week_totals[str(item["week_start"])] = week_totals.get(str(item["week_start"]), 0) + int(item["points"])
        total = int(pass_row["total_points"])
        for item in candidates:
            source_operation_id = str(item["operation_id"])
            if source_operation_id in existing:
                continue
            source_key = sources[str(item["operation_name"])]
            try:
                raw_points = wayfaring_source_points(source_key)
            except ValueError:
                continue
            try:
                business_date = datetime.fromisoformat(str(item["created_at"])).date()
            except ValueError:
                business_date = now.date()
            business_date_text = business_date.isoformat()
            week_text = wayfaring_week_start(business_date).isoformat()
            remaining = min(
                WAYFARING_DAILY_POINT_CAP - day_totals.get(business_date_text, 0),
                WAYFARING_WEEKLY_POINT_CAP - week_totals.get(week_text, 0),
            )
            points = max(0, min(raw_points, remaining))
            connection.execute(
                """
                INSERT INTO wayfaring_point_events(
                    player_id, pass_id, source_key, source_operation_id,
                    business_date, week_start, points, created_at, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    player["id"], pass_row["id"], source_key, source_operation_id,
                    business_date_text, week_text, points, serialize_datetime(now),
                    json.dumps({"raw_points": raw_points, "capped": points != raw_points}, ensure_ascii=False, sort_keys=True),
                ),
            )
            existing.add(source_operation_id)
            day_totals[business_date_text] = day_totals.get(business_date_text, 0) + points
            week_totals[week_text] = week_totals.get(week_text, 0) + points
            total = min(
                WAYFARING_LEVELS[-1] * WAYFARING_POINTS_PER_LEVEL,
                total + points,
            )
        today_text = now.date().isoformat()
        week_text = wayfaring_week_start(now.date()).isoformat()
        status = str(pass_row["status"])
        if total >= WAYFARING_LEVELS[-1] * WAYFARING_POINTS_PER_LEVEL:
            status = "completed"
        connection.execute(
            """
            UPDATE wayfaring_passes
            SET total_points = ?, daily_date = ?, daily_points = ?,
                week_start = ?, weekly_points = ?, status = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                total, today_text, day_totals.get(today_text, 0), week_text,
                week_totals.get(week_text, 0), status, serialize_datetime(now), pass_row["id"],
            ),
        )

    @staticmethod
    def _apply_dao_reward(
        connection: sqlite3.Connection,
        player: sqlite3.Row,
        reward: dict[str, int],
        now_text: str,
    ) -> dict[str, int]:
        inventory = SQLitePlayerRepository._json_object(player["inventory_json"], {})
        stones = int(player["spirit_stones"])
        energy = int(player["energy"])
        actual: dict[str, int] = {}
        local_reputation = 0
        service_reputation = 0
        for key, raw_quantity in reward.items():
            quantity = int(raw_quantity)
            if key == "spirit_stones":
                stones += quantity
                actual[key] = quantity
            elif key == "energy":
                gained = min(quantity, max(0, int(player["energy_max"]) - energy))
                energy += gained
                actual[key] = gained
            elif key == "local_reputation":
                local_reputation += quantity
                actual[key] = quantity
            elif key == "service_reputation":
                service_reputation += quantity
                actual[key] = quantity
            else:
                inventory[key] = int(inventory.get(key, 0)) + quantity
                actual[key] = quantity
        if local_reputation or service_reputation:
            reputation = connection.execute(
                "SELECT local_json, service_reputation FROM player_reputations WHERE player_id = ?",
                (player["id"],),
            ).fetchone()
            local = SQLitePlayerRepository._json_object(reputation["local_json"], {}) if reputation is not None else {}
            local["local.xuantian.new_town"] = int(local.get("local.xuantian.new_town", 0)) + local_reputation
            current_service = int(reputation["service_reputation"]) if reputation is not None else 0
            current_service = min(100, current_service + service_reputation)
            connection.execute(
                """
                INSERT INTO player_reputations(player_id, local_json, service_reputation, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(player_id) DO UPDATE SET local_json = excluded.local_json,
                    service_reputation = excluded.service_reputation, updated_at = excluded.updated_at
                """,
                (player["id"], json.dumps(local, ensure_ascii=False, sort_keys=True), current_service, now_text),
            )
        connection.execute(
            """
            UPDATE players
            SET spirit_stones = ?, energy = ?, inventory_json = ?, updated_at = ?
            WHERE id = ?
            """,
            (stones, energy, json.dumps(inventory, ensure_ascii=False, sort_keys=True), now_text, player["id"]),
        )
        return actual

    @staticmethod
    def _dao_status_from_connection(
        connection: sqlite3.Connection,
        player: sqlite3.Row,
        business_date: date,
    ) -> DaoContractStatusRecord:
        rows = connection.execute(
            """
            SELECT contract_key, starts_on, ends_on, status
            FROM dao_contracts
            WHERE player_id = ?
            ORDER BY starts_on DESC, id DESC
            """,
            (player["id"],),
        ).fetchall()
        views: list[DaoContractView] = []
        for row in rows:
            try:
                definition = dao_contract(str(row["contract_key"]))
            except ValueError:
                continue
            status = str(row["status"])
            if status == "active" and business_date > date.fromisoformat(str(row["ends_on"])):
                status = "expired"
            views.append(
                DaoContractView(
                    contract_key=definition.key,
                    label=definition.label,
                    status=status,
                    starts_on=str(row["starts_on"]),
                    ends_on=str(row["ends_on"]),
                    daily_reward=definition.daily_reward_map(),
                )
            )
        return DaoContractStatusRecord(
            player=SQLitePlayerRepository._row_to_player(player),
            contracts=tuple(views),
        )

    async def get_dao_contract_status(
        self,
        *,
        platform: str,
        platform_user_id: str,
    ) -> DaoContractStatusRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._get_dao_contract_status_sync,
                platform,
                platform_user_id,
            )

    def _get_dao_contract_status_sync(
        self,
        platform: str,
        platform_user_id: str,
    ) -> DaoContractStatusRecord:
        with self._connect() as connection:
            row = self._require_player(connection, platform, platform_user_id)
            return self._dao_status_from_connection(connection, row, self._now().date())

    async def activate_dao_contract(
        self,
        *,
        platform: str,
        platform_user_id: str,
        receipt_token: str,
        operation_id: str,
    ) -> DaoContractActivationRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._activate_dao_contract_sync,
                platform,
                platform_user_id,
                receipt_token,
                operation_id,
            )

    def _activate_dao_contract_sync(
        self,
        platform: str,
        platform_user_id: str,
        receipt_token: str,
        operation_id: str,
    ) -> DaoContractActivationRecord:
        try:
            receipt = verify_receipt(receipt_token, self.settings.billing_public_key)
        except BillingReceiptError as exc:
            raise BillingReceiptInvalidError(str(exc)) from exc
        try:
            definition = dao_contract(receipt.contract_key)
        except ValueError as exc:
            raise BillingReceiptInvalidError("receipt contract is not registered") from exc
        subject = f"{platform}:{platform_user_id}"
        now = self._now()
        if receipt.subject != subject:
            raise BillingReceiptInvalidError("receipt subject does not match the player")
        if receipt.currency != "spirit_stones" or receipt.amount != definition.price:
            raise BillingReceiptInvalidError("receipt price does not match the contract")
        if receipt.issued_at > now:
            raise BillingReceiptInvalidError("receipt was issued in the future")
        if receipt.valid_until is not None and receipt.valid_until < now:
            raise BillingReceiptInvalidError("receipt is expired")
        request_hash = self._request_hash(
            "routine.activate_dao_contract",
            {
                "platform": platform,
                "platform_user_id": platform_user_id,
                "receipt_hash": receipt.payload_hash,
            },
        )
        now_text = serialize_datetime(now)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            if existing is not None:
                if existing["operation_name"] != "routine.activate_dao_contract" or existing["request_hash"] != request_hash:
                    raise OperationConflictError("operation input differs from its original request")
                return self._dao_activation_from_payload(json.loads(existing["result_json"]), replay=True)
            row = self._require_player(connection, platform, platform_user_id)
            used = connection.execute(
                "SELECT 1 FROM dao_contracts WHERE receipt_id = ? OR receipt_hash = ?",
                (receipt.receipt_id, receipt.payload_hash),
            ).fetchone()
            if used is not None:
                raise BillingReceiptAlreadyUsedError("receipt was already consumed")
            today = now.date()
            active = connection.execute(
                """
                SELECT ends_on FROM dao_contracts
                WHERE player_id = ? AND contract_key = ? AND status = 'active'
                ORDER BY ends_on DESC LIMIT 1
                """,
                (row["id"], definition.key),
            ).fetchone()
            if active is not None and date.fromisoformat(str(active["ends_on"])) >= today:
                starts = date.fromisoformat(str(active["ends_on"])) + timedelta(days=1)
            else:
                starts = today
            ends = starts + timedelta(days=definition.duration_days - 1)
            activation_reward = self._apply_dao_reward(
                connection, row, definition.activation_reward_map(), now_text
            )
            connection.execute(
                """
                INSERT INTO dao_contracts(
                    player_id, contract_key, receipt_id, receipt_hash, subject,
                    starts_on, ends_on, status, content_version, rule_version,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?)
                """,
                (
                    row["id"], definition.key, receipt.receipt_id, receipt.payload_hash,
                    receipt.subject, starts.isoformat(), ends.isoformat(),
                    definition.content_version, definition.rule_version, now_text, now_text,
                ),
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (row["id"],)).fetchone()
            if updated is None:
                raise RuntimeError("contract activation returned no player")
            payload = {
                "player": self._player_payload(self._row_to_player(updated)),
                "contract_key": definition.key,
                "label": definition.label,
                "receipt_id": receipt.receipt_id,
                "starts_on": starts.isoformat(),
                "ends_on": ends.isoformat(),
                "activation_reward": activation_reward,
                "content_version": definition.content_version,
                "rule_version": definition.rule_version,
            }
            connection.execute(
                """
                INSERT INTO operations(
                    operation_id, operation_name, player_id, request_hash, result_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    operation_id, "routine.activate_dao_contract", row["id"], request_hash,
                    json.dumps(payload, ensure_ascii=False, sort_keys=True), now_text,
                ),
            )
            return self._dao_activation_from_payload(payload)

    @staticmethod
    def _dao_activation_from_payload(
        payload: dict[str, Any], replay: bool = False
    ) -> DaoContractActivationRecord:
        return DaoContractActivationRecord(
            player=SQLitePlayerRepository._row_to_player(payload["player"]),
            contract_key=str(payload["contract_key"]),
            label=str(payload["label"]),
            receipt_id=str(payload["receipt_id"]),
            starts_on=str(payload["starts_on"]),
            ends_on=str(payload["ends_on"]),
            activation_reward={str(key): int(value) for key, value in dict(payload.get("activation_reward", {})).items()},
            already_completed=replay,
        )

    async def claim_dao_contract(
        self,
        *,
        platform: str,
        platform_user_id: str,
        contract_key: str,
        operation_id: str,
    ) -> DaoContractClaimRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._claim_dao_contract_sync,
                platform,
                platform_user_id,
                contract_key,
                operation_id,
            )

    def _claim_dao_contract_sync(
        self,
        platform: str,
        platform_user_id: str,
        contract_key: str,
        operation_id: str,
    ) -> DaoContractClaimRecord:
        try:
            definition = dao_contract(contract_key)
        except ValueError as exc:
            raise DaoContractInvalidError(str(exc)) from exc
        today = self._now().date()
        operation_name = "routine.claim_dao_contract"
        request_hash = self._request_hash(
            operation_name,
            {"platform": platform, "platform_user_id": platform_user_id, "contract_key": contract_key, "business_date": today.isoformat()},
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
                return self._dao_claim_from_payload(json.loads(existing["result_json"]), replay=True)
            row = self._require_player(connection, platform, platform_user_id)
            contract_row = connection.execute(
                """
                SELECT * FROM dao_contracts
                WHERE player_id = ? AND contract_key = ? AND status = 'active'
                  AND starts_on <= ? AND ends_on >= ?
                ORDER BY starts_on DESC LIMIT 1
                """,
                (row["id"], contract_key, today.isoformat(), today.isoformat()),
            ).fetchone()
            if contract_row is None:
                raise DaoContractNotActiveError("dao contract is not active")
            claimed = connection.execute(
                "SELECT 1 FROM dao_contract_claims WHERE contract_id = ? AND business_date = ?",
                (contract_row["id"], today.isoformat()),
            ).fetchone()
            if claimed is not None:
                raise DaoContractAlreadyClaimedError("dao contract was already claimed today")
            reward = definition.daily_reward_map()
            offset = (today - date.fromisoformat(str(contract_row["starts_on"]))).days
            if definition.reputation_every_days and offset % definition.reputation_every_days == 0:
                reward["local_reputation"] = reward.get("local_reputation", 0) + definition.reputation_reward
            actual_reward = self._apply_dao_reward(connection, row, reward, now_text)
            connection.execute(
                """
                INSERT INTO dao_contract_claims(
                    player_id, contract_id, contract_key, business_date, operation_id,
                    reward_json, content_version, rule_version, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["id"], contract_row["id"], definition.key, today.isoformat(), operation_id,
                    json.dumps(actual_reward, ensure_ascii=False, sort_keys=True),
                    definition.content_version, definition.rule_version, now_text,
                ),
            )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (row["id"],)).fetchone()
            if updated is None:
                raise RuntimeError("contract claim returned no player")
            payload = {
                "player": self._player_payload(self._row_to_player(updated)),
                "contract_key": definition.key,
                "label": definition.label,
                "business_date": today.isoformat(),
                "reward": actual_reward,
                "content_version": definition.content_version,
                "rule_version": definition.rule_version,
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
            return self._dao_claim_from_payload(payload)

    @staticmethod
    def _dao_claim_from_payload(
        payload: dict[str, Any], replay: bool = False
    ) -> DaoContractClaimRecord:
        return DaoContractClaimRecord(
            player=SQLitePlayerRepository._row_to_player(payload["player"]),
            contract_key=str(payload["contract_key"]),
            label=str(payload["label"]),
            business_date=str(payload["business_date"]),
            reward={str(key): int(value) for key, value in dict(payload.get("reward", {})).items()},
            already_completed=replay,
        )

    async def revoke_dao_contract(
        self,
        *,
        player_id: str,
        contract_key: str,
        reason: str,
        operation_id: str,
    ) -> bool:
        """Admin/billing port: stop future claims without clawing back rewards."""

        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._revoke_dao_contract_sync,
                player_id,
                contract_key,
                reason,
                operation_id,
            )

    def _revoke_dao_contract_sync(
        self,
        player_id: str,
        contract_key: str,
        reason: str,
        operation_id: str,
    ) -> bool:
        if not reason.strip() or len(reason) > 256:
            raise DaoContractAlreadyRevokedError("revoke reason is required")
        request_hash = self._request_hash(
            "routine.revoke_dao_contract",
            {"player_id": player_id, "contract_key": contract_key, "reason": reason.strip()},
        )
        now_text = serialize_datetime(self._now())
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT operation_name, request_hash, result_json FROM operations WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            if existing is not None:
                if existing["operation_name"] != "routine.revoke_dao_contract" or existing["request_hash"] != request_hash:
                    raise OperationConflictError("operation input differs from its original request")
                return bool(json.loads(existing["result_json"]).get("revoked", False))
            row = connection.execute(
                """
                SELECT dc.id, p.id AS player_db_id
                FROM dao_contracts AS dc
                JOIN players AS p ON p.id = dc.player_id
                WHERE p.player_id = ? AND dc.contract_key = ? AND dc.status = 'active'
                ORDER BY dc.ends_on DESC LIMIT 1
                """,
                (player_id, contract_key),
            ).fetchone()
            if row is None:
                raise DaoContractAlreadyRevokedError("dao contract is not active")
            connection.execute(
                "UPDATE dao_contracts SET status = 'revoked', revoke_reason = ?, updated_at = ? WHERE id = ?",
                (reason.strip(), now_text, row["id"]),
            )
            connection.execute(
                "INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (operation_id, "routine.revoke_dao_contract", row["player_db_id"], request_hash, json.dumps({"revoked": True}), now_text),
            )
            return True

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
            if str(row["realm_key"]) == "soul_transformation" and int(row["domain_charge_max"]) > 0:
                business_date = self._now().date().isoformat()
                if str(row["domain_charge_reset_date"] or "") != business_date:
                    connection.execute(
                        "UPDATE players SET domain_charge = domain_charge_max, domain_charge_reset_date = ?, updated_at = ? WHERE id = ?",
                        (business_date, serialize_datetime(self._now()), row["id"]),
                    )
                    row = connection.execute("SELECT * FROM players WHERE id = ?", (row["id"],)).fetchone()
            if row["domain_crack_until"]:
                try:
                    if self._now() >= datetime.fromisoformat(str(row["domain_crack_until"])):
                        connection.execute("UPDATE players SET domain_crack_until = NULL, updated_at = ? WHERE id = ?", (serialize_datetime(self._now()), row["id"]))
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
        value = json.loads(raw) if isinstance(raw, str) else raw
        return dict(value) if isinstance(value, dict) else dict(default)

    @staticmethod
    def _row_to_player(row: sqlite3.Row | dict[str, Any]) -> PlayerView:
        def value(name: str, default: Any = None) -> Any:
            if isinstance(row, dict):
                return row.get(name, default)
            try:
                return row[name]
            except (IndexError, KeyError):
                return default

        qualification_raw = value("qualification_json", "{}")
        qualification = json.loads(qualification_raw) if isinstance(qualification_raw, str) else qualification_raw
        inventory_raw = value("inventory_json", "{}")
        inventory = json.loads(inventory_raw) if isinstance(inventory_raw, str) else inventory_raw
        intro_raw = value("intro_json", "{}")
        intro_state = json.loads(intro_raw) if isinstance(intro_raw, str) else intro_raw
        if not isinstance(inventory, dict):
            inventory = {}
        if not isinstance(intro_state, dict):
            intro_state = {}
        return PlayerView(
            player_id=str(value("player_id", value("id", ""))),
            platform=str(value("platform", "")),
            platform_user_id=str(value("platform_user_id", "")),
            scene_id=str(value("scene_id", "")),
            nickname=str(value("nickname", "")),
            dao_name=str(value("dao_name", "")),
            stage=str(value("stage", STAGE_NEW_USER)),
            spirit_stones=int(value("spirit_stones", 0)),
            qualification={str(key): int(value) for key, value in qualification.items()},
            created_at=datetime.fromisoformat(str(value("created_at"))),
            updated_at=datetime.fromisoformat(str(value("updated_at"))),
            status=str(value("status", "active")),
            location_key=str(value("location_key", "xuantian.new_town")),
            rule_version=str(value("rule_version", "player-onboarding-v0.1.0")),
            path_key=value("path_key"),
            subprofession_key=value("subprofession_key"),
            stamina=int(value("stamina", 0)),
            stamina_max=int(value("stamina_max", 0)),
            energy=int(value("energy", 0)),
            energy_max=int(value("energy_max", 0)),
            inventory={str(key): int(item) for key, item in inventory.items()},
            durability={
                str(key): int(item)
                for key, item in SQLitePlayerRepository._json_object(value("durability_json", "{}"), {}).items()
            },
            intro_flags=tuple(str(item) for item in intro_state.get("flags", [])),
            selected_service=(
                str(intro_state.get("selected_service"))
                if intro_state.get("selected_service")
                else value("selected_service")
            ),
            realm_key=str(value("realm_key", "mortal")),
            realm_layer=int(value("realm_layer", 0)),
            cultivation=int(value("cultivation", 0)),
            total_cultivation=int(value("total_cultivation", 0)),
            foundation_quality=int(value("foundation_quality", 0)),
            world_merit=int(value("world_merit", 0)),
            talent_points=int(value("talent_points", 0)),
            skill_insights=int(value("skill_insights", 0)),
            weakness_until=(
                datetime.fromisoformat(str(value("weakness_until")))
                if value("weakness_until")
                else None
            ),
            breakthrough_pity_bp=int(value("breakthrough_pity_bp", 0)),
            soul_power=int(value("soul_power", 0)),
            soul_power_max=int(value("soul_power_max", 0)),
            domain_charge=int(value("domain_charge", 0)),
            domain_charge_max=int(value("domain_charge_max", 0)),
            pollution=int(value("pollution", 0)),
            bloodline_stability=int(value("bloodline_stability", 0)),
            cross_realm_penalty_bp=int(value("cross_realm_penalty_bp", 0)),
            soul_fatigue_until=(
                datetime.fromisoformat(str(value("soul_fatigue_until")))
                if value("soul_fatigue_until")
                else None
            ),
            heart_demon_bonus_bp=int(value("heart_demon_bonus_bp", 0)),
            max_hp=int(value("max_hp", 0)),
            max_mp=int(value("max_mp", 0)),
            carry_capacity=int(value("carry_capacity", 0)),
            exploration_efficiency_bp=int(value("exploration_efficiency_bp", 0)),
            domain_key=value("domain_key"),
            domain_power=int(value("domain_power", 0)),
            realm_resistance_bp=int(value("realm_resistance_bp", 0)),
            domain_crack_until=(
                datetime.fromisoformat(str(value("domain_crack_until")))
                if value("domain_crack_until") else None
            ),
            initiative=int(value("initiative", 0)),
            faction_reputation={
                str(key): int(item)
                for key, item in SQLitePlayerRepository._json_object(value("faction_reputation_json", "{}"), {}).items()
            },
            domain_level=int(value("domain_level", 0)),
            void_power=int(value("void_power", 0)),
            void_power_max=int(value("void_power_max", 0)),
            space_resistance_bp=int(value("space_resistance_bp", 0)),
            void_instability_until=(
                datetime.fromisoformat(str(value("void_instability_until")))
                if value("void_instability_until") else None
            ),
            void_route_count=int(value("void_route_count", 0)),
            void_anchor_capacity=int(value("void_anchor_capacity", 0)),
            dao_fruit_progress=int(value("dao_fruit_progress", 0)),
            ascension_merit=int(value("ascension_merit", 0)),
            tribulation_debt=int(value("tribulation_debt", 0)),
            dao_fruit_key=value("dao_fruit_key"),
            endgame_status=str(value("endgame_status", "none")),
            ending_key=value("ending_key"),
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
            "qualification_json": json.dumps(player.qualification, ensure_ascii=False, sort_keys=True),
            "created_at": serialize_datetime(player.created_at),
            "updated_at": serialize_datetime(player.updated_at),
            "status": player.status,
            "location_key": player.location_key,
            "rule_version": player.rule_version,
            "path_key": player.path_key,
            "subprofession_key": player.subprofession_key,
            "stamina": player.stamina,
            "stamina_max": player.stamina_max,
            "energy": player.energy,
            "energy_max": player.energy_max,
            "inventory_json": json.dumps(player.inventory, ensure_ascii=False, sort_keys=True),
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
            "talent_points": player.talent_points,
            "skill_insights": player.skill_insights,
            "weakness_until": serialize_datetime(player.weakness_until) if player.weakness_until else None,
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
