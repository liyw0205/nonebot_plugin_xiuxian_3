from __future__ import annotations

import asyncio
import json
import shutil
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from combat_fixtures import BALANCED_QUALIFICATION, equip_damage_weapon

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.exploration.rules import battle_roll_bp
from nonebot_plugin_xiuxian_3.xiuxian.rewards.rules import (
    reward_pool_map,
    reward_pool_uses_item_weight_bonus,
)

VOID_ROUTE = "explore.void_route"
ARCHIVE_RUINS = "explore.archive_ruins"
VOID_ROUTE_NAME = "虚空航道历练"
ARCHIVE_RUINS_NAME = "档案遗迹搜寻"

# (alias, objective kind, payload) for the whole 24-stage void archive arc.
# Travel payloads are the hop sequence: the void has no direct ruins -> portal edge.
STAGES = (
    ("记录者一关", "travel", ("虚空第一航道",)),
    ("记录者二关", "reward", (VOID_ROUTE, "item.archive_fragment.alpha")),
    ("记录者三关", "battle", VOID_ROUTE),
    ("记录者四关", "travel", ("虚空档案遗迹",)),
    ("记录者五关", "reward", (ARCHIVE_RUINS, "item.archive_fragment.beta")),
    ("记录者六关", "reward", (ARCHIVE_RUINS, "item.archive_fragment.gamma")),
    ("记录者七关", "reward", (ARCHIVE_RUINS, "item.void_archive")),
    ("记录者终关", "battle", ARCHIVE_RUINS),
    ("护航者一关", "travel", ("虚空第一航道",)),
    ("护航者二关", "reward", (VOID_ROUTE, "item.void_anchor")),
    ("护航者三关", "reward", (VOID_ROUTE, "item.void_crystal")),
    ("护航者四关", "battle", VOID_ROUTE),
    ("护航者五关", "travel", ("虚空档案遗迹",)),
    ("护航者六关", "reward", (ARCHIVE_RUINS, "item.archive_fragment.gamma")),
    ("护航者七关", "battle", ARCHIVE_RUINS),
    ("护航者终关", "travel", ("虚空第一航道", "虚空门户")),
    ("归乡者一关", "travel", ("虚空第一航道",)),
    ("归乡者二关", "reward", (ARCHIVE_RUINS, "item.archive_fragment.beta")),
    ("归乡者三关", "reward", (VOID_ROUTE, "item.void_crystal")),
    ("归乡者四关", "battle", VOID_ROUTE),
    ("归乡者五关", "travel", ("虚空档案遗迹",)),
    ("归乡者六关", "reward", (ARCHIVE_RUINS, "item.void_archive")),
    ("归乡者七关", "battle", ARCHIVE_RUINS),
    ("归乡者终关", "travel", ("虚空第一航道", "虚空门户")),
)

STAGE_KEYS = (
    "void_archive.recorder.1", "void_archive.recorder.2", "void_archive.recorder.3",
    "void_archive.recorder.4", "void_archive.recorder.5", "void_archive.recorder.6",
    "void_archive.recorder.7", "void_archive.recorder.8",
    "void_archive.escort.1", "void_archive.escort.2", "void_archive.escort.3",
    "void_archive.escort.4", "void_archive.escort.5", "void_archive.escort.6",
    "void_archive.escort.7", "void_archive.escort.8",
    "void_archive.return.1", "void_archive.return.2", "void_archive.return.3",
    "void_archive.return.4", "void_archive.return.5", "void_archive.return.6",
    "void_archive.return.7", "void_archive.return.8",
)

# Where the player must stand before each stage's objective, when the previous stage
# left them somewhere else. Positioning travel is not part of the objective itself.
POSITIONING = {
    "归乡者二关": ("虚空档案遗迹",),
    "归乡者三关": ("虚空第一航道",),
}


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


