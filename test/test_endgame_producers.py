from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.events.rules import final_heaven_season_window
from nonebot_plugin_xiuxian_3.xiuxian.production.endgame_rules import ENDGAME_RECIPES, recipe_roll_bp
from nonebot_plugin_xiuxian_3.xiuxian.quests.rules import (
    DAO_ORIGIN_REWARDS,
    DAO_ORIGIN_TASKS,
    DAO_UNION_MAINLINE_CONTENT_VERSION,
    DAO_UNION_MAINLINE_LANES,
    DAO_UNION_MAINLINE_RULE_VERSION,
    DAO_UNION_MAINLINE_STAGE_KEYS,
    DAO_UNION_MAINLINE_STORY_KEY,
)
from nonebot_plugin_xiuxian_3.xiuxian.progression.endgame_rules import (
    TRIBULATION_MERIT_REWARD,
    TRIBULATION_PROGRESS_REWARD,
    trial_roll_bp,
)


class MutableClock:
    def __init__(self) -> None:
        self.value = datetime(2026, 9, 24, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **kwargs: int) -> None:
        self.value += timedelta(**kwargs)


def _ctx(adapter: str, user: str, operation: str) -> CommandContext:
    return CommandContext(adapter=adapter, user_id=user, operation_id=operation)


async def _create(runtime, adapter: str, user: str) -> None:
    result = await runtime.dispatch(_ctx(adapter, user, f"create-{user}"), "开始修仙")
    assert result.ok


def _set_player(runtime, adapter: str, user: str, **values: object) -> None:
    assignments = ", ".join(f"{key} = ?" for key in values)
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            f"UPDATE players SET {assignments} WHERE platform = ? AND platform_user_id = ?",
            (*values.values(), adapter, user),
        )


def _insert_origin_evidence(
    connection: sqlite3.Connection,
    *,
    adapter: str,
    player_id: int,
    apprentice_ids: tuple[int, ...],
    task_key: str,
    now: datetime,
    count: int,
) -> None:
    now_text = now.isoformat()
    if task_key == "task.dao_origin.guard":
        raise AssertionError("守界 evidence must come from the automatic battle flow")
    for index in range(count):
        source = f"{adapter}-{task_key}-{now.date()}-{index}"
        if task_key == "task.dao_origin.build":
            project_id = f"project-{source}"
            connection.execute(
                "INSERT INTO livelihood_projects(project_id, project_key, business_week, status, target_points, contribution_points, requirements_json, progress_json, effect_key, snapshot_json, result_json, created_at, updated_at) "
                "VALUES (?, 'project.town_well', ?, 'active', 10, 10, '{}', '{}', 'town_well', '{}', '{}', ?, ?)",
                (project_id, f"week-{source}", now_text, now_text),
            )
            connection.execute(
                "INSERT INTO livelihood_project_rewards(project_id, player_id, operation_id, eligible, reward_json, created_at) VALUES (?, ?, ?, 1, '{}', ?)",
                (project_id, player_id, f"project-reward-op-{source}", now_text),
            )
        else:
            apprentice_id = apprentice_ids[index % len(apprentice_ids)]
            connection.execute(
                "INSERT INTO mentor_relations(relation_id, master_id, apprentice_id, status, expires_at, invited_at, graduated_at, graduate_operation_id, content_version, rule_version, created_at, updated_at) "
                "VALUES (?, ?, ?, 'graduated', ?, ?, ?, ?, 'content-0.1', 'social-0.1.0', ?, ?)",
                (f"relation-{source}", player_id, apprentice_id, now_text, now_text, now_text, f"graduate-op-{source}", now_text, now_text),
            )


