from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.companions.rules import (
    companion_definitions,
    companion_evolution_definitions,
)
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle

DATA = Path(__file__).parents[1] / "data"


def _context(user_id: str, request_id: str, *, operation_id: str = "") -> CommandContext:
    return CommandContext(
        adapter="web",
        user_id=user_id,
        request_id=request_id,
        operation_id=operation_id,
    )


def test_companion_evolutions_close_references_and_stay_single_edge() -> None:
    bundle = ContentBundle.load(DATA)
    companions = companion_definitions(bundle)
    evolutions = companion_evolution_definitions(bundle)

    # Three edges: wood_rat -> iron_rat (existing), iron_rat -> jade_rat and
    # bamboo_deer -> cloud_elk (this slice). Each source keeps exactly one
    # outgoing edge — evolution lookup resolves by source_key, so multi-edge
    # sources would be ambiguous — and the runtime pins a companion after one
    # evolution (evolution_stage = evolved), so chained edges never fire.
    assert len(evolutions) == 3
    by_source: dict[str, int] = {}
    for definition in evolutions.values():
        by_source[definition.source_key] = by_source.get(definition.source_key, 0) + 1
    assert all(count == 1 for count in by_source.values())

    lineage = {
        "beast.evolution.wood_rat_1": ("beast.wood_rat", "beast.iron_rat", 10, 40, 1),
        "beast.evolution.iron_rat_2": ("beast.iron_rat", "beast.jade_rat", 18, 60, 2),
        "mount.evolution.bamboo_deer_1": ("mount.bamboo_deer", "mount.cloud_elk", 12, 50, 1),
    }
    for key, (source, target, level, affinity, slots) in lineage.items():
        definition = evolutions[key]
        assert (definition.source_key, definition.target_key) == (source, target)
        assert definition.required_level == level
        assert definition.required_affinity == affinity
        assert definition.skill_slots == slots
        assert definition.success_bp == 10000
        assert definition.kind == companions[source].kind
        assert companions[target].kind == definition.kind
        # Both endpoints must be active records that exist in content.
        assert source in companions and target in companions
        # Evolution targets carry the companion.evolution source marker.
        assert "companion.evolution" in companions[target].source

    # New form records keep the discovery-effect family and extend ranges.
    assert companions["beast.jade_rat"].level_max == 30
    assert companions["mount.cloud_elk"].level_max == 25
    elk_effect = companions["mount.cloud_elk"].effect or {}
    assert elk_effect["value"] == 500
    # Costs only reference existing closed assets (no invented materials).
    for definition in evolutions.values():
        for cost_key in definition.costs:
            if cost_key.startswith("item."):
                assert bundle.has("item", cost_key, include_locked=False)


def test_evolution_edges_fire_for_both_kinds() -> None:
    async def run() -> None:
        with TemporaryDirectory() as temp:
            runtime = create_runtime(data_dir=Path(temp))
            user = "evolution-user"
            assert (
                await runtime.dispatch(_context(user, "create"), "开始修仙")
            ).ok
            assert (
                await runtime.dispatch(_context(user, "seek"), "寻仙问道")
            ).ok
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE players SET stage='cultivator', realm_key='qi_sensing',"
                    " realm_layer=2, stamina=100, stamina_max=100, energy=30,"
                    " energy_max=30, spirit_stones=100000, inventory_json=?"
                    " WHERE platform_user_id=?",
                    (
                        json.dumps(
                            {
                                "item.ancient_fruit": 3,
                                "item.ancestral_blood": 2,
                                "item.beast_blood": 2,
                            }
                        ),
                        user,
                    ),
                )
                connection.execute(
                    "INSERT INTO companion_instances (instance_id, player_id,"
                    " companion_key, kind, status, level, experience, affinity,"
                    " stamina, evolution_stage, skill_slots, deployed, snapshot_json,"
                    " created_at, updated_at)"
                    " VALUES ('inst-iron-1',"
                    " (SELECT id FROM players WHERE platform_user_id=?),"
                    " 'beast.iron_rat', 'beast', 'active', 18, 0, 60, 50,"
                    " 'base', 1, 0, '{}', datetime('now'), datetime('now'))",
                    (user,),
                )
                connection.execute(
                    "INSERT INTO companion_instances (instance_id, player_id,"
                    " companion_key, kind, status, level, experience, affinity,"
                    " stamina, evolution_stage, skill_slots, deployed, snapshot_json,"
                    " created_at, updated_at)"
                    " VALUES ('inst-deer-1',"
                    " (SELECT id FROM players WHERE platform_user_id=?),"
                    " 'mount.bamboo_deer', 'mount', 'active', 12, 0, 50, 50,"
                    " 'base', 1, 0, '{}', datetime('now'), datetime('now'))",
                    (user,),
                )
            # Beast edge: iron_rat -> jade_rat.
            first = await runtime.dispatch(
                _context(user, "evo-1", operation_id="evo-1"), "蜕变灵兽 inst-iron-1"
            )
            assert first.ok, (first.code, first.message)
            # Mount edge: bamboo_deer -> cloud_elk.
            second = await runtime.dispatch(
                _context(user, "evo-2", operation_id="evo-2"), "蜕变灵兽 inst-deer-1"
            )
            assert second.ok, (second.code, second.message)
            with sqlite3.connect(runtime.settings.database_path) as connection:
                rows = connection.execute(
                    "SELECT companion_key, evolution_stage, skill_slots FROM"
                    " companion_instances WHERE player_id=(SELECT id FROM players"
                    " WHERE platform_user_id=?) ORDER BY companion_key",
                    (user,),
                ).fetchall()
            assert (rows[0][0], rows[0][1], rows[0][2]) == ("beast.jade_rat", "evolved", 2)
            assert (rows[1][0], rows[1][1], rows[1][2]) == ("mount.cloud_elk", "evolved", 1)
            # An evolved instance is pinned: evolving again is rejected even
            # with materials on hand.
            third = await runtime.dispatch(
                _context(user, "evo-3", operation_id="evo-3"), "蜕变灵兽 inst-iron-1"
            )
            assert not third.ok
            await runtime.close()

    asyncio.run(run())
