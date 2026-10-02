from __future__ import annotations

import asyncio
import json
import shutil
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.exploration.rules import cloud_boat_storm_roll_bp


def _context(adapter: str, user: str, request_id: str, operation_id: str = "") -> CommandContext:
    return CommandContext(adapter=adapter, user_id=user, request_id=request_id, operation_id=operation_id)


def _set_player(runtime, adapter: str, user: str, **values: object) -> None:
    assignments = ", ".join(f"{key} = ?" for key in values)
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            f"UPDATE players SET {assignments} WHERE platform = ? AND platform_user_id = ?",
            (*values.values(), adapter, user),
        )


def _expire(runtime, exploration_id: str) -> None:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE exploration_sessions SET ends_at = ? WHERE exploration_id = ?",
            ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(), exploration_id),
        )


def _storm_operation(prefix: str) -> str:
    return next(
        f"{prefix}-{index}"
        for index in range(1000)
        if cloud_boat_storm_roll_bp(f"{prefix}-{index}") < 2500
    )


def _clear_operation(prefix: str) -> str:
    return next(
        f"{prefix}-{index}"
        for index in range(1000)
        if cloud_boat_storm_roll_bp(f"{prefix}-{index}") >= 2500
    )


def _update_record(path: Path, key: str, **changes: object) -> None:
    document = json.loads(path.read_text(encoding="utf-8"))
    next(record for record in document["records"] if record["key"] == key).update(changes)
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _set_cloud_boat_pool(data_dir: Path, rewards: dict[str, int]) -> None:
    _update_record(
        data_dir / "奖励" / "奖励.json",
        "reward_pool.exploration.cloud_boat_trial",
        outcomes=[{"weight": 1, "rewards": rewards}],
    )


def test_cloud_boat_trial_pay_and_clear_are_idempotent_for_qq_and_onebot() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            cases = (
                ("qq.official", "cloud-trial-qq", _storm_operation("qq-trial"), "支付"),
                ("onebot.v11", "cloud-trial-ob", _clear_operation("ob-trial"), "clear"),
            )
            for adapter, user, operation, mode in cases:
                created = await runtime.adapters.dispatch(adapter, _context(adapter, user, "create"), "开始修仙")
                assert created.code == "PLAYER_CREATED"
                _set_player(
                    runtime,
                    adapter,
                    user,
                    stage="cultivator",
                    realm_key="golden_core",
                    realm_layer=1,
                    location_key="xuantian.floating_boat",
                    stamina=30,
                    stamina_max=30,
                    spirit_stones=300,
                    inventory_json=json.dumps({}),
                )
                started = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "start", operation),
                    "开始探索 云舟试炼",
                )
                assert started.code == "EXPLORATION_STARTED"
                assert started.data["mode_key"] == "explore.cloud_boat_trial"
                assert started.data["stamina_cost"] == 12
                _expire(runtime, started.data["exploration_id"])
                settle_operation = f"{adapter}:settle"
                settled = await runtime.adapters.dispatch(adapter, _context(adapter, user, "settle", settle_operation), "结算探索")
                if mode == "支付":
                    assert settled.code == "EXPLORATION_STORM_PENDING"
                    chosen = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, user, "storm", operation_id=f"{adapter}:storm-pay"),
                        "选择云舟风暴 支付",
                    )
                    assert chosen.code == "EXPLORATION_STORM_SETTLED"
                    assert chosen.data["result"]["cultivation"] >= 800
                    replay = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, user, "storm-replay", operation_id=f"{adapter}:storm-pay"),
                        "选择云舟风暴 支付",
                    )
                    assert replay.data["idempotent_replay"] is True
                    with sqlite3.connect(runtime.settings.database_path) as connection:
                        state = connection.execute(
                            "SELECT stamina, spirit_stones, cultivation FROM players WHERE platform = ? AND platform_user_id = ?",
                            (adapter, user),
                        ).fetchone()
                    assert state[0:2] == (18, 200)
                else:
                    assert settled.code == "EXPLORATION_SETTLED"
                    assert 600 <= settled.data["result"]["cultivation"] <= 900
                    assert 1 <= settled.data["result"]["item.ticket.cloud_boat_fragment"] <= 2
                    replay = await runtime.adapters.dispatch(
                        adapter,
                            _context(adapter, user, "settle-replay", operation_id=settle_operation),
                        "结算探索",
                    )
                    assert replay.data["idempotent_replay"] is True
            await runtime.close()

    asyncio.run(run())


