from __future__ import annotations

import asyncio
import json
import sqlite3
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime


def _context(adapter: str, user: str, operation_id: str) -> CommandContext:
    return CommandContext(adapter=adapter, user_id=user, operation_id=operation_id)


def test_qq_onebot_party_pve_uses_team_snapshot_locks_and_unique_rewards() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            leader_adapter, leader = "qq.official", "party-leader"
            helper_adapter, helper = "onebot.v11", "party-helper"
            for adapter, user in ((leader_adapter, leader), (helper_adapter, helper)):
                created = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, f"{adapter}-create"),
                    "开始修仙",
                )
                assert created.code == "PLAYER_CREATED"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE players SET stage='cultivator', realm_key='qi_sensing', realm_layer=2, "
                        "location_key='xuantian.outskirts', stamina=100, max_hp=999, initiative=99, "
                        "qualification_json=? WHERE platform=? AND platform_user_id=?",
                        (json.dumps({"body": 2_000, "agility": 2_000}), adapter, user),
                    )

            created_party = await runtime.adapters.dispatch(
                leader_adapter,
                _context(leader_adapter, leader, "party-create"),
                "创建双人队伍",
            )
            assert created_party.code == "PARTY_CREATED"
            party_id = str(created_party.data["party_id"])
            assert (
                await runtime.adapters.dispatch(
                    leader_adapter,
                    _context(leader_adapter, leader, "party-invite"),
                    f"邀请入队 {helper_adapter}:{helper}",
                )
            ).code == "PARTY_INVITED"
            assert (
                await runtime.adapters.dispatch(
                    helper_adapter,
                    _context(helper_adapter, helper, "party-accept"),
                    f"接受入队 {party_id}",
                )
            ).code == "PARTY_JOINED"
            assert (
                await runtime.adapters.dispatch(
                    leader_adapter,
                    _context(leader_adapter, leader, "party-confirm-leader"),
                    f"确认入队 {party_id}",
                )
            ).code == "PARTY_CONFIRMED"
            ready = await runtime.adapters.dispatch(
                helper_adapter,
                _context(helper_adapter, helper, "party-confirm-helper"),
                f"确认入队 {party_id}",
            )
            assert ready.code == "PARTY_READY"

            denied = await runtime.adapters.dispatch(
                helper_adapter,
                _context(helper_adapter, helper, "party-helper-start"),
                "开始队伍战斗",
            )
            assert denied.code == "PARTY_BATTLE_PERMISSION_DENIED"

            started = await runtime.repository.start_party_battle(
                platform=leader_adapter,
                platform_user_id=leader,
                party_id=party_id,
                operation_id="party-battle-start",
            )
            assert started.member_player_ids
            with sqlite3.connect(runtime.settings.database_path) as connection:
                locked = connection.execute(
                    "SELECT COUNT(*) FROM party_battle_members WHERE battle_id=? AND asset_lock_status='locked'",
                    (started.battle_id,),
                ).fetchone()[0]
                snapshots = connection.execute(
                    "SELECT snapshot_json FROM party_battle_members WHERE battle_id=? ORDER BY id",
                    (started.battle_id,),
                ).fetchall()
            assert locked == 2
            assert {json.loads(row[0])["player_id"] for row in snapshots} == set(started.member_player_ids)

            cultivation_locked = await runtime.adapters.dispatch(
                helper_adapter,
                _context(helper_adapter, helper, "party-battle-cultivation-locked"),
                "开始修炼",
            )
            assert cultivation_locked.code == "CULTIVATION_BUSY"
            leave_locked = await runtime.adapters.dispatch(
                leader_adapter,
                _context(leader_adapter, leader, "party-battle-leave-locked"),
                "退出队伍",
            )
            assert leave_locked.code == "PARTY_STATE_CONFLICT"

            settled_by_helper = await runtime.adapters.dispatch(
                helper_adapter,
                _context(helper_adapter, helper, "party-battle-helper-settle"),
                f"结算队伍战斗 {started.battle_id}",
            )
            assert settled_by_helper.code == "PARTY_BATTLE_SETTLED"
            assert settled_by_helper.data["outcome"] == "won"
            assert set(settled_by_helper.data["rewards"]) == {"1", "2"}

            before_replay = settled_by_helper.data["rewards"]
            settled_again = await runtime.adapters.dispatch(
                leader_adapter,
                _context(leader_adapter, leader, "party-battle-leader-replay"),
                f"结算队伍战斗 {started.battle_id}",
            )
            assert settled_again.code == "PARTY_BATTLE_SETTLED"
            assert settled_again.data["rewards"] == before_replay

            replay = await runtime.adapters.dispatch(
                leader_adapter,
                _context(leader_adapter, leader, "party-battle-replay"),
                f"队伍战斗回放 {started.battle_id}",
            )
            assert replay.code == "PARTY_BATTLE_REPLAY"
            assert replay.data["actions"]

            with sqlite3.connect(runtime.settings.database_path) as connection:
                reward_count = connection.execute(
                    "SELECT COUNT(*) FROM party_battle_rewards WHERE battle_id=?",
                    (started.battle_id,),
                ).fetchone()[0]
                remaining_locks = connection.execute(
                    "SELECT COUNT(*) FROM party_battle_members WHERE battle_id=? AND asset_lock_status='locked'",
                    (started.battle_id,),
                ).fetchone()[0]
                player_assets = connection.execute(
                    "SELECT platform, cultivation, spirit_stones FROM players WHERE platform_user_id IN (?, ?) ORDER BY platform_user_id",
                    (leader, helper),
                ).fetchall()
            assert reward_count == 2
            assert remaining_locks == 0
            assert all(int(row[1]) == 30 and int(row[2]) == 10 for row in player_assets)
            await runtime.close()

            recovered = create_runtime(data_dir=data_dir)
            replay_after_restart = await recovered.adapters.dispatch(
                helper_adapter,
                _context(helper_adapter, helper, "party-battle-replay-restart"),
                f"队伍战斗回放 {started.battle_id}",
            )
            assert replay_after_restart.code == "PARTY_BATTLE_REPLAY"
            await recovered.close()

    asyncio.run(run())
