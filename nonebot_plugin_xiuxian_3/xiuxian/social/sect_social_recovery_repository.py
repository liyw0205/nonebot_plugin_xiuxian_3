"""Backup, restore and consistency drills for cross-server social data.

The recovery boundary is kept in the social domain instead of the general
repository facade.  Artifacts are namespace-scoped, restored through a
temporary SQLite file, and activated only after social references are checked.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sqlite3
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any
from uuid import uuid4

from ...contracts import serialize_datetime
from .sect_social_recovery_models import SocialRecoveryArtifact, SocialRecoveryReport
from .sect_social_recovery_rules import (
    SOCIAL_RECOVERY_ARTIFACT_ROOT,
    SOCIAL_RECOVERY_CONTENT_VERSION,
    SOCIAL_RECOVERY_RULE_VERSION,
    SOCIAL_RECOVERY_TABLES,
    validate_social_recovery_artifact_key,
)


class SectSocialRecoveryRepositoryMixin:
    """Own auditable social backup artifacts and recovery drills."""

    async def create_social_recovery_backup(
        self, *, artifact_key: str, request_id: str, operation_id: str
    ) -> SocialRecoveryArtifact:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._retry_sync,
                self._create_social_recovery_backup_once,
                artifact_key,
                request_id,
                operation_id,
            )

    async def verify_social_recovery_backup(self, *, artifact_key: str) -> SocialRecoveryArtifact:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(self._verify_social_recovery_backup_once, artifact_key)

    async def restore_social_recovery_backup(
        self,
        *,
        artifact_key: str,
        request_id: str,
        operation_id: str,
        fail_after_snapshot: bool = False,
    ) -> SocialRecoveryReport:
        await self.initialize()
        async with self._inflight:
            return await asyncio.to_thread(
                self._retry_sync,
                self._restore_social_recovery_backup_once,
                artifact_key,
                request_id,
                operation_id,
                fail_after_snapshot,
            )

    def _social_backup_root(self) -> Path:
        data_root = self.settings.data_dir.resolve()
        root = (data_root / SOCIAL_RECOVERY_ARTIFACT_ROOT).resolve()
        if not root.is_relative_to(data_root):
            raise ValueError("social recovery artifact root is not allowed")
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _social_artifact_paths(self, artifact_key: str) -> tuple[str, Path, Path]:
        key = validate_social_recovery_artifact_key(artifact_key)
        root = self._social_backup_root()
        database_path = root / f"{key}.sqlite3"
        manifest_path = root / f"{key}.json"
        for path in (database_path, manifest_path):
            if path.is_symlink() or path.resolve().parent != root:
                raise ValueError("social recovery artifact path is not allowed")
        return key, database_path, manifest_path

    def _create_social_recovery_backup_once(
        self, artifact_key: str, request_id: str, operation_id: str
    ) -> SocialRecoveryArtifact:
        key, database_path, manifest_path = self._social_artifact_paths(artifact_key)
        started = time.perf_counter()
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT result_json FROM social_recovery_events "
                "WHERE event_key='social.backup.created' AND operation_id=?",
                (operation_id,),
            ).fetchone()
        if existing is not None:
            return self._artifact_from_dict(self._json_map(existing[0])["artifact"])
        if database_path.exists() or manifest_path.exists():
            raise ValueError("social recovery artifact key already exists")

        temporary_path = database_path.with_name(f".{database_path.name}.{uuid4().hex}.tmp")
        try:
            with self._connect() as source, sqlite3.connect(temporary_path) as target:
                source.backup(target)
            artifact = self._inspect_social_artifact(
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
                self._record_social_recovery_event(
                    connection,
                    event_key="social.backup.created",
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

    def _verify_social_recovery_backup_once(self, artifact_key: str) -> SocialRecoveryArtifact:
        key, database_path, manifest_path = self._social_artifact_paths(artifact_key)
        if not manifest_path.is_file() or not database_path.is_file():
            raise FileNotFoundError("social recovery artifact does not exist")
        try:
            metadata = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("social recovery manifest is invalid") from exc
        artifact = self._artifact_from_dict(metadata)
        if artifact.artifact_key != key or artifact.database_file != database_path.name:
            raise ValueError("social recovery manifest target mismatch")
        inspected = self._inspect_social_artifact(key, database_path, created_at=artifact.created_at)
        if inspected.sha256 != artifact.sha256 or inspected.schema_hash != artifact.schema_hash:
            raise ValueError("social recovery checksum or schema mismatch")
        if inspected.row_counts != artifact.row_counts:
            raise ValueError("social recovery row count mismatch")
        return artifact

    def _restore_social_recovery_backup_once(
        self,
        artifact_key: str,
        request_id: str,
        operation_id: str,
        fail_after_snapshot: bool,
    ) -> SocialRecoveryReport:
        started = time.perf_counter()
        artifact: SocialRecoveryArtifact | None = None
        pre_restore: SocialRecoveryArtifact | None = None
        try:
            with self._connect() as connection:
                completed = connection.execute(
                    "SELECT result_json FROM social_recovery_events "
                    "WHERE event_key='social.restore.completed' AND operation_id=?",
                    (operation_id,),
                ).fetchone()
                self._record_social_recovery_event(
                    connection,
                    event_key="social.restore.requested",
                    request_id=request_id,
                    operation_id=operation_id,
                    artifact_id=f"social.backup:{artifact_key}",
                    status="requested",
                    result={},
                )
            if completed is not None:
                payload = self._json_map(completed[0])
                return SocialRecoveryReport(
                    request_id=request_id,
                    operation_id=operation_id,
                    status="active",
                    artifact=self._artifact_from_dict(payload["artifact"]),
                    pre_restore_artifact=self._artifact_from_dict(payload["pre_restore_artifact"]),
                    checks=dict(payload.get("checks", {})),
                    elapsed_ms=int(payload.get("elapsed_ms", 0)),
                    idempotent_replay=True,
                )

            artifact = self._verify_social_recovery_backup_once(artifact_key)
            with self._connect() as connection:
                self._record_social_recovery_event(
                    connection,
                    event_key="social.restore.verified",
                    request_id=request_id,
                    operation_id=operation_id,
                    artifact_id=artifact.artifact_id,
                    status="verified",
                    result={"artifact": artifact.as_dict()},
                )
            pre_key = f"pre-restore-{hashlib.sha256(operation_id.encode('utf-8')).hexdigest()[:24]}"
            pre_restore = self._create_social_recovery_backup_once(
                pre_key, request_id, f"{operation_id}:pre-restore"
            )
            with self._connect() as connection:
                self._record_social_recovery_event(
                    connection,
                    event_key="social.restore.snapshot_created",
                    request_id=request_id,
                    operation_id=operation_id,
                    artifact_id=artifact.artifact_id,
                    status="snapshot_created",
                    result={"pre_restore_artifact": pre_restore.as_dict()},
                )

            database_path = self.settings.database_path
            temporary_path = database_path.with_name(f".{database_path.name}.{uuid4().hex}.restore")
            try:
                source_path = self._social_artifact_paths(artifact_key)[1]
                with sqlite3.connect(source_path) as source, sqlite3.connect(temporary_path) as target:
                    source.backup(target)
                with self._connect() as connection:
                    self._record_social_recovery_event(
                        connection,
                        event_key="social.restore.restoring",
                        request_id=request_id,
                        operation_id=operation_id,
                        artifact_id=artifact.artifact_id,
                        status="restoring",
                        result={"artifact": artifact.as_dict()},
                    )
                checks = self._inspect_social_database(temporary_path)
                with self._connect() as connection:
                    self._record_social_recovery_event(
                        connection,
                        event_key="social.restore.integrity_checked",
                        request_id=request_id,
                        operation_id=operation_id,
                        artifact_id=artifact.artifact_id,
                        status="integrity_checked",
                        result={"checks": checks},
                    )
                if fail_after_snapshot:
                    raise RuntimeError("social recovery drill injected failure")
                for suffix in ("-wal", "-shm"):
                    database_path.with_name(database_path.name + suffix).unlink(missing_ok=True)
                os.replace(temporary_path, database_path)
                checks = self._inspect_social_database(database_path)
            finally:
                temporary_path.unlink(missing_ok=True)

            elapsed_ms = max(0, int((time.perf_counter() - started) * 1000))
            with self._connect() as connection:
                self._record_social_recovery_event(
                    connection,
                    event_key="social.restore.completed",
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
            return SocialRecoveryReport(
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
                self._record_social_recovery_event(
                    connection,
                    event_key="social.restore.failed",
                    request_id=request_id,
                    operation_id=operation_id,
                    artifact_id=f"social.backup:{artifact_key}",
                    status="failed",
                    failure_reason=str(exc),
                    result={"error_type": type(exc).__name__},
                    elapsed_ms=elapsed_ms,
                )
            return SocialRecoveryReport(
                request_id=request_id,
                operation_id=operation_id,
                status="failed",
                artifact=artifact,
                pre_restore_artifact=pre_restore,
                checks={},
                elapsed_ms=elapsed_ms,
                failure_reason=str(exc),
            )

    def _inspect_social_artifact(
        self, artifact_key: str, path: Path, *, created_at: str
    ) -> SocialRecoveryArtifact:
        checks = self._inspect_social_database(path)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        schema_hash = str(checks.pop("schema_hash"))
        row_counts = {key: int(value) for key, value in checks.pop("row_counts").items()}
        return SocialRecoveryArtifact(
            artifact_id=f"social.backup:{artifact_key}",
            artifact_key=artifact_key,
            database_file=path.name,
            sha256=digest,
            size_bytes=path.stat().st_size,
            schema_hash=schema_hash,
            row_counts=row_counts,
            created_at=created_at,
        )

    @staticmethod
    def _inspect_social_database(path: Path) -> dict[str, Any]:
        with sqlite3.connect(path) as connection:
            integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
            if integrity != "ok":
                raise ValueError(f"sqlite integrity check failed: {integrity}")
            if connection.execute("PRAGMA foreign_key_check").fetchall():
                raise ValueError("sqlite foreign key check failed")
            tables = {
                str(row[0]): str(row[1] or "")
                for row in connection.execute(
                    "SELECT name, sql FROM sqlite_master WHERE type='table' "
                    "AND name NOT LIKE 'sqlite_%' ORDER BY name"
                )
            }
            missing = [name for name in SOCIAL_RECOVERY_TABLES if name not in tables]
            if missing:
                raise ValueError(f"social recovery tables missing: {', '.join(missing)}")
            schema_hash = hashlib.sha256(
                json.dumps(tables, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            row_counts = {
                name: int(connection.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0])
                for name in SOCIAL_RECOVERY_TABLES
            }
            _check_social_references(connection)
            return {
                "integrity_check": integrity,
                "foreign_key_check": "ok",
                "social_reference_check": "ok",
                "schema_hash": schema_hash,
                "row_counts": row_counts,
            }

    @staticmethod
    def _artifact_from_dict(payload: dict[str, Any]) -> SocialRecoveryArtifact:
        return SocialRecoveryArtifact(
            artifact_id=str(payload["artifact_id"]),
            artifact_key=str(payload["artifact_key"]),
            database_file=str(payload["database_file"]),
            sha256=str(payload["sha256"]),
            size_bytes=int(payload["size_bytes"]),
            schema_hash=str(payload["schema_hash"]),
            row_counts={str(key): int(value) for key, value in dict(payload["row_counts"]).items()},
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

    def _record_social_recovery_event(
        self,
        connection: sqlite3.Connection,
        *,
        event_key: str,
        request_id: str,
        operation_id: str,
        artifact_id: str,
        status: str,
        result: dict[str, Any],
        failure_reason: str = "",
        elapsed_ms: int = 0,
    ) -> None:
        connection.execute(
            "INSERT OR IGNORE INTO social_recovery_events("
            "event_key,request_id,operation_id,artifact_id,content_version,rule_version,status,result_json,failure_reason,elapsed_ms,created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                event_key,
                request_id,
                operation_id,
                artifact_id,
                SOCIAL_RECOVERY_CONTENT_VERSION,
                SOCIAL_RECOVERY_RULE_VERSION,
                status,
                json.dumps(result, ensure_ascii=False, sort_keys=True),
                failure_reason,
                max(0, int(elapsed_ms)),
                serialize_datetime(self._now()),
            ),
        )


def _check_social_references(connection: sqlite3.Connection) -> None:
    """Validate JSON snapshots and cross-domain references before activation."""

    def player_exists(player_id: int) -> bool:
        return connection.execute("SELECT 1 FROM players WHERE id=?", (player_id,)).fetchone() is not None

    def sect_exists(sect_id: str) -> bool:
        return connection.execute("SELECT 1 FROM sects WHERE sect_id=?", (sect_id,)).fetchone() is not None

    def operation_exists(operation_id: str) -> bool:
        return connection.execute("SELECT 1 FROM operations WHERE operation_id=?", (operation_id,)).fetchone() is not None

    def json_object(raw: Any, label: str) -> dict[str, Any]:
        try:
            value = json.loads(raw or "{}")
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError(f"social recovery JSON is invalid: {label}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"social recovery JSON must be an object: {label}")
        return value

    def json_value(raw: Any, label: str) -> Any:
        try:
            return json.loads(raw or "null")
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError(f"social recovery JSON is invalid: {label}") from exc

    for table, column in (
        ("sect_war_federation_snapshots", "snapshot_json"),
        ("sect_war_federation_results", "result_json"),
        ("sect_cross_server_war_registrations", "snapshot_json"),
        ("sect_cross_server_war_members", "snapshot_json"),
        ("sect_cross_server_war_sessions", "snapshot_json"),
        ("sect_cross_server_war_sessions", "replay_json"),
        ("sect_cross_server_war_sessions", "result_json"),
        ("sect_cross_server_reward_boxes", "reward_json"),
        ("sect_cross_server_reward_boxes", "distributed_json"),
        ("sect_alliance_contracts", "snapshot_json"),
    ):
        for row in connection.execute(f"SELECT rowid, {column} FROM {table}"):
            json_value(row[1], f"{table}:{row[0]}:{column}")

    for row in connection.execute("SELECT snapshot_id, snapshot_json FROM sect_war_federation_snapshots"):
        payload = json_object(row[1], f"federation snapshot:{row[0]}")
        for member in payload.get("members", []):
            if not isinstance(member, dict) or not player_exists(int(member.get("player_id", 0))):
                raise ValueError(f"federation snapshot references missing player: {row[0]}")
        source_operation_id = str(payload.get("source_registration_operation_id", ""))
        if source_operation_id and not operation_exists(source_operation_id):
            raise ValueError(f"federation snapshot references missing operation: {row[0]}")

    for table, id_column, sect_column in (
        ("sect_war_federation_snapshots", "snapshot_id", "sect_id"),
        ("sect_war_federation_results", "result_id", "sect_id"),
        ("sect_cross_server_war_registrations", "id", "sect_id"),
        ("sect_cross_server_war_members", "id", "sect_id"),
        ("sect_cross_server_war_actions", "id", "sect_id"),
        ("sect_cross_server_war_sessions", "session_id", "sect_id"),
        ("sect_cross_server_reward_boxes", "box_id", "sect_id"),
    ):
        for row in connection.execute(f"SELECT {id_column}, {sect_column} FROM {table}"):
            if not sect_exists(str(row[1])):
                raise ValueError(f"{table} references missing sect: {row[0]}")

    for table, id_column in (
        ("sect_cross_server_war_members", "id"),
        ("sect_cross_server_war_actions", "id"),
        ("sect_cross_server_reward_allocations", "id"),
        ("sect_cross_server_weekly_rewards", "id"),
    ):
        for row in connection.execute(f"SELECT {id_column}, player_id FROM {table}"):
            if not player_exists(int(row[1])):
                raise ValueError(f"{table} references missing player: {row[0]}")

    for table, id_column, operation_column in (
        ("sect_cross_server_war_registrations", "id", "operation_id"),
        ("sect_cross_server_war_actions", "id", "operation_id"),
        ("sect_cross_server_reward_allocations", "id", "operation_id"),
        ("sect_alliance_research", "id", "operation_id"),
    ):
        for row in connection.execute(f"SELECT {id_column}, {operation_column} FROM {table}"):
            if not operation_exists(str(row[1])):
                raise ValueError(f"{table} references missing operation: {row[0]}")

    for table in ("sect_void_fortresses", "sect_void_beacons"):
        for row in connection.execute(f"SELECT sect_id, snapshot_json FROM {table}"):
            if not sect_exists(str(row[0])):
                raise ValueError(f"{table} references missing sect: {row[0]}")
            json_object(row[1], f"{table}:{row[0]}")
    for row in connection.execute("SELECT sect_id FROM sect_alliance_cooldowns"):
        if not sect_exists(str(row[0])):
            raise ValueError(f"sect_alliance_cooldowns references missing sect: {row[0]}")

    for row in connection.execute(
        "SELECT alliance_id, sect_a_id, sect_b_id, proposer_sect_id, proposer_player_id, snapshot_json "
        "FROM sect_alliance_contracts"
    ):
        if not sect_exists(str(row[1])) or not sect_exists(str(row[2])) or not sect_exists(str(row[3])):
            raise ValueError(f"alliance references missing sect: {row[0]}")
        if not player_exists(int(row[4])):
            raise ValueError(f"alliance references missing proposer: {row[0]}")
        json_object(row[5], f"alliance:{row[0]}")

    for row in connection.execute("SELECT id, source_sect_id, target_sect_id FROM sect_alliance_research"):
        if not sect_exists(str(row[1])) or not sect_exists(str(row[2])):
            raise ValueError(f"alliance research references missing sect: {row[0]}")

    for row in connection.execute("SELECT route_key, player_id, platform, platform_user_id FROM arena_identity_routes"):
        player = connection.execute(
            "SELECT platform, platform_user_id FROM players WHERE id=?", (row[1],)
        ).fetchone()
        if player is None or str(player[0]) != str(row[2]) or str(player[1]) != str(row[3]):
            raise ValueError(f"identity route references mismatched player: {row[0]}")

    for row in connection.execute("SELECT event_key, operation_id, match_id, player_id, payload_json FROM arena_audit_events"):
        payload = json_object(row[4], f"arena audit:{row[0]}:{row[1]}")
        for field in ("operation_id", "match_id", "player_id", "content_version", "rule_version", "result"):
            if field not in payload:
                raise ValueError(f"arena audit payload missing {field}: {row[1]}")
        if str(payload["operation_id"]) != str(row[1]) or str(payload["match_id"]) != str(row[2]) or int(payload["player_id"]) != int(row[3]):
            raise ValueError(f"arena audit payload identity mismatch: {row[1]}")
        if not operation_exists(str(row[1])):
            raise ValueError(f"arena audit references missing operation: {row[1]}")
        if connection.execute(
            "SELECT 1 FROM arena_matches WHERE match_id=? UNION ALL "
            "SELECT 1 FROM arena_team_matches WHERE match_id=? LIMIT 1", (row[2], row[2])
        ).fetchone() is None:
            raise ValueError(f"arena audit references missing match: {row[2]}")


__all__ = ["SectSocialRecoveryRepositoryMixin"]
