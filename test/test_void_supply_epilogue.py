from __future__ import annotations

import asyncio
import json
import shutil
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.adventures.mainline import (
    VOID_ARCHIVE_STORY_KEY,
    mainline_definitions,
)
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError
from nonebot_plugin_xiuxian_3.xiuxian.exploration.rules import battle_roll_bp
from nonebot_plugin_xiuxian_3.xiuxian.rewards.rules import reward_pool_map, reward_pool_uses_item_weight_bonus
from travel_fixtures import set_travel_end_at

ROOT = Path(__file__).parents[1]
STORY = VOID_ARCHIVE_STORY_KEY
PREFIX = "void_archive.supply."


class Clock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **kwargs: int) -> None:
        self.value += timedelta(**kwargs)


def _copy_data(path: Path) -> Path:
    target = path / "content"
    shutil.copytree(ROOT / "data", target)
    return target


def _edit_story(path: Path, edit) -> None:
    story_path = path / "剧情" / "主线.json"
    document = json.loads(story_path.read_text(encoding="utf-8"))
    edit({row["key"]: row for row in document["records"]})
    story_path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _context(user: str, operation: str, *, operation_id: str | None = None) -> CommandContext:
    return CommandContext(
        adapter="onebot.v11",
        user_id=user,
        request_id=operation,
        operation_id=operation_id or operation,
    )


def _seed_archive_return(runtime, user: str, clock: Clock) -> int:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        player_id = connection.execute(
            "SELECT id FROM players WHERE platform='onebot.v11' AND platform_user_id=?", (user,)
        ).fetchone()[0]
        stamp = clock().isoformat()
        connection.execute(
            "UPDATE players SET stage='cultivator', realm_key='void_refining', realm_layer=1, "
            "location_key='void.portal', stamina=500, stamina_max=500, energy=100, energy_max=100 "
            "WHERE id=?",
            (player_id,),
        )
        connection.execute(
            "INSERT INTO mainline_runs(player_id,story_key,chapter,stage,stage_key,status,"
            "first_clear_claimed,first_clear_key,snapshot_json,result_json,created_at,updated_at) "
            "VALUES(?,?,?,?,?,'claimed',1,?,'{}','{}',?,?)",
            (player_id, STORY, 3, 8, "void_archive.return.8", "seed-return", stamp, stamp),
        )
        connection.execute(
            "INSERT INTO activity_events(player_id,event_key,source_operation_id,occurred_at) VALUES(?,?,?,?)",
            (player_id, f"{STORY}:void_archive.return.8", "seed-return", stamp),
        )
    return int(player_id)


def _reward_operation(content, prefix: str) -> str:
    mode = content.require("exploration_mode", "explore.void_route")
    pool_key = str(mode["reward_pool_key"])
    weighted = reward_pool_uses_item_weight_bonus(pool_key, content)
    for index in range(500):
        candidate = f"{prefix}-{index}"
        seed = f"{candidate}:reward" if weighted else candidate
        if reward_pool_map(pool_key, seed, content).get("item.void_anchor", 0) >= 1:
            if battle_roll_bp(f"{candidate}:battle") >= int(mode["battle_chance_bp"]):
                return candidate
    raise AssertionError("could not find a non-combat anchor reward seed")


def test_void_supply_epilogue_contract_and_help() -> None:
    bundle = ContentBundle.load(ROOT / "data")
    definitions = {row.key: row for row in mainline_definitions(bundle, story_key=STORY)}
    stages = [definitions[PREFIX + str(index)] for index in (1, 2, 3)]
    assert [row.next_stage_key for row in stages] == [PREFIX + "2", PREFIX + "3", None]
    assert definitions["void_archive.return.8"].next_stage_key == PREFIX + "1"
    assert all(row.lane == "supply" and row.lane_label == "虚空补给" for row in stages)
    assert stages[0].objectives[0]["destination_key"] == "void.first_route"
    assert stages[1].objectives[0]["route_key"] == "idle.void_supply_watch"
    assert stages[2].objectives[0]["item_key"] == "item.void_anchor"
    assert stages[2].objectives[0]["mode_key"] == "explore.void_route"
    assert all(
        item.get("destination_key") not in {"void.sect_fortress", "void.void_market"}
        for row in stages
        for item in row.objectives
    )
    route = next(row for row in bundle.list("livelihood") if row["key"] == "idle.void_supply_watch")
    rewards = {row["key"]: row for row in bundle.list("reward")}
    assert route["duration_seconds"] == 12 * 60 * 60 and route["daily_limit"] == 1
    assert rewards[route["reward_pool_key"]]["outcomes"]
    assert rewards[route["fallback_reward_pool_key"]]["outcomes"]


