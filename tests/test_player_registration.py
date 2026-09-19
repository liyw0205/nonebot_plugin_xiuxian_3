from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

import pytest

from xiuxian3.application.player import (
    GetPlayerInfo,
    GetPlayerInfoQuery,
    RegisterPlayer,
    RegisterPlayerCommand,
)
from xiuxian3.domain.result import ErrorCode
from xiuxian3.infrastructure.deterministic import FixedClock, SequenceIdGenerator
from xiuxian3.infrastructure.sqlite import SQLiteDatabase, SQLiteUnitOfWork

pytestmark = pytest.mark.integration


class PlayerRegistrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        database = SQLiteDatabase(Path(self.directory.name) / "game.sqlite3")
        self.clock = FixedClock(datetime(2026, 1, 1, tzinfo=UTC))
        self.ids = SequenceIdGenerator(["player-1"])
        self.register = RegisterPlayer(
            lambda: SQLiteUnitOfWork(database),
            clock=self.clock,
            ids=self.ids,
        )
        self.info = GetPlayerInfo(lambda: SQLiteUnitOfWork(database))

    def tearDown(self) -> None:
        self.directory.cleanup()

    def test_registration_persists_player_and_replays_same_operation(self) -> None:
        command = RegisterPlayerCommand(actor_id="qq-1", operation_id="op-register-1")
        first = self.register.execute(command)
        second = self.register.execute(command)
        self.assertTrue(first.ok)
        self.assertTrue(second.ok)
        self.assertEqual(first.value, second.value)
        self.assertEqual(first.value.player_id, "player-1")
        self.assertEqual(first.value.nickname, "qq-1")
        self.assertEqual(first.value.stamina, 100)

    def test_same_operation_id_with_different_input_is_conflict(self) -> None:
        self.assertTrue(
            self.register.execute(
                RegisterPlayerCommand(actor_id="qq-1", operation_id="op-register-2")
            ).ok
        )
        conflict = self.register.execute(
            RegisterPlayerCommand(actor_id="qq-2", operation_id="op-register-2")
        )
        self.assertFalse(conflict.ok)
        self.assertEqual(conflict.error.code, ErrorCode.CONFLICT)

    def test_existing_player_with_new_operation_is_rejected_without_second_player(self) -> None:
        self.assertTrue(
            self.register.execute(
                RegisterPlayerCommand(actor_id="qq-1", operation_id="op-register-3")
            ).ok
        )
        duplicate = self.register.execute(
            RegisterPlayerCommand(actor_id="qq-1", operation_id="op-register-4")
        )
        self.assertFalse(duplicate.ok)
        self.assertEqual(duplicate.error.code, ErrorCode.CONFLICT)

    def test_info_query_is_read_only_and_missing_player_is_not_found(self) -> None:
        missing = self.info.execute(GetPlayerInfoQuery(actor_id="missing"))
        self.assertFalse(missing.ok)
        self.assertEqual(missing.error.code, ErrorCode.NOT_FOUND)
        self.assertTrue(
            self.register.execute(
                RegisterPlayerCommand(actor_id="qq-1", operation_id="op-register-5")
            ).ok
        )
        result = self.info.execute(GetPlayerInfoQuery(actor_id="qq-1"))
        self.assertTrue(result.ok)
        self.assertEqual(result.value.realm, "凡人")
        self.assertEqual(result.value.cultivation, 0)
