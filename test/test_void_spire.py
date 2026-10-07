from __future__ import annotations

import asyncio
import json
import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from shutil import copytree
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from combat_fixtures import BALANCED_QUALIFICATION, equip_damage_weapon

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.combat.rules import enemy_definition
from nonebot_plugin_xiuxian_3.xiuxian.specials.dispatch_rules import DAO_SERVICE, DISPATCHES, choose_outcome
from nonebot_plugin_xiuxian_3.xiuxian.specials.void_spire_rules import (
    MAX_FLOOR,
    floor_definition,
)


async def _send(runtime, adapter: str, user: str, operation_id: str, command: str):
    return await runtime.adapters.dispatch(
        adapter,
        CommandContext(adapter=adapter, user_id=user, operation_id=operation_id),
        command,
    )


async def _setup(runtime, adapter: str, user: str, prefix: str, *, damage: int | None = None) -> None:
    for index, command in enumerate(
        (
            "开始修仙",
            "寻仙问道",
            "完成引导 阅读",
            "前往近郊",
            "完成引导 采集",
            "完成引导 炼丹",
            "选择道途 体修",
        )
    ):
        result = await _send(runtime, adapter, user, f"{prefix}-setup-{index}", command)
        assert result.ok, (command, result.code, result.message)
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE players SET realm_key='void_refining', realm_layer=1, stamina=100, stamina_max=100 "
            "WHERE platform=? AND platform_user_id=?",
            (adapter, user),
        )
    if damage is not None:
        equip_damage_weapon(runtime, adapter, user, damage)


def _seed_claimed_floors(connection: sqlite3.Connection, player_id: int, start: int, stop: int) -> None:
    history = "2026-01-01T00:00:00+00:00"
    connection.executemany(
        "INSERT INTO void_spire_runs(run_id,player_id,tower_key,floor_no,route_key,"
        "status,first_clear,starts_at,result_json,reward_json,created_at,updated_at) "
        "VALUES(?,?,'tower.void_spire',?,?,'claimed',1,?,'{}','{}',?,?)",
        [
            (
                f"seed-{player_id}-{floor_no}", player_id, floor_no,
                floor_definition(floor_no).route_key, history,
                history, history,
            )
            for floor_no in range(start, stop + 1)
        ],
    )


def test_void_spire_first_slice_works_on_qq_and_onebot() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(
                data_dir=data_dir,
                clock=lambda: datetime(2026, 9, 29, tzinfo=timezone.utc),
            )
            for adapter, user in (("qq.official", "void-qq"), ("onebot.v11", "void-onebot")):
                prefix = adapter.replace(".", "-")
                await _setup(runtime, adapter, user, prefix)

                preview = await _send(runtime, adapter, user, f"{prefix}-preview", "虚空塔")
                assert preview.code == "VOID_SPIRE_PREVIEW"
                assert preview.data["highest_floor"] == 0
                assert preview.data["weekly_limit"] == 2

                invalid = await _send(runtime, adapter, user, f"{prefix}-invalid", "挑战虚空塔 91")
                assert invalid.code == "INVALID_VOID_SPIRE_COMMAND"

                first = await _send(runtime, adapter, user, f"{prefix}-first", "挑战虚空塔 1")
                assert first.code == "VOID_SPIRE_CHALLENGE_SETTLED"
                assert first.data["status"] == "reward_pending"
                assert first.data["first_clear"] is True

                locked = await _send(runtime, adapter, user, f"{prefix}-locked", "挑战虚空塔 2")
                assert locked.code == "VOID_SPIRE_BUSY"

                claim = await _send(runtime, adapter, user, f"{prefix}-claim", "领取虚空塔奖励")
                assert claim.code == "VOID_SPIRE_REWARD_CLAIMED"
                assert claim.data["first_clear"] is True
                replay = await _send(runtime, adapter, user, f"{prefix}-claim", "领取虚空塔奖励")
                assert replay.ok and replay.data["idempotent_replay"] is True

                second = await _send(runtime, adapter, user, f"{prefix}-second", "挑战虚空塔 1")
                assert second.code == "VOID_SPIRE_CHALLENGE_SETTLED"
                assert second.data["first_clear"] is False
                practice_claim = await _send(runtime, adapter, user, f"{prefix}-practice-claim", "领取虚空塔奖励")
                assert practice_claim.code == "VOID_SPIRE_REWARD_CLAIMED"

                third = await _send(runtime, adapter, user, f"{prefix}-third", "挑战虚空塔 1")
                assert third.code == "VOID_SPIRE_WEEKLY_LIMIT"

                with sqlite3.connect(runtime.settings.database_path) as connection:
                    rows = connection.execute(
                        "SELECT void_spire_runs.route_key, void_spire_runs.floor_no FROM void_spire_runs "
                        "JOIN players ON players.id=void_spire_runs.player_id "
                        "WHERE players.platform=? AND players.platform_user_id=? ORDER BY void_spire_runs.id",
                        (adapter, user),
                    ).fetchall()
                    assert rows and rows[0][0] == "storm"
                    codex = connection.execute(
                        "SELECT entry_key FROM codex_entries JOIN players ON players.id=codex_entries.player_id "
                        "WHERE players.platform=? AND players.platform_user_id=? AND entry_key LIKE 'codex.void.%'",
                        (adapter, user),
                    ).fetchall()
                    assert ("codex.void.route_spire_storm",) in codex
            await runtime.close()

    asyncio.run(run())


