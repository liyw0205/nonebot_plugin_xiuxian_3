from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import timedelta
from urllib.parse import quote

import pytest

from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.production.rules import (
    MAX_PRODUCTION_BATCH,
    ProductionBatchError,
    production_batch_count,
    production_batch_supported,
    random_quality_bp,
    recipe_definitions,
)
from test_wilderness_idle import Clock, change_content, move, send, starter
from test_player_interaction import _links


def state(runtime):
    with sqlite3.connect(runtime.settings.database_path) as connection:
        return tuple(connection.iterdump())


def player(runtime):
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.row_factory = sqlite3.Row
        return dict(connection.execute("SELECT * FROM players WHERE platform_user_id='gatherer'").fetchone())


async def preview_batch(runtime, command):
    def assets():
        with sqlite3.connect(runtime.settings.database_path) as connection:
            return {table: connection.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
                for table in ("players", "production_orders", "operations", "equipment_instances", "economy_ledger_entries", "player_reputations", "codex_entries")}
    before = assets()
    result = await send(runtime, command)
    assert result.ok, result.message
    assert assets() == before
    with sqlite3.connect(runtime.settings.database_path) as connection:
        event = connection.execute("SELECT payload_json FROM activity_events WHERE event_key='production.preview' AND source_operation_id=?", (result.operation_id,)).fetchone()
    assert json.loads(event[0]) == {"recipe_key": result.data["recipe_key"], "batch_count": result.data["batch_count"]}
    return result


def roll_operation(prefix, roll=1000):
    return next(f"{prefix}-{i}" for i in range(1000) if random_quality_bp(f"{prefix}-{i}") == roll)


async def prepared(runtime, *, profession="炼丹", recipe_key="recipe.pill.healing_low"):
    await starter(runtime, path=f"辅修 {profession}")
    recipe = recipe_definitions()[recipe_key]
    inventory = {key: quantity * 20 for key, quantity in recipe.inputs.items()}
    if recipe.tool_key:
        inventory[recipe.tool_key] = 1
    # Transaction fixtures, not evidence of public material acquisition.
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE players SET realm_key=?, realm_layer=10, energy=100, energy_max=100, "
            "spirit_stones=100000, inventory_json=? WHERE platform_user_id='gatherer'",
            (recipe.required_realm, json.dumps(inventory)),
        )


@pytest.mark.parametrize("bad", [True, False, 0, -1, 6, 1.0, "2", None, 10**100])
def test_batch_count_is_an_exact_bounded_integer(bad):
    with pytest.raises(ProductionBatchError):
        production_batch_count(bad)
    assert MAX_PRODUCTION_BATCH == 5
    assert [production_batch_count(i) for i in range(1, 6)] == list(range(1, 6))


