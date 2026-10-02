from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.production.rules import random_quality_bp


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


def _set_player(runtime, adapter: str, user: str, *, location: str, blood: int = 3) -> None:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            """
            UPDATE players SET stage='cultivator', realm_key='nascent_soul', realm_layer=1,
                path_key='beast', location_key=?, energy=30, energy_max=30,
                spirit_stones=1000, inventory_json=?, intro_json='{}'
            WHERE platform=? AND platform_user_id=?
            """,
            (
                location,
                json.dumps({"item.beast_blood": blood}),
                adapter,
                user,
            ),
        )


def _finish(runtime, order_id: str, clock: MutableClock) -> None:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE production_orders SET ends_at=? WHERE order_id=?",
            ((clock() - timedelta(seconds=1)).isoformat(), order_id),
        )


def test_beast_pact_production_binds_slot_and_expires_on_qq_and_onebot() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 25, 12, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=Path(data_dir), clock=clock)
            for adapter in ("qq.official", "onebot.v11"):
                user = f"beast-pact-{adapter}"
                created = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, f"create-{adapter}"),
                    "开始修仙",
                )
                assert created.ok
                _set_player(runtime, adapter, user, location="beast.ten_thousand_hills", blood=3)

                preview = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, f"preview-{adapter}"),
                    "生产预览 妖兽契约",
                )
                assert preview.code == "RECIPE_PREVIEW"
                assert preview.data["recipe_key"] == "recipe.contract.beast_pact"
                assert (preview.data["energy_cost"], preview.data["currency_cost"]) == (10, 500)

                start_operation = f"{adapter}-beast-pact-start"
                started = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, f"start-{adapter}", start_operation),
                    "开始生产 兽契",
                )
                assert started.code == "PRODUCTION_STARTED"
                replay = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, f"start-replay-{adapter}", start_operation),
                    "开始生产 妖兽契约",
                )
                assert replay.data["idempotent_replay"] is True
                _finish(runtime, started.data["order_id"], clock)

                settled = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, f"settle-{adapter}", f"{adapter}-beast-pact-settle"),
                    "领取生产",
                )
                assert settled.code == "PRODUCTION_COMPLETED"
                assert settled.data["outputs"] == {"item.contract.beast_pact": 1}
                assert settled.data["binding_expires_at"] == (
                    clock() + timedelta(days=1)
                ).isoformat()
                replay_settlement = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, f"settle-replay-{adapter}", f"{adapter}-beast-pact-settle"),
                    "领取生产",
                )
                assert replay_settlement.data["idempotent_replay"] is True

                occupied = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, f"occupied-{adapter}", f"{adapter}-occupied"),
                    "开始生产 妖兽契约",
                )
                assert occupied.code == "CONTRACT_SLOT_OCCUPIED"
                market = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, f"market-{adapter}", f"{adapter}-market"),
                    "发布摆摊 item.contract.beast_pact 1 1",
                )
                assert market.code == "MARKET_ITEM_FORBIDDEN"

                clock.advance(days=1, seconds=1)
                _set_player(runtime, adapter, user, location="beast.ten_thousand_hills", blood=3)
                restarted = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, f"restart-{adapter}", f"{adapter}-restart"),
                    "开始生产 妖兽契约",
                )
                assert restarted.code == "PRODUCTION_STARTED"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    binding = connection.execute(
                        "SELECT status FROM production_item_bindings WHERE player_id=(SELECT id FROM players WHERE platform=? AND platform_user_id=?)",
                        (adapter, user),
                    ).fetchone()
                assert binding == ("expired",)

            await runtime.close()

    asyncio.run(run())


def test_beast_pact_failure_refunds_sixty_percent_floor() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 25, 12, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            adapter, user = "qq.official", "beast-pact-failure"
            await runtime.adapters.dispatch(adapter, _context(adapter, user, "create"), "开始修仙")
            _set_player(runtime, adapter, user, location="demon.abyss_market", blood=3)
            operation = next(
                f"beast-pact-failure-{index}"
                for index in range(256)
                if random_quality_bp(f"beast-pact-failure-{index}") == 0
            )
            started = await runtime.adapters.dispatch(
                adapter,
                _context(adapter, user, "start", operation),
                "开始生产 妖兽契约",
            )
            assert started.code == "PRODUCTION_STARTED"
            _finish(runtime, started.data["order_id"], clock)
            failed = await runtime.adapters.dispatch(
                adapter,
                _context(adapter, user, "settle", "beast-pact-failure-settle"),
                "领取生产",
            )
            assert failed.code == "PRODUCTION_COMPLETED"
            assert failed.data["success"] is False
            assert failed.data["refunds"] == {"item.beast_blood": 1}
            await runtime.close()

    asyncio.run(run())
