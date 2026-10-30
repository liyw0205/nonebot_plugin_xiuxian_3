"""Behavioural contract for the ironwood trial, a common secret realm.

The realm is pure content: entrance gating, node order, combat, quota and the
first/repeat reward split all come from the shared secret-realm engine.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory

from combat_fixtures import equip_damage_weapon

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime

REALM_KEY = "instance.secret_realm.ironwood_trial"
LOCATION = "xuantian.ironwood_grove"
ADAPTERS = ("qq.official", "onebot.v11")


def _context(adapter: str, user: str, operation_id: str) -> CommandContext:
    return CommandContext(adapter=adapter, user_id=user, operation_id=operation_id)


async def _create_and_seek(runtime, adapter: str, user: str) -> None:
    assert (await runtime.dispatch(_context(adapter, user, f"{adapter}-create"), "开始修仙")).ok
    assert (await runtime.dispatch(_context(adapter, user, f"{adapter}-seek"), "寻仙问道")).ok


def _prepare(
    runtime,
    adapter: str,
    user: str,
    *,
    realm: str = "qi_sensing",
    layer: int = 2,
    location: str = LOCATION,
    stamina: int = 200,
    damage: int = 50,
) -> None:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE players SET stage='cultivator', realm_key=?, realm_layer=?, location_key=?, "
            "stamina=?, stamina_max=?, max_hp=?, inventory_json='{}' "
            "WHERE platform=? AND platform_user_id=?",
            (realm, layer, location, stamina, max(stamina, 200), damage * 8 or 8, adapter, user),
        )
    if damage:
        equip_damage_weapon(runtime, adapter, user, damage)


def _inventory(runtime, adapter: str, user: str) -> dict[str, int]:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        raw = connection.execute(
            "SELECT inventory_json FROM players WHERE platform=? AND platform_user_id=?",
            (adapter, user),
        ).fetchone()[0]
    return json.loads(raw or "{}")


def _stamina(runtime, adapter: str, user: str) -> int:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        return connection.execute(
            "SELECT stamina FROM players WHERE platform=? AND platform_user_id=?",
            (adapter, user),
        ).fetchone()[0]


async def _clear_once(runtime, adapter: str, user: str, tag: str) -> dict:
    entered = await runtime.dispatch(_context(adapter, user, f"{tag}-enter"), "进入秘境 铁木林秘境")
    assert entered.code == "SECRET_REALM_ENTERED", entered
    resource = await runtime.dispatch(_context(adapter, user, f"{tag}-resource"), "选择秘境节点 资源")
    assert resource.data["current_node"] == "encounter", resource
    encounter = await runtime.dispatch(_context(adapter, user, f"{tag}-encounter"), "选择秘境节点 遭遇")
    assert encounter.code == "SECRET_REALM_COMBAT_PENDING", encounter
    replay = await runtime.dispatch(_context(adapter, user, f"{tag}-encounter"), "选择秘境节点 遭遇")
    assert replay.data["battle_id"] == encounter.data["battle_id"], replay
    progressed = await runtime.dispatch(_context(adapter, user, f"{tag}-combat-settle"), "结算秘境")
    assert progressed.data["current_node"] == "choice", progressed
    choice = await runtime.dispatch(_context(adapter, user, f"{tag}-choice"), "选择秘境节点 选择")
    assert choice.data["status"] == "cleared", choice
    settled = await runtime.dispatch(_context(adapter, user, f"{tag}-settle"), "结算秘境")
    assert settled.code == "SECRET_REALM_SETTLED", settled
    return settled


def test_ironwood_trial_appears_in_preview_for_both_adapters() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, adapters=ADAPTERS)
            try:
                for adapter, user in (
                    ("qq.official", "qq-ironwood-preview"),
                    ("onebot.v11", "ob-ironwood-preview"),
                ):
                    await _create_and_seek(runtime, adapter, user)
                    preview = await runtime.adapters.dispatch(
                        adapter, _context(adapter, user, f"{adapter}-preview"), "秘境预览"
                    )
                    assert preview.code == "SECRET_REALM_PREVIEW", preview
                    realm = next(
                        item for item in preview.data["realms"] if item["instance_key"] == REALM_KEY
                    )
                    assert realm["label"] == "铁木试炼"
                    assert tuple(realm["nodes"]) == ("resource", "encounter", "choice")
                    assert realm["stamina_cost"] == 12
                    assert realm["ticket_key"] is None
                    assert realm["quota_period"] == "week"
                    assert realm["quota_limit"] == 2
                    assert realm["first_reward"]["item.mat.wood"] == 3
            finally:
                await runtime.close()

    asyncio.run(run())


def test_ironwood_trial_rejects_entrance_without_spending_stamina() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, adapters=("onebot.v11",))
            adapter, user = "onebot.v11", "ob-ironwood-gate"
            try:
                await _create_and_seek(runtime, adapter, user)

                # Wrong location.
                _prepare(runtime, adapter, user, location="xuantian.new_town")
                wrong_place = await runtime.dispatch(
                    _context(adapter, user, "gate-place"), "进入秘境 铁木林秘境"
                )
                assert wrong_place.code == "SECRET_REALM_REQUIREMENT_MISSING", wrong_place
                assert _stamina(runtime, adapter, user) == 200

                # Realm below the gate (mortal sits under qi_sensing).
                _prepare(runtime, adapter, user, realm="mortal", layer=10)
                low_realm = await runtime.dispatch(
                    _context(adapter, user, "gate-realm"), "进入秘境 铁木林秘境"
                )
                assert low_realm.code == "SECRET_REALM_REQUIREMENT_MISSING", low_realm
                assert _stamina(runtime, adapter, user) == 200

                # Stamina below the cost.
                _prepare(runtime, adapter, user, stamina=5)
                low_stamina = await runtime.dispatch(
                    _context(adapter, user, "gate-stamina"), "进入秘境 铁木林秘境"
                )
                assert low_stamina.code == "RESOURCE_INSUFFICIENT", low_stamina
                assert _stamina(runtime, adapter, user) == 5

                # Node selection before entering.
                jumped = await runtime.dispatch(
                    _context(adapter, user, "gate-jump"), "选择秘境节点 资源"
                )
                assert jumped.code == "SECRET_REALM_NOT_FOUND", jumped
            finally:
                await runtime.close()

    asyncio.run(run())


def test_ironwood_trial_first_clear_repeat_pool_and_weekly_quota() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, adapters=("onebot.v11",))
            adapter, user = "onebot.v11", "ob-ironwood-clear"
            try:
                await _create_and_seek(runtime, adapter, user)
                _prepare(runtime, adapter, user)

                first = await _clear_once(runtime, adapter, user, "clear1")
                assert first.data["reward"] == {
                    "item.mat.wood": 3,
                    "item.ore.ironstone": 2,
                    "local.xuantian.new_town": 8,
                }, first.data["reward"]
                replay = await runtime.dispatch(
                    _context(adapter, user, "clear1-settle"), "结算秘境"
                )
                assert replay.data["idempotent_replay"] is True, replay
                inventory = _inventory(runtime, adapter, user)
                assert inventory["item.mat.wood"] == 3, inventory

                second = await _clear_once(runtime, adapter, user, "clear2")
                # The second clear draws the repeat pool instead of the first reward.
                assert second.data["reward"] != first.data["reward"], second.data["reward"]
                assert set(second.data["reward"]) <= {
                    "item.mat.wood",
                    "item.ore.ironstone",
                }, second.data["reward"]

                third = await runtime.dispatch(
                    _context(adapter, user, "clear3-enter"), "进入秘境 铁木林秘境"
                )
                assert third.code == "SECRET_REALM_QUOTA_EXHAUSTED", third
            finally:
                await runtime.close()

    asyncio.run(run())


def test_ironwood_trial_battle_failure_yields_no_first_reward() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, adapters=("onebot.v11",))
            adapter, user = "onebot.v11", "ob-ironwood-fail"
            try:
                await _create_and_seek(runtime, adapter, user)
                _prepare(runtime, adapter, user, damage=0)
                entered = await runtime.dispatch(
                    _context(adapter, user, "fail-enter"), "进入秘境 铁木林秘境"
                )
                assert entered.code == "SECRET_REALM_ENTERED", entered
                await runtime.dispatch(_context(adapter, user, "fail-resource"), "选择秘境节点 资源")
                pending = await runtime.dispatch(
                    _context(adapter, user, "fail-encounter"), "选择秘境节点 遭遇"
                )
                assert pending.code == "SECRET_REALM_COMBAT_PENDING", pending
                settled = await runtime.dispatch(_context(adapter, user, "fail-settle"), "结算秘境")
                assert settled.code == "SECRET_REALM_SETTLED", settled
                assert settled.data["reward"] == {}, settled.data["reward"]
                assert "item.mat.wood" not in _inventory(runtime, adapter, user)
            finally:
                await runtime.close()

    asyncio.run(run())


def test_ironwood_trial_expiry_refunds_stamina() -> None:
    async def run() -> None:
        now = datetime(2026, 9, 29, tzinfo=timezone.utc)
        current = [now]
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(
                data_dir=data_dir, adapters=("onebot.v11",), clock=lambda: current[0]
            )
            adapter, user = "onebot.v11", "ob-ironwood-expire"
            try:
                await _create_and_seek(runtime, adapter, user)
                _prepare(runtime, adapter, user)
                before = _stamina(runtime, adapter, user)
                entered = await runtime.dispatch(
                    _context(adapter, user, "exp-enter"), "进入秘境 铁木林秘境"
                )
                assert entered.code == "SECRET_REALM_ENTERED", entered
                assert _stamina(runtime, adapter, user) == before - 12
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE secret_realm_runs SET expires_at=? WHERE run_id=?",
                        ((now - timedelta(seconds=1)).isoformat(), entered.data["run_id"]),
                    )
                expired = await runtime.dispatch(_context(adapter, user, "exp-settle"), "结算秘境")
                assert expired.data["outcome"] == "expired", expired
                assert expired.data["stamina_refunded"] == 12, expired
            finally:
                await runtime.close()

    asyncio.run(run())
