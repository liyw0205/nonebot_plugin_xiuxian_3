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
                        assert not any(word in command for word in ("道号", "配方名", "悬赏名", "灵兽号", "申请号"))
            finally:
                await runtime.close()

    asyncio.run(run())
