"""SQLite persistence for player identity and the first idempotent operation."""

from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
from datetime import date, datetime, timezone
from typing import Any, Callable

from ...contracts import serialize_datetime
from ..config import XiuxianSettings
from ..player.repository import PlayerRepositoryMixin
from ..progression.repository import ProgressionRepositoryMixin
from ..progression.cultivation_repository import CultivationRepositoryMixin
from ..progression.endgame_repository import EndgameRepositoryMixin
from ..progression.final_battle_repository import FinalBattleRepositoryMixin
from ..progression.tribulation_repository import TribulationTrialRepositoryMixin
from ..progression.breakthrough.repository import BreakthroughRepositoryMixin
from ..world.repository import WorldRepositoryMixin
from ..world.travel_repository import TravelRepositoryMixin
from ..world.cloud_repository import CloudRepositoryMixin
from ..exploration.repository import ExplorationRepositoryMixin
from ..combat.repository import CombatRepositoryMixin
from ..combat.party_repository import PartyCombatRepositoryMixin
from ..adventures.repository import AdventuresRepositoryMixin
from ..adventures.dao_echoes_repository import DaoEchoesRepositoryMixin
from ..production.repository import ProductionRepositoryMixin
from ..production.contract_repository import ContractProductionRepositoryMixin
from ..production.facility_repository import FacilityRepositoryMixin
from ..items.repository import ItemRepositoryMixin
from ..production.endgame_repository import EndgameProductionRepositoryMixin
from ..advancement.repository import AdvancementRepositoryMixin
from ..livelihood.repository import LivelihoodRepositoryMixin
from ..social.sect_repository import SectRepositoryMixin
from ..social.party_repository import PartyRepositoryMixin
from ..social.mentor_repository import MentorRepositoryMixin
from ..events.repository import EventsRepositoryMixin
from ..events.demon_repository import DemonInvasionRepositoryMixin
from ..events.season_repository import FinalHeavenSeasonRepositoryMixin
from ..specials.arena_repository import ArenaRepositoryMixin
from ..specials.team_arena_repository import TeamArenaRepositoryMixin
from ..specials.arena_recovery_repository import ArenaRecoveryRepositoryMixin
from ..specials.arena_projection import project_arena_result
from ..quests.repository import QuestRepositoryMixin
from ..quests.cross_realm_repository import DemonQuestRepositoryMixin
from ..economy.repository import EconomyRepositoryMixin
from ..economy.cross_realm_trade_repository import CrossRealmTradeRepositoryMixin
from ..routine.repository import RoutineRepositoryMixin
from .errors import *  # noqa: F401,F403
from .schema import SCHEMA


