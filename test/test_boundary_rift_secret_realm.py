from __future__ import annotations

import asyncio
import json
import sqlite3
from combat_fixtures import equip_damage_weapon
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


def _ctx(adapter: str, user: str, operation: str = "") -> CommandContext:
    return CommandContext(adapter=adapter, user_id=user, operation_id=operation)


async def _player(runtime, adapter: str, user: str, *, ticket: int = 0, mainline: bool = True, strong: bool = True) -> None:
    created = await runtime.adapters.dispatch(adapter, _ctx(adapter, user, f"create:{adapter}:{user}"), "开始修仙")
    assert created.code == "PLAYER_CREATED"
    assert (await runtime.adapters.dispatch(adapter, _ctx(adapter, user, f"seek:{adapter}:{user}"), "寻仙问道")).ok
    flags = ["story.mainline.three_realms"] if mainline else []
    inventory = {"item.soul_crystal": ticket} if ticket else {}
    max_hp = 50000 if strong else 1
    initiative = 9999 if strong else 1
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE players SET stage='cultivator', realm_key='nascent_soul', realm_layer=1, "
            "location_key='cave.boundary_realm', stamina=100, stamina_max=100, max_hp=?, "
            "initiative=?, soul_power=10000, intro_json=?, inventory_json=? "
            "WHERE platform=? AND platform_user_id=?",
            (max_hp, initiative, json.dumps({"flags": flags}), json.dumps(inventory), adapter, user),
        )
    if strong:
        equip_damage_weapon(runtime, adapter, user, 1000)


async def _create_party(runtime, leader: tuple[str, str], member: tuple[str, str]) -> str:
    created = await runtime.adapters.dispatch(leader[0], _ctx(*leader, "party-create"), "创建界隙裂隙秘境队伍")
    assert created.code == "PARTY_CREATED"
    party_id = str(created.data["party_id"])
    invited = await runtime.adapters.dispatch(
        leader[0], _ctx(*leader, "party-invite"), f"邀请入队 {member[0]}:{member[1]}"
    )
    assert invited.code == "PARTY_INVITED"
    accepted = await runtime.adapters.dispatch(member[0], _ctx(*member, "party-accept"), f"接受入队 {party_id}")
    assert accepted.code == "PARTY_JOINED"
    for index, identity in enumerate((leader, member)):
        confirmed = await runtime.adapters.dispatch(
            identity[0], _ctx(*identity, f"party-confirm-{index}"), f"确认入队 {party_id}"
        )
        assert confirmed.ok
    return party_id


async def _clear_boundary_rift(
    runtime,
    leader: tuple[str, str],
    member: tuple[str, str],
    operation_prefix: str,
) -> dict[str, object]:
    entered = await runtime.adapters.dispatch(
        leader[0], _ctx(*leader, f"{operation_prefix}:enter"), "进入秘境 界隙裂隙"
    )
    assert entered.code == "BOUNDARY_RIFT_ENTERED"
    assert (await runtime.adapters.dispatch(
        leader[0], _ctx(*leader, f"{operation_prefix}:approach"), "选择秘境节点 裂隙入口"
    )).ok
    assert (await runtime.adapters.dispatch(
        leader[0], _ctx(*leader, f"{operation_prefix}:path"), "选择秘境节点 破碎岔路 内"
    )).ok
    assert (await runtime.adapters.dispatch(
        leader[0], _ctx(*leader, f"{operation_prefix}:sentinel"), "选择秘境节点 跨界哨卫"
    )).code == "BOUNDARY_RIFT_COMBAT_PENDING"
    assert (await runtime.adapters.dispatch(
        member[0], _ctx(*member, f"{operation_prefix}:sentinel-settle"), "结算界隙裂隙秘境"
    )).data["status"] == "routing"
    assert (await runtime.adapters.dispatch(
        leader[0], _ctx(*leader, f"{operation_prefix}:tide"), "选择秘境节点 神魂潮汐"
    )).ok
    assert (await runtime.adapters.dispatch(
        leader[0], _ctx(*leader, f"{operation_prefix}:watcher"), "选择秘境节点 界隙守望者"
    )).code == "BOUNDARY_RIFT_COMBAT_PENDING"
    assert (await runtime.adapters.dispatch(
        member[0], _ctx(*member, f"{operation_prefix}:watcher-settle"), "结算界隙裂隙秘境"
    )).data["current_node"] == "rift_seal"
    assert (await runtime.adapters.dispatch(
        leader[0], _ctx(*leader, f"{operation_prefix}:seal"), "选择秘境节点 裂隙封印"
    )).data["status"] == "cleared"
    settled = await runtime.adapters.dispatch(
        member[0], _ctx(*member, f"{operation_prefix}:settle"), "结算界隙裂隙秘境"
    )
    assert settled.code == "BOUNDARY_RIFT_SETTLED"
    return settled.data