def test_dao_origin_resource_closure_and_qq_onebot_task_producers() -> None:
    async def run() -> None:
        clock = MutableClock()
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            for adapter, user in (("qq.official", "qq-origin"), ("onebot.v11", "ob-origin")):
                await _create(runtime, adapter, user)
                apprentice_users = tuple(f"{user}-apprentice-{index}" for index in range(3))
                for apprentice_user in apprentice_users:
                    await _create(runtime, adapter, apprentice_user)
                _set_player(
                    runtime,
                    adapter,
                    user,
                    stage="cultivator",
                    realm_key="dao_union",
                    realm_layer=1,
                    endgame_status="dao_union",
                    location_key="cave.boundary_realm",
                    max_hp=500_000,
                    initiative=1_000,
                    qualification_json=json.dumps({"body": 100_000}),
                )
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    player_id = connection.execute(
                        "SELECT id FROM players WHERE platform = ? AND platform_user_id = ?",
                        (adapter, user),
                    ).fetchone()[0]
                    apprentice_ids = tuple(
                        connection.execute(
                            "SELECT id FROM players WHERE platform = ? AND platform_user_id = ?",
                            (adapter, apprentice_user),
                        ).fetchone()[0]
                        for apprentice_user in apprentice_users
                    )

                for task_key, label in zip(DAO_ORIGIN_TASKS, ("守界", "建设", "传承"), strict=True):
                    blocked = await runtime.dispatch(
                        _ctx(adapter, user, f"missing-{task_key}"), f"完成道源任务 {label}"
                    )
                    assert blocked.code == "ENDGAME_EVENT_REQUIREMENT_MISSING"

                for index in range(3):
                    battle = await runtime.dispatch(
                        _ctx(adapter, user, f"{adapter}-dao-origin-battle-{index}"), "开始合道挑战"
                    )
                    assert battle.code == "DAO_UNION_CHALLENGE_SETTLED"
                    assert battle.data["outcome"] == "won"

                with sqlite3.connect(runtime.settings.database_path) as connection:
                    for task_key in DAO_ORIGIN_TASKS[1:]:
                        _insert_origin_evidence(
                            connection,
                            adapter=adapter,
                            player_id=player_id,
                            apprentice_ids=apprentice_ids,
                            task_key=task_key,
                            now=clock.value,
                            count=3,
                        )

                for task_key, label in zip(DAO_ORIGIN_TASKS, ("守界", "建设", "传承"), strict=True):
                    for index in range(3):
                        operation = f"{adapter}-{task_key}-{index}"
                        completed = await runtime.dispatch(
                            _ctx(adapter, user, operation), f"完成道源任务 {label}"
                        )
                        assert completed.code == "DAO_ORIGIN_TASK_RECORDED"
                        assert completed.data["progress"]["completed"] == index + 1
                        if index < 2:
                            assert completed.data["reward"] == {}
                        else:
                            assert completed.data["reward"]["dao_fruit_progress"] == DAO_ORIGIN_REWARDS[task_key]["dao_fruit_progress"]
                            assert completed.data["reward"]["ascension_merit"] == DAO_ORIGIN_REWARDS[task_key]["ascension_merit"]
                            assert completed.data["reward"]["world_merit"] > 0
                        replay = await runtime.dispatch(
                            _ctx(adapter, user, operation), f"完成道源任务 {label}"
                        )
                        assert replay.data["idempotent_replay"] is True
                exhausted = await runtime.dispatch(
                    _ctx(adapter, user, f"exhausted-{adapter}"), "完成道源任务 守界"
                )
                assert exhausted.code == "QUEST_ALREADY_COMPLETED"

                with sqlite3.connect(runtime.settings.database_path) as connection:
                    resources = connection.execute(
                        "SELECT dao_fruit_progress, ascension_merit, world_merit FROM players WHERE platform = ? AND platform_user_id = ?",
                        (adapter, user),
                    ).fetchone()
                    event_count = connection.execute(
                        "SELECT COUNT(*) FROM quest_events JOIN players ON players.id = quest_events.player_id "
                        "WHERE players.platform = ? AND players.platform_user_id = ? AND quest_key = 'event.dao_origin'",
                        (adapter, user),
                    ).fetchone()[0]
                    event_versions = connection.execute(
                        "SELECT DISTINCT quest_events.content_version, quest_events.rule_version FROM quest_events "
                        "JOIN players ON players.id = quest_events.player_id "
                        "WHERE players.platform = ? AND players.platform_user_id = ? "
                        "AND quest_key IN ('event.dao_origin', 'task.dao_origin.guard', 'task.dao_origin.build', 'task.dao_origin.teach')",
                        (adapter, user),
                    ).fetchall()
                    progress_versions = connection.execute(
                        "SELECT DISTINCT quest_progress.content_version, quest_progress.rule_version FROM quest_progress "
                        "JOIN players ON players.id = quest_progress.player_id "
                        "WHERE players.platform = ? AND players.platform_user_id = ? "
                        "AND quest_key IN ('task.dao_origin.guard', 'task.dao_origin.build', 'task.dao_origin.teach')",
                        (adapter, user),
                    ).fetchall()
                assert resources == (470, 450, 1_000)
                assert event_count == 9
                assert {tuple(row) for row in event_versions} == {("content-0.6", "events-0.6.0")}
                assert {tuple(row) for row in progress_versions} == {("content-0.6", "events-0.6.0")}

                clock.advance(days=36)
                season_id, _, _ = final_heaven_season_window(clock.value)
                stale = await runtime.dispatch(
                    _ctx(adapter, user, f"stale-source-{adapter}"), "完成道源任务 守界"
                )
                assert stale.code == "ENDGAME_EVENT_REQUIREMENT_MISSING"
                status = await runtime.dispatch(
                    _ctx(adapter, user, f"season-status-{adapter}"), "高阶任务"
                )
                assert status.data["quests"]["task.dao_origin.guard"]["progress"] == {
                    "completed": 0,
                    "target": 3,
                }
                assert status.data["quests"]["task.dao_origin.guard"]["season_id"] == season_id
            await runtime.close()

    asyncio.run(run())


