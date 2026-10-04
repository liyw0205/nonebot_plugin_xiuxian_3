from __future__ import annotations

import asyncio
import json
import sqlite3
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime


def _context(adapter: str, user: str, operation_id: str) -> CommandContext:
    return CommandContext(adapter=adapter, user_id=user, operation_id=operation_id)


async def _create_and_seek(runtime, adapter: str, user: str) -> None:
    assert (await runtime.dispatch(_context(adapter, user, f"{adapter}-create"), "开始修仙")).ok
    assert (await runtime.dispatch(_context(adapter, user, f"{adapter}-seek"), "寻仙问道")).ok


def _prepare_golden_core(runtime, adapter: str, user: str, location: str, inventory: dict[str, int]) -> None:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE players SET stage='cultivator', realm_key='golden_core', realm_layer=1, "
            "location_key=?, stamina=100, stamina_max=100, max_hp=5000, initiative=100, "
            "qualification_json=?, inventory_json=? WHERE platform=? AND platform_user_id=?",
            (
                location,
                json.dumps({"body": 1000, "agility": 100}),
                json.dumps(inventory),
                adapter,
                user,
            ),
        )


def test_qq_mist_depth_two_supports_five_nodes_and_equipment_reward() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, adapters=("qq.official",))
            adapter = "qq.official"
            user = "qq-secret-depth"
            await _create_and_seek(runtime, adapter, user)
            _prepare_golden_core(runtime, adapter, user, "cave.mist_grotto_2", {"item.cave_pass_advanced": 1})

            entered = await runtime.dispatch(
                _context(adapter, user, "depth-enter"), "进入秘境 雾隐洞天二层秘境"
            )
            assert entered.code == "SECRET_REALM_ENTERED"
            assert entered.data["current_node"] == "resource"
            assert (
                await runtime.dispatch(
                    _context(adapter, user, "depth-resource"), "选择秘境节点 资源"
                )
            ).ok
            assert (
                await runtime.dispatch(
                    _context(adapter, user, "depth-encounter-1"), "选择秘境节点 遭遇"
                )
            ).code == "SECRET_REALM_COMBAT_PENDING"
            after_first = await runtime.dispatch(
                _context(adapter, user, "depth-settle-1"), "结算秘境"
            )
            assert after_first.data["current_node"] == "choice"
            choice_one = await runtime.dispatch(
                _context(adapter, user, "depth-choice-1"), "选择秘境节点 选择"
            )
            assert choice_one.data["current_node"] == "encounter"
            assert (
                await runtime.dispatch(
                    _context(adapter, user, "depth-encounter-2"), "选择秘境节点 遭遇"
                )
            ).code == "SECRET_REALM_COMBAT_PENDING"
            after_second = await runtime.dispatch(
                _context(adapter, user, "depth-settle-2"), "结算秘境"
            )
            assert after_second.data["current_node"] == "choice"
            choice_two = await runtime.dispatch(
                _context(adapter, user, "depth-choice-2"), "选择秘境节点 选择"
            )
            assert choice_two.data["status"] == "cleared"
            settled = await runtime.dispatch(
                _context(adapter, user, "depth-final"), "结算秘境"
            )
            assert settled.data["reward"] == {"item.weapon.cloud_sword": 1}
            replay = await runtime.dispatch(
                _context(adapter, user, "depth-final"), "结算秘境"
            )
            assert replay.data["idempotent_replay"] is True
            with sqlite3.connect(runtime.settings.database_path) as connection:
                equipment_count, pass_count, battle_count = connection.execute(
                    "SELECT "
                    "(SELECT COUNT(*) FROM equipment_instances WHERE player_id=p.id AND item_key='item.weapon.cloud_sword'), "
                    "COALESCE(json_extract(p.inventory_json, '$.item.cave_pass_advanced'), 0), "
                    "(SELECT COUNT(*) FROM battle_sessions WHERE player_id=p.id) "
                    "FROM players p WHERE p.platform=? AND p.platform_user_id=?",
                    (adapter, user),
                ).fetchone()
                assert (equipment_count, pass_count, battle_count) == (1, 0, 2)
                connection.execute(
                    "UPDATE players SET inventory_json=? WHERE platform=? AND platform_user_id=?",
                    (json.dumps({"item.cave_pass_advanced": 1}), adapter, user),
                )
            limited = await runtime.dispatch(
                _context(adapter, user, "depth-limited"), "进入秘境 雾隐洞天二层秘境"
            )
            assert limited.code == "SECRET_REALM_QUOTA_EXHAUSTED"
            await runtime.close()

    asyncio.run(run())