def test_void_spire_reward_snapshots_and_operation_replays_are_strict_on_both_adapters() -> None:
    async def run() -> None:
        malformed_rewards = (
            '{"spirit_stones":120,"spirit_stones":9999}',
            '{"spirit_stones":',
            '[]',
            '{"spirit_stones":-1}',
            '{"spirit_stones":true}',
            '{"spirit_stones":"120"}',
        )
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            replay_cases: list[tuple[str, str, str]] = []
            for adapter in ("qq.official", "onebot.v11"):
                user = f"strict-reward-{adapter.replace('.', '-')}"
                await _setup(runtime, adapter, user, user)
                challenge = await _send(runtime, adapter, user, f"{user}-challenge", "挑战虚空塔 1")
                assert challenge.code == "VOID_SPIRE_CHALLENGE_SETTLED"
                claim_operation = f"{user}-claim"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    player_id, run_id, valid_reward = connection.execute(
                        "SELECT players.id, void_spire_runs.run_id, void_spire_runs.reward_json "
                        "FROM players JOIN void_spire_runs ON players.id=void_spire_runs.player_id "
                        "WHERE players.platform=? AND players.platform_user_id=?",
                        (adapter, user),
                    ).fetchone()
                    before = connection.execute(
                        "SELECT spirit_stones, inventory_json FROM players WHERE id=?", (player_id,)
                    ).fetchone()

                for index, malformed in enumerate(malformed_rewards):
                    operation_id = f"{claim_operation}-{index}"
                    with sqlite3.connect(runtime.settings.database_path) as connection:
                        connection.execute(
                            "UPDATE void_spire_runs SET reward_json=? WHERE run_id=?", (malformed, run_id)
                        )
                    failed = await _send(runtime, adapter, user, operation_id, "领取虚空塔奖励")
                    assert failed.code == "PERSISTENCE_ERROR"
                    with sqlite3.connect(runtime.settings.database_path) as connection:
                        assert connection.execute(
                            "SELECT spirit_stones, inventory_json FROM players WHERE id=?", (player_id,)
                        ).fetchone() == before
                        assert connection.execute(
                            "SELECT status FROM void_spire_runs WHERE run_id=?", (run_id,)
                        ).fetchone()[0] == "reward_pending"
                        assert connection.execute(
                            "SELECT COUNT(*) FROM void_spire_reward_claims WHERE run_id=?", (run_id,)
                        ).fetchone()[0] == 0
                        assert connection.execute(
                            "SELECT COUNT(*) FROM operations WHERE operation_id=?", (operation_id,)
                        ).fetchone()[0] == 0

                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE void_spire_runs SET reward_json=? WHERE run_id=?", (valid_reward, run_id)
                    )
                settled = await _send(runtime, adapter, user, claim_operation, "领取虚空塔奖励")
                assert settled.code == "VOID_SPIRE_REWARD_CLAIMED"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    stored_start = connection.execute(
                        "SELECT result_json FROM operations WHERE operation_id=?",
                        (f"{user}-challenge",),
                    ).fetchone()[0]
                    start_payload = json.loads(stored_start)
                    start_payload["floor_no"] = 2
                    connection.execute(
                        "UPDATE operations SET result_json=? WHERE operation_id=?",
                        (json.dumps(start_payload), f"{user}-challenge"),
                    )
                tampered_start = await _send(
                    runtime, adapter, user, f"{user}-challenge", "挑战虚空塔 1"
                )
                assert tampered_start.code == "PERSISTENCE_ERROR"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE operations SET result_json=? WHERE operation_id=?",
                        (stored_start, f"{user}-challenge"),
                    )
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE void_spire_runs SET reward_json=? WHERE run_id=?",
                        ('{"spirit_stones":', run_id),
                    )
                corrupted_run_replay = await _send(
                    runtime, adapter, user, f"{user}-challenge", "挑战虚空塔 1"
                )
                assert corrupted_run_replay.code == "PERSISTENCE_ERROR"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE void_spire_runs SET reward_json=? WHERE run_id=?", (valid_reward, run_id)
                    )
                    stored_operation = connection.execute(
                        "SELECT result_json FROM operations WHERE operation_id=?", (claim_operation,)
                    ).fetchone()[0]
                    player_after_claim = connection.execute(
                        "SELECT spirit_stones, inventory_json FROM players WHERE id=?", (player_id,)
                    ).fetchone()
                    assert connection.execute(
                        "SELECT COUNT(*) FROM void_spire_reward_claims WHERE run_id=?", (run_id,)
                    ).fetchone()[0] == 1
                    valid_payload = json.loads(stored_operation)
                    valid_payload["reward"]["spirit_stones"] = 9999
                    connection.execute(
                        "UPDATE operations SET result_json=? WHERE operation_id=?",
                        (json.dumps(valid_payload), claim_operation),
                    )
                tampered_claim = await _send(runtime, adapter, user, claim_operation, "领取虚空塔奖励")
                assert tampered_claim.code == "PERSISTENCE_ERROR"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE operations SET result_json=? WHERE operation_id=?",
                        (stored_operation, claim_operation),
                    )
                    assert connection.execute(
                        "SELECT spirit_stones, inventory_json FROM players WHERE id=?", (player_id,)
                    ).fetchone() == player_after_claim
                    corrupted_operation = stored_operation.replace(
                        '"reward":', '"reward":{},"reward":', 1
                    )
                    connection.execute(
                        "UPDATE operations SET result_json=? WHERE operation_id=?",
                        (corrupted_operation, claim_operation),
                    )
                failed_replay = await _send(runtime, adapter, user, claim_operation, "领取虚空塔奖励")
                assert failed_replay.code == "PERSISTENCE_ERROR"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    assert connection.execute(
                        "SELECT spirit_stones, inventory_json FROM players WHERE id=?", (player_id,)
                    ).fetchone() == player_after_claim
                    assert connection.execute(
                        "SELECT COUNT(*) FROM void_spire_reward_claims WHERE run_id=?", (run_id,)
                    ).fetchone()[0] == 1
                    connection.execute(
                        "UPDATE operations SET result_json=? WHERE operation_id=?",
                        (stored_operation, claim_operation),
                    )
                replay = await _send(runtime, adapter, user, claim_operation, "领取虚空塔奖励")
                assert replay.code == "VOID_SPIRE_REWARD_CLAIMED"
                assert replay.data["idempotent_replay"] is True
                replay_cases.append((adapter, user, claim_operation))
            await runtime.close()
            restarted = create_runtime(data_dir=data_dir)
            for adapter, user, operation_id in replay_cases:
                replay = await _send(restarted, adapter, user, operation_id, "领取虚空塔奖励")
                assert replay.code == "VOID_SPIRE_REWARD_CLAIMED"
                assert replay.data["idempotent_replay"] is True
            await restarted.close()

    asyncio.run(run())


