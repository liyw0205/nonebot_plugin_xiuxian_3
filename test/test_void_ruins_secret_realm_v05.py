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


async def _player(runtime, adapter: str, user: str, *, strong: bool = True, unstable_until: str | None = None) -> None:
    created = await runtime.adapters.dispatch(adapter, _ctx(adapter, user, f"{user}:create"), "开始修仙")
    assert created.code == "PLAYER_CREATED"
    body = 100_000 if strong else 0
    max_hp = 2_000_000 if strong else 1
    initiative = 9_999 if strong else 0
    agility = 9_999 if strong else 0
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE players SET realm_key='void_refining', realm_layer=1, location_key='void.archive_ruins', "
            "stamina=100, stamina_max=100, max_hp=?, initiative=?, qualification_json=?, inventory_json=?, "
            "void_instability_until=? WHERE platform=? AND platform_user_id=?",
            (
                max_hp, initiative, json.dumps({"body": body, "agility": agility}),
                json.dumps({"item.void_anchor": 1}), unstable_until, adapter, user,
            ),
        )


async def _party(runtime, leader: tuple[str, str], member: tuple[str, str]) -> str:
    created = await runtime.adapters.dispatch(
        leader[0], _ctx(*leader, "party:create"), "创建虚空遗迹秘境队伍"
    )
    assert created.code == "PARTY_CREATED"
    party_id = str(created.data["party_id"])
    invited = await runtime.adapters.dispatch(
        leader[0], _ctx(*leader, "party:invite"), f"邀请入队 {member[0]}:{member[1]}"
    )
    assert invited.code == "PARTY_INVITED"
    accepted = await runtime.adapters.dispatch(
        member[0], _ctx(*member, "party:accept"), f"接受入队 {party_id}"
    )
    assert accepted.code == "PARTY_JOINED"
    for index, identity in enumerate((leader, member)):
        confirmed = await runtime.adapters.dispatch(
            identity[0], _ctx(*identity, f"party:confirm:{index}"), f"确认入队 {party_id}"
        )
        assert confirmed.ok
    return party_id


async def _choose(runtime, identity: tuple[str, str], operation: str, node: str):
    return await runtime.adapters.dispatch(
        identity[0], _ctx(*identity, operation), f"选择秘境节点 {node}"
    )


async def _clear(runtime, leader: tuple[str, str], member: tuple[str, str], prefix: str):
    entered = await runtime.adapters.dispatch(
        leader[0], _ctx(*leader, f"{prefix}:enter"), "进入秘境 虚空遗迹"
    )
    assert entered.code == "VOID_RUINS_ENTERED", entered
    for index, node in enumerate(("遗迹入口", "破碎信标", "虚空回廊")):
        selected = await _choose(runtime, leader, f"{prefix}:node:{index}", node)
        assert selected.code == "VOID_RUINS_NODE_SELECTED", selected
    sentinel = await _choose(runtime, leader, f"{prefix}:sentinel", "裂隙哨卫")
    assert sentinel.code == "VOID_RUINS_COMBAT_PENDING", sentinel
    first_battle = sentinel.data["battle_id"]
    first_result = await runtime.adapters.dispatch(
        member[0], _ctx(*member, f"{prefix}:sentinel:settle"), "结算秘境"
    )
    assert first_result.code == "VOID_RUINS_BATTLE_SETTLED", first_result
    assert first_result.data["current_node"] == "archive_fringe"

    for index, node in enumerate(("档案外围", "虚空风暴", "锚点原野"), start=4):
        selected = await _choose(runtime, leader, f"{prefix}:node:{index}", node)
        assert selected.code == "VOID_RUINS_NODE_SELECTED", selected
    keeper = await _choose(runtime, leader, f"{prefix}:keeper", "档案守卫")
    assert keeper.code == "VOID_RUINS_COMBAT_PENDING", keeper
    second_battle = keeper.data["battle_id"]
    second_result = await runtime.adapters.dispatch(
        member[0], _ctx(*member, f"{prefix}:keeper:settle"), "结算秘境"
    )
    assert second_result.code == "VOID_RUINS_BATTLE_SETTLED", second_result
    assert second_result.data["current_node"] == "route_tablet"
    for index, node in enumerate(("航道石碑", "归航之门"), start=8):
        selected = await _choose(runtime, leader, f"{prefix}:node:{index}", node)
    assert selected.code == "VOID_RUINS_ROUTE_CLEARED", selected
    settled = await runtime.adapters.dispatch(
        member[0], _ctx(*member, f"{prefix}:finish"), "结算秘境"
    )
    assert settled.code == "VOID_RUINS_SETTLED", settled
    return entered, settled, (first_battle, second_battle)


