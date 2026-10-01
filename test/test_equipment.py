from __future__ import annotations

import asyncio
import json
import sqlite3
import shutil
from collections import defaultdict
from tempfile import TemporaryDirectory
from pathlib import Path

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.content import bundled_content
from nonebot_plugin_xiuxian_3.xiuxian.advancement.equipment_rules import (
    EQUIPMENT_DEFINITIONS,
    equipment_resource_label,
    refinement_affix,
    refinement_roll_bp,
    temper_cost,
    temper_roll_bp,
    temper_success_bp,
)


def _context(user_id: str, request_id: str, *, operation_id: str = "") -> CommandContext:
    return CommandContext(adapter="web", user_id=user_id, request_id=request_id, operation_id=operation_id)


async def _enter_cultivator(runtime, user_id: str) -> None:
    commands = (
        "开始修仙",
        "寻仙问道",
        "完成引导 阅读",
        "前往近郊",
        "完成引导 采集",
        "完成引导 炼丹",
        "选择道途 体修",
    )
    for index, command in enumerate(commands):
        result = await runtime.dispatch(_context(user_id, f"setup-{index}"), command)
        assert result.ok, (command, result.code, result.message)


def _set_equipment_resources(runtime, user_id: str, *, ironstone: int, stones: int, sword: int = 1) -> None:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        row = connection.execute(
            "SELECT inventory_json FROM players WHERE platform = ? AND platform_user_id = ?",
            ("web", user_id),
        ).fetchone()
        assert row is not None
        inventory = json.loads(row[0])
        inventory["item.weapon.wood_sword"] = sword
        inventory["item.ore.ironstone"] = ironstone
        connection.execute(
            "UPDATE players SET inventory_json = ?, spirit_stones = ? WHERE platform = ? AND platform_user_id = ?",
            (json.dumps(inventory, ensure_ascii=False, sort_keys=True), stones, "web", user_id),
        )


def _equipment_state(runtime, user_id: str) -> tuple[str, int, dict[str, int], int]:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        row = connection.execute(
            """
            SELECT instance_id, temper_level, affixes_json, refinement_failure_streak
            FROM equipment_instances
            WHERE player_id = (SELECT id FROM players WHERE platform = ? AND platform_user_id = ?)
              AND item_key = 'item.weapon.wood_sword' AND status = 'active'
            ORDER BY id LIMIT 1
            """,
            ("web", user_id),
        ).fetchone()
        assert row is not None
        return row[0], int(row[1]), json.loads(row[2]), int(row[3])


def test_equipment_growth_and_affixes_come_from_content_records() -> None:
    cloud_sword = EQUIPMENT_DEFINITIONS["item.weapon.cloud_sword"]

    assert cloud_sword.max_temper_level == 5
    assert temper_cost(5, cloud_sword) == {
        "item.material.cloud_iron": 8,
        "currency.spirit_stone": 500,
    }
    assert temper_success_bp(5, cloud_sword) == 3000
    assert equipment_resource_label("item.material.cloud_iron") == "云铁"
    assert cloud_sword.growth["refinement"]["pity_failures"] == 4
    assert {
        refinement_affix(str(seed), cloud_sword)[0]
        for seed in range(200)
    } == {"damage", "hp", "initiative"}


