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
    DOMAIN_FRONTIER_STORY_KEY,
    mainline_definitions,
)
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError

ROOT = Path(__file__).parents[1]
STORY = DOMAIN_FRONTIER_STORY_KEY
PREFIX = "domain_frontier.habitat."


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


def _context(user: str, operation: str) -> CommandContext:
    return CommandContext(adapter="onebot.v11", user_id=user, request_id=operation, operation_id=operation)


def test_habitat_epilogue_uses_open_world_and_existing_producers() -> None:
    bundle = ContentBundle.load(ROOT / "data")
    definitions = {row.key: row for row in mainline_definitions(bundle, story_key=STORY)}
    stages = [definitions[PREFIX + str(index)] for index in (1, 2, 3)]
    assert [row.next_stage_key for row in stages] == [PREFIX + "2", PREFIX + "3", None]
    assert all(row.key in {item.key for item in mainline_definitions(story_key=STORY)} for row in stages)

    first, second, third = stages
    refuge_tail = definitions["domain_frontier.refuge.3"]
    assert (refuge_tail.lane, refuge_tail.lane_label) == ("refuge", "领域避难所")
    assert all(
        (definitions[PREFIX + str(index)].lane, definitions[PREFIX + str(index)].lane_label)
        == ("habitat", "祖灵栖地")
        for index in (1, 2, 3)
    )
    assert first.objectives[0]["destination_key"] == "beast.ten_thousand_hills"
    assert second.objectives[0]["route_key"] == "idle.beast_habitat_watch"
    assert {item["destination_key"] for item in third.objectives if item["type"] == "travel_arrival"} == {
        "beast.three_realms_trade_port"
    }
    assert all(item.get("destination_key") != "beast.ancestral_lake" for row in stages for item in row.objectives)
    assert first.actions[0]["argument"] == "万兽山入口"
    assert third.actions[1]["command"] == "公共项目"
    assert third.actions[1]["argument"] == ""

    locations = {row["key"]: row for row in bundle.list("location")}
    assert locations["beast.ten_thousand_hills"]["status"] == "open"
    lake_gate = locations["beast.ancestral_lake"]["requirements"]
    assert {row.get("min") for row in lake_gate if row.get("type") == "faction_reputation"} == {3000}

    regions = json.loads((ROOT / "data" / "地图" / "区域.json").read_text(encoding="utf-8"))["records"]
    connections = [edge for region in regions for edge in region["connections"]]
    assert {"from": "beast.three_realms_trade_port", "to": "beast.ten_thousand_hills", "duration_seconds": 300, "stamina": 12, "spirit_stone": 0} in connections
    assert {"from": "beast.ten_thousand_hills", "to": "beast.three_realms_trade_port", "duration_seconds": 180, "stamina": 8, "spirit_stone": 0} in connections

    livelihood = json.loads((ROOT / "data" / "生活" / "生活.json").read_text(encoding="utf-8"))["records"]
    project = next(row for row in livelihood if row["key"] == "project.ancestral_habitat")
    route = next(row for row in livelihood if row["key"] == "idle.beast_habitat_watch")
    assert project["required_faction_reputation"] == 300
    assert project["contribution_resources"] == ["item.food.coarse_spirit_rice", "item.herb.spirit_leaf"]
    assert route["requirements"]["required_permit"] == "permit.beast_trade"
    assert route["duration_seconds"] == 8 * 60 * 60 and route["daily_limit"] == 1

    rewards = json.loads((ROOT / "data" / "奖励" / "奖励.json").read_text(encoding="utf-8"))["records"]
    pool = next(row for row in rewards if row["key"] == route["reward_pool_key"])
    assert all(outcome["rewards"].get("item.food.coarse_spirit_rice", 0) >= 1 for outcome in pool["outcomes"])
    assert all(outcome["rewards"].get("item.herb.spirit_leaf", 0) >= 1 for outcome in pool["outcomes"])


@pytest.mark.parametrize(
    "stage,field,value",
    [
        ("1", "body", "短文"),
        ("2", "route_key", "idle.missing"),
        ("3", "project_key", "project.missing"),
        ("3", "min_points", True),
    ],
)
def test_habitat_epilogue_rejects_incomplete_content(tmp_path: Path, stage: str, field: str, value: object) -> None:
    data = _copy_data(tmp_path)

    def break_stage(rows) -> None:
        if field == "body":
            rows[PREFIX + stage][field] = value
        else:
            rows[PREFIX + stage]["objectives"][0][field] = value

    _edit_story(data, break_stage)
    with pytest.raises(ContentError):
        mainline_definitions(ContentBundle.load(data), story_key=STORY)


