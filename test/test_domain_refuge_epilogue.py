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
from nonebot_plugin_xiuxian_3.xiuxian.adventures.mainline import DOMAIN_FRONTIER_STORY_KEY, mainline_definitions
from nonebot_plugin_xiuxian_3.xiuxian.adventures.repository import AdventuresRepositoryMixin
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError

ROOT = Path(__file__).parents[1]
STORY = DOMAIN_FRONTIER_STORY_KEY
PREFIX = "domain_frontier.refuge."


def _copy_data(path):
    target = path / "content"
    shutil.copytree(ROOT / "data", target, ignore=shutil.ignore_patterns("*.db*", "*.sqlite3*"))
    return target


def _edit_story(path, edit):
    file = path / "剧情/主线.json"
    document = json.loads(file.read_text(encoding="utf-8"))
    edit({row["key"]: row for row in document["records"]})
    file.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")


@pytest.mark.parametrize("key,field,value", [
    ("2", "project_key", "idle.domain_refuge_watch"),
    ("2", "project_key", "project.missing"),
    ("2", "min_points", True),
    ("2", "min_points", 0),
    ("2", "self_report", 10),
    ("3", "route_key", "project.domain_refuge"),
    ("3", "route_key", "idle.missing"),
    ("3", "fallback", True),
])
def test_epilogue_rejects_unprovable_objective_content(tmp_path, key, field, value):
    data = _copy_data(tmp_path)
    _edit_story(data, lambda rows: rows[PREFIX + key]["objectives"][0].update({field: value}))
    with pytest.raises(ContentError):
        mainline_definitions(ContentBundle.load(data), story_key=STORY)