@pytest.mark.parametrize("profession, recipe_key, item_key, destination", [
    ("烹饪", "recipe.food.spirit_rice", "item.food.spirit_rice", "体力"),
    ("炼丹", "recipe.pill.healing_low", "item.pill.healing_low", ""),
])
def test_public_materials_batch_restart_claim_and_actual_use(tmp_path, profession, recipe_key, item_key, destination):
    async def run():
        clock = Clock()
        runtime = create_runtime(data_dir=tmp_path, clock=clock)
        try:
            await starter(runtime, path=f"辅修 {profession}")
            # Reuse established realm/capacity growth; materials and tools stay publicly acquired.
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute("UPDATE players SET realm_key='qi_gathering', realm_layer=1, energy=100, energy_max=100, stamina=100, stamina_max=100")
            if profession == "炼丹":
                await move(runtime, clock, "百草坡")
                assert (await send(runtime, "开始挂机 百草坡采药", "public-herbs")).ok
                clock.advance(hours=4)
                assert (await send(runtime, "领取挂机", "public-herbs-claim")).ok
                await move(runtime, clock, "近郊")
            await move(runtime, clock, "青石镇")
            await move(runtime, clock, "灵泉谷")
            assert (await send(runtime, "开始挂机 灵泉谷拾穗", "public-rice")).ok
            clock.advance(hours=4)
            assert (await send(runtime, "领取挂机", "public-rice-claim")).ok
            before = player(runtime)
            materials = json.loads(before["inventory_json"])
            recipe = recipe_definitions()[recipe_key]
            assert all(materials.get(key, 0) >= quantity * 2 for key, quantity in recipe.inputs.items())
            preview = await preview_batch(runtime, f"生产预览 {recipe.name} 2")
            assert preview.ok and preview.data["batch_count"] == 2, preview.message
            assert preview.data["inputs"] == {key: value * 2 for key, value in recipe.inputs.items()}
            assert preview.data["outputs"] == {key: value * 2 for key, value in recipe.outputs.items()}
            assert preview.data["duration_seconds"] == recipe.duration_seconds * 2
            operation = roll_operation("public-batch")
            started = await send(runtime, f"开始生产 {recipe.name} 2", operation)
            assert started.code == "PRODUCTION_STARTED", started.message
            after = player(runtime)
            assert after["energy"] == before["energy"] - recipe.energy_cost * 2
            assert json.loads(after["inventory_json"]) == {
                key: value - recipe.inputs.get(key, 0) * 2 for key, value in materials.items()
                if value - recipe.inputs.get(key, 0) * 2 > 0
            }
            if recipe.tool_key:
                assert json.loads(after["durability_json"])[recipe.tool_key] == 1800
            baseline = state(runtime)
            status = await send(runtime, "生产行程")
            assert status.ok and status.data["order"]["batch_count"] == 2 and not status.actions
            early = await send(runtime, "领取生产", "public-claim")
            assert early.code == "PRODUCTION_NOT_READY" and state(runtime) == baseline
            await runtime.close()

            def close_recipe(records):
                records["recipe", recipe_key].update(name="已关闭的新名称", status="locked", outputs={item_key: 999})
            runtime = create_runtime(data_dir=tmp_path, clock=clock)
            runtime.repository.content = change_content(close_recipe)
            clock.advance(seconds=recipe.duration_seconds * 2)
            assert (await send(runtime, f"开始生产 {recipe_key} 2", operation)).data["idempotent_replay"]
            baseline = state(runtime)
            status = await send(runtime, "生产状态")
            assert status.data["order"]["recipe_name"] == recipe.name
            assert len(status.actions) == 1 and status.actions[0].command == "领取生产" and status.actions[0].enter
            assert state(runtime) == baseline
            claimed = await send(runtime, status.actions[0].command, "public-claim")
            assert claimed.code == "PRODUCTION_COMPLETED" and claimed.data["success"], claimed.message
            assert claimed.data["outputs"] == {key: value * 2 for key, value in recipe.outputs.items()}
            assert claimed.data["batch_count"] == 2
            baseline = state(runtime)
            replay = await send(runtime, "领取生产", "public-claim")
            assert replay.data["idempotent_replay"] and replay.message == claimed.message
            assert (await send(runtime, "生产状态")).data["order"]["status"] == "completed"
            assert state(runtime) == baseline
            denied = await send(runtime, f"开始生产 {recipe_key} 2", "closed-new")
            assert denied.code == "RECIPE_NOT_FOUND" and state(runtime) == baseline
            with sqlite3.connect(runtime.settings.database_path) as connection:
                # An injury fixture avoids replaying the delivered breakthrough chain.
                connection.execute("UPDATE players SET stamina=1, weakness_until=?", ((clock() + timedelta(hours=1)).isoformat(),))
            before_use = player(runtime)
            command = f"使用 {item_key} {destination}" if destination else "恢复虚弱 提前"
            used = await send(runtime, command, "public-use")
            assert used.ok, used.message
            after_use = player(runtime)
            assert json.loads(after_use["inventory_json"])[item_key] == claimed.data["outputs"][item_key] - 1
            if destination:
                assert after_use["stamina"] > before_use["stamina"]
            else:
                assert before_use["weakness_until"] and after_use["weakness_until"] is None
                assert after_use["spirit_stones"] == before_use["spirit_stones"] - 50
            baseline = state(runtime)
            assert (await send(runtime, command, "public-use")).data["idempotent_replay"]
            assert state(runtime) == baseline
        finally:
            await runtime.close()
    asyncio.run(run())


