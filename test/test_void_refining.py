from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.persistence.sqlite_repository import SQLitePlayerRepository
from nonebot_plugin_xiuxian_3.xiuxian.progression.breakthrough.rules import breakthrough_roll_bp
from nonebot_plugin_xiuxian_3.xiuxian.world.void_rules import void_route_roll_bp


def _ctx(adapter: str, user: str, operation: str) -> CommandContext:
    return CommandContext(adapter=adapter, user_id=user, operation_id=operation)


def _past_breakthrough(runtime, session_id: str) -> None:
    with sqlite3.connect(runtime.settings.database_path) as db:
        db.execute(
            "UPDATE breakthrough_sessions SET ends_at = ? WHERE session_id = ?",
            ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(), session_id),
        )


def _past_route(runtime, session_id: str) -> None:
    with sqlite3.connect(runtime.settings.database_path) as db:
        db.execute(
            "UPDATE void_route_sessions SET ends_at = ? WHERE session_id = ?",
            ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(), session_id),
        )


def test_void_route_discovery_migration_counts_distinct_settled_routes() -> None:
    with sqlite3.connect(":memory:") as connection:
        connection.executescript(
            """
            CREATE TABLE players (id INTEGER PRIMARY KEY, void_route_count INTEGER NOT NULL);
            CREATE TABLE void_route_sessions (
                player_id INTEGER NOT NULL,
                route_key TEXT NOT NULL,
                status TEXT NOT NULL
            );
            CREATE TABLE progression_milestones (milestone_key TEXT PRIMARY KEY, status TEXT NOT NULL);
            INSERT INTO players VALUES (1, 4);
            INSERT INTO void_route_sessions VALUES
                (1, 'void.first_route', 'settled'),
                (1, 'void.first_route', 'settled'),
                (1, 'void.archive_ruins', 'settled'),
                (1, 'void.void_market', 'settled'),
                (1, 'void.sect_fortress', 'settled');
            INSERT INTO progression_milestones VALUES ('milestone.void_refining_late', 'unlocked');
            """
        )

        SQLitePlayerRepository._migrate_void_route_discovery_count(connection)

        assert connection.execute("SELECT void_route_count FROM players WHERE id=1").fetchone()[0] == 2
        assert connection.execute(
            "SELECT status FROM progression_milestones WHERE milestone_key='milestone.void_refining_late'"
        ).fetchone()[0] == "unlocked"


async def _prepare_void_player(runtime, user: str, *, adapter: str = "web") -> None:
    assert (await runtime.dispatch(_ctx(adapter, user, f"create-{user}"), "开始修仙")).ok
    with sqlite3.connect(runtime.settings.database_path) as db:
        db.execute(
            "UPDATE players SET stage='cultivator', realm_key='soul_transformation', realm_layer=10, cultivation=500000, total_cultivation=848960, spirit_stones=100000, world_merit=1000, domain_charge=150, domain_power=500, location_key='void.first_route', stamina=100, stamina_max=100, inventory_json=?, intro_json=? WHERE platform_user_id=? AND platform=?",
            (
                json.dumps({"item.void_crystal": 5, "item.void_anchor": 5}),
                json.dumps({"flags": ["quest.break_void"]}),
                user,
                adapter,
            ),
        )


def test_void_refining_success_initializes_resources_and_is_idempotent() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            await _prepare_void_player(runtime, "void-success")
            operation = next(
                f"void-success-{i}"
                for i in range(1000)
                if breakthrough_roll_bp(f"void-success-{i}") < 7_950
            )
            started = await runtime.dispatch(_ctx("web", "void-success", operation), "开始突破 炼虚")
            assert started.code == "BREAKTHROUGH_STARTED"
            assert started.data["success_bp"] == 7_550
            _past_breakthrough(runtime, started.data["session_id"])
            settled = await runtime.dispatch(_ctx("web", "void-success", "void-settle"), "结算突破")
            replay = await runtime.dispatch(_ctx("web", "void-success", "void-settle"), "结算突破")
            assert settled.code == "BREAKTHROUGH_SUCCEEDED"
            assert replay.data["idempotent_replay"] is True
            with sqlite3.connect(runtime.settings.database_path) as db:
                row = db.execute(
                    "SELECT realm_key, realm_layer, void_power, void_power_max, space_resistance_bp, void_anchor_capacity, max_hp, max_mp, carry_capacity, world_merit, domain_charge FROM players WHERE platform_user_id='void-success'"
                ).fetchone()
            assert row == ("void_refining", 1, 200, 200, 1500, 20, 1500, 1200, 100, 1000, 50)
            await runtime.close()

    asyncio.run(run())


