from __future__ import annotations

import asyncio
import json
import sqlite3
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime


async def _send(runtime, adapter: str, user: str, operation: str, command: str):
    return await runtime.adapters.dispatch(
        adapter,
        CommandContext(adapter=adapter, user_id=user, operation_id=operation),
        command,
    )


def _eligible(runtime, identities: list[tuple[str, str]], *, realm: str = "nascent_soul", layer: int = 1, hp: int = 100000) -> None:
    with sqlite3.connect(runtime.settings.database_path) as db:
        for adapter, user in identities:
            db.execute(
                "UPDATE players SET stage='cultivator',realm_key=?,realm_layer=?,stamina=100,stamina_max=100,max_hp=?,initiative=1000,"
                "qualification_json=?,intro_json=?,faction_reputation_json=? WHERE platform=? AND platform_user_id=?",
                (
                    realm,
                    layer,
                    hp,
                    json.dumps({"body": 1000, "agility": 1000}),
                    json.dumps({"flags": ["alliance.xuantian"]}),
                    json.dumps({"xuantian": 500}),
                    adapter,
                    user,
                ),
            )
            player_id = db.execute(
                "SELECT id FROM players WHERE platform=? AND platform_user_id=?", (adapter, user)
            ).fetchone()[0]
            db.execute(
                "INSERT INTO player_reputations(player_id,local_json,service_reputation,updated_at) VALUES (?,?,0,'2026-09-28T00:00:00+00:00') "
                "ON CONFLICT(player_id) DO UPDATE SET local_json=excluded.local_json,updated_at=excluded.updated_at",
                (player_id, json.dumps({"local.domain_refuge": 500})),
            )


async def _ready_duo(runtime, leader: tuple[str, str], member: tuple[str, str]) -> str:
    created = await _send(runtime, leader[0], leader[1], "party-create", "创建三界塔双人队伍")
    assert created.ok
    party_id = str(created.data["party_id"])
    assert (await _send(runtime, leader[0], leader[1], "party-invite", f"邀请入队 {member[0]}:{member[1]}")).ok
    assert (await _send(runtime, member[0], member[1], "party-accept", f"接受入队 {party_id}")).ok
    assert (await _send(runtime, leader[0], leader[1], "party-confirm-leader", f"确认入队 {party_id}")).ok
    ready = await _send(runtime, member[0], member[1], "party-confirm-member", f"确认入队 {party_id}")
    assert ready.code == "PARTY_READY"
    return party_id


def test_three_realms_tower_duo_qq_onebot_progression_and_isolation(monkeypatch) -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            await runtime.initialize()
            leader = ("qq.official", "tower-duo-qq")
            member = ("onebot.v11", "tower-duo-onebot")
            third = ("qq.official", "tower-duo-third")
            for index, identity in enumerate((leader, member, third)):
                assert (await _send(runtime, identity[0], identity[1], f"create-{index}", "开始修仙")).ok
            _eligible(runtime, [leader, member, third])
            party_id = await _ready_duo(runtime, leader, member)
            third_join = await _send(runtime, leader[0], leader[1], "third-invite", f"邀请入队 {third[0]}:{third[1]}")
            assert not third_join.ok
            assert third_join.code == "PARTY_MEMBER_CAP"

            before = {}
            with sqlite3.connect(runtime.settings.database_path) as db:
                for adapter, user in (leader, member):
                    before[user] = db.execute(
                        "SELECT stamina FROM players WHERE platform=? AND platform_user_id=?", (adapter, user)
                    ).fetchone()[0]
            settled = await _send(runtime, leader[0], leader[1], "duo-floor-1", "挑战三界塔双人 1")
            assert settled.code == "THREE_REALMS_TOWER_DUO_SETTLED"
            assert settled.data["outcome"] == "won"
            with sqlite3.connect(runtime.settings.database_path) as db:
                for adapter, user in (leader, member):
                    assert db.execute(
                        "SELECT stamina FROM players WHERE platform=? AND platform_user_id=?", (adapter, user)
                    ).fetchone()[0] == before[user] - 12
                snapshot = db.execute(
                    "SELECT snapshot_json FROM party_battle_sessions WHERE battle_id=?", (settled.data["battle_id"],)
                ).fetchone()[0]
                assert len(json.loads(snapshot)["members"]) == 2
                assert json.loads(snapshot)["party_type"] == "three_realms_tower_duo"

            claim_leader = await _send(runtime, leader[0], leader[1], "duo-claim-leader", "领取三界塔双人奖励")
            assert claim_leader.ok and claim_leader.data["first_clear"] is True
            claim_replay = await _send(runtime, leader[0], leader[1], "duo-claim-leader", "领取三界塔双人奖励")
            assert claim_replay.ok and claim_replay.data["idempotent_replay"] is True
            await runtime.close()

            runtime = create_runtime(data_dir=data_dir)
            await runtime.initialize()
            claim_member = await _send(runtime, member[0], member[1], "duo-claim-member", "领取三界塔双人奖励")
            assert claim_member.ok and claim_member.data["first_clear"] is True
            with sqlite3.connect(runtime.settings.database_path) as db:
                db.execute(
                    "UPDATE players SET max_hp=1,initiative=0,qualification_json=? WHERE platform IN ('qq.official','onebot.v11') AND platform_user_id IN (?,?)",
                    (json.dumps({"body": 0, "agility": 0}), leader[1], member[1]),
                )
            from nonebot_plugin_xiuxian_3.xiuxian.combat import party_repository as party_repo
            from nonebot_plugin_xiuxian_3.xiuxian.combat.rules import EnemyDefinition
            monkeypatch.setattr(
                party_repo,
                "enemy_definition",
                lambda key: EnemyDefinition(key, "测试高阶敌人", "xuantian.new_town", "nascent_soul", 1, 100000, 100000, 100, 100, "enemy_skill.test", "test", {}),
            )
            failed = await _send(runtime, leader[0], leader[1], "duo-loss", "挑战三界塔双人 1")
            assert failed.ok and failed.data["outcome"] != "won"
            no_reward = await _send(runtime, leader[0], leader[1], "duo-loss-claim", "领取三界塔双人奖励")
            assert no_reward.code == "THREE_REALMS_TOWER_DUO_REWARD_NOT_AVAILABLE"
            with sqlite3.connect(runtime.settings.database_path) as db:
                rewards = db.execute(
                    "SELECT COUNT(*) FROM three_realms_tower_duo_member_runs WHERE duo_run_id=? AND status='claimed'",
                    (settled.data["duo_run_id"],),
                ).fetchone()[0]
                assert rewards == 2
            await runtime.close()

    asyncio.run(run())


