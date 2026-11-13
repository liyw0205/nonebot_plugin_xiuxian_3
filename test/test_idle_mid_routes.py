from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.specials.idle_rules import (
    idle_route_definitions,
    reward_for,
)

ROUTES = {
    "idle.cloud_mine_watch": ("foundation", 4, None, {}, 21600, 1),
    "idle.cloud_city_shop": (None, 0, None, {"local.xuantian.cloud_city": 200}, 28800, 1),
    "idle.demon_trade_post": (None, 0, "permit.demon_trade", {}, 28800, 1),
    "idle.beast_habitat_watch": (None, 0, "permit.beast_trade", {}, 28800, 1),
}

ROUTE_LOCATIONS = {"idle.cloud_city_shop": "xuantian.cloud_city"}


class Clock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


def _context(adapter: str, user: str, request: str, operation: str = "") -> CommandContext:
    return CommandContext(
        adapter=adapter,
        user_id=user,
        request_id=request,
        operation_id=operation,
        can_write_assets=True,
    )


def test_mid_routes_load_with_expected_gates_and_pools() -> None:
    definitions = idle_route_definitions()
    assert set(ROUTES) <= set(definitions)
    for key, (realm, layer, permit, reputation, duration, daily) in ROUTES.items():
        definition = definitions[key]
        assert definition.required_realm == realm
        assert definition.required_layer == layer
        assert definition.required_permit == permit
        assert dict(definition.required_local_reputation) == reputation
        assert definition.required_location == ROUTE_LOCATIONS.get(key)
        assert definition.duration_seconds == duration
        assert definition.daily_limit == daily
        full = reward_for(definition, "mid:seed", fallback=False)
        fallback = reward_for(definition, "mid:seed", fallback=True)
        assert full and fallback
        assert set(fallback) == set(reward_for(definition, "mid:other", fallback=True))
        assert len(reward_for(definition, "mid:seed", fallback=True)) == len(fallback)


def test_mid_route_preview_enforces_realm_reputation_and_permits() -> None:
    async def run() -> None:
        clock = Clock(datetime(2026, 9, 27, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            adapter, user = "onebot.v11", "idle-mid-gates"
            created = await runtime.dispatch(
                _context(adapter, user, "create"), "开始修仙"
            )
            assert created.ok, created.message
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE players SET stage='cultivator', realm_key='foundation', "
                    "realm_layer=3, energy=100, energy_max=100, stamina=100, stamina_max=100 "
                    "WHERE platform=? AND platform_user_id=?",
                    (adapter, user),
                )
                player_id = connection.execute(
                    "SELECT id FROM players WHERE platform=? AND platform_user_id=?",
                    (adapter, user),
                ).fetchone()[0]

            def preview(route: str, request: str):
                return runtime.dispatch(
                    _context(adapter, user, request), f"挂机预览 {route}"
                )

            def row(result, key: str):
                return next(item for item in result.data["routes"] if item["route_key"] == key)

            blocked = await preview("矿区看守", "mine-blocked")
            assert blocked.code == "IDLE_PREVIEW", blocked.message
            mine = row(blocked, "idle.cloud_mine_watch")
            assert mine["ready"] is False
            assert any("境界不足" in value for value in mine["missing"])
            assert mine["requirements"]["required_realm"] == "foundation"
            assert mine["requirements"]["required_layer"] == 4

            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE players SET realm_layer=4 WHERE id=?", (player_id,)
                )
            allowed = await preview("矿区看守", "mine-allowed")
            assert row(allowed, "idle.cloud_mine_watch")["ready"] is True

            shop = row(await preview("云城店铺", "shop-blocked"), "idle.cloud_city_shop")
            assert shop["ready"] is False
            assert "地方名望不足（需要 200）" in shop["missing"]
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "INSERT INTO player_reputations(player_id, local_json, service_reputation, updated_at) "
                    "VALUES (?, ?, 0, ?) ON CONFLICT(player_id) DO UPDATE SET local_json=excluded.local_json",
                    (
                        player_id,
                        json.dumps({"local.xuantian.cloud_city": 200}, sort_keys=True),
                        clock.value.isoformat(),
                    ),
                )
            shop = row(await preview("云城店铺", "shop-location-blocked"), "idle.cloud_city_shop")
            assert shop["ready"] is False
            assert any("所在地点不符" in value for value in shop["missing"])
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE players SET location_key='xuantian.cloud_city' WHERE id=?",
                    (player_id,),
                )
            assert row(await preview("云城店铺", "shop-allowed"), "idle.cloud_city_shop")["ready"] is True

            post = row(
                await preview("魔界驿所", "demon-blocked"), "idle.demon_trade_post"
            )
            assert post["ready"] is False
            assert "需要有效的贸易许可" in post["missing"]
            habitat = row(
                await preview("妖界栖地", "beast-blocked"), "idle.beast_habitat_watch"
            )
            assert habitat["ready"] is False
            assert "需要有效的贸易许可" in habitat["missing"]

            with sqlite3.connect(runtime.settings.database_path) as connection:
                for index, permit_key in enumerate(
                    ("permit.demon_trade", "permit.beast_trade"), start=1
                ):
                    connection.execute(
                        "INSERT INTO trade_permits(permit_id, player_id, operation_id, permit_key, "
                        "issued_at, expires_at, cost, snapshot_json, created_at, updated_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, 0, '{}', ?, ?)",
                        (
                            f"permit-row-{index}",
                            player_id,
                            f"permit-op-{index}",
                            permit_key,
                            clock.value.isoformat(),
                            (clock.value + timedelta(days=7)).isoformat(),
                            clock.value.isoformat(),
                            clock.value.isoformat(),
                        ),
                    )
            assert row(await preview("魔界驿所", "demon-allowed"), "idle.demon_trade_post")["ready"] is True
            assert row(await preview("妖界栖地", "beast-allowed"), "idle.beast_habitat_watch")["ready"] is True

            base = row(await preview("镇中行旅", "base-route"), "idle.town_errand")
            assert "境界不足" not in base["missing"]
            assert "需要有效的贸易许可" not in base["missing"]
            await runtime.close()

    asyncio.run(run())
