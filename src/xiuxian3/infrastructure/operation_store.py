"""Small in-memory operation ledger for P1 tests and local composition."""

from __future__ import annotations

from ..domain.operation import OperationRecord


class DuplicateOperationError(ValueError):
    """Raised when an operation ID is appended twice."""


class InMemoryOperationStore:
    def __init__(self) -> None:
        self._records: dict[str, OperationRecord] = {}

    def get(self, operation_id: str) -> OperationRecord | None:
        return self._records.get(operation_id)

    def append(self, record: OperationRecord) -> None:
        if record.operation_id in self._records:
            raise DuplicateOperationError(record.operation_id)
        self._records[record.operation_id] = record

    def __len__(self) -> int:
        return len(self._records)