from __future__ import annotations

import asyncio
import json
import sqlite3
from dataclasses import replace
from datetime import datetime, timezone
from tempfile import TemporaryDirectory

import pytest

from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.specials.arena_federation import freeze_arena_season_snapshot

from test.test_arena import MutableClock, _adapter_contexts, _cultivator


def test_qq_onebot_arena_recovery_restores_federation_inputs_and_replays_operation() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 25, tzinfo=timezone.utc))
        qq, onebot = _adapter_contexts()
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            qq = replace(qq, user_id="recovery-qq")
            onebot = replace(onebot, user_id="recovery-onebot")
            await _cultivator(runtime, qq, "recovery-qq")
            await _cultivator(runtime, onebot, "recovery-onebot")
            published = await runtime.adapters.dispatch(
                onebot.adapter, replace(onebot, operation_id="recovery-publish"), "发布竞技场快照"
            )
            clock.advance(minutes=31)
            challenged = await runtime.adapters.dispatch(
                qq.adapter,
                replace(qq, operation_id="recovery-challenge", request_id="recovery-request"),
                f"挑战竞技场 {published.data['snapshot_id']}",
            )
            assert challenged.ok
            match_id = challenged.data["match_id"]
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.row_factory = sqlite3.Row
                assert freeze_arena_season_snapshot(
                    connection,
                    season_key="arena.recovery.1",
                    frozen_at="2026-09-25T00:31:00+00:00",
                ) == 2
            backup = await runtime.repository.create_arena_recovery_backup(
                artifact_key="arena-recovery",
                request_id="backup-request",
                operation_id="backup-operation",
            )
            assert backup.row_counts["arena_matches"] == 1
            assert backup.row_counts["arena_projection_events"] == 2
            assert backup.row_counts["arena_identity_routes"] == 2
            assert backup.row_counts["arena_season_snapshots"] == 2

            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute("UPDATE players SET arena_rating = 1")
                connection.commit()
            report = await runtime.repository.restore_arena_recovery_backup(
                artifact_key="arena-recovery",
                request_id="restore-request",
                operation_id="restore-operation",
            )
            assert report.status == "active"
            assert report.checks["integrity_check"] == "ok"
            assert report.checks["foreign_key_check"] == "ok"
            assert report.pre_restore_artifact is not None

            replay = await runtime.adapters.dispatch(
                qq.adapter,
                replace(qq, operation_id="recovery-challenge", request_id="recovery-request"),
                f"挑战竞技场 {published.data['snapshot_id']}",
            )
            assert replay.ok
            assert replay.data["idempotent_replay"] is True
            assert replay.data["match_id"] == match_id
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute("SELECT COUNT(*) FROM arena_projection_events").fetchone()[0] == 2
                assert connection.execute("SELECT COUNT(*) FROM arena_identity_routes").fetchone()[0] == 2
                assert connection.execute("SELECT COUNT(*) FROM arena_season_snapshots").fetchone()[0] == 2
                audit = connection.execute(
                    "SELECT payload_json FROM arena_audit_events WHERE match_id = ?", (match_id,)
                ).fetchone()[0]
                audit_payload = json.loads(audit)
                assert audit_payload["request_id"] == "recovery-request"
                assert audit_payload["operation_id"] == "recovery-challenge"
                assert audit_payload["match_id"] == match_id
                assert audit_payload["content_version"]
                assert audit_payload["rule_version"]
                recovery = connection.execute(
                    "SELECT request_id, operation_id, status, elapsed_ms FROM arena_recovery_events "
                    "WHERE event_key = 'arena.restore.completed'"
                ).fetchone()
                assert recovery[:3] == ("restore-request", "restore-operation", "active")
                assert recovery[3] >= 0
            await runtime.close()

    asyncio.run(run())


def test_arena_recovery_failure_keeps_live_database_and_records_pre_restore_snapshot() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            await runtime.initialize()
            await runtime.repository.create_arena_recovery_backup(
                artifact_key="failure-source",
                request_id="backup-request",
                operation_id="backup-operation",
            )
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute("UPDATE players SET arena_rating = arena_rating + 1")
                connection.commit()
            failed = await runtime.repository.restore_arena_recovery_backup(
                artifact_key="failure-source",
                request_id="failure-request",
                operation_id="failure-operation",
                fail_after_snapshot=True,
            )
            assert failed.status == "failed"
            assert "injected failure" in failed.failure_reason
            assert failed.pre_restore_artifact is not None
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute("SELECT COUNT(*) FROM arena_recovery_events WHERE status = 'failed'").fetchone()[0] == 1
            await runtime.close()

    asyncio.run(run())


def test_corrupt_arena_recovery_artifact_is_rejected_without_activation() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            await runtime.initialize()
            artifact = await runtime.repository.create_arena_recovery_backup(
                artifact_key="corrupt-source",
                request_id="backup-request",
                operation_id="backup-operation",
            )
            path = runtime.settings.data_dir / "backups" / artifact.database_file
            path.write_bytes(path.read_bytes() + b"corrupt")
            with pytest.raises(ValueError, match="checksum"):
                await runtime.repository.verify_arena_recovery_backup(artifact_key="corrupt-source")
            report = await runtime.repository.restore_arena_recovery_backup(
                artifact_key="corrupt-source",
                request_id="corrupt-request",
                operation_id="corrupt-operation",
            )
            assert report.status == "failed"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
                assert connection.execute(
                    "SELECT failure_reason FROM arena_recovery_events "
                    "WHERE operation_id = 'corrupt-operation' AND status = 'failed'"
                ).fetchone()[0]
            await runtime.close()

    asyncio.run(run())
