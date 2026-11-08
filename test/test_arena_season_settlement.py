"""The weekly arena settlement must freeze a closed week and pay only from it.

Reviewed requirement: a closed week's rank and payout may never depend on the
mutable ``players.arena_rating``/``arena_wins`` columns, and later matches, later
player edits or a retry must not move it.  The board is rebuilt from
``arena_matches``, frozen once into ``arena_season_settlements``, and claims read
only that frozen row.  Per-match acknowledgement still pays nothing.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.specials.arena_season import (
    MatchEvent,
    build_board,
    week_key,
    week_window,
)

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


async def _prepare_pair(runtime, challenger: str, defender: str) -> None:
    await _cultivator(runtime, challenger)
    await _cultivator(runtime, defender)


async def _ranked_match(runtime, challenger: str, defender: str, *, prefix: str, clock) -> str:
    published = await runtime.dispatch(_ctx(defender, f"{prefix}-publish"), "发布竞技场快照")
    assert published.code == "ARENA_SNAPSHOT_PUBLISHED", published.message
    clock.advance(minutes=31)
    challenged = await runtime.dispatch(
        _ctx(challenger, f"{prefix}-challenge"),
        f"挑战竞技场排位 {published.data['snapshot_id']}",
    )
    assert challenged.code == "ARENA_MATCH_SETTLED", challenged.message
    clock.advance(minutes=1)
    return str(challenged.data["match_id"])


def _arena_state(runtime, user: str) -> tuple[int, int, int]:
    with sqlite3.connect(runtime.settings.database_path) as db:
        return tuple(
            db.execute(
                "SELECT arena_rating, arena_wins, arena_losses FROM players "
                "WHERE platform='web' AND platform_user_id=?",
                (user,),
            ).fetchone()
        )


def test_the_board_orders_by_rating_then_wins_and_breaks_ties_stably() -> None:
    anchor = datetime(2026, 1, 5, tzinfo=timezone.utc)
    start, end, key = week_window(datetime(2026, 1, 7, tzinfo=timezone.utc), anchor)
    assert key == week_key(start) == "arena.week.2026-01-05"

    earlier = start + timedelta(hours=1)
    later = start + timedelta(hours=2)
    events = [
        # Player 3 wins once late, player 1 wins once early: same rating/wins,
        # so the earlier first win must win the tie.
        MatchEvent(1, 25, True, "won", earlier),
        MatchEvent(3, 25, True, "won", later),
        MatchEvent(2, 50, True, "won", later),
        MatchEvent(2, 0, True, "lost", later),
        # Outside the window: must not count as a week result.
        MatchEvent(4, 999, True, "won", end + timedelta(seconds=1)),
    ]
    board = build_board(events, start=start, end=end)
    assert [entry.player_id for entry in board] == [2, 1, 3]
    assert [entry.rank for entry in board] == [1, 2, 3]
    assert board[0].rating == 1050 and board[0].wins == 1 and board[0].losses == 1


def test_practice_and_uncounted_matches_never_enter_the_board() -> None:
    anchor = datetime(2026, 1, 5, tzinfo=timezone.utc)
    start, end, _key = week_window(datetime(2026, 1, 7, tzinfo=timezone.utc), anchor)
    events = [
        MatchEvent(1, 0, False, "won", start + timedelta(hours=1)),
        MatchEvent(2, 25, True, "won", start + timedelta(hours=1)),
    ]
    board = build_board(events, start=start, end=end)
    assert [entry.player_id for entry in board] == [2]


def test_a_closed_week_freezes_and_later_history_cannot_move_it() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 24, 12, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            challenger, defender = "arena-season-a", "arena-season-b"
            await _prepare_pair(runtime, challenger, defender)
            await _ranked_match(runtime, challenger, defender, prefix="wk1", clock=clock)

            board = await runtime.repository.arena_season_board(
                platform="web", platform_user_id=challenger, week=None
            )
            old_week = board["week_key"]
            assert board["closed"] is False
            assert board["mine"] is not None

            # The week closes seven days after its start.
            clock.advance(days=8)
            mine_before = next(
                entry
                for entry in (
                    await runtime.repository.arena_season_board(
                        platform="web", platform_user_id=challenger, week=old_week
                    )
                )["board"]
                if entry["rank"] == 1
            )
            frozen_claim = await runtime.repository.claim_arena_season_reward(
                platform="web",
                platform_user_id=challenger,
                week=old_week,
                operation_id="season-claim-wk1",
            )
            assert frozen_claim["rank"] in {1, 2}
            assert frozen_claim["reward"]

            with sqlite3.connect(runtime.settings.database_path) as db:
                frozen_rows = db.execute(
                    "SELECT player_id, rank, rating, wins, reward_json FROM arena_season_settlements "
                    "WHERE week_key=? ORDER BY rank",
                    (old_week,),
                ).fetchall()
            assert frozen_rows, "the closed week must be frozen"
            rating_after_match, wins_after_match, _losses = _arena_state(runtime, challenger)

            # Later matches (a new week) change the live rating/wins columns.
            await _ranked_match(runtime, defender, challenger, prefix="wk2a", clock=clock)
            await _ranked_match(runtime, challenger, defender, prefix="wk2b", clock=clock)
            assert _arena_state(runtime, challenger) != (rating_after_match, wins_after_match, _losses)

            with sqlite3.connect(runtime.settings.database_path) as db:
                assert (
                    db.execute(
                        "SELECT player_id, rank, rating, wins, reward_json FROM arena_season_settlements "
                        "WHERE week_key=? ORDER BY rank",
                        (old_week,),
                    ).fetchall()
                    == frozen_rows
                )
            # The old week still renders exactly as frozen, and the claim replays.
            again = await runtime.repository.arena_season_board(
                platform="web", platform_user_id=challenger, week=old_week
            )
            assert again["board"][0]["rank"] == mine_before["rank"]
            assert again["board"][0]["rating"] == mine_before["rating"]
            assert again["claimed"] is True
            replay = await runtime.repository.claim_arena_season_reward(
                platform="web",
                platform_user_id=challenger,
                week=old_week,
                operation_id="season-claim-wk1",
            )
            assert replay["reward"] == frozen_claim["reward"]
            assert replay.get("idempotent_replay") is True
            with sqlite3.connect(runtime.settings.database_path) as db:
                assert db.execute(
                    "SELECT COUNT(*) FROM arena_season_claims WHERE week_key=?", (old_week,)
                ).fetchone()[0] == 1

    asyncio.run(run())


def _assets(runtime, user: str) -> tuple[int, str, str]:
    with sqlite3.connect(runtime.settings.database_path) as db:
        row = db.execute(
            "SELECT spirit_stones, inventory_json, intro_json FROM players "
            "WHERE platform='web' AND platform_user_id=?",
            (user,),
        ).fetchone()
    return int(row[0]), str(row[1]), str(row[2])


def test_a_match_pays_nothing_and_later_player_edits_cannot_move_a_closed_week() -> None:
    """Anti win-trading: assets move once per week, never per match."""

    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 24, 12, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            challenger, defender = "arena-pay-a", "arena-pay-b"
            await _prepare_pair(runtime, challenger, defender)
            before = _assets(runtime, challenger)

            await _ranked_match(runtime, challenger, defender, prefix="pay-1", clock=clock)
            assert _assets(runtime, challenger) == before
            await _ranked_match(runtime, challenger, defender, prefix="pay-2", clock=clock)
            assert _assets(runtime, challenger) == before, "a match must never pay assets"

            week = (
                await runtime.repository.arena_season_board(
                    platform="web", platform_user_id=challenger, week=None
                )
            )["week_key"]
            clock.advance(days=8)  # 2026-09-24 -> 2026-10-02: closed, still inside the claim window

            claim = await runtime.repository.claim_arena_season_reward(
                platform="web", platform_user_id=challenger, week=week, operation_id="pay-claim"
            )
            with sqlite3.connect(runtime.settings.database_path) as db:
                frozen = db.execute(
                    "SELECT player_id, rank, rating, wins, reward_json FROM arena_season_settlements "
                    "WHERE week_key=? ORDER BY rank",
                    (week,),
                ).fetchall()
            assert frozen, "the claim must freeze the closed week"
            reward = claim["reward"]
            paid = _assets(runtime, challenger)
            assert paid[0] == before[0] + int(reward.get("spirit_stones", 0))
            assert paid[1] != before[1] or not [
                key for key in reward if key.startswith("item.")
            ]

            # Direct edits to the mutable columns cannot rewrite the closed week.
            with sqlite3.connect(runtime.settings.database_path) as db:
                db.execute(
                    "UPDATE players SET arena_rating=99999, arena_wins=999, arena_losses=0 "
                    "WHERE platform='web' AND platform_user_id=?",
                    (challenger,),
                )
                db.commit()
                assert (
                    db.execute(
                        "SELECT player_id, rank, rating, wins, reward_json "
                        "FROM arena_season_settlements WHERE week_key=? ORDER BY rank",
                        (week,),
                    ).fetchall()
                    == frozen
                )
            board = await runtime.repository.arena_season_board(
                platform="web", platform_user_id=challenger, week=week
            )
            assert board["mine"] is not None
            assert board["mine"]["rating"] < 99999
            assert board["mine"]["wins"] < 999
            assert board["mine"]["rank"] == frozen[0][1]
            replay = await runtime.repository.claim_arena_season_reward(
                platform="web", platform_user_id=challenger, week=week, operation_id="pay-claim"
            )
            assert replay["reward"] == reward and replay.get("idempotent_replay") is True
            assert _assets(runtime, challenger) == paid

    asyncio.run(run())


def test_the_tie_break_is_win_rate_before_first_score() -> None:
    anchor = datetime(2026, 1, 5, tzinfo=timezone.utc)
    start, end, _key = week_window(datetime(2026, 1, 7, tzinfo=timezone.utc), anchor)
    early = start + timedelta(hours=1)
    late = start + timedelta(hours=2)
    events = [
        # Both end on 1000, but player 1 is 1/3 (win, loss, draw) and player 2 is
        # 1/2, so the documented win-rate tie-break must put player 2 first.
        MatchEvent(1, 25, True, "won", early),
        MatchEvent(1, -25, True, "lost", early),
        MatchEvent(1, 0, True, "draw", late),
        MatchEvent(2, 25, True, "won", late),
        MatchEvent(2, -25, True, "lost", late),
    ]
    board = build_board(events, start=start, end=end)
    assert [entry.player_id for entry in board] == [2, 1]
    assert board[0].rating == board[1].rating == 1000


def test_a_settled_week_stops_paying_once_the_claim_window_closes() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 24, 12, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            challenger, defender = "arena-exp-a", "arena-exp-b"
            await _prepare_pair(runtime, challenger, defender)
            await _ranked_match(runtime, challenger, defender, prefix="exp-1", clock=clock)
            week = (
                await runtime.repository.arena_season_board(
                    platform="web", platform_user_id=challenger, week=None
                )
            )["week_key"]

            clock.advance(days=8)  # closed
            clock.advance(days=8)  # well past the seven-day claim window
            board = await runtime.repository.arena_season_board(
                platform="web", platform_user_id=challenger, week=week
            )
            assert board["closed"] is True
            assert board["claim_expired"] is True
            assert board["claimable"] is False
            before = _assets(runtime, challenger)
            try:
                await runtime.repository.claim_arena_season_reward(
                    platform="web", platform_user_id=challenger, week=week, operation_id="exp-claim"
                )
            except Exception as exc:  # noqa: BLE001
                assert type(exc).__name__ == "ArenaSeasonClaimExpiredError"
            else:  # pragma: no cover
                raise AssertionError("an expired week must not pay")
            assert _assets(runtime, challenger) == before
            with sqlite3.connect(runtime.settings.database_path) as db:
                assert db.execute(
                    "SELECT COUNT(*) FROM arena_season_claims WHERE week_key=?", (week,)
                ).fetchone()[0] == 0

    asyncio.run(run())


def test_an_open_week_and_a_non_participant_are_refused() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 24, 12, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            challenger, defender = "arena-open-a", "arena-open-b"
            await _prepare_pair(runtime, challenger, defender)
            board = await runtime.repository.arena_season_board(
                platform="web", platform_user_id=challenger, week=None
            )
            open_week = board["week_key"]
            try:
                await runtime.repository.claim_arena_season_reward(
                    platform="web",
                    platform_user_id=challenger,
                    week=open_week,
                    operation_id="open-claim",
                )
            except Exception as exc:  # noqa: BLE001 - the typed error is asserted below
                assert type(exc).__name__ == "ArenaSeasonNotClosedError"
            else:  # pragma: no cover - a successful open-week claim is a defect
                raise AssertionError("an open week must not be claimable")

            clock.advance(days=8)
            with sqlite3.connect(runtime.settings.database_path) as db:
                assert db.execute(
                    "SELECT COUNT(*) FROM arena_season_claims WHERE week_key=?", (open_week,)
                ).fetchone()[0] == 0
                assert db.execute(
                    "SELECT COUNT(*) FROM arena_season_settlements WHERE week_key=?", (open_week,)
                ).fetchone()[0] == 0
            # A player with no counted match this week cannot claim even once it closes.
            late = "arena-late-joiner"
            await _cultivator(runtime, late)
            try:
                await runtime.repository.claim_arena_season_reward(
                    platform="web", platform_user_id=late, week=open_week, operation_id="late-claim"
                )
            except Exception as exc:  # noqa: BLE001
                assert type(exc).__name__ == "ArenaSeasonRankOutOfBoardError"
            else:  # pragma: no cover
                raise AssertionError("a non-participant must not be rewarded")

    asyncio.run(run())