def test_tribulation_and_dao_origin_rewards_match_documented_totals() -> None:
    assert sum(TRIBULATION_PROGRESS_REWARD.values()) == 530
    assert sum(TRIBULATION_MERIT_REWARD.values()) == 550
    assert sum(reward["dao_fruit_progress"] for reward in DAO_ORIGIN_REWARDS.values()) == 470
    assert sum(reward["ascension_merit"] for reward in DAO_ORIGIN_REWARDS.values()) == 450
    assert sum(TRIBULATION_PROGRESS_REWARD.values()) + sum(
        reward["dao_fruit_progress"] for reward in DAO_ORIGIN_REWARDS.values()
    ) == 1_000
    assert sum(TRIBULATION_MERIT_REWARD.values()) + sum(
        reward["ascension_merit"] for reward in DAO_ORIGIN_REWARDS.values()
    ) == 1_000


def test_dao_union_qualification_requires_server_evidence_and_freezes_snapshot() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            for adapter, user in (("qq.official", "qq-dao-quest"), ("onebot.v11", "ob-dao-quest")):
                await _create(runtime, adapter, user)
                _set_player(
                    runtime,
                    adapter,
                    user,
                    stage="cultivator",
                    realm_key="void_refining",
                    realm_layer=10,
                    location_key="cave.boundary_realm",
                    total_cultivation=2_998_960,
                    path_key="body",
                    qualification_json=json.dumps({"body": 100_000}),
                    max_hp=500_000,
                    initiative=1_000,
                    inventory_json=json.dumps({"item.masterwork.body": 1}),
                )
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    player_id = connection.execute(
                        "SELECT id FROM players WHERE platform = ? AND platform_user_id = ?",
                        (adapter, user),
                    ).fetchone()[0]
                    for stage in range(1, 4):
                        connection.execute(
                            "INSERT INTO mainline_runs(player_id, story_key, chapter, stage, stage_key, status, first_clear_key, content_version, rule_version, created_at, updated_at) "
                            "VALUES (?, 'story.mainline.xuantian', 1, ?, ?, 'claimed', ?, 'content-test', 'rule-test', 'created', 'updated')",
                            (player_id, stage, f"chapter.1.stage.{stage}", f"{user}-mainline-{stage}"),
                        )

                rejected_xuantian = await runtime.dispatch(
                    _ctx(adapter, user, f"mainline-xuantian-{adapter}"), "记录合道主线"
                )
                assert rejected_xuantian.code == "QUEST_REQUIREMENT_MISSING"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    assert connection.execute(
                        "SELECT COUNT(*) FROM quest_events WHERE player_id=? AND quest_key='quest.dao_union' "
                        "AND component_key='three_realm_mainline'",
                        (player_id,),
                    ).fetchone()[0] == 0
                    for lane in DAO_UNION_MAINLINE_LANES[:2]:
                        for chapter, stage_key in enumerate(DAO_UNION_MAINLINE_STAGE_KEYS[lane], start=1):
                            connection.execute(
                                "INSERT INTO mainline_runs(player_id, story_key, chapter, stage, stage_key, status, "
                                "first_clear_key, content_version, rule_version, created_at, updated_at) "
                                "VALUES (?, ?, ?, 1, ?, 'claimed', ?, ?, ?, 'created', 'updated')",
                                (
                                    player_id,
                                    DAO_UNION_MAINLINE_STORY_KEY,
                                    chapter,
                                    stage_key,
                                    f"{user}-{stage_key}",
                                    DAO_UNION_MAINLINE_CONTENT_VERSION,
                                    DAO_UNION_MAINLINE_RULE_VERSION,
                                ),
                            )

                partial_lanes = await runtime.dispatch(
                    _ctx(adapter, user, f"mainline-partial-{adapter}"), "记录合道主线"
                )
                assert partial_lanes.code == "QUEST_REQUIREMENT_MISSING"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    for chapter, stage_key in enumerate(DAO_UNION_MAINLINE_STAGE_KEYS["traveler"], start=1):
                        connection.execute(
                            "INSERT INTO mainline_runs(player_id, story_key, chapter, stage, stage_key, status, "
                            "first_clear_key, content_version, rule_version, created_at, updated_at) "
                            "VALUES (?, ?, ?, 1, ?, 'claimed', ?, ?, ?, 'created', 'updated')",
                            (
                                player_id,
                                DAO_UNION_MAINLINE_STORY_KEY,
                                chapter,
                                stage_key,
                                f"{user}-{stage_key}",
                                DAO_UNION_MAINLINE_CONTENT_VERSION,
                                DAO_UNION_MAINLINE_RULE_VERSION,
                            ),
                        )

                mainline = await runtime.dispatch(
                    _ctx(adapter, user, f"mainline-{adapter}"), "记录合道主线"
                )
                assert mainline.code == "QUEST_ACTION_RECORDED"
                challenge = await runtime.dispatch(
                    _ctx(adapter, user, f"challenge-{adapter}"), "开始合道挑战"
                )
                assert challenge.code == "DAO_UNION_CHALLENGE_SETTLED"
                assert challenge.data["outcome"] == "won"
                assert challenge.data["progress"]["cross_server_challenge"] == 1
                work = await runtime.dispatch(
                    _ctx(adapter, user, f"work-{adapter}"), "交付合道作品"
                )
                assert work.code == "QUEST_ACTION_RECORDED"
                permit = await runtime.dispatch(
                    _ctx(adapter, user, f"permit-{adapter}"), "领取合道许可"
                )
                assert permit.code == "QUEST_PERMIT_GRANTED"
                assert permit.data["snapshot"]["path_key"] == "body"
                assert permit.data["snapshot"]["components"] == {
                    "three_realm_mainline": 1,
                    "cross_server_challenge": 1,
                    "endgame_work": 1,
                }
                replay = await runtime.dispatch(
                    _ctx(adapter, user, f"permit-{adapter}"), "领取合道许可"
                )
                assert replay.data["idempotent_replay"] is True
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    state = connection.execute(
                        "SELECT intro_json, inventory_json FROM players WHERE id = ?", (player_id,)
                    ).fetchone()
                    event_versions = connection.execute(
                        "SELECT DISTINCT content_version, rule_version FROM quest_events "
                        "WHERE player_id = ? AND quest_key = 'quest.dao_union'",
                        (player_id,),
                    ).fetchall()
                    progress_version = connection.execute(
                        "SELECT content_version, rule_version FROM quest_progress "
                        "WHERE player_id = ? AND quest_key = 'quest.dao_union'",
                        (player_id,),
                    ).fetchone()
                assert "quest.dao_union" in json.loads(state[0])["flags"]
                assert json.loads(state[1]).get("item.masterwork.body", 0) == 0
                assert {tuple(row) for row in event_versions} == {("content-0.6", "quests-0.6.0")}
                assert tuple(progress_version) == ("content-0.6", "quests-0.6.0")
            await runtime.close()

    asyncio.run(run())


