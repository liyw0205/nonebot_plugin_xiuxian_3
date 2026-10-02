from __future__ import annotations

import asyncio
import json
import sqlite3
from tempfile import TemporaryDirectory

import pytest

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.repository import PartyBattleRequirementError


def _ctx(adapter: str, user: str, operation: str = "") -> CommandContext:
    return CommandContext(adapter=adapter, user_id=user, operation_id=operation)


async def _create_standard_player(runtime, adapter: str, user: str) -> None:
    created = await runtime.adapters.dispatch(
        adapter,
        _ctx(adapter, user, f"create:{adapter}:{user}"),
        "开始修仙",
    )
    assert created.code == "PLAYER_CREATED"
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE players SET stage='cultivator', realm_key='mortal', realm_layer=0, "
            "location_key='xuantian.outskirts', stamina=100, stamina_max=100, "
            "max_hp=999, initiative=99, qualification_json=? "
            "WHERE platform=? AND platform_user_id=?",
            (json.dumps({"body": 2_000, "agility": 2_000}), adapter, user),
        )


async def _invite_and_accept(runtime, leader_adapter: str, leader: str, member_adapter: str, member: str, party_id: str, index: int) -> None:
    invited = await runtime.adapters.dispatch(
        leader_adapter,
        _ctx(leader_adapter, leader, f"invite:{index}"),
        f"邀请入队 {member_adapter}:{member}",
    )
    assert invited.code == "PARTY_INVITED"
    accepted = await runtime.adapters.dispatch(
        member_adapter,
        _ctx(member_adapter, member, f"accept:{index}"),
        f"接受入队 {party_id}",
    )
    assert accepted.code == "PARTY_JOINED"


def test_standard_pve_qq_onebot_party_limits_snapshot_and_idempotency() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            members = (
                ("qq.official", "standard-leader"),
                ("onebot.v11", "standard-two"),
                ("qq.official", "standard-three"),
                ("onebot.v11", "standard-four"),
                ("qq.official", "standard-five"),
                ("onebot.v11", "standard-six"),
            )
            for adapter, user in members:
                await _create_standard_player(runtime, adapter, user)

            leader_adapter, leader = members[0]
            created = await runtime.adapters.dispatch(
                leader_adapter,
                _ctx(leader_adapter, leader, "standard-create"),
                "创建四人副本队伍",
            )
            assert created.code == "PARTY_CREATED"
            assert created.data["party_type"] == "standard_pve"
            party_id = str(created.data["party_id"])
            replay_create = await runtime.adapters.dispatch(
                leader_adapter,
                _ctx(leader_adapter, leader, "standard-create"),
                "创建普通副本队伍",
            )
            assert replay_create.code == "PARTY_CREATED"
            assert replay_create.data["party_id"] == party_id
            assert replay_create.data["idempotent_replay"] is True

            # Three confirmed members remain below the four-player minimum.
            for index, (adapter, user) in enumerate(members[1:3], start=1):
                await _invite_and_accept(runtime, leader_adapter, leader, adapter, user, party_id, index)
            for index, (adapter, user) in enumerate(members[:3]):
                confirmed = await runtime.adapters.dispatch(
                    adapter,
                    _ctx(adapter, user, f"confirm:{index}"),
                    f"确认入队 {party_id}",
                )
                assert confirmed.code == "PARTY_CONFIRMED"
            with pytest.raises(PartyBattleRequirementError):
                await runtime.repository.start_party_battle(
                    platform=leader_adapter,
                    platform_user_id=leader,
                    party_id=party_id,
                    operation_id="standard-too-small",
                )

            # Invitations are still accepted while the party is forming; five is the cap.
            for index, (adapter, user) in enumerate(members[3:5], start=3):
                await _invite_and_accept(runtime, leader_adapter, leader, adapter, user, party_id, index)
            too_many = await runtime.adapters.dispatch(
                leader_adapter,
                _ctx(leader_adapter, leader, "invite:6"),
                f"邀请入队 {members[5][0]}:{members[5][1]}",
            )
            assert too_many.code == "PARTY_MEMBER_CAP"

            for index, (adapter, user) in enumerate(members[3:5], start=3):
                confirmed = await runtime.adapters.dispatch(
                    adapter,
                    _ctx(adapter, user, f"confirm:{index}"),
                    f"确认入队 {party_id}",
                )
                assert confirmed.code == ("PARTY_READY" if index == 4 else "PARTY_CONFIRMED")
            profile = await runtime.adapters.dispatch(
                leader_adapter,
                _ctx(leader_adapter, leader),
                "队伍状态",
            )
            assert profile.code == "PARTY_PROFILE"
            assert profile.data["party_type"] == "standard_pve"
            assert profile.data["ready"] is True
            assert len(profile.data["members"]) == 5

            started = await runtime.repository.start_party_battle(
                platform=leader_adapter,
                platform_user_id=leader,
                party_id=party_id,
                operation_id="standard-start",
            )
            replay_start = await runtime.repository.start_party_battle(
                platform=leader_adapter,
                platform_user_id=leader,
                party_id=party_id,
                operation_id="standard-start",
            )
            assert replay_start.battle_id == started.battle_id
            assert replay_start.already_completed is True
            assert len(started.member_player_ids) == 5
            with sqlite3.connect(runtime.settings.database_path) as connection:
                session = connection.execute(
                    "SELECT party_id, battle_type, enemy_key, status, snapshot_json "
                    "FROM party_battle_sessions WHERE battle_id=?",
                    (started.battle_id,),
                ).fetchone()
                snapshot_rows = connection.execute(
                    "SELECT snapshot_json FROM party_battle_members WHERE battle_id=? ORDER BY id",
                    (started.battle_id,),
                ).fetchall()
            assert session[0] == party_id
            assert session[1] == "pve.party"
            assert session[2] == "enemy.wood_rat"
            assert session[3] == "created"
            assert len(json.loads(session[4])["members"]) == 5
            assert len(snapshot_rows) == 5

            settled = await runtime.repository.settle_party_battle(
                platform=leader_adapter,
                platform_user_id=leader,
                battle_id=started.battle_id,
                operation_id="standard-settle",
            )
            assert settled.outcome == "won"
            assert set(settled.rewards) == {"1", "2", "3", "4", "5"}
            settled_replay = await runtime.repository.settle_party_battle(
                platform=leader_adapter,
                platform_user_id=leader,
                battle_id=started.battle_id,
                operation_id="standard-settle",
            )
            assert settled_replay.already_completed is True
            assert settled_replay.rewards == settled.rewards
            with sqlite3.connect(runtime.settings.database_path) as connection:
                battle_count = connection.execute(
                    "SELECT COUNT(*) FROM party_battle_sessions WHERE party_id=?",
                    (party_id,),
                ).fetchone()[0]
                reward_count = connection.execute(
                    "SELECT COUNT(*) FROM party_battle_rewards WHERE battle_id=?",
                    (started.battle_id,),
                ).fetchone()[0]
            assert battle_count == 1
            assert reward_count == 5
            await runtime.close()

    asyncio.run(run())


