from __future__ import annotations

import asyncio
import json
import sqlite3
import pytest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle
from nonebot_plugin_xiuxian_3.xiuxian.items.rules import item_records, resolve_item
from nonebot_plugin_xiuxian_3.xiuxian.livelihood.rules import (
    crop_definition,
    residence_definition,
)
from nonebot_plugin_xiuxian_3.xiuxian.material_content import validate_material_content
from nonebot_plugin_xiuxian_3.xiuxian.production.rules import recipe_definitions
from test_data_completion import Flow


DATA = Path(__file__).parents[1] / "data"


def _context(user: str, operation_id: str = "") -> CommandContext:
    return CommandContext(adapter="web", user_id=user, operation_id=operation_id)


def _seed_residence_requirement(runtime, user: str, *, reputation: int) -> None:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        player_id = connection.execute(
            "SELECT id FROM players WHERE platform_user_id = ?", (user,)
        ).fetchone()[0]
        connection.execute(
            "UPDATE players SET spirit_stones = 1000, energy = 30, inventory_json = ? WHERE id = ?",
            (json.dumps({"item.herb.spirit_leaf": 8}), player_id),
        )
        connection.execute(
            """
            INSERT INTO player_reputations(player_id, local_json, service_reputation, updated_at)
            VALUES (?, ?, 0, ?)
            ON CONFLICT(player_id) DO UPDATE SET local_json = excluded.local_json
            """,
            (player_id, json.dumps({"local.xuantian.new_town": reputation}), "2026-10-10T00:00:00+00:00"),
        )


def test_multi_plot_content_chain_is_closed_and_keeps_the_material_matrix() -> None:
    bundle = ContentBundle.load(DATA)
    residence = residence_definition("residence.herb_court", bundle)
    assert residence.plot_count == 2
    assert residence.rent_cost == 150
    assert residence.lease_days == 7
    assert residence.required_local_reputation == 60
    assert residence.local_reputation_key == "local.xuantian.new_town"

    crop = crop_definition("云纹稻", bundle)
    assert crop.key == "crop.cloud_rice"
    assert crop.residence_key == "residence.herb_court"
    assert crop.residence_keys == ("residence.herb_court",)
    assert crop.seed_key == "item.grain.cloud_rice"
    assert crop.seed_quantity == 1
    assert crop.maintained_harvest == {
        "item.grain.cloud_rice": 4,
        "item.herb.spirit_leaf": 1,
    }
    assert crop.unmaintained_harvest == {"item.grain.cloud_rice": 2}
    assert crop.daily_limit == 2
    assert crop.required_maintenance == 2
    assert crop.maintenance_energy == 1
    assert crop.reputation_key == "local.xuantian.new_town"
    assert crop.reputation_delta == 2
    assert crop.reputation_maximum == 1000

    recipes = recipe_definitions(bundle)
    recipe = recipes["recipe.food.cloud_rice_meal"]
    assert recipe.inputs == {"item.grain.cloud_rice": 3}
    assert recipe.outputs == {"item.food.cloud_rice_meal": 2}
    assert recipe.required_realm == "qi_sensing"
    assert recipe.success_threshold_bp == 4_500

    meal = resolve_item("云纹灵米饭", bundle)
    assert meal.effect_type == "restore_choice"
    assert meal.effect_value == 8
    assert meal.resources == ("stamina", "energy")
    assert resolve_item("云纹灵米饭", bundle).key == "item.food.cloud_rice_meal"
    assert item_records(bundle)["item.grain.cloud_rice"].name == "云纹稻谷"

    # The new crop chain must not widen the declared gathering matrix.
    assert validate_material_content(bundle) == {
        "materials": 14,
        "gathering_sources": 19,
        "modes": 11,
        "recipe_consumers": 33,
    }


