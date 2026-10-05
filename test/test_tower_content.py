from __future__ import annotations

import asyncio
import json
import shutil
import sqlite3
from pathlib import Path

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime


ADAPTERS = ("qq.official", "onebot.v11")


def _copy_data(tmp_path: Path) -> Path:
    target = tmp_path / "data"
    shutil.copytree(Path(__file__).parents[1] / "data", target)
    (target / "xiuxian3.sqlite3").unlink(missing_ok=True)
    return target


def _update_record(path: Path, key: str, **changes: object) -> None:
    document = json.loads(path.read_text(encoding="utf-8"))
    next(record for record in document["records"] if record["key"] == key).update(changes)
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _tower_record(data_dir: Path) -> dict:
    path = data_dir / "特殊" / "试炼塔.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    return next(record for record in document["records"] if record["key"] == "tower.mist_trial")


def _write_tower(data_dir: Path, tower: dict) -> None:
    path = data_dir / "特殊" / "试炼塔.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    target = next(record for record in document["records"] if record["key"] == "tower.mist_trial")
    target.clear()
    target.update(tower)
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _context(adapter: str, user: str, operation_id: str) -> CommandContext:
    return CommandContext(adapter=adapter, user_id=user, operation_id=operation_id)


async def _send(runtime, adapter: str, user: str, operation_id: str, command: str):
    return await runtime.adapters.dispatch(
        adapter, _context(adapter, user, operation_id), command
    )


async def _enter_tower(runtime, adapter: str, user: str) -> None:
    for index, command in enumerate(
        (
            "开始修仙",
            "寻仙问道",
            "完成引导 阅读",
            "前往近郊",
            "完成引导 采集",
            "完成引导 炼丹",
            "选择道途 体修",
        )
    ):
        result = await _send(runtime, adapter, user, f"{user}-setup-{index}", command)
        assert result.ok, (command, result.code, result.message)


def test_tower_reward_snapshot_survives_content_change_close_restart_and_replay(tmp_path: Path) -> None:
    async def run() -> None:
        data_dir = _copy_data(tmp_path)
        tower = _tower_record(data_dir)
        tower["segments"][0]["first_clear_rewards"] = [
            {"weight": 1, "rewards": {"spirit_stones": 17, "item.mat.array_sand": 2}}
        ]
        tower["segments"][0]["repeat_rewards"] = [
            {"weight": 1, "rewards": {"item.mat.array_sand": 1}}
        ]
        tower["status"] = "active"
        _write_tower(data_dir, tower)
        _update_record(
            data_dir / "战斗" / "敌人.json",
            "enemy.mist_trial.sensing",
            stats={"hp": 1, "attack": 1, "initiative": 1, "agility": 1},
        )
        runtime = create_runtime(data_dir=data_dir, adapters=ADAPTERS)
        pending: dict[str, str] = {}
        try:
            for adapter in ADAPTERS:
                user = f"tower-content-{adapter}"
                await _enter_tower(runtime, adapter, user)
                started = await _send(runtime, adapter, user, f"{user}-challenge", "挑战试炼塔 1")
                assert started.code == "TOWER_CHALLENGE_SETTLED"
                assert started.data["reward"] == {
                    "item.mat.array_sand": 2,
                    "spirit_stones": 17,
                }
                assert started.data["status"] == "reward_pending"
                pending[adapter] = user
        finally:
            await runtime.close()

        tower["status"] = "locked"
        tower["segments"][0]["first_clear_rewards"] = [
            {"weight": 1, "rewards": {"spirit_stones": 99, "item.mat.array_sand": 9}}
        ]
        _write_tower(data_dir, tower)
        recovered = create_runtime(data_dir=data_dir, adapters=ADAPTERS)
        try:
            for adapter, user in pending.items():
                replayed = await _send(
                    recovered, adapter, user, f"{user}-challenge", "挑战试炼塔 1"
                )
                assert replayed.code == "TOWER_CHALLENGE_SETTLED"
                assert replayed.data["idempotent_replay"] is True
                assert replayed.data["reward"] == {
                    "item.mat.array_sand": 2,
                    "spirit_stones": 17,
                }
                claimed = await _send(
                    recovered, adapter, user, f"{user}-claim", "领取试炼塔奖励"
                )
                assert claimed.code == "TOWER_REWARD_CLAIMED"
                assert claimed.data["reward"] == {
                    "item.mat.array_sand": 2,
                    "spirit_stones": 17,
                }
                replay = await _send(
                    recovered, adapter, user, f"{user}-claim", "领取试炼塔奖励"
                )
                assert replay.data["idempotent_replay"] is True
                with sqlite3.connect(recovered.settings.database_path) as connection:
                    inventory, stones, status = connection.execute(
                        "SELECT p.inventory_json,p.spirit_stones,t.status "
                        "FROM players p JOIN tower_runs t ON t.player_id=p.id "
                        "WHERE p.platform=? AND p.platform_user_id=?",
                        (adapter, user),
                    ).fetchone()
                assert json.loads(inventory)["item.mat.array_sand"] == 2
                assert stones == 317
                assert status == "claimed"
        finally:
            await recovered.close()

    asyncio.run(run())


def test_tower_bad_content_is_rejected_before_stamina_or_run_write(tmp_path: Path) -> None:
    async def run() -> None:
        data_dir = _copy_data(tmp_path)
        tower = _tower_record(data_dir)
        tower["segments"][0]["enemy_key"] = "enemy.missing"
        _write_tower(data_dir, tower)
        runtime = create_runtime(data_dir=data_dir, adapters=ADAPTERS)
        try:
            for adapter in ADAPTERS:
                user = f"tower-invalid-{adapter}"
                await _enter_tower(runtime, adapter, user)
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    before = connection.execute(
                        "SELECT stamina FROM players WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    ).fetchone()[0]
                result = await _send(runtime, adapter, user, f"{user}-challenge", "挑战试炼塔 1")
                assert result.code == "TOWER_REQUIREMENT_MISSING"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    after, runs = connection.execute(
                        "SELECT p.stamina, (SELECT COUNT(*) FROM tower_runs t WHERE t.player_id=p.id) "
                        "FROM players p WHERE p.platform=? AND p.platform_user_id=?",
                        (adapter, user),
                    ).fetchone()
                assert after == before
                assert runs == 0
        finally:
            await runtime.close()

    asyncio.run(run())