def test_equipment_catalog_covers_every_quality_with_distinct_combat_stats() -> None:
    content = bundled_content()
    qualities = {"common", "uncommon", "rare", "heaven", "mythic"}
    for item_type in ("weapon", "armor"):
        records = [
            row
            for row in content.list("item", include_locked=False)
            if row.get("item_type") == item_type
        ]
        assert len({row["key"] for row in records}) == len(records)
        assert len(records) >= 879
        assert all(sum(row.get("quality") == quality for row in records) >= 9 for quality in qualities)
        assert {row["key"] for row in records} <= set(EQUIPMENT_DEFINITIONS)
        flat_stats = {
            "physical_damage", "max_hp", "max_mana", "hp_regen", "mana_regen", "initiative", "agility",
        }
        combat_stats = {
            "damage_reduction_bp", "crit_chance_bp", "crit_damage_bp", "evasion_bp", "accuracy_bp",
            "anti_crit_bp", "damage_reflection_bp", "lifesteal_bp", "mana_leech_bp",
            "healing_reduction_bp", "recovery_reduction_bp",
        }
        assert all(
            (effect.get("type") == "flat_stat" and effect.get("stat") in flat_stats)
            or (effect.get("type") == "combat_stat_bp" and effect.get("stat") in combat_stats)
            for row in records
            for effect in row.get("effects", [])
        )
        paths = {row["key"] for row in content.list("path", include_locked=False)}
        realms = {
            row["key"]
            for row in content.list("realm", include_locked=False)
            if row["key"] != "mortal"
        }
        records_by_build: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
        for row in records:
            if row.get("path_key") is None:
                continue
            realm_requirements = [
                requirement for requirement in row["requirements"]
                if requirement.get("type") == "realm"
            ]
            assert len(realm_requirements) == 1
            records_by_build[(row["path_key"], realm_requirements[0]["realm_key"])].append(row)
        expected_builds = {(path, realm) for path in paths for realm in realms}
        assert set(records_by_build) == expected_builds
        assert all(len(rows) >= 16 for rows in records_by_build.values())
        assert all(
            len({tuple(sorted((effect["stat"], effect["value"]) for effect in row["effects"])) for row in rows})
            == len(rows)
            for rows in records_by_build.values()
        )

    for item_type in ("weapon", "armor"):
        records = [
            row for row in content.list("item", include_locked=False)
            if row.get("item_type") == item_type and row.get("path_key") is not None
        ]
        assert len({row["name"] for row in records}) == len(records)

    accessories = [
        row for row in content.list("item", include_locked=False)
        if row.get("item_type") == "accessory"
    ]
    realms = {
        row["key"]
        for row in content.list("realm", include_locked=False)
        if row["key"] != "mortal"
    }
    paths = {row["key"] for row in content.list("path", include_locked=False)}
    accessories_by_build: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    for row in accessories:
        realm_requirements = [
            requirement for requirement in row["requirements"]
            if requirement.get("type") == "realm"
        ]
        assert len(realm_requirements) == 1
        accessories_by_build[(row["path_key"], realm_requirements[0]["realm_key"])].append(row)

    expected_builds = {(path, realm) for path in paths for realm in realms}
    assert set(accessories_by_build) == expected_builds
    assert all(len(rows) >= 2 for rows in accessories_by_build.values())
    assert all(
        len({tuple(sorted((effect["stat"], effect["value"]) for effect in row["effects"])) for row in rows})
        == len(rows)
        for rows in accessories_by_build.values()
    )
    supported_stats = {
        "physical_damage", "max_hp", "max_mana", "hp_regen", "mana_regen",
        "damage_reduction_bp", "crit_chance_bp", "crit_damage_bp", "evasion_bp",
        "accuracy_bp", "anti_crit_bp", "damage_reflection_bp", "lifesteal_bp",
        "mana_leech_bp", "healing_reduction_bp", "recovery_reduction_bp", "initiative", "agility",
    }
    assert {effect["stat"] for row in accessories for effect in row["effects"]} >= supported_stats
    assert {row["key"] for row in accessories} <= set(EQUIPMENT_DEFINITIONS)


def test_equipment_growth_profile_changes_real_tempering() -> None:
    async def run(data_dir: Path) -> None:
        growth_path = data_dir / "装备" / "成长.json"
        document = json.loads(growth_path.read_text(encoding="utf-8"))
        profile = next(row for row in document["records"] if row["key"] == "equipment.growth.uncommon")
        profile["growth"]["temper"]["max_level"] = 1
        profile["growth"]["temper"]["costs"] = {
            "1": {"item.ore.ironstone": 1, "currency.spirit_stone": 5}
        }
        profile["growth"]["temper"]["success_bp"] = {"1": 10000}
        growth_path.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")

        runtime = create_runtime(data_dir=data_dir)
        preview = await runtime.dispatch(_context("missing", "profile-preview"), "法器预览")
        assert "青霜剑" in preview.message
        assert "最高阶数：1" in preview.message

        user = "equipment-profile-config"
        await _enter_cultivator(runtime, user)
        with sqlite3.connect(runtime.settings.database_path) as connection:
            row = connection.execute(
                "SELECT inventory_json FROM players WHERE platform = 'web' AND platform_user_id = ?",
                (user,),
            ).fetchone()
            inventory = json.loads(row[0])
            inventory["item.weapon.green_frost_sword"] = 1
            inventory["item.ore.ironstone"] = 2
            connection.execute(
                "UPDATE players SET inventory_json = ?, spirit_stones = 10, realm_key = 'qi_gathering', realm_layer = 1 WHERE platform = 'web' AND platform_user_id = ?",
                (json.dumps(inventory, ensure_ascii=False, sort_keys=True), user),
            )

        result = await runtime.dispatch(
            _context(user, "temper-profile", operation_id="temper-profile-config"),
            "强化法器 青霜剑",
        )
        assert result.code == "EQUIPMENT_TEMPERED"
        assert result.data["success"] is True
        assert result.data["costs_spent"] == {
            "item.ore.ironstone": 1,
            "currency.spirit_stone": 5,
        }
        with sqlite3.connect(runtime.settings.database_path) as connection:
            equipment = connection.execute(
                "SELECT temper_level, max_temper_level FROM equipment_instances WHERE item_key = 'item.weapon.green_frost_sword'"
            ).fetchone()
        assert equipment == (1, 1)
        await runtime.close()

    with TemporaryDirectory() as directory:
        data_dir = Path(directory) / "data"
        shutil.copytree(Path(__file__).parents[1] / "data", data_dir)
        asyncio.run(run(data_dir))


