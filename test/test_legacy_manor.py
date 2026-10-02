from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory

import pytest

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime


CLUE = "item.clue.demon_contract"
STORY = "story.legacy.demon_reliquary"


class MutableClock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs: int) -> None:
        self.now += timedelta(**kwargs)


def _ctx(adapter: str, user: str, operation: str) -> CommandContext:
    return CommandContext(adapter=adapter, user_id=user, operation_id=operation)


async def _player(runtime, adapter: str, user: str, *, permission: bool = True, clue_count: int = 1) -> None:
    created = await runtime.adapters.dispatch(adapter, _ctx(adapter, user, f"{user}:create"), "开始修仙")
    assert created.code == "PLAYER_CREATED"
    flags = ["access.demon.fallen_ruins"] if permission else []
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE players SET realm_key='nascent_soul', realm_layer=1, location_key='demon.fallen_ruins', "
            "intro_json=?, inventory_json=?, stamina=43, spirit_stones=71, pollution=12 "
            "WHERE platform=? AND platform_user_id=?",
            (
                json.dumps({"flags": flags}),
                json.dumps({CLUE: clue_count} if clue_count else {}),
                adapter,
                user,
            ),
        )


async def _finish(runtime, adapter: str, user: str, prefix: str, *, start_index: int = 0):
    nodes = ("遗府封印", "契约档案", "旧誓密室")
    for index in range(start_index, len(nodes)):
        node = nodes[index]
        selected = await runtime.adapters.dispatch(
            adapter,
            _ctx(adapter, user, f"{prefix}:node:{index}"),
            f"选择遗府节点 {node}",
        )
        assert selected.ok, selected
    return await runtime.adapters.dispatch(adapter, _ctx(adapter, user, f"{prefix}:settle"), "结算遗府")


@pytest.mark.parametrize("adapter", ["qq.official", "onebot.v11"])
def test_legacy_manor_is_idempotent_and_story_only(adapter: str) -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, adapters=(adapter,))
            user = f"legacy-manor-{adapter}"
            await _player(runtime, adapter, user)
            entered = await runtime.adapters.dispatch(adapter, _ctx(adapter, user, "entry"), "进入遗府")
            replay = await runtime.adapters.dispatch(adapter, _ctx(adapter, user, "entry"), "进入遗府")
            assert entered.code == "LEGACY_MANOR_ENTERED"
            assert replay.data["idempotent_replay"] is True

            skipped = await runtime.adapters.dispatch(adapter, _ctx(adapter, user, "skip"), "选择遗府节点 契约档案")
            assert skipped.code == "LEGACY_MANOR_NODE_FORBIDDEN"
            first = await runtime.adapters.dispatch(adapter, _ctx(adapter, user, "route:0"), "选择遗府节点 遗府封印")
            assert first.ok
            first_replay = await runtime.adapters.dispatch(adapter, _ctx(adapter, user, "route:0"), "选择遗府节点 遗府封印")
            assert first_replay.data["idempotent_replay"] is True
            conflict = await runtime.adapters.dispatch(adapter, _ctx(adapter, user, "route:0"), "选择遗府节点 契约档案")
            assert conflict.code == "OPERATION_CONFLICT"

            settled = await _finish(runtime, adapter, user, "route", start_index=1)
            assert settled.code == "LEGACY_MANOR_SETTLED"
            assert settled.data["story_flag_written"] is True
            settlement_replay = await runtime.adapters.dispatch(adapter, _ctx(adapter, user, "route:settle"), "结算遗府")
            assert settlement_replay.data["idempotent_replay"] is True
            denied_repeat = await runtime.adapters.dispatch(adapter, _ctx(adapter, user, "entry:after-clear"), "进入遗府")
            assert denied_repeat.code == "LEGACY_MANOR_ALREADY_CLEARED"

            with sqlite3.connect(runtime.settings.database_path) as connection:
                flags, inventory, stamina, stones, pollution, reputation = connection.execute(
                    "SELECT intro_json, inventory_json, stamina, spirit_stones, pollution, faction_reputation_json "
                    "FROM players WHERE platform=? AND platform_user_id=?",
                    (adapter, user),
                ).fetchone()
                run_count = connection.execute("SELECT COUNT(*) FROM legacy_manor_runs WHERE player_id=("
                    "SELECT id FROM players WHERE platform=? AND platform_user_id=?)", (adapter, user)).fetchone()[0]
            assert json.loads(flags)["flags"].count(STORY) == 1
            assert json.loads(inventory) == {CLUE: 1}
            assert (stamina, stones, pollution, json.loads(reputation)) == (43, 71, 12, {})
            assert run_count == 1
            await runtime.close()

    asyncio.run(run())


