from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime


def _context(adapter: str, user: str, operation_id: str) -> CommandContext:
    return CommandContext(adapter=adapter, user_id=user, operation_id=operation_id)


def _prepare_player(runtime, adapter: str, user: str, *, realm: str, layer: int, location: str, body: int, ticket: int = 0) -> None:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE players SET stage='cultivator', realm_key=?, realm_layer=?, location_key=?, stamina=30, stamina_max=30, "
            "qualification_json=?, inventory_json=? WHERE platform=? AND platform_user_id=?",
            (
                realm,
                layer,
                location,
                json.dumps({"body": body, "agility": 20}),
                json.dumps({"item.cave_pass_basic": ticket}),
                adapter,
                user,
            ),
    )


async def _create_and_seek(runtime, adapter: str, user: str) -> None:
    assert (await runtime.dispatch(_context(adapter, user, f"{adapter}-create"), "开始修仙")).ok
    assert (await runtime.dispatch(_context(adapter, user, f"{adapter}-seek"), "寻仙问道")).ok


def test_qq_and_onebot_secret_realm_preview_are_isolated() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, adapters=("qq.official", "onebot.v11"))
            for adapter, user in (("qq.official", "qq-secret-preview"), ("onebot.v11", "ob-secret-preview")):
                assert (await runtime.adapters.dispatch(adapter, _context(adapter, user, f"{adapter}-create"), "开始修仙")).ok
                assert (await runtime.adapters.dispatch(adapter, _context(adapter, user, f"{adapter}-seek"), "寻仙问道")).ok
            qq = await runtime.adapters.dispatch("qq.official", _context("qq.official", "qq-secret-preview", "qq-preview"), "秘境预览")
            ob = await runtime.adapters.dispatch("onebot.v11", _context("onebot.v11", "ob-secret-preview", "ob-preview"), "秘境预览")
            assert qq.code == ob.code == "SECRET_REALM_PREVIEW"
            assert {item["instance_key"] for item in qq.data["realms"]} == {
                "instance.secret_realm.mist_grotto",
                "instance.secret_realm.spring_path",
                "instance.secret_realm.mist_depth_2",
                "instance.secret_realm.cloud_boat",
                "instance.secret_realm.demon_abyss",
                "instance.secret_realm.ancient_domain",
                    "instance.secret_realm.ancestral_hall",
                    "instance.secret_realm.void_ruins",
                    "instance.secret_realm.time_fort",
                }
            demon_abyss = next(
                item
                for item in qq.data["realms"]
                if item["instance_key"] == "instance.secret_realm.demon_abyss"
            )
            assert demon_abyss["first_reward"]["story.demon_abyss_echo"] == 1
            await runtime.close()

    asyncio.run(run())


def test_mist_grotto_enforces_nodes_and_is_idempotent() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, adapters=("qq.official",))
            user = "qq-secret-mist"
            await runtime.dispatch(_context("qq.official", user, "create"), "开始修仙")
            await runtime.dispatch(_context("qq.official", user, "seek"), "寻仙问道")
            _prepare_player(runtime, "qq.official", user, realm="qi_gathering", layer=4, location="cave.mist_grotto", body=100, ticket=1)
            jumped = await runtime.dispatch(_context("qq.official", user, "jump"), "选择秘境节点 遭遇")
            assert jumped.code == "SECRET_REALM_NOT_FOUND"
            entered = await runtime.dispatch(_context("qq.official", user, "enter"), "进入秘境 雾隐秘境")
            assert entered.code == "SECRET_REALM_ENTERED"
            resource = await runtime.dispatch(_context("qq.official", user, "resource"), "选择秘境节点 资源")
            assert resource.data["current_node"] == "encounter"
            encounter = await runtime.dispatch(_context("qq.official", user, "encounter"), "选择秘境节点 遭遇")
            assert encounter.code == "SECRET_REALM_COMBAT_PENDING"
            replay = await runtime.dispatch(_context("qq.official", user, "encounter"), "选择秘境节点 遭遇")
            assert replay.code == "SECRET_REALM_COMBAT_PENDING"
            assert replay.data["battle_id"] == encounter.data["battle_id"]
            progressed = await runtime.dispatch(_context("qq.official", user, "combat-settle"), "结算秘境")
            assert progressed.data["status"] == "routing"
            assert progressed.data["current_node"] == "choice"
            choice = await runtime.dispatch(_context("qq.official", user, "choice"), "选择秘境节点 选择")
            assert choice.data["status"] == "cleared"
            settled = await runtime.dispatch(_context("qq.official", user, "settle"), "结算秘境")
            assert settled.code == "SECRET_REALM_SETTLED"
            assert settled.data["reward"]["spirit_stones"] == 80
            replay_settlement = await runtime.dispatch(_context("qq.official", user, "settle"), "结算秘境")
            assert replay_settlement.data["idempotent_replay"] is True
            with sqlite3.connect(runtime.settings.database_path) as connection:
                status, node_index, battle_count = connection.execute(
                    "SELECT status, node_index, (SELECT COUNT(*) FROM battle_sessions) FROM secret_realm_runs"
                ).fetchone()
                assert (status, node_index, battle_count) == ("settled", 3, 1)
            await runtime.close()

    asyncio.run(run())


