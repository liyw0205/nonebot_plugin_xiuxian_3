from __future__ import annotations

import asyncio
import json
import sqlite3
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime


def _context(adapter: str, user: str, request: str, operation: str = "") -> CommandContext:
    return CommandContext(
        adapter=adapter,
        user_id=user,
        request_id=request,
        operation_id=operation,
        can_write_assets=True,
    )


async def _prepare(runtime, adapter: str, user: str, *, pollution: int, pills: int) -> None:
    created = await runtime.adapters.dispatch(adapter, _context(adapter, user, f"create-{user}"), "开始修仙")
    assert created.ok
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            """
            UPDATE players SET stage='cultivator', realm_key='nascent_soul', realm_layer=1,
                location_key='demon.fallen_ruins', path_key='spell', stamina=100, stamina_max=100,
                energy=30, energy_max=30, soul_power=100, soul_power_max=100,
                pollution=?, qualification_json=?, intro_json=?, inventory_json=?
            WHERE platform=? AND platform_user_id=?
            """,
            (
                pollution,
                json.dumps({"body": 100000, "agility": 100000}),
                json.dumps({"flags": ["access.demon.fallen_ruins"]}),
                json.dumps({"item.pill.soul_restore": pills}),
                adapter,
                user,
            ),
        )


def test_pollution_purification_is_idempotent_and_isolated_on_qq_and_onebot() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            for adapter in ("qq.official", "onebot.v11"):
                user = f"purify-{adapter}"
                await _prepare(runtime, adapter, user, pollution=80, pills=2)

            for adapter in ("qq.official", "onebot.v11"):
                user = f"purify-{adapter}"
                blocked = await runtime.adapters.dispatch(
                    adapter, _context(adapter, user, f"blocked-{adapter}"), "开始探索 魔界堕落遗迹探索"
                )
                assert blocked.code == "POLLUTION_TOO_HIGH"
                purified = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, f"purify-{adapter}", f"purify-{adapter}"),
                    "净化污染",
                )
                assert purified.code == "POLLUTION_PURIFIED"
                assert purified.data["pollution_before"] == 80
                assert purified.data["pollution_after"] == 60
                assert purified.data["item_quantity"] == 1
                replay = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, f"purify-replay-{adapter}", f"purify-{adapter}"),
                    "净化污染",
                )
                assert replay.code == "POLLUTION_PURIFIED"
                assert replay.data["idempotent_replay"] is True
                started = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, f"explore-{adapter}"),
                    "开始探索 魔界堕落遗迹探索",
                )
                assert started.code == "EXPLORATION_STARTED"

            with sqlite3.connect(runtime.settings.database_path) as connection:
                rows = connection.execute(
                    "SELECT platform, pollution, inventory_json FROM players "
                    "WHERE platform_user_id LIKE 'purify-%' ORDER BY platform"
                ).fetchall()
            assert [(row[0], row[1], json.loads(row[2])["item.pill.soul_restore"]) for row in rows] == [
                ("onebot.v11", 70, 1),
                ("qq.official", 70, 1),
            ]
            await runtime.close()

    asyncio.run(run())


def test_pollution_purification_rejects_missing_material_without_writes() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            adapter, user = "qq.official", "purify-missing"
            await _prepare(runtime, adapter, user, pollution=80, pills=0)
            result = await runtime.adapters.dispatch(
                adapter, _context(adapter, user, "purify-missing", "purify-missing"), "净化污染"
            )
            assert result.code == "MATERIAL_INSUFFICIENT"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                pollution, inventory = connection.execute(
                    "SELECT pollution, inventory_json FROM players WHERE platform=? AND platform_user_id=?",
                    (adapter, user),
                ).fetchone()
            assert pollution == 80
            assert json.loads(inventory) == {"item.pill.soul_restore": 0}
            await runtime.close()

    asyncio.run(run())


def test_pollution_purification_rejects_pending_heart_demon_without_writes() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            adapter, user = "onebot.v11", "purify-heart-demon"
            await _prepare(runtime, adapter, user, pollution=60, pills=1)
            now = "2026-09-27T12:00:00+00:00"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                player_id = connection.execute(
                    "SELECT id FROM players WHERE platform=? AND platform_user_id=?",
                    (adapter, user),
                ).fetchone()[0]
                connection.execute(
                    """
                    INSERT INTO breakthrough_sessions(
                        session_id, player_id, operation_id, target_realm, status,
                        starts_at, ends_at, snapshot_json, result_json, created_at, updated_at
                    ) VALUES (?, ?, ?, 'nascent_soul', 'failed', ?, ?, '{}', '{}', ?, ?)
                    """,
                    ("fixture-breakthrough", player_id, "fixture-breakthrough-op", now, now, now, now),
                )
                breakthrough_id = connection.execute(
                    "SELECT id FROM breakthrough_sessions WHERE session_id=?",
                    ("fixture-breakthrough",),
                ).fetchone()[0]
                connection.execute(
                    """
                    INSERT INTO heart_demon_sessions(
                        session_id, player_id, breakthrough_session_id, operation_id, status,
                        expires_at, snapshot_json, result_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, 'pending', ?, '{}', '{}', ?, ?)
                    """,
                    (
                        "fixture-heart-demon",
                        player_id,
                        breakthrough_id,
                        "fixture-heart-demon-op",
                        "2099-01-01T00:00:00+00:00",
                        now,
                        now,
                    ),
                )

            result = await runtime.adapters.dispatch(
                adapter,
                _context(adapter, user, "purify-heart-demon", "purify-heart-demon"),
                "净化污染",
            )
            assert result.code == "HEART_DEMON_PENDING"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                pollution, inventory = connection.execute(
                    "SELECT pollution, inventory_json FROM players WHERE platform=? AND platform_user_id=?",
                    (adapter, user),
                ).fetchone()
                operation = connection.execute(
                    "SELECT 1 FROM operations WHERE operation_id=?",
                    ("purify-heart-demon",),
                ).fetchone()
            assert pollution == 60
            assert json.loads(inventory) == {"item.pill.soul_restore": 1}
            assert operation is None
            await runtime.close()

    asyncio.run(run())