def test_endgame_recipes_require_dao_origin_gate_on_qq_and_onebot() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            for adapter, user in (("qq.official", "qq-origin-gate"), ("onebot.v11", "ob-origin-gate")):
                await _create(runtime, adapter, user)
                _set_player(runtime, adapter, user, stage="cultivator", realm_key="tribulation", realm_layer=10)
                for recipe_key, recipe in ENDGAME_RECIPES.items():
                    realm_key = recipe.required_realm
                    _set_player(runtime, adapter, user, realm_key=realm_key)
                    blocked = await runtime.dispatch(
                        _ctx(adapter, user, f"wrong-place-{recipe_key}"),
                        f"开始终局配方 {recipe_key}",
                    )
                    assert blocked.code == "ENDGAME_RECIPE_CONTEXT_INVALID"

                _set_player(
                    runtime,
                    adapter,
                    user,
                    realm_key="dao_union",
                    realm_layer=1,
                    endgame_status="dao_union",
                    location_key="dao.origin_gate",
                    inventory_json=json.dumps({"item.dao_fruit_fragment": 10, "item.soul_crystal": 5}),
                )
                started = await runtime.dispatch(
                    _ctx(adapter, user, f"at-origin-gate-{adapter}"),
                    "开始终局配方 recipe.dao.fruit_fragment",
                )
                assert started.code == "ENDGAME_RECIPE_STARTED"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    snapshot_json = connection.execute(
                        "SELECT snapshot_json FROM endgame_sessions WHERE session_id = ?",
                        (started.data["session_id"],),
                    ).fetchone()[0]
                assert json.loads(snapshot_json)["location_key"] == "dao.origin_gate"
            await runtime.close()

    asyncio.run(run())


