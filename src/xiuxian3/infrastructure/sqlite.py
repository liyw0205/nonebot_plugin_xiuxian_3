"""SQLite persistence boundary for transactions and operation idempotency."""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path
from collections.abc import Mapping
from types import TracebackType
from typing import Self

from ..domain.operation import Operation, OperationConflictError, OperationRecord, OperationStatus
from ..domain.player import Player, PlayerStatus


class SQLitePersistenceError(RuntimeError):
    """Base class for persistence failures."""


class MigrationError(SQLitePersistenceError):
    """Raised when migrations are missing, invalid or changed after applying."""


class OperationStateError(SQLitePersistenceError):
    """Raised when a ledger record cannot be moved to the requested state."""


@dataclass(frozen=True, slots=True)
class OperationClaim:
    record: OperationRecord
    replay: bool


@dataclass(frozen=True, slots=True)
class _Migration:
    version: int
    name: str
    sql: str
    checksum: str


def _migration_set() -> tuple[_Migration, ...]:
    migration_dir = files("xiuxian3").joinpath("migrations")
    migrations: list[_Migration] = []
    for resource in sorted(migration_dir.iterdir(), key=lambda item: item.name):
        resource_name = resource.name
        if not resource_name.endswith(".sql"):
            continue
        stem = resource_name[:-4]
        prefix, separator, name = stem.partition("_")
        if not separator or not prefix.isdigit():
            raise MigrationError(f"invalid migration filename: {resource_name}")
        sql = resource.read_text(encoding="utf-8")
        migrations.append(
            _Migration(
                version=int(prefix),
                name=name,
                sql=sql,
                checksum=hashlib.sha256(sql.encode("utf-8")).hexdigest(),
            )
        )
    versions = [migration.version for migration in migrations]
    if len(versions) != len(set(versions)) or versions != sorted(versions):
        raise MigrationError("migration versions must be unique and ordered")
    return tuple(migrations)