def test_void_spire_rules_and_content_records_are_stable() -> None:
    assert MAX_FLOOR == 90
    assert floor_definition(15).boss is True
    assert floor_definition(15).route_key == "storm"
    assert floor_definition(30).boss is True
    assert floor_definition(30).route_key == "echo"
    assert floor_definition(45).boss is True
    assert floor_definition(45).route_key == "inscription"
    assert floor_definition(60).boss is True
    assert floor_definition(60).route_key == "witness"
    assert floor_definition(31).weekly_limit == 1
    assert floor_definition(30).route_key != floor_definition(31).route_key
    with open("data/战斗/敌人.json", encoding="utf-8") as handle:
        records = {row["key"]: row for row in json.load(handle)["records"]}
    expected = {
        "enemy.void_spire.scout",
        "enemy.void_spire.sentinel",
        "enemy.void_spire.watcher",
        "enemy.void_spire.warlord",
        "enemy.void_spire.route_storm_boss",
        "enemy.void_spire.route_echo_boss",
        "enemy.void_spire.scribe",
        "enemy.void_spire.keeper",
        "enemy.void_spire.route_inscription_boss",
        "enemy.void_spire.echo_warden",
        "enemy.void_spire.origin_guard",
        "enemy.void_spire.route_witness_boss",
    }
    assert expected <= records.keys()
    for key in expected:
        row = records[key]
        definition = enemy_definition(key)
        assert (definition.max_hp, definition.attack, definition.label) == (
            row["stats"]["hp"], row["stats"]["attack"], row["name"]
        )


def test_void_spire_claim_failure_rolls_back_and_retries_same_operation(monkeypatch) -> None:
    async def run() -> None:
        from nonebot_plugin_xiuxian_3.xiuxian.specials import void_spire_repository

        def fail_codex(*args, **kwargs):
            raise RuntimeError("codex write failed")

        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            for adapter in ("qq.official", "onebot.v11"):
                user = f"claim-retry-{adapter.replace('.', '-')}"
                await _setup(runtime, adapter, user, user)
                challenge = await _send(runtime, adapter, user, f"{user}-challenge", "挑战虚空塔 1")
                assert challenge.code == "VOID_SPIRE_CHALLENGE_SETTLED"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    player_id, before = connection.execute(
                        "SELECT id, spirit_stones FROM players WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    ).fetchone()
                monkeypatch.setattr(
                    void_spire_repository,
                    "record_codex_discovery",
                    fail_codex,
                )
                failed = await _send(runtime, adapter, user, f"{user}-claim", "领取虚空塔奖励")
                assert failed.code == "PERSISTENCE_ERROR"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    assert connection.execute(
                        "SELECT spirit_stones FROM players WHERE id=?", (player_id,)
                    ).fetchone()[0] == before
                    assert connection.execute(
                        "SELECT status FROM void_spire_runs WHERE run_id=?", (challenge.data["run_id"],)
                    ).fetchone()[0] == "reward_pending"
                    assert connection.execute(
                        "SELECT COUNT(*) FROM void_spire_reward_claims WHERE run_id=?", (challenge.data["run_id"],)
                    ).fetchone()[0] == 0
                monkeypatch.setattr(
                    void_spire_repository,
                    "record_codex_discovery",
                    original_record_codex_discovery,
                )
                claimed = await _send(runtime, adapter, user, f"{user}-claim", "领取虚空塔奖励")
                assert claimed.code == "VOID_SPIRE_REWARD_CLAIMED"
            await runtime.close()

    from nonebot_plugin_xiuxian_3.xiuxian.specials.void_spire_repository import record_codex_discovery

    original_record_codex_discovery = record_codex_discovery
    asyncio.run(run())


def test_void_spire_reputation_boundary_and_previous_floor_lock() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            await _setup(runtime, "qq.official", "reputation", "reputation")
            with sqlite3.connect(runtime.settings.database_path) as connection:
                player_id = connection.execute(
                    "SELECT id FROM players WHERE platform='qq.official' AND platform_user_id='reputation'"
                ).fetchone()[0]
                connection.execute("UPDATE players SET realm_key='qi_sensing',realm_layer=1 WHERE id=?", (player_id,))
                connection.execute(
                    "INSERT INTO player_reputations(player_id,local_json,service_reputation,updated_at) "
                    "VALUES(?,?,0,?)",
                    (player_id, json.dumps({"local.void_supply": 599}), "2026-01-01T00:00:00+00:00"),
                )
            denied = await _send(runtime, "qq.official", "reputation", "deny-599", "挑战虚空塔 1")
            assert denied.code == "VOID_SPIRE_REQUIREMENT_MISSING"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE player_reputations SET local_json=? WHERE player_id=?",
                    (json.dumps({"local.void_supply": 600}), player_id),
                )
            locked = await _send(runtime, "qq.official", "reputation", "locked-2", "挑战虚空塔 2")
            assert locked.code == "VOID_SPIRE_FLOOR_LOCKED"
            first = await _send(runtime, "qq.official", "reputation", "first-600", "挑战虚空塔 1")
            assert first.code == "VOID_SPIRE_CHALLENGE_SETTLED"
            await runtime.close()

    asyncio.run(run())