@pytest.mark.parametrize("edit", [
    lambda rows: rows[PREFIX + "2"]["objectives"][0].__setitem__("route_key", "idle.missing"),
    lambda rows: rows[PREFIX + "3"]["objectives"][0].__setitem__("item_key", "item.void_missing"),
])
def test_void_supply_epilogue_rejects_missing_source(tmp_path: Path, edit) -> None:
    data = _copy_data(tmp_path)
    _edit_story(data, edit)
    with pytest.raises(ContentError):
        mainline_definitions(ContentBundle.load(data), story_key=STORY)


def test_void_supply_epilogue_requires_full_idle_and_real_exploration(tmp_path: Path) -> None:
    async def run() -> None:
        data = _copy_data(tmp_path)
        clock = Clock(datetime(2026, 11, 12, 12, tzinfo=timezone.utc))
        runtime = create_runtime(data_dir=data, clock=clock)
        user = "void-supply"

        async def send(operation: str, command: str, *, op_id: str | None = None):
            return await runtime.dispatch(_context(user, operation, operation_id=op_id), command)

        try:
            assert (await send("create", "开始修仙")).ok
            assert (await send("seek", "寻仙问道")).ok
            player_id = _seed_archive_return(runtime, user, clock)
            help_explore = await send("help-explore", "修仙帮助 探索")
            assert "虚空第一航道" in help_explore.message and "虚空航道历练" in help_explore.message
            help_life = await send("help-life", "修仙帮助 生活")
            assert "虚空补给看守" in help_life.message and "十二小时" in help_life.message

            assert (await send("start-1", "开始虚空档案主线 补给再临")).code == "MAINLINE_STARTED"
            early = await send("early-1", "领取虚空档案主线奖励 补给再临")
            assert early.code == "MAINLINE_OBJECTIVES_INCOMPLETE"
            _edit_story(
                data,
                lambda rows: rows[PREFIX + "1"]["first_clear_reward"].update({"spirit_stones": 999}),
            )
            await runtime.close()
            runtime = create_runtime(data_dir=data, clock=clock)
            travel = await send("travel", "前往 虚空第一航道")
            assert travel.code == "TRAVEL_STARTED", travel.message
            with runtime.repository._connect() as connection:
                set_travel_end_at(connection, travel.data["session_id"], (clock() - timedelta(seconds=1)).isoformat())
            assert (await send("travel-settle", "结算移动")).code == "TRAVEL_COMPLETED"
            claim_one = await send("claim-1", "领取虚空档案主线奖励 补给再临")
            assert claim_one.code == "MAINLINE_REWARD_CLAIMED"
            assert claim_one.data["reward"]["spirit_stones"] == 20

            # A complete assignment before stage 2 starts is deliberately stale evidence.
            old_idle = await send("old-idle", "开始挂机 虚空补给看守")
            assert old_idle.code == "IDLE_STARTED", old_idle.message
            clock.advance(hours=12)
            assert (await send("old-idle-claim", "领取挂机")).data["fallback"] is False
            clock.advance(days=1)
            assert (await send("start-2", "开始虚空档案主线 航道值守")).code == "MAINLINE_STARTED"
            stale = await send("claim-2-stale", "领取虚空档案主线奖励 航道值守")
            assert stale.code == "MAINLINE_OBJECTIVES_INCOMPLETE"
            with runtime.repository._connect() as connection:
                assert connection.execute("SELECT status FROM mainline_runs WHERE player_id=? AND stage_key=?", (player_id, PREFIX + "2")).fetchone()[0] == "running"

            current_idle = await send("current-idle", "开始挂机 虚空补给看守")
            assert current_idle.code == "IDLE_STARTED", current_idle.message
            clock.advance(hours=12)
            claimed_idle = await send("current-idle-claim", "领取挂机")
            assert claimed_idle.code == "IDLE_CLAIMED" and claimed_idle.data["fallback"] is False
            assert claimed_idle.data["reward"]["item.token.construction_coupon"] >= 1
            assert (await send("claim-2", "领取虚空档案主线奖励 航道值守")).code == "MAINLINE_REWARD_CLAIMED"

            assert (await send("start-3", "开始虚空档案主线 锚点回响")).code == "MAINLINE_STARTED"
            seed = _reward_operation(runtime.content, "void-supply-anchor")
            explored = await send(seed, "开始探索 虚空航道历练", op_id=seed)
            assert explored.code == "EXPLORATION_STARTED", explored.message
            clock.advance(seconds=901)
            settled = await send("explore-settle", "结算探索")
            assert settled.code == "EXPLORATION_SETTLED", settled.message
            assert settled.data["result"].get("item.void_anchor", 0) >= 1
            claimed = await send("claim-3", "领取虚空档案主线奖励 锚点回响")
            assert claimed.code == "MAINLINE_REWARD_CLAIMED", claimed.message
            replay = await send("claim-3-replay", "领取虚空档案主线奖励 锚点回响", op_id="claim-3")
            assert replay.data["idempotent_replay"] is True
        finally:
            await runtime.close()

    asyncio.run(run())


