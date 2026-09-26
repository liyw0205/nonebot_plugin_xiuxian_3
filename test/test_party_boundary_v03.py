from __future__ import annotations

import asyncio
import json
import sqlite3
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.repository import (
    BoundaryRealmRequirementError,
)


def _ctx(adapter: str, user: str, operation: str = "") -> CommandContext:
    return CommandContext(adapter=adapter, user_id=user, operation_id=operation)


async def _player(runtime, adapter: str, user: str, *, strong: bool = True, ticket: int = 0) -> None:
    created = await runtime.adapters.dispatch(adapter, _ctx(adapter, user, f"create:{adapter}:{user}"), "开始修仙")
    assert created.code == "PLAYER_CREATED"
    qualification = {"body": 2_000, "agility": 2_000} if strong else {"body": 1, "agility": 1}
    intro = {"flags": ["story.mainline.three_realms"]}
    inventory = {"item.soul_crystal": ticket} if ticket else {}
    with sqlite3.connect(runtime.settings.database_path) as db:
        db.execute(
            "UPDATE players SET stage='cultivator', realm_key='nascent_soul', realm_layer=1, "
            "location_key='cave.boundary_realm', stamina=30, max_hp=?, initiative=99, soul_power=10000, "
            "qualification_json=?, intro_json=?, inventory_json=? WHERE platform=? AND platform_user_id=?",
            (50000 if strong else 1, json.dumps(qualification), json.dumps(intro), json.dumps(inventory), adapter, user),
        )


def test_boundary_party_qq_onebot_three_members_is_atomic_and_unique() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            members = (("qq.official", "boundary-leader"), ("onebot.v11", "boundary-two"), ("qq.official", "boundary-three"))
            for index, (adapter, user) in enumerate(members):
                await _player(runtime, adapter, user, ticket=1 if index == 0 else 0)

            created = await runtime.adapters.dispatch(members[0][0], _ctx(members[0][0], members[0][1], "boundary-create"), "创建界隙队伍")
            assert created.code == "PARTY_CREATED"
            party_id = str(created.data["party_id"])
            for index, (adapter, user) in enumerate(members[1:], start=1):
                invited = await runtime.adapters.dispatch(
                    members[0][0], _ctx(members[0][0], members[0][1], f"boundary-invite-{index}"),
                    f"邀请入队 {adapter}:{user}",
                )
                assert invited.code == "PARTY_INVITED"
                accepted = await runtime.adapters.dispatch(adapter, _ctx(adapter, user, f"boundary-accept-{index}"), f"接受入队 {party_id}")
                assert accepted.code == "PARTY_JOINED"
            for index, (adapter, user) in enumerate(members):
                confirmed = await runtime.adapters.dispatch(adapter, _ctx(adapter, user, f"boundary-confirm-{index}"), f"确认入队 {party_id}")
                assert confirmed.ok
            profile = await runtime.adapters.dispatch(members[0][0], _ctx(members[0][0], members[0][1]), "队伍状态")
            assert profile.code == "PARTY_PROFILE"
            assert profile.data["ready"] is True
            assert len(profile.data["members"]) == 3

            started = await runtime.repository.start_party_battle(
                platform=members[0][0], platform_user_id=members[0][1], party_id=party_id, operation_id="boundary-start"
            )
            assert started.enemy_key == "enemy.boundary_watcher"
            assert len(started.member_player_ids) == 3
            with sqlite3.connect(runtime.settings.database_path) as db:
                state = db.execute(
                    "SELECT stamina, inventory_json FROM players WHERE platform=? AND platform_user_id=?",
                    members[0],
                ).fetchone()
                stamina = db.execute(
                    "SELECT stamina FROM players WHERE platform_user_id IN (?, ?) ORDER BY platform_user_id",
                    (members[1][1], members[2][1]),
                ).fetchall()
                snapshot = json.loads(db.execute("SELECT snapshot_json FROM party_battle_sessions WHERE battle_id=?", (started.battle_id,)).fetchone()[0])
            assert state[0] == 0 and state[1] == "{}"
            assert [row[0] for row in stamina] == [0, 0]
            assert len(snapshot["members"]) == 3
            assert all("cross_realm" in member for member in snapshot["members"])

            resolved = await runtime.repository.settle_party_battle(
                platform=members[0][0], platform_user_id=members[0][1], battle_id=started.battle_id, operation_id="boundary-resolve"
            )
            assert resolved.outcome == "won"
            assert set(resolved.rewards) == {"1", "2", "3"}
            assert len(resolved.contributions) == 3
            assert len(resolved.reward_order) == 3
            assert set(resolved.reward_rolls) == set(resolved.contributions)
            with sqlite3.connect(runtime.settings.database_path) as db:
                rewards = db.execute("SELECT COUNT(*) FROM party_battle_rewards WHERE battle_id=?", (started.battle_id,)).fetchone()[0]
                crystals = db.execute(
                    "SELECT inventory_json FROM players WHERE platform_user_id IN (?, ?, ?) ORDER BY platform_user_id",
                    (members[0][1], members[1][1], members[2][1]),
                ).fetchall()
            assert rewards == 3
            assert all(json.loads(row[0]).get("item.soul_crystal") == 1 for row in crystals)
            await runtime.close()

    asyncio.run(run())