def test_void_spire_reputation_read_failure_is_atomic_and_recoverable() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            cases = (("qq.official", "reputation-json-qq"), ("onebot.v11", "reputation-json-onebot"))
            for adapter, user in cases:
                await _setup(runtime, adapter, user, user, damage=500)
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    player_id = connection.execute(
                        "SELECT id FROM players WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    ).fetchone()[0]
                    connection.execute(
                        "UPDATE players SET realm_key='qi_sensing', realm_layer=1, stamina=100, stamina_max=100 WHERE id=?",
                        (player_id,),
                    )
                    connection.execute(
                        "INSERT INTO player_reputations(player_id, local_json, service_reputation, updated_at) "
                        "VALUES (?, '{', 0, 'before') "
                        "ON CONFLICT(player_id) DO UPDATE SET local_json=excluded.local_json",
                        (player_id,),
                    )
                failed = await _send(runtime, adapter, user, f"{user}-start", "挑战虚空塔 1")
                assert failed.code == "PERSISTENCE_ERROR"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    assert connection.execute("SELECT stamina FROM players WHERE id=?", (player_id,)).fetchone()[0] == 100
                    assert connection.execute("SELECT COUNT(*) FROM void_spire_runs WHERE player_id=?", (player_id,)).fetchone()[0] == 0
                    connection.execute(
                        "UPDATE player_reputations SET local_json=? WHERE player_id=?",
                        (json.dumps({"local.void_supply": 600}), player_id),
                    )
                settled = await _send(runtime, adapter, user, f"{user}-start", "挑战虚空塔 1")
                assert settled.code == "VOID_SPIRE_CHALLENGE_SETTLED"
                replay = await _send(runtime, adapter, user, f"{user}-start", "挑战虚空塔 1")
                assert replay.code == settled.code
                assert replay.data["idempotent_replay"] is True
            await runtime.close()

            recovered = create_runtime(data_dir=data_dir)
            for adapter, user in cases:
                replay = await _send(recovered, adapter, user, f"{user}-start", "挑战虚空塔 1")
                assert replay.code == "VOID_SPIRE_CHALLENGE_SETTLED"
                assert replay.data["idempotent_replay"] is True
            await recovered.close()

    asyncio.run(run())


def test_void_spire_start_failure_refunds_and_replay_is_failure(monkeypatch) -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            await _setup(runtime, "onebot.v11", "failure", "failure")
            original = runtime.repository.start_quest_battle

            async def fail_start(**kwargs):
                raise RuntimeError("battle unavailable")

            monkeypatch.setattr(runtime.repository, "start_quest_battle", fail_start)
            failed = await _send(runtime, "onebot.v11", "failure", "failure-start", "挑战虚空塔 1")
            assert failed.code == "VOID_SPIRE_START_FAILED"
            replay = await _send(runtime, "onebot.v11", "failure", "failure-start", "挑战虚空塔 1")
            assert replay.code == "VOID_SPIRE_START_FAILED"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute(
                    "SELECT status FROM void_spire_runs"
                ).fetchall() == [("aborted",)]
                assert connection.execute(
                    "SELECT stamina FROM players WHERE platform='onebot.v11' AND platform_user_id='failure'"
                ).fetchone()[0] == 100
            preview = await _send(runtime, "onebot.v11", "failure", "failure-preview", "虚空塔")
            assert preview.data["weekly_used"] == 0
            monkeypatch.setattr(runtime.repository, "start_quest_battle", original)
            retry = await _send(runtime, "onebot.v11", "failure", "failure-retry", "挑战虚空塔 1")
            assert retry.code == "VOID_SPIRE_CHALLENGE_SETTLED"
            await runtime.close()

    asyncio.run(run())


def test_void_spire_losses_count_against_weekly_limit_without_rewards(monkeypatch) -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            await _setup(runtime, "qq.official", "loser", "loser")
            original_enemy_definition = enemy_definition

            def overpowering_enemy(enemy_key: str, *, content=None):
                enemy = original_enemy_definition(enemy_key, content=content)
                if enemy_key == "enemy.void_spire.scout":
                    return replace(enemy, max_hp=200000, attack=10000, initiative=10000, agility=10000)
                return enemy

            monkeypatch.setattr(
                "nonebot_plugin_xiuxian_3.xiuxian.combat.repository.enemy_definition",
                overpowering_enemy,
            )
            for index in range(2):
                lost = await _send(runtime, "qq.official", "loser", f"loss-{index}", "挑战虚空塔 1")
                assert lost.code == "VOID_SPIRE_CHALLENGE_SETTLED"
                assert lost.data["status"] == "lost"
                claim = await _send(runtime, "qq.official", "loser", f"loss-claim-{index}", "领取虚空塔奖励")
                assert claim.code == "VOID_SPIRE_REWARD_NOT_AVAILABLE"
            capped = await _send(runtime, "qq.official", "loser", "loss-capped", "挑战虚空塔 1")
            assert capped.code == "VOID_SPIRE_WEEKLY_LIMIT"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute("SELECT COUNT(*) FROM void_spire_reward_claims").fetchone()[0] == 0
                assert connection.execute("SELECT stamina FROM players WHERE platform_user_id='loser'").fetchone()[0] == 60
            await runtime.close()

    asyncio.run(run())


def test_void_spire_route_bosses_keep_battle_and_claim_snapshots() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            for floor_no, adapter in ((15, "qq.official"), (30, "onebot.v11")):
                user = f"boss-{floor_no}"
                await _setup(runtime, adapter, user, user, damage=500)
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    player_id = connection.execute(
                        "SELECT id FROM players WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    ).fetchone()[0]
                    connection.execute(
                        "UPDATE players SET qualification_json=?,max_hp=30000,initiative=30000 WHERE id=?",
                        (json.dumps(BALANCED_QUALIFICATION), player_id),
                    )
                    history = "2026-01-01T00:00:00+00:00"
                    connection.executemany(
                        "INSERT INTO void_spire_runs(run_id,player_id,tower_key,floor_no,route_key,"
                        "status,first_clear,starts_at,result_json,reward_json,created_at,updated_at) "
                        "VALUES(?,?,'tower.void_spire',?,?,'claimed',1,?,'{}','{}',?,?)",
                        [
                            (
                                f"{user}-historical-{previous}", player_id, previous,
                                floor_definition(previous).route_key, history,
                                history, history,
                            )
                            for previous in range(1, floor_no)
                        ],
                    )
                challenge = await _send(runtime, adapter, user, f"{user}-challenge", f"挑战虚空塔 {floor_no}")
                assert challenge.code == "VOID_SPIRE_CHALLENGE_SETTLED"
                assert challenge.data["outcome"] == "won"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    snapshot, reward_status = connection.execute(
                        "SELECT b.snapshot_json,b.reward_status "
                        "FROM battle_sessions b JOIN void_spire_runs t ON b.battle_id=t.battle_id "
                        "WHERE t.run_id=?",
                        (challenge.data["run_id"],),
                    ).fetchone()
                    assert json.loads(snapshot)["enemy"]["key"] == floor_definition(floor_no).enemy_key
                    assert reward_status == "none"
                    connection.execute(
                        "INSERT INTO player_reputations(player_id,local_json,service_reputation,updated_at) "
                        "VALUES(?,?,0,'before-claim') ON CONFLICT(player_id) DO UPDATE SET local_json=excluded.local_json",
                        (player_id, json.dumps({"local.void_supply": 990})),
                    )
                reward = await _send(runtime, adapter, user, f"{user}-reward", "领取虚空塔奖励")
                assert reward.code == "VOID_SPIRE_REWARD_CLAIMED"
                assert reward.data["reward"]["local.void_supply"] == 30
                replay = await _send(runtime, adapter, user, f"{user}-reward", "领取虚空塔奖励")
                assert replay.ok and replay.data["idempotent_replay"] is True
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    local_json, = connection.execute(
                        "SELECT local_json FROM player_reputations WHERE player_id=?", (player_id,)
                    ).fetchone()
                    assert json.loads(local_json)["local.void_supply"] == 1000
                    keys = {
                        row[0] for row in connection.execute(
                            "SELECT entry_key FROM codex_entries WHERE player_id=?", (player_id,)
                        )
                    }
                    assert f"codex.challenge.void_spire.floor_{floor_no}" in keys
                    assert f"codex.void.route_spire_{floor_definition(floor_no).route_key}" in keys
            await runtime.close()

    asyncio.run(run())


def test_void_spire_running_battle_resumes_after_restart(monkeypatch) -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            adapter, user, operation = "onebot.v11", "restart", "restart-challenge"
            await _setup(runtime, adapter, user, "restart")

            async def keep_running(**kwargs):
                return SimpleNamespace(status="running")

            monkeypatch.setattr(runtime.repository, "run_battle_turn", keep_running)
            pending = await _send(runtime, adapter, user, operation, "挑战虚空塔 1")
            assert pending.code == "VOID_SPIRE_NOT_READY"
            await runtime.close()

            restarted = create_runtime(data_dir=data_dir)
            resumed = await _send(restarted, adapter, user, operation, "挑战虚空塔 1")
            assert resumed.code == "VOID_SPIRE_CHALLENGE_SETTLED"
            assert resumed.data["status"] == "reward_pending"
            with sqlite3.connect(restarted.settings.database_path) as connection:
                assert connection.execute("SELECT COUNT(*) FROM void_spire_runs").fetchone()[0] == 1
                assert connection.execute(
                    "SELECT stamina FROM players WHERE platform=? AND platform_user_id=?", (adapter, user)
                ).fetchone()[0] == 80
            await restarted.close()

    asyncio.run(run())


def test_void_spire_enemy_uses_host_content_override(tmp_path: Path) -> None:
    async def run() -> None:
        content_dir = tmp_path / "data"
        copytree(Path(__file__).parents[1] / "data", content_dir)
        enemy_file = content_dir / "战斗" / "敌人.json"
        document = json.loads(enemy_file.read_text(encoding="utf-8"))
        scout = next(row for row in document["records"] if row["key"] == "enemy.void_spire.scout")
        scout["stats"]["hp"] = 125
        enemy_file.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")

        runtime = create_runtime(data_dir=content_dir)
        await _setup(runtime, "qq.official", "content-override", "content-override")
        challenge = await _send(runtime, "qq.official", "content-override", "override-1", "挑战虚空塔 1")
        assert challenge.data["outcome"] == "won"
        with sqlite3.connect(runtime.settings.database_path) as connection:
            snapshot = connection.execute(
                "SELECT snapshot_json FROM battle_sessions WHERE battle_id=?", (challenge.data["battle_id"],)
            ).fetchone()[0]
            assert json.loads(snapshot)["enemy"]["max_hp"] == 125
        await runtime.close()

    asyncio.run(run())


def test_void_spire_upper_floors_have_independent_weekly_quota_on_both_adapters() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=lambda: datetime(2026, 9, 29, tzinfo=timezone.utc))
            for adapter, user in (("qq.official", "upper-qq"), ("onebot.v11", "upper-onebot")):
                await _setup(runtime, adapter, user, user, damage=500)
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    player_id = connection.execute(
                        "SELECT id FROM players WHERE platform=? AND platform_user_id=?", (adapter, user)
                    ).fetchone()[0]
                    _seed_claimed_floors(connection, player_id, 1, 30)
                    connection.execute(
                        "UPDATE players SET realm_key='dao_union',realm_layer=1,stamina=200,stamina_max=200,"
                        "max_hp=30000,initiative=30000,qualification_json=? WHERE id=?",
                        (json.dumps(BALANCED_QUALIFICATION), player_id),
                    )
                preview = await _send(runtime, adapter, user, f"{user}-preview", "虚空塔")
                assert (preview.data["next_floor"], preview.data["weekly_used"], preview.data["weekly_limit"]) == (31, 0, 1)
                lower = await _send(runtime, adapter, user, f"{user}-lower-1", "挑战虚空塔 30")
                assert lower.data["outcome"] == "won"
                assert (await _send(runtime, adapter, user, f"{user}-lower-claim-1", "领取虚空塔奖励")).ok

                upper = await _send(runtime, adapter, user, f"{user}-upper-31", "挑战虚空塔 31")
                assert upper.code == "VOID_SPIRE_CHALLENGE_SETTLED"
                assert upper.data["status"] == "reward_pending"
                assert upper.data["reward"] == {}
                claim = await _send(runtime, adapter, user, f"{user}-upper-claim", "领取虚空塔奖励")
                assert claim.code == "VOID_SPIRE_REWARD_CLAIMED"
                assert set(claim.data["discoveries"]) == {
                    "codex.void.route_spire_inscription", "codex.challenge.void_spire.floor_31",
                }
                assert claim.data["title"] is None
                replay = await _send(runtime, adapter, user, f"{user}-upper-claim", "领取虚空塔奖励")
                assert replay.data["idempotent_replay"] is True
                assert replay.data["discoveries"] == claim.data["discoveries"]
                capped = await _send(runtime, adapter, user, f"{user}-upper-32", "挑战虚空塔 32")
                assert capped.code == "VOID_SPIRE_WEEKLY_LIMIT"

                second_lower = await _send(runtime, adapter, user, f"{user}-lower-2", "挑战虚空塔 30")
                assert second_lower.data["outcome"] == "won"
                assert (await _send(runtime, adapter, user, f"{user}-lower-claim-2", "领取虚空塔奖励")).ok
                assert (await _send(runtime, adapter, user, f"{user}-lower-3", "挑战虚空塔 30")).code == "VOID_SPIRE_WEEKLY_LIMIT"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    battle = connection.execute(
                        "SELECT b.snapshot_json,b.reward_status "
                        "FROM battle_sessions b JOIN void_spire_runs t ON t.battle_id=b.battle_id "
                        "WHERE t.run_id=?", (upper.data["run_id"],)
                    ).fetchone()
                    assert json.loads(battle[0])["enemy"]["key"] == floor_definition(31).enemy_key
                    assert battle[1] == "none"
                    assert connection.execute(
                        "SELECT stamina FROM players WHERE id=?", (player_id,)
                    ).fetchone()[0] == 140
            await runtime.close()

    asyncio.run(run())


def test_void_spire_upper_reputation_gate_boss_stories_and_display_title() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=lambda: datetime(2026, 9, 29, tzinfo=timezone.utc))
            for floor_no, adapter in ((31, "qq.official"), (45, "onebot.v11"), (60, "qq.official")):
                user = f"high-{floor_no}"
                await _setup(runtime, adapter, user, user, damage=500)
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    player_id = connection.execute(
                        "SELECT id FROM players WHERE platform=? AND platform_user_id=?", (adapter, user)
                    ).fetchone()[0]
                    _seed_claimed_floors(connection, player_id, 1, floor_no - 1)
                    connection.execute(
                        "UPDATE players SET max_hp=30000,initiative=30000,qualification_json=? WHERE id=?",
                        (json.dumps(BALANCED_QUALIFICATION), player_id),
                    )
                    connection.execute(
                        "INSERT INTO player_reputations(player_id,local_json,service_reputation,updated_at) "
                        "VALUES(?,?,100,?)",
                        (player_id, json.dumps({"local.dao_service": 699}), "2026-01-01T00:00:00+00:00"),
                    )
                denied = await _send(runtime, adapter, user, f"{user}-denied", f"挑战虚空塔 {floor_no}")
                assert denied.code == "VOID_SPIRE_REQUIREMENT_MISSING"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE player_reputations SET local_json=? WHERE player_id=?",
                        (json.dumps({"local.dao_service": 700}), player_id),
                    )
                challenge = await _send(runtime, adapter, user, f"{user}-challenge", f"挑战虚空塔 {floor_no}")
                assert challenge.data["outcome"] == "won"
                assert challenge.data["route_key"] == floor_definition(floor_no).route_key
                assert challenge.data["reward"] == {}
                claim = await _send(runtime, adapter, user, f"{user}-claim", "领取虚空塔奖励")
                assert claim.data["reward"] == {}
                assert f"codex.challenge.void_spire.floor_{floor_no}" in claim.data["discoveries"]
                if floor_no in (45, 60):
                    assert f"codex.story.void_spire.{floor_definition(floor_no).route_key}" in claim.data["discoveries"]
                if floor_no == 60:
                    assert claim.data["title"] == "虚空见证者"
                    honors = await _send(runtime, adapter, user, f"{user}-honors", "功业录")
                    assert next(
                        item for item in honors.data["titles"]
                        if item["title_key"] == "title.void_spire.witness"
                    )["acquired"] is True
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    assert connection.execute(
                        "SELECT COUNT(*) FROM codex_entries WHERE player_id=? AND entry_key=?",
                        (player_id, f"codex.challenge.void_spire.floor_{floor_no}"),
                    ).fetchone()[0] == 1
                    snapshot_json, reward_status = connection.execute(
                        "SELECT b.snapshot_json,b.reward_status "
                        "FROM battle_sessions b JOIN void_spire_runs t ON t.battle_id=b.battle_id "
                        "WHERE t.run_id=?", (challenge.data["run_id"],)
                    ).fetchone()
                    assert json.loads(snapshot_json)["enemy"]["key"] == floor_definition(floor_no).enemy_key
                    assert reward_status == "none"
            await runtime.close()

    asyncio.run(run())


