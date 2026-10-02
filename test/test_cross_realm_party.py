from __future__ import annotations

import asyncio
import json
import sqlite3
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime


def _ctx(adapter: str, user: str, request: str, operation: str = "") -> CommandContext:
    return CommandContext(adapter=adapter, user_id=user, request_id=request, operation_id=operation)


async def _player(
    runtime,
    adapter: str,
    user: str,
    *,
    location: str,
    intro_flags: list[str],
    faction: dict[str, int],
    body: int = 2_000,
) -> None:
    created = await runtime.adapters.dispatch(adapter, _ctx(adapter, user, f"create:{adapter}:{user}"), "开始修仙")
    assert created.code == "PLAYER_CREATED"
    with sqlite3.connect(runtime.settings.database_path) as db:
        db.execute(
            "UPDATE players SET stage='cultivator', realm_key='nascent_soul', realm_layer=1, "
            "location_key=?, stamina=20, max_hp=50000, initiative=9999, soul_power=10000, "
            "qualification_json=?, intro_json=?, faction_reputation_json=?, pollution=10, bloodline_stability=60 "
            "WHERE platform=? AND platform_user_id=?",
            (
                location,
                json.dumps({"body": body, "agility": body}),
                json.dumps({"flags": intro_flags}),
                json.dumps(faction),
                adapter,
                user,
            ),
        )


async def _form_party(runtime, party_command: str, leader: tuple[str, str], member: tuple[str, str]) -> str:
    created = await runtime.adapters.dispatch(leader[0], _ctx(*leader, "create-party"), party_command)
    assert created.code == "PARTY_CREATED"
    party_id = str(created.data["party_id"])
    invited = await runtime.adapters.dispatch(
        leader[0], _ctx(*leader, "invite"), f"邀请入队 {member[0]}:{member[1]}"
    )
    assert invited.code == "PARTY_INVITED"
    accepted = await runtime.adapters.dispatch(
        member[0], _ctx(*member, "accept"), f"接受入队 {party_id}"
    )
    assert accepted.code == "PARTY_JOINED"
    for index, identity in enumerate((leader, member)):
        confirmed = await runtime.adapters.dispatch(
            identity[0], _ctx(*identity, f"confirm-{index}"), f"确认入队 {party_id}"
        )
        assert confirmed.ok
    return party_id


def test_demon_and_beast_party_dungeons_use_mixed_adapters_and_frozen_rewards() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            demon_leader = ("qq.official", "demon-party-leader")
            demon_member = ("onebot.v11", "demon-party-member")
            beast_leader = ("onebot.v11", "beast-party-leader")
            beast_member = ("qq.official", "beast-party-member")
            for identity in (demon_leader, demon_member):
                await _player(runtime, *identity, location="demon.fallen_ruins", intro_flags=["access.demon.fallen_ruins"], faction={"demon": 200})
            for identity in (beast_leader, beast_member):
                await _player(runtime, *identity, location="beast.ten_thousand_hills", intro_flags=[], faction={"beast": 200}, body=600)

            demon_party = await _form_party(runtime, "创建魔渊队伍", demon_leader, demon_member)
            demon_start = await runtime.repository.start_party_battle(
                platform=demon_leader[0], platform_user_id=demon_leader[1], party_id=demon_party, operation_id="demon-party-start"
            )
            demon_result = await runtime.repository.settle_party_battle(
                platform=demon_member[0], platform_user_id=demon_member[1], battle_id=demon_start.battle_id, operation_id="demon-party-resolve"
            )
            assert demon_start.enemy_key == "enemy.demon_overlord"
            assert demon_result.outcome == "won"
            demon_replay = await runtime.repository.replay_party_battle(
                platform=demon_leader[0], platform_user_id=demon_leader[1], battle_id=demon_start.battle_id
            )
            assert any(action["skill_key"] == "skill.demonic.abyss_communion" for action in demon_replay.actions)
            assert any(action["skill_key"] == "skill.demonic.abyss_communion" and "pollution_gain" in str(action["state_json"]) for action in demon_replay.actions)

            beast_party = await _form_party(runtime, "创建万兽队伍", beast_leader, beast_member)
            beast_start = await runtime.repository.start_party_battle(
                platform=beast_leader[0], platform_user_id=beast_leader[1], party_id=beast_party, operation_id="beast-party-start"
            )
            beast_result = await runtime.repository.settle_party_battle(
                platform=beast_member[0], platform_user_id=beast_member[1], battle_id=beast_start.battle_id, operation_id="beast-party-resolve"
            )
            assert beast_start.enemy_key == "enemy.beast_ancestor"
            assert beast_result.outcome == "won"
            beast_replay = await runtime.repository.replay_party_battle(
                platform=beast_leader[0], platform_user_id=beast_leader[1], battle_id=beast_start.battle_id
            )
            assert any(action["strategy_key"] == "enemy.ancestral_summon" for action in beast_replay.actions)
            assert any(action["strategy_key"] == "party.clear_summon" for action in beast_replay.actions)

            with sqlite3.connect(runtime.settings.database_path) as db:
                rows = db.execute(
                    "SELECT platform_user_id, stamina, inventory_json, faction_reputation_json FROM players "
                    "WHERE platform_user_id IN (?, ?, ?, ?) ORDER BY platform_user_id",
                    (demon_leader[1], demon_member[1], beast_leader[1], beast_member[1]),
                ).fetchall()
            values = {row[0]: (row[1], json.loads(row[2]), json.loads(row[3])) for row in rows}
            assert values[demon_leader[1]][0] == 0
            assert values[demon_leader[1]][1]["item.demon_core"] == 1
            assert values[demon_leader[1]][2]["demon"] == 215
            assert values[beast_member[1]][1]["item.beast_blood"] == 1
            assert values[beast_member[1]][2]["beast"] == 215
            await runtime.close()

    asyncio.run(run())


