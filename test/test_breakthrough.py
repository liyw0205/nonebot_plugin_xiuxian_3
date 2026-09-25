from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.progression.breakthrough.rules import breakthrough_roll_bp


def _context(user_id: str, request_id: str, *, operation_id: str = "") -> CommandContext:
    return CommandContext(adapter="web", user_id=user_id, request_id=request_id, operation_id=operation_id)


async def _cultivator(runtime, user_id: str) -> None:
    for index, command in enumerate(
        (
            "开始修仙",
            "寻仙问道",
            "完成引导 阅读",
            "前往近郊",
            "完成引导 采集",
            "完成引导 炼丹",
            "选择道途 体修",
        )
    ):
        result = await runtime.dispatch(_context(user_id, f"setup-{index}"), command)
        assert result.ok


def test_breakthrough_preview_accepts_read_only_identity() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            user = "breakthrough-preview-reader"
            await _cultivator(runtime, user)

            result = await runtime.dispatch(
                CommandContext(
                    adapter="web",
                    user_id=user,
                    request_id="preview-read-only",
                    can_write_assets=False,
                ),
                "突破预览 聚气",
            )

            assert result.code == "BREAKTHROUGH_PREVIEW"
            assert result.data["target_realm"] == "qi_gathering"
            assert result.data["ready"] is False
            await runtime.close()

    asyncio.run(run())


def _prepare_player(runtime, user_id: str, *, inventory: dict[str, int], stones: int = 500, layer: int = 10, cultivation: int = 1360) -> None:
    import json

    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE players SET realm_key = 'qi_sensing', realm_layer = ?, cultivation = ?, total_cultivation = 1360, inventory_json = ?, spirit_stones = ? WHERE platform_user_id = ?",
            (layer, cultivation, json.dumps(inventory, ensure_ascii=False), stones, user_id),
        )


def _finish_breakthrough(runtime, session_id: str) -> None:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE breakthrough_sessions SET ends_at = ? WHERE session_id = ?",
            ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(), session_id),
        )


def test_breakthrough_rejects_l9_and_missing_cost_without_changes() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            user = "breakthrough-gate"
            await _cultivator(runtime, user)
            inventory = {"item.pill.focus_low": 1, "item.herb.spirit_leaf": 3}
            _prepare_player(runtime, user, inventory=inventory, stones=99, layer=9)
            rejected = await runtime.dispatch(_context(user, "l9"), "开始突破 聚气")
            assert rejected.code == "BREAKTHROUGH_REQUIREMENT_MISSING"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                row = connection.execute("SELECT spirit_stones, inventory_json FROM players WHERE platform_user_id = ?", (user,)).fetchone()
                assert row == (99, '{"item.pill.focus_low": 1, "item.herb.spirit_leaf": 3}')
            _prepare_player(runtime, user, inventory=inventory, stones=99, layer=10)
            missing = await runtime.dispatch(_context(user, "missing"), "开始突破 聚气")
            assert missing.code == "RESOURCE_INSUFFICIENT"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute("SELECT COUNT(*) FROM breakthrough_sessions").fetchone()[0] == 0
            await runtime.close()

    asyncio.run(run())


def test_breakthrough_failure_protection_and_weakness_recovery() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            user = "breakthrough-failure"
            await _cultivator(runtime, user)
            _prepare_player(
                runtime,
                user,
                inventory={
                    "item.pill.focus_low": 1,
                    "item.herb.spirit_leaf": 3,
                    "item.pill.qi_guard": 1,
                    "item.pill.healing_low": 1,
                },
            )
            operation_id = next(f"start-failure-{index}" for index in range(100) if breakthrough_roll_bp(f"start-failure-{index}") >= 8000)
            started = await runtime.dispatch(_context(user, "start", operation_id=operation_id), "开始突破 聚气 护脉")
            assert started.code == "BREAKTHROUGH_STARTED"
            _finish_breakthrough(runtime, started.data["session_id"])
            settled = await runtime.dispatch(_context(user, "settle", operation_id="settle-failure"), "结算突破")
            assert settled.code == "BREAKTHROUGH_FAILED"
            assert settled.data["cultivation_after"] == 1224
            assert settled.data["protection_consumed"] is True
            assert settled.data["pity_after_bp"] == 300
            replay = await runtime.dispatch(_context(user, "replay", operation_id="settle-failure"), "结算突破")
            assert replay.data["idempotent_replay"] is True
            early = await runtime.dispatch(_context(user, "recover", operation_id="recover-weakness"), "恢复虚弱 提前")
            assert early.code == "WEAKNESS_RECOVERED"
            assert early.data["medicine_consumed"] is True
            with sqlite3.connect(runtime.settings.database_path) as connection:
                row = connection.execute("SELECT weakness_until, breakthrough_pity_bp, cultivation FROM players WHERE platform_user_id = ?", (user,)).fetchone()
                assert row[0] is None
                assert row[1] == 300
                assert row[2] == 1224
            await runtime.close()

    asyncio.run(run())