def test_epilogue_public_supply_contribution_and_full_watch_with_recovery(tmp_path):
    async def run():
        data = _copy_data(tmp_path)
        now = [datetime(2026, 11, 11, 12, tzinfo=timezone.utc)]
        runtime = create_runtime(data_dir=data, clock=lambda: now[0], adapters=("onebot.v11",))

        async def send(op, command):
            return await runtime.dispatch(CommandContext(adapter="onebot.v11", user_id="refuge", operation_id=op), command)

        async def travel(op, destination):
            result = await send(op, f"前往 {destination}")
            assert result.code == "TRAVEL_STARTED", result.message
            now[0] += timedelta(minutes=10)
            result = await send(op + "-settle", "结算移动")
            assert result.code == "TRAVEL_COMPLETED", result.message

        try:
            assert (await send("create", "开始修仙")).ok
            assert (await send("seek", "寻仙问道")).ok
            with runtime.repository._connect() as connection:
                connection.execute("UPDATE players SET stage='cultivator', realm_key='soul_transformation', realm_layer=1, location_key='xuantian.domain_front', stamina=200, stamina_max=200")
            # Only the pre-existing realm and completed guard lane are fixtures.
            # All objective materials, transport, contribution and idle rewards below use public commands.
            denied = await send("gate", "开始领域前线主线 归镇筹粮")
            assert denied.code == "MAINLINE_REQUIREMENT_MISSING"
            with runtime.repository._connect() as connection:
                assert connection.execute("SELECT 1 FROM operations WHERE operation_id='gate'").fetchone() is None
                connection.execute(
                    "INSERT INTO mainline_runs(player_id,story_key,chapter,stage,stage_key,status,first_clear_claimed,first_clear_key,created_at,updated_at) "
                    "VALUES (1,?,1,6,'domain_frontier.guard.6','claimed',1,'prior-guard',?,?)",
                    (STORY, now[0].isoformat(), now[0].isoformat()),
                )
                connection.execute(
                    "INSERT INTO activity_events(player_id,event_key,source_operation_id,occurred_at) VALUES (1,'access.project.domain_refuge','prior-guard',?)",
                    (now[0].isoformat(),),
                )
            status = await send("status", "领域前线主线")
            assert "开始领域前线主线 归镇筹粮" in status.message
            assert (await send("start1", "开始领域前线主线 归镇筹粮")).ok
            assert (await send("early1", "领取领域前线主线奖励 归镇筹粮")).code == "MAINLINE_OBJECTIVES_INCOMPLETE"
            await travel("return-town", "青石镇")
            assert (await send("claim1", "领取领域前线主线奖励 归镇筹粮")).ok
            assert (await send("start2", "开始领域前线主线 共筑安所")).ok
            no_source = await send("no-source", "贡献公共项目 领域避难所 运输")
            assert no_source.code == "PROJECT_SOURCE_INVALID", no_source.message
            with runtime.repository._connect() as connection:
                assert connection.execute("SELECT 1 FROM operations WHERE operation_id='no-source'").fetchone() is None
                assert connection.execute("SELECT 1 FROM livelihood_project_contributions").fetchone() is None
            await travel("supplies", "近郊")
            gathered = await send("gather", "开始探索 近郊采集")
            assert gathered.code == "EXPLORATION_STARTED", gathered.message
            now[0] += timedelta(minutes=5)
            harvest = await send("gather-settle", "结算探索")
            assert harvest.code == "EXPLORATION_SETTLED", harvest.message
            assert harvest.data["result"]["item.herb.blood_grass"] >= 1
            await travel("load-town", "青石镇")
            route = await send("route", "开始运输 止血草 1")
            assert route.code == "ROUTE_STARTED", route.message
            now[0] += timedelta(hours=1)
            settlement = await send("route-settle", "结算运输")
            assert settlement.code == "ROUTE_SETTLED", settlement.message
            assert "贡献公共项目 项目名 运输" in settlement.message
            with runtime.repository._connect() as connection:
                connection.execute("CREATE TRIGGER fail_contribution BEFORE INSERT ON livelihood_project_contributions BEGIN SELECT RAISE(ABORT,'contribution failure'); END")
            assert (await send("contribute", "贡献公共项目 领域避难所 运输")).code == "PERSISTENCE_ERROR"
            with runtime.repository._connect() as connection:
                assert connection.execute("SELECT 1 FROM operations WHERE operation_id='contribute'").fetchone() is None
                assert connection.execute("SELECT 1 FROM livelihood_project_contributions").fetchone() is None
                connection.execute("DROP TRIGGER fail_contribution")
            contribution = await send("contribute", "贡献公共项目 领域避难所 运输")
            assert contribution.ok, contribution.message
            assert contribution.data["contribution_points"] == 20
            assert (await send("contribute", "贡献公共项目 领域避难所 运输")).data["idempotent_replay"]
            assert (await send("duplicate", "贡献公共项目 领域避难所 运输")).code == "PROJECT_SOURCE_ALREADY_USED"
            with runtime.repository._connect() as connection:
                assert connection.execute("SELECT COUNT(*) FROM sect_members").fetchone()[0] == 0
                assert connection.execute("SELECT source_operation_id FROM livelihood_project_contributions").fetchone()[0] == "route-settle"
            assert (await send("claim2", "领取领域前线主线奖励 共筑安所")).ok
            assert (await send("gather2", "开始探索 近郊采集")).ok
            now[0] += timedelta(minutes=5)
            assert (await send("gather2-settle", "结算探索")).ok
            await travel("load-town2", "青石镇")
            assert (await send("route2", "开始运输 止血草 1")).ok
            now[0] += timedelta(hours=1)
            assert (await send("route2-settle", "结算运输")).ok
            assert (await send("contribute", "贡献公共项目 领域避难所 运输")).data["idempotent_replay"]
            quota = await send("contribute2", "贡献公共项目 领域避难所 运输")
            assert quota.code == "PROJECT_CONTRIBUTION_LIMIT" and "明日" in quota.message
            with runtime.repository._connect() as connection:
                assert connection.execute("SELECT COUNT(*) FROM livelihood_project_contributions").fetchone()[0] == 1
                assert connection.execute("SELECT 1 FROM operations WHERE operation_id='contribute2'").fetchone() is None
            started = await send("start3", "开始领域前线主线 灯火长守")
            assert started.ok, started.message
            assert (await send("early3", "领取领域前线主线奖励 灯火长守")).code == "MAINLINE_OBJECTIVES_INCOMPLETE"
            watch = await send("watch", "开始挂机 避难所看守")
            assert watch.code == "IDLE_STARTED", watch.message
            assert (await send("watch-early", "领取挂机")).code == "IDLE_CLAIM_TOO_EARLY"
            now[0] += timedelta(hours=35)
            late = await send("watch-late", "领取挂机")
            assert late.code == "IDLE_CLAIMED" and late.data["fallback"]
            assert (await send("late-story", "领取领域前线主线奖励 灯火长守")).code == "MAINLINE_OBJECTIVES_INCOMPLETE"
            assert (await send("watch-retry", "开始挂机 避难所看守")).code == "IDLE_STARTED"
            now[0] += timedelta(hours=10)

            def change_current(rows):
                rows[PREFIX + "3"]["objectives"][0]["route_key"] = "idle.town_errand"
                rows[PREFIX + "3"]["first_clear_reward"]["spirit_stones"] = 999
            _edit_story(data, change_current)
            await runtime.close()
            runtime = create_runtime(data_dir=data, clock=lambda: now[0], adapters=("onebot.v11",))
            full = await send("watch-claim", "领取挂机")
            assert full.code == "IDLE_CLAIMED", full.message
            assert full.data["reward"]["item.token.construction_coupon"] == 1
            with runtime.repository._connect() as connection:
                before = tuple(connection.execute("SELECT spirit_stones,inventory_json FROM players").fetchone())
                connection.execute("CREATE TRIGGER fail_story_ledger BEFORE INSERT ON operations WHEN NEW.operation_id='claim3' BEGIN SELECT RAISE(ABORT,'story ledger failure'); END")
            failure = await send("claim3", "领取领域前线主线奖励 灯火长守")
            assert failure.code == "PERSISTENCE_ERROR", failure.message
            with runtime.repository._connect() as connection:
                assert tuple(connection.execute("SELECT spirit_stones,inventory_json FROM players").fetchone()) == before
                assert connection.execute("SELECT status FROM mainline_runs WHERE stage_key=?", (PREFIX + "3",)).fetchone()[0] == "running"
                assert connection.execute("SELECT 1 FROM activity_events WHERE event_key=?", (STORY + ":" + PREFIX + "3",)).fetchone() is None
                assert connection.execute("SELECT 1 FROM operations WHERE operation_id='claim3'").fetchone() is None
                connection.execute("DROP TRIGGER fail_story_ledger")
            claimed = await send("claim3", "领取领域前线主线奖励 灯火长守")
            assert claimed.code == "MAINLINE_REWARD_CLAIMED", claimed.message
            assert claimed.data["reward"] == {"spirit_stones": 40, "local_reputation": 3, "service_reputation": 1}
            assert (await send("claim3", "领取领域前线主线奖励 灯火长守")).data["idempotent_replay"]
            assert (await send("claim3", "领取领域前线主线奖励 归镇筹粮")).code == "OPERATION_CONFLICT"
            for category in ("生活", "探索"):
                help_result = await send("help-" + category, "修仙帮助 " + category)
                assert "后记" in help_result.message
                assert not help_result.actions
        finally:
            await runtime.close()
    asyncio.run(run())


