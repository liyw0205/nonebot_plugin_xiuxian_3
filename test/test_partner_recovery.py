from __future__ import annotations

import asyncio
import json
import sqlite3
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone

import pytest
from test_partner import MutableClock, _context, _create_player, _promote

from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.content import bundled_content
from nonebot_plugin_xiuxian_3.xiuxian.social import partner_repository


async def _setup(path, adapter):
    clock = MutableClock(datetime(2026, 10, 7, tzinfo=timezone.utc))
    runtime = create_runtime(data_dir=path, clock=clock)
    other = "onebot.v11" if adapter == "qq.official" else "qq.official"
    identities = ((adapter, "initiator"), (other, "invitee"), (adapter, "outsider"))
    for identity, name in zip(identities, ("青玄", "白衡", "松岚")):
        await _create_player(runtime, *identity, name)
        _promote(runtime, *identity)
    return runtime, clock, identities


async def _send(runtime, identity, operation, command):
    return await runtime.adapters.dispatch(identity[0], _context(*identity, operation), command)


def _database(runtime):
    with sqlite3.connect(runtime.settings.database_path) as connection:
        return tuple(connection.iterdump())


def _unrelated_state(runtime):
    with sqlite3.connect(runtime.settings.database_path) as connection:
        return {
            table: connection.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
            for table in ("players", "codex_entries", "equipment_instances", "battle_sessions", "arena_matches", "stat_snapshots")
        }


def _snapshot(runtime, relation_id):
    with sqlite3.connect(runtime.settings.database_path) as connection:
        return connection.execute("SELECT snapshot_json FROM partner_relations WHERE relation_id=?", (relation_id,)).fetchone()[0]


def _set_snapshot(runtime, relation_id, raw):
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute("UPDATE partner_relations SET snapshot_json=? WHERE relation_id=?", (raw, relation_id))


async def _rejected_without_writes(runtime, identity, operation, command):
    before = _database(runtime)
    result = await _send(runtime, identity, operation, command)
    assert not result.ok, (command, result)
    assert _database(runtime) == before, command
    return result


@pytest.mark.parametrize("adapter", ("qq.official", "onebot.v11"))
def test_partner_corrupt_snapshots_reject_transitions_and_recover(tmp_path, adapter):
    async def run():
        runtime, clock, (initiator, invitee, _) = await _setup(tmp_path, adapter)
        before_assets = _unrelated_state(runtime)
        invitation = await _send(runtime, initiator, "invite", "邀请结为道侣 白衡")
        assert invitation.code == "PARTNER_INVITED"
        relation_id = invitation.data["relation_id"]
        original = _snapshot(runtime, relation_id)
        definition = json.loads(original)
        missing = deepcopy(definition)
        del missing["dissolution_ttl_seconds"]
        boolean = {**definition, "required_layer": True}
        negative = {**definition, "reunion_cooldown_seconds": -1}
        duplicate = '{"required_rank":0,' + original[1:]
        corruptions = ("{", duplicate, json.dumps(missing), json.dumps(boolean), json.dumps(negative))
        accept_command = f"接受道侣邀请 {relation_id}"
        for raw in corruptions:
            _set_snapshot(runtime, relation_id, raw)
            await _rejected_without_writes(runtime, invitee, "accept", accept_command)
        await _rejected_without_writes(runtime, invitee, "reject-invitation", f"拒绝道侣邀请 {relation_id}")

        before_replay = _database(runtime)
        replay = await _send(runtime, initiator, "invite", "邀请结为道侣 白衡")
        assert replay.data["idempotent_replay"] is True
        assert _database(runtime) == before_replay
        _set_snapshot(runtime, relation_id, original)
        assert (await _send(runtime, invitee, "accept", accept_command)).code == "PARTNER_ACCEPTED"

        cases = (
            (initiator, "request", f"申请解除道侣 {relation_id}", corruptions[2], "PARTNER_DISSOLUTION_REQUESTED"),
            (invitee, "reject", f"拒绝解除道侣 {relation_id}", corruptions[3], "PARTNER_DISSOLUTION_REJECTED"),
            (initiator, "request-again", f"申请解除道侣 {relation_id}", corruptions[1], "PARTNER_DISSOLUTION_REQUESTED"),
            (invitee, "confirm", f"确认解除道侣 {relation_id}", corruptions[4], "PARTNER_DISSOLVED"),
        )
        for identity, operation, command, corrupt, code in cases:
            _set_snapshot(runtime, relation_id, corrupt)
            await _rejected_without_writes(runtime, identity, operation, command)
            _set_snapshot(runtime, relation_id, original)
            result = await _send(runtime, identity, operation, command)
            assert result.code == code, result
            assert result.data["idempotent_replay"] is False
        assert _unrelated_state(runtime) == before_assets
        await runtime.close()
        runtime = create_runtime(data_dir=tmp_path, clock=clock)
        await runtime.initialize()
        before_replay = _database(runtime)
        replay = await _send(runtime, invitee, "confirm", f"确认解除道侣 {relation_id}")
        assert replay.code == "PARTNER_DISSOLVED"
        assert replay.data["idempotent_replay"] is True
        assert _database(runtime) == before_replay
        await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("adapter", ("qq.official", "onebot.v11"))