def test_dao_service_dispatch_produces_upper_floor_admission_on_both_adapters(monkeypatch) -> None:
    async def run() -> None:
        now = [datetime(2026, 9, 29, tzinfo=timezone.utc)]
        successful = (
            f"{seed:032x}" for seed in range(100)
            if choose_outcome(DISPATCHES[DAO_SERVICE], f"{seed:032x}") == "success"
        )
        uuid_values = iter(
            (next(successful), "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
             next(successful), "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb")
        )
        monkeypatch.setattr(
            "nonebot_plugin_xiuxian_3.xiuxian.specials.dispatch_repository.uuid4",
            lambda: SimpleNamespace(hex=next(uuid_values)),
        )
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=lambda: now[0])
            for adapter, user in (("qq.official", "service-qq"), ("onebot.v11", "service-onebot")):
                await _setup(runtime, adapter, user, user, damage=500)
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    player_id = connection.execute(
                        "SELECT id FROM players WHERE platform=? AND platform_user_id=?", (adapter, user)
                    ).fetchone()[0]
                    _seed_claimed_floors(connection, player_id, 1, 30)
                    connection.execute(
                        "UPDATE players SET max_hp=30000,initiative=30000,qualification_json=? WHERE id=?",
                        (json.dumps(BALANCED_QUALIFICATION), player_id),
                    )
                    connection.execute(
                        "INSERT INTO player_reputations(player_id,local_json,service_reputation,updated_at) "
                        "VALUES(?,?,80,?)",
                        (player_id, json.dumps({"local.dao_service": 696}), now[0].isoformat()),
                    )
                before = await _send(runtime, adapter, user, f"{user}-before", "挑战虚空塔 31")
                assert before.code == "VOID_SPIRE_REQUIREMENT_MISSING"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE player_reputations SET local_json=?,service_reputation=98 WHERE player_id=?",
                        (json.dumps({"local.dao_service": 996}), player_id),
                    )
                preview = await _send(runtime, adapter, user, f"{user}-dispatch-preview", "派遣预览 道统服务")
                assert preview.data["dispatches"][0]["ready"] is True
                accepted = await _send(runtime, adapter, user, f"{user}-accept", "接受派遣 道统服务")
                assert accepted.code == "DISPATCH_ACCEPTED"
                assert accepted.data["outcome"] == "success"
                now[0] += timedelta(hours=8, seconds=1)
                settled = await _send(runtime, adapter, user, f"{user}-settle", "结算派遣")
                assert settled.code == "DISPATCH_SETTLED"
                assert settled.data["reward"]["local.dao_service"] == 4
                replay = await _send(runtime, adapter, user, f"{user}-settle", "结算派遣")
                assert replay.data["idempotent_replay"] is True
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    local_json, service = connection.execute(
                        "SELECT local_json,service_reputation FROM player_reputations WHERE player_id=?",
                        (player_id,),
                    ).fetchone()
                    assert json.loads(local_json)["local.dao_service"] == 1000
                    assert service == 100
                upper = await _send(runtime, adapter, user, f"{user}-upper", "挑战虚空塔 31")
                assert upper.code == "VOID_SPIRE_CHALLENGE_SETTLED" and upper.data["outcome"] == "won"
                assert (await _send(runtime, adapter, user, f"{user}-claim", "领取虚空塔奖励")).ok
            await runtime.close()

    asyncio.run(run())


