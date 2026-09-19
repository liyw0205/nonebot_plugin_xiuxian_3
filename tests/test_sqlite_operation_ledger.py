from __future__ import annotations

import sqlite3
import tempfile
import unittest
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from xiuxian3.domain.operation import Operation, OperationStatus
from xiuxian3.infrastructure import sqlite as sqlite_module
from xiuxian3.infrastructure.sqlite import (
    MigrationError,
    OperationConflictError,
    OperationStateError,
    SQLiteDatabase,
    SQLiteUnitOfWork,
)

pytestmark = pytest.mark.integration


class SQLiteOperationLedgerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.database = SQLiteDatabase(Path(self.directory.name) / "game.sqlite3")

    def tearDown(self) -> None:
        self.directory.cleanup()

    def test_migrations_are_applied_once(self) -> None:
        expected_versions = tuple(migration.version for migration in sqlite_module._migration_set())
        self.assertEqual(self.database.migrate(), expected_versions)
        self.assertEqual(self.database.migrate(), ())
        with self.database.connect() as connection:
            version = connection.execute(
                "SELECT MAX(version) FROM schema_migrations"
            ).fetchone()[0]
            self.assertEqual(version, expected_versions[-1])
            self.assertIsNotNone(
                connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'operation_ledger'"
                ).fetchone()
            )

    def test_same_operation_replays_without_a_second_ledger_record(self) -> None:
        operation = Operation("op-1", "test.write", "actor", "target", "input-a", "rules-1")
        started_at = datetime(2026, 1, 1, tzinfo=UTC)
        applied_at = datetime(2026, 1, 1, 0, 0, 1, tzinfo=UTC)

        with SQLiteUnitOfWork(self.database) as unit:
            first = unit.operations.claim(operation, started_at)
            self.assertFalse(first.replay)
            unit.operations.complete(
                replace(
                    first.record,
                    status=OperationStatus.APPLIED,
                    ended_at=applied_at,
                    result_digest="result-a",
                )
            )

        with SQLiteUnitOfWork(self.database) as unit:
            second = unit.operations.claim(operation, started_at)
            self.assertTrue(second.replay)
            self.assertEqual(second.record.status, OperationStatus.APPLIED)
            self.assertEqual(second.record.result_digest, "result-a")

        with self.database.connect() as connection:
            count = connection.execute("SELECT COUNT(*) FROM operation_ledger").fetchone()[0]
            self.assertEqual(count, 1)

    def test_same_operation_id_with_different_input_is_a_conflict(self) -> None:
        original = Operation("op-2", "test.write", "actor", "target", "input-a", "rules-1")
        conflicting = replace(original, input_digest="input-b")
        with SQLiteUnitOfWork(self.database) as unit:
            unit.operations.claim(original, datetime(2026, 1, 1, tzinfo=UTC))

        with self.assertRaises(OperationConflictError):
            with SQLiteUnitOfWork(self.database) as unit:
                unit.operations.claim(conflicting, datetime(2026, 1, 1, tzinfo=UTC))

        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT input_digest FROM operation_ledger WHERE operation_id = ?",
                (original.operation_id,),
            ).fetchone()
            self.assertEqual(row[0], "input-a")

    def test_unit_of_work_rolls_back_domain_writes_on_exception(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "rollback probe"):
            with SQLiteUnitOfWork(self.database) as unit:
                unit.connection.execute("CREATE TABLE rollback_probe (value TEXT NOT NULL)")
                unit.connection.execute("INSERT INTO rollback_probe(value) VALUES (?)", ("x",))
                raise RuntimeError("rollback probe")

        with self.database.connect() as connection:
            with self.assertRaises(sqlite3.OperationalError):
                connection.execute("SELECT value FROM rollback_probe").fetchall()

    def test_failed_migration_rolls_back_schema_and_version_record(self) -> None:
        good = sqlite_module._Migration(
            version=1,
            name="good",
            sql="CREATE TABLE migration_probe (value TEXT NOT NULL);",
            checksum="good-checksum",
        )
        bad = sqlite_module._Migration(
            version=2,
            name="bad",
            sql="CREATE TABLE broken (",
            checksum="bad-checksum",
        )
        with patch.object(sqlite_module, "_migration_set", return_value=(good, bad)):
            with self.assertRaises((sqlite3.OperationalError, MigrationError)):
                self.database.migrate()

        with self.database.connect() as connection:
            self.assertIsNone(
                connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'migration_probe'"
                ).fetchone()
            )
            self.assertIsNone(
                connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'schema_migrations'"
                ).fetchone()
            )

    def test_terminal_operation_cannot_be_reopened(self) -> None:
        operation = Operation("op-3", "test.write", "actor", "target", "input-a", "rules-1")
        started_at = datetime(2026, 1, 1, tzinfo=UTC)
        ended_at = datetime(2026, 1, 1, 0, 0, 1, tzinfo=UTC)
        with SQLiteUnitOfWork(self.database) as unit:
            claim = unit.operations.claim(operation, started_at)
            unit.operations.complete(
                replace(claim.record, status=OperationStatus.APPLIED, ended_at=ended_at)
            )
            with self.assertRaises(OperationStateError):
                unit.operations.complete(
                    replace(claim.record, status=OperationStatus.ACCEPTED, ended_at=None)
                )