def test_partner_bad_content_and_operation_json_never_write(tmp_path, adapter):
    async def run():
        runtime, clock, (initiator, _, _) = await _setup(tmp_path, adapter)
        content = bundled_content()
        records = deepcopy(content._records)
        records[("social_interaction", "social.partner")]["invitation_ttl_seconds"] = True
        runtime.repository.content = replace(content, _records=records)
        await _rejected_without_writes(runtime, initiator, "invite", "邀请结为道侣 白衡")
        runtime.repository.content = content
        created = await _send(runtime, initiator, "invite", "邀请结为道侣 白衡")
        assert created.code == "PARTNER_INVITED"
        with sqlite3.connect(runtime.settings.database_path) as connection:
            original = connection.execute("SELECT result_json FROM operations WHERE operation_id='invite'").fetchone()[0]
        payload = json.loads(original)
        missing = {key: value for key, value in payload.items() if key != "status"}
        corruptions = (
            "{", "[]", '{"status":"active",' + original[1:], json.dumps(missing),
            json.dumps({**payload, "status": True}), json.dumps({**payload, "invited_at": "2026-10-07"}),
        )
        for corrupt in corruptions:
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute("UPDATE operations SET result_json=? WHERE operation_id='invite'", (corrupt,))
            await _rejected_without_writes(runtime, initiator, "invite", "邀请结为道侣 白衡")
        with sqlite3.connect(runtime.settings.database_path) as connection:
            connection.execute("UPDATE operations SET result_json=? WHERE operation_id='invite'", (original,))
        await runtime.close()
        runtime = create_runtime(data_dir=tmp_path, clock=clock)
        await runtime.initialize()
        before = _database(runtime)
        result = await _send(runtime, initiator, "invite", "邀请结为道侣 白衡")
        assert result.data["idempotent_replay"] is True
        assert result.data["relation_id"] == created.data["relation_id"]
        assert _database(runtime) == before
        await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("adapter", ("qq.official", "onebot.v11"))
def test_partner_ledger_fault_rolls_back_each_transition_and_retries(tmp_path, monkeypatch, adapter):
    async def run():
        runtime, clock, (initiator, invitee, outsider) = await _setup(tmp_path, adapter)
        before_assets = _unrelated_state(runtime)
        real_record = partner_repository.record_operation
        history = []

        def fail_after_record(*args, **kwargs):
            real_record(*args, **kwargs)
            raise RuntimeError("injected partner ledger failure")

        async def attempt(identity, operation, command, code):
            with monkeypatch.context() as patch:
                patch.setattr(partner_repository, "record_operation", fail_after_record)
                await _rejected_without_writes(runtime, identity, operation, command)
            result = await _send(runtime, identity, operation, command)
            assert result.code == code, result
            assert result.data["idempotent_replay"] is False
            history.append((identity, operation, command, code, result.data["relation_id"]))
            assert _unrelated_state(runtime) == before_assets
            return result

        invitation = await attempt(initiator, "invite", "邀请结为道侣 白衡", "PARTNER_INVITED")
        relation_id = invitation.data["relation_id"]
        await attempt(invitee, "accept", f"接受道侣邀请 {relation_id}", "PARTNER_ACCEPTED")
        await runtime.close()
        runtime = create_runtime(data_dir=tmp_path, clock=clock)
        await runtime.initialize()
        await attempt(initiator, "request", f"申请解除道侣 {relation_id}", "PARTNER_DISSOLUTION_REQUESTED")
        await attempt(invitee, "reject", f"拒绝解除道侣 {relation_id}", "PARTNER_DISSOLUTION_REJECTED")
        assert (await _send(runtime, initiator, "request-again", f"申请解除道侣 {relation_id}")).ok
        await attempt(invitee, "confirm", f"确认解除道侣 {relation_id}", "PARTNER_DISSOLVED")
        second = await _send(runtime, initiator, "invite-other", "邀请结为道侣 松岚")
        assert second.code == "PARTNER_INVITED"
        await attempt(outsider, "reject-invitation", f"拒绝道侣邀请 {second.data['relation_id']}", "PARTNER_REJECTED")
        await runtime.close()
        runtime = create_runtime(data_dir=tmp_path, clock=clock)
        await runtime.initialize()
        before = _database(runtime)
        for identity, operation, command, code, expected_relation in history:
            result = await _send(runtime, identity, operation, command)
            assert result.code == code
            assert result.data["relation_id"] == expected_relation
            assert result.data["idempotent_replay"] is True
        assert _database(runtime) == before
        assert _unrelated_state(runtime) == before_assets
        await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("adapter", ("qq.official", "onebot.v11"))
