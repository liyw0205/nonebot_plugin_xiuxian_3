from __future__ import annotations

import asyncio
import json
import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.combat.rules import enemy_definition
from nonebot_plugin_xiuxian_3.xiuxian.specials.tower_migration import ensure_tower_schema
from nonebot_plugin_xiuxian_3.xiuxian.specials.tower_rules import floor_definition, reward_for


class MutableClock:
    def __init__(self, value: datetime):
        self.value = value

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **kwargs: int) -> None:
        self.value += timedelta(**kwargs)


async def _send(runtime, adapter: str, user: str, operation_id: str, command: str):
    return await runtime.adapters.dispatch(
        adapter,
        CommandContext(adapter=adapter, user_id=user, operation_id=operation_id),
        command,
    )


async def _enter_tower_eligible_path(runtime, adapter: str, user: str, prefix: str) -> None:
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


def test_mist_trial_tower_first_clear_reward_and_day_five_goal_on_both_adapters() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 27, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            for adapter, user in (("qq.official", "tower-qq"), ("onebot.v11", "tower-onebot")):
                prefix = adapter.replace(".", "-")
                await _enter_tower_eligible_path(runtime, adapter, user, prefix)
                clock.advance(days=4)
                preview = await _send(runtime, adapter, user, f"{prefix}-preview", "试炼塔")
                assert preview.code == "TOWER_PREVIEW"
                assert preview.data["next_floor"] == 1

                locked = await _send(runtime, adapter, user, f"{prefix}-locked", "挑战试炼塔 2")
                assert locked.code == "TOWER_FLOOR_LOCKED"

                with sqlite3.connect(runtime.settings.database_path) as connection:
                    stamina_before = connection.execute(
                        "SELECT stamina FROM players WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    ).fetchone()[0]
                challenged = await _send(runtime, adapter, user, f"{prefix}-challenge", "挑战试炼塔 1")
                assert challenged.code == "TOWER_CHALLENGE_SETTLED", (challenged.code, challenged.message)
                assert challenged.data["status"] == "reward_pending"
                assert challenged.data["outcome"] == "won"
                assert challenged.data["first_clear"] is True

                with sqlite3.connect(runtime.settings.database_path) as connection:
                    reward_status, stamina, cultivation = connection.execute(
                        "SELECT b.reward_status,p.stamina,p.cultivation FROM battle_sessions b "
                        "JOIN tower_runs t ON t.battle_id=b.battle_id JOIN players p ON p.id=t.player_id "
                        "WHERE p.platform=? AND p.platform_user_id=?",
                        (adapter, user),
                    ).fetchone()
                    assert reward_status == "none"
                    assert stamina == stamina_before - floor_definition(1).stamina_cost
                    assert cultivation == 0

                blocked = await _send(runtime, adapter, user, f"{prefix}-pending", "挑战试炼塔 2")
                assert blocked.code == "TOWER_BUSY"
                replayed = await _send(runtime, adapter, user, f"{prefix}-challenge", "挑战试炼塔 1")
                assert replayed.ok and replayed.data["idempotent_replay"] is True

                claim = await _send(runtime, adapter, user, f"{prefix}-claim", "领取试炼塔奖励")
                assert claim.code == "TOWER_REWARD_CLAIMED"
                assert claim.data["first_clear"] is True
                assert claim.data["reward"] == {"item.mat.array_sand": 1, "spirit_stones": 10}
                replay_claim = await _send(runtime, adapter, user, f"{prefix}-claim", "领取试炼塔奖励")
                assert replay_claim.data["idempotent_replay"] is True

                practice = await _send(runtime, adapter, user, f"{prefix}-practice", "挑战试炼塔 1")
                assert practice.code == "TOWER_CHALLENGE_SETTLED"
                assert practice.data["first_clear"] is False
                practice_claim = await _send(
                    runtime, adapter, user, f"{prefix}-practice-claim", "领取试炼塔奖励"
                )
                assert practice_claim.code == "TOWER_REWARD_CLAIMED"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    observation = connection.execute(
                        "SELECT first_seen_operation_id FROM codex_entries c "
                        "JOIN players p ON p.id=c.player_id "
                        "WHERE p.platform=? AND p.platform_user_id=? AND c.entry_key=?",
                        (adapter, user, "codex.challenge.mist_trial.floor_1"),
                    ).fetchone()
                    assert observation[0] == f"{prefix}-practice-claim"

                floor_two = await _send(runtime, adapter, user, f"{prefix}-floor-two", "挑战试炼塔 2")
                assert floor_two.code == "TOWER_CHALLENGE_SETTLED"
                assert floor_two.data["first_clear"] is True
                # Leave its reward pending so the test does not consume extra daily attempts.

                goal = await _send(runtime, adapter, user, f"{prefix}-goals", "七日入道")
                assert goal.code == "SEVEN_DAY_STATUS"
                assert goal.data["goals"][4]["state"] == "claimable"
                claimed = await _send(runtime, adapter, user, f"{prefix}-day-five", "领取七日目标 5")
                assert claimed.code == "SEVEN_DAY_GOAL_CLAIMED"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    source_operation_id = connection.execute(
                        "SELECT c.source_operation_id FROM seven_day_goal_claims c "
                        "JOIN players p ON p.id=c.player_id WHERE p.platform=? AND p.platform_user_id=? AND c.day_number=5",
                        (adapter, user),
                    ).fetchone()[0]
                    assert source_operation_id.startswith("battle.resolve:")
            await runtime.close()

    asyncio.run(run())


def test_mist_trial_tower_floor_rules_match_v01_bands_and_bosses() -> None:
    assert (floor_definition(1).required_realm, floor_definition(1).stamina_cost, floor_definition(1).daily_limit) == ("qi_sensing", 4, 5)
    assert floor_definition(5).enemy_key.endswith("sensing_boss")
    assert floor_definition(10).enemy_key.endswith("sensing_boss")
    assert (floor_definition(11).required_realm, floor_definition(11).stamina_cost, floor_definition(11).daily_limit) == ("qi_gathering", 6, 4)
    assert floor_definition(15).enemy_key.endswith("gathering_boss")
    assert floor_definition(20).enemy_key.endswith("gathering_boss")
    assert (floor_definition(21).required_realm, floor_definition(21).stamina_cost, floor_definition(21).daily_limit) == ("foundation", 8, 3)
    assert floor_definition(25).enemy_key.endswith("foundation_boss")
    assert floor_definition(30).enemy_key.endswith("foundation_boss")
    assert reward_for(15, "seed", first_clear=True)["item.clue.recipe_basic"] == 1
    assert reward_for(20, "seed", first_clear=True)["item.clue.recipe_basic"] == 1
    assert reward_for(25, "seed", first_clear=True)["item.clue.mist_cave_route"] == 1
    assert reward_for(30, "seed", first_clear=True)["item.clue.mist_cave_route"] == 1


def test_mist_trial_tower_v02_rules_are_a_separate_band() -> None:
    assert (floor_definition(31).required_realm, floor_definition(31).required_layer) == ("golden_core", 3)
    assert (floor_definition(31).stamina_cost, floor_definition(31).daily_limit) == (10, 3)
    assert floor_definition(34).enemy_key == "enemy.mist_trial.golden_core"
    for floor_no in (35, 40, 45):
        assert floor_definition(floor_no).enemy_key == "enemy.mist_trial.golden_core_boss"
        assert reward_for(floor_no, "seed", first_clear=True) == {
            "spirit_stones": 60,
            "item.mat.array_sand": 2,
            "item.clue.recipe_basic": 1,
        }
    assert reward_for(31, "seed", first_clear=True) == {
        "spirit_stones": 60,
        "item.mat.array_sand": 2,
    }
    assert reward_for(35, "seed", first_clear=False) in ({}, {"item.mat.array_sand": 1})


def test_tower_schema_has_current_floor_range_and_no_release_metadata() -> None:
    with sqlite3.connect(":memory:") as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("CREATE TABLE players(id INTEGER PRIMARY KEY)")
        connection.execute("INSERT INTO players(id) VALUES (1)")
        ensure_tower_schema(connection)
        ensure_tower_schema(connection)


        connection.execute(
            "INSERT INTO tower_runs(run_id,player_id,tower_key,floor_no,status,first_clear,starts_at,"
            "result_json,reward_json,created_at,updated_at) VALUES('new-run',1,'tower.mist_trial',45,"
            "'claimed',1,'2026-01-02','{}','{}','2026-01-02','2026-01-02')"
        )
        assert connection.execute("SELECT run_id, floor_no FROM tower_runs").fetchall() == [("new-run", 45)]
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_tower_v01_start_operation_hash_remains_replayable_after_expansion() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            adapter = "qq.official"
            user = "tower-v01-hash-compat"
            await _enter_tower_eligible_path(runtime, adapter, user, "tower-v01-hash")
            with sqlite3.connect(runtime.settings.database_path) as connection:
                player_id = connection.execute(
                    "SELECT id FROM players WHERE platform=? AND platform_user_id=?", (adapter, user)
                ).fetchone()[0]
                now = "2026-01-01T00:00:00+00:00"
                connection.execute(
                    "INSERT INTO tower_runs(run_id,player_id,tower_key,floor_no,status,first_clear,"
                    "starts_at,result_json,reward_json,created_at,updated_at) "
                    "VALUES('v01-existing-run',?,'tower.mist_trial',1,'claimed',1,?,'{}','{}',?,?)",
                    (player_id, now, now, now),
                )
                old_payload = {
                    "platform": adapter,
                    "platform_user_id": user,
                    "tower_key": "tower.mist_trial",
                    "floor_no": 1,
                }
                old_hash = runtime.repository._request_hash("specials.start_tower", old_payload)
                connection.execute(
                    "INSERT INTO operations(operation_id,operation_name,player_id,request_hash,result_json,created_at) "
                    "VALUES('old-v01-start','specials.start_tower',?,?,?,?)",
                    (
                        player_id,
                        old_hash,
                        json.dumps(
                            {"run_id": "v01-existing-run", "tower_key": "tower.mist_trial", "floor_no": 1},
                            sort_keys=True,
                        ),
                        now,
                    ),
                )

            replay = await _send(runtime, adapter, user, "old-v01-start", "挑战试炼塔 1")
            assert replay.code == "TOWER_CHALLENGE_SETTLED"
            assert replay.data["idempotent_replay"] is True
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute(
                    "SELECT COUNT(*) FROM tower_runs WHERE player_id=?", (player_id,)
                ).fetchone()[0] == 1
            await runtime.close()

    asyncio.run(run())


def test_mist_trial_tower_upper_floors_and_quotas_on_both_adapters() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 28, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            for adapter in ("qq.official", "onebot.v11"):
                prefix = adapter.replace(".", "-")
                users = {floor_no: f"tower-v02-{prefix}-{floor_no}" for floor_no in (31, 35, 40, 45)}
                for floor_no, user in users.items():
                    await _enter_tower_eligible_path(runtime, adapter, user, f"{prefix}-{floor_no}")
                    with sqlite3.connect(runtime.settings.database_path) as connection:
                        player_id = connection.execute(
                            "SELECT id FROM players WHERE platform=? AND platform_user_id=?",
                            (adapter, user),
                        ).fetchone()[0]
                        connection.execute(
                            "UPDATE players SET realm_key='golden_core',realm_layer=2,stamina=100,"
                            "stamina_max=100,qualification_json=?,max_hp=30000,initiative=30000 "
                            "WHERE id=?",
                            (json.dumps({"body": 1000, "agility": 1000}), player_id),
                        )
                        connection.execute(
                            "UPDATE players SET realm_layer=3 WHERE id=?", (player_id,)
                        )
                        historical = "2026-09-01T00:00:00+00:00"
                        connection.executemany(
                            "INSERT INTO tower_runs(run_id,player_id,tower_key,floor_no,status,first_clear,"
                            "starts_at,result_json,reward_json,created_at,updated_at) "
                            "VALUES(?,?,'tower.mist_trial',?,'claimed',1,?,'{}','{}',?,?)",
                            [
                                (f"history-{player_id}-{previous_floor}", player_id, previous_floor,
                                 historical, historical, historical)
                                for previous_floor in range(1, floor_no)
                            ],
                        )

                    if floor_no == 31:
                        with sqlite3.connect(runtime.settings.database_path) as connection:
                            connection.execute(
                                "UPDATE players SET realm_layer=2 WHERE platform=? AND platform_user_id=?",
                                (adapter, user),
                            )
                        denied = await _send(
                            runtime, adapter, user, f"{prefix}-31-underlevel", "挑战试炼塔 31"
                        )
                        assert denied.code == "TOWER_REQUIREMENT_MISSING"
                        with sqlite3.connect(runtime.settings.database_path) as connection:
                            connection.execute(
                                "UPDATE players SET realm_layer=3 WHERE platform=? AND platform_user_id=?",
                                (adapter, user),
                            )

                    challenge = await _send(
                        runtime, adapter, user, f"{prefix}-floor-{floor_no}",
                        f"挑战试炼塔 {floor_no}",
                    )
                    assert challenge.code == "TOWER_CHALLENGE_SETTLED"
                    assert challenge.data["outcome"] == "won"
                    with sqlite3.connect(runtime.settings.database_path) as connection:
                        snapshot_json = connection.execute(
                            "SELECT b.snapshot_json FROM battle_sessions b "
                            "JOIN tower_runs t ON t.battle_id=b.battle_id WHERE t.run_id=?",
                            (challenge.data["run_id"],),
                        ).fetchone()[0]
                    enemy_key = json.loads(snapshot_json)["enemy"]["key"]
                    expected_enemy = (
                        "enemy.mist_trial.golden_core_boss"
                        if floor_no in (35, 40, 45)
                        else "enemy.mist_trial.golden_core"
                    )
                    assert enemy_key == expected_enemy

                    claimed = await _send(
                        runtime, adapter, user, f"{prefix}-claim-{floor_no}", "领取试炼塔奖励"
                    )
                    assert claimed.code == "TOWER_REWARD_CLAIMED"
                    expected_reward = {"spirit_stones": 60, "item.mat.array_sand": 2}
                    if floor_no in (35, 40, 45):
                        expected_reward["item.clue.recipe_basic"] = 1
                        with sqlite3.connect(runtime.settings.database_path) as connection:
                            assert connection.execute(
                                "SELECT 1 FROM codex_entries c JOIN players p ON p.id=c.player_id "
                                "WHERE p.platform=? AND p.platform_user_id=? AND c.entry_key=?",
                                (
                                    adapter,
                                    user,
                                    f"codex.challenge.mist_trial.floor_{floor_no}",
                                ),
                            ).fetchone() is not None
                    assert claimed.data["reward"] == expected_reward

                    if floor_no == 31:
                        for next_floor in (32, 33):
                            next_challenge = await _send(
                                runtime, adapter, user, f"{prefix}-floor-{next_floor}",
                                f"挑战试炼塔 {next_floor}",
                            )
                            assert next_challenge.data["outcome"] == "won"
                            next_claim = await _send(
                                runtime, adapter, user, f"{prefix}-claim-{next_floor}",
                                "领取试炼塔奖励",
                            )
                            assert next_claim.code == "TOWER_REWARD_CLAIMED"
                        capped = await _send(
                            runtime, adapter, user, f"{prefix}-floor-34-capped", "挑战试炼塔 34"
                        )
                        assert capped.code == "TOWER_ATTEMPT_CAP"
                        clock.advance(days=1)
                        retry = await _send(
                            runtime, adapter, user, f"{prefix}-floor-34-next-day", "挑战试炼塔 34"
                        )
                        assert retry.code == "TOWER_CHALLENGE_SETTLED"
                        assert retry.data["outcome"] == "won"

            await runtime.close()

    asyncio.run(run())


def test_tower_battle_start_failure_refunds_stamina_and_attempt_quota(monkeypatch) -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            adapter = "qq.official"
            user = "tower-start-failure"
            await _enter_tower_eligible_path(runtime, adapter, user, "tower-failure")
            with sqlite3.connect(runtime.settings.database_path) as connection:
                stamina_before = connection.execute(
                    "SELECT stamina FROM players WHERE platform=? AND platform_user_id=?",
                    (adapter, user),
                ).fetchone()[0]

            original_start = runtime.repository.start_quest_battle

            async def fail_start(**kwargs):
                raise RuntimeError("battle service unavailable")

            monkeypatch.setattr(runtime.repository, "start_quest_battle", fail_start)
            failed = await _send(runtime, adapter, user, "tower-failure-run-1", "挑战试炼塔 1")
            assert failed.code == "TOWER_START_FAILED"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                stamina, status = connection.execute(
                    "SELECT p.stamina,t.status FROM players p JOIN tower_runs t ON t.player_id=p.id "
                    "WHERE p.platform=? AND p.platform_user_id=?",
                    (adapter, user),
                ).fetchone()
            assert stamina == stamina_before
            assert status == "aborted"

            replayed_failure = await _send(
                runtime, adapter, user, "tower-failure-run-1", "挑战试炼塔 1"
            )
            assert replayed_failure.code == "TOWER_START_FAILED"
            monkeypatch.setattr(runtime.repository, "start_quest_battle", original_start)
            preview = await _send(runtime, adapter, user, "tower-failure-preview", "试炼塔")
            assert preview.data["daily_used"] == 0
            retry = await _send(runtime, adapter, user, "tower-failure-run-2", "挑战试炼塔 1")
            assert retry.code == "TOWER_CHALLENGE_SETTLED"
            await runtime.close()

    asyncio.run(run())


def test_tower_running_battle_resumes_after_runtime_restart(monkeypatch) -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            adapter = "onebot.v11"
            user = "tower-restart"
            runtime = create_runtime(data_dir=data_dir)
            await _enter_tower_eligible_path(runtime, adapter, user, "tower-restart")
            with sqlite3.connect(runtime.settings.database_path) as connection:
                stamina_before = connection.execute(
                    "SELECT stamina FROM players WHERE platform=? AND platform_user_id=?",
                    (adapter, user),
                ).fetchone()[0]

            async def leave_battle_running(**kwargs):
                return SimpleNamespace(status="running")

            monkeypatch.setattr(runtime.repository, "run_battle_turn", leave_battle_running)
            interrupted = await _send(
                runtime, adapter, user, "tower-restart-challenge", "挑战试炼塔 1"
            )
            assert interrupted.code == "TOWER_NOT_READY"
            await runtime.close()

            runtime = create_runtime(data_dir=data_dir)
            resumed = await _send(
                runtime, adapter, user, "tower-restart-challenge", "挑战试炼塔 1"
            )
            assert resumed.code == "TOWER_CHALLENGE_SETTLED"
            assert resumed.data["status"] == "reward_pending"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                run_count, stamina, reward_status = connection.execute(
                    "SELECT COUNT(*),p.stamina,MAX(b.reward_status) FROM tower_runs t "
                    "JOIN players p ON p.id=t.player_id JOIN battle_sessions b ON b.battle_id=t.battle_id "
                    "WHERE p.platform=? AND p.platform_user_id=?",
                    (adapter, user),
                ).fetchone()
            assert run_count == 1
            assert stamina == stamina_before - floor_definition(1).stamina_cost
            assert reward_status == "none"
            await runtime.close()

    asyncio.run(run())


def test_tower_boss_honor_quotas_and_realm_band_transition_on_both_adapters() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 27, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            for adapter, user in (("qq.official", "tower-boss-qq"), ("onebot.v11", "tower-boss-onebot")):
                prefix = adapter.replace(".", "-")
                await _enter_tower_eligible_path(runtime, adapter, user, prefix)
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE players SET qualification_json=?,max_hp=30000,initiative=30000,"
                        "stamina=100,stamina_max=100 WHERE platform=? AND platform_user_id=?",
                        (json.dumps({"body": 1000, "agility": 1000}), adapter, user),
                    )

                for floor_no in range(1, 6):
                    challenge = await _send(
                        runtime, adapter, user, f"{prefix}-floor-{floor_no}", f"挑战试炼塔 {floor_no}"
                    )
                    assert challenge.code == "TOWER_CHALLENGE_SETTLED"
                    assert challenge.data["outcome"] == "won"
                    if floor_no == 5:
                        with sqlite3.connect(runtime.settings.database_path) as connection:
                            snapshot_json = connection.execute(
                                "SELECT snapshot_json FROM battle_sessions WHERE battle_id=?",
                                (challenge.data["battle_id"],),
                            ).fetchone()[0]
                        assert json.loads(snapshot_json)["enemy"]["key"] == "enemy.mist_trial.sensing_boss"
                    claim = await _send(
                        runtime, adapter, user, f"{prefix}-floor-{floor_no}-claim", "领取试炼塔奖励"
                    )
                    assert claim.code == "TOWER_REWARD_CLAIMED"

                daily_cap = await _send(
                    runtime, adapter, user, f"{prefix}-daily-cap", "挑战试炼塔 6"
                )
                assert daily_cap.code == "TOWER_ATTEMPT_CAP"
                preview = await _send(runtime, adapter, user, f"{prefix}-daily-preview", "试炼塔")
                assert preview.data["daily_used"] == 5

                clock.advance(days=1)
                for floor_no in range(6, 11):
                    challenge = await _send(
                        runtime, adapter, user, f"{prefix}-floor-{floor_no}", f"挑战试炼塔 {floor_no}"
                    )
                    assert challenge.code == "TOWER_CHALLENGE_SETTLED"
                    assert challenge.data["outcome"] == "won"
                    if floor_no == 10:
                        with sqlite3.connect(runtime.settings.database_path) as connection:
                            snapshot_json = connection.execute(
                                "SELECT snapshot_json FROM battle_sessions WHERE battle_id=?",
                                (challenge.data["battle_id"],),
                            ).fetchone()[0]
                        assert json.loads(snapshot_json)["enemy"]["key"] == "enemy.mist_trial.sensing_boss"
                    claim = await _send(
                        runtime, adapter, user, f"{prefix}-floor-{floor_no}-claim", "领取试炼塔奖励"
                    )
                    assert claim.code == "TOWER_REWARD_CLAIMED"

                honors = await _send(runtime, adapter, user, f"{prefix}-honors", "功业录")
                tower_achievement = next(
                    item for item in honors.data["achievements"]
                    if item["achievement_key"] == "achievement.tower_10"
                )
                assert tower_achievement["state"] == "claimable"
                achievement_claim = await _send(
                    runtime,
                    adapter,
                    user,
                    f"{prefix}-honor-claim",
                    f"领取功业 {tower_achievement['index']}",
                )
                assert achievement_claim.code == "ACHIEVEMENT_CLAIMED"
                assert achievement_claim.data["achievement_key"] == "achievement.tower_10"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    assert connection.execute(
                        "SELECT 1 FROM honor_titles h JOIN players p ON p.id=h.player_id "
                        "WHERE p.platform=? AND p.platform_user_id=? AND h.title_key='title.first_tower_clear'",
                        (adapter, user),
                    ).fetchone() is not None

                underqualified = await _send(
                    runtime, adapter, user, f"{prefix}-floor-11-underqualified", "挑战试炼塔 11"
                )
                assert underqualified.code == "TOWER_REQUIREMENT_MISSING"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE players SET realm_key='qi_gathering',realm_layer=3 WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    )
                layer_three = await _send(
                    runtime, adapter, user, f"{prefix}-floor-11-layer-three", "挑战试炼塔 11"
                )
                assert layer_three.code == "TOWER_REQUIREMENT_MISSING"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE players SET realm_layer=4 WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    )
                layer_four = await _send(
                    runtime, adapter, user, f"{prefix}-floor-11-layer-four", "挑战试炼塔 11"
                )
                assert layer_four.code == "TOWER_CHALLENGE_SETTLED"
                assert layer_four.data["outcome"] == "won"
                assert (await _send(
                    runtime, adapter, user, f"{prefix}-floor-11-claim", "领取试炼塔奖励"
                )).code == "TOWER_REWARD_CLAIMED"

                for floor_no in range(12, 15):
                    challenge = await _send(
                        runtime, adapter, user, f"{prefix}-floor-{floor_no}", f"挑战试炼塔 {floor_no}"
                    )
                    assert challenge.code == "TOWER_CHALLENGE_SETTLED"
                    assert challenge.data["outcome"] == "won"
                    assert (await _send(
                        runtime, adapter, user, f"{prefix}-floor-{floor_no}-claim", "领取试炼塔奖励"
                    )).code == "TOWER_REWARD_CLAIMED"

                clock.advance(days=1)
                floor_fifteen = await _send(
                    runtime, adapter, user, f"{prefix}-floor-15", "挑战试炼塔 15"
                )
                assert floor_fifteen.code == "TOWER_CHALLENGE_SETTLED"
                assert floor_fifteen.data["outcome"] == "won"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    snapshot_json = connection.execute(
                        "SELECT snapshot_json FROM battle_sessions WHERE battle_id=?",
                        (floor_fifteen.data["battle_id"],),
                    ).fetchone()[0]
                assert json.loads(snapshot_json)["enemy"]["key"] == "enemy.mist_trial.gathering_boss"
                floor_fifteen_claim = await _send(
                    runtime, adapter, user, f"{prefix}-floor-15-claim", "领取试炼塔奖励"
                )
                assert floor_fifteen_claim.code == "TOWER_REWARD_CLAIMED"
                assert floor_fifteen_claim.data["reward"]["item.clue.recipe_basic"] == 1

                for practice_no in range(1, 4):
                    practice = await _send(
                        runtime,
                        adapter,
                        user,
                        f"{prefix}-weekly-practice-{practice_no}",
                        "挑战试炼塔 10",
                    )
                    assert practice.code == "TOWER_CHALLENGE_SETTLED"
                    assert practice.data["first_clear"] is False
                    assert (await _send(
                        runtime,
                        adapter,
                        user,
                        f"{prefix}-weekly-practice-{practice_no}-claim",
                        "领取试炼塔奖励",
                    )).code == "TOWER_REWARD_CLAIMED"
                weekly_cap = await _send(
                    runtime, adapter, user, f"{prefix}-weekly-cap", "挑战试炼塔 10"
                )
                assert weekly_cap.code == "TOWER_ATTEMPT_CAP"
            await runtime.close()

    asyncio.run(run())


