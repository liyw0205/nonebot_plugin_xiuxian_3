from __future__ import annotations

import asyncio
import json
import shutil
import sqlite3
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest
from test_adapter_simulation import MutableClock, _onebot_group_event, _qq_group_event

from nonebot_plugin_xiuxian_3.adapters.onebot import normalize_event as normalize_onebot
from nonebot_plugin_xiuxian_3.adapters.qq import normalize_event as normalize_qq
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.production.rules import random_quality_bp


ADAPTERS = ("qq.official", "onebot.v11")
RULE_PATH = Path("社交") / "玩家互动.json"
REALM_PATH = Path("境界") / "境界.json"
RULE_KEY = "social.mentor_graduation"
LOCAL_KEY = "local.xuantian.new_town"


async def _send(runtime, adapter, user, operation, command):
    normalized = (
        normalize_qq(_qq_group_event(command, message_id=operation))
        if adapter == "qq.official" else normalize_onebot(_onebot_group_event(command))
    )
    return await runtime.adapters.dispatch(
        adapter, replace(normalized.context, user_id=user, operation_id=operation), normalized.text
    )


def _change_record(data_dir, relative_path, key, changes):
    path = data_dir / relative_path
    document = json.loads(path.read_text(encoding="utf-8"))
    record = next(record for record in document["records"] if record["key"] == key)
    if changes is None:
        document["records"].remove(record)
    else:
        record.update(changes)
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")


def _set_realm(runtime, user, realm, layer: int | float, *, stage="cultivator"):
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE players SET stage=?,realm_key=?,realm_layer=? WHERE platform_user_id=?",
            (stage, realm, layer, user),
        )


def _database(runtime):
    with sqlite3.connect(runtime.settings.database_path) as connection:
        return tuple(connection.iterdump())


def _reputation(runtime, user):
    with sqlite3.connect(runtime.settings.database_path) as connection:
        row = connection.execute(
            "SELECT r.local_json,r.service_reputation FROM player_reputations r "
            "JOIN players p ON p.id=r.player_id WHERE p.platform_user_id=?", (user,)
        ).fetchone()
    return (json.loads(row[0]), row[1]) if row is not None else ({}, 0)


async def _setup(tmp_path, adapter):
    data_dir = tmp_path / "data"
    shutil.copytree(Path(__file__).parents[1] / "data", data_dir)
    clock = MutableClock(datetime(2026, 10, 7, 12, tzinfo=timezone.utc))
    runtime = create_runtime(data_dir=data_dir, clock=clock)
    for index, command in enumerate(("开始修仙 青玄", "寻仙问道")):
        result = await _send(runtime, adapter, "master", f"master-setup-{index}", command)
        assert result.ok, result
    _set_realm(runtime, "master", "foundation", 4)
    return runtime, data_dir, clock


async def _apprentice(runtime, clock, adapter, user):
    commands = (
        "开始修仙", "寻仙问道", "完成引导 阅读", "前往近郊",
        "完成引导 采集", "完成引导 炼丹", "选择道途 辅修 炼丹",
    )
    for index, command in enumerate(commands):
        result = await _send(runtime, adapter, user, f"{user}-setup-{index}", command)
        assert result.ok, (command, result)
    invited = await _send(runtime, adapter, "master", f"invite-{user}", f"邀请拜师 {adapter}:{user}")
    assert invited.code == "MENTOR_INVITED", invited
    relation = invited.data["relation_id"]
    accepted = await _send(runtime, adapter, user, f"accept-{user}", f"接受拜师 {relation}")
    assert accepted.code == "MENTOR_ACCEPTED", accepted
    operation = next(
        f"{user}-production-{index}" for index in range(1000)
        if random_quality_bp(f"{user}-production-{index}") >= 500
    )
    started = await _send(runtime, adapter, user, operation, "开始生产 疗伤丹")
    assert started.code == "PRODUCTION_STARTED", started
    clock.advance(seconds=31)
    completed = await _send(runtime, adapter, user, f"claim-{user}", "领取生产")
    assert completed.code == "PRODUCTION_COMPLETED", completed
    assert completed.data["success"] is True
    assert completed.data["outputs"]["item.pill.healing_low"] >= 1
    with sqlite3.connect(runtime.settings.database_path) as connection:
        order = connection.execute(
            "SELECT recipe_key,status FROM production_orders WHERE operation_id=?", (operation,)
        ).fetchone()
        assert order == ("recipe.pill.healing_low", "completed")
    return relation


