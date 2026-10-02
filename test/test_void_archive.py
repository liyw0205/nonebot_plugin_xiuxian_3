from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.world.void_rules import void_route_roll_bp


def _ctx(adapter: str, user: str, operation: str) -> CommandContext:
    return CommandContext(
        adapter=adapter,
        user_id=user,
        request_id=operation,
        operation_id=operation,
        can_write_assets=True,
    )


def _past_route(runtime) -> None:
    with sqlite3.connect(runtime.settings.database_path) as db:
        db.execute(
            "UPDATE void_route_sessions SET ends_at = ? WHERE status = 'running'",
            ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),),
        )


async def _prepare(runtime, adapter: str, user: str) -> None:
    assert (await runtime.dispatch(_ctx(adapter, user, f"create-{user}"), "开始修仙")).ok
    with sqlite3.connect(runtime.settings.database_path) as db:
        db.execute(
            "UPDATE players SET stage='cultivator', realm_key='void_refining', realm_layer=1, location_key='void.portal', stamina=200, stamina_max=200, energy=100, spirit_stones=1000, inventory_json=? WHERE platform=? AND platform_user_id=?",
            (
                json.dumps({"item.void_anchor": 30, "item.void_crystal": 20}),
                adapter,
                user,
            ),
        )


async def _settle_route(runtime, adapter: str, user: str, route: str, operation: str) -> None:
    started = await runtime.dispatch(_ctx(adapter, user, operation), f"进入虚空航道 {route}")
    assert started.code == "VOID_ROUTE_STARTED", started
    _past_route(runtime)
    settled = await runtime.dispatch(_ctx(adapter, user, f"{operation}-settle"), "结算虚空航道")
    assert settled.code == "VOID_ROUTE_SETTLED", settled


def test_qq_and_onebot_void_archive_weekly_tasks_and_cap() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            for adapter, user in (("qq.official", "archive-qq"), ("onebot.v11", "archive-ob")):
                await _prepare(runtime, adapter, user)
                missing = await runtime.dispatch(_ctx(adapter, user, f"missing-{adapter}"), "领取档案碎片 beta")
                assert missing.code == "ARCHIVE_TASK_NOT_COMPLETE"

                await _settle_route(runtime, adapter, user, "第一航道", f"first-{adapter}-1")
                await _settle_route(runtime, adapter, user, "第一航道", f"first-{adapter}-2")
                archive_operation = next(
                    f"archive-{adapter}-{index}"
                    for index in range(1000)
                    if void_route_roll_bp(f"archive-{adapter}-{index}") >= 1500
                )
                await _settle_route(runtime, adapter, user, "档案遗迹", archive_operation)
                archive = await runtime.dispatch(_ctx(adapter, user, f"archive-run-{adapter}"), "探索档案遗迹")
                assert archive.code == "ARCHIVE_RUN_SETTLED", archive
                assert archive.data["outcome"] == "won"
                archive_replay = await runtime.dispatch(_ctx(adapter, user, f"archive-run-{adapter}"), "探索档案遗迹")
                assert archive_replay.code == "ARCHIVE_RUN_SETTLED" and archive_replay.data["idempotent_replay"] is True
                beta = await runtime.dispatch(_ctx(adapter, user, f"claim-beta-{adapter}"), "领取档案碎片 beta")
                assert beta.code == "ARCHIVE_TASK_CLAIMED", beta
                replay = await runtime.dispatch(_ctx(adapter, user, f"claim-beta-{adapter}"), "领取档案碎片 beta")
                assert replay.code == "ARCHIVE_TASK_CLAIMED" and replay.data["idempotent_replay"] is True

                with sqlite3.connect(runtime.settings.database_path) as db:
                    db.execute(
                        "UPDATE players SET inventory_json=? WHERE platform=? AND platform_user_id=?",
                        (json.dumps({"item.void_anchor": 30, "item.void_crystal": 20}), adapter, user),
                    )
                second_route = next(
                    f"archive-second-{adapter}-{index}"
                    for index in range(1000)
                    if void_route_roll_bp(f"archive-second-{adapter}-{index}") >= 1500
                )
                await _settle_route(runtime, adapter, user, "档案遗迹", second_route)
                second = await runtime.dispatch(_ctx(adapter, user, f"archive-run-2-{adapter}"), "探索档案遗迹")
                assert second.code == "ARCHIVE_RUN_SETTLED", second
                assert second.data["reward"] == {"item.void_crystal": 3}

                production = await runtime.dispatch(_ctx(adapter, user, f"production-{adapter}"), "开始生产 虚空晶炼制")
                assert production.code == "PRODUCTION_STARTED", production
                with sqlite3.connect(runtime.settings.database_path) as db:
                    db.execute(
                        "UPDATE production_orders SET ends_at=? WHERE order_id=?",
                        ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(), production.data["order_id"]),
                    )
                completed = await runtime.dispatch(_ctx(adapter, user, f"production-settle-{adapter}"), "领取生产")
                assert completed.code == "PRODUCTION_COMPLETED", completed

                for task in ("alpha", "gamma"):
                    claimed = await runtime.dispatch(_ctx(adapter, user, f"claim-{task}-{adapter}"), f"领取档案碎片 {task}")
                    assert claimed.code == "ARCHIVE_TASK_CLAIMED", claimed
                status = await runtime.dispatch(_ctx(adapter, user, f"status-{adapter}"), "档案状态")
                assert status.code == "ARCHIVE_STATUS"
                assert status.data["unlocked"] is True
                assert status.data["tasks"]["task.archive_fragment.alpha"]["progress"] == 2
                assert status.data["tasks"]["task.archive_fragment.gamma"]["progress"] == 1
            await runtime.close()

    asyncio.run(run())


def test_void_archive_rejects_forged_route_and_operation_conflicts() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            await _prepare(runtime, "qq.official", "archive-forge")
            blocked = await runtime.dispatch(_ctx("qq.official", "archive-forge", "archive-no-route"), "探索档案遗迹")
            assert blocked.code == "ARCHIVE_ROUTE_REQUIRED"
            forged = await runtime.dispatch(_ctx("qq.official", "archive-forge", "forged"), "领取档案碎片 alpha 999")
            assert forged.code == "INVALID_ARCHIVE_TASK"
            await runtime.close()

    asyncio.run(run())