def test_partner_permissions_never_change_other_players_relations(tmp_path, adapter):
    async def run():
        runtime, _, (initiator, invitee, outsider) = await _setup(tmp_path, adapter)
        before_assets = _unrelated_state(runtime)
        invitation = await _send(runtime, initiator, "invite", "邀请结为道侣 白衡")
        relation_id = invitation.data["relation_id"]
        commands = ("接受道侣邀请", "拒绝道侣邀请", "申请解除道侣", "确认解除道侣", "拒绝解除道侣")
        for index, command in enumerate(commands):
            await _rejected_without_writes(runtime, outsider, f"outsider:{index}", f"{command} {relation_id}")
        for index, command in enumerate(commands[:2]):
            await _rejected_without_writes(runtime, initiator, f"self:{index}", f"{command} {relation_id}")
        for identity in (initiator, invitee):
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute("UPDATE players SET status='suspended' WHERE platform=? AND platform_user_id=?", identity)
            await _rejected_without_writes(runtime, invitee, "accept", f"接受道侣邀请 {relation_id}")
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute("UPDATE players SET status='active' WHERE platform=? AND platform_user_id=?", identity)
        assert (await _send(runtime, invitee, "accept", f"接受道侣邀请 {relation_id}")).ok
        assert (await _send(runtime, initiator, "request", f"申请解除道侣 {relation_id}")).ok
        for identity in (initiator, outsider):
            for command in ("确认解除道侣", "拒绝解除道侣"):
                await _rejected_without_writes(runtime, identity, f"forbidden:{identity[1]}:{command}", f"{command} {relation_id}")
        with sqlite3.connect(runtime.settings.database_path) as connection:
            connection.execute("UPDATE players SET status='suspended' WHERE platform=? AND platform_user_id=?", invitee)
        await _rejected_without_writes(runtime, invitee, "confirm", f"确认解除道侣 {relation_id}")
        with sqlite3.connect(runtime.settings.database_path) as connection:
            connection.execute("UPDATE players SET status='active' WHERE platform=? AND platform_user_id=?", invitee)
        assert (await _send(runtime, invitee, "confirm", f"确认解除道侣 {relation_id}")).code == "PARTNER_DISSOLVED"
        assert _unrelated_state(runtime) == before_assets
        await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("adapter", ("qq.official", "onebot.v11"))
def test_partner_concurrent_operations_across_runtimes_settle_once(tmp_path, adapter):
    async def run():
        runtime, clock, (initiator, invitee, _) = await _setup(tmp_path, adapter)
        recovered = create_runtime(data_dir=tmp_path, clock=clock)
        await recovered.initialize()
        before_assets = _unrelated_state(runtime)
        invitations = await asyncio.gather(
            _send(runtime, initiator, "invite", "邀请结为道侣 白衡"),
            _send(recovered, initiator, "invite", "邀请结为道侣 白衡"),
        )
        assert all(result.code == "PARTNER_INVITED" for result in invitations)
        assert sorted(result.data["idempotent_replay"] for result in invitations) == [False, True]
        relation_id = invitations[0].data["relation_id"]
        assert invitations[1].data["relation_id"] == relation_id
        accepted = await asyncio.gather(
            _send(runtime, invitee, "accept-one", f"接受道侣邀请 {relation_id}"),
            _send(recovered, invitee, "accept-two", f"接受道侣邀请 {relation_id}"),
        )
        assert sum(result.ok for result in accepted) == 1
        requested = await asyncio.gather(
            _send(runtime, initiator, "request", f"申请解除道侣 {relation_id}"),
            _send(recovered, initiator, "request", f"申请解除道侣 {relation_id}"),
        )
        assert all(result.code == "PARTNER_DISSOLUTION_REQUESTED" for result in requested)
        assert sorted(result.data["idempotent_replay"] for result in requested) == [False, True]
        resolved = await asyncio.gather(
            _send(runtime, invitee, "confirm", f"确认解除道侣 {relation_id}"),
            _send(recovered, invitee, "reject", f"拒绝解除道侣 {relation_id}"),
        )
        assert sum(result.ok for result in resolved) == 1
        with sqlite3.connect(runtime.settings.database_path) as connection:
            assert connection.execute("SELECT COUNT(*) FROM partner_relations").fetchone()[0] == 1
            assert connection.execute("SELECT COUNT(*) FROM operations WHERE operation_name LIKE 'social.%partner%'").fetchone()[0] == 4
        assert _unrelated_state(runtime) == before_assets
        await recovered.close()
        await runtime.close()

    asyncio.run(run())
