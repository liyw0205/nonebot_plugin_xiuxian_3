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

MODE_NAMES = {
    "explore.demon_abyss": "魔界堕落遗迹探索",
    "explore.demon_threshold": "深渊门备材",
    "explore.beast_hunt": "万兽山狩猎",
    "explore.ancestral_lake": "祖灵湖探索",
    "explore.boundary_rift": "界隙巡查",
    "explore.void_route": "虚空航道历练",
    "explore.archive_ruins": "档案遗迹搜寻",
}

# (lane, stage, kind, payload) — travel payloads are the real hop sequence; the
# first hop's origin is the context fixture the test positions the player at.
STAGES = (
    ("builder", 1, "travel", ("玄天界·云城", "青石镇")),
    ("builder", 2, "reward", ("explore.demon_abyss", "item.clue.demon_contract")),
    ("builder", 3, "reward", ("explore.beast_hunt", "item.clue.beast_bloodline")),
    ("builder", 4, "travel", ("万兽山入口", "三界贸易口")),
    ("builder", 5, "travel", ("魔界战线", "界隙秘境")),
    ("builder", 6, "battle", ("explore.boundary_rift",)),
    ("builder", 7, "reward", ("explore.void_route", "item.void_crystal")),
    ("builder", 8, "travel", ("虚空第一航道", "虚空档案遗迹")),
    ("builder", 9, "reward", ("explore.archive_ruins", "item.archive_fragment.beta")),
    ("builder", 10, "travel", ("虚空档案遗迹", "道源门")),
    ("witness", 1, "travel", ("青石镇", "玄天界·云城")),
    ("witness", 2, "travel", ("魔渊入口", "魔渊集市")),
    ("witness", 3, "reward", ("explore.demon_abyss", "item.demon_core")),
    ("witness", 4, "battle", ("explore.demon_abyss",)),
    ("witness", 5, "battle", ("explore.ancestral_lake",)),
    ("witness", 6, "reward", ("explore.beast_hunt", "item.beast_blood")),
    ("witness", 7, "travel", ("万兽山入口", "三界贸易口")),
    ("witness", 8, "reward", ("explore.archive_ruins", "item.archive_fragment.gamma")),
    ("witness", 9, "reward", ("explore.archive_ruins", "item.void_archive")),
    ("witness", 10, "travel", ("虚空第一航道", "虚空档案遗迹")),
    ("traveler", 1, "travel", ("青石镇", "宗门山门")),
    ("traveler", 2, "travel", ("魔渊入口", "堕落遗迹")),
    ("traveler", 3, "travel", ("云舟渡口", "万兽山入口")),
    ("traveler", 4, "battle", ("explore.boundary_rift",)),
    ("traveler", 5, "travel", ("虚空第一航道", "虚空档案遗迹")),
    ("traveler", 6, "travel", ("万兽山入口", "三界贸易口")),
    ("traveler", 7, "travel", ("万兽山入口", "云舟渡口")),
    ("traveler", 8, "reward", ("explore.demon_threshold", "item.soul_crystal")),
    ("traveler", 9, "reward", ("explore.void_route", "item.void_anchor")),
    ("traveler", 10, "travel", ("云舟渡口", "玄天界·云城", "青石镇")),
)

LOCATION_NAMES = {
    "xuantian.new_town": "青石镇",
    "xuantian.cloud_city": "玄天界·云城",
    "xuantian.sect_gate": "宗门山门",
    "xuantian.floating_boat": "云舟渡口",
    "demon.abyss_gate": "魔渊入口",
    "demon.abyss_market": "魔渊集市",
    "demon.fallen_ruins": "堕落遗迹",
    "beast.ten_thousand_hills": "万兽山入口",
    "beast.three_realms_trade_port": "三界贸易口",
    "beast.ancestral_lake": "祖灵湖",
    "cave.boundary_realm": "界隙秘境",
    "xuantian.war_front": "魔界战线",
    "void.first_route": "虚空第一航道",
    "void.archive_ruins": "虚空档案遗迹",
    "dao.origin_gate": "道源门",
}
NAME_TO_KEY = {name: key for key, name in LOCATION_NAMES.items()}


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


