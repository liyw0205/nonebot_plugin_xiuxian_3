from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.config import XiuxianSettings
from nonebot_plugin_xiuxian_3.xiuxian.exploration.rules import battle_roll_bp


def _context(adapter: str, user: str, operation_id: str) -> CommandContext:
    return CommandContext(adapter=adapter, user_id=user, operation_id=operation_id)


def test_qq_and_onebot_exploration_encounters_use_frozen_battle_and_replay() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            operations: dict[str, tuple[str, str]] = {}
            for adapter, user in (("qq.official", "qq-exploration-combat"), ("onebot.v11", "ob-exploration-combat")):
                created = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, f"{adapter}-create"),
                    "开始修仙",
                )
                assert created.code == "PLAYER_CREATED"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE players SET stage='cultivator', realm_key='qi_sensing', realm_layer=2, "
                        "location_key='xuantian.outskirts', stamina=100, max_hp=999, initiative=99, "
                        "qualification_json=?, inventory_json=? WHERE platform=? AND platform_user_id=?",
                        (
                            json.dumps({"body": 2_000, "agility": 2_000}),
                            json.dumps({}),
                            adapter,
                            user,
                        ),
                    )
                start_operation = next(
                    f"{adapter}-encounter-{index}"
                    for index in range(1_000)
                    if battle_roll_bp(f"{adapter}-encounter-{index}:battle") < 1_000
                )
                started = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, start_operation),
                    "开始探索 短历练",
                )
                assert started.code == "EXPLORATION_STARTED"
                exploration_id = str(started.data["exploration_id"])
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE players SET qualification_json=?, max_hp=100, initiative=8 "
                        "WHERE platform=? AND platform_user_id=?",
                        (json.dumps({"body": 0, "agility": 0}), adapter, user),
                    )
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE exploration_sessions SET ends_at=? WHERE exploration_id=?",
                        ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(), exploration_id),
                    )
                with patch(
                    "nonebot_plugin_xiuxian_3.xiuxian.exploration.repository.settlement_result",
                    return_value={"item.demon_core": 1},
                ):
                    settled = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, user, f"{adapter}-settle"),
                        "结算探索",
                    )
                assert settled.code == "EXPLORATION_SETTLED"
                assert settled.data["battle_outcome"] == "won"
                assert settled.data["result"] == {"item.demon_core": 1}
                battle_id = str(settled.data["battle_id"])
                replay = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, f"{adapter}-replay"),
                    f"战斗回放 {battle_id}",
                )
                assert replay.code == "BATTLE_REPLAY"
                assert replay.data["enemy_key"] == "enemy.wood_rat"
                assert replay.data["actions"]
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    status, snapshot_text = connection.execute(
                        "SELECT status, snapshot_json FROM exploration_sessions WHERE exploration_id=?",
                        (exploration_id,),
                    ).fetchone()
                    battle_status, linked = connection.execute(
                        "SELECT status, json_extract(snapshot_json, '$.exploration_id') "
                        "FROM battle_sessions WHERE battle_id=?",
                        (battle_id,),
                    ).fetchone()
                    operation_count = connection.execute(
                        "SELECT COUNT(*) FROM operations WHERE operation_id LIKE ?",
                        (f"exploration.battle:{exploration_id}%",),
                    ).fetchone()[0]
                    bindings = connection.execute(
                        "SELECT item_key, quantity FROM exploration_item_bindings WHERE player_id="
                        "(SELECT id FROM players WHERE platform=? AND platform_user_id=?)",
                        (adapter, user),
                    ).fetchall()
                assert status == "settled"
                assert json.loads(snapshot_text)["qualification"]["body"] == 2_000
                assert battle_status == "settled"
                assert linked == exploration_id
                assert operation_count == 1
                assert bindings == [("item.demon_core", 1)]
                operations[adapter] = (exploration_id, f"{adapter}-settle")

            await runtime.close()
            recovered = create_runtime(data_dir=data_dir)
            for adapter, user in (("qq.official", "qq-exploration-combat"), ("onebot.v11", "ob-exploration-combat")):
                replay = await recovered.adapters.dispatch(
                    adapter,
                    _context(adapter, user, operations[adapter][1]),
                    "结算探索",
                )
                assert replay.code == "EXPLORATION_SETTLED"
                assert replay.data["idempotent_replay"] is True
                with sqlite3.connect(recovered.settings.database_path) as connection:
                    assert connection.execute(
                        "SELECT COUNT(*) FROM exploration_item_bindings WHERE player_id="
                        "(SELECT id FROM players WHERE platform=? AND platform_user_id=?)",
                        (adapter, user),
                    ).fetchone()[0] == 1
            await recovered.close()

    asyncio.run(run())


