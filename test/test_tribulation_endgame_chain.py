from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import timedelta
from tempfile import TemporaryDirectory

from combat_fixtures import BALANCED_QUALIFICATION
from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.events.rules import final_heaven_season_window
from nonebot_plugin_xiuxian_3.xiuxian.progression.endgame_rules import trial_roll_bp
from nonebot_plugin_xiuxian_3.xiuxian.progression.rules import next_layer_threshold
from nonebot_plugin_xiuxian_3.xiuxian.quests.rules import DAO_ORIGIN_TASKS, dao_origin_task_definition


class MutableClock:
    def __init__(self) -> None:
        from datetime import datetime, timezone

        self.value = datetime(2026, 9, 24, 12, tzinfo=timezone.utc)

    def __call__(self):
        return self.value

    def advance(self, **kwargs: int) -> None:
        self.value += timedelta(**kwargs)


def _ctx(adapter: str, user: str, operation: str) -> CommandContext:
    return CommandContext(adapter=adapter, user_id=user, request_id=operation, operation_id=operation)


async def _create_trial_player(runtime, adapter: str, user: str, *, strong: bool = True) -> None:
    created = await runtime.dispatch(_ctx(adapter, user, f"create-{user}"), "开始修仙")
    assert created.ok
    qualification = {"body": 2_000, "agility": 2_000} if strong else {"body": 0, "agility": 0}
    with sqlite3.connect(runtime.settings.database_path) as db:
        db.execute(
            """
            UPDATE players SET stage='cultivator', realm_key='tribulation', realm_layer=9,
                endgame_status='tribulation', location_key='tribulation.sky_terrace',
                path_key='body', dao_fruit_progress=280, ascension_merit=0,
                faction_reputation_json=?, inventory_json=?, qualification_json=?,
                tribulation_debt=0
            WHERE platform=? AND platform_user_id=?
            """,
            (
                json.dumps({}),
                json.dumps({"item.tribulation_token": 3}),
                json.dumps(qualification),
                adapter,
                user,
            ),
        )


def _join_route_sect(
    runtime,
    clock,
    adapter: str,
    user: str,
    route_key: str | None,
    *,
    sect_id: str = "sect-route",
    sect_name: str = "试炼宗",
) -> int:
    """Attach a player to an active sect, optionally carrying one dao route."""

    with sqlite3.connect(runtime.settings.database_path) as db:
        player_id = int(
            db.execute(
                "SELECT id FROM players WHERE platform=? AND platform_user_id=?",
                (adapter, user),
            ).fetchone()[0]
        )
        now_text = clock.value.isoformat()
        db.execute(
            "INSERT INTO sects(sect_id, name, name_key, leader_id, status, level, "
            "max_members, warehouse_capacity, construction, spirit_stones, "
            "sect_merit, warehouse_json, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, 'active', 6, 80, 100, 0, 0, 1000, '{}', ?, ?)",
            (sect_id, sect_name, f"{sect_id}:name", player_id, now_text, now_text),
        )
        db.execute(
            "INSERT INTO sect_members(sect_id, player_id, role, status, contribution, "
            "joined_at, last_action_at, created_at, updated_at) "
            "VALUES (?, ?, 'leader', 'active', 0, ?, ?, ?, ?)",
            (sect_id, player_id, now_text, now_text, now_text, now_text),
        )
        if route_key is not None:
            db.execute(
                "INSERT INTO dao_route_state(sect_id, route_key, cycle_id, locked_until, "
                "updated_at) VALUES (?, ?, 'route:test', ?, ?)",
                (
                    sect_id,
                    route_key,
                    (clock.value + timedelta(days=7)).isoformat(),
                    now_text,
                ),
            )
        return player_id


