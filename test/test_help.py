from __future__ import annotations

import asyncio
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime


def test_help_overview_and_bounty_category_use_unprefixed_commands() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            context = CommandContext(adapter="web", user_id="help-user")
            try:
                overview = await runtime.dispatch(context, "帮助")
                assert overview.code == "HELP_OVERVIEW"
                assert all(
                    f"修仙帮助 {category}" in overview.message
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
            finally:
                await runtime.close()

    asyncio.run(run())
