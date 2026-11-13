from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from urllib.parse import quote, unquote

import pytest

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


def _inventory(runtime) -> dict[str, int]:
    with runtime.repository._connect() as connection:
        return json.loads(connection.execute("SELECT inventory_json FROM players").fetchone()[0])


def _database_state(runtime) -> tuple[str, ...]:
    with runtime.repository._connect() as connection:
        return tuple(connection.iterdump())


async def _assert_delivery(result, monkeypatch) -> None:
    from nonebot_plugin_xiuxian_3.adapters.message import markdown, qq

    class Bot:
        async def send(self, event, message, **kwargs):
            self.message = message
            return {"id": "reply"}

    keyboards = []

    def keyboard(rows, *, command_prefix=""):
        keyboards.append((rows, command_prefix))
        return "\n<keyboard>"

    monkeypatch.setattr(qq, "qq_keyboard", keyboard)
    monkeypatch.setattr(
        markdown, "qq_markdown_segment",
        lambda body, command_prefix="": markdown._qq_command_links(body, command_prefix=command_prefix),
    )
    bot = Bot()
    sent = await markdown.send_markdown_message(
        bot, object(), result.message, capabilities=("markdown", "keyboard"),
        actions=result.actions, command_prefix="!",
    )
    assert sent.sent_format == ("markdown+keyboard" if result.actions else "markdown")
    if result.actions:
        assert keyboards == [((result.actions,), "!")]
        assert all(action.enter for action in result.actions)
        assert all(action.command not in result.message for action in result.actions)
    else:
        assert not keyboards
        commands = [unquote(value) for value in re.findall(r"\]\(command:([^)]+)\)", result.message)]
        assert commands and all("<" not in command for command in commands)
        assert all(quote("!" + command, safe="") in bot.message for command in commands)
        assert "enter=false" in bot.message
    plain_bot = Bot()
    sent = await markdown.send_markdown_message(plain_bot, object(), result.message, actions=result.actions)
    assert sent.sent_format == "text"
    assert "command:" not in plain_bot.message and "mqqapi:" not in plain_bot.message
    assert "灵兽旧兽道" in plain_bot.message


