from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.exploration.rules import battle_roll_bp
from test_wayfaring_content import ADAPTERS, Clock, _send


def _events(runtime) -> list[tuple]:
    with sqlite3.connect(runtime.settings.database_path) as db:
        return db.execute(
            "SELECT e.source_key, e.source_operation_id, e.points, e.payload_json, "
            "o.operation_name, e.player_id=o.player_id "
            "FROM wayfaring_point_events e JOIN operations o "
            "ON o.operation_id=e.source_operation_id ORDER BY e.id"
        ).fetchall()


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_default_mixed_public_sources_reach_daily_cap_without_duplicate_points(
    tmp_path: Path, adapter: str
) -> None:
    async def run() -> None:
        clock = Clock()
        runtime = create_runtime(data_dir=tmp_path, clock=clock, adapters=(adapter,))
        try:
            for operation, command in (
                ("create", "开始修仙"),
                ("start", "开始行卷"),
                ("seek", "寻仙问道"),
                ("checkin", "道历问安"),
            ):
                result = await _send(runtime, adapter, operation, command)
                assert result.ok, (command, result)
            status = await _send(runtime, adapter, "status-before-bounty", "问道行卷")
            assert status.data["total_points"] == 30
            accepted = await _send(
                runtime, adapter, "bounty-accept", "接取悬赏 草药补给"
            )
            assert accepted.code == "BOUNTY_ACCEPTED", accepted
            status = await _send(runtime, adapter, "status-after-bounty", "问道行卷")
            assert status.data["total_points"] == 30
            with sqlite3.connect(runtime.settings.database_path) as db:
                assert db.execute(
                    "SELECT operation_name FROM operations WHERE operation_id='bounty-accept'"
                ).fetchone() == ("bounty.accept",)
            assert (await _send(runtime, adapter, "travel", "前往近郊")).ok
            for index in range(4):
                # Select a repeatable, non-combat trip without replacing source results.
                operation = next(
                    candidate
                    for candidate in (
                        f"{adapter}-gather-{index}-{seed}" for seed in range(100)
                    )
                    if battle_roll_bp(f"{candidate}:battle") >= 1000
                )
                started = await _send(runtime, adapter, operation, "开始探索 近郊采集")
                assert started.code == "EXPLORATION_STARTED", started
                before_settle = await _send(
                    runtime, adapter, f"pending-{index}", "问道行卷"
                )
                assert before_settle.data["total_points"] == min(100, 30 + index * 20)
                clock.value = datetime.fromisoformat(
                    started.data["ends_at"]
                ) + timedelta(seconds=1)
                settled = await _send(runtime, adapter, f"settle-{index}", "结算探索")
                assert settled.code == "EXPLORATION_SETTLED", settled
                assert settled.data["status"] == "settled"
                assert settled.data["mode_key"] == "explore.gather_outskirts"
                status = await _send(runtime, adapter, f"status-{index}", "问道行卷")
                assert status.data["total_points"] == min(100, 50 + index * 20)
                events = _events(runtime)
                replay = await _send(runtime, adapter, f"settle-{index}", "结算探索")
                assert replay.data["idempotent_replay"] is True
                assert replay.data["result"] == settled.data["result"]
                replay_status = await _send(
                    runtime, adapter, f"status-replay-{index}", "问道行卷"
                )
                assert replay_status.data["total_points"] == status.data["total_points"]
                assert _events(runtime) == events
            assert status.data["total_points"] == status.data["daily_points"] == 100
            assert status.data["current_level"] == 1
            events = _events(runtime)
            assert len(events) == 6
            assert {row[0] for row in events} == {
                "player.start_seeking",
                "routine.checkin.daily",
                "exploration.settle",
            }
            assert all(row[0] == row[4] and row[5] == 1 for row in events)
            assert len({row[1] for row in events}) == len(events)
            assert sum(row[2] for row in events) == 100
            gather_events = [row for row in events if row[0] == "exploration.settle"]
            assert [row[2] for row in gather_events] == [20, 20, 20, 10]
            assert all(json.loads(row[3])["raw_points"] == 20 for row in gather_events)
            assert json.loads(gather_events[-1][3])["capped"] is True
            claimed = await _send(runtime, adapter, "claim", "领取行卷 1")
            assert claimed.code == "WAYFARING_LEVEL_CLAIMED", claimed
            assert claimed.data["reward"] == {"item.herb.blood_grass": 2}
        finally:
            await runtime.close()

    asyncio.run(run())