def test_batch_arguments_special_boundaries_and_shortages_are_zero_write(tmp_path):
    async def run():
        clock = Clock()
        runtime = create_runtime(data_dir=tmp_path, clock=clock)
        try:
            await prepared(runtime)
            for quantity in ("0", "6", "-1", "2.0", "True", "份数", "2 extra", "9" * 5000):
                baseline = state(runtime)
                for verb in ("生产预览", "开始生产"):
                    result = await send(runtime, f"{verb} 疗伤丹 {quantity}", "invalid")
                    assert result.code == "PRODUCTION_BATCH_INVALID"
                    assert state(runtime) == baseline
            recipes = recipe_definitions()
            singles = [recipe for recipe in recipes.values() if not production_batch_supported(recipe)]
            assert singles and any(recipe.key.startswith("recipe.permit.") for recipe in singles)
            baseline = state(runtime)
            for recipe in singles:
                for verb in ("生产预览", "开始生产"):
                    result = await send(runtime, f"{verb} {recipe.key} 2", "single-only")
                    assert result.code == "PRODUCTION_BATCH_INVALID", (recipe.key, result.code)
                    assert state(runtime) == baseline
            for field, value, code in (
                ("energy", 7, "ENERGY_INSUFFICIENT"),
                ("durability_json", '{"item.tool.basic_furnace":199}', "TOOL_DURABILITY_INSUFFICIENT"),
                ("inventory_json", '{"item.herb.blood_grass":3,"item.food.coarse_spirit_rice":2,"item.tool.basic_furnace":1}', "MATERIAL_INSUFFICIENT"),
            ):
                original = player(runtime)[field]
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(f"UPDATE players SET {field}=?", (value,))
                baseline = state(runtime)
                result = await send(runtime, "开始生产 疗伤丹 2", "shortage")
                assert result.code == code, result.message
                assert state(runtime) == baseline
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(f"UPDATE players SET {field}=?", (original,))
            baseline = state(runtime)
            for bad in (True, 2.0, 6):
                with pytest.raises(ProductionBatchError):
                    await runtime.repository.start_production(platform="onebot.v11", platform_user_id="gatherer", recipe_key="recipe.pill.healing_low", operation_id="typed", batch_count=bad)
                assert state(runtime) == baseline
        finally:
            await runtime.close()
    asyncio.run(run())


def test_single_batch_shared_daily_quota_and_next_day(tmp_path):
    async def run():
        clock = Clock()
        runtime = create_runtime(data_dir=tmp_path, clock=clock)
        try:
            await prepared(runtime)
            used = 0
            for index, count in enumerate((1, 5, 2)):
                operation = roll_operation(f"quota-{index}")
                suffix = f" {count}" if count > 1 else ""
                started = await send(runtime, f"开始生产 疗伤丹{suffix}", operation)
                assert started.ok, started.message
                used += count
                if count == 1:
                    with sqlite3.connect(runtime.settings.database_path) as connection:
                        snapshot = json.loads(connection.execute("SELECT snapshot_json FROM production_orders").fetchone()[0])
                        assert "batch_count" not in snapshot
                    assert (await send(runtime, "开始生产 疗伤丹 1", operation)).data["idempotent_replay"]
                clock.advance(seconds=count * 30)
                assert (await send(runtime, "领取生产", f"quota-claim-{index}")).ok
                preview = await send(runtime, "生产预览 疗伤丹 2")
                assert preview.data["daily_used"] == used
            baseline = state(runtime)
            denied = await send(runtime, "开始生产 疗伤丹", "cap")
            assert denied.code == "RECIPE_DAILY_CAP" and state(runtime) == baseline
            clock.advance(days=1)
            assert (await send(runtime, "生产预览 疗伤丹 5")).data["daily_used"] == 0
            assert (await send(runtime, "开始生产 疗伤丹 5", "next-day")).ok
        finally:
            await runtime.close()
    asyncio.run(run())


@pytest.mark.parametrize("outcome", ["failure", "high_quality"])
def test_batch_quality_outputs_and_refunds_scale_once(tmp_path, outcome):
    async def run():
        clock = Clock()
        content = change_content(lambda records: records["recipe", "recipe.pill.healing_low"].update(proficiency_bp=10000)) if outcome == "high_quality" else None
        runtime = create_runtime(data_dir=tmp_path, clock=clock)
        if content is not None:
            runtime.repository.content = content
        try:
            await prepared(runtime)
            expected_roll = 1000 if outcome == "high_quality" else 0
            operation = roll_operation("quality", expected_roll)
            before = player(runtime)
            assert (await send(runtime, "开始生产 疗伤丹 3", operation)).ok
            clock.advance(seconds=90)
            result = await send(runtime, "领取生产", "quality-claim")
            assert result.ok and result.data["batch_count"] == 3
            assert result.data["random_quality_bp"] == expected_roll
            assert result.data["tool_durability_bp"] == 1700
            if outcome == "failure":
                assert result.data["success"] is False and result.data["outputs"] == {}
                assert result.data["refunds"] == {"item.herb.blood_grass": 3}
                assert json.loads(player(runtime)["inventory_json"])["item.herb.blood_grass"] == json.loads(before["inventory_json"])["item.herb.blood_grass"] - 3
            else:
                assert result.data["quality_bp"] == 8400 and result.data["success"]
                assert result.data["outputs"] == {"item.pill.healing_low": 6} and not result.data["refunds"]
            assert (await send(runtime, "生产预览 疗伤丹 2")).data["daily_used"] == 3
        finally:
            await runtime.close()
    asyncio.run(run())