def test_legacy_manor_requires_existing_permission_and_clue_atomically() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, adapters=("qq.official",))
            user = "legacy-manor-gates"
            await _player(runtime, "qq.official", user, permission=False, clue_count=1)
            denied_permission = await runtime.adapters.dispatch(
                "qq.official", _ctx("qq.official", user, "denied:permission"), "进入遗府"
            )
            assert denied_permission.code == "LEGACY_MANOR_REQUIREMENT_MISSING"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                player_id = connection.execute(
                    "SELECT id FROM players WHERE platform=? AND platform_user_id=?", ("qq.official", user)
                ).fetchone()[0]
                assert connection.execute("SELECT COUNT(*) FROM legacy_manor_runs WHERE player_id=?", (player_id,)).fetchone()[0] == 0
                connection.execute(
                    "UPDATE players SET intro_json=?, inventory_json='{}' WHERE id=?",
                    (json.dumps({"flags": ["access.demon.fallen_ruins"]}), player_id),
                )
            denied_clue = await runtime.adapters.dispatch(
                "qq.official", _ctx("qq.official", user, "denied:clue"), "进入遗府"
            )
            assert denied_clue.code == "LEGACY_MANOR_REQUIREMENT_MISSING"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute("SELECT COUNT(*) FROM legacy_manor_runs WHERE player_id=?", (player_id,)).fetchone()[0] == 0
                connection.execute("UPDATE players SET inventory_json=? WHERE id=?", (json.dumps({CLUE: 1}), player_id))
            entered = await runtime.adapters.dispatch("qq.official", _ctx("qq.official", user, "allowed"), "进入遗府")
            assert entered.ok
            with runtime.repository._connect() as connection:
                assert runtime.repository._has_active_long_action(connection, player_id)
            conflicting = await runtime.adapters.dispatch("qq.official", _ctx("qq.official", user, "entry:parallel"), "进入遗府")
            assert conflicting.code == "LEGACY_MANOR_BUSY"
            await runtime.close()

    asyncio.run(run())


def test_legacy_manor_entry_rolls_back_if_operation_ledger_write_fails() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, adapters=("onebot.v11",))
            user = "legacy-manor-persistence-failure"
            await _player(runtime, "onebot.v11", user)
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "CREATE TRIGGER fail_legacy_manor_enter BEFORE INSERT ON operations "
                    "WHEN NEW.operation_name='legacy_manor.enter' "
                    "BEGIN SELECT RAISE(ABORT, 'injected legacy-manor operation failure'); END"
                )
            failed = await runtime.adapters.dispatch(
                "onebot.v11", _ctx("onebot.v11", user, "rollback:entry"), "进入遗府"
            )
            assert failed.code == "PERSISTENCE_ERROR"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                player_id = connection.execute(
                    "SELECT id FROM players WHERE platform=? AND platform_user_id=?", ("onebot.v11", user)
                ).fetchone()[0]
                assert connection.execute("SELECT COUNT(*) FROM legacy_manor_runs WHERE player_id=?", (player_id,)).fetchone()[0] == 0
                assert connection.execute("SELECT COUNT(*) FROM operations WHERE operation_id='rollback:entry'").fetchone()[0] == 0
            await runtime.close()

    asyncio.run(run())


def test_legacy_manor_survives_adapter_handoff_expiry_and_system_abort() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 28, 12, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            user = "legacy-manor-handoff"
            await _player(runtime, "qq.official", user)
            entered = await runtime.adapters.dispatch("qq.official", _ctx("qq.official", user, "handoff:entry"), "进入遗府")
            assert entered.ok
            first_node = await runtime.adapters.dispatch(
                "qq.official", _ctx("qq.official", user, "handoff:node:0"), "选择遗府节点 遗府封印"
            )
            assert first_node.ok
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE players SET platform='onebot.v11' WHERE platform='qq.official' AND platform_user_id=?",
                    (user,),
                )
            await runtime.close()

            runtime = create_runtime(data_dir=data_dir, clock=clock)
            status = await runtime.adapters.dispatch(
                "onebot.v11", _ctx("onebot.v11", user, "handoff:status"), "遗府状态"
            )
            assert status.ok and status.data["current_node"] == "pact_archive"
            clock.advance(hours=1, seconds=1)
            expired_status = await runtime.adapters.dispatch(
                "onebot.v11", _ctx("onebot.v11", user, "handoff:expired-status"), "遗府状态"
            )
            assert expired_status.ok and expired_status.data["status"] == "expired"
            expired = await runtime.adapters.dispatch(
                "onebot.v11", _ctx("onebot.v11", user, "handoff:expire"), "结算遗府"
            )
            assert expired.data["outcome"] == "expired" and expired.data["story_flag_written"] is False

            retry = await runtime.adapters.dispatch("onebot.v11", _ctx("onebot.v11", user, "handoff:retry"), "进入遗府")
            assert retry.ok
            aborted = await runtime.repository.compensate_legacy_manor_system_failure(
                run_id=retry.data["run_id"], operation_id="handoff:abort"
            )
            replay = await runtime.repository.compensate_legacy_manor_system_failure(
                run_id=retry.data["run_id"], operation_id="handoff:abort"
            )
            assert aborted.outcome == "system_aborted" and replay.already_completed is True
            final_retry = await runtime.adapters.dispatch("onebot.v11", _ctx("onebot.v11", user, "handoff:retry-again"), "进入遗府")
            assert final_retry.ok
            cleared = await _finish(runtime, "onebot.v11", user, "handoff:clear")
            assert cleared.data["story_flag_written"] is True
            await runtime.close()

    asyncio.run(run())
