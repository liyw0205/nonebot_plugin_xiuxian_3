from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.events.rules import final_heaven_season_window
from nonebot_plugin_xiuxian_3.xiuxian.progression.endgame_rules import trial_roll_bp


def _ctx(adapter: str, user: str, operation: str) -> CommandContext:
    return CommandContext(adapter=adapter, user_id=user, operation_id=operation)


async def _created(runtime, adapter: str, user: str) -> None:
    assert (await runtime.dispatch(_ctx(adapter, user, f"create-{user}"), "开始修仙")).ok


def _set_player(runtime, adapter: str, user: str, **values) -> None:
    assignments = ", ".join(f"{key} = ?" for key in values)
    params = list(values.values()) + [adapter, user]
    with sqlite3.connect(runtime.settings.database_path) as db:
        db.execute(
            f"UPDATE players SET {assignments} WHERE platform = ? AND platform_user_id = ?",
            params,
        )


def _past_trial(runtime, session_id: str) -> None:
    with sqlite3.connect(runtime.settings.database_path) as db:
        db.execute(
            "UPDATE tribulation_trial_sessions SET ends_at = ? WHERE session_id = ?",
            ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(), session_id),
        )


def test_qq_and_onebot_endgame_entry_and_trial_settlement() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            for adapter, user in (("qq.official", "qq-endgame"), ("onebot.v11", "onebot-endgame")):
                await _created(runtime, adapter, user)
                _set_player(
                    runtime,
                    adapter,
                    user,
                    stage="cultivator",
                    realm_key="void_refining",
                    realm_layer=10,
                    cultivation=2_150_000,
                    total_cultivation=2_998_960,
                    spirit_stones=500_000,
                    world_merit=3_000,
                    path_key="body",
                    intro_json=json.dumps({"flags": ["quest.dao_union"]}),
                    inventory_json=json.dumps({"item.dao_fruit_fragment": 10}),
                )
                union = await runtime.dispatch(_ctx(adapter, user, f"union-{adapter}"), "开始合道")
                assert union.code == "DAO_UNION_STARTED"
                _set_player(
                    runtime,
                    adapter,
                    user,
                    realm_key="dao_union",
                    realm_layer=10,
                    cultivation=6_000_000,
                    total_cultivation=8_998_960,
                )
                entry = await runtime.dispatch(_ctx(adapter, user, f"entry-{adapter}"), "开始渡劫")
                assert entry.code == "TRIBULATION_STARTED"
                _set_player(
                    runtime,
                    adapter,
                    user,
                    realm_key="tribulation",
                    realm_layer=3,
                    cultivation=220_000,
                    inventory_json=json.dumps({"item.tribulation_token": 1}),
                )
                operation = next(
                    f"{adapter}-trial-{index}"
                    for index in range(1000)
                    if trial_roll_bp(f"{adapter}-trial-{index}") < 7000
                )
                started = await runtime.dispatch(
                    _ctx(adapter, user, operation), "开始天劫试炼 身心劫"
                )
                assert started.code == "TRIAL_STARTED"
                _past_trial(runtime, started.data["session_id"])
                settled = await runtime.dispatch(
                    _ctx(adapter, user, f"settle-{adapter}"), "结算天劫试炼"
                )
                assert settled.code == "TRIAL_SUCCEEDED"
                replay = await runtime.dispatch(
                    _ctx(adapter, user, f"settle-{adapter}"), "结算天劫试炼"
                )
                assert replay.code == "TRIAL_SUCCEEDED"
                assert replay.data["idempotent_replay"] is True
            await runtime.close()

    asyncio.run(run())


