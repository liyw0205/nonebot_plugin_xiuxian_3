from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timezone
from tempfile import TemporaryDirectory

import pytest

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.persistence.errors import (
    CrossServerRewardAllocationError,
    OperationResultMalformedError,
)


ROUND_ID = "sect_war.cross:2026-W39"
OPERATION_NAME = "social.sect_war_cross_server.allocate_reward"


async def _setup_reward_box(runtime, *, reward_json: str, distributed_json: str = "{}") -> int:
    context = CommandContext(
        adapter="qq.official",
        user_id="reward-leader",
        operation_id="create-reward-leader",
        can_write_assets=True,
    )
    assert (await runtime.dispatch(context, "开始修仙")).code == "PLAYER_CREATED"
    await runtime.repository.get_cross_server_sect_war(
        platform="qq.official", platform_user_id="reward-leader", round_id=ROUND_ID
    )
    now_text = "2026-09-25T12:00:00+00:00"
    with sqlite3.connect(runtime.settings.database_path) as connection:
        player_id = connection.execute(
            "SELECT id FROM players WHERE platform='qq.official' AND platform_user_id='reward-leader'"
        ).fetchone()[0]
        connection.execute(
            "INSERT INTO sects(sect_id,name,name_key,leader_id,status,level,max_members,warehouse_capacity,construction,spirit_stones,sect_merit,warehouse_json,created_at,updated_at) "
            "VALUES ('reward-sect','奖励宗','reward-sect',?,'active',5,120,100,0,0,0,'{}',?,?)",
            (player_id, now_text, now_text),
        )
        connection.execute(
            "INSERT INTO sect_members(sect_id,player_id,role,status,contribution,joined_at,last_action_at,created_at,updated_at) "
            "VALUES ('reward-sect',?,'leader','active',0,?,?,?,?)",
            (player_id, now_text, now_text, now_text, now_text),
        )
        connection.execute(
            "INSERT INTO sect_cross_server_war_registrations(round_id,sect_id,operation_id,entry_fee,status,roster_size,score,rank,winner,snapshot_json,registered_at) "
            "VALUES (?,'reward-sect','reward-registration',0,'registered',1,0,1,1,'{}',?)",
            (ROUND_ID, now_text),
        )
        connection.execute(
            "INSERT INTO sect_cross_server_war_members(round_id,sect_id,player_id,roster_slot,snapshot_json,created_at,updated_at) "
            "VALUES (?,'reward-sect',?,1,'{}',?,?)",
            (ROUND_ID, player_id, now_text, now_text),
        )
        connection.execute(
            "INSERT INTO sect_cross_server_reward_boxes(box_id,round_id,sect_id,status,reward_json,distributed_json,created_at,updated_at) "
            "VALUES ('reward-box',?,'reward-sect','pending',?,?,?,?)",
            (ROUND_ID, reward_json, distributed_json, now_text, now_text),
        )
    return int(player_id)


def test_cross_server_reward_box_rejects_duplicate_json_without_granting_assets() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(
                data_dir=data_dir,
                clock=lambda: datetime(2026, 9, 25, 12, tzinfo=timezone.utc),
            )
            try:
                await _setup_reward_box(
                    runtime,
                    reward_json='{"item.void_crystal":1,"item.void_crystal":10}',
                )
                with pytest.raises(CrossServerRewardAllocationError):
                    await runtime.repository.allocate_cross_server_reward(
                        platform="qq.official",
                        platform_user_id="reward-leader",
                        round_id=ROUND_ID,
                        target_platform="qq.official",
                        target_platform_user_id="reward-leader",
                        quantity=10,
                        operation_id="duplicate-reward-box-allocation",
                    )
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    inventory_json, allocation_count, operation_count, distributed_json = connection.execute(
                        "SELECT p.inventory_json, "
                        "(SELECT COUNT(*) FROM sect_cross_server_reward_allocations), "
                        "(SELECT COUNT(*) FROM operations WHERE operation_id='duplicate-reward-box-allocation'), "
                        "b.distributed_json "
                        "FROM players p JOIN sect_cross_server_reward_boxes b ON b.sect_id='reward-sect' "
                        "WHERE p.platform_user_id='reward-leader'"
                    ).fetchone()
                    assert json.loads(inventory_json) == {}
                    assert allocation_count == 0
                    assert operation_count == 0
                    assert distributed_json == "{}"
            finally:
                await runtime.close()

    asyncio.run(run())