def test_secret_realm_battle_failure_refunds_ticket_but_not_stamina() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, adapters=("onebot.v11",))
            user = "ob-secret-fail"
            await runtime.dispatch(_context("onebot.v11", user, "create"), "开始修仙")
            await runtime.dispatch(_context("onebot.v11", user, "seek"), "寻仙问道")
            _prepare_player(runtime, "onebot.v11", user, realm="qi_gathering", layer=4, location="cave.mist_grotto", body=0, ticket=1)
            await runtime.dispatch(_context("onebot.v11", user, "enter"), "进入秘境 雾隐秘境")
            await runtime.dispatch(_context("onebot.v11", user, "resource"), "选择秘境节点 资源")
            await runtime.dispatch(_context("onebot.v11", user, "encounter"), "选择秘境节点 遭遇")
            result = await runtime.dispatch(_context("onebot.v11", user, "settle"), "结算秘境")
            assert result.code == "SECRET_REALM_SETTLED"
            assert result.data["reward"] == {}
            with sqlite3.connect(runtime.settings.database_path) as connection:
                inventory, stamina, status = connection.execute(
                    "SELECT p.inventory_json, p.stamina, r.status FROM players p JOIN secret_realm_runs r ON r.player_id=p.id"
                ).fetchone()
                assert json.loads(inventory)["item.cave_pass_basic"] == 1
                assert stamina == 20
                assert status == "settled"
            await runtime.close()

    asyncio.run(run())


def test_secret_realm_expiry_releases_locked_resources() -> None:
    async def run() -> None:
        now = datetime(2026, 9, 27, tzinfo=timezone.utc)
        current = [now]
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, adapters=("qq.official",), clock=lambda: current[0])
            user = "qq-secret-expire"
            await runtime.dispatch(_context("qq.official", user, "create"), "开始修仙")
            await runtime.dispatch(_context("qq.official", user, "seek"), "寻仙问道")
            _prepare_player(runtime, "qq.official", user, realm="qi_gathering", layer=4, location="cave.mist_grotto", body=100, ticket=1)
            entered = await runtime.dispatch(_context("qq.official", user, "enter"), "进入秘境 雾隐秘境")
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute("UPDATE secret_realm_runs SET expires_at=? WHERE run_id=?", ((now - timedelta(seconds=1)).isoformat(), entered.data["run_id"]))
            expired = await runtime.dispatch(_context("qq.official", user, "settle"), "结算秘境")
            assert expired.data["outcome"] == "expired"
            assert expired.data["stamina_refunded"] == 10
            await runtime.close()

    asyncio.run(run())