@pytest.mark.parametrize("fault", ["start_player", "start_order", "start_operation", "claim_player", "claim_operation", "recover_operation"])
def test_batch_faults_roll_back_and_same_request_retries(tmp_path, fault):
    async def run():
        clock = Clock()
        runtime = create_runtime(data_dir=tmp_path, clock=clock)
        try:
            await prepared(runtime)
            operation = roll_operation("fault-start")
            settling = fault.startswith(("claim", "recover"))
            if settling:
                assert (await send(runtime, "开始生产 疗伤丹 2", operation)).ok
                clock.advance(seconds=60)
                if fault.startswith("recover"):
                    clock.advance(hours=25)
                operation = "fault-claim"
            table = "players" if fault.endswith("player") else "production_orders" if fault.endswith("order") else "operations"
            action = "UPDATE" if table == "players" else "INSERT"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(f"CREATE TRIGGER batch_fault BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT, 'batch fault'); END")
            baseline = state(runtime)
            command = "恢复生产" if fault.startswith("recover") else "领取生产" if settling else "开始生产 疗伤丹 2"
            rejected = await send(runtime, command, operation)
            assert rejected.code == "PERSISTENCE_ERROR" and rejected.retryable
            assert state(runtime) == baseline
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute("DROP TRIGGER batch_fault")
            retried = await send(runtime, command, operation)
            assert retried.ok and retried.data["batch_count"] == 2
            baseline = state(runtime)
            assert (await send(runtime, command, operation)).data["idempotent_replay"]
            assert state(runtime) == baseline
        finally:
            await runtime.close()
    asyncio.run(run())


@pytest.mark.parametrize("bad_count", [True, 2.0, 0, 6, 3, 10**100])
def test_corrupt_frozen_batch_and_original_request_repair(tmp_path, bad_count):
    async def run():
        clock = Clock()
        runtime = create_runtime(data_dir=tmp_path, clock=clock)
        try:
            await prepared(runtime)
            operation = roll_operation("snapshot")
            assert (await send(runtime, "开始生产 疗伤丹 2", operation)).ok
            clock.advance(seconds=60)
            with sqlite3.connect(runtime.settings.database_path) as connection:
                raw_snapshot = connection.execute("SELECT snapshot_json FROM production_orders").fetchone()[0]
                raw_operation = connection.execute("SELECT result_json FROM operations WHERE operation_id=?", (operation,)).fetchone()[0]
                snapshot = json.loads(raw_snapshot)
                receipt = json.loads(raw_operation)
                snapshot["batch_count"] = bad_count
                receipt["snapshot"]["batch_count"] = bad_count
                connection.execute("UPDATE production_orders SET snapshot_json=?", (json.dumps(snapshot),))
                connection.execute("UPDATE operations SET result_json=? WHERE operation_id=?", (json.dumps(receipt), operation))
            baseline = state(runtime)
            for command, op in (("生产状态", ""), ("领取生产", "snapshot-claim"), ("开始生产 疗伤丹 2", operation), ("生产预览 疗伤丹 2", "")):
                result = await send(runtime, command, op)
                assert result.code == "PERSISTENCE_ERROR" and result.retryable, (command, result.code)
                assert state(runtime) == baseline
            clock.advance(hours=25)
            for command in ("领取生产", "恢复生产"):
                assert (await send(runtime, command, "bad-overdue")).code == "PERSISTENCE_ERROR"
                assert state(runtime) == baseline
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute("UPDATE production_orders SET snapshot_json=?", (raw_snapshot,))
                connection.execute("UPDATE operations SET result_json=? WHERE operation_id=?", (raw_operation, operation))
            assert (await send(runtime, "开始生产 疗伤丹 2", operation)).data["idempotent_replay"]
            assert (await send(runtime, "恢复生产", "snapshot-claim")).ok
        finally:
            await runtime.close()
    asyncio.run(run())


