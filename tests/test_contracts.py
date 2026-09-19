from __future__ import annotations

import unittest
from datetime import UTC, datetime

from xiuxian3.domain.operation import Operation, OperationRecord, OperationStatus
from xiuxian3.domain.result import Error, ErrorCode, Result
from xiuxian3.infrastructure.deterministic import FixedClock, SequenceIdGenerator, SequenceRandom
from xiuxian3.infrastructure.operation_store import DuplicateOperationError, InMemoryOperationStore


class ContractTests(unittest.TestCase):
    def test_result_contains_exactly_one_outcome(self) -> None:
        success = Result.success({"status": "ok"})
        empty_success = Result.success(None)
        failure = Result.failure(Error(ErrorCode.CONFLICT, "already processed"))
        self.assertTrue(success.ok)
        self.assertEqual(success.value, {"status": "ok"})
        self.assertTrue(empty_success.ok)
        self.assertIsNone(empty_success.value)
        self.assertFalse(failure.ok)
        self.assertEqual(failure.error.code, ErrorCode.CONFLICT)
        with self.assertRaises(ValueError):
            Result()

    def test_operation_store_rejects_duplicate_operation_id(self) -> None:
        operation = Operation("op-1", "test", "actor", "target", "digest", "rules-1")
        record = OperationRecord(
            operation=operation,
            status=OperationStatus.APPLIED,
            started_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        store = InMemoryOperationStore()
        store.append(record)
        self.assertIs(store.get("op-1"), record)
        with self.assertRaises(DuplicateOperationError):
            store.append(record)
        self.assertEqual(len(store), 1)

    def test_deterministic_ports_replay_values(self) -> None:
        instant = datetime(2026, 1, 1, tzinfo=UTC)
        self.assertEqual(FixedClock(instant).now(), instant)
        self.assertEqual(SequenceRandom([2]).randbelow(3), 2)
        self.assertEqual(SequenceIdGenerator(["fixed-id"]).new_id(), "fixed-id")