def test_trial_order_token_atomicity_and_failure_cooldown() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            adapter, user = "onebot.v11", "trial-contract"
            await _created(runtime, adapter, user)
            _set_player(
                runtime,
                adapter,
                user,
                stage="cultivator",
                realm_key="tribulation",
                realm_layer=6,
                cultivation=850_000,
                total_cultivation=8_998_960,
                path_key="body",
                faction_reputation_json=json.dumps({"xuantian": 2_000, "demon": 2_000, "beast": 2_000}),
                inventory_json=json.dumps({}),
            )
            missing = await runtime.dispatch(
                _ctx(adapter, user, "missing-token"), "开始天劫试炼 身心劫"
            )
            assert missing.code == "TRIBULATION_TOKEN_INSUFFICIENT"
            with sqlite3.connect(runtime.settings.database_path) as db:
                db.execute(
                    "UPDATE players SET inventory_json = ? WHERE platform_user_id = ?",
                    (json.dumps({"item.tribulation_token": 1}), user),
                )
            skipped = await runtime.dispatch(
                _ctx(adapter, user, "skip"), "开始天劫试炼 三界劫"
            )
            assert skipped.code == "TRIAL_SEQUENCE_INVALID"
            operation = next(
                f"failure-{index}" for index in range(1000) if trial_roll_bp(f"failure-{index}") >= 7000
            )
            _set_player(runtime, adapter, user, realm_layer=3, cultivation=220_000)
            started = await runtime.dispatch(
                _ctx(adapter, user, operation), "开始天劫试炼 身心劫"
            )
            assert started.code == "TRIAL_STARTED"
            _past_trial(runtime, started.data["session_id"])
            failed = await runtime.dispatch(
                _ctx(adapter, user, "failure-settle"), "结算天劫试炼"
            )
            assert failed.code == "TRIAL_FAILED"
            assert failed.data["tribulation_debt"] == 10
            cooldown = await runtime.dispatch(
                _ctx(adapter, user, "cooldown"), "开始天劫试炼 身心劫"
            )
            assert cooldown.code == "TRIBULATION_COOLDOWN"
            with sqlite3.connect(runtime.settings.database_path) as db:
                inventory = json.loads(
                    db.execute(
                        "SELECT inventory_json FROM players WHERE platform_user_id = ?", (user,)
                    ).fetchone()[0]
                )
            assert inventory.get("item.tribulation_token", 0) == 0
            await runtime.close()

    asyncio.run(run())


def test_tribulation_layer_requires_ordered_trials_and_origin_tasks() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            adapter, user = "qq.official", "layer-gate"
            await _created(runtime, adapter, user)
            _set_player(
                runtime,
                adapter,
                user,
                stage="cultivator",
                realm_key="tribulation",
                realm_layer=3,
                cultivation=380_000,
                total_cultivation=8_998_960,
            )
            blocked = await runtime.dispatch(_ctx(adapter, user, "blocked"), "晋升境界")
            assert blocked.code == "TRIAL_SEQUENCE_INVALID"
            with sqlite3.connect(runtime.settings.database_path) as db:
                db.execute(
                    "INSERT INTO tribulation_trial_sessions(session_id, player_id, operation_id, trial_key, status, starts_at, ends_at, result_json, created_at, updated_at) "
                    "SELECT 's1', id, 'op-s1', 'trial.body_and_mind', 'succeeded', 'x', 'x', '{}', 'x', 'x' FROM players WHERE platform_user_id = ?",
                    (user,),
                )
            advanced = await runtime.dispatch(_ctx(adapter, user, "advance"), "晋升境界")
            assert advanced.code == "REALM_LAYER_ADVANCED"
            assert advanced.data["realm_layer"] == 4
            await runtime.close()

    asyncio.run(run())


def test_tribulation_l10_requires_three_current_season_events_per_origin_task() -> None:
    async def run() -> None:
        now = datetime(2026, 9, 24, tzinfo=timezone.utc)
        season_id, _, _ = final_heaven_season_window(now)
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=lambda: now)
            for adapter, user in (("qq.official", "qq-season-gate"), ("onebot.v11", "ob-season-gate")):
                await _created(runtime, adapter, user)
                _set_player(
                    runtime,
                    adapter,
                    user,
                    stage="cultivator",
                    realm_key="tribulation",
                    realm_layer=9,
                    cultivation=2_400_000,
                    total_cultivation=8_998_960,
                )
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    player_id = connection.execute(
                        "SELECT id FROM players WHERE platform = ? AND platform_user_id = ?",
                        (adapter, user),
                    ).fetchone()[0]
                    for index, trial_key in enumerate(
                        ("trial.body_and_mind", "trial.three_realms", "trial.dao_choice"), start=1
                    ):
                        connection.execute(
                            "INSERT INTO tribulation_trial_sessions(session_id, player_id, operation_id, trial_key, status, starts_at, ends_at, result_json, created_at, updated_at) "
                            "VALUES (?, ?, ?, ?, 'succeeded', 'start', 'end', '{}', 'created', 'updated')",
                            (f"{user}-trial-{index}", player_id, f"{user}-trial-op-{index}", trial_key),
                        )
                    for task_key in (
                        "task.dao_origin.guard",
                        "task.dao_origin.build",
                        "task.dao_origin.teach",
                    ):
                        for index in range(3):
                            event_season = season_id if index < 2 else "season.final_heaven:stale"
                            connection.execute(
                                "INSERT INTO quest_events(player_id, quest_key, component_key, source_operation_id, outcome, payload_json, content_version, rule_version, created_at) "
                                "VALUES (?, ?, 'completed', ?, 'success', ?, 'content-0.6', 'events-0.6.0', 'created')",
                                (
                                    player_id,
                                    task_key,
                                    f"{user}-{task_key}-{index}",
                                    json.dumps({"season_id": event_season}),
                                ),
                            )

                blocked = await runtime.dispatch(
                    _ctx(adapter, user, f"l10-blocked-{adapter}"), "晋升境界"
                )
                assert blocked.code == "TRIAL_SEQUENCE_INVALID"

                with sqlite3.connect(runtime.settings.database_path) as connection:
                    for task_key in (
                        "task.dao_origin.guard",
                        "task.dao_origin.build",
                        "task.dao_origin.teach",
                    ):
                        connection.execute(
                            "UPDATE quest_events SET payload_json = ? WHERE player_id = ? AND quest_key = ?",
                            (json.dumps({"season_id": season_id}), player_id, task_key),
                        )

                advanced = await runtime.dispatch(
                    _ctx(adapter, user, f"l10-ready-{adapter}"), "晋升境界"
                )
                assert advanced.code == "REALM_LAYER_ADVANCED"
                assert advanced.data["realm_layer"] == 10
            await runtime.close()

    asyncio.run(run())


