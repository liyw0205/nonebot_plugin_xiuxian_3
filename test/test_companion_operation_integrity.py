from __future__ import annotations

import asyncio
import json
import shutil
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from nonebot_plugin_xiuxian_3.runtime import create_runtime

from test_companions import _context, _prepare


def _operation_result(database: str, operation_id: str) -> str:
    with sqlite3.connect(database) as connection:
        return str(
            connection.execute(
                "SELECT result_json FROM operations WHERE operation_id = ?", (operation_id,)
            ).fetchone()[0]
        )


def _state(database: str, instance_id: str) -> tuple[object, ...]:
    with sqlite3.connect(database) as connection:
        return tuple(
            connection.execute(
                "SELECT spirit_stones, inventory_json FROM players "
                "JOIN companion_instances ON companion_instances.player_id = players.id "
                "WHERE companion_instances.instance_id = ?",
                (instance_id,),
            ).fetchone()
        ) + tuple(
            connection.execute(
                "SELECT experience, level, status, evolution_stage FROM companion_instances "
                "WHERE instance_id = ?",
                (instance_id,),
            ).fetchone()
        )


def _duplicate_companion_experience(raw: str) -> str:
    payload = json.loads(raw)
    compact = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    marker = '"experience":'
    offset = compact.index(marker)
    value_start = offset + len(marker)
    value_end = value_start
    while value_end < len(compact) and compact[value_end] not in ",}":
        value_end += 1
    return compact[:value_end] + "," + marker + "9999" + compact[value_end:]


def test_companion_operation_replay_rejects_corruption_on_both_adapters() -> None:
    async def run() -> None:
        for adapter in ("qq.official", "onebot.v11"):
            with TemporaryDirectory() as data_dir:
                runtime = create_runtime(data_dir=data_dir, adapters=(adapter,))
                user = f"integrity-{adapter}"
                await _prepare(runtime, adapter=adapter, user=user)
                bonded = await runtime.dispatch(
                    _context(adapter, user, "bond", "bond"), "结缘灵兽 beast.wood_rat"
                )
                instance_id = str(bonded.data["instance_id"])
                operation_id = "feed"
                fed = await runtime.dispatch(
                    _context(adapter, user, operation_id, "feed"),
                    f"喂养灵兽 {instance_id}",
                )
                assert fed.code == "COMPANION_FED"
                original = _operation_result(runtime.settings.database_path, operation_id)
                before = _state(runtime.settings.database_path, instance_id)

                for index, corrupted in enumerate((
                    _duplicate_companion_experience(original),
                    json.dumps({**json.loads(original), "companion": {**json.loads(original)["companion"], "experience": 9999}}),
                    original[:-1],
                    "[]",
                )):
                    with sqlite3.connect(runtime.settings.database_path) as connection:
                        connection.execute(
                            "UPDATE operations SET result_json = ? WHERE operation_id = ?",
                            (corrupted, operation_id),
                        )
                    rejected = await runtime.dispatch(
                        _context(adapter, user, operation_id, f"{operation_id}-bad"),
                        f"喂养灵兽 {instance_id}",
                    )
                    assert rejected.code == "PERSISTENCE_ERROR", index
                    assert _state(runtime.settings.database_path, instance_id) == before
                    with sqlite3.connect(runtime.settings.database_path) as connection:
                        connection.execute(
                            "UPDATE operations SET result_json = ? WHERE operation_id = ?",
                            (original, operation_id),
                        )

                replay = await runtime.dispatch(
                    _context(adapter, user, operation_id, f"{operation_id}-repair"),
                    f"喂养灵兽 {instance_id}",
                )
                assert replay.code == "COMPANION_FED"
                assert replay.data["idempotent_replay"] is True
                assert _state(runtime.settings.database_path, instance_id) == before

                conflict = await runtime.dispatch(
                    _context(adapter, user, operation_id, f"{operation_id}-conflict"),
                    "喂养灵兽 missing-companion",
                )
                assert conflict.code == "OPERATION_CONFLICT"

                await runtime.close()
                runtime = create_runtime(data_dir=data_dir, adapters=(adapter,))
                restarted = await runtime.dispatch(
                    _context(adapter, user, operation_id, f"{operation_id}-restart"),
                    f"喂养灵兽 {instance_id}",
                )
                assert restarted.code == "COMPANION_FED"
                assert restarted.data["idempotent_replay"] is True
                assert _state(runtime.settings.database_path, instance_id) == before
                await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("action", ("bond", "equip", "evolve"))
