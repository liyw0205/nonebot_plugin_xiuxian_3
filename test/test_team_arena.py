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
                ratings = connection.execute("SELECT arena_rating FROM players WHERE platform_user_id LIKE 'team-%'").fetchall()
            assert all(int(row[0]) != 1000 for row in ratings)
            await runtime.close()

    asyncio.run(run())
