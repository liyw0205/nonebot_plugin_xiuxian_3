from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timezone
from tempfile import TemporaryDirectory

import pytest

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.persistence.errors import OperationConflictError


def _ctx(adapter: str, user: str, operation: str) -> CommandContext:
    return CommandContext(
        adapter=adapter,
        user_id=user,
        request_id=operation,
        operation_id=operation,
        can_write_assets=True,
    )


def test_cross_server_sect_war_freezes_roster_and_imports_audited_result_without_assets() -> None:
    async def run() -> None:
        now = datetime(2026, 9, 25, 12, tzinfo=timezone.utc)
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=lambda: now)
            assert (await runtime.adapters.dispatch("qq.official", _ctx("qq.official", "federation-qq", "create-qq"), "开始修仙")).code == "PLAYER_CREATED"
            assert (await runtime.adapters.dispatch("onebot.v11", _ctx("onebot.v11", "federation-ob", "create-ob"), "开始修仙")).code == "PLAYER_CREATED"
            now_text = now.isoformat()
            with sqlite3.connect(runtime.settings.database_path) as connection:
                players = dict(connection.execute("SELECT platform_user_id,id FROM players").fetchall())
                connection.execute(
                    "INSERT INTO sects(sect_id,name,name_key,motto,leader_id,status,level,max_members,warehouse_capacity,construction,spirit_stones,sect_merit,created_at,updated_at,content_version,rule_version) VALUES ('federation-sect','跨服测试宗','federation-sect','', ?, 'active', 5, 120, 100, 0, 5000, 0, ?, ?, 'content-0.5', 'social-0.5.0')",
                    (players["federation-qq"], now_text, now_text),
                )
                connection.execute(
                    "INSERT INTO sect_members(sect_id,player_id,role,status,contribution,joined_at,last_action_at,created_at,updated_at) VALUES ('federation-sect', ?, 'leader', 'active', 10, ?, ?, ?, ?)",
                    (players["federation-qq"], now_text, now_text, now_text, now_text),
                )
                connection.execute(
                    "INSERT INTO sect_war_rounds(round_id,registration_open_at,registration_close_at,starts_at,ends_at,claim_expires_at,status,snapshot_json,created_at,updated_at) VALUES ('sect_war:20260921:1', ?, ?, ?, ?, ?, 'open', '{}', ?, ?)",
                    (now_text, now_text, now_text, now_text, now_text, now_text, now_text),
                )
                connection.execute(
                    "INSERT INTO sect_war_registrations(round_id,sect_id,operation_id,entry_fee,status,snapshot_json,registered_at) VALUES ('sect_war:20260921:1','federation-sect','federation-register',2000,'registered',?,?)",
                    (json.dumps({"sect_id": "federation-sect"}), now_text),
                )
                connection.execute(
                    "INSERT INTO sect_war_members(round_id,sect_id,player_id,roster_slot,snapshot_json,contribution,created_at,updated_at) VALUES ('sect_war:20260921:1','federation-sect',?,1,?,20,?,?)",
                    (players["federation-qq"], json.dumps({"realm_key": "void_refining", "realm_layer": 1}), now_text, now_text),
                )

            frozen = await runtime.repository.freeze_sect_war_federation_snapshot(
                platform="qq.official",
                platform_user_id="federation-qq",
                round_id="sect_war:20260921:1",
                shard_key="local-a",
                operation_id="federation-freeze",
            )
            assert frozen.roster_size == 1
            replay = await runtime.repository.freeze_sect_war_federation_snapshot(
                platform="qq.official",
                platform_user_id="federation-qq",
                round_id="sect_war:20260921:1",
                shard_key="local-a",
                operation_id="federation-freeze",
            )
            assert replay.already_completed is True

            imported = await runtime.repository.import_sect_war_federation_result(
                platform="onebot.v11",
                platform_user_id="federation-ob",
                round_id="sect_war:20260921:1",
                shard_key="remote-b",
                sect_id="remote-sect",
                score=130,
                winner=True,
                source_operation_id="remote-settlement-1",
                operation_id="federation-import",
                result_id="remote-result-1",
            )
            assert imported.winner is True
            imported_replay = await runtime.repository.import_sect_war_federation_result(
                platform="onebot.v11",
                platform_user_id="federation-ob",
                round_id="sect_war:20260921:1",
                shard_key="remote-b",
                sect_id="remote-sect",
                score=130,
                winner=True,
                source_operation_id="remote-settlement-1",
                operation_id="federation-import",
                result_id="remote-result-1",
            )
            assert imported_replay.already_completed is True
            with pytest.raises(OperationConflictError):
                await runtime.repository.import_sect_war_federation_result(
                    platform="onebot.v11",
                    platform_user_id="federation-ob",
                    round_id="sect_war:20260921:1",
                    shard_key="remote-b",
                    sect_id="remote-sect",
                    score=131,
                    winner=True,
                    source_operation_id="remote-settlement-1",
                    operation_id="federation-import-conflict",
                    result_id="remote-result-1",
                )
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute("SELECT COUNT(*) FROM sect_war_federation_snapshots").fetchone()[0] == 1
                assert connection.execute("SELECT COUNT(*) FROM sect_war_federation_results").fetchone()[0] == 1
                assert connection.execute("SELECT spirit_stones,world_merit FROM players ORDER BY platform_user_id").fetchall() == [(0, 0), (0, 0)]
            await runtime.close()

    asyncio.run(run())
