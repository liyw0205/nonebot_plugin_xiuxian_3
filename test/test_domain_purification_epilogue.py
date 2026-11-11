from __future__ import annotations

import json
import shutil
import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.adventures.mainline import DOMAIN_FRONTIER_STORY_KEY, mainline_definitions
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError
from travel_fixtures import set_travel_end_at

ROOT = Path(__file__).parents[1]
STORY = DOMAIN_FRONTIER_STORY_KEY
PREFIX = "domain_frontier.purification."


def _copy_data(path: Path) -> Path:
    target = path / "content"
    shutil.copytree(ROOT / "data", target)
    return target


def _edit(path: Path, edit) -> None:
    story_path = path / "剧情" / "主线.json"
    document = json.loads(story_path.read_text(encoding="utf-8"))
    edit({row["key"]: row for row in document["records"]})
    story_path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_purification_epilogue_closes_open_world_idle_and_project_sources() -> None:
    bundle = ContentBundle.load(ROOT / "data")
    rows = {row.key: row for row in mainline_definitions(bundle, story_key=STORY)}
    stages = [rows[PREFIX + str(index)] for index in (1, 2, 3)]
    assert [stage.next_stage_key for stage in stages] == [PREFIX + "2", PREFIX + "3", None]
    assert all(stage.lane == "purification" and stage.lane_label == "魔渊驿路" for stage in stages)
    assert stages[0].objectives[0] == {
        "key": "reach_abyss_market",
        "type": "travel_arrival",
        "label": "结算行程抵达魔渊集市",
        "destination_key": "demon.abyss_market",
    }
    assert stages[1].objectives[0]["route_key"] == "idle.demon_trade_post"
    assert stages[2].objectives[0]["project_key"] == "project.abyss_purification"
    assert all(item.get("destination_key") != "demon.abyss_depths" for stage in stages for item in stage.objectives)

    livelihood = {row["key"]: row for row in bundle.list("livelihood")}
    project = livelihood["project.abyss_purification"]
    route = livelihood["idle.demon_trade_post"]
    assert project["required_faction_reputation"] == 300
    assert project["contribution_resources"] == ["item.herb.blood_grass", "item.mat.array_sand"]
    assert route["requirements"]["required_permit"] == "permit.demon_trade"
    assert route["duration_seconds"] == 8 * 60 * 60 and route["daily_limit"] == 1
    rewards = {row["key"]: row for row in bundle.list("reward")}
    assert rewards[route["reward_pool_key"]]["outcomes"]
    assert rewards[route["fallback_reward_pool_key"]]["outcomes"]


@pytest.mark.parametrize("edit", [
    lambda rows: rows[PREFIX + "2"]["objectives"].__setitem__(0, {
        "key": "claim_demon_trade_post", "type": "idle_claim", "label": "坏路线", "route_key": "idle.missing"
    }),
    lambda rows: rows[PREFIX + "3"]["objectives"].__setitem__(0, {
        "key": "contribute_abyss_purification", "type": "public_project_contribution", "label": "坏项目",
        "project_key": "project.missing", "min_points": 1
    }),
])
def test_purification_epilogue_rejects_missing_idle_or_project_contract(tmp_path: Path, edit) -> None:
    data = _copy_data(tmp_path)
    _edit(data, edit)
    with pytest.raises(ContentError):
        mainline_definitions(ContentBundle.load(data), story_key=STORY)


