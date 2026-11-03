from __future__ import annotations

import asyncio
import json
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from urllib.parse import unquote

from nonebot_plugin_xiuxian_3.adapters.message.markdown import (
    markdown_to_text,
    send_markdown_message,
)
from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime

SEASON = "season.final_heaven:202610"
ENDS_AT = datetime(2026, 11, 3, 4, 0, tzinfo=timezone.utc)


class MutableClock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **kwargs: int) -> None:
        self.value += timedelta(**kwargs)


class FakeBot:
    def __init__(self) -> None:
        self.sent: list[object] = []

    async def send(self, *, event: object, message: object, **kwargs: object) -> dict[str, str]:
        self.sent.append(message)
        return {"message_id": "reply-1"}


def _context(user: str) -> CommandContext:
    return CommandContext(adapter="onebot.v11", user_id=user)


async def _send(runtime, user: str, text: str):
    return await runtime.adapters.dispatch("onebot.v11", _context(user), text)


async def _create_player(runtime, user: str) -> int:
    assert (await _send(runtime, user, "开始修仙")).ok
    assert (await _send(runtime, user, "寻仙问道")).ok
    with sqlite3.connect(runtime.settings.database_path) as connection:
        return int(
            connection.execute(
                "SELECT id FROM players WHERE platform='onebot.v11' AND platform_user_id=?", (user,)
            ).fetchone()[0]
        )


def _freeze_season(runtime, *, status: str = "frozen") -> None:
    snapshot = json.dumps(
        {
            "boards": {
                "ascension": [
                    {
                        "rank": 1,
                        "anonymous_label": "无名甲",
                        "score": 1000,
                        "achieved_at": "2026-11-01T00:00:00+00:00",
                    }
                ],
                "dao": [
                    {
                        "rank": 1,
                        "anonymous_label": "无名乙",
                        "score": 800,
                        "achieved_at": "2026-11-01T00:00:00+00:00",
                    }
                ],
                "cooperation": [],
            },
            "frozen_at": "2026-11-03T04:00:00+00:00",
        },
        ensure_ascii=False,
    )
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "INSERT INTO final_heaven_seasons(season_id, starts_at, ends_at, claim_expires_at, "
            "status, snapshot_json, frozen_at, created_at, updated_at) "
            "VALUES (?, '2026-09-28T00:00:00+00:00', ?, '2026-11-10T04:00:00+00:00', ?, ?, "
            "'2026-11-03T04:00:00+00:00', '2026-11-03T04:00:00+00:00', '2026-11-03T04:00:00+00:00')",
            (SEASON, ENDS_AT.isoformat(), status, snapshot if status == "frozen" else "{}"),
        )


def _record_ending(runtime, player_id: int, ending: str = "remain_in_world") -> None:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "INSERT INTO endgame_endings(player_id, ending_key, status, snapshot_json, "
            "operation_id, created_at) VALUES (?, ?, 'remained_in_world', '{}', ?, ?)",
            (player_id, ending, f"ending:{player_id}", "2026-11-01T00:00:00+00:00"),
        )


def _snapshot_state(runtime) -> tuple:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        assets = connection.execute(
            "SELECT id, spirit_stones, world_merit, ascension_merit, tribulation_debt "
            "FROM players ORDER BY id"
        ).fetchall()
        endings = connection.execute(
            "SELECT player_id, ending_key, status FROM endgame_endings ORDER BY player_id"
        ).fetchall()
        rankings = connection.execute(
            "SELECT season_id, board_key, rank, score FROM final_heaven_rankings "
            "ORDER BY board_key, rank"
        ).fetchall()
        operations = connection.execute("SELECT COUNT(*) FROM operations").fetchone()[0]
    return assets, endings, rankings, operations


def test_no_frozen_season_reports_a_missing_season() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 11, 3, 5, 0, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            try:
                await _create_player(runtime, "early")
                result = await _send(runtime, "early", "飞升日")
                assert result.ok and result.code == "ASCENSION_DAY_NO_SEASON"
                assert result.data["state"] == "pending"
                assert result.data["season_id"] == ""
                # The new-chapter entries are still listed so the page is never empty.
                assert result.data["chapters"] == [
                    "lane.builder.chapter.01",
                    "lane.witness.chapter.01",
                    "lane.traveler.chapter.01",
                ]

                # A collecting season is not a closed one.
                _freeze_season(runtime, status="collecting")
                collecting = await _send(runtime, "early", "飞升日")
                assert collecting.code == "ASCENSION_DAY_NO_SEASON"
            finally:
                await runtime.close()

    asyncio.run(run())


