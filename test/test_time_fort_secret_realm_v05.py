from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory

import pytest

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime


class MutableClock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs: int) -> None:
        self.now += timedelta(**kwargs)


def _ctx(adapter: str, user: str, operation: str) -> CommandContext:
    return CommandContext(adapter=adapter, user_id=user, operation_id=operation)


async def _player(runtime, adapter: str, user: str) -> None:
    assert (await runtime.adapters.dispatch(adapter, _ctx(adapter, user, f"{user}:create"), "开始修仙")).ok
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE players SET realm_key='void_refining', realm_layer=1, location_key='void.archive_ruins', "
            "stamina=100, stamina_max=100, max_hp=2000000, initiative=9999, "
            "qualification_json=?, intro_json=? WHERE platform=? AND platform_user_id=?",
            (json.dumps({"body": 100000, "agility": 9999}), json.dumps({"flags": ["access.void.time_fort"]}), adapter, user),
        )


async def _party(runtime, leader: tuple[str, str], member: tuple[str, str]) -> str:
    created = await runtime.adapters.dispatch(leader[0], _ctx(*leader, "party:create"), "创建时序堡垒秘境队伍")
    assert created.code == "PARTY_CREATED", created
    party_id = str(created.data["party_id"])
    assert (await runtime.adapters.dispatch(leader[0], _ctx(*leader, "party:invite"), f"邀请入队 {member[0]}:{member[1]}")).ok
    assert (await runtime.adapters.dispatch(member[0], _ctx(*member, "party:accept"), f"接受入队 {party_id}")).ok
    for index, identity in enumerate((leader, member)):
        assert (await runtime.adapters.dispatch(identity[0], _ctx(*identity, f"party:confirm:{index}"), f"确认入队 {party_id}")).ok
    return party_id


@pytest.mark.parametrize(("leader_adapter", "member_adapter"), [("qq.official", "onebot.v11"), ("onebot.v11", "qq.official")])
def test_time_fort_mixed_adapters_route_storm_restart_and_rewards(leader_adapter: str, member_adapter: str) -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 28, 12, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            leader = (leader_adapter, f"time-leader-{leader_adapter}")
            member = (member_adapter, f"time-member-{leader_adapter}")
            await _player(runtime, *leader)
            await _player(runtime, *member)
            await _party(runtime, leader, member)
            entered = await runtime.adapters.dispatch(leader[0], _ctx(*leader, "time:enter"), "进入秘境 时序堡垒")
            assert entered.code == "TIME_FORT_ENTERED", entered
            for index, node in enumerate(("堡垒门庭", "星时回廊", "时间风暴", "残破沙漏")):
                assert (await runtime.adapters.dispatch(leader[0], _ctx(*leader, f"time:node:{index}"), f"选择秘境节点 {node}")).ok
            pending = await runtime.adapters.dispatch(leader[0], _ctx(*leader, "time:keeper"), "选择秘境节点 守时者")
            assert pending.code == "TIME_FORT_COMBAT_PENDING", pending
            battle_id = pending.data["battle_id"]
            with sqlite3.connect(runtime.settings.database_path) as connection:
                session = connection.execute("SELECT snapshot_json FROM party_battle_sessions WHERE battle_id=?", (battle_id,)).fetchone()
                snapshot = json.loads(session[0])
                assert snapshot["time_storm"]["enabled"] is True
            await runtime.close()
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            settled_battle = await runtime.adapters.dispatch(member[0], _ctx(*member, "time:battle"), "结算秘境")
            assert settled_battle.code == "TIME_FORT_BATTLE_SETTLED", settled_battle
            assert settled_battle.data["current_node"] == "chronicle_exit"
            assert (await runtime.adapters.dispatch(leader[0], _ctx(*leader, "time:exit"), "选择秘境节点 编年出口")).code == "TIME_FORT_ROUTE_CLEARED"
            settled = await runtime.adapters.dispatch(member[0], _ctx(*member, "time:finish"), "结算秘境")
            assert settled.code == "TIME_FORT_SETTLED", settled
            with sqlite3.connect(runtime.settings.database_path) as connection:
                stable_ids = {row[0] for row in connection.execute("SELECT player_id FROM players WHERE platform_user_id IN (?, ?)", (leader[1], member[1])).fetchall()}
                assert set(settled.data["first_clear_members"]) == stable_ids
                rows = connection.execute("SELECT inventory_json, intro_json FROM players ORDER BY id").fetchall()
                assert all(json.loads(row[0]).get("item.mat.array_sand") == 2 for row in rows)
                assert all("story.mainline.void_archive.time_fort" in json.loads(row[1]).get("flags", []) for row in rows)
            await runtime.close()

    asyncio.run(run())


def test_time_fort_expiry_and_system_compensation() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 28, 12, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            leader = ("qq.official", "time-expire-leader")
            member = ("onebot.v11", "time-expire-member")
            await _player(runtime, *leader)
            await _player(runtime, *member)
            await _party(runtime, leader, member)
            assert (await runtime.adapters.dispatch(leader[0], _ctx(*leader, "time:enter"), "进入秘境 时序堡垒")).ok
            clock.advance(hours=1, seconds=1)
            expired = await runtime.adapters.dispatch(member[0], _ctx(*member, "time:expire"), "结算秘境")
            assert expired.code == "TIME_FORT_SETTLED"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                stamina = connection.execute("SELECT stamina FROM players WHERE platform=? AND platform_user_id=?", leader).fetchone()[0]
                assert stamina == 60
            await runtime.close()

    asyncio.run(run())
