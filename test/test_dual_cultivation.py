from __future__ import annotations

import asyncio
import json
import shutil
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError
from nonebot_plugin_xiuxian_3.xiuxian.social.dual_cultivation_migration import ensure_dual_cultivation_schema


ROOT = Path(__file__).resolve().parents[1]


class MutableClock:
    def __init__(self, value: datetime):
        self.value = value

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **kwargs: int) -> None:
        self.value += timedelta(**kwargs)


def _context(adapter: str, user: str, operation_id: str = "") -> CommandContext:
    return CommandContext(adapter=adapter, user_id=user, operation_id=operation_id)


async def _player(runtime, adapter: str, user: str, name: str) -> None:
    assert (await runtime.dispatch(_context(adapter, user), f"开始修仙 {name}")).ok
    assert (await runtime.dispatch(_context(adapter, user), "寻仙问道")).ok
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE players SET stage='cultivator', realm_key='nascent_soul', realm_layer=1, "
            "cultivation=0, total_cultivation=248960, location_key='xuantian.new_town', "
            "spirit_stones=1000, energy=100 WHERE platform=? AND platform_user_id=?",
            (adapter, user),
        )


async def _partners(runtime, *, web: bool = False, invitee_name: str = "白衡") -> str:
    initiator_adapter, initiator_id = ("web", "a") if web else ("qq.official", "a")
    invitee_adapter, invitee_id = ("web", "b") if web else ("onebot.v11", "b")
    invite = await runtime.adapters.dispatch(
        initiator_adapter, _context(initiator_adapter, initiator_id, "relationship-invite"), f"邀请结为道侣 {invitee_name}"
    )
    assert invite.code == "PARTNER_INVITED"
    accepted = await runtime.adapters.dispatch(
        invitee_adapter, _context(invitee_adapter, invitee_id, "relationship-accept"),
        f"接受道侣邀请 {invite.data['relation_id']}",
    )
    assert accepted.code == "PARTNER_ACCEPTED"
    return invite.data["relation_id"]


def _players(runtime) -> tuple[tuple[int, ...], tuple[int, ...]]:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        rows = tuple(connection.execute(
            "SELECT id,spirit_stones,energy,cultivation,total_cultivation FROM players "
            "WHERE platform_user_id IN ('a','b') ORDER BY platform_user_id DESC"
        ))
    return tuple(row[1:] for row in rows), tuple(row[0] for row in rows)


def test_dual_cultivation_cross_adapter_settles_both_players_once() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, adapters=("qq.official", "onebot.v11"))
            await _player(runtime, "qq.official", "a", "青玄")
            await _player(runtime, "onebot.v11", "b", "白衡")
            relation_id = await _partners(runtime)
            before, player_ids = _players(runtime)
            preview = await runtime.adapters.dispatch("qq.official", _context("qq.official", "a"), "双修预览")
            assert preview.code == "DUAL_CULTIVATION_PREVIEW" and preview.data["eligible"]
            invitation = await runtime.adapters.dispatch(
                "qq.official", _context("qq.official", "a", "dual-invite"), "发起双修 白衡"
            )
            assert invitation.code == "DUAL_CULTIVATION_INVITED"
            assert invitation.actions
            invite_replay = await runtime.adapters.dispatch(
                "qq.official", _context("qq.official", "a", "dual-invite"), "发起双修 白衡"
            )
            assert invite_replay.data["idempotent_replay"] is True
            assert invite_replay.data["invitation_id"] == invitation.data["invitation_id"]
            assert (await runtime.dispatch(_context("qq.official", "a"), "双修状态")).data["invitations"]
            accepted = await runtime.adapters.dispatch(
                "onebot.v11", _context("onebot.v11", "b", "dual-accept"),
                f"接受双修 {invitation.data['invitation_id']}",
            )
            assert accepted.code == "DUAL_CULTIVATION_SETTLED"
            await runtime.close()
            runtime = create_runtime(data_dir=data_dir, adapters=("qq.official", "onebot.v11"))
            replay = await runtime.adapters.dispatch(
                "onebot.v11", _context("onebot.v11", "b", "dual-accept"),
                f"接受双修 {invitation.data['invitation_id']}",
            )
            assert replay.data["idempotent_replay"] is True
            conflict = await runtime.adapters.dispatch(
                "onebot.v11", _context("onebot.v11", "b", "dual-accept"), "接受双修 another-invitation"
            )
            assert conflict.code == "OPERATION_CONFLICT"
            after, _ = _players(runtime)
            for old, new in zip(before, after):
                assert new[0] == old[0] - 100
                assert new[1] == old[1] - 5
                assert new[2] > old[2] and new[2] <= 9000
                assert new[3] == old[3] + new[2] - old[2]
            with sqlite3.connect(runtime.settings.database_path) as connection:
                invitation_id = invitation.data["invitation_id"]
                assert connection.execute(
                    "SELECT status FROM partner_cultivation_invitations WHERE invitation_id=?", (invitation_id,)
                ).fetchone()[0] == "settled"
                settlements = connection.execute(
                    "SELECT player_id,operation_id,cost_json,gain FROM partner_cultivation_settlements "
                    "WHERE invitation_id=? ORDER BY player_id", (invitation_id,)
                ).fetchall()
                assert len(settlements) == 2 and {row[0] for row in settlements} == set(player_ids)
                assert {row[2] for row in settlements} == {'{"energy": 5, "spirit_stones": 100}'}
                assert connection.execute(
                    "SELECT COUNT(*) FROM operations WHERE operation_id='dual-accept'"
                ).fetchone()[0] == 1
                assert connection.execute(
                    "SELECT COUNT(DISTINCT player_id) FROM economy_ledger_entries WHERE operation_id='dual-accept'"
                ).fetchone()[0] == 2
                assert connection.execute(
                    "SELECT relation_id FROM partner_cultivation_invitations WHERE invitation_id=?", (invitation_id,)
                ).fetchone()[0] == relation_id
            await runtime.close()

    asyncio.run(run())


