from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime


class MutableClock:
    def __init__(self, value: datetime):
        self.value = value

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **kwargs: int) -> None:
        self.value += timedelta(**kwargs)


def _context(adapter: str, user: str, request_id: str, operation_id: str = "") -> CommandContext:
    return CommandContext(
        adapter=adapter,
        user_id=user,
        request_id=request_id,
        operation_id=operation_id,
        can_write_assets=True,
    )


def _prepare_player(runtime, adapter: str, user: str, sect_id: str) -> None:
    now = runtime.repository._now().isoformat()
    with sqlite3.connect(runtime.settings.database_path) as connection:
        player_id = connection.execute(
            "SELECT id FROM players WHERE platform=? AND platform_user_id=?",
            (adapter, user),
        ).fetchone()[0]
        connection.execute(
            """
            UPDATE players
            SET stage='cultivator', realm_key='soul_transformation', realm_layer=1,
                domain_key='domain.fire', location_key='xuantian.domain_front', stamina=100,
                faction_reputation_json='{"demon":300,"beast":300}'
            WHERE id=?
            """,
            (player_id,),
        )
        connection.execute(
            """
            INSERT INTO sects(
                sect_id,name,name_key,motto,leader_id,status,level,max_members,
                warehouse_capacity,construction,spirit_stones,sect_merit,warehouse_json,
                created_at,updated_at
            ) VALUES (?, ?, ?, '', ?, 'active', 4, 20, 100, 0, 0, 0, '{}', ?, ?)
            """,
            (sect_id, "领域宗门", sect_id, player_id, now, now),
        )
        connection.execute(
            """
            INSERT INTO sect_members(
                sect_id,player_id,role,status,contribution,joined_at,last_action_at,created_at,updated_at
            ) VALUES (?, ?, 'leader', 'active', 0, ?, ?, ?, ?)
            """,
            (sect_id, player_id, now, now, now, now),
        )


def test_domain_frontier_mainline_runs_all_lanes_on_both_adapters() -> None:
    async def run() -> None:
        for adapter in ("qq.official", "onebot.v11"):
            clock = MutableClock(datetime(2026, 9, 25, 12, 5, tzinfo=timezone.utc))
            with TemporaryDirectory() as data_dir:
                runtime = create_runtime(data_dir=Path(data_dir), clock=clock)
                user = f"frontier-mainline-{adapter}"
                dispatch = lambda request, command, operation="": runtime.adapters.dispatch(
                    adapter, _context(adapter, user, request, operation), command
                )

                assert (await dispatch("create", "开始修仙")).ok
                _prepare_player(runtime, adapter, user, f"sect-{adapter}")
                assert (await dispatch("join", "加入领域前线", "domain-join")).ok
                joined_status = await dispatch("joined-status", "领域前线")
                round_id = str(joined_status.data["round_id"])
                assert (await dispatch("battle", "开始领域战", "domain-battle")).ok
                assert (await dispatch("contribute", "贡献领域前线 战斗", "domain-contribution")).ok
                clock.advance(minutes=31)
                assert (await dispatch("event-claim", f"领取领域前线奖励 {round_id}", "domain-claim")).ok

                first = await dispatch("same-operation", "开始领域前线主线 守界一关", "same-mainline")
                assert first.code == "MAINLINE_STARTED"
                replay = await dispatch("same-operation", "开始领域前线主线 守界一关", "same-mainline")
                assert replay.data["idempotent_replay"] is True
                conflict = await dispatch("same-operation", "开始领域前线主线 净渊一关", "same-mainline")
                assert conflict.code == "OPERATION_CONFLICT"

                for lane, final_alias in (("守界", "守界终关"), ("净渊", "净渊终关"), ("护祖", "护祖终关")):
                    aliases = [f"{lane}{name}关" for name in ("一", "二", "三", "四", "五")] + [final_alias]
                    for index, alias in enumerate(aliases, start=1):
                        if lane == "守界" and index == 1:
                            claim = await dispatch("claim-guard-1", "领取领域前线主线奖励 守界一关", "claim-guard-1")
                        else:
                            started = await dispatch(f"start-{lane}-{index}", f"开始领域前线主线 {alias}", f"start-{lane}-{index}")
                            assert started.code == "MAINLINE_STARTED"
                            claim = await dispatch(f"claim-{lane}-{index}", f"领取领域前线主线奖励 {alias}", f"claim-{lane}-{index}")
                        assert claim.code == "MAINLINE_REWARD_CLAIMED"
                    replay = await dispatch(f"replay-{lane}", f"领取领域前线主线奖励 {final_alias}", f"claim-{lane}-6")
                    assert replay.data["idempotent_replay"] is True

                with sqlite3.connect(runtime.settings.database_path) as connection:
                    rows = connection.execute(
                        "SELECT story_key, COUNT(*) FROM mainline_runs WHERE player_id=(SELECT id FROM players WHERE platform=? AND platform_user_id=?) GROUP BY story_key",
                        (adapter, user),
                    ).fetchall()
                    assert rows == [("story.mainline.domain_frontier", 18)]
                    rewards = connection.execute(
                        "SELECT inventory_json, world_merit FROM players WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    ).fetchone()
                    inventory = json.loads(rewards[0])
                    assert rewards[1] == 100
                    assert inventory.get("item.domain_core_fragment") == 5
                    permissions = {
                        row[0]
                        for row in connection.execute(
                            "SELECT event_key FROM activity_events WHERE player_id=(SELECT id FROM players WHERE platform=? AND platform_user_id=?) AND event_key LIKE 'access.project.%'",
                            (adapter, user),
                        ).fetchall()
                    }
                    assert permissions == {
                        "access.project.domain_refuge",
                        "access.project.abyss_purification",
                        "access.project.ancestral_habitat",
                    }
                projects = await dispatch("projects", "公共项目")
                assert projects.code == "PROJECT_LIST"
                assert {item["project_key"] for item in projects.data["projects"]} >= {
                    "project.domain_refuge",
                    "project.abyss_purification",
                    "project.ancestral_habitat",
                }
                await runtime.close()

    asyncio.run(run())
