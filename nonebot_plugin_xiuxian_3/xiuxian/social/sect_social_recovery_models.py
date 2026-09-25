"""DTOs for cross-server social backup and restore operations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class SocialRecoveryArtifact:
    artifact_id: str
    artifact_key: str
    database_file: str
    sha256: str
    size_bytes: int
    schema_hash: str
    row_counts: dict[str, int]
    created_at: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "artifact_key": self.artifact_key,
            "database_file": self.database_file,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "schema_hash": self.schema_hash,
            "row_counts": dict(self.row_counts),
            "created_at": self.created_at,
        }


@dataclass(frozen=True, slots=True)
class SocialRecoveryReport:
    request_id: str
    operation_id: str
    status: str
    artifact: SocialRecoveryArtifact | None
    pre_restore_artifact: SocialRecoveryArtifact | None
    checks: dict[str, Any]
    elapsed_ms: int
    failure_reason: str = ""
    idempotent_replay: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "operation_id": self.operation_id,
            "status": self.status,
            "artifact": self.artifact.as_dict() if self.artifact else None,
            "pre_restore_artifact": self.pre_restore_artifact.as_dict() if self.pre_restore_artifact else None,
            "checks": dict(self.checks),
            "elapsed_ms": self.elapsed_ms,
            "failure_reason": self.failure_reason,
            "idempotent_replay": self.idempotent_replay,
        }


__all__ = ["SocialRecoveryArtifact", "SocialRecoveryReport"]