def _datetime_text(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("operation timestamps must be timezone-aware")
    return value.isoformat()


def _datetime_value(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _status(value: str) -> OperationStatus:
    try:
        return OperationStatus(value)
    except ValueError as exc:
        raise SQLitePersistenceError(f"unknown operation status in database: {value}") from exc


def _record_from_row(row: sqlite3.Row) -> OperationRecord:
    operation = Operation(
        operation_id=row["operation_id"],
        request_type=row["request_type"],
        actor_id=row["actor_id"],
        target_id=row["target_id"],
        input_digest=row["input_digest"],
        rule_version=row["rule_version"],
    )
    return OperationRecord(
        operation=operation,
        status=_status(row["status"]),
        started_at=_datetime_value(row["started_at"]),
        ended_at=_datetime_value(row["ended_at"]) if row["ended_at"] is not None else None,
        result_digest=row["result_digest"],
        result_payload=row["result_payload"] if "result_payload" in row.keys() else None,
        error_code=row["error_code"],
    )


def _execute_script_atomically(connection: sqlite3.Connection, sql: str) -> None:
    """Execute trusted migration SQL without ``executescript`` implicit COMMIT."""

    statement = ""
    for line in sql.splitlines(keepends=True):
        statement += line
        if not sqlite3.complete_statement(statement):
            continue
        if statement.strip():
            connection.execute(statement)
        statement = ""
    if statement.strip():
        raise MigrationError("migration contains an incomplete SQL statement")


class SQLiteDatabase:
    """Open short-lived connections and apply versioned migrations."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def migrate(self) -> tuple[int, ...]:
        migrations = _migration_set()
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS schema_migrations (
                        version INTEGER PRIMARY KEY,
                        name TEXT NOT NULL,
                        checksum TEXT NOT NULL,
                        applied_at TEXT NOT NULL
                    )
                    """
                )
                applied_rows = connection.execute(
                    "SELECT version, name, checksum FROM schema_migrations ORDER BY version"
                ).fetchall()
                applied = {row["version"]: row for row in applied_rows}
                applied_versions = set(applied)
                expected_versions = {migration.version for migration in migrations}
                unknown_versions = applied_versions - expected_versions
                if unknown_versions:
                    raise MigrationError(
                        f"database contains unknown migration versions: {sorted(unknown_versions)}"
                    )
                for migration in migrations:
                    row = applied.get(migration.version)
                    if row is not None:
                        if row["name"] != migration.name or row["checksum"] != migration.checksum:
                            raise MigrationError(
                                f"migration {migration.version} changed after it was applied"
                            )
                        continue
                    _execute_script_atomically(connection, migration.sql)
                    connection.execute(
                        """
                        INSERT INTO schema_migrations(version, name, checksum, applied_at)
                        VALUES (?, ?, ?, ?)
                        """,
                        (migration.version, migration.name, migration.checksum, _datetime_text(datetime.now(UTC))),
                    )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return tuple(migration.version for migration in migrations if migration.version not in applied_versions)


class SQLiteOperationLedger:
    """Transactional operation ledger bound to one Unit of Work connection."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def get(self, operation_id: str) -> OperationRecord | None:
        row = self._connection.execute(
            "SELECT * FROM operation_ledger WHERE operation_id = ?",
            (operation_id,),
        ).fetchone()
        return _record_from_row(row) if row is not None else None

    def claim(self, operation: Operation, started_at: datetime) -> OperationClaim:
        existing = self.get(operation.operation_id)
        if existing is not None:
            if existing.operation != operation:
                raise OperationConflictError(
                    f"operation_id {operation.operation_id!r} was already used with different input"
                )
            return OperationClaim(existing, replay=True)
        record = OperationRecord(
            operation=operation,
            status=OperationStatus.ACCEPTED,
            started_at=started_at,
        )
        self._connection.execute(
            """
            INSERT INTO operation_ledger(
                operation_id, request_type, actor_id, target_id, input_digest,
                rule_version, status, started_at, ended_at, result_digest, result_payload, error_code
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                operation.operation_id,
                operation.request_type,
                operation.actor_id,
                operation.target_id,
                operation.input_digest,
                operation.rule_version,
                record.status.value,
                _datetime_text(record.started_at),
                None,
                None,
                None,
                None,
            ),
        )
        return OperationClaim(record, replay=False)

    def complete(self, record: OperationRecord) -> None:
        current = self.get(record.operation_id)
        if current is None:
            raise OperationStateError(f"operation does not exist: {record.operation_id}")
        if current.status is not OperationStatus.ACCEPTED:
            raise OperationStateError(
                f"terminal operation cannot transition from {current.status.value}"
            )
        if current.operation != record.operation:
            raise OperationConflictError(
                f"operation_id {record.operation_id!r} immutable fields changed"
            )
        if record.status is OperationStatus.ACCEPTED:
            raise OperationStateError("complete requires a terminal operation status")
        if record.ended_at is None and record.status in {
            OperationStatus.APPLIED,
            OperationStatus.REJECTED,
            OperationStatus.FAILED,
            OperationStatus.EXPIRED,
        }:
            raise OperationStateError("terminal operation records require ended_at")
        updated = self._connection.execute(
            """
            UPDATE operation_ledger
               SET status = ?, ended_at = ?, result_digest = ?, result_payload = ?, error_code = ?
             WHERE operation_id = ?
            """,
            (
                record.status.value,
                _datetime_text(record.ended_at) if record.ended_at is not None else None,
                record.result_digest,
                record.result_payload,
                record.error_code,
                record.operation_id,
            ),
        ).rowcount
        if updated != 1:
            raise OperationStateError(f"operation update failed: {record.operation_id}")


class SQLiteUnitOfWork:
    """A single explicit transaction for operation and domain writes."""

    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database
        self.connection: sqlite3.Connection | None = None
        self.operations: SQLiteOperationLedger | None = None
        self.players: SQLitePlayerRepository | None = None

    def __enter__(self) -> Self:
        self.database.migrate()
        self.connection = self.database.connect()
        try:
            self.connection.execute("BEGIN IMMEDIATE")
            self.operations = SQLiteOperationLedger(self.connection)
            self.players = SQLitePlayerRepository(self.connection)
        except Exception:
            self.connection.close()
            self.connection = None
            raise
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self.connection is None:
            return
        try:
            if exc_type is None:
                self.connection.commit()
            else:
                self.connection.rollback()
        finally:
            self.connection.close()
            self.connection = None
            self.operations = None
            self.players = None


def _player_from_row(row: sqlite3.Row) -> Player:
    return Player(
        player_id=row["player_id"],
        external_id=row["external_id"],
        nickname=row["nickname"],
        realm=row["realm"],
        level=int(row["level"]),
        cultivation=int(row["cultivation"]),
        spirit_stones=int(row["spirit_stones"]),
        stamina=int(row["stamina"]),
        status=PlayerStatus(row["status"]),
        platform=row["platform"] if "platform" in row.keys() else "legacy",
        platform_user_id=(
            row["platform_user_id"]
            if "platform_user_id" in row.keys() and row["platform_user_id"]
            else row["external_id"]
        ),
        scene=row["scene"] if "scene" in row.keys() else "unknown",
        stage=row["stage"] if "stage" in row.keys() else "mortal",
        location_key=(
            row["location_key"] if "location_key" in row.keys() else "xuantian.new_town"
        ),
        energy=int(row["energy"]) if "energy" in row.keys() else 0,
        inventory_json=row["inventory_json"] if "inventory_json" in row.keys() else "{}",
        qualification_snapshot_id=(
            row["qualification_snapshot_id"]
            if "qualification_snapshot_id" in row.keys()
            else None
        ),
        guide_state_json=row["guide_state_json"] if "guide_state_json" in row.keys() else "{}",
        realm_key=row["realm_key"] if "realm_key" in row.keys() else "mortal",
        realm_layer=int(row["realm_layer"]) if "realm_layer" in row.keys() else 0,
        path_key=row["path_key"] if "path_key" in row.keys() else None,
        subprofession_key=(
            row["subprofession_key"] if "subprofession_key" in row.keys() else None
        ),
        known_skills_json=(
            row["known_skills_json"] if "known_skills_json" in row.keys() else "[]"
        ),
    )


