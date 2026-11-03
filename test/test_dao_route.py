from __future__ import annotations

import asyncio
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

GUARD = "route.dao_settlement.guard_world"
ASCEND = "route.dao_settlement.ascend"
REMAIN = "route.dao_settlement.remain"
SECT = "sect.council"


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


def _context(user: str, operation: str = "") -> CommandContext:
    return CommandContext(adapter="onebot.v11", user_id=user, operation_id=operation)


async def _send(runtime, user: str, text: str, operation: str = ""):
    return await runtime.adapters.dispatch("onebot.v11", _context(user, operation), text)


async def _create_player(
    runtime, user: str, *, realm: str = "dao_union", layer: int = 1, sect: bool = True
) -> int:
    assert (await _send(runtime, user, "开始修仙")).ok
    assert (await _send(runtime, user, "寻仙问道")).ok
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE players SET stage='cultivator', realm_key=?, realm_layer=? "
            "WHERE platform='onebot.v11' AND platform_user_id=?",
            (realm, layer, user),
        )
        player_id = int(
            connection.execute(
                "SELECT id FROM players WHERE platform='onebot.v11' AND platform_user_id=?", (user,)
            ).fetchone()[0]
        )
    if sect:
        _join_sect(runtime, player_id)
    return player_id


def _join_sect(
    runtime, player_id: int, *, level: int = 6, merit: int = 5000, sect_id: str = SECT
) -> None:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        row = connection.execute(
            "SELECT sect_id FROM sects WHERE sect_id = ?", (sect_id,)
        ).fetchone()
        if row is None:
            connection.execute(
                "INSERT INTO sects(sect_id, name, name_key, leader_id, status, level, "
                "max_members, warehouse_capacity, spirit_stones, sect_merit, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, 'active', ?, 50, 10, 0, ?, ?, ?)",
                (
                    sect_id,
                    f"道统测试宗{sect_id}",
                    f"道统测试宗{sect_id}",
                    player_id,
                    level,
                    merit,
                    "2026-11-01T00:00:00+00:00",
                    "2026-11-01T00:00:00+00:00",
                ),
            )
        connection.execute(
            "INSERT INTO sect_members(sect_id, player_id, role, status, joined_at, "
            "last_action_at, created_at, updated_at) "
            "VALUES (?, ?, 'member', 'active', ?, ?, ?, ?)",
            (
                sect_id,
                player_id,
                "2026-11-01T00:00:00+00:00",
                "2026-11-01T00:00:00+00:00",
                "2026-11-01T00:00:00+00:00",
                "2026-11-01T00:00:00+00:00",
            ),
        )


def _sect_row(runtime):
    with sqlite3.connect(runtime.settings.database_path) as connection:
        return connection.execute(
            "SELECT sect_merit, level FROM sects WHERE sect_id = ?", (SECT,)
        ).fetchone()


def _route_state(runtime):
    with sqlite3.connect(runtime.settings.database_path) as connection:
        return connection.execute(
            "SELECT route_key, locked_until FROM dao_route_state WHERE sect_id = ?", (SECT,)
        ).fetchone()


def _vote_count(runtime) -> int:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        return int(
            connection.execute("SELECT COUNT(*) FROM dao_route_votes").fetchone()[0]
        )


def test_requirements_block_votes_without_writing() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 11, 3, 5, 0, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            try:
                # Not 合道.
                await _create_player(runtime, "low", realm="nascent_soul", layer=9)
                low = await _send(runtime, "low", "道统投票 守界", "v-1")
                assert not low.ok and low.code == "DAO_ROUTE_REQUIREMENT"
                assert _vote_count(runtime) == 0

                # 合道 but no sect.
                await _create_player(runtime, "solo", sect=False)
                solo = await _send(runtime, "solo", "道统投票 守界", "v-2")
                assert not solo.ok and solo.code == "DAO_ROUTE_REQUIREMENT"
                assert _vote_count(runtime) == 0
                solo_status = await _send(runtime, "solo", "道统")
                assert solo_status.ok and solo_status.data["eligible"] is False

                # Sect below level 6.
                await _create_player(runtime, "small", sect=False)
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    player_id = connection.execute(
                        "SELECT id FROM players WHERE platform_user_id='small'"
                    ).fetchone()[0]
                _join_sect(runtime, int(player_id), level=5, sect_id="sect.small")
                small = await _send(runtime, "small", "道统投票 守界", "v-3")
                assert not small.ok and small.code == "DAO_ROUTE_REQUIREMENT"
                assert _vote_count(runtime) == 0
                assert any(
                    "宗门等级" in item
                    for item in (await _send(runtime, "small", "道统")).data["missing"]
                )
            finally:
                await runtime.close()

    asyncio.run(run())


