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


def _ctx(adapter: str, user: str, operation: str = "") -> CommandContext:
    return CommandContext(adapter=adapter, user_id=user, operation_id=operation)


async def _player(runtime, identity: tuple[str, str], *, domain_key: str | None = "domain.heavenly_sword", energy: int = 25) -> None:
    adapter, user = identity
    created = await runtime.adapters.dispatch(adapter, _ctx(adapter, user, f"create:{adapter}:{user}"), "开始修仙")
    assert created.code == "PLAYER_CREATED"
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE players SET realm_key='soul_transformation', realm_layer=1, "
            "location_key='cave.ancient_domain', stamina=100, stamina_max=100, "
            "max_hp=50000, initiative=9999, qualification_json=?, domain_key=?, "
            "domain_charge=?, domain_charge_max=100, domain_power=100 "
            "WHERE platform=? AND platform_user_id=?",
            (json.dumps({"body": 2000, "agility": 2000}), domain_key, energy, adapter, user),
        )


async def _create_party(runtime, members: tuple[tuple[str, str], ...]) -> str:
    leader = members[0]
    created = await runtime.adapters.dispatch(
        leader[0], _ctx(*leader, "party-create"), "创建远古洞天秘境队伍"
    )
    assert created.code == "PARTY_CREATED"
    party_id = str(created.data["party_id"])
    for index, member in enumerate(members[1:]):
        invited = await runtime.adapters.dispatch(
            leader[0], _ctx(*leader, f"party-invite-{index}"), f"邀请入队 {member[0]}:{member[1]}"
        )
        assert invited.code == "PARTY_INVITED"
        accepted = await runtime.adapters.dispatch(
            member[0], _ctx(*member, f"party-accept-{index}"), f"接受入队 {party_id}"
        )
        assert accepted.code == "PARTY_JOINED"
    for index, member in enumerate(members):
        confirmed = await runtime.adapters.dispatch(
            member[0], _ctx(*member, f"party-confirm-{index}"), f"确认入队 {party_id}"
        )
        assert confirmed.ok
    return party_id


async def _clear_run(runtime, members: tuple[tuple[str, str], ...], prefix: str) -> dict[str, object]:
    leader = members[0]
    entered = await runtime.adapters.dispatch(
        leader[0], _ctx(*leader, f"{prefix}:enter"), "进入秘境 远古洞天"
    )
    assert entered.code == "ANCIENT_DOMAIN_ENTERED"
    replay = await runtime.adapters.dispatch(
        leader[0], _ctx(*leader, f"{prefix}:enter"), "进入秘境 远古洞天"
    )
    assert replay.code == "ANCIENT_DOMAIN_ENTERED"
    assert replay.data["run_id"] == entered.data["run_id"]

    route = (
        ("洞天入口",),
        ("裂痕回廊", "内"),
        ("封印古藏",),
        ("太初灵园",),
        ("洞天灵泉",),
    )
    for index, args in enumerate(route):
        result = await runtime.adapters.dispatch(
            leader[0], _ctx(*leader, f"{prefix}:node:{index}"), "选择秘境节点 " + " ".join(args)
        )
        assert result.ok, result
    boss = await runtime.adapters.dispatch(
        leader[0], _ctx(*leader, f"{prefix}:boss"), "选择秘境节点 远古洞天之主"
    )
    assert boss.code == "ANCIENT_DOMAIN_COMBAT_PENDING"
    blocked_leave = await runtime.adapters.dispatch(
        members[1][0], _ctx(*members[1], f"{prefix}:locked-leave"), "退出队伍"
    )
    assert blocked_leave.code == "PARTY_STATE_CONFLICT"
    resumed = await runtime.adapters.dispatch(
        members[2][0], _ctx(*members[2], f"{prefix}:boss-settle"), "结算秘境"
    )
    assert resumed.code == "ANCIENT_DOMAIN_BATTLE_SETTLED"
    assert resumed.data["current_node"] == "weathered_steps"
    for index, node in enumerate(("风化天阶", "本源封印")):
        result = await runtime.adapters.dispatch(
            leader[0], _ctx(*leader, f"{prefix}:after:{index}"), f"选择秘境节点 {node}"
        )
        assert result.ok, result
    settled = await runtime.adapters.dispatch(
        members[1][0], _ctx(*members[1], f"{prefix}:settle"), "结算秘境"
    )
    assert settled.code == "ANCIENT_DOMAIN_SETTLED"
    return settled.data