def test_habitat_epilogue_public_round_trip_idle_contribution_and_recovery(tmp_path: Path) -> None:
    async def run() -> None:
        data = _copy_data(tmp_path)
        clock = Clock(datetime(2026, 11, 11, 12, tzinfo=timezone.utc))
        runtime = create_runtime(data_dir=data, clock=clock)
        user = "habitat-epilogue"

        async def send(operation: str, command: str):
            return await runtime.dispatch(_context(user, operation), command)

        async def send_as(platform_user: str, operation: str, command: str):
            return await runtime.dispatch(_context(platform_user, operation), command)

        async def travel(operation: str, destination: str, seconds: int):
            started = await send(operation, f"前往 {destination}")
            assert started.code == "TRAVEL_STARTED", started.message
            clock.advance(seconds=seconds)
            settled = await send(operation + "-settle", "结算移动")
            assert settled.code == "TRAVEL_COMPLETED", settled.message

        def inventory() -> dict[str, int]:
            with runtime.repository._connect() as connection:
                row = connection.execute("SELECT inventory_json FROM players WHERE platform_user_id=?", (user,)).fetchone()
            return json.loads(row[0])

        try:
            assert (await send("create", "开始修仙")).ok
            assert (await send("seek", "寻仙问道")).ok
            with runtime.repository._connect() as connection:
                player_id = connection.execute(
                    "SELECT id FROM players WHERE platform='onebot.v11' AND platform_user_id=?", (user,)
                ).fetchone()[0]
                connection.execute(
                    "UPDATE players SET stage='cultivator',realm_key='soul_transformation',realm_layer=1,"
                    "location_key='beast.three_realms_trade_port',stamina=200,stamina_max=200,"
                    "faction_reputation_json=? WHERE id=?",
                    (json.dumps({"beast": 300}, sort_keys=True), player_id),
                )
                connection.execute(
                    "INSERT INTO mainline_runs(player_id,story_key,chapter,stage,stage_key,status,"
                    "first_clear_claimed,first_clear_key,created_at,updated_at) VALUES (?,?,?,?,?,'claimed',1,?,?,?)",
                    (player_id, STORY, 3, 6, "domain_frontier.protect.6", "prior-protect", clock().isoformat(), clock().isoformat()),
                )
                for event in (
                    "access.project.ancestral_habitat",
                    STORY + ":domain_frontier.protect.6",
                ):
                    connection.execute(
                        "INSERT INTO activity_events(player_id,event_key,source_operation_id,occurred_at) VALUES (?,?,?,?)",
                        (player_id, event, "prior-protect", clock().isoformat()),
                    )
                connection.execute(
                    "INSERT INTO trade_permits(permit_id,player_id,operation_id,permit_key,issued_at,expires_at,"
                    "cost,snapshot_json,created_at,updated_at) VALUES (?,?,?,?,?,?,500,'{}',?,?)",
                    (
                        "permit-beast-test", player_id, "permit-beast-test-op", "permit.beast_trade",
                        clock().isoformat(), (clock() + timedelta(days=7)).isoformat(),
                        clock().isoformat(), clock().isoformat(),
                    ),
                )

            blocked = await send("blocked", "开始领域前线主线 灵粮入册")
            assert blocked.code == "MAINLINE_REQUIREMENT_MISSING"
            with runtime.repository._connect() as connection:
                assert connection.execute("SELECT 1 FROM operations WHERE operation_id='blocked'").fetchone() is None

            status = await send("status", "领域前线主线")
            assert "开始领域前线主线 重巡万兽山" in status.message
            assert (await send("start-1", "开始领域前线主线 重巡万兽山")).code == "MAINLINE_STARTED"
            assert (await send("early-1", "领取领域前线主线奖励 重巡万兽山")).code == "MAINLINE_OBJECTIVES_INCOMPLETE"
            with runtime.repository._connect() as connection:
                assert connection.execute("SELECT 1 FROM operations WHERE operation_id='early-1'").fetchone() is None

            # Hot content changes affect new runs, not this stage's frozen reward.
            _edit_story(data, lambda rows: rows[PREFIX + "1"]["first_clear_reward"].update({"spirit_stones": 999}))
            await runtime.close()
            runtime = create_runtime(data_dir=data, clock=clock)
            await travel("to-hills", "万兽山入口", 300)
            first = await send("claim-1", "领取领域前线主线奖励 重巡万兽山")
            assert first.code == "MAINLINE_REWARD_CLAIMED", first.message
            assert first.data["reward"]["spirit_stones"] == 20

            # A full pre-stage idle claim is not evidence for the new stage.
            pre = await send("idle-pre", "开始挂机 妖界栖地")
            assert pre.code == "IDLE_STARTED", pre.message
            clock.advance(hours=8)
            pre_claim = await send("idle-pre-claim", "领取挂机")
            assert pre_claim.code == "IDLE_CLAIMED" and not pre_claim.data["fallback"]
            assert pre_claim.data["reward"]["item.food.coarse_spirit_rice"] >= 1
            assert pre_claim.data["reward"]["item.herb.spirit_leaf"] >= 1

            assert (await send("start-2", "开始领域前线主线 栖地夜值")).code == "MAINLINE_STARTED"

            other_user = "habitat-other"
            assert (await send_as(other_user, "other-create", "开始修仙")).ok
            assert (await send_as(other_user, "other-seek", "寻仙问道")).ok
            with runtime.repository._connect() as connection:
                other_id = connection.execute(
                    "SELECT id FROM players WHERE platform='onebot.v11' AND platform_user_id=?",
                    (other_user,),
                ).fetchone()[0]
                other_inventory = json.loads(connection.execute(
                    "SELECT inventory_json FROM players WHERE id=?", (other_id,)
                ).fetchone()[0])
                other_inventory["item.food.coarse_spirit_rice"] = 5
                connection.execute(
                    "UPDATE players SET stage='cultivator',realm_key='soul_transformation',realm_layer=1,"
                    "location_key='beast.ten_thousand_hills',stamina=200,stamina_max=200,"
                    "faction_reputation_json=?,inventory_json=? WHERE id=?",
                    (json.dumps({"beast": 300}, sort_keys=True), json.dumps(other_inventory, sort_keys=True), other_id),
                )
                connection.execute(
                    "INSERT INTO activity_events(player_id,event_key,source_operation_id,occurred_at) VALUES (?,?,?,?)",
                    (other_id, "access.project.ancestral_habitat", "other-prior-protect", clock().isoformat()),
                )
                connection.execute(
                    "INSERT INTO trade_permits(permit_id,player_id,operation_id,permit_key,issued_at,expires_at,"
                    "cost,snapshot_json,created_at,updated_at) VALUES (?,?,?,?,?,?,500,'{}',?,?)",
                    (
                        "other-permit", other_id, "other-permit-op", "permit.beast_trade",
                        clock().isoformat(), (clock() + timedelta(days=7)).isoformat(),
                        clock().isoformat(), clock().isoformat(),
                    ),
                )
            other_idle = await send_as(other_user, "other-idle", "开始挂机 妖界栖地")
            assert other_idle.code == "IDLE_STARTED", other_idle.message
            clock.advance(hours=8)
            other_claim = await send_as(other_user, "other-idle-claim", "领取挂机")
            assert other_claim.code == "IDLE_CLAIMED" and not other_claim.data["fallback"]
            assert (await send("early-2", "领取领域前线主线奖励 栖地夜值")).code == "MAINLINE_OBJECTIVES_INCOMPLETE"
            with runtime.repository._connect() as connection:
                assert connection.execute("SELECT 1 FROM operations WHERE operation_id='early-2'").fetchone() is None

            clock.advance(days=1)
            expired_start = await send("idle-expired", "开始挂机 妖界栖地")
            assert expired_start.code == "IDLE_STARTED", expired_start.message
            _edit_story(data, lambda rows: rows[PREFIX + "2"]["first_clear_reward"].update({"spirit_stones": 999}))
            await runtime.close()
            runtime = create_runtime(data_dir=data, clock=clock)
            clock.advance(hours=33)
            expired = await send("idle-expired-claim", "领取挂机")
            assert expired.code == "IDLE_CLAIMED" and expired.data["fallback"]
            assert (await send("expired-story", "领取领域前线主线奖励 栖地夜值")).code == "MAINLINE_OBJECTIVES_INCOMPLETE"
            with runtime.repository._connect() as connection:
                assert connection.execute("SELECT 1 FROM operations WHERE operation_id='expired-story'").fetchone() is None

            retry_start = await send("idle-retry", "开始挂机 妖界栖地")
            assert retry_start.code == "IDLE_STARTED", retry_start.message
            clock.advance(hours=8)
            full = await send("idle-retry-claim", "领取挂机")
            assert full.code == "IDLE_CLAIMED" and not full.data["fallback"]
            assert full.data["reward"]["item.food.coarse_spirit_rice"] >= 1
            assert full.data["reward"]["item.herb.spirit_leaf"] >= 1
            claim_two = await send("claim-2", "领取领域前线主线奖励 栖地夜值")
            assert claim_two.code == "MAINLINE_REWARD_CLAIMED", claim_two.message
            assert claim_two.data["reward"]["spirit_stones"] == 25

            clock.advance(days=1)
            old_stock_idle = await send("old-stock-idle", "开始挂机 妖界栖地")
            assert old_stock_idle.code == "IDLE_STARTED", old_stock_idle.message
            clock.advance(hours=8)
            old_stock_claim = await send("old-stock-claim", "领取挂机")
            assert old_stock_claim.code == "IDLE_CLAIMED" and not old_stock_claim.data["fallback"]

            # The old point is real but predates this stage and must not count.
            old_contribution = await send(
                "old-project-contribution", "贡献公共项目 祖灵栖地修复 灵米 2"
            )
            assert old_contribution.code == "PROJECT_CONTRIBUTED", old_contribution.message
            assert old_contribution.data["contribution_points"] == 2
            clock.advance(seconds=1)
            stage_three = await send("start-3", "开始领域前线主线 灵粮入册")
            assert stage_three.code == "MAINLINE_STARTED", stage_three.message
            assert "`公共项目` ·" in stage_three.message
            await travel("back-to-port", "三界贸易口", 180)
            other_supply = await send_as(
                other_user, "other-project-supply", "贡献公共项目 祖灵栖地修复 灵米 2"
            )
            assert other_supply.code == "PROJECT_CONTRIBUTED", other_supply.message
            assert other_supply.data["contribution_points"] == 2
            early_three = await send("early-3", "领取领域前线主线奖励 灵粮入册")
            assert early_three.code == "MAINLINE_OBJECTIVES_INCOMPLETE", early_three.message
            with runtime.repository._connect() as connection:
                assert connection.execute("SELECT 1 FROM operations WHERE operation_id='early-3'").fetchone() is None
                assert connection.execute(
                    "SELECT status FROM mainline_runs WHERE player_id=? AND stage_key=?",
                    (player_id, PREFIX + "3"),
                ).fetchone()[0] == "running"

            inventory_before = inventory()
            rice = await send("supply-rice", "贡献公共项目 祖灵栖地修复 灵米 1")
            leaf = await send("supply-leaf", "贡献公共项目 祖灵栖地修复 灵叶 1")
            assert rice.code == leaf.code == "PROJECT_CONTRIBUTED"
            inventory_after = inventory()
            assert inventory_after["item.food.coarse_spirit_rice"] == inventory_before["item.food.coarse_spirit_rice"] - 1
            assert inventory_after["item.herb.spirit_leaf"] == inventory_before["item.herb.spirit_leaf"] - 1

            with runtime.repository._connect() as connection:
                connection.execute(
                    "CREATE TRIGGER fail_final_claim BEFORE INSERT ON operations "
                    "WHEN NEW.operation_id='claim-3' BEGIN SELECT RAISE(ABORT,'claim failure'); END"
                )
                before = tuple(connection.execute(
                    "SELECT spirit_stones, inventory_json FROM players WHERE id=?", (player_id,)
                ).fetchone())
            failed = await send("claim-3", "领取领域前线主线奖励 灵粮入册")
            assert failed.code == "PERSISTENCE_ERROR", failed.message
            with runtime.repository._connect() as connection:
                assert tuple(connection.execute(
                    "SELECT spirit_stones, inventory_json FROM players WHERE id=?", (player_id,)
                ).fetchone()) == before
                assert connection.execute(
                    "SELECT status FROM mainline_runs WHERE player_id=? AND stage_key=?",
                    (player_id, PREFIX + "3"),
                ).fetchone()[0] == "running"
                assert connection.execute(
                    "SELECT 1 FROM activity_events WHERE player_id=? AND event_key=?",
                    (player_id, STORY + ":" + PREFIX + "3"),
                ).fetchone() is None
                assert connection.execute("SELECT 1 FROM operations WHERE operation_id='claim-3'").fetchone() is None
                connection.execute("DROP TRIGGER fail_final_claim")

            claimed = await send("claim-3", "领取领域前线主线奖励 灵粮入册")
            assert claimed.code == "MAINLINE_REWARD_CLAIMED", claimed.message
            assert claimed.data["reward"] == {"spirit_stones": 30, "local_reputation": 3, "service_reputation": 1}
            assert (await send("claim-3", "领取领域前线主线奖励 灵粮入册")).data["idempotent_replay"]
            conflict = await send("claim-3", "领取领域前线主线奖励 栖地夜值")
            assert conflict.code == "OPERATION_CONFLICT"

            help_result = await send("help-livelihood", "修仙帮助 生活")
            assert "妖界栖地" in help_result.message
            assert all(value in help_result.message for value in ("80 点妖界声望", "500 灵石", "七日", "300 点妖界声望", "完整领取"))
            assert not help_result.actions
        finally:
            await runtime.close()

    asyncio.run(run())
