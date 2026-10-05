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


ADAPTERS = ("qq.official", "onebot.v11")


class MutableClock:
    def __init__(self, value: datetime):
        self.value = value

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **kwargs: int) -> None:
        self.value += timedelta(**kwargs)


def _context(adapter: str, user: str, operation_id: str) -> CommandContext:
    return CommandContext(adapter=adapter, user_id=user, operation_id=operation_id)


async def _enter_mortal(runtime, adapter: str, user: str) -> None:
    assert (await runtime.adapters.dispatch(adapter, _context(adapter, user, f"{user}-create"), "开始修仙")).ok
    assert (await runtime.adapters.dispatch(adapter, _context(adapter, user, f"{user}-seek"), "寻仙问道")).ok


def _set_resources(database_path: Path, adapter: str, user: str, *, stones: int, energy: int) -> None:
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "UPDATE players SET spirit_stones=?, energy=?, energy_max=30 WHERE platform=? AND platform_user_id=?",
            (stones, energy, adapter, user),
        )


def _set_reward_quantity(data_dir: Path, key: str, index: int, quantity: int) -> None:
    path = data_dir / "奖励" / "奖励.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    record = next(item for item in document["records"] if item["key"] == key)
    record["entries"][index]["quantity"] = quantity
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _set_reward_status(data_dir: Path, key: str, status: str) -> None:
    path = data_dir / "奖励" / "奖励.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    record = next(item for item in document["records"] if item["key"] == key)
    record["status"] = status
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_routine_checkin_and_makeup_rewards_follow_content_and_freeze_replays() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
        with TemporaryDirectory() as temp:
            data_dir = Path(temp) / "data"
            source = Path(__file__).parents[1] / "data"
            shutil.copytree(source, data_dir)
            runtime = create_runtime(data_dir=data_dir, clock=clock, adapters=ADAPTERS)
            checkin_operations: dict[str, str] = {}
            try:
                for adapter in ADAPTERS:
                    user = f"routine-content-{adapter}"
                    await _enter_mortal(runtime, adapter, user)
                    _set_resources(runtime.settings.database_path, adapter, user, stones=0, energy=0)
                    result = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, user, f"{user}-checkin"),
                        "道历问安",
                    )
                    assert result.ok
                    assert result.data["reward"] == {"energy": 3, "spirit_stones": 20}
                    checkin_operations[adapter] = f"{user}-checkin"

                makeup_user = "routine-content-makeup-qq.official"
                await _enter_mortal(runtime, "qq.official", makeup_user)
                _set_resources(runtime.settings.database_path, "qq.official", makeup_user, stones=100, energy=0)
                makeup = await runtime.adapters.dispatch(
                    "qq.official",
                    _context("qq.official", makeup_user, "makeup-old"),
                    "补录道历 2026-09-21",
                )
                assert makeup.ok
                assert makeup.data["reward"] == {"energy": 2, "spirit_stones": 16}
                makeup_conflict = await runtime.adapters.dispatch(
                    "qq.official",
                    _context("qq.official", makeup_user, "makeup-old"),
                    "补录道历 2026-09-20",
                )
                assert makeup_conflict.code == "OPERATION_CONFLICT"
            finally:
                await runtime.close()

            _set_reward_quantity(data_dir, "reward.routine.checkin.daily", 0, 41)
            _set_reward_quantity(data_dir, "reward.routine.checkin.daily", 1, 6)
            _set_reward_quantity(data_dir, "reward.routine.makeup.daily", 0, 29)
            _set_reward_quantity(data_dir, "reward.routine.makeup.daily", 1, 5)

            recovered = create_runtime(data_dir=data_dir, clock=clock, adapters=ADAPTERS)
            try:
                for adapter in ADAPTERS:
                    user = f"routine-content-{adapter}"
                    replay = await recovered.adapters.dispatch(
                        adapter,
                        _context(adapter, user, checkin_operations[adapter]),
                        "道历问安",
                    )
                    assert replay.ok
                    assert replay.data["idempotent_replay"] is True
                    assert replay.data["reward"] == {"energy": 3, "spirit_stones": 20}

                makeup_replay = await recovered.adapters.dispatch(
                    "qq.official",
                    _context("qq.official", makeup_user, "makeup-old"),
                    "补录道历 2026-09-21",
                )
                assert makeup_replay.data["idempotent_replay"] is True
                assert makeup_replay.data["reward"] == {"energy": 2, "spirit_stones": 16}

                new_user = "routine-content-makeup-onebot"
                await _enter_mortal(recovered, "onebot.v11", new_user)
                _set_resources(recovered.settings.database_path, "onebot.v11", new_user, stones=100, energy=0)
                new_makeup = await recovered.adapters.dispatch(
                    "onebot.v11",
                    _context("onebot.v11", new_user, "makeup-new"),
                    "补录道历 2026-09-21",
                )
                assert new_makeup.ok
                assert new_makeup.data["reward"] == {"energy": 5, "spirit_stones": 29}

                clock.advance(days=1)
                new_checkin = await recovered.adapters.dispatch(
                    "qq.official",
                    _context("qq.official", "routine-content-qq.official", "checkin-new"),
                    "道历问安",
                )
                assert new_checkin.ok
                assert new_checkin.data["reward"] == {"energy": 6, "spirit_stones": 41}
            finally:
                await recovered.close()

    asyncio.run(run())


