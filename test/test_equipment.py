from __future__ import annotations

import asyncio
import json
import sqlite3
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.advancement.equipment_rules import (
    refinement_roll_bp,
    temper_roll_bp,
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
                assert json.loads(event[0])["rule_version"] == "advancement-0.1.0"
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
