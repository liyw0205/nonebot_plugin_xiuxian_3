"""Player-facing surface for the weekly arena ladder.

The status page must show the live standing and offer the claim only when a
closed week has something to pay; the claim must refuse an open week and an
already-claimed week with distinct codes; help must mention the loop without
attaching buttons.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime

PLAYER_COMMANDS = (
    "开始修仙",
    "寻仙问道",
    "完成引导 阅读",
    "前往近郊",
    "完成引导 采集",
    "完成引导 炼丹",
    "选择道途 体修",
)


class MutableClock:
    def __init__(self, value: datetime):
        self.value = value

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **kwargs: int) -> None:
        self.value += timedelta(**kwargs)


def _ctx(user: str, operation: str) -> CommandContext:
    return CommandContext(adapter="web", user_id=user, request_id=operation, operation_id=operation)


async def _cultivator(runtime, user: str) -> None:
    for index, command in enumerate(PLAYER_COMMANDS):
        result = await runtime.dispatch(_ctx(user, f"{user}-{index}"), command)
        assert result.ok, (command, result.code, result.message)


async def _ranked_match(runtime, challenger: str, defender: str, *, prefix: str, clock) -> None:
    published = await runtime.dispatch(_ctx(defender, f"{prefix}-publish"), "发布竞技场快照")
    assert published.code == "ARENA_SNAPSHOT_PUBLISHED", published.message
    clock.advance(minutes=31)
    challenged = await runtime.dispatch(
        _ctx(challenger, f"{prefix}-challenge"),
        f"挑战竞技场排位 {published.data['snapshot_id']}",
    )
    assert challenged.code == "ARENA_MATCH_SETTLED", challenged.message
    clock.advance(minutes=1)


def test_the_status_page_offers_the_claim_only_after_the_week_closes() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 24, 12, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            challenger, defender = "season-ui-a", "season-ui-b"
            await _cultivator(runtime, challenger)
            await _cultivator(runtime, defender)
            await _ranked_match(runtime, challenger, defender, prefix="ui-wk1", clock=clock)

            live = await runtime.dispatch(_ctx(challenger, "ui-live"), "竞技场赛季")
            assert live.code == "ARENA_SEASON", live.message
            assert "周赛季" in live.message
            assert "我的名次" in live.message
            assert live.data["closed"] is False
            assert live.actions == ()
            assert "command:" not in live.message.split("**本周前五**")[-1]
            assert "本周结算后可按名次领取奖励" in live.message

            # The open current week is refused even when named explicitly.
            early = await runtime.dispatch(
                _ctx(challenger, "ui-early"), f"领取竞技场赛季奖励 {live.data['week_key']}"
            )
            assert early.code == "ARENA_SEASON_OPEN", early.message

            clock.advance(days=8)
            last_week = live.data["week_key"]
            closed = await runtime.dispatch(_ctx(challenger, "ui-closed"), "竞技场赛季")
            assert closed.code == "ARENA_SEASON"
            # The page still shows the live current week, and surfaces last week's claim.
            assert closed.data["closed"] is False
            assert closed.data["previous"]["week_key"] == last_week
            assert closed.data["previous"]["claimable"] is True
            assert "上周名次" in closed.message
            assert "已可领取" in closed.message
            assert "领取上周竞技奖励" in closed.message
            assert "command:" in closed.message
            assert [action.label for action in closed.actions] == ["领取周榜奖励"]

            # A bare claim collects the previous closed week.
            claimed = await runtime.dispatch(_ctx(challenger, "ui-claim"), "领取竞技场赛季奖励")
            assert claimed.code == "ARENA_SEASON_CLAIMED", claimed.message
            assert claimed.data["week_key"] == last_week
            assert "名次" in claimed.message and "所得" in claimed.message
            assert [action.label for action in claimed.actions] == ["再看竞技场赛季"]
            assert "竞技场赛季" in claimed.message  # blue link back to the board

            again = await runtime.dispatch(_ctx(challenger, "ui-claim-2"), "领取竞技场赛季奖励")
            assert again.code == "ARENA_SEASON_ALREADY_CLAIMED", again.message

            done = await runtime.dispatch(_ctx(challenger, "ui-done"), "竞技场赛季")
            assert done.data["previous"]["claimed"] is True
            assert "上周奖励已领取" in done.message
            assert done.actions == ()

    asyncio.run(run())


def test_help_lists_the_season_loop_without_buttons() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            result = await runtime.dispatch(_ctx("season-help", "help-social"), "修仙帮助 社交")
            assert result.ok
            assert "竞技场赛季" in result.message
            assert "领取竞技场赛季奖励" in result.message
            assert result.actions == ()

    asyncio.run(run())