class SQLitePlayerRepository:
    """Player repository bound to the current unit-of-work transaction."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def get_by_external_id(self, external_id: str) -> Player | None:
        row = self._connection.execute(
            "SELECT * FROM players WHERE external_id = ?",
            (external_id,),
        ).fetchone()
        return _player_from_row(row) if row is not None else None

    def get_by_player_id(self, player_id: str) -> Player | None:
        row = self._connection.execute(
            "SELECT * FROM players WHERE player_id = ?",
            (player_id,),
        ).fetchone()
        return _player_from_row(row) if row is not None else None

    def get_by_platform_identity(self, platform: str, platform_user_id: str) -> Player | None:
        row = self._connection.execute(
            "SELECT * FROM players WHERE platform = ? AND platform_user_id = ?",
            (platform, platform_user_id),
        ).fetchone()
        return _player_from_row(row) if row is not None else None

    def add(self, player: Player) -> None:
        self._connection.execute(
            """
            INSERT INTO players(
                player_id, external_id, nickname, realm, level,
                cultivation, spirit_stones, stamina, status,
                platform, platform_user_id, scene, stage, location_key,
                energy, inventory_json, qualification_snapshot_id, guide_state_json,
                realm_key, realm_layer, path_key, subprofession_key, known_skills_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                player.player_id,
                player.external_id,
                player.nickname,
                player.realm,
                player.level,
                player.cultivation,
                player.spirit_stones,
                player.stamina,
                player.status.value,
                player.platform,
                player.platform_user_id,
                player.scene,
                player.stage,
                player.location_key,
                player.energy,
                player.inventory_json,
                player.qualification_snapshot_id,
                player.guide_state_json,
                player.realm_key,
                player.realm_layer,
                player.path_key,
                player.subprofession_key,
                player.known_skills_json,
            ),
        )

    def update(self, player: Player) -> None:
        self._connection.execute(
            """
            UPDATE players SET external_id = ?, nickname = ?, realm = ?, level = ?,
                cultivation = ?, spirit_stones = ?, stamina = ?, status = ?,
                platform = ?, platform_user_id = ?, scene = ?, stage = ?,
                location_key = ?, energy = ?, inventory_json = ?,
                qualification_snapshot_id = ?, guide_state_json = ?, realm_key = ?,
                realm_layer = ?, path_key = ?, subprofession_key = ?, known_skills_json = ?
            WHERE player_id = ?
            """,
            (
                player.external_id,
                player.nickname,
                player.realm,
                player.level,
                player.cultivation,
                player.spirit_stones,
                player.stamina,
                player.status.value,
                player.platform,
                player.platform_user_id,
                player.scene,
                player.stage,
                player.location_key,
                player.energy,
                player.inventory_json,
                player.qualification_snapshot_id,
                player.guide_state_json,
                player.realm_key,
                player.realm_layer,
                player.path_key,
                player.subprofession_key,
                player.known_skills_json,
                player.player_id,
            ),
        )

    def add_qualification_snapshot(self, snapshot: Mapping[str, object]) -> None:
        self._connection.execute(
            """
            INSERT INTO qualification_snapshots(
                snapshot_id, player_id, spirit_root, body, spirit, insight, root,
                agility, fortune, random_pool, result_digest, operation_id, rule_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot["snapshot_id"],
                snapshot["player_id"],
                snapshot["spirit_root"],
                snapshot["body"],
                snapshot["spirit"],
                snapshot["insight"],
                snapshot["root"],
                snapshot["agility"],
                snapshot["fortune"],
                snapshot["random_pool"],
                snapshot["result_digest"],
                snapshot["operation_id"],
                snapshot["rule_version"],
            ),
        )

    def get_qualification_snapshot(self, snapshot_id: str) -> sqlite3.Row | None:
        return self._connection.execute(
            "SELECT * FROM qualification_snapshots WHERE snapshot_id = ?",
            (snapshot_id,),
        ).fetchone()