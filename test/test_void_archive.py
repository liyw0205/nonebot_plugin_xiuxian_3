from __future__ import annotations

import asyncio
import json
import shutil
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from combat_fixtures import BALANCED_QUALIFICATION
from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError
from nonebot_plugin_xiuxian_3.xiuxian.events.void_archive_rules import void_archive_definition
from nonebot_plugin_xiuxian_3.xiuxian.world.void_rules import void_route_roll_bp


def _ctx(adapter: str, user: str, operation: str) -> CommandContext:
    return CommandContext(
        adapter=adapter,
        user_id=user,
        request_id=operation,
        operation_id=operation,
        can_write_assets=True,
    )


async def _dispatch(runtime, context: CommandContext, text: str):
    return await runtime.adapters.dispatch(context.adapter, context, text)


def _past_route(runtime) -> None:
    with sqlite3.connect(runtime.settings.database_path) as db:
        db.execute(
            "UPDATE void_route_sessions SET ends_at = ? WHERE status = 'running'",
            ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),),
        )


async def _prepare(runtime, adapter: str, user: str) -> None:
    assert (await _dispatch(runtime, _ctx(adapter, user, f"create-{user}"), "开始修仙")).ok
    with sqlite3.connect(runtime.settings.database_path) as db:
        db.execute(
            "UPDATE players SET stage='cultivator', realm_key='void_refining', realm_layer=1, location_key='void.portal', stamina=200, stamina_max=200, energy=100, spirit_stones=1000, inventory_json=?, qualification_json=? WHERE platform=? AND platform_user_id=?",
            (
                json.dumps({"item.void_anchor": 30, "item.void_crystal": 20}),
                json.dumps(BALANCED_QUALIFICATION),
                adapter,
                user,
            ),
        )


async def _settle_route(runtime, adapter: str, user: str, route: str, operation: str) -> None:
    started = await _dispatch(runtime, _ctx(adapter, user, operation), f"进入虚空航道 {route}")
    assert started.code == "VOID_ROUTE_STARTED", started
    _past_route(runtime)
    settled = await _dispatch(runtime, _ctx(adapter, user, f"{operation}-settle"), "结算虚空航道")
    assert settled.code == "VOID_ROUTE_SETTLED", settled


def test_qq_and_onebot_void_archive_weekly_tasks_and_cap() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            for adapter, user in (("qq.official", "archive-qq"), ("onebot.v11", "archive-ob")):
                await _prepare(runtime, adapter, user)
                missing = await _dispatch(runtime, _ctx(adapter, user, f"missing-{adapter}"), "领取档案碎片 守卫遗迹")
                assert missing.code == "ARCHIVE_TASK_NOT_COMPLETE"

                await _settle_route(runtime, adapter, user, "第一航道", f"first-{adapter}-1")
                await _settle_route(runtime, adapter, user, "第一航道", f"first-{adapter}-2")
                archive_operation = next(
                    f"archive-{adapter}-{index}"
                    for index in range(1000)
                    if void_route_roll_bp(f"archive-{adapter}-{index}") >= 1500
                )
                await _settle_route(runtime, adapter, user, "档案遗迹", archive_operation)
                archive = await _dispatch(runtime, _ctx(adapter, user, f"archive-run-{adapter}"), "探索档案遗迹")
                assert archive.code == "ARCHIVE_RUN_SETTLED", archive
                assert archive.data["outcome"] == "won"
                archive_replay = await _dispatch(runtime, _ctx(adapter, user, f"archive-run-{adapter}"), "探索档案遗迹")
                assert archive_replay.code == "ARCHIVE_RUN_SETTLED" and archive_replay.data["idempotent_replay"] is True
                beta = await _dispatch(runtime, _ctx(adapter, user, f"claim-beta-{adapter}"), "领取档案碎片 守卫遗迹")
                assert beta.code == "ARCHIVE_TASK_CLAIMED", beta
                assert "档案碎片·守卫" in beta.message
                assert "beta" not in beta.message.lower()
                replay = await _dispatch(runtime, _ctx(adapter, user, f"claim-beta-{adapter}"), "领取档案碎片 守卫遗迹")
                assert replay.code == "ARCHIVE_TASK_CLAIMED" and replay.data["idempotent_replay"] is True
                conflict = await _dispatch(runtime, _ctx(adapter, user, f"claim-beta-{adapter}"), "领取档案碎片 初入航道")
                assert conflict.code == "OPERATION_CONFLICT"

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
                second = await _dispatch(runtime, _ctx(adapter, user, f"archive-run-2-{adapter}"), "探索档案遗迹")
                assert second.code == "ARCHIVE_RUN_SETTLED", second
                assert second.data["reward"] == {"item.void_crystal": 3}

                production = await _dispatch(runtime, _ctx(adapter, user, f"production-{adapter}"), "开始生产 虚空晶炼制")
                assert production.code == "PRODUCTION_STARTED", production
                with sqlite3.connect(runtime.settings.database_path) as db:
                    db.execute(
                        "UPDATE production_orders SET ends_at=? WHERE order_id=?",
                        ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(), production.data["order_id"]),
                    )
                completed = await _dispatch(runtime, _ctx(adapter, user, f"production-settle-{adapter}"), "领取生产")
                assert completed.code == "PRODUCTION_COMPLETED", completed

                for task_name, task_key in (("初入航道", "alpha"), ("炼制虚空晶", "gamma")):
                    claimed = await _dispatch(runtime, _ctx(adapter, user, f"claim-{task_key}-{adapter}"), f"领取档案碎片 {task_name}")
                    assert claimed.code == "ARCHIVE_TASK_CLAIMED", claimed
                status = await _dispatch(runtime, _ctx(adapter, user, f"status-{adapter}"), "档案状态")
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
            blocked = await _dispatch(runtime, _ctx("qq.official", "archive-forge", "archive-no-route"), "探索档案遗迹")
            assert blocked.code == "ARCHIVE_ROUTE_REQUIRED"
            forged = await _dispatch(runtime, _ctx("qq.official", "archive-forge", "forged"), "领取档案碎片 不存在的任务")
            assert forged.code == "INVALID_ARCHIVE_TASK"
            await runtime.close()

    asyncio.run(run())


