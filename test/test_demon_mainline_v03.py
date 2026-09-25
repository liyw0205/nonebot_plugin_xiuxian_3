from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
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


async def _player(runtime, adapter: str, user: str, *, flag: bool = True) -> None:
    created = await runtime.adapters.dispatch(
        adapter, _context(adapter, user, f"create-{user}"), "开始修仙"
    )
    assert created.ok
    flags = ["access.demon.fallen_ruins"] if flag else []
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            """
            UPDATE players
            SET stage='cultivator', realm_key='nascent_soul', realm_layer=1,
                location_key='demon.fallen_ruins', stamina=100, stamina_max=100,
                energy=100, energy_max=100, max_hp=100000, initiative=100000,
                qualification_json=?, faction_reputation_json=?, intro_json=?
            WHERE platform=? AND platform_user_id=?
            """,
            (
                json.dumps({"body": 100000, "agility": 100000}),
                json.dumps({"demon": 200}),
                json.dumps({"flags": flags}),
                adapter,
                user,
            ),
        )


def _expire(runtime, exploration_id: str) -> None:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE exploration_sessions SET ends_at=? WHERE exploration_id=?",
            ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(), exploration_id),
        )


def test_demon_mainline_requires_server_evidence_and_unlocks_both_adapters() -> None:
    async def run() -> None:
        for adapter in ("qq.official", "onebot.v11"):
            with TemporaryDirectory() as data_dir:
                runtime = create_runtime(data_dir=Path(data_dir) / adapter)
                user = f"demon-mainline-{adapter}"
                await _player(runtime, adapter, user)

                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE players SET faction_reputation_json=? WHERE platform=? AND platform_user_id=?",
                        (json.dumps({"demon": 199}), adapter, user),
                    )
                insufficient_reputation = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "claim-reputation", "demon-claim-reputation"),
                    "领取魔界主线",
                )
                assert insufficient_reputation.code == "QUEST_REQUIREMENT_MISSING"

                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE players SET faction_reputation_json=? WHERE platform=? AND platform_user_id=?",
                        (json.dumps({"demon": 200}), adapter, user),
                    )

                for index in range(2):
                    started = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, user, f"explore-start-{index}", f"demon-explore-{index}"),
                        "开始探索 魔界堕落遗迹探索",
                    )
                    assert started.code == "EXPLORATION_STARTED"
                    _expire(runtime, started.data["exploration_id"])
                    settled = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, user, f"explore-settle-{index}", f"demon-settle-{index}"),
                        "结算探索",
                    )
                    assert settled.code == "EXPLORATION_SETTLED"
                    assert settled.data["battle_outcome"] == "won"

                claim = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "claim", "demon-mainline-claim"),
                    "领取魔界主线",
                )
                assert claim.code == "QUEST_PERMIT_GRANTED"
                assert claim.data["quest_key"] == "quest.demon_main_1"
                assert claim.data["snapshot"]["exploration_target"] == 2

                replay = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "claim-replay", "demon-mainline-claim"),
                    "领取魔界主线",
                )
                assert replay.code == "QUEST_PERMIT_GRANTED"
                assert replay.data["idempotent_replay"] is True

                duplicate = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "claim-duplicate", "demon-mainline-claim-2"),
                    "领取魔界主线",
                )
                assert duplicate.code == "QUEST_ALREADY_COMPLETED"

                with sqlite3.connect(runtime.settings.database_path) as connection:
                    intro_text, progress, event_count = connection.execute(
                        """
                        SELECT p.intro_json, q.progress_json,
                               (SELECT COUNT(*) FROM quest_events WHERE player_id=p.id AND quest_key='quest.demon_main_1')
                        FROM players p
                        JOIN quest_progress q ON q.player_id=p.id AND q.quest_key='quest.demon_main_1'
                        WHERE p.platform=? AND p.platform_user_id=?
                        """,
                        (adapter, user),
                    ).fetchone()
                assert "access.demon.fallen_ruins" in json.loads(intro_text)["flags"]
                assert json.loads(progress)["explore.demon_abyss"] == 2
                assert event_count == 2
                await runtime.close()

    asyncio.run(run())


def test_demon_fallen_ruins_movement_requires_unlock_flag_without_spending_stamina() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=Path(data_dir))
            adapter, user = "qq.official", "demon-gate"
            await _player(runtime, adapter, user, flag=False)
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE players SET location_key='demon.abyss_gate', stamina=100 WHERE platform=? AND platform_user_id=?",
                    (adapter, user),
                )
            denied = await runtime.adapters.dispatch(
                adapter,
                _context(adapter, user, "travel-denied"),
                "前往 魔界堕落遗迹",
            )
            assert denied.code == "LOCATION_REQUIREMENT_MISSING"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                stamina = connection.execute(
                    "SELECT stamina FROM players WHERE platform=? AND platform_user_id=?",
                    (adapter, user),
                ).fetchone()[0]
            assert stamina == 100
            await runtime.close()

    asyncio.run(run())
