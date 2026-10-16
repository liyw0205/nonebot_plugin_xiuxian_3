from __future__ import annotations

import asyncio
import json
import shutil
import sqlite3
from pathlib import Path

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.world.rules import destination_definition


ROOT = Path(__file__).parents[1]

# Preserve the target-based fees previously charged by ordinary travel while
# making each incoming directed edge the sole runtime source of those values.
_LEGACY_TARGET_FEES = {
    "ascension.heaven_path": (5400, 0, 0, None, 0, 0),
    "ascension.left_world_hall": (1800, 10, 0, None, 0, 0),
    "beast.ancestral_lake": (600, 25, 0, None, 0, 0),
    "beast.ten_thousand_hills": (300, 12, 0, None, 0, 0),
    "beast.three_realms_trade_port": (180, 8, 0, None, 0, 0),
    "cave.ancient_domain": (0, 0, 0, None, 0, 0),
    "cave.boundary_realm": (600, 30, 0, None, 0, 0),
    "cave.mist_grotto": (120, 5, 10, "item.cave_pass_basic", 1, 0),
    "cave.mist_grotto_2": (180, 8, 0, "item.cave_pass_advanced", 1, 0),
    "cave.time_garden": (1800, 30, 0, "item.void_crystal", 1, 0),
    "dao.origin_gate": (3600, 20, 0, "item.dao_fruit_fragment", 2, 1),
    "dao_service": (0, 0, 0, None, 0, 0),
    "demon.abyss_depths": (0, 0, 0, None, 0, 0),
    "demon.abyss_gate": (120, 10, 0, None, 0, 0),
    "demon.abyss_market": (300, 12, 500, None, 0, 0),
    "demon.fallen_ruins": (480, 20, 0, None, 0, 0),
    "tribulation.sky_terrace": (1800, 0, 0, "item.tribulation_token", 1, 0),
    "void.archive_ruins": (2700, 40, 0, None, 0, 0),
    "void.first_route": (1800, 35, 0, None, 0, 0),
    "void.portal": (300, 10, 0, None, 0, 0),
    "xuantian.array_hall": (0, 0, 0, None, 0, 0),
    "xuantian.basalt_pass": (120, 5, 0, None, 0, 0),
    "xuantian.cloud_city": (180, 8, 0, None, 0, 0),
    "xuantian.cloud_mine": (120, 6, 0, None, 0, 0),
    "xuantian.domain_front": (300, 20, 0, None, 0, 0),
    "xuantian.floating_boat": (60, 0, 500, None, 0, 0),
    "xuantian.herb_vale": (60, 3, 0, None, 0, 0),
    "xuantian.ironwood_grove": (90, 4, 0, None, 0, 0),
    "xuantian.new_town": (0, 0, 0, None, 0, 0),
    "xuantian.outskirts": (30, 2, 0, None, 0, 0),
    "xuantian.sect_gate": (60, 3, 0, None, 0, 0),
    "xuantian.spirit_field": (90, 4, 0, None, 0, 0),
    "xuantian.war_front": (300, 15, 0, None, 0, 0),
}


def _documents() -> tuple[dict, dict]:
    locations = json.loads((ROOT / "data/地图/地点.json").read_text(encoding="utf-8"))
    regions = json.loads((ROOT / "data/地图/区域.json").read_text(encoding="utf-8"))
    return locations, regions


def _context(user: str, request: str, operation: str = "") -> CommandContext:
    return CommandContext(
        adapter="onebot.v11",
        user_id=user,
        request_id=request,
        operation_id=operation,
        can_write_assets=True,
    )


def test_every_incoming_route_preserves_legacy_target_cost_and_pass() -> None:
    _, region_document = _documents()
    incoming: dict[str, list[dict]] = {}
    for region in region_document["records"]:
        for edge in region["connections"]:
            incoming.setdefault(edge["to"], []).append(edge)

    assert set(incoming) == set(_LEGACY_TARGET_FEES)
    for target, edges in incoming.items():
        actual = {
            (
                edge["duration_seconds"],
                edge["stamina"],
                edge["spirit_stone"],
                edge.get("item_key"),
                edge.get("item_quantity", 0),
                edge.get("daily_start_limit", 0),
            )
            for edge in edges
        }
        assert actual == {_LEGACY_TARGET_FEES[target]}, target