def test_batch_settlement_receipt_count_and_result_are_strict(tmp_path):
    async def run():
        clock = Clock()
        runtime = create_runtime(data_dir=tmp_path, clock=clock)
        try:
            await prepared(runtime)
            assert (await send(runtime, "开始生产 疗伤丹 2", roll_operation("receipt"))).ok
            clock.advance(seconds=60)
            claimed = await send(runtime, "领取生产", "receipt-claim")
            assert claimed.ok
            with sqlite3.connect(runtime.settings.database_path) as connection:
                raw_result = connection.execute("SELECT result_json FROM production_orders").fetchone()[0]
                raw_receipt = connection.execute("SELECT result_json FROM operations WHERE operation_id='receipt-claim'").fetchone()[0]
            for bad in (True, 1, 3, 6, 10**100, None):
                receipt = json.loads(raw_receipt)
                result = json.loads(raw_result)
                if bad is None:
                    receipt.pop("batch_count")
                    result.pop("batch_count")
                else:
                    receipt["batch_count"] = result["batch_count"] = bad
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute("UPDATE production_orders SET result_json=?", (json.dumps(result),))
                    connection.execute("UPDATE operations SET result_json=? WHERE operation_id='receipt-claim'", (json.dumps(receipt),))
                baseline = state(runtime)
                for command, op in (("生产状态", ""), ("领取生产", "receipt-claim")):
                    assert (await send(runtime, command, op)).code == "PERSISTENCE_ERROR"
                    assert state(runtime) == baseline
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute("UPDATE production_orders SET result_json=?", (raw_result,))
                connection.execute("UPDATE operations SET result_json=? WHERE operation_id='receipt-claim'", (raw_receipt,))
            baseline = state(runtime)
            assert (await send(runtime, "领取生产", "receipt-claim")).data["idempotent_replay"]
            assert (await send(runtime, "生产状态")).ok and state(runtime) == baseline
        finally:
            await runtime.close()
    asyncio.run(run())


def test_batch_concurrent_runtimes_start_claim_and_quantity_conflicts(tmp_path):
    async def run():
        clock = Clock()
        first = create_runtime(data_dir=tmp_path, clock=clock)
        second = create_runtime(data_dir=tmp_path, clock=clock)
        try:
            await prepared(first)
            await second.initialize()
            operation = roll_operation("concurrent")
            starts = await asyncio.gather(*(send(runtime, "开始生产 疗伤丹 2", operation) for runtime in (first, second)))
            assert all(result.ok for result in starts)
            assert sum(result.data["idempotent_replay"] for result in starts) == 1
            assert starts[0].data["order_id"] == starts[1].data["order_id"]
            baseline = state(first)
            assert (await send(second, "开始生产 疗伤丹 3", operation)).code == "OPERATION_CONFLICT"
            assert (await send(second, "开始生产 疗伤丹 2", "other-start")).code == "PRODUCTION_BUSY"
            assert state(first) == baseline
            clock.advance(seconds=60)
            claims = await asyncio.gather(*(send(runtime, "领取生产", "concurrent-claim") for runtime in (first, second)))
            assert all(result.ok for result in claims)
            assert sum(result.data["idempotent_replay"] for result in claims) == 1
            assert json.loads(player(first)["inventory_json"])["item.pill.healing_low"] == 2
            baseline = state(first)
            assert (await send(second, "领取生产", "other-claim")).code == "PRODUCTION_NOT_FOUND"
            assert state(first) == baseline
        finally:
            await second.close()
            await first.close()
    asyncio.run(run())


def test_batch_overdue_status_recovery_and_new_order_are_not_confused(tmp_path):
    async def run():
        clock = Clock()
        runtime = create_runtime(data_dir=tmp_path, clock=clock)
        try:
            await prepared(runtime)
            first = await send(runtime, "开始生产 疗伤丹 2", roll_operation("overdue"))
            assert first.ok
            clock.advance(seconds=60, hours=24)
            baseline = state(runtime)
            status = await send(runtime, "生产状态")
            assert status.data["order"]["ready"] and status.actions[0].command == "领取生产"
            assert (await send(runtime, "恢复生产", "recover")).code == "PRODUCTION_NOT_READY"
            assert state(runtime) == baseline
            clock.advance(seconds=1)
            baseline = state(runtime)
            status = await send(runtime, "生产状态")
            assert status.actions[0].command == "恢复生产" and status.data["order"]["recoverable"]
            assert state(runtime) == baseline
            assert (await send(runtime, "领取生产", "late-claim")).code == "ORDER_EXPIRED"
            second = await send(runtime, "开始生产 疗伤丹 3", roll_operation("new-processing"))
            assert second.ok
            baseline = state(runtime)
            status = await send(runtime, "生产状态")
            assert [order["batch_count"] for order in status.data["orders"]] == [3, 2]
            assert status.actions[0].command == "恢复生产" and state(runtime) == baseline
            await runtime.close()
            runtime = create_runtime(data_dir=tmp_path, clock=clock)
            recovered = await send(runtime, "恢复生产", "recover")
            assert recovered.ok and recovered.data["order_id"] == first.data["order_id"] and recovered.data["batch_count"] == 2
            baseline = state(runtime)
            assert (await send(runtime, "恢复生产", "recover")).data["idempotent_replay"]
            assert (await send(runtime, "生产状态")).data["order"]["order_id"] == second.data["order_id"]
            assert state(runtime) == baseline
            clock.advance(seconds=90)
            assert (await send(runtime, "领取生产", "new-claim")).data["batch_count"] == 3
        finally:
            await runtime.close()
    asyncio.run(run())


