from __future__ import annotations

import asyncio
import json
import shutil
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from test_equipment import _enter_cultivator


ROOT = Path(__file__).parents[1]


def _context(user: str, request: str, *, operation_id: str = "") -> CommandContext:
    return CommandContext(
        adapter="web",
        user_id=user,
        request_id=request,
        operation_id=operation_id,
    )


def _prepare_player(runtime, user: str) -> None:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        row = connection.execute(
            "SELECT inventory_json FROM players WHERE platform='web' AND platform_user_id=?",
            (user,),
        ).fetchone()
        assert row is not None
        inventory = json.loads(row[0])
        inventory.update(
            {
                "item.ore.ironstone": 20,
                "item.mat.wood": 20,
                "item.herb.blood_grass": 20,
                "item.equipment.repair_kit": 0,
                "item.weapon.wood_sword": 1,
            }
        )
        connection.execute(
            "UPDATE players SET inventory_json=?, energy=energy_max, realm_key='qi_sensing', realm_layer=2, "
            "location_key='xuantian.new_town', spirit_stones=1000 WHERE platform='web' AND platform_user_id=?",
            (json.dumps(inventory, ensure_ascii=False, sort_keys=True), user),
        )


def _finish_production(runtime, order_id: str) -> None:
    now = datetime.now(timezone.utc)
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE production_orders SET starts_at=?, ends_at=? WHERE order_id=?",
            ((now - timedelta(seconds=30)).isoformat(), (now - timedelta(seconds=1)).isoformat(), order_id),
        )


def _instance(runtime, user: str) -> str:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        row = connection.execute(
            "SELECT instance_id FROM equipment_instances WHERE player_id=(SELECT id FROM players WHERE platform='web' AND platform_user_id=?) "
            "AND status IN ('active','broken') ORDER BY id LIMIT 1",
            (user,),
        ).fetchone()
    assert row is not None
    return str(row[0])


def _state(runtime, user: str, instance_id: str) -> tuple[dict[str, int], int, str, int, int, str]:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        player = connection.execute(
            "SELECT inventory_json, spirit_stones FROM players WHERE platform='web' AND platform_user_id=?",
            (user,),
        ).fetchone()
        equipment = connection.execute(
            "SELECT status, equipped, durability_bp, temper_level, affixes_json FROM equipment_instances WHERE instance_id=?",
            (instance_id,),
        ).fetchone()
    assert player is not None and equipment is not None
    return json.loads(player[0]), int(player[1]), str(equipment[0]), int(equipment[1]), int(equipment[2]), str(equipment[4])


async def _make_kit(runtime, user: str, suffix: str = "") -> None:
    operation = f"kit-start{suffix}"
    started = await runtime.dispatch(
        _context(user, operation, operation_id=operation), "开始生产 野外修缮包"
    )
    assert started.ok, (started.code, started.message)
    _finish_production(runtime, started.data["order_id"])
    completed = await runtime.dispatch(_context(user, "kit-complete"), "领取生产")
    assert completed.ok and completed.data["outputs"] == {"item.equipment.repair_kit": 1}


