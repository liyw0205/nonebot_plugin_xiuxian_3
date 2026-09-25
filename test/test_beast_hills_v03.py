from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.exploration.rules import weighted_value


def _context(adapter: str, user: str, request: str, operation: str = "") -> CommandContext:
    return CommandContext(
        adapter=adapter,
        user_id=user,
        request_id=request,
        operation_id=operation,
        can_write_assets=True,
    )


async def _prepare_player(runtime, adapter: str, user: str, *, reputation: int) -> None:
    await runtime.adapters.dispatch(adapter, _context(adapter, user, f"create-{adapter}"), "开始修仙")
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            """
            UPDATE players
            SET stage='cultivator', realm_key='nascent_soul', realm_layer=1,
                location_key='xuantian.floating_boat', stamina=60, stamina_max=60,
                energy=30, energy_max=30, spirit_stones=1000,
                bloodline_stability=33, max_hp=100000, initiative=100000,
                qualification_json=?, faction_reputation_json=?
            WHERE platform=? AND platform_user_id=?
            """,
            (
                json.dumps({"body": 100000, "agility": 100000}, sort_keys=True),
                json.dumps({"beast": reputation}),
                adapter,
                user,
            ),
        )


def _expire(runtime, table: str, key: str, value: str) -> None:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            f"UPDATE {table} SET ends_at=? WHERE {key}=?",
            ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(), value),
        )


def test_beast_hills_gate_travel_and_blood_reward_are_idempotent_on_both_adapters() -> None:
    async def run() -> None:
        operation = next(
            f"beast-blood-{index}"
            for index in range(1000)
            if weighted_value(f"beast-blood-{index}:reward", (0, 1, 2, 3), (45, 30, 15, 10)) == 0
        )
        for adapter in ("qq.official", "onebot.v11"):
            with TemporaryDirectory() as data_dir:
                runtime = create_runtime(data_dir=Path(data_dir) / adapter)
                user = f"beast-{adapter}"
                await _prepare_player(runtime, adapter, user, reputation=199)

                preview = await runtime.adapters.dispatch(
                    adapter, _context(adapter, user, "preview"), "移动预览 万兽山"
                )
                assert preview.code == "TRAVEL_PREVIEW"
                assert preview.data["ready"] is False
                assert any("妖界声望" in item and "200" in item for item in preview.data["missing"])
                denied = await runtime.adapters.dispatch(
                    adapter, _context(adapter, user, "denied", "beast-denied"), "前往 万兽山"
                )
                assert denied.code == "FACTION_REPUTATION_INSUFFICIENT"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    assert connection.execute(
                        "SELECT stamina FROM players WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    ).fetchone()[0] == 60
                    connection.execute(
                        "UPDATE players SET faction_reputation_json=? WHERE platform=? AND platform_user_id=?",
                        (json.dumps({"beast": 200}), adapter, user),
                    )

                started = await runtime.adapters.dispatch(
                    adapter, _context(adapter, user, "start", "beast-travel"), "前往 万兽山"
                )
                assert started.code == "TRAVEL_STARTED"
                replay = await runtime.adapters.dispatch(
                    adapter, _context(adapter, user, "start-replay", "beast-travel"), "前往 beast.ten_thousand_hills"
                )
                assert replay.data["idempotent_replay"] is True
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    snapshot = connection.execute(
                        "SELECT snapshot_json FROM travel_sessions WHERE session_id=?",
                        (started.data["session_id"],),
                    ).fetchone()[0]
                assert json.loads(snapshot)["destination"] == "beast.ten_thousand_hills"
                assert json.loads(snapshot)["faction_reputation"] == 200
                _expire(runtime, "travel_sessions", "session_id", started.data["session_id"])
                assert (
                    await runtime.adapters.dispatch(
                        adapter, _context(adapter, user, "travel-settle", "beast-travel-settle"), "结算移动"
                    )
                ).code == "TRAVEL_COMPLETED"

                explored = await runtime.adapters.dispatch(
                    adapter, _context(adapter, user, "explore-start", operation), "开始探索 万兽山狩猎"
                )
                assert explored.code == "EXPLORATION_STARTED"
                assert explored.data["cross_realm_penalty_bp"] == 1000
                assert explored.data["bloodline_stability_before"] == 33
                _expire(runtime, "exploration_sessions", "exploration_id", explored.data["exploration_id"])
                settled = await runtime.adapters.dispatch(
                    adapter, _context(adapter, user, "explore-settle", "beast-settle"), "结算探索"
                )
                assert settled.code == "EXPLORATION_SETTLED"
                assert settled.data["battle_outcome"] == "won"
                assert settled.data["result"] == {"item.beast_blood": 1}
                assert settled.data["bloodline_stability_after"] == 33
                replay = await runtime.adapters.dispatch(
                    adapter, _context(adapter, user, "explore-replay", "beast-settle"), "结算探索"
                )
                assert replay.data["idempotent_replay"] is True
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    inventory, reputation, bloodline = connection.execute(
                        "SELECT inventory_json, faction_reputation_json, bloodline_stability FROM players WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    ).fetchone()
                assert json.loads(inventory)["item.beast_blood"] == 1
                assert json.loads(reputation)["beast"] == 200
                assert bloodline == 33
                await runtime.close()

    asyncio.run(run())


def test_beast_hills_clue_reward_uses_v03_snapshot() -> None:
    async def run() -> None:
        operation = next(
            f"beast-clue-{index}"
            for index in range(1000)
            if weighted_value(f"beast-clue-{index}:reward", (0, 1, 2, 3), (45, 30, 15, 10)) == 2
        )
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=Path(data_dir))
            adapter, user = "onebot.v11", "beast-clue"
            await _prepare_player(runtime, adapter, user, reputation=200)
            travel = await runtime.adapters.dispatch(
                adapter, _context(adapter, user, "travel-start", "travel"), "前往 万兽山"
            )
            assert travel.code == "TRAVEL_STARTED"
            _expire(runtime, "travel_sessions", "session_id", travel.data["session_id"])
            assert (
                await runtime.adapters.dispatch(
                    adapter, _context(adapter, user, "travel-settle", "travel-settle"), "结算移动"
                )
            ).code == "TRAVEL_COMPLETED"
            started = await runtime.adapters.dispatch(
                adapter, _context(adapter, user, "explore-start", operation), "开始探索 妖界万兽山探索"
            )
            assert started.code == "EXPLORATION_STARTED"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                snapshot = json.loads(
                    connection.execute(
                        "SELECT snapshot_json FROM exploration_sessions WHERE exploration_id=?",
                        (started.data["exploration_id"],),
                    ).fetchone()[0]
                )
            assert snapshot["random_pool"] == "loot.beast.hills.v0.3"
            assert snapshot["content_version"] == "content-0.3"
            assert snapshot["bloodline_stability_before"] == 33
            _expire(runtime, "exploration_sessions", "exploration_id", started.data["exploration_id"])
            settled = await runtime.adapters.dispatch(
                adapter, _context(adapter, user, "settle", "beast-clue-settle"), "结算探索"
            )
            assert settled.code == "EXPLORATION_SETTLED"
            assert settled.data["result"] == {"item.clue.beast_bloodline": 1}
            await runtime.close()

    asyncio.run(run())
