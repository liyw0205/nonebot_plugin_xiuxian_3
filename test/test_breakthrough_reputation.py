from __future__ import annotations

import asyncio
import json
import shutil
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.progression.breakthrough.rules import breakthrough_roll_bp


ADAPTERS = ("qq.official", "onebot.v11")
LOCAL_KEY = "local.xuantian.new_town"
REWARD_KEY = "reward.breakthrough.golden_core"


def _context(adapter: str, user: str, operation_id: str) -> CommandContext:
    return CommandContext(
        adapter=adapter,
        user_id=user,
        request_id=f"request:{operation_id}",
        operation_id=operation_id,
    )


def _copy_content(data_dir: Path) -> None:
    shutil.copytree(Path(__file__).parents[1] / "data", data_dir)


def _update_content(data_dir: Path, *, cap: int | None = None, amount: int | None = None, active: bool = True) -> None:
    if cap is not None:
        path = data_dir / "地图" / "地点.json"
        document = json.loads(path.read_text(encoding="utf-8"))
        location = next(row for row in document["records"] if row["key"] == "xuantian.new_town")
        location["local_reputation_maximum"] = cap
        path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if amount is not None or not active:
        path = data_dir / "奖励" / "奖励.json"
        document = json.loads(path.read_text(encoding="utf-8"))
        reward = next(row for row in document["records"] if row["key"] == REWARD_KEY)
        reward["entries"][0]["quantity"] = amount if amount is not None else reward["entries"][0]["quantity"]
        if not active:
            reward["status"] = "locked"
        path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


async def _create_cultivator(runtime, adapter: str, user: str) -> None:
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
        result = await runtime.adapters.dispatch(
            adapter,
            _context(adapter, user, f"{user}:setup:{index}"),
            command,
        )
        assert result.ok, result


def _prepare_golden_core(runtime, adapter: str, user: str, reputation: int) -> None:
    inventory = {
        "item.pill.core_condense": 1,
        "item.material.cloud_iron": 3,
        "item.manual.basic_qi": 1,
        "item.token.faction_seal": 1,
    }
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE players SET stage='cultivator', realm_key='foundation', realm_layer=10, "
            "cultivation=7700, total_cultivation=11960, foundation_quality=4000, "
            "location_key='xuantian.cloud_city', world_merit=0, spirit_stones=2000, "
            "inventory_json=? WHERE platform=? AND platform_user_id=?",
            (json.dumps(inventory, ensure_ascii=False, sort_keys=True), adapter, user),
        )
        player_id = connection.execute(
            "SELECT id FROM players WHERE platform=? AND platform_user_id=?", (adapter, user)
        ).fetchone()[0]
        connection.execute(
            "INSERT INTO player_reputations(player_id, local_json, service_reputation, updated_at) "
            "VALUES (?, ?, 0, 'test') ON CONFLICT(player_id) DO UPDATE SET local_json=excluded.local_json",
            (player_id, json.dumps({LOCAL_KEY: reputation}, sort_keys=True)),
        )


def _success_operation(user: str) -> str:
    return next(
        f"{user}:start:{index}"
        for index in range(10000)
        if breakthrough_roll_bp(f"{user}:start:{index}") < 5700
    )


async def _start_successful_run(runtime, adapter: str, user: str) -> tuple[str, str]:
    operation_id = _success_operation(user)
    started = await runtime.adapters.dispatch(
        adapter,
        _context(adapter, user, operation_id),
        "开始突破 金丹",
    )
    assert started.code == "BREAKTHROUGH_STARTED"
    assert started.data["success_bp"] == 5700
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE breakthrough_sessions SET ends_at=? WHERE session_id=?",
            (
                (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
                started.data["session_id"],
            ),
        )
    return operation_id, str(started.data["session_id"])