def test_tower_defeat_consumes_one_attempt_without_reward_on_both_adapters(monkeypatch) -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            original_enemy_definition = enemy_definition

            def overpowering_enemy(enemy_key: str, *, content=None):
                enemy = original_enemy_definition(enemy_key, content=content)
                if enemy_key == "enemy.mist_trial.sensing":
                    return replace(
                        enemy,
                        max_hp=1_000_000,
                        attack=100_000,
                        initiative=100_000,
                        agility=100_000,
                    )
                return enemy

            monkeypatch.setattr(
                "nonebot_plugin_xiuxian_3.xiuxian.combat.repository.enemy_definition",
                overpowering_enemy,
            )
            for adapter, user in (("qq.official", "tower-loss-qq"), ("onebot.v11", "tower-loss-onebot")):
                prefix = adapter.replace(".", "-")
                await _enter_tower_eligible_path(runtime, adapter, user, prefix)
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    stamina_before = connection.execute(
                        "SELECT stamina FROM players WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    ).fetchone()[0]
                lost = await _send(runtime, adapter, user, f"{prefix}-lost", "挑战试炼塔 1")
                assert lost.code == "TOWER_CHALLENGE_SETTLED"
                assert lost.data["outcome"] == "lost"
                assert lost.data["status"] == "lost"
                assert lost.data["first_clear"] is False
                unavailable = await _send(
                    runtime, adapter, user, f"{prefix}-lost-claim", "领取试炼塔奖励"
                )
                assert unavailable.code == "TOWER_REWARD_NOT_AVAILABLE"
                preview = await _send(runtime, adapter, user, f"{prefix}-preview", "试炼塔")
                assert preview.data["daily_used"] == 1
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    stamina, event_count, reward_claim_count = connection.execute(
                        "SELECT p.stamina,"
                        "(SELECT COUNT(*) FROM activity_events e WHERE e.player_id=p.id AND e.event_key='specials.tower.floor.1'),"
                        "(SELECT COUNT(*) FROM tower_reward_claims c WHERE c.player_id=p.id) "
                        "FROM players p WHERE p.platform=? AND p.platform_user_id=?",
                        (adapter, user),
                    ).fetchone()
                assert stamina == stamina_before - floor_definition(1).stamina_cost
                assert event_count == reward_claim_count == 0
            await runtime.close()

    asyncio.run(run())


def test_tower_upper_floor_clue_rewards_are_claimed_on_both_adapters() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 28, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            for adapter in ("qq.official", "onebot.v11"):
                for floor_no in (20, 25, 30):
                    user = f"tower-upper-{adapter}-{floor_no}"
                    prefix = f"{adapter.replace('.', '-')}-{floor_no}"
                    await _enter_tower_eligible_path(runtime, adapter, user, prefix)
                    realm_key = "qi_gathering" if floor_no == 20 else "foundation"
                    with sqlite3.connect(runtime.settings.database_path) as connection:
                        player_id = connection.execute(
                            "SELECT id FROM players WHERE platform=? AND platform_user_id=?",
                            (adapter, user),
                        ).fetchone()[0]
                        connection.execute(
                            "UPDATE players SET realm_key=?,realm_layer=4,qualification_json=?,"
                            "max_hp=30000,initiative=30000,stamina=100,stamina_max=100 WHERE id=?",
                            (realm_key, json.dumps({"body": 1000, "agility": 1000}), player_id),
                        )
                        connection.execute(
                            "UPDATE players SET realm_layer=3 WHERE id=?", (player_id,)
                        )
                        historical = "2026-09-01T00:00:00+00:00"
                        connection.executemany(
                            "INSERT INTO tower_runs(run_id,player_id,tower_key,floor_no,status,first_clear,"
                            "starts_at,result_json,reward_json,created_at,updated_at) "
                            "VALUES(?,?,'tower.mist_trial',?,'claimed',1,?,'{}','{}',?,?)",
                            [
                                (f"history-{user}-{previous_floor}", player_id, previous_floor,
                                 historical, historical, historical)
                                for previous_floor in range(1, floor_no)
                            ],
                        )

                    underqualified = await _send(
                        runtime,
                        adapter,
                        user,
                        f"{prefix}-underqualified",
                        f"挑战试炼塔 {floor_no}",
                    )
                    assert underqualified.code == "TOWER_REQUIREMENT_MISSING"
                    with sqlite3.connect(runtime.settings.database_path) as connection:
                        connection.execute(
                            "UPDATE players SET realm_layer=4 WHERE platform=? AND platform_user_id=?",
                            (adapter, user),
                        )

                    challenge = await _send(
                        runtime,
                        adapter,
                        user,
                        f"{prefix}-challenge",
                        f"挑战试炼塔 {floor_no}",
                    )
                    assert challenge.code == "TOWER_CHALLENGE_SETTLED"
                    assert challenge.data["outcome"] == "won"
                    with sqlite3.connect(runtime.settings.database_path) as connection:
                        snapshot_json = connection.execute(
                            "SELECT snapshot_json FROM battle_sessions WHERE battle_id=?",
                            (challenge.data["battle_id"],),
                        ).fetchone()[0]
                    tier = "gathering" if floor_no == 20 else "foundation"
                    assert json.loads(snapshot_json)["enemy"]["key"] == (
                        f"enemy.mist_trial.{tier}_boss"
                    )
                    reward = await _send(
                        runtime, adapter, user, f"{prefix}-claim", "领取试炼塔奖励"
                    )
                    assert reward.code == "TOWER_REWARD_CLAIMED"
                    clue_key = (
                        "item.clue.recipe_basic"
                        if floor_no == 20
                        else "item.clue.mist_cave_route"
                    )
                    assert reward.data["reward"][clue_key] == 1
                    with sqlite3.connect(runtime.settings.database_path) as connection:
                        inventory_json = connection.execute(
                            "SELECT p.inventory_json "
                            "FROM players p JOIN tower_reward_claims c ON c.player_id=p.id "
                            "WHERE p.platform=? AND p.platform_user_id=? AND c.floor_no=?",
                            (adapter, user, floor_no),
                        ).fetchone()[0]
                    assert json.loads(inventory_json)[clue_key] == 1
            await runtime.close()

    asyncio.run(run())
