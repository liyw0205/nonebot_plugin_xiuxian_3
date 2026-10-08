from __future__ import annotations

import asyncio
import json
import shutil
import sqlite3
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.contracts import CommandContext


def _context(adapter: str, user_id: str, request_id: str) -> CommandContext:
    return CommandContext(adapter=adapter, user_id=user_id, request_id=request_id)


async def _create(runtime, context: CommandContext, key: str) -> None:
    assert (await runtime.adapters.dispatch(context.adapter, replace(context, operation_id=key), "开始修仙")).ok
    assert (await runtime.adapters.dispatch(context.adapter, replace(context, operation_id=key + "-seek"), "寻仙问道")).ok


def test_spar_is_immediate_adapter_neutral_and_read_only() -> None:
    async def run() -> None:
        qq = _context("qq.official", "qq-user", "qq-request")
        onebot = _context("onebot.v11", "ob-user", "ob-request")
        with TemporaryDirectory() as data_dir:
            content_dir = Path(data_dir) / "data"
            shutil.copytree(Path(__file__).parents[1] / "data", content_dir)
            content_path = content_dir / "社交" / "玩家互动.json"
            content = json.loads(content_path.read_text(encoding="utf-8"))
            content["records"][0]["max_rounds"] = 1
            content_path.write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")
            runtime = create_runtime(data_dir=content_dir)
            await _create(runtime, qq, "qq-create")
            await _create(runtime, onebot, "ob-create")
            with sqlite3.connect(runtime.settings.database_path) as connection:
                for context, name in ((qq, "甲"), (onebot, "乙_观星*客")):
                    connection.execute(
                        "UPDATE players SET stage='cultivator', realm_key='qi_sensing', realm_layer=1, dao_name=? WHERE platform=? AND platform_user_id=?",
                        (name, context.adapter, context.user_id),
                    )
                before_players = connection.execute(
                    "SELECT platform_user_id, spirit_stones, total_cultivation, stamina, energy, inventory_json, durability_json FROM players ORDER BY id"
                ).fetchall()
                before_operations = connection.execute("SELECT COUNT(*) FROM operations").fetchone()[0]
                before_battle_rows = {
                    table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                    for table in ("battle_sessions", "battle_actions", "codex_entries")
                }
                before_database = tuple(connection.iterdump())

            result = await runtime.adapters.dispatch(
                qq.adapter, replace(qq, operation_id="spar-start"), "切磋 乙_观星*客"
            )
            assert result.code == "SPAR_SPECTATOR"
            assert result.data["status"] == "preview"
            assert result.data["persistent"] is False
            assert result.data["rounds"] == 1
            assert result.data["actions"]
            assert "乙\\_观星\\*客" in result.message
            assert "交手合数" in result.message
            assert "点伤害" not in result.message
            assert "qq-user" not in json.dumps(result.data, ensure_ascii=False)
            assert "ob-user" not in json.dumps(result.data, ensure_ascii=False)
            self_spar = await runtime.adapters.dispatch(
                qq.adapter, replace(qq, operation_id="spar-self"), "切磋 甲"
            )
            assert self_spar.code == "SPAR_REQUIREMENT_MISSING"
            missing = await runtime.adapters.dispatch(
                qq.adapter, replace(qq, operation_id="spar-missing"), "切磋 不存在的道号"
            )
            assert missing.code == "PLAYER_NOT_FOUND"
            repeated = await runtime.adapters.dispatch(
                qq.adapter, replace(qq, operation_id="spar-repeat"), "切磋 乙_观星*客"
            )
            assert repeated.code == "SPAR_SPECTATOR"
            assert repeated.data == result.data
            reverse = await runtime.adapters.dispatch(
                onebot.adapter, replace(onebot, operation_id="spar-reverse"), "切磋 甲"
            )
            assert reverse.code == "SPAR_SPECTATOR"
            assert reverse.data["actions"]
            with sqlite3.connect(runtime.settings.database_path) as connection:
                after = connection.execute(
                    "SELECT platform_user_id, spirit_stones, total_cultivation, stamina, energy, inventory_json, durability_json FROM players ORDER BY id"
                ).fetchall()
                assert after == before_players
                assert connection.execute("SELECT COUNT(*) FROM operations").fetchone()[0] == before_operations
                assert connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'spar_%'"
                ).fetchall() == []
                assert {
                    table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                    for table in before_battle_rows
                } == before_battle_rows
                assert tuple(connection.iterdump()) == before_database
            await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("adapter", ("qq.official", "onebot.v11"))