def _battle_seed(prefix: str, chance_bp: int) -> str:
    for index in range(500):
        candidate = f"{prefix}-{index}"
        if battle_roll_bp(candidate + ":battle") < chance_bp:
            return candidate
    raise AssertionError("no seeded battle encounter found")


def _reward_seed(prefix: str, pool_key: str, item_key: str, content) -> str:
    suffixed = reward_pool_uses_item_weight_bonus(pool_key, content)
    for index in range(500):
        candidate = f"{prefix}-{index}"
        seed = f"{candidate}:reward" if suffixed else candidate
        if reward_pool_map(pool_key, seed, content).get(item_key, 0) >= 1:
            return candidate
    raise AssertionError("no seeded reward outcome found")


def _seed_prerequisite_context(runtime, adapter: str, user: str) -> None:
    """Context fixtures only: the archive unlock, the guard win and the time-fort clear.

    Each producer has its own focused test (test_void_archive.py, test_time_fort_secret_realm.py,
    test_void_ruins_secret_realm.py); here they are only the prerequisites of the story stages.
    """

    now = runtime.repository._now()
    now_text = now.isoformat()
    with sqlite3.connect(runtime.settings.database_path) as connection:
        player_id = connection.execute(
            "SELECT id FROM players WHERE platform=? AND platform_user_id=?",
            (adapter, user),
        ).fetchone()[0]
        connection.execute(
            """
            UPDATE players
            SET stage='cultivator', realm_key='void_refining', realm_layer=1,
                location_key='void.portal', stamina=5000, stamina_max=5000,
                energy=5000, energy_max=5000, spirit_stones=50000, bloodline_stability=100,
                max_hp=100000, initiative=1000, qualification_json=?
            WHERE id=?
            """,
            (json.dumps(BALANCED_QUALIFICATION), player_id),
        )
        connection.execute(
            "INSERT INTO void_route_sessions(session_id,player_id,operation_id,route_key,status,"
            "starts_at,ends_at,anchor_cost,stamina_cost,snapshot_json,result_json,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                f"archive-route-{adapter}", player_id, f"archive-route-operation-{adapter}",
                "void.archive_ruins", "settled", now_text, now_text, 1, 0, "{}",
                '{"outcome":"won"}', now_text, now_text,
            ),
        )
        connection.execute(
            "INSERT INTO battle_sessions(battle_id,player_id,start_operation_id,battle_type,enemy_key,"
            "location_key,status,reward_status,round_no,action_sequence,starts_at,turn_deadline,"
            "snapshot_json,state_json,result_json,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                f"archive-battle-{adapter}", player_id, f"archive-battle-operation-{adapter}",
                "pve.archive_keeper", "enemy.archive_keeper", "void.archive_ruins", "settled",
                "none", 20, 20, now_text, now_text, "{}", "{}", '{"outcome":"won"}',
                now_text, now_text,
            ),
        )
        connection.execute(
            "INSERT INTO void_archive_runs(run_id,player_id,week_id,route_session_id,battle_id,"
            "operation_id,outcome,reward_json,snapshot_json,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                f"archive-run-{adapter}", player_id, now.strftime("%Y-%m-%d"),
                f"archive-route-{adapter}", f"archive-battle-{adapter}",
                f"archive-run-operation-{adapter}", "won", "{}", "{}", now_text,
            ),
        )
        connection.execute(
            "INSERT INTO void_archive_unlocks(player_id,week_id,event_key,starts_at,ends_at,"
            "operation_id,created_at) VALUES (?,?,?,?,?,?,?)",
            (
                player_id, now.strftime("%Y-%m-%d"), "event.archive_unlock", now_text,
                (now + timedelta(days=7)).isoformat(), f"archive-unlock-operation-{adapter}",
                now_text,
            ),
        )
        party_id = f"time-fort-party-{adapter}"
        connection.execute(
            "INSERT INTO parties(party_id,party_type,status,leader_id,location_key,"
            "confirmation_deadline,distribution_key,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                party_id, "secret_realm_time_fort", "ready", player_id, "void.archive_ruins",
                now_text, "contribution", now_text, now_text,
            ),
        )
        connection.execute(
            "INSERT INTO time_fort_runs(run_id,party_id,status,node_index,battle_id,quota_key,"
            "starts_at,expires_at,stamina_cost,snapshot_json,result_json,entry_operation_id,"
            "created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                f"time-fort-run-{adapter}", party_id, "settled", 6, None,
                now.strftime("%Y-%m-%d"), now_text, now_text, 40, "{}", '{"outcome":"won"}',
                f"time-fort-entry-{adapter}", now_text, now_text,
            ),
        )
        connection.execute(
            "INSERT INTO time_fort_members(run_id,player_id,quota_key,member_order,first_clear,"
            "status,reward_json,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                f"time-fort-run-{adapter}", player_id, now.strftime("%Y-%m-%d"), 0, 1,
                "settled", "{}", now_text, now_text,
            ),
        )
    equip_damage_weapon(runtime, adapter, user, 50000)