def test_qq_and_onebot_three_trials_isolated_and_replayable() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            clock = MutableClock()
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            for adapter in ("qq.official", "onebot.v11"):
                user = f"trial-chain-{adapter}"
                await _create_trial_player(runtime, adapter, user)
                trials = (
                    ("身心劫", None),
                    ("三界劫", None),
                    ("道果劫", "fruit.immortal_body"),
                )
                for index, (label, fruit) in enumerate(trials):
                    command = f"开始天劫试炼 {label}" if fruit is None else f"开始天劫试炼 {label} {fruit}"
                    operation = f"{user}-start-{index}"
                    started = await runtime.dispatch(_ctx(adapter, user, operation), command)
                    assert started.code == "TRIAL_STARTED", (adapter, index, started.code, started.message)
                    assert started.data["battle_outcome"] == "won"
                    replay = await runtime.dispatch(_ctx(adapter, user, operation), command)
                    assert replay.code == "TRIAL_STARTED"
                    assert replay.data["idempotent_replay"] is True
                    too_early = await runtime.dispatch(
                        _ctx(adapter, user, f"{user}-early-settle-{index}"), "结算天劫试炼"
                    )
                    assert too_early.code == "TRIBULATION_TRIAL_NOT_READY"
                    clock.advance(minutes=31)
                    settled = await runtime.dispatch(
                        _ctx(adapter, user, f"{user}-settle-{index}"), "结算天劫试炼"
                    )
                    assert settled.code == "TRIAL_SUCCEEDED"
                    assert settled.data["trial_key"] == (
                        "trial.body_and_mind",
                        "trial.three_realms",
                        "trial.dao_choice",
                    )[index]
                    assert settled.data["success"] is True
                    settlement_replay = await runtime.dispatch(
                        _ctx(adapter, user, f"{user}-settle-{index}"), "结算天劫试炼"
                    )
                    assert settlement_replay.data["idempotent_replay"] is True
                with sqlite3.connect(runtime.settings.database_path) as db:
                    row = db.execute(
                        "SELECT inventory_json, dao_fruit_progress, ascension_merit, tribulation_debt, dao_fruit_key FROM players WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    ).fetchone()
                    sessions = db.execute(
                        "SELECT trial_key, status, COUNT(*) FROM tribulation_trial_sessions WHERE player_id=(SELECT id FROM players WHERE platform=? AND platform_user_id=?) GROUP BY trial_key, status",
                        (adapter, user),
                    ).fetchall()
                assert json.loads(row[0]) == {"item.dao_fruit_fragment": 1}
                assert row[1:] == (810, 550, 0, "fruit.immortal_body")
                assert set(sessions) == {
                    ("trial.body_and_mind", "succeeded", 1),
                    ("trial.three_realms", "succeeded", 1),
                    ("trial.dao_choice", "succeeded", 1),
                }
            await runtime.close()

    asyncio.run(run())


def test_dao_origin_gate_accepts_same_historical_season_on_both_adapters() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            clock = MutableClock()
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            _, current_start, _ = final_heaven_season_window(clock())
            current_id, _, _ = final_heaven_season_window(current_start)
            previous_id, previous_start, previous_end = final_heaven_season_window(
                current_start - timedelta(seconds=1)
            )
            older_id, older_start, _ = final_heaven_season_window(previous_start - timedelta(seconds=1))
            assert current_id != previous_id != older_id
            season_created_at = {
                previous_id: previous_end - timedelta(seconds=1),
                older_id: older_start,
            }

            for adapter in ("qq.official", "onebot.v11"):
                for scenario in ("shared", "split"):
                    user = f"dao-origin-{scenario}-{adapter}"
                    await _create_trial_player(runtime, adapter, user)
                    for index, (label, fruit) in enumerate(
                        (("身心劫", None), ("三界劫", None), ("道果劫", "fruit.immortal_body"))
                    ):
                        command = (
                            f"开始天劫试炼 {label}"
                            if fruit is None
                            else f"开始天劫试炼 {label} {fruit}"
                        )
                        started = await runtime.dispatch(
                            _ctx(adapter, user, f"{user}-trial-{index}"), command
                        )
                        assert started.code == "TRIAL_STARTED"
                        assert started.data["battle_outcome"] == "won"
                        clock.advance(minutes=31)
                        settled = await runtime.dispatch(
                            _ctx(adapter, user, f"{user}-settle-{index}"), "结算天劫试炼"
                        )
                        assert settled.code == "TRIAL_SUCCEEDED"

                    with sqlite3.connect(runtime.settings.database_path) as db:
                        player_id = db.execute(
                            "SELECT id FROM players WHERE platform=? AND platform_user_id=?",
                            (adapter, user),
                        ).fetchone()[0]
                        for task_key in DAO_ORIGIN_TASKS:
                            season_id = (
                                previous_id
                                if scenario == "shared" or task_key == DAO_ORIGIN_TASKS[0]
                                else older_id
                            )
                            for attempt in range(3):
                                db.execute(
                                    "INSERT INTO quest_events(player_id, quest_key, component_key, "
                                    "source_operation_id, outcome, payload_json, created_at) "
                                    "VALUES (?, ?, 'completed', ?, 'success', ?, ?)",
                                    (
                                        player_id,
                                        task_key,
                                        f"{user}-{task_key}-{attempt}",
                                        json.dumps({
                                            "season_id": season_id,
                                            "task_snapshot": dao_origin_task_definition(task_key).snapshot(season_id),
                                        }),
                                        season_created_at[season_id].isoformat(),
                                    ),
                                )
                        db.execute(
                            "UPDATE players SET cultivation=2400000 WHERE id=?", (player_id,)
                        )

                    advanced = await runtime.dispatch(
                        _ctx(adapter, user, f"{user}-advance-l10"), "晋升境界"
                    )
                    if scenario == "shared":
                        assert advanced.code == "REALM_LAYER_ADVANCED", (
                            adapter,
                            advanced.code,
                            advanced.message,
                        )
                        assert advanced.data["realm_layer"] == 10
                    else:
                        assert advanced.code == "TRIAL_SEQUENCE_INVALID"
                        with sqlite3.connect(runtime.settings.database_path) as db:
                            layer = db.execute(
                                "SELECT realm_layer FROM players WHERE platform=? AND platform_user_id=?",
                                (adapter, user),
                            ).fetchone()[0]
                        assert layer == 9
            await runtime.close()

    asyncio.run(run())


def test_natural_qualification_wins_first_tribulation_trial_on_both_adapters() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            clock = MutableClock()
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            for adapter, user in (
                ("qq.official", "foundation-source-qq.official"),
                ("onebot.v11", "foundation-source-onebot.v11"),
            ):
                await runtime.dispatch(_ctx(adapter, user, f"create-{user}"), "开始修仙")
                await runtime.dispatch(_ctx(adapter, user, f"seek-{user}"), "寻仙问道")
                with sqlite3.connect(runtime.settings.database_path) as db:
                    db.execute(
                        "UPDATE players SET stage='cultivator', realm_key='tribulation', realm_layer=3, "
                        "endgame_status='tribulation', location_key='tribulation.sky_terrace', "
                        "inventory_json=? WHERE platform=? AND platform_user_id=?",
                        (json.dumps({"item.tribulation_token": 1}), adapter, user),
                    )
                operation = next(
                    f"{user}-body-trial-{candidate}"
                    for candidate in range(1000)
                    if trial_roll_bp(f"{user}-body-trial-{candidate}") < 7_000
                )
                started = await runtime.dispatch(
                    _ctx(adapter, user, operation), "开始天劫试炼 身心劫"
                )
                assert started.code == "TRIAL_STARTED"
                assert started.data["battle_outcome"] == "won", (adapter, started.data)
                clock.advance(minutes=31)
                settled = await runtime.dispatch(
                    _ctx(adapter, user, f"{user}-body-trial-settle"), "结算天劫试炼"
                )
                assert settled.code == "TRIAL_SUCCEEDED"
            await runtime.close()

    asyncio.run(run())


def test_qq_and_onebot_reach_tribulation_l6_and_complete_three_realms_trial() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            clock = MutableClock()
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            for adapter in ("qq.official", "onebot.v11"):
                user = f"tribulation-l6-{adapter}"
                await runtime.dispatch(_ctx(adapter, user, f"create-{user}"), "开始修仙")
                with sqlite3.connect(runtime.settings.database_path) as db:
                    db.execute(
                        "UPDATE players SET stage='cultivator', realm_key='tribulation', "
                        "realm_layer=3, cultivation=220000, total_cultivation=8998960, "
                        "endgame_status='tribulation', location_key='tribulation.sky_terrace', "
                        "stamina=100, stamina_max=100, energy=100, energy_max=100, "
                        "qualification_json=?, inventory_json=? "
                        "WHERE platform=? AND platform_user_id=?",
                        (
                            json.dumps({**BALANCED_QUALIFICATION, "body": 10, "agility": 15}),
                            json.dumps({"item.tribulation_token": 2}),
                            adapter,
                            user,
                        ),
                    )

                body_operation = next(
                    f"{user}-body-{candidate}"
                    for candidate in range(1_000)
                    if trial_roll_bp(f"{user}-body-{candidate}") < 7_000
                )
                body = await runtime.dispatch(
                    _ctx(adapter, user, body_operation), "开始天劫试炼 身心劫"
                )
                assert body.code == "TRIAL_STARTED"
                assert body.data["battle_outcome"] == "won"
                clock.advance(minutes=31)
                body_settlement = await runtime.dispatch(
                    _ctx(adapter, user, f"{user}-body-settle"), "结算天劫试炼"
                )
                assert body_settlement.code == "TRIAL_SUCCEEDED"

                reached_l6 = False
                for day in range(100):
                    clock.advance(days=1)
                    await runtime.dispatch(
                        _ctx(adapter, user, f"{user}-restore-{day}"), "恢复状态"
                    )
                    for slot in range(2):
                        operation_base = f"{user}-cultivation-{day}-{slot}"
                        started = await runtime.dispatch(
                            _ctx(adapter, user, f"{operation_base}-start"),
                            "开始修炼 神魂淬炼",
                        )
                        assert started.code == "CULTIVATION_STARTED"
                        clock.advance(minutes=30)
                        settled = await runtime.dispatch(
                            _ctx(adapter, user, f"{operation_base}-settle"), "结算修炼"
                        )
                        assert settled.data["realm_key"] == "tribulation"
                        assert settled.data["cultivation_gain"] >= 5_000
                        threshold = next_layer_threshold(
                            "tribulation", int(settled.data["realm_layer"])
                        )
                        layer = int(settled.data["realm_layer"])
                        cultivation = int(settled.data["cultivation"])
                        while threshold is not None and cultivation >= threshold:
                            advanced = await runtime.dispatch(
                                _ctx(adapter, user, f"{operation_base}-advance-{layer}"),
                                "晋升境界",
                            )
                            assert advanced.code == "REALM_LAYER_ADVANCED"
                            layer = int(advanced.data["realm_layer"])
                            cultivation = int(advanced.data["cultivation"])
                            threshold = next_layer_threshold("tribulation", layer)
                            if layer == 6:
                                reached_l6 = True
                                break
                        if slot == 0 and not reached_l6:
                            clock.advance(hours=8)
                            await runtime.dispatch(
                                _ctx(adapter, user, f"{operation_base}-recovery"), "恢复状态"
                            )
                        if reached_l6:
                            break
                    if reached_l6:
                        break
                assert reached_l6, f"{adapter} did not reach tribulation L6"

                three_realms_operation = next(
                    f"{user}-three-realms-{candidate}"
                    for candidate in range(1_000)
                    if trial_roll_bp(f"{user}-three-realms-{candidate}") < 7_000
                )
                three_realms = await runtime.dispatch(
                    _ctx(adapter, user, three_realms_operation), "开始天劫试炼 三界劫"
                )
                assert three_realms.code == "TRIAL_STARTED", (
                    adapter,
                    three_realms.code,
                    three_realms.message,
                )
                assert three_realms.data["battle_outcome"] == "won"
                clock.advance(minutes=31)
                three_realms_settlement = await runtime.dispatch(
                    _ctx(adapter, user, f"{user}-three-realms-settle"), "结算天劫试炼"
                )
                assert three_realms_settlement.code == "TRIAL_SUCCEEDED"
                assert three_realms_settlement.data["dao_fruit_progress"] == 280
                assert three_realms_settlement.data["ascension_merit"] == 300
                with sqlite3.connect(runtime.settings.database_path) as db:
                    state = db.execute(
                        "SELECT realm_key, realm_layer, cultivation, faction_reputation_json, "
                        "inventory_json FROM players WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    ).fetchone()
                assert state[0:2] == ("tribulation", 6)
                assert json.loads(state[3]) == {}
                assert json.loads(state[4]) == {"item.dao_fruit_fragment": 1}
            await runtime.close()

    asyncio.run(run())


def test_failed_trial_keeps_progress_isolated_and_allows_cooldown_retry() -> None:
    async def run() -> None:
        clock = MutableClock()
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            adapter, user = "qq.official", "trial-retry"
            await _create_trial_player(runtime, adapter, user, strong=False)
            failed_operation = next(
                f"{user}-failed-{index}"
                for index in range(1_000)
                if trial_roll_bp(f"{user}-failed-{index}") >= 7_000
            )
            started = await runtime.dispatch(
                _ctx(adapter, user, failed_operation), "开始天劫试炼 身心劫"
            )
            assert started.code == "TRIAL_STARTED"
            assert started.data["battle_outcome"] == "lost"
            too_early = await runtime.dispatch(
                _ctx(adapter, user, f"{user}-early-failed-settle"), "结算天劫试炼"
            )
            assert too_early.code == "TRIBULATION_TRIAL_NOT_READY"
            clock.advance(minutes=31)
            failed = await runtime.dispatch(
                _ctx(adapter, user, f"{user}-failed-settle"), "结算天劫试炼"
            )
            assert failed.code == "TRIAL_FAILED"
            assert failed.data["dao_fruit_progress"] == 280
            assert failed.data["tribulation_debt"] == 10
            blocked = await runtime.dispatch(
                _ctx(adapter, user, f"{user}-retry-too-soon"), "开始天劫试炼 身心劫"
            )
            assert blocked.code == "TRIBULATION_COOLDOWN"
            with sqlite3.connect(runtime.settings.database_path) as db:
                inventory = json.loads(
                    db.execute(
                        "SELECT inventory_json FROM players WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    ).fetchone()[0]
                )
            assert inventory == {"item.tribulation_token": 2}

            clock.advance(hours=25)
            with sqlite3.connect(runtime.settings.database_path) as db:
                db.execute(
                    "UPDATE players SET qualification_json=?, inventory_json=? WHERE platform=? AND platform_user_id=?",
                    (
                        json.dumps({"body": 2_000, "agility": 2_000}),
                        json.dumps({"item.tribulation_token": 2}),
                        adapter,
                        user,
                    ),
                )
            retry_operation = next(
                f"{user}-retry-{index}"
                for index in range(1_000)
                if trial_roll_bp(f"{user}-retry-{index}") < 7_000
            )
            retried = await runtime.dispatch(
                _ctx(adapter, user, retry_operation), "开始天劫试炼 身心劫"
            )
            assert retried.code == "TRIAL_STARTED"
            assert retried.data["battle_outcome"] == "won"
            clock.advance(minutes=31)
            recovered = await runtime.dispatch(
                _ctx(adapter, user, f"{user}-retry-settle"), "结算天劫试炼"
            )
            assert recovered.code == "TRIAL_SUCCEEDED"
            assert recovered.data["dao_fruit_progress"] == 380
            with sqlite3.connect(runtime.settings.database_path) as db:
                row = db.execute(
                    "SELECT inventory_json, dao_fruit_progress, tribulation_debt FROM players WHERE platform=? AND platform_user_id=?",
                    (adapter, user),
                ).fetchone()
                sessions = db.execute(
                    "SELECT trial_key, status, COUNT(*) FROM tribulation_trial_sessions WHERE player_id=(SELECT id FROM players WHERE platform=? AND platform_user_id=?) GROUP BY trial_key, status",
                    (adapter, user),
                ).fetchall()
            assert json.loads(row[0]) == {
                "item.tribulation_token": 1,
                "item.dao_fruit_fragment": 1,
            }
            assert row[1:] == (380, 10)
            assert set(sessions) == {
                ("trial.body_and_mind", "failed", 1),
                ("trial.body_and_mind", "succeeded", 1),
            }
            await runtime.close()

    asyncio.run(run())


def test_ascend_route_adds_1000_bp_to_trial_progress() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            clock = MutableClock()
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            adapter = "onebot.v11"
            user = "trial-ascend-route"
            await _create_trial_player(runtime, adapter, user)
            player_id = _join_route_sect(
                runtime,
                clock,
                adapter,
                user,
                "route.dao_settlement.ascend",
                sect_id="sect-ascend",
                sect_name="飞升宗",
            )
            started = await runtime.dispatch(
                _ctx(adapter, user, "route-trial-start"), "开始天劫试炼 身心劫"
            )
            assert started.code == "TRIAL_STARTED", started.message
            assert started.data["battle_outcome"] == "won"
            clock.advance(minutes=31)
            settled = await runtime.dispatch(
                _ctx(adapter, user, "route-trial-settle"), "结算天劫试炼"
            )
            assert settled.code == "TRIAL_SUCCEEDED", settled.message
            assert settled.data["base_progress_reward"] == 100
            assert settled.data["route_bonus_bp"] == 1000
            assert settled.data["reward_progress"] == 110
            assert settled.data["dao_fruit_progress"] == 390
            assert (
                "道果进度 +110（基础 100 + 飞升路线 10% = 110）"
                in settled.message
            )
            with sqlite3.connect(runtime.settings.database_path) as db:
                progress = db.execute(
                    "SELECT dao_fruit_progress FROM players WHERE id=?", (player_id,)
                ).fetchone()[0]
            assert progress == 390
            await runtime.close()

    asyncio.run(run())


def test_route_bonus_only_applies_to_an_active_sect_on_the_ascend_route() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            clock = MutableClock()
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            adapter = "onebot.v11"
            scenarios = (
                ("route-no-sect", None, None),
                ("route-no-route", "sect-no-route", None),
                ("route-guard-world", "sect-guard", "route.dao_settlement.guard_world"),
                ("route-remain", "sect-remain", "route.dao_settlement.remain"),
                ("route-defaults-only", "sect-defaults", "route.dao_settlement.defaults"),
            )
            for user, sect_id, route_key in scenarios:
                await _create_trial_player(runtime, adapter, user)
                if sect_id is not None:
                    _join_route_sect(
                        runtime, clock, adapter, user, route_key, sect_id=sect_id
                    )
                started = await runtime.dispatch(
                    _ctx(adapter, user, f"{user}-start"), "开始天劫试炼 身心劫"
                )
                assert started.code == "TRIAL_STARTED", started.message
                assert started.data["battle_outcome"] == "won"
                clock.advance(minutes=31)
                settled = await runtime.dispatch(
                    _ctx(adapter, user, f"{user}-settle"), "结算天劫试炼"
                )
                assert settled.code == "TRIAL_SUCCEEDED", settled.message
                assert settled.data["base_progress_reward"] == 100, user
                assert settled.data["route_bonus_bp"] == 0, user
                assert settled.data["reward_progress"] == 100, user
                assert settled.data["dao_fruit_progress"] == 380, user
                assert "飞升路线" not in settled.message, user
            await runtime.close()

    asyncio.run(run())


def test_route_bonus_is_resolved_when_the_trial_settles() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            clock = MutableClock()
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            adapter = "qq.official"
            user = "route-during-battle"
            await _create_trial_player(runtime, adapter, user)
            started = await runtime.dispatch(
                _ctx(adapter, user, "route-during-start"), "开始天劫试炼 身心劫"
            )
            assert started.code == "TRIAL_STARTED", started.message
            assert started.data["battle_outcome"] == "won"
            _join_route_sect(
                runtime,
                clock,
                adapter,
                user,
                "route.dao_settlement.ascend",
                sect_id="sect-late-route",
                sect_name="后立宗",
            )
            clock.advance(minutes=31)
            settled = await runtime.dispatch(
                _ctx(adapter, user, "route-during-settle"), "结算天劫试炼"
            )
            assert settled.code == "TRIAL_SUCCEEDED", settled.message
            assert settled.data["base_progress_reward"] == 100
            assert settled.data["route_bonus_bp"] == 1000
            assert settled.data["reward_progress"] == 110
            assert settled.data["dao_fruit_progress"] == 390
            await runtime.close()

    asyncio.run(run())


def test_failed_trial_earns_no_ascend_route_bonus() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            clock = MutableClock()
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            adapter, user = "qq.official", "route-failed"
            await _create_trial_player(runtime, adapter, user, strong=False)
            _join_route_sect(
                runtime,
                clock,
                adapter,
                user,
                "route.dao_settlement.ascend",
                sect_id="sect-failed",
                sect_name="败试宗",
            )
            operation = next(
                f"{user}-failed-{index}"
                for index in range(1_000)
                if trial_roll_bp(f"{user}-failed-{index}") >= 7_000
            )
            started = await runtime.dispatch(
                _ctx(adapter, user, operation), "开始天劫试炼 身心劫"
            )
            assert started.code == "TRIAL_STARTED", started.message
            assert started.data["battle_outcome"] == "lost"
            clock.advance(minutes=31)
            failed = await runtime.dispatch(
                _ctx(adapter, user, f"{user}-failed-settle"), "结算天劫试炼"
            )
            assert failed.code == "TRIAL_FAILED", failed.message
            assert failed.data["base_progress_reward"] == 0
            assert failed.data["route_bonus_bp"] == 0
            assert failed.data["reward_progress"] == 0
            assert failed.data["dao_fruit_progress"] == 280
            assert "飞升路线" not in failed.message
            await runtime.close()

    asyncio.run(run())


def test_ascend_route_bonus_respects_the_fruit_progress_cap() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            clock = MutableClock()
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            adapter, user = "onebot.v11", "route-capped"
            await _create_trial_player(runtime, adapter, user)
            player_id = _join_route_sect(
                runtime,
                clock,
                adapter,
                user,
                "route.dao_settlement.ascend",
                sect_id="sect-capped",
                sect_name="满果宗",
            )
            with sqlite3.connect(runtime.settings.database_path) as db:
                db.execute(
                    "UPDATE players SET dao_fruit_progress=1290 WHERE id=?",
                    (player_id,),
                )
            started = await runtime.dispatch(
                _ctx(adapter, user, "route-capped-start"), "开始天劫试炼 身心劫"
            )
            assert started.code == "TRIAL_STARTED", started.message
            assert started.data["battle_outcome"] == "won"
            clock.advance(minutes=31)
            settled = await runtime.dispatch(
                _ctx(adapter, user, "route-capped-settle"), "结算天劫试炼"
            )
            assert settled.code == "TRIAL_SUCCEEDED", settled.message
            assert settled.data["base_progress_reward"] == 100
            assert settled.data["route_bonus_bp"] == 1000
            assert settled.data["reward_progress"] == 10
            assert settled.data["dao_fruit_progress"] == 1300
            assert "道果进度 +10（基础 100 + 飞升路线 10% = 110" in settled.message
            assert "已达道果进度上限" in settled.message
            with sqlite3.connect(runtime.settings.database_path) as db:
                progress = db.execute(
                    "SELECT dao_fruit_progress FROM players WHERE id=?", (player_id,)
                ).fetchone()[0]
            assert progress == 1300
            await runtime.close()

    asyncio.run(run())


def test_replay_and_restart_keep_the_settled_route_bonus() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            clock = MutableClock()
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            adapter, user = "onebot.v11", "route-replay"
            await _create_trial_player(runtime, adapter, user)
            player_id = _join_route_sect(
                runtime,
                clock,
                adapter,
                user,
                "route.dao_settlement.ascend",
                sect_id="sect-replay",
                sect_name="重放宗",
            )
            started = await runtime.dispatch(
                _ctx(adapter, user, "route-replay-start"), "开始天劫试炼 身心劫"
            )
            assert started.code == "TRIAL_STARTED", started.message
            assert started.data["battle_outcome"] == "won"
            clock.advance(minutes=31)
            settled = await runtime.dispatch(
                _ctx(adapter, user, "route-replay-settle"), "结算天劫试炼"
            )
            assert settled.code == "TRIAL_SUCCEEDED", settled.message
            assert settled.data["reward_progress"] == 110
            assert settled.data["dao_fruit_progress"] == 390
            replay = await runtime.dispatch(
                _ctx(adapter, user, "route-replay-settle"), "结算天劫试炼"
            )
            assert replay.code == "TRIAL_SUCCEEDED"
            assert replay.data["idempotent_replay"] is True
            assert replay.data["base_progress_reward"] == 100
            assert replay.data["route_bonus_bp"] == 1000
            assert replay.data["reward_progress"] == 110
            assert replay.data["dao_fruit_progress"] == 390
            await runtime.close()

            restarted = create_runtime(data_dir=data_dir, clock=clock)
            try:
                with sqlite3.connect(restarted.settings.database_path) as db:
                    progress = db.execute(
                        "SELECT dao_fruit_progress FROM players WHERE id=?",
                        (player_id,),
                    ).fetchone()[0]
                    stored = json.loads(
                        db.execute(
                            "SELECT result_json FROM tribulation_trial_sessions "
                            "WHERE player_id=? ORDER BY id DESC LIMIT 1",
                            (player_id,),
                        ).fetchone()[0]
                    )
                assert progress == 390
                assert stored["base_progress_reward"] == 100
                assert stored["route_bonus_bp"] == 1000
                assert stored["reward_progress"] == 110
                replay_after_restart = await restarted.dispatch(
                    _ctx(adapter, user, "route-replay-settle"), "结算天劫试炼"
                )
                assert replay_after_restart.code == "TRIAL_SUCCEEDED"
                assert replay_after_restart.data["idempotent_replay"] is True
                assert replay_after_restart.data["reward_progress"] == 110
                assert replay_after_restart.data["dao_fruit_progress"] == 390
            finally:
                await restarted.close()

    asyncio.run(run())


def test_legacy_settlement_payload_without_bonus_fields_replays_as_zero_bonus() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            clock = MutableClock()
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            adapter, user = "onebot.v11", "route-legacy"
            await _create_trial_player(runtime, adapter, user)
            _join_route_sect(
                runtime,
                clock,
                adapter,
                user,
                "route.dao_settlement.ascend",
                sect_id="sect-legacy",
                sect_name="旧案宗",
            )
            started = await runtime.dispatch(
                _ctx(adapter, user, "route-legacy-start"), "开始天劫试炼 身心劫"
            )
            assert started.code == "TRIAL_STARTED", started.message
            assert started.data["battle_outcome"] == "won"
            clock.advance(minutes=31)
            settled = await runtime.dispatch(
                _ctx(adapter, user, "route-legacy-settle"), "结算天劫试炼"
            )
            assert settled.code == "TRIAL_SUCCEEDED", settled.message
            with sqlite3.connect(runtime.settings.database_path) as db:
                payload = json.loads(
                    db.execute(
                        "SELECT result_json FROM operations WHERE operation_id=?",
                        ("route-legacy-settle",),
                    ).fetchone()[0]
                )
                payload.pop("base_progress_reward")
                payload.pop("route_bonus_bp")
                db.execute(
                    "UPDATE operations SET result_json=? WHERE operation_id=?",
                    (json.dumps(payload, ensure_ascii=False, sort_keys=True), "route-legacy-settle"),
                )
            replay = await runtime.dispatch(
                _ctx(adapter, user, "route-legacy-settle"), "结算天劫试炼"
            )
            assert replay.code == "TRIAL_SUCCEEDED"
            assert replay.data["idempotent_replay"] is True
            assert replay.data["base_progress_reward"] == 0
            assert replay.data["route_bonus_bp"] == 0
            assert replay.data["reward_progress"] == 110
            assert replay.data["dao_fruit_progress"] == 390
            assert "飞升路线" not in replay.message
            await runtime.close()

    asyncio.run(run())