@pytest.mark.parametrize("recipe_key, profession", [
    ("recipe.weapon.wood_sword", "炼器"),
    ("recipe.tool.mining_pickaxe", "采矿"),
    ("recipe.companion.sack_small", "烹饪"),
])
def test_batch_equipment_tool_and_companion_outputs_use_existing_consumers(tmp_path, recipe_key, profession):
    async def run():
        clock = Clock()
        runtime = create_runtime(data_dir=tmp_path, clock=clock)
        try:
            await prepared(runtime, profession=profession, recipe_key=recipe_key)
            recipe = recipe_definitions()[recipe_key]
            before = player(runtime)
            assert (await send(runtime, f"开始生产 {recipe_key} 2", roll_operation("equipment"))).ok
            after_start = player(runtime)
            assert after_start["spirit_stones"] == before["spirit_stones"] - recipe.currency_cost * 2
            assert after_start["energy"] == before["energy"] - recipe.energy_cost * 2
            clock.advance(seconds=recipe.duration_seconds * 2)
            result = await send(runtime, "领取生产", "equipment-claim")
            assert result.ok and result.data["success"], result.message
            item = next(iter(recipe.outputs))
            assert result.data["outputs"][item] == recipe.outputs[item] * 2
            with sqlite3.connect(runtime.settings.database_path) as connection:
                instances = connection.execute("SELECT item_key, durability_bp FROM equipment_instances WHERE item_key=?", (item,)).fetchall()
            if recipe_key.startswith("recipe.weapon."):
                assert len(instances) == 2 and instances[0] == instances[1]
                listed = await send(runtime, "我的装备")
                assert len(listed.data["equipment"]) == 2
                first, second = listed.data["equipment"]
                assert first["instance_id"] != second["instance_id"]
                assert first["equipped"] and not second["equipped"]
                baseline = state(runtime)
                assert (await send(runtime, "穿戴法器 木纹剑", "ambiguous")).code == "EQUIPMENT_AMBIGUOUS"
                assert state(runtime) == baseline
                command = _links(next(line for line in listed.message.splitlines() if "[穿戴]" in line))["穿戴"]
                assert command == "穿戴法器 " + second["instance_id"]
                unload = _links(next(line for line in listed.message.splitlines() if "卸下" in line))["卸下"]
                assert (await send(runtime, unload, "unload-first")).ok
                equipped = await send(runtime, command, "equip")
                assert equipped.ok, equipped.message
                assert (await send(runtime, command, "equip")).data["idempotent_replay"]
                await starter(runtime, user="outsider")
                baseline = state(runtime)
                assert not (await send(runtime, command, "foreign", user="outsider")).ok
                assert state(runtime) == baseline
                listed = await send(runtime, "我的装备")
                unequip = _links(next(line for line in listed.message.splitlines() if "卸下" in line))["卸下"]
                assert (await send(runtime, unequip, "unequip")).ok
                from nonebot_plugin_xiuxian_3.xiuxian.advancement.equipment_rules import equipment_definition, refinement_cost, temper_cost

                definition = equipment_definition(item)
                costs = {**refinement_cost(definition), **temper_cost(1, definition)}
                inventory = json.loads(player(runtime)["inventory_json"])
                inventory.update({key: value * 10 for key, value in costs.items() if key.startswith("item.")})
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute("UPDATE players SET inventory_json=? WHERE platform_user_id='gatherer'", (json.dumps(inventory),))
                for verb in ("强化法器", "重铸法器"):
                    label = "祭炼" if verb == "强化法器" else "重铸"
                    listed = await send(runtime, "我的装备")
                    row = next(line for line in listed.message.splitlines() if second["instance_id"] in _links(line).get(label, ""))
                    upgrade = _links(row)[label]
                    assert upgrade == f"{verb} {second['instance_id']}"
                    result = await send(runtime, upgrade, verb)
                    assert result.ok, result.message
                    assert (await send(runtime, f"{verb} {second['instance_id']}", verb)).data["idempotent_replay"]
            else:
                assert json.loads(player(runtime)["inventory_json"])[item] == recipe.outputs[item] * 2
                if recipe_key.startswith("recipe.companion."):
                    beast = await send(runtime, "结缘灵兽 木鼠", "batch-beast")
                    assert beast.ok, beast.message
                    before_stats = (await send(runtime, "我的属性")).data["derived_stats"]
                    equipped = await send(runtime, f"装备灵具 {beast.data['instance_id']} 小型灵兽行囊", "batch-sack")
                    assert equipped.ok, equipped.message
                    assert json.loads(player(runtime)["inventory_json"])[item] == 1
                    assert (await send(runtime, "我的属性")).data["derived_stats"]["carry_capacity"] == before_stats["carry_capacity"] + 5
        finally:
            await runtime.close()
    asyncio.run(run())


