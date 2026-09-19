from __future__ import annotations

import json
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

import pytest

from xiuxian3.domain.operation import Operation, OperationStatus
from xiuxian3.infrastructure.backup import BackupIntegrityError, SQLiteBackupManager
from xiuxian3.infrastructure.paths import PathBoundaryError, RuntimePaths
from xiuxian3.infrastructure.sqlite import SQLiteDatabase, SQLiteUnitOfWork
from xiuxian3.infrastructure import sqlite as sqlite_module

pytestmark = pytest.mark.integration


class SQLiteBackupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.paths = RuntimePaths.from_root(self.root)
        self.paths.ensure_layout()
        self.database = SQLiteDatabase(self.paths.resolve("game.sqlite3"))
        self.manager = SQLiteBackupManager(self.database, self.paths)

    def tearDown(self) -> None:
        self.directory.cleanup()

    def _write_operation(self, operation_id: str) -> None:
        operation = Operation(
            operation_id,
            "test.write",
            "actor",
            "target",
            operation_id,
            "rules-1",
        )
        started_at = datetime(2026, 1, 1, tzinfo=UTC)
        ended_at = datetime(2026, 1, 1, 0, 0, 1, tzinfo=UTC)
        with SQLiteUnitOfWork(self.database) as unit:
            claim = unit.operations.claim(operation, started_at)
            unit.operations.complete(
                claim.record.__class__(
                    operation=claim.record.operation,
                    status=OperationStatus.APPLIED,
                    started_at=claim.record.started_at,
                    ended_at=ended_at,
                    result_digest=f"result-{operation_id}",
                )
            )

    def test_backup_records_checksum_and_restore_leaves_pre_restore_snapshot(self) -> None:
        self._write_operation("before")
        artifact = self.manager.create_backup("baseline")

        metadata = json.loads(artifact.metadata_path.read_text(encoding="utf-8"))
        self.assertEqual(metadata["backup_id"], "baseline")
        self.assertEqual(metadata["sha256"], artifact.sha256)
        expected_schema_version = max(
            migration.version for migration in sqlite_module._migration_set()
        )
        self.assertEqual(metadata["schema_version"], expected_schema_version)
        self.assertEqual(artifact.database_path.parent, self.paths.resolve("backups"))

        self._write_operation("after")
        restored = self.manager.restore("baseline")
        self.assertEqual(restored.backup_id, "baseline")

        with self.database.connect() as connection:
            ids = [row[0] for row in connection.execute(
                "SELECT operation_id FROM operation_ledger ORDER BY operation_id"
            )]
        self.assertEqual(ids, ["before"])
        snapshots = sorted(self.paths.resolve("backups").glob("pre-restore-*.sqlite3"))
        self.assertEqual(len(snapshots), 1)

    def test_tampered_backup_is_rejected_without_changing_current_database(self) -> None:
        self._write_operation("current")
        artifact = self.manager.create_backup("tamper")
        artifact.database_path.write_bytes(artifact.database_path.read_bytes() + b"tampered")

        with self.assertRaises(BackupIntegrityError):
            self.manager.restore("tamper")

        with self.database.connect() as connection:
            ids = [row[0] for row in connection.execute("SELECT operation_id FROM operation_ledger")]
        self.assertEqual(ids, ["current"])

    def test_tampered_schema_version_is_rejected_without_changing_current_database(self) -> None:
        self._write_operation("current")
        artifact = self.manager.create_backup("version-tamper")
        metadata = json.loads(artifact.metadata_path.read_text(encoding="utf-8"))
        metadata["schema_version"] = 999
        artifact.metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

        with self.assertRaises(BackupIntegrityError):
            self.manager.restore("version-tamper")

        with self.database.connect() as connection:
            ids = [row[0] for row in connection.execute("SELECT operation_id FROM operation_ledger")]
        self.assertEqual(ids, ["current"])

    def test_backup_identifier_cannot_escape_backup_directory(self) -> None:
        with self.assertRaises(PathBoundaryError):
            self.manager.restore("../outside")