async def _refused(runtime, adapter, relation, operation, code="MENTOR_GRADUATION_NOT_READY"):
    before = _database(runtime)
    result = await _send(runtime, adapter, "master", operation, f"师徒毕业 {relation}")
    assert not result.ok, result
    assert result.code == code, result
    assert _database(runtime) == before
    return result


async def _graduate(runtime, adapter, user, relation, operation, gains=(10, 20, 2, 2)):
    apprentice_before, service_before = _reputation(runtime, user)
    _, master_before = _reputation(runtime, "master")
    result = await _send(runtime, adapter, "master", operation, f"师徒毕业 {relation}")
    assert result.code == "MENTOR_GRADUATED", result
    assert result.data["status"] == "graduated"
    assert tuple(result.data[key] for key in (
        "apprentice_local_reputation", "master_contribution",
        "apprentice_service_reputation_gain", "master_service_reputation_gain",
    )) == gains
    apprentice_after, service_after = _reputation(runtime, user)
    _, master_after = _reputation(runtime, "master")
    assert apprentice_after.get(LOCAL_KEY, 0) - apprentice_before.get(LOCAL_KEY, 0) == gains[0]
    assert service_after - service_before == gains[2]
    assert master_after - master_before == gains[3]
    return result


async def _replay(runtime, adapter, relation, operation, original):
    before = _database(runtime)
    result = await _send(runtime, adapter, "master", operation, f"师徒毕业 {relation}")
    assert result.ok and result.code == original.code, result
    assert result.message == original.message
    assert result.data == {**original.data, "idempotent_replay": True}
    assert _database(runtime) == before


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_graduation_accepts_all_higher_open_realms_and_rejects_invalid_progress(tmp_path, adapter):
    async def run():
        runtime, data_dir, clock = await _setup(tmp_path, adapter)
        first_user = "apprentice-0"
        first_relation = await _apprentice(runtime, clock, adapter, first_user)
        candidates = (
            ("qi_gathering", 2, "cultivator"),
            ("qi_gathering", 0, "cultivator"),
            ("qi_gathering", 11, "cultivator"),
            ("qi_gathering", 3.5, "cultivator"),
            ("foundation", 0, "cultivator"),
            ("foundation", 1.5, "cultivator"),
            ("golden_core", 11, "cultivator"),
            ("unknown_realm", 1, "cultivator"),
            ("qi_gathering", 3, "seeker"),
        )
        for realm, layer, stage in candidates:
            _set_realm(runtime, first_user, realm, layer, stage=stage)
            if isinstance(layer, float):
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    assert connection.execute(
                        "SELECT typeof(realm_layer),realm_layer FROM players WHERE platform_user_id=?",
                        (first_user,),
                    ).fetchone() == ("real", layer)
            await _refused(runtime, adapter, first_relation, "graduate-0")
        await runtime.close()
        _change_record(data_dir, REALM_PATH, "golden_core", {"status": "locked"})
        runtime = create_runtime(data_dir=data_dir, clock=clock)
        await runtime.initialize()
        _set_realm(runtime, first_user, "golden_core", 1)
        await _refused(runtime, adapter, first_relation, "graduate-0")
        await runtime.close()
        _change_record(data_dir, REALM_PATH, "golden_core", {"status": "open"})
        runtime = create_runtime(data_dir=data_dir, clock=clock)
        await runtime.initialize()
        realms = runtime.repository.content.list("realm", include_locked=False)
        threshold = next(row for row in realms if row["key"] == "qi_gathering")
        eligible = sorted((row for row in realms if row["rank"] >= threshold["rank"]), key=lambda row: row["rank"])
        history = []
        for index, realm in enumerate(eligible):
            user = f"apprentice-{index}"
            relation = first_relation if index == 0 else await _apprentice(runtime, clock, adapter, user)
            layer = 3 if realm["key"] == "qi_gathering" else realm["layer_min"]
            _set_realm(runtime, user, realm["key"], layer)
            operation = f"graduate-{index}"
            result = await _graduate(runtime, adapter, user, relation, operation)
            await _replay(runtime, adapter, relation, operation, result)
            await _refused(runtime, adapter, relation, operation + "-again", "MENTOR_STATE_CONFLICT")
            history.append((relation, operation, result))
        with sqlite3.connect(runtime.settings.database_path) as connection:
            assert connection.execute("SELECT COUNT(*) FROM mentor_relations WHERE status='graduated'").fetchone()[0] == len(eligible)
            assert connection.execute("SELECT COUNT(*) FROM operations WHERE operation_name='social.graduate_apprentice'").fetchone()[0] == len(eligible)
            assert connection.execute("SELECT SUM(master_contribution) FROM mentor_relations").fetchone()[0] == len(eligible) * 20
        await runtime.close()
        runtime = create_runtime(data_dir=data_dir, clock=clock)
        await runtime.initialize()
        for relation, operation, result in history:
            await _replay(runtime, adapter, relation, operation, result)
        await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_graduation_uses_current_rules_once_and_freezes_real_gains_after_content_removal(tmp_path, adapter):
    async def run():
        runtime, data_dir, clock = await _setup(tmp_path, adapter)
        relations = {}
        for user in ("first", "second", "waiting"):
            relations[user] = await _apprentice(runtime, clock, adapter, user)
            _set_realm(runtime, user, "qi_gathering", 3)
        old_rules = runtime.repository.content.require("social_interaction", RULE_KEY)
        with sqlite3.connect(runtime.settings.database_path) as connection:
            player_id = connection.execute("SELECT id FROM players WHERE platform_user_id='first'").fetchone()[0]
            connection.execute(
                "INSERT INTO player_reputations(player_id,local_json,updated_at) VALUES (?,?,?) "
                "ON CONFLICT(player_id) DO UPDATE SET local_json=excluded.local_json",
                (player_id, json.dumps({LOCAL_KEY: 998}), clock.value.isoformat()),
            )
        first = await _graduate(runtime, adapter, "first", relations["first"], "graduate-first", gains=(2, 20, 2, 2))
        await runtime.close()

        changes = {
            "required_realm": "foundation", "required_layer": 2,
            "apprentice_local_reputation": 7, "master_contribution": 11, "service_reputation": 3,
        }
        _change_record(data_dir, RULE_PATH, RULE_KEY, changes)
        _change_record(data_dir, Path("地图") / "地点.json", "xuantian.new_town", {"local_reputation_maximum": 1005})
        runtime = create_runtime(data_dir=data_dir, clock=clock)
        await runtime.initialize()
        new_rules = runtime.repository.content.require("social_interaction", RULE_KEY)
        await _replay(runtime, adapter, relations["first"], "graduate-first", first)
        await _refused(runtime, adapter, relations["second"], "graduate-first", "OPERATION_CONFLICT")
        await _refused(runtime, adapter, relations["second"], "graduate-second")
        _set_realm(runtime, "second", "foundation", 1)
        await _refused(runtime, adapter, relations["second"], "graduate-second")
        _set_realm(runtime, "second", "foundation", 2)
        second = await _graduate(runtime, adapter, "second", relations["second"], "graduate-second", gains=(7, 11, 3, 3))
        with sqlite3.connect(runtime.settings.database_path) as connection:
            for operation, definition, rank, maximum in (("graduate-first", old_rules, 2, 1000), ("graduate-second", new_rules, 3, 1005)):
                payload = json.loads(connection.execute("SELECT result_json FROM operations WHERE operation_id=?", (operation,)).fetchone()[0])
                expected = {key: value for key, value in definition.items() if key not in {"name", "desc", "status"}}
                assert payload["graduation_rules"] == {**expected, "required_rank": rank, "local_reputation_maximum": maximum}
            assert connection.execute("SELECT master_contribution FROM mentor_relations WHERE relation_id=?", (relations["first"],)).fetchone()[0] == 20
            assert connection.execute("SELECT master_contribution FROM mentor_relations WHERE relation_id=?", (relations["second"],)).fetchone()[0] == 11
        _set_realm(runtime, "waiting", "foundation", 2)
        await runtime.close()

        for changes in ({"status": "locked"}, None):
            _change_record(data_dir, RULE_PATH, RULE_KEY, changes)
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            await runtime.initialize()
            await _replay(runtime, adapter, relations["first"], "graduate-first", first)
            await _replay(runtime, adapter, relations["second"], "graduate-second", second)
            await _refused(runtime, adapter, relations["waiting"], "graduate-waiting", "CONTENT_ERROR")
            await _refused(runtime, adapter, relations["waiting"], "graduate-first", "OPERATION_CONFLICT")
            assert _reputation(runtime, "first")[0][LOCAL_KEY] == 1000
            await runtime.close()

    asyncio.run(run())