def test_void_archive_mainline_shared_lane_runs_once() -> None:
    # Policy: the shared gameplay lane executes exactly once (qq.official);
    # OneBot v11 differences are covered by the messaging contract tests only.
    async def run() -> None:
        adapter = "qq.official"
        clock = MutableClock(datetime(2026, 10, 1, 12, 5, tzinfo=timezone.utc))
        with TemporaryDirectory() as tmp_dir:
            data_dir = Path(tmp_dir) / "content"
            shutil.copytree(
                Path(__file__).resolve().parents[1] / "data",
                data_dir,
                ignore=shutil.ignore_patterns("*.sqlite3", "*.sqlite3-*", "*.db", "*.db-*"),
            )
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            user = f"void-archive-mainline-{adapter}"
            dispatch = lambda request, command, operation="": runtime.adapters.dispatch(
                adapter, _context(adapter, user, request, operation), command
            )

            assert (await dispatch("create", "开始修仙")).ok
            _seed_prerequisite_context(runtime, adapter, user)

            with sqlite3.connect(runtime.settings.database_path) as connection:
                player_id = connection.execute(
                    "SELECT id FROM players WHERE platform=? AND platform_user_id=?",
                    (adapter, user),
                ).fetchone()[0]

            def quota_used(mode_key: str) -> int:
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    return int(
                        connection.execute(
                            "SELECT COUNT(*) FROM exploration_sessions WHERE player_id=? "
                            "AND mode_key=? AND business_date=?",
                            (player_id, mode_key, runtime.repository._now().date().isoformat()),
                        ).fetchone()[0]
                    )

            def refresh_stamina() -> None:
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE players SET stamina=MAX(stamina, 5000), energy=MAX(energy, 5000) "
                        "WHERE id=?",
                        (player_id,),
                    )

            async def move(hops, tag: str) -> None:
                for hop_index, destination in enumerate(hops, start=1):
                    refresh_stamina()
                    hop = await dispatch(
                        f"{tag}-go-{hop_index}", f"前往 {destination}", f"{tag}-go-{hop_index}"
                    )
                    assert hop.code == "TRAVEL_STARTED", hop.message
                    clock.advance(seconds=2701)
                    settled = await dispatch(
                        f"{tag}-settle-{hop_index}", "结算移动", f"{tag}-settle-{hop_index}"
                    )
                    assert settled.code == "TRAVEL_COMPLETED", settled.message

            async def explore(mode_key: str, mode_name: str, seed: str, tag: str):
                used = quota_used(mode_key)
                if used >= 2:
                    clock.advance(days=1)
                refresh_stamina()
                started = await dispatch(f"{tag}-explore", f"开始探索 {mode_name}", seed)
                assert started.code == "EXPLORATION_STARTED", started.message
                clock.advance(seconds=1201)
                settled = await dispatch(f"{tag}-settle", "结算探索", f"{tag}-settle")
                assert settled.code == "EXPLORATION_SETTLED", settled.message
                return settled

            for index, (alias, kind, payload) in enumerate(STAGES, start=1):
                tag = f"stage{index:02d}"
                if alias in POSITIONING:
                    await move(POSITIONING[alias], f"{tag}-pos")
                started = await dispatch(f"{tag}-start", f"开始虚空档案主线 {alias}", f"{tag}-start")
                assert started.code == "MAINLINE_STARTED", started.message
                if index == 1:
                    early = await dispatch(
                        f"{tag}-early", f"领取虚空档案主线奖励 {alias}", f"{tag}-early"
                    )
                    assert early.code == "MAINLINE_OBJECTIVES_INCOMPLETE", early.message

                if kind == "travel":
                    await move(payload, tag)
                elif kind == "reward":
                    mode_key, item_key = payload
                    mode = runtime.content.require("exploration_mode", mode_key)
                    mode_name = VOID_ROUTE_NAME if mode_key == VOID_ROUTE else ARCHIVE_RUINS_NAME
                    seed = _reward_seed(
                        f"{tag}-{mode_key}",
                        str(mode["reward_pool_key"]),
                        item_key,
                        runtime.content,
                    )
                    settled = await explore(mode_key, mode_name, seed, tag)
                    assert settled.data["result"].get(item_key, 0) >= 1, settled.data
                else:
                    mode_key = payload
                    mode = runtime.content.require("exploration_mode", mode_key)
                    mode_name = VOID_ROUTE_NAME if mode_key == VOID_ROUTE else ARCHIVE_RUINS_NAME
                    seed = _battle_seed(f"{tag}-{mode_key}", int(mode["battle_chance_bp"]))
                    settled = await explore(mode_key, mode_name, seed, tag)
                    assert settled.data["battle_outcome"] == "won", settled.data

                claimed = await dispatch(f"{tag}-claim", f"领取虚空档案主线奖励 {alias}", f"{tag}-claim")
                assert claimed.code == "MAINLINE_REWARD_CLAIMED", claimed.message

            # The final stage replays idempotently instead of paying out twice.
            replay = await dispatch(
                "final-replay", "领取虚空档案主线奖励 归乡者终关", "stage24-claim"
            )
            assert replay.data["idempotent_replay"] is True

            with sqlite3.connect(runtime.settings.database_path) as connection:
                runs = connection.execute(
                    "SELECT story_key, COUNT(*) FROM mainline_runs WHERE player_id=? "
                    "GROUP BY story_key",
                    (player_id,),
                ).fetchall()
                assert runs == [("story.mainline.void_archive", 24)]
                for stage_key in STAGE_KEYS:
                    events = connection.execute(
                        "SELECT COUNT(*) FROM activity_events WHERE player_id=? AND event_key=?",
                        (player_id, f"story.mainline.void_archive:{stage_key}"),
                    ).fetchone()[0]
                    assert int(events) == 1, stage_key
                stones = connection.execute(
                    "SELECT spirit_stones FROM players WHERE id=?", (player_id,)
                ).fetchone()[0]
                # The three chapter-final stages each pay 20 spirit stones on top of the seed.
                assert stones >= 50060
                codex = connection.execute(
                    "SELECT COUNT(*) FROM activity_events WHERE player_id=? AND event_key=?",
                    (player_id, "codex.void.route_ruins"),
                ).fetchone()[0]
                assert int(codex) >= 1
                inventory = json.loads(
                    connection.execute(
                        "SELECT inventory_json FROM players WHERE id=?", (player_id,)
                    ).fetchone()[0]
                )
                # The objectives ran for real: the arc's exploration gains are in the pack.
                assert inventory.get("item.archive_fragment.alpha", 0) >= 1
                assert inventory.get("item.archive_fragment.beta", 0) >= 2
                assert inventory.get("item.void_archive", 0) >= 2
            await runtime.close()

    asyncio.run(run())
