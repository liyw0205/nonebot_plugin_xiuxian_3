from __future__ import annotations

import asyncio
import json
from pathlib import Path
from urllib.parse import quote

import pytest

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.adventures.mainline import (
    BASALT_WAYMARKER_STORY_KEY,
    mainline_definitions,
)
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError

from test_mainline_vertical_slice import MutableClock, _copy_content


def _context(adapter: str, user: str, operation: str) -> CommandContext:
    return CommandContext(
        adapter=adapter,
        user_id=user,
        request_id=operation,
        operation_id=operation,
        capabilities=("text", "markdown", "keyboard"),
    )


def test_basalt_waymarker_contract_rejects_missing_sources_and_preserves_frozen_json(tmp_path: Path) -> None:
    data = _copy_content(tmp_path)
    bundle = ContentBundle.load(data)
    definitions = mainline_definitions(bundle, story_key=BASALT_WAYMARKER_STORY_KEY)
    assert [stage.key for stage in definitions] == [f"basalt_waymarker.{i}" for i in (1, 2, 3)]
    assert definitions[0].objectives[0]["destination_key"] == "xuantian.basalt_pass"
    assert definitions[1].objectives[0]["route_key"] == "idle.basalt_sifting"
    assert definitions[2].objectives[0]["dispatch_key"] == "dispatch.basalt_watermark_works"
    assert all(len(stage.body) >= 80 and stage.actions and stage.retry_message for stage in definitions)

    path = data / "剧情" / "主线.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    row = next(row for row in document["records"] if row["key"] == "basalt_waymarker.3")
    row["objectives"][0]["dispatch_key"] = "dispatch.missing"
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ContentError, match="unknown dispatch"):
        mainline_definitions(ContentBundle.load(data), story_key=BASALT_WAYMARKER_STORY_KEY)