def test_cloud_boat_trial_wait_timeout_and_turn_back_paths() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            for adapter in ("qq.official", "onebot.v11"):
                for index, choice in enumerate(("等待", "超时", "返航")):
                    prefix = f"{adapter}:storm-choice:{index}"
                    user = f"cloud-trial-choice-{adapter}-{index}"
                    created = await runtime.adapters.dispatch(
                        adapter, _context(adapter, user, "create"), "开始修仙"
                    )
                    assert created.code == "PLAYER_CREATED"
                    _set_player(
                        runtime,
                        adapter,
                        user,
                        stage="cultivator",
                        realm_key="golden_core",
                        realm_layer=1,
                        location_key="xuantian.floating_boat",
                        stamina=30,
                        stamina_max=30,
                        spirit_stones=300,
                        inventory_json=json.dumps({}),
                    )
                    started = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, user, "start", _storm_operation(prefix)),
                        "开始探索 云舟试炼",
                    )
                    assert started.code == "EXPLORATION_STARTED"
                    exploration_id = str(started.data["exploration_id"])
                    with sqlite3.connect(runtime.settings.database_path) as connection:
                        snapshot = json.loads(
                            connection.execute(
                                "SELECT snapshot_json FROM exploration_sessions WHERE exploration_id=?",
                                (exploration_id,),
                            ).fetchone()[0]
                        )
                    frozen = snapshot["frozen_result"]
                    _expire(runtime, exploration_id)
                    pending = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, user, "settle", f"{prefix}:pending"),
                        "结算探索",
                    )
                    assert pending.code == "EXPLORATION_STORM_PENDING"

                    if choice == "等待":
                        wait_operation = f"{prefix}:wait"
                        waited = await runtime.adapters.dispatch(
                            adapter,
                            _context(adapter, user, "wait", wait_operation),
                            "选择云舟风暴 等待",
                        )
                        assert waited.code == "EXPLORATION_STORM_WAITING"
                        replay = await runtime.adapters.dispatch(
                            adapter,
                            _context(adapter, user, "wait-replay", wait_operation),
                            "选择云舟风暴 等待",
                        )
                        assert replay.data["idempotent_replay"] is True
                    elif choice == "超时":
                        with sqlite3.connect(runtime.settings.database_path) as connection:
                            result = json.loads(
                                connection.execute(
                                    "SELECT result_json FROM exploration_sessions WHERE exploration_id=?",
                                    (exploration_id,),
                                ).fetchone()[0]
                            )
                            result["storm_deadline"] = (
                                datetime.now(timezone.utc) - timedelta(seconds=1)
                            ).isoformat()
                            connection.execute(
                                "UPDATE exploration_sessions SET result_json=? WHERE exploration_id=?",
                                (json.dumps(result, ensure_ascii=False, sort_keys=True), exploration_id),
                            )
                        timeout_operation = f"{prefix}:timeout"
                        waited = await runtime.adapters.dispatch(
                            adapter,
                            _context(adapter, user, "timeout", timeout_operation),
                            "结算探索",
                        )
                        assert waited.code == "EXPLORATION_STORM_WAITING"
                        assert waited.data["storm_choice"] == "wait"
                        replay = await runtime.adapters.dispatch(
                            adapter,
                            _context(adapter, user, "timeout-replay", timeout_operation),
                            "结算探索",
                        )
                        assert replay.data["idempotent_replay"] is True
                    else:
                        return_operation = f"{prefix}:return"
                        returned = await runtime.adapters.dispatch(
                            adapter,
                            _context(adapter, user, "turn-back", return_operation),
                            "选择云舟风暴 返航",
                        )
                        assert returned.code == "EXPLORATION_STORM_SETTLED"
                        assert returned.data["result"] == {"stamina_refund": 6}
                        replay = await runtime.adapters.dispatch(
                            adapter,
                            _context(adapter, user, "turn-back-replay", return_operation),
                            "选择云舟风暴 返航",
                        )
                        assert replay.data["idempotent_replay"] is True
                        conflict = await runtime.adapters.dispatch(
                            adapter,
                            _context(adapter, user, "turn-back-conflict", return_operation),
                            "选择云舟风暴 等待",
                        )
                        assert conflict.code == "OPERATION_CONFLICT"
                        with sqlite3.connect(runtime.settings.database_path) as connection:
                            state = connection.execute(
                                "SELECT stamina, spirit_stones, cultivation, inventory_json FROM players "
                                "WHERE platform=? AND platform_user_id=?",
                                (adapter, user),
                            ).fetchone()
                        assert state[0:3] == (24, 300, 0)
                        assert json.loads(state[3]) == {}
                        continue

                    _expire(runtime, exploration_id)
                    settled = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, user, "settle-after-wait", f"{prefix}:finish"),
                        "结算探索",
                    )
                    assert settled.code == "EXPLORATION_SETTLED"
                    assert settled.data["result"] == frozen
            await runtime.close()

    asyncio.run(run())