def test_routine_reward_content_failure_is_atomic_and_retryable() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
        with TemporaryDirectory() as temp:
            data_dir = Path(temp) / "data"
            source = Path(__file__).parents[1] / "data"
            shutil.copytree(source, data_dir)
            _set_reward_quantity(data_dir, "reward.routine.checkin.daily", 0, -1)
            runtime = create_runtime(data_dir=data_dir, clock=clock, adapters=("qq.official",))
            user = "routine-content-invalid"
            try:
                await _enter_mortal(runtime, "qq.official", user)
                _set_resources(runtime.settings.database_path, "qq.official", user, stones=0, energy=0)
                failed = await runtime.adapters.dispatch(
                    "qq.official",
                    _context("qq.official", user, "invalid-checkin"),
                    "道历问安",
                )
                assert failed.code == "PERSISTENCE_ERROR"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    player = connection.execute(
                        "SELECT id, spirit_stones, energy FROM players WHERE platform=? AND platform_user_id=?",
                        ("qq.official", user),
                    ).fetchone()
                    assert player[1:] == (0, 0)
                    assert connection.execute(
                        "SELECT COUNT(*) FROM routine_checkins WHERE player_id=?", (player[0],)
                    ).fetchone()[0] == 0
                    assert connection.execute(
                        "SELECT COUNT(*) FROM operations WHERE operation_id='invalid-checkin'"
                    ).fetchone()[0] == 0

            finally:
                await runtime.close()

            _set_reward_quantity(data_dir, "reward.routine.checkin.daily", 0, 20)
            retry_runtime = create_runtime(data_dir=data_dir, clock=clock, adapters=("qq.official",))
            try:
                retried = await retry_runtime.adapters.dispatch(
                    "qq.official",
                    _context("qq.official", user, "invalid-checkin"),
                    "道历问安",
                )
                assert retried.ok
                assert retried.data["reward"] == {"energy": 3, "spirit_stones": 20}
            finally:
                await retry_runtime.close()

            _set_reward_status(data_dir, "reward.routine.makeup.daily", "closed")
            closed_runtime = create_runtime(data_dir=data_dir, clock=clock, adapters=("onebot.v11",))
            closed_user = "routine-content-closed"
            try:
                await _enter_mortal(closed_runtime, "onebot.v11", closed_user)
                _set_resources(closed_runtime.settings.database_path, "onebot.v11", closed_user, stones=100, energy=0)
                closed = await closed_runtime.adapters.dispatch(
                    "onebot.v11",
                    _context("onebot.v11", closed_user, "closed-makeup"),
                    "补录道历 2026-09-21",
                )
                assert closed.code == "PERSISTENCE_ERROR"
                with sqlite3.connect(closed_runtime.settings.database_path) as connection:
                    player = connection.execute(
                        "SELECT id, spirit_stones, energy FROM players WHERE platform=? AND platform_user_id=?",
                        ("onebot.v11", closed_user),
                    ).fetchone()
                    assert player[1:] == (100, 0)
                    assert connection.execute(
                        "SELECT COUNT(*) FROM routine_checkins WHERE player_id=?", (player[0],)
                    ).fetchone()[0] == 0
            finally:
                await closed_runtime.close()

    asyncio.run(run())


