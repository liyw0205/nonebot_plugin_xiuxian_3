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
                stamina_max=1000, energy=5000, energy_max=5000, spirit_stones=50000,
                bloodline_stability=100, max_hp=100000, initiative=1000, qualification_json=?,
                intro_json=?, faction_reputation_json='{"demon":300,"beast":3000}'
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

                # guard.5 (共铸守门): gather the gate's mist core from the rift patrol.
                started = await dispatch("start-guard-5", "开始领域前线主线 守界五关", "start-guard-5")
                assert started.code == "MAINLINE_STARTED"
                mist_operation = _reward_seed(
                    "guard5-rift",
                    str(rift_mode["reward_pool_key"]),
                    "item.material.mist_core",
                    runtime.content,
                )
                patrol = await dispatch("guard5-explore", "开始探索 界隙巡查", mist_operation)
                assert patrol.code == "EXPLORATION_STARTED", patrol.message
                clock.advance(seconds=601)
                settled = await dispatch("guard5-settle", "结算探索", "guard5-settle")
                assert settled.code == "EXPLORATION_SETTLED", settled.message
                assert settled.data["result"].get("item.material.mist_core", 0) >= 1, settled.data
                claim = await dispatch("claim-guard-5", "领取领域前线主线奖励 守界五关", "claim-guard-5")
                assert claim.code == "MAINLINE_REWARD_CLAIMED", claim.message

                # guard.6 (守界封天): carry the patrol gains back to the frontier and seal it.
                started = await dispatch("start-guard-6", "开始领域前线主线 守界终关", "start-guard-6")
                assert started.code == "MAINLINE_STARTED"
                for index, (destination, wait) in enumerate(
                    (("魔界战线", 301), ("青石镇", 301), ("领域前线", 301)), start=1
                ):
                    hop = await dispatch(f"guard6-hop-{index}", f"前往 {destination}", f"guard6-hop-{index}")
                    assert hop.code == "TRAVEL_STARTED", hop.message
                    clock.advance(seconds=wait)
                    settled = await dispatch(f"guard6-settle-{index}", "结算移动", f"guard6-settle-{index}")
                    assert settled.code == "TRAVEL_COMPLETED", settled.message
                claim = await dispatch("claim-guard-6", "领取领域前线主线奖励 守界终关", "claim-guard-6")
                assert claim.code == "MAINLINE_REWARD_CLAIMED", claim.message
                replay = await dispatch("guard6-replay", "领取领域前线主线奖励 守界终关", "claim-guard-6")
                assert replay.data["idempotent_replay"] is True

                # protect.1 (祖脉来书): answer the ancestral summons at the lake.
                started = await dispatch("start-protect-1", "开始领域前线主线 护祖一关", "start-protect-1")
                assert started.code == "MAINLINE_STARTED"
                for index, (destination, wait) in enumerate(
                    (("青石镇", 301), ("云城", 181), ("云舟渡口", 61), ("万兽山", 301), ("祖灵湖", 601)),
                    start=1,
                ):
                    hop = await dispatch(f"protect1-hop-{index}", f"前往 {destination}", f"protect1-hop-{index}")
                    assert hop.code == "TRAVEL_STARTED", hop.message
                    clock.advance(seconds=wait)
                    settled = await dispatch(f"protect1-settle-{index}", "结算移动", f"protect1-settle-{index}")
                    assert settled.code == "TRAVEL_COMPLETED", settled.message
                claim = await dispatch("claim-protect-1", "领取领域前线主线奖励 护祖一关", "claim-protect-1")
                assert claim.code == "MAINLINE_REWARD_CLAIMED", claim.message

                # protect.2 (护脉踏歌): bring back the ancestral blood from the lake.
                started = await dispatch("start-protect-2", "开始领域前线主线 护祖二关", "start-protect-2")
                assert started.code == "MAINLINE_STARTED"
                lake_mode = runtime.content.require("exploration_mode", "explore.ancestral_lake")
                blood_operation = _reward_seed(
                    "protect2-lake",
                    str(lake_mode["reward_pool_key"]),
                    "item.ancestral_blood",
                    runtime.content,
                )
                patrol = await dispatch("protect2-explore", "开始探索 祖灵湖探索", blood_operation)
                assert patrol.code == "EXPLORATION_STARTED", patrol.message
                clock.advance(seconds=1201)
                settled = await dispatch("protect2-settle", "结算探索", "protect2-settle")
                assert settled.code == "EXPLORATION_SETTLED", settled.message
                assert settled.data["result"].get("item.ancestral_blood", 0) >= 1, settled.data
                claim = await dispatch("claim-protect-2", "领取领域前线主线奖励 护祖二关", "claim-protect-2")
                assert claim.code == "MAINLINE_REWARD_CLAIMED", claim.message

                # protect.3 (祖影临阵): hold the line when the ancestral shadow appears.
                started = await dispatch("start-protect-3", "开始领域前线主线 护祖三关", "start-protect-3")
                assert started.code == "MAINLINE_STARTED"
                shadow_operation = _battle_seed("protect3-lake", int(lake_mode["battle_chance_bp"]))
                patrol = await dispatch("protect3-explore", "开始探索 祖灵湖探索", shadow_operation)
                assert patrol.code == "EXPLORATION_STARTED", patrol.message
                clock.advance(seconds=1201)
                settled = await dispatch("protect3-settle", "结算探索", "protect3-settle")
                assert settled.code == "EXPLORATION_SETTLED", settled.message
                assert settled.data["battle_outcome"] == "won", settled.data
                claim = await dispatch("claim-protect-3", "领取领域前线主线奖励 护祖三关", "claim-protect-3")
                assert claim.code == "MAINLINE_REWARD_CLAIMED", claim.message

                # protect.4 (血誓回潮): swear the blood oath with beast blood from the hills.
                started = await dispatch("start-protect-4", "开始领域前线主线 护祖四关", "start-protect-4")
                assert started.code == "MAINLINE_STARTED"
                hop = await dispatch("protect4-travel", "前往 万兽山", "protect4-travel")
                assert hop.code == "TRAVEL_STARTED", hop.message
                clock.advance(seconds=601)
                settled = await dispatch("protect4-settle", "结算移动", "protect4-settle")
                assert settled.code == "TRAVEL_COMPLETED", settled.message
                hunt_mode = runtime.content.require("exploration_mode", "explore.beast_hunt")
                blood_hunt_operation = _reward_seed(
                    "protect4-hunt",
                    str(hunt_mode["reward_pool_key"]),
                    "item.beast_blood",
                    runtime.content,
                )
                hunt = await dispatch("protect4-explore", "开始探索 万兽山狩猎", blood_hunt_operation)
                assert hunt.code == "EXPLORATION_STARTED", hunt.message
                clock.advance(seconds=901)
                settled = await dispatch("protect4-explore-settle", "结算探索", "protect4-explore-settle")
                assert settled.code == "EXPLORATION_SETTLED", settled.message
                assert settled.data["result"].get("item.beast_blood", 0) >= 1, settled.data
                claim = await dispatch("claim-protect-4", "领取领域前线主线奖励 护祖四关", "claim-protect-4")
                assert claim.code == "MAINLINE_REWARD_CLAIMED", claim.message

                # protect.5 (万灵同守): recover the bloodline clue that binds the spirits.
                started = await dispatch("start-protect-5", "开始领域前线主线 护祖五关", "start-protect-5")
                assert started.code == "MAINLINE_STARTED"
                clue_operation = _reward_seed(
                    "protect5-hunt",
                    str(hunt_mode["reward_pool_key"]),
                    "item.clue.beast_bloodline",
                    runtime.content,
                )
                hunt = await dispatch("protect5-explore", "开始探索 万兽山狩猎", clue_operation)
                assert hunt.code == "EXPLORATION_STARTED", hunt.message
                clock.advance(seconds=901)
                settled = await dispatch("protect5-settle", "结算探索", "protect5-settle")
                assert settled.code == "EXPLORATION_SETTLED", settled.message
                assert settled.data["result"].get("item.clue.beast_bloodline", 0) >= 1, settled.data
                claim = await dispatch("claim-protect-5", "领取领域前线主线奖励 护祖五关", "claim-protect-5")
                assert claim.code == "MAINLINE_REWARD_CLAIMED", claim.message

                # protect.6 (护祖长明): register the habitat at the three-realms trade port.
                started = await dispatch("start-protect-6", "开始领域前线主线 护祖终关", "start-protect-6")
                assert started.code == "MAINLINE_STARTED"
                hop = await dispatch("protect6-travel", "前往 三界贸易口", "protect6-travel")
                assert hop.code == "TRAVEL_STARTED", hop.message
                clock.advance(seconds=181)
                settled = await dispatch("protect6-settle", "结算移动", "protect6-settle")
                assert settled.code == "TRAVEL_COMPLETED", settled.message
                claim = await dispatch("claim-protect-6", "领取领域前线主线奖励 护祖终关", "claim-protect-6")
                assert claim.code == "MAINLINE_REWARD_CLAIMED", claim.message
                replay = await dispatch("protect6-replay", "领取领域前线主线奖励 护祖终关", "claim-protect-6")
                assert replay.data["idempotent_replay"] is True

                # purify.1 (浊潮初见): cross to the abyss gate and accept the demon intro.
                started = await dispatch("start-purify-1", "开始领域前线主线 净渊一关", "start-purify-1")
                assert started.code == "MAINLINE_STARTED"
                for index, (destination, wait) in enumerate(
                    (("万兽山", 601), ("云舟渡口", 301)), start=1
                ):
                    hop = await dispatch(f"purify1-hop-{index}", f"前往 {destination}", f"purify1-hop-{index}")
                    assert hop.code == "TRAVEL_STARTED", hop.message
                    clock.advance(seconds=wait)
                    settled = await dispatch(f"purify1-settle-{index}", "结算移动", f"purify1-settle-{index}")
                    assert settled.code == "TRAVEL_COMPLETED", settled.message
                claim = await dispatch("claim-purify-1", "领取领域前线主线奖励 净渊一关", "claim-purify-1")
                assert claim.code == "MAINLINE_REWARD_CLAIMED", claim.message
                boarded = await dispatch("purify1-board", "登上云舟 魔界引导", "purify1-board")
                assert boarded.code == "CLOUD_BOAT_STARTED", boarded.message
                clock.advance(seconds=301)
                arrived = await dispatch("purify1-arrive", "结算云舟", "purify1-arrive")
                assert arrived.code == "CLOUD_BOAT_ARRIVED", arrived.message
                intro = await dispatch("purify1-intro", "接受魔界引导", "purify1-intro")
                assert intro.code == "DEMON_INTRO_ACCEPTED", intro.message

                # purify.2 (引流归墟): draw the turbid tide with soul crystals from the gate.
                started = await dispatch("start-purify-2", "开始领域前线主线 净渊二关", "start-purify-2")
                assert started.code == "MAINLINE_STARTED"
                gate_mode = runtime.content.require("exploration_mode", "explore.demon_threshold")
                crystal_operation = _reward_seed(
                    "purify2-gate",
                    str(gate_mode["reward_pool_key"]),
                    "item.soul_crystal",
                    runtime.content,
                )
                gathered = await dispatch("purify2-explore", "开始探索 深渊门备材", crystal_operation)
                assert gathered.code == "EXPLORATION_STARTED", gathered.message
                clock.advance(seconds=241)
                settled = await dispatch("purify2-settle", "结算探索", "purify2-settle")
                assert settled.code == "EXPLORATION_SETTLED", settled.message
                assert settled.data["result"].get("item.soul_crystal", 0) >= 1, settled.data
                claim = await dispatch("claim-purify-2", "领取领域前线主线奖励 净渊二关", "claim-purify-2")
                assert claim.code == "MAINLINE_REWARD_CLAIMED", claim.message

                # purify.3 (净火照渊): burn the hidden line with a demon core.
                started = await dispatch("start-purify-3", "开始领域前线主线 净渊三关", "start-purify-3")
                assert started.code == "MAINLINE_STARTED"
                core_operation = _reward_seed(
                    "purify3-gate",
                    str(gate_mode["reward_pool_key"]),
                    "item.demon_core",
                    runtime.content,
                )
                gathered = await dispatch("purify3-explore", "开始探索 深渊门备材", core_operation)
                assert gathered.code == "EXPLORATION_STARTED", gathered.message
                clock.advance(seconds=241)
                settled = await dispatch("purify3-settle", "结算探索", "purify3-settle")
                assert settled.code == "EXPLORATION_SETTLED", settled.message
                assert settled.data["result"].get("item.demon_core", 0) >= 1, settled.data
                claim = await dispatch("claim-purify-3", "领取领域前线主线奖励 净渊三关", "claim-purify-3")
                assert claim.code == "MAINLINE_REWARD_CLAIMED", claim.message

                # purify.4 (洗剑沉渊): descend into the fallen ruins.
                started = await dispatch("start-purify-4", "开始领域前线主线 净渊四关", "start-purify-4")
                assert started.code == "MAINLINE_STARTED"
                hop = await dispatch("purify4-travel", "前往 堕落遗迹", "purify4-travel")
                assert hop.code == "TRAVEL_STARTED", hop.message
                clock.advance(seconds=481)
                settled = await dispatch("purify4-settle", "结算移动", "purify4-settle")
                assert settled.code == "TRAVEL_COMPLETED", settled.message
                claim = await dispatch("claim-purify-4", "领取领域前线主线奖励 净渊四关", "claim-purify-4")
                assert claim.code == "MAINLINE_REWARD_CLAIMED", claim.message

                # purify.5 (百宗同契): recover the old abyss contract from the ruins.
                started = await dispatch("start-purify-5", "开始领域前线主线 净渊五关", "start-purify-5")
                assert started.code == "MAINLINE_STARTED"
                ruins_mode = runtime.content.require("exploration_mode", "explore.demon_abyss")
                contract_operation = _reward_seed(
                    "purify5-ruins",
                    str(ruins_mode["reward_pool_key"]),
                    "item.clue.demon_contract",
                    runtime.content,
                )
                patrol = await dispatch("purify5-explore", "开始探索 魔界堕落遗迹探索", contract_operation)
                assert patrol.code == "EXPLORATION_STARTED", patrol.message
                clock.advance(seconds=901)
                settled = await dispatch("purify5-settle", "结算探索", "purify5-settle")
                assert settled.code == "EXPLORATION_SETTLED", settled.message
                assert settled.data["result"].get("item.clue.demon_contract", 0) >= 1, settled.data
                claim = await dispatch("claim-purify-5", "领取领域前线主线奖励 净渊五关", "claim-purify-5")
                assert claim.code == "MAINLINE_REWARD_CLAIMED", claim.message

                # purify.6 (净渊开明): seal the source by beating its guardian.
                started = await dispatch("start-purify-6", "开始领域前线主线 净渊终关", "start-purify-6")
                assert started.code == "MAINLINE_STARTED"
                source_operation = _battle_seed("purify6-ruins", int(ruins_mode["battle_chance_bp"]))
                patrol = await dispatch("purify6-explore", "开始探索 魔界堕落遗迹探索", source_operation)
                assert patrol.code == "EXPLORATION_STARTED", patrol.message
                clock.advance(seconds=901)
                settled = await dispatch("purify6-settle", "结算探索", "purify6-settle")
                assert settled.code == "EXPLORATION_SETTLED", settled.message
                assert settled.data["battle_outcome"] == "won", settled.data
                claim = await dispatch("claim-purify-6", "领取领域前线主线奖励 净渊终关", "claim-purify-6")
                assert claim.code == "MAINLINE_REWARD_CLAIMED", claim.message
                replay = await dispatch("purify6-replay", "领取领域前线主线奖励 净渊终关", "claim-purify-6")
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
                        "domain_frontier.guard.5",
                        "domain_frontier.guard.6",
                        "domain_frontier.protect.1",
                        "domain_frontier.protect.2",
                        "domain_frontier.protect.3",
                        "domain_frontier.protect.4",
                        "domain_frontier.protect.5",
                        "domain_frontier.protect.6",
                        "domain_frontier.purify.1",
                        "domain_frontier.purify.2",
                        "domain_frontier.purify.3",
                        "domain_frontier.purify.4",
                        "domain_frontier.purify.5",
                        "domain_frontier.purify.6",
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