@pytest.mark.parametrize(
    ("leader_adapter", "member_adapter"),
    [("qq.official", "onebot.v11"), ("onebot.v11", "qq.official")],
)
def test_boundary_rift_secret_realm_two_battles_first_clear_and_weekly_limit(leader_adapter, member_adapter) -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            leader = (leader_adapter, f"rift-leader-{leader_adapter}")
            member = (member_adapter, f"rift-member-{leader_adapter}")
            await _player(runtime, *leader, ticket=1)
            await _player(runtime, *member)
            party_id = await _create_party(runtime, leader, member)

            entered = await runtime.adapters.dispatch(leader[0], _ctx(*leader, "rift-enter"), "进入秘境 界隙裂隙")
            assert entered.code == "BOUNDARY_RIFT_ENTERED"
            leave = await runtime.adapters.dispatch(member[0], _ctx(*member, "rift-leave"), "退出队伍")
            assert leave.code == "PARTY_STATE_CONFLICT"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                rows = connection.execute(
                    "SELECT platform_user_id, stamina, inventory_json FROM players WHERE platform_user_id IN (?, ?)",
                    (leader[1], member[1]),
                ).fetchall()
            assert [row[1] for row in rows] == [70, 70]
            assert sum(json.loads(row[2]).get("item.soul_crystal", 0) for row in rows) == 0

            skipped = await runtime.adapters.dispatch(
                leader[0], _ctx(*leader, "rift-skip"), "选择秘境节点 界隙守望者"
            )
            assert skipped.code == "BOUNDARY_RIFT_NODE_FORBIDDEN"
            assert (await runtime.adapters.dispatch(leader[0], _ctx(*leader, "rift-approach"), "选择秘境节点 裂隙入口")).ok
            path = await runtime.adapters.dispatch(leader[0], _ctx(*leader, "rift-path"), "选择秘境节点 破碎岔路 内")
            assert path.data["current_node"] == "cross_realm_sentinel"
            scout = await runtime.adapters.dispatch(leader[0], _ctx(*leader, "rift-scout"), "选择秘境节点 跨界哨卫")
            assert scout.code == "BOUNDARY_RIFT_COMBAT_PENDING"
            scout_battle = scout.data["battle_id"]
            resolved_scout = await runtime.adapters.dispatch(
                member[0], _ctx(*member, "rift-scout-settle"), "结算界隙裂隙秘境"
            )
            assert resolved_scout.code == "BOUNDARY_RIFT_SETTLED"
            assert resolved_scout.data["status"] == "routing"
            assert resolved_scout.data["current_node"] == "soul_current"

            assert (await runtime.adapters.dispatch(leader[0], _ctx(*leader, "rift-tide"), "选择秘境节点 神魂潮汐")).ok
            watcher = await runtime.adapters.dispatch(leader[0], _ctx(*leader, "rift-watcher"), "选择秘境节点 界隙守望者")
            assert watcher.code == "BOUNDARY_RIFT_COMBAT_PENDING"
            watcher_battle = watcher.data["battle_id"]
            completed_battle = await runtime.adapters.dispatch(
                member[0], _ctx(*member, "rift-watcher-settle"), "结算界隙裂隙秘境"
            )
            assert completed_battle.data["current_node"] == "rift_seal"
            assert (await runtime.adapters.dispatch(leader[0], _ctx(*leader, "rift-seal"), "选择秘境节点 裂隙封印")).data["status"] == "cleared"
            settled = await runtime.adapters.dispatch(
                member[0], _ctx(*member, "rift-final"), "结算界隙裂隙秘境"
            )
            assert settled.code == "BOUNDARY_RIFT_SETTLED"
            assert settled.data["status"] == "settled"
            assert len(settled.data["first_clear_members"]) == 2
            replay = await runtime.adapters.dispatch(
                member[0], _ctx(*member, "rift-final"), "结算界隙裂隙秘境"
            )
            assert replay.data["idempotent_replay"] is True

            with sqlite3.connect(runtime.settings.database_path) as connection:
                battles = connection.execute(
                    "SELECT enemy_key FROM party_battle_sessions WHERE party_id=? ORDER BY id",
                    (party_id,),
                ).fetchall()
                party_rewards = connection.execute(
                    "SELECT COUNT(*) FROM party_battle_rewards WHERE battle_id IN (?, ?) AND status='claimed'",
                    (scout_battle, watcher_battle),
                ).fetchone()[0]
                codex_count = connection.execute(
                    "SELECT COUNT(*) FROM codex_entries c JOIN players p ON p.id=c.player_id "
                    "WHERE c.entry_key='codex.route.boundary' AND p.platform_user_id IN (?, ?)",
                    (leader[1], member[1]),
                ).fetchone()[0]
                player_rows = connection.execute(
                    "SELECT platform_user_id, inventory_json, intro_json FROM players "
                    "WHERE platform_user_id IN (?, ?)",
                    (leader[1], member[1]),
                ).fetchall()
            assert [row[0] for row in battles] == ["enemy.cross_realm_sentinel", "enemy.boundary_watcher"]
            assert party_rewards == 0
            assert codex_count == 2
            for user, inventory_json, intro_json in player_rows:
                assert json.loads(inventory_json).get("item.soul_crystal") == 1
                flags = json.loads(intro_json)["flags"]
                assert "story.boundary_rift" in flags

            limited = await runtime.adapters.dispatch(leader[0], _ctx(*leader, "rift-weekly-limit"), "进入秘境 界隙裂隙")
            assert limited.code == "BOUNDARY_RIFT_QUOTA_EXHAUSTED"
            await runtime.close()

    asyncio.run(run())