def test_dual_cultivation_failure_is_atomic_and_invite_can_be_retried() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, adapters=("web",))
            await _player(runtime, "web", "a", "甲")
            await _player(runtime, "web", "b", "乙")
            await _partners(runtime, web=True, invitee_name="乙")
            invitation = await runtime.dispatch(_context("web", "a", "dual-invite"), "发起双修 乙")
            invitation_id = invitation.data["invitation_id"]
            before, _ = _players(runtime)
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute("UPDATE players SET energy=0 WHERE platform_user_id='b'")
            failed = await runtime.dispatch(
                _context("web", "b", "dual-accept-failed"), f"接受双修 {invitation_id}"
            )
            assert failed.code == "DUAL_CULTIVATION_COST"
            failed_state, _ = _players(runtime)
            assert failed_state[0][0] == before[0][0] and failed_state[0][1] == 0
            assert failed_state[0][2:] == before[0][2:]
            assert failed_state[1] == before[1]
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute(
                    "SELECT status FROM partner_cultivation_invitations WHERE invitation_id=?", (invitation_id,)
                ).fetchone()[0] == "invited"
                assert connection.execute(
                    "SELECT COUNT(*) FROM partner_cultivation_settlements WHERE invitation_id=?", (invitation_id,)
                ).fetchone()[0] == 0
                assert connection.execute(
                    "SELECT COUNT(*) FROM operations WHERE operation_id='dual-accept-failed'"
                ).fetchone()[0] == 0
                connection.execute("UPDATE players SET energy=100 WHERE platform_user_id='b'")
            retried = await runtime.dispatch(
                _context("web", "b", "dual-accept-retry"), f"接受双修 {invitation_id}"
            )
            assert retried.code == "DUAL_CULTIVATION_SETTLED"
            assert before[0][0] != _players(runtime)[0][0]
            second_invite = await runtime.dispatch(_context("web", "a", "another-invite"), "发起双修 乙")
            assert second_invite.code == "DUAL_CULTIVATION_INVITED"
            second_accept = await runtime.dispatch(
                _context("web", "b", "second-accept"), f"接受双修 {second_invite.data['invitation_id']}"
            )
            assert second_accept.code == "DUAL_CULTIVATION_SETTLED"
            third_invite = await runtime.dispatch(_context("web", "a", "third-invite"), "发起双修 乙")
            assert third_invite.code == "DUAL_CULTIVATION_QUOTA"
            await runtime.close()

    asyncio.run(run())


