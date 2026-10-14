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

# The weekly border war (魔界入侵) opens the only road into the rift. The schedule uses
# Python's weekday convention (Monday=0), so the window is Wednesday 20:00-23:00 UTC.
BORDER_WAR_WINDOW = datetime(2026, 9, 30, 20, 30, tzinfo=timezone.utc)


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
    """Pick an operation id whose seeded roll makes the patrol meet an encounter."""

    for index in range(500):
        candidate = f"{prefix}-{index}"
        if battle_roll_bp(candidate + ":battle") < chance_bp:
            return candidate
    raise AssertionError("no seeded battle encounter found")


def _reward_seed(prefix: str, pool_key: str, item_key: str, content) -> str:
    """Pick an operation id whose seeded reward roll yields the objective item."""

    suffixed = reward_pool_uses_item_weight_bonus(pool_key, content)
    for index in range(500):
        candidate = f"{prefix}-{index}"
        seed = f"{candidate}:reward" if suffixed else candidate
        if reward_pool_map(pool_key, seed, content).get(item_key, 0) >= 1:
            return candidate
    raise AssertionError("no seeded reward outcome found")


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
                domain_key='domain.fire', location_key='xuantian.domain_front', stamina=1000,
                stamina_max=1000, max_hp=100000, initiative=1000, qualification_json=?,
                intro_json=?, faction_reputation_json='{"demon":300,"beast":300}'
            WHERE id=?
            """,
            (
                json.dumps(BALANCED_QUALIFICATION),
                # The rift road is gated on the three-realms permit; the guard lane runs after it.
                json.dumps({"flags": ["story.mainline.three_realms"]}),
                player_id,
            ),
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
    equip_damage_weapon(runtime, adapter, user, 50000)


def test_domain_frontier_mainline_shared_lane_runs_once() -> None:
    # Policy: the shared gameplay lane executes exactly once (qq.official);
    # OneBot v11 differences are covered by the messaging contract tests only.
    async def run() -> None:
        for adapter in ("qq.official",):
            clock = MutableClock(datetime(2026, 9, 25, 12, 5, tzinfo=timezone.utc))
            with TemporaryDirectory() as tmp_dir:
                # Travel truth must come from the content pack, exactly as production runtime.
                data_dir = Path(tmp_dir) / "content"
                shutil.copytree(
                    Path(__file__).resolve().parents[1] / "data",
                    data_dir,
                    ignore=shutil.ignore_patterns("*.sqlite3", "*.sqlite3-*", "*.db", "*.db-*"),
                )
                runtime = create_runtime(data_dir=data_dir, clock=clock)
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

                early_claim = await dispatch(
                    "guard1-early", "领取领域前线主线奖励 守界一关", "guard1-early"
                )
                assert early_claim.code == "MAINLINE_OBJECTIVES_INCOMPLETE"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE players SET stamina = MAX(stamina, 1000) "
                        "WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    )
                travel_out = await dispatch("guard1-travel-out", "前往 青石镇", "guard1-travel-out")
                assert travel_out.code == "TRAVEL_STARTED", travel_out.message
                clock.advance(seconds=301)
                settle_out = await dispatch("guard1-settle-out", "结算移动", "guard1-settle-out")
                assert settle_out.code == "TRAVEL_COMPLETED", settle_out.message
                travel_back = await dispatch(
                    "guard1-travel-back", "前往 领域前线", "guard1-travel-back"
                )
                assert travel_back.code == "TRAVEL_STARTED", travel_back.message
                clock.advance(seconds=301)
                settle_back = await dispatch("guard1-settle-back", "结算移动", "guard1-settle-back")
                assert settle_back.code == "TRAVEL_COMPLETED", settle_back.message
                guard1_claim = await dispatch(
                    "claim-guard-1", "领取领域前线主线奖励 守界一关", "claim-guard-1"
                )
                assert guard1_claim.code == "MAINLINE_REWARD_CLAIMED", guard1_claim.message

                # guard.2 (巡守裂隙): the rift road opens only inside the border-war window.
                started = await dispatch("start-guard-2", "开始领域前线主线 守界二关", "start-guard-2")
                assert started.code == "MAINLINE_STARTED"
                early = await dispatch("guard2-early", "领取领域前线主线奖励 守界二关", "guard2-early")
                assert early.code == "MAINLINE_OBJECTIVES_INCOMPLETE"
                clock.value = BORDER_WAR_WINDOW
                for index, (destination, wait) in enumerate(
                    (("青石镇", 301), ("魔界战线", 301), ("界隙秘境", 601)), start=1
                ):
                    hop = await dispatch(f"guard2-hop-{index}", f"前往 {destination}", f"guard2-hop-{index}")
                    assert hop.code == "TRAVEL_STARTED", hop.message
                    clock.advance(seconds=wait)
                    settled = await dispatch(f"guard2-settle-{index}", "结算移动", f"guard2-settle-{index}")
                    assert settled.code == "TRAVEL_COMPLETED", settled.message
                guard2_claim = await dispatch(
                    "claim-guard-2", "领取领域前线主线奖励 守界二关", "claim-guard-2"
                )
                assert guard2_claim.code == "MAINLINE_REWARD_CLAIMED", guard2_claim.message
                guard2_replay = await dispatch(
                    "guard2-replay", "领取领域前线主线奖励 守界二关", "claim-guard-2"
                )
                assert guard2_replay.data["idempotent_replay"] is True

                # guard.3 (鏖战边关): repel the rift watcher in a seeded boundary-rift patrol.
                started = await dispatch("start-guard-3", "开始领域前线主线 守界三关", "start-guard-3")
                assert started.code == "MAINLINE_STARTED"
                rift_mode = runtime.content.require("exploration_mode", "explore.boundary_rift")
                battle_operation = _battle_seed("guard3-rift", int(rift_mode["battle_chance_bp"]))
                patrol = await dispatch("guard3-explore", "开始探索 界隙巡查", battle_operation)
                assert patrol.code == "EXPLORATION_STARTED", patrol.message
                clock.advance(seconds=601)
                settled = await dispatch("guard3-settle", "结算探索", "guard3-settle")
                assert settled.code == "EXPLORATION_SETTLED", settled.message
                assert settled.data["battle_outcome"] == "won", settled.data
                guard3_claim = await dispatch(
                    "claim-guard-3", "领取领域前线主线奖励 守界三关", "claim-guard-3"
                )
                assert guard3_claim.code == "MAINLINE_REWARD_CLAIMED", guard3_claim.message

                # guard.4 (镇纹回响): recover a domain core fragment from the same patrol grounds.
                started = await dispatch("start-guard-4", "开始领域前线主线 守界四关", "start-guard-4")
                assert started.code == "MAINLINE_STARTED"
                reward_operation = _reward_seed(
                    "guard4-rift",
                    str(rift_mode["reward_pool_key"]),
                    "item.domain_core_fragment",
                    runtime.content,
                )
                patrol = await dispatch("guard4-explore", "开始探索 界隙巡查", reward_operation)
                assert patrol.code == "EXPLORATION_STARTED", patrol.message
                clock.advance(seconds=601)
                settled = await dispatch("guard4-settle", "结算探索", "guard4-settle")
                assert settled.code == "EXPLORATION_SETTLED", settled.message
                assert settled.data["result"].get("item.domain_core_fragment", 0) >= 1, settled.data
                guard4_claim = await dispatch(
                    "claim-guard-4", "领取领域前线主线奖励 守界四关", "claim-guard-4"
                )
                assert guard4_claim.code == "MAINLINE_REWARD_CLAIMED", guard4_claim.message

                for lane, final_alias in (("守界", "守界终关"), ("净渊", "净渊终关"), ("护祖", "护祖终关")):
                    aliases = [f"{lane}{name}关" for name in ("一", "二", "三", "四", "五")] + [final_alias]
                    for index, alias in enumerate(aliases, start=1):
                        if lane == "守界" and index <= 4:
                            # guard.1-4 already ran their real objectives above.
                            continue
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
                    # Five fragments come from the frontier event chain; the guard.4 patrol adds one.
                    assert inventory.get("item.domain_core_fragment") == 6
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
                    for stage_key in (
                        "domain_frontier.guard.1",
                        "domain_frontier.guard.2",
                        "domain_frontier.guard.3",
                        "domain_frontier.guard.4",
                    ):
                        oath_events = connection.execute(
                            "SELECT COUNT(*) FROM activity_events WHERE player_id=(SELECT id FROM players WHERE platform=? AND platform_user_id=?) AND event_key=?",
                            (adapter, user, f"story.mainline.domain_frontier:{stage_key}"),
                        ).fetchone()[0]
                        assert int(oath_events) == 1
                projects = await dispatch("projects", "公共项目")
                assert projects.code == "PROJECT_LIST"
                assert {item["project_key"] for item in projects.data["projects"]} >= {
                    "project.domain_refuge",
                    "project.abyss_purification",
                    "project.ancestral_habitat",
                }
                await runtime.close()

    asyncio.run(run())
