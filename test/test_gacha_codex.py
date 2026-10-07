from __future__ import annotations

import asyncio
import json
import shutil
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from nonebot_plugin_xiuxian_3.adapters.onebot import normalize_event
from nonebot_plugin_xiuxian_3.adapters.qq import normalize_event as normalize_qq_event
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from test_adapter_simulation import _onebot_group_event, _qq_group_event


ADAPTERS = ("qq.official", "onebot.v11")
USER = "gacha-seeker"


async def _send(runtime, adapter, operation, command, user=USER):
    message = (
        normalize_qq_event(_qq_group_event(command, message_id=operation))
        if adapter == "qq.official" else normalize_event(_onebot_group_event(command))
    )
    return await runtime.adapters.dispatch(
        adapter, replace(message.context, user_id=user, operation_id=operation), message.text
    )


async def _setup(tmp_path, adapter):
    data_dir = tmp_path / "data"
    shutil.copytree(Path(__file__).parents[1] / "data", data_dir)
    runtime = create_runtime(data_dir=data_dir, adapters=(adapter,))
    for operation, command in (("create", "开始修仙 青玄"), ("seek", "寻仙问道")):
        result = await _send(runtime, adapter, operation, command)
        assert result.ok, result
    return runtime


def _database(runtime):
    with sqlite3.connect(runtime.settings.database_path) as connection:
        return tuple(connection.iterdump())


def _codex(runtime):
    with sqlite3.connect(runtime.settings.database_path) as connection:
        return connection.execute(
            "SELECT entry_key, first_seen_operation_id, payload_json FROM codex_entries "
            "WHERE player_id=(SELECT id FROM players WHERE platform_user_id=?) ORDER BY entry_key",
            (USER,),
        ).fetchall()


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_fate_material_is_recorded_in_codex_through_the_public_adapters(tmp_path, adapter):
    async def run():
        runtime = await _setup(tmp_path, adapter)
        result = await _send(runtime, adapter, "audit-material-11", "机缘寻宝 单抽")
        assert result.code == "FATE_POOL_ROLLED", result
        assert result.data["reward"].get("item.ore.ironstone", 0) == 2
        entries = _codex(runtime)
        ironstone = next(row for row in entries if row[0] == "codex.material.ironstone")
        assert ironstone[1] == "audit-material-11"
        payload = json.loads(ironstone[2])
        assert payload["source"] == "routine.roll_fate_pool"
        assert payload["pool_key"] == "gacha.fate.basic"
        listed = await _send(runtime, adapter, "codex-query", "我的图鉴")
        assert listed.ok
        shown = next(row for row in listed.data["entries"] if row["entry_key"] == ironstone[0])
        assert shown["label"] == "铁石"
        await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_fate_codex_first_seen_survives_content_rename_and_replay(tmp_path, adapter):
    async def run():
        runtime = await _setup(tmp_path, adapter)
        first = await _send(runtime, adapter, "audit-material-11", "机缘寻宝 单抽")
        assert first.ok
        before = _codex(runtime)
        await runtime.close()

        entry_path = tmp_path / "data" / "图鉴" / "条目.json"
        document = json.loads(entry_path.read_text(encoding="utf-8"))
        entry = next(row for row in document["records"] if row["key"] == "codex.material.ironstone")
        entry["name"] = "旧铁石"
        entry_path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
        runtime = create_runtime(data_dir=tmp_path / "data", adapters=(adapter,))
        listed = await _send(runtime, adapter, "codex-query", "我的图鉴")
        assert listed.ok
        shown = next(row for row in listed.data["entries"] if row["entry_key"] == "codex.material.ironstone")
        assert shown["label"] == "铁石"
        replay_before = _database(runtime)
        replay = await _send(runtime, adapter, "audit-material-11", "机缘寻宝 单抽")
        assert replay.ok and replay.data["idempotent_replay"] is True
        assert _database(runtime) == replay_before
        assert _codex(runtime) == before
        await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_fate_codex_does_not_create_entries_for_non_material_rewards(tmp_path, adapter):
    async def run():
        runtime = await _setup(tmp_path, adapter)
        result = await _send(runtime, adapter, "audit-material-11", "机缘寻宝 单抽")
        assert result.ok
        entries = {row[0] for row in _codex(runtime)}
        assert "codex.material.spirit_stone" not in entries
        assert "codex.material.local" not in entries
        assert all(not key.endswith("spirit_stone") for key in entries)
        await runtime.close()

    asyncio.run(run())