def test_two_plots_grow_maintain_harvest_cook_and_survive_restart(tmp_path: Path) -> None:
    async def run() -> None:
        flow = Flow(tmp_path)
        try:
            await flow.enter("辅修 烹饪")
            flow.context(realm_key="qi_sensing", realm_layer=1)
            player_id = flow.player()["id"]
            with flow.runtime.repository._connect() as db:
                db.execute(
                    "UPDATE players SET spirit_stones = 1000, energy = 30 WHERE id = ?",
                    (player_id,),
                )
                db.execute(
                    """
                    INSERT INTO player_reputations(player_id, local_json, service_reputation, updated_at)
                    VALUES (?, ?, 0, ?)
                    ON CONFLICT(player_id) DO UPDATE SET local_json = excluded.local_json
                    """,
                    (player_id, json.dumps({"local.xuantian.new_town": 60}), "2026-10-10T00:00:00+00:00"),
                )
                inventory = json.loads(
                    db.execute(
                        "SELECT inventory_json FROM players WHERE id = ?", (player_id,)
                    ).fetchone()[0]
                )
                inventory["item.grain.cloud_rice"] = inventory.get("item.grain.cloud_rice", 0) + 8
                db.execute(
                    "UPDATE players SET inventory_json = ? WHERE id = ?",
                    (json.dumps(inventory), player_id),
                )

            leased = await flow.send("租住居所 灵圃小院", "multi-lease")
            assert leased.code == "RESIDENCE_LEASED"

            first = await flow.send("灵田播种 云纹稻", "multi-plant-1")
            assert first.code == "FIELD_PLOT_PLANTED"
            assert first.data["plot_index"] == 1
            second = await flow.send("灵田播种 云纹稻 2", "multi-plant-2")
            assert second.code == "FIELD_PLOT_PLANTED"
            assert second.data["plot_index"] == 2

            out_of_range = await flow.send("灵田播种 云纹稻 3", "multi-plant-3", ok=False)
            assert out_of_range.code == "INVALID_FIELD_SLOT"
            occupied = await flow.send("灵田播种 云纹稻 1", "multi-plant-4", ok=False)
            assert occupied.code == "FIELD_PLOT_BUSY"
            all_busy = await flow.send("灵田播种 云纹稻", "multi-plant-5", ok=False)
            assert all_busy.code == "FIELD_PLOT_BUSY"

            profile = await flow.send("我的灵田")
            assert profile.data["plot_count"] == 2
            assert [entry["plot_index"] for entry in profile.data["plots"]] == [1, 2]
            assert {entry["status"] for entry in profile.data["plots"]} == {"growing"}

            maintain_first = await flow.send("灵田维护 2", "multi-maintain-1")
            assert maintain_first.code == "FIELD_PLOT_MAINTAINED"
            assert maintain_first.data["plot_index"] == 2
            maintain_second = await flow.send("灵田维护 2", "multi-maintain-2")
            assert maintain_second.data["maintenance_count"] == 2
            bad_maintain = await flow.send("灵田维护 9", "multi-maintain-3", ok=False)
            assert bad_maintain.code == "INVALID_FIELD_SLOT"

            flow.now += timedelta(hours=6, seconds=1)
            first_harvest = await flow.send("灵田收获 1", "multi-harvest-1")
            assert first_harvest.code == "FIELD_PLOT_HARVESTED"
            assert first_harvest.data["plot_index"] == 1
            assert first_harvest.data["harvest"] == {"item.grain.cloud_rice": 2}
            second_harvest = await flow.send("灵田收获 2", "multi-harvest-2")
            assert second_harvest.code == "FIELD_PLOT_HARVESTED"
            assert second_harvest.data["plot_index"] == 2
            assert second_harvest.data["harvest"] == {
                "item.grain.cloud_rice": 4,
                "item.herb.spirit_leaf": 1,
            }
            repeated = await flow.send("灵田收获 2", "multi-harvest-3", ok=False)
            assert repeated.code == "FIELD_PLOT_ALREADY_HARVESTED"
            bad_harvest = await flow.send("灵田收获 4", "multi-harvest-4", ok=False)
            assert bad_harvest.code == "INVALID_FIELD_SLOT"

            replay = await flow.send("灵田收获 1", "multi-harvest-1")
            assert replay.data["idempotent_replay"] is True
            assert replay.data["harvest"] == {"item.grain.cloud_rice": 2}
            conflict = await flow.send("灵田维护", "multi-harvest-1", ok=False)
            assert conflict.code == "OPERATION_CONFLICT"

            # Same-day planting quota is shared by both plots.
            quota = await flow.send("灵田播种 云纹稻 1", "multi-plant-6", ok=False)
            assert quota.code == "CROP_DAILY_LIMIT"

            _, produced = await flow.produce("云纹灵米饭", operation="multi-cook")
            assert produced.data["outputs"] == {"item.food.cloud_rice_meal": 2}
            # 8 seeded - 2 sown + 6 harvested - 3 cooked = 9
            assert flow.inventory()["item.grain.cloud_rice"] == 9
            assert flow.inventory()["item.food.cloud_rice_meal"] == 2
            used = await flow.send("使用物品 云纹灵米饭 精力", "multi-use")
            assert used.data["effect"]["restored"] > 0
            used_replay = await flow.send("使用物品 云纹灵米饭 精力", "multi-use")
            assert used_replay.data["idempotent_replay"] is True

            with sqlite3.connect(flow.runtime.settings.database_path) as db:
                rows = db.execute(
                    "SELECT plot_index, status FROM field_plots ORDER BY plot_index"
                ).fetchall()
                assert rows == [(1, "harvested"), (2, "harvested")]
        finally:
            await flow.runtime.close()

        flow.runtime = create_runtime(
            data_dir=flow.root, clock=lambda: flow.now, adapters=("onebot.v11",)
        )
        try:
            profile = await flow.send("我的灵田")
            assert profile.data["plot_count"] == 2
            assert [entry["plot_index"] for entry in profile.data["plots"]] == [1, 2]
            assert {entry["status"] for entry in profile.data["plots"]} == {"harvested"}
            assert flow.inventory()["item.grain.cloud_rice"] == 9
            assert flow.inventory()["item.food.cloud_rice_meal"] == 1
        finally:
            await flow.runtime.close()

    asyncio.run(run())


