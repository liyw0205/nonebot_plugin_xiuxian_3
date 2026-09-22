from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime


class MutableClock:
    def __init__(self, value: datetime):
        self.value = value

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **kwargs: int) -> None:
        self.value += timedelta(**kwargs)


def _context(user_id: str, request_id: str, *, operation_id: str = "") -> CommandContext:
    return CommandContext(adapter="web", user_id=user_id, request_id=request_id, operation_id=operation_id)


async def _enter_cultivator(runtime, user_id: str) -> None:
    commands = (
        "开始修仙",
        "寻仙问道",
        "完成引导 阅读",
        "前往近郊",
        "完成引导 采集",
        "完成引导 炼丹",
        "选择道途 体修",
    )
    for index, command in enumerate(commands):
        result = await runtime.dispatch(_context(user_id, f"setup-{index}"), command)
        assert result.ok, (command, result.code, result.message)


def _add_item(runtime, user_id: str, item_key: str, quantity: int) -> None:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        row = connection.execute(
            "SELECT inventory_json FROM players WHERE platform_user_id = ?", (user_id,)
        ).fetchone()
        inventory = json.loads(row[0])
        inventory[item_key] = int(inventory.get(item_key, 0)) + quantity
        connection.execute(
            "UPDATE players SET inventory_json = ? WHERE platform_user_id = ?",
            (json.dumps(inventory, ensure_ascii=False, sort_keys=True), user_id),
        )


def test_constitution_preview_selection_and_profile_are_idempotent() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            user = "constitution-select"
            preview = await runtime.dispatch(_context(user, "preview"), "体质预览")
            assert preview.ok
            assert all(label in preview.message for label in ("铁骨", "灵根", "风行", "巧手", "御兽", "福缘"))

            before = await runtime.dispatch(_context(user, "before"), "选择体质 铁骨")
            assert before.code == "PLAYER_NOT_FOUND"
            await _enter_cultivator(runtime, user)

            selected = await runtime.dispatch(
                _context(user, "select", operation_id="constitution-select-1"), "选择体质 铁骨"
            )
            assert selected.code == "CONSTITUTION_SELECTED"
            assert selected.data["constitution_key"] == "constitution.iron_bone"
            replay = await runtime.dispatch(
                _context(user, "replay", operation_id="constitution-select-1"), "选择体质 铁骨"
            )
            assert replay.data["idempotent_replay"] is True
            assert replay.data["effect"] == selected.data["effect"]

            duplicate = await runtime.dispatch(_context(user, "duplicate"), "选择体质 灵根")
            assert duplicate.code == "CONSTITUTION_ALREADY_SELECTED"
            profile = await runtime.dispatch(_context(user, "profile"), "我的体质")
            assert profile.code == "CONSTITUTION_PROFILE"
            assert profile.data["label"] == "铁骨"
            await runtime.close()

    asyncio.run(run())


def test_constitution_selection_respects_long_action_lock() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            user = "constitution-busy"
            await _enter_cultivator(runtime, user)
            started = await runtime.dispatch(_context(user, "retreat"), "开始闭关")
            assert started.ok
            blocked = await runtime.dispatch(_context(user, "select"), "选择体质 灵根")
            assert blocked.code == "CONSTITUTION_BUSY"
            await runtime.close()

    asyncio.run(run())


def test_constitution_selection_is_unique_under_concurrency() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            user = "constitution-concurrent"
            await _enter_cultivator(runtime, user)
            results = await asyncio.gather(
                *(
                    runtime.dispatch(
                        _context(user, f"select-{index}", operation_id=f"constitution-{index}"),
                        "选择体质 福缘",
                    )
                    for index in range(12)
                )
            )
            assert sum(result.ok for result in results) == 1
            assert {result.code for result in results} == {
                "CONSTITUTION_SELECTED",
                "CONSTITUTION_ALREADY_SELECTED",
            }
            with sqlite3.connect(runtime.settings.database_path) as connection:
                count = connection.execute(
                    "SELECT COUNT(*) FROM constitution_profiles WHERE player_id = (SELECT id FROM players WHERE platform_user_id = ?)",
                    (user,),
                ).fetchone()[0]
            assert count == 1
            await runtime.close()

    asyncio.run(run())


def test_constitution_reshape_consumes_token_and_enforces_cooldown() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            user = "constitution-reshape"
            await _enter_cultivator(runtime, user)
            selected = await runtime.dispatch(_context(user, "select"), "选择体质 铁骨")
            assert selected.ok
            _add_item(runtime, user, "item.token.constitution_reset", 1)

            reshaped = await runtime.dispatch(
                _context(user, "reshape", operation_id="constitution-reshape-1"), "重塑体质 灵根"
            )
            assert reshaped.code == "CONSTITUTION_RESHAPED"
            assert reshaped.data["constitution_key"] == "constitution.spirit_root"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                inventory = json.loads(
                    connection.execute(
                        "SELECT inventory_json FROM players WHERE platform_user_id = ?", (user,)
                    ).fetchone()[0]
                )
            assert inventory.get("item.token.constitution_reset", 0) == 0

            replay = await runtime.dispatch(
                _context(user, "reshape-replay", operation_id="constitution-reshape-1"), "重塑体质 灵根"
            )
            assert replay.data["idempotent_replay"] is True
            cooldown = await runtime.dispatch(_context(user, "cooldown"), "重塑体质 风行")
            assert cooldown.code == "CONSTITUTION_COOLDOWN"

            clock.advance(days=30)
            _add_item(runtime, user, "item.token.constitution_reset", 1)
            reshaped_again = await runtime.dispatch(
                _context(user, "reshape-again", operation_id="constitution-reshape-2"), "重塑体质 风行"
            )
            assert reshaped_again.code == "CONSTITUTION_RESHAPED"
            assert reshaped_again.data["reshape_count"] == 2
            await runtime.close()

    asyncio.run(run())


def test_constitution_reshape_requires_existing_profile_and_token() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            user = "constitution-missing"
            await _enter_cultivator(runtime, user)
            missing = await runtime.dispatch(_context(user, "reshape"), "重塑体质 福缘")
            assert missing.code == "CONSTITUTION_NOT_SELECTED"
            selected = await runtime.dispatch(_context(user, "select"), "选择体质 福缘")
            assert selected.ok
            no_token = await runtime.dispatch(_context(user, "reshape"), "重塑体质 巧手")
            assert no_token.code == "RESOURCE_INSUFFICIENT"
            await runtime.close()

    asyncio.run(run())
