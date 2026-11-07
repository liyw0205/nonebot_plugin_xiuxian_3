"""Behavioural contract for the two trade-endpoint common secret realms.

Both realms are pure content driven by the shared secret-realm engine: gating,
node order, combat, quota and the first/repeat reward split all come from the
generic loader. This file pins the content contract, proves discoverability on
the two trade locations, and exercises the full play loop (enter, route,
encounter, battle, settle, replay, repeat pool, quota, failure, expiry) plus the
four entrance rejections.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from combat_fixtures import equip_damage_weapon
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.adventures.secret_realm_rules import (
    resolve_secret_realm,
    secret_realm_definitions,
)
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

MARKET = "instance.secret_realm.abyss_market_run"
MARKET_LABEL = "魔渊契约集市"
MARKET_ALIAS = "魔渊集市秘境"
MARKET_LOCATION = "demon.abyss_market"
MARKET_ENEMY = "enemy.abyss_market_warden"
MARKET_REP = "local.demon.abyss_market"
PORT = "instance.secret_realm.trade_port_convoy"
PORT_LABEL = "三界货栈"
PORT_ALIAS = "贸易口秘境"
PORT_LOCATION = "beast.three_realms_trade_port"
PORT_ENEMY = "enemy.trade_port_smuggler"
PORT_REP = "local.beast.three_realms_trade_port"
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
    realm: str = "nascent_soul",
    layer: int = 1,
    location: str = MARKET_LOCATION,
    stamina: int = 200,
    damage: int = 300,
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


async def _clear_once(runtime, adapter: str, user: str, tag: str, alias: str) -> dict:
    entered = await runtime.dispatch(_context(adapter, user, f"{tag}-enter"), f"进入秘境 {alias}")
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


def test_trade_endpoint_realms_follow_the_common_realm_contract() -> None:
    bundle = ContentBundle.load(DATA)
    definitions = secret_realm_definitions(bundle)
    assert len(definitions) == 9

    expected = {
        MARKET: (MARKET_LABEL, MARKET_LOCATION, MARKET_ENEMY, MARKET_REP, "item.demon_core"),
        PORT: (PORT_LABEL, PORT_LOCATION, PORT_ENEMY, PORT_REP, "item.beast_blood"),
    }
    for key, (label, location, enemy, reputation, item) in expected.items():
        definition = definitions[key]
        assert definition.label == label, key
        assert definition.description.strip(), key
        assert definition.required_realm == "nascent_soul" and definition.required_layer == 1, key
        assert definition.location_key == location, key
        assert definition.stamina_cost == 20, key
        assert definition.ticket_key is None and definition.ticket_quantity == 0, key
        assert definition.node_keys == ("resource", "encounter", "choice"), key
        assert definition.enemy_key == enemy, key
        assert definition.first_reward == {item: 2, reputation: 8}, key
        assert definition.quota_period == "week" and definition.quota_limit == 2, key
        assert definition.expiry_seconds == 3600, key
        assert definition.reputation_key == reputation, key
        # Every repeat outcome is either the same item or an explicit no-reward.
        for _weight, rewards in definition.repeat_reward_pool:
            assert set(rewards) <= {item}, (key, rewards)

    assert resolve_secret_realm(MARKET_ALIAS, bundle) == MARKET
    assert resolve_secret_realm(PORT_ALIAS, bundle) == PORT
    assert resolve_secret_realm(MARKET_LABEL, bundle) == MARKET
    assert resolve_secret_realm(PORT_LABEL, bundle) == PORT


def test_trade_endpoint_realms_are_discoverable_from_their_locations() -> None:
    """A realm no location lists is invisible; both must be advertised."""

    bundle = ContentBundle.load(DATA)
    market = bundle.require("location", MARKET_LOCATION)
    assert MARKET in (market.get("actions") or [])
    assert market["codex_entry_key"] == "codex.place.demon_market"
    port = bundle.require("location", PORT_LOCATION)
    assert PORT in (port.get("actions") or [])
    assert port["codex_entry_key"] == "codex.place.trade_port"
    # The enemies must resolve as active combat content at the same places.
    for enemy_key, location in ((MARKET_ENEMY, MARKET_LOCATION), (PORT_ENEMY, PORT_LOCATION)):
        record = bundle.require("enemy", enemy_key, include_locked=False)
        assert record["location_key"] == location, enemy_key
        assert isinstance(record.get("combat_profile"), dict), enemy_key
        assert isinstance(record["stats"].get("agility"), int), enemy_key


def test_trade_endpoint_realms_appear_in_preview_for_both_adapters() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, adapters=ADAPTERS)
            try:
                for adapter, user in (
                    ("qq.official", "qq-market-preview"),
                    ("onebot.v11", "ob-market-preview"),
                ):
                    await _create_and_seek(runtime, adapter, user)
                    preview = await runtime.adapters.dispatch(
                        adapter, _context(adapter, user, f"{adapter}-preview"), "秘境预览"
                    )
                    assert preview.code == "SECRET_REALM_PREVIEW", preview
                    keys = {item["instance_key"] for item in preview.data["realms"]}
                    assert {MARKET, PORT} <= keys, keys
                    market = next(
                        item for item in preview.data["realms"] if item["instance_key"] == MARKET
                    )
                    assert market["label"] == MARKET_LABEL
                    assert tuple(market["nodes"]) == ("resource", "encounter", "choice")
                    assert market["stamina_cost"] == 20
                    assert market["ticket_key"] is None
                    assert market["quota_period"] == "week"
                    assert market["quota_limit"] == 2
                    assert market["first_reward"]["item.demon_core"] == 2
            finally:
                await runtime.close()

    asyncio.run(run())


def test_trade_endpoint_realms_reject_entrance_without_spending_stamina() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, adapters=("onebot.v11",))
            adapter, user = "onebot.v11", "ob-trade-gate"
            try:
                await _create_and_seek(runtime, adapter, user)

                # Wrong location.
                _prepare(runtime, adapter, user, location="xuantian.new_town")
                wrong_place = await runtime.dispatch(
                    _context(adapter, user, "gate-place"), f"进入秘境 {PORT_ALIAS}"
                )
                assert wrong_place.code == "SECRET_REALM_REQUIREMENT_MISSING", wrong_place
                assert _stamina(runtime, adapter, user) == 200

                # Realm below the gate (mortal sits under nascent_soul).
                _prepare(runtime, adapter, user, realm="mortal", layer=10)
                low_realm = await runtime.dispatch(
                    _context(adapter, user, "gate-realm"), f"进入秘境 {PORT_ALIAS}"
                )
                assert low_realm.code == "SECRET_REALM_REQUIREMENT_MISSING", low_realm
                assert _stamina(runtime, adapter, user) == 200

                # Stamina below the cost.
                _prepare(runtime, adapter, user, location=PORT_LOCATION, stamina=5)
                low_stamina = await runtime.dispatch(
                    _context(adapter, user, "gate-stamina"), f"进入秘境 {PORT_ALIAS}"
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


def test_abyss_market_realm_first_clear_repeat_pool_and_weekly_quota() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, adapters=("onebot.v11",))
            adapter, user = "onebot.v11", "ob-market-clear"
            try:
                await _create_and_seek(runtime, adapter, user)
                _prepare(runtime, adapter, user)

                first = await _clear_once(runtime, adapter, user, "clear1", MARKET_ALIAS)
                assert first.data["reward"] == {
                    "item.demon_core": 2,
                    MARKET_REP: 8,
                }, first.data["reward"]
                replay = await runtime.dispatch(
                    _context(adapter, user, "clear1-settle"), "结算秘境"
                )
                assert replay.data["idempotent_replay"] is True, replay
                assert _inventory(runtime, adapter, user)["item.demon_core"] == 2

                second = await _clear_once(runtime, adapter, user, "clear2", MARKET_ALIAS)
                # The second clear draws the repeat pool instead of the first reward.
                assert second.data["reward"] != first.data["reward"], second.data["reward"]
                assert set(second.data["reward"]) <= {"item.demon_core", MARKET_REP}, second.data[
                    "reward"
                ]

                third = await runtime.dispatch(
                    _context(adapter, user, "clear3-enter"), f"进入秘境 {MARKET_ALIAS}"
                )
                assert third.code == "SECRET_REALM_QUOTA_EXHAUSTED", third
            finally:
                await runtime.close()

    asyncio.run(run())


def test_trade_port_convoy_full_clear_settles_a_real_battle() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, adapters=("qq.official",))
            adapter, user = "qq.official", "qq-port-clear"
            try:
                await _create_and_seek(runtime, adapter, user)
                _prepare(runtime, adapter, user, location=PORT_LOCATION)
                settled = await _clear_once(runtime, adapter, user, "port1", PORT_ALIAS)
                assert settled.data["reward"] == {
                    "item.beast_blood": 2,
                    PORT_REP: 8,
                }, settled.data["reward"]
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    battles = [
                        (row[0], row[1])
                        for row in connection.execute(
                            "SELECT enemy_key, status FROM battle_sessions WHERE player_id="
                            "(SELECT id FROM players WHERE platform=? AND platform_user_id=?)",
                            (adapter, user),
                        ).fetchall()
                    ]
                assert len(battles) == 1 and battles[0][1] == "settled", battles
                assert battles[0][0] == PORT_ENEMY
            finally:
                await runtime.close()

    asyncio.run(run())


def test_trade_endpoint_realm_battle_failure_yields_no_first_reward() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, adapters=("onebot.v11",))
            adapter, user = "onebot.v11", "ob-market-fail"
            try:
                await _create_and_seek(runtime, adapter, user)
                _prepare(runtime, adapter, user, damage=0)
                await runtime.dispatch(_context(adapter, user, "fail-enter"), f"进入秘境 {MARKET_ALIAS}")
                await runtime.dispatch(_context(adapter, user, "fail-resource"), "选择秘境节点 资源")
                pending = await runtime.dispatch(
                    _context(adapter, user, "fail-encounter"), "选择秘境节点 遭遇"
                )
                assert pending.code == "SECRET_REALM_COMBAT_PENDING", pending
                settled = await runtime.dispatch(_context(adapter, user, "fail-settle"), "结算秘境")
                assert settled.code == "SECRET_REALM_SETTLED", settled
                assert settled.data["reward"] == {}, settled.data["reward"]
                assert "item.demon_core" not in _inventory(runtime, adapter, user)
            finally:
                await runtime.close()

    asyncio.run(run())


def test_trade_endpoint_realm_expiry_refunds_stamina() -> None:
    async def run() -> None:
        now = datetime(2026, 11, 2, tzinfo=timezone.utc)
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(
                data_dir=data_dir, adapters=("onebot.v11",), clock=lambda: now
            )
            adapter, user = "onebot.v11", "ob-port-expire"
            try:
                await _create_and_seek(runtime, adapter, user)
                _prepare(runtime, adapter, user, location=PORT_LOCATION)
                before = _stamina(runtime, adapter, user)
                entered = await runtime.dispatch(
                    _context(adapter, user, "exp-enter"), f"进入秘境 {PORT_ALIAS}"
                )
                assert entered.code == "SECRET_REALM_ENTERED", entered
                assert _stamina(runtime, adapter, user) == before - 20
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE secret_realm_runs SET expires_at=? WHERE run_id=?",
                        ((now - timedelta(seconds=1)).isoformat(), entered.data["run_id"]),
                    )
                expired = await runtime.dispatch(_context(adapter, user, "exp-settle"), "结算秘境")
                assert expired.data["outcome"] == "expired", expired
                assert expired.data["stamina_refunded"] == 20, expired
            finally:
                await runtime.close()

    asyncio.run(run())