@pytest.mark.parametrize("kind,player,key,status,when,points,complete", [
    ("project", 1, "project.domain_refuge", "", "2026-11-12", 6, False),
    ("project", 1, "project.domain_refuge", "", "2026-11-12", 10, True),
    ("project", 1, "project.domain_refuge", "", "2026-11-10", 30, False),
    ("project", 2, "project.domain_refuge", "", "2026-11-12", 30, False),
    ("project", 1, "project.new_town_granary", "", "2026-11-12", 30, False),
    ("idle", 1, "idle.domain_refuge_watch", "claimed", "2026-11-12", 0, True),
    ("idle", 1, "idle.domain_refuge_watch", "claimed", "2026-11-10", 0, False),
    ("idle", 2, "idle.domain_refuge_watch", "claimed", "2026-11-12", 0, False),
    ("idle", 1, "idle.town_errand", "claimed", "2026-11-12", 0, False),
    ("idle", 1, "idle.domain_refuge_watch", "expired", "2026-11-12", 0, False),
    ("idle", 1, "idle.domain_refuge_watch", "cancelled", "2026-11-12", 0, False),
    ("idle", 1, "idle.domain_refuge_watch", "running", "2026-11-12", 0, False),
])
def test_only_new_personal_project_or_full_watch_evidence_counts(kind, player, key, status, when, points, complete):
    with sqlite3.connect(":memory:") as connection:
        connection.row_factory = sqlite3.Row
        connection.executescript("""
            CREATE TABLE livelihood_projects(project_id TEXT,project_key TEXT);
            CREATE TABLE livelihood_project_contributions(project_id TEXT,player_id INTEGER,contribution_points INTEGER,created_at TEXT);
            CREATE TABLE idle_assignments(id INTEGER PRIMARY KEY AUTOINCREMENT,player_id INTEGER,route_key TEXT,status TEXT,starts_at TEXT);
        """)
        definition = next(row for row in mainline_definitions(story_key=STORY) if row.key == PREFIX + ("2" if kind == "project" else "3"))
        if kind == "project":
            connection.execute("INSERT INTO livelihood_projects VALUES ('week-1',?)", (key,))
            connection.execute("INSERT INTO livelihood_project_contributions VALUES ('week-1',?,?,?)", (player, points, when))
        else:
            connection.execute("INSERT INTO idle_assignments(player_id,route_key,status,starts_at) VALUES (?,?,?,?)", (player, key, status, when))
        run = {"snapshot_json": json.dumps({"started_at": "2026-11-11", "definition": {"objectives": list(definition.objectives)}})}
        missing = AdventuresRepositoryMixin._mainline_missing_objectives(connection, 1, run)
        assert (not missing) is complete