@pytest.mark.parametrize("adapter", ["onebot.v11", "qq.official"])
def test_basalt_waymarker_real_journey_restart_boundaries_and_replay(tmp_path, monkeypatch, adapter: str) -> None:
    outcome = {"value": "success"}
    monkeypatch.setattr(
        "nonebot_plugin_xiuxian_3.xiuxian.specials.dispatch_repository.choose_outcome",
        lambda *_: outcome["value"],
    )

    async def run() -> None:
        data = _copy_content(tmp_path)
        clock = MutableClock()
        user = f"basalt-{adapter}"
        runtime = create_runtime(data_dir=data, clock=clock, adapters=(adapter,))

        async def send(operation: str, command: str, *, who: str = user):
            return await runtime.dispatch(_context(adapter, who, operation), command)

        async def move_to_basalt(prefix: str) -> None:
            started = await send(f"{prefix}-outskirts", "前往 近郊")
            assert started.code == "TRAVEL_STARTED", started.message
            clock.advance(minutes=3)
            assert (await send(f"{prefix}-outskirts-settle", "结算移动")).code == "TRAVEL_COMPLETED"
            started = await send(f"{prefix}-basalt", "前往 玄武岩径")
            assert started.code == "TRAVEL_STARTED", started.message
            clock.advance(minutes=3)
            assert (await send(f"{prefix}-basalt-settle", "结算移动")).code == "TRAVEL_COMPLETED"

        async def restart() -> None:
            nonlocal runtime
            await runtime.close()
            runtime = create_runtime(data_dir=data, clock=clock, adapters=(adapter,))
            await runtime.repository.initialize()

        try:
            assert (await send("create", "开始修仙")).ok
            assert (await send("seek", "寻仙问道")).ok
            for command in ("完成引导 阅读", "前往近郊", "完成引导 采集", "完成引导 炼丹", "选择道途 器修"):
                assert (await send(f"guide-{command}", command)).ok, command
            with runtime.repository._connect() as connection:
                connection.execute(
                    "UPDATE players SET realm_key='qi_gathering', realm_layer=1, location_key='xuantian.new_town' "
                    "WHERE platform=? AND platform_user_id=?",
                    (adapter, user),
                )

            # A journey settled before the stage starts is deliberately stale.
            await move_to_basalt("old")
            old_start = await send("old-stage-travel", "开始玄武岩径水标回响主线 水标入径")
            assert old_start.code == "MAINLINE_STARTED", old_start.message
            # The old journey was completed before start, so this is still incomplete.
            assert (await send("old-claim", "领取玄武岩径水标回响主线奖励 水标入径")).code == "MAINLINE_OBJECTIVES_INCOMPLETE"
            await move_to_basalt("new")
            first = await send("first-claim", "领取玄武岩径水标回响主线奖励 水标入径")
            assert first.code == "MAINLINE_REWARD_CLAIMED", first.message
            assert first.data["next_stage_key"] == "basalt_waymarker.2"

            # Build a pre-stage idle record, then prove it is excluded by the snapshot baseline.
            old_idle = await send("old-idle-start", "开始挂机 玄武岩径筛砂")
            assert old_idle.code == "IDLE_STARTED", old_idle.message
            clock.advance(hours=8)
            assert (await send("old-idle-claim", "领取挂机")).code == "IDLE_CLAIMED"
            clock.advance(days=1)
            second = await send("second-start", "开始玄武岩径水标回响主线 筛砂留线")
            assert second.code == "MAINLINE_STARTED", second.message
            assert (await send("old-idle-story", "领取玄武岩径水标回响主线奖励 筛砂留线")).code == "MAINLINE_OBJECTIVES_INCOMPLETE"

            cancelled = await send("cancel-start", "开始挂机 玄武岩径筛砂")
            assert cancelled.code == "IDLE_STARTED"
            assert (await send("cancel", "取消挂机")).code == "IDLE_CANCELLED"
            assert (await send("cancel-story", "领取玄武岩径水标回响主线奖励 筛砂留线")).code == "MAINLINE_OBJECTIVES_INCOMPLETE"

            clock.advance(days=1)
            expired = await send("expired-start", "开始挂机 玄武岩径筛砂")
            assert expired.code == "IDLE_STARTED"
            clock.advance(hours=33)
            late = await send("expired-claim", "领取挂机")
            assert late.code == "IDLE_CLAIMED" and late.data["fallback"] is True
            assert (await send("expired-story", "领取玄武岩径水标回响主线奖励 筛砂留线")).code == "MAINLINE_OBJECTIVES_INCOMPLETE"

            clock.advance(days=1)
            full = await send("full-start", "开始挂机 玄武岩径筛砂")
            assert full.code == "IDLE_STARTED"
            clock.advance(hours=8)
            await restart()
            status = await send("idle-status", "挂机状态")
            assert status.code == "IDLE_STATUS"
            claimed = await send("full-claim", "领取挂机")
            assert claimed.code == "IDLE_CLAIMED" and claimed.data["fallback"] is False
            replay_idle = await send("full-claim", "领取挂机")
            assert replay_idle.data["idempotent_replay"] is True
            stage_two = await send("second-claim", "领取玄武岩径水标回响主线奖励 筛砂留线")
            assert stage_two.code == "MAINLINE_REWARD_CLAIMED"

            # A success from before stage 3 starts must not satisfy the dispatch objective.
            assert (await send("recover-before-dispatch", "恢复状态")).ok
            with runtime.repository._connect() as connection:
                connection.execute(
                    "UPDATE players SET stamina=stamina_max, energy=energy_max WHERE platform=? AND platform_user_id=?",
                    (adapter, user),
                )
            old_dispatch = await send("old-dispatch", "接受派遣 玄武岩径水标勘务 踏勘")
            assert old_dispatch.code == "DISPATCH_ACCEPTED", old_dispatch.message
            third = await send("third-start", "开始玄武岩径水标回响主线 水标回响")
            assert third.code == "MAINLINE_STARTED", third.message
            clock.advance(hours=2)
            old_settle = await send("old-settle", "结算派遣")
            assert old_settle.data["outcome"] == "success"
            assert (await send("old-dispatch-story", "领取玄武岩径水标回响主线奖励 水标回响")).code == "MAINLINE_OBJECTIVES_INCOMPLETE"

            clock.advance(days=1)
            outcome["value"] = "partial"
            assert (await send("recover-partial", "恢复状态")).ok
            with runtime.repository._connect() as connection:
                connection.execute(
                    "UPDATE players SET stamina=stamina_max, energy=energy_max WHERE platform=? AND platform_user_id=?",
                    (adapter, user),
                )
            partial_dispatch = await send("partial-dispatch", "接受派遣 玄武岩径水标勘务 踏勘")
            assert partial_dispatch.code == "DISPATCH_ACCEPTED", partial_dispatch.message
            clock.advance(hours=2)
            partial = await send("partial-settle", "结算派遣")
            assert partial.data["outcome"] == "partial"
            assert (await send("partial-story", "领取玄武岩径水标回响主线奖励 水标回响")).code == "MAINLINE_OBJECTIVES_INCOMPLETE"

            clock.advance(days=1)
            outcome["value"] = "success"
            assert (await send("recover-success", "恢复状态")).ok
            with runtime.repository._connect() as connection:
                connection.execute(
                    "UPDATE players SET stamina=stamina_max, energy=energy_max WHERE platform=? AND platform_user_id=?",
                    (adapter, user),
                )
            new_dispatch = await send("new-dispatch", "接受派遣 玄武岩径水标勘务 踏勘")
            assert new_dispatch.code == "DISPATCH_ACCEPTED", new_dispatch.message
            clock.advance(hours=2)
            await restart()
            assert (await send("dispatch-status", "派遣状态")).code == "DISPATCH_STATUS"
            settled = await send("new-settle", "结算派遣")
            assert settled.code == "DISPATCH_SETTLED" and settled.data["outcome"] == "success"
            reward = await send("third-claim", "领取玄武岩径水标回响主线奖励 水标回响")
            assert reward.code == "MAINLINE_REWARD_CLAIMED"
            replay = await send("third-claim", "领取玄武岩径水标回响主线奖励 水标回响")
            assert replay.data["idempotent_replay"] is True

            # A different player’s records never satisfy this player’s snapshot.
            assert (await send("other-create", "开始修仙", who="other-basalt")).ok
            with runtime.repository._connect() as connection:
                events = [row["event_key"] for row in connection.execute("SELECT event_key FROM activity_events").fetchall()]
            assert "story.mainline.basalt_waymarker:basalt_waymarker.3" in events

            help_result = await send("help", "修仙帮助 生活")
            assert help_result.ok and "玄武岩径水标回响主线" in help_result.message
            assert "开始挂机 玄武岩径筛砂" in help_result.message
        finally:
            await runtime.close()

    asyncio.run(run())