def test_exploration_battle_loss_does_not_award_frozen_result() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            adapter = "onebot.v11"
            user = "exploration-combat-loss"
            created = await runtime.adapters.dispatch(
                adapter,
                _context(adapter, user, "loss-create"),
                "开始修仙",
            )
            assert created.code == "PLAYER_CREATED"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE players SET stage='cultivator', realm_key='qi_gathering', realm_layer=4, "
                    "location_key='cave.mist_grotto', stamina=100, max_hp=100, initiative=8, "
                    "qualification_json=?, inventory_json=? WHERE platform=? AND platform_user_id=?",
                    (json.dumps({"body": 0, "agility": 0}), json.dumps({"item.cave_pass_basic": 1}), adapter, user),
                )
            start_operation = next(
                f"mist-loss-{index}"
                for index in range(1_000)
                if battle_roll_bp(f"mist-loss-{index}:battle") < 2_500
            )
            started = await runtime.adapters.dispatch(
                adapter,
                _context(adapter, user, start_operation),
                "开始探索 雾隐洞天探索",
            )
            assert started.code == "EXPLORATION_STARTED"
            exploration_id = str(started.data["exploration_id"])
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE exploration_sessions SET ends_at=? WHERE exploration_id=?",
                    ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(), exploration_id),
                )
                before = connection.execute(
                    "SELECT cultivation, total_cultivation, spirit_stones, inventory_json FROM players "
                    "WHERE platform=? AND platform_user_id=?",
                    (adapter, user),
                ).fetchone()
            with patch(
                "nonebot_plugin_xiuxian_3.xiuxian.exploration.repository.settlement_result",
                return_value={"item.demon_core": 1},
            ):
                settled = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "loss-settle"),
                    "结算探索",
                )
            assert settled.code == "EXPLORATION_SETTLED"
            assert settled.data["battle_outcome"] == "lost"
            assert settled.data["result"] == {}
            with sqlite3.connect(runtime.settings.database_path) as connection:
                after = connection.execute(
                    "SELECT cultivation, total_cultivation, spirit_stones, inventory_json FROM players "
                    "WHERE platform=? AND platform_user_id=?",
                    (adapter, user),
                ).fetchone()
                bindings = connection.execute("SELECT COUNT(*) FROM exploration_item_bindings").fetchone()[0]
            assert after == before
            assert bindings == 0
            await runtime.close()

    asyncio.run(run())


def test_exploration_auto_battle_does_not_nest_inflight_semaphore() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(
                settings=XiuxianSettings(data_dir=Path(data_dir), max_inflight=1),
            )
            adapter = "qq.official"
            user = "exploration-inflight-one"
            created = await runtime.adapters.dispatch(
                adapter,
                _context(adapter, user, "one-create"),
                "开始修仙",
            )
            assert created.code == "PLAYER_CREATED"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE players SET stage='cultivator', realm_key='qi_sensing', realm_layer=2, "
                    "location_key='xuantian.outskirts', stamina=100, max_hp=999, initiative=99, "
                    "qualification_json=? WHERE platform=? AND platform_user_id=?",
                    (json.dumps({"body": 2_000, "agility": 2_000}), adapter, user),
                )
            operation = next(
                f"one-inflight-{index}"
                for index in range(1_000)
                if battle_roll_bp(f"one-inflight-{index}:battle") < 1_000
            )
            started = await runtime.adapters.dispatch(
                adapter,
                _context(adapter, user, operation),
                "开始探索 短历练",
            )
            assert started.code == "EXPLORATION_STARTED"
            exploration_id = str(started.data["exploration_id"])
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE exploration_sessions SET ends_at=? WHERE exploration_id=?",
                    ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(), exploration_id),
                )
            settled = await asyncio.wait_for(
                runtime.adapters.dispatch(adapter, _context(adapter, user, "one-settle"), "结算探索"),
                timeout=5,
            )
            assert settled.code == "EXPLORATION_SETTLED"
            await runtime.close()

    asyncio.run(run())