def test_boundary_rift_secret_realm_rejects_missing_mainline_without_resource_debit() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            leader = ("qq.official", "rift-denied-leader")
            member = ("onebot.v11", "rift-denied-member")
            await _player(runtime, *leader, ticket=1)
            await _player(runtime, *member, mainline=False)
            await _create_party(runtime, leader, member)
            denied = await runtime.adapters.dispatch(leader[0], _ctx(*leader, "rift-denied-enter"), "进入秘境 界隙裂隙")
            assert denied.code == "BOUNDARY_RIFT_REQUIREMENT_MISSING"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                rows = connection.execute(
                    "SELECT stamina, inventory_json FROM players WHERE platform_user_id IN (?, ?) ORDER BY platform_user_id",
                    (leader[1], member[1]),
                ).fetchall()
            assert [row[0] for row in rows] == [100, 100]
            assert json.loads(next(row[1] for row in rows if json.loads(row[1]).get("item.soul_crystal"))) == {"item.soul_crystal": 1}
            await runtime.close()

    asyncio.run(run())


def test_boundary_rift_party_accepts_five_members_and_rejects_sixth() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            identities = [
                ("qq.official", "rift-cap-0"),
                ("onebot.v11", "rift-cap-1"),
                ("qq.official", "rift-cap-2"),
                ("onebot.v11", "rift-cap-3"),
                ("qq.official", "rift-cap-4"),
                ("onebot.v11", "rift-cap-5"),
            ]
            for identity in identities:
                await _player(runtime, *identity)

            leader = identities[0]
            created = await runtime.adapters.dispatch(
                leader[0], _ctx(*leader, "cap-create"), "创建界隙裂隙秘境队伍"
            )
            assert created.code == "PARTY_CREATED"
            party_id = str(created.data["party_id"])
            for index, identity in enumerate(identities[1:5], start=1):
                invited = await runtime.adapters.dispatch(
                    leader[0],
                    _ctx(*leader, f"cap-invite-{index}"),
                    f"邀请入队 {identity[0]}:{identity[1]}",
                )
                assert invited.code == "PARTY_INVITED"
                accepted = await runtime.adapters.dispatch(
                    identity[0], _ctx(*identity, f"cap-accept-{index}"), f"接受入队 {party_id}"
                )
                assert accepted.code == "PARTY_JOINED"

            for index, identity in enumerate(identities[:5]):
                confirmed = await runtime.adapters.dispatch(
                    identity[0], _ctx(*identity, f"cap-confirm-{index}"), f"确认入队 {party_id}"
                )
                assert confirmed.ok
            assert confirmed.data["ready"] is True

            over_capacity = await runtime.adapters.dispatch(
                leader[0],
                _ctx(*leader, "cap-invite-sixth"),
                f"邀请入队 {identities[5][0]}:{identities[5][1]}",
            )
            assert over_capacity.code == "PARTY_MEMBER_CAP"
            await runtime.close()

    asyncio.run(run())