@pytest.mark.parametrize("adapter", ADAPTERS)
@pytest.mark.parametrize(
    ("starting_reputation", "initial_cap", "expected_reward"),
    ((30, 60, 30), (30, 1000, 75), (80, 60, 0), (1010, 1000, 0)),
)
def test_golden_core_reputation_uses_frozen_content_and_cap_after_restart(
    tmp_path: Path,
    adapter: str,
    starting_reputation: int,
    initial_cap: int,
    expected_reward: int,
) -> None:
    async def run() -> None:
        data_dir = tmp_path / "data"
        _copy_content(data_dir)
        _update_content(data_dir, cap=initial_cap, amount=75)
        user = f"{adapter}:golden-core:{starting_reputation}:{initial_cap}"
        runtime = create_runtime(data_dir=data_dir, adapters=(adapter,))
        await _create_cultivator(runtime, adapter, user)
        _prepare_golden_core(runtime, adapter, user, starting_reputation)

        start_operation, session_id = await _start_successful_run(runtime, adapter, user)
        with sqlite3.connect(runtime.settings.database_path) as connection:
            snapshot = json.loads(
                connection.execute(
                    "SELECT snapshot_json FROM breakthrough_sessions WHERE session_id=?",
                    (session_id,),
                ).fetchone()[0]
            )
        assert snapshot["success_reward"]["key"] == REWARD_KEY
        assert snapshot["success_reward"]["local_reputation"] == {LOCAL_KEY: 75}
        assert snapshot["success_reward_local_reputation_maximums"] == {LOCAL_KEY: initial_cap}
        await runtime.close()

        _update_content(data_dir, cap=2000, amount=1, active=False)
        recovered = create_runtime(data_dir=data_dir, adapters=(adapter,))
        settle_operation = f"{user}:settle"
        settled = await recovered.adapters.dispatch(
            adapter,
            _context(adapter, user, settle_operation),
            "结算突破",
        )
        assert settled.code == "BREAKTHROUGH_SUCCEEDED"
        assert settled.data["reward_local_reputation"] == expected_reward
        assert settled.data["idempotent_replay"] is False

        with sqlite3.connect(recovered.settings.database_path) as connection:
            local_raw, realm, merit = connection.execute(
                "SELECT r.local_json, p.realm_key, p.world_merit FROM players p "
                "JOIN player_reputations r ON r.player_id=p.id "
                "WHERE p.platform=? AND p.platform_user_id=?",
                (adapter, user),
            ).fetchone()
            session_result = json.loads(
                connection.execute(
                    "SELECT result_json FROM breakthrough_sessions WHERE session_id=?",
                    (session_id,),
                ).fetchone()[0]
            )
            operation_result = json.loads(
                connection.execute(
                    "SELECT result_json FROM operations WHERE operation_id=?",
                    (settle_operation,),
                ).fetchone()[0]
            )
        assert json.loads(local_raw)[LOCAL_KEY] == starting_reputation + expected_reward
        assert realm == "golden_core"
        assert merit == 100
        assert session_result["reward_local_reputation"] == expected_reward
        assert operation_result["reward_local_reputation"] == expected_reward

        replay = await recovered.adapters.dispatch(
            adapter,
            _context(adapter, user, settle_operation),
            "结算突破",
        )
        assert replay.code == "BREAKTHROUGH_SUCCEEDED"
        assert replay.data["idempotent_replay"] is True
        conflict = await recovered.adapters.dispatch(
            adapter,
            _context(adapter, f"{user}:other", settle_operation),
            "结算突破",
        )
        assert conflict.code == "OPERATION_CONFLICT"
        start_conflict = await recovered.adapters.dispatch(
            adapter,
            _context(adapter, user, start_operation),
            "结算突破",
        )
        assert start_conflict.code == "OPERATION_CONFLICT"
        await recovered.close()

        restarted = create_runtime(data_dir=data_dir, adapters=(adapter,))
        restarted_replay = await restarted.adapters.dispatch(
            adapter,
            _context(adapter, user, settle_operation),
            "结算突破",
        )
        assert restarted_replay.data["idempotent_replay"] is True
        await restarted.close()

    asyncio.run(run())