def test_cross_realm_party_rejects_missing_access_or_reputation_without_debit() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            leader = ("qq.official", "demon-party-denied-leader")
            member = ("onebot.v11", "demon-party-denied-member")
            await _player(runtime, *leader, location="demon.fallen_ruins", intro_flags=[], faction={"demon": 200})
            await _player(runtime, *member, location="demon.fallen_ruins", intro_flags=["access.demon.fallen_ruins"], faction={"demon": 199})
            party_id = await _form_party(runtime, "创建魔渊队伍", leader, member)
            denied = await runtime.adapters.dispatch(leader[0], _ctx(*leader, "denied-start"), f"开始队伍战斗 {party_id}")
            assert denied.code == "BATTLE_CROSS_REALM_REQUIREMENT_MISSING"
            with sqlite3.connect(runtime.settings.database_path) as db:
                rows = db.execute(
                    "SELECT stamina FROM players WHERE platform_user_id IN (?, ?) ORDER BY platform_user_id",
                    (leader[1], member[1]),
                ).fetchall()
            assert [row[0] for row in rows] == [20, 20]
            await runtime.close()

    asyncio.run(run())


def test_demon_party_failure_releases_locks_and_applies_fatigue_once() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            leader = ("qq.official", "demon-party-loss-leader")
            member = ("onebot.v11", "demon-party-loss-member")
            for identity in (leader, member):
                await _player(
                    runtime,
                    *identity,
                    location="demon.fallen_ruins",
                    intro_flags=["access.demon.fallen_ruins"],
                    faction={"demon": 200},
                    body=1,
                )
            party_id = await _form_party(runtime, "创建魔渊队伍", leader, member)
            started = await runtime.repository.start_party_battle(
                platform=leader[0], platform_user_id=leader[1], party_id=party_id, operation_id="demon-party-loss-start"
            )
            result = await runtime.repository.settle_party_battle(
                platform=member[0], platform_user_id=member[1], battle_id=started.battle_id, operation_id="demon-party-loss-resolve"
            )
            assert result.outcome in {"lost", "expired"}
            replay = await runtime.repository.replay_party_battle(
                platform=leader[0], platform_user_id=leader[1], battle_id=started.battle_id
            )
            assert replay.result["outcome"] in {"lost", "expired"}
            with sqlite3.connect(runtime.settings.database_path) as db:
                rows = db.execute(
                    "SELECT soul_fatigue_until, stamina FROM players WHERE platform_user_id IN (?, ?) ORDER BY platform_user_id",
                    (leader[1], member[1]),
                ).fetchall()
                locked = db.execute(
                    "SELECT COUNT(*) FROM party_battle_members WHERE battle_id=? AND asset_lock_status='locked'",
                    (started.battle_id,),
                ).fetchone()[0]
            assert all(row[0] for row in rows)
            assert [row[1] for row in rows] == [0, 0]
            assert locked == 0
            await runtime.close()

    asyncio.run(run())