def test_void_archive_freezes_claimed_task_and_run_across_content_reload() -> None:
    async def run() -> None:
        with TemporaryDirectory() as root:
            content_dir = Path(root) / "content"
            shutil.copytree(Path(__file__).parents[1] / "data", content_dir)
            runtime = create_runtime(data_dir=content_dir)
            adapter, user = "qq.official", "archive-snapshot"
            await _prepare(runtime, adapter, user)
            await _settle_route(runtime, adapter, user, "第一航道", "snapshot-first-1")
            await _settle_route(runtime, adapter, user, "第一航道", "snapshot-first-2")
            await _settle_route(runtime, adapter, user, "档案遗迹", "snapshot-archive-route")
            settled = await _dispatch(runtime, _ctx(adapter, user, "snapshot-run"), "探索档案遗迹")
            assert settled.code == "ARCHIVE_RUN_SETTLED"
            claimed = await _dispatch(runtime, _ctx(adapter, user, "snapshot-beta"), "领取档案碎片 守卫遗迹")
            assert claimed.code == "ARCHIVE_TASK_CLAIMED"
            await runtime.close()

            event_path = content_dir / "事件" / "事件.json"
            event_document = json.loads(event_path.read_text(encoding="utf-8"))
            archive = next(row for row in event_document["records"] if row["key"] == "event.archive_unlock")["archive"]
            beta = next(task for task in archive["tasks"] if task["key"] == "task.archive_fragment.beta")
            beta["name"] = "改动后的守卫任务"
            beta["target"] = 9
            event_path.write_text(json.dumps(event_document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            reward_path = content_dir / "奖励" / "奖励.json"
            reward_document = json.loads(reward_path.read_text(encoding="utf-8"))
            reward = next(row for row in reward_document["records"] if row["key"] == "reward.event.archive.fragment.beta")
            reward["entries"][0]["quantity"] = 9
            reward_path.write_text(json.dumps(reward_document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            recovered = create_runtime(data_dir=content_dir)
            replay = await _dispatch(recovered, _ctx(adapter, user, "snapshot-run"), "探索档案遗迹")
            assert replay.code == "ARCHIVE_RUN_SETTLED"
            assert replay.data["idempotent_replay"] is True
            task_replay = await _dispatch(recovered, _ctx(adapter, user, "snapshot-beta"), "领取档案碎片 守卫遗迹")
            assert task_replay.code == "ARCHIVE_TASK_CLAIMED"
            assert task_replay.data["idempotent_replay"] is True
            assert task_replay.data["task_name"] == "守卫遗迹"
            assert task_replay.data["target"] == 1
            assert task_replay.data["reward"]["item.archive_fragment.beta"] == 1
            status = await _dispatch(recovered, _ctx(adapter, user, "snapshot-status"), "档案状态")
            assert status.code == "ARCHIVE_STATUS"
            beta_status = status.data["tasks"]["task.archive_fragment.beta"]
            assert beta_status["target"] == 1
            assert beta_status["reward"]["item.archive_fragment.beta"] == 1
            await recovered.close()

    asyncio.run(run())


def test_void_archive_contract_rejects_unknown_task_fields_and_bad_reward_reference() -> None:
    with TemporaryDirectory() as root:
        content_dir = Path(root) / "content"
        shutil.copytree(Path(__file__).parents[1] / "data", content_dir)
        event_path = content_dir / "事件" / "事件.json"
        event_document = json.loads(event_path.read_text(encoding="utf-8"))
        archive = next(row for row in event_document["records"] if row["key"] == "event.archive_unlock")["archive"]
        archive["tasks"][0]["unexpected"] = True
        event_path.write_text(json.dumps(event_document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        with pytest.raises(ContentError):
            void_archive_definition(ContentBundle.load(content_dir))

        archive["tasks"][0].pop("unexpected")
        reward_path = content_dir / "奖励" / "奖励.json"
        reward_document = json.loads(reward_path.read_text(encoding="utf-8"))
        reward = next(row for row in reward_document["records"] if row["key"] == "reward.event.archive.first")
        reward["entries"][0]["item_key"] = "item.archive_fragment.missing"
        reward_path.write_text(json.dumps(reward_document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        event_path.write_text(json.dumps(event_document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        with pytest.raises(ContentError):
            void_archive_definition(ContentBundle.load(content_dir))


def test_void_archive_task_operation_failure_rolls_back_and_retries() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            adapter, user = "onebot.v11", "archive-operation-retry"
            await _prepare(runtime, adapter, user)
            await _settle_route(runtime, adapter, user, "第一航道", "first-onebot.v11-1")
            await _settle_route(runtime, adapter, user, "第一航道", "first-onebot.v11-2")
            archive_route_operation = next(
                f"archive-onebot.v11-{index}"
                for index in range(1000)
                if void_route_roll_bp(f"archive-onebot.v11-{index}") >= 1500
            )
            await _settle_route(runtime, adapter, user, "档案遗迹", archive_route_operation)
            settled = await _dispatch(runtime, _ctx(adapter, user, "retry-archive-run"), "探索档案遗迹")
            assert settled.code == "ARCHIVE_RUN_SETTLED"
            with sqlite3.connect(runtime.settings.database_path) as db:
                before = db.execute(
                    "SELECT inventory_json, void_merit FROM players WHERE platform=? AND platform_user_id=?",
                    (adapter, user),
                ).fetchone()
                db.execute(
                    "CREATE TRIGGER fail_archive_task_operation BEFORE INSERT ON operations "
                    "WHEN NEW.operation_id = 'archive-task-failure' "
                    "BEGIN SELECT RAISE(ABORT, 'injected archive operation failure'); END"
                )
            failed = await _dispatch(runtime, _ctx(adapter, user, "archive-task-failure"), "领取档案碎片 守卫遗迹")
            assert failed.code == "PERSISTENCE_ERROR"
            with sqlite3.connect(runtime.settings.database_path) as db:
                after = db.execute(
                    "SELECT inventory_json, void_merit FROM players WHERE platform=? AND platform_user_id=?",
                    (adapter, user),
                ).fetchone()
                assert after == before
                assert db.execute("SELECT 1 FROM void_archive_tasks WHERE operation_id=?", ("archive-task-failure",)).fetchone() is None
                db.execute("DROP TRIGGER fail_archive_task_operation")
            retried = await _dispatch(runtime, _ctx(adapter, user, "archive-task-failure"), "领取档案碎片 守卫遗迹")
            assert retried.code == "ARCHIVE_TASK_CLAIMED"
            await runtime.close()

    asyncio.run(run())