@pytest.mark.parametrize("adapter", ADAPTERS)
@pytest.mark.parametrize("failure", ("invalid_json", "non_object_json", "invalid_value", "write_trigger"))
def test_golden_core_reputation_failure_rolls_back_and_same_operation_retries(
    tmp_path: Path,
    adapter: str,
    failure: str,
) -> None:
    async def run() -> None:
        data_dir = tmp_path / "data"
        _copy_content(data_dir)
        runtime = create_runtime(data_dir=data_dir, adapters=(adapter,))
        user = f"{adapter}:golden-core-failure:{failure}"
        await _create_cultivator(runtime, adapter, user)
        _prepare_golden_core(runtime, adapter, user, 20)
        _, session_id = await _start_successful_run(runtime, adapter, user)
        settle_operation = f"{user}:settle"
        with sqlite3.connect(runtime.settings.database_path) as connection:
            if failure == "invalid_json":
                connection.execute(
                    "UPDATE player_reputations SET local_json='{' WHERE player_id=(SELECT id FROM players WHERE platform=? AND platform_user_id=?)",
                    (adapter, user),
                )
                expected_json = "{"
            elif failure == "non_object_json":
                connection.execute(
                    "UPDATE player_reputations SET local_json='[]' WHERE player_id=(SELECT id FROM players WHERE platform=? AND platform_user_id=?)",
                    (adapter, user),
                )
                expected_json = "[]"
            elif failure == "invalid_value":
                connection.execute(
                    "UPDATE player_reputations SET local_json=? WHERE player_id=(SELECT id FROM players WHERE platform=? AND platform_user_id=?)",
                    (json.dumps({LOCAL_KEY: True}), adapter, user),
                )
                expected_json = json.dumps({LOCAL_KEY: True})
            else:
                connection.execute(
                    "CREATE TRIGGER reject_breakthrough_reputation BEFORE UPDATE ON player_reputations "
                    "BEGIN SELECT RAISE(ABORT, 'reputation unavailable'); END"
                )
                expected_json = json.dumps({LOCAL_KEY: 20}, sort_keys=True)
            player_before = connection.execute(
                "SELECT realm_key, world_merit, spirit_stones, inventory_json FROM players "
                "WHERE platform=? AND platform_user_id=?",
                (adapter, user),
            ).fetchone()

        failed = await runtime.adapters.dispatch(
            adapter,
            _context(adapter, user, settle_operation),
            "结算突破",
        )
        assert failed.code == "PERSISTENCE_ERROR"
        with sqlite3.connect(runtime.settings.database_path) as connection:
            reputation_raw = connection.execute(
                "SELECT local_json FROM player_reputations WHERE player_id=(SELECT id FROM players WHERE platform=? AND platform_user_id=?)",
                (adapter, user),
            ).fetchone()[0]
            player_after = connection.execute(
                "SELECT realm_key, world_merit, spirit_stones, inventory_json FROM players "
                "WHERE platform=? AND platform_user_id=?",
                (adapter, user),
            ).fetchone()
            session_status = connection.execute(
                "SELECT status FROM breakthrough_sessions WHERE session_id=?", (session_id,)
            ).fetchone()[0]
            operation_count = connection.execute(
                "SELECT COUNT(*) FROM operations WHERE operation_id=?", (settle_operation,)
            ).fetchone()[0]
            assert reputation_raw == expected_json
            assert player_after == player_before
            assert session_status == "preparing"
            assert operation_count == 0
            if failure != "write_trigger":
                connection.execute(
                    "UPDATE player_reputations SET local_json=? WHERE player_id=(SELECT id FROM players WHERE platform=? AND platform_user_id=?)",
                    (json.dumps({LOCAL_KEY: 20}, sort_keys=True), adapter, user),
                )
            else:
                connection.execute("DROP TRIGGER reject_breakthrough_reputation")

        retried = await runtime.adapters.dispatch(
            adapter,
            _context(adapter, user, settle_operation),
            "结算突破",
        )
        assert retried.code == "BREAKTHROUGH_SUCCEEDED"
        assert retried.data["reward_local_reputation"] == 50
        replay = await runtime.adapters.dispatch(
            adapter,
            _context(adapter, user, settle_operation),
            "结算突破",
        )
        assert replay.data["idempotent_replay"] is True
        with sqlite3.connect(runtime.settings.database_path) as connection:
            assert json.loads(
                connection.execute(
                    "SELECT local_json FROM player_reputations WHERE player_id=(SELECT id FROM players WHERE platform=? AND platform_user_id=?)",
                    (adapter, user),
                ).fetchone()[0]
            )[LOCAL_KEY] == 70
        await runtime.close()

    asyncio.run(run())