def test_qq_and_onebot_choose_ascension_endings_and_freeze_writes() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            for adapter, user in (("qq.official", "qq-ending"), ("onebot.v11", "onebot-ending")):
                await _created(runtime, adapter, user)
                blocked = await runtime.dispatch(
                    _ctx(adapter, user, f"ending-blocked-{adapter}"), "选择结局 飞升"
                )
                assert blocked.code == "ASCENSION_REQUIREMENT_MISSING"
                _set_player(
                    runtime,
                    adapter,
                    user,
                    stage="cultivator",
                    realm_key="tribulation",
                    realm_layer=10,
                    total_cultivation=8_998_960,
                    endgame_status="ascension_ready",
                    dao_fruit_key=None,
                )
                frozen_candidate = await runtime.dispatch(
                    _ctx(adapter, user, f"rename-candidate-{adapter}"), "修仙改名 候选后"
                )
                assert frozen_candidate.code == "PLAYER_SUSPENDED"
                chosen = await runtime.dispatch(
                    _ctx(adapter, user, f"ending-{adapter}"), "终局选择 飞升"
                )
                assert chosen.code == "ENDING_CHOSEN"
                assert chosen.data["ending_key"] == "ascend"
                assert chosen.data["status"] == "ascended"
                replay = await runtime.dispatch(
                    _ctx(adapter, user, f"ending-{adapter}"), "选择结局 ascend"
                )
                assert replay.code == "ENDING_CHOSEN"
                assert replay.data["idempotent_replay"] is True
                conflict = await runtime.dispatch(
                    _ctx(adapter, user, f"ending-conflict-{adapter}"), "选择结局 留界"
                )
                assert conflict.code == "ENDING_ALREADY_CHOSEN"
                frozen = await runtime.dispatch(
                    _ctx(adapter, user, f"rename-after-ending-{adapter}"), "修仙改名 终局后"
                )
                assert frozen.code == "PLAYER_SUSPENDED"
                with sqlite3.connect(runtime.settings.database_path) as db:
                    ending = db.execute(
                        "SELECT endgame_endings.ending_key, endgame_endings.status, endgame_endings.operation_id FROM endgame_endings "
                        "JOIN players ON players.id = endgame_endings.player_id "
                        "WHERE players.platform = ? AND players.platform_user_id = ?",
                        (adapter, user),
                    ).fetchone()
                assert ending == ("ascend", "ascended", f"ending-{adapter}")
            await runtime.close()

    asyncio.run(run())