def test_boundary_rift_pending_battle_resumes_after_runtime_restart() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            leader = ("qq.official", "rift-restart-leader")
            member = ("onebot.v11", "rift-restart-member")
            runtime = create_runtime(data_dir=data_dir)
            await _player(runtime, *leader, ticket=1)
            await _player(runtime, *member)
            await _create_party(runtime, leader, member)
            assert (await runtime.adapters.dispatch(leader[0], _ctx(*leader, "restart-enter"), "进入秘境 界隙裂隙")).ok
            assert (await runtime.adapters.dispatch(leader[0], _ctx(*leader, "restart-approach"), "选择秘境节点 裂隙入口")).ok
            assert (await runtime.adapters.dispatch(leader[0], _ctx(*leader, "restart-path"), "选择秘境节点 破碎岔路 外")).ok
            started = await runtime.adapters.dispatch(
                leader[0], _ctx(*leader, "restart-scout"), "选择秘境节点 跨界哨卫"
            )
            assert started.code == "BOUNDARY_RIFT_COMBAT_PENDING"
            battle_id = started.data["battle_id"]
            await runtime.close()

            runtime = create_runtime(data_dir=data_dir)
            resumed = await runtime.adapters.dispatch(
                member[0], _ctx(*member, "restart-settle"), "结算界隙裂隙秘境"
            )
            assert resumed.data["status"] == "routing"
            assert resumed.data["current_node"] == "soul_current"
            replay = await runtime.repository.replay_party_battle(
                platform=leader[0], platform_user_id=leader[1], battle_id=battle_id
            )
            assert replay.status == "settled"
            await runtime.close()

    asyncio.run(run())