def test_void_refining_gate_and_failure_do_not_charge_incorrectly() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            await _prepare_void_player(runtime, "void-failure")
            with sqlite3.connect(runtime.settings.database_path) as db:
                db.execute("UPDATE players SET intro_json=? WHERE platform_user_id='void-failure'", (json.dumps({"flags": []}),))
            blocked = await runtime.dispatch(_ctx("web", "void-failure", "void-gate"), "开始突破 炼虚")
            assert blocked.code == "VOID_QUEST_MISSING"
            with sqlite3.connect(runtime.settings.database_path) as db:
                assert db.execute("SELECT spirit_stones, world_merit, domain_charge FROM players WHERE platform_user_id='void-failure'").fetchone() == (100000, 1000, 150)
                db.execute("UPDATE players SET intro_json=? WHERE platform_user_id='void-failure'", (json.dumps({"flags": ["quest.break_void"]}),))
            operation = next(
                f"void-failure-{i}"
                for i in range(1000)
                if breakthrough_roll_bp(f"void-failure-{i}") >= 7_950
            )
            started = await runtime.dispatch(_ctx("web", "void-failure", operation), "开始突破 炼虚")
            _past_breakthrough(runtime, started.data["session_id"])
            settled = await runtime.dispatch(_ctx("web", "void-failure", "void-failure-settle"), "结算突破")
            assert settled.code == "BREAKTHROUGH_FAILED"
            with sqlite3.connect(runtime.settings.database_path) as db:
                row = db.execute("SELECT realm_key, realm_layer, cultivation, breakthrough_pity_bp, void_instability_until, world_merit, domain_charge FROM players WHERE platform_user_id='void-failure'").fetchone()
            assert row[0:4] == ("soul_transformation", 10, 375000, 250)
            assert row[4] and row[5:] == (500, 50)
            await runtime.close()

    asyncio.run(run())