def test_routine_operation_failure_rolls_back_and_retries() -> None:
    async def run() -> None:
        with TemporaryDirectory() as temp:
            data_dir = Path(temp) / "data"
            source = Path(__file__).parents[1] / "data"
            shutil.copytree(source, data_dir)
            clock = MutableClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
            runtime = create_runtime(data_dir=data_dir, clock=clock, adapters=("qq.official",))
            user = "routine-content-operation-failure"
            try:
                await _enter_mortal(runtime, "qq.official", user)
                _set_resources(runtime.settings.database_path, "qq.official", user, stones=0, energy=0)
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        """
                        CREATE TRIGGER routine_checkin_operation_failure
                        BEFORE INSERT ON operations
                        WHEN NEW.operation_id = 'checkin-failure'
                        BEGIN SELECT RAISE(ABORT, 'injected checkin operation failure'); END
                        """
                    )
                failed = await runtime.adapters.dispatch(
                    "qq.official",
                    _context("qq.official", user, "checkin-failure"),
                    "道历问安",
                )
                assert failed.code == "PERSISTENCE_ERROR"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    player = connection.execute(
                        "SELECT id, spirit_stones, energy FROM players WHERE platform=? AND platform_user_id=?",
                        ("qq.official", user),
                    ).fetchone()
                    assert player[1:] == (0, 0)
                    assert connection.execute(
                        "SELECT COUNT(*) FROM routine_checkins WHERE player_id=?", (player[0],)
                    ).fetchone()[0] == 0
                    connection.execute("DROP TRIGGER routine_checkin_operation_failure")

                retried = await runtime.adapters.dispatch(
                    "qq.official",
                    _context("qq.official", user, "checkin-failure"),
                    "道历问安",
                )
                assert retried.ok
                assert retried.data["reward"] == {"energy": 3, "spirit_stones": 20}

                makeup_user = "routine-content-makeup-failure"
                await _enter_mortal(runtime, "qq.official", makeup_user)
                _set_resources(runtime.settings.database_path, "qq.official", makeup_user, stones=100, energy=0)
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        """
                        CREATE TRIGGER routine_makeup_operation_failure
                        BEFORE INSERT ON operations
                        WHEN NEW.operation_id = 'makeup-failure'
                        BEGIN SELECT RAISE(ABORT, 'injected makeup operation failure'); END
                        """
                    )
                makeup_failed = await runtime.adapters.dispatch(
                    "qq.official",
                    _context("qq.official", makeup_user, "makeup-failure"),
                    "补录道历 2026-09-21",
                )
                assert makeup_failed.code == "PERSISTENCE_ERROR"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    player = connection.execute(
                        "SELECT id, spirit_stones, energy FROM players WHERE platform=? AND platform_user_id=?",
                        ("qq.official", makeup_user),
                    ).fetchone()
                    assert player[1:] == (100, 0)
                    assert connection.execute(
                        "SELECT COUNT(*) FROM routine_checkins WHERE player_id=?", (player[0],)
                    ).fetchone()[0] == 0
                    connection.execute("DROP TRIGGER routine_makeup_operation_failure")

                makeup_retried = await runtime.adapters.dispatch(
                    "qq.official",
                    _context("qq.official", makeup_user, "makeup-failure"),
                    "补录道历 2026-09-21",
                )
                assert makeup_retried.ok
                assert makeup_retried.data["reward"] == {"energy": 2, "spirit_stones": 16}
            finally:
                await runtime.close()

    asyncio.run(run())


def test_routine_seven_day_bonus_follows_content() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
        with TemporaryDirectory() as temp:
            data_dir = Path(temp) / "data"
            shutil.copytree(Path(__file__).parents[1] / "data", data_dir)
            _set_reward_quantity(data_dir, "reward.routine.checkin.streak", 0, 2)
            runtime = create_runtime(data_dir=data_dir, clock=clock, adapters=("onebot.v11",))
            user = "routine-content-streak"
            try:
                await _enter_mortal(runtime, "onebot.v11", user)
                _set_resources(runtime.settings.database_path, "onebot.v11", user, stones=0, energy=0)
                result = None
                for index in range(7):
                    result = await runtime.adapters.dispatch(
                        "onebot.v11",
                        _context("onebot.v11", user, f"streak-{index}"),
                        "道历问安",
                    )
                    assert result.ok
                    if index < 6:
                        clock.advance(days=1)
                assert result is not None
                assert result.data["reward"] == {
                    "energy": 3,
                    "item.ticket.fate_basic": 2,
                    "spirit_stones": 20,
                }
            finally:
                await runtime.close()

    asyncio.run(run())
