from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime


class MutableClock:
    def __init__(self, value: datetime):
        self.value = value

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **kwargs: int) -> None:
        self.value += timedelta(**kwargs)


def _ctx(adapter: str, user: str, operation: str) -> CommandContext:
    return CommandContext(adapter=adapter, user_id=user, operation_id=operation)


async def _player(runtime, adapter: str, user: str, operation: str) -> None:
    created = await runtime.adapters.dispatch(adapter, _ctx(adapter, user, operation), "开始修仙")
    assert created.ok, (created.code, created.message)
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE players SET stage='cultivator', realm_key='qi_sensing', realm_layer=2, location_key='xuantian.outskirts', max_hp=999, initiative=99, qualification_json=? WHERE platform=? AND platform_user_id=?",
            (json.dumps({"body": 100, "agility": 100}), adapter, user),
        )


async def _ready_party(runtime, adapter: str, leader: str, member: str, prefix: str) -> str:
    created = await runtime.adapters.dispatch(adapter, _ctx(adapter, leader, prefix + "-create"), "创建双人队伍")
    assert created.code == "PARTY_CREATED"
    party_id = str(created.data["party_id"])
    invited = await runtime.adapters.dispatch(adapter, _ctx(adapter, leader, prefix + "-invite"), f"邀请入队 {member}")
    assert invited.code == "PARTY_INVITED"
    accepted = await runtime.adapters.dispatch(adapter, _ctx(adapter, member, prefix + "-accept"), f"接受入队 {party_id}")
    assert accepted.code == "PARTY_JOINED"
    assert (await runtime.adapters.dispatch(adapter, _ctx(adapter, leader, prefix + "-confirm-leader"), f"确认入队 {party_id}")).code == "PARTY_CONFIRMED"
    assert (await runtime.adapters.dispatch(adapter, _ctx(adapter, member, prefix + "-confirm-member"), f"确认入队 {party_id}")).code == "PARTY_READY"
    return party_id


async def _ready_trio_party(runtime, adapter: str, leader: str, members: tuple[str, str], prefix: str) -> str:
    created = await runtime.adapters.dispatch(adapter, _ctx(adapter, leader, prefix + "-create"), "创建三人竞技队伍")
    assert created.code == "PARTY_CREATED"
    assert created.data["party_type"] == "arena_trio"
    party_id = str(created.data["party_id"])
    for index, member in enumerate(members):
        invited = await runtime.adapters.dispatch(adapter, _ctx(adapter, leader, f"{prefix}-invite-{index}"), f"邀请入队 {member}")
        assert invited.code == "PARTY_INVITED"
        accepted = await runtime.adapters.dispatch(adapter, _ctx(adapter, member, f"{prefix}-accept-{index}"), f"接受入队 {party_id}")
        assert accepted.code == "PARTY_JOINED"
    for index, user in enumerate((leader, *members)):
        confirmed = await runtime.adapters.dispatch(adapter, _ctx(adapter, user, f"{prefix}-confirm-{index}"), f"确认入队 {party_id}")
        assert confirmed.code in {"PARTY_CONFIRMED", "PARTY_READY"}
    profile = await runtime.adapters.dispatch(adapter, _ctx(adapter, leader, prefix + "-profile"), "队伍状态")
    assert profile.code == "PARTY_PROFILE"
    assert profile.data["ready"] is True
    return party_id


def test_qq_onebot_team_arena_uses_team_snapshots_and_server_replay() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 25, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            await _player(runtime, "qq.official", "team-qq-leader", "qq-create")
            await _player(runtime, "qq.official", "team-qq-member", "qq-member-create")
            await _player(runtime, "onebot.v11", "team-ob-leader", "ob-create")
            await _player(runtime, "onebot.v11", "team-ob-member", "ob-member-create")
            await _ready_party(runtime, "qq.official", "team-qq-leader", "team-qq-member", "qq-party")
            await _ready_party(runtime, "onebot.v11", "team-ob-leader", "team-ob-member", "ob-party")

            qq_published = await runtime.adapters.dispatch("qq.official", _ctx("qq.official", "team-qq-leader", "qq-publish"), "发布组队竞技场快照")
            ob_published = await runtime.adapters.dispatch("onebot.v11", _ctx("onebot.v11", "team-ob-leader", "ob-publish"), "发布组队竞技场快照")
            assert qq_published.code == "TEAM_ARENA_SNAPSHOT_PUBLISHED"
            assert ob_published.code == "TEAM_ARENA_SNAPSHOT_PUBLISHED"
            before = await runtime.adapters.dispatch("qq.official", _ctx("qq.official", "team-qq-leader", "qq-before"), "挑战组队竞技场")
            assert before.code == "TEAM_ARENA_OPPONENT_UNAVAILABLE"
            clock.advance(minutes=31)
            listed = await runtime.adapters.dispatch("qq.official", _ctx("qq.official", "team-qq-leader", "qq-list"), "组队竞技场列表")
            assert listed.code == "TEAM_ARENA_SNAPSHOT_LIST"
            team_snapshot_id = str(ob_published.data["snapshot_id"])
            result = await runtime.adapters.dispatch("qq.official", _ctx("qq.official", "team-qq-leader", "qq-challenge"), f"挑战组队竞技场 {team_snapshot_id}")
            assert result.code == "TEAM_ARENA_MATCH_SETTLED", result.message
            assert result.data["rounds"] <= 15
            replay = await runtime.adapters.dispatch("onebot.v11", _ctx("onebot.v11", "team-ob-member", "ob-replay"), f"组队竞技场回放 {result.data['match_id']}")
            assert replay.code == "TEAM_ARENA_REPLAY"
            assert replay.data["actions"]
            replayed = await runtime.adapters.dispatch("qq.official", _ctx("qq.official", "team-qq-leader", "qq-challenge"), f"挑战组队竞技场 {team_snapshot_id}")
            assert replayed.data["idempotent_replay"] is True
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute("SELECT COUNT(*) FROM arena_team_matches").fetchone()[0] == 1
                assert connection.execute("SELECT COUNT(*) FROM arena_team_actions").fetchone()[0] > 0
                assert connection.execute("SELECT COUNT(*) FROM battle_sessions").fetchone()[0] == 0
                assert connection.execute("SELECT COUNT(*) FROM arena_projection_events").fetchone()[0] == 4
                assert connection.execute("SELECT COUNT(*) FROM codex_entries").fetchone()[0] == 8
                assert connection.execute("SELECT COUNT(*) FROM arena_identity_routes").fetchone()[0] == 4
                assert connection.execute("SELECT COUNT(*) FROM arena_audit_events").fetchone()[0] == 4
                ratings = connection.execute("SELECT arena_rating FROM players WHERE platform_user_id LIKE 'team-%'").fetchall()
            assert all(int(row[0]) != 1000 for row in ratings)
            await runtime.close()

    asyncio.run(run())


