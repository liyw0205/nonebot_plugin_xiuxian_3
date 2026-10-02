from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory

import pytest

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.adventures.demon_abyss_rules import (
    demon_abyss_risk_applies,
    demon_abyss_risk_roll_bp,
)


def _context(adapter: str, user: str, operation_id: str) -> CommandContext:
    return CommandContext(adapter=adapter, user_id=user, operation_id=operation_id)


async def _create_player(
    runtime,
    adapter: str,
    user: str,
    *,
    realm: str = "foundation",
    layer: int = 1,
    location: str = "demon.abyss_gate",
    access: bool = True,
    reputation: int = 200,
    body: int = 4000,
    pollution: int = 10,
    soul_restore: int = 0,
) -> None:
    assert (await runtime.adapters.dispatch(adapter, _context(adapter, user, f"{user}:create"), "开始修仙")).ok
    assert (await runtime.adapters.dispatch(adapter, _context(adapter, user, f"{user}:seek"), "寻仙问道")).ok
    flags = ["access.demon_abyss_gate"] if access else []
    inventory = {"item.pill.soul_restore": soul_restore} if soul_restore else {}
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE players SET stage='cultivator', realm_key=?, realm_layer=?, location_key=?, "
            "stamina=100, stamina_max=100, max_hp=?, initiative=2000, pollution=?, qualification_json=?, "
            "intro_json=?, faction_reputation_json=?, inventory_json=? WHERE platform=? AND platform_user_id=?",
            (
                realm,
                layer,
                location,
                50_000 if body else 100,
                pollution,
                json.dumps({"body": body, "agility": 200}),
                json.dumps({"flags": flags}),
                json.dumps({"demon": reputation}),
                json.dumps(inventory),
                adapter,
                user,
            ),
        )


async def _command(runtime, adapter: str, user: str, operation: str, command: str):
    return await runtime.adapters.dispatch(
        adapter,
        _context(adapter, user, operation),
        command,
    )


async def _clear_realm(
    runtime, adapter: str, user: str, prefix: str, *, first_clear: bool = True
) -> dict[str, object]:
    entered = await _command(runtime, adapter, user, f"{prefix}:enter", "进入秘境 魔界深渊")
    assert entered.code == "DEMON_ABYSS_ENTERED"
    replay = await _command(runtime, adapter, user, f"{prefix}:enter", "进入秘境 魔界深渊")
    assert replay.data["idempotent_replay"] is True

    skipped = await _command(runtime, adapter, user, f"{prefix}:skip", "选择秘境节点 残响守卫")
    assert skipped.code == "DEMON_ABYSS_NODE_FORBIDDEN"
    threshold = await _command(runtime, adapter, user, f"{prefix}:threshold", "选择秘境节点 深渊门")
    assert threshold.data["current_node"] == "pollution_seep"
    risk = await _command(runtime, adapter, user, f"{prefix}:risk", "选择秘境节点 污染渗流")
    assert risk.code == "DEMON_ABYSS_NODE_SELECTED"
    assert risk.data["risk_modifier_bp"] == 50
    assert risk.data["current_node"] == "echo_guardian"

    first_battle = await _command(runtime, adapter, user, f"{prefix}:echo", "选择秘境节点 残响守卫")
    assert first_battle.code == "DEMON_ABYSS_COMBAT_PENDING"
    advanced = await _command(runtime, adapter, user, f"{prefix}:echo-settle", "结算秘境")
    assert advanced.code == "DEMON_ABYSS_NODE_SETTLED"
    assert advanced.data["current_node"] == "abyss_heart"
    second_battle = await _command(runtime, adapter, user, f"{prefix}:heart", "选择秘境节点 深渊之心")
    assert second_battle.code == "DEMON_ABYSS_COMBAT_PENDING"
    settled = await _command(runtime, adapter, user, f"{prefix}:finish", "结算秘境")
    assert settled.code == "DEMON_ABYSS_SETTLED"
    assert settled.data["outcome"] == "won"
    assert settled.data["first_clear"] is first_clear
    expected_reward = (
        {
            "faction_reputation.demon": 20,
            "item.clue.demon_abyss_echo": 1,
            "story.demon_abyss_echo": 1,
        }
        if first_clear
        else {"item.demon_core": 1}
    )
    assert settled.data["reward"] == expected_reward
    replay_settlement = await _command(runtime, adapter, user, f"{prefix}:finish", "结算秘境")
    assert replay_settlement.data["idempotent_replay"] is True
    return settled.data