def test_shared_gates_and_special_entry_edges_are_complete() -> None:
    location_document, region_document = _documents()
    locations = {row["key"]: row for row in location_document["records"]}
    edges = {
        (edge["from"], edge["to"]): edge
        for region in region_document["records"]
        for edge in region["connections"]
    }

    boundary_requirements = locations["cave.boundary_realm"]["requirements"]
    assert {json.dumps(item, sort_keys=True) for item in boundary_requirements} == {
        json.dumps({"type": "realm", "realm_key": "nascent_soul", "min_layer": 1}, sort_keys=True),
        json.dumps({"type": "intro_flag", "value": "story.mainline.three_realms"}, sort_keys=True),
    }

    dao_requirements = locations["dao.origin_gate"]["requirements"]
    assert any(
        item.get("type") == "dao_fruit_progress" and item.get("minimum") == 470
        for item in dao_requirements
    )
    dao_entries = [edge for edge in edges.values() if edge["to"] == "dao.origin_gate"]
    assert {edge["from"] for edge in dao_entries} == {
        "void.archive_ruins",
        "dao_service",
        "tribulation.sky_terrace",
    }
    assert all(
        edge.get("item_key") == "item.dao_fruit_fragment"
        and edge.get("item_quantity") == 2
        and edge.get("daily_start_limit") == 1
        for edge in dao_entries
    )

    sky_entries = [edge for edge in edges.values() if edge["to"] == "tribulation.sky_terrace"]
    assert {edge["from"] for edge in sky_entries} == {"dao.origin_gate", "ascension.heaven_path"}
    assert all(
        edge.get("item_key") == "item.tribulation_token" and edge.get("item_quantity") == 1
        for edge in sky_entries
    )

    assert "requirements" not in edges[("xuantian.war_front", "cave.boundary_realm")]


def test_current_content_bundle_accepts_the_audited_world_contract() -> None:
    bundle = ContentBundle.load(ROOT / "data")
    assert bundle.has("location", "cave.boundary_realm")
    assert bundle.has("world_region", "region.dao.origin")
    market = destination_definition("demon.abyss_market", bundle)
    hills = destination_definition("beast.ten_thousand_hills", bundle)
    assert (market.required_faction, market.required_faction_reputation) == ("demon", 200)
    assert (hills.required_faction, hills.required_faction_reputation) == ("beast", 200)


def test_dao_service_entry_checks_progress_before_charging_pass_or_resources(tmp_path: Path) -> None:
    async def run() -> None:
        data_dir = tmp_path / "data"
        shutil.copytree(ROOT / "data", data_dir)
        runtime = create_runtime(data_dir=data_dir)
        user = "dao-route-audit"
        await runtime.adapters.dispatch("onebot.v11", _context(user, "create"), "开始修仙")
        no_route = await runtime.adapters.dispatch(
            "onebot.v11", _context(user, "no-route"), "移动预览 天劫台"
        )
        assert no_route.data["route_available"] is False
        assert no_route.data["duration_seconds"] is None
        assert no_route.data["stamina_cost"] is None
        assert "当前位置没有通往此地的路线" in no_route.message
        assert "0 分钟" not in no_route.message

        with sqlite3.connect(runtime.settings.database_path) as connection:
            connection.execute(
                "UPDATE players SET stage='cultivator', realm_key='dao_union', realm_layer=6, "
                "location_key='dao_service', stamina=100, stamina_max=100, spirit_stones=1000, "
                "dao_fruit_progress=469, inventory_json=? "
                "WHERE platform='onebot.v11' AND platform_user_id=?",
                (json.dumps({"item.dao_fruit_fragment": 2}), user),
            )
            before = connection.execute(
                "SELECT stamina, spirit_stones, inventory_json, location_key FROM players "
                "WHERE platform='onebot.v11' AND platform_user_id=?",
                (user,),
            ).fetchone()

        preview = await runtime.adapters.dispatch(
            "onebot.v11", _context(user, "preview"), "移动预览 道源门"
        )
        assert preview.data["ready"] is False
        assert "道果进度" in preview.data["missing"]
        assert (preview.data["duration_seconds"], preview.data["stamina_cost"]) == (3600, 20)

        denied = await runtime.adapters.dispatch(
            "onebot.v11",
            _context(user, "denied", "denied-dao-entry"),
            "前往 道源门",
        )
        assert denied.code == "DAO_ORIGIN_REQUIREMENT_MISSING"
        with sqlite3.connect(runtime.settings.database_path) as connection:
            after = connection.execute(
                "SELECT stamina, spirit_stones, inventory_json, location_key FROM players "
                "WHERE platform='onebot.v11' AND platform_user_id=?",
                (user,),
            ).fetchone()
            assert after == before
            assert connection.execute(
                "SELECT COUNT(*) FROM operations WHERE operation_id='denied-dao-entry'"
            ).fetchone()[0] == 0
            connection.execute(
                "UPDATE players SET dao_fruit_progress=470 "
                "WHERE platform='onebot.v11' AND platform_user_id=?",
                (user,),
            )

        allowed_preview = await runtime.adapters.dispatch(
            "onebot.v11", _context(user, "preview-allowed"), "移动预览 道源门"
        )
        assert allowed_preview.data["ready"] is True
        started = await runtime.adapters.dispatch(
            "onebot.v11",
            _context(user, "start", "allowed-dao-entry"),
            "前往 道源门",
        )
        assert started.code == "TRAVEL_STARTED"
        with sqlite3.connect(runtime.settings.database_path) as connection:
            after_start = connection.execute(
                "SELECT stamina, spirit_stones, inventory_json, location_key FROM players "
                "WHERE platform='onebot.v11' AND platform_user_id=?",
                (user,),
            ).fetchone()
            assert (after_start[0], after_start[1], json.loads(after_start[2]), after_start[3]) == (
                80,
                1000,
                {},
                "dao_service",
            )
        await runtime.close()

    asyncio.run(run())