@pytest.mark.parametrize("adapter", ["onebot.v11", "qq.official"])
def test_batch_normalized_message_reaches_application_and_replays(tmp_path, adapter):
    from types import SimpleNamespace
    from nonebot_plugin_xiuxian_3.adapters.onebot import normalize_event as onebot_event
    from nonebot_plugin_xiuxian_3.adapters.qq import normalize_event as qq_event

    async def run():
        clock = Clock()
        runtime = create_runtime(data_dir=tmp_path, clock=clock)
        try:
            await starter(runtime, adapter=adapter, path="辅修 炼丹")
            for command in ("开始生产 疗伤丹 2", "生产状态"):
                event = SimpleNamespace(content=command, raw_message=command, id=command,
                    message_id=command, user_id="gatherer", post_type="message", message_type="group",
                    group_id="test-group", group_openid="test-group", self_id="test-bot",
                    author={"member_openid": "gatherer"})
                normalized = onebot_event(event) if adapter == "onebot.v11" else qq_event(event)
                assert normalized.context.adapter == adapter and normalized.context.can_write_assets
                result = await runtime.dispatch(normalized.context, normalized.text)
                if command.startswith("开始"):
                    assert result.code == "PRODUCTION_STARTED" and result.data["batch_count"] == 2
                    baseline = state(runtime)
                    assert (await runtime.dispatch(normalized.context, normalized.text)).data["idempotent_replay"]
                    assert state(runtime) == baseline
                else:
                    assert result.ok and result.data["order"]["batch_count"] == 2
                    assert not result.actions
        finally:
            await runtime.close()
    asyncio.run(run())


def test_batch_large_assets_currency_shortage_and_readonly_identity(tmp_path):
    async def run():
        clock = Clock()
        runtime = create_runtime(data_dir=tmp_path, clock=clock)
        try:
            await prepared(runtime, profession="采矿", recipe_key="recipe.tool.mining_pickaxe")
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute("UPDATE players SET spirit_stones=19")
            baseline = state(runtime)
            assert (await send(runtime, "开始生产 基础矿镐 2", "large")).code == "MATERIAL_INSUFFICIENT"
            assert state(runtime) == baseline
            huge = 10**60
            inventory = {"item.ore.ironstone": huge, "item.mat.wood": huge}
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute("UPDATE players SET spirit_stones=?, energy=?, energy_max=?, inventory_json=?", (sqlite3.Binary(str(huge).encode()), sqlite3.Binary(str(huge).encode()), sqlite3.Binary(str(huge).encode()), json.dumps(inventory)))
            started = await send(runtime, "开始生产 基础矿镐 2", "large")
            assert started.ok, started.message
            after = player(runtime)
            assert int(after["spirit_stones"]) == huge - 20 and int(after["energy"]) == huge - 6
            assert json.loads(after["inventory_json"]) == {"item.ore.ironstone": huge - 4, "item.mat.wood": huge - 2}
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute("UPDATE players SET endgame_status='remained_in_world'")
            baseline = state(runtime)
            assert (await send(runtime, "生产状态")).ok
            assert state(runtime) == baseline
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute("UPDATE players SET status='suspended'")
            baseline = state(runtime)
            assert (await send(runtime, "生产状态")).code == "PLAYER_SUSPENDED"
            assert state(runtime) == baseline
        finally:
            await runtime.close()
    asyncio.run(run())


def test_batch_preview_keeps_the_seven_day_event_consumer(tmp_path):
    async def run():
        clock = Clock()
        runtime = create_runtime(data_dir=tmp_path, clock=clock)
        try:
            await prepared(runtime)
            assert (await send(runtime, "七日入道")).ok
            clock.advance(days=2)
            before = player(runtime)
            await preview_batch(runtime, "生产预览 疗伤丹 2")
            claimed = await send(runtime, "领取七日目标 3", "preview-day3")
            assert claimed.ok, claimed.message
            assert player(runtime)["spirit_stones"] == before["spirit_stones"] + 30
            baseline = state(runtime)
            assert (await send(runtime, "领取七日目标 3", "preview-day3")).data["idempotent_replay"]
            assert state(runtime) == baseline
        finally:
            await runtime.close()
    asyncio.run(run())