def test_standard_pve_rejects_unsupported_location_and_keeps_other_party_types_separate() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            adapter, leader, member = "qq.official", "standard-location-leader", "standard-location-member"
            await _create_standard_player(runtime, adapter, leader)
            await _create_standard_player(runtime, "onebot.v11", member)
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE players SET location_key='xuantian.new_town' WHERE platform=? AND platform_user_id=?",
                    (adapter, leader),
                )
                connection.execute(
                    "UPDATE players SET location_key='xuantian.new_town' WHERE platform=? AND platform_user_id=?",
                    ("onebot.v11", member),
                )
            created = await runtime.adapters.dispatch(
                adapter,
                _ctx(adapter, leader, "unsupported-create"),
                "创建多人副本队伍",
            )
            party_id = str(created.data["party_id"])
            await _invite_and_accept(runtime, adapter, leader, "onebot.v11", member, party_id, 1)
            for index, (member_adapter, user) in enumerate(((adapter, leader), ("onebot.v11", member))):
                confirmed = await runtime.adapters.dispatch(
                    member_adapter,
                    _ctx(member_adapter, user, f"unsupported-confirm:{index}"),
                    f"确认入队 {party_id}",
                )
                assert confirmed.code == "PARTY_CONFIRMED"
            with pytest.raises(PartyBattleRequirementError):
                await runtime.repository.start_party_battle(
                    platform=adapter,
                    platform_user_id=leader,
                    party_id=party_id,
                    operation_id="unsupported-start",
                )
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute(
                    "SELECT COUNT(*) FROM party_battle_sessions WHERE party_id=?",
                    (party_id,),
                ).fetchone()[0] == 0

            # The legacy pair entry remains its own type and is not upgraded accidentally.
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE players SET location_key='xuantian.outskirts' WHERE platform=? AND platform_user_id=?",
                    (adapter, leader),
                )
            await runtime.adapters.dispatch(adapter, _ctx(adapter, leader, "leave-unsupported"), "退出队伍")
            pair_created = await runtime.adapters.dispatch(
                adapter,
                _ctx(adapter, leader, "pair-create"),
                "创建双人队伍",
            )
            assert pair_created.data["party_type"] == "exploration_pair"
            await runtime.close()

    asyncio.run(run())