def test_companion_replay_keeps_frozen_result_after_content_changes(action: str) -> None:
    async def run() -> None:
        for adapter in ("qq.official", "onebot.v11"):
            with TemporaryDirectory() as directory:
                data_dir = Path(directory) / "data"
                shutil.copytree(Path(__file__).parents[1] / "data", data_dir)
                runtime = create_runtime(data_dir=data_dir)
                user = f"frozen-{adapter}"
                try:
                    await _prepare(runtime, adapter=adapter, user=user)
                    bonded = await runtime.dispatch(
                        _context(adapter, user, "bond", "bond"), "结缘灵兽 beast.wood_rat"
                    )
                    assert bonded.code == "COMPANION_BONDED"
                    instance_id = str(bonded.data["instance_id"])
                    operation_id = action
                    command = "结缘灵兽 beast.wood_rat"
                    original = bonded
                    content_path = data_dir / "灵兽" / "灵兽.json"
                    if action == "equip":
                        command = f"装备灵具 {instance_id} beast.gear.sack_small"
                        original = await runtime.dispatch(
                            _context(adapter, user, action, action), command
                        )
                        assert original.code == "COMPANION_GEAR_EQUIPPED"
                    elif action == "evolve":
                        with runtime.repository._connect() as connection:
                            connection.execute(
                                "UPDATE players SET spirit_stones=500, inventory_json=? "
                                "WHERE platform=? AND platform_user_id=?",
                                (json.dumps({"item.ancient_fruit": 3}), adapter, user),
                            )
                            connection.execute(
                                "UPDATE companion_instances SET level=10, affinity=40 WHERE instance_id=?",
                                (instance_id,),
                            )
                        command = f"蜕变灵兽 {instance_id}"
                        operation_id = "evolve-op"
                        original = await runtime.dispatch(
                            _context(adapter, user, operation_id, action), command
                        )
                        assert original.code == "COMPANION_EVOLVED"
                        content_path = data_dir / "灵兽" / "蜕变.json"
                    await runtime.close()
                    content = json.loads(content_path.read_text(encoding="utf-8"))
                    if action == "bond":
                        record = next(row for row in content["records"] if row["key"] == "beast.wood_rat")
                        record["name"] = "Renamed wood rat"
                    elif action == "equip":
                        record = next(row for row in content["records"] if row["key"] == "beast.gear.sack_small")
                        record["status"] = "locked"
                    else:
                        record = next(row for row in content["records"] if row["key"] == "beast.evolution.wood_rat_1")
                        record["costs"]["spirit_stones"] = 400
                    content_path.write_text(json.dumps(content, ensure_ascii=False), encoding="utf-8")
                    runtime = create_runtime(data_dir=data_dir)
                    await runtime.repository.initialize()
                    with runtime.repository._connect() as connection:
                        before = tuple(connection.iterdump())
                    replay = await runtime.dispatch(
                        _context(adapter, user, operation_id, "replay"), command
                    )
                    assert replay.code == original.code, (replay.code, replay.message)
                    assert replay.data["idempotent_replay"] is True
                    assert {key: value for key, value in replay.data.items() if key != "idempotent_replay"} == {
                        key: value for key, value in original.data.items() if key != "idempotent_replay"
                    }
                    with runtime.repository._connect() as connection:
                        assert tuple(connection.iterdump()) == before
                finally:
                    await runtime.close()

    asyncio.run(run())