def test_boundary_requirement_failure_does_not_debit_and_loss_applies_soul_fatigue() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            await _player(runtime, "qq.official", "boundary-bad-leader", strong=False, ticket=1)
            await _player(runtime, "onebot.v11", "boundary-bad-member", strong=False)
            with sqlite3.connect(runtime.settings.database_path) as db:
                db.execute("UPDATE players SET realm_key='golden_core', realm_layer=10 WHERE platform_user_id=?", ("boundary-bad-member",))
            created = await runtime.adapters.dispatch("qq.official", _ctx("qq.official", "boundary-bad-leader", "bad-create"), "创建界隙队伍")
            party_id = str(created.data["party_id"])
            await runtime.adapters.dispatch("qq.official", _ctx("qq.official", "boundary-bad-leader", "bad-invite"), "邀请入队 onebot.v11:boundary-bad-member")
            await runtime.adapters.dispatch("onebot.v11", _ctx("onebot.v11", "boundary-bad-member", "bad-accept"), f"接受入队 {party_id}")
            for index, (adapter, user) in enumerate((("qq.official", "boundary-bad-leader"), ("onebot.v11", "boundary-bad-member"))):
                await runtime.adapters.dispatch(adapter, _ctx(adapter, user, f"bad-confirm-{index}"), f"确认入队 {party_id}")
            try:
                await runtime.repository.start_party_battle(
                    platform="qq.official", platform_user_id="boundary-bad-leader", party_id=party_id, operation_id="bad-start"
                )
            except BoundaryRealmRequirementError:
                pass
            else:
                raise AssertionError("invalid boundary member was accepted")
            with sqlite3.connect(runtime.settings.database_path) as db:
                row = db.execute(
                    "SELECT stamina, inventory_json FROM players WHERE platform=? AND platform_user_id=?",
                    ("qq.official", "boundary-bad-leader"),
                ).fetchone()
            assert row[0] == 30 and json.loads(row[1]).get("item.soul_crystal") == 1
            await runtime.close()

    asyncio.run(run())


def test_boundary_battle_loss_applies_soul_fatigue_after_one_revival_per_member_and_releases_locks() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            await _player(runtime, "qq.official", "boundary-loss-leader", strong=False, ticket=1)
            await _player(runtime, "onebot.v11", "boundary-loss-member", strong=False)
            created = await runtime.adapters.dispatch("qq.official", _ctx("qq.official", "boundary-loss-leader", "loss-create"), "创建界隙队伍")
            party_id = str(created.data["party_id"])
            await runtime.adapters.dispatch("qq.official", _ctx("qq.official", "boundary-loss-leader", "loss-invite"), "邀请入队 onebot.v11:boundary-loss-member")
            await runtime.adapters.dispatch("onebot.v11", _ctx("onebot.v11", "boundary-loss-member", "loss-accept"), f"接受入队 {party_id}")
            for index, (adapter, user) in enumerate((("qq.official", "boundary-loss-leader"), ("onebot.v11", "boundary-loss-member"))):
                await runtime.adapters.dispatch(adapter, _ctx(adapter, user, f"loss-confirm-{index}"), f"确认入队 {party_id}")
            started = await runtime.repository.start_party_battle(
                platform="qq.official", platform_user_id="boundary-loss-leader", party_id=party_id, operation_id="loss-start"
            )
            result = await runtime.repository.settle_party_battle(
                platform="onebot.v11", platform_user_id="boundary-loss-member", battle_id=started.battle_id, operation_id="loss-resolve"
            )
            assert result.outcome == "lost"
            replay = await runtime.repository.replay_party_battle(
                platform="qq.official", platform_user_id="boundary-loss-leader", battle_id=started.battle_id
            )
            revivals = [action for action in replay.actions if action["skill_key"] == "skill.soul.revival"]
            assert 1 <= len(revivals) <= 2
            assert len({action["target_key"] for action in revivals}) == len(revivals)
            assert all('"soul_power_cost": 25' in action["state_json"] for action in revivals)
            timeline_impacts = sum(action["skill_key"] == "skill.soul.suppression" for action in replay.actions)
            with sqlite3.connect(runtime.settings.database_path) as db:
                rows = db.execute(
                    "SELECT soul_power, soul_fatigue_until FROM players WHERE platform_user_id IN (?, ?) ORDER BY platform_user_id",
                    ("boundary-loss-leader", "boundary-loss-member"),
                ).fetchall()
                locked = db.execute(
                    "SELECT COUNT(*) FROM party_battle_members WHERE battle_id=? AND asset_lock_status='locked'",
                    (started.battle_id,),
                ).fetchone()[0]
            assert sum(row[0] for row in rows) == 16000 - 25 * len(revivals) - 20 * timeline_impacts
            assert all(row[1] for row in rows)
            assert locked == 0
            await runtime.close()

    asyncio.run(run())