def test_breakthrough_success_changes_realm_and_concurrent_start_is_unique() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            user = "breakthrough-success"
            await _cultivator(runtime, user)
            _prepare_player(
                runtime,
                user,
                inventory={
                    "item.pill.focus_low": 2,
                    "item.herb.spirit_leaf": 6,
                    "item.pill.qi_guard": 1,
                },
            )
            first, second = await asyncio.gather(
                runtime.dispatch(_context(user, "a", operation_id="same-start"), "开始突破 聚气"),
                runtime.dispatch(_context(user, "b", operation_id="other-start"), "开始突破 聚气"),
            )
            assert {first.code, second.code} == {"BREAKTHROUGH_STARTED", "BREAKTHROUGH_BUSY"}
            started = first if first.code == "BREAKTHROUGH_STARTED" else second
            _finish_breakthrough(runtime, started.data["session_id"])
            settled = await runtime.dispatch(_context(user, "settle", operation_id="settle-success"), "结算突破")
            assert settled.code == "BREAKTHROUGH_SUCCEEDED"
            assert settled.data["cultivation_after"] == 0
            profile = await runtime.dispatch(_context(user, "profile"), "我的状态")
            assert "聚气 L1" in profile.message
            with sqlite3.connect(runtime.settings.database_path) as connection:
                inventory = json.loads(
                    connection.execute(
                        "SELECT inventory_json FROM players WHERE platform_user_id = ?",
                        (user,),
                    ).fetchone()[0]
                )
            assert inventory["item.pill.qi_guard"] == 1
            await runtime.close()

    asyncio.run(run())


def test_foundation_breakthrough_failure_consumes_foundation_guard() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            user = "foundation-breakthrough-failure"
            await _cultivator(runtime, user)
            _prepare_player(
                runtime,
                user,
                inventory={
                    "item.pill.foundation_draft": 1,
                    "item.mat.array_sand": 3,
                    "item.ore.ironstone": 3,
                    "item.pill.foundation_guard": 1,
                },
                stones=1_000,
                layer=10,
                cultivation=2_900,
            )
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE players SET realm_key = 'qi_gathering', total_cultivation = 4260 WHERE platform_user_id = ?",
                    (user,),
                )
            operation_id = next(
                f"foundation-failure-{index}"
                for index in range(1000)
                if breakthrough_roll_bp(f"foundation-failure-{index}") >= 7500
            )
            started = await runtime.dispatch(
                _context(user, "foundation-start", operation_id=operation_id),
                "开始突破 筑基 筑基护脉丹",
            )
            assert started.code == "BREAKTHROUGH_STARTED"
            _finish_breakthrough(runtime, started.data["session_id"])
            settled = await runtime.dispatch(
                _context(user, "foundation-settle", operation_id="foundation-failure-settle"),
                "结算突破",
            )
            assert settled.code == "BREAKTHROUGH_FAILED"
            assert settled.data["protection_consumed"] is True
            assert settled.data["cultivation_after"] == 2465
            with sqlite3.connect(runtime.settings.database_path) as connection:
                inventory = json.loads(
                    connection.execute(
                        "SELECT inventory_json FROM players WHERE platform_user_id = ?",
                        (user,),
                    ).fetchone()[0]
                )
            assert inventory["item.pill.foundation_guard"] == 0
            await runtime.close()

    asyncio.run(run())


def test_foundation_breakthrough_uses_quality_snapshot_and_grants_cave_pass() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            user = "foundation-breakthrough"
            await _cultivator(runtime, user)
            _prepare_player(
                runtime,
                user,
                inventory={
                    "item.pill.foundation_draft": 1,
                    "item.mat.array_sand": 3,
                    "item.ore.ironstone": 3,
                    "item.manual.basic_qi": 1,
                },
                stones=1_000,
                layer=10,
                cultivation=2_900,
            )
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE players SET realm_key = 'qi_gathering', total_cultivation = 4260, foundation_quality = 5000, subprofession_key = 'formation' WHERE platform_user_id = ?",
                    (user,),
                )
            started = await runtime.dispatch(_context(user, "start", operation_id="foundation-start-0"), "开始突破 筑基")
            assert started.code == "BREAKTHROUGH_STARTED"
            assert started.data["success_bp"] == 8_600
            _finish_breakthrough(runtime, started.data["session_id"])
            settled = await runtime.dispatch(_context(user, "settle", operation_id="foundation-settle"), "结算突破")
            assert settled.code == "BREAKTHROUGH_SUCCEEDED"
            assert settled.data["target_realm"] == "foundation"
            assert settled.data["reward_world_merit"] == 50
            assert settled.data["reward_items"] == {"item.cave_pass_basic": 1}
            with sqlite3.connect(runtime.settings.database_path) as connection:
                row = connection.execute(
                    "SELECT realm_key, realm_layer, cultivation, world_merit, inventory_json, spirit_stones FROM players WHERE platform_user_id = ?",
                    (user,),
                ).fetchone()
                assert row[0:4] == ("foundation", 1, 0, 50)
                assert '"item.cave_pass_basic": 1' in row[4]
                assert row[5] == 500
            await runtime.close()

    asyncio.run(run())


