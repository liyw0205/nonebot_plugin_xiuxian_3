"""The city patrol opens a real fight, and the bandit enemy is combat-capable.

Settlement resolves an exploration battle inline: the repository starts the
fight, runs it to completion and returns the post-battle record. A settled
result therefore proves the battle ran, which this module checks against the
battle table rather than the command code.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from combat_fixtures import BALANCED_QUALIFICATION

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.combat.rules import enemy_definition
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle
from nonebot_plugin_xiuxian_3.xiuxian.exploration.rules import battle_roll_bp

DATA = Path(__file__).parents[1] / "data"
MODE = "explore.cloud_city_patrol"
POOL = "encounter.xuantian.cloud_city"
BATTLE_BP = 3_500


def _context(user: str, name: str, operation_id: str = "") -> CommandContext:
    return CommandContext(adapter="web", user_id=user, request_id=name, operation_id=operation_id)


def test_bandit_apprentice_is_a_supported_combat_enemy() -> None:
    bundle = ContentBundle.load(DATA)
    record = bundle.require("enemy", "enemy.bandit_apprentice")
    assert isinstance(record.get("combat_profile"), dict), "bandit must declare a combat profile"
    for field in ("hp", "attack", "initiative", "agility"):
        value = record["stats"].get(field)
        assert isinstance(value, int) and value >= 0, field
    definition = enemy_definition("enemy.bandit_apprentice", content=bundle)
    assert definition.key == "enemy.bandit_apprentice"


def test_cloud_city_patrol_declares_a_battle_pool() -> None:
    bundle = ContentBundle.load(DATA)
    mode = bundle.require("exploration_mode", MODE)
    assert mode["battle_chance_bp"] == BATTLE_BP
    assert mode["enemy_pool_key"] == POOL
    pool = bundle.require("encounter_pool", POOL)
    candidates = {row["enemy_key"] for row in pool["candidates"]}
    assert candidates == {"enemy.bandit_apprentice"}
    for enemy in candidates:
        assert bundle.get("enemy", enemy, include_locked=False) is not None, enemy


def test_cloud_city_patrol_settles_through_a_real_battle() -> None:
    async def run() -> None:
        clock_box = [datetime(2026, 9, 30, 21, tzinfo=timezone.utc)]
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=Path(data_dir), clock=lambda: clock_box[0])
            user = "patrol-battle"
            try:
                assert (await runtime.dispatch(_context(user, "create"), "开始修仙")).ok
                assert (await runtime.dispatch(_context(user, "seek"), "寻仙问道")).ok
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE players SET stage='cultivator', realm_key='golden_core', "
                        "realm_layer=1, location_key='xuantian.cloud_city', stamina=200, "
                        "stamina_max=200, max_hp=9000, initiative=9000, "
                        "qualification_json=? WHERE platform_user_id=?",
                        (json.dumps(BALANCED_QUALIFICATION), user),
                    )
                operation = next(
                    f"{user}-{index}"
                    for index in range(10_000)
                    if battle_roll_bp(f"{user}-{index}:battle") < BATTLE_BP
                )
                started = await runtime.dispatch(
                    _context(user, "start", operation), "开始探索 云城巡夜"
                )
                assert started.code == "EXPLORATION_STARTED", started
                clock_box[0] = clock_box[0] + timedelta(seconds=200)
                settled = await runtime.dispatch(_context(user, "settle"), "结算探索")
                # Settlement resolves the fight inline, so the final code is SETTLED.
                assert settled.code == "EXPLORATION_SETTLED", settled
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    rows = connection.execute(
                        "SELECT enemy_key FROM battle_sessions WHERE player_id="
                        "(SELECT id FROM players WHERE platform_user_id=?)",
                        (user,),
                    ).fetchall()
                assert len(rows) == 1, f"expected exactly one battle, got {rows}"
                assert rows[0][0] == "enemy.bandit_apprentice", rows
            finally:
                await runtime.close()

    asyncio.run(run())