def test_field_repair_production_preview_repair_replay_and_commission(tmp_path: Path) -> None:
    async def run() -> None:
        data_dir = tmp_path / "data"
        shutil.copytree(ROOT / "data", data_dir)
        runtime = create_runtime(data_dir=data_dir)
        user = "field-repair-main"
        other = "field-repair-other"
        try:
            await _enter_cultivator(runtime, user)
            _prepare_player(runtime, user)
            await _make_kit(runtime, user, "-first")
            made = await runtime.dispatch(_context(user, "materialize"), "强化法器 木纹剑")
            assert made.ok
            instance_id = _instance(runtime, user)
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE equipment_instances SET status='broken', equipped=0, durability_bp=0, temper_level=2, affixes_json=? WHERE instance_id=?",
                    (json.dumps({"damage": 3}), instance_id),
                )
            before = _state(runtime, user, instance_id)
            preview = await runtime.dispatch(
                _context(user, "field-preview"), f"野外修缮预览 {instance_id}"
            )
            assert preview.ok and preview.data["durability_after"] == 2000
            assert _state(runtime, user, instance_id) == before
            repaired = await runtime.dispatch(
                _context(user, "field-repair", operation_id="field-repair-1"),
                f"野外修缮装备 {instance_id}",
            )
            assert repaired.ok and repaired.data["durability_after"] == 2000
            inventory, stones, status, equipped, durability, affixes = _state(runtime, user, instance_id)
            assert status == "active" and equipped == 0 and durability == 2000
            assert json.loads(affixes) == {"damage": 3}
            assert inventory.get("item.equipment.repair_kit", 0) == before[0].get("item.equipment.repair_kit", 0) - 1
            assert stones == before[1]
            replay = await runtime.dispatch(
                _context(user, "field-replay", operation_id="field-repair-1"),
                f"野外修缮装备 {instance_id}",
            )
            assert replay.ok and replay.data["idempotent_replay"]

            full = await runtime.dispatch(
                _context(user, "field-full", operation_id="field-full"),
                f"野外修缮装备 {instance_id}",
            )
            assert full.code == "EQUIPMENT_REPAIR_KIT_INSUFFICIENT"

            await _enter_cultivator(runtime, other)
            foreign = await runtime.dispatch(
                _context(other, "field-foreign", operation_id="field-foreign"),
                f"野外修缮装备 {instance_id}",
            )
            assert foreign.code == "EQUIPMENT_NOT_OWNED"

            _prepare_player(runtime, user)
            with sqlite3.connect(runtime.settings.database_path) as connection:
                player_row = connection.execute(
                    "SELECT id, inventory_json FROM players WHERE platform='web' AND platform_user_id=?", (user,)
                ).fetchone()
                player_id = int(player_row[0])
                inventory = json.loads(player_row[1])
                inventory["item.equipment.repair_kit"] = 1
                connection.execute(
                    "UPDATE players SET inventory_json=? WHERE id=?",
                    (json.dumps(inventory, ensure_ascii=False, sort_keys=True), player_id),
                )
                connection.execute(
                    "UPDATE equipment_instances SET durability_bp=0, status='broken' WHERE instance_id=?", (instance_id,)
                )
                connection.execute(
                    "INSERT INTO cultivation_sessions(session_id, player_id, operation_id, mode_key, status, starts_at, ends_at, created_at, updated_at) "
                    "VALUES ('field-lock', ?, 'field-lock-op', 'basic', 'running', ?, ?, ?, ?)",
                    (player_id, "2026-11-18T00:00:00+00:00", "2026-11-19T00:00:00+00:00", "2026-11-18T00:00:00+00:00", "2026-11-18T00:00:00+00:00"),
                )
            busy = await runtime.dispatch(
                _context(user, "field-busy", operation_id="field-busy"), f"野外修缮装备 {instance_id}"
            )
            assert busy.code == "EQUIPMENT_BUSY"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute("DELETE FROM cultivation_sessions WHERE session_id='field-lock'")
                connection.execute(
                    "CREATE TRIGGER reject_field_repair BEFORE INSERT ON equipment_field_repair_events "
                    "BEGIN SELECT RAISE(ABORT, 'forced field repair failure'); END"
                )
            before_failure = _state(runtime, user, instance_id)
            failed = await runtime.dispatch(
                _context(user, "field-failure", operation_id="field-failure"),
                f"野外修缮装备 {instance_id}",
            )
            assert failed.code == "PERSISTENCE_ERROR" and failed.retryable
            assert _state(runtime, user, instance_id) == before_failure
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute("DROP TRIGGER reject_field_repair")
            retried = await runtime.dispatch(
                _context(user, "field-retry", operation_id="field-failure"),
                f"野外修缮装备 {instance_id}",
            )
            assert retried.ok

            await runtime.close()
            document = json.loads((data_dir / "道具" / "材料.json").read_text(encoding="utf-8"))
            next(row for row in document["records"] if row["key"] == "item.equipment.repair_kit")["status"] = "closed"
            (data_dir / "道具" / "材料.json").write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
            recipes_path = data_dir / "生产" / "配方.json"
            recipes = json.loads(recipes_path.read_text(encoding="utf-8"))
            for row in recipes["records"]:
                if row["key"].startswith("recipe.equipment.repair_kit"):
                    row["status"] = "closed"
            recipes_path.write_text(json.dumps(recipes, ensure_ascii=False), encoding="utf-8")
            recovered = create_runtime(data_dir=data_dir)
            try:
                replay_after_close = await recovered.dispatch(
                    _context(user, "field-replay-closed", operation_id="field-repair-1"),
                    f"野外修缮装备 {instance_id}",
                )
                assert replay_after_close.ok and replay_after_close.data["idempotent_replay"]
            finally:
                await recovered.close()
        finally:
            await runtime.close()

    asyncio.run(run())


