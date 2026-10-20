from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.exploration.rules import (
    exploration_definitions_by_location,
)


def _context(user_id: str, request_id: str, *, operation_id: str = "") -> CommandContext:
    return CommandContext(
        adapter="web",
        user_id=user_id,
        request_id=request_id,
        operation_id=operation_id,
    )


def _set_player(runtime, user_id: str, **values: object) -> None:
    assignments = ", ".join(f"{key} = ?" for key in values)
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            f"UPDATE players SET {assignments} WHERE platform_user_id = ?",
            (*values.values(), user_id),
        )


async def _make_player(runtime, user_id: str) -> None:
    assert (await runtime.dispatch(_context(user_id, "create"), "开始修仙")).ok
    assert (await runtime.dispatch(_context(user_id, "seek"), "寻仙问道")).ok
    _set_player(
        runtime,
        user_id,
        stage="cultivator",
        realm_key="void_refining",
        realm_layer=1,
        location_key="cave.time_garden",
        stamina=100,
        stamina_max=100,
        energy=30,
        energy_max=30,
    )


def test_explore_help_lists_open_modes_grouped_by_location() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=Path(data_dir))
            result = await runtime.dispatch(_context("help-reader", "help"), "修仙帮助 探索")
            assert result.code == "HELP_CATEGORY"
            body = result.message
            assert "**当前开放探索**" in body
            assert "时序福地采撷" in body, "new modes must appear in the help page"
            assert "近郊采集" in body
            assert "返回修仙指南" in body
            await runtime.close()

    asyncio.run(run())


def test_explore_help_falls_back_when_content_fails() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=Path(data_dir))
            # Break the content bundle the dynamic block reads; the method's
            # own try/except must swallow the failure and render the page.
            runtime.application.content = None
            original_grouped = (
                "nonebot_plugin_xiuxian_3.xiuxian.exploration.rules."
                "exploration_definitions_by_location"
            )
            import nonebot_plugin_xiuxian_3.xiuxian.exploration.rules as rules

            def boom(content=None):
                raise RuntimeError("boom")

            setattr(rules, "exploration_definitions_by_location", boom)
            try:
                result = await runtime.dispatch(
                    _context("help-reader", "help"), "修仙帮助 探索"
                )
            finally:
                import importlib

                importlib.reload(rules)
            assert result.code == "HELP_CATEGORY"
            assert "返回修仙指南" in result.message
            await runtime.close()

    asyncio.run(run())


def test_start_exploration_without_args_lists_location_modes() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=Path(data_dir))
            user = "garden-list"
            await _make_player(runtime, user)
            result = await runtime.dispatch(_context(user, "start-plain"), "开始探索")
            assert result.code == "INVALID_EXPLORATION_MODE"
            assert "时序福地采撷" in result.message, result.message
            assert "cave.time_garden" not in result.message, "must show labels, not keys"
            assert "请发送 `开始探索 探索名称`" in result.message
            await runtime.close()

    asyncio.run(run())


def test_start_exploration_without_args_guides_when_no_modes() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=Path(data_dir))
            user = "empty-spot"
            await _make_player(runtime, user)
            _set_player(runtime, user, location_key="void.portal")
            result = await runtime.dispatch(_context(user, "start-plain"), "开始探索")
            assert result.code == "INVALID_EXPLORATION_MODE"
            assert "暂无开放的探索模式" in result.message
            await runtime.close()

    asyncio.run(run())


def test_start_exploration_without_args_player_missing() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=Path(data_dir))
            result = await runtime.dispatch(
                _context("nobody", "start-plain"), "开始探索"
            )
            assert result.code == "PLAYER_NOT_FOUND"
            await runtime.close()

    asyncio.run(run())


def test_location_groups_cover_the_new_mode() -> None:
    grouped = exploration_definitions_by_location()
    garden = grouped.get("cave.time_garden", {})
    assert "explore.time_garden" in garden
    assert garden["explore.time_garden"].daily_limit == 2
    # Open modes only: locked ones (e.g. dao_origin) must not appear.
    assert "explore.dao_origin" not in grouped.get("dao.origin_gate", {})