def test_one_vote_per_week_and_majority_settles_once() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 11, 3, 5, 0, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            try:
                for name in ("a", "b", "c"):
                    await _create_player(runtime, name)
                status = await _send(runtime, "a", "道统")
                assert status.ok and status.code == "DAO_ROUTE_STATUS"
                assert status.data["cycle_id"] == "dao_route:2026-W45"
                assert status.data["quorum"] == 3
                assert status.data["voter_count"] == 0

                first = await _send(runtime, "a", "道统投票 守界", "v-a")
                assert first.ok and first.code == "DAO_ROUTE_VOTE"
                assert first.data["route_key"] == GUARD
                assert first.data["voter_count"] == 1

                again = await _send(runtime, "a", "道统投票 飞升", "v-a2")
                assert not again.ok and again.code == "DAO_VOTE_ALREADY_CAST"
                assert _vote_count(runtime) == 1

                assert (await _send(runtime, "b", "道统投票 守界", "v-b")).ok
                assert (await _send(runtime, "c", "道统投票 留界", "v-c")).ok
                assert _vote_count(runtime) == 3

                clock.advance(days=7)
                settled = await _send(runtime, "a", "道统结算", "s-1")
                assert settled.ok and settled.code == "DAO_ROUTE_SETTLE"
                assert settled.data["route_key"] == GUARD
                assert settled.data["voter_count"] == 3
                assert settled.data["sect_merit_spent"] == 1000
                assert settled.data["sect_merit_after"] == 4000
                assert settled.data["tie_carryover"] is False
                assert settled.data["locked_until"] == "2026-11-17T05:00:00+00:00"
                assert _sect_row(runtime) == (4000, 6)
                assert _route_state(runtime)[0] == GUARD

                after = await _send(runtime, "a", "道统")
                assert after.data["route_key"] == GUARD
                assert after.data["locked"] is True
            finally:
                await runtime.close()

    asyncio.run(run())


def test_tie_carries_the_previous_route() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 11, 3, 5, 0, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            try:
                for name in ("a", "b", "c", "d"):
                    await _create_player(runtime, name)
                # Week 45: 守界 wins 3:1.
                for name, route, op in (
                    ("a", "守界", "w1-a"),
                    ("b", "守界", "w1-b"),
                    ("c", "留界", "w1-c"),
                    ("d", "守界", "w1-d"),
                ):
                    assert (await _send(runtime, name, f"道统投票 {route}", op)).ok
                clock.advance(days=7)
                first = await _send(runtime, "a", "道统结算", "s-1")
                assert first.data["route_key"] == GUARD
                merit_after_first = first.data["sect_merit_after"]

                # Week 46: a 2:2 tie, so the previous route carries over.
                clock.advance(days=7)
                for name, route, op in (
                    ("a", "飞升", "w2-a"),
                    ("b", "飞升", "w2-b"),
                    ("c", "留界", "w2-c"),
                    ("d", "留界", "w2-d"),
                ):
                    assert (await _send(runtime, name, f"道统投票 {route}", op)).ok
                clock.advance(days=7)
                second = await _send(runtime, "a", "道统结算", "s-2")
                assert second.ok, second
                assert second.data["route_key"] == GUARD
                assert second.data["tie_carryover"] is True
                assert second.data["sect_merit_spent"] == 1000
                assert second.data["sect_merit_after"] == merit_after_first - 1000
            finally:
                await runtime.close()

    asyncio.run(run())


def test_short_quorum_closes_the_cycle_without_wedging_votes() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 11, 3, 5, 0, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            try:
                await _create_player(runtime, "a")
                await _create_player(runtime, "b")
                assert (await _send(runtime, "a", "道统投票 守界", "v-a")).ok
                assert (await _send(runtime, "b", "道统投票 留界", "v-b")).ok

                # Settling inside the week is rejected as not due yet.
                early = await _send(runtime, "a", "道统结算", "s-early")
                assert not early.ok and early.code == "DAO_ROUTE_NOT_DUE"
                assert _sect_row(runtime)[0] == 5000

                # Two votes are short of quorum: the cycle closes with no route.
                clock.advance(days=7)
                short = await _send(runtime, "a", "道统结算", "s-short")
                assert not short.ok and short.code == "DAO_COUNCIL_QUORUM_MISSING"
                assert short.data["voter_count"] == 2
                assert _sect_row(runtime)[0] == 5000
                assert _route_state(runtime) is None

                # Crucially the closed cycle no longer blocks the new week.
                for name in ("a", "b"):
                    voted = await _send(runtime, name, "道统投票 守界", f"w2-{name}")
                    assert voted.ok, voted
                assert _vote_count(runtime) == 4
            finally:
                await runtime.close()

    asyncio.run(run())