def _edit_record(data_dir, relative_path, key, **changes):
    path = data_dir / relative_path
    document = json.loads(path.read_text(encoding="utf-8"))
    record = next(item for item in document["records"] if item["key"] == key)
    record.update(changes)
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_fate_material_is_recorded_in_codex_with_first_source(tmp_path, adapter):
    async def run():
        runtime = await _setup(tmp_path, adapter)
        claimed = await _send(runtime, adapter, "claim-seeking", "领取引路嘉奖 第一次寻仙")
        assert claimed.code == "GUIDANCE_REWARD_CLAIMED", claimed
        first = await _send(runtime, adapter, "audit-material-11", "机缘寻宝 单抽")
        assert first.code == "FATE_POOL_ROLLED", first
        assert first.data["reward"] == {"item.ore.ironstone": 2}
        second = await _send(runtime, adapter, "repeat-material-0", "机缘寻宝 单抽")
        assert second.code == "FATE_POOL_ROLLED", second
        assert "item.ore.ironstone" in second.data["reward"]
        overview = await _send(runtime, adapter, "codex-read", "我的图鉴")
        entries = [entry for entry in overview.data["entries"] if entry["entry_key"] == "codex.material.ironstone"]
        assert len(entries) == 1
        assert entries[0]["label"] == "铁石"
        with sqlite3.connect(runtime.settings.database_path) as connection:
            assert connection.execute(
                "SELECT first_seen_operation_id,payload_json FROM codex_entries "
                "WHERE player_id=(SELECT id FROM players WHERE platform_user_id=?) "
                "AND entry_key='codex.material.ironstone'", (USER,),
            ).fetchone() == (
                "audit-material-11",
                '{"label": "铁石", "pool_key": "gacha.fate.basic", "source": "routine.roll_fate_pool"}',
            )
        await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_fate_ten_pull_duplicate_material_creates_one_codex_entry(tmp_path, adapter):
    async def run():
        runtime = await _setup(tmp_path, adapter)
        with sqlite3.connect(runtime.settings.database_path) as connection:
            connection.execute(
                "UPDATE players SET spirit_stones=500 WHERE platform_user_id=?", (USER,)
            )
        ten = await _send(runtime, adapter, "ten-dup-1", "机缘寻宝 十连")
        assert ten.code == "FATE_POOL_ROLLED", ten
        iron_draws = [draw for draw in ten.data["draws"] if draw["key"] == "item.ore.ironstone"]
        assert len(iron_draws) == 2
        with sqlite3.connect(runtime.settings.database_path) as connection:
            assert connection.execute(
                "SELECT COUNT(*) FROM codex_entries WHERE player_id=(SELECT id FROM players WHERE platform_user_id=?) "
                "AND entry_key='codex.material.ironstone'", (USER,),
            ).fetchone()[0] == 1
        await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_fate_replay_keeps_codex_label_after_content_rename_and_close(tmp_path, adapter):
    async def run():
        runtime = await _setup(tmp_path, adapter)
        claimed = await _send(runtime, adapter, "claim-seeking", "领取引路嘉奖 第一次寻仙")
        assert claimed.code == "GUIDANCE_REWARD_CLAIMED", claimed
        original = await _send(runtime, adapter, "audit-material-11", "机缘寻宝 单抽")
        assert original.data["reward"] == {"item.ore.ironstone": 2}
        data_dir = tmp_path / "data"
        _edit_record(data_dir, Path("图鉴") / "条目.json", "codex.material.ironstone", name="改名铁石", status="closed")
        _edit_record(data_dir, Path("图鉴") / "里程碑.json", "codex.xuantian.materials_5", status="closed")
        _edit_record(data_dir, Path("奖励") / "奖励.json", "reward.gacha.fate.basic", status="closed")
        await runtime.close()
        runtime = create_runtime(data_dir=data_dir, adapters=(adapter,))
        await runtime.initialize()
        overview = await _send(runtime, adapter, "codex-after-close", "我的图鉴")
        entry = next(item for item in overview.data["entries"] if item["entry_key"] == "codex.material.ironstone")
        assert entry["label"] == "铁石"
        before_replay = _database(runtime)
        replay = await _send(runtime, adapter, "audit-material-11", "机缘寻宝 单抽")
        assert replay.code == "FATE_POOL_ROLLED", replay
        assert replay.data["idempotent_replay"] is True
        assert replay.data["reward"] == original.data["reward"]
        assert _database(runtime) == before_replay
        await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_fate_unregistered_item_and_currency_rewards_do_not_create_codex_entries(tmp_path, adapter):
    async def run():
        runtime = await _setup(tmp_path, adapter)
        before = await _send(runtime, adapter, "codex-before", "我的图鉴")
        before_keys = {entry["entry_key"] for entry in before.data["entries"]}
        claimed = await _send(runtime, adapter, "claim-seeking", "领取引路嘉奖 第一次寻仙")
        assert claimed.code == "GUIDANCE_REWARD_CLAIMED", claimed
        rolled = await _send(runtime, adapter, "nonmaterial-10", "机缘寻宝 单抽")
        assert rolled.code == "FATE_POOL_ROLLED", rolled
        assert rolled.data["reward"] == {"spirit_stones": 75}
        after = await _send(runtime, adapter, "codex-after", "我的图鉴")
        after_keys = {entry["entry_key"] for entry in after.data["entries"]}
        assert after_keys == before_keys
        await runtime.close()

    asyncio.run(run())
