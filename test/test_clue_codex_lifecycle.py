"""Every `item.clue.*` must reach the codex and come from a real producer.

`record_material_discoveries` maps an item key to `codex.material.<last suffix>`,
so a clue without a matching codex entry silently no-ops on acquisition. This
module pins the six clue entries, the two producers the clue set was missing, and
the real discovery projection at exploration settlement.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from combat_fixtures import BALANCED_QUALIFICATION

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle
from nonebot_plugin_xiuxian_3.xiuxian.exploration.rules import battle_roll_bp
from nonebot_plugin_xiuxian_3.xiuxian.rewards.rules import reward_pool_outcomes

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

CLUES = (
    "item.clue.recipe_basic",
    "item.clue.manual_basic",
    "item.clue.demon_contract",
    "item.clue.demon_abyss_echo",
    "item.clue.beast_bloodline",
    "item.clue.mist_cave_route",
)
# The two clues this phase gave a real producer.
MIST_CLUE = "item.clue.mist_cave_route"
ABYSS_CLUE = "item.clue.demon_abyss_echo"
MIST_POOL = "reward_pool.exploration.mist_grotto"
ABYSS_POOL = "reward_pool.exploration.demon_abyss"
MODE = "explore.mist_grotto"
LOCATION = "cave.mist_grotto"
BATTLE_BP = 2500


def _context(user: str, name: str, operation_id: str = "") -> CommandContext:
    return CommandContext(
        adapter="web", user_id=user, request_id=name, operation_id=operation_id
    )


def test_every_clue_reaches_an_active_codex_entry() -> None:
    bundle = ContentBundle.load(DATA)
    for clue in CLUES:
        assert bundle.require("item", clue)["item_type"] == "clue", clue
        suffix = clue.split(".")[-1]
        entry = bundle.get("codex_entry", f"codex.material.{suffix}", include_locked=False)
        assert entry is not None, f"{clue} has no codex.material.{suffix} entry"
        assert entry["category"] == "material", clue


def test_the_two_new_producers_actually_yield_their_clue() -> None:
    bundle = ContentBundle.load(DATA)
    for pool_key, clue in ((MIST_POOL, MIST_CLUE), (ABYSS_POOL, ABYSS_CLUE)):
        outcomes = reward_pool_outcomes(pool_key, bundle)
        assert any(rewards.get(clue, 0) > 0 for _, rewards in outcomes), (pool_key, clue)


def test_clue_source_declaration_covers_every_clue() -> None:
    bundle = ContentBundle.load(DATA)
    sources = {row["key"]: row for row in bundle.list("source", include_locked=False)}
    declared = {asset for row in sources.values() for asset in row.get("asset_keys") or []}
    assert set(CLUES) <= declared, set(CLUES) - declared


def test_settling_the_route_clue_pool_records_the_codex_discovery(tmp_path: Path) -> None:
    async def run() -> None:
        data_dir = tmp_path / "data"
        shutil.copytree(DATA, data_dir)
        # Force the mist pool to always hand over the route clue so the
        # projection is exercised deterministically.
        document = json.loads((data_dir / "奖励" / "奖励.json").read_text(encoding="utf-8"))
        pool = next(row for row in document["records"] if row["key"] == MIST_POOL)
        pool["outcomes"] = [{"weight": 1, "rewards": {"cultivation": 10, MIST_CLUE: 1}}]
        (data_dir / "奖励" / "奖励.json").write_text(
            json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        clock_box = [datetime(2026, 9, 30, 12, tzinfo=timezone.utc)]
        runtime = create_runtime(data_dir=data_dir, clock=lambda: clock_box[0])
        user = "clue-settle"
        try:
            assert (await runtime.dispatch(_context(user, "create"), "开始修仙")).ok
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE players SET stage='cultivator', realm_key='qi_gathering', "
                    "realm_layer=4, location_key=?, stamina=100, stamina_max=100, "
                    "qualification_json=?, inventory_json=? WHERE platform_user_id=?",
                    (
                        LOCATION,
                        json.dumps(BALANCED_QUALIFICATION),
                        json.dumps({"item.cave_pass_basic": 1}),
                        user,
                    ),
                )
            # Pick an operation whose battle roll stays calm so settlement pays
            # the pool directly.
            operation = next(
                f"{user}-{index}"
                for index in range(5_000)
                if battle_roll_bp(f"{user}-{index}:battle") >= BATTLE_BP
            )
            started = await runtime.dispatch(
                _context(user, "start", operation), "开始探索 雾隐洞天探索"
            )
            assert started.code == "EXPLORATION_STARTED", started
            clock_box[0] = clock_box[0] + timedelta(seconds=400)
            settled = await runtime.dispatch(_context(user, "settle"), "结算探索")
            assert settled.code == "EXPLORATION_SETTLED", settled
            assert settled.data["result"].get(MIST_CLUE) == 1, settled.data["result"]
            with sqlite3.connect(runtime.settings.database_path) as connection:
                entries = {
                    row[0]
                    for row in connection.execute(
                        "SELECT entry_key FROM codex_entries WHERE player_id="
                        "(SELECT id FROM players WHERE platform_user_id=?)",
                        (user,),
                    ).fetchall()
                }
            assert "codex.material.mist_cave_route" in entries, entries
        finally:
            await runtime.close()

    asyncio.run(run())