class SQLitePlayerRepository(
    PlayerRepositoryMixin,
    TravelRepositoryMixin,
    CloudRepositoryMixin,
    TribulationTrialRepositoryMixin,
    EndgameRepositoryMixin,
    FinalBattleRepositoryMixin,
    WorldRepositoryMixin,
    ProgressionRepositoryMixin,
    RoutineRepositoryMixin,
    ExplorationRepositoryMixin,
    CombatRepositoryMixin,
    PartyCombatRepositoryMixin,
    AdventuresRepositoryMixin,
    DaoEchoesRepositoryMixin,
    ContractProductionRepositoryMixin,
    ProductionRepositoryMixin,
    FacilityRepositoryMixin,
    ItemRepositoryMixin,
    EndgameProductionRepositoryMixin,
    LivelihoodRepositoryMixin,
    SectRepositoryMixin,
    PartyRepositoryMixin,
    MentorRepositoryMixin,
    EventsRepositoryMixin,
    DemonInvasionRepositoryMixin,
    FinalHeavenSeasonRepositoryMixin,
    ArenaRepositoryMixin,
    TeamArenaRepositoryMixin,
    ArenaRecoveryRepositoryMixin,
    DemonQuestRepositoryMixin,
    QuestRepositoryMixin,
    EconomyRepositoryMixin,
    CrossRealmTradeRepositoryMixin,
    AdvancementRepositoryMixin,
    CultivationRepositoryMixin,
    BreakthroughRepositoryMixin,
):
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

    @staticmethod
    def _project_arena_result(connection, **kwargs):
        return project_arena_result(connection, **kwargs)

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
        if writable and str(row["endgame_status"] or "none") in {
            "ascension_ready",
            "ascended",
            "remained_in_world",
        }:
            raise PlayerSuspendedError("endgame state has frozen ordinary writes")
        if writable and connection.execute(
            "SELECT 1 FROM final_battle_members WHERE player_id=? AND asset_lock_status='locked' LIMIT 1",
            (row["id"],),
        ).fetchone() is not None:
            raise PlayerSuspendedError("final battle assets are locked")
        return row

    def _initialize_sync(self) -> None:
        with self._connect() as connection:
            connection.executescript(SCHEMA)
            self._migrate_legacy_schema(connection)
            self._migrate_arena_mode_schema(connection)
            self._migrate_party_type_schema(connection)
            self._migrate_cultivation_session_status(connection)
            self._migrate_economy_ledger_asset_kind(connection)
            self._migrate_facility_schema(connection)
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
                "INSERT OR IGNORE INTO schema_migrations(migration_key, applied_at) VALUES (?, ?)",
                ("events.final_heaven.v0.6", serialize_datetime(self._now())),
            )
            connection.execute(
                "INSERT OR IGNORE INTO schema_migrations(migration_key, applied_at) VALUES (?, ?)",
                ("production.contract.v0.3", serialize_datetime(self._now())),
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
    def _migrate_facility_schema(connection: sqlite3.Connection) -> None:
        """Add v0.2 facility ownership fields to databases created earlier."""

        sect_columns = {row["name"] for row in connection.execute("PRAGMA table_info(sects)")}
        if "spirit_stones" not in sect_columns:
            connection.execute(
                "ALTER TABLE sects ADD COLUMN spirit_stones INTEGER NOT NULL DEFAULT 0 CHECK (spirit_stones >= 0)"
            )
        order_columns = {row["name"] for row in connection.execute("PRAGMA table_info(production_orders)")}
        if "facility_slot_id" not in order_columns:
            connection.execute(
                "ALTER TABLE production_orders ADD COLUMN facility_slot_id INTEGER REFERENCES production_facility_slots(id)"
            )
        connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_production_orders_facility_active "
            "ON production_orders(facility_slot_id) "
            "WHERE facility_slot_id IS NOT NULL AND status = 'processing'"
        )
        connection.execute(
            "CREATE TABLE IF NOT EXISTS production_facility_slots ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "slot_key TEXT NOT NULL UNIQUE,"
            "location_key TEXT NOT NULL,"
            "facility_kind TEXT NOT NULL,"
            "slot_index INTEGER NOT NULL CHECK (slot_index > 0),"
            "owner_type TEXT CHECK (owner_type IN ('personal', 'sect')),"
            "owner_id TEXT,"
            "status TEXT NOT NULL CHECK (status IN ('unclaimed', 'active', 'inactive')),"
            "last_maintenance_date TEXT,"
            "created_at TEXT NOT NULL,"
            "updated_at TEXT NOT NULL,"
            "CHECK ((status = 'unclaimed' AND owner_type IS NULL AND owner_id IS NULL) OR "
            "(status IN ('active', 'inactive') AND owner_type IS NOT NULL AND owner_id IS NOT NULL)),"
            "UNIQUE (location_key, facility_kind, slot_index))"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_production_facility_owner "
            "ON production_facility_slots(owner_type, owner_id, status)"
        )
        connection.execute(
            "CREATE TABLE IF NOT EXISTS production_facility_maintenance ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT,"
            "slot_id INTEGER NOT NULL REFERENCES production_facility_slots(id),"
            "business_date TEXT NOT NULL,"
            "owner_type TEXT NOT NULL CHECK (owner_type IN ('personal', 'sect')),"
            "owner_id TEXT NOT NULL,"
            "fee INTEGER NOT NULL CHECK (fee > 0),"
            "paid INTEGER NOT NULL CHECK (paid IN (0, 1)),"
            "status TEXT NOT NULL CHECK (status IN ('active', 'inactive')),"
            "operation_id TEXT NOT NULL UNIQUE,"
            "created_at TEXT NOT NULL,"
            "UNIQUE (slot_id, business_date))"
        )
        now_text = serialize_datetime(datetime.now(timezone.utc))
        from ..production.facility_rules import FACILITY_DEFINITIONS

        for definition in FACILITY_DEFINITIONS:
            connection.execute(
                "INSERT OR IGNORE INTO production_facility_slots("
                "slot_key, location_key, facility_kind, slot_index, status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, 'unclaimed', ?, ?)",
                (
                    definition.slot_key,
                    definition.location_key,
                    definition.facility_kind,
                    definition.slot_index,
                    now_text,
                    now_text,
                ),
            )

    @staticmethod
    def _migrate_arena_mode_schema(connection: sqlite3.Connection) -> None:
        """Expand spar-only arena tables without losing existing rows."""

        tables = {
            name: connection.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
            ).fetchone()
            for name in ("arena_snapshots", "arena_matches")
        }
        if all(
            table and "'arena.rank'" in str(table[0]) and "'arena.practice'" in str(table[0])
            for table in tables.values()
        ):
            return
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute("DROP INDEX IF EXISTS idx_arena_snapshots_pool")
        connection.execute("DROP INDEX IF EXISTS idx_arena_snapshots_player")
        connection.execute("DROP INDEX IF EXISTS idx_arena_snapshots_active_player")
        connection.execute("DROP INDEX IF EXISTS idx_arena_matches_challenger")
        connection.execute("DROP INDEX IF EXISTS idx_arena_matches_defender_snapshot")
        connection.execute(
            """
            CREATE TABLE arena_snapshots_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_id TEXT NOT NULL UNIQUE,
                player_id INTEGER NOT NULL REFERENCES players(id),
                status TEXT NOT NULL CHECK (status IN ('published', 'revoked', 'expired')),
                arena_mode_key TEXT NOT NULL CHECK (arena_mode_key IN ('arena.spar', 'arena.rank', 'arena.practice')),
                rating INTEGER NOT NULL CHECK (rating >= 0),
                matchable_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                snapshot_json TEXT NOT NULL DEFAULT '{}',
                public_json TEXT NOT NULL DEFAULT '{}',
                content_version TEXT NOT NULL,
                rule_version TEXT NOT NULL,
                revoked_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute("INSERT INTO arena_snapshots_new SELECT * FROM arena_snapshots")
        connection.execute("DROP TABLE arena_snapshots")
        connection.execute("ALTER TABLE arena_snapshots_new RENAME TO arena_snapshots")
        connection.execute(
            "CREATE INDEX idx_arena_snapshots_pool ON arena_snapshots(status, rating, matchable_at, expires_at)"
        )
        connection.execute(
            "CREATE INDEX idx_arena_snapshots_player ON arena_snapshots(player_id, status, created_at)"
        )
        connection.execute(
            "CREATE UNIQUE INDEX idx_arena_snapshots_active_player ON arena_snapshots(player_id) WHERE status = 'published'"
        )
        connection.execute(
            """
            CREATE TABLE arena_matches_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                match_id TEXT NOT NULL UNIQUE,
                challenger_id INTEGER NOT NULL REFERENCES players(id),
                defender_id INTEGER NOT NULL REFERENCES players(id),
                challenger_snapshot_id TEXT NOT NULL REFERENCES arena_snapshots(snapshot_id),
                defender_snapshot_id TEXT NOT NULL REFERENCES arena_snapshots(snapshot_id),
                arena_mode_key TEXT NOT NULL CHECK (arena_mode_key IN ('arena.spar', 'arena.rank', 'arena.practice')),
                status TEXT NOT NULL CHECK (status IN ('settled')),
                outcome TEXT NOT NULL CHECK (outcome IN ('challenger_won', 'defender_won', 'draw')),
                rounds INTEGER NOT NULL CHECK (rounds BETWEEN 1 AND 15),
                score_counted INTEGER NOT NULL CHECK (score_counted IN (0, 1)),
                challenger_rating_delta INTEGER NOT NULL,
                defender_rating_delta INTEGER NOT NULL,
                snapshot_json TEXT NOT NULL DEFAULT '{}',
                result_json TEXT NOT NULL DEFAULT '{}',
                operation_id TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL,
                settled_at TEXT NOT NULL,
                CHECK (challenger_id <> defender_id)
            )
            """
        )
        connection.execute(
            "INSERT INTO arena_matches_new SELECT * FROM arena_matches"
        )
        connection.execute("DROP TABLE arena_matches")
        connection.execute("ALTER TABLE arena_matches_new RENAME TO arena_matches")
        connection.execute(
            "CREATE INDEX idx_arena_matches_challenger ON arena_matches(challenger_id, created_at)"
        )
        connection.execute(
            "CREATE INDEX idx_arena_matches_defender_snapshot ON arena_matches(challenger_id, defender_snapshot_id, created_at)"
        )
        connection.execute("PRAGMA foreign_keys = ON")

    @staticmethod
    def _migrate_party_type_schema(connection: sqlite3.Connection) -> None:
        """Allow the arena-specific three-member party type in old databases."""

        table = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'parties'"
        ).fetchone()
        schema_sql = str(table[0]) if table and table[0] else ""
        if "'arena_trio'" in schema_sql:
            return
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute("DROP INDEX IF EXISTS idx_parties_leader")
        connection.execute("DROP INDEX IF EXISTS idx_parties_status")
        connection.execute(
            """
            CREATE TABLE parties_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                party_id TEXT NOT NULL UNIQUE,
                party_type TEXT NOT NULL CHECK (party_type IN ('exploration_pair', 'arena_trio')),
                status TEXT NOT NULL CHECK (status IN ('forming', 'ready', 'disbanded', 'expired')),
                leader_id INTEGER NOT NULL REFERENCES players(id),
                location_key TEXT NOT NULL,
                confirmation_deadline TEXT NOT NULL,
                current_session_id TEXT,
                distribution_key TEXT NOT NULL DEFAULT 'contribution',
                content_version TEXT NOT NULL,
                rule_version TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute("INSERT INTO parties_new SELECT * FROM parties")
        connection.execute("DROP TABLE parties")
        connection.execute("ALTER TABLE parties_new RENAME TO parties")
        connection.execute("CREATE INDEX idx_parties_leader ON parties(leader_id, status, created_at)")
        connection.execute("CREATE INDEX idx_parties_status ON parties(status, confirmation_deadline)")
        connection.execute("PRAGMA foreign_keys = ON")

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
            ("item_effects_json", "TEXT NOT NULL DEFAULT '{}'"),
            ("intro_json", "TEXT NOT NULL DEFAULT '{}'"),
            ("selected_service", "TEXT"),
            ("realm_key", "TEXT NOT NULL DEFAULT 'mortal'"),
            ("realm_layer", "INTEGER NOT NULL DEFAULT 0"),
            ("cultivation", "INTEGER NOT NULL DEFAULT 0"),
            ("total_cultivation", "INTEGER NOT NULL DEFAULT 0"),
            ("foundation_quality", "INTEGER NOT NULL DEFAULT 0"),
            ("world_merit", "INTEGER NOT NULL DEFAULT 0"),
            ("arena_rating", "INTEGER NOT NULL DEFAULT 1000"),
            ("arena_wins", "INTEGER NOT NULL DEFAULT 0"),
            ("arena_losses", "INTEGER NOT NULL DEFAULT 0"),
            ("arena_draws", "INTEGER NOT NULL DEFAULT 0"),
            ("talent_points", "INTEGER NOT NULL DEFAULT 0"),
            ("skill_insights", "INTEGER NOT NULL DEFAULT 0"),
            ("weakness_until", "TEXT"),
            ("battle_defeat_until", "TEXT"),
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
            ("sect_join_cooldown_until", "TEXT"),
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
    def _migrate_economy_ledger_asset_kind(connection: sqlite3.Connection) -> None:
        """Allow resource locks in the economy ledger on pre-market databases."""

        table = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'economy_ledger_entries'"
        ).fetchone()
        schema_sql = str(table[0]) if table and table[0] else ""
        if "'resource'" in schema_sql:
            return
        connection.execute("ALTER TABLE economy_ledger_entries RENAME TO economy_ledger_entries_legacy")
        connection.execute(
            """
            CREATE TABLE economy_ledger_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                operation_id TEXT NOT NULL,
                player_id INTEGER NOT NULL REFERENCES players(id),
                asset_kind TEXT NOT NULL CHECK (asset_kind IN ('currency', 'item', 'resource')),
                asset_key TEXT NOT NULL,
                reason TEXT NOT NULL,
                direction TEXT NOT NULL CHECK (direction IN ('credit', 'debit', 'lock', 'release')),
                amount INTEGER NOT NULL CHECK (amount >= 0),
                before_value INTEGER NOT NULL CHECK (before_value >= 0),
                after_value INTEGER NOT NULL CHECK (after_value >= 0),
                source_id TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO economy_ledger_entries(
                id, operation_id, player_id, asset_kind, asset_key, reason, direction,
                amount, before_value, after_value, source_id, created_at
            )
            SELECT id, operation_id, player_id, asset_kind, asset_key, reason, direction,
                   amount, before_value, after_value, source_id, created_at
            FROM economy_ledger_entries_legacy
            """
        )
        connection.execute("DROP TABLE economy_ledger_entries_legacy")
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_economy_ledger_operation ON economy_ledger_entries(operation_id)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_economy_ledger_player ON economy_ledger_entries(player_id, created_at)"
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

