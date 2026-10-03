from __future__ import annotations

import asyncio
import json
import sqlite3
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pytest

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.events.daily_quest_repository import DailyQuestRepositoryMixin
from nonebot_plugin_xiuxian_3.xiuxian.events.daily_quest_rules import (
    daily_quest_rules,
    daily_task_definitions,
    select_daily_tasks,
)
from nonebot_plugin_xiuxian_3.xiuxian.exploration.rules import battle_roll_bp


ROOT = Path(__file__).parents[1]
ADAPTERS = ("qq.official", "onebot.v11")


class MutableClock:
    def __init__(self) -> None:
        self.current = datetime(2026, 1, 15, 12, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.current

    def advance(self, **kwargs: int) -> None:
        self.current += timedelta(**kwargs)


def _context(adapter: str, user: str, request: str, operation: str = "") -> CommandContext:
    return CommandContext(
        adapter=adapter,
        user_id=user,
        request_id=request,
        operation_id=operation,
        can_write_assets=True,
    )


def _insert_operation(
    runtime,
    *,
    player_id: int,
    operation_id: str,
    operation_name: str,
    result: dict[str, object],
    created_at: datetime,
) -> None:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "INSERT INTO operations(operation_id, operation_name, player_id, request_hash, result_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                operation_id,
                operation_name,
                player_id,
                "daily-task-fixture",
                json.dumps(result, sort_keys=True),
                created_at.isoformat(),
            ),
        )


def _insert_battle(runtime, *, player_id: int, battle_id: str, battle_type: str) -> None:
    now = "2026-01-15T12:00:00+00:00"
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            """
            INSERT INTO battle_sessions(
                battle_id, player_id, start_operation_id, battle_type, enemy_key,
                location_key, status, reward_status, starts_at, turn_deadline,
                result_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'settled', 'none', ?, ?, ?, ?, ?)
            """,
            (
                battle_id,
                player_id,
                f"{battle_id}:start",
                battle_type,
                "enemy.training_dummy",
                "xuantian.outskirts",
                now,
                now,
                json.dumps({"outcome": "won"}),
                now,
                now,
            ),
        )


def _daily_state(runtime, adapter: str, user: str) -> tuple[object, ...]:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        player = connection.execute(
            "SELECT spirit_stones, inventory_json, energy, cultivation, total_cultivation "
            "FROM players WHERE platform=? AND platform_user_id=?",
            (adapter, user),
        ).fetchone()
        reputation = connection.execute(
            "SELECT local_json FROM player_reputations WHERE player_id="
            "(SELECT id FROM players WHERE platform=? AND platform_user_id=?)",
            (adapter, user),
        ).fetchone()
        rounds = connection.execute(
            "SELECT round_key, business_date, status, snapshot_json FROM daily_task_rounds "
            "WHERE player_id=(SELECT id FROM players WHERE platform=? AND platform_user_id=?) "
            "ORDER BY business_date",
            (adapter, user),
        ).fetchall()
        tasks = connection.execute(
            "SELECT task_key, progress, target, status, snapshot_json FROM daily_tasks "
            "WHERE player_id=(SELECT id FROM players WHERE platform=? AND platform_user_id=?) "
            "ORDER BY round_id, position",
            (adapter, user),
        ).fetchall()
        events = connection.execute(
            "SELECT task_id, source_operation_id, source_operation_name, payload_json "
            "FROM daily_task_events WHERE player_id=(SELECT id FROM players WHERE platform=? AND platform_user_id=?) "
            "ORDER BY source_operation_id",
            (adapter, user),
        ).fetchall()
        claims = connection.execute(
            "SELECT round_id, operation_id, reward_json FROM daily_task_claims "
            "WHERE player_id=(SELECT id FROM players WHERE platform=? AND platform_user_id=?)",
            (adapter, user),
        ).fetchall()
        operations = connection.execute(
            "SELECT operation_id, request_hash, result_json FROM operations "
            "WHERE player_id=(SELECT id FROM players WHERE platform=? AND platform_user_id=?) "
            "AND operation_name='event.claim_daily_tasks'",
            (adapter, user),
        ).fetchall()
    return player, reputation, rounds, tasks, events, claims, operations


