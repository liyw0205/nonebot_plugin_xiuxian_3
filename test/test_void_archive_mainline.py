from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime


def _context(adapter: str, user: str, request_id: str, operation_id: str = "") -> CommandContext:
    return CommandContext(
        adapter=adapter,
        user_id=user,
        request_id=request_id,
        operation_id=operation_id,
        can_write_assets=True,
    )


def _seed_archive_evidence(runtime, adapter: str, user: str) -> None:
    now = runtime.repository._now()
    now_text = now.isoformat()
    with sqlite3.connect(runtime.settings.database_path) as connection:
        player_id = connection.execute(
            "SELECT id FROM players WHERE platform=? AND platform_user_id=?",
            (adapter, user),
        ).fetchone()[0]
        connection.execute(
            "UPDATE players SET stage='cultivator', realm_key='void_refining', realm_layer=1, "
            "location_key='void.archive_ruins', intro_json=? WHERE id=?",
            (json.dumps({"flags": ["story.mainline.void_archive.time_fort"]}), player_id),
        )
        connection.execute(
            "INSERT INTO void_route_sessions(session_id,player_id,operation_id,route_key,status,"
            "starts_at,ends_at,anchor_cost,stamina_cost,snapshot_json,result_json,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                f"archive-route-{adapter}",
                player_id,
                f"archive-route-operation-{adapter}",
                "void.archive_ruins",
                "settled",
                now_text,
                now_text,
                1,
                0,
                "{}",
                '{"outcome":"won"}',
                now_text,
                now_text,
            ),
        )
        connection.execute(
            "INSERT INTO battle_sessions(battle_id,player_id,start_operation_id,battle_type,enemy_key,"
            "location_key,status,reward_status,round_no,action_sequence,starts_at,turn_deadline,"
            "snapshot_json,state_json,result_json,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                f"archive-battle-{adapter}",
                player_id,
                f"archive-battle-operation-{adapter}",
                "pve.archive_keeper",
                "enemy.archive_keeper",
                "void.archive_ruins",
                "settled",
                "none",
                20,
                20,
                now_text,
                now_text,
                "{}",
                "{}",
                '{"outcome":"won"}',
                now_text,
                now_text,
            ),
        )
        connection.execute(
            "INSERT INTO void_archive_runs(run_id,player_id,week_id,route_session_id,battle_id,"
            "operation_id,outcome,reward_json,snapshot_json,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                f"archive-run-{adapter}",
                player_id,
                now.strftime("%Y-%m-%d"),
                f"archive-route-{adapter}",
                f"archive-battle-{adapter}",
                f"archive-run-operation-{adapter}",
                "won",
                "{}",
                "{}",
                now_text,
            ),
        )
        connection.execute(
            "INSERT INTO void_archive_unlocks(player_id,week_id,event_key,starts_at,ends_at,operation_id,created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (
                player_id,
                now.strftime("%Y-%m-%d"),
                "event.archive_unlock",
                now_text,
                (now + timedelta(days=7)).isoformat(),
                f"archive-unlock-operation-{adapter}",
                now_text,
            ),
        )
        party_id = f"time-fort-party-{adapter}"
        connection.execute(
            "INSERT INTO parties(party_id,party_type,status,leader_id,location_key,confirmation_deadline,"
            "distribution_key,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                party_id,
                "secret_realm_time_fort",
                "ready",
                player_id,
                "void.archive_ruins",
                now_text,
                "contribution",
                now_text,
                now_text,
            ),
        )
        connection.execute(
            "INSERT INTO time_fort_runs(run_id,party_id,status,node_index,battle_id,quota_key,starts_at,"
            "expires_at,stamina_cost,snapshot_json,result_json,entry_operation_id,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                f"time-fort-run-{adapter}",
                party_id,
                "settled",
                6,
                None,
                now.strftime("%Y-%m-%d"),
                now_text,
                now_text,
                40,
                "{}",
                '{"outcome":"won"}',
                f"time-fort-entry-{adapter}",
                now_text,
                now_text,
            ),
        )
        connection.execute(
            "INSERT INTO time_fort_members(run_id,player_id,quota_key,member_order,first_clear,status,"
            "reward_json,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                f"time-fort-run-{adapter}",
                player_id,
                now.strftime("%Y-%m-%d"),
                0,
                1,
                "settled",
                "{}",
                now_text,
                now_text,
            ),
        )