def test_cloud_boat_trial_reward_freezes_across_restart_for_both_adapters() -> None:
    async def run() -> None:
        with TemporaryDirectory() as temp:
            data_dir = Path(temp) / "data"
            shutil.copytree(Path(__file__).parents[1] / "data", data_dir)
            frozen = {"cultivation": 777, "item.ticket.cloud_boat_fragment": 3}
            changed = {"cultivation": 999, "item.ticket.cloud_boat_fragment": 6}
            _set_cloud_boat_pool(data_dir, frozen)
            _update_record(
                data_dir / "道具" / "材料.json",
                "item.ticket.cloud_boat_fragment",
                name="初开云舟残票",
            )
            runtime = create_runtime(data_dir=data_dir)
            pending: dict[str, tuple[str, str, str]] = {}
            try:
                for adapter in ("qq.official", "onebot.v11"):
                    user = f"cloud-content-{adapter}"
                    created = await runtime.adapters.dispatch(
                        adapter, _context(adapter, user, "create"), "开始修仙"
                    )
                    assert created.code == "PLAYER_CREATED"
                    _set_player(
                        runtime,
                        adapter,
                        user,
                        stage="cultivator",
                        realm_key="golden_core",
                        realm_layer=1,
                        location_key="xuantian.floating_boat",
                        stamina=30,
                        stamina_max=30,
                        inventory_json=json.dumps({}),
                    )
                    operation = _clear_operation(f"content-{adapter}")
                    started = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, user, "start", operation),
                        "开始探索 云舟试炼",
                    )
                    assert started.code == "EXPLORATION_STARTED"
                    exploration_id = str(started.data["exploration_id"])
                    _expire(runtime, exploration_id)
                    with sqlite3.connect(runtime.settings.database_path) as connection:
                        snapshot = json.loads(
                            connection.execute(
                                "SELECT snapshot_json FROM exploration_sessions WHERE exploration_id=?",
                                (exploration_id,),
                            ).fetchone()[0]
                        )
                    assert snapshot["reward_pool_key"] == "reward_pool.exploration.cloud_boat_trial"
                    assert snapshot["frozen_result"] == frozen
                    assert snapshot["storm_chance_bp"] == 2500
                    pending[adapter] = (user, exploration_id, f"{adapter}:settle")
            finally:
                await runtime.close()

            _set_cloud_boat_pool(data_dir, changed)
            _update_record(
                data_dir / "道具" / "材料.json",
                "item.ticket.cloud_boat_fragment",
                name="新炼云舟残票",
            )
            recovered = create_runtime(data_dir=data_dir)
            try:
                for adapter, (user, exploration_id, settle_operation) in pending.items():
                    settled = await recovered.adapters.dispatch(
                        adapter, _context(adapter, user, "settle", settle_operation), "结算探索"
                    )
                    assert settled.code == "EXPLORATION_SETTLED"
                    assert settled.data["result"] == frozen
                    assert "境内修为 +777" in settled.message
                    assert "新炼云舟残票 ×3" in settled.message
                    with sqlite3.connect(recovered.settings.database_path) as connection:
                        inventory_text, cultivation, total_cultivation, stamina = connection.execute(
                            "SELECT inventory_json, cultivation, total_cultivation, stamina FROM players "
                            "WHERE platform=? AND platform_user_id=?",
                            (adapter, user),
                        ).fetchone()
                    assert json.loads(inventory_text) == {"item.ticket.cloud_boat_fragment": 3}
                    assert (cultivation, total_cultivation, stamina) == (777, 777, 18)
                    replay = await recovered.adapters.dispatch(
                        adapter, _context(adapter, user, "settle", settle_operation), "结算探索"
                    )
                    assert replay.data["idempotent_replay"] is True
            finally:
                await recovered.close()

    asyncio.run(run())