def test_boundary_battle_without_revival_ends_and_fatigue_is_idempotent() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            await _player(runtime, "qq.official", "boundary-no-revive-leader", strong=False, ticket=1)
            await _player(runtime, "onebot.v11", "boundary-no-revive-member", strong=False)
            with sqlite3.connect(runtime.settings.database_path) as db:
                db.execute(
                    "UPDATE players SET soul_power=1 WHERE platform_user_id IN (?, ?)",
                    ("boundary-no-revive-leader", "boundary-no-revive-member"),
                )
            created = await runtime.adapters.dispatch(
                "qq.official",
                _ctx("qq.official", "boundary-no-revive-leader", "no-revive-create"),
                "创建界隙队伍",
            )
            party_id = str(created.data["party_id"])
            await runtime.adapters.dispatch(
                "qq.official",
                _ctx("qq.official", "boundary-no-revive-leader", "no-revive-invite"),
                "邀请入队 onebot.v11:boundary-no-revive-member",
            )
            await runtime.adapters.dispatch(
                "onebot.v11",
                _ctx("onebot.v11", "boundary-no-revive-member", "no-revive-accept"),
                f"接受入队 {party_id}",
            )
            for index, (adapter, user) in enumerate(
                (("qq.official", "boundary-no-revive-leader"), ("onebot.v11", "boundary-no-revive-member"))
            ):
                await runtime.adapters.dispatch(
                    adapter,
                    _ctx(adapter, user, f"no-revive-confirm-{index}"),
                    f"确认入队 {party_id}",
                )
            started = await runtime.repository.start_party_battle(
                platform="qq.official",
                platform_user_id="boundary-no-revive-leader",
                party_id=party_id,
                operation_id="no-revive-start",
            )
            resolved = await runtime.repository.settle_party_battle(
                platform="onebot.v11",
                platform_user_id="boundary-no-revive-member",
                battle_id=started.battle_id,
                operation_id="no-revive-resolve",
            )
            replay = await runtime.repository.replay_party_battle(
                platform="qq.official",
                platform_user_id="boundary-no-revive-leader",
                battle_id=started.battle_id,
            )
            assert resolved.outcome == "lost"
            assert not any(action["skill_key"] == "skill.soul.revival" for action in replay.actions)
            repeated = await runtime.repository.settle_party_battle(
                platform="qq.official",
                platform_user_id="boundary-no-revive-leader",
                battle_id=started.battle_id,
                operation_id="no-revive-resolve-replay",
            )
            assert repeated.rewards == resolved.rewards
            with sqlite3.connect(runtime.settings.database_path) as db:
                rows = db.execute(
                    "SELECT soul_power, soul_fatigue_until FROM players WHERE platform_user_id IN (?, ?) ORDER BY platform_user_id",
                    ("boundary-no-revive-leader", "boundary-no-revive-member"),
                ).fetchall()
                reward_count = db.execute(
                    "SELECT COUNT(*) FROM party_battle_rewards WHERE battle_id=?", (started.battle_id,)
                ).fetchone()[0]
            assert [row[0] for row in rows] == [0, 0]
            assert all(row[1] for row in rows)
            assert reward_count == 2
            await runtime.close()

    asyncio.run(run())
