from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from xiuxian3.application.player import (
    CompleteIntro,
    CompleteIntroCommand,
    CreatePlayer,
    CreatePlayerCommand,
    StartSeeking,
    StartSeekingCommand,
)
from xiuxian3.infrastructure.deterministic import FixedClock, SequenceIdGenerator, SequenceRandom
from xiuxian3.infrastructure.sqlite import SQLiteDatabase, SQLiteUnitOfWork


def setup():
    directory = TemporaryDirectory()
    database = SQLiteDatabase(Path(directory.name) / "game.sqlite3")
    ids = SequenceIdGenerator(["player-intro-1"])
    create = CreatePlayer(
        lambda: SQLiteUnitOfWork(database),
        clock=FixedClock(datetime(2026, 1, 1, tzinfo=UTC)),
        ids=ids,
    )
    created = create.execute(
        CreatePlayerCommand("onebot_v11", "qq-intro", "private", "凡人", "op-create-intro")
    )
    assert created.ok
    seeking = StartSeeking(
        lambda: SQLiteUnitOfWork(database),
        clock=FixedClock(datetime(2026, 1, 1, tzinfo=UTC)),
        random_source=SequenceRandom([0] * 40),
    )
    mortal = seeking.execute(
        StartSeekingCommand(created.value.player_id, "wood", "op-seeking-intro")
    )
    assert mortal.ok
    intro = CompleteIntro(
        lambda: SQLiteUnitOfWork(database),
        clock=FixedClock(datetime(2026, 1, 1, tzinfo=UTC)),
        random_source=SequenceRandom([0]),
    )
    return directory, database, mortal.value, intro


def test_intro_guides_can_complete_in_any_order_and_enter_seeker() -> None:
    directory, _, player, intro = setup()
    try:
        service = intro.execute(
            CompleteIntroCommand(player.player_id, "choose_service", "alchemy", "guide-service")
        )
        read = intro.execute(CompleteIntroCommand(player.player_id, "read_world", None, "guide-read"))
        gather = intro.execute(CompleteIntroCommand(player.player_id, "gather_blood_grass", None, "guide-gather"))

        assert service.ok and read.ok and gather.ok
        assert gather.value.stage == "seeker"
        assert gather.value.stamina == 28
        assert gather.value.energy == 28
        assert "item.herb.blood_grass" in gather.value.inventory_json
    finally:
        directory.cleanup()


def test_repeated_guide_operation_replays_without_double_cost() -> None:
    directory, _, player, intro = setup()
    try:
        first = intro.execute(
            CompleteIntroCommand(player.player_id, "gather_blood_grass", None, "guide-repeat")
        )
        replay = intro.execute(
            CompleteIntroCommand(player.player_id, "gather_blood_grass", None, "guide-repeat")
        )
        assert first.ok and replay.ok
        assert replay.value == first.value
        assert replay.value.stamina == 28
    finally:
        directory.cleanup()