def test_companion_old_trail_mainline_is_real_and_survives_restart(tmp_path: Path, monkeypatch) -> None:
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
            denied = await send("trail-locked", "开始灵兽旧兽道回响主线 近郊结缘")
            assert denied.code == "MAINLINE_REQUIREMENT_MISSING"
            with runtime.repository._connect() as connection:
                player = connection.execute("SELECT * FROM players").fetchone()
                for event_key in (
                    "story.mainline.xuantian:chapter.1.stage.1",
                    "story.mainline.void_archive.time_fort",
                ):
                    connection.execute(
                        "INSERT INTO activity_events(player_id,event_key,source_operation_id,occurred_at) "
                        "VALUES (?,?,?,?)",
                        (player["id"], event_key, "stale-projection", clock().isoformat()),
                    )
                evidence = runtime.repository._mainline_completed_events(connection, player, now=clock())
                assert "story.mainline.xuantian:chapter.1.stage.1" not in evidence
                assert "story.mainline.void_archive.time_fort" not in evidence
            assert (await send("trail-projected", "开始灵兽旧兽道回响主线 近郊结缘")).code == "MAINLINE_REQUIREMENT_MISSING"
            assert (await send("chapter-start", "开始主线 初入玄天")).ok
            travel = await send("travel-start", "前往 近郊")
            assert travel.code == "TRAVEL_STARTED", travel.message
            clock.advance(seconds=30)
            assert (await send("travel-settle", "结算移动")).code == "TRAVEL_COMPLETED"
            assert (await send("chapter-claim", "领取主线奖励 初入玄天")).code == "MAINLINE_REWARD_CLAIMED"

            # This is a real source operation, but it predates the old-trail run.
            old_bond = await send("old-bond", "结缘灵兽 木鼠")
            assert old_bond.code == "COMPANION_BONDED", old_bond.message
            old_instance = str(old_bond.data["instance_id"])
            initial_rice = _inventory(runtime)["item.food.coarse_spirit_rice"]
            assert initial_rice > 0
            for index in range(initial_rice):
                assert (await send(f"old-feed-{index}", f"喂养灵兽 {old_instance}")).code == "COMPANION_FED"
            assert _inventory(runtime).get("item.food.coarse_spirit_rice", 0) == 0
            started = await send("trail-1-start", "开始灵兽旧兽道回响主线 近郊结缘")
            assert started.code == "MAINLINE_STARTED", started.message
            assert "结缘灵兽" in started.message and "command:" in started.message
            early = await send("trail-1-old-claim", "领取灵兽旧兽道回响主线奖励 近郊结缘")
            assert early.code == "MAINLINE_OBJECTIVES_INCOMPLETE"

            fresh_bond = await send("fresh-bond", "结缘灵兽 木鼠")
            assert fresh_bond.code == "COMPANION_BONDED", fresh_bond.message
            stage_one = await send("trail-1-claim", "领取灵兽旧兽道回响主线奖励 近郊结缘")
            assert stage_one.code == "MAINLINE_REWARD_CLAIMED", stage_one.message
            await _assert_delivery(stage_one, monkeypatch)

            stage_two = await send("trail-2-start", "开始灵兽旧兽道回响主线 四时巡护")
            assert stage_two.code == "MAINLINE_STARTED", stage_two.message
            await _assert_delivery(stage_two, monkeypatch)
            instance_id = str(fresh_bond.data["instance_id"])
            status = await send("companions", "灵兽状态")
            assert instance_id in status.message
            assert quote(f"喂养灵兽 {instance_id}", safe="") in status.message
            preview = await send("patrol-preview", "挂机预览 灵兽栖地巡护")
            assert preview.data["routes"][0]["ready"]
            patrol = await send("patrol-start", f"开始挂机 灵兽栖地巡护 {instance_id}")
            assert patrol.code == "IDLE_STARTED", patrol.message
            cancelled = await send("patrol-cancel", "取消挂机")
            assert cancelled.code == "IDLE_CANCELLED", cancelled.message
            assert (await send("trail-2-cancel", "领取灵兽旧兽道回响主线奖励 四时巡护")).code == "MAINLINE_OBJECTIVES_INCOMPLETE"
            with runtime.repository._connect() as connection:
                assert connection.execute(
                    "SELECT status FROM idle_assignments WHERE assignment_id=?", (patrol.data["assignment_id"],)
                ).fetchone()[0] == "cancelled"
            retry_patrol = await send("patrol-retry", f"开始挂机 灵兽栖地巡护 {instance_id}")
            assert retry_patrol.code == "IDLE_STARTED", retry_patrol.message
            assert (await send("trail-2-running", "领取灵兽旧兽道回响主线奖励 四时巡护")).code == "MAINLINE_OBJECTIVES_INCOMPLETE"
            clock.advance(hours=29)
            late = await send("patrol-late", "领取挂机")
            assert late.code == "IDLE_CLAIMED" and late.data["fallback"]
            assert _inventory(runtime).get("item.food.coarse_spirit_rice", 0) == 0
            assert (await send("trail-2-late", "领取灵兽旧兽道回响主线奖励 四时巡护")).code == "MAINLINE_OBJECTIVES_INCOMPLETE"
            assert (await send("patrol-full", f"开始挂机 灵兽栖地巡护 {instance_id}")).code == "IDLE_STARTED"
            clock.advance(hours=4)
            await runtime.close()

            runtime = create_runtime(data_dir=data_dir, clock=clock, adapters=("onebot.v11",))
            settled = await send("patrol-claim", "领取挂机")
            assert settled.code == "IDLE_CLAIMED", settled.message
            assert settled.data["fallback"] is False
            assert settled.data["reward"]["item.food.coarse_spirit_rice"] >= 1
            assert _inventory(runtime)["item.food.coarse_spirit_rice"] == settled.data["reward"]["item.food.coarse_spirit_rice"]
            assert (await send("patrol-claim", "领取挂机")).data["idempotent_replay"] is True
            stage_two_claim = await send("trail-2-claim", "领取灵兽旧兽道回响主线奖励 四时巡护")
            assert stage_two_claim.code == "MAINLINE_REWARD_CLAIMED", stage_two_claim.message
            for index in range(_inventory(runtime)["item.food.coarse_spirit_rice"]):
                assert (await send(f"before-stage-3-feed-{index}", f"喂养灵兽 {instance_id}")).code == "COMPANION_FED"

            stage_three = await send("trail-3-start", "开始灵兽旧兽道回响主线 灵米喂伴")
            assert stage_three.code == "MAINLINE_STARTED", stage_three.message
            await _assert_delivery(stage_three, monkeypatch)
            missing = await send("trail-3-early", "领取灵兽旧兽道回响主线奖励 灵米喂伴")
            assert missing.code == "MAINLINE_OBJECTIVES_INCOMPLETE"
            before_missing = _database_state(runtime)
            assert (await send("feed", f"喂养灵兽 {instance_id}")).code == "COMPANION_FEED_INSUFFICIENT"
            assert _database_state(runtime) == before_missing
            clock.advance(days=1)
            assert (await send("resupply", f"开始挂机 灵兽栖地巡护 {instance_id}")).code == "IDLE_STARTED"
            assert (await send("feed-busy", f"喂养灵兽 {instance_id}")).code == "COMPANION_BUSY"
            clock.advance(hours=4)
            assert (await send("resupply-claim", "领取挂机")).code == "IDLE_CLAIMED"
            with runtime.repository._connect() as connection:
                connection.execute(
                    "CREATE TRIGGER fail_old_trail_feed BEFORE INSERT ON operations "
                    "WHEN NEW.operation_id='feed' BEGIN SELECT RAISE(ABORT, 'forced feed failure'); END"
                )
            before_feed = _database_state(runtime)
            assert (await send("feed", f"喂养灵兽 {instance_id}")).code == "PERSISTENCE_ERROR"
            assert _database_state(runtime) == before_feed
            assert (await send("trail-3-failed-feed", "领取灵兽旧兽道回响主线奖励 灵米喂伴")).code == "MAINLINE_OBJECTIVES_INCOMPLETE"
            with runtime.repository._connect() as connection:
                connection.execute("DROP TRIGGER fail_old_trail_feed")
            await runtime.close()
            runtime = create_runtime(data_dir=data_dir, clock=clock, adapters=("onebot.v11",))
            fed = await send("feed", f"喂养灵兽 {instance_id}")
            assert fed.code == "COMPANION_FED", fed.message
            assert fed.data["spent"] == {"item.food.coarse_spirit_rice": 1}
            after_feed = _database_state(runtime)
            assert (await send("feed", f"喂养灵兽 {instance_id}")).data["idempotent_replay"]
            assert _database_state(runtime) == after_feed

            with runtime.repository._connect() as connection:
                connection.execute(
                    "CREATE TRIGGER fail_old_trail_claim BEFORE INSERT ON operations "
                    "WHEN NEW.operation_id='trail-3-claim' BEGIN SELECT RAISE(ABORT, 'forced old trail claim failure'); END"
                )
            before_claim = _database_state(runtime)
            failed = await send("trail-3-claim", "领取灵兽旧兽道回响主线奖励 灵米喂伴")
            assert failed.code == "PERSISTENCE_ERROR", failed.message
            assert _database_state(runtime) == before_claim
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
            after_claim = _database_state(runtime)
            duplicate = await send("trail-3-claim-new-id", "领取灵兽旧兽道回响主线奖励 灵米喂伴")
            assert duplicate.data["idempotent_replay"]
            assert duplicate.data["reward"] == claimed.data["reward"]
            assert _database_state(runtime) == after_claim
        finally:
            await runtime.close()

    asyncio.run(run())