def test_three_realms_tower_duo__gate_failure_and_start_refund(monkeypatch) -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            await runtime.initialize()
            identities = [("qq.official", "tower-duo-gate"), ("onebot.v11", "tower-duo-gate-member")]
            for index, identity in enumerate(identities):
                assert (await _send(runtime, identity[0], identity[1], f"create-{index}", "开始修仙")).ok
            _eligible(runtime, identities, realm="soul_transformation", layer=1)
            party_id = await _ready_duo(runtime, identities[0], identities[1])
            with sqlite3.connect(runtime.settings.database_path) as db:
                db.execute(
                    "UPDATE players SET realm_key='nascent_soul',realm_layer=1 WHERE platform=? AND platform_user_id=?",
                    identities[1],
                )
                db.execute("UPDATE player_reputations SET local_json=? WHERE player_id=(SELECT id FROM players WHERE platform=? AND platform_user_id=?)", (json.dumps({"local.domain_refuge": 499}), identities[1][0], identities[1][1]))
                db.execute(
                    "INSERT INTO three_realms_tower_duo_runs(duo_run_id,party_id,tower_key,floor_no,status,member_run_ids_json,result_json,start_operation_id,created_at,updated_at) VALUES ('seed-duo',?,'tower.three_realms',20,'won','[]','{}','seed-op','2026-09-27T00:00:00+00:00','2026-09-27T00:00:00+00:00')",
                    (party_id,),
                )
                player_ids = [db.execute("SELECT id FROM players WHERE platform=? AND platform_user_id=?", identity).fetchone()[0] for identity in identities]
                for index, player_id in enumerate(player_ids):
                    db.execute(
                        "INSERT INTO three_realms_tower_duo_member_runs(run_id,duo_run_id,player_id,floor_no,first_clear,status,reward_json,created_at,updated_at) VALUES (?,?,?,?,1,'claimed','{}','2026-09-27T00:00:00+00:00','2026-09-27T00:00:00+00:00')",
                        (f"seed-member-{index}", "seed-duo", player_id, 20),
                    )
            denied = await _send(runtime, identities[0][0], identities[0][1], "duo-denied", "挑战三界塔双人 21")
            assert denied.code == "THREE_REALMS_TOWER_DUO_REQUIREMENT_MISSING"
            _eligible(runtime, identities, realm="soul_transformation", layer=1)
            original = runtime.repository.start_party_battle

            async def fail_start(**kwargs):
                raise RuntimeError("simulated start failure")

            monkeypatch.setattr(runtime.repository, "start_party_battle", fail_start)
            before = {}
            with sqlite3.connect(runtime.settings.database_path) as db:
                for identity in identities:
                    before[identity] = db.execute("SELECT stamina FROM players WHERE platform=? AND platform_user_id=?", identity).fetchone()[0]
            failed = await _send(runtime, identities[0][0], identities[0][1], "duo-failed", "挑战三界塔双人 1")
            assert failed.code == "THREE_REALMS_TOWER_DUO_START_FAILED"
            with sqlite3.connect(runtime.settings.database_path) as db:
                for identity in identities:
                    assert db.execute("SELECT stamina FROM players WHERE platform=? AND platform_user_id=?", identity).fetchone()[0] == before[identity]
                assert db.execute("SELECT status FROM three_realms_tower_duo_runs ORDER BY id DESC LIMIT 1").fetchone()[0] == "aborted"
            monkeypatch.setattr(runtime.repository, "start_party_battle", original)
            await runtime.close()

    asyncio.run(run())