def test_active_lock_rejects_a_locked_settlement() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 11, 3, 5, 0, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            try:
                for name in ("a", "b", "c"):
                    await _create_player(runtime, name)
                for name, op in (("a", "v-a"), ("b", "v-b"), ("c", "v-c")):
                    assert (await _send(runtime, name, "道统投票 守界", op)).ok
                clock.advance(days=7)
                settled = await _send(runtime, "a", "道统结算", "s-1")
                assert settled.ok and settled.data["locked_until"] is not None

                # A second settlement inside the protection window is refused.
                blocked = await _send(runtime, "a", "道统结算", "s-2")
                assert not blocked.ok and blocked.code == "DAO_ROUTE_LOCKED"
            finally:
                await runtime.close()

    asyncio.run(run())


def test_vote_replay_is_idempotent_and_survives_restart() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 11, 3, 5, 0, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            try:
                await _create_player(runtime, "replay")
                first = await _send(runtime, "replay", "道统投票 留界", "v-1")
                assert first.ok

                replay = await _send(runtime, "replay", "道统投票 留界", "v-1")
                assert replay.ok and replay.data["already_completed"] is True
                assert replay.data["voter_count"] == first.data["voter_count"]
                assert _vote_count(runtime) == 1

                conflict = await _send(runtime, "replay", "道统投票 飞升", "v-1")
                assert not conflict.ok
                assert conflict.code in {"LEDGER_CONFLICT", "DAO_VOTE_ALREADY_CAST"}
            finally:
                await runtime.close()

            reopened = create_runtime(data_dir=data_dir, clock=clock)
            try:
                status = await _send(reopened, "replay", "道统")
                assert status.ok
                assert status.data["my_vote_key"] == REMAIN
                assert status.data["voter_count"] == 1
            finally:
                await reopened.close()

    asyncio.run(run())


def test_route_never_touches_endgame_state() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 11, 3, 5, 0, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            try:
                for name in ("a", "b", "c"):
                    await _create_player(runtime, name)
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    before = connection.execute(
                        "SELECT ascension_merit, tribulation_debt, dao_fruit_progress "
                        "FROM players ORDER BY id"
                    ).fetchall()
                for name, op in (("a", "v-a"), ("b", "v-b"), ("c", "v-c")):
                    assert (await _send(runtime, name, "道统投票 守界", op)).ok
                clock.advance(days=7)
                assert (await _send(runtime, "a", "道统结算", "s-1")).ok
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    after = connection.execute(
                        "SELECT ascension_merit, tribulation_debt, dao_fruit_progress "
                        "FROM players ORDER BY id"
                    ).fetchall()
                assert after == before
            finally:
                await runtime.close()

    asyncio.run(run())


def test_rendering_keeps_blue_links_one_action_and_onebot_fallback() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 11, 3, 5, 0, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            try:
                await _create_player(runtime, "render")
                page = await _send(runtime, "render", "道统")
                assert page.ok and page.code == "DAO_ROUTE_STATUS"
                assert [action.label for action in page.actions] == ["投票 守界"]

                links = [
                    unquote(match.group(1))
                    for match in re.finditer(r"command:([^)]+)", page.message)
                ]
                assert "道统投票 守界" in links
                text = markdown_to_text(page.message)
                assert "command:" not in text
                assert "route.dao_settlement" not in page.message

                bot = FakeBot()
                fallback = await send_markdown_message(
                    bot,
                    SimpleNamespace(),
                    page.message,
                    capabilities=("text",),
                    actions=page.actions,
                )
                assert fallback.sent_format == "text" and fallback.degraded is True
                assert str(bot.sent[0]).endswith("可发送：道统投票 守界")
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
                assert native.sent_format == "markdown+keyboard", native
                assert "keyboard" in str(qq_bot.sent[0])
                assert "route.dao_settlement" not in str(qq_bot.sent[0])

                help_page = await _send(runtime, "render", "修仙帮助 社交")
                assert help_page.code == "HELP_CATEGORY"
                assert "道统" in help_page.message
                assert "道统投票 守界" in markdown_to_text(help_page.message)
                assert not help_page.actions
            finally:
                await runtime.close()

    asyncio.run(run())