def test_facility_declared_duration_and_legacy_fallback_do_not_scale_ordinary_batches():
    from types import SimpleNamespace
    from nonebot_plugin_xiuxian_3.xiuxian.production.facility_repository import FacilityRepositoryMixin
    from nonebot_plugin_xiuxian_3.xiuxian.production.repository import ProductionRepositoryMixin

    recipe = recipe_definitions()["recipe.pill.golden_core_guard"]
    row = {"location_key": "cave.mist_grotto_2", "inventory_json": json.dumps({"item.array.gathering_basic": 1})}
    content = change_content(lambda records: records["item", "item.array.gathering_basic"]["effects"][0].update(value=7000))
    repository = SimpleNamespace(content=content)
    duration = FacilityRepositoryMixin._facility_duration_seconds
    assert duration(repository, row, recipe) == 84
    row["inventory_json"] = "{}"
    assert duration(repository, row, recipe) == 120
    row["inventory_json"] = json.dumps({"item.array.gathering_basic": 1})
    repository.content = change_content(lambda records: records["item", "item.array.gathering_basic"].update(effects=[]))
    assert duration(repository, row, recipe) == 108
    batch = ProductionRepositoryMixin._batch_recipe(recipe_definitions()["recipe.food.spirit_rice"], 2)
    assert duration(repository, row, batch) == 30


def test_batch_help_onebot_qq_prefix_prefill_ready_and_plain_contract(tmp_path, monkeypatch):
    from nonebot_plugin_xiuxian_3.adapters.message import markdown

    class Bot:
        async def send(self, event, message, **kwargs):
            self.message = message
            return {"id": "reply"}

    async def run():
        clock = Clock()
        runtime = create_runtime(data_dir=tmp_path, clock=clock)
        try:
            assert (await send(runtime, "生产状态")).code == "PLAYER_NOT_FOUND"
            await prepared(runtime)
            assert (await send(runtime, "生产状态")).data["order"] is None
            baseline = state(runtime)
            help_result = await send(runtime, "修仙帮助 生活")
            assert help_result.ok and not help_result.actions and "生产状态" in help_result.message
            converted = markdown._qq_command_links(help_result.message, command_prefix="!")
            assert quote("!生产预览 配方名 份数", safe="") in converted and "enter=false" in converted
            preview = await preview_batch(runtime, "生产预览 疗伤丹 2")
            baseline = state(runtime)
            converted = markdown._qq_command_links(preview.message, command_prefix="!")
            assert quote("!开始生产 低阶疗伤丹 2", safe="") in converted
            assert quote("!生产预览 低阶疗伤丹 份数", safe="") in converted
            assert not preview.actions and "制作份数" in preview.message and "成功产出" in preview.message
            plain = markdown.markdown_to_text(preview.message)
            assert "开始生产 低阶疗伤丹 2" in plain and "command:" not in plain
            assert (await send(runtime, "生产状态 extra")).code == "INVALID_PRODUCTION_COMMAND"
            assert state(runtime) == baseline
            assert (await send(runtime, "开始生产 疗伤丹 2", roll_operation("messages"))).ok
            clock.advance(seconds=60)
            ready = await send(runtime, "生产状态")
            assert ready.actions[0].enter and ready.actions[0].command == "领取生产"
            # Exercise the repository formatter contract without installing the optional SDK.
            monkeypatch.setattr(markdown, "qq_markdown_segment", lambda body, command_prefix="": markdown._qq_command_links(body, command_prefix=command_prefix))
            bot = Bot()
            sent = await markdown.send_markdown_message(bot, object(), ready.message, capabilities=("markdown",), actions=ready.actions, command_prefix="!")
            assert sent.sent_format == "markdown" and quote("!领取生产", safe="") in bot.message
            plain_bot = Bot()
            sent = await markdown.send_markdown_message(plain_bot, object(), ready.message, actions=ready.actions)
            assert sent.sent_format == "text" and "可发送：领取生产" in plain_bot.message
            assert "command:" not in plain_bot.message and "mqqapi:" not in plain_bot.message
            await starter(runtime, user="qq-contract", adapter="qq.official", path="辅修 炼丹")
            qq_preview = await send(runtime, "生产预览 疗伤丹 2", user="qq-contract", adapter="qq.official")
            assert qq_preview.ok and qq_preview.data["batch_count"] == 2
            assert (await send(runtime, "生产状态", user="qq-contract", adapter="qq.official")).data["order"] is None
            assert (await send(runtime, "生产状态", user="gatherer", adapter="qq.official")).code == "PLAYER_NOT_FOUND"
        finally:
            await runtime.close()
    asyncio.run(run())