def test_void_archive_mainline_uses_server_evidence_on_both_adapters() -> None:
    async def run() -> None:
        for adapter in ("qq.official", "onebot.v11"):
            with TemporaryDirectory() as data_dir:
                clock_value = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)
                runtime = create_runtime(data_dir=Path(data_dir), clock=lambda: clock_value)
                user = f"void-archive-mainline-{adapter}"

                async def dispatch(request_id: str, command: str, operation_id: str = ""):
                    return await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, user, request_id, operation_id),
                        command,
                    )

                assert (await dispatch("create", "开始修仙")).ok
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    player_id = connection.execute(
                        "SELECT id FROM players WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    ).fetchone()[0]
                    connection.execute(
                        "UPDATE players SET stage='cultivator', realm_key='void_refining', realm_layer=1, "
                        "intro_json=? WHERE id=?",
                        (json.dumps({"flags": ["story.mainline.void_archive.time_fort"]}), player_id),
                    )

                # A dungeon flag is only one piece of evidence; it cannot open the story by itself.
                blocked = await dispatch("blocked", "开始虚空档案主线 记录者一关", "blocked")
                assert blocked.code == "MAINLINE_REQUIREMENT_MISSING"

                _seed_archive_evidence(runtime, adapter, user)
                started = await dispatch("start-record-1", "开始虚空档案主线 记录者一关", "same-mainline")
                assert started.code == "MAINLINE_STARTED"
                replay = await dispatch("start-record-1-replay", "开始虚空档案主线 记录者一关", "same-mainline")
                assert replay.code == "MAINLINE_STARTED"
                assert replay.data["idempotent_replay"] is True
                conflict = await dispatch("start-conflict", "开始虚空档案主线 护航者一关", "same-mainline")
                assert conflict.code == "OPERATION_CONFLICT"

                await runtime.close()
                runtime = create_runtime(data_dir=Path(data_dir), clock=lambda: clock_value)

                async def dispatch_after_restart(request_id: str, command: str, operation_id: str = ""):
                    return await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, user, request_id, operation_id),
                        command,
                    )

                assert (
                    await dispatch_after_restart(
                        "claim-record-1",
                        "领取虚空档案主线奖励 记录者一关",
                        "claim-record-1",
                    )
                ).code == "MAINLINE_REWARD_CLAIMED"

                for lane in ("记录者", "护航者", "归乡者"):
                    aliases = [f"{lane}{numeral}关" for numeral in ("一", "二", "三", "四", "五", "六", "七")] + [f"{lane}终关"]
                    for index, alias in enumerate(aliases, start=1):
                        if lane == "记录者" and index == 1:
                            continue
                        started = await dispatch_after_restart(
                            f"start-{lane}-{index}",
                            f"开始虚空档案主线 {alias}",
                            f"start-{lane}-{index}",
                        )
                        assert started.code == "MAINLINE_STARTED", started
                        claimed = await dispatch_after_restart(
                            f"claim-{lane}-{index}",
                            f"领取虚空档案主线奖励 {alias}",
                            f"claim-{lane}-{index}",
                        )
                        assert claimed.code == "MAINLINE_REWARD_CLAIMED", claimed

                with sqlite3.connect(runtime.settings.database_path) as connection:
                    rows = connection.execute(
                        "SELECT story_key, COUNT(*) FROM mainline_runs WHERE player_id=? GROUP BY story_key",
                        (player_id,),
                    ).fetchall()
                    assert rows == [("story.mainline.void_archive", 24)]
                    rewards = connection.execute(
                        "SELECT spirit_stones, inventory_json FROM players WHERE id=?",
                        (player_id,),
                    ).fetchone()
                    assert rewards[0] == 60
                    assert "void_crystal" not in rewards[1]
                    assert "void_power" not in rewards[1]
                await runtime.close()

    asyncio.run(run())
