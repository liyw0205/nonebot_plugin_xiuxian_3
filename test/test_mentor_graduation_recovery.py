from __future__ import annotations

import asyncio
import json
import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from nonebot_plugin_xiuxian_3.adapters.onebot import normalize_event
from nonebot_plugin_xiuxian_3.adapters.qq import normalize_event as normalize_qq_event
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.content import bundled_content
from nonebot_plugin_xiuxian_3.xiuxian.rewards.rules import local_reputation_maximum
from nonebot_plugin_xiuxian_3.xiuxian.social import mentor_repository
from test_adapter_simulation import _onebot_group_event, _qq_group_event


ADAPTERS = ("qq.official", "onebot.v11")


class Clock:
    def __init__(self):
        self.value = datetime(2026, 10, 5, tzinfo=timezone.utc)

    def __call__(self):
        return self.value


async def _send(runtime, adapter, user, operation, command):
    if adapter == "qq.official":
        message = normalize_qq_event(_qq_group_event(command, message_id=operation))
    else:
        message = normalize_event(_onebot_group_event(command))
    return await runtime.adapters.dispatch(
        adapter, replace(message.context, user_id=user, operation_id=operation), message.text
    )


async def _start_production(runtime, adapter, user):
    for index, command in enumerate((
        "完成引导 阅读", "前往近郊", "完成引导 采集", "完成引导 炼丹", "选择道途 辅修 炼丹",
    )):
        result = await _send(runtime, adapter, user, f"{user}-guide-{index}", command)
        assert result.ok, (command, result)
    operation = "production-start-1" if user == "apprentice" else "outsider-production-start"
    started = await _send(runtime, adapter, user, operation, "开始生产 疗伤丹")
    assert started.code == "PRODUCTION_STARTED", started
    return started.data["order_id"]


async def _complete_production(runtime, adapter, user, order, clock):
    with sqlite3.connect(runtime.settings.database_path) as connection:
        ends_at = connection.execute("SELECT ends_at FROM production_orders WHERE order_id=?", (order,)).fetchone()[0]
    clock.value = max(clock.value, datetime.fromisoformat(ends_at) + timedelta(seconds=1))
    result = await _send(runtime, adapter, user, f"{user}-production-complete", "领取生产")
    assert result.code == "PRODUCTION_COMPLETED", result
    assert result.data["success"] is True, result
    assert result.data["outputs"] == {"item.pill.healing_low": 1}


async def _setup(path, adapter, *, complete=True):
    clock = Clock()
    runtime = create_runtime(data_dir=path, adapters=(adapter,), clock=clock)
    for user, name in (("master", "青玄"), ("apprentice", "白衡"), ("outsider", "素心")):
        assert (await _send(runtime, adapter, user, f"create-{user}", f"开始修仙 {name}")).ok
        assert (await _send(runtime, adapter, user, f"seek-{user}", "寻仙问道")).ok
    # Realm and the master's founding funds are fixtures; relations and sources are not.
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE players SET stage='cultivator',realm_key='foundation',realm_layer=4,spirit_stones=2000 "
            "WHERE platform=? AND platform_user_id='master'", (adapter,),
        )
    sect = await _send(runtime, adapter, "master", "sect", "创建宗门 归元学宫")
    assert sect.code == "SECT_CREATED", sect
    invitation = await _send(runtime, adapter, "master", "invite", f"邀请拜师 {adapter}:apprentice")
    assert invitation.code == "MENTOR_INVITED", invitation
    relation = invitation.data["relation_id"]
    accepted = await _send(runtime, adapter, "apprentice", "accept", f"接受拜师 {relation}")
    assert accepted.code == "MENTOR_ACCEPTED", accepted
    order = await _start_production(runtime, adapter, "apprentice")
    if complete:
        await _complete_production(runtime, adapter, "apprentice", order, clock)
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE players SET realm_key='foundation',realm_layer=1 WHERE platform=? AND platform_user_id='apprentice'",
            (adapter,),
        )
    return runtime, clock, relation, order


