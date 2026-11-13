from __future__ import annotations

import asyncio
import json
from pathlib import Path

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.adventures.mainline import (
    COMPANION_OLD_TRAIL_STORY_KEY,
    mainline_definitions,
)
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError

from test_mainline_vertical_slice import MutableClock, _copy_content


def test_old_trail_feed_requires_every_patrol_outcome_to_produce_the_real_item(tmp_path: Path) -> None:
    data_dir = _copy_content(tmp_path)
    reward_path = data_dir / "奖励" / "奖励.json"
    document = json.loads(reward_path.read_text(encoding="utf-8"))
    pool = next(row for row in document["records"] if row["key"] == "reward_pool.idle.beast_habitat_patrol")
    pool["outcomes"][0]["rewards"].pop("item.food.coarse_spirit_rice")
    reward_path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    try:
        mainline_definitions(ContentBundle.load(data_dir), story_key=COMPANION_OLD_TRAIL_STORY_KEY)
    except ContentError as exc:
        assert "not guaranteed" in str(exc)
    else:
        raise AssertionError("a patrol outcome without feed rice must reject the story contract")


def _context(user: str, operation: str) -> CommandContext:
    return CommandContext(
        adapter="onebot.v11",
        user_id=user,
        request_id=operation,
        operation_id=operation,
        capabilities=("text",),
    )


def test_companion_old_trail_mainline_is_real_and_survives_restart(tmp_path: Path) -> None:
    async def run() -> None:
        data_dir = _copy_content(tmp_path)
        clock = MutableClock()
        user = "companion-old-trail"
        runtime = create_runtime(data_dir=data_dir, clock=clock, adapters=("onebot.v11",))

        async def send(operation: str, command: str):
            return await runtime.dispatch(_context(user, operation), command)

        try:
            assert (await send("create", "开始修仙")).ok
            assert (await send("seek", "寻仙问道")).ok
            assert (await send("chapter-start", "开始主线 初入玄天")).ok
            travel = await send("travel-start", "前往 近郊")
            assert travel.code == "TRAVEL_STARTED", travel.message
            clock.advance(seconds=30)
            assert (await send("travel-settle", "结算移动")).code == "TRAVEL_COMPLETED"
            assert (await send("chapter-claim", "领取主线奖励 初入玄天")).code == "MAINLINE_REWARD_CLAIMED"

            # This is a real source operation, but it predates the old-trail run.
            old_bond = await send("old-bond", "结缘灵兽 beast.wood_rat")
            assert old_bond.code == "COMPANION_BONDED", old_bond.message
            started = await send("trail-1-start", "开始灵兽旧兽道回响主线 近郊结缘")
            assert started.code == "MAINLINE_STARTED", started.message
            assert "结缘灵兽" in started.message and "command:" in started.message
            early = await send("trail-1-old-claim", "领取灵兽旧兽道回响主线奖励 近郊结缘")
            assert early.code == "MAINLINE_OBJECTIVES_INCOMPLETE"

            fresh_bond = await send("fresh-bond", "结缘灵兽 beast.wood_rat")
            assert fresh_bond.code == "COMPANION_BONDED", fresh_bond.message
            stage_one = await send("trail-1-claim", "领取灵兽旧兽道回响主线奖励 近郊结缘")
            assert stage_one.code == "MAINLINE_REWARD_CLAIMED", stage_one.message

            stage_two = await send("trail-2-start", "开始灵兽旧兽道回响主线 四时巡护")
            assert stage_two.code == "MAINLINE_STARTED", stage_two.message
            instance_id = str(fresh_bond.data["instance_id"])
            patrol = await send("patrol-start", f"开始挂机 灵兽栖地巡护 {instance_id}")
            assert patrol.code == "IDLE_STARTED", patrol.message
            cancelled = await send("patrol-cancel", "取消挂机")
            assert cancelled.code == "IDLE_CANCELLED", cancelled.message
            with runtime.repository._connect() as connection:
                assert connection.execute(
                    "SELECT status FROM idle_assignments WHERE assignment_id=?", (patrol.data["assignment_id"],)
                ).fetchone()[0] == "cancelled"
            retry_patrol = await send("patrol-retry", f"开始挂机 灵兽栖地巡护 {instance_id}")
            assert retry_patrol.code == "IDLE_STARTED", retry_patrol.message
            clock.advance(hours=4)
            await runtime.close()

            runtime = create_runtime(data_dir=data_dir, clock=clock, adapters=("onebot.v11",))
            settled = await send("patrol-claim", "领取挂机")
            assert settled.code == "IDLE_CLAIMED", settled.message
            assert settled.data["fallback"] is False
            assert settled.data["reward"]["item.food.coarse_spirit_rice"] >= 1
            assert (await send("patrol-claim", "领取挂机")).data["idempotent_replay"] is True
            stage_two_claim = await send("trail-2-claim", "领取灵兽旧兽道回响主线奖励 四时巡护")
            assert stage_two_claim.code == "MAINLINE_REWARD_CLAIMED", stage_two_claim.message

            stage_three = await send("trail-3-start", "开始灵兽旧兽道回响主线 灵米喂伴")
            assert stage_three.code == "MAINLINE_STARTED", stage_three.message
            missing = await send("trail-3-early", "领取灵兽旧兽道回响主线奖励 灵米喂伴")
            assert missing.code == "MAINLINE_OBJECTIVES_INCOMPLETE"
            fed = await send("feed", f"喂养灵兽 {instance_id}")
            assert fed.code == "COMPANION_FED", fed.message

            with runtime.repository._connect() as connection:
                connection.execute(
                    "CREATE TRIGGER fail_old_trail_claim BEFORE INSERT ON operations "
                    "WHEN NEW.operation_id='trail-3-claim' BEGIN SELECT RAISE(ABORT, 'forced old trail claim failure'); END"
                )
            failed = await send("trail-3-claim", "领取灵兽旧兽道回响主线奖励 灵米喂伴")
            assert failed.code == "PERSISTENCE_ERROR", failed.message
            with runtime.repository._connect() as connection:
                assert connection.execute(
                    "SELECT status FROM mainline_runs WHERE stage_key='companion_old_trail.3'"
                ).fetchone()[0] == "running"
                connection.execute("DROP TRIGGER fail_old_trail_claim")
            claimed = await send("trail-3-claim", "领取灵兽旧兽道回响主线奖励 灵米喂伴")
            assert claimed.code == "MAINLINE_REWARD_CLAIMED", claimed.message
            replay = await send("trail-3-claim", "领取灵兽旧兽道回响主线奖励 灵米喂伴")
            assert replay.data["idempotent_replay"] is True
            assert claimed.data["reward"]["service_reputation"] == 2
        finally:
            await runtime.close()

    asyncio.run(run())
