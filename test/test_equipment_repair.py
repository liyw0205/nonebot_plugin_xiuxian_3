from __future__ import annotations

import asyncio
import json
import sqlite3
import shutil
from pathlib import Path

from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.advancement.equipment_rules import (
    EQUIPMENT_DEFINITIONS,
    equipment_repair_cost,
)
from test_equipment import _context, _enter_cultivator


def _set_repair_resources(runtime, user_id: str, *, ironstone: int, stones: int, location: str) -> None:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        row = connection.execute(
            "SELECT inventory_json FROM players WHERE platform='web' AND platform_user_id=?",
            (user_id,),
        ).fetchone()
        assert row is not None
        inventory = json.loads(row[0])
        inventory["item.weapon.wood_sword"] = max(1, int(inventory.get("item.weapon.wood_sword", 0)))
        inventory["item.ore.ironstone"] = ironstone
        connection.execute(
            "UPDATE players SET inventory_json=?, spirit_stones=?, location_key=? "
            "WHERE platform='web' AND platform_user_id=?",
            (json.dumps(inventory, ensure_ascii=False, sort_keys=True), stones, location, user_id),
        )


def _damage_equipment(runtime, instance_id: str, *, status: str = "broken", durability: int = 0) -> None:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE equipment_instances SET status=?, equipped=0, durability_bp=?, "
            "temper_level=1, affixes_json=? WHERE instance_id=?",
            (status, durability, json.dumps({"damage": 3}), instance_id),
        )


def _equipment(runtime, instance_id: str) -> tuple[str, int, int, int, str]:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        row = connection.execute(
            "SELECT status, equipped, durability_bp, temper_level, affixes_json "
            "FROM equipment_instances WHERE instance_id=?",
            (instance_id,),
        ).fetchone()
    assert row is not None
    return str(row[0]), int(row[1]), int(row[2]), int(row[3]), str(row[4])


def _player_assets(runtime, user_id: str) -> tuple[dict[str, int], int]:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        row = connection.execute(
            "SELECT inventory_json, spirit_stones FROM players "
            "WHERE platform='web' AND platform_user_id=?",
            (user_id,),
        ).fetchone()
    assert row is not None
    return json.loads(row[0]), int(row[1])