def test_equipment_tempering_is_idempotent_and_migrates_legacy_inventory() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            user = "equipment-temper"
            assert (await runtime.dispatch(_context(user, "missing-preview"), "法器预览")).ok
            assert (await runtime.dispatch(_context(user, "missing"), "强化法器 木纹剑")).code == "PLAYER_NOT_FOUND"
            await _enter_cultivator(runtime, user)
            _set_equipment_resources(runtime, user, ironstone=100, stones=10_000)

            first = await runtime.dispatch(
                _context(user, "temper-1", operation_id="equipment-temper-1"),
                "强化法器 木纹剑",
            )
            assert first.code == "EQUIPMENT_TEMPERED"
            assert first.data["temper_level"] == 1
            instance_id, level, _, _ = _equipment_state(runtime, user)
            assert level == 1
            with sqlite3.connect(runtime.settings.database_path) as connection:
                inventory = json.loads(
                    connection.execute(
                        "SELECT inventory_json FROM players WHERE platform_user_id = ?", (user,)
                    ).fetchone()[0]
                )
                assert inventory.get("item.weapon.wood_sword", 0) == 0

            replay = await runtime.dispatch(
                _context(user, "temper-1-replay", operation_id="equipment-temper-1"),
                "强化法器 木纹剑",
            )
            assert replay.code == "EQUIPMENT_TEMPERED"
            assert replay.data["idempotent_replay"] is True
            conflict = await runtime.dispatch(
                _context(user, "temper-1-conflict", operation_id="equipment-temper-1"),
                "强化法器 棉袍",
            )
            assert conflict.code == "OPERATION_CONFLICT"

            # Find deterministic outcomes without weakening the production rule.
            fail_op = next(
                f"equipment-temper-fail-{index}"
                for index in range(100)
                if temper_roll_bp(f"equipment-temper-fail-{index}:{instance_id}:2") >= 9000
            )
            failed = await runtime.dispatch(
                _context(user, "temper-failed", operation_id=fail_op),
                "强化法器 木纹剑",
            )
            assert failed.data["success"] is False
            assert _equipment_state(runtime, user)[1] == 1

            success_op = next(
                f"equipment-temper-success-{index}"
                for index in range(100)
                if temper_roll_bp(f"equipment-temper-success-{index}:{instance_id}:2") < 9000
            )
            second = await runtime.dispatch(
                _context(user, "temper-success", operation_id=success_op),
                "强化法器 木纹剑",
            )
            assert second.data["success"] is True
            assert _equipment_state(runtime, user)[1] == 2

            third_op = next(
                f"equipment-temper-third-{index}"
                for index in range(100)
                if temper_roll_bp(f"equipment-temper-third-{index}:{instance_id}:3") < 7500
            )
            third = await runtime.dispatch(
                _context(user, "temper-third", operation_id=third_op),
                "强化法器 木纹剑",
            )
            assert third.data["success"] is True
            assert _equipment_state(runtime, user)[1] == 3
            assert (await runtime.dispatch(_context(user, "temper-maxed"), "强化法器 木纹剑")).code == "EQUIPMENT_MAXED"

            with sqlite3.connect(runtime.settings.database_path) as connection:
                events = connection.execute(
                    "SELECT COUNT(*) FROM equipment_tempering_events WHERE player_id = (SELECT id FROM players WHERE platform_user_id = ?)",
                    (user,),
                ).fetchone()[0]
            assert events == 4
            await runtime.close()

    asyncio.run(run())


