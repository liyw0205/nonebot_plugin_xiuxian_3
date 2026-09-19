"""Operation ledger port; implementations own transactional persistence."""

from typing import Protocol

from ..domain.operation import OperationRecord


class OperationStore(Protocol):
    def get(self, operation_id: str) -> OperationRecord | None:
        """Return the prior operation, if it exists."""

    def append(self, record: OperationRecord) -> None:
        """Append exactly one operation record or raise on a duplicate key."""