def test_repair_preview_and_idempotent_repair_restore_broken_equipment(tmp_path: Path) -> None:
    async def run() -> None:
        data_dir = tmp_path / "data"
        shutil.copytree(Path(__file__).parents[1] / "data", data_dir)
        runtime = create_runtime(data_dir=data_dir)
        user = "equipment-repair-main"
        try:
            await _enter_cultivator(runtime, user)
            _set_repair_resources(runtime, user, ironstone=20, stones=1_000, location="xuantian.new_town")
            made = await runtime.dispatch(_context(user, "repair-materialize"), "强化法器 木纹剑")
            assert made.ok, (made.code, made.message)
            with sqlite3.connect(runtime.settings.database_path) as connection:
                row = connection.execute(
                    "SELECT instance_id FROM equipment_instances WHERE player_id="
                    "(SELECT id FROM players WHERE platform='web' AND platform_user_id=?)",
                    (user,),
                ).fetchone()
            assert row is not None
            instance_id = str(row[0])
            _damage_equipment(runtime, instance_id)
            _set_repair_resources(runtime, user, ironstone=20, stones=1_000, location="xuantian.new_town")

            definition = EQUIPMENT_DEFINITIONS["item.weapon.wood_sword"]
            assert equipment_repair_cost(1, definition) == {
                "item.ore.ironstone": 1,
                "currency.spirit_stone": 20,
            }
            assert equipment_repair_cost(2_001, definition) == {
                "item.ore.ironstone": 2,
                "currency.spirit_stone": 40,
            }
            custom_growth_definition = EQUIPMENT_DEFINITIONS["item.weapon.cloud_sword"]
            assert equipment_repair_cost(1_000, custom_growth_definition) == {
                "item.material.cloud_iron": 1,
                "currency.spirit_stone": 80,
            }

            before_assets = _player_assets(runtime, user)
            before_equipment = _equipment(runtime, instance_id)
            before_events = sqlite3.connect(runtime.settings.database_path)
            try:
                event_count = before_events.execute("SELECT COUNT(*) FROM equipment_repair_events").fetchone()[0]
            finally:
                before_events.close()
            preview = await runtime.dispatch(
                _context(user, "repair-preview"), f"装备修复预览 {instance_id}"
            )
            assert preview.ok and preview.data["costs"] == {
                "item.ore.ironstone": 5,
                "currency.spirit_stone": 100,
            }
            assert not preview.data["shortages"] and preview.data["at_location"]
            assert _player_assets(runtime, user) == before_assets
            assert _equipment(runtime, instance_id) == before_equipment
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute("SELECT COUNT(*) FROM equipment_repair_events").fetchone()[0] == event_count

            result = await runtime.dispatch(
                _context(user, "repair-1", operation_id="repair-main-1"),
                f"修复装备 {instance_id}",
            )
            assert result.ok and result.code == "EQUIPMENT_REPAIRED", (result.code, result.message)
            assert result.data["durability_before"] == 0 and result.data["durability_after"] == 10_000
            assert result.data["costs_spent"] == preview.data["costs"]
            status, equipped, durability, temper_level, affixes = _equipment(runtime, instance_id)
            assert (status, equipped, durability, temper_level) == ("active", 0, 10_000, 1)
            assert json.loads(affixes) == {"damage": 3}
            inventory, stones = _player_assets(runtime, user)
            assert inventory["item.ore.ironstone"] == 15 and stones == 900

            replay = await runtime.dispatch(
                _context(user, "repair-1-replay", operation_id="repair-main-1"),
                f"修复装备 {instance_id}",
            )
            assert replay.ok and replay.data["idempotent_replay"]
            conflict = await runtime.dispatch(
                _context(user, "repair-1-conflict", operation_id="repair-main-1"),
                "修复装备 not-my-instance",
            )
            assert conflict.code == "OPERATION_CONFLICT"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute("SELECT COUNT(*) FROM equipment_repair_events").fetchone()[0] == event_count + 1

            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE equipment_instances SET status='active', equipped=1, durability_bp=9000, "
                    "temper_level=2 WHERE instance_id=?",
                    (instance_id,),
                )
            _set_repair_resources(runtime, user, ironstone=5, stones=100, location="xuantian.new_town")
            active_repair = await runtime.dispatch(
                _context(user, "repair-active", operation_id="repair-active-1"),
                f"修复装备 {instance_id}",
            )
            assert active_repair.ok and active_repair.data["durability_before"] == 9_000
            assert active_repair.data["equipped"] is True
            assert _equipment(runtime, instance_id) == ("active", 1, 10_000, 2, '{"damage": 3}')

            before_full_assets = _player_assets(runtime, user)
            before_full_equipment = _equipment(runtime, instance_id)
            full = await runtime.dispatch(
                _context(user, "repair-full", operation_id="repair-full-1"),
                f"修复装备 {instance_id}",
            )
            assert full.code == "EQUIPMENT_REPAIR_NOT_NEEDED"
            assert _player_assets(runtime, user) == before_full_assets
            assert _equipment(runtime, instance_id) == before_full_equipment
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute("SELECT COUNT(*) FROM equipment_repair_events").fetchone()[0] == event_count + 2
        finally:
            await runtime.close()

    asyncio.run(run())


