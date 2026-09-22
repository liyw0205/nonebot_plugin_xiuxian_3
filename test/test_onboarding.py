from __future__ import annotations

import asyncio
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime


def _context(user_id: str, index: str, *, operation_id: str = "") -> CommandContext:
    return CommandContext(
        adapter="web",
        user_id=user_id,
        request_id=f"request-{index}",
        operation_id=operation_id,
    )


def test_mortal_intro_and_first_path_flow() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            user = "intro-user"
            assert (await runtime.dispatch(_context(user, "create"), "开始修仙")).ok
            seeking = await runtime.dispatch(_context(user, "seek"), "寻仙问道")
            assert seeking.code == "SEEKING_STARTED"
            assert seeking.data["stamina"] == 30
            assert seeking.data["energy"] == 30
            assert seeking.data["inventory"]["item.herb.blood_grass"] == 3

            skipped = await runtime.dispatch(_context(user, "path-before"), "选择道途 体修")
            assert skipped.code == "PLAYER_STAGE_CONFLICT"

            read = await runtime.dispatch(_context(user, "read"), "完成引导 阅读")
            assert read.code == "INTRO_COMPLETED"
            assert read.data["intro_flags"] == ("guide.read_world",)

            at_town = await runtime.dispatch(_context(user, "gather-town"), "完成引导 采集")
            assert at_town.code == "LOCATION_REQUIRED"

            travel = await runtime.dispatch(_context(user, "travel"), "前往近郊")
            assert travel.code == "TRAVEL_COMPLETED"
            assert travel.data["stamina"] == 28

            gather = await runtime.dispatch(_context(user, "gather"), "完成引导 采集")
            assert gather.code == "INTRO_COMPLETED"
            assert 1 <= gather.data["item_quantity"] <= 2
            assert gather.data["stamina"] == 26

            service = await runtime.dispatch(_context(user, "service"), "完成引导 炼丹")
            assert service.code == "INTRO_COMPLETED"
            assert service.data["stage"] == "seeker"
            assert service.data["energy"] == 28

            entered = await runtime.dispatch(_context(user, "enter"), "选择道途 体修")
            assert entered.code == "CULTIVATION_ENTERED"
            assert entered.data["stage"] == "cultivator"
            assert entered.data["realm_key"] == "qi_sensing"
            assert entered.data["realm_layer"] == 1
            assert entered.data["inventory"]["item.manual.basic_qi"] == 1
            assert entered.data["inventory"]["skill.body.heavy_strike"] == 1
            assert entered.data["spirit_stones"] == 300

            profile = await runtime.dispatch(_context(user, "profile"), "我的状态")
            assert "感气 L1" in profile.message
            assert "xuantian" not in profile.message
            assert "玄天界·近郊" in profile.message
            assert "用户 ID" not in profile.message
            await runtime.close()

    asyncio.run(run())


def test_intro_and_cultivation_operations_are_idempotent() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            user = "replay-user"
            await runtime.dispatch(_context(user, "create"), "开始修仙")
            await runtime.dispatch(_context(user, "seek"), "寻仙问道")

            first = await runtime.dispatch(
                _context(user, "read-op", operation_id="intro-read-1"),
                "完成引导 阅读",
            )
            replay = await runtime.dispatch(
                _context(user, "read-replay", operation_id="intro-read-1"),
                "完成引导 阅读",
            )
            assert first.code == "INTRO_COMPLETED"
            assert replay.code == "INTRO_COMPLETED"
            assert replay.data["idempotent_replay"] is True

            await runtime.dispatch(_context(user, "travel"), "前往近郊")
            await runtime.dispatch(_context(user, "gather"), "完成引导 采集")
            await runtime.dispatch(_context(user, "service"), "完成引导 炼器")
            enter = await runtime.dispatch(
                _context(user, "enter-op", operation_id="cultivation-1"),
                "选择道途 器修",
            )
            replay_enter = await runtime.dispatch(
                _context(user, "enter-replay", operation_id="cultivation-1"),
                "选择道途 器修",
            )
            assert enter.code == "CULTIVATION_ENTERED"
            assert replay_enter.code == "CULTIVATION_ENTERED"
            assert replay_enter.data["idempotent_replay"] is True
            assert replay_enter.data["spirit_stones"] == 300
            await runtime.close()

    asyncio.run(run())


def test_support_path_requires_and_rewards_subprofession() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            user = "support-user"
            await runtime.dispatch(_context(user, "create"), "开始修仙")
            await runtime.dispatch(_context(user, "seek"), "寻仙问道")
            await runtime.dispatch(_context(user, "read"), "完成引导 阅读")
            await runtime.dispatch(_context(user, "travel"), "前往近郊")
            await runtime.dispatch(_context(user, "gather"), "完成引导 采集")
            await runtime.dispatch(_context(user, "service"), "完成引导 布阵")

            missing = await runtime.dispatch(_context(user, "support-missing"), "选择道途 辅修")
            assert missing.code == "SUBPROFESSION_REQUIRED"
            selected = await runtime.dispatch(
                _context(user, "support-selected"),
                "选择道途 辅修 布阵",
            )
            assert selected.code == "CULTIVATION_ENTERED"
            assert selected.data["subprofession_key"] == "formation"
            assert selected.data["inventory"]["item.mat.array_sand"] == 3
            await runtime.close()

    asyncio.run(run())