def test_window_opens_pending_then_closes_and_never_writes() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 11, 3, 3, 0, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            try:
                player_id = await _create_player(runtime, "watcher")
                _record_ending(runtime, player_id)
                _freeze_season(runtime)

                before = _snapshot_state(runtime)

                pending = await _send(runtime, "watcher", "飞升日")
                assert pending.ok and pending.code == "ASCENSION_DAY_PENDING"
                assert pending.data["state"] == "pending"
                assert pending.data["boards"] == []

                clock.value = ENDS_AT
                opened = await _send(runtime, "watcher", "飞升日")
                assert opened.ok and opened.code == "ASCENSION_DAY_OPEN"
                assert opened.data["season_id"] == SEASON
                assert opened.data["ending_key"] == "remain_in_world"
                boards = {board["board_key"]: board["rows"] for board in opened.data["boards"]}
                assert boards["ascension"] == [
                    {"rank": 1, "label": "无名甲", "score": 1000}
                ]
                assert boards["dao"] == [{"rank": 1, "label": "无名乙", "score": 800}]
                assert boards["cooperation"] == []

                clock.value = ENDS_AT + timedelta(hours=23, minutes=59)
                still_open = await _send(runtime, "watcher", "飞升日")
                assert still_open.code == "ASCENSION_DAY_OPEN"

                clock.value = ENDS_AT + timedelta(hours=24)
                closed = await _send(runtime, "watcher", "飞升日")
                assert closed.code == "ASCENSION_DAY_CLOSED"
                assert closed.data["boards"] == []

                # Display only: no asset, ending, ranking or operation changed.
                assert _snapshot_state(runtime) == before
            finally:
                await runtime.close()

    asyncio.run(run())


def test_state_is_stable_across_restart() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 11, 3, 5, 0, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            try:
                await _create_player(runtime, "restart")
                _freeze_season(runtime)
                first = await _send(runtime, "restart", "飞升日")
                assert first.code == "ASCENSION_DAY_OPEN"
            finally:
                await runtime.close()

            reopened = create_runtime(data_dir=data_dir, clock=clock)
            try:
                again = await _send(reopened, "restart", "飞升日")
                assert again.code == "ASCENSION_DAY_OPEN"
                assert again.data == first.data
            finally:
                await reopened.close()

    asyncio.run(run())


def test_command_rejects_arguments_and_unknown_players() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 11, 3, 5, 0, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            try:
                unknown = await _send(runtime, "ghost", "飞升日")
                assert not unknown.ok and unknown.code == "PLAYER_NOT_FOUND"

                await _create_player(runtime, "strict")
                extra = await _send(runtime, "strict", "飞升日 多余")
                assert not extra.ok and extra.code == "INVALID_ASCENSION_DAY_COMMAND"
            finally:
                await runtime.close()

    asyncio.run(run())


def test_rendering_uses_blue_links_without_exposing_stable_keys() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 11, 3, 5, 0, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            try:
                await _create_player(runtime, "render")
                _freeze_season(runtime)
                page = await _send(runtime, "render", "飞升日")
                assert page.ok and page.code == "ASCENSION_DAY_OPEN"
                # A display page never carries a write button.
                assert page.actions == ()
                links = [
                    unquote(match.group(1))
                    for match in re.finditer(r"command:([^)]+)", page.message)
                ]
                assert links and all(link == "主线道途" for link in links)
                text = markdown_to_text(page.message)
                assert "command:" not in text
                assert "lane.builder.chapter" not in page.message
                assert "ascension" not in page.message

                bot = FakeBot()
                fallback = await send_markdown_message(
                    bot,
                    SimpleNamespace(),
                    page.message,
                    capabilities=("text",),
                    actions=page.actions,
                )
                assert fallback.sent_format == "text" and fallback.degraded is True
                assert "command:" not in str(bot.sent[0])

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
                assert native.sent_format == "markdown", native
                assert "keyboard" not in str(qq_bot.sent[0])

                help_page = await _send(runtime, "render", "修仙帮助 探索")
                assert help_page.code == "HELP_CATEGORY"
                assert "飞升日" in help_page.message
                assert not help_page.actions
            finally:
                await runtime.close()

    asyncio.run(run())