def test_repair_location_shortage_and_event_failure_are_zero_write_retryable(tmp_path: Path) -> None:
    async def run() -> None:
        data_dir = tmp_path / "data"
        shutil.copytree(Path(__file__).parents[1] / "data", data_dir)
        runtime = create_runtime(data_dir=data_dir)
        user = "equipment-repair-boundaries"
        try:
            await _enter_cultivator(runtime, user)
            _set_repair_resources(runtime, user, ironstone=20, stones=1_000, location="xuantian.new_town")
            made = await runtime.dispatch(_context(user, "repair-boundary-materialize"), "强化法器 木纹剑")
            assert made.ok
            with sqlite3.connect(runtime.settings.database_path) as connection:
                row = connection.execute(
                    "SELECT instance_id FROM equipment_instances WHERE player_id="
                    "(SELECT id FROM players WHERE platform='web' AND platform_user_id=?)",
                    (user,),
                ).fetchone()
            assert row is not None
            instance_id = str(row[0])
            _damage_equipment(runtime, instance_id)

            _set_repair_resources(runtime, user, ironstone=20, stones=1_000, location="xuantian.outskirts")
            wrong_location_assets = _player_assets(runtime, user)
            wrong_location_gear = _equipment(runtime, instance_id)
            wrong_location = await runtime.dispatch(
                _context(user, "repair-wrong-location"), f"修复装备 {instance_id}"
            )
            assert wrong_location.code == "EQUIPMENT_REPAIR_WRONG_LOCATION"
            assert _player_assets(runtime, user) == wrong_location_assets
            assert _equipment(runtime, instance_id) == wrong_location_gear

            _set_repair_resources(runtime, user, ironstone=0, stones=1_000, location="xuantian.new_town")
            shortage_assets = _player_assets(runtime, user)
            shortage_gear = _equipment(runtime, instance_id)
            shortage = await runtime.dispatch(
                _context(user, "repair-shortage"), f"修复装备 {instance_id}"
            )
            assert shortage.code == "EQUIPMENT_REPAIR_RESOURCE_INSUFFICIENT"
            assert _player_assets(runtime, user) == shortage_assets
            assert _equipment(runtime, instance_id) == shortage_gear

            _set_repair_resources(runtime, user, ironstone=20, stones=1_000, location="xuantian.new_town")
            before_assets = _player_assets(runtime, user)
            before_gear = _equipment(runtime, instance_id)
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "CREATE TRIGGER reject_equipment_repair BEFORE INSERT ON equipment_repair_events "
                    "BEGIN SELECT RAISE(ABORT, 'forced repair event failure'); END"
                )
            failed = await runtime.dispatch(
                _context(user, "repair-trigger-failure", operation_id="repair-retry-after-trigger"),
                f"修复装备 {instance_id}",
            )
            assert failed.code == "PERSISTENCE_ERROR" and failed.retryable
            assert _player_assets(runtime, user) == before_assets
            assert _equipment(runtime, instance_id) == before_gear
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute("DROP TRIGGER reject_equipment_repair")

            retried = await runtime.dispatch(
                _context(user, "repair-trigger-retry", operation_id="repair-retry-after-trigger"),
                f"修复装备 {instance_id}",
            )
            assert retried.ok and retried.code == "EQUIPMENT_REPAIRED"
            assert _equipment(runtime, instance_id)[:3] == ("active", 0, 10_000)
        finally:
            await runtime.close()

    asyncio.run(run())


def test_repair_rejects_foreign_busy_and_malformed_equipment_without_writes(tmp_path: Path) -> None:
    async def run() -> None:
        data_dir = tmp_path / "data"
        shutil.copytree(Path(__file__).parents[1] / "data", data_dir)
        runtime = create_runtime(data_dir=data_dir)
        owner = "equipment-repair-owner"
        other = "equipment-repair-other"
        try:
            await _enter_cultivator(runtime, owner)
            await _enter_cultivator(runtime, other)
            _set_repair_resources(runtime, owner, ironstone=20, stones=1_000, location="xuantian.new_town")
            made = await runtime.dispatch(_context(owner, "repair-owner-materialize"), "强化法器 木纹剑")
            assert made.ok
            with sqlite3.connect(runtime.settings.database_path) as connection:
                row = connection.execute(
                    "SELECT instance_id, (SELECT id FROM players WHERE platform='web' AND platform_user_id=?) "
                    "FROM equipment_instances WHERE player_id="
                    "(SELECT id FROM players WHERE platform='web' AND platform_user_id=?)",
                    (owner, owner),
                ).fetchone()
                assert row is not None
                instance_id, owner_id = str(row[0]), int(row[1])
            _damage_equipment(runtime, instance_id)
            _set_repair_resources(runtime, owner, ironstone=20, stones=1_000, location="xuantian.new_town")

            before_assets = _player_assets(runtime, owner)
            before_equipment = _equipment(runtime, instance_id)
            foreign = await runtime.dispatch(
                _context(other, "repair-foreign"), f"修复装备 {instance_id}"
            )
            assert foreign.code == "EQUIPMENT_NOT_OWNED"
            assert _player_assets(runtime, owner) == before_assets
            assert _equipment(runtime, instance_id) == before_equipment

            timestamp = "2026-11-18T00:00:00+00:00"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "INSERT INTO cultivation_sessions("
                    "session_id, player_id, operation_id, mode_key, status, starts_at, ends_at, created_at, updated_at"
                    ") VALUES ('repair-lock', ?, 'repair-lock-op', 'basic', 'running', ?, ?, ?, ?)",
                    (owner_id, timestamp, timestamp, timestamp, timestamp),
                )
            busy_assets = _player_assets(runtime, owner)
            busy_equipment = _equipment(runtime, instance_id)
            busy = await runtime.dispatch(
                _context(owner, "repair-busy"), f"修复装备 {instance_id}"
            )
            assert busy.code == "EQUIPMENT_BUSY"
            assert _player_assets(runtime, owner) == busy_assets
            assert _equipment(runtime, instance_id) == busy_equipment

            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute("DELETE FROM cultivation_sessions WHERE session_id='repair-lock'")
                connection.execute(
                    "UPDATE equipment_instances SET affixes_json='{' WHERE instance_id=?",
                    (instance_id,),
                )
            malformed_assets = _player_assets(runtime, owner)
            malformed_equipment = _equipment(runtime, instance_id)
            malformed = await runtime.dispatch(
                _context(owner, "repair-malformed"), f"修复装备 {instance_id}"
            )
            assert malformed.code == "PERSISTENCE_ERROR" and malformed.retryable
            assert _player_assets(runtime, owner) == malformed_assets
            assert _equipment(runtime, instance_id) == malformed_equipment
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute("SELECT COUNT(*) FROM equipment_repair_events").fetchone()[0] == 0
        finally:
            await runtime.close()

    asyncio.run(run())