def test_dual_cultivation_reject_cancel_and_changed_location() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, adapters=("web",))
            await _player(runtime, "web", "a", "甲")
            await _player(runtime, "web", "b", "乙")
            await _partners(runtime, web=True, invitee_name="乙")
            reject_invite = await runtime.dispatch(_context("web", "a", "invite-1"), "发起双修 乙")
            rejected = await runtime.dispatch(
                _context("web", "b", "reject-1"), f"拒绝双修 {reject_invite.data['invitation_id']}"
            )
            assert rejected.code == "DUAL_CULTIVATION_REJECTED"
            cancel_invite = await runtime.dispatch(_context("web", "a", "invite-2"), "发起双修 乙")
            cancelled = await runtime.dispatch(
                _context("web", "a", "cancel-2"), f"取消双修 {cancel_invite.data['invitation_id']}"
            )
            assert cancelled.code == "DUAL_CULTIVATION_CANCELLED"
            moved = await runtime.dispatch(_context("web", "a", "invite-3"), "发起双修 乙")
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute("UPDATE players SET location_key='xuantian.cloud_city' WHERE platform_user_id='b'")
            before, _ = _players(runtime)
            failed = await runtime.dispatch(
                _context("web", "b", "accept-moved"), f"接受双修 {moved.data['invitation_id']}"
            )
            assert failed.code == "DUAL_CULTIVATION_LOCATION"
            assert _players(runtime)[0] == before
            await runtime.close()

    asyncio.run(run())


def test_dual_cultivation_rechecks_relationship_before_acceptance() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, adapters=("web",))
            await _player(runtime, "web", "a", "甲")
            await _player(runtime, "web", "b", "乙")
            relation_id = await _partners(runtime, web=True, invitee_name="乙")
            invitation = await runtime.dispatch(_context("web", "a", "invite"), "发起双修 乙")
            before, _ = _players(runtime)
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE partner_relations SET status='dissolution_pending' WHERE relation_id=?",
                    (relation_id,),
                )

            denied = await runtime.dispatch(
                _context("web", "b", "accept-dissolving"),
                f"接受双修 {invitation.data['invitation_id']}",
            )
            assert denied.code == "DUAL_CULTIVATION_RELATION"
            assert _players(runtime)[0] == before
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute(
                    "SELECT status FROM partner_cultivation_invitations WHERE invitation_id=?",
                    (invitation.data["invitation_id"],),
                ).fetchone()[0] == "invited"
                connection.execute(
                    "UPDATE partner_relations SET status='active' WHERE relation_id=?", (relation_id,)
                )

            accepted = await runtime.dispatch(
                _context("web", "b", "accept-restored"),
                f"接受双修 {invitation.data['invitation_id']}",
            )
            assert accepted.code == "DUAL_CULTIVATION_SETTLED"
            await runtime.close()

    asyncio.run(run())


def test_dual_cultivation_rejects_invalid_invitation_targets_and_requirements() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, adapters=("web",))
            await _player(runtime, "web", "a", "甲")
            await _player(runtime, "web", "b", "乙")
            await _player(runtime, "web", "c", "丙")
            await _partners(runtime, web=True, invitee_name="乙")

            self_invite = await runtime.dispatch(_context("web", "a", "self"), "发起双修 甲")
            stranger = await runtime.dispatch(_context("web", "a", "stranger"), "发起双修 丙")
            unknown = await runtime.dispatch(_context("web", "a", "unknown"), "发起双修 不存在")
            assert self_invite.code == "DUAL_CULTIVATION_SELF"
            assert stranger.code == "DUAL_CULTIVATION_RELATION"
            assert unknown.code == "DUAL_CULTIVATION_TARGET"

            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE players SET realm_key='qi_gathering',realm_layer=1 WHERE platform_user_id='b'"
                )
            below_gate = await runtime.dispatch(_context("web", "a", "below-gate"), "发起双修 乙")
            assert below_gate.code == "DUAL_CULTIVATION_PROGRESSION"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute(
                    "SELECT COUNT(*) FROM partner_cultivation_invitations"
                ).fetchone()[0] == 0
                assert connection.execute(
                    "SELECT COUNT(*) FROM operations WHERE operation_id IN ('self','stranger','unknown','below-gate')"
                ).fetchone()[0] == 0
            await runtime.close()

    asyncio.run(run())


