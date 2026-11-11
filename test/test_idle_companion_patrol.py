from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory

import pytest

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime


class Clock:
    def __init__(self) -> None:
        self.value = datetime(2026, 11, 12, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **kwargs: int) -> None:
        self.value += timedelta(**kwargs)


def _context(adapter: str, user: str, operation: str) -> CommandContext:
    return CommandContext(adapter=adapter, user_id=user, operation_id=operation)


async def _send(runtime, text: str, operation: str, *, adapter: str = "onebot.v11", user: str = "patrol"):
    return await runtime.dispatch(_context(adapter, user, operation), text)


async def _prepare(runtime, *, adapter: str = "onebot.v11", user: str = "patrol") -> str:
    assert (await _send(runtime, "开始修仙", f"{user}:create", adapter=adapter, user=user)).ok
    assert (await _send(runtime, "寻仙问道", f"{user}:seek", adapter=adapter, user=user)).ok
    with runtime.repository._connect() as connection:
        connection.execute(
            "UPDATE players SET location_key = 'xuantian.outskirts' WHERE platform = ? AND platform_user_id = ?",
            (adapter, user),
        )
    bonded = await _send(runtime, "结缘灵兽 beast.wood_rat", f"{user}:bond", adapter=adapter, user=user)
    assert bonded.code == "COMPANION_BONDED", bonded.message
    return str(bonded.data["instance_id"])


def test_companion_patrol_full_flow_restarts_and_feeds_from_real_rewards() -> None:
    async def run() -> None:
        clock = Clock()
        with TemporaryDirectory() as directory:
            runtime = create_runtime(data_dir=directory, clock=clock)
            instance_id = await _prepare(runtime)
            with runtime.repository._connect() as connection:
                initial_inventory = json.loads(
                    connection.execute("SELECT inventory_json FROM players").fetchone()[0]
                )
            preview = await _send(runtime, "挂机预览 灵兽栖地巡护", "preview")
            assert preview.data["routes"][0]["ready"]
            assert preview.data["routes"][0]["requirements"]["required_companion_kind"] == "beast"
            started = await _send(runtime, f"开始挂机 灵兽栖地巡护 {instance_id}", "start")
            assert started.code == "IDLE_STARTED", started.message
            fed_busy = await _send(runtime, f"喂养灵兽 {instance_id}", "feed-busy")
            assert fed_busy.code == "COMPANION_BUSY"
            assert fed_busy.data == {"reason": "travelling companion cannot be fed", "subject": instance_id}
            busy = await _send(runtime, f"灵兽相伴 {instance_id}", "company")
            assert busy.code == "COMPANION_BUSY"
            assert busy.data == {"reason": "travelling companion cannot be companied", "subject": instance_id}
            with runtime.repository._connect() as connection:
                state = connection.execute(
                    "SELECT status, experience, affinity FROM companion_instances WHERE instance_id = ?",
                    (instance_id,),
                ).fetchone()
                assert tuple(state) == ("travelling", 0, 0)

            await runtime.close()
            runtime = create_runtime(data_dir=directory, clock=clock)
            restored = await _send(runtime, "挂机状态", "status")
            assert restored.data["assignment"]["companion_instance_id"] == instance_id
            clock.advance(hours=4)
            claimed = await _send(runtime, "领取挂机", "claim")
            assert claimed.code == "IDLE_CLAIMED", claimed.message
            assert claimed.data["companion_progress"] == {"experience": 20, "affinity": 4}
            rice_reward = int(claimed.data["reward"]["item.food.coarse_spirit_rice"])
            assert rice_reward >= 1
            replay = await _send(runtime, "领取挂机", "claim")
            assert replay.data["idempotent_replay"] is True
            assert replay.message == claimed.message
            fed = await _send(runtime, f"喂养灵兽 {instance_id}", "feed")
            assert fed.code == "COMPANION_FED"
            with runtime.repository._connect() as connection:
                row = connection.execute(
                    "SELECT status, experience, affinity FROM companion_instances WHERE instance_id = ?",
                    (instance_id,),
                ).fetchone()
                assert tuple(row) == ("active", 30, 4)
                inventory = json.loads(
                    connection.execute("SELECT inventory_json FROM players").fetchone()[0]
                )
                assert inventory["item.food.coarse_spirit_rice"] == (
                    initial_inventory["item.food.coarse_spirit_rice"] + rice_reward - 1
                )
            await runtime.close()

    asyncio.run(run())


