from __future__ import annotations

import asyncio
import json
import shutil
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from combat_fixtures import equip_damage_weapon
from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.adventures.mainline import (
    BEAST_HABITAT_ECHOES_STORY_KEY,
    mainline_definitions,
)
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle


ROOT = Path(__file__).parents[1]
ADAPTERS = ("qq.official", "onebot.v11")


class Clock:
    def __init__(self) -> None:
        self.value = datetime(2026, 11, 14, 8, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **kwargs: int) -> None:
        self.value += timedelta(**kwargs)


def _context(adapter: str, user: str, operation: str) -> CommandContext:
    return CommandContext(
        adapter=adapter,
        user_id=user,
        request_id=f"{adapter}:{user}:{operation}",
        operation_id=f"{adapter}:{user}:{operation}",
        can_write_assets=True,
    )


def _copy_data(tmp_path: Path) -> Path:
    content = tmp_path / "content"
    shutil.copytree(ROOT / "data", content)
    rewards_path = content / "奖励" / "奖励.json"
    rewards = json.loads(rewards_path.read_text(encoding="utf-8"))
    pool = next(row for row in rewards["records"] if row["key"] == "reward_pool.exploration.beast_hunt")
    pool["outcomes"] = [
        {"weight": 1000, "rewards": {"item.beast_blood": 1}},
        {"weight": 1, "rewards": {"item.clue.beast_bloodline": 1}},
        {"weight": 1, "rewards": {"faction_reputation.beast": 15}},
    ]
    rewards_path.write_text(json.dumps(rewards, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return content


def _prepare_player(runtime, adapter: str, user: str) -> None:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        row = connection.execute(
            "SELECT id FROM players WHERE platform=? AND platform_user_id=?", (adapter, user)
        ).fetchone()
        assert row is not None
        intro = {"flags": ["quest.beast_intro"]}
        connection.execute(
                "UPDATE players SET stage='cultivator', realm_key='nascent_soul', realm_layer=10, "
            "location_key='beast.ten_thousand_hills', stamina=200, stamina_max=200, "
            "spirit_stones=1500, faction_reputation_json=?, intro_json=?, max_hp=100000, initiative=100000 "
            "WHERE id=?",
            (json.dumps({"beast": 300}, sort_keys=True), json.dumps(intro, sort_keys=True), row[0]),
        )


def test_beast_habitat_echoes_content_and_real_chain_on_both_adapters(tmp_path: Path) -> None:
    content = _copy_data(tmp_path)
    definitions = mainline_definitions(ContentBundle.load(content), story_key=BEAST_HABITAT_ECHOES_STORY_KEY)
    assert [item.key for item in definitions] == [
        "beast_habitat_echoes.1",
        "beast_habitat_echoes.2",
        "beast_habitat_echoes.3",
    ]
    assert definitions[0].objectives[0]["destination_key"] == "beast.three_realms_trade_port"
    assert definitions[1].objectives[0]["item_key"] == "item.beast_blood"
    assert definitions[2].objectives[0]["route_key"] == "idle.beast_habitat_watch"
    assert all(len(item.body) >= 80 and item.actions and item.retry_message for item in definitions)

    async def run() -> None:
        clock = Clock()
        runtime = create_runtime(data_dir=content, clock=clock, adapters=ADAPTERS)
        try:
            for adapter in ADAPTERS:
                user = f"beast-habitat-{adapter}"

                async def send(operation: str, command: str):
                    return await runtime.adapters.dispatch(adapter, _context(adapter, user, operation), command)

                assert (await send("create", "开始修仙")).code == "PLAYER_CREATED"
                assert (await send("seek", "寻仙问道")).ok
                _prepare_player(runtime, adapter, user)
                help_result = await send("help", "修仙帮助 生活")
                assert "妖界栖地回响主线" in help_result.message

                locked = await send("locked", "开始妖界栖地回响主线 贸易口登记")
                assert locked.code == "MAINLINE_REQUIREMENT_MISSING"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    player_id = connection.execute(
                        "SELECT id FROM players WHERE platform=? AND platform_user_id=?", (adapter, user)
                    ).fetchone()[0]
                    row = connection.execute("SELECT intro_json FROM players WHERE id=?", (player_id,)).fetchone()
                    intro = json.loads(row[0])
                    intro["flags"] = sorted(set(intro.get("flags", [])) | {"access.beast_ten_thousand_hills"})
                    connection.execute("UPDATE players SET intro_json=? WHERE id=?", (json.dumps(intro), player_id))

                started = await send("stage-1-start", "开始妖界栖地回响主线 贸易口登记")
                assert started.code == "MAINLINE_STARTED", started.message
                early = await send("stage-1-early", "领取妖界栖地回响主线奖励 贸易口登记")
                assert early.code == "MAINLINE_OBJECTIVES_INCOMPLETE"
                travel = await send("to-port", "前往 三界贸易口")
                assert travel.code == "TRAVEL_STARTED", travel.message
                clock.advance(seconds=180)
                assert (await send("to-port-settle", "结算移动")).code == "TRAVEL_COMPLETED"
                assert (await send("stage-1-claim", "领取妖界栖地回响主线奖励 贸易口登记")).code == "MAINLINE_REWARD_CLAIMED"

                assert (await send("stage-2-start", "开始妖界栖地回响主线 夜巡取证")).code == "MAINLINE_STARTED"
                travel_back = await send("to-hills", "前往 万兽山入口")
                assert travel_back.code == "TRAVEL_STARTED", travel_back.message
                clock.advance(seconds=300)
                assert (await send("to-hills-settle", "结算移动")).code == "TRAVEL_COMPLETED"
                equip_damage_weapon(runtime, adapter, user, 50_000)
                explored = await send("hunt", "开始探索 万兽山狩猎")
                assert explored.code == "EXPLORATION_STARTED", explored.message
                clock.advance(minutes=20)
                settled = await send("hunt-settle", "结算探索")
                assert settled.code == "EXPLORATION_SETTLED", settled.message
                assert settled.data["result"].get("item.beast_blood", 0) >= 1
                assert (await send("stage-2-claim", "领取妖界栖地回响主线奖励 夜巡取证")).code == "MAINLINE_REWARD_CLAIMED"

                permit = await send("permit", "申请贸易许可 妖界")
                assert permit.code == "TRADE_PERMIT_ISSUED", permit.message
                assert datetime.fromisoformat(permit.data["expires_at"]) - datetime.fromisoformat(
                    permit.data["issued_at"]
                ) == timedelta(days=7)
                assert (await send("stage-3-start", "开始妖界栖地回响主线 妖界栖地夜值")).code == "MAINLINE_STARTED"
                assert (await send("preview", "挂机预览 妖界栖地")).data["routes"][0]["ready"] is True

                idle = await send("idle-cancelled", "开始挂机 妖界栖地")
                assert idle.code == "IDLE_STARTED"
                assert (await send("cancel", "取消挂机")).code == "IDLE_CANCELLED"
                assert (await send("after-cancel", "领取妖界栖地回响主线奖励 妖界栖地夜值")).code == "MAINLINE_OBJECTIVES_INCOMPLETE"

                clock.advance(days=1)
                late_start = await send("idle-late", "开始挂机 妖界栖地")
                assert late_start.code == "IDLE_STARTED"
                await runtime.close()
                runtime = create_runtime(data_dir=content, clock=clock, adapters=ADAPTERS)
                clock.advance(hours=35)
                late = await send("late-claim", "领取挂机")
                assert late.code == "IDLE_CLAIMED" and late.data["fallback"] is True
                assert (await send("after-late", "领取妖界栖地回响主线奖励 妖界栖地夜值")).code == "MAINLINE_OBJECTIVES_INCOMPLETE"

                clock.advance(days=1)
                full_start = await send("idle-full", "开始挂机 妖界栖地")
                assert full_start.code == "IDLE_STARTED"
                clock.advance(hours=8)
                full = await send("full-claim", "领取挂机")
                assert full.code == "IDLE_CLAIMED" and full.data["fallback"] is False
                claim_operation_id = f"{adapter}:{user}:stage-3-claim"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "CREATE TRIGGER fail_beast_habitat_mainline_claim BEFORE INSERT ON operations "
                        f"WHEN NEW.operation_id='{claim_operation_id}' "
                        "BEGIN SELECT RAISE(ABORT, 'forced habitat mainline claim failure'); END"
                    )
                failed = await send("stage-3-claim", "领取妖界栖地回响主线奖励 妖界栖地夜值")
                assert failed.code == "PERSISTENCE_ERROR"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    run_state = connection.execute(
                        "SELECT status, first_clear_claimed FROM mainline_runs "
                        "WHERE player_id=? AND stage_key='beast_habitat_echoes.3'",
                        (player_id,),
                    ).fetchone()
                    assert tuple(run_state) == ("running", 0)
                    assert connection.execute(
                        "SELECT 1 FROM activity_events WHERE player_id=? "
                        "AND event_key='story.mainline.beast_habitat_echoes:beast_habitat_echoes.3'",
                        (player_id,),
                    ).fetchone() is None
                    connection.execute("DROP TRIGGER fail_beast_habitat_mainline_claim")
                done = await send("stage-3-claim", "领取妖界栖地回响主线奖励 妖界栖地夜值")
                assert done.code == "MAINLINE_REWARD_CLAIMED", done.message
                assert done.data["reward"]["local_reputation"] == 6
                replay = await send("stage-3-claim", "领取妖界栖地回响主线奖励 妖界栖地夜值")
                assert replay.data["idempotent_replay"] is True
        finally:
            await runtime.close()

    asyncio.run(run())
