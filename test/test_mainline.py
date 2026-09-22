from __future__ import annotations

import asyncio
import json
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime


def _context(operation_id: str) -> CommandContext:
    return CommandContext(
        adapter="web",
        user_id="mainline-user",
        operation_id=operation_id,
    )


def test_mainline_first_clear_retry_and_operation_replay() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            await runtime.dispatch(_context("create"), "开始修仙")
            await runtime.dispatch(_context("seek"), "寻仙问道")

            started = await runtime.dispatch(_context("mainline-start-1"), "开始主线 1")
            assert started.code == "MAINLINE_STARTED"
            claimed = await runtime.dispatch(_context("mainline-claim-1"), "领取主线奖励 1")
            assert claimed.code == "MAINLINE_REWARD_CLAIMED"
            assert claimed.data["first_clear"] is True
            assert claimed.data["reward"]["local_reputation"] == 3
            assert "access.xuantian.outskirts" not in claimed.message
            assert "用户 ID" not in claimed.message

            replay = await runtime.dispatch(_context("mainline-claim-1"), "领取主线奖励 1")
            assert replay.code == "MAINLINE_REWARD_CLAIMED"
            assert replay.data["first_clear"] is True
            assert replay.data["idempotent_replay"] is True

            retry_start = await runtime.dispatch(_context("mainline-start-1-retry"), "开始主线 1")
            assert retry_start.code == "MAINLINE_STARTED"
            assert retry_start.data["first_clear"] is False
            retry_claim = await runtime.dispatch(_context("mainline-claim-1-retry"), "领取主线奖励 1")
            assert retry_claim.code == "MAINLINE_REWARD_CLAIMED"
            assert retry_claim.data["first_clear"] is False
            assert retry_claim.data["reward"] == {"spirit_stones": 5}

            with runtime.repository._connect() as connection:
                row = connection.execute(
                    "SELECT first_clear_claimed, attempt_count, status FROM mainline_runs WHERE stage_key = ?",
                    ("chapter.1.stage.1",),
                ).fetchone()
                assert row is not None
                assert int(row["first_clear_claimed"]) == 1
                assert int(row["attempt_count"]) == 2
                assert row["status"] == "claimed"
                event_count = connection.execute(
                    "SELECT COUNT(*) AS count FROM activity_events WHERE player_id = (SELECT id FROM players WHERE platform_user_id = ?) AND event_key = ?",
                    ("mainline-user", "access.xuantian.outskirts"),
                ).fetchone()
                assert int(event_count["count"]) == 1
            await runtime.close()

    asyncio.run(run())


def test_mainline_stage_prerequisites_and_reward_assets() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            await runtime.dispatch(_context("create"), "开始修仙")
            await runtime.dispatch(_context("seek"), "寻仙问道")
            await runtime.dispatch(_context("stage1-start"), "开始主线 初入玄天")
            await runtime.dispatch(_context("stage1-claim"), "领取主线奖励 初入玄天")

            locked = await runtime.dispatch(_context("stage2-locked"), "开始主线 2")
            assert locked.code == "MAINLINE_REQUIREMENT_MISSING"

            with runtime.repository._connect() as connection:
                connection.execute(
                    "UPDATE players SET realm_key = 'qi_sensing', realm_layer = 1 WHERE platform_user_id = ?",
                    ("mainline-user",),
                )
            stage2 = await runtime.dispatch(_context("stage2-start"), "开始主线 2")
            assert stage2.code == "MAINLINE_STARTED"
            stage2_claim = await runtime.dispatch(_context("stage2-claim"), "领取主线奖励 2")
            assert stage2_claim.data["reward"]["item.herb.spirit_leaf"] == 2

            with runtime.repository._connect() as connection:
                connection.execute(
                    "UPDATE players SET realm_layer = 3 WHERE platform_user_id = ?",
                    ("mainline-user",),
                )
            stage3 = await runtime.dispatch(_context("stage3-start"), "开始主线 3")
            assert stage3.code == "MAINLINE_STARTED"
            stage3_claim = await runtime.dispatch(_context("stage3-claim"), "领取主线奖励 3")
            assert stage3_claim.data["reward"]["title_key"] == "title.mist_watcher"

            with runtime.repository._connect() as connection:
                player = connection.execute(
                    "SELECT inventory_json FROM players WHERE platform_user_id = ?",
                    ("mainline-user",),
                ).fetchone()
                inventory = json.loads(player["inventory_json"])
                assert inventory["item.herb.spirit_leaf"] == 2
                title = connection.execute(
                    "SELECT title_key FROM honor_titles WHERE title_key = ?",
                    ("title.mist_watcher",),
                ).fetchone()
                assert title is not None
            await runtime.close()

    asyncio.run(run())


def test_closed_mainline_stage_does_not_create_a_run() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            await runtime.dispatch(_context("create"), "开始修仙")
            await runtime.dispatch(_context("seek"), "寻仙问道")
            result = await runtime.dispatch(_context("closed-stage"), "开始主线 城镇委托")
            assert result.code == "CONTENT_CLOSED"
            with runtime.repository._connect() as connection:
                count = connection.execute(
                    "SELECT COUNT(*) AS count FROM mainline_runs WHERE stage_key = ?",
                    ("chapter.2.stage.1",),
                ).fetchone()
                assert int(count["count"]) == 0
            await runtime.close()

    asyncio.run(run())