def test_purification_epilogue_rejects_idle_route_without_fallback_pool(tmp_path: Path) -> None:
    data = _copy_data(tmp_path)
    livelihood_path = data / "生活" / "生活.json"
    livelihood = json.loads(livelihood_path.read_text(encoding="utf-8"))
    for row in livelihood["records"]:
        if row.get("key") == "idle.demon_trade_post":
            row.pop("fallback_reward_pool_key")
    livelihood_path.write_text(json.dumps(livelihood, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(ContentError):
        mainline_definitions(ContentBundle.load(data), story_key=STORY)


def test_purification_epilogue_uses_real_market_travel_permit_idle_and_project_consumer() -> None:
    async def run() -> None:
        now = [datetime(2026, 11, 12, 12, tzinfo=timezone.utc)]
        with TemporaryDirectory() as temp:
            runtime = create_runtime(data_dir=Path(temp), clock=lambda: now[0])
            user = "purification-epilogue"

            def context(operation: str) -> CommandContext:
                return CommandContext(adapter="onebot.v11", user_id=user, request_id=operation, operation_id=operation)

            async def send(operation: str, command: str):
                return await runtime.dispatch(context(operation), command)

            try:
                assert (await send("create", "开始修仙")).ok
                assert (await send("seek", "寻仙问道")).ok
                with runtime.repository._connect() as connection:
                    player_id = connection.execute(
                        "SELECT id FROM players WHERE platform='onebot.v11' AND platform_user_id=?", (user,)
                    ).fetchone()[0]
                    timestamp = now[0].isoformat()
                    connection.execute(
                        "UPDATE players SET stage='cultivator', realm_key='soul_transformation', realm_layer=1, "
                        "location_key='demon.abyss_gate', stamina=100, stamina_max=100, spirit_stones=2000, "
                        "faction_reputation_json=?, intro_json=? WHERE id=?",
                        (json.dumps({"demon": 300}, sort_keys=True), json.dumps({"flags": ["access.demon_abyss_gate", "quest.demon_intro"]}), player_id),
                    )
                    for event in ("access.project.abyss_purification", f"{STORY}:domain_frontier.purify.6"):
                        connection.execute(
                            "INSERT INTO activity_events(player_id,event_key,source_operation_id,occurred_at) VALUES (?,?,?,?)",
                            (player_id, event, "purify-prior", timestamp),
                        )
                    connection.execute(
                        "INSERT INTO mainline_runs(player_id,story_key,chapter,stage,stage_key,status,first_clear_claimed,first_clear_key,snapshot_json,result_json,created_at,updated_at) "
                        "VALUES(?,?,?,?,?,'claimed',1,?,'{}','{}',?,?)",
                        (player_id, STORY, 3, 6, "domain_frontier.purify.6", "purify-prior", timestamp, timestamp),
                    )

                assert (await send("start-1", "开始领域前线主线 驿路复核")).code == "MAINLINE_STARTED"
                travel = await send("market-start", "前往 魔渊集市")
                assert travel.code == "TRAVEL_STARTED", travel.message
                with runtime.repository._connect() as connection:
                    set_travel_end_at(connection, travel.data["session_id"], (now[0] - timedelta(seconds=1)).isoformat())
                assert (await send("market-settle", "结算移动")).code == "TRAVEL_COMPLETED"
                assert (await send("claim-1", "领取领域前线主线奖励 驿路复核")).code == "MAINLINE_REWARD_CLAIMED"

                assert (await send("start-2", "开始领域前线主线 驿所夜值")).code == "MAINLINE_STARTED"
                permit = await send("permit", "申请贸易许可 魔界")
                assert permit.code == "TRADE_PERMIT_ISSUED", permit.message
                idle = await send("idle-start", "开始挂机 魔界驿所")
                assert idle.code == "IDLE_STARTED", idle.message
                now[0] += timedelta(hours=8)
                idle_claim = await send("idle-claim", "领取挂机")
                assert idle_claim.code == "IDLE_CLAIMED" and not idle_claim.data["fallback"]
                assert idle_claim.data["reward"]["local.demon.abyss_market"] == 3
                assert (await send("claim-2", "领取领域前线主线奖励 驿所夜值")).code == "MAINLINE_REWARD_CLAIMED"

                assert (await send("start-3", "开始领域前线主线 净化入册")).code == "MAINLINE_STARTED"
                with runtime.repository._connect() as connection:
                    connection.execute(
                        "UPDATE players SET faction_reputation_json=? WHERE id=?",
                        (json.dumps({"demon": 299}, sort_keys=True), player_id),
                    )
                blocked = await send("project-blocked", "贡献公共项目 魔渊净化工程 血草 1")
                assert blocked.code == "LIVELIHOOD_CONTENT_CLOSED"
                with runtime.repository._connect() as connection:
                    assert connection.execute("SELECT 1 FROM operations WHERE operation_id='project-blocked'").fetchone() is None
                    connection.execute(
                        "UPDATE players SET faction_reputation_json=?, inventory_json=? WHERE id=?",
                        (json.dumps({"demon": 300}, sort_keys=True), json.dumps({"item.herb.blood_grass": 1}), player_id),
                    )
                contributed = await send("project", "贡献公共项目 魔渊净化工程 血草 1")
                assert contributed.code == "PROJECT_CONTRIBUTED", contributed.message
                assert contributed.data["contribution_points"] == 1
                claimed = await send("claim-3", "领取领域前线主线奖励 净化入册")
                assert claimed.code == "MAINLINE_REWARD_CLAIMED", claimed.message
                replay = await send("claim-3", "领取领域前线主线奖励 净化入册")
                assert replay.data["idempotent_replay"] is True
            finally:
                await runtime.close()

    asyncio.run(run())