def test_dao_fruit_recipe_cap_spans_dao_union_and_tribulation_chain() -> None:
    async def run() -> None:
        clock = MutableClock()
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            for adapter, user in (("qq.official", "qq-fruit-chain"), ("onebot.v11", "ob-fruit-chain")):
                await _create(runtime, adapter, user)
                _set_player(
                    runtime,
                    adapter,
                    user,
                    stage="cultivator",
                    realm_key="dao_union",
                    realm_layer=1,
                    endgame_status="dao_union",
                    location_key="dao.origin_gate",
                    inventory_json=json.dumps({"item.dao_fruit_fragment": 10, "item.soul_crystal": 5}),
                )
                for attempt in range(1, 4):
                    success = attempt != 2
                    operation = next(
                        f"{adapter}-fruit-chain-start-{attempt}-{index}"
                        for index in range(1_000)
                        if (recipe_roll_bp(f"{adapter}-fruit-chain-start-{attempt}-{index}") < 8_000) is success
                    )
                    _set_player(
                        runtime,
                        adapter,
                        user,
                        inventory_json=json.dumps({"item.dao_fruit_fragment": 10, "item.soul_crystal": 5}),
                    )
                    started = await runtime.dispatch(
                        _ctx(adapter, user, operation),
                        "开始终局配方 recipe.dao.fruit_fragment",
                    )
                    assert started.code == "ENDGAME_RECIPE_STARTED"
                    clock.advance(minutes=21)
                    settled = await runtime.dispatch(
                        _ctx(adapter, user, f"{adapter}-fruit-chain-settle-{attempt}"), "结算终局配方"
                    )
                    assert settled.code == "ENDGAME_RECIPE_SETTLED"
                    assert settled.data["success"] is success
                    if attempt == 1:
                        _set_player(
                            runtime,
                            adapter,
                            user,
                            realm_key="tribulation",
                            realm_layer=1,
                            endgame_status="tribulation",
                        )

                _set_player(
                    runtime,
                    adapter,
                    user,
                    inventory_json=json.dumps({"item.dao_fruit_fragment": 10, "item.soul_crystal": 5}),
                )
                exhausted = await runtime.dispatch(
                    _ctx(adapter, user, f"{adapter}-fruit-chain-fourth"),
                    "开始终局配方 recipe.dao.fruit_fragment",
                )
                assert exhausted.code == "ENDGAME_RECIPE_ALREADY_CREATED"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    state = connection.execute(
                        "SELECT inventory_json, (SELECT COUNT(*) FROM endgame_sessions WHERE player_id=p.id "
                        "AND session_type='recipe.dao.fruit_fragment') FROM players p "
                        "WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    ).fetchone()
                assert json.loads(state[0]) == {"item.dao_fruit_fragment": 10, "item.soul_crystal": 5}
                assert state[1] == 3
            await runtime.close()

    asyncio.run(run())


def test_dao_origin_gate_travel_has_atomic_gates_and_daily_limit() -> None:
    async def run() -> None:
        clock = MutableClock()
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            for adapter, user in (("qq.official", "qq-gate-travel"), ("onebot.v11", "ob-gate-travel")):
                await _create(runtime, adapter, user)
                _set_player(
                    runtime,
                    adapter,
                    user,
                    stage="cultivator",
                    realm_key="dao_union",
                    realm_layer=6,
                    location_key="void.archive_ruins",
                    dao_fruit_progress=499,
                    stamina=30,
                    stamina_max=30,
                    inventory_json=json.dumps({"item.dao_fruit_fragment": 2}),
                )
                missing_progress = await runtime.dispatch(
                    _ctx(adapter, user, f"preview-progress-{adapter}"), "移动预览 道源门"
                )
                assert missing_progress.data["ready"] is False
                assert "道果进度" in missing_progress.data["missing"]
                blocked = await runtime.dispatch(
                    _ctx(adapter, user, f"gate-progress-{adapter}"), "前往 道源门"
                )
                assert blocked.code == "DAO_ORIGIN_REQUIREMENT_MISSING"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    unchanged = connection.execute(
                        "SELECT stamina, inventory_json FROM players WHERE platform = ? AND platform_user_id = ?",
                        (adapter, user),
                    ).fetchone()
                assert unchanged == (30, json.dumps({"item.dao_fruit_fragment": 2}))

                _set_player(runtime, adapter, user, dao_fruit_progress=500)
                ready = await runtime.dispatch(
                    _ctx(adapter, user, f"preview-ready-{adapter}"), "移动预览 道源门"
                )
                assert ready.data["ready"] is True
                assert ready.data["duration_seconds"] == 3_600
                assert ready.data["stamina_cost"] == 20
                assert ready.data["pass_key"] == "item.dao_fruit_fragment"
                assert ready.data["pass_quantity"] == 2
                assert ready.data["daily_start_limit"] == 1

                started = await runtime.dispatch(
                    _ctx(adapter, user, f"gate-start-{adapter}"), "前往 道源门"
                )
                assert started.code == "TRAVEL_STARTED"
                replay = await runtime.dispatch(
                    _ctx(adapter, user, f"gate-start-{adapter}"), "前往 道源门"
                )
                assert replay.data["idempotent_replay"] is True
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    row = connection.execute(
                        "SELECT stamina, inventory_json, location_key FROM players WHERE platform = ? AND platform_user_id = ?",
                        (adapter, user),
                    ).fetchone()
                    snapshot_json = connection.execute(
                        "SELECT snapshot_json FROM travel_sessions WHERE session_id = ?",
                        (started.data["session_id"],),
                    ).fetchone()[0]
                    connection.execute(
                        "UPDATE travel_sessions SET ends_at = ? WHERE session_id = ?",
                        ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(), started.data["session_id"]),
                    )
                assert row == (10, "{}", "void.archive_ruins")
                snapshot = json.loads(snapshot_json)
                assert snapshot["rule_version"] == "world-0.6.0"
                assert snapshot["content_version"] == "content-0.6"
                assert snapshot["required_dao_fruit_progress"] == 500
                assert snapshot["daily_start_limit"] == 1
                arrived = await runtime.dispatch(
                    _ctx(adapter, user, f"gate-settle-{adapter}"), "结算移动"
                )
                assert arrived.code == "TRAVEL_COMPLETED"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    location = connection.execute(
                        "SELECT location_key FROM players WHERE platform = ? AND platform_user_id = ?",
                        (adapter, user),
                    ).fetchone()[0]
                assert location == "dao.origin_gate"

                _set_player(
                    runtime,
                    adapter,
                    user,
                    location_key="void.archive_ruins",
                    stamina=30,
                    inventory_json=json.dumps({"item.dao_fruit_fragment": 2}),
                )
                exhausted = await runtime.dispatch(
                    _ctx(adapter, user, f"preview-daily-{adapter}"), "移动预览 道源门"
                )
                assert exhausted.data["ready"] is False
                assert "今日访问次数" in exhausted.data["missing"]
                blocked_daily = await runtime.dispatch(
                    _ctx(adapter, user, f"gate-daily-{adapter}"), "前往 道源门"
                )
                assert blocked_daily.code == "DAO_ORIGIN_REQUIREMENT_MISSING"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    after_daily_block = connection.execute(
                        "SELECT stamina, inventory_json FROM players WHERE platform = ? AND platform_user_id = ?",
                        (adapter, user),
                    ).fetchone()
                assert after_daily_block == (30, json.dumps({"item.dao_fruit_fragment": 2}))

                clock.advance(days=1)
                next_day = await runtime.dispatch(
                    _ctx(adapter, user, f"preview-next-day-{adapter}"), "移动预览 道源门"
                )
                assert next_day.data["ready"] is True
            await runtime.close()

    asyncio.run(run())