def test_void_spire_upper_start_failure_and_restart_keep_quota_and_stamina(monkeypatch) -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            clock = lambda: datetime(2026, 9, 29, tzinfo=timezone.utc)
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            adapter, user = "onebot.v11", "upper-recovery"
            await _setup(runtime, adapter, user, user, damage=500)
            with sqlite3.connect(runtime.settings.database_path) as connection:
                player_id = connection.execute(
                    "SELECT id FROM players WHERE platform=? AND platform_user_id=?", (adapter, user)
                ).fetchone()[0]
                _seed_claimed_floors(connection, player_id, 1, 30)
                connection.execute(
                    "UPDATE players SET realm_key='dao_union',realm_layer=1,"
                    "max_hp=30000,initiative=30000,qualification_json=? WHERE id=?",
                    (json.dumps(BALANCED_QUALIFICATION), player_id),
                )

            original = runtime.repository.start_quest_battle

            async def fail_start(**kwargs):
                raise RuntimeError("battle unavailable")

            monkeypatch.setattr(runtime.repository, "start_quest_battle", fail_start)
            failed = await _send(runtime, adapter, user, "upper-failed", "挑战虚空塔 31")
            assert failed.code == "VOID_SPIRE_START_FAILED"
            assert (await _send(runtime, adapter, user, "upper-failed", "挑战虚空塔 31")).code == failed.code
            assert (await _send(runtime, adapter, user, "upper-preview", "虚空塔")).data["weekly_used"] == 0
            monkeypatch.setattr(runtime.repository, "start_quest_battle", original)

            async def keep_running(**kwargs):
                return SimpleNamespace(status="running")

            monkeypatch.setattr(runtime.repository, "run_battle_turn", keep_running)
            pending = await _send(runtime, adapter, user, "upper-pending", "挑战虚空塔 31")
            assert pending.code == "VOID_SPIRE_NOT_READY"
            await runtime.close()

            restarted = create_runtime(data_dir=data_dir, clock=clock)
            resolved = await _send(restarted, adapter, user, "upper-pending", "挑战虚空塔 31")
            assert resolved.code == "VOID_SPIRE_CHALLENGE_SETTLED"
            assert resolved.data["status"] == "reward_pending"
            assert (await _send(restarted, adapter, user, "upper-claim", "领取虚空塔奖励")).ok
            assert (await _send(restarted, adapter, user, "upper-capped", "挑战虚空塔 31")).code == "VOID_SPIRE_WEEKLY_LIMIT"
            with sqlite3.connect(restarted.settings.database_path) as connection:
                statuses = connection.execute(
                    "SELECT status FROM void_spire_runs WHERE player_id=? AND floor_no=31 ORDER BY id",
                    (player_id,),
                ).fetchall()
                assert statuses == [("aborted",), ("claimed",)]
                assert connection.execute(
                    "SELECT stamina FROM players WHERE id=?", (player_id,)
                ).fetchone()[0] == 80
            await restarted.close()

    asyncio.run(run())