def test_boundary_rift_expiry_keeps_cost_and_consumes_weekly_quota() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            leader = ("qq.official", "rift-expire-leader")
            member = ("onebot.v11", "rift-expire-member")
            await _player(runtime, *leader, ticket=1)
            await _player(runtime, *member)
            await _create_party(runtime, leader, member)
            entered = await runtime.adapters.dispatch(leader[0], _ctx(*leader, "expire-enter"), "进入秘境 界隙裂隙")
            run_id = str(entered.data["run_id"])
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE boundary_rift_runs SET expires_at='2000-01-01T00:00:00+00:00' WHERE run_id=?",
                    (run_id,),
                )
            expired = await runtime.adapters.dispatch(
                leader[0], _ctx(*leader, "expire-node"), "选择秘境节点 裂隙入口"
            )
            assert expired.code == "BOUNDARY_RIFT_NOT_READY"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                rows = connection.execute(
                    "SELECT stamina, inventory_json FROM players WHERE platform_user_id IN (?, ?) ORDER BY platform_user_id",
                    (leader[1], member[1]),
                ).fetchall()
                states = connection.execute(
                    "SELECT DISTINCT status FROM boundary_rift_members WHERE run_id=?",
                    (run_id,),
                ).fetchall()
                run_status = connection.execute(
                    "SELECT status FROM boundary_rift_runs WHERE run_id=?", (run_id,)
                ).fetchone()[0]
            assert [row[0] for row in rows] == [70, 70]
            assert sum(json.loads(row[1]).get("item.soul_crystal", 0) for row in rows) == 0
            assert [row[0] for row in states] == ["expired"]
            assert run_status == "expired"
            limited = await runtime.adapters.dispatch(leader[0], _ctx(*leader, "expire-quota"), "进入秘境 界隙裂隙")
            assert limited.code == "BOUNDARY_RIFT_QUOTA_EXHAUSTED"
            await runtime.close()

    asyncio.run(run())


def test_boundary_rift_battle_start_failure_refunds_entry_and_weekly_quota() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            leader = ("qq.official", "rift-refund-leader")
            member = ("onebot.v11", "rift-refund-member")
            await _player(runtime, *leader, ticket=1)
            await _player(runtime, *member)
            await _create_party(runtime, leader, member)
            entered = await runtime.adapters.dispatch(leader[0], _ctx(*leader, "refund-enter"), "进入秘境 界隙裂隙")
            run_id = str(entered.data["run_id"])
            assert (await runtime.adapters.dispatch(leader[0], _ctx(*leader, "refund-approach"), "选择秘境节点 裂隙入口")).ok
            assert (await runtime.adapters.dispatch(leader[0], _ctx(*leader, "refund-path"), "选择秘境节点 破碎岔路 内")).ok
            start_party_battle = runtime.repository.start_party_battle

            async def fail_start(**_kwargs):
                raise RuntimeError("synthetic startup failure")

            runtime.repository.start_party_battle = fail_start
            failed = await runtime.adapters.dispatch(
                leader[0], _ctx(*leader, "refund-scout"), "选择秘境节点 跨界哨卫"
            )
            runtime.repository.start_party_battle = start_party_battle
            assert failed.code == "PERSISTENCE_ERROR"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                rows = connection.execute(
                    "SELECT platform_user_id, stamina, inventory_json FROM players WHERE platform_user_id IN (?, ?)",
                    (leader[1], member[1]),
                ).fetchall()
                result_json = connection.execute(
                    "SELECT result_json FROM boundary_rift_runs WHERE run_id=?", (run_id,)
                ).fetchone()[0]
                quota_keys = connection.execute(
                    "SELECT DISTINCT quota_key FROM boundary_rift_members WHERE run_id=?", (run_id,)
                ).fetchall()
            resources = {row[0]: (row[1], json.loads(row[2])) for row in rows}
            assert all(value[0] == 100 for value in resources.values())
            assert resources[leader[1]][1].get("item.soul_crystal") == 1
            assert json.loads(result_json)["entry_cost_refunded"] is True
            assert len(quota_keys) == 1 and quota_keys[0][0] == f"released:{run_id}"
            retry = await runtime.adapters.dispatch(leader[0], _ctx(*leader, "refund-reenter"), "进入秘境 界隙裂隙")
            assert retry.code == "BOUNDARY_RIFT_ENTERED"
            await runtime.close()

    asyncio.run(run())