def test_golden_core_breakthrough_success_grants_merit_and_local_reputation() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            user = "golden-core-success"
            await _cultivator(runtime, user)
            _prepare_player(
                runtime,
                user,
                inventory={
                    "item.pill.core_condense": 1,
                    "item.material.cloud_iron": 3,
                    "item.manual.basic_qi": 1,
                    "item.token.faction_seal": 1,
                },
                stones=2_000,
                layer=10,
                cultivation=7_700,
            )
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE players SET realm_key = 'foundation', total_cultivation = 11960, foundation_quality = 4000, location_key = 'xuantian.cloud_city' WHERE platform_user_id = ?",
                    (user,),
                )
            operation_id = next(
                f"golden-success-{index}"
                for index in range(1000)
                if breakthrough_roll_bp(f"golden-success-{index}") < 5_700
            )
            started = await runtime.dispatch(
                _context(user, "start", operation_id=operation_id),
                "开始突破 金丹",
            )
            assert started.code == "BREAKTHROUGH_STARTED"
            assert started.data["success_bp"] == 5_700
            _finish_breakthrough(runtime, started.data["session_id"])
            settled = await runtime.dispatch(
                _context(user, "settle", operation_id="golden-settle"),
                "结算突破",
            )
            assert settled.code == "BREAKTHROUGH_SUCCEEDED"
            assert settled.data["reward_world_merit"] == 100
            assert settled.data["reward_local_reputation"] == 50
            with sqlite3.connect(runtime.settings.database_path) as connection:
                row = connection.execute(
                    "SELECT realm_key, realm_layer, cultivation, total_cultivation, world_merit, spirit_stones FROM players WHERE platform_user_id = ?",
                    (user,),
                ).fetchone()
                reputation = connection.execute(
                    "SELECT local_json FROM player_reputations WHERE player_id = (SELECT id FROM players WHERE platform_user_id = ?)",
                    (user,),
                ).fetchone()
            assert row == ("golden_core", 1, 0, 11960, 100, 1_000)
            assert '"local.xuantian.new_town": 50' in reputation[0]
            await runtime.close()

    asyncio.run(run())


def test_golden_core_failure_protection_and_foundation_shock_recovery() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            user = "golden-core-failure"
            await _cultivator(runtime, user)
            _prepare_player(
                runtime,
                user,
                inventory={
                    "item.pill.core_condense": 1,
                    "item.material.cloud_iron": 3,
                    "item.pill.golden_core_guard": 1,
                    "item.pill.golden_core_restore": 1,
                },
                stones=2_000,
                layer=10,
                cultivation=7_700,
            )
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE players SET realm_key = 'foundation', total_cultivation = 11960, foundation_quality = 4000 WHERE platform_user_id = ?",
                    (user,),
                )
            operation_id = next(
                f"golden-failure-{index}"
                for index in range(1000)
                if breakthrough_roll_bp(f"golden-failure-{index}") >= 4_800
            )
            started = await runtime.dispatch(
                _context(user, "start", operation_id=operation_id),
                "开始突破 金丹 金丹护脉丹",
            )
            assert started.code == "BREAKTHROUGH_STARTED"
            assert started.data["success_bp"] == 4_800
            _finish_breakthrough(runtime, started.data["session_id"])
            settled = await runtime.dispatch(
                _context(user, "settle", operation_id="golden-failure-settle"),
                "结算突破",
            )
            assert settled.code == "BREAKTHROUGH_FAILED"
            assert settled.data["cultivation_after"] == 5_390
            assert settled.data["protection_consumed"] is True
            early = await runtime.dispatch(
                _context(user, "recover", operation_id="golden-recover"),
                "恢复道基震荡 提前",
            )
            assert early.code == "FOUNDATION_SHOCK_RECOVERED"
            assert early.data["spirit_stones_spent"] == 200
            assert early.data["medicine_key"] == "item.pill.golden_core_restore"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                row = connection.execute(
                    "SELECT weakness_until, breakthrough_pity_bp, spirit_stones, inventory_json FROM players WHERE platform_user_id = ?",
                    (user,),
                ).fetchone()
            assert row[0] is None
            assert row[1] == 500
            assert row[2] == 800
            assert '"item.pill.golden_core_restore": 0' in row[3]
            await runtime.close()

    asyncio.run(run())