@pytest.mark.parametrize("adapter", ["qq.official", "onebot.v11"])
def test_demon_abyss_first_clear_and_weekly_quota_on_both_adapters(adapter: str) -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            user = f"demon-abyss-{adapter}"
            await _create_player(runtime, adapter, user)
            result = await _clear_realm(runtime, adapter, user, f"{adapter}:clear")
            retry = await _command(runtime, adapter, user, "weekly-limit", "进入秘境 魔界深渊")
            assert retry.code == "DEMON_ABYSS_QUOTA_EXHAUSTED"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                player = connection.execute(
                    "SELECT stamina, faction_reputation_json, inventory_json, intro_json FROM players "
                    "WHERE platform=? AND platform_user_id=?",
                    (adapter, user),
                ).fetchone()
                battles = connection.execute(
                    "SELECT enemy_key, reward_status FROM battle_sessions "
                    "WHERE battle_type='pve.secret_realm.demon_abyss' ORDER BY id"
                ).fetchall()
            assert player[0] == 80
            assert json.loads(player[1])["demon"] == 220
            assert json.loads(player[2])["item.clue.demon_abyss_echo"] == 1
            assert "story.demon_abyss_echo" in json.loads(player[3])["flags"]
            assert [row[0] for row in battles] == ["enemy.demon_abyss_echo_guardian", "enemy.demon_abyss_heart"]
            assert all(row[1:] == ("none",) for row in battles)
            assert result["outcome"] == "won"
            await runtime.close()

    asyncio.run(run())


def test_demon_abyss_repeat_clear_uses_repeat_reward() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, adapters=("qq.official",))
            user = "demon-abyss-repeat"
            await _create_player(runtime, "qq.official", user)
            await _clear_realm(runtime, "qq.official", user, "first")
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE secret_realm_runs SET quota_key='1990-W01' WHERE player_id=("
                    "SELECT id FROM players WHERE platform='qq.official' AND platform_user_id=?)",
                    (user,),
                )
            repeated = await _clear_realm(
                runtime, "qq.official", user, "repeat", first_clear=False
            )
            with sqlite3.connect(runtime.settings.database_path) as connection:
                reputation, inventory = connection.execute(
                    "SELECT faction_reputation_json, inventory_json FROM players "
                    "WHERE platform='qq.official' AND platform_user_id=?",
                    (user,),
                ).fetchone()
            assert repeated["reward"] == {"item.demon_core": 1}
            assert json.loads(reputation)["demon"] == 220
            assert json.loads(inventory)["item.demon_core"] == 1
            await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize(
    ("realm", "location", "access", "reputation"),
    [
        ("qi_gathering", "demon.abyss_gate", True, 200),
        ("foundation", "demon.fallen_ruins", True, 200),
        ("foundation", "demon.abyss_gate", False, 200),
        ("foundation", "demon.abyss_gate", True, 199),
    ],
)
def test_demon_abyss_entry_requirements_reject_atomically(realm, location, access, reputation) -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, adapters=("qq.official",))
            user = f"demon-gate-{realm}-{location}-{access}-{reputation}"
            await _create_player(
                runtime,
                "qq.official",
                user,
                realm=realm,
                location=location,
                access=access,
                reputation=reputation,
            )
            denied = await _command(runtime, "qq.official", user, "enter", "进入秘境 魔界深渊")
            assert denied.code == "DEMON_ABYSS_REQUIREMENT_MISSING"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                stamina, runs = connection.execute(
                    "SELECT stamina, (SELECT COUNT(*) FROM secret_realm_runs WHERE player_id=players.id) "
                    "FROM players WHERE platform='qq.official' AND platform_user_id=?",
                    (user,),
                ).fetchone()
            assert stamina == 100
            assert runs == 0
            await runtime.close()

    asyncio.run(run())


