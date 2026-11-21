from __future__ import annotations

import asyncio
import re
from tempfile import TemporaryDirectory
from urllib.parse import unquote

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.adapters.message.markdown import markdown_to_text


def test_help_overview_and_bounty_category_use_unprefixed_commands() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            context = CommandContext(adapter="web", user_id="help-user")
            try:
                overview = await runtime.dispatch(context, "帮助")
                assert overview.code == "HELP_OVERVIEW"
                assert all(
                    f"修仙帮助 {category}" in markdown_to_text(overview.message)
                    for category in ("启程", "修炼", "探索", "悬赏", "生活", "社交")
                )
                assert "/" not in overview.message

                bounty = await runtime.dispatch(context, "修仙帮助 悬赏")
                assert bounty.code == "HELP_CATEGORY"
                assert bounty.data["category"] == "悬赏"
                assert "接取悬赏 悬赏名" in bounty.message
                assert "UTC 自然日" in bounty.message
                assert "有效期内" in bounty.message
                assert "/" not in bounty.message

                unknown = await runtime.dispatch(context, "修仙帮助 未知")
                assert unknown.code == "HELP_CATEGORY_NOT_FOUND"
                assert unknown.message == overview.message
                assert not overview.actions and not unknown.actions
                assert not overview.message.startswith("#")
                overview_links = re.findall(r"\[([^]]+)\]\(command:([^)]+)\)", overview.message)
                assert [label for label, _ in overview_links] == ["启程", "修炼", "探索", "悬赏", "生活", "社交"]
                for label, payload in overview_links:
                    assert unquote(payload) == f"修仙帮助 {label}"
                    page = await runtime.dispatch(context, unquote(payload))
                    assert page.ok and not page.actions
                    assert page.message.count("返回修仙指南") == 1
                    assert not page.message.startswith("#")
                    links = re.findall(r"\[([^]]+)\]\(command:([^)]+)\)", page.message)
                    assert unquote(links[-1][1]) == "修仙帮助"
                    assert [unquote(payload) for _, payload in links if unquote(payload).startswith("修仙帮助")] == ["修仙帮助"]
                    for _, payload in links:
                        command = unquote(payload)
                        assert command.split()[0] in runtime.router.commands
                        if command == "生产预览 配方名 份数":
                            continue
                        assert not any(word in command for word in ("道号", "配方名", "悬赏名", "灵兽号", "申请号"))
            finally:
                await runtime.close()

    asyncio.run(run())


def test_life_help_exposes_complete_equipment_care_loop() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            try:
                result = await runtime.dispatch(
                    CommandContext(adapter="onebot.v11", user_id="equipment-help"),
                    "修仙帮助 生活",
                )
                assert result.ok
                for token in (
                    "装备修复预览 实例编号",
                    "修复装备 实例编号",
                    "装备回收预览 实例编号",
                    "回收装备 实例编号",
                    "生产预览 野外修缮包",
                    "野外修缮预览 实例编号",
                    "野外修缮装备 实例编号",
                    "接取委托 修缮包回收",
                    "交付委托 修缮包回收",
                ):
                    assert token in result.message, token
            finally:
                await runtime.close()

    asyncio.run(run())


def test_social_help_exposes_party_preparation_and_recovery() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            try:
                result = await runtime.dispatch(
                    CommandContext(adapter="onebot.v11", user_id="party-help"),
                    "修仙帮助 社交",
                )
                assert result.ok
                for command in (
                    "多人副本预览",
                    "创建多人副本队伍",
                    "邀请入队",
                    "接受入队",
                    "确认入队",
                    "开始队伍战斗",
                    "结算队伍战斗",
                    "队伍战斗回放",
                ):
                    assert command in result.message
                assert "玄武岩径古渠守标" in result.message
                assert "聚气二层" in result.message
                assert "每日一次" in result.message
                assert "玄武岩径古渠守标" in result.message
                assert "聚气二层" in result.message
                assert "每日一次" in result.message
            finally:
                await runtime.close()

    asyncio.run(run())


def test_cultivation_help_exposes_battle_tactic_configuration() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            try:
                result = await runtime.dispatch(
                    CommandContext(adapter="qq.official", user_id="tactic-help"),
                    "修仙帮助 修炼",
                )
                assert result.ok
                assert "战术预览" in result.message
                commands = {
                    unquote(payload)
                    for _, payload in re.findall(r"\[([^]]+)\]\(command:([^)]+)\)", result.message)
                }
                assert "设置战术 神通名" in commands
                assert "设置战术 自动" in commands
                assert "法力不足" in result.message
                assert "开战时冻结" in result.message
            finally:
                await runtime.close()

    asyncio.run(run())
