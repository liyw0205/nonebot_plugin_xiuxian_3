from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from xiuxian3.application.player import CreatePlayer, CreatePlayerCommand, StartSeeking, StartSeekingCommand
from xiuxian3.domain.result import ErrorCode
from xiuxian3.infrastructure.deterministic import FixedClock, SequenceIdGenerator, SequenceRandom
from xiuxian3.infrastructure.sqlite import SQLiteDatabase, SQLiteUnitOfWork


def setup():
    directory = TemporaryDirectory()
    database = SQLiteDatabase(Path(directory.name) / "game.sqlite3")
    create = CreatePlayer(
        lambda: SQLiteUnitOfWork(database),
        clock=FixedClock(datetime(2026, 1, 1, tzinfo=UTC)),
        ids=SequenceIdGenerator(["player-seeking-1"]),
    )
    created = create.execute(
        CreatePlayerCommand("onebot_v11", "qq-seeking", "private", "求道者", "op-create-seeking")
    )
    assert created.ok
    seeking = StartSeeking(
        lambda: SQLiteUnitOfWork(database),
        clock=FixedClock(datetime(2026, 1, 1, tzinfo=UTC)),
        random_source=SequenceRandom([0] * 40),
    )
    return directory, database, created.value, seeking


def test_start_seeking_creates_snapshot_and_initial_resources() -> None:
    directory, database, player, seeking = setup()
    try:
        result = seeking.execute(
            StartSeekingCommand(player.player_id, "water", "op-seeking-1")
        )
        assert result.ok
        updated = result.value
        assert updated.stage == "mortal"
        assert updated.spirit_stones == 100
        assert updated.stamina == 30
        assert updated.energy == 30
        assert updated.qualification_snapshot_id
        with database.connect() as connection:
            snapshot = connection.execute(
                "SELECT * FROM qualification_snapshots WHERE snapshot_id = ?",
                (updated.qualification_snapshot_id,),
            ).fetchone()
        assert snapshot is not None
        values = [snapshot[key] for key in ("body", "spirit", "insight", "root", "agility", "fortune")]
        assert sum(values) == 60
        assert all(5 <= value <= 15 for value in values)
        assert snapshot["spirit_root"] == "water"
    finally:
        directory.cleanup()


def test_start_seeking_replays_and_rejects_different_operation_input() -> None:
    directory, _, player, seeking = setup()
    try:
        command = StartSeekingCommand(player.player_id, "metal", "op-seeking-2")
        first = seeking.execute(command)
        replay = seeking.execute(command)
        conflict = seeking.execute(
            StartSeekingCommand(player.player_id, "wood", "op-seeking-2")
        )
        assert first.ok and replay.ok
        assert replay.value == first.value
        assert not conflict.ok
        assert conflict.error is not None
        assert conflict.error.code is ErrorCode.CONFLICT
    finally:
        directory.cleanup()


def test_start_seeking_rejects_invalid_tendency_without_changing_player() -> None:
    directory, _, player, seeking = setup()
    try:
        result = seeking.execute(
            StartSeekingCommand(player.player_id, "void", "op-seeking-3")
        )
        assert not result.ok
        assert result.error is not None
        assert result.error.code is ErrorCode.INVALID_INPUT
        current = seeking.get_player(player.player_id)
        assert current.stage == "new_user"
        assert current.spirit_stones == 0
    finally:
        directory.cleanup()
