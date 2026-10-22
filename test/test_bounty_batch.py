from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime


def _context(user_id: str, request_id: str, *, operation_id: str = "") -> CommandContext:
    return CommandContext(
        adapter="web",
        user_id=user_id,
        request_id=request_id,
        operation_id=operation_id,
    )


class MutableClock:
    def __init__(self) -> None:
        self.value = datetime(2026, 10, 1, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **kwargs: int) -> None:
        self.value += timedelta(**kwargs)


def _set_player(runtime, user_id: str, **values: object) -> None:
    assignments = ", ".join(f"{key} = ?" for key in values)
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            f"UPDATE players SET {assignments} WHERE platform_user_id = ?",
            (*values.values(), user_id),
        )


async def _make_cultivator(runtime, user_id: str) -> None:
    assert (await runtime.dispatch(_context(user_id, "create"), "开始修仙")).ok
    assert (await runtime.dispatch(_context(user_id, "seek"), "寻仙问道")).ok
    _set_player(
        runtime,
        user_id,
        stage="cultivator",
        realm_key="qi_sensing",
        realm_layer=2,
        stamina=100,
        stamina_max=100,
        energy=30,
        energy_max=30,
    )


def test_bounty_board_shows_a_daily_batch_not_all_definitions() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=Path(data_dir))
            user = "batch-player"
            await _make_cultivator(runtime, user)
            board = await runtime.repository.get_bounty_board(
                platform="web", platform_user_id=user
            )
            offers = list(board.offers)
            assert len(offers) == 3, (
                f"the board must show a 3-offer batch, got {len(offers)}"
            )
            keys = [offer.key for offer in offers]
            assert len(set(keys)) == 3, "batch entries must be unique"
            # The board no longer renders the full definition set (34 bounties):
            # a batch of 3 covers it, so the M9 audit line
            # "当前展示全定义而非持久随机批次" is closed.
            rendered = await runtime.dispatch(
                _context(user, "board-message"), "悬赏榜"
            )
            assert rendered.ok and rendered.message.count("### ") <= 4, (
                "the rendered board must not enumerate the full definition set"
            )
            # Deterministic: the same player on the same business day gets the
            # identical batch.
            again = await runtime.repository.get_bounty_board(
                platform="web", platform_user_id=user
            )
            assert [offer.key for offer in again.offers] == keys
            await runtime.close()

    asyncio.run(run())


def test_bounty_batch_seed_isolated_between_players() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=Path(data_dir))
            await _make_cultivator(runtime, "player-a")
            await _make_cultivator(runtime, "player-b")
            board_a = await runtime.repository.get_bounty_board(
                platform="web", platform_user_id="player-a"
            )
            board_b = await runtime.repository.get_bounty_board(
                platform="web", platform_user_id="player-b"
            )
            keys_a = [offer.key for offer in board_a.offers]
            keys_b = [offer.key for offer in board_b.offers]
            assert board_a.refresh_seed != board_b.refresh_seed
            # Same-day batches may overlap, but the full 3-key ordering must
            # not be identical for both players (34 definitions, seeded order).
            assert keys_a != keys_b, (
                "different players must not share the same batch ordering"
            )
            await runtime.close()

    asyncio.run(run())


def test_bounty_batch_rotates_across_business_days() -> None:
    async def run() -> None:
        clock = MutableClock()
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=Path(data_dir), clock=clock)
            user = "rotating-player"
            await _make_cultivator(runtime, user)
            day_one = await runtime.repository.get_bounty_board(
                platform="web", platform_user_id=user
            )
            keys_one = [offer.key for offer in day_one.offers]
            clock.advance(days=1)
            day_two = await runtime.repository.get_bounty_board(
                platform="web", platform_user_id=user
            )
            keys_two = [offer.key for offer in day_two.offers]
            assert day_one.business_date != day_two.business_date
            assert keys_one != keys_two, "the batch must rotate across UTC days"
            await runtime.close()

    asyncio.run(run())


def test_accepted_bounty_stays_visible_outside_the_batch() -> None:
    async def run() -> None:
        clock = MutableClock()
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=Path(data_dir), clock=clock)
            user = "accepted-player"
            await _make_cultivator(runtime, user)
            board = await runtime.repository.get_bounty_board(
                platform="web", platform_user_id=user
            )
            in_batch = [offer.key for offer in board.offers]
            # Find an open bounty outside the current batch and accept it by key.
            from nonebot_plugin_xiuxian_3.xiuxian.adventures.rules import bounty_definitions

            outside = next(
                definition.key
                for definition in bounty_definitions(runtime.content or None)
                if definition.key not in in_batch
            )
            accepted = await runtime.repository.accept_bounty(
                platform="web",
                platform_user_id=user,
                bounty_key=outside,
                operation_id="accept-outside",
            )
            assert accepted.status == "accepted"
            board_after = await runtime.repository.get_bounty_board(
                platform="web", platform_user_id=user
            )
            keys_after = [offer.key for offer in board_after.offers]
            assert outside in keys_after, (
                "the accepted bounty must remain on the board even outside the batch"
            )
            assert len(keys_after) == 4, "batch of 3 plus the accepted bounty"
            await runtime.close()

    asyncio.run(run())
