from __future__ import annotations

import asyncio
import json
import re
import sqlite3
from datetime import datetime, timezone
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from urllib.parse import unquote

from nonebot_plugin_xiuxian_3.adapters.message.markdown import (
    markdown_to_text,
    send_markdown_message,
)
from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime


class FakeBot:
    def __init__(self) -> None:
        self.sent: list[object] = []

    async def send(self, *, event: object, message: object, **kwargs: object) -> dict[str, str]:
        self.sent.append(message)
        return {"message_id": "reply-1"}


def _context(user: str, operation: str = "") -> CommandContext:
    return CommandContext(adapter="onebot.v11", user_id=user, operation_id=operation)


async def _send(runtime, user: str, text: str, operation: str = ""):
    return await runtime.adapters.dispatch("onebot.v11", _context(user, operation), text)


async def _create_players(runtime, *users: str) -> dict[str, int]:
    ids: dict[str, int] = {}
    for user in users:
        assert (await _send(runtime, user, "开始修仙")).ok
        assert (await _send(runtime, user, "寻仙问道")).ok
    with sqlite3.connect(runtime.settings.database_path) as connection:
        for user in users:
            ids[user] = int(
                connection.execute(
                    "SELECT id FROM players WHERE platform='onebot.v11' AND platform_user_id=?",
                    (user,),
                ).fetchone()[0]
            )
    return ids


def _pair(runtime, ids: dict[str, int], *, left: str = "a", right: str = "b") -> None:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "INSERT INTO partner_relations(relation_id, player_a_id, player_b_id, pair_key, "
            "initiator_id, invitee_id, status, invited_at, invitation_expires_at, accepted_at, "
            "created_at, updated_at) VALUES ('rel-1', ?, ?, ?, ?, ?, 'active', "
            "'2026-11-01T00:00:00+00:00', '2026-11-05T00:00:00+00:00', "
            "'2026-11-01T00:00:00+00:00', '2026-11-01T00:00:00+00:00', "
            "'2026-11-01T00:00:00+00:00')",
            (ids[left], ids[right], f"{left}:{right}", ids[left], ids[right]),
        )


def _assist_win(runtime, ids: dict[str, int], *, helper: str, index: int = 1) -> None:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "INSERT INTO final_battle_sessions(battle_id, initiator_id, create_operation_id, "
            "status, starts_at, expires_at, snapshot_json, created_at, updated_at) "
            "VALUES (?, ?, ?, 'won', '2026-11-03T05:00:00+00:00', '2026-11-03T06:00:00+00:00', "
            "'{}', '2026-11-03T05:00:00+00:00', '2026-11-03T05:00:00+00:00')",
            (f"fb-{index}", ids["a"], f"fb-create-{index}"),
        )
        connection.execute(
            "INSERT INTO final_battle_members(battle_id, player_id, role, asset_lock_status, "
            "snapshot_json, created_at, updated_at) VALUES (?, ?, 'helper', 'released', '{}', "
            "'2026-11-03T05:00:00+00:00', '2026-11-03T05:00:00+00:00')",
            (f"fb-{index}", ids[helper]),
        )


def _player_state(runtime, player_id: int) -> tuple:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        return connection.execute(
            "SELECT world_merit, inventory_json, ascension_merit, tribulation_debt, "
            "dao_fruit_progress FROM players WHERE id = ?",
            (player_id,),
        ).fetchone()


def _endings(runtime) -> list:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        return connection.execute(
            "SELECT player_id, ending_key, status FROM endgame_endings ORDER BY player_id"
        ).fetchall()


def test_without_a_partner_nothing_can_start() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(
                data_dir=data_dir, clock=lambda: datetime(2026, 11, 3, 5, 0, tzinfo=timezone.utc)
            )
            try:
                await _create_players(runtime, "solo")
                status = await _send(runtime, "solo", "道侣协作")
                assert status.ok and status.code == "PARTNER_TASK_STATUS"
                assert status.data["has_partner"] is False
                assert status.actions == ()

                started = await _send(runtime, "solo", "开始道侣协作", "s-1")
                assert not started.ok and started.code == "PARTNER_TASK_NO_PARTNER"
                claimed = await _send(runtime, "solo", "领取道侣协作", "c-1")
                assert not claimed.ok and claimed.code == "PARTNER_TASK_NO_PARTNER"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    assert connection.execute("SELECT COUNT(*) FROM partner_tasks").fetchone()[0] == 0
            finally:
                await runtime.close()

    asyncio.run(run())


def test_task_start_progress_and_per_player_rewards() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(
                data_dir=data_dir, clock=lambda: datetime(2026, 11, 3, 5, 0, tzinfo=timezone.utc)
            )
            try:
                ids = await _create_players(runtime, "a", "b")
                _pair(runtime, ids)
                before = {name: _player_state(runtime, pid) for name, pid in ids.items()}
                endings_before = _endings(runtime)

                started = await _send(runtime, "a", "开始道侣协作", "s-1")
                assert started.ok and started.code == "PARTNER_TASK_START"
                assert started.data["target_amount"] == 1

                active = await _send(runtime, "b", "开始道侣协作", "s-2")
                assert not active.ok and active.code == "PARTNER_TASK_ACTIVE"

                early_claim = await _send(runtime, "a", "领取道侣协作", "c-1")
                assert not early_claim.ok and early_claim.code == "PARTNER_TASK_NOT_COMPLETE"

                _assist_win(runtime, ids, helper="b")
                progress = await _send(runtime, "a", "道侣协作")
                assert progress.data["progress"] == 1
                assert progress.data["complete"] is True
                assert [action.label for action in progress.actions] == ["领取道侣协作"]

                first = await _send(runtime, "a", "领取道侣协作", "c-2")
                assert first.ok and first.code == "PARTNER_TASK_CLAIM"
                assert first.data["reward"] == {"item.spirit_water": 1, "world_merit": 20}
                duplicate = await _send(runtime, "a", "领取道侣协作", "c-3")
                assert not duplicate.ok and duplicate.code == "PARTNER_TASK_CLAIMED"

                second = await _send(runtime, "b", "领取道侣协作", "c-4")
                assert second.ok and second.code == "PARTNER_TASK_CLAIM"

                # Each side gains exactly its own reward, and endings stay untouched.
                for name, player_id in ids.items():
                    after = _player_state(runtime, player_id)
                    assert after[0] == before[name][0] + 20
                    inventory = json.loads(after[1])
                    assert inventory.get("item.spirit_water", 0) == json.loads(before[name][1]).get(
                        "item.spirit_water", 0
                    ) + 1
                    assert after[2:] == before[name][2:]
                assert _endings(runtime) == endings_before
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    assert connection.execute(
                        "SELECT status FROM partner_tasks"
                    ).fetchone()[0] == "completed"
                    assert connection.execute(
                        "SELECT COUNT(*) FROM partner_task_claims"
                    ).fetchone()[0] == 2
            finally:
                await runtime.close()

    asyncio.run(run())