def _prepare_player(runtime, adapter: str, user: str) -> None:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        player_id = connection.execute(
            "SELECT id FROM players WHERE platform=? AND platform_user_id=?",
            (adapter, user),
        ).fetchone()[0]
        connection.execute(
            """
            UPDATE players
            SET stage='cultivator', realm_key='void_refining', realm_layer=10,
                location_key='xuantian.new_town', stamina=5000, stamina_max=5000,
                energy=5000, energy_max=5000, spirit_stones=50000, bloodline_stability=100,
                max_hp=100000, initiative=1000, qualification_json=?,
                faction_reputation_json='{"demon":3000,"beast":3000}',
                intro_json='{"flags":["story.mainline.three_realms","access.demon_abyss_gate"]}',
                inventory_json='{"item.dao_fruit_fragment": 4}'
            WHERE id=?
            """,
            (json.dumps(BALANCED_QUALIFICATION), player_id),
        )
        connection.execute(
            "UPDATE players SET dao_fruit_progress=470 WHERE id=?", (player_id,)
        )
    equip_damage_weapon(runtime, adapter, user, 50000)


def test_dao_echoes_mainline_shared_lane_runs_once() -> None:
    # Policy: the shared gameplay lane executes exactly once (qq.official);
    # OneBot v11 differences are covered by the messaging contract tests only.
    async def run() -> None:
        adapter = "qq.official"
        clock = MutableClock(datetime(2026, 10, 7, 12, 5, tzinfo=timezone.utc))
        with TemporaryDirectory() as tmp_dir:
            data_dir = Path(tmp_dir) / "content"
            shutil.copytree(
                Path(__file__).resolve().parents[1] / "data",
                data_dir,
                ignore=shutil.ignore_patterns("*.sqlite3", "*.sqlite3-*", "*.db", "*.db-*"),
            )
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            user = f"dao-echoes-mainline-{adapter}"
            dispatch = lambda request, command, operation="": runtime.adapters.dispatch(
                adapter, _context(adapter, user, request, operation), command
            )

            assert (await dispatch("create", "开始修仙")).ok
            _prepare_player(runtime, adapter, user)

            with sqlite3.connect(runtime.settings.database_path) as connection:
                player_id = connection.execute(
                    "SELECT id FROM players WHERE platform=? AND platform_user_id=?",
                    (adapter, user),
                ).fetchone()[0]

            def position(location_key: str, *, realm: str = "void_refining", layer: int = 10) -> None:
                """Context fixture: where the stage's objective starts from."""

                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE players SET location_key=?, realm_key=?, realm_layer=?, "
                        "stamina=MAX(stamina, 5000), energy=MAX(energy, 5000) WHERE id=?",
                        (location_key, realm, layer, player_id),
                    )

            def quota_used(mode_key: str) -> int:
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    return int(
                        connection.execute(
                            "SELECT COUNT(*) FROM exploration_sessions WHERE player_id=? "
                            "AND mode_key=? AND business_date=?",
                            (player_id, mode_key, runtime.repository._now().date().isoformat()),
                        ).fetchone()[0]
                    )

            async def move(hops, tag: str) -> None:
                for hop_index, destination in enumerate(hops, start=1):
                    hop = await dispatch(
                        f"{tag}-go-{hop_index}", f"前往 {destination}", f"{tag}-go-{hop_index}"
                    )
                    assert hop.code == "TRAVEL_STARTED", hop.message
                    clock.advance(seconds=3601)
                    settled = await dispatch(
                        f"{tag}-settle-{hop_index}", "结算移动", f"{tag}-settle-{hop_index}"
                    )
                    assert settled.code == "TRAVEL_COMPLETED", settled.message

            async def explore(mode_key: str, seed: str, tag: str):
                if quota_used(mode_key) >= 2:
                    clock.advance(days=1)
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE players SET stamina=MAX(stamina, 5000), energy=MAX(energy, 5000) "
                        "WHERE id=?",
                        (player_id,),
                    )
                started = await dispatch(
                    f"{tag}-explore", f"开始探索 {MODE_NAMES[mode_key]}", seed
                )
                assert started.code == "EXPLORATION_STARTED", started.message
                clock.advance(seconds=1801)
                settled = await dispatch(f"{tag}-settle", "结算探索", f"{tag}-settle")
                assert settled.code == "EXPLORATION_SETTLED", settled.message
                return settled

            for index, (lane, stage, kind, payload) in enumerate(STAGES, start=1):
                tag = f"s{index:02d}"
                if kind == "travel":
                    position(NAME_TO_KEY[payload[0]])
                else:
                    mode_key = payload[0]
                    position(
                        str(runtime.content.require("exploration_mode", mode_key)["location_key"])
                    )
                if (lane, stage) == ("builder", 10):
                    position("void.archive_ruins", realm="dao_union", layer=6)

                started = await dispatch(f"{tag}-start", f"开始道源主线 {lane} {stage}", f"{tag}-start")
                assert started.code == "DAO_ECHOES_STAGE_STARTED", started.message
                if index == 1:
                    early = await dispatch(
                        f"{tag}-early", f"领取道源主线奖励 {lane} {stage}", f"{tag}-early"
                    )
                    assert early.code == "MAINLINE_OBJECTIVES_INCOMPLETE", early.message

                if kind == "travel":
                    await move(payload[1:], tag)
                elif kind == "reward":
                    mode_key, item_key = payload
                    mode = runtime.content.require("exploration_mode", mode_key)
                    seed = _reward_seed(
                        f"{tag}-{mode_key}", str(mode["reward_pool_key"]), item_key, runtime.content
                    )
                    settled = await explore(mode_key, seed, tag)
                    assert settled.data["result"].get(item_key, 0) >= 1, settled.data
                else:
                    mode_key = payload[0]
                    mode = runtime.content.require("exploration_mode", mode_key)
                    seed = _battle_seed(f"{tag}-{mode_key}", int(mode["battle_chance_bp"]))
                    settled = await explore(mode_key, seed, tag)
                    assert settled.data["battle_outcome"] == "won", settled.data

                claimed = await dispatch(
                    f"{tag}-claim", f"领取道源主线奖励 {lane} {stage}", f"{tag}-claim"
                )
                assert claimed.code == "DAO_ECHOES_STAGE_CLAIMED", claimed.message
                assert claimed.data["first_clear"] is True

            replay = await dispatch("final-replay", "领取道源主线奖励 builder 1", "s01-claim")
            assert replay.data["idempotent_replay"] is True

            status = await dispatch("status", "道源主线")
            assert status.code == "DAO_ECHOES_STATUS"
            assert all(lane["completed"] == 10 for lane in status.data["lanes"])

            # The three-realm mainline qualification only opens once every lane is done.
            qualification = await dispatch("record-mainline", "记录合道主线")
            assert qualification.code == "QUEST_ACTION_RECORDED", qualification.message
            assert qualification.data["progress"]["three_realm_mainline"] == 1

            with sqlite3.connect(runtime.settings.database_path) as connection:
                runs = connection.execute(
                    "SELECT COUNT(*) FROM mainline_runs WHERE player_id=? AND story_key=? "
                    "AND status='claimed' AND first_clear_claimed=1",
                    (player_id, "story.mainline.dao_echoes"),
                ).fetchone()[0]
                assert int(runs) == 30
                for lane in ("builder", "witness", "traveler"):
                    for stage in range(1, 11):
                        key = f"lane.{lane}.chapter.{stage:02d}"
                        events = connection.execute(
                            "SELECT COUNT(*) FROM activity_events WHERE player_id=? AND event_key=?",
                            (player_id, f"story.mainline.dao_echoes:{key}"),
                        ).fetchone()[0]
                        assert int(events) == 1, key
                flags = connection.execute(
                    "SELECT COUNT(*) FROM activity_events WHERE player_id=? "
                    "AND event_key LIKE 'codex.story.dao_echoes.%'",
                    (player_id,),
                ).fetchone()[0]
                assert int(flags) == 30
            await runtime.close()

    asyncio.run(run())
