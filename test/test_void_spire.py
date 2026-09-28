from __future__ import annotations

import asyncio
import json
import sqlite3
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from shutil import copytree
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.combat.rules import ENEMIES, enemy_definition
from nonebot_plugin_xiuxian_3.xiuxian.specials.void_spire_rules import (
    DESIGN_MAX_FLOOR,
    MAX_FLOOR,
    floor_definition,
    versions_for_floor,
)


async def _send(runtime, adapter: str, user: str, operation_id: str, command: str):
    return await runtime.adapters.dispatch(
        adapter,
        CommandContext(adapter=adapter, user_id=user, operation_id=operation_id),
        command,
    )


async def _setup(runtime, adapter: str, user: str, prefix: str) -> None:
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

                invalid = await _send(runtime, adapter, user, f"{prefix}-invalid", "挑战虚空塔 31")
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
                        "SELECT void_spire_runs.route_key, void_spire_runs.floor_no, void_spire_runs.content_version, void_spire_runs.rule_version FROM void_spire_runs "
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


def test_void_spire_rules_and_content_records_are_stable() -> None:
    assert MAX_FLOOR == 30
    assert DESIGN_MAX_FLOOR == 90
    assert floor_definition(15).boss is True
    assert floor_definition(15).route_key == "storm"
    assert floor_definition(30).boss is True
    assert floor_definition(30).route_key == "echo"
    with open("data/战斗/敌人.json", encoding="utf-8") as handle:
        records = {row["key"]: row for row in json.load(handle)["records"]}
    expected = {
        "enemy.void_spire.scout",
        "enemy.void_spire.sentinel",
        "enemy.void_spire.watcher",
        "enemy.void_spire.warlord",
        "enemy.void_spire.route_storm_boss",
        "enemy.void_spire.route_echo_boss",
    }
    assert expected <= records.keys()
    for key in expected:
        row = records[key]
        definition = enemy_definition(key)
        assert (definition.max_hp, definition.attack, definition.label) == (
            row["stats"]["hp"], row["stats"]["attack"], row["name"]
        )


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
            enemy = enemy_definition("enemy.void_spire.scout")
            monkeypatch.setitem(
                ENEMIES, enemy.key,
                replace(enemy, max_hp=200000, attack=10000, initiative=10000, agility=10000),
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
                await _setup(runtime, adapter, user, user)
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    player_id = connection.execute(
                        "SELECT id FROM players WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    ).fetchone()[0]
                    connection.execute(
                        "UPDATE players SET qualification_json=?,max_hp=30000,initiative=30000 WHERE id=?",
                        (json.dumps({"body": 1000, "agility": 1000}), player_id),
                    )
                    history = "2026-01-01T00:00:00+00:00"
                    connection.executemany(
                        "INSERT INTO void_spire_runs(run_id,player_id,tower_key,floor_no,route_key,"
                        "status,first_clear,starts_at,result_json,reward_json,content_version,rule_version,"
                        "created_at,updated_at) VALUES(?,?,'tower.void_spire',?,?,'claimed',1,"
                        "?,'{}','{}',?,?,?,?)",
                        [
                            (
                                f"{user}-historical-{previous}", player_id, previous,
                                floor_definition(previous).route_key, history,
                                *versions_for_floor(previous), history, history,
                            )
                            for previous in range(1, floor_no)
                        ],
                    )
                challenge = await _send(runtime, adapter, user, f"{user}-challenge", f"挑战虚空塔 {floor_no}")
                assert challenge.code == "VOID_SPIRE_CHALLENGE_SETTLED"
                assert challenge.data["outcome"] == "won"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    snapshot, reward_status, content_version, rule_version = connection.execute(
                        "SELECT b.snapshot_json,b.reward_status,t.content_version,t.rule_version "
                        "FROM battle_sessions b JOIN void_spire_runs t ON b.battle_id=t.battle_id "
                        "WHERE t.run_id=?",
                        (challenge.data["run_id"],),
                    ).fetchone()
                    assert json.loads(snapshot)["enemy"]["key"] == floor_definition(floor_no).enemy_key
                    assert reward_status == "none"
                    assert (content_version, rule_version) == versions_for_floor(floor_no)
                reward = await _send(runtime, adapter, user, f"{user}-reward", "领取虚空塔奖励")
                assert reward.code == "VOID_SPIRE_REWARD_CLAIMED"
                assert reward.data["reward"]["local.void_supply"] == 30
                with sqlite3.connect(runtime.settings.database_path) as connection:
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