def _seed_for_tasks(content, required: set[str]) -> str:
    rules = daily_quest_rules(content)
    definitions = daily_task_definitions(content)
    for seed in (str(index) for index in range(10000)):
        if required <= {
            definition.key
            for definition in select_daily_tasks(rules, definitions, seed)
        }:
            return seed
    raise AssertionError("could not find a daily task selection for the test")


def _replace_daily_reward(path: Path, quantity: int) -> None:
    document = json.loads(path.read_text(encoding="utf-8"))
    record = next(row for row in document["records"] if row["key"] == "reward.daily_task_claim")
    next(entry for entry in record["entries"] if entry.get("currency_key") == "currency.spirit_stone")[
        "quantity"
    ] = quantity
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_daily_tasks_project_owned_settlements_and_claim_atomically(adapter: str) -> None:
    async def run() -> None:
        with TemporaryDirectory() as temp:
            data_dir = Path(temp) / "data"
            shutil.copytree(ROOT / "data", data_dir)
            clock = MutableClock()
            runtime = create_runtime(data_dir=data_dir, adapters=(adapter,), clock=clock)
            user = f"daily-{adapter}"
            other_user = f"daily-other-{adapter}"
            try:
                assert (await runtime.adapters.dispatch(
                    adapter, _context(adapter, user, "create"), "开始修仙"
                )).code == "PLAYER_CREATED"
                assert (await runtime.adapters.dispatch(
                    adapter, _context(adapter, other_user, "create-other"), "开始修仙"
                )).code == "PLAYER_CREATED"

                seed = _seed_for_tasks(
                    runtime.content,
                    {"task.daily.cultivation", "task.daily.outskirts_gather", "task.daily.checkin", "task.daily.pve_victory"},
                )
                with patch(
                    "nonebot_plugin_xiuxian_3.xiuxian.events.daily_quest_repository.secrets.token_hex",
                    return_value=seed,
                ):
                    initial = await runtime.adapters.dispatch(
                        adapter, _context(adapter, user, "daily-status"), "每日修行"
                    )
                assert initial.code == "DAILY_TASK_STATUS"
                assert len(initial.data["tasks"]) == 7
                assert "task.daily." not in initial.message
                assert "version" not in initial.message.lower()

                with sqlite3.connect(runtime.settings.database_path) as connection:
                    player_ids = dict(
                        connection.execute(
                            "SELECT platform_user_id, id FROM players WHERE platform=?",
                            (adapter,),
                        ).fetchall()
                    )
                _insert_operation(
                    runtime,
                    player_id=player_ids[user],
                    operation_id=f"failed-gather-{adapter}",
                    operation_name="exploration.settle",
                    result={
                        "exploration_id": "failed-gather",
                        "mode_key": "explore.gather_outskirts",
                        "status": "expired",
                        "result": {},
                        "battle_pending": False,
                        "expired": True,
                        "battle_outcome": None,
                    },
                    created_at=clock.current,
                )
                _insert_operation(
                    runtime,
                    player_id=player_ids[other_user],
                    operation_id=f"other-checkin-{adapter}",
                    operation_name="routine.checkin.daily",
                    result={"makeup": False, "target_date": clock.current.date().isoformat(), "consecutive_days": 1},
                    created_at=clock.current,
                )
                _insert_battle(
                    runtime,
                    player_id=player_ids[user],
                    battle_id=f"training-dummy-{adapter}",
                    battle_type="training.dummy",
                )
                _insert_operation(
                    runtime,
                    player_id=player_ids[user],
                    operation_id=f"training-resolution-{adapter}",
                    operation_name="battle.resolve",
                    result={
                        "battle_id": f"training-dummy-{adapter}",
                        "enemy_key": "enemy.training_dummy",
                        "status": "settled",
                        "outcome": "won",
                    },
                    created_at=clock.current,
                )
                filtered = await runtime.adapters.dispatch(
                    adapter, _context(adapter, user, "daily-filtered"), "每日修行"
                )
                progress = {task["task_key"]: task["progress"] for task in filtered.data["tasks"]}
                assert progress["task.daily.checkin"] == 0
                assert progress["task.daily.outskirts_gather"] == 0
                assert progress["task.daily.pve_victory"] == 0

                for suffix, command in (
                    ("seek", "寻仙问道"),
                    ("read", "完成引导 阅读"),
                    ("travel", "前往近郊"),
                    ("gather-intro", "完成引导 采集"),
                    ("craft-intro", "完成引导 炼丹"),
                    ("path", "选择道途 体修"),
                ):
                    result = await runtime.adapters.dispatch(
                        adapter, _context(adapter, user, suffix), command
                    )
                    assert result.ok, (command, result.code)

                cultivation = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "cultivation-start", f"daily-cultivation-start-{adapter}"),
                    "开始修炼",
                )
                assert cultivation.code == "CULTIVATION_STARTED"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE cultivation_sessions SET ends_at=? WHERE session_id=?",
                        ((clock.current - timedelta(seconds=1)).isoformat(), cultivation.data["session_id"]),
                    )
                settled_cultivation = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "cultivation-settle", f"daily-cultivation-settle-{adapter}"),
                    "结算修炼",
                )
                assert settled_cultivation.code == "CULTIVATION_SETTLED"

                checked_in = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "daily-checkin", f"daily-checkin-{adapter}"),
                    "道历问安",
                )
                assert checked_in.ok, checked_in.code
                for index in range(2):
                    operation = next(
                        f"daily-gather-{adapter}-{candidate}"
                        for candidate in range(index * 1000, (index + 1) * 1000)
                        if battle_roll_bp(f"daily-gather-{adapter}-{candidate}:battle") >= 1000
                    )
                    started = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, user, f"gather-start-{index}", operation),
                        "开始探索 近郊采集",
                    )
                    assert started.code == "EXPLORATION_STARTED", started.code
                    clock.advance(minutes=5)
                    with sqlite3.connect(runtime.settings.database_path) as connection:
                        connection.execute(
                            "UPDATE exploration_sessions SET ends_at=? WHERE exploration_id=?",
                            ((clock.current - timedelta(seconds=1)).isoformat(), started.data["exploration_id"]),
                        )
                    gathered = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, user, f"gather-settle-{index}", f"{operation}-settle"),
                        "结算探索",
                    )
                    assert gathered.code == "EXPLORATION_SETTLED", gathered.code
                    assert gathered.data["status"] == "settled"

                # The second source is still a server-settled exploration record;
                # its fixture keeps this test independent from random encounter timing.
                _insert_operation(
                    runtime,
                    player_id=player_ids[user],
                    operation_id=f"daily-gather-fixture-{adapter}",
                    operation_name="exploration.settle",
                    result={
                        "exploration_id": f"fixture-gather-{adapter}",
                        "mode_key": "explore.gather_outskirts",
                        "status": "settled",
                        "result": {"item.herb.blood_grass": 1},
                        "battle_pending": False,
                        "expired": False,
                        "battle_outcome": None,
                    },
                    created_at=clock.current,
                )

                ready = await runtime.adapters.dispatch(
                    adapter, _context(adapter, user, "daily-ready"), "每日修行"
                )
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    daily_events = connection.execute(
                        "SELECT source_operation_id, source_operation_name FROM daily_task_events "
                        "WHERE player_id=? ORDER BY source_operation_id",
                        (player_ids[user],),
                    ).fetchall()
                assert ready.data["completed_count"] == 3, (
                    daily_events,
                )
                assert {task["task_key"] for task in ready.data["tasks"] if task["status"] == "completed"} >= {
                    "task.daily.cultivation",
                    "task.daily.outskirts_gather",
                    "task.daily.checkin",
                }
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    assert connection.execute(
                        "SELECT COUNT(*) FROM daily_task_events WHERE player_id=?",
                        (player_ids[user],),
                    ).fetchone()[0] == 5
                await runtime.close()
            finally:
                if not runtime._closed:
                    await runtime.close()

            reward_path = data_dir / "奖励" / "奖励.json"
            _replace_daily_reward(reward_path, 777)
            recovered = create_runtime(data_dir=data_dir, adapters=(adapter,), clock=clock)
            operation_id = f"daily-claim-{adapter}"
            try:
                status = await recovered.adapters.dispatch(
                    adapter, _context(adapter, user, "daily-status-recovered"), "每日修行"
                )
                assert status.data["completed_count"] == 3
                before_failure = _daily_state(recovered, adapter, user)

                with patch.object(
                    DailyQuestRepositoryMixin,
                    "_daily_task_payload",
                    side_effect=RuntimeError("injected failure after player grant"),
                ):
                    failed_claim = await recovered.adapters.dispatch(
                        adapter,
                        _context(adapter, user, "daily-claim-failure", operation_id),
                        "领取日课嘉奖",
                    )
                assert failed_claim.code == "PERSISTENCE_ERROR"
                assert _daily_state(recovered, adapter, user) == before_failure

                claimed = await recovered.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "daily-claim", operation_id),
                    "领取日课嘉奖",
                )
                assert claimed.code == "DAILY_TASK_REWARD_CLAIMED"
                assert claimed.data["reward"]["spirit_stones"] == 50
                assert "青石镇名望 ×2" in claimed.message
                assert "local.xuantian.new_town" not in claimed.message
                assert claimed.data["snapshot"]["reward"]["assets"]["spirit_stones"] == 50
                with sqlite3.connect(recovered.settings.database_path) as connection:
                    reputation = connection.execute(
                        "SELECT local_json FROM player_reputations WHERE player_id=?",
                        (player_ids[user],),
                    ).fetchone()[0]
                    assert json.loads(reputation)["local.xuantian.new_town"] == 2
                before_replay = _daily_state(recovered, adapter, user)
                await recovered.close()

                replay_runtime = create_runtime(data_dir=data_dir, adapters=(adapter,), clock=clock)
                replay = await replay_runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "daily-claim-replay", operation_id),
                    "领取日课嘉奖",
                )
                assert replay.data["idempotent_replay"] is True
                assert replay.data["reward"]["spirit_stones"] == 50
                assert _daily_state(replay_runtime, adapter, user) == before_replay
                conflict = await replay_runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, f"other-{user}", "daily-claim-conflict", operation_id),
                    "领取日课嘉奖",
                )
                assert conflict.code == "OPERATION_CONFLICT"
                await replay_runtime.close()
            finally:
                if not recovered._closed:
                    await recovered.close()

    asyncio.run(run())


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_daily_task_round_rotates_at_utc_day_and_expires(adapter: str) -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            content_dir = Path(data_dir) / "content"
            shutil.copytree(ROOT / "data", content_dir)
            clock = MutableClock()
            runtime = create_runtime(data_dir=content_dir, adapters=(adapter,), clock=clock)
            user = f"daily-expiry-{adapter}"
            try:
                await runtime.adapters.dispatch(
                    adapter, _context(adapter, user, "create"), "开始修仙"
                )
                created = await runtime.adapters.dispatch(
                    adapter, _context(adapter, user, "daily"), "每日修行"
                )
                assert created.data["business_date"] == "2026-01-15"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE daily_tasks SET progress=target, status='completed' WHERE round_id="
                        "(SELECT id FROM daily_task_rounds WHERE business_date='2026-01-15')"
                    )
                clock.advance(days=2)
                expired = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "claim-expired", "daily-expired-claim"),
                    "领取日课嘉奖",
                )
                assert expired.code == "DAILY_TASK_REWARD_EXPIRED"
                rotated = await runtime.adapters.dispatch(
                    adapter, _context(adapter, user, "daily-next"), "每日修行"
                )
                assert rotated.data["business_date"] == "2026-01-17"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    rows = connection.execute(
                        "SELECT business_date, status FROM daily_task_rounds "
                        "WHERE player_id=(SELECT id FROM players WHERE platform=? AND platform_user_id=?) "
                        "ORDER BY business_date",
                        (adapter, user),
                    ).fetchall()
                assert rows == [("2026-01-15", "expired"), ("2026-01-17", "open")]
            finally:
                await runtime.close()

    asyncio.run(run())