def test_corrupt_second_plot_snapshot_rolls_back_without_touching_the_first(
    tmp_path: Path,
) -> None:
    async def run() -> None:
        flow = Flow(tmp_path)
        try:
            await flow.enter("辅修 烹饪")
            flow.context(realm_key="qi_sensing", realm_layer=1)
            player_id = flow.player()["id"]
            with flow.runtime.repository._connect() as db:
                db.execute(
                    "UPDATE players SET spirit_stones = 1000, energy = 30 WHERE id = ?",
                    (player_id,),
                )
                db.execute(
                    """
                    INSERT INTO player_reputations(player_id, local_json, service_reputation, updated_at)
                    VALUES (?, ?, 0, ?)
                    ON CONFLICT(player_id) DO UPDATE SET local_json = excluded.local_json
                    """,
                    (player_id, json.dumps({"local.xuantian.new_town": 60}), "2026-10-10T00:00:00+00:00"),
                )
                inventory = json.loads(
                    db.execute(
                        "SELECT inventory_json FROM players WHERE id = ?", (player_id,)
                    ).fetchone()[0]
                )
                inventory["item.grain.cloud_rice"] = inventory.get("item.grain.cloud_rice", 0) + 6
                db.execute(
                    "UPDATE players SET inventory_json = ? WHERE id = ?",
                    (json.dumps(inventory), player_id),
                )
            await flow.send("租住居所 灵圃小院", "corrupt-lease")
            first = await flow.send("灵田播种 云纹稻", "corrupt-plant-1")
            second = await flow.send("灵田播种 云纹稻 2", "corrupt-plant-2")
            flow.now += timedelta(hours=6, seconds=1)
            with sqlite3.connect(flow.runtime.settings.database_path) as db:
                raw = db.execute(
                    "SELECT snapshot_json FROM field_plots WHERE plot_id = ?",
                    (second.data["plot_id"],),
                ).fetchone()[0]
                damaged = raw.replace(
                    '"maintained_harvest": {',
                    '"maintained_harvest": {"item.grain.cloud_rice": 9, "unexpected": "x", ',
                    1,
                ) if '"maintained_harvest": {' in raw else raw
                db.execute(
                    "UPDATE field_plots SET snapshot_json = ? WHERE plot_id = ?",
                    (damaged, second.data["plot_id"]),
                )
            before = flow.dump()
            with pytest.raises(ValueError):
                await flow.send("灵田收获 2", "corrupt-harvest-1", ok=False)
            assert flow.dump() == before

            with sqlite3.connect(flow.runtime.settings.database_path) as db:
                db.execute(
                    "UPDATE field_plots SET snapshot_json = ? WHERE plot_id = ?",
                    (raw, second.data["plot_id"]),
                )
            retried = await flow.send("灵田收获 2", "corrupt-harvest-1")
            assert retried.code == "FIELD_PLOT_HARVESTED"
            assert retried.data["harvest"] == {
                "item.grain.cloud_rice": 2,
            }
            untouched = await flow.send("灵田收获 1", "corrupt-harvest-2")
            assert untouched.code == "FIELD_PLOT_HARVESTED"
            assert untouched.data["harvest"] == {"item.grain.cloud_rice": 2}
            assert first.data["plot_id"] != second.data["plot_id"]
        finally:
            await flow.runtime.close()

    asyncio.run(run())


