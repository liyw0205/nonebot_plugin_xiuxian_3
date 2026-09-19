"""Local SQLite backup and restore with checksum and path boundaries."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from .paths import RuntimePaths
from .sqlite import SQLiteDatabase


class BackupError(RuntimeError):
    """Base class for backup and restore failures."""


class BackupIntegrityError(BackupError):
    """Raised when a backup file or metadata does not match its checksum."""


@dataclass(frozen=True, slots=True)
class BackupArtifact:
    backup_id: str
    database_path: Path
    metadata_path: Path
    sha256: str
    schema_version: int


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _backup_name(backup_id: str) -> str:
    return f"{backup_id}.sqlite3"


class SQLiteBackupManager:
    """Create and restore local snapshots inside the configured data root."""

    def __init__(self, database: SQLiteDatabase, paths: RuntimePaths) -> None:
        self.database = database
        self.paths = paths

    def create_backup(self, backup_id: str) -> BackupArtifact:
        destination = self.paths.resolve(Path("backups") / _backup_name(backup_id))
        metadata_path = self.paths.resolve(Path("backups") / f"{backup_id}.json")
        temporary = destination.with_name(f".{destination.name}.tmp")
        if temporary.exists():
            temporary.unlink()
        try:
            with self.database.connect() as source:
                source.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                with sqlite3.connect(temporary) as target:
                    source.backup(target)
            digest = _sha256(temporary)
            os.replace(temporary, destination)
            schema_version = self._schema_version(destination)
            metadata = {
                "backup_id": backup_id,
                "created_at": datetime.now(UTC).isoformat(),
                "database_filename": destination.name,
                "schema_version": schema_version,
                "sha256": digest,
            }
            metadata_path.write_text(json.dumps(metadata, sort_keys=True) + "\n", encoding="utf-8")
            return BackupArtifact(backup_id, destination, metadata_path, digest, schema_version)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise

    def restore(self, backup_id: str) -> BackupArtifact:
        source = self.paths.resolve(Path("backups") / _backup_name(backup_id))
        metadata_path = self.paths.resolve(Path("backups") / f"{backup_id}.json")
        metadata = self._read_metadata(metadata_path, backup_id)
        if _sha256(source) != metadata["sha256"]:
            raise BackupIntegrityError(f"backup checksum mismatch: {backup_id}")
        self._validate_database(source)
        if self._schema_version(source) != cast(int, metadata["schema_version"]):
            raise BackupIntegrityError(f"backup schema version mismatch: {backup_id}")

        current_snapshot = self._create_pre_restore_snapshot()
        temporary = self.database.path.with_name(f".{self.database.path.name}.restore.tmp")
        try:
            shutil.copyfile(source, temporary)
            self._validate_database(temporary)
            os.replace(temporary, self.database.path)
            return BackupArtifact(
                backup_id=backup_id,
                database_path=source,
                metadata_path=metadata_path,
                sha256=str(metadata["sha256"]),
                schema_version=cast(int, metadata["schema_version"]),
            )
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
        finally:
            # The snapshot is intentionally retained for manual recovery.
            del current_snapshot

    def _read_metadata(self, path: Path, backup_id: str) -> dict[str, object]:
        try:
            metadata = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError) as exc:
            raise BackupIntegrityError(f"invalid backup metadata: {backup_id}") from exc
        if not isinstance(metadata, dict) or metadata.get("backup_id") != backup_id:
            raise BackupIntegrityError(f"backup metadata identity mismatch: {backup_id}")
        if not isinstance(metadata.get("sha256"), str) or not isinstance(metadata.get("schema_version"), int):
            raise BackupIntegrityError(f"backup metadata fields are invalid: {backup_id}")
        return metadata

    def _schema_version(self, path: Path) -> int:
        with sqlite3.connect(path) as connection:
            row = connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
        if row is None or row[0] is None:
            raise BackupIntegrityError("database has no schema migration version")
        return int(row[0])

    def _validate_database(self, path: Path) -> None:
        with sqlite3.connect(path) as connection:
            result = connection.execute("PRAGMA integrity_check").fetchone()
            if result is None or result[0] != "ok":
                raise BackupIntegrityError(f"SQLite integrity check failed: {path.name}")
            self._schema_version(path)

    def _create_pre_restore_snapshot(self) -> Path:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        snapshot = self.paths.resolve(Path("backups") / f"pre-restore-{stamp}.sqlite3")
        temporary = snapshot.with_name(f".{snapshot.name}.tmp")
        with self.database.connect() as source:
            with sqlite3.connect(temporary) as target:
                source.backup(target)
        os.replace(temporary, snapshot)
        return snapshot