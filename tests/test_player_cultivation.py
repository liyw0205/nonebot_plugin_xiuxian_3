from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from xiuxian3.application.player import (
    CompleteIntro,
    CompleteIntroCommand,
    CreatePlayer,
    CreatePlayerCommand,
    EnterCultivation,
    EnterCultivationCommand,
    StartSeeking,
    StartSeekingCommand,
)
from xiuxian3.domain.result import ErrorCode
from xiuxian3.infrastructure.deterministic import FixedClock, SequenceIdGenerator, SequenceRandom
from xiuxian3.infrastructure.sqlite import SQLiteDatabase, SQLiteUnitOfWork


def setup_seeker():
    directory = TemporaryDirectory()
    database = SQLiteDatabase(Path(directory.name) / "game.sqlite3")
    create = CreatePlayer(
        lambda: SQLiteUnitOfWork(database),
        clock=FixedClock(datetime(2026, 1, 1, tzinfo=UTC)),
        ids=SequenceIdGenerator(["player-cultivation-1"]),
    )
    created = create.execute(
        CreatePlayerCommand("onebot_v11", "qq-cultivation", "private", "求道者", "op-create-cultivation")
    )
    assert created.ok
    seeking = StartSeeking(
        lambda: SQLiteUnitOfWork(database),
        clock=FixedClock(datetime(2026, 1, 1, tzinfo=UTC)),
        random_source=SequenceRandom([0] * 40),
    )
    mortal = seeking.execute(
        StartSeekingCommand(created.value.player_id, "water", "op-seeking-cultivation")
    )
    assert mortal.ok
    intro = CompleteIntro(
        lambda: SQLiteUnitOfWork(database),
        clock=FixedClock(datetime(2026, 1, 1, tzinfo=UTC)),
        random_source=SequenceRandom([0]),
    )
    player = mortal.value
    for guide_key, service_key, operation_id in (
        ("read_world", None, "intro-read-cultivation"),
        ("choose_service", "alchemy", "intro-service-cultivation"),
        ("gather_blood_grass", None, "intro-gather-cultivation"),
    ):
        result = intro.execute(
            CompleteIntroCommand(player.player_id, guide_key, service_key, operation_id)
        )
        assert result.ok
        player = result.value
    assert player.stage == "seeker"
    enter = EnterCultivation(
        lambda: SQLiteUnitOfWork(database),
        clock=FixedClock(datetime(2026, 1, 1, tzinfo=UTC)),
    )
    return directory, database, player, enter


def test_enter_cultivation_sets_path_and_qi_sensing_layer_one() -> None:
    directory, _, player, enter = setup_seeker()
    try:
        result = enter.execute(
            EnterCultivationCommand(player.player_id, "spell", None, "op-enter-spell")
        )
        assert result.ok
        updated = result.value
        assert updated.stage == "cultivator"
        assert updated.realm_key == "qi_sensing"
        assert updated.realm_layer == 1
        assert updated.realm == "感气"
        assert updated.path_key == "spell"
        assert updated.subprofession_key is None
        assert updated.spirit_stones == 300
        assert "item.manual.basic_qi" in updated.inventory_json
        assert "skill.spell.water_bolt" in updated.known_skills_json
    finally:
        directory.cleanup()


def test_support_requires_a_valid_subprofession_and_replays() -> None:
    directory, _, player, enter = setup_seeker()
    try:
        missing = enter.execute(
            EnterCultivationCommand(player.player_id, "support", None, "op-enter-support-missing")
        )
        assert not missing.ok
        assert missing.error is not None
        assert missing.error.code is ErrorCode.INVALID_INPUT

        command = EnterCultivationCommand(
            player.player_id, "support", "formation", "op-enter-support"
        )
        first = enter.execute(command)
        replay = enter.execute(command)
        conflict = enter.execute(
            EnterCultivationCommand(player.player_id, "support", "alchemy", "op-enter-support")
        )
        assert first.ok and replay.ok
        assert replay.value == first.value
        assert first.value.subprofession_key == "formation"
        assert not conflict.ok
        assert conflict.error is not None
        assert conflict.error.code is ErrorCode.CONFLICT
    finally:
        directory.cleanup()


def test_non_seeker_cannot_enter_cultivation() -> None:
    directory = TemporaryDirectory()
    database = SQLiteDatabase(Path(directory.name) / "game.sqlite3")
    create = CreatePlayer(
        lambda: SQLiteUnitOfWork(database),
        clock=FixedClock(datetime(2026, 1, 1, tzinfo=UTC)),
        ids=SequenceIdGenerator(["player-not-seeker"]),
    )
    try:
        created = create.execute(
            CreatePlayerCommand("onebot_v11", "qq-not-seeker", "private", "新用户", "op-not-seeker")
        )
        assert created.ok
        enter = EnterCultivation(
            lambda: SQLiteUnitOfWork(database),
            clock=FixedClock(datetime(2026, 1, 1, tzinfo=UTC)),
        )
        result = enter.execute(
            EnterCultivationCommand(created.value.player_id, "body", None, "op-enter-not-seeker")
        )
        assert not result.ok
        assert result.error is not None
        assert result.error.code is ErrorCode.PLAYER_STAGE_CONFLICT
    finally:
        directory.cleanup()
