"""SQLite persistence for player identity and the first idempotent operation."""

from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable
from uuid import uuid4

from ..contracts import PlayerView, serialize_datetime
from .config import XiuxianSettings
from .player.models import (
    CultivationRecord,
    IntroRecord,
    PlayerCreateRecord,
    RenameRecord,
    SeekingRecord,
    TravelRecord,
)
from .player.rules import STAGE_MORTAL, STAGE_NEW_USER, qualification_for
from .progression.models import (
    CultivationCancelRecord,
    CultivationRecoveryRecord,
    CultivationSessionRecord,
    CultivationSettlementRecord,
    LayerAdvanceRecord,
    LayerUnlock,
    ResourceRecoveryRecord,
)
from .production.models import (
    ProductionOrderRecord,
    ProductionPreviewRecord,
    ProductionSettlementRecord,
)
from .progression.breakthrough.models import (
    BreakthroughSettlementRecord,
    BreakthroughSessionRecord,
    WeaknessRecoveryRecord,
)
from .world.models import TravelPreview, TravelSettlementRecord, TravelStartRecord
from .world.rules import destination_definition, meets_realm, RULE_VERSION
from .exploration.models import ExplorationSettlementRecord, ExplorationStartRecord
from .exploration.rules import (
    battle_roll_bp,
    exploration_definition,
    meets_realm as exploration_meets_realm,
    settlement_result,
)
from .adventures.models import BountyAcceptRecord, BountyBoardRecord, BountyClaimRecord, BountyOfferView
from .adventures.rules import bounty_definition, DEFINITIONS as BOUNTY_DEFINITIONS, meets_realm as bounty_meets_realm, reward_map
from .routine.models import (
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
    RoutineClaimRecord,
    SevenDayGoalRecord,
    SevenDayGoalView,
    SevenDayStatusRecord,
    SpiritTreeRecord,
)
from .routine.billing import BillingReceiptError, verify_receipt
from .routine.rules import (
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
    weakness_until TEXT,
    breakthrough_pity_bp INTEGER NOT NULL DEFAULT 0 CHECK (breakthrough_pity_bp >= 0),
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


class WeaknessActiveError(RuntimeError):
    """A temporary breakthrough weakness blocks high-risk actions."""


class WeaknessNotActiveError(RuntimeError):
    """There is no breakthrough weakness to recover."""


class CurrencyInsufficientError(RuntimeError):
    """The player does not have enough spirit stones."""


class ProtectionItemInsufficientError(RuntimeError):
    """The requested breakthrough protection item is missing."""


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


class SQLitePlayerRepository:
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
            ("weakness_until", "TEXT"),
            ("breakthrough_pity_bp", "INTEGER NOT NULL DEFAULT 0"),
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

            row = connection.execute(
                "SELECT * FROM players WHERE platform = ? AND platform_user_id = ?",
                (platform, platform_user_id),
            ).fetchone()
            if row is None:
                raise PlayerNotFoundError("player does not exist")
            if row["status"] != "active":
                raise PlayerSuspendedError("player is not writable")

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

            row = connection.execute(
                "SELECT * FROM players WHERE platform = ? AND platform_user_id = ?",
                (platform, platform_user_id),
            ).fetchone()
            if row is None:
                raise PlayerNotFoundError("player does not exist")
            if row["status"] != "active":
                raise PlayerSuspendedError("player is not writable")
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

            from .player.intro_rules import intro_complete

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
        from .player.intro_rules import GUIDE_GATHER_BLOOD_GRASS, TRAVEL_COSTS
        from .progression.rules import REALM_QI_SENSING, SPIRIT_FIELD_LOCATION

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

            row = connection.execute(
                "SELECT * FROM players WHERE platform = ? AND platform_user_id = ?",
                (platform, platform_user_id),
            ).fetchone()
            if row is None:
                raise PlayerNotFoundError("player does not exist")
            if row["status"] != "active":
                raise PlayerSuspendedError("player is not writable")
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

            row = connection.execute(
                "SELECT * FROM players WHERE platform = ? AND platform_user_id = ?",
                (platform, platform_user_id),
            ).fetchone()
            if row is None:
                raise PlayerNotFoundError("player does not exist")
            if row["status"] != "active":
                raise PlayerSuspendedError("player is not writable")
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
            row = connection.execute(
                "SELECT * FROM players WHERE platform = ? AND platform_user_id = ?", (platform, platform_user_id)
            ).fetchone()
            if row is None:
                raise PlayerNotFoundError("player does not exist")
            if row["status"] != "active":
                raise PlayerSuspendedError("player is not writable")
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

            row = connection.execute(
                "SELECT * FROM players WHERE platform = ? AND platform_user_id = ?",
                (platform, platform_user_id),
            ).fetchone()
            if row is None:
                raise PlayerNotFoundError("player does not exist")
            if row["status"] != "active":
                raise PlayerSuspendedError("player is not writable")
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
            row = connection.execute(
                "SELECT * FROM players WHERE platform = ? AND platform_user_id = ?",
                (platform, platform_user_id),
            ).fetchone()
            if row is None:
                raise PlayerNotFoundError("player does not exist")
            if row["status"] != "active":
                raise PlayerSuspendedError("player is not writable")
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
            row = connection.execute(
                "SELECT * FROM players WHERE platform = ? AND platform_user_id = ?", (platform, platform_user_id)
            ).fetchone()
            if row is None:
                raise PlayerNotFoundError("player does not exist")
            if row["status"] != "active":
                raise PlayerSuspendedError("player is not writable")
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
            row = connection.execute(
                "SELECT * FROM players WHERE platform = ? AND platform_user_id = ?",
                (platform, platform_user_id),
            ).fetchone()
            if row is None:
                raise PlayerNotFoundError("player does not exist")
            if row["status"] != "active":
                raise PlayerSuspendedError("player is not readable")
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
            row = connection.execute(
                "SELECT * FROM players WHERE platform = ? AND platform_user_id = ?",
                (platform, platform_user_id),
            ).fetchone()
            if row is None:
                raise PlayerNotFoundError("player does not exist")
            if row["status"] != "active":
                raise PlayerSuspendedError("player is not writable")
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
            row = connection.execute(
                "SELECT * FROM players WHERE platform = ? AND platform_user_id = ?",
                (platform, platform_user_id),
            ).fetchone()
            if row is None:
                raise PlayerNotFoundError("player does not exist")
            if row["status"] != "active":
                raise PlayerSuspendedError("player is not writable")
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
        from .player.path_rules import reward_items

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

            row = connection.execute(
                "SELECT * FROM players WHERE platform = ? AND platform_user_id = ?",
                (platform, platform_user_id),
            ).fetchone()
            if row is None:
                raise PlayerNotFoundError("player does not exist")
            if row["status"] != "active":
                raise PlayerSuspendedError("player is not writable")
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
        from .progression.rules import REALM_QI_SENSING, cultivation_mode

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

            row = connection.execute(
                "SELECT * FROM players WHERE platform = ? AND platform_user_id = ?",
                (platform, platform_user_id),
            ).fetchone()
            if row is None:
                raise PlayerNotFoundError("player does not exist")
            if row["status"] != "active":
                raise PlayerSuspendedError("player is not writable")
            if row["stage"] != "cultivator" or row["realm_key"] != REALM_QI_SENSING:
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
                from .player.intro_rules import GUIDE_GATHER_BLOOD_GRASS

                if GUIDE_GATHER_BLOOD_GRASS not in set(intro_state.get("flags", [])):
                    raise LocationRequirementError("spirit cultivation requires the gathering lesson")
            exploration = connection.execute(
                "SELECT 1 FROM exploration_sessions WHERE player_id = ? AND status IN ('created', 'running', 'combat_pending') LIMIT 1",
                (row["id"],),
            ).fetchone()
            if exploration is not None:
                raise CultivationBusyError("exploration is still running")
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
        from .progression.rules import CULTIVATION_SETTLEMENT_GRACE_SECONDS, cultivation_gain

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

            row = connection.execute(
                "SELECT * FROM players WHERE platform = ? AND platform_user_id = ?",
                (platform, platform_user_id),
            ).fetchone()
            if row is None:
                raise PlayerNotFoundError("player does not exist")
            if row["status"] != "active":
                raise PlayerSuspendedError("player is not writable")
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
        from .progression.rules import CULTIVATION_SETTLEMENT_GRACE_SECONDS, cultivation_gain

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

            row = connection.execute(
                "SELECT * FROM players WHERE platform = ? AND platform_user_id = ?",
                (platform, platform_user_id),
            ).fetchone()
            if row is None:
                raise PlayerNotFoundError("player does not exist")
            if row["status"] != "active":
                raise PlayerSuspendedError("player is not writable")
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
        from .progression.rules import CULTIVATION_SETTLEMENT_GRACE_SECONDS

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
            row = connection.execute(
                "SELECT * FROM players WHERE platform = ? AND platform_user_id = ?",
                (platform, platform_user_id),
            ).fetchone()
            if row is None:
                raise PlayerNotFoundError("player does not exist")
            if row["status"] != "active":
                raise PlayerSuspendedError("player is not writable")
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
        from .progression.rules import can_advance_layer, layer_unlocks, next_layer_threshold, REALM_QI_SENSING

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
            row = connection.execute(
                "SELECT * FROM players WHERE platform = ? AND platform_user_id = ?",
                (platform, platform_user_id),
            ).fetchone()
            if row is None:
                raise PlayerNotFoundError("player does not exist")
            if row["status"] != "active":
                raise PlayerSuspendedError("player is not writable")
            if row["stage"] != "cultivator" or row["realm_key"] != REALM_QI_SENSING:
                raise PlayerStageConflictError("player is not ready to advance")
            running = connection.execute(
                "SELECT 1 FROM cultivation_sessions WHERE player_id = ? AND status = 'running' LIMIT 1",
                (row["id"],),
            ).fetchone()
            if running is not None:
                raise CultivationBusyError("cultivation is still running")
            layer = int(row["realm_layer"])
            if layer >= 10 or next_layer_threshold(REALM_QI_SENSING, layer) is None:
                raise RealmLayerInvalidError("realm is already at its maximum layer")
            if not can_advance_layer(REALM_QI_SENSING, layer, int(row["cultivation"])):
                raise RealmCultivationInsufficientError("realm cultivation is insufficient")
            unlocks = layer_unlocks(REALM_QI_SENSING, layer + 1)
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

    async def recover_resources(
        self,
        *,
        platform: str,
        platform_user_id: str,
        operation_id: str,
    ) -> ResourceRecoveryRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._recover_resources_sync, platform, platform_user_id, operation_id)

    def _recover_resources_sync(self, platform: str, platform_user_id: str, operation_id: str) -> ResourceRecoveryRecord:
        last_error: Exception | None = None
        for attempt in range(5):
            try:
                return self._recover_resources_once(platform, platform_user_id, operation_id)
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).lower():
                    raise
                if attempt == 4:
                    raise RepositoryBusyError("database remained locked") from exc
                last_error = exc
                time.sleep(0.01 * (2**attempt))
        raise RepositoryBusyError("database remained locked") from last_error

    def _recover_resources_once(self, platform: str, platform_user_id: str, operation_id: str) -> ResourceRecoveryRecord:
        from .progression.rules import RECOVERY_PERIOD_SECONDS

        operation_payload = {"platform": platform, "platform_user_id": platform_user_id}
        request_hash = self._request_hash("player.recover_resources", operation_payload)
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
                    existing_operation["operation_name"] != "player.recover_resources"
                    or existing_operation["request_hash"] != request_hash
                ):
                    raise OperationConflictError("operation input differs from its original request")
                payload = json.loads(existing_operation["result_json"])
                return ResourceRecoveryRecord(
                    player=self._row_to_player(payload["player"]),
                    periods=int(payload["periods"]),
                    recovered_stamina=int(payload["recovered_stamina"]),
                    recovered_energy=int(payload["recovered_energy"]),
                    changed=bool(payload["changed"]),
                    already_completed=True,
                )
            row = connection.execute(
                "SELECT * FROM players WHERE platform = ? AND platform_user_id = ?",
                (platform, platform_user_id),
            ).fetchone()
            if row is None:
                raise PlayerNotFoundError("player does not exist")
            if row["status"] != "active":
                raise PlayerSuspendedError("player is not writable")
            try:
                last_update = datetime.fromisoformat(str(row["updated_at"]))
            except ValueError:
                last_update = now
            elapsed = max(0, int((now - last_update).total_seconds()))
            periods = elapsed // RECOVERY_PERIOD_SECONDS
            stamina_before = int(row["stamina"])
            energy_before = int(row["energy"])
            stamina_after = min(int(row["stamina_max"]), stamina_before + periods)
            energy_after = min(int(row["energy_max"]), energy_before + periods)
            recovered_stamina = stamina_after - stamina_before
            recovered_energy = energy_after - energy_before
            changed = recovered_stamina > 0 or recovered_energy > 0
            if periods > 0:
                advanced_update = last_update + timedelta(seconds=periods * RECOVERY_PERIOD_SECONDS)
                connection.execute(
                    "UPDATE players SET stamina = ?, energy = ?, updated_at = ? WHERE id = ?",
                    (stamina_after, energy_after, serialize_datetime(advanced_update), row["id"]),
                )
            updated = connection.execute("SELECT * FROM players WHERE id = ?", (row["id"],)).fetchone()
            if updated is None:
                raise RuntimeError("resource recovery returned no player")
            player = self._row_to_player(updated)
            payload = {
                "player": self._player_payload(player),
                "periods": periods,
                "recovered_stamina": recovered_stamina,
                "recovered_energy": recovered_energy,
                "changed": changed,
            }
            connection.execute(
                "INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    operation_id,
                    "player.recover_resources",
                    row["id"],
                    request_hash,
                    json.dumps(payload, ensure_ascii=False, sort_keys=True),
                    now_text,
                ),
            )
            return ResourceRecoveryRecord(
                player=player,
                periods=periods,
                recovered_stamina=recovered_stamina,
                recovered_energy=recovered_energy,
                changed=changed,
            )

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
        from .production.rules import recipe_definition

        recipe = recipe_definition(recipe_key)
        now = self._now()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM players WHERE platform = ? AND platform_user_id = ?",
                (platform, platform_user_id),
            ).fetchone()
            if row is None:
                raise PlayerNotFoundError("player does not exist")
            if row["status"] != "active":
                raise PlayerSuspendedError("player is not writable")
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
        from .production.rules import RECIPE_RULE_VERSION, TOOL_MAX_DURABILITY_BP, random_quality_bp, recipe_definition

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

            row = connection.execute(
                "SELECT * FROM players WHERE platform = ? AND platform_user_id = ?",
                (platform, platform_user_id),
            ).fetchone()
            if row is None:
                raise PlayerNotFoundError("player does not exist")
            if row["status"] != "active":
                raise PlayerSuspendedError("player is not writable")
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
        from .production.rules import HIGH_QUALITY_THRESHOLD_BP, QUALITY_SUCCESS_THRESHOLD_BP, recipe_definition

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
            row = connection.execute(
                "SELECT * FROM players WHERE platform = ? AND platform_user_id = ?",
                (platform, platform_user_id),
            ).fetchone()
            if row is None:
                raise PlayerNotFoundError("player does not exist")
            if row["status"] != "active":
                raise PlayerSuspendedError("player is not writable")
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
        from .production.rules import production_quality

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
        from .progression.breakthrough.rules import breakthrough_definition, success_bp

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

            row = connection.execute(
                "SELECT * FROM players WHERE platform = ? AND platform_user_id = ?",
                (platform, platform_user_id),
            ).fetchone()
            if row is None:
                raise PlayerNotFoundError("player does not exist")
            if row["status"] != "active":
                raise PlayerSuspendedError("player is not writable")
            if target_realm != definition.target_realm:
                raise BreakthroughRequirementError("target breakthrough is not open")
            if row["stage"] != "cultivator" or row["realm_key"] != definition.source_realm:
                raise BreakthroughRequirementError("current realm does not match the breakthrough")
            if int(row["realm_layer"]) != 10:
                raise BreakthroughRequirementError("only the current realm's L10 can break through")
            if int(row["total_cultivation"]) < definition.required_total_cultivation:
                raise BreakthroughRequirementError("total cultivation is insufficient")
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

            inventory = self._json_object(row["inventory_json"], {})
            for item_key, quantity in definition.materials.items():
                if int(inventory.get(item_key, 0)) < quantity:
                    raise MaterialInsufficientError("breakthrough material is insufficient")
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
            preparation_bp = quality_bonus_bp + technique_bonus_bp + formation_bonus_bp
            final_success_bp = success_bp(definition, pity_before, preparation_bp)
            for item_key, quantity in definition.materials.items():
                inventory[item_key] = int(inventory.get(item_key, 0)) - quantity
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
                "random_pool": definition.random_pool,
                "base_success_bp": definition.base_success_bp,
                "foundation_quality": foundation_quality,
                "quality_bonus_bp": quality_bonus_bp,
                "technique_bonus_bp": technique_bonus_bp,
                "formation_bonus_bp": formation_bonus_bp,
                "preparation_bp": preparation_bp,
                "success_bp": final_success_bp,
                "pity_before_bp": pity_before,
                "protection_requested": protection,
                "protection_key": definition.protection_key if protection else None,
                "materials": definition.materials,
                "currency_cost": definition.currency_cost,
                "random_seed": operation_id,
            }
            connection.execute(
                "UPDATE players SET inventory_json = ?, spirit_stones = spirit_stones - ?, updated_at = ? WHERE id = ?",
                (
                    json.dumps(inventory, ensure_ascii=False, sort_keys=True),
                    definition.currency_cost,
                    now_text,
                    row["id"],
                ),
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
        from .progression.breakthrough.rules import (
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
            row = connection.execute(
                "SELECT * FROM players WHERE platform = ? AND platform_user_id = ?",
                (platform, platform_user_id),
            ).fetchone()
            if row is None:
                raise PlayerNotFoundError("player does not exist")
            if row["status"] != "active":
                raise PlayerSuspendedError("player is not writable")
            session = connection.execute(
                "SELECT * FROM breakthrough_sessions WHERE player_id = ? AND status = 'preparing' ORDER BY id DESC LIMIT 1",
                (row["id"],),
            ).fetchone()
            if session is None:
                raise BreakthroughNotFoundError("no preparing breakthrough")
            ends_at = datetime.fromisoformat(str(session["ends_at"]))
            if now < ends_at:
                raise BreakthroughNotReadyError("breakthrough is not ready")
            snapshot = self._json_object(session["snapshot_json"], {})
            from .progression.breakthrough.rules import breakthrough_definition

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
            protection_key = str(snapshot.get("protection_key") or definition.protection_key)
            inventory = self._json_object(row["inventory_json"], {})
            protection_consumed = bool(
                (not success)
                and protection_requested
                and int(inventory.get(protection_key, 0)) > 0
            )
            if protection_consumed:
                inventory[protection_key] = int(inventory.get(protection_key, 0)) - 1
            pity_after = next_pity_bp(definition, pity_before, success)
            weakness_until: str | None = None
            if success:
                cultivation_after = 0
                stamina_after = min(
                    int(row["stamina_max"]),
                    int(row["stamina"]) + definition.reward_stamina,
                )
                reward_items = dict(definition.reward_items or {})
                for item_key, quantity in reward_items.items():
                    inventory[item_key] = int(inventory.get(item_key, 0)) + quantity
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
                status = "succeeded"
            else:
                retention_bp = definition.protection_retention_bp if protection_consumed else definition.retention_bp
                weakness_seconds = definition.protection_weakness_seconds if protection_consumed else definition.weakness_seconds
                cultivation_after = retained_cultivation(
                    cultivation_before,
                    retention_bp,
                    definition.source_cultivation_cap,
                )
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
                "foundation_quality": int(snapshot.get("foundation_quality", 0)),
                "preparation_bp": int(snapshot.get("preparation_bp", 0)),
                "reward_currency": definition.reward_currency if success else 0,
                "reward_stamina": definition.reward_stamina if success else 0,
                "reward_world_merit": definition.reward_world_merit if success else 0,
                "reward_items": dict(definition.reward_items or {}) if success else {},
                "status": status,
            }
            connection.execute(
                "UPDATE breakthrough_sessions SET status = ?, result_json = ?, updated_at = ? WHERE id = ?",
                (status, json.dumps(result, ensure_ascii=False, sort_keys=True), now_text, session["id"]),
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
                self._recover_weakness_sync, platform, platform_user_id, early, operation_id
            )

    def _recover_weakness_sync(self, platform: str, platform_user_id: str, early: bool, operation_id: str) -> WeaknessRecoveryRecord:
        last_error: Exception | None = None
        for attempt in range(5):
            try:
                return self._recover_weakness_once(platform, platform_user_id, early, operation_id)
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).lower():
                    raise
                if attempt == 4:
                    raise RepositoryBusyError("database remained locked") from exc
                last_error = exc
                time.sleep(0.01 * (2**attempt))
        raise RepositoryBusyError("database remained locked") from last_error

    def _recover_weakness_once(self, platform: str, platform_user_id: str, early: bool, operation_id: str) -> WeaknessRecoveryRecord:
        operation_name = "progression.recover_weakness"
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
                    already_completed=True,
                )
            row = connection.execute(
                "SELECT * FROM players WHERE platform = ? AND platform_user_id = ?",
                (platform, platform_user_id),
            ).fetchone()
            if row is None:
                raise PlayerNotFoundError("player does not exist")
            if row["status"] != "active":
                raise PlayerSuspendedError("player is not writable")
            weakness_until = row["weakness_until"]
            if not weakness_until:
                raise WeaknessNotActiveError("no breakthrough weakness is active")
            until = datetime.fromisoformat(str(weakness_until))
            expired = now >= until
            inventory = self._json_object(row["inventory_json"], {})
            medicine_consumed = False
            stones_spent = 0
            if not expired and not early:
                raise WeaknessActiveError("weakness has not expired")
            if not expired and early:
                if int(inventory.get("item.pill.healing_low", 0)) < 1:
                    raise MaterialInsufficientError("early recovery requires a low healing pill")
                if int(row["spirit_stones"]) < 50:
                    raise CurrencyInsufficientError("early recovery requires 50 spirit stones")
                inventory["item.pill.healing_low"] = int(inventory.get("item.pill.healing_low", 0)) - 1
                medicine_consumed = True
                stones_spent = 50
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
            reward_items={str(key): int(value) for key, value in payload.get("reward_items", {}).items()},
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

            row = connection.execute(
                "SELECT * FROM players WHERE platform = ? AND platform_user_id = ?",
                (platform, platform_user_id),
            ).fetchone()
            if row is None:
                raise PlayerNotFoundError("player does not exist")
            if row["status"] != "active":
                raise PlayerSuspendedError("player is not writable")

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

            row = connection.execute(
                "SELECT * FROM players WHERE platform = ? AND platform_user_id = ?",
                (platform, platform_user_id),
            ).fetchone()
            if row is None:
                raise PlayerNotFoundError("player does not exist")
            if row["status"] != "active":
                raise PlayerSuspendedError("player is not writable")
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
            row = connection.execute(
                "SELECT * FROM players WHERE platform = ? AND platform_user_id = ?",
                (platform, platform_user_id),
            ).fetchone()
            if row is None:
                raise PlayerNotFoundError("player does not exist")
            if row["status"] != "active":
                raise PlayerSuspendedError("player is not writable")
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
            row = connection.execute(
                "SELECT * FROM players WHERE platform = ? AND platform_user_id = ?",
                (platform, platform_user_id),
            ).fetchone()
            if row is None:
                raise PlayerNotFoundError("player does not exist")
            if row["status"] != "active":
                raise PlayerSuspendedError("player is not writable")
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
            row = connection.execute(
                "SELECT * FROM players WHERE platform = ? AND platform_user_id = ?",
                (platform, platform_user_id),
            ).fetchone()
            if row is None:
                raise PlayerNotFoundError("player does not exist")
            if row["status"] != "active":
                raise PlayerSuspendedError("player is not writable")
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
            row = connection.execute(
                "SELECT * FROM players WHERE platform = ? AND platform_user_id = ?",
                (platform, platform_user_id),
            ).fetchone()
            if row is None:
                raise PlayerNotFoundError("player does not exist")
            if row["status"] != "active":
                raise PlayerSuspendedError("player is not writable")
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
            row = connection.execute(
                "SELECT * FROM players WHERE platform = ? AND platform_user_id = ?",
                (platform, platform_user_id),
            ).fetchone()
            if row is None:
                raise PlayerNotFoundError("player does not exist")
            if row["status"] != "active":
                raise PlayerSuspendedError("player is not writable")
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
            row = connection.execute(
                "SELECT * FROM players WHERE platform = ? AND platform_user_id = ?",
                (platform, platform_user_id),
            ).fetchone()
            if row is None:
                raise PlayerNotFoundError("player does not exist")
            if row["status"] != "active":
                raise PlayerSuspendedError("player is not writable")
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
            row = connection.execute(
                "SELECT * FROM players WHERE platform = ? AND platform_user_id = ?",
                (platform, platform_user_id),
            ).fetchone()
            if row is None:
                raise PlayerNotFoundError("player does not exist")
            if row["status"] != "active":
                raise PlayerSuspendedError("player is not writable")
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
            row = connection.execute(
                "SELECT * FROM players WHERE platform = ? AND platform_user_id = ?",
                (platform, platform_user_id),
            ).fetchone()
            if row is None:
                raise PlayerNotFoundError("player does not exist")
            if row["status"] != "active":
                raise PlayerSuspendedError("player is not writable")
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
            row = connection.execute(
                "SELECT * FROM players WHERE platform = ? AND platform_user_id = ?",
                (platform, platform_user_id),
            ).fetchone()
            if row is None:
                raise PlayerNotFoundError("player does not exist")
            if row["status"] != "active":
                raise PlayerSuspendedError("player is not writable")
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
            row = connection.execute(
                "SELECT * FROM players WHERE platform = ? AND platform_user_id = ?",
                (platform, platform_user_id),
            ).fetchone()
            if row is None:
                raise PlayerNotFoundError("player does not exist")
            if row["status"] != "active":
                raise PlayerSuspendedError("player is not writable")
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
            row = connection.execute(
                "SELECT * FROM players WHERE platform = ? AND platform_user_id = ?",
                (platform, platform_user_id),
            ).fetchone()
            if row is None:
                raise PlayerNotFoundError("player does not exist")
            if row["status"] != "active":
                raise PlayerSuspendedError("player is not writable")
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
            row = connection.execute(
                "SELECT * FROM players WHERE platform = ? AND platform_user_id = ?",
                (platform, platform_user_id),
            ).fetchone()
            if row is None:
                raise PlayerNotFoundError("player does not exist")
            if row["status"] != "active":
                raise PlayerSuspendedError("player is not writable")
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
        return self._row_to_player(row) if row is not None else None

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
            weakness_until=(
                datetime.fromisoformat(str(value("weakness_until")))
                if value("weakness_until")
                else None
            ),
            breakthrough_pity_bp=int(value("breakthrough_pity_bp", 0)),
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
            "weakness_until": serialize_datetime(player.weakness_until) if player.weakness_until else None,
            "breakthrough_pity_bp": player.breakthrough_pity_bp,
        }
