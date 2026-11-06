from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timezone
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime


def _context(adapter: str, user: str, request: str, operation: str = "") -> CommandContext:
    return CommandContext(
        adapter=adapter,
        user_id=user,
        request_id=request,
        operation_id=operation,
        can_write_assets=True,
    )


def test_help_pages_name_the_real_idle_and_dao_commands() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(
                data_dir=data_dir,
                clock=lambda: datetime(2026, 9, 27, tzinfo=timezone.utc),
            )
            adapter, user = "onebot.v11", "help-idle-dao"
            assert (await runtime.dispatch(_context(adapter, user, "create"), "开始修仙")).ok

            life = await runtime.dispatch(_context(adapter, user, "life"), "修仙帮助 生活")
            assert life.ok, life.message
            for token in ("挂机预览", "开始挂机", "领取挂机", "取消挂机"):
                assert token in life.message, token
            assert "\\n" not in life.message

            social = await runtime.dispatch(_context(adapter, user, "social"), "修仙帮助 社交")
            assert social.ok, social.message
            for token in ("道统", "道统投票", "道统结算", "建立据点", "据点"):
                assert token in social.message, token
            assert "\\n" not in social.message
            await runtime.close()

    asyncio.run(run())


def test_idle_onboarding_guide_is_cultivator_only_and_repeatable() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(
                data_dir=data_dir,
                clock=lambda: datetime(2026, 9, 27, tzinfo=timezone.utc),
            )
            adapter, user = "onebot.v11", "guide-idle"
            assert (await runtime.dispatch(_context(adapter, user, "create"), "开始修仙")).ok

            mortal = await runtime.dispatch(
                _context(adapter, user, "mortal", "guide-idle-mortal"), "完成引导 闲居"
            )
            assert mortal.ok is False, mortal.message

            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE players SET stage='cultivator', realm_key='qi_sensing', "
                    "realm_layer=1 WHERE platform=? AND platform_user_id=?",
                    (adapter, user),
                )

            completed = await runtime.dispatch(
                _context(adapter, user, "idle-guide", "guide-idle-done"), "完成引导 闲居"
            )
            assert completed.code == "INTRO_COMPLETED", completed.message
            assert "闲居指路" in completed.message
            assert "挂机预览" in completed.message

            replay = await runtime.dispatch(
                _context(adapter, user, "idle-guide-again", "guide-idle-again"), "完成引导 闲居"
            )
            assert replay.code == "INTRO_ALREADY_COMPLETED", replay.message

            with sqlite3.connect(runtime.settings.database_path) as connection:
                flags = connection.execute(
                    "SELECT intro_json FROM players WHERE platform=? AND platform_user_id=?",
                    (adapter, user),
                ).fetchone()[0]
            assert "guide.idle_entry" in flags
            await runtime.close()

    asyncio.run(run())