def test_demon_abyss_refuses_to_overlap_another_secret_realm() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, adapters=("qq.official",))
            user = "demon-abyss-overlap"
            await _create_player(runtime, "qq.official", user)
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE players SET realm_key='qi_gathering', realm_layer=4, "
                    "location_key='cave.mist_grotto', inventory_json=? "
                    "WHERE platform='qq.official' AND platform_user_id=?",
                    (json.dumps({"item.cave_pass_basic": 1}), user),
                )
            entered = await _command(
                runtime, "qq.official", user, "other-realm", "进入秘境 雾隐秘境"
            )
            assert entered.code == "SECRET_REALM_ENTERED"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE players SET realm_key='foundation', realm_layer=1, "
                    "location_key='demon.abyss_gate' "
                    "WHERE platform='qq.official' AND platform_user_id=?",
                    (user,),
                )
            denied = await _command(
                runtime, "qq.official", user, "overlap", "进入秘境 魔界深渊"
            )
            assert denied.code == "DEMON_ABYSS_BUSY"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                stamina, count = connection.execute(
                    "SELECT stamina, (SELECT COUNT(*) FROM secret_realm_runs "
                    "WHERE player_id=players.id) FROM players "
                    "WHERE platform='qq.official' AND platform_user_id=?",
                    (user,),
                ).fetchone()
            assert (stamina, count) == (90, 1)
            await runtime.close()

    asyncio.run(run())


def test_demon_abyss_adapter_handoff_survives_runtime_restart() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            first_runtime = create_runtime(data_dir=data_dir)
            user = "demon-abyss-handoff"
            await _create_player(first_runtime, "qq.official", user)
            entered = await _command(first_runtime, "qq.official", user, "entry", "进入秘境 魔界深渊")
            assert entered.code == "DEMON_ABYSS_ENTERED"
            assert (await _command(first_runtime, "qq.official", user, "threshold", "选择秘境节点 深渊门")).ok
            assert (await _command(first_runtime, "qq.official", user, "risk", "选择秘境节点 污染渗流")).ok
            await first_runtime.close()

            second_runtime = create_runtime(data_dir=data_dir)
            # Simulate a platform identity route moving to the other adapter.
            with sqlite3.connect(second_runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE players SET platform='onebot.v11' WHERE platform='qq.official' AND platform_user_id=?",
                    (user,),
                )
            result = await _clear_realm_from_guardian(second_runtime, "onebot.v11", user, "handoff")
            assert result["outcome"] == "won"
            await second_runtime.close()

    asyncio.run(run())


async def _clear_realm_from_guardian(runtime, adapter: str, user: str, prefix: str) -> dict[str, object]:
    first_battle = await _command(runtime, adapter, user, f"{prefix}:echo", "选择秘境节点 残响守卫")
    assert first_battle.code == "DEMON_ABYSS_COMBAT_PENDING"
    advanced = await _command(runtime, adapter, user, f"{prefix}:echo-settle", "结算秘境")
    assert advanced.code == "DEMON_ABYSS_NODE_SETTLED"
    second_battle = await _command(runtime, adapter, user, f"{prefix}:heart", "选择秘境节点 深渊之心")
    assert second_battle.code == "DEMON_ABYSS_COMBAT_PENDING"
    settled = await _command(runtime, adapter, user, f"{prefix}:finish", "结算秘境")
    assert settled.code == "DEMON_ABYSS_SETTLED"
    return settled.data


