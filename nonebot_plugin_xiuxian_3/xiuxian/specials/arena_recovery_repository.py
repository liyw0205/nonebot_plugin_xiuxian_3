"""Arena backup, restore and consistency-drill transactions.

The recovery boundary is intentionally separate from match repositories.  It
uses SQLite's online backup API, keeps artifacts below the configured data
root, and never activates a restored file until integrity and arena-reference
checks have passed.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import sqlite3
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any
from uuid import uuid4

from ...contracts import serialize_datetime


RECOVERY_RULE_VERSION = "arena-recovery-0.1.0"
RECOVERY_CONTENT_VERSION = "content-0.6"
_ARTIFACT_KEY = re.compile(r"^[a-z0-9-]{1,48}$")
_ARENA_TABLES = (
    "arena_matches",
    "arena_team_matches",
    "arena_actions",
    "arena_team_actions",
    "arena_projection_events",
    "arena_identity_routes",
    "arena_season_snapshots",
    "arena_audit_events",
    "arena_recovery_events",
)


@dataclass(frozen=True, slots=True)
class ArenaRecoveryArtifact:
    artifact_id: str
    artifact_key: str
    database_file: str
    sha256: str
    size_bytes: int
    schema_hash: str
    row_counts: dict[str, int]
    content_versions: tuple[str, ...]
    rule_versions: tuple[str, ...]
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
            "content_versions": list(self.content_versions),
            "rule_versions": list(self.rule_versions),
            "created_at": self.created_at,
        }


@dataclass(frozen=True, slots=True)
class ArenaRecoveryReport:
    request_id: str
    operation_id: str
    status: str
    artifact: ArenaRecoveryArtifact | None
    pre_restore_artifact: ArenaRecoveryArtifact | None
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


class ArenaRecoveryRepositoryMixin:
    """Own logical backup artifacts and recovery drills for arena data."""

    async def create_arena_recovery_backup(
        self, *, artifact_key: str, request_id: str, operation_id: str
    ) -> ArenaRecoveryArtifact:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._retry_sync,
                self._create_arena_recovery_backup_once,
                artifact_key,
                request_id,
                operation_id,
            )

    async def verify_arena_recovery_backup(
        self, *, artifact_key: str
    ) -> ArenaRecoveryArtifact:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._verify_arena_recovery_backup_once, artifact_key
            )

    async def restore_arena_recovery_backup(
        self,
        *,
        artifact_key: str,
        request_id: str,
        operation_id: str,
        fail_after_snapshot: bool = False,
    ) -> ArenaRecoveryReport:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._retry_sync,
                self._restore_arena_recovery_backup_once,
                artifact_key,
                request_id,
                operation_id,
                fail_after_snapshot,
            )

    def _backup_root(self) -> Path:
        root = (self.settings.data_dir / "backups").resolve()
        root.mkdir(parents=True, exist_ok=True)
        return root

    @staticmethod
    def _validate_artifact_key(artifact_key: str) -> str:
        key = str(artifact_key).strip()
        if not _ARTIFACT_KEY.fullmatch(key):
            raise ValueError("arena recovery artifact key is invalid")
        return key

    def _artifact_paths(self, artifact_key: str) -> tuple[str, Path, Path]:
        key = self._validate_artifact_key(artifact_key)
        root = self._backup_root()
        database_path = root / f"{key}.sqlite3"
        manifest_path = root / f"{key}.json"
        for path in (database_path, manifest_path):
            if path.is_symlink() or path.resolve().parent != root:
                raise ValueError("arena recovery artifact path is not allowed")
        return key, database_path, manifest_path

    def _create_arena_recovery_backup_once(
        self, artifact_key: str, request_id: str, operation_id: str
    ) -> ArenaRecoveryArtifact:
        key, database_path, manifest_path = self._artifact_paths(artifact_key)
        started = time.perf_counter()
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT result_json FROM arena_recovery_events WHERE event_key = 'arena.backup.created' AND operation_id = ?",
                (operation_id,),
            ).fetchone()
        if existing is not None:
            payload = self._json_map(existing[0])
            return self._artifact_from_dict(payload["artifact"])
        if manifest_path.exists() or database_path.exists():
            raise ValueError("arena recovery artifact key already exists")

        temporary_path = database_path.with_name(f".{database_path.name}.{uuid4().hex}.tmp")
        try:
            with self._connect() as source, sqlite3.connect(temporary_path) as target:
                source.backup(target)
            artifact = self._inspect_arena_artifact(
                key, temporary_path, created_at=serialize_datetime(self._now())
            )
            artifact = replace(artifact, database_file=database_path.name)
            os.replace(temporary_path, database_path)
            manifest_path.write_text(
                json.dumps(artifact.as_dict(), ensure_ascii=False, sort_keys=True, indent=2),
                encoding="utf-8",
            )
            elapsed_ms = max(0, int((time.perf_counter() - started) * 1000))
            with self._connect() as connection:
                self._record_recovery_event(
                    connection,
                    event_key="arena.backup.created",
                    request_id=request_id,
                    operation_id=operation_id,
                    artifact_id=artifact.artifact_id,
                    status="active",
                    result={"artifact": artifact.as_dict()},
                    elapsed_ms=elapsed_ms,
                )
            return artifact
        except Exception:
            temporary_path.unlink(missing_ok=True)
            database_path.unlink(missing_ok=True)
            manifest_path.unlink(missing_ok=True)
            raise

    def _verify_arena_recovery_backup_once(self, artifact_key: str) -> ArenaRecoveryArtifact:
        key, database_path, manifest_path = self._artifact_paths(artifact_key)
        if not manifest_path.is_file() or not database_path.is_file():
            raise FileNotFoundError("arena recovery artifact does not exist")
        try:
            metadata = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("arena recovery manifest is invalid") from exc
        artifact = self._artifact_from_dict(metadata)
        if artifact.artifact_key != key or artifact.database_file != database_path.name:
            raise ValueError("arena recovery manifest target mismatch")
        inspected = self._inspect_arena_artifact(key, database_path, created_at=artifact.created_at)
        if inspected.sha256 != artifact.sha256 or inspected.schema_hash != artifact.schema_hash:
            raise ValueError("arena recovery checksum or schema mismatch")
        if inspected.row_counts != artifact.row_counts:
            raise ValueError("arena recovery row count mismatch")
        return artifact

    def _restore_arena_recovery_backup_once(
        self,
        artifact_key: str,
        request_id: str,
        operation_id: str,
        fail_after_snapshot: bool,
    ) -> ArenaRecoveryReport:
        started = time.perf_counter()
        artifact: ArenaRecoveryArtifact | None = None
        pre_restore: ArenaRecoveryArtifact | None = None
        try:
            with self._connect() as connection:
                completed = connection.execute(
                    "SELECT result_json FROM arena_recovery_events WHERE event_key = 'arena.restore.completed' AND operation_id = ?",
                    (operation_id,),
                ).fetchone()
                self._record_recovery_event(
                    connection,
                    event_key="arena.restore.requested",
                    request_id=request_id,
                    operation_id=operation_id,
                    artifact_id=f"arena.backup:{artifact_key}",
                    status="requested",
                    result={},
                )
            if completed is not None:
                payload = self._json_map(completed[0])
                return ArenaRecoveryReport(
                    request_id=request_id,
                    operation_id=operation_id,
                    status="active",
                    artifact=self._artifact_from_dict(payload["artifact"]),
                    pre_restore_artifact=self._artifact_from_dict(payload["pre_restore_artifact"]),
                    checks=dict(payload.get("checks", {})),
                    elapsed_ms=int(payload.get("elapsed_ms", 0)),
                    idempotent_replay=True,
                )
            artifact = self._verify_arena_recovery_backup_once(artifact_key)
            with self._connect() as connection:
                self._record_recovery_event(
                    connection,
                    event_key="arena.restore.verified",
                    request_id=request_id,
                    operation_id=operation_id,
                    artifact_id=artifact.artifact_id,
                    status="verified",
                    result={"artifact": artifact.as_dict()},
                )
            pre_key = f"pre-restore-{hashlib.sha256(operation_id.encode('utf-8')).hexdigest()[:24]}"
            pre_restore = self._create_arena_recovery_backup_once(
                pre_key, request_id, f"{operation_id}:pre-restore"
            )
            with self._connect() as connection:
                self._record_recovery_event(
                    connection,
                    event_key="arena.restore.snapshot_created",
                    request_id=request_id,
                    operation_id=operation_id,
                    artifact_id=artifact.artifact_id,
                    status="snapshot_created",
                    result={"pre_restore_artifact": pre_restore.as_dict()},
                )

            database_path = self.settings.database_path
            temporary_path = database_path.with_name(f".{database_path.name}.{uuid4().hex}.restore")
            try:
                with sqlite3.connect(Path(self._artifact_paths(artifact_key)[1])) as source, sqlite3.connect(temporary_path) as target:
                    source.backup(target)
                with self._connect() as connection:
                    self._record_recovery_event(
                        connection,
                        event_key="arena.restore.restoring",
                        request_id=request_id,
                        operation_id=operation_id,
                        artifact_id=artifact.artifact_id,
                        status="restoring",
                        result={"artifact": artifact.as_dict()},
                    )
                checks = self._inspect_arena_database(temporary_path)
                with self._connect() as connection:
                    self._record_recovery_event(
                        connection,
                        event_key="arena.restore.integrity_checked",
                        request_id=request_id,
                        operation_id=operation_id,
                        artifact_id=artifact.artifact_id,
                        status="integrity_checked",
                        result={"checks": checks},
                    )
                if fail_after_snapshot:
                    raise RuntimeError("recovery drill injected failure")
                for suffix in ("-wal", "-shm"):
                    database_path.with_name(database_path.name + suffix).unlink(missing_ok=True)
                os.replace(temporary_path, database_path)
                checks = self._inspect_arena_database(database_path)
            finally:
                temporary_path.unlink(missing_ok=True)
            elapsed_ms = max(0, int((time.perf_counter() - started) * 1000))
            with self._connect() as connection:
                for event_key, status, result in (
                    ("arena.restore.requested", "requested", {}),
                    ("arena.restore.verified", "verified", {"artifact": artifact.as_dict()}),
                    ("arena.restore.snapshot_created", "snapshot_created", {"pre_restore_artifact": pre_restore.as_dict()}),
                    ("arena.restore.restoring", "restoring", {"artifact": artifact.as_dict()}),
                    ("arena.restore.integrity_checked", "integrity_checked", {"checks": checks}),
                ):
                    self._record_recovery_event(
                        connection,
                        event_key=event_key,
                        request_id=request_id,
                        operation_id=operation_id,
                        artifact_id=artifact.artifact_id,
                        status=status,
                        result=result,
                    )
                self._record_recovery_event(
                    connection,
                    event_key="arena.restore.completed",
                    request_id=request_id,
                    operation_id=operation_id,
                    artifact_id=artifact.artifact_id,
                    status="active",
                    result={
                        "artifact": artifact.as_dict(),
                        "pre_restore_artifact": pre_restore.as_dict(),
                        "checks": checks,
                        "elapsed_ms": elapsed_ms,
                    },
                    elapsed_ms=elapsed_ms,
                )
            return ArenaRecoveryReport(
                request_id=request_id,
                operation_id=operation_id,
                status="active",
                artifact=artifact,
                pre_restore_artifact=pre_restore,
                checks=checks,
                elapsed_ms=elapsed_ms,
            )
        except Exception as exc:
            elapsed_ms = max(0, int((time.perf_counter() - started) * 1000))
            with self._connect() as connection:
                self._record_recovery_event(
                    connection,
                    event_key="arena.restore.failed",
                    request_id=request_id,
                    operation_id=operation_id,
                    artifact_id=f"arena.backup:{artifact_key}",
                    status="failed",
                    failure_reason=str(exc),
                    result={"error_type": type(exc).__name__},
                    elapsed_ms=elapsed_ms,
                )
            return ArenaRecoveryReport(
                request_id=request_id,
                operation_id=operation_id,
                status="failed",
                artifact=artifact,
                pre_restore_artifact=pre_restore,
                checks={},
                elapsed_ms=elapsed_ms,
                failure_reason=str(exc),
            )

    def _inspect_arena_artifact(
        self, artifact_key: str, path: Path, *, created_at: str
    ) -> ArenaRecoveryArtifact:
        checks = self._inspect_arena_database(path)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        schema_hash = str(checks.pop("schema_hash"))
        row_counts = {key: int(value) for key, value in checks.pop("row_counts").items()}
        versions = self._read_versions(path)
        return ArenaRecoveryArtifact(
            artifact_id=f"arena.backup:{artifact_key}",
            artifact_key=artifact_key,
            database_file=path.name,
            sha256=digest,
            size_bytes=path.stat().st_size,
            schema_hash=schema_hash,
            row_counts=row_counts,
            content_versions=versions[0],
            rule_versions=versions[1],
            created_at=created_at,
        )

    @staticmethod
    def _inspect_arena_database(path: Path) -> dict[str, Any]:
        with sqlite3.connect(path) as connection:
            integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
            if integrity != "ok":
                raise ValueError(f"sqlite integrity check failed: {integrity}")
            foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
            if foreign_keys:
                raise ValueError("sqlite foreign key check failed")
            tables = {
                str(row[0]): str(row[1] or "")
                for row in connection.execute(
                    "SELECT name, sql FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
                )
            }
            missing = [name for name in _ARENA_TABLES if name not in tables]
            if missing:
                raise ValueError(f"arena recovery tables missing: {', '.join(missing)}")
            schema_hash = hashlib.sha256(
                json.dumps(tables, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            row_counts = {
                name: int(connection.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0])
                for name in _ARENA_TABLES
            }
            projections = connection.execute(
                "SELECT match_id, player_id, operation_id, mode_key, payload_json FROM arena_projection_events"
            ).fetchall()
            for match_id, player_id, operation_id, mode_key, payload_json in projections:
                match_exists = connection.execute(
                    "SELECT 1 FROM arena_matches WHERE match_id = ? UNION ALL SELECT 1 FROM arena_team_matches WHERE match_id = ? LIMIT 1",
                    (match_id, match_id),
                ).fetchone()
                if match_exists is None:
                    raise ValueError(f"arena projection references missing match: {match_id}")
                payload = json.loads(payload_json)
                for field in ("operation_id", "match_id", "player_id", "mode_key", "content_version", "rule_version", "result"):
                    if field not in payload:
                        raise ValueError(f"arena projection payload missing {field}: {operation_id}")
                if int(payload["player_id"]) != int(player_id) or str(payload["mode_key"]) != str(mode_key):
                    raise ValueError(f"arena projection payload identity mismatch: {operation_id}")
                if connection.execute(
                    "SELECT 1 FROM arena_audit_events WHERE match_id = ? AND operation_id = ? AND player_id = ? LIMIT 1",
                    (match_id, operation_id, player_id),
                ).fetchone() is None:
                    raise ValueError(f"arena projection is missing settlement audit: {operation_id}")
            for table in ("arena_matches", "arena_team_matches"):
                for match_id, status in connection.execute(f"SELECT match_id, status FROM {table}"):
                    if str(status) == "settled" and connection.execute(
                        "SELECT 1 FROM arena_projection_events WHERE match_id = ? LIMIT 1", (match_id,)
                    ).fetchone() is None:
                        raise ValueError(f"settled arena match is missing projection: {match_id}")
            for match_id, operation_id, player_id, payload_json in connection.execute(
                "SELECT match_id, operation_id, player_id, payload_json FROM arena_audit_events"
            ):
                payload = json.loads(payload_json)
                for field in ("request_id", "operation_id", "match_id", "player_id", "mode_key", "content_version", "rule_version", "result"):
                    if field not in payload:
                        raise ValueError(f"arena audit payload missing {field}: {operation_id}")
                if str(payload["match_id"]) != str(match_id) or int(payload["player_id"]) != int(player_id):
                    raise ValueError(f"arena audit payload identity mismatch: {operation_id}")
            for table, key in (("arena_identity_routes", "player_id"), ("arena_season_snapshots", "player_id"), ("arena_audit_events", "player_id")):
                missing_players = connection.execute(
                    f"SELECT COUNT(*) FROM {table} t LEFT JOIN players p ON p.id = t.{key} WHERE p.id IS NULL"
                ).fetchone()[0]
                if int(missing_players):
                    raise ValueError(f"{table} references missing player")
            return {"integrity_check": integrity, "foreign_key_check": "ok", "schema_hash": schema_hash, "row_counts": row_counts}

    @staticmethod
    def _read_versions(path: Path) -> tuple[tuple[str, ...], tuple[str, ...]]:
        with sqlite3.connect(path) as connection:
            content = {
                str(row[0])
                for table, column in (("arena_matches", "snapshot_json"), ("arena_team_matches", "snapshot_json"))
                for row in connection.execute(f"SELECT json_extract({column}, '$.content_version') FROM {table}")
                if row[0]
            }
            rules = {
                str(row[0])
                for table in ("arena_matches", "arena_team_matches")
                for row in connection.execute(f"SELECT json_extract(snapshot_json, '$.rule_version') FROM {table}")
                if row[0]
            }
        return tuple(sorted(content)), tuple(sorted(rules))

    @staticmethod
    def _artifact_from_dict(payload: dict[str, Any]) -> ArenaRecoveryArtifact:
        return ArenaRecoveryArtifact(
            artifact_id=str(payload["artifact_id"]),
            artifact_key=str(payload["artifact_key"]),
            database_file=str(payload["database_file"]),
            sha256=str(payload["sha256"]),
            size_bytes=int(payload["size_bytes"]),
            schema_hash=str(payload["schema_hash"]),
            row_counts={str(key): int(value) for key, value in dict(payload["row_counts"]).items()},
            content_versions=tuple(str(value) for value in payload.get("content_versions", [])),
            rule_versions=tuple(str(value) for value in payload.get("rule_versions", [])),
            created_at=str(payload["created_at"]),
        )

    @staticmethod
    def _json_map(raw: Any) -> dict[str, Any]:
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except json.JSONDecodeError:
                return {}
        return dict(raw) if isinstance(raw, dict) else {}

    def _record_recovery_event(
        self,
        connection: sqlite3.Connection,
        *,
        event_key: str,
        request_id: str,
        operation_id: str,
        artifact_id: str,
        status: str,
        result: dict[str, Any],
        elapsed_ms: int = 0,
        failure_reason: str = "",
        created_at: str | None = None,
    ) -> None:
        connection.execute(
            """
            INSERT OR IGNORE INTO arena_recovery_events(
                event_key, request_id, operation_id, artifact_id, mode_key,
                content_version, rule_version, status, result_json,
                failure_reason, elapsed_ms, created_at
            ) VALUES (?, ?, ?, ?, 'arena.federation', ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_key,
                request_id,
                operation_id,
                artifact_id,
                RECOVERY_CONTENT_VERSION,
                RECOVERY_RULE_VERSION,
                status,
                json.dumps(result, ensure_ascii=False, sort_keys=True),
                failure_reason,
                max(0, int(elapsed_ms)),
                created_at or serialize_datetime(self._now()),
            ),
        )


__all__ = [
    "ArenaRecoveryArtifact",
    "ArenaRecoveryReport",
    "ArenaRecoveryRepositoryMixin",
    "RECOVERY_CONTENT_VERSION",
    "RECOVERY_RULE_VERSION",
]
