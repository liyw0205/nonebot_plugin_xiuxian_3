from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.exploration.rules import battle_roll_bp


def _context(adapter: str, user: str, request: str, operation: str = "") -> CommandContext:
    return CommandContext(
        adapter=adapter,
        user_id=user,
        request_id=request,
        operation_id=operation,
        can_write_assets=True,
    )


def _prepare_foundation_outskirts(runtime, adapter: str, user: str) -> None:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            """
            UPDATE players
            SET stage='cultivator', realm_key='foundation', realm_layer=1,
                location_key='xuantian.outskirts', stamina=60, stamina_max=60,
                intro_json='{}'
            WHERE platform=? AND platform_user_id=?
            """,
            (adapter, user),
        )


def _expire_exploration(runtime, exploration_id: str) -> None:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE exploration_sessions SET ends_at=? WHERE exploration_id=?",
            ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(), exploration_id),
        )


def test_beast_intro_uses_owned_evidence_and_unlocks_hills_on_both_adapters() -> None:
    async def run() -> None:
        for adapter in ("qq.official", "onebot.v11"):
            with TemporaryDirectory() as data_dir:
                runtime = create_runtime(data_dir=Path(data_dir) / adapter)
                user = f"beast-intro-{adapter}"
                await runtime.adapters.dispatch(adapter, _context(adapter, user, "create"), "开始修仙")
                await runtime.adapters.dispatch(adapter, _context(adapter, user, "seeking"), "寻仙问道")
                _prepare_foundation_outskirts(runtime, adapter, user)

                poor_user = f"beast-intro-no-stones-{adapter}"
                await runtime.adapters.dispatch(adapter, _context(adapter, poor_user, "poor-create"), "开始修仙")
                _prepare_foundation_outskirts(runtime, adapter, poor_user)
                poor_operation = next(
                    f"beast-no-stones-{index}"
                    for index in range(1000)
                    if battle_roll_bp(f"beast-no-stones-{index}:battle") >= 1000
                )
                poor_started = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, poor_user, "poor-explore-start", poor_operation),
                    "开始探索 近郊采集",
                )
                assert poor_started.code == "EXPLORATION_STARTED"
                _expire_exploration(runtime, poor_started.data["exploration_id"])
                assert (
                    await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, poor_user, "poor-explore-settle", "poor-explore-settle"),
                        "结算探索",
                    )
                ).code == "EXPLORATION_SETTLED"
                assert (
                    await runtime.adapters.dispatch(
                        adapter, _context(adapter, poor_user, "poor-history", "poor-history"), "阅读妖界史"
                    )
                ).code == "BEAST_HISTORY_RECORDED"
                poor_completion = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, poor_user, "poor-intro", "poor-intro"),
                    "完成妖界引导",
                )
                assert poor_completion.code == "BEAST_INTRO_STONES_INSUFFICIENT"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    poor_state = connection.execute(
                        "SELECT spirit_stones, faction_reputation_json, intro_json FROM players "
                        "WHERE platform=? AND platform_user_id=?",
                        (adapter, poor_user),
                    ).fetchone()
                assert poor_state[0] == 0
                assert json.loads(poor_state[1]) == {}
                assert json.loads(poor_state[2]).get("flags", []) == []

                operation = next(
                    f"beast-outskirts-{index}"
                    for index in range(1000)
                    if battle_roll_bp(f"beast-outskirts-{index}:battle") >= 1000
                )
                started = await runtime.adapters.dispatch(
                    adapter, _context(adapter, user, "explore-start", operation), "开始探索 近郊采集"
                )
                assert started.code == "EXPLORATION_STARTED"
                active_attempt = await runtime.adapters.dispatch(
                    adapter, _context(adapter, user, "intro-active", "intro-active"), "完成妖界引导"
                )
                assert active_attempt.code == "BEAST_INTRO_REQUIREMENT_MISSING"

                _expire_exploration(runtime, started.data["exploration_id"])
                settled = await runtime.adapters.dispatch(
                    adapter, _context(adapter, user, "explore-settle", "explore-settle"), "结算探索"
                )
                assert settled.code == "EXPLORATION_SETTLED"

                unread_attempt = await runtime.adapters.dispatch(
                    adapter, _context(adapter, user, "intro-unread", "intro-unread"), "完成妖界引导"
                )
                assert unread_attempt.code == "BEAST_INTRO_REQUIREMENT_MISSING"
                history = await runtime.adapters.dispatch(
                    adapter, _context(adapter, user, "history", "history"), "阅读妖界史"
                )
                assert history.code == "BEAST_HISTORY_RECORDED"
                history_replay = await runtime.adapters.dispatch(
                    adapter, _context(adapter, user, "history-replay", "history"), "阅读妖界史"
                )
                assert history_replay.data["idempotent_replay"] is True

                completed = await runtime.adapters.dispatch(
                    adapter, _context(adapter, user, "intro", "intro"), "完成妖界引导"
                )
                assert completed.code == "BEAST_INTRO_COMPLETED"
                replay = await runtime.adapters.dispatch(
                    adapter, _context(adapter, user, "intro-replay", "intro"), "完成妖界引导"
                )
                assert replay.data["idempotent_replay"] is True
                duplicate = await runtime.adapters.dispatch(
                    adapter, _context(adapter, user, "intro-duplicate", "intro-duplicate"), "完成妖界引导"
                )
                assert duplicate.code == "BEAST_INTRO_ALREADY_COMPLETED"

                with sqlite3.connect(runtime.settings.database_path) as connection:
                    player = connection.execute(
                        "SELECT spirit_stones, faction_reputation_json, intro_json FROM players "
                        "WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    ).fetchone()
                    events = connection.execute(
                        "SELECT component_key, source_operation_id FROM quest_events "
                        "WHERE player_id=(SELECT id FROM players WHERE platform=? AND platform_user_id=?) "
                        "AND quest_key='quest.beast_intro' ORDER BY id",
                        (adapter, user),
                    ).fetchall()
                    progress = connection.execute(
                        "SELECT status, progress_json, snapshot_json FROM quest_progress "
                        "WHERE player_id=(SELECT id FROM players WHERE platform=? AND platform_user_id=?) "
                        "AND quest_key='quest.beast_intro'",
                        (adapter, user),
                    ).fetchone()
                assert player[0] == 0
                assert json.loads(player[1]) == {"beast": 20}
                assert set(json.loads(player[2])["flags"]) == {
                    "quest.beast_intro",
                    "access.beast_ten_thousand_hills",
                }
                assert {event[0] for event in events} == {
                    "outskirts_beast_observation",
                    "submission",
                    "beast_history_read",
                }
                assert len(events) == 3
                assert progress[0] == "completed"
                assert json.loads(progress[1]) == {
                    "beast_history_read": 1,
                    "outskirts_beast_observation": 1,
                    "submission": 1,
                }
                snapshot = json.loads(progress[2])
                assert snapshot["exploration_id"] == started.data["exploration_id"]
                assert snapshot["exploration_operation_id"] == "explore-settle"
                assert snapshot["exploration_start_operation_id"] == operation

                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE players SET realm_key='nascent_soul', location_key='xuantian.floating_boat', "
                        "stamina=60, stamina_max=60 WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    )
                preview = await runtime.adapters.dispatch(
                    adapter, _context(adapter, user, "preview"), "移动预览 万兽山"
                )
                assert preview.code == "TRAVEL_PREVIEW"
                assert preview.data["ready"] is True
                travel = await runtime.adapters.dispatch(
                    adapter, _context(adapter, user, "travel", "beast-travel"), "前往 万兽山"
                )
                assert travel.code == "TRAVEL_STARTED"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    travel_snapshot = json.loads(
                        connection.execute(
                            "SELECT snapshot_json FROM travel_sessions WHERE session_id=?",
                            (travel.data["session_id"],),
                        ).fetchone()[0]
                    )
                assert travel_snapshot["beast_hills_permission"] == "intro_flag"
                assert travel_snapshot["faction_reputation"] == 20
                await runtime.close()

    asyncio.run(run())