def test_demon_abyss_failure_expiry_pollution_lock_and_system_compensation() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, adapters=("onebot.v11",))

            loser = "demon-abyss-loser"
            await _create_player(runtime, "onebot.v11", loser, body=0)
            await _command(runtime, "onebot.v11", loser, "loss-enter", "进入秘境 魔界深渊")
            await _command(runtime, "onebot.v11", loser, "loss-threshold", "选择秘境节点 深渊门")
            await _command(runtime, "onebot.v11", loser, "loss-risk", "选择秘境节点 污染渗流")
            await _command(runtime, "onebot.v11", loser, "loss-encounter", "选择秘境节点 残响守卫")
            lost = await _command(runtime, "onebot.v11", loser, "loss-settle", "结算秘境")
            assert lost.data["outcome"] == "lost"
            assert lost.data["reward"] == {}
            with sqlite3.connect(runtime.settings.database_path) as connection:
                loser_stamina = connection.execute(
                    "SELECT stamina FROM players WHERE platform_user_id=?", (loser,)
                ).fetchone()[0]
            assert loser_stamina == 80

            expired_user = "demon-abyss-expired"
            await _create_player(runtime, "onebot.v11", expired_user)
            expired_entry = await _command(runtime, "onebot.v11", expired_user, "expired-enter", "进入秘境 魔界深渊")
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE secret_realm_runs SET expires_at=? WHERE run_id=?",
                    ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(), expired_entry.data["run_id"]),
                )
            expired = await _command(runtime, "onebot.v11", expired_user, "expired-settle", "结算秘境")
            assert expired.data["outcome"] == "expired"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                expired_stamina = connection.execute(
                    "SELECT stamina FROM players WHERE platform_user_id=?", (expired_user,)
                ).fetchone()[0]
            assert expired_stamina == 80

            system_user = "demon-abyss-system-abort"
            await _create_player(runtime, "onebot.v11", system_user, soul_restore=1)
            started = await _command(runtime, "onebot.v11", system_user, "system-enter", "进入秘境 魔界深渊")
            locked_purify = await _command(runtime, "onebot.v11", system_user, "purify-locked", "净化污染")
            assert locked_purify.code == "SECRET_REALM_BUSY"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                run = connection.execute(
                    "SELECT id, snapshot_json FROM secret_realm_runs WHERE run_id=?", (started.data["run_id"],)
                ).fetchone()
                snapshot = json.loads(run[1])
                risk_seed = next(
                    str(index)
                    for index in range(100_000)
                    if demon_abyss_risk_roll_bp(f"{index}:pollution_seep") < 50
                )
                snapshot["random_seed"] = risk_seed
                connection.execute(
                    "UPDATE secret_realm_runs SET snapshot_json=? WHERE id=?",
                    (json.dumps(snapshot, sort_keys=True), run[0]),
                )
            await _command(runtime, "onebot.v11", system_user, "system-threshold", "选择秘境节点 深渊门")
            risk = await _command(runtime, "onebot.v11", system_user, "system-risk", "选择秘境节点 污染渗流")
            assert risk.data["pollution_after"] == 11
            compensated = await runtime.repository.compensate_demon_abyss_system_failure(
                run_id=started.data["run_id"],
                operation_id="operator:system-abort",
            )
            assert compensated.system_aborted is True
            assert compensated.pollution_after == 10
            with sqlite3.connect(runtime.settings.database_path) as connection:
                stamina, pollution, pills = connection.execute(
                    "SELECT stamina, pollution, json_extract(inventory_json, '$.\"item.pill.soul_restore\"') "
                    "FROM players WHERE platform_user_id=?",
                    (system_user,),
                ).fetchone()
            assert (stamina, pollution, pills) == (100, 10, 1)
            retried = await _command(runtime, "onebot.v11", system_user, "system-retry", "进入秘境 魔界深渊")
            assert retried.code == "DEMON_ABYSS_ENTERED"
            await runtime.close()

    asyncio.run(run())


def test_demon_abyss_pollution_risk_roll_boundaries() -> None:
    assert demon_abyss_risk_applies(0, 50)
    assert demon_abyss_risk_applies(49, 50)
    assert not demon_abyss_risk_applies(50, 50)
    assert not demon_abyss_risk_applies(-1, 50)
    assert not demon_abyss_risk_applies(0, 0)


def test_demon_abyss_expired_combat_does_not_continue_running() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, adapters=("onebot.v11",))
            user = "demon-abyss-expired-battle"
            await _create_player(runtime, "onebot.v11", user)
            entered = await _command(
                runtime, "onebot.v11", user, "entry", "进入秘境 魔界深渊"
            )
            await _command(runtime, "onebot.v11", user, "threshold", "选择秘境节点 深渊门")
            await _command(runtime, "onebot.v11", user, "risk", "选择秘境节点 污染渗流")
            battle = await _command(
                runtime, "onebot.v11", user, "encounter", "选择秘境节点 残响守卫"
            )
            assert battle.code == "DEMON_ABYSS_COMBAT_PENDING"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE secret_realm_runs SET expires_at=? WHERE run_id=?",
                    (
                        (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
                        entered.data["run_id"],
                    ),
                )
            result = await _command(runtime, "onebot.v11", user, "expired", "结算秘境")
            assert result.data["outcome"] == "expired"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                battle_status, battle_result, reward_status, stamina = connection.execute(
                    "SELECT battle_sessions.status, battle_sessions.result_json, "
                    "battle_sessions.reward_status, players.stamina FROM battle_sessions "
                    "JOIN players ON players.id=battle_sessions.player_id "
                    "WHERE battle_sessions.battle_type='pve.secret_realm.demon_abyss' "
                    "AND players.platform_user_id=?",
                    (user,),
                ).fetchone()
            assert battle_status == "settled"
            assert json.loads(battle_result)["outcome"] == "expired"
            assert reward_status == "none"
            assert stamina == 80
            await runtime.close()

    asyncio.run(run())