def test_spring_path_first_clear_grants_leaf_and_local_reputation() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, adapters=("onebot.v11",))
            user = "ob-secret-spring"
            await _create_and_seek(runtime, "onebot.v11", user)
            _prepare_player(
                runtime,
                "onebot.v11",
                user,
                realm="qi_sensing",
                layer=3,
                location="xuantian.spirit_field",
                body=100,
            )
            entered = await runtime.dispatch(
                _context("onebot.v11", user, "spring-enter"), "进入秘境 灵泉小径"
            )
            assert entered.code == "SECRET_REALM_ENTERED"
            resource = await runtime.dispatch(
                _context("onebot.v11", user, "spring-resource"), "选择秘境节点 资源"
            )
            assert resource.data["current_node"] == "encounter"
            encounter = await runtime.dispatch(
                _context("onebot.v11", user, "spring-encounter"), "选择秘境节点 遭遇"
            )
            assert encounter.code == "SECRET_REALM_COMBAT_PENDING"
            settled = await runtime.dispatch(
                _context("onebot.v11", user, "spring-settle"), "结算秘境"
            )
            assert settled.code == "SECRET_REALM_SETTLED"
            assert settled.data["reward"] == {"item.herb.spirit_leaf": 2, "local.xuantian.new_town": 5}
            with sqlite3.connect(runtime.settings.database_path) as connection:
                inventory, local_json = connection.execute(
                    "SELECT p.inventory_json, r.local_json FROM players p "
                    "JOIN player_reputations r ON r.player_id=p.id "
                    "WHERE p.platform=? AND p.platform_user_id=?",
                    ("onebot.v11", user),
                ).fetchone()
                assert json.loads(inventory)["item.herb.spirit_leaf"] == 2
                assert json.loads(local_json)["local.xuantian.new_town"] == 5
            limited = await runtime.dispatch(
                _context("onebot.v11", user, "spring-limited"), "进入秘境 灵泉小径"
            )
            assert limited.code == "SECRET_REALM_QUOTA_EXHAUSTED"
            await runtime.close()

    asyncio.run(run())


def test_mist_grotto_weekly_quota_counts_failed_runs() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, adapters=("qq.official",))
            user = "qq-secret-quota"
            await _create_and_seek(runtime, "qq.official", user)
            _prepare_player(
                runtime,
                "qq.official",
                user,
                realm="qi_gathering",
                layer=4,
                location="cave.mist_grotto",
                body=0,
                ticket=1,
            )
            for index in range(2):
                suffix = str(index)
                assert (
                    await runtime.dispatch(
                        _context("qq.official", user, f"quota-enter-{suffix}"), "进入秘境 雾隐秘境"
                    )
                ).ok
                assert (
                    await runtime.dispatch(
                        _context("qq.official", user, f"quota-resource-{suffix}"), "选择秘境节点 资源"
                    )
                ).ok
                assert (
                    await runtime.dispatch(
                        _context("qq.official", user, f"quota-encounter-{suffix}"), "选择秘境节点 遭遇"
                    )
                ).ok
                result = await runtime.dispatch(
                    _context("qq.official", user, f"quota-settle-{suffix}"), "结算秘境"
                )
                assert result.data["outcome"] == "lost"
            limited = await runtime.dispatch(
                _context("qq.official", user, "quota-blocked"), "进入秘境 雾隐秘境"
            )
            assert limited.code == "SECRET_REALM_QUOTA_EXHAUSTED"
            await runtime.close()

    asyncio.run(run())


def test_secret_realm_entry_resource_guards_are_atomic() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, adapters=("qq.official",))
            user = "qq-secret-resources"
            await _create_and_seek(runtime, "qq.official", user)
            _prepare_player(
                runtime,
                "qq.official",
                user,
                realm="qi_gathering",
                layer=4,
                location="cave.mist_grotto",
                body=100,
                ticket=0,
            )
            missing_ticket = await runtime.dispatch(
                _context("qq.official", user, "missing-ticket"), "进入秘境 雾隐秘境"
            )
            assert missing_ticket.code == "SECRET_REALM_REQUIREMENT_MISSING"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                stamina, inventory = connection.execute(
                    "SELECT stamina, inventory_json FROM players WHERE platform_user_id=?", (user,)
                ).fetchone()
                assert stamina == 30
                assert json.loads(inventory).get("item.cave_pass_basic", 0) == 0
                connection.execute(
                    "UPDATE players SET stamina=5, inventory_json=? WHERE platform_user_id=?",
                    (json.dumps({"item.cave_pass_basic": 1}), user),
                )
            low_stamina = await runtime.dispatch(
                _context("qq.official", user, "low-stamina"), "进入秘境 雾隐秘境"
            )
            assert low_stamina.code == "RESOURCE_INSUFFICIENT"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                stamina, inventory = connection.execute(
                    "SELECT stamina, inventory_json FROM players WHERE platform_user_id=?", (user,)
                ).fetchone()
                assert stamina == 5
                assert json.loads(inventory)["item.cave_pass_basic"] == 1
            await runtime.close()

    asyncio.run(run())
