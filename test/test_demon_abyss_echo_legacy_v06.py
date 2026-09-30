from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory

import pytest

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.adventures.legacy_manor_migration import ensure_legacy_manor_schema


CLUE = "item.clue.demon_abyss_echo"
STORY = "story.legacy.demon_abyss_echo"
NODES = ("残响门庭", "封存回声", "未竟之言")


class MutableClock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs: int) -> None:
        self.now += timedelta(**kwargs)


def _ctx(adapter: str, user: str, operation: str) -> CommandContext:
    return CommandContext(adapter=adapter, user_id=user, operation_id=operation)


async def _player(runtime, adapter: str, user: str, *, permission: bool, clue_count: int) -> None:
    created = await runtime.adapters.dispatch(adapter, _ctx(adapter, user, f"{user}:create"), "开始修仙")
    assert created.code == "PLAYER_CREATED"
    flags = ["access.demon_abyss_gate"] if permission else []
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE players SET realm_key='foundation', realm_layer=1, location_key='demon.abyss_gate', "
            "intro_json=?, inventory_json=?, stamina=41, spirit_stones=73, pollution=9 "
            "WHERE platform=? AND platform_user_id=?",
            (json.dumps({"flags": flags}), json.dumps({CLUE: clue_count} if clue_count else {}), adapter, user),
        )


@pytest.mark.parametrize("adapter", ["qq.official", "onebot.v11"])
def test_demon_abyss_echo_manor_is_isolated_and_resumable(adapter: str) -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            user = f"abyss-echo-manor-{adapter}"
            await _player(runtime, adapter, user, permission=False, clue_count=1)
            denied_permission = await runtime.adapters.dispatch(
                adapter, _ctx(adapter, user, "denied:permission"), "进入残响遗府"
            )
            assert denied_permission.code == "LEGACY_MANOR_REQUIREMENT_MISSING"

            with sqlite3.connect(runtime.settings.database_path) as connection:
                player_id = connection.execute(
                    "SELECT id FROM players WHERE platform=? AND platform_user_id=?", (adapter, user)
                ).fetchone()[0]
                assert connection.execute(
                    "SELECT COUNT(*) FROM legacy_manor_runs WHERE player_id=?", (player_id,)
                ).fetchone()[0] == 0
                connection.execute(
                    "UPDATE players SET intro_json=?, inventory_json='{}' WHERE id=?",
                    (json.dumps({"flags": ["access.demon_abyss_gate"]}), player_id),
                )
            denied_clue = await runtime.adapters.dispatch(
                adapter, _ctx(adapter, user, "denied:clue"), "进入残响遗府"
            )
            assert denied_clue.code == "LEGACY_MANOR_REQUIREMENT_MISSING"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute("UPDATE players SET inventory_json=? WHERE id=?", (json.dumps({CLUE: 1}), player_id))

            entered = await runtime.adapters.dispatch(adapter, _ctx(adapter, user, "entry"), "进入残响遗府")
            replay = await runtime.adapters.dispatch(adapter, _ctx(adapter, user, "entry"), "进入残响遗府")
            assert entered.code == "LEGACY_MANOR_ENTERED"
            assert replay.data["idempotent_replay"] is True
            skipped = await runtime.adapters.dispatch(
                adapter, _ctx(adapter, user, "skip"), f"选择残响遗府节点 {NODES[1]}"
            )
            assert skipped.code == "LEGACY_MANOR_NODE_FORBIDDEN"
            first = await runtime.adapters.dispatch(
                adapter, _ctx(adapter, user, "route:0"), f"选择残响遗府节点 {NODES[0]}"
            )
            assert first.ok
            conflict = await runtime.adapters.dispatch(
                adapter, _ctx(adapter, user, "route:0"), f"选择残响遗府节点 {NODES[1]}"
            )
            assert conflict.code == "OPERATION_CONFLICT"

            other_adapter = "onebot.v11" if adapter == "qq.official" else "qq.official"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE players SET platform=? WHERE platform=? AND platform_user_id=?",
                    (other_adapter, adapter, user),
                )
            await runtime.close()

            runtime = create_runtime(data_dir=data_dir)
            status = await runtime.adapters.dispatch(
                other_adapter, _ctx(other_adapter, user, "handoff:status"), "残响遗府状态"
            )
            assert status.ok and status.data["current_node"] == "sealed_resonance"
            for index in (1, 2):
                selected = await runtime.adapters.dispatch(
                    other_adapter,
                    _ctx(other_adapter, user, f"route:{index}"),
                    f"选择残响遗府节点 {NODES[index]}",
                )
                assert selected.ok
            settled = await runtime.adapters.dispatch(
                other_adapter, _ctx(other_adapter, user, "settle"), "结算残响遗府"
            )
            assert settled.code == "LEGACY_MANOR_SETTLED"
            assert settled.data["story_flag_written"] is True
            repeat = await runtime.adapters.dispatch(
                other_adapter, _ctx(other_adapter, user, "entry:again"), "进入残响遗府"
            )
            assert repeat.code == "LEGACY_MANOR_ALREADY_CLEARED"

            with sqlite3.connect(runtime.settings.database_path) as connection:
                flags, inventory, stamina, stones, pollution, reputation, instance_key = connection.execute(
                    "SELECT p.intro_json, p.inventory_json, p.stamina, p.spirit_stones, p.pollution, "
                    "p.faction_reputation_json, r.instance_key FROM players p JOIN legacy_manor_runs r "
                    "ON r.player_id=p.id WHERE p.id=?",
                    (player_id,),
                ).fetchone()
            assert json.loads(flags)["flags"].count(STORY) == 1
            assert json.loads(inventory) == {CLUE: 1}
            assert (stamina, stones, pollution, json.loads(reputation)) == (41, 73, 9, {})
            assert instance_key == "instance.legacy.demon_abyss_echo"
            await runtime.close()

    asyncio.run(run())