def test_void_spire_upper_concurrent_requests_take_only_one_quota_slot() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=lambda: datetime(2026, 9, 29, tzinfo=timezone.utc))
            adapter, user = "onebot.v11", "upper-concurrent"
            await _setup(runtime, adapter, user, user, damage=500)
            with sqlite3.connect(runtime.settings.database_path) as connection:
                player_id = connection.execute(
                    "SELECT id FROM players WHERE platform=? AND platform_user_id=?", (adapter, user)
                ).fetchone()[0]
                _seed_claimed_floors(connection, player_id, 1, 30)
                connection.execute(
                    "UPDATE players SET realm_key='dao_union',realm_layer=1,"
                    "max_hp=30000,initiative=30000,qualification_json=? WHERE id=?",
                    (json.dumps(BALANCED_QUALIFICATION), player_id),
                )
            results = await asyncio.gather(
                _send(runtime, adapter, user, "upper-concurrent-1", "挑战虚空塔 31"),
                _send(runtime, adapter, user, "upper-concurrent-2", "挑战虚空塔 31"),
            )
            assert sorted(result.code for result in results) == [
                "VOID_SPIRE_BUSY", "VOID_SPIRE_CHALLENGE_SETTLED",
            ]
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute(
                    "SELECT COUNT(*) FROM void_spire_runs WHERE player_id=? AND floor_no=31", (player_id,)
                ).fetchone()[0] == 1
                assert connection.execute(
                    "SELECT stamina FROM players WHERE id=?", (player_id,)
                ).fetchone()[0] == 80
            await runtime.close()

    asyncio.run(run())