def test_training_dummy_is_read_only_and_has_no_reward_or_replay(adapter: str) -> None:
    async def run() -> None:
        player = _context(adapter, "training-preview", "training-request")
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            await _create(runtime, player, "training-create")
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE players SET stage='cultivator', realm_key='qi_sensing', realm_layer=1 WHERE platform=? AND platform_user_id=?",
                    (player.adapter, player.user_id),
                )
                before = connection.execute(
                    "SELECT spirit_stones, cultivation, total_cultivation, stamina, energy, battle_defeat_until FROM players WHERE platform=? AND platform_user_id=?",
                    (player.adapter, player.user_id),
                ).fetchone()
                operation_count = connection.execute("SELECT COUNT(*) FROM operations").fetchone()[0]
                battle_rows = {
                    table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                    for table in ("battle_sessions", "battle_actions", "codex_entries")
                }
                before_database = tuple(connection.iterdump())
            result = await runtime.adapters.dispatch(adapter, replace(player, operation_id="training-preview-start"), "开始训练战")
            assert result.code == "TRAINING_SPECTATOR"
            assert result.data["status"] == "spectator"
            assert result.data["actions"]
            claim = await runtime.adapters.dispatch(adapter, replace(player, operation_id="training-preview-claim"), "领取战斗奖励")
            assert claim.code == "BATTLE_REWARD_NOT_AVAILABLE"
            replay = await runtime.adapters.dispatch(adapter, replace(player, operation_id="training-replay"), "战斗回放")
            assert replay.code == "BATTLE_NOT_FOUND"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                after = connection.execute(
                    "SELECT spirit_stones, cultivation, total_cultivation, stamina, energy, battle_defeat_until FROM players WHERE platform=? AND platform_user_id=?",
                    (player.adapter, player.user_id),
                ).fetchone()
                assert after == before
                assert connection.execute("SELECT COUNT(*) FROM operations").fetchone()[0] == operation_count
                assert {
                    table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                    for table in battle_rows
                } == battle_rows
                assert tuple(connection.iterdump()) == before_database
            await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("adapter", ("qq.official", "onebot.v11"))
def test_spectators_accept_read_only_identity_on_both_adapters(adapter: str) -> None:
    async def run() -> None:
        player = _context(adapter, f"readonly-{adapter}", f"readonly-{adapter}-request")
        opponent_adapter = "onebot.v11" if adapter == "qq.official" else "qq.official"
        opponent = _context(opponent_adapter, f"opponent-{adapter}", f"opponent-{adapter}-request")
        player_name = f"甲-{adapter}"
        opponent_name = f"乙-{adapter}"
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            await _create(runtime, player, f"readonly-{adapter}-create")
            await _create(runtime, opponent, f"opponent-{adapter}-create")
            with sqlite3.connect(runtime.settings.database_path) as connection:
                for context, dao_name in ((player, player_name), (opponent, opponent_name)):
                    connection.execute(
                        "UPDATE players SET stage='cultivator', realm_key='qi_sensing', "
                        "realm_layer=1, dao_name=? WHERE platform=? AND platform_user_id=?",
                        (dao_name, context.adapter, context.user_id),
                    )
                before_database = tuple(connection.iterdump())

            read_only = replace(player, can_write_assets=False, operation_id="readonly-training")
            training = await runtime.application.start_training_battle(read_only)
            assert training.code == "TRAINING_SPECTATOR"
            assert training.data["status"] == "spectator"
            assert training.data["actions"]

            spar_context = replace(
                read_only,
                operation_id="readonly-spar",
                command_args=(opponent_name,),
            )
            spar = await runtime.application.spar_players(spar_context)
            assert spar.code == "SPAR_SPECTATOR"
            assert spar.data["persistent"] is False
            assert spar.data["actions"]

            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert tuple(connection.iterdump()) == before_database
            await runtime.close()

    asyncio.run(run())
