"""Contract for the war-front ward array, its recipe and the evolution codex.

P3 adds a third array (`item.array.war_front_ward`) whose risk reduction names
`xuantian.war_front`, produced by a new formation recipe from a material the
P1 war-front pool actually drops. P4 makes the two evolution creatures reachable
in the codex and adds a milestone over them.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.companions.rules import companion_definition
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle
from nonebot_plugin_xiuxian_3.xiuxian.exploration.rules import battle_roll_bp
from nonebot_plugin_xiuxian_3.xiuxian.items.rules import resolve_item

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

WARD = "item.array.war_front_ward"
WARD_RECIPE = "recipe.array.war_front_ward"
PLATE = "item.material.ward_plate"
WAR_FRONT = "xuantian.war_front"
MODE = "explore.war_front_patrol"
CHANCE = 3000
CREATURE_ENTRIES = {
    "beast.jade_rat": "codex.creature.jade_rat",
    "mount.cloud_elk": "codex.creature.cloud_elk",
}


def _bundle() -> ContentBundle:
    return ContentBundle.load(DATA)


def _context(user: str, name: str, operation_id: str = "") -> CommandContext:
    return CommandContext(
        adapter="web", user_id=user, request_id=name, operation_id=operation_id
    )


def test_war_front_ward_item_and_recipe_contract() -> None:
    bundle = _bundle()
    definition = resolve_item(WARD, bundle)
    assert definition.effect_type == "exploration_risk_reduction_bp"
    assert definition.effect_value == 600
    assert definition.location_key == WAR_FRONT
    assert definition.duration_seconds == 43200

    # The recipe must consume the material the war-front pool actually drops.
    recipe = bundle.require("recipe", WARD_RECIPE)
    assert recipe["outputs"] == {WARD: 1}
    assert PLATE in recipe["inputs"]
    assert bundle.require("item", PLATE)["gathering_sources"][0]["mode_key"] == MODE


def test_evolution_creatures_are_named_in_the_codex() -> None:
    bundle = _bundle()
    for companion_key, entry_key in CREATURE_ENTRIES.items():
        definition = companion_definition(companion_key, bundle)
        assert definition.codex_entry_key == entry_key
        assert bundle.get("codex_entry", entry_key, include_locked=False) is not None


def test_evolution_milestone_covers_both_creatures() -> None:
    bundle = _bundle()
    milestones = {row["key"]: row for row in bundle.list("codex_milestone", include_locked=False)}
    group = milestones["codex.creature.evolutions_two"]
    assert set(group["entry_keys"]) == set(CREATURE_ENTRIES.values())
    assert group["reward"]["amount"] > 0
    assert group["unlocks"] == []


def test_war_front_ward_is_produced_and_used_only_at_the_front() -> None:
    async def run() -> None:
        now = datetime(2026, 9, 30, 12, tzinfo=timezone.utc)
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=lambda: now)
            user = "ward-run"
            try:
                assert (await runtime.dispatch(_context(user, "create"), "开始修仙")).ok
                assert (await runtime.dispatch(_context(user, "seek"), "寻仙问道")).ok
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE players SET stage='cultivator', realm_key='nascent_soul', "
                        "realm_layer=1, location_key=?, stamina=200, stamina_max=200, "
                        "energy=40, energy_max=40, spirit_stones=500, "
                        "inventory_json=? WHERE platform_user_id=?",
                        (
                            WAR_FRONT,
                            json.dumps(
                                {
                                    "item.material.ward_plate": 4,
                                    "item.mat.array_sand": 4,
                                    WARD: 1,
                                }
                            ),
                            user,
                        ),
                    )
                used = await runtime.dispatch(
                    _context(user, "ward-use", "ward-use-op"),
                    "使用 战线护阵 魔界战线",
                )
                assert used.code == "ITEM_USED", used

                # Using it from the wrong location must refuse.
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE players SET location_key='xuantian.new_town', inventory_json=? "
                        "WHERE platform_user_id=?",
                        (json.dumps({WARD: 1}), user),
                    )
                wrong = await runtime.dispatch(
                    _context(user, "ward-wrong", "ward-wrong-op"),
                    "使用 战线护阵 魔界战线",
                )
                assert wrong.code == "ITEM_LOCATION_REQUIRED", wrong

                # Back at the front, a second ward of the same kind must not
                # stack: the first one is still active.
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE players SET location_key=?, inventory_json=? WHERE platform_user_id=?",
                        (WAR_FRONT, json.dumps({WARD: 1}), user),
                    )
                stacked = await runtime.dispatch(
                    _context(user, "ward-stack", "ward-stack-op"), "使用 战线护阵 魔界战线"
                )
                assert stacked.code == "ITEM_EFFECT_ALREADY_ACTIVE", stacked

                # The active ward still reduces the front's battle chance.
                operation = next(
                    f"{user}-calm-{index}"
                    for index in range(10_000)
                    if battle_roll_bp(f"{user}-calm-{index}:battle") >= CHANCE
                )
                started = await runtime.dispatch(
                    _context(user, "start", operation), "开始探索 战线巡防"
                )
                assert started.code == "EXPLORATION_STARTED", started
                assert started.data["risk_reduction_bp"] == 600
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    snapshot = json.loads(
                        connection.execute(
                            "SELECT snapshot_json FROM exploration_sessions WHERE mode_key=?",
                            (MODE,),
                        ).fetchone()[0]
                    )
                assert snapshot["base_battle_chance_bp"] == CHANCE
                assert snapshot["battle_chance_bp"] == CHANCE - 600
            finally:
                await runtime.close()

    asyncio.run(run())
