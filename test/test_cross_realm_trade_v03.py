from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime


class MutableClock:
    def __init__(self, value: datetime):
        self.value = value

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **kwargs: int) -> None:
        self.value += timedelta(**kwargs)


def _context(adapter: str, user: str, request: str, operation: str = "") -> CommandContext:
    return CommandContext(
        adapter=adapter,
        user_id=user,
        request_id=request,
        operation_id=operation,
        can_write_assets=True,
    )


async def _prepare_player(runtime, adapter: str, user: str) -> None:
    await runtime.adapters.dispatch(adapter, _context(adapter, user, f"create-{adapter}"), "开始修仙")
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            """
            UPDATE players
            SET stage='cultivator', realm_key='nascent_soul', realm_layer=1,
                location_key='demon.abyss_market', spirit_stones=1200,
                faction_reputation_json=?, inventory_json=?
            WHERE platform=? AND platform_user_id=?
            """,
            (
                json.dumps({"demon": 200}),
                json.dumps({"item.material.cloud_iron": 70}),
                adapter,
                user,
            ),
        )


def test_fixed_demon_trade_caps_binding_and_replays_on_qq_and_onebot() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 21, 12, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=Path(data_dir), clock=clock)
            for adapter in ("qq.official", "onebot.v11"):
                clock.value = datetime(2026, 9, 21, 12, tzinfo=timezone.utc)
                user = f"trade-{adapter}"
                await _prepare_player(runtime, adapter, user)

                first = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "trade-first", f"{adapter}-trade-first"),
                    "跨界贸易 云铁换魔核",
                )
                assert first.code == "CROSS_REALM_TRADE_COMPLETED"
                assert first.data["output_items"] == {"item.demon_core": 1}
                assert first.data["content_version"] == "content-0.3"
                assert first.data["rule_version"] == "economy-0.3.0"
                replay = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "trade-first-replay", f"{adapter}-trade-first"),
                    "固定贸易 trade.xuantian_to_demon",
                )
                assert replay.code == "CROSS_REALM_TRADE_COMPLETED"
                assert replay.data["idempotent_replay"] is True

                bound_listing = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "bound-listing", f"{adapter}-bound-listing"),
                    "发布摆摊 item.demon_core 1 1",
                )
                assert bound_listing.code == "ITEM_BINDING_ACTIVE"

                for index in range(2, 6):
                    completed = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, user, f"trade-{index}", f"{adapter}-trade-{index}"),
                        "三界贸易 玄天到魔界",
                    )
                    assert completed.code == "CROSS_REALM_TRADE_COMPLETED"
                capped = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "trade-capped", f"{adapter}-trade-capped"),
                    "跨界贸易 云铁兑换魔核",
                )
                assert capped.code == "TRADE_WEEKLY_CAP"

                with sqlite3.connect(runtime.settings.database_path) as connection:
                    state = connection.execute(
                        "SELECT spirit_stones, inventory_json FROM players WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    ).fetchone()
                    assert state[0] == 200
                    assert json.loads(state[1]) == {"item.material.cloud_iron": 20, "item.demon_core": 5}
                    trade_count = connection.execute(
                        "SELECT COUNT(*) FROM cross_realm_trades WHERE player_id=(SELECT id FROM players WHERE platform=? AND platform_user_id=?)",
                        (adapter, user),
                    ).fetchone()[0]
                    assert trade_count == 5
                    binding = connection.execute(
                        "SELECT item_key, quantity, bound_until, source_trade_id FROM item_bindings WHERE player_id=(SELECT id FROM players WHERE platform=? AND platform_user_id=?)",
                        (adapter, user),
                    ).fetchone()
                assert binding[0:2] == ("item.demon_core", 1)
                assert binding[2] == first.data["binding_expires_at"]
                assert binding[3] == first.data["trade_id"]

                clock.advance(days=7)
                next_week = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "trade-next-week", f"{adapter}-trade-next-week"),
                    "跨界贸易 云铁换魔核",
                )
                assert next_week.code == "CROSS_REALM_TRADE_COMPLETED"
                assert next_week.data["week_start"] == "2026-09-28"
            await runtime.close()

    asyncio.run(run())


def test_fixed_demon_trade_permission_and_input_fail_without_mutation() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=Path(data_dir))
            adapter, user = "qq.official", "trade-permission"
            await runtime.adapters.dispatch(adapter, _context(adapter, user, "create"), "开始修仙")
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE players SET stage='cultivator', realm_key='nascent_soul', realm_layer=1, location_key='demon.fallen_ruins', spirit_stones=500, faction_reputation_json=?, inventory_json=? WHERE platform=? AND platform_user_id=?",
                    (json.dumps({"demon": 199}), json.dumps({"item.material.cloud_iron": 9}), adapter, user),
                )
            denied = await runtime.adapters.dispatch(
                adapter,
                _context(adapter, user, "denied", "trade-denied"),
                "跨界贸易 云铁换魔核",
            )
            assert denied.code == "CROSS_REALM_TRADE_PERMISSION_DENIED"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                state = connection.execute(
                    "SELECT spirit_stones, inventory_json FROM players WHERE platform=? AND platform_user_id=?",
                    (adapter, user),
                ).fetchone()
                connection.execute(
                    "UPDATE players SET location_key='demon.abyss_market', faction_reputation_json=? WHERE platform=? AND platform_user_id=?",
                    (json.dumps({"demon": 200}), adapter, user),
                )
            assert state == (500, json.dumps({"item.material.cloud_iron": 9}))
            insufficient = await runtime.adapters.dispatch(
                adapter,
                _context(adapter, user, "insufficient", "trade-insufficient"),
                "跨界贸易 云铁换魔核",
            )
            assert insufficient.code == "TRADE_INPUT_INSUFFICIENT"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute(
                    "SELECT spirit_stones, inventory_json FROM players WHERE platform=? AND platform_user_id=?",
                    (adapter, user),
                ).fetchone() == state
            await runtime.close()

    asyncio.run(run())