def test_a_recorded_ending_blocks_further_cooperation() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(
                data_dir=data_dir, clock=lambda: datetime(2026, 11, 3, 5, 0, tzinfo=timezone.utc)
            )
            try:
                ids = await _create_players(runtime, "a", "b")
                _pair(runtime, ids)
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "INSERT INTO endgame_endings(player_id, ending_key, status, snapshot_json, "
                        "operation_id, created_at) VALUES (?, 'remain_in_world', "
                        "'remained_in_world', '{}', 'e-1', '2026-11-03T05:00:00+00:00')",
                        (ids["a"],),
                    )
                status = await _send(runtime, "b", "道侣协作")
                assert status.ok and status.data["partner_locked"] is True
                assert status.actions == ()

                blocked = await _send(runtime, "b", "开始道侣协作", "s-1")
                assert not blocked.ok and blocked.code == "ENDGAME_PARTNER_STATE_CONFLICT"
                claimed = await _send(runtime, "b", "领取道侣协作", "c-1")
                assert not claimed.ok and claimed.code == "ENDGAME_PARTNER_STATE_CONFLICT"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    assert connection.execute("SELECT COUNT(*) FROM partner_tasks").fetchone()[0] == 0
            finally:
                await runtime.close()

    asyncio.run(run())


def test_replay_and_restart_keep_one_task_and_one_reward() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            clock = lambda: datetime(2026, 11, 3, 5, 0, tzinfo=timezone.utc)
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            try:
                ids = await _create_players(runtime, "a", "b")
                _pair(runtime, ids)
                first = await _send(runtime, "a", "开始道侣协作", "s-1")
                assert first.ok
                replay = await _send(runtime, "a", "开始道侣协作", "s-1")
                assert replay.ok and replay.data["already_completed"] is True
                assert replay.data["task_id"] == first.data["task_id"]
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    assert connection.execute("SELECT COUNT(*) FROM partner_tasks").fetchone()[0] == 1

                _assist_win(runtime, ids, helper="a")
                claim = await _send(runtime, "a", "领取道侣协作", "c-1")
                assert claim.ok
                claim_replay = await _send(runtime, "a", "领取道侣协作", "c-1")
                assert claim_replay.ok and claim_replay.data["already_completed"] is True
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    assert connection.execute(
                        "SELECT COUNT(*) FROM partner_task_claims"
                    ).fetchone()[0] == 1
            finally:
                await runtime.close()

            reopened = create_runtime(data_dir=data_dir, clock=clock)
            try:
                status = await _send(reopened, "a", "道侣协作")
                assert status.ok
                assert status.data["task_status"] == "open"
                assert status.data["claimed"] is True
            finally:
                await reopened.close()

    asyncio.run(run())


def test_rendering_and_help() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(
                data_dir=data_dir, clock=lambda: datetime(2026, 11, 3, 5, 0, tzinfo=timezone.utc)
            )
            try:
                ids = await _create_players(runtime, "a", "b")
                _pair(runtime, ids)
                page = await _send(runtime, "a", "道侣协作")
                assert page.ok
                assert [action.label for action in page.actions] == ["开始道侣协作"]
                links = [
                    unquote(match.group(1))
                    for match in re.finditer(r"command:([^)]+)", page.message)
                ]
                assert "开始道侣协作" in links
                text = markdown_to_text(page.message)
                assert "command:" not in text
                assert "task.partner" not in page.message

                bot = FakeBot()
                fallback = await send_markdown_message(
                    bot,
                    SimpleNamespace(),
                    page.message,
                    capabilities=("text",),
                    actions=page.actions,
                )
                assert fallback.sent_format == "text" and fallback.degraded is True
                assert str(bot.sent[0]).endswith("可发送：开始道侣协作")

                class FakeQQBot(FakeBot):
                    __module__ = "nonebot.adapters.qq.bot"

                class FakeQQEvent:
                    __module__ = "nonebot.adapters.qq.event"

                qq_bot = FakeQQBot()
                native = await send_markdown_message(
                    qq_bot,
                    FakeQQEvent(),
                    page.message,
                    capabilities=("markdown", "keyboard"),
                    actions=page.actions,
                )
                assert native.sent_format == "markdown+keyboard", native
                assert "keyboard" in str(qq_bot.sent[0])

                help_page = await _send(runtime, "a", "修仙帮助 社交")
                assert help_page.code == "HELP_CATEGORY"
                assert "道侣" in help_page.message
                assert not help_page.actions
            finally:
                await runtime.close()

    asyncio.run(run())