def test_onebot_cloud_boat_uses_ticket_and_projects_reputation() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, adapters=("onebot.v11",))
            adapter = "onebot.v11"
            user = "ob-secret-cloud"
            await _create_and_seek(runtime, adapter, user)
            _prepare_golden_core(
                runtime,
                adapter,
                user,
                "xuantian.floating_boat",
                {"item.ticket.cloud_boat_fragment": 1},
            )
            entered = await runtime.dispatch(
                _context(adapter, user, "cloud-enter"), "进入秘境 云舟秘境"
            )
            assert entered.code == "SECRET_REALM_ENTERED"
            assert (
                await runtime.dispatch(
                    _context(adapter, user, "cloud-resource"), "选择秘境节点 资源"
                )
            ).ok
            assert (
                await runtime.dispatch(
                    _context(adapter, user, "cloud-encounter"), "选择秘境节点 遭遇"
                )
            ).code == "SECRET_REALM_COMBAT_PENDING"
            assert (
                await runtime.dispatch(
                    _context(adapter, user, "cloud-combat"), "结算秘境"
                )
            ).data["current_node"] == "choice"
            assert (
                await runtime.dispatch(
                    _context(adapter, user, "cloud-choice"), "选择秘境节点 选择"
                )
            ).data["status"] == "cleared"
            settled = await runtime.dispatch(
                _context(adapter, user, "cloud-final"), "结算秘境"
            )
            assert settled.data["reward"] == {
                "codex.instance.cloud_boat": 1,
                "local.xuantian.new_town": 12,
            }
            with sqlite3.connect(runtime.settings.database_path) as connection:
                inventory, local_json, stamina = connection.execute(
                    "SELECT p.inventory_json, r.local_json, p.stamina FROM players p "
                    "JOIN player_reputations r ON r.player_id=p.id "
                    "WHERE p.platform=? AND p.platform_user_id=?",
                    (adapter, user),
                ).fetchone()
                assert json.loads(inventory).get("item.ticket.cloud_boat_fragment", 0) == 0
                assert json.loads(local_json)["local.xuantian.new_town"] == 12
                assert stamina == 88
                connection.execute(
                    "UPDATE players SET inventory_json=? WHERE platform=? AND platform_user_id=?",
                    (json.dumps({"item.ticket.cloud_boat_fragment": 1}), adapter, user),
                )
            assert (
                await runtime.dispatch(
                    _context(adapter, user, "cloud-repeat-enter"), "进入秘境 云舟秘境"
                )
            ).ok
            assert (
                await runtime.dispatch(
                    _context(adapter, user, "cloud-repeat-resource"), "选择秘境节点 资源"
                )
            ).ok
            assert (
                await runtime.dispatch(
                    _context(adapter, user, "cloud-repeat-encounter"), "选择秘境节点 遭遇"
                )
            ).ok
            assert (
                await runtime.dispatch(
                    _context(adapter, user, "cloud-repeat-combat"), "结算秘境"
                )
            ).data["current_node"] == "choice"
            assert (
                await runtime.dispatch(
                    _context(adapter, user, "cloud-repeat-choice"), "选择秘境节点 选择"
                )
            ).data["status"] == "cleared"
            repeat = await runtime.dispatch(
                _context(adapter, user, "cloud-repeat-final"), "结算秘境"
            )
            assert repeat.data["reward"] in (
                {},
                {"item.ticket.cloud_boat_fragment": 1},
            )
            assert "失败" not in repeat.message
            limited = await runtime.dispatch(
                _context(adapter, user, "cloud-limited"), "进入秘境 云舟秘境"
            )
            assert limited.code == "SECRET_REALM_QUOTA_EXHAUSTED"
            await runtime.close()

    asyncio.run(run())