def test_cross_server_allocation_replay_rejects_duplicate_result_without_second_grant() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(
                data_dir=data_dir,
                clock=lambda: datetime(2026, 9, 25, 12, tzinfo=timezone.utc),
            )
            try:
                player_id = await _setup_reward_box(runtime, reward_json='{"item.void_crystal":10}')
                operation_id = "corrupt-allocation-replay"
                request = {
                    "platform": "qq.official",
                    "platform_user_id": "reward-leader",
                    "round_id": ROUND_ID,
                    "target_platform": "qq.official",
                    "target_platform_user_id": "reward-leader",
                    "quantity": 1,
                }
                request_hash = runtime.repository._request_hash(OPERATION_NAME, request)
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "INSERT INTO operations(operation_id,operation_name,player_id,request_hash,result_json,created_at) "
                        "VALUES (?,?,?,?,?,?)",
                        (
                            operation_id,
                            OPERATION_NAME,
                            player_id,
                            request_hash,
                            '{"round_id":"sect_war.cross:2026-W39","sect_id":"reward-sect",'
                            '"reward":{"item.void_crystal":1,"item.void_crystal":99},"status":"partial"}',
                            "2026-09-25T12:00:00+00:00",
                        ),
                    )
                with pytest.raises(OperationResultMalformedError):
                    await runtime.repository.allocate_cross_server_reward(
                        platform="qq.official",
                        platform_user_id="reward-leader",
                        round_id=ROUND_ID,
                        target_platform="qq.official",
                        target_platform_user_id="reward-leader",
                        quantity=1,
                        operation_id=operation_id,
                    )
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    inventory_json, allocation_count, distributed_json = connection.execute(
                        "SELECT p.inventory_json, "
                        "(SELECT COUNT(*) FROM sect_cross_server_reward_allocations), "
                        "b.distributed_json "
                        "FROM players p JOIN sect_cross_server_reward_boxes b ON b.sect_id='reward-sect' "
                        "WHERE p.platform_user_id='reward-leader'"
                    ).fetchone()
                    assert json.loads(inventory_json) == {}
                    assert allocation_count == 0
                    assert distributed_json == "{}"
            finally:
                await runtime.close()

    asyncio.run(run())


def test_cross_server_allocation_replay_is_idempotent_after_box_is_empty() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(
                data_dir=data_dir,
                clock=lambda: datetime(2026, 9, 25, 12, tzinfo=timezone.utc),
            )
            try:
                await _setup_reward_box(runtime, reward_json='{"item.void_crystal":10}')
                first = await runtime.repository.allocate_cross_server_reward(
                    platform="qq.official",
                    platform_user_id="reward-leader",
                    round_id=ROUND_ID,
                    target_platform="qq.official",
                    target_platform_user_id="reward-leader",
                    quantity=10,
                    operation_id="idempotent-allocation",
                )
                replay = await runtime.repository.allocate_cross_server_reward(
                    platform="qq.official",
                    platform_user_id="reward-leader",
                    round_id=ROUND_ID,
                    target_platform="qq.official",
                    target_platform_user_id="reward-leader",
                    quantity=10,
                    operation_id="idempotent-allocation",
                )
                assert first.reward == {"item.void_crystal": 10}
                assert replay.reward == first.reward
                assert replay.already_completed is True
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    inventory_json, allocation_count = connection.execute(
                        "SELECT inventory_json, "
                        "(SELECT COUNT(*) FROM sect_cross_server_reward_allocations) "
                        "FROM players WHERE platform_user_id='reward-leader'"
                    ).fetchone()
                    assert json.loads(inventory_json) == {"item.void_crystal": 10}
                    assert allocation_count == 1
            finally:
                await runtime.close()

    asyncio.run(run())