def test_qq_and_onebot_final_battle_preview_is_read_only() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            for adapter, user, command in (
                ("qq.official", "qq-final-preview", "终局战预览"),
                ("onebot.v11", "onebot-final-preview", "预览终局战"),
            ):
                await _created(runtime, adapter, user)
                _set_player(runtime, adapter, user, tribulation_debt=100)
                blocked = await runtime.dispatch(_ctx(adapter, user, f"preview-blocked-{adapter}"), command)
                assert blocked.code == "FINAL_BATTLE_PREVIEW"
                assert blocked.data["ready"] is False
                assert blocked.data["runtime_open"] is False
                assert blocked.data["missing"] == (
                    "TRIBULATION_L10_REQUIRED",
                    "TRIBULATION_TRIALS_INCOMPLETE",
                    "DAO_FRUIT_PROGRESS_INSUFFICIENT",
                    "ASCENSION_MERIT_INSUFFICIENT",
                    "TRIBULATION_DEBT_BLOCKED",
                    "ASCENSION_CERTIFICATE_MISSING",
                )

                _set_player(
                    runtime,
                    adapter,
                    user,
                    stage="cultivator",
                    realm_key="tribulation",
                    realm_layer=10,
                    dao_fruit_progress=1_000,
                    ascension_merit=1_000,
                    tribulation_debt=0,
                    inventory_json=json.dumps({"item.ascension_certificate": 1}),
                )
                with sqlite3.connect(runtime.settings.database_path) as db:
                    player_id = db.execute(
                        "SELECT id FROM players WHERE platform = ? AND platform_user_id = ?",
                        (adapter, user),
                    ).fetchone()[0]
                    for index, trial_key in enumerate(
                        ("trial.body_and_mind", "trial.three_realms", "trial.dao_choice"),
                        start=1,
                    ):
                        db.execute(
                            "INSERT INTO tribulation_trial_sessions(session_id, player_id, operation_id, trial_key, status, starts_at, ends_at, result_json, created_at, updated_at) "
                            "VALUES (?, ?, ?, ?, 'succeeded', 'start', 'end', '{}', 'created', 'updated')",
                            (f"{user}-trial-{index}", player_id, f"{user}-trial-op-{index}", trial_key),
                        )
                    before = db.execute(
                        "SELECT inventory_json, dao_fruit_progress, ascension_merit, tribulation_debt FROM players WHERE id = ?",
                        (player_id,),
                    ).fetchone()
                    operation_count = db.execute("SELECT COUNT(*) FROM operations WHERE player_id = ?", (player_id,)).fetchone()[0]

                ready = await runtime.dispatch(_ctx(adapter, user, f"preview-ready-{adapter}"), command)
                assert ready.code == "FINAL_BATTLE_PREVIEW"
                assert ready.data["ready"] is True
                assert ready.data["missing"] == ()
                assert ready.data["trial_keys"] == (
                    "trial.body_and_mind",
                    "trial.three_realms",
                    "trial.dao_choice",
                )
                assert ready.data["certificate_count"] == 1
                assert ready.data["runtime_open"] is False
                replay = await runtime.dispatch(_ctx(adapter, user, f"preview-ready-{adapter}"), command)
                assert replay.data == ready.data

                with sqlite3.connect(runtime.settings.database_path) as db:
                    after = db.execute(
                        "SELECT inventory_json, dao_fruit_progress, ascension_merit, tribulation_debt FROM players WHERE id = ?",
                        (player_id,),
                    ).fetchone()
                    assert after == before
                    assert db.execute("SELECT COUNT(*) FROM operations WHERE player_id = ?", (player_id,)).fetchone()[0] == operation_count
                    assert db.execute("SELECT COUNT(*) FROM endgame_sessions WHERE player_id = ?", (player_id,)).fetchone()[0] == 0

                _set_player(runtime, adapter, user, endgame_status="ascension_ready", realm_key="mortal", realm_layer=0)
                candidate = await runtime.dispatch(_ctx(adapter, user, f"preview-candidate-{adapter}"), command)
                assert candidate.code == "FINAL_BATTLE_PREVIEW"
                assert candidate.data["ready"] is True
                assert candidate.data["missing"] == ()
                assert candidate.data["endgame_status"] == "ascension_ready"
            await runtime.close()

    asyncio.run(run())


def test_remain_in_world_requires_dao_fruit_and_records_one_ending() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            adapter, user = "onebot.v11", "remain-ending"
            await _created(runtime, adapter, user)
            _set_player(
                runtime,
                adapter,
                user,
                realm_key="tribulation",
                realm_layer=10,
                total_cultivation=8_998_960,
                endgame_status="ascension_ready",
                dao_fruit_key=None,
            )
            missing_fruit = await runtime.dispatch(
                _ctx(adapter, user, "remain-missing-fruit"), "选择结局 留界"
            )
            assert missing_fruit.code == "ASCENSION_REQUIREMENT_MISSING"
            _set_player(runtime, adapter, user, dao_fruit_key="fruit.immortal_body")
            chosen = await runtime.dispatch(
                _ctx(adapter, user, "remain-choice"), "选择结局 留界"
            )
            assert chosen.code == "ENDING_CHOSEN"
            assert chosen.data["ending_key"] == "remain_in_world"
            assert chosen.data["status"] == "remained_in_world"
            assert chosen.data["realm_key"] == "tribulation"
            with sqlite3.connect(runtime.settings.database_path) as db:
                count, fruit = db.execute(
                    "SELECT COUNT(*), MAX(fruit_key) FROM endgame_endings "
                    "JOIN players ON players.id = endgame_endings.player_id "
                    "WHERE players.platform_user_id = ?",
                    (user,),
                ).fetchone()
            assert (count, fruit) == (1, "fruit.immortal_body")
            await runtime.close()

    asyncio.run(run())