def test_cloud_boat_storm_pay_uses_frozen_content_after_restart_for_both_adapters() -> None:
    async def run() -> None:
        with TemporaryDirectory() as temp:
            data_dir = Path(temp) / "data"
            shutil.copytree(Path(__file__).parents[1] / "data", data_dir)
            frozen = {"cultivation": 777, "item.ticket.cloud_boat_fragment": 3}
            changed = {"cultivation": 999, "item.ticket.cloud_boat_fragment": 6}
            _set_cloud_boat_pool(data_dir, frozen)
            runtime = create_runtime(data_dir=data_dir)
            pending: list[tuple[str, str]] = []
            try:
                for adapter in ("qq.official", "onebot.v11"):
                    user = f"cloud-storm-content-{adapter}"
                    created = await runtime.adapters.dispatch(
                        adapter, _context(adapter, user, "create"), "开始修仙"
                    )
                    assert created.code == "PLAYER_CREATED"
                    _set_player(
                        runtime,
                        adapter,
                        user,
                        stage="cultivator",
                        realm_key="golden_core",
                        realm_layer=1,
                        location_key="xuantian.floating_boat",
                        stamina=30,
                        stamina_max=30,
                        spirit_stones=300,
                        inventory_json=json.dumps({}),
                    )
                    operation = _storm_operation(f"storm-content-{adapter}")
                    started = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, user, "start", operation),
                        "开始探索 云舟试炼",
                    )
                    assert started.code == "EXPLORATION_STARTED"
                    _expire(runtime, started.data["exploration_id"])
                    pending_result = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, user, "settle", f"{adapter}:settle"),
                        "结算探索",
                    )
                    assert pending_result.code == "EXPLORATION_STORM_PENDING"
                    pending.append((adapter, user))
            finally:
                await runtime.close()

            _set_cloud_boat_pool(data_dir, changed)
            recovered = create_runtime(data_dir=data_dir)
            try:
                for adapter, user in pending:
                    chosen = await recovered.adapters.dispatch(
                        adapter,
                        _context(adapter, user, "storm", f"{adapter}:storm-pay"),
                        "选择云舟风暴 支付",
                    )
                    assert chosen.code == "EXPLORATION_STORM_SETTLED"
                    assert chosen.data["result"] == {
                        "cultivation": 977,
                        "item.ticket.cloud_boat_fragment": 3,
                    }
                    with sqlite3.connect(recovered.settings.database_path) as connection:
                        spirit_stones, cultivation, total_cultivation, stamina, inventory_text = connection.execute(
                            "SELECT spirit_stones, cultivation, total_cultivation, stamina, inventory_json "
                            "FROM players WHERE platform=? AND platform_user_id=?",
                            (adapter, user),
                        ).fetchone()
                    assert (spirit_stones, cultivation, total_cultivation, stamina) == (200, 977, 977, 18)
                    assert json.loads(inventory_text) == {"item.ticket.cloud_boat_fragment": 3}
                    replay = await recovered.adapters.dispatch(
                        adapter,
                        _context(adapter, user, "storm-replay", f"{adapter}:storm-pay"),
                        "选择云舟风暴 支付",
                    )
                    assert replay.data["idempotent_replay"] is True
                    conflict = await recovered.adapters.dispatch(
                        adapter,
                        _context(adapter, user, "storm-conflict", f"{adapter}:storm-pay"),
                        "选择云舟风暴 等待",
                    )
                    assert conflict.code == "OPERATION_CONFLICT"
            finally:
                await recovered.close()

    asyncio.run(run())


def test_cloud_boat_trial_rejects_invalid_reward_without_cost_or_session() -> None:
    async def run() -> None:
        with TemporaryDirectory() as temp:
            data_dir = Path(temp) / "data"
            shutil.copytree(Path(__file__).parents[1] / "data", data_dir)
            _set_cloud_boat_pool(data_dir, {"item.missing": 1})
            for adapter in ("qq.official", "onebot.v11"):
                runtime = create_runtime(data_dir=data_dir, adapters=(adapter,))
                try:
                    user = f"cloud-invalid-{adapter}"
                    created = await runtime.adapters.dispatch(
                        adapter, _context(adapter, user, "create"), "开始修仙"
                    )
                    assert created.code == "PLAYER_CREATED"
                    _set_player(
                        runtime,
                        adapter,
                        user,
                        stage="cultivator",
                        realm_key="golden_core",
                        realm_layer=1,
                        location_key="xuantian.floating_boat",
                        stamina=30,
                        stamina_max=30,
                        inventory_json=json.dumps({}),
                    )
                    rejected = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, user, "invalid-start"),
                        "开始探索 云舟试炼",
                    )
                    assert rejected.code == "PERSISTENCE_ERROR"
                    with sqlite3.connect(runtime.settings.database_path) as connection:
                        stamina, sessions, operation = connection.execute(
                            "SELECT "
                            "(SELECT stamina FROM players WHERE platform=? AND platform_user_id=?), "
                            "(SELECT COUNT(*) FROM exploration_sessions WHERE player_id=(SELECT id FROM players WHERE platform=? AND platform_user_id=?)), "
                            "(SELECT COUNT(*) FROM operations WHERE operation_id=?)",
                            (adapter, user, adapter, user, "invalid-start"),
                        ).fetchone()
                    assert (stamina, sessions, operation) == (30, 0, 0)
                finally:
                    await runtime.close()

    asyncio.run(run())