# Routine replay helpers historically referenced the concrete class by name.
# Bind it after composition so the mixin stays independent of this module.
from ..routine import repository as _routine_repository
from ..exploration import repository as _exploration_repository
from ..adventures import repository as _adventures_repository
from ..production import repository as _production_repository
from ..advancement import repository as _advancement_repository
from ..progression import cultivation_repository as _cultivation_repository
from ..progression.breakthrough import repository as _breakthrough_repository
from ..player import repository as _player_repository
from ..world import travel_repository as _travel_repository

_player_repository.SQLitePlayerRepository = SQLitePlayerRepository
_travel_repository.SQLitePlayerRepository = SQLitePlayerRepository
_routine_repository.SQLitePlayerRepository = SQLitePlayerRepository
_exploration_repository.SQLitePlayerRepository = SQLitePlayerRepository
_adventures_repository.SQLitePlayerRepository = SQLitePlayerRepository
_production_repository.SQLitePlayerRepository = SQLitePlayerRepository
_advancement_repository.SQLitePlayerRepository = SQLitePlayerRepository
_cultivation_repository.SQLitePlayerRepository = SQLitePlayerRepository
_breakthrough_repository.SQLitePlayerRepository = SQLitePlayerRepository
from ..items import repository as _items_repository
_items_repository.SQLitePlayerRepository = SQLitePlayerRepository