@pytest.mark.parametrize(
    ("leader_adapter", "member_adapter"),
    [("qq.official", "onebot.v11"), ("onebot.v11", "qq.official")],
)
def test_void_ruins_full_route_handoff_restart_and_first_clear(leader_adapter, member_adapter) -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 28, 12, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            leader = (leader_adapter, f"void-leader-{leader_adapter}")
            member = (member_adapter, f"void-member-{leader_adapter}")
            unstable_until = (clock.now + timedelta(hours=1)).isoformat()
            await _player(runtime, *leader)
            await _player(runtime, *member, unstable_until=unstable_until)
            party_id = await _party(runtime, leader, member)

            entered = await runtime.adapters.dispatch(
                leader[0], _ctx(*leader, "void:first:enter"), "进入秘境 虚空遗迹"
            )
            assert entered.code == "VOID_RUINS_ENTERED"
            replay = await runtime.adapters.dispatch(
                leader[0], _ctx(*leader, "void:first:enter"), "进入秘境 虚空遗迹"
            )
            assert replay.data["idempotent_replay"] is True
            skipped = await _choose(runtime, leader, "void:skip", "裂隙哨卫")
            assert skipped.code == "VOID_RUINS_NODE_FORBIDDEN"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE players SET void_instability_until='2000-01-01T00:00:00+00:00' "
                    "WHERE platform=? AND platform_user_id=?",
                    (member[0], member[1]),
                )
            for index, node in enumerate(("遗迹入口", "破碎信标", "虚空回廊")):
                assert (await _choose(runtime, leader, f"void:node:{index}", node)).ok
            sentinel = await _choose(runtime, leader, "void:sentinel", "裂隙哨卫")
            assert sentinel.code == "VOID_RUINS_COMBAT_PENDING"
            sentinel_battle = sentinel.data["battle_id"]
            with sqlite3.connect(runtime.settings.database_path) as connection:
                frozen_enemy = connection.execute(
                    "SELECT enemy_key FROM party_battle_sessions WHERE battle_id=?", (sentinel_battle,)
                ).fetchone()[0]
            assert frozen_enemy == "enemy.void_ruins_sentinel_unstable"
            await runtime.close()

            runtime = create_runtime(data_dir=data_dir, clock=clock)
            resumed = await runtime.adapters.dispatch(
                member[0], _ctx(*member, "void:sentinel:resume"), "结算秘境"
            )
            assert resumed.code == "VOID_RUINS_BATTLE_SETTLED", resumed
            assert resumed.data["current_node"] == "archive_fringe"
            # Resume the same frozen run using the public route, while the other adapter owns the leader.
            for index, node in enumerate(("档案外围", "虚空风暴", "锚点原野"), start=4):
                assert (await _choose(runtime, leader, f"void:node:{index}", node)).ok
            keeper = await _choose(runtime, leader, "void:keeper", "档案守卫")
            assert keeper.code == "VOID_RUINS_COMBAT_PENDING"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                frozen_keeper = connection.execute(
                    "SELECT enemy_key FROM party_battle_sessions WHERE battle_id=?", (keeper.data["battle_id"],)
                ).fetchone()[0]
            assert frozen_keeper == "enemy.void_ruins_keeper_unstable"
            keeper_result = await runtime.adapters.dispatch(
                member[0], _ctx(*member, "void:keeper:settle"), "结算秘境"
            )
            assert keeper_result.data["current_node"] == "route_tablet"
            assert (await _choose(runtime, leader, "void:node:8", "航道石碑")).ok
            assert (await _choose(runtime, leader, "void:node:9", "归航之门")).data["status"] == "cleared"
            settled = await runtime.adapters.dispatch(
                member[0], _ctx(*member, "void:finish"), "结算秘境"
            )
            assert settled.code == "VOID_RUINS_SETTLED", settled
            with sqlite3.connect(runtime.settings.database_path) as connection:
                stable_ids = {
                    row[0] for row in connection.execute(
                        "SELECT player_id FROM players WHERE platform_user_id IN (?, ?)",
                        (leader[1], member[1]),
                    ).fetchall()
                }
            assert set(settled.data["first_clear_members"]) == stable_ids
            replay_settlement = await runtime.adapters.dispatch(
                member[0], _ctx(*member, "void:finish"), "结算秘境"
            )
            assert replay_settlement.data["idempotent_replay"] is True

            with sqlite3.connect(runtime.settings.database_path) as connection:
                runs = connection.execute(
                    "SELECT status, content_version, rule_version FROM void_ruins_runs WHERE party_id=?",
                    (party_id,),
                ).fetchall()
                battles = connection.execute(
                    "SELECT enemy_key, rule_version FROM party_battle_sessions WHERE party_id=? ORDER BY id",
                    (party_id,),
                ).fetchall()
                claimed = connection.execute(
                    "SELECT COUNT(*) FROM party_battle_rewards WHERE party_id=? AND status='claimed'", (party_id,)
                ).fetchone()[0]
                players = connection.execute(
                    "SELECT platform_user_id, stamina, inventory_json, intro_json FROM players "
                    "WHERE platform_user_id IN (?, ?) ORDER BY platform_user_id",
                    (leader[1], member[1]),
                ).fetchall()
                codex_count = connection.execute(
                    "SELECT COUNT(*) FROM codex_entries c JOIN players p ON p.id=c.player_id "
                    "WHERE c.entry_key='codex.void.route_ruins' AND p.platform_user_id IN (?, ?)",
                    (leader[1], member[1]),
                ).fetchone()[0]
            assert runs == [("settled", "", "")]
            assert [battle[0] for battle in battles] == [
                "enemy.void_ruins_sentinel_unstable", "enemy.void_ruins_keeper_unstable"
            ]
            assert all(battle[1] == "" for battle in battles)
            assert claimed == 0
            assert codex_count == 2
            for user, stamina, inventory_json, intro_json in players:
                inventory = json.loads(inventory_json)
                flags = json.loads(intro_json)["flags"]
                assert stamina == (50 if user == leader[1] else 100)
                assert inventory.get("item.void_anchor") == 1
                assert inventory.get("item.void_crystal") == 1
                assert "access.void.time_fort" in flags

            quota = await runtime.adapters.dispatch(
                leader[0], _ctx(*leader, "void:weekly"), "进入秘境 虚空遗迹"
            )
            assert quota.code == "VOID_RUINS_QUOTA_EXHAUSTED"
            clock.advance(days=7)
            repeat = await _clear(runtime, leader, member, "void:repeat")
            assert repeat[1].data["first_clear_members"] == []
            with sqlite3.connect(runtime.settings.database_path) as connection:
                repeat_inventory = connection.execute(
                    "SELECT inventory_json FROM players WHERE platform_user_id=?", (leader[1],)
                ).fetchone()[0]
            assert json.loads(repeat_inventory).get("item.void_crystal") == 2
            await runtime.close()

    asyncio.run(run())


