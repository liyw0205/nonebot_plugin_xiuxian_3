from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timezone
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.persistence.errors import (
    AchievementNotCompletedError,
    HonorTitleClosedError,
)
from nonebot_plugin_xiuxian_3.xiuxian.routine.achievement_content import achievement_definitions

ACHIEVEMENT = "achievement.dao_service"
TITLE = "title.dao_service"


def _context(user: str, operation: str = "") -> CommandContext:
    return CommandContext(adapter="onebot.v11", user_id=user, operation_id=operation)


def _write(connection, player_id: int, *, outcome: str, dispatch_key: str, index: int) -> None:
    connection.execute(
        "INSERT INTO activity_events(player_id, event_key, source_operation_id, occurred_at, payload_json) "
        "VALUES (?, 'specials.dispatch.settled', ?, ?, ?)",
        (
            player_id,
            f"op-{index}",
            f"2026-11-03T05:00:{index:02d}+00:00",
            json.dumps(
                {"assignment_id": f"a-{index}", "dispatch_key": dispatch_key, "outcome": outcome},
                ensure_ascii=False,
                sort_keys=True,
            ),
        ),
    )


def test_content_declares_a_counted_tenout() -> None:
    definitions = {row.key: row for row in achievement_definitions()}
    definition = definitions[ACHIEVEMENT]
    assert definition.required_count == 10
    assert definition.count_event_key == "dispatch.dao_service"
    assert dict(definition.reward) == {"title_key": TITLE}
    assert definition.source_event == "specials.dispatch.settled"
    # Every other shipped achievement stays single-event.
    assert all(
        row.required_count == 1 and row.count_event_key is None
        for key, row in definitions.items()
        if key != ACHIEVEMENT
    )


def test_claim_needs_ten_successful_dao_dispatches() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(
                data_dir=data_dir, clock=lambda: datetime(2026, 11, 3, 5, 0, tzinfo=timezone.utc)
            )
            try:
                assert (
                    await runtime.adapters.dispatch(
                        "onebot.v11", _context("a"), "开始修仙"
                    )
                ).ok
                assert (
                    await runtime.adapters.dispatch(
                        "onebot.v11", _context("a"), "寻仙问道"
                    )
                ).ok
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    player_id = int(
                        connection.execute(
                            "SELECT id FROM players WHERE platform_user_id='a'"
                        ).fetchone()[0]
                    )
                    # Nine successes, plus noise that must not count: another
                    # dispatch key and a failed dao dispatch.
                    for index in range(1, 10):
                        _write(
                            connection,
                            player_id,
                            outcome="success",
                            dispatch_key="dispatch.dao_service",
                            index=index,
                        )
                    _write(
                        connection,
                        player_id,
                        outcome="success",
                        dispatch_key="dispatch.escort",
                        index=10,
                    )
                    _write(
                        connection,
                        player_id,
                        outcome="failure",
                        dispatch_key="dispatch.dao_service",
                        index=11,
                    )

                try:
                    await runtime.repository.claim_achievement(
                        platform="onebot.v11",
                        platform_user_id="a",
                        achievement_key=ACHIEVEMENT,
                        operation_id="cl-early",
                    )
                except AchievementNotCompletedError:
                    pass
                else:  # pragma: no cover - nine must not be enough
                    raise AssertionError("nine services must not complete the achievement")

                with sqlite3.connect(runtime.settings.database_path) as connection:
                    _write(
                        connection,
                        player_id,
                        outcome="success",
                        dispatch_key="dispatch.dao_service",
                        index=12,
                    )

                claimed = await runtime.repository.claim_achievement(
                    platform="onebot.v11",
                    platform_user_id="a",
                    achievement_key=ACHIEVEMENT,
                    operation_id="cl-1",
                )
                assert claimed.already_completed is False
                assert claimed.reward.get("title_key") == TITLE

                replay = await runtime.repository.claim_achievement(
                    platform="onebot.v11",
                    platform_user_id="a",
                    achievement_key=ACHIEVEMENT,
                    operation_id="cl-1",
                )
                assert replay.already_completed is True
            finally:
                await runtime.close()

    asyncio.run(run())


def test_failed_dao_dispatches_never_stack_up() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(
                data_dir=data_dir, clock=lambda: datetime(2026, 11, 3, 5, 0, tzinfo=timezone.utc)
            )
            try:
                await runtime.adapters.dispatch("onebot.v11", _context("b"), "开始修仙")
                await runtime.adapters.dispatch("onebot.v11", _context("b"), "寻仙问道")
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    player_id = int(
                        connection.execute(
                            "SELECT id FROM players WHERE platform_user_id='b'"
                        ).fetchone()[0]
                    )
                    for index in range(1, 16):
                        _write(
                            connection,
                            player_id,
                            outcome="failure",
                            dispatch_key="dispatch.dao_service",
                            index=index,
                        )
                try:
                    await runtime.repository.claim_achievement(
                        platform="onebot.v11",
                        platform_user_id="b",
                        achievement_key=ACHIEVEMENT,
                        operation_id="cl-b",
                    )
                except AchievementNotCompletedError:
                    pass
                else:  # pragma: no cover
                    raise AssertionError("failed dispatches must not complete the achievement")
            finally:
                await runtime.close()

    asyncio.run(run())