def test_endgame_recipe_replay_failure_refund_and_final_battle_preview_path() -> None:
    async def run() -> None:
        clock = MutableClock()
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            adapter, user = "onebot.v11", "endgame-recipe"
            await _create(runtime, adapter, user)
            _set_player(
                runtime,
                adapter,
                user,
                stage="cultivator",
                realm_key="tribulation",
                realm_layer=10,
                endgame_status="tribulation",
                dao_fruit_progress=1_000,
                ascension_merit=1_000,
                world_merit=1_000,
                location_key="dao.origin_gate",
                inventory_json=json.dumps({"item.dao_fruit_fragment": 10, "item.soul_crystal": 5}),
            )
            with sqlite3.connect(runtime.settings.database_path) as connection:
                player_id = connection.execute(
                    "SELECT id FROM players WHERE platform = ? AND platform_user_id = ?", (adapter, user)
                ).fetchone()[0]
                for index, trial_key in enumerate(
                    ("trial.body_and_mind", "trial.three_realms", "trial.dao_choice"), start=1
                ):
                    connection.execute(
                        "INSERT INTO tribulation_trial_sessions(session_id, player_id, operation_id, trial_key, status, starts_at, ends_at, result_json, created_at, updated_at) "
                        "VALUES (?, ?, ?, ?, 'succeeded', 'start', 'end', '{}', 'created', 'updated')",
                        (f"{user}-trial-{index}", player_id, f"{user}-trial-op-{index}", trial_key),
                    )

            success_operation = next(
                f"fruit-success-{index}"
                for index in range(1_000)
                if recipe_roll_bp(f"start-fruit-success-{index}") < 8_000
            )
            started = await runtime.dispatch(
                _ctx(adapter, user, f"start-{success_operation}"),
                "开始终局配方 recipe.dao.fruit_fragment",
            )
            assert started.code == "ENDGAME_RECIPE_STARTED"
            replay_start = await runtime.dispatch(
                _ctx(adapter, user, f"start-{success_operation}"),
                "开始终局配方 道果碎片加工",
            )
            assert replay_start.data["idempotent_replay"] is True
            clock.advance(minutes=21)
            settled = await runtime.dispatch(
                _ctx(adapter, user, "settle-fruit-success"), "结算终局配方"
            )
            assert settled.code == "ENDGAME_RECIPE_SETTLED"
            assert settled.data["success"] is True
            assert settled.data["dao_fruit_progress"] == 1_100
            replay = await runtime.dispatch(
                _ctx(adapter, user, "settle-fruit-success"), "结算终局配方"
            )
            assert replay.data["idempotent_replay"] is True

            failure_operation = next(
                f"fruit-failure-{index}"
                for index in range(1_000)
                if recipe_roll_bp(f"start-fruit-failure-{index}") >= 8_000
            )
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE players SET inventory_json = ? WHERE id = ?",
                    (json.dumps({"item.dao_fruit_fragment": 10, "item.soul_crystal": 5}), player_id),
                )
            failed_start = await runtime.dispatch(
                _ctx(adapter, user, f"start-{failure_operation}"),
                "开始终局配方 recipe.dao.fruit_fragment",
            )
            assert failed_start.code == "ENDGAME_RECIPE_STARTED"
            clock.advance(minutes=21)
            failed = await runtime.dispatch(_ctx(adapter, user, "settle-fruit-failure"), "结算终局配方")
            assert failed.data["success"] is False
            assert failed.data["refunds"] == {"item.dao_fruit_fragment": 5}
            assert failed.data["dao_fruit_progress"] == 1_100

            _set_player(runtime, adapter, user, inventory_json=json.dumps({}))
            certificate_op = next(
                f"certificate-{index}"
                for index in range(1_000)
                if recipe_roll_bp(f"start-certificate-{index}") < 8_000
            )
            cert_started = await runtime.dispatch(
                _ctx(adapter, user, f"start-{certificate_op}"),
                "开始终局配方 recipe.ascension.certificate",
            )
            assert cert_started.code == "ENDGAME_RECIPE_STARTED"
            clock.advance(minutes=11)
            cert = await runtime.dispatch(
                _ctx(adapter, user, "settle-certificate"), "结算终局配方"
            )
            assert cert.data["success"] is True
            assert cert.data["rewards"] == {"item.ascension_certificate": 1}
            assert cert.data["dao_fruit_progress"] == 1_100
            assert cert.data["ascension_merit"] == 1_000
            assert cert.data["world_merit"] == 0

            preview = await runtime.dispatch(_ctx(adapter, user, "final-preview"), "终局战预览")
            assert preview.data["ready"] is True
            assert preview.data["runtime_open"] is False
            await runtime.close()

    asyncio.run(run())


