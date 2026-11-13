from __future__ import annotations

import asyncio
import json
from pathlib import Path

from combat_fixtures import BALANCED_QUALIFICATION
from test_mainline_vertical_slice import MutableClock, _context, _copy_content

from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.exploration.rules import battle_roll_bp
from nonebot_plugin_xiuxian_3.xiuxian.progression.breakthrough.rules import breakthrough_roll_bp


def test_mist_gate_and_first_town_delivery_use_public_sources_after_restart(tmp_path: Path) -> None:
    async def run() -> None:
        data_dir = _copy_content(tmp_path)
        clock = MutableClock()
        user = "mist-town-player"
        runtime = create_runtime(data_dir=data_dir, clock=clock, adapters=("onebot.v11",))

        async def send(operation: str, command: str):
            return await runtime.adapters.dispatch("onebot.v11", _context(user, operation), command)

        async def move(operation: str, destination: str, seconds: int):
            started = await send(f"{operation}-start", f"前往 {destination}")
            assert started.code == "TRAVEL_STARTED", started.message
            clock.advance(seconds=seconds)
            arrived = await send(f"{operation}-arrive", "结算移动")
            assert arrived.code == "TRAVEL_COMPLETED", arrived.message

        def rows(table: str):
            with runtime.repository._connect() as connection:
                return [tuple(row) for row in connection.execute(f"SELECT * FROM {table} ORDER BY rowid")]

        def close_stage_with_changed_reward(stage_key: str) -> None:
            path = data_dir / "剧情" / "主线.json"
            document = json.loads(path.read_text(encoding="utf-8"))
            stage = next(row for row in document["records"] if row["key"] == stage_key)
            stage["status"] = "locked"
            stage["first_clear_reward"] = {"spirit_stones": 999}
            path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")

        async def claim_after_rollback(operation: str, command: str):
            tables = ("players", "mainline_runs", "operations", "honor_titles",
                      "player_reputations", "activity_events", "codex_entries")
            before = {table: rows(table) for table in tables}
            with runtime.repository._connect() as connection:
                connection.execute(
                    "CREATE TRIGGER fail_story_claim BEFORE INSERT ON operations "
                    "WHEN NEW.operation_name='mainline.claim_first_clear' "
                    "BEGIN SELECT RAISE(ABORT, 'injected story ledger failure'); END"
                )
            try:
                failed = await send(operation, command)
                assert failed.code == "PERSISTENCE_ERROR", failed.message
                assert before == {table: rows(table) for table in tables}
            finally:
                with runtime.repository._connect() as connection:
                    connection.execute("DROP TRIGGER fail_story_claim")
            return await send(operation, command)

        try:
            assert (await send("create", "开始修仙")).ok
            assert (await send("seek", "寻仙问道")).ok
            assert (await send("first-start", "开始主线 初入玄天")).ok
            assert (await send("read", "完成引导 阅读")).ok
            await move("outskirts", "近郊", 30)
            assert (await send("first-claim", "领取主线奖励 初入玄天")).ok
            for operation, command in (
                ("gather-lesson", "完成引导 采集"),
                ("production-lesson", "完成引导 炼丹"),
                ("path", "选择道途 体修"),
            ):
                result = await send(operation, command)
                assert result.ok, result.message

            # Isolate the growth prerequisite; neither the pass nor commission herbs
            # are supplied here. The breakthrough still consumes its actual inputs.
            with runtime.repository._connect() as connection:
                connection.execute(
                    "UPDATE players SET realm_key='qi_gathering', realm_layer=10, cultivation=2900, "
                    "total_cultivation=4260, spirit_stones=1000, stamina=100, stamina_max=100, "
                    "max_hp=20000, initiative=1000, qualification_json=?, inventory_json=? "
                    "WHERE platform='onebot.v11' AND platform_user_id=?",
                    (json.dumps(BALANCED_QUALIFICATION), json.dumps({
                        "item.pill.foundation_draft": 1,
                        "item.mat.array_sand": 3,
                        "item.ore.ironstone": 3,
                    }), user),
                )
            assert (await send("second-start", "开始主线 灵泉取叶")).ok
            assert (await send("return-town", "返回新手城")).ok
            await move("spring", "灵泉谷", 90)
            assert (await send("spring-explore-start", "开始探索 灵泉采集")).ok
            clock.advance(seconds=90)
            assert (await send("spring-settle", "结算探索")).ok
            assert (await send("second-claim", "领取主线奖励 灵泉取叶")).ok
            denied = await send("mist-too-early", "开始主线 雾中守门")
            assert denied.code == "MAINLINE_REQUIREMENT_MISSING"

            breakthrough_operation = next(
                f"mist-foundation-{index}" for index in range(100)
                if breakthrough_roll_bp(f"mist-foundation-{index}") < 7500
            )
            started = await send(breakthrough_operation, "开始突破 筑基")
            assert started.code == "BREAKTHROUGH_STARTED", started.message
            clock.advance(seconds=300)
            breakthrough = await send("foundation-settle", "结算突破")
            assert breakthrough.code == "BREAKTHROUGH_SUCCEEDED", breakthrough.message
            assert breakthrough.data["reward_items"] == {"item.cave_pass_basic": 1}

            mist = await send("mist-start", "开始主线 雾中守门")
            assert mist.code == "MAINLINE_STARTED", mist.message
            assert "筑基" in mist.message and "灵泉谷" in mist.message
            await move("cave", "雾隐洞天一层", 120)
            with runtime.repository._connect() as connection:
                inventory = json.loads(connection.execute(
                    "SELECT inventory_json FROM players WHERE platform_user_id=?", (user,)
                ).fetchone()[0])
                assert inventory.get("item.cave_pass_basic", 0) == 0

            quiet = next(f"mist-quiet-{i}" for i in range(100) if battle_roll_bp(f"mist-quiet-{i}:battle") >= 2500)
            assert (await send(quiet, "开始探索 雾隐洞天探索")).code == "EXPLORATION_STARTED"
            clock.advance(seconds=300)
            explored = await send("mist-quiet-settle", "结算探索")
            assert explored.code == "EXPLORATION_SETTLED", explored.message
            assert explored.data["battle_outcome"] is None
            early = await send("mist-claim", "领取主线奖励 雾中守门")
            assert early.code == "MAINLINE_OBJECTIVES_INCOMPLETE"
            encounter = next(f"mist-fight-{i}" for i in range(100) if battle_roll_bp(f"mist-fight-{i}:battle") < 2500)
            assert (await send(encounter, "开始探索 雾隐洞天探索")).code == "EXPLORATION_STARTED"
            await runtime.close()
            close_stage_with_changed_reward("chapter.1.stage.3")
            clock.advance(seconds=300)
            runtime = create_runtime(data_dir=data_dir, clock=clock, adapters=("onebot.v11",))
            fought = await send("mist-battle-settle", "结算探索")
            assert fought.code == "EXPLORATION_SETTLED", fought.message
            assert fought.data["battle_outcome"] == "won"
            assert fought.data["battle_id"]
            claimed = await claim_after_rollback("mist-claim", "领取主线奖励 雾中守门")
            assert claimed.code == "MAINLINE_REWARD_CLAIMED", claimed.message
            assert claimed.data["reward"] == {"access.instance.secret_realm": 1, "title_key": "title.mist_watcher"}
            assert claimed.data["next_stage_key"] == "chapter.2.stage.1"
            before = {table: rows(table) for table in ("players", "mainline_runs", "operations", "honor_titles")}
            replay = await send("mist-claim", "领取主线奖励 雾中守门")
            assert replay.data == {**claimed.data, "idempotent_replay": True}
            assert before == {table: rows(table) for table in before}

            await move("leave-cave", "灵泉谷", 90)
            assert (await send("return-after-cave", "返回新手城")).ok
            assert rows("town_commission_claims") == []
            town = await send("town-start", "开始主线 城镇委托")
            assert town.code == "MAINLINE_STARTED", town.message
            assert "城镇委托" in town.message and "百草坡采药" in town.message
            assert "查看委托 城镇委托" not in town.message
            assert (await send("town-list", "城镇委托")).code == "COMMISSION_LIST"
            assert (await send("town-accept", "接取委托 止血草供应")).code == "COMMISSION_ACCEPTED"
            assert (await send("town-short", "交付委托 止血草供应")).code == "RESOURCE_INSUFFICIENT"
            assert (await send("town-claim", "领取主线奖励 城镇委托")).code == "MAINLINE_OBJECTIVES_INCOMPLETE"
            await move("herb-road", "近郊", 30)
            await move("herb-vale", "百草坡", 60)
            assert (await send("herb-idle-start", "开始挂机 百草坡采药")).code == "IDLE_STARTED"
            await runtime.close()
            close_stage_with_changed_reward("chapter.2.stage.1")
            clock.advance(hours=4)
            runtime = create_runtime(data_dir=data_dir, clock=clock, adapters=("onebot.v11",))
            idle = await send("herb-idle-claim", "领取挂机")
            assert idle.code == "IDLE_CLAIMED", idle.message
            assert idle.data["reward"]["item.herb.blood_grass"] >= 2
            assert (await send("herb-gather-start", "开始探索 百草坡采集")).code == "EXPLORATION_STARTED"
            clock.advance(seconds=45)
            gathered = await send("herb-gather-settle", "结算探索")
            assert gathered.code == "EXPLORATION_SETTLED"
            assert gathered.data["result"]["item.herb.blood_grass"] >= 2
            await move("herb-return", "近郊", 30)
            assert (await send("herb-return-town", "返回新手城")).ok
            delivered = await send("town-deliver", "交付委托 止血草供应")
            assert delivered.code == "COMMISSION_DELIVERED", delivered.message
            town_claim = await claim_after_rollback("town-claim", "领取主线奖励 城镇委托")
            assert town_claim.code == "MAINLINE_REWARD_CLAIMED", town_claim.message
            assert town_claim.data["reward"] == {"access.xuantian.trade_route": 1, "service_reputation": 5}
            assert town_claim.data["next_stage_key"] == "chapter.2.stage.2"
            before = {table: rows(table) for table in ("players", "mainline_runs", "operations", "town_commission_claims", "player_reputations")}
            replay = await send("town-claim", "领取主线奖励 城镇委托")
            assert replay.data == {**town_claim.data, "idempotent_replay": True}
            assert before == {table: rows(table) for table in before}
            assert len(rows("town_commission_claims")) == 1
            with runtime.repository._connect() as connection:
                for stage_key in ("chapter.1.stage.3", "chapter.2.stage.1"):
                    row = connection.execute(
                        "SELECT status, attempt_count FROM mainline_runs WHERE stage_key=?", (stage_key,)
                    ).fetchone()
                    assert tuple(row) == ("claimed", 1)
        finally:
            await runtime.close()

    asyncio.run(run())