def test_legacy_manors_share_one_active_action_lock() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            user = "legacy-manors-shared-lock"
            await _player(runtime, "qq.official", user, permission=True, clue_count=1)
            entered = await runtime.adapters.dispatch(
                "qq.official", _ctx("qq.official", user, "entry:echo"), "进入残响遗府"
            )
            assert entered.ok
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE players SET realm_key='nascent_soul', realm_layer=1, location_key='demon.fallen_ruins', "
                    "intro_json=?, inventory_json=? WHERE platform_user_id=?",
                    (
                        json.dumps({"flags": ["access.demon.fallen_ruins"]}),
                        json.dumps({CLUE: 1, "item.clue.demon_contract": 1}),
                        user,
                    ),
                )
            competing = await runtime.adapters.dispatch(
                "qq.official", _ctx("qq.official", user, "entry:reliquary"), "进入遗府"
            )
            assert competing.code == "LEGACY_MANOR_BUSY"
            await runtime.close()

    asyncio.run(run())


def test_legacy_manor_schema_migration_tags_existing_rows_as_first_manor() -> None:
    with sqlite3.connect(":memory:") as connection:
        connection.execute("CREATE TABLE players(id INTEGER PRIMARY KEY)")
        connection.execute("INSERT INTO players(id) VALUES (1)")
        connection.executescript(
            "CREATE TABLE legacy_manor_runs ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL UNIQUE, "
            "player_id INTEGER NOT NULL REFERENCES players(id), "
            "status TEXT NOT NULL CHECK (status IN ('routing','cleared','expired','settled','system_aborted')), "
            "node_index INTEGER NOT NULL CHECK (node_index >= 0), starts_at TEXT NOT NULL, expires_at TEXT NOT NULL, "
            "snapshot_json TEXT NOT NULL, result_json TEXT NOT NULL DEFAULT '{}', "
            "entry_operation_id TEXT NOT NULL UNIQUE, content_version TEXT NOT NULL, rule_version TEXT NOT NULL, "
            "created_at TEXT NOT NULL, updated_at TEXT NOT NULL);"
        )
        connection.execute(
            "INSERT INTO legacy_manor_runs(run_id,player_id,status,node_index,starts_at,expires_at,snapshot_json,"
            "entry_operation_id,content_version,rule_version,created_at,updated_at) "
            "VALUES ('old-run',1,'settled',3,'2026-01-01','2026-01-01','{}','old-op','','',"
            "'2026-01-01','2026-01-01')"
        )
        ensure_legacy_manor_schema(connection)
        row = connection.execute("SELECT instance_key FROM legacy_manor_runs WHERE run_id='old-run'").fetchone()
        assert row[0] == "instance.legacy.demon_reliquary"


def test_demon_abyss_echo_manor_expiry_and_system_abort_allow_retry() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 28, 12, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            user = "abyss-echo-manor-recovery"
            await _player(runtime, "onebot.v11", user, permission=True, clue_count=1)
            first = await runtime.adapters.dispatch(
                "onebot.v11", _ctx("onebot.v11", user, "expiry:entry"), "进入残响遗府"
            )
            assert first.ok
            clock.advance(hours=1, seconds=1)
            status = await runtime.adapters.dispatch(
                "onebot.v11", _ctx("onebot.v11", user, "expiry:status"), "残响遗府状态"
            )
            assert status.ok and status.data["status"] == "expired"
            expired = await runtime.adapters.dispatch(
                "onebot.v11", _ctx("onebot.v11", user, "expiry:settle"), "结算残响遗府"
            )
            assert expired.data["outcome"] == "expired" and not expired.data["story_flag_written"]

            aborted_run = await runtime.adapters.dispatch(
                "onebot.v11", _ctx("onebot.v11", user, "abort:entry"), "进入残响遗府"
            )
            aborted = await runtime.repository.compensate_legacy_manor_system_failure(
                run_id=aborted_run.data["run_id"],
                operation_id="abort:compensate",
                instance_key="instance.legacy.demon_abyss_echo",
            )
            replay = await runtime.repository.compensate_legacy_manor_system_failure(
                run_id=aborted_run.data["run_id"],
                operation_id="abort:compensate",
                instance_key="instance.legacy.demon_abyss_echo",
            )
            assert aborted.outcome == "system_aborted" and replay.already_completed
            retry = await runtime.adapters.dispatch(
                "onebot.v11", _ctx("onebot.v11", user, "final:entry"), "进入残响遗府"
            )
            assert retry.ok
            for index, node in enumerate(NODES):
                selected = await runtime.adapters.dispatch(
                    "onebot.v11",
                    _ctx("onebot.v11", user, f"final:node:{index}"),
                    f"选择残响遗府节点 {node}",
                )
                assert selected.ok
            won = await runtime.adapters.dispatch(
                "onebot.v11", _ctx("onebot.v11", user, "final:settle"), "结算残响遗府"
            )
            assert won.data["story_flag_written"] is True
            await runtime.close()

    asyncio.run(run())