def test_old_trail_existing_companion_choice_at_capacity_is_public_and_persisted(tmp_path: Path) -> None:
    async def run() -> None:
        clock = MutableClock()
        runtime = create_runtime(data_dir=_copy_content(tmp_path), clock=clock, adapters=("qq.official",))

        async def send(operation: str, command: str):
            context = CommandContext(adapter="qq.official", user_id="full-companions", operation_id=operation)
            return await runtime.dispatch(context, command)

        try:
            assert (await send("create", "开始修仙")).ok
            assert (await send("seek", "寻仙问道")).ok
            assert (await send("chapter", "开始主线 初入玄天")).ok
            assert (await send("travel", "前往 近郊")).code == "TRAVEL_STARTED"
            clock.advance(seconds=30)
            assert (await send("arrival", "结算移动")).code == "TRAVEL_COMPLETED"
            assert (await send("chapter-claim", "领取主线奖励 初入玄天")).code == "MAINLINE_REWARD_CLAIMED"
            for index in range(3):
                bonded = await send(f"bond-{index}", "结缘灵兽 木鼠")
                assert bonded.code == "COMPANION_BONDED"
            instance = bonded.data["instance_id"]
            assert (await send("company-old", f"灵兽相伴 {instance}")).code == "COMPANION_COMPANIED"
            assert (await send("start", "开始灵兽旧兽道回响主线 近郊结缘")).code == "MAINLINE_STARTED"
            assert (await send("old-claim", "领取灵兽旧兽道回响主线奖励 近郊结缘")).code == "MAINLINE_OBJECTIVES_INCOMPLETE"
            assert (await send("full", "结缘灵兽 木鼠")).code == "COMPANION_CAPACITY"
            assert (await send("company", f"灵兽相伴 {instance}")).code == "COMPANION_COMPANY_SPENT"
            clock.advance(days=1)
            await runtime.close()
            runtime = create_runtime(data_dir=tmp_path / "data", clock=clock, adapters=("qq.official",))
            status = await send("status", "灵兽旧兽道回响主线")
            assert status.data["stages"][0]["status"] == "running" and not status.actions
            before = (await send("before", "灵兽状态")).data["companions"]
            assert (await send("company", f"灵兽相伴 {instance}")).code == "COMPANION_COMPANIED"
            after = (await send("after", "灵兽状态")).data["companions"]
            assert len(after) == len(before) == 3
            assert after[-1]["affinity"] > before[-1]["affinity"]
            assert (await send("claim", "领取灵兽旧兽道回响主线奖励 近郊结缘")).code == "MAINLINE_REWARD_CLAIMED"
        finally:
            await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("candidate", ["mount.bamboo_deer", "beast.missing", "beast.wood_rat"])
def test_old_trail_companion_alternatives_reject_invalid_references(tmp_path: Path, candidate: str) -> None:
    data_dir = _copy_content(tmp_path)
    path = data_dir / "剧情" / "主线.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    stage = next(row for row in document["records"] if row["key"] == "companion_old_trail.3")
    stage["objectives"][0]["alternate_companion_keys"] = [candidate]
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ContentError):
        mainline_definitions(ContentBundle.load(data_dir), story_key=COMPANION_OLD_TRAIL_STORY_KEY)