def test_basalt_waymarker_message_actions_render_for_qq_and_plain_text(monkeypatch, tmp_path: Path) -> None:
    async def run() -> None:
        data = _copy_content(tmp_path)
        runtime = create_runtime(data_dir=data, adapters=("qq.official", "onebot.v11"))
        try:
            result = await runtime.dispatch(_context("qq.official", "render-basalt", "start"), "开始修仙")
            assert result.ok
            result = await runtime.dispatch(_context("qq.official", "render-basalt", "help"), "修仙帮助 探索")
            assert result.ok and "玄武岩径水标回响主线" in result.message
            from nonebot_plugin_xiuxian_3.adapters.message.markdown import _qq_command_links, markdown_to_text

            converted = _qq_command_links(result.message, command_prefix="!")
            assert quote("!玄武岩径水标回响主线", safe="") in converted
            assert "enter=false" in converted
            assert "command:" not in markdown_to_text(result.message)
            result = await runtime.dispatch(
                _context("qq.official", "render-basalt", "story"),
                "开始玄武岩径水标回响主线 水标入径",
            )
            assert result.code == "MAINLINE_REQUIREMENT_MISSING"
            # The adapter-neutral error remains diagnostic on both adapters.
            onebot = await runtime.dispatch(
                _context("onebot.v11", "missing-basalt", "story"),
                "开始玄武岩径水标回响主线 水标入径",
            )
            assert onebot.code == "PLAYER_NOT_FOUND"
            assert "开始修仙" in onebot.message
        finally:
            await runtime.close()

    asyncio.run(run())