def test_endgame_recipe_frontier_is_atomic_when_requirements_are_missing() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            adapter, user = "qq.official", "endgame-recipe-blocked"
            await _create(runtime, adapter, user)
            _set_player(
                runtime,
                adapter,
                user,
                realm_key="tribulation",
                realm_layer=10,
                location_key="dao.origin_gate",
                world_merit=999,
            )
            blocked = await runtime.dispatch(
                _ctx(adapter, user, "certificate-blocked"),
                "开始终局配方 recipe.ascension.certificate",
            )
            assert blocked.code == "ENDGAME_RECIPE_CONTEXT_INVALID"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                state = connection.execute(
                    "SELECT world_merit, dao_fruit_progress, ascension_merit FROM players WHERE platform = ? AND platform_user_id = ?",
                    (adapter, user),
                ).fetchone()
                sessions = connection.execute("SELECT COUNT(*) FROM endgame_sessions").fetchone()[0]
            assert state == (999, 0, 0)
            assert sessions == 0
            await runtime.close()

    asyncio.run(run())


def test_tribulation_guard_is_locked_returned_on_success_and_consumed_on_failure() -> None:
    async def run() -> None:
        clock = MutableClock()
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            for adapter, user, succeeded in (
                ("qq.official", "guard-success", True),
                ("onebot.v11", "guard-failure", False),
            ):
                await _create(runtime, adapter, user)
                _set_player(
                    runtime,
                    adapter,
                    user,
                    stage="cultivator",
                    realm_key="tribulation",
                    realm_layer=3,
                    location_key="tribulation.sky_terrace",
                    path_key="body",
                    inventory_json=json.dumps({"item.tribulation_token": 1, "item.tribulation_guard": 1}),
                )
                operation = next(
                    f"{user}-trial-{index}"
                    for index in range(1_000)
                    if (trial_roll_bp(f"{user}-trial-{index}") < 7_000) is succeeded
                )
                started = await runtime.dispatch(
                    _ctx(adapter, user, operation), "开始天劫试炼 身心劫"
                )
                assert started.code == "TRIAL_STARTED"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    during = json.loads(
                        connection.execute(
                            "SELECT inventory_json FROM players WHERE platform = ? AND platform_user_id = ?",
                            (adapter, user),
                        ).fetchone()[0]
                    )
                assert during.get("item.tribulation_guard", 0) == 0
                clock.advance(minutes=31)
                settled = await runtime.dispatch(
                    _ctx(adapter, user, f"settle-{user}"), "结算天劫试炼"
                )
                assert settled.data["success"] is succeeded
                assert settled.data["tribulation_debt"] == (0 if succeeded else 5)
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    after = json.loads(
                        connection.execute(
                            "SELECT inventory_json FROM players WHERE platform = ? AND platform_user_id = ?",
                            (adapter, user),
                        ).fetchone()[0]
                    )
                assert after.get("item.tribulation_guard", 0) == (1 if succeeded else 0)
            await runtime.close()

    asyncio.run(run())