def test_single_plot_residence_keeps_the_old_busy_semantics_and_schema_migrates() -> None:
    async def run() -> None:
        clock_now = datetime(2026, 9, 22, tzinfo=timezone.utc)
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=lambda: clock_now)
            user = "single-plot-user"
            try:
                assert (await runtime.dispatch(_context(user), "开始修仙")).ok
                assert (await runtime.dispatch(_context(user), "寻仙问道")).ok
                _seed_residence_requirement(runtime, user, reputation=40)
                leased = await runtime.dispatch(_context(user, "lease"), "租住居所 小院")
                assert leased.code == "RESIDENCE_LEASED"
                first = await runtime.dispatch(_context(user, "plant-1"), "灵田播种 灵叶")
                assert first.code == "FIELD_PLOT_PLANTED"
                assert first.data["plot_index"] == 1
                second = await runtime.dispatch(_context(user, "plant-2"), "灵田播种 灵叶")
                assert second.code == "FIELD_PLOT_BUSY"
                profile = await runtime.dispatch(_context(user), "我的灵田")
                assert profile.data["plot_count"] == 1
                assert [entry["plot_index"] for entry in profile.data["plots"]] == [1]

                path = runtime.settings.database_path
            finally:
                await runtime.close()

            with sqlite3.connect(path) as db:
                columns = {
                    row[1] for row in db.execute("PRAGMA table_info(field_plots)").fetchall()
                }
                assert "plot_index" in columns
                indexes = {
                    row[1] for row in db.execute("PRAGMA index_list(field_plots)").fetchall()
                }
                assert "idx_field_plots_slot" in indexes
                assert "idx_field_plots_active" not in indexes
                assert db.execute(
                    "SELECT plot_index FROM field_plots ORDER BY id"
                ).fetchall() == [(1,)]

            # Repeated initialization must not fail or duplicate the slot index.
            runtime = create_runtime(data_dir=data_dir, clock=lambda: clock_now)
            await runtime.initialize()
            await runtime.close()

    asyncio.run(run())
