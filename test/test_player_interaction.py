from __future__ import annotations

import asyncio
import re
from dataclasses import replace
from tempfile import TemporaryDirectory
from urllib.parse import unquote

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.adapters.message.markdown import markdown_to_text


def _links(message: str) -> dict[str, str]:
    return {
        label: unquote(payload)
        for label, payload in re.findall(r"\[([^]]+)\]\(command:([^)]+)\)", message)
    }


def test_public_onboarding_links_buttons_and_recipe_preview() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)

            async def dispatch(command: str, request: str = ""):
                context = CommandContext(adapter="onebot.v11", user_id="interaction-user")
                if request:
                    context = replace(context, request_id=request)
                return await runtime.dispatch(context, command)

            try:
                for command in ("我的状态", "寻仙问道", "悬赏榜", "生产预览 疗伤丹"):
                    missing = await dispatch(command)
                    assert missing.code == "PLAYER_NOT_FOUND"
                    assert _links(missing.message)["开始修仙"] == "开始修仙"
                    assert not missing.actions

                created = await dispatch("开始修仙 青云", "create")
                assert created.code == "PLAYER_CREATED"
                assert len(created.actions) == 1
                assert created.actions[0].command == "寻仙问道" and created.actions[0].enter
                assert "寻仙问道" not in _links(created.message).values()
                assert _links(created.message)["改名"] == "修仙改名"
                replay = await dispatch("开始修仙 青云", "create")
                assert replay.data["idempotent_replay"] and replay.actions == created.actions

                profile = await dispatch("我的状态")
                dao_line = next(line for line in profile.message.splitlines() if "**道号**" in line)
                assert "青云" in dao_line and _links(dao_line)["改名"] == "修仙改名"
                assert _links(profile.message)["寻仙问道"] == "寻仙问道"
                rename_prompt = await dispatch(_links(dao_line)["改名"])
                assert rename_prompt.code == "INVALID_DAO_NAME"
                assert _links(rename_prompt.message)["修仙改名"] == "修仙改名"

                seeking = await dispatch(created.actions[0].command, "seek")
                assert seeking.code == "SEEKING_STARTED"
                assert seeking.actions[0].command == "完成引导 阅读" and seeking.actions[0].enter
                assert "完成引导 阅读" not in _links(seeking.message).values()
                seek_replay = await dispatch(created.actions[0].command, "seek")
                assert seek_replay.data["idempotent_replay"] and not seek_replay.actions
                assert seek_replay.data["inventory"] == seeking.data["inventory"]
                assert _links(seek_replay.message)["我的状态"] == "我的状态"

                read = await dispatch(seeking.actions[0].command)
                assert _links(read.message)["前往近郊"] == "前往近郊"
                assert (await dispatch(_links(read.message)["前往近郊"])).ok
                gather = await dispatch("完成引导 采集")
                assert gather.ok and not gather.actions
                assert set(_links(gather.message).values()) == {
                    "完成引导 炼丹", "完成引导 炼器", "完成引导 布阵", "完成引导 烹饪"
                }
                service = await dispatch(_links(gather.message)["完成引导 炼丹"])
                assert _links(service.message)["选择道途"] == "选择道途"
                assert (await dispatch("选择道途 辅修 炼丹")).ok
                board = await dispatch("悬赏榜")
                assert board.ok and not board.actions
                assert "bounty." not in markdown_to_text(board.message)
                accept = next(
                    unquote(payload) for label, payload in re.findall(r"\[([^]]+)\]\(command:([^)]+)\)", board.message)
                    if label == "接取"
                )
                offer = next(offer for offer in board.data["offers"] if accept == "接取悬赏 " + offer["label"])
                accepted = await dispatch(accept)
                assert accepted.code == "BOUNTY_ACCEPTED"
                assert accepted.data["bounty_key"] == offer["bounty_key"]
                before = await dispatch("我的状态")
                preview = await dispatch("生产预览 疗伤丹")
                assert preview.code == "RECIPE_PREVIEW" and not preview.actions
                start = next(command for command in _links(preview.message).values() if command.startswith("开始生产 "))
                assert "配方名" not in start and "recipe." not in start
                after = await dispatch("我的状态")
                assert after.data["inventory"] == before.data["inventory"]
                assert after.data["energy"] == before.data["energy"]
                produced = await dispatch(start)
                assert produced.code == "PRODUCTION_STARTED"
                assert produced.data["energy"] == before.data["energy"] - preview.data["energy_cost"]
            finally:
                await runtime.close()

    asyncio.run(run())