def test_void_refining_failure_replays_and_recovers_after_instability_expires() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            for adapter, user in (("qq.official", "qq-void-recovery"), ("onebot.v11", "ob-void-recovery")):
                await _prepare_void_player(runtime, user, adapter=adapter)
                with sqlite3.connect(runtime.settings.database_path) as db:
                    db.execute(
                        "UPDATE players SET intro_json=? WHERE platform=? AND platform_user_id=?",
                        (json.dumps({"flags": ["quest.break_void", "story.mainline.three_realms"]}), adapter, user),
                    )
                    db.execute(
                        "UPDATE players SET inventory_json=? WHERE platform=? AND platform_user_id=?",
                        (json.dumps({"item.void_crystal": 5, "item.void_anchor": 7}), adapter, user),
                    )
                    player_id = db.execute(
                        "SELECT id FROM players WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    ).fetchone()[0]
                    for index in range(3):
                        db.execute(
                            "INSERT INTO quest_events(player_id, quest_key, component_key, source_operation_id, outcome, payload_json, content_version, rule_version, created_at) "
                            "VALUES (?, 'quest.break_void', 'void_wall_trial', ?, 'success', '{}', '', '', 'created')",
                            (player_id, f"{user}-wall-trial-{index}"),
                        )

                failed_operation = next(
                    f"{user}-failed-breakthrough-{index}"
                    for index in range(1_000)
                    if breakthrough_roll_bp(f"{user}-failed-breakthrough-{index}") >= 7_550
                )
                started = await runtime.dispatch(
                    _ctx(adapter, user, failed_operation), "开始突破 炼虚"
                )
                assert started.code == "BREAKTHROUGH_STARTED"
                _past_breakthrough(runtime, started.data["session_id"])
                failed = await runtime.dispatch(
                    _ctx(adapter, user, f"{user}-settle-failed-breakthrough"), "结算突破"
                )
                assert failed.code == "BREAKTHROUGH_FAILED"
                assert failed.data["weakness_until"]
                with sqlite3.connect(runtime.settings.database_path) as db:
                    failed_state = db.execute(
                        "SELECT spirit_stones, world_merit, domain_charge, inventory_json, void_instability_until "
                        "FROM players WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    ).fetchone()
                failed_inventory = json.loads(failed_state[3])
                assert failed_inventory["item.void_crystal"] == 0
                assert failed_inventory["item.void_anchor"] == 5
                assert failed_state[:3] == (20_000, 500, 50)
                instability_until = datetime.fromisoformat(failed_state[4])
                assert abs(
                    (instability_until - datetime.now(timezone.utc)).total_seconds()
                    - 48 * 60 * 60
                ) < 10

                replay = await runtime.dispatch(
                    _ctx(adapter, user, f"{user}-settle-failed-breakthrough"), "结算突破"
                )
                assert replay.data["idempotent_replay"] is True
                with sqlite3.connect(runtime.settings.database_path) as db:
                    assert db.execute(
                        "SELECT spirit_stones, world_merit, domain_charge, inventory_json, void_instability_until "
                        "FROM players WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    ).fetchone() == failed_state

                blocked = await runtime.dispatch(
                    _ctx(adapter, user, f"{user}-archive-during-instability"),
                    "进入虚空航道 档案遗迹",
                )
                assert blocked.code == "VOID_INSTABILITY_ACTIVE"
                with sqlite3.connect(runtime.settings.database_path) as db:
                    db.execute(
                        "UPDATE players SET void_instability_until=? WHERE platform=? AND platform_user_id=?",
                        (
                            (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
                            adapter,
                            user,
                        ),
                    )

                recovered = await runtime.dispatch(
                    _ctx(adapter, user, f"{user}-archive-after-instability"),
                    "进入虚空航道 档案遗迹",
                )
                assert recovered.code == "VOID_ROUTE_STARTED"
                assert recovered.data["anchor_cost"] == 4
                with sqlite3.connect(runtime.settings.database_path) as db:
                    player_state = db.execute(
                        "SELECT void_instability_until, inventory_json, stamina FROM players "
                        "WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    ).fetchone()
                assert player_state[0] is None
                assert json.loads(player_state[1])["item.void_anchor"] == 1
                assert player_state[2] == 60
            await runtime.close()

    asyncio.run(run())


def test_void_refining_materials_can_be_replenished_after_failure_on_both_adapters() -> None:
    async def run() -> None:
        for adapter in ("qq.official", "onebot.v11"):
            current = [datetime(2026, 9, 21, 12, tzinfo=timezone.utc)]
            clock = lambda: current[0]
            with TemporaryDirectory() as data_dir:
                runtime = create_runtime(data_dir=data_dir, clock=clock)
                user = f"void-replenish-{adapter}"
                await _prepare_void_player(runtime, user, adapter=adapter)
                with sqlite3.connect(runtime.settings.database_path) as db:
                    db.execute(
                        "UPDATE players SET intro_json=? WHERE platform=? AND platform_user_id=?",
                        (json.dumps({"flags": ["quest.break_void", "story.mainline.three_realms"]}), adapter, user),
                    )
                    db.execute(
                        "UPDATE players SET inventory_json=?, qualification_json=?, max_hp=10000, initiative=100, "
                        "stamina=100, domain_charge_max=150, location_key='cave.boundary_realm' "
                        "WHERE platform=? AND platform_user_id=?",
                        (
                            json.dumps({"item.void_anchor": 10}),
                            json.dumps({"body": 10000, "spirit": 10000, "insight": 10000, "root": 10000, "agility": 10000}),
                            adapter,
                            user,
                        ),
                    )

                to_portal = await runtime.adapters.dispatch(
                    adapter, _ctx(adapter, user, f"{user}-portal-start"), "前往 虚空门户"
                )
                assert to_portal.code == "TRAVEL_STARTED"
                current[0] += timedelta(minutes=5)
                assert (
                    await runtime.adapters.dispatch(
                        adapter, _ctx(adapter, user, f"{user}-portal-settle"), "结算移动"
                    )
                ).code == "TRAVEL_COMPLETED"
                for index in range(3):
                    trial = await runtime.adapters.dispatch(
                        adapter,
                        _ctx(adapter, user, f"{user}-initial-trial-{index}"),
                        "开始界壁试炼",
                    )
                    assert trial.code == "VOID_WALL_TRIAL_RECORDED"
                    assert trial.data["outcome"] == "won"

                archive_operation = next(
                    f"{user}-initial-archive-{index}"
                    for index in range(1000)
                    if void_route_roll_bp(f"{user}-initial-archive-{index}") >= 1_500
                )
                archive = await runtime.adapters.dispatch(
                    adapter, _ctx(adapter, user, archive_operation), "进入虚空航道 档案遗迹"
                )
                assert archive.code == "VOID_ROUTE_STARTED"
                current[0] += timedelta(minutes=45)
                assert (
                    await runtime.adapters.dispatch(
                        adapter, _ctx(adapter, user, f"{user}-initial-archive-settle"), "结算虚空航道"
                    )
                ).code == "VOID_ROUTE_SETTLED"

                # Keep the controlled reset limited to the depleted material
                # precondition. Qualification, route and battle evidence above
                # still came from public commands; the material itself is the
                # documented one-time test fixture for the failed attempt.
                with sqlite3.connect(runtime.settings.database_path) as db:
                    db.execute(
                        "UPDATE players SET inventory_json=? WHERE platform=? AND platform_user_id=?",
                        (json.dumps({"item.void_crystal": 5, "item.void_anchor": 10}), adapter, user),
                    )

                failed_operation = next(
                    f"{user}-failed-{index}"
                    for index in range(1000)
                    if breakthrough_roll_bp(f"{user}-failed-{index}") >= 7_550
                )
                started = await runtime.adapters.dispatch(
                    adapter, _ctx(adapter, user, failed_operation), "开始突破 炼虚"
                )
                assert started.code == "BREAKTHROUGH_STARTED"
                with sqlite3.connect(runtime.settings.database_path) as db:
                    db.execute(
                        "UPDATE breakthrough_sessions SET ends_at=? WHERE session_id=?",
                        ((current[0] - timedelta(seconds=1)).isoformat(), started.data["session_id"]),
                    )
                failed = await runtime.adapters.dispatch(
                    adapter, _ctx(adapter, user, f"{user}-failed-settle"), "结算突破"
                )
                assert failed.code == "BREAKTHROUGH_FAILED"
                with sqlite3.connect(runtime.settings.database_path) as db:
                    inventory = json.loads(
                        db.execute(
                            "SELECT inventory_json FROM players WHERE platform=? AND platform_user_id=?",
                            (adapter, user),
                        ).fetchone()[0]
                    )
                assert inventory["item.void_crystal"] == 0
                assert inventory["item.void_anchor"] == 8

                current[0] += timedelta(days=7)
                refreshed = await runtime.adapters.dispatch(
                    adapter, _ctx(adapter, user, f"{user}-resource-recovery"), "恢复状态"
                )
                assert refreshed.ok and refreshed.data["stamina"] >= 70, refreshed.data
                profile = await runtime.adapters.dispatch(
                    adapter, _ctx(adapter, user, f"{user}-daily-domain-reset"), "我的状态"
                )
                assert profile.ok
                archive_operation = next(
                    f"{user}-archive-{index}"
                    for index in range(1000)
                    if void_route_roll_bp(f"{user}-archive-{index}") >= 1_500
                )
                archive = await runtime.adapters.dispatch(
                    adapter,
                    _ctx(adapter, user, archive_operation),
                    "进入虚空航道 档案遗迹",
                )
                assert archive.code == "VOID_ROUTE_STARTED"
                current[0] += timedelta(minutes=45)
                settled_archive = await runtime.adapters.dispatch(
                    adapter, _ctx(adapter, user, f"{user}-archive-settle"), "结算虚空航道"
                )
                assert settled_archive.code == "VOID_ROUTE_SETTLED"

                to_boundary = await runtime.adapters.dispatch(
                    adapter, _ctx(adapter, user, f"{user}-boundary-start"), "前往 界隙秘境"
                )
                assert to_boundary.code == "TRAVEL_STARTED"
                current[0] += timedelta(minutes=10)
                assert (
                    await runtime.adapters.dispatch(
                        adapter, _ctx(adapter, user, f"{user}-boundary-settle"), "结算移动"
                    )
                    ).code == "TRAVEL_COMPLETED"
                to_portal = await runtime.adapters.dispatch(
                    adapter, _ctx(adapter, user, f"{user}-portal-retry-start"), "前往 虚空门户"
                )
                assert to_portal.code == "TRAVEL_STARTED"
                current[0] += timedelta(minutes=5)
                assert (
                    await runtime.adapters.dispatch(
                        adapter, _ctx(adapter, user, f"{user}-portal-retry-settle"), "结算移动"
                    )
                ).code == "TRAVEL_COMPLETED"
                for index in range(3):
                    trial = await runtime.adapters.dispatch(
                        adapter,
                        _ctx(adapter, user, f"{user}-trial-{index}"),
                        "开始界壁试炼",
                    )
                    assert trial.code == "VOID_WALL_TRIAL_RECORDED"
                    assert trial.data["outcome"] == "won"

                with sqlite3.connect(runtime.settings.database_path) as db:
                    inventory = json.loads(
                        db.execute(
                            "SELECT inventory_json FROM players WHERE platform=? AND platform_user_id=?",
                            (adapter, user),
                        ).fetchone()[0]
                    )
                assert inventory["item.void_crystal"] == 7
                assert inventory["item.void_anchor"] == 10

                # Replenish the breakthrough fee through the public market
                # path. The collaborator balance is a controlled seller-side
                # precondition; the main player's wallet and merit are never
                # written back after the failed operation.
                helper_adapter = "onebot.v11" if adapter == "qq.official" else "qq.official"
                helper = f"void-replenish-helper-{adapter}"
                helper_created = await runtime.adapters.dispatch(
                    helper_adapter,
                    _ctx(helper_adapter, helper, f"{user}-helper-create"),
                    "开始修仙",
                )
                assert helper_created.code == "PLAYER_CREATED"
                with sqlite3.connect(runtime.settings.database_path) as db:
                    db.execute(
                        "UPDATE players SET spirit_stones=100000 WHERE platform=? AND platform_user_id=?",
                        (helper_adapter, helper),
                    )
                    failed_wallet = db.execute(
                        "SELECT spirit_stones, world_merit FROM players WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    ).fetchone()
                    helper_wallet_before = db.execute(
                        "SELECT spirit_stones FROM players WHERE platform=? AND platform_user_id=?",
                        (helper_adapter, helper),
                    ).fetchone()[0]
                assert failed_wallet == (20_000, 500)

                listed = await runtime.adapters.dispatch(
                    adapter,
                    _ctx(adapter, user, f"{user}-replenish-list"),
                    "发布摆摊 item.void_crystal 1 90000",
                )
                assert listed.code == "MARKET_ORDER_CREATED"
                purchased = await runtime.adapters.dispatch(
                    helper_adapter,
                    _ctx(helper_adapter, helper, f"{user}-replenish-buy"),
                    f"购买摆摊 {listed.data['order_id']}",
                )
                assert purchased.code == "MARKET_ORDER_PURCHASED"
                with sqlite3.connect(runtime.settings.database_path) as db:
                    replenished_wallet = db.execute(
                        "SELECT spirit_stones, world_merit, inventory_json FROM players "
                        "WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    ).fetchone()
                    helper_wallet_after = db.execute(
                        "SELECT spirit_stones, inventory_json FROM players WHERE platform=? AND platform_user_id=?",
                        (helper_adapter, helper),
                    ).fetchone()
                assert replenished_wallet[0] >= 80_000
                assert replenished_wallet[1] == failed_wallet[1]
                assert json.loads(replenished_wallet[2]).get("item.void_crystal", 0) == 6
                assert helper_wallet_after[0] < helper_wallet_before
                assert json.loads(helper_wallet_after[1]).get("item.void_crystal", 0) == 1

                current[0] += timedelta(hours=12)
                refreshed_again = await runtime.adapters.dispatch(
                    adapter, _ctx(adapter, user, f"{user}-resource-recovery-again"), "恢复状态"
                )
                assert refreshed_again.ok and refreshed_again.data["stamina"] >= 40, refreshed_again.data
                second_archive = next(
                    f"{user}-archive-retry-{index}"
                    for index in range(1000)
                    if void_route_roll_bp(f"{user}-archive-retry-{index}") >= 1_500
                )
                retry_route = await runtime.adapters.dispatch(
                    adapter,
                    _ctx(adapter, user, second_archive),
                    "进入虚空航道 档案遗迹",
                )
                assert retry_route.code == "VOID_ROUTE_STARTED"
                current[0] += timedelta(minutes=45)
                assert (
                    await runtime.adapters.dispatch(
                        adapter, _ctx(adapter, user, f"{user}-retry-route-settle"), "结算虚空航道"
                    )
                ).code == "VOID_ROUTE_SETTLED"

                retry_operation = next(
                    f"{user}-retry-breakthrough-{index}"
                    for index in range(1000)
                    if breakthrough_roll_bp(f"{user}-retry-breakthrough-{index}") < 7_550
                )
                retry = await runtime.adapters.dispatch(
                    adapter, _ctx(adapter, user, retry_operation), "开始突破 炼虚"
                )
                assert retry.code == "BREAKTHROUGH_STARTED"
                await runtime.close()

    asyncio.run(run())


def test_void_refining_world_merit_can_be_replenished_by_public_events_before_retry() -> None:
    async def run() -> None:
        for adapter in ("qq.official", "onebot.v11"):
            current = [datetime(2026, 9, 21, 12, tzinfo=timezone.utc)]
            runtime = None
            with TemporaryDirectory() as data_dir:
                runtime = create_runtime(data_dir=data_dir, clock=lambda: current[0])
                user = f"void-merit-{adapter}"
                await _prepare_void_player(runtime, user, adapter=adapter)
                with sqlite3.connect(runtime.settings.database_path) as db:
                    # Start at the exact fee so the failed breakthrough exhausts
                    # world merit; this is a controlled test precondition.
                    db.execute(
                        "UPDATE players SET world_merit=500, spirit_stones=160000, inventory_json=?, max_hp=10000, initiative=100, stamina=100, stamina_max=100, domain_charge_max=150, qualification_json=? WHERE platform=? AND platform_user_id=?",
                        (
                            json.dumps({"item.void_crystal": 5, "item.void_anchor": 8}),
                            json.dumps({"body": 10000, "spirit": 10000, "insight": 10000, "root": 10000, "agility": 10000}),
                            adapter,
                            user,
                        ),
                    )

                failed_operation = next(
                    f"{user}-failed-{index}"
                    for index in range(1000)
                    if breakthrough_roll_bp(f"{user}-failed-{index}") >= 7_550
                )
                started = await runtime.adapters.dispatch(
                    adapter, _ctx(adapter, user, failed_operation), "开始突破 炼虚"
                )
                assert started.code == "BREAKTHROUGH_STARTED"
                with sqlite3.connect(runtime.settings.database_path) as db:
                    db.execute(
                        "UPDATE breakthrough_sessions SET ends_at=? WHERE session_id=?",
                        ((current[0] - timedelta(seconds=1)).isoformat(), started.data["session_id"]),
                    )
                failed = await runtime.adapters.dispatch(
                    adapter, _ctx(adapter, user, f"{user}-failed-settle"), "结算突破"
                )
                assert failed.code == "BREAKTHROUGH_FAILED"
                with sqlite3.connect(runtime.settings.database_path) as db:
                    failed_state = db.execute(
                        "SELECT world_merit, inventory_json FROM players WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    ).fetchone()
                assert failed_state[0] == 0
                assert json.loads(failed_state[1])["item.void_crystal"] == 0

                # Domain-front rounds are public event sources. The sect and
                # staging location are controlled access prerequisites only.
                current[0] += timedelta(days=7)
                status = await runtime.adapters.dispatch(
                    adapter, _ctx(adapter, user, f"{user}-recover"), "恢复状态"
                )
                assert status.ok
                profile = await runtime.adapters.dispatch(
                    adapter, _ctx(adapter, user, f"{user}-daily-reset"), "我的状态"
                )
                assert profile.ok and profile.data["domain_charge"] >= 100, profile.data
                with sqlite3.connect(runtime.settings.database_path) as db:
                    player_id = db.execute(
                        "SELECT id FROM players WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    ).fetchone()[0]
                    now = current[0].isoformat()
                    db.execute(
                        "UPDATE players SET domain_key='domain.fire', location_key='xuantian.domain_front' WHERE id=?",
                        (player_id,),
                    )
                    db.execute(
                        "INSERT INTO sects(sect_id,name,name_key,motto,leader_id,status,level,max_members,warehouse_capacity,construction,spirit_stones,sect_merit,warehouse_json,created_at,updated_at,content_version,rule_version) VALUES (?, ?, ?, '', ?, 'active', 4, 20, 100, 0, 0, 0, '{}', ?, ?, '', '')",
                        (f"void-merit-sect-{adapter}", "功勋补给宗", f"void-merit-sect-{adapter}", player_id, now, now),
                    )
                    db.execute(
                        "INSERT INTO sect_members(sect_id,player_id,role,status,contribution,joined_at,last_action_at,created_at,updated_at) VALUES (?, ?, 'leader', 'active', 0, ?, ?, ?, ?)",
                        (f"void-merit-sect-{adapter}", player_id, now, now, now, now),
                    )

                for round_index in range(5):
                    event = await runtime.adapters.dispatch(
                        adapter, _ctx(adapter, user, f"{user}-event-status-{round_index}"), "领域前线"
                    )
                    assert event.code == "DOMAIN_EVENT_STATUS"
                    round_id = event.data["round_id"]
                    joined = await runtime.adapters.dispatch(
                        adapter, _ctx(adapter, user, f"{user}-event-join-{round_index}"), "加入领域前线"
                    )
                    assert joined.code == "DOMAIN_EVENT_JOINED"
                    battle = await runtime.adapters.dispatch(
                        adapter, _ctx(adapter, user, f"{user}-event-battle-{round_index}"), "开始领域战"
                    )
                    assert battle.code == "DOMAIN_BATTLE_SETTLED"
                    contribution = await runtime.adapters.dispatch(
                        adapter,
                        _ctx(adapter, user, f"{user}-event-contribute-{round_index}"),
                        "贡献领域前线 战斗",
                    )
                    assert contribution.code == "DOMAIN_EVENT_CONTRIBUTION_RECORDED"
                    current[0] += timedelta(minutes=31)
                    settled = await runtime.adapters.dispatch(
                        adapter,
                        _ctx(adapter, user, f"{user}-event-settle-{round_index}"),
                        f"领域前线 {round_id}",
                    )
                    assert settled.data["status"] == "settled"
                    claimed = await runtime.adapters.dispatch(
                        adapter,
                        _ctx(adapter, user, f"{user}-event-claim-{round_index}"),
                        f"领取领域前线奖励 {round_id}",
                    )
                    assert claimed.code == "DOMAIN_EVENT_REWARD_CLAIMED"
                    assert claimed.data["reward"]["world_merit"] == 100
                    if round_index < 4:
                        current[0] += timedelta(hours=3, minutes=29)

                with sqlite3.connect(runtime.settings.database_path) as db:
                    merit, inventory = db.execute(
                        "SELECT world_merit, inventory_json FROM players WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    ).fetchone()
                assert merit == 500
                assert json.loads(inventory)["item.domain_core_fragment"] == 25

                # Material replenishment is isolated to this retry precondition;
                # world merit above came only from public event claims.
                with sqlite3.connect(runtime.settings.database_path) as db:
                    db.execute(
                        "UPDATE players SET location_key='void.first_route', inventory_json=? WHERE platform=? AND platform_user_id=?",
                        (json.dumps({"item.void_crystal": 5, "item.void_anchor": 8}), adapter, user),
                    )
                retry_operation = next(
                    f"{user}-retry-{index}"
                    for index in range(1000)
                    if breakthrough_roll_bp(f"{user}-retry-{index}") < 7_800
                )
                retry = await runtime.adapters.dispatch(
                    adapter, _ctx(adapter, user, retry_operation), "开始突破 炼虚"
                )
                assert retry.code == "BREAKTHROUGH_STARTED"
                with sqlite3.connect(runtime.settings.database_path) as db:
                    db.execute(
                        "UPDATE breakthrough_sessions SET ends_at=? WHERE session_id=?",
                        ((current[0] - timedelta(seconds=1)).isoformat(), retry.data["session_id"]),
                    )
                settled_retry = await runtime.adapters.dispatch(
                    adapter, _ctx(adapter, user, f"{user}-retry-settle"), "结算突破"
                )
                assert settled_retry.code == "BREAKTHROUGH_SUCCEEDED"
                with sqlite3.connect(runtime.settings.database_path) as db:
                    realm, final_merit = db.execute(
                        "SELECT realm_key, world_merit FROM players WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    ).fetchone()
                assert realm == "void_refining"
                assert final_merit == 500
                await runtime.close()

    asyncio.run(run())


def test_void_route_resistance_floor_and_adapter_simulation() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            await _prepare_void_player(runtime, "qq-void", adapter="qq.official")
            with sqlite3.connect(runtime.settings.database_path) as db:
                db.execute("UPDATE players SET realm_key='void_refining', realm_layer=1, space_resistance_bp=7500, inventory_json=?, stamina=100 WHERE platform='qq.official' AND platform_user_id='qq-void'", (json.dumps({"item.void_anchor": 2}),))
            qq = await runtime.dispatch(_ctx("qq.official", "qq-void", "qq-route"), "进入虚空航道 第一航道")
            assert qq.code == "VOID_ROUTE_STARTED" and qq.data["anchor_cost"] == 2
            with sqlite3.connect(runtime.settings.database_path) as db:
                anchors = json.loads(db.execute("SELECT inventory_json FROM players WHERE platform='qq.official' AND platform_user_id='qq-void'").fetchone()[0])["item.void_anchor"]
            assert anchors == 0
            _past_route(runtime, qq.data["session_id"])
            qq_settled = await runtime.dispatch(_ctx("qq.official", "qq-void", "qq-settle"), "结算虚空航道")
            assert qq_settled.code == "VOID_ROUTE_SETTLED"

            await _prepare_void_player(runtime, "ob-void", adapter="onebot.v11")
            with sqlite3.connect(runtime.settings.database_path) as db:
                db.execute("UPDATE players SET realm_key='void_refining', realm_layer=1, inventory_json=?, stamina=100 WHERE platform='onebot.v11' AND platform_user_id='ob-void'", (json.dumps({"item.void_anchor": 3}),))
            onebot = await runtime.dispatch(_ctx("onebot.v11", "ob-void", "ob-route"), "进入虚空航道 第一航道")
            assert onebot.code == "VOID_ROUTE_STARTED"
            _past_route(runtime, onebot.data["session_id"])
            replay = await runtime.dispatch(_ctx("onebot.v11", "ob-void", "ob-settle"), "结算虚空航道")
            replay_again = await runtime.dispatch(_ctx("onebot.v11", "ob-void", "ob-settle"), "结算虚空航道")
            assert replay.code == "VOID_ROUTE_SETTLED"
            assert replay_again.data["idempotent_replay"] is True
            await runtime.close()

    asyncio.run(run())


def test_higher_realms_can_reenter_archive_route_on_both_adapters() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            for adapter, user in (("qq.official", "qq-high-route"), ("onebot.v11", "ob-high-route")):
                seller = f"{user}-anchor-seller"
                await runtime.dispatch(_ctx(adapter, user, f"create-{user}"), "开始修仙")
                await runtime.dispatch(_ctx(adapter, seller, f"create-{seller}"), "开始修仙")
                with sqlite3.connect(runtime.settings.database_path) as db:
                    db.execute(
                        "UPDATE players SET stage='cultivator', realm_key='tribulation', realm_layer=3, "
                        "location_key='void.portal', stamina=100, space_resistance_bp=0, "
                        "spirit_stones=10, inventory_json='{}' WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    )
                    db.execute(
                        "UPDATE players SET location_key='void.portal', spirit_stones=1000, inventory_json=? "
                        "WHERE platform=? AND platform_user_id=?",
                        (json.dumps({"item.void_anchor": 4}), adapter, seller),
                    )
                listing = await runtime.dispatch(
                    _ctx(adapter, seller, f"{seller}-list"),
                    "发布摆摊 item.void_anchor 4 1",
                )
                assert listing.code == "MARKET_ORDER_CREATED", (adapter, listing.code, listing.message)
                purchase = await runtime.dispatch(
                    _ctx(adapter, user, f"{user}-buy"),
                    f"购买摆摊 {listing.data['order_id']} 4",
                )
                assert purchase.code == "MARKET_ORDER_PURCHASED"
                operation = f"{user}-archive-route"
                started = await runtime.dispatch(
                    _ctx(adapter, user, operation), "进入虚空航道 档案遗迹"
                )
                assert started.code == "VOID_ROUTE_STARTED", (adapter, started.code, started.message)
                assert started.data["anchor_cost"] == 4
                with sqlite3.connect(runtime.settings.database_path) as db:
                    snapshot_json = db.execute(
                        "SELECT snapshot_json FROM void_route_sessions WHERE session_id=?",
                        (started.data["session_id"],),
                    ).fetchone()[0]
                assert "rule_version" not in json.loads(snapshot_json)
            await runtime.close()

    asyncio.run(run())


def test_void_power_recovers_once_per_business_day() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            user = "void-recovery"
            assert (await runtime.dispatch(_ctx("web", user, "void-recovery-create"), "开始修仙")).ok
            yesterday = (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()
            with sqlite3.connect(runtime.settings.database_path) as db:
                db.execute(
                    "UPDATE players SET void_power=0, void_power_max=200, void_power_reset_date=?, stamina=30, stamina_max=30, energy=30, energy_max=30, updated_at=? WHERE platform_user_id=?",
                    (yesterday, datetime.now(timezone.utc).isoformat(), user),
                )
            recovered = await runtime.dispatch(_ctx("web", user, "void-recovery-1"), "恢复状态")
            assert recovered.code == "RESOURCES_RECOVERED"
            assert recovered.data["recovered_void_power"] == 200
            assert recovered.data["void_power"] == 200
            assert "虚力" in recovered.message

            second = await runtime.dispatch(_ctx("web", user, "void-recovery-2"), "恢复状态")
            assert second.code == "RESOURCES_ALREADY_FULL"
            assert second.data["recovered_void_power"] == 0
            assert second.data["void_power"] == 200
            await runtime.close()

    asyncio.run(run())


def test_void_route_instability_cost_and_insufficient_anchor_atomicity() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            await _prepare_void_player(runtime, "void-unstable")
            unstable_until = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
            with sqlite3.connect(runtime.settings.database_path) as db:
                db.execute(
                    "UPDATE players SET realm_key='void_refining', realm_layer=1, space_resistance_bp=0, void_instability_until=?, inventory_json=?, stamina=100 WHERE platform_user_id=?",
                    (unstable_until, json.dumps({"item.void_anchor": 4}), "void-unstable"),
                )
            started = await runtime.dispatch(_ctx("web", "void-unstable", "unstable-route"), "进入虚空航道 第一航道")
            assert started.code == "VOID_ROUTE_STARTED"
            assert started.data["anchor_cost"] == 4
            with sqlite3.connect(runtime.settings.database_path) as db:
                    assert db.execute("SELECT stamina, inventory_json FROM players WHERE platform_user_id=?", ("void-unstable",)).fetchone()[0] == 65

            await _prepare_void_player(runtime, "void-no-anchor")
            with sqlite3.connect(runtime.settings.database_path) as db:
                db.execute(
                    "UPDATE players SET realm_key='void_refining', realm_layer=1, inventory_json=?, stamina=10 WHERE platform_user_id=?",
                    (json.dumps({}), "void-no-anchor"),
                )
            blocked = await runtime.dispatch(_ctx("web", "void-no-anchor", "no-anchor-route"), "进入虚空航道 第一航道")
            assert blocked.code == "VOID_ANCHOR_INSUFFICIENT"
            with sqlite3.connect(runtime.settings.database_path) as db:
                row = db.execute("SELECT stamina, inventory_json FROM players WHERE platform_user_id=?", ("void-no-anchor",)).fetchone()
            assert row[0] == 10 and json.loads(row[1]) == {}
            await runtime.close()

    asyncio.run(run())