def test_boundary_rift_real_battle_loss_keeps_entry_cost_and_applies_fatigue() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            leader = ("qq.official", "rift-loss-leader")
            member = ("onebot.v11", "rift-loss-member")
            await _player(runtime, *leader, ticket=1, strong=False)
            await _player(runtime, *member, strong=False)
            await _create_party(runtime, leader, member)
            assert (await runtime.adapters.dispatch(leader[0], _ctx(*leader, "loss-enter"), "进入秘境 界隙裂隙")).ok
            assert (await runtime.adapters.dispatch(leader[0], _ctx(*leader, "loss-approach"), "选择秘境节点 裂隙入口")).ok
            assert (await runtime.adapters.dispatch(leader[0], _ctx(*leader, "loss-path"), "选择秘境节点 破碎岔路 外")).ok
            assert (await runtime.adapters.dispatch(leader[0], _ctx(*leader, "loss-scout"), "选择秘境节点 跨界哨卫")).code == "BOUNDARY_RIFT_COMBAT_PENDING"
            scout = await runtime.adapters.dispatch(
                member[0], _ctx(*member, "loss-settle"), "结算界隙裂隙秘境"
            )
            assert scout.data["status"] == "routing"
            assert (await runtime.adapters.dispatch(leader[0], _ctx(*leader, "loss-tide"), "选择秘境节点 神魂潮汐")).ok
            assert (await runtime.adapters.dispatch(leader[0], _ctx(*leader, "loss-watcher"), "选择秘境节点 界隙守望者")).code == "BOUNDARY_RIFT_COMBAT_PENDING"
            result = await runtime.adapters.dispatch(
                member[0], _ctx(*member, "loss-final-settle"), "结算界隙裂隙秘境"
            )
            assert result.data["status"] == "failed"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                rows = connection.execute(
                    "SELECT stamina, inventory_json, soul_fatigue_until FROM players WHERE platform_user_id IN (?, ?)",
                    (leader[1], member[1]),
                ).fetchall()
            assert all(row[0] == 70 for row in rows)
            assert all(row[2] for row in rows)
            assert json.loads(next(row[1] for row in rows if json.loads(row[1]).get("item.soul_crystal", 0) == 0)).get("item.soul_crystal", 0) == 0
            limited = await runtime.adapters.dispatch(leader[0], _ctx(*leader, "loss-quota"), "进入秘境 界隙裂隙")
            assert limited.code == "BOUNDARY_RIFT_QUOTA_EXHAUSTED"
            await runtime.close()

    asyncio.run(run())


def test_boundary_rift_repeat_clear_after_next_utc_week_has_no_first_clear_rewards() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            clock = MutableClock(datetime(2026, 9, 28, tzinfo=timezone.utc))
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            leader = ("qq.official", "rift-repeat-leader")
            member = ("onebot.v11", "rift-repeat-member")
            await _player(runtime, *leader, ticket=1)
            await _player(runtime, *member)
            await _create_party(runtime, leader, member)

            first = await _clear_boundary_rift(runtime, leader, member, "repeat-first")
            assert len(first["first_clear_members"]) == 2
            clock.advance(days=7)
            repeated = await _clear_boundary_rift(runtime, leader, member, "repeat-second")
            assert repeated["first_clear_members"] == []
            assert repeated["rewards"]

            with sqlite3.connect(runtime.settings.database_path) as connection:
                codex_count = connection.execute(
                    "SELECT COUNT(*) FROM codex_entries c JOIN players p ON p.id=c.player_id "
                    "WHERE c.entry_key='codex.route.boundary' AND p.platform_user_id IN (?, ?)",
                    (leader[1], member[1]),
                ).fetchone()[0]
                player_rows = connection.execute(
                    "SELECT platform_user_id, inventory_json, intro_json FROM players "
                    "WHERE platform_user_id IN (?, ?)",
                    (leader[1], member[1]),
                ).fetchall()
            assert codex_count == 2
            inventory = {row[0]: json.loads(row[1]) for row in player_rows}
            assert inventory[leader[1]].get("item.soul_crystal") == 1
            assert inventory[member[1]].get("item.soul_crystal") == 2
            for _, _, intro_json in player_rows:
                assert "story.boundary_rift" in json.loads(intro_json)["flags"]
            await runtime.close()

    asyncio.run(run())
