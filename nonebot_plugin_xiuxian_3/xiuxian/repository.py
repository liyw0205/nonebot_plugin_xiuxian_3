"""SQLite persistence for player identity and the first idempotent operation."""

from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from typing import Any
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


class SQLitePlayerRepository:
    """Short-transaction repository safe for concurrent asyncio requests.

    Each operation uses a thread-local SQLite connection through ``to_thread``.
    WAL allows readers to proceed while a writer commits, and the semaphore
    prevents an unbounded burst from creating more connections than useful.
    """

    def __init__(self, settings: XiuxianSettings):
        self.settings = settings
        self._initialized = False
        self._initialize_lock = asyncio.Lock()
        self._inflight = asyncio.Semaphore(settings.max_inflight)

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
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_players_dao_name "
                "ON players(dao_name) WHERE dao_name <> ''"
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
        now = datetime.now(timezone.utc)
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
            for table, status in (("production_orders", "processing"), ("breakthrough_sessions", "preparing"), ("travel_sessions", "running")):
                occupied = connection.execute(
                    f"SELECT 1 FROM {table} WHERE player_id = ? AND status = ? LIMIT 1",
                    (row["id"], status),
                ).fetchone()
                if occupied is not None:
                    raise CultivationBusyError("another action must be settled before moving")
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
            for table, status in (("cultivation_sessions", "running"), ("production_orders", "processing"), ("breakthrough_sessions", "preparing")):
                busy = connection.execute(
                    f"SELECT 1 FROM {table} WHERE player_id = ? AND status = ? LIMIT 1", (player_id, status)
                ).fetchone()
                if busy is not None:
                    raise TravelBusyError("another action is already running")

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
    ) -> ProductionPreviewRecord:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._preview_production_sync,
                platform,
                platform_user_id,
                recipe_key,
            )

    def _preview_production_sync(
        self,
        platform: str,
        platform_user_id: str,
        recipe_key: str,
    ) -> ProductionPreviewRecord:
        from .production.rules import recipe_definition

        recipe = recipe_definition(recipe_key)
        now = datetime.now(timezone.utc)
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