def _database(runtime):
    with sqlite3.connect(runtime.settings.database_path) as connection:
        return tuple(connection.iterdump())


def _non_rewards(runtime):
    with sqlite3.connect(runtime.settings.database_path) as connection:
        return (
            connection.execute(
                "SELECT id,spirit_stones,inventory_json,stamina,energy,cultivation,total_cultivation,durability_json "
                "FROM players ORDER BY id"
            ).fetchall(),
            connection.execute("SELECT * FROM codex_entries ORDER BY rowid").fetchall(),
            connection.execute("SELECT * FROM equipment_instances ORDER BY rowid").fetchall(),
        )


async def _rejected(runtime, adapter, user, operation, command, code):
    before = _database(runtime)
    result = await _send(runtime, adapter, user, operation, command)
    assert result.code == code, result
    assert not result.ok
    assert _database(runtime) == before
    return result


def _assert_replay(original, replay):
    assert replay.code == original.code == "MENTOR_GRADUATED"
    assert replay.message == original.message
    assert replay.data == {**original.data, "idempotent_replay": True}


def _assert_one_award(runtime, relation, result):
    with sqlite3.connect(runtime.settings.database_path) as connection:
        row = connection.execute(
            "SELECT status,master_contribution,graduate_operation_id FROM mentor_relations WHERE relation_id=?",
            (relation,),
        ).fetchone()
        assert row == ("graduated", result.data["master_contribution"], result.operation_id)
        assert connection.execute(
            "SELECT COUNT(*) FROM operations WHERE operation_name='social.graduate_apprentice'"
        ).fetchone()[0] == 1
        events = connection.execute(
            "SELECT source_operation_id,quantity FROM sect_contribution_events"
        ).fetchall()
        assert events == [(result.operation_id, result.data["master_contribution"])]
        assert connection.execute(
            "SELECT contribution FROM sect_members WHERE player_id=(SELECT id FROM players WHERE platform_user_id='master')"
        ).fetchone()[0] == result.data["master_contribution"]


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_mentor_graduation_requires_own_completed_source_and_master_permission(tmp_path, adapter):
    async def run():
        runtime, clock, relation, order = await _setup(tmp_path, adapter, complete=False)
        command = f"师徒毕业 {relation}"
        await _rejected(runtime, adapter, "master", "graduate", command, "MENTOR_GRADUATION_NOT_READY")
        outsider_order = await _start_production(runtime, adapter, "outsider")
        await _complete_production(runtime, adapter, "outsider", outsider_order, clock)
        await _rejected(runtime, adapter, "master", "graduate", command, "MENTOR_GRADUATION_NOT_READY")
        with sqlite3.connect(runtime.settings.database_path) as connection:
            assert connection.execute("SELECT status FROM production_orders WHERE order_id=?", (order,)).fetchone()[0] == "processing"
        for user in ("outsider", "apprentice"):
            await _rejected(runtime, adapter, user, f"wrong-master-{user}", command, "MENTOR_PERMISSION_DENIED")
        await _complete_production(runtime, adapter, "apprentice", order, clock)
        with sqlite3.connect(runtime.settings.database_path) as connection:
            connection.execute("UPDATE players SET status='suspended' WHERE platform_user_id='master'")
        await _rejected(runtime, adapter, "master", "graduate", command, "PLAYER_SUSPENDED")
        with sqlite3.connect(runtime.settings.database_path) as connection:
            connection.execute("UPDATE players SET status='active' WHERE platform_user_id='master'")
        before = _non_rewards(runtime)
        graduated = await _send(runtime, adapter, "master", "graduate", command)
        assert graduated.code == "MENTOR_GRADUATED", graduated
        _assert_one_award(runtime, relation, graduated)
        assert _non_rewards(runtime) == before
        await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_mentor_graduation_corrupt_results_and_rules_never_replay(tmp_path, adapter):
    async def run():
        runtime, clock, relation, _ = await _setup(tmp_path, adapter)
        command = f"师徒毕业 {relation}"
        graduated = await _send(runtime, adapter, "master", "graduate", command)
        assert graduated.code == "MENTOR_GRADUATED", graduated
        with sqlite3.connect(runtime.settings.database_path) as connection:
            original, owner = connection.execute(
                "SELECT result_json,player_id FROM operations WHERE operation_id='graduate'"
            ).fetchone()
            people = dict(connection.execute("SELECT platform_user_id,id FROM players"))
            public_ids = dict(connection.execute("SELECT platform_user_id,player_id FROM players"))
        payload = json.loads(original)
        rules = payload["graduation_rules"]
        corruptions = [
            "{", "[]", original[:-1] + ',"apprentice_local_reputation":999}',
            json.dumps({**payload, "relation_id": "mentor-other"}),
            json.dumps({**payload, "status": "active"}),
            json.dumps({**payload, "master_platform_user_id": "outsider"}),
            json.dumps({**payload, "master_player_id": public_ids["outsider"]}),
            json.dumps({**payload, "apprentice_player_id": public_ids["outsider"]}),
            json.dumps({**payload, "apprentice_platform_user_id": "outsider"}),
            json.dumps({**payload, "master_contribution": True}),
            json.dumps({**payload, "master_contribution": payload["master_contribution"] + 1}),
            json.dumps({**payload, "apprentice_local_reputation": 1.5}),
            json.dumps({**payload, "apprentice_local_reputation": rules["local_reputation_maximum"] + 1}),
            json.dumps({**payload, "apprentice_service_reputation_gain": -1}),
            json.dumps({**payload, "master_service_reputation_gain": rules["service_reputation"] + 1}),
            json.dumps({**payload, "graduated_at": "2026-10-05"}),
            json.dumps({**payload, "graduated_at": None}),
            json.dumps({**payload, "expires_at": payload["accepted_at"]}),
            json.dumps({**payload, "graduated_at": (datetime.fromisoformat(payload["accepted_at"]) - timedelta(seconds=1)).isoformat()}),
            json.dumps({**payload, "graduation_rules": {**rules, "required_rank": True}}),
            json.dumps({**payload, "graduation_rules": {**rules, "local_reputation_maximum": -1}}),
            json.dumps({**payload, "graduation_rules": {key: value for key, value in rules.items() if key != "required_rank"}}),
        ]
        corruptions.extend(
            json.dumps({key: value for key, value in payload.items() if key != missing})
            for missing in ("graduated_at", "accepted_at", "master_contribution", "graduation_rules")
        )
        for corrupt in corruptions:
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute("UPDATE operations SET result_json=? WHERE operation_id='graduate'", (corrupt,))
            await _rejected(runtime, adapter, "master", "graduate", command, "PERSISTENCE_ERROR")
        with sqlite3.connect(runtime.settings.database_path) as connection:
            connection.execute("UPDATE operations SET result_json=?,player_id=? WHERE operation_id='graduate'", (original, people["apprentice"]))
        await _rejected(runtime, adapter, "master", "graduate", command, "OPERATION_CONFLICT")
        with sqlite3.connect(runtime.settings.database_path) as connection:
            connection.execute("UPDATE operations SET player_id=? WHERE operation_id='graduate'", (owner,))
        await runtime.close()

        runtime = create_runtime(data_dir=tmp_path, adapters=(adapter,), clock=clock)
        await runtime.initialize()
        before = _database(runtime)
        _assert_replay(graduated, await _send(runtime, adapter, "master", "graduate", command))
        assert _database(runtime) == before
        await _rejected(runtime, adapter, "outsider", "graduate", command, "OPERATION_CONFLICT")
        await _rejected(runtime, adapter, "master", "graduate", "师徒毕业 mentor-other", "OPERATION_CONFLICT")
        with sqlite3.connect(runtime.settings.database_path) as connection:
            original_endgame = connection.execute("SELECT endgame_status FROM players WHERE platform_user_id='master'").fetchone()[0]
        for status in ("ascension_ready", "ascended", "remained_in_world"):
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute("UPDATE players SET endgame_status=? WHERE platform_user_id='master'", (status,))
            before = _database(runtime)
            _assert_replay(graduated, await _send(runtime, adapter, "master", "graduate", command))
            assert _database(runtime) == before
            await _rejected(runtime, adapter, "master", f"graduate-new-{status}", command, "PLAYER_SUSPENDED")
        with sqlite3.connect(runtime.settings.database_path) as connection:
            connection.execute("UPDATE players SET endgame_status=?,status='suspended' WHERE platform_user_id='master'", (original_endgame,))
        await _rejected(runtime, adapter, "master", "graduate", command, "PLAYER_SUSPENDED")
        with sqlite3.connect(runtime.settings.database_path) as connection:
            connection.execute("UPDATE players SET status='active' WHERE platform_user_id='master'")
        _assert_one_award(runtime, relation, graduated)
        await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_mentor_graduation_rolls_back_reputation_contribution_and_operation(tmp_path, monkeypatch, adapter):
    async def run():
        runtime, clock, relation, _ = await _setup(tmp_path, adapter)
        command = f"师徒毕业 {relation}"
        maximum = local_reputation_maximum("local.xuantian.new_town", runtime.repository.content)
        apprentice_local = json.dumps({"local.xuantian.new_town": maximum - 1})
        with sqlite3.connect(runtime.settings.database_path) as connection:
            people = dict(connection.execute("SELECT platform_user_id,id FROM players"))
            for user, local, service in (("master", "{}", 100), ("apprentice", "{", 99)):
                connection.execute(
                    "INSERT INTO player_reputations(player_id,local_json,service_reputation,updated_at) VALUES (?,?,?,?) "
                    "ON CONFLICT(player_id) DO UPDATE SET local_json=excluded.local_json,service_reputation=excluded.service_reputation",
                    (people[user], local, service, clock.value.isoformat()),
                )
        await _rejected(runtime, adapter, "master", "graduate", command, "PERSISTENCE_ERROR")
        with sqlite3.connect(runtime.settings.database_path) as connection:
            connection.execute("UPDATE player_reputations SET local_json=? WHERE player_id=?", (apprentice_local, people["apprentice"]))
        untouched = _non_rewards(runtime)
        real_record = mentor_repository.record_operation

        def fail_after_record(*args, **kwargs):
            real_record(*args, **kwargs)
            raise RuntimeError("injected mentor graduation ledger failure")

        with monkeypatch.context() as patch:
            patch.setattr(mentor_repository, "record_operation", fail_after_record)
            await _rejected(runtime, adapter, "master", "graduate", command, "PERSISTENCE_ERROR")
        await runtime.close()
        runtime = create_runtime(data_dir=tmp_path, adapters=(adapter,), clock=clock)
        graduated = await _send(runtime, adapter, "master", "graduate", command)
        assert graduated.code == "MENTOR_GRADUATED", graduated
        assert graduated.data["apprentice_local_reputation"] == 1
        assert graduated.data["apprentice_service_reputation_gain"] == 1
        assert graduated.data["master_service_reputation_gain"] == 0
        _assert_one_award(runtime, relation, graduated)
        assert _non_rewards(runtime) == untouched
        with sqlite3.connect(runtime.settings.database_path) as connection:
            assert connection.execute("SELECT service_reputation FROM player_reputations WHERE player_id=?", (people["master"],)).fetchone()[0] == 100
            local, service = connection.execute("SELECT local_json,service_reputation FROM player_reputations WHERE player_id=?", (people["apprentice"],)).fetchone()
            assert json.loads(local)["local.xuantian.new_town"] == maximum
            assert service == 100
        before = _database(runtime)
        _assert_replay(graduated, await _send(runtime, adapter, "master", "graduate", command))
        assert _database(runtime) == before
        await _rejected(runtime, adapter, "master", "graduate-again", command, "MENTOR_STATE_CONFLICT")
        await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_mentor_graduation_zero_rewards_records_relation_without_contribution_event(tmp_path, monkeypatch, adapter):
    async def run():
        runtime, _, relation, _ = await _setup(tmp_path, adapter)
        content = bundled_content()
        identity = ("social_interaction", "social.mentor_graduation")
        rule = content.require(*identity)
        rule.update(apprentice_local_reputation=0, master_contribution=0, service_reputation=0)
        monkeypatch.setattr(runtime.repository, "content", replace(content, _records={**content._records, identity: rule}))

        def reputation_state():
            with sqlite3.connect(runtime.settings.database_path) as connection:
                rows = connection.execute(
                    "SELECT p.id,r.local_json,r.service_reputation FROM players p "
                    "LEFT JOIN player_reputations r ON r.player_id=p.id ORDER BY p.id"
                ).fetchall()
            return tuple(
                (player_id, {key: value for key, value in json.loads(local or "{}").items() if value}, service or 0)
                for player_id, local, service in rows
            )

        reputations = reputation_state()
        untouched = _non_rewards(runtime)
        command = f"师徒毕业 {relation}"
        graduated = await _send(runtime, adapter, "master", "graduate", command)
        assert graduated.code == "MENTOR_GRADUATED", graduated
        for field in (
            "apprentice_local_reputation", "master_contribution",
            "apprentice_service_reputation_gain", "master_service_reputation_gain",
        ):
            assert graduated.data[field] == 0
        assert reputation_state() == reputations
        assert _non_rewards(runtime) == untouched
        with sqlite3.connect(runtime.settings.database_path) as connection:
            assert connection.execute(
                "SELECT status,master_contribution,graduate_operation_id FROM mentor_relations WHERE relation_id=?",
                (relation,),
            ).fetchone() == ("graduated", 0, "graduate")
            assert connection.execute(
                "SELECT COUNT(*) FROM operations WHERE operation_id='graduate' AND operation_name='social.graduate_apprentice'"
            ).fetchone()[0] == 1
            assert connection.execute("SELECT COUNT(*) FROM sect_contribution_events").fetchone()[0] == 0
            assert connection.execute(
                "SELECT contribution FROM sect_members WHERE player_id=(SELECT id FROM players WHERE platform_user_id='master')"
            ).fetchone()[0] == 0
        monkeypatch.setattr(runtime.repository, "content", replace(
            content, _records={key: value for key, value in content._records.items() if key != identity},
        ))
        before = _database(runtime)
        _assert_replay(graduated, await _send(runtime, adapter, "master", "graduate", command))
        assert _database(runtime) == before
        await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("adapter", ADAPTERS)
