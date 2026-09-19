"""Operation and idempotency contracts independent of storage."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class OperationConflictError(RuntimeError):
    """Raised when an operation ID is reused with different immutable input."""


class OperationStatus(str, Enum):
    ACCEPTED = "accepted"
    APPLIED = "applied"
    REJECTED = "rejected"
    FAILED = "failed"
    EXPIRED = "expired"


@dataclass(frozen=True, slots=True)
class Operation:
    operation_id: str
    request_type: str
    actor_id: str
    target_id: str
    input_digest: str
    rule_version: str


@dataclass(frozen=True, slots=True)
class OperationRecord:
    operation: Operation
    status: OperationStatus
    started_at: datetime
    ended_at: datetime | None = None
    result_digest: str | None = None
    result_payload: str | None = None
    error_code: str | None = None

    @property
    def operation_id(self) -> str:
        return self.operation.operation_id