def test_void_spire_upper_enemy_uses_host_json_override(tmp_path: Path) -> None:
    async def run() -> None:
        content_dir = tmp_path / "data"
        copytree(Path(__file__).parents[1] / "data", content_dir)
        enemy_file = content_dir / "战斗" / "敌人.json"
        document = json.loads(enemy_file.read_text(encoding="utf-8"))
        scribe = next(row for row in document["records"] if row["key"] == "enemy.void_spire.scribe")
        scribe["stats"]["hp"] = 261
        enemy_file.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")

        runtime = create_runtime(data_dir=content_dir)
        await _setup(runtime, "qq.official", "upper-override", "upper-override", damage=500)
        with sqlite3.connect(runtime.settings.database_path) as connection:
            player_id = connection.execute(
                "SELECT id FROM players WHERE platform_user_id='upper-override'"
            ).fetchone()[0]
            _seed_claimed_floors(connection, player_id, 1, 30)
            connection.execute(
                "UPDATE players SET realm_key='dao_union',realm_layer=1,"
                "max_hp=30000,initiative=30000,qualification_json=? WHERE id=?",
                (json.dumps(BALANCED_QUALIFICATION), player_id),
            )
        challenge = await _send(runtime, "qq.official", "upper-override", "upper-override-31", "挑战虚空塔 31")
        assert challenge.data["outcome"] == "won"
        with sqlite3.connect(runtime.settings.database_path) as connection:
            snapshot = connection.execute(
                "SELECT snapshot_json FROM battle_sessions WHERE battle_id=?", (challenge.data["battle_id"],)
            ).fetchone()[0]
            assert json.loads(snapshot)["enemy"]["max_hp"] == 261
        await runtime.close()

    asyncio.run(run())


def test_void_spire_final_routes_use_contract_rewards_and_boss_evidence_on_both_adapters() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(
                data_dir=data_dir,
                clock=lambda: datetime(2026, 9, 29, tzinfo=timezone.utc),
            )
            for adapter, user, floor_no in (
                ("qq.official", "origin-route", 75),
                ("onebot.v11", "ascension-route", 90),
            ):
                await _setup(runtime, adapter, user, user, damage=500)
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    player_id = connection.execute(
                        "SELECT id FROM players WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    ).fetchone()[0]
                    _seed_claimed_floors(connection, player_id, 1, floor_no - 1)
                    connection.execute(
                        "UPDATE players SET realm_key='tribulation',realm_layer=1,stamina=200,stamina_max=200,"
                        "max_hp=30000,initiative=30000,qualification_json=? WHERE id=?",
                        (json.dumps(BALANCED_QUALIFICATION), player_id),
                    )
                challenge = await _send(runtime, adapter, user, f"{user}-challenge", f"挑战虚空塔 {floor_no}")
                assert challenge.code == "VOID_SPIRE_CHALLENGE_SETTLED"
                assert challenge.data["route_key"] == floor_definition(floor_no).route_key
                assert challenge.data["outcome"] == "won"
                conflict = await _send(runtime, adapter, user, f"{user}-challenge", "挑战虚空塔 1")
                assert conflict.code == "OPERATION_CONFLICT"
                claim = await _send(runtime, adapter, user, f"{user}-claim", "领取虚空塔奖励")
                assert claim.code == "VOID_SPIRE_REWARD_CLAIMED"
                assert claim.data["reward"]["item.void_crystal"] >= 2
                assert f"codex.challenge.void_spire.floor_{floor_no}" in claim.data["discoveries"]
                assert f"codex.void.route_spire_{floor_definition(floor_no).route_key}" in claim.data["discoveries"]
                assert claim.data["discoveries"][-1] == (
                    "codex.story.void_spire.ascension" if floor_no == 90 else "codex.story.void_spire.origin"
                )
                replay = await _send(runtime, adapter, user, f"{user}-claim", "领取虚空塔奖励")
                assert replay.data["idempotent_replay"] is True
                if floor_no == 90:
                    assert claim.data["title"] == "虚空登临者"
            await runtime.close()

    asyncio.run(run())


def test_void_spire_upper_contract_override_changes_cost_and_reward(tmp_path: Path) -> None:
    content_dir = tmp_path / "data"
    copytree(Path(__file__).parents[1] / "data", content_dir)
    contract_file = content_dir / "特殊" / "虚空塔.json"
    document = json.loads(contract_file.read_text(encoding="utf-8"))
    origin = next(row for row in document["records"] if row["key"] == "tower.void_spire.origin")
    origin["stamina_cost"] = 37
    origin["first_clear_reward"]["spirit_stones"] = 777
    contract_file.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")

    async def run() -> None:
        runtime = create_runtime(data_dir=content_dir)
        await _setup(runtime, "qq.official", "upper-contract", "upper-contract", damage=500)
        with sqlite3.connect(runtime.settings.database_path) as connection:
            player_id = connection.execute(
                "SELECT id FROM players WHERE platform_user_id='upper-contract'"
            ).fetchone()[0]
            _seed_claimed_floors(connection, player_id, 1, 60)
            connection.execute(
                "UPDATE players SET realm_key='tribulation',realm_layer=1,stamina=100,stamina_max=100,"
                "max_hp=30000,initiative=30000,qualification_json=? WHERE id=?",
                (json.dumps(BALANCED_QUALIFICATION), player_id),
            )
        challenge = await _send(runtime, "qq.official", "upper-contract", "contract-start", "挑战虚空塔 61")
        assert challenge.data["outcome"] == "won"
        assert challenge.data["reward"]["spirit_stones"] == 777
        with sqlite3.connect(runtime.settings.database_path) as connection:
            assert connection.execute(
                "SELECT stamina FROM players WHERE platform_user_id='upper-contract'"
            ).fetchone()[0] == 63
        await runtime.close()

    asyncio.run(run())