def test_void_supply_epilogue_rejects_partial_and_expired_idle_claims(tmp_path: Path) -> None:
    async def run() -> None:
        data = _copy_data(tmp_path)
        clock = Clock(datetime(2026, 11, 14, 12, tzinfo=timezone.utc))
        runtime = create_runtime(data_dir=data, clock=clock)
        user = "void-supply-idle-boundaries"

        async def send(operation: str, command: str):
            return await runtime.dispatch(_context(user, operation), command)

        try:
            assert (await send("create", "开始修仙")).ok
            assert (await send("seek", "寻仙问道")).ok
            _seed_archive_return(runtime, user, clock)
            assert (await send("start-1", "开始虚空档案主线 补给再临")).code == "MAINLINE_STARTED"
            travel = await send("travel", "前往 虚空第一航道")
            assert travel.code == "TRAVEL_STARTED"
            with runtime.repository._connect() as connection:
                set_travel_end_at(connection, travel.data["session_id"], (clock() - timedelta(seconds=1)).isoformat())
            assert (await send("travel-settle", "结算移动")).code == "TRAVEL_COMPLETED"
            assert (await send("claim-1", "领取虚空档案主线奖励 补给再临")).code == "MAINLINE_REWARD_CLAIMED"
            assert (await send("start-2", "开始虚空档案主线 航道值守")).code == "MAINLINE_STARTED"

            started = await send("idle", "开始挂机 虚空补给看守")
            assert started.code == "IDLE_STARTED"
            clock.advance(hours=1)
            early = await send("early", "领取挂机")
            assert early.code == "IDLE_CLAIM_TOO_EARLY"
            with runtime.repository._connect() as connection:
                assert connection.execute("SELECT 1 FROM operations WHERE operation_id='early'").fetchone() is None

            clock.advance(hours=36)
            late = await send("late", "领取挂机")
            assert late.code == "IDLE_CLAIMED" and late.data["fallback"] is True
            incomplete = await send("claim-2", "领取虚空档案主线奖励 航道值守")
            assert incomplete.code == "MAINLINE_OBJECTIVES_INCOMPLETE"
        finally:
            await runtime.close()

    asyncio.run(run())
