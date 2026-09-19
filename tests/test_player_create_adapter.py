from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from xiuxian3.adapters.commands import PlayerCommandAdapter
from xiuxian3.adapters.contracts import CommandContext, MessageCapability, Scene
from xiuxian3.application.player import CreatePlayer, GetPlayerInfo
from xiuxian3.infrastructure.deterministic import FixedClock, SequenceIdGenerator
from xiuxian3.infrastructure.sqlite import SQLiteDatabase, SQLiteUnitOfWork


def test_registration_command_uses_new_user_create_contract() -> None:
    with TemporaryDirectory() as directory:
        database = SQLiteDatabase(Path(directory) / "game.sqlite3")
        adapter = PlayerCommandAdapter(
            CreatePlayer(
                lambda: SQLiteUnitOfWork(database),
                clock=FixedClock(datetime(2026, 1, 1, tzinfo=UTC)),
                ids=SequenceIdGenerator(["player-command-1"]),
            ),
            GetPlayerInfo(lambda: SQLiteUnitOfWork(database)),
        )
        context = CommandContext(
            actor_id="qq-200",
            scene=Scene.GROUP,
            group_id="group-1",
            message_id="message-1",
            text="我要修仙",
            raw_text_digest="digest-1",
            reply_to_message_id=None,
            capabilities=frozenset({MessageCapability.TEXT}),
            can_write_assets=True,
        )

        reply = adapter.handle(context)
        info = adapter.handle(
            CommandContext(
                actor_id="qq-200",
                scene=Scene.GROUP,
                group_id="group-1",
                message_id="message-2",
                text="我的状态",
                raw_text_digest="digest-2",
                reply_to_message_id=None,
                capabilities=frozenset({MessageCapability.TEXT}),
                can_write_assets=True,
            )
        )

        assert "新用户" in reply.text
        assert "new_user" in info.text
        assert "灵石：0" in info.text