@pytest.mark.parametrize(
    "members",
    [
        (("qq.official", "ancient-qq-lead"), ("onebot.v11", "ancient-ob-a"), ("qq.official", "ancient-qq-b")),
        (("onebot.v11", "ancient-ob-lead"), ("qq.official", "ancient-qq-a"), ("onebot.v11", "ancient-ob-b")),
    ],
)
def test_ancient_domain_first_repeat_clear_and_mixed_adapter_restart(members) -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 28, 12, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            for identity in members:
                await _player(runtime, identity)
            party_id = await _create_party(runtime, members)

            entered = await runtime.adapters.dispatch(
                members[0][0], _ctx(*members[0], "charge-check"), "进入秘境 远古洞天"
            )
            assert entered.code == "ANCIENT_DOMAIN_ENTERED"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                rows = connection.execute(
                    "SELECT platform_user_id, stamina FROM players WHERE platform_user_id IN (?, ?, ?) ORDER BY platform_user_id",
                    tuple(member[1] for member in members),
                ).fetchall()
            assert sum(row[1] == 60 for row in rows) == 1
            assert sum(row[1] == 100 for row in rows) == 2

            # Resume the same persisted run through a fresh runtime and another adapter.
            await runtime.close()
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            leader = members[0]
            for index, args in enumerate((("洞天入口",), ("裂痕回廊", "外"), ("封印古藏",), ("太初灵园",), ("洞天灵泉",))):
                result = await runtime.adapters.dispatch(
                    leader[0], _ctx(*leader, f"first-route:{index}"), "选择秘境节点 " + " ".join(args)
                )
                assert result.ok, result
            boss = await runtime.adapters.dispatch(
                leader[0], _ctx(*leader, "first-boss"), "选择秘境节点 远古洞天之主"
            )
            assert boss.code == "ANCIENT_DOMAIN_COMBAT_PENDING"
            battle_id = boss.data["battle_id"]
            await runtime.close()
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            first = await runtime.adapters.dispatch(
                members[2][0], _ctx(*members[2], "first-boss-settle"), "结算秘境"
            )
            assert first.code == "ANCIENT_DOMAIN_BATTLE_SETTLED"
            for index, node in enumerate(("风化天阶", "本源封印")):
                assert (await runtime.adapters.dispatch(
                    leader[0], _ctx(*leader, f"first-after:{index}"), f"选择秘境节点 {node}"
                )).ok
            first = await runtime.adapters.dispatch(
                members[1][0], _ctx(*members[1], "first-settle"), "结算秘境"
            )
            assert first.code == "ANCIENT_DOMAIN_SETTLED"
            assert len(first.data["first_clear_members"]) == 3
            replay = await runtime.adapters.dispatch(
                members[1][0], _ctx(*members[1], "first-settle"), "结算秘境"
            )
            assert replay.data["idempotent_replay"] is True

            with sqlite3.connect(runtime.settings.database_path) as connection:
                battle_enemies = connection.execute(
                    "SELECT enemy_key, status, state_json, snapshot_json FROM party_battle_sessions WHERE battle_id=?", (battle_id,)
                ).fetchone()
                energy_loss = connection.execute(
                    "SELECT player_id, SUM(amount) FROM ancient_domain_energy_events WHERE run_id=? GROUP BY player_id",
                    (entered.data["run_id"],),
                ).fetchall()
                energies = connection.execute(
                    "SELECT platform_user_id, domain_charge FROM players WHERE platform_user_id IN (?, ?, ?)",
                    tuple(member[1] for member in members),
                ).fetchall()
                fruits = connection.execute(
                    "SELECT p.platform_user_id, json_extract(p.inventory_json, '$.\"item.ancient_fruit\"') "
                    "FROM players p WHERE p.platform_user_id IN (?, ?, ?)",
                    tuple(member[1] for member in members),
                ).fetchall()
                codex_count = connection.execute(
                    "SELECT COUNT(*) FROM codex_entries c JOIN players p ON p.id=c.player_id "
                    "WHERE c.entry_key='codex.domain.ancient_domain' AND p.platform_user_id IN (?, ?, ?)",
                    tuple(member[1] for member in members),
                ).fetchone()[0]
                suppression_actions = connection.execute(
                    "SELECT COUNT(*) FROM party_battle_actions WHERE battle_id=? AND strategy_key='enemy.domain_suppress'",
                    (battle_id,),
                ).fetchone()[0]
                standard_battle_rewards = connection.execute(
                    "SELECT COUNT(*) FROM party_battle_rewards WHERE battle_id=? AND status='claimed'",
                    (battle_id,),
                ).fetchone()[0]
            assert battle_enemies[0] == "enemy.ancient_domain_lord"
            assert battle_enemies[1] == "settled"
            assert all(not value for value in json.loads(battle_enemies[2])["member_domain_active"].values())
            assert all(member["domain_charge"] == 25 for member in json.loads(battle_enemies[3])["members"])
            assert suppression_actions >= 3
            assert standard_battle_rewards == 0
            assert len(energy_loss) == 3
            assert all(amount > 0 for _, amount in energy_loss)
            assert all(charge == 0 for _, charge in energies)
            assert all(quantity == 2 for _, quantity in fruits)
            assert codex_count == 3

            with sqlite3.connect(runtime.settings.database_path) as connection:
                leader_row = connection.execute(
                    "SELECT inventory_json, stamina FROM players WHERE platform=? AND platform_user_id=?",
                    leader,
                ).fetchone()
                inventory = json.loads(leader_row[0])
                inventory["item.cave_pass_basic"] = 1
                connection.execute(
                    "UPDATE players SET realm_key='qi_gathering', realm_layer=4, location_key='cave.mist_grotto', inventory_json=? "
                    "WHERE platform=? AND platform_user_id=?",
                    (json.dumps(inventory), *leader),
                )
            ordinary = await runtime.adapters.dispatch(
                leader[0], _ctx(*leader, "same-second-ordinary-enter"), "进入秘境 雾隐秘境"
            )
            assert ordinary.code == "SECRET_REALM_ENTERED"
            ordinary_settlement = await runtime.adapters.dispatch(
                leader[0], _ctx(*leader, "same-second-ordinary-settle"), "结算秘境"
            )
            assert ordinary_settlement.code == "SECRET_REALM_NOT_READY"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE secret_realm_runs SET status='settled' WHERE run_id=?", (ordinary.data["run_id"],)
                )
                connection.execute(
                    "UPDATE players SET realm_key='soul_transformation', realm_layer=1, location_key='cave.ancient_domain', stamina=? "
                    "WHERE platform=? AND platform_user_id=?",
                    (leader_row[1], *leader),
                )

            limited = await runtime.adapters.dispatch(
                members[0][0], _ctx(*members[0], "same-week-limit"), "进入秘境 远古洞天"
            )
            assert limited.code == "ANCIENT_DOMAIN_QUOTA_EXHAUSTED"

            clock.advance(days=7)
            repeated = await _clear_run(runtime, members, "repeat")
            assert not repeated["first_clear_members"]
            with sqlite3.connect(runtime.settings.database_path) as connection:
                fruits = connection.execute(
                    "SELECT json_extract(inventory_json, '$.\"item.ancient_fruit\"') FROM players WHERE platform_user_id IN (?, ?, ?)",
                    tuple(member[1] for member in members),
                ).fetchall()
                codex_count = connection.execute(
                    "SELECT COUNT(*) FROM codex_entries c JOIN players p ON p.id=c.player_id "
                    "WHERE c.entry_key='codex.domain.ancient_domain' AND p.platform_user_id IN (?, ?, ?)",
                    tuple(member[1] for member in members),
                ).fetchone()[0]
                stamina = connection.execute(
                    "SELECT platform_user_id, stamina FROM players WHERE platform_user_id IN (?, ?, ?)",
                    tuple(member[1] for member in members),
                ).fetchall()
                assert connection.execute("SELECT party_type FROM parties WHERE party_id=?", (party_id,)).fetchone()[0] == "secret_realm_ancient"
            assert all(quantity == 3 for (quantity,) in fruits)
            assert codex_count == 3
            assert sum(value == 20 for _, value in stamina) == 1
            assert sum(value == 100 for _, value in stamina) == 2
            await runtime.close()

    asyncio.run(run())