def test_dual_cultivation_concurrent_acceptance_settles_once() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, adapters=("web",))
            await _player(runtime, "web", "a", "甲")
            await _player(runtime, "web", "b", "乙")
            await _partners(runtime, web=True, invitee_name="乙")
            invitation = await runtime.dispatch(_context("web", "a", "invite"), "发起双修 乙")
            invitation_id = invitation.data["invitation_id"]
            results = await asyncio.gather(
                runtime.dispatch(_context("web", "b", "accept-1"), f"接受双修 {invitation_id}"),
                runtime.dispatch(_context("web", "b", "accept-2"), f"接受双修 {invitation_id}"),
            )
            assert sorted(result.code for result in results) == [
                "DUAL_CULTIVATION_SETTLED", "DUAL_CULTIVATION_STATE",
            ]
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute(
                    "SELECT COUNT(*) FROM partner_cultivation_settlements WHERE invitation_id=?", (invitation_id,)
                ).fetchone()[0] == 2
                assert connection.execute(
                    "SELECT COUNT(*) FROM economy_ledger_entries WHERE reason='partner_cultivation'"
                ).fetchone()[0] == 8
            await runtime.close()

    asyncio.run(run())


def test_dual_cultivation_lock_and_consent_boundaries() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, adapters=("web",))
            await _player(runtime, "web", "a", "甲")
            await _player(runtime, "web", "b", "乙")
            await _player(runtime, "web", "c", "丙")
            await _partners(runtime, web=True, invitee_name="乙")
            invitation = await runtime.dispatch(_context("web", "a", "invite"), "发起双修 乙")
            invitation_id = invitation.data["invitation_id"]
            third_party = await runtime.dispatch(
                _context("web", "c", "third-party"), f"接受双修 {invitation_id}"
            )
            assert third_party.code == "DUAL_CULTIVATION_NOT_FOUND"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                player_id = connection.execute(
                    "SELECT id FROM players WHERE platform='web' AND platform_user_id='b'"
                ).fetchone()[0]
                connection.execute(
                    "INSERT INTO cultivation_sessions(session_id,player_id,operation_id,mode_key,status,"
                    "starts_at,ends_at,stamina_cost,created_at,updated_at) "
                    "VALUES('lock-session',?,'lock-operation','cultivation.standard','running',"
                    "'2026-11-21T00:00:00+00:00','2026-11-21T01:00:00+00:00',0,"
                    "'2026-11-21T00:00:00+00:00','2026-11-21T00:00:00+00:00')", (player_id,),
                )
            locked = await runtime.dispatch(
                _context("web", "b", "locked-accept"), f"接受双修 {invitation_id}"
            )
            assert locked.code == "DUAL_CULTIVATION_BUSY"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute(
                    "SELECT status FROM partner_cultivation_invitations WHERE invitation_id=?", (invitation_id,)
                ).fetchone()[0] == "invited"
                connection.execute("DELETE FROM cultivation_sessions WHERE session_id='lock-session'")
            accepted = await runtime.dispatch(
                _context("web", "b", "unlocked-accept"), f"接受双修 {invitation_id}"
            )
            assert accepted.code == "DUAL_CULTIVATION_SETTLED"
            await runtime.close()

    asyncio.run(run())


def test_dual_cultivation_mid_transaction_failure_rolls_back_everything() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, adapters=("web",))
            await _player(runtime, "web", "a", "甲")
            await _player(runtime, "web", "b", "乙")
            await _partners(runtime, web=True, invitee_name="乙")
            invitation = await runtime.dispatch(_context("web", "a", "invite"), "发起双修 乙")
            invitation_id = invitation.data["invitation_id"]
            before, _ = _players(runtime)
            original = runtime.repository._dual_settle_player
            calls = 0

            def fail_second(connection, player, gain, rule, day, invite_id, operation_id, now_text):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise sqlite3.OperationalError("injected second-player failure")
                return original(connection, player, gain, rule, day, invite_id, operation_id, now_text)

            runtime.repository._dual_settle_player = fail_second
            failed = await runtime.dispatch(
                _context("web", "b", "settlement-failure"), f"接受双修 {invitation_id}"
            )
            assert failed.code == "PERSISTENCE_ERROR"
            assert _players(runtime)[0] == before
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute(
                    "SELECT status FROM partner_cultivation_invitations WHERE invitation_id=?", (invitation_id,)
                ).fetchone()[0] == "invited"
                assert connection.execute(
                    "SELECT COUNT(*) FROM partner_cultivation_settlements WHERE invitation_id=?", (invitation_id,)
                ).fetchone()[0] == 0
                assert connection.execute(
                    "SELECT COUNT(*) FROM economy_ledger_entries WHERE reason='partner_cultivation'"
                ).fetchone()[0] == 0
                assert connection.execute(
                    "SELECT COUNT(*) FROM operations WHERE operation_id='settlement-failure'"
                ).fetchone()[0] == 0
            runtime.repository._dual_settle_player = original
            retried = await runtime.dispatch(
                _context("web", "b", "settlement-failure"), f"接受双修 {invitation_id}"
            )
            assert retried.code == "DUAL_CULTIVATION_SETTLED"
            await runtime.close()

    asyncio.run(run())