def test_repair_concurrent_replay_survives_restart_and_closed_rules(tmp_path: Path) -> None:
    async def run() -> None:
        data_dir = tmp_path / "data"
        shutil.copytree(Path(__file__).parents[1] / "data", data_dir)
        first = create_runtime(data_dir=data_dir)
        second = create_runtime(data_dir=data_dir)
        user = "equipment-repair-replay"
        try:
            await _enter_cultivator(first, user)
            _set_repair_resources(first, user, ironstone=20, stones=1_000, location="xuantian.new_town")
            made = await first.dispatch(_context(user, "repair-race-materialize"), "强化法器 木纹剑")
            assert made.ok
            with sqlite3.connect(first.settings.database_path) as connection:
                row = connection.execute(
                    "SELECT instance_id FROM equipment_instances WHERE player_id="
                    "(SELECT id FROM players WHERE platform='web' AND platform_user_id=?)",
                    (user,),
                ).fetchone()
            assert row is not None
            instance_id = str(row[0])
            _damage_equipment(first, instance_id)
            _set_repair_resources(first, user, ironstone=20, stones=1_000, location="xuantian.new_town")

            operation_id = "repair-concurrent-1"
            text = f"修复装备 {instance_id}"
            raced = await asyncio.gather(
                first.dispatch(
                    _context(user, "repair-race-first", operation_id=operation_id), text
                ),
                second.dispatch(
                    _context(user, "repair-race-second", operation_id=operation_id), text
                ),
            )
            assert all(result.ok and result.code == "EQUIPMENT_REPAIRED" for result in raced)
            assert sum(bool(result.data["idempotent_replay"]) for result in raced) == 1
            inventory, stones = _player_assets(first, user)
            assert inventory["item.ore.ironstone"] == 15 and stones == 900
            with sqlite3.connect(first.settings.database_path) as connection:
                assert connection.execute("SELECT COUNT(*) FROM equipment_repair_events").fetchone()[0] == 1
                assert connection.execute(
                    "UPDATE equipment_instances SET durability_bp=9999 WHERE instance_id=?",
                    (instance_id,),
                ).rowcount == 1
        finally:
            await second.close()
            await first.close()

        growth_path = data_dir / "装备" / "成长.json"
        growth_document = json.loads(growth_path.read_text(encoding="utf-8"))
        common_profile = next(
            row for row in growth_document["records"] if row["key"] == "equipment.growth.common"
        )
        common_profile["status"] = "closed"
        growth_path.write_text(json.dumps(growth_document, ensure_ascii=False, indent=2), encoding="utf-8")

        recovered = create_runtime(data_dir=data_dir)
        try:
            replay = await recovered.dispatch(
                _context(user, "repair-after-restart", operation_id="repair-concurrent-1"), text
            )
            assert replay.ok and replay.data["idempotent_replay"]
            assert replay.data["durability_before"] == 0

            before_assets = _player_assets(recovered, user)
            before_equipment = _equipment(recovered, instance_id)
            closed_rules = await recovered.dispatch(
                _context(user, "repair-closed-new-operation", operation_id="repair-after-close-new"),
                text,
            )
            assert closed_rules.code == "INVALID_EQUIPMENT"
            assert _player_assets(recovered, user) == before_assets
            assert _equipment(recovered, instance_id) == before_equipment
            with sqlite3.connect(recovered.settings.database_path) as connection:
                assert connection.execute("SELECT COUNT(*) FROM equipment_repair_events").fetchone()[0] == 1
                assert connection.execute(
                    "SELECT COUNT(*) FROM operations WHERE operation_id='repair-after-close-new'"
                ).fetchone()[0] == 0
        finally:
            await recovered.close()

    asyncio.run(run())