def test_ancient_domain_atomic_admission_and_system_compensation() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 28, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            members = (("qq.official", "ancient-comp-lead"), ("onebot.v11", "ancient-comp-a"), ("qq.official", "ancient-comp-b"))
            for identity in members:
                await _player(runtime, identity)
            await _create_party(runtime, members)
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute("UPDATE players SET domain_crack_until='2099-01-01T00:00:00+00:00' WHERE platform_user_id=?", (members[1][1],))
            denied = await runtime.adapters.dispatch(
                members[0][0], _ctx(*members[0], "crack-denied"), "进入秘境 远古洞天"
            )
            assert denied.code == "ANCIENT_DOMAIN_REQUIREMENT_MISSING"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute(
                    "SELECT COUNT(*) FROM ancient_domain_runs"
                ).fetchone()[0] == 0
                assert [row[0] for row in connection.execute(
                    "SELECT stamina FROM players WHERE platform_user_id IN (?, ?, ?)", tuple(member[1] for member in members)
                ).fetchall()] == [100, 100, 100]
                connection.execute("UPDATE players SET domain_crack_until=NULL WHERE platform_user_id=?", (members[1][1],))

            entered = await runtime.adapters.dispatch(
                members[0][0], _ctx(*members[0], "comp-enter"), "进入秘境 远古洞天"
            )
            assert entered.code == "ANCIENT_DOMAIN_ENTERED"
            leader = members[0]
            for index, args in enumerate((("洞天入口",), ("裂痕回廊", "内"), ("封印古藏",), ("太初灵园",), ("洞天灵泉",))):
                assert (await runtime.adapters.dispatch(
                    leader[0], _ctx(*leader, f"comp-route:{index}"), "选择秘境节点 " + " ".join(args)
                )).ok
            boss = await runtime.adapters.dispatch(
                leader[0], _ctx(*leader, "comp-boss"), "选择秘境节点 远古洞天之主"
            )
            assert boss.code == "ANCIENT_DOMAIN_COMBAT_PENDING"
            won = await runtime.adapters.dispatch(
                members[1][0], _ctx(*members[1], "comp-boss-settle"), "结算秘境"
            )
            assert won.code == "ANCIENT_DOMAIN_BATTLE_SETTLED"
            compensated = await runtime.repository.compensate_ancient_domain_system_failure(run_id=entered.data["run_id"])
            assert compensated.status == "system_aborted"
            replayed = await runtime.repository.compensate_ancient_domain_system_failure(run_id=entered.data["run_id"])
            assert replayed.status == "system_aborted"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                rows = connection.execute(
                    "SELECT platform_user_id, stamina, domain_charge FROM players WHERE platform_user_id IN (?, ?, ?)",
                    tuple(member[1] for member in members),
                ).fetchall()
                quotas = connection.execute(
                    "SELECT DISTINCT status, quota_key FROM ancient_domain_members WHERE run_id=?",
                    (entered.data["run_id"],),
                ).fetchall()
                locks = connection.execute(
                    "SELECT COUNT(*) FROM party_battle_members WHERE asset_lock_status='locked' "
                    "AND battle_id=(SELECT battle_id FROM party_battle_sessions WHERE party_id=(SELECT party_id FROM ancient_domain_runs WHERE run_id=?))",
                    (entered.data["run_id"],),
                ).fetchone()[0]
                inventory = connection.execute(
                    "SELECT inventory_json FROM players WHERE platform_user_id=?", (members[0][1],)
                ).fetchone()[0]
            assert sum(value == 100 for _, value, _ in rows) == 3
            assert all(energy == 25 for _, _, energy in rows)
            assert len(quotas) == 3
            assert all(status == "released" and key.startswith("released:") for status, key in quotas)
            assert locks == 0
            assert json.loads(inventory).get("item.domain_core", 0) == 0
            await runtime.close()

    asyncio.run(run())


