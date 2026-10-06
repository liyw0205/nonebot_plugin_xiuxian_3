from __future__ import annotations

import asyncio
import json
import shutil
import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from nonebot_plugin_xiuxian_3.adapters.onebot import normalize_event
from nonebot_plugin_xiuxian_3.adapters.qq import normalize_event as normalize_qq_event
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from test_adapter_simulation import _onebot_group_event, _qq_group_event


ADAPTERS = ("qq.official", "onebot.v11")
NAMES = {"a": "青玄", "b": "白衡", "c": "素心", "d": "清尘"}
INVITATION_SECONDS = 3600
DISSOLUTION_SECONDS = 600
COOLDOWN_SECONDS = 900


class Clock:
    def __init__(self):
        self.value = datetime(2026, 10, 1, tzinfo=timezone.utc)

    def __call__(self):
        return self.value

    def advance(self, seconds: int):
        self.value += timedelta(seconds=seconds)


def _content(tmp_path: Path) -> Path:
    root = tmp_path / "content"
    shutil.copytree(Path(__file__).parents[1] / "data", root)
    _edit(
        root,
        invitation_ttl_seconds=INVITATION_SECONDS,
        dissolution_ttl_seconds=DISSOLUTION_SECONDS,
        reunion_cooldown_seconds=COOLDOWN_SECONDS,
    )
    return root


def _edit(root: Path, *, remove: bool = False, **changes) -> None:
    path = root / "社交" / "玩家互动.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    if remove:
        document["records"] = [
            row for row in document["records"] if row["key"] != "social.partner"
        ]
    else:
        next(row for row in document["records"] if row["key"] == "social.partner").update(changes)
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")


def _restore_content(root: Path, **changes) -> None:
    source = Path(__file__).parents[1] / "data" / "社交" / "玩家互动.json"
    shutil.copyfile(source, root / "社交" / "玩家互动.json")
    _edit(root, **changes)


async def _send(runtime, adapter: str, user: str, operation: str, command: str):
    if adapter == "qq.official":
        message = normalize_qq_event(_qq_group_event(command, message_id=operation))
    else:
        message = normalize_event(_onebot_group_event(command))
    context = replace(message.context, user_id=user, operation_id=operation)
    return await runtime.adapters.dispatch(adapter, context, message.text)


async def _players(runtime, adapter: str, users=("a", "b")) -> None:
    for user in users:
        assert (await _send(runtime, adapter, user, f"create-{user}", f"开始修仙 {NAMES[user]}")).ok
        assert (await _send(runtime, adapter, user, f"seek-{user}", "寻仙问道")).ok
        # Only realm eligibility is a fixture; every relation uses public commands.
        _set_realm(runtime, adapter, user, "nascent_soul")


def _set_realm(runtime, adapter: str, user: str, realm: str) -> None:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE players SET stage='cultivator', realm_key=?, realm_layer=1 "
            "WHERE platform=? AND platform_user_id=?",
            (realm, adapter, user),
        )


def _state(runtime, *, relationships: bool = False) -> dict[str, list]:
    tables = ["players", "equipment_instances", "player_reputations", "codex_entries"]
    if relationships:
        tables.extend(("partner_relations", "operations"))
    with sqlite3.connect(runtime.settings.database_path) as connection:
        return {
            table: connection.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
            for table in tables
        }


def _assert_replay(original, replay) -> None:
    assert replay.ok, replay
    assert replay.code == original.code
    assert replay.message == original.message
    assert replay.data == {**original.data, "idempotent_replay": True}