def test_three_member_arena_party_matches_three_member_snapshot_without_party_pve() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 25, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            qq_members = ("trio-qq-member-1", "trio-qq-member-2")
            ob_members = ("trio-ob-member-1", "trio-ob-member-2")
            for user in ("trio-qq-leader", *qq_members):
                await _player(runtime, "qq.official", user, "create-" + user)
            for user in ("trio-ob-leader", *ob_members):
                await _player(runtime, "onebot.v11", user, "create-" + user)
            await _ready_trio_party(runtime, "qq.official", "trio-qq-leader", qq_members, "qq-trio")
            await _ready_trio_party(runtime, "onebot.v11", "trio-ob-leader", ob_members, "ob-trio")
            pve = await runtime.adapters.dispatch("qq.official", _ctx("qq.official", "trio-qq-leader", "trio-pve"), "开始队伍战斗")
            assert pve.code == "PARTY_BATTLE_REQUIREMENT_MISSING"
            left = await runtime.adapters.dispatch("qq.official", _ctx("qq.official", "trio-qq-leader", "trio-publish"), "发布组队竞技场快照")
            right = await runtime.adapters.dispatch("onebot.v11", _ctx("onebot.v11", "trio-ob-leader", "trio-ob-publish"), "发布组队竞技场快照")
            assert left.code == right.code == "TEAM_ARENA_SNAPSHOT_PUBLISHED"
            clock.advance(minutes=31)
            result = await runtime.adapters.dispatch("qq.official", _ctx("qq.official", "trio-qq-leader", "trio-challenge"), f"挑战组队竞技场 {right.data['snapshot_id']}")
            assert result.code == "TEAM_ARENA_MATCH_SETTLED", result.message
            replay = await runtime.adapters.dispatch("onebot.v11", _ctx("onebot.v11", "trio-ob-member-2", "trio-replay"), f"组队竞技场回放 {result.data['match_id']}")
            assert replay.code == "TEAM_ARENA_REPLAY"
            assert len(replay.data["snapshot"]["challenger"]["members"]) == 3
            assert len(replay.data["snapshot"]["defender"]["members"]) == 3
            await runtime.close()

    asyncio.run(run())


def test_asymmetric_two_vs_three_team_arena_replays_both_team_sizes() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 25, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            for user in ("asym-qq-leader", "asym-qq-member"):
                await _player(runtime, "qq.official", user, "create-" + user)
            for user in ("asym-ob-leader", "asym-ob-member-1", "asym-ob-member-2"):
                await _player(runtime, "onebot.v11", user, "create-" + user)
            await _ready_party(runtime, "qq.official", "asym-qq-leader", "asym-qq-member", "asym-pair")
            await _ready_trio_party(runtime, "onebot.v11", "asym-ob-leader", ("asym-ob-member-1", "asym-ob-member-2"), "asym-trio")
            pair = await runtime.adapters.dispatch("qq.official", _ctx("qq.official", "asym-qq-leader", "asym-pair-publish"), "发布组队竞技场快照")
            trio = await runtime.adapters.dispatch("onebot.v11", _ctx("onebot.v11", "asym-ob-leader", "asym-trio-publish"), "发布组队竞技场快照")
            assert pair.code == trio.code == "TEAM_ARENA_SNAPSHOT_PUBLISHED"
            clock.advance(minutes=31)
            result = await runtime.adapters.dispatch("qq.official", _ctx("qq.official", "asym-qq-leader", "asym-challenge"), f"挑战组队竞技场 {trio.data['snapshot_id']}")
            assert result.code == "TEAM_ARENA_MATCH_SETTLED", result.message
            replay = await runtime.adapters.dispatch("onebot.v11", _ctx("onebot.v11", "asym-ob-member-1", "asym-replay"), f"组队竞技场回放 {result.data['match_id']}")
            assert replay.code == "TEAM_ARENA_REPLAY"
            assert len(replay.data["snapshot"]["challenger"]["members"]) == 2
            assert len(replay.data["snapshot"]["defender"]["members"]) == 3
            await runtime.close()

    asyncio.run(run())