def test_ancient_domain_boss_expiry_releases_combat_lock_and_keeps_entry_cost() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 28, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            members = (("qq.official", "ancient-expire-lead"), ("onebot.v11", "ancient-expire-a"), ("qq.official", "ancient-expire-b"))
            for identity in members:
                await _player(runtime, identity)
            await _create_party(runtime, members)
            leader = members[0]
            entered = await runtime.adapters.dispatch(
                leader[0], _ctx(*leader, "expire-enter"), "进入秘境 远古洞天"
            )
            for index, args in enumerate((("洞天入口",), ("裂痕回廊", "内"), ("封印古藏",), ("太初灵园",), ("洞天灵泉",))):
                assert (await runtime.adapters.dispatch(
                    leader[0], _ctx(*leader, f"expire-route:{index}"), "选择秘境节点 " + " ".join(args)
                )).ok
            boss = await runtime.adapters.dispatch(
                leader[0], _ctx(*leader, "expire-boss"), "选择秘境节点 远古洞天之主"
            )
            assert boss.code == "ANCIENT_DOMAIN_COMBAT_PENDING"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE ancient_domain_runs SET expires_at='2000-01-01T00:00:00+00:00' WHERE run_id=?",
                    (entered.data["run_id"],),
                )
            expired = await runtime.adapters.dispatch(
                members[1][0], _ctx(*members[1], "expire-settle"), "结算秘境"
            )
            assert expired.code == "ANCIENT_DOMAIN_SETTLED"
            assert expired.data["status"] == "expired"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                run = connection.execute(
                    "SELECT status FROM ancient_domain_runs WHERE run_id=?", (entered.data["run_id"],)
                ).fetchone()[0]
                battle = connection.execute(
                    "SELECT status, json_extract(result_json, '$.outcome') FROM party_battle_sessions WHERE battle_id=?",
                    (boss.data["battle_id"],),
                ).fetchone()
                locks = connection.execute(
                    "SELECT COUNT(*) FROM party_battle_members WHERE battle_id=? AND asset_lock_status='locked'",
                    (boss.data["battle_id"],),
                ).fetchone()[0]
                stamina = connection.execute(
                    "SELECT platform_user_id, stamina FROM players WHERE platform_user_id IN (?, ?, ?)",
                    tuple(member[1] for member in members),
                ).fetchall()
                member_statuses = connection.execute(
                    "SELECT DISTINCT status FROM ancient_domain_members WHERE run_id=?", (entered.data["run_id"],)
                ).fetchall()
                assert connection.execute(
                    "SELECT COUNT(*) FROM party_battle_rewards WHERE battle_id=? AND status='claimed'",
                    (boss.data["battle_id"],),
                ).fetchone()[0] == 0
            assert run == "expired"
            assert battle == ("settled", "expired")
            assert locks == 0
            assert sum(value == 60 for _, value in stamina) == 1
            assert sum(value == 100 for _, value in stamina) == 2
            assert member_statuses == [("expired",)]
            await runtime.close()

    asyncio.run(run())