def test_endgame_recipes_and_trials_are_state_gated_and_mutually_exclusive() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            recipe_user = "qq-trial-recipe-lock"
            await _create(runtime, "qq.official", recipe_user)
            _set_player(
                runtime,
                "qq.official",
                recipe_user,
                realm_key="tribulation",
                realm_layer=3,
                endgame_status="tribulation",
                domain_key="domain.body",
                location_key="dao.origin_gate",
                inventory_json=json.dumps({"item.tribulation_token": 1, "item.domain_core": 3}),
            )
            recipe = await runtime.dispatch(
                _ctx("qq.official", recipe_user, "guard-recipe"), "开始终局配方 recipe.tribulation.guard"
            )
            assert recipe.code == "ENDGAME_RECIPE_STARTED"
            blocked_trial = await runtime.dispatch(
                _ctx("qq.official", recipe_user, "trial-blocked"), "开始天劫试炼 身心劫"
            )
            assert blocked_trial.code == "TRIBULATION_TRIAL_BUSY"

            trial_user = "onebot-trial-recipe-lock"
            await _create(runtime, "onebot.v11", trial_user)
            _set_player(
                runtime,
                "onebot.v11",
                trial_user,
                realm_key="tribulation",
                realm_layer=3,
                endgame_status="tribulation",
                domain_key="domain.body",
                location_key="tribulation.sky_terrace",
                inventory_json=json.dumps({"item.tribulation_token": 1, "item.domain_core": 3}),
            )
            trial = await runtime.dispatch(
                _ctx("onebot.v11", trial_user, "trial-first"), "开始天劫试炼 身心劫"
            )
            assert trial.code == "TRIAL_STARTED"
            blocked_recipe = await runtime.dispatch(
                _ctx("onebot.v11", trial_user, "recipe-blocked"), "开始终局配方 recipe.tribulation.guard"
            )
            assert blocked_recipe.code == "ENDGAME_RECIPE_BUSY"

            ended_user = "onebot-ended-recipe"
            await _create(runtime, "onebot.v11", ended_user)
            _set_player(
                runtime,
                "onebot.v11",
                ended_user,
                realm_key="tribulation",
                realm_layer=10,
                endgame_status="ascended",
                domain_key="domain.body",
                location_key="dao.origin_gate",
                inventory_json=json.dumps({"item.tribulation_token": 1, "item.domain_core": 3}),
            )
            ended_recipe = await runtime.dispatch(
                _ctx("onebot.v11", ended_user, "ended-recipe"), "开始终局配方 recipe.tribulation.guard"
            )
            assert ended_recipe.code == "PLAYER_SUSPENDED"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute(
                    "SELECT COUNT(*) FROM endgame_sessions WHERE player_id = "
                    "(SELECT id FROM players WHERE platform_user_id = ?)",
                    (ended_user,),
                ).fetchone()[0] == 0

            race_user = "qq-trial-recipe-race"
            await _create(runtime, "qq.official", race_user)
            _set_player(
                runtime,
                "qq.official",
                race_user,
                realm_key="tribulation",
                realm_layer=3,
                endgame_status="tribulation",
                domain_key="domain.body",
                location_key="dao.origin_gate",
                inventory_json=json.dumps({"item.tribulation_token": 1, "item.domain_core": 3}),
            )
            trial_result, recipe_result = await asyncio.gather(
                runtime.dispatch(
                    _ctx("qq.official", race_user, "race-trial"), "开始天劫试炼 身心劫"
                ),
                runtime.dispatch(
                    _ctx("qq.official", race_user, "race-recipe"),
                    "开始终局配方 recipe.tribulation.guard",
                ),
            )
            assert {trial_result.code, recipe_result.code} in (
                {"TRIAL_STARTED", "ENDGAME_RECIPE_BUSY"},
                {"TRIBULATION_TRIAL_BUSY", "ENDGAME_RECIPE_STARTED"},
                {"TRIBULATION_LOCATION_REQUIRED", "ENDGAME_RECIPE_STARTED"},
            )
            with sqlite3.connect(runtime.settings.database_path) as connection:
                active_count = connection.execute(
                    "SELECT "
                    "(SELECT COUNT(*) FROM tribulation_trial_sessions WHERE player_id = p.id AND status = 'preparing') + "
                    "(SELECT COUNT(*) FROM endgame_sessions WHERE player_id = p.id AND status = 'preparing') "
                    "FROM players p WHERE p.platform = ? AND p.platform_user_id = ?",
                    ("qq.official", race_user),
                ).fetchone()[0]
            assert active_count == 1
            await runtime.close()

    asyncio.run(run())
