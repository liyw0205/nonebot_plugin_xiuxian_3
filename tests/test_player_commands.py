from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from xiuxian3.adapters.commands import PlayerCommandAdapter
from xiuxian3.adapters.contracts import CommandContext, MessageCapability, Scene
from xiuxian3.application.player import GetPlayerInfo, RegisterPlayer
from xiuxian3.infrastructure.deterministic import FixedClock, SequenceIdGenerator
from xiuxian3.infrastructure.sqlite import SQLiteDatabase, SQLiteUnitOfWork


class PlayerCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        database = SQLiteDatabase(Path(self.directory.name) / "game.sqlite3")
        clock = FixedClock(datetime(2026, 1, 1, tzinfo=UTC))
        self.adapter = PlayerCommandAdapter(
            RegisterPlayer(
                lambda: SQLiteUnitOfWork(database),
                clock=clock,
                ids=SequenceIdGenerator(["player-1"]),
            ),
            GetPlayerInfo(lambda: SQLiteUnitOfWork(database)),
        )

    def tearDown(self) -> None:
        self.directory.cleanup()

    def _context(self, text: str, message_id: str) -> CommandContext:
        return CommandContext(
            actor_id="qq-1",
            scene=Scene.GROUP,
            group_id="group-1",
            message_id=message_id,
            text=text,
            raw_text_digest=f"digest-{message_id}",
            reply_to_message_id=None,
            capabilities=frozenset({MessageCapability.TEXT, MessageCapability.KEYBOARD}),
            can_write_assets=True,
        )

    def test_text_registration_and_button_registration_share_application_result(self) -> None:
        text_reply = self.adapter.handle(self._context("我要修仙", "m-1"))
        button_reply = self.adapter.handle_button(self._context("我要修仙", "m-1"))
        self.assertIn("player-1", text_reply.text)
        self.assertEqual(text_reply.text, button_reply.text)

    def test_info_aliases_share_query_use_case(self) -> None:
        self.adapter.handle(self._context("我要修仙", "m-2"))
        first = self.adapter.handle(self._context("我的修仙信息", "m-3"))
        second = self.adapter.handle(self._context("我的状态", "m-4"))
        self.assertEqual(first.text, second.text)
        self.assertIn("凡人", first.text)
