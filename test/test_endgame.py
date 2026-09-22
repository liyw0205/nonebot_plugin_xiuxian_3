from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
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