@pytest.mark.parametrize("adapter", ADAPTERS)
@pytest.mark.parametrize("content_state", ("changed", "closed", "removed"))
def test_partner_lifecycle_freezes_rules_and_replays_after_restart(
    tmp_path: Path, adapter: str, content_state: str
) -> None:
    async def run() -> None:
        root, clock = _content(tmp_path), Clock()
        runtime = create_runtime(data_dir=root, adapters=(adapter,), clock=clock)
        await _players(runtime, adapter, ("a", "b", "c", "d"))
        assets = _state(runtime)
        history = []

        async def act(user, operation, command, code):
            result = await _send(runtime, adapter, user, operation, command)
            assert result.code == code, result
            history.append((user, operation, command, result))
            return result

        invited = await act("a", "invite", "邀请结为道侣 白衡", "PARTNER_INVITED")
        relation = invited.data["relation_id"]
        assert invited.data["invitation_expires_at"] == (
            clock.value + timedelta(seconds=INVITATION_SECONDS)
        ).isoformat()
        await runtime.close()
        _edit(
            root,
            required_realm="soul_transformation",
            invitation_ttl_seconds=11,
            dissolution_ttl_seconds=13,
            reunion_cooldown_seconds=17,
            status="closed" if content_state == "closed" else "active",
        )
        if content_state == "removed":
            _edit(root, remove=True)
        clock.advance(30)
        runtime = create_runtime(data_dir=root, adapters=(adapter,), clock=clock)
        before = _state(runtime, relationships=True)
        _assert_replay(invited, await _send(runtime, adapter, "a", "invite", "邀请结为道侣 白衡"))
        conflict = await _send(runtime, adapter, "a", "invite", "邀请结为道侣 素心")
        assert conflict.code == "OPERATION_CONFLICT"
        preview = await _send(runtime, adapter, "b", "view-invitation", "道侣关系")
        assert preview.data["status"] == "invited"
        assert preview.data["invitation_expires_at"] == invited.data["invitation_expires_at"]
        assert _state(runtime, relationships=True) == before

        await act("b", "accept", f"接受道侣邀请 {relation}", "PARTNER_ACCEPTED")
        blocked = await _send(runtime, adapter, "c", "new-invite", "邀请结为道侣 清尘")
        expected = "PARTNER_REQUIREMENT_MISSING" if content_state == "changed" else "CONTENT_ERROR"
        assert blocked.code == expected
        requested = await act("a", "request", f"申请解除道侣 {relation}", "PARTNER_DISSOLUTION_REQUESTED")
        assert requested.data["dissolution_expires_at"] == (
            clock.value + timedelta(seconds=DISSOLUTION_SECONDS)
        ).isoformat()
        await act("b", "reject-dissolution", f"拒绝解除道侣 {relation}", "PARTNER_DISSOLUTION_REJECTED")
        clock.advance(1)
        requested = await act("b", "request-again", f"申请解除道侣 {relation}", "PARTNER_DISSOLUTION_REQUESTED")
        assert requested.data["dissolution_expires_at"] == (
            clock.value + timedelta(seconds=DISSOLUTION_SECONDS)
        ).isoformat()
        dissolved = await act("a", "confirm", f"确认解除道侣 {relation}", "PARTNER_DISSOLVED")
        assert dissolved.data["cooldown_until"] == (
            clock.value + timedelta(seconds=COOLDOWN_SECONDS)
        ).isoformat()
        assert _state(runtime) == assets
        await runtime.close()

        runtime = create_runtime(data_dir=root, adapters=(adapter,), clock=clock)
        before = _state(runtime, relationships=True)
        for user, operation, command, result in history:
            _assert_replay(result, await _send(runtime, adapter, user, operation, command))
        for user, operation, command in (
            ("b", "accept", "接受道侣邀请 missing-relation"),
            ("b", "reject-dissolution", "拒绝解除道侣 missing-relation"),
            ("a", "confirm", "确认解除道侣 missing-relation"),
        ):
            assert (await _send(runtime, adapter, user, operation, command)).code == "OPERATION_CONFLICT"
        assert (await _send(runtime, adapter, "a", "view-dissolved", "道侣关系")).code == "PARTNER_NONE"
        assert _state(runtime, relationships=True) == before
        await runtime.close()

        _restore_content(
            root,
            invitation_ttl_seconds=11,
            dissolution_ttl_seconds=13,
            reunion_cooldown_seconds=17,
        )
        runtime = create_runtime(data_dir=root, adapters=(adapter,), clock=clock)
        clock.advance(COOLDOWN_SECONDS - 1)
        before = _state(runtime, relationships=True)
        blocked = await _send(runtime, adapter, "b", "reunite", "邀请结为道侣 青玄")
        assert blocked.code == "PARTNER_BREAK_COOLDOWN"
        assert _state(runtime, relationships=True) == before
        clock.advance(1)
        new_invite = await _send(runtime, adapter, "b", "reunite", "邀请结为道侣 青玄")
        assert new_invite.code == "PARTNER_INVITED", new_invite
        assert new_invite.data["relation_id"] != relation
        assert new_invite.data["invitation_expires_at"] == (clock.value + timedelta(seconds=11)).isoformat()
        _assert_replay(invited, await _send(runtime, adapter, "a", "invite", "邀请结为道侣 白衡"))
        assert _state(runtime) == assets
        with sqlite3.connect(runtime.settings.database_path) as connection:
            assert connection.execute("SELECT COUNT(*) FROM partner_relations").fetchone()[0] == 2
            assert connection.execute(
                "SELECT COUNT(*) FROM operations WHERE operation_name LIKE 'social.%partner%'"
            ).fetchone()[0] == len(history) + 1
        await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("adapter", ADAPTERS)