@pytest.mark.parametrize("same_operation", (False, True))
def test_two_runtimes_graduate_once_under_competing_requests(tmp_path, adapter, same_operation):
    async def run():
        first, clock, relation, _ = await _setup(tmp_path, adapter)
        second = create_runtime(data_dir=tmp_path, adapters=(adapter,), clock=clock)
        await second.initialize()
        untouched = _non_rewards(first)
        command = f"师徒毕业 {relation}"
        operations = ("graduate", "graduate" if same_operation else "graduate-other")
        results = await asyncio.gather(
            _send(first, adapter, "master", operations[0], command),
            _send(second, adapter, "master", operations[1], command),
        )
        if same_operation:
            assert all(result.code == "MENTOR_GRADUATED" for result in results), results
            assert sorted(result.data["idempotent_replay"] for result in results) == [False, True]
        else:
            assert sorted(result.code for result in results) == ["MENTOR_GRADUATED", "MENTOR_STATE_CONFLICT"], results
        graduated = next(result for result in results if result.ok and not result.data["idempotent_replay"])
        _assert_one_award(first, relation, graduated)
        assert _non_rewards(first) == untouched
        await first.close()
        await second.close()
        runtime = create_runtime(data_dir=tmp_path, adapters=(adapter,), clock=clock)
        await runtime.initialize()
        before = _database(runtime)
        _assert_replay(graduated, await _send(runtime, adapter, "master", graduated.operation_id, command))
        assert _database(runtime) == before
        await runtime.close()

    asyncio.run(run())
