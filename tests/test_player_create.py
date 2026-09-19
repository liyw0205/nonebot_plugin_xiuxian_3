from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from xiuxian3.application.player import CreatePlayer, CreatePlayerCommand
from xiuxian3.domain.result import ErrorCode
from xiuxian3.infrastructure.deterministic import FixedClock, SequenceIdGenerator
from xiuxian3.infrastructure.sqlite import SQLiteDatabase, SQLiteUnitOfWork


def make_create(directory: str) -> CreatePlayer:
    database = SQLiteDatabase(Path(directory) / "game.sqlite3")
    return CreatePlayer(
        lambda: SQLiteUnitOfWork(database),
        clock=FixedClock(datetime(2026, 1, 1, tzinfo=UTC)),
        ids=SequenceIdGenerator(["player-new-1"]),
    )


def test_player_create_only_creates_new_user_without_assets() -> None:
    with TemporaryDirectory() as directory:
        result = make_create(directory).execute(
            CreatePlayerCommand(
                platform="onebot_v11",
                platform_user_id="qq-100",
                scene="group:42",
                nickname="初入玄天",
                operation_id="player.create:onebot_v11:qq-100",
            )
        )

        assert result.ok
        player = result.value
        assert player.stage == "new_user"
        assert player.status.value == "active"
        assert player.platform == "onebot_v11"
        assert player.location_key == "xuantian.new_town"
        assert player.spirit_stones == 0
        assert player.stamina == 0
        assert player.cultivation == 0


def test_player_create_replays_and_same_identity_returns_existing_player() -> None:
    with TemporaryDirectory() as directory:
        create = make_create(directory)
        first = create.execute(
            CreatePlayerCommand("onebot_v11", "qq-101", "private", "甲", "op-create-1")
        )
        replay = create.execute(
            CreatePlayerCommand("onebot_v11", "qq-101", "private", "甲", "op-create-1")
        )
        same_identity = create.execute(
            CreatePlayerCommand("onebot_v11", "qq-101", "private", "乙", "op-create-2")
        )

        assert first.ok and replay.ok and same_identity.ok
        assert replay.value == first.value
        assert same_identity.value == first.value


def test_player_create_conflicting_operation_returns_result_error() -> None:
    with TemporaryDirectory() as directory:
        create = make_create(directory)
        assert create.execute(
            CreatePlayerCommand("onebot_v11", "qq-102", "private", "甲", "op-create-3")
        ).ok

        conflict = create.execute(
            CreatePlayerCommand("onebot_v11", "qq-103", "private", "乙", "op-create-3")
        )

        assert not conflict.ok
        assert conflict.error is not None
        assert conflict.error.code is ErrorCode.CONFLICT
