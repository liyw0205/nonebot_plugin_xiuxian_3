from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from xiuxian3.application.player import RegisterPlayer, RegisterPlayerCommand
from xiuxian3.domain.result import ErrorCode
from xiuxian3.infrastructure.deterministic import FixedClock, SequenceIdGenerator
from xiuxian3.infrastructure.sqlite import SQLiteDatabase, SQLiteUnitOfWork


def test_register_maps_ledger_conflict_to_application_result() -> None:
    with TemporaryDirectory() as directory:
        database = SQLiteDatabase(Path(directory) / "game.sqlite3")
        register = RegisterPlayer(
            lambda: SQLiteUnitOfWork(database),
            clock=FixedClock(datetime(2026, 1, 1, tzinfo=UTC)),
            ids=SequenceIdGenerator(["player-1"]),
        )

        first = register.execute(
            RegisterPlayerCommand(actor_id="qq-1", operation_id="op-conflict-boundary")
        )
        second = register.execute(
            RegisterPlayerCommand(actor_id="qq-2", operation_id="op-conflict-boundary")
        )

        assert first.ok
        assert not second.ok
        assert second.error is not None
        assert second.error.code is ErrorCode.CONFLICT