def test_void_ruins_requirement_is_atomic_and_start_failure_compensates() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            leader = ("qq.official", "void-compensate-leader")
            member = ("onebot.v11", "void-compensate-member")
            await _player(runtime, *leader)
            await _player(runtime, *member)
            await _party(runtime, leader, member)
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE players SET inventory_json='{}' WHERE platform=? AND platform_user_id=?",
                    member,
                )
            denied = await runtime.adapters.dispatch(
                leader[0], _ctx(*leader, "void:missing-anchor"), "进入秘境 虚空遗迹"
            )
            assert denied.code == "VOID_RUINS_REQUIREMENT_MISSING"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute(
                    "SELECT stamina FROM players WHERE platform=? AND platform_user_id=?", leader
                ).fetchone()[0] == 100
                assert connection.execute("SELECT COUNT(*) FROM void_ruins_runs").fetchone()[0] == 0
                connection.execute(
                    "UPDATE players SET inventory_json=? WHERE platform=? AND platform_user_id=?",
                    (json.dumps({"item.void_anchor": 1}), *member),
                )

            entered = await runtime.adapters.dispatch(
                leader[0], _ctx(*leader, "void:comp:enter"), "进入秘境 虚空遗迹"
            )
            for index, node in enumerate(("遗迹入口", "破碎信标", "虚空回廊")):
                assert (await _choose(runtime, leader, f"void:comp:{index}", node)).ok
            start_battle = runtime.repository.start_party_battle

            async def fail_start(**_kwargs):
                raise RuntimeError("synthetic battle startup failure")

            runtime.repository.start_party_battle = fail_start
            failed = await _choose(runtime, leader, "void:comp:sentinel", "裂隙哨卫")
            runtime.repository.start_party_battle = start_battle
            assert failed.code == "PERSISTENCE_ERROR"
            compensated = await runtime.repository.compensate_void_ruins_system_failure(
                run_id=entered.data["run_id"]
            )
            replayed_compensation = await runtime.repository.compensate_void_ruins_system_failure(
                run_id=entered.data["run_id"]
            )
            assert compensated.status == "system_aborted"
            assert replayed_compensation.already_completed is True
            with sqlite3.connect(runtime.settings.database_path) as connection:
                run = connection.execute(
                    "SELECT status FROM void_ruins_runs WHERE run_id=?", (entered.data["run_id"],)
                ).fetchone()[0]
                members = connection.execute(
                    "SELECT status, quota_key, anchor_status FROM void_ruins_members WHERE run_id=?",
                    (entered.data["run_id"],),
                ).fetchall()
                players = connection.execute(
                    "SELECT platform_user_id, stamina, inventory_json FROM players "
                    "WHERE platform_user_id IN (?, ?) ORDER BY platform_user_id",
                    (leader[1], member[1]),
                ).fetchall()
            assert run == "system_aborted"
            assert all(row[0] == "system_aborted" and row[1].startswith("released:") and row[2] == "released" for row in members)
            for user, stamina, inventory_json in players:
                assert stamina == 100
                assert json.loads(inventory_json).get("item.void_anchor") == 1
            retried = await runtime.adapters.dispatch(
                leader[0], _ctx(*leader, "void:comp:retry"), "进入秘境 虚空遗迹"
            )
            assert retried.code == "VOID_RUINS_ENTERED"
            await runtime.close()

    asyncio.run(run())


