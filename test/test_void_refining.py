from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.progression.breakthrough.rules import breakthrough_roll_bp


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
                assert json.loads(snapshot_json)["rule_version"] == "world-0.5.1"
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
