from __future__ import annotations

import asyncio
import copy
import json
import sqlite3
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError
from nonebot_plugin_xiuxian_3.xiuxian.items.rules import item_records
from nonebot_plugin_xiuxian_3.xiuxian.material_content import validate_material_content
from nonebot_plugin_xiuxian_3.xiuxian.production.rules import recipe_definitions

DATA = Path(__file__).parents[1] / "data"
TIME_TRACE = "item.herb.time_trace"
TIME_WARD = "item.pill.time_ward"
GATHERING_ARRAY = "item.array.gathering_basic"


def _context(user_id: str, request_id: str, *, operation_id: str = ""):
    from nonebot_plugin_xiuxian_3.contracts import CommandContext

    return CommandContext(
        adapter="web",
        user_id=user_id,
        request_id=request_id,
        operation_id=operation_id,
    )


def test_time_craft_content_contract_closes_recipe_and_effect_references() -> None:
    bundle = ContentBundle.load(DATA)
    recipes = recipe_definitions(bundle)
    ward_recipe = recipes["recipe.pill.time_ward"]
    assert ward_recipe.profession == "alchemy"
    assert ward_recipe.inputs == {TIME_TRACE: 1, "item.herb.spirit_leaf": 2}
    assert ward_recipe.outputs == {TIME_WARD: 1}
    assert ward_recipe.success_threshold_bp == 4500
    assert ward_recipe.high_quality_threshold_bp == 8000
    assert ward_recipe.failure_refunds == {TIME_TRACE: 1, "item.herb.spirit_leaf": 1}
    assert ward_recipe.facility_kind == "alchemy"

    anchor_recipe = recipes["recipe.array.time_anchor"]
    assert anchor_recipe.profession == "formation"
    assert anchor_recipe.inputs == {TIME_TRACE: 2, "item.mat.array_sand": 1}
    assert anchor_recipe.outputs == {GATHERING_ARRAY: 1}
    assert anchor_recipe.facility_kind == "array"
    assert anchor_recipe.failure_refunds == {TIME_TRACE: 1, "item.mat.array_sand": 1}

    ward = item_records(bundle)[TIME_WARD]
    effects = [effect for effect in ward.effects if effect["type"] != "crafting_material"]
    assert effects == [
        {
            "type": "restore_choice",
            "resources": ["stamina"],
            "amount": 30,
            "cooldown_seconds": 300,
        }
    ]
    # The consumable effect stays inside the existing restore_choice
    # whitelist: resources are limited to stamina/energy/void_power and the
    # cooldown is a positive integer — no new effect types are introduced.
    row = next(
        record
        for record in bundle.list("item")
        if record["key"] == TIME_WARD
    )
    assert row["source_recipe_key"] == "recipe.pill.time_ward"
    assert validate_material_content(bundle)["recipe_consumers"] == 32


def test_time_ward_pill_restores_stamina_under_cooldown() -> None:
    async def run() -> None:
        with TemporaryDirectory() as temp:
            runtime = create_runtime(data_dir=Path(temp))
            user = "time-ward-user"
            assert (await runtime.dispatch(_context(user, "create"), "开始修仙")).ok
            assert (await runtime.dispatch(_context(user, "seek"), "寻仙问道")).ok
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE players SET stage='cultivator', realm_key='qi_sensing',"
                    " realm_layer=2, stamina=10, stamina_max=100, energy=30,"
                    " energy_max=30, inventory_json=? WHERE platform_user_id=?",
                    (json.dumps({TIME_WARD: 2}), user),
                )
            used = await runtime.dispatch(
                _context(user, "use"), f"使用 {TIME_WARD} 体力"
            )
            assert used.ok, (used.code, used.message)
            with sqlite3.connect(runtime.settings.database_path) as connection:
                stamina, inventory = connection.execute(
                    "SELECT stamina, inventory_json FROM players WHERE platform_user_id=?",
                    (user,),
                ).fetchone()
            assert stamina == 40
            assert json.loads(inventory)[TIME_WARD] == 1
            # Same-item cooldown blocks an immediate second use.
            blocked = await runtime.dispatch(
                _context(user, "use-again"), f"使用 {TIME_WARD} 体力"
            )
            assert not blocked.ok
            await runtime.close()

    asyncio.run(run())


def test_time_ward_recipe_crafts_through_the_alchemy_gate() -> None:
    async def run() -> None:
        with TemporaryDirectory() as temp:
            runtime = create_runtime(data_dir=Path(temp))
            user = "time-craft-user"
            commands = (
                "开始修仙",
                "寻仙问道",
                "完成引导 阅读",
                "前往近郊",
                "完成引导 采集",
                "完成引导 炼丹",
                "选择道途 辅修 炼丹",
            )
            for index, command in enumerate(commands):
                result = await runtime.dispatch(_context(user, f"setup-{index}"), command)
                assert result.ok, (command, result.code, result.message)
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE players SET realm_key='qi_sensing', realm_layer=2,"
                    " stamina=100, stamina_max=100, energy=30, energy_max=30,"
                    " inventory_json=? WHERE platform_user_id=?",
                    (
                        json.dumps(
                            {
                                TIME_TRACE: 3,
                                "item.herb.spirit_leaf": 6,
                                "item.tool.basic_furnace": 1,
                            }
                        ),
                        user,
                    ),
                )
            started = await runtime.dispatch(
                _context(user, "craft", operation_id="time-ward-craft"),
                "开始生产 时序护心丹",
            )
            assert started.ok, (started.code, started.message)
            await runtime.close()

    asyncio.run(run())


def test_time_ward_recipe_rejects_missing_inputs_atomically() -> None:
    async def run() -> None:
        with TemporaryDirectory() as temp:
            runtime = create_runtime(data_dir=Path(temp))
            user = "time-craft-broke"
            commands = (
                "开始修仙",
                "寻仙问道",
                "完成引导 阅读",
                "前往近郊",
                "完成引导 采集",
                "完成引导 炼丹",
                "选择道途 辅修 炼丹",
            )
            for index, command in enumerate(commands):
                result = await runtime.dispatch(_context(user, f"setup-{index}"), command)
                assert result.ok, (command, result.code, result.message)
            with sqlite3.connect(runtime.settings.database_path) as connection:
                # Only one of the two spirit leaves: the craft must fail with
                # zero writes (no partial consumption).
                connection.execute(
                    "UPDATE players SET realm_key='qi_sensing', realm_layer=2,"
                    " stamina=100, stamina_max=100, energy=30, energy_max=30,"
                    " inventory_json=? WHERE platform_user_id=?",
                    (
                        json.dumps({TIME_TRACE: 1, "item.herb.spirit_leaf": 1}),
                        user,
                    ),
                )
            failed = await runtime.dispatch(
                _context(user, "craft", operation_id="time-ward-broke"),
                "开始生产 时序护心丹",
            )
            assert not failed.ok
            with sqlite3.connect(runtime.settings.database_path) as connection:
                inventory = connection.execute(
                    "SELECT inventory_json FROM players WHERE platform_user_id=?",
                    (user,),
                ).fetchone()[0]
                orders = connection.execute(
                    "SELECT COUNT(*) FROM production_orders WHERE player_id ="
                    " (SELECT id FROM players WHERE platform_user_id=?)",
                    (user,),
                ).fetchone()[0]
            assert json.loads(inventory) == {TIME_TRACE: 1, "item.herb.spirit_leaf": 1}
            assert orders == 0
            await runtime.close()

    asyncio.run(run())
