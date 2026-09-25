from __future__ import annotations

import asyncio
import json
import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.contracts import CommandContext

from test.test_arena import MutableClock, _adapter_contexts, _cultivator


def test_qq_onebot_social_recovery_restores_cross_server_inputs_and_replays_operation() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 25, 12, tzinfo=timezone.utc))
        qq, onebot = _adapter_contexts()
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            qq = replace(qq, user_id="social-recovery-qq")
            onebot = replace(onebot, user_id="social-recovery-onebot")
            await _cultivator(runtime, qq, "social-qq")
            await _cultivator(runtime, onebot, "social-ob")
            now_text = clock.value.isoformat()
            with sqlite3.connect(runtime.settings.database_path) as connection:
                players = dict(connection.execute("SELECT platform_user_id,id FROM players").fetchall())
                connection.execute(
                    "INSERT INTO sects(sect_id,name,name_key,leader_id,status,level,max_members,warehouse_capacity,construction,spirit_stones,sect_merit,warehouse_json,created_at,updated_at,content_version,rule_version) "
                    "VALUES ('social-sect','恢复宗','social-sect',?,'active',5,120,100,0,20000,0,?,?,?,'content-0.5','social-0.5.0')",
                    (players["social-recovery-qq"], json.dumps({"item.void_anchor": 35, "item.mat.array_sand": 40}), now_text, now_text),
                )
                for user, role in (("social-recovery-qq", "leader"), ("social-recovery-onebot", "member")):
                    connection.execute(
                        "INSERT INTO sect_members(sect_id,player_id,role,status,contribution,joined_at,last_action_at,created_at,updated_at) VALUES ('social-sect',? ,?,'active',0,?,?,?,?)",
                            (players[user], role, now_text, now_text, now_text, now_text),
                    )

            built = await runtime.repository.build_void_fortress(
                platform="qq.official", platform_user_id="social-recovery-qq", operation_id="social-build"
            )
            assert built.status == "building"
            clock.value += timedelta(hours=49)
            beacon = await runtime.repository.build_void_beacon(
                platform="qq.official", platform_user_id="social-recovery-qq", operation_id="social-beacon"
            )
            assert beacon.status == "building"

            published = await runtime.adapters.dispatch(
                onebot.adapter, replace(onebot, operation_id="social-arena-publish"), "发布竞技场快照"
            )
            clock.value += timedelta(minutes=31)
            challenged = await runtime.adapters.dispatch(
                qq.adapter,
                replace(qq, operation_id="social-arena-challenge"),
                f"挑战竞技场 {published.data['snapshot_id']}",
            )
            assert challenged.ok

            with sqlite3.connect(runtime.settings.database_path) as connection:
                leader_id = players["social-recovery-qq"]
                connection.execute(
                    "INSERT INTO sects(sect_id,name,name_key,leader_id,status,level,max_members,warehouse_capacity,construction,spirit_stones,sect_merit,warehouse_json,created_at,updated_at,content_version,rule_version) "
                    "VALUES ('social-sect-b','恢复乙宗','social-sect-b',?,'active',5,120,100,0,20000,0,'{}',?,?, 'content-0.5','social-0.5.0')",
                    (players["social-recovery-onebot"], now_text, now_text),
                )
                connection.execute(
                    "INSERT INTO sect_alliance_contracts(alliance_id,sect_a_id,sect_b_id,proposer_sect_id,proposer_player_id,status,sect_a_confirmed,sect_b_confirmed,confirmation_expires_at,starts_at,ends_at,snapshot_json,content_version,rule_version,created_at,updated_at) "
                        "VALUES ('social-alliance','social-sect','social-sect-b','social-sect',?,'active',1,1,?,?,?,?,'content-0.5','social-0.5.0',?,?)",
                    (leader_id, now_text, now_text, now_text, json.dumps({"agreement": "test"}), now_text, now_text),
                )

            backup_context = replace(
                qq,
                capabilities=qq.capabilities + ("social.recovery",),
                operation_id="social-backup-command",
                request_id="social-backup-request",
            )
            denied = await runtime.adapters.dispatch(qq.adapter, replace(qq, operation_id="social-denied"), "创建跨服社交备份 denied")
            assert denied.code == "SOCIAL_RECOVERY_PERMISSION_DENIED"
            invalid_key = await runtime.adapters.dispatch(qq.adapter, replace(backup_context, operation_id="social-invalid-key"), "创建跨服社交备份 ../escape")
            assert invalid_key.code == "INVALID_SOCIAL_RECOVERY"
            created = await runtime.adapters.dispatch(qq.adapter, backup_context, "创建跨服社交备份 social-main")
            assert created.code == "SOCIAL_RECOVERY_BACKUP_CREATED"
            assert created.data["row_counts"]["sect_void_fortresses"] == 1
            assert created.data["row_counts"]["sect_void_beacons"] == 1
            assert created.data["row_counts"]["sect_alliance_contracts"] == 1

            verify_context = replace(
                onebot,
                capabilities=onebot.capabilities + ("ops.recovery",),
                operation_id="social-verify-command",
            )
            verified = await runtime.adapters.dispatch(onebot.adapter, verify_context, "校验跨服社交备份 social-main")
            assert verified.code == "SOCIAL_RECOVERY_BACKUP_VERIFIED"

            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute("UPDATE sects SET spirit_stones=1 WHERE sect_id='social-sect'")
                connection.commit()
            restored = await runtime.adapters.dispatch(
                qq.adapter,
                replace(backup_context, operation_id="social-restore-command", request_id="social-restore-request"),
                "恢复跨服社交备份 social-main",
            )
            assert restored.code == "SOCIAL_RECOVERY_RESTORED"
            assert restored.data["checks"]["social_reference_check"] == "ok"
            assert restored.data["pre_restore_artifact"] is not None
            restore_replay = await runtime.adapters.dispatch(
                onebot.adapter,
                replace(verify_context, operation_id="social-restore-command", request_id="social-restore-request"),
                "恢复跨服社交备份 social-main",
            )
            assert restore_replay.code == "SOCIAL_RECOVERY_RESTORED"
            assert restore_replay.data["idempotent_replay"] is True

            replay = await runtime.repository.build_void_fortress(
                platform="qq.official", platform_user_id="social-recovery-qq", operation_id="social-build"
            )
            assert replay.already_completed is True
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute("SELECT spirit_stones FROM sects WHERE sect_id='social-sect'").fetchone()[0] == 10000
                assert connection.execute("SELECT COUNT(*) FROM arena_identity_routes").fetchone()[0] == 2
                assert connection.execute("SELECT COUNT(*) FROM arena_audit_events").fetchone()[0] == 2
                event = connection.execute(
                    "SELECT status, request_id, operation_id FROM social_recovery_events WHERE event_key='social.restore.completed'"
                ).fetchone()
                assert event == ("active", "social-restore-request", "social-restore-command")
            await runtime.close()

    asyncio.run(run())


def test_social_recovery_failure_preserves_live_database_and_records_snapshot() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            await runtime.initialize()
            assert (await runtime.dispatch(CommandContext(adapter="qq.official", user_id="social-failure-user", operation_id="create-failure"), "开始修仙")).ok
            await runtime.repository.create_social_recovery_backup(
                artifact_key="social-failure", request_id="backup-request", operation_id="backup-operation"
            )
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute("UPDATE players SET arena_rating=7")
                connection.commit()
            failed = await runtime.repository.restore_social_recovery_backup(
                artifact_key="social-failure",
                request_id="failure-request",
                operation_id="failure-operation",
                fail_after_snapshot=True,
            )
            assert failed.status == "failed"
            assert "injected failure" in failed.failure_reason
            assert failed.pre_restore_artifact is not None
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute("SELECT arena_rating FROM players").fetchone()[0] == 7
                assert connection.execute("SELECT COUNT(*) FROM social_recovery_events WHERE status='failed'").fetchone()[0] == 1
            await runtime.close()

    asyncio.run(run())