def test_repair_kit_commission_consumes_surplus_and_rewards(tmp_path: Path) -> None:
    async def run() -> None:
        data_dir = tmp_path / "data"
        shutil.copytree(ROOT / "data", data_dir)
        runtime = create_runtime(data_dir=data_dir)
        user = "field-repair-commission"
        try:
            await _enter_cultivator(runtime, user)
            _prepare_player(runtime, user)
            with sqlite3.connect(runtime.settings.database_path) as connection:
                row = connection.execute(
                    "SELECT inventory_json FROM players WHERE platform='web' AND platform_user_id=?", (user,)
                ).fetchone()
                inventory = json.loads(row[0])
                inventory["item.equipment.repair_kit"] = 2
                connection.execute(
                    "UPDATE players SET inventory_json=? WHERE platform='web' AND platform_user_id=?",
                    (json.dumps(inventory, ensure_ascii=False, sort_keys=True), user),
                )
            listing = await runtime.dispatch(_context(user, "commission-list"), "城镇委托")
            assert listing.ok and any(row["commission_key"] == "town_commission.repair_kits" for row in listing.data["commissions"])
            accepted = await runtime.dispatch(
                _context(user, "commission-accept", operation_id="commission-accept"), "接取委托 修缮包回收"
            )
            assert accepted.ok
            delivered = await runtime.dispatch(
                _context(user, "commission-deliver", operation_id="commission-deliver"), "交付委托 修缮包回收"
            )
            assert delivered.ok and delivered.data["reward_stones"] == 28
            with sqlite3.connect(runtime.settings.database_path) as connection:
                row = connection.execute(
                    "SELECT inventory_json, spirit_stones FROM players WHERE platform='web' AND platform_user_id=?", (user,)
                ).fetchone()
            assert json.loads(row[0]).get("item.equipment.repair_kit", 0) == 0
            assert int(row[1]) == 1028
        finally:
            await runtime.close()

    asyncio.run(run())


def test_equipment_care_commands_share_qq_and_onebot_application_entry(tmp_path: Path) -> None:
    async def run() -> None:
        data_dir = tmp_path / "data"
        shutil.copytree(ROOT / "data", data_dir)
        runtime = create_runtime(data_dir=data_dir, adapters=("qq.official", "onebot.v11"))
        try:
            for adapter in ("qq.official", "onebot.v11"):
                user = f"equipment-care-{adapter}"
                created = await runtime.adapters.dispatch(
                    adapter,
                    CommandContext(adapter=adapter, user_id=user, request_id=f"{adapter}-create"),
                    "开始修仙",
                )
                assert created.ok
                listed = await runtime.adapters.dispatch(
                    adapter,
                    CommandContext(adapter=adapter, user_id=user, request_id=f"{adapter}-list"),
                    "我的装备",
                )
                assert listed.code == "EQUIPMENT_LISTED"
                for index, command in enumerate(
                    (
                        "装备修复预览 missing-instance",
                        "修复装备 missing-instance",
                        "装备回收预览 missing-instance",
                        "回收装备 missing-instance",
                        "野外修缮预览 missing-instance",
                        "野外修缮装备 missing-instance",
                    )
                ):
                    result = await runtime.adapters.dispatch(
                        adapter,
                        CommandContext(
                            adapter=adapter,
                            user_id=user,
                            request_id=f"{adapter}-care-{index}",
                        ),
                        command,
                    )
                    assert result.code != "COMMAND_NOT_FOUND", (adapter, command, result)
        finally:
            await runtime.close()

    asyncio.run(run())