def test_dual_cultivation_expiry_and_closed_rules_preserve_snapshot() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 11, 21, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            shutil.copytree(ROOT / "data", data_dir, dirs_exist_ok=True)
            runtime = create_runtime(data_dir=data_dir, adapters=("web",), clock=clock)
            await _player(runtime, "web", "a", "甲")
            await _player(runtime, "web", "b", "乙")
            await _partners(runtime, web=True, invitee_name="乙")
            invitation = await runtime.dispatch(_context("web", "a", "invite"), "发起双修 乙")
            clock.advance(seconds=600)
            expired = await runtime.dispatch(
                _context("web", "b", "expire-accept"), f"接受双修 {invitation.data['invitation_id']}"
            )
            assert expired.code == "DUAL_CULTIVATION_EXPIRED"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute(
                    "SELECT status FROM partner_cultivation_invitations WHERE invitation_id=?",
                    (invitation.data["invitation_id"],),
                ).fetchone()[0] == "expired"

            clock.advance(seconds=1)
            active_invitation = await runtime.dispatch(_context("web", "a", "invite-2"), "发起双修 乙")
            rule_path = Path(data_dir) / "社交" / "双修.json"
            document = json.loads(rule_path.read_text(encoding="utf-8"))
            document["records"][0]["status"] = "closed"
            rule_path.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
            runtime.repository.content = ContentBundle.load(data_dir)
            closed = await runtime.dispatch(_context("web", "a", "closed-invite"), "发起双修 乙")
            assert closed.code == "DUAL_CULTIVATION_CLOSED"
            accepted = await runtime.dispatch(
                _context("web", "b", "accept-closed-rule"),
                f"接受双修 {active_invitation.data['invitation_id']}",
            )
            assert accepted.code == "DUAL_CULTIVATION_SETTLED"
            await runtime.close()

    asyncio.run(run())


def test_dual_cultivation_content_is_strict_and_migration_is_repeatable() -> None:
    bundle = ContentBundle.load(ROOT / "data")
    record = bundle.require("partner_cultivation", "social.partner_cultivation")
    assert record["allowed_locations"] == ["xuantian.new_town", "xuantian.cloud_city"]
    with TemporaryDirectory() as content_dir:
        shutil.copytree(ROOT / "data", content_dir, dirs_exist_ok=True)
        path = Path(content_dir) / "社交" / "双修.json"
        document = json.loads(path.read_text(encoding="utf-8"))
        document["records"][0]["cost"]["unknown"] = 3
        path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
        with pytest.raises(ContentError):
            ContentBundle.load(content_dir)

    connection = sqlite3.connect(":memory:")
    connection.execute("PRAGMA foreign_keys=ON")
    connection.executescript("CREATE TABLE players(id INTEGER PRIMARY KEY); CREATE TABLE partner_relations(relation_id TEXT PRIMARY KEY); CREATE TABLE operations(operation_id TEXT PRIMARY KEY);")
    connection.execute("INSERT INTO players VALUES(1)")
    connection.execute("INSERT INTO partner_relations VALUES('existing')")
    ensure_dual_cultivation_schema(connection)
    ensure_dual_cultivation_schema(connection)
    assert connection.execute("SELECT relation_id FROM partner_relations").fetchall() == [("existing",)]
    connection.close()