def test_void_ruins_pending_battle_expiry_releases_battle_assets_but_keeps_cost_and_quota() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 28, 12, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            leader = ("qq.official", "void-expire-leader")
            member = ("onebot.v11", "void-expire-member")
            await _player(runtime, *leader)
            await _player(runtime, *member)
            party_id = await _party(runtime, leader, member)
            entered = await runtime.adapters.dispatch(
                leader[0], _ctx(*leader, "void:expire:enter"), "进入秘境 虚空遗迹"
            )
            for index, node in enumerate(("遗迹入口", "破碎信标", "虚空回廊")):
                assert (await _choose(runtime, leader, f"void:expire:{index}", node)).ok
            battle = await _choose(runtime, leader, "void:expire:sentinel", "裂隙哨卫")
            battle_id = battle.data["battle_id"]
            clock.advance(minutes=61)
            expired = await runtime.adapters.dispatch(
                member[0], _ctx(*member, "void:expire:settle"), "结算秘境"
            )
            assert expired.code == "VOID_RUINS_SETTLED", expired
            assert expired.data["status"] == "expired"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                session = connection.execute(
                    "SELECT status FROM party_battle_sessions WHERE battle_id=?", (battle_id,)
                ).fetchone()[0]
                locked = connection.execute(
                    "SELECT COUNT(*) FROM party_battle_members WHERE battle_id=? AND asset_lock_status='locked'",
                    (battle_id,),
                ).fetchone()[0]
                current_session = connection.execute(
                    "SELECT current_session_id FROM parties WHERE party_id=?", (party_id,)
                ).fetchone()[0]
                players = connection.execute(
                    "SELECT platform_user_id, stamina, inventory_json FROM players "
                    "WHERE platform_user_id IN (?, ?) ORDER BY platform_user_id",
                    (leader[1], member[1]),
                ).fetchall()
                run_status = connection.execute(
                    "SELECT status FROM void_ruins_runs WHERE run_id=?", (entered.data["run_id"],)
                ).fetchone()[0]
            assert (session, locked, current_session, run_status) == ("settled", 0, None, "expired")
            for user, stamina, inventory_json in players:
                assert stamina == (50 if user == leader[1] else 100)
                assert json.loads(inventory_json).get("item.void_anchor") == 1
            quota = await runtime.adapters.dispatch(
                leader[0], _ctx(*leader, "void:expire:quota"), "进入秘境 虚空遗迹"
            )
            assert quota.code == "VOID_RUINS_QUOTA_EXHAUSTED"
            await runtime.close()

    asyncio.run(run())