@pytest.mark.parametrize("remove", (False, True))
def test_pending_partner_can_be_rejected_after_content_disappears(
    tmp_path: Path, adapter: str, remove: bool
) -> None:
    async def run() -> None:
        root, clock = _content(tmp_path), Clock()
        runtime = create_runtime(data_dir=root, adapters=(adapter,), clock=clock)
        await _players(runtime, adapter)
        assets = _state(runtime)
        invited = await _send(runtime, adapter, "a", "invite", "邀请结为道侣 白衡")
        assert invited.code == "PARTNER_INVITED", invited
        command = f"拒绝道侣邀请 {invited.data['relation_id']}"
        await runtime.close()
        _edit(root, remove=remove, status="closed")
        runtime = create_runtime(data_dir=root, adapters=(adapter,), clock=clock)
        rejected = await _send(runtime, adapter, "b", "reject", command)
        assert rejected.code == "PARTNER_REJECTED", rejected
        assert rejected.data["status"] == "rejected"
        assert _state(runtime) == assets
        await runtime.close()

        runtime = create_runtime(data_dir=root, adapters=(adapter,), clock=clock)
        before = _state(runtime, relationships=True)
        _assert_replay(rejected, await _send(runtime, adapter, "b", "reject", command))
        _assert_replay(invited, await _send(runtime, adapter, "a", "invite", "邀请结为道侣 白衡"))
        assert (await _send(runtime, adapter, "b", "view", "道侣关系")).code == "PARTNER_NONE"
        conflict = await _send(runtime, adapter, "b", "reject", "拒绝道侣邀请 missing-relation")
        assert conflict.code == "OPERATION_CONFLICT"
        assert _state(runtime, relationships=True) == before
        await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_current_content_cannot_lower_an_existing_partner_invitation_requirement(
    tmp_path: Path, adapter: str
) -> None:
    async def run() -> None:
        root, clock = _content(tmp_path), Clock()
        runtime = create_runtime(data_dir=root, adapters=(adapter,), clock=clock)
        await _players(runtime, adapter)
        invited = await _send(runtime, adapter, "a", "invite", "邀请结为道侣 白衡")
        assert invited.code == "PARTNER_INVITED", invited
        command = f"接受道侣邀请 {invited.data['relation_id']}"
        _set_realm(runtime, adapter, "b", "foundation")
        await runtime.close()
        _edit(root, required_realm="foundation")
        runtime = create_runtime(data_dir=root, adapters=(adapter,), clock=clock)
        before = _state(runtime, relationships=True)
        blocked = await _send(runtime, adapter, "b", "accept", command)
        assert blocked.code == "PARTNER_REQUIREMENT_MISSING", blocked
        assert _state(runtime, relationships=True) == before
        _set_realm(runtime, adapter, "b", "nascent_soul")
        assets = _state(runtime)
        accepted = await _send(runtime, adapter, "b", "accept", command)
        assert accepted.code == "PARTNER_ACCEPTED", accepted
        assert _state(runtime) == assets
        await runtime.close()

    asyncio.run(run())