def test_equipment_refinement_pity_and_resource_zero_change() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            user = "equipment-refine"
            await _enter_cultivator(runtime, user)
            _set_equipment_resources(runtime, user, ironstone=0, stones=0)
            before = sqlite3.connect(runtime.settings.database_path)
            try:
                before_player = before.execute(
                    "SELECT inventory_json, spirit_stones FROM players WHERE platform_user_id = ?", (user,)
                ).fetchone()
            finally:
                before.close()
            insufficient = await runtime.dispatch(_context(user, "insufficient"), "重铸法器 木纹剑")
            assert insufficient.code == "EQUIPMENT_RESOURCE_INSUFFICIENT"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                after_player = connection.execute(
                    "SELECT inventory_json, spirit_stones FROM players WHERE platform_user_id = ?", (user,)
                ).fetchone()
                assert connection.execute("SELECT COUNT(*) FROM equipment_instances").fetchone()[0] == 0
            assert after_player == before_player

            _set_equipment_resources(runtime, user, ironstone=20, stones=1_000)
            tempered = await runtime.dispatch(_context(user, "make-instance"), "强化法器 木纹剑")
            assert tempered.ok
            instance_id, _, old_affixes, _ = _equipment_state(runtime, user)
            assert old_affixes == {}

            for streak in range(3):
                operation_id = next(
                    f"equipment-refine-fail-{streak}-{index}"
                    for index in range(100)
                    if refinement_roll_bp(
                        f"equipment-refine-fail-{streak}-{index}:{instance_id}:{streak}"
                    ) >= 7500
                )
                failed = await runtime.dispatch(
                    _context(user, f"refine-fail-{streak}", operation_id=operation_id),
                    "重铸法器 木纹剑",
                )
                assert failed.code == "EQUIPMENT_REFINED"
                assert failed.data["success"] is False
                assert failed.data["new_affixes"] == {}
                assert failed.data["failure_streak_after"] == streak + 1

            pity = await runtime.dispatch(
                _context(user, "refine-pity", operation_id="equipment-refine-pity"),
                "重铸法器 木纹剑",
            )
            assert pity.code == "EQUIPMENT_REFINED"
            assert pity.data["success"] is True
            assert pity.data["new_affixes"]
            assert pity.data["failure_streak_after"] == 0
            replay = await runtime.dispatch(
                _context(user, "refine-pity-replay", operation_id="equipment-refine-pity"),
                "重铸法器 木纹剑",
            )
            assert replay.data["idempotent_replay"] is True
            with sqlite3.connect(runtime.settings.database_path) as connection:
                event = connection.execute(
                    "SELECT snapshot_json FROM equipment_refinement_events WHERE operation_id = ?",
                    ("equipment-refine-pity",),
                ).fetchone()
                assert event is not None
            await runtime.close()

    asyncio.run(run())


def test_equipment_requires_ownership_and_respects_long_action_and_concurrency() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            user = "equipment-gates"
            await _enter_cultivator(runtime, user)
            _set_equipment_resources(runtime, user, ironstone=10, stones=200, sword=0)
            missing = await runtime.dispatch(_context(user, "no-item"), "强化法器 木纹剑")
            assert missing.code == "EQUIPMENT_NOT_OWNED"
            busy_user = "equipment-busy"
            await _enter_cultivator(runtime, busy_user)
            _set_equipment_resources(runtime, busy_user, ironstone=10, stones=200)
            started = await runtime.dispatch(_context(busy_user, "retreat"), "开始闭关")
            assert started.ok
            blocked = await runtime.dispatch(_context(busy_user, "busy-temper"), "强化法器 木纹剑")
            assert blocked.code == "EQUIPMENT_BUSY"

            concurrent = "equipment-concurrent"
            await _enter_cultivator(runtime, concurrent)
            _set_equipment_resources(runtime, concurrent, ironstone=1, stones=20)
            results = await asyncio.gather(
                *(
                    runtime.dispatch(
                        _context(concurrent, f"concurrent-{index}", operation_id=f"equipment-concurrent-{index}"),
                        "强化法器 木纹剑",
                    )
                    for index in range(12)
                )
            )
            assert sum(result.ok for result in results) == 1
            assert {result.code for result in results} == {
                "EQUIPMENT_TEMPERED",
                "EQUIPMENT_RESOURCE_INSUFFICIENT",
            }
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute(
                    "SELECT COUNT(*) FROM equipment_tempering_events WHERE player_id = (SELECT id FROM players WHERE platform_user_id = ?)",
                    (concurrent,),
                ).fetchone()[0] == 1
            await runtime.close()

    asyncio.run(run())