def test_void_ruins_battle_loss_returns_escrow_but_not_entry_cost_or_quota() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            leader = ("onebot.v11", "void-loss-leader")
            member = ("qq.official", "void-loss-member")
            await _player(runtime, *leader, strong=False)
            await _player(runtime, *member, strong=False)
            await _party(runtime, leader, member)
            entered = await runtime.adapters.dispatch(
                leader[0], _ctx(*leader, "void:loss:enter"), "进入秘境 虚空遗迹"
            )
            for index, node in enumerate(("遗迹入口", "破碎信标", "虚空回廊")):
                assert (await _choose(runtime, leader, f"void:loss:{index}", node)).ok
            assert (await _choose(runtime, leader, "void:loss:sentinel", "裂隙哨卫")).ok
            loss = await runtime.adapters.dispatch(
                member[0], _ctx(*member, "void:loss:settle"), "结算秘境"
            )
            assert loss.code == "VOID_RUINS_SETTLED", loss
            assert loss.data["status"] == "failed"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                rows = connection.execute(
                    "SELECT platform_user_id, stamina, inventory_json FROM players "
                    "WHERE platform_user_id IN (?, ?) ORDER BY platform_user_id",
                    (leader[1], member[1]),
                ).fetchall()
                run_status = connection.execute(
                    "SELECT status FROM void_ruins_runs WHERE run_id=?", (entered.data["run_id"],)
                ).fetchone()[0]
            assert run_status == "failed"
            assert all(row[1] == (50 if row[0] == leader[1] else 100) for row in rows)
            assert all(json.loads(row[2]).get("item.void_anchor") == 1 for row in rows)
            assert all(json.loads(row[2]).get("item.void_crystal", 0) == 0 for row in rows)
            quota = await runtime.adapters.dispatch(
                leader[0], _ctx(*leader, "void:loss:quota"), "进入秘境 虚空遗迹"
            )
            assert quota.code == "VOID_RUINS_QUOTA_EXHAUSTED"
            await runtime.close()

    asyncio.run(run())