def test_companion_patrol_cancel_and_late_claim_restore_without_growth() -> None:
    async def run() -> None:
        clock = Clock()
        with TemporaryDirectory() as directory:
            runtime = create_runtime(data_dir=directory, clock=clock)
            instance_id = await _prepare(runtime, user="late")
            started = await _send(runtime, f"开始挂机 灵兽栖地巡护 {instance_id}", "start", user="late")
            assert started.ok
            cancelled = await _send(runtime, "取消挂机", "cancel", user="late")
            assert cancelled.code == "IDLE_CANCELLED"
            with runtime.repository._connect() as connection:
                row = connection.execute(
                    "SELECT status, experience, affinity FROM companion_instances WHERE instance_id = ?",
                    (instance_id,),
                ).fetchone()
                assert tuple(row) == ("active", 0, 0)
                assert connection.execute("SELECT stamina FROM players").fetchone()[0] == 30

            started = await _send(runtime, f"开始挂机 灵兽栖地巡护 {instance_id}", "start-2", user="late")
            assert started.ok
            clock.advance(hours=29)
            late = await _send(runtime, "领取挂机", "claim-2", user="late")
            assert late.code == "IDLE_CLAIMED"
            assert late.data["fallback"] is True
            assert late.data["companion_progress"] == {"experience": 0, "affinity": 0}
            with runtime.repository._connect() as connection:
                row = connection.execute(
                    "SELECT status, experience, affinity FROM companion_instances WHERE instance_id = ?",
                    (instance_id,),
                ).fetchone()
                assert tuple(row) == ("active", 0, 0)
            await runtime.close()

    asyncio.run(run())


def test_companion_patrol_claim_rolls_back_all_writes_on_operation_failure() -> None:
    async def run() -> None:
        clock = Clock()
        with TemporaryDirectory() as directory:
            runtime = create_runtime(data_dir=directory, clock=clock)
            instance_id = await _prepare(runtime, user="rollback")
            started = await _send(runtime, f"开始挂机 灵兽栖地巡护 {instance_id}", "start", user="rollback")
            assert started.ok
            clock.advance(hours=4)
            with runtime.repository._connect() as connection:
                connection.execute(
                    "CREATE TRIGGER fail_patrol_claim BEFORE INSERT ON operations "
                    "WHEN NEW.operation_id = 'claim' BEGIN SELECT RAISE(ABORT, 'forced patrol claim failure'); END"
                )
                before = connection.execute(
                    "SELECT status, experience, affinity FROM companion_instances WHERE instance_id = ?",
                    (instance_id,),
                ).fetchone()
                before_player = connection.execute(
                    "SELECT stamina, inventory_json FROM players"
                ).fetchone()
            with pytest.raises(sqlite3.IntegrityError, match="forced patrol claim failure"):
                await _send(runtime, "领取挂机", "claim", user="rollback")
            with runtime.repository._connect() as connection:
                after = connection.execute(
                    "SELECT status, experience, affinity FROM companion_instances WHERE instance_id = ?",
                    (instance_id,),
                ).fetchone()
                after_player = connection.execute(
                    "SELECT stamina, inventory_json FROM players"
                ).fetchone()
                assignment = connection.execute(
                    "SELECT status, claim_operation_id FROM idle_assignments"
                ).fetchone()
                assert tuple(after) == tuple(before)
                assert tuple(after_player) == tuple(before_player)
                assert tuple(assignment) == ("running", None)
            await runtime.close()

    asyncio.run(run())


def test_companion_patrol_rejects_tampered_snapshot_without_writes() -> None:
    async def run() -> None:
        clock = Clock()
        with TemporaryDirectory() as directory:
            runtime = create_runtime(data_dir=directory, clock=clock)
            instance_id = await _prepare(runtime, user="tampered")
            started = await _send(runtime, f"开始挂机 灵兽栖地巡护 {instance_id}", "start", user="tampered")
            assert started.ok
            clock.advance(hours=4)
            with runtime.repository._connect() as connection:
                assignment = connection.execute(
                    "SELECT assignment_id, snapshot_json FROM idle_assignments"
                ).fetchone()
                snapshot = json.loads(assignment["snapshot_json"])
                snapshot["companion"]["progress"]["unexpected"] = 1
                connection.execute(
                    "UPDATE idle_assignments SET snapshot_json = ? WHERE assignment_id = ?",
                    (json.dumps(snapshot, ensure_ascii=False), assignment["assignment_id"]),
                )
                before = connection.execute(
                    "SELECT status, experience, affinity FROM companion_instances WHERE instance_id = ?",
                    (instance_id,),
                ).fetchone()
            with pytest.raises(ValueError, match="companion progress has invalid fields"):
                await _send(runtime, "领取挂机", "claim", user="tampered")
            with runtime.repository._connect() as connection:
                after = connection.execute(
                    "SELECT status, experience, affinity FROM companion_instances WHERE instance_id = ?",
                    (instance_id,),
                ).fetchone()
                assignment_state = connection.execute(
                    "SELECT status, claim_operation_id FROM idle_assignments WHERE assignment_id = ?",
                    (assignment["assignment_id"],),
                ).fetchone()
                assert tuple(after) == tuple(before)
                assert tuple(assignment_state) == ("running", None)
            await runtime.close()

    asyncio.run(run())
