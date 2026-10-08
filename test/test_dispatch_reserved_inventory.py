from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime


def _context(adapter: str, user: str, operation_id: str) -> CommandContext:
    return CommandContext(
        adapter=adapter,
        user_id=user,
        request_id=operation_id,
        operation_id=operation_id,
        can_write_assets=True,
    )


async def _send(runtime, adapter: str, user: str, operation_id: str, text: str):
    return await runtime.adapters.dispatch(adapter, _context(adapter, user, operation_id), text)


def _dispatch_cost_state(runtime, adapter: str, user: str, order_id: str, operation_id: str):
    with sqlite3.connect(runtime.settings.database_path) as connection:
        player = connection.execute(
            "SELECT inventory_json, stamina, energy FROM players WHERE platform=? AND platform_user_id=?",
            (adapter, user),
        ).fetchone()
        order = connection.execute(
            "SELECT status, remaining_quantity, item_key FROM market_orders WHERE order_id=?",
            (order_id,),
        ).fetchone()
        lock = connection.execute(
            "SELECT quantity FROM market_item_locks WHERE order_id=?",
            (order_id,),
        ).fetchone()
        assignments = connection.execute(
            "SELECT COUNT(*) FROM dispatch_assignments WHERE player_id=(SELECT id FROM players WHERE platform=? AND platform_user_id=?)",
            (adapter, user),
        ).fetchone()[0]
        operation_count = connection.execute(
            "SELECT COUNT(*) FROM operations WHERE operation_id=?",
            (operation_id,),
        ).fetchone()[0]
    assert player is not None and order is not None and lock is not None
    return (
        tuple(player),
        tuple(order),
        tuple(lock),
        int(assignments),
        int(operation_count),
    )


def test_dispatch_cannot_spend_market_reserved_wood_on_either_adapter() -> None:
    async def run() -> None:
        for adapter in ("qq.official", "onebot.v11"):
            with TemporaryDirectory() as data_dir:
                root = Path(data_dir)
                clock = lambda: datetime(2026, 10, 6, 12, tzinfo=UTC)
                runtime = create_runtime(data_dir=root, clock=clock)
                user = f"dispatch-reserved-{adapter}"
                operation_id = f"{adapter}-dispatch-accept"
                try:
                    created = await _send(runtime, adapter, user, f"{adapter}-create", "开始修仙")
                    assert created.code == "PLAYER_CREATED"
                    with sqlite3.connect(runtime.settings.database_path) as connection:
                        connection.execute(
                            "UPDATE players SET stage='mortal', intro_json=?, inventory_json=?, "
                            "location_key='beast.ten_thousand_hills', faction_reputation_json=?, "
                            "spirit_stones=1000, energy=100 WHERE platform=? AND platform_user_id=?",
                            (
                                json.dumps({"flags": ["guide.choose_service"]}, sort_keys=True),
                                json.dumps({"item.mat.wood": 2}, sort_keys=True),
                                json.dumps({"beast": 200}, sort_keys=True),
                                adapter,
                                user,
                            ),
                        )

                    listed = await _send(
                        runtime,
                        adapter,
                        user,
                        f"{adapter}-market-list",
                        "发布摆摊 item.mat.wood 2 100",
                    )
                    assert listed.code == "MARKET_ORDER_CREATED"
                    order_id = listed.data["order_id"]

                    preview = await _send(
                        runtime,
                        adapter,
                        user,
                        f"{adapter}-dispatch-preview",
                        "派遣预览 dispatch.workshop_help",
                    )
                    assert preview.code == "DISPATCH_PREVIEW"
                    record = preview.data["dispatches"][0]
                    assert record["ready"] is False
                    assert any("木材" in item for item in record["missing"])

                    before = _dispatch_cost_state(runtime, adapter, user, order_id, operation_id)
                    rejected = await _send(
                        runtime,
                        adapter,
                        user,
                        operation_id,
                        "接受派遣 dispatch.workshop_help",
                    )
                    assert rejected.code == "DISPATCH_REQUIREMENT_MISSING"
                    assert _dispatch_cost_state(runtime, adapter, user, order_id, operation_id) == before

                    cancelled = await _send(
                        runtime,
                        adapter,
                        user,
                        f"{adapter}-market-cancel",
                        f"取消摆摊 {order_id}",
                    )
                    assert cancelled.code == "MARKET_ORDER_CANCELLED"

                    accepted = await _send(
                        runtime,
                        adapter,
                        user,
                        operation_id,
                        "接受派遣 dispatch.workshop_help",
                    )
                    assert accepted.code == "DISPATCH_ACCEPTED"
                    assert accepted.data["idempotent_replay"] is False
                    with sqlite3.connect(runtime.settings.database_path) as connection:
                        inventory_text, energy = connection.execute(
                            "SELECT inventory_json, energy FROM players WHERE platform=? AND platform_user_id=?",
                            (adapter, user),
                        ).fetchone()
                        assignment_count = connection.execute(
                            "SELECT COUNT(*) FROM dispatch_assignments WHERE player_id=(SELECT id FROM players WHERE platform=? AND platform_user_id=?)",
                            (adapter, user),
                        ).fetchone()[0]
                        operation_count = connection.execute(
                            "SELECT COUNT(*) FROM operations WHERE operation_id=?",
                            (operation_id,),
                        ).fetchone()[0]
                    assert json.loads(inventory_text) == {}
                    assert energy == 96
                    assert assignment_count == operation_count == 1

                    await runtime.close()
                    runtime = create_runtime(data_dir=root, clock=clock)
                    replay = await _send(
                        runtime,
                        adapter,
                        user,
                        operation_id,
                        "接受派遣 dispatch.workshop_help",
                    )
                    assert replay.code == "DISPATCH_ACCEPTED"
                    assert replay.data["idempotent_replay"] is True
                    with sqlite3.connect(runtime.settings.database_path) as connection:
                        inventory_text, energy = connection.execute(
                            "SELECT inventory_json, energy FROM players WHERE platform=? AND platform_user_id=?",
                            (adapter, user),
                        ).fetchone()
                        assignment_count = connection.execute(
                            "SELECT COUNT(*) FROM dispatch_assignments WHERE player_id=(SELECT id FROM players WHERE platform=? AND platform_user_id=?)",
                            (adapter, user),
                        ).fetchone()[0]
                        operation_count = connection.execute(
                            "SELECT COUNT(*) FROM operations WHERE operation_id=?",
                            (operation_id,),
                        ).fetchone()[0]
                    assert json.loads(inventory_text) == {}
                    assert energy == 96
                    assert assignment_count == operation_count == 1

                    available_user = f"dispatch-unreserved-{adapter}"
                    created = await _send(
                        runtime,
                        adapter,
                        available_user,
                        f"{adapter}-available-create",
                        "开始修仙",
                    )
                    assert created.code == "PLAYER_CREATED"
                    with sqlite3.connect(runtime.settings.database_path) as connection:
                        connection.execute(
                            "UPDATE players SET stage='mortal', intro_json=?, inventory_json=?, "
                            "location_key='beast.ten_thousand_hills', faction_reputation_json=?, "
                            "spirit_stones=1000, energy=100 WHERE platform=? AND platform_user_id=?",
                            (
                                json.dumps({"flags": ["guide.choose_service"]}, sort_keys=True),
                                json.dumps({"item.mat.wood": 4}, sort_keys=True),
                                json.dumps({"beast": 200}, sort_keys=True),
                                adapter,
                                available_user,
                            ),
                        )
                    available_listing = await _send(
                        runtime,
                        adapter,
                        available_user,
                        f"{adapter}-available-market-list",
                        "发布摆摊 item.mat.wood 2 100",
                    )
                    assert available_listing.code == "MARKET_ORDER_CREATED"
                    available_order_id = available_listing.data["order_id"]
                    available_preview = await _send(
                        runtime,
                        adapter,
                        available_user,
                        f"{adapter}-available-dispatch-preview",
                        "派遣预览 dispatch.workshop_help",
                    )
                    assert available_preview.code == "DISPATCH_PREVIEW"
                    assert available_preview.data["dispatches"][0]["ready"] is True
                    available_dispatch = await _send(
                        runtime,
                        adapter,
                        available_user,
                        f"{adapter}-available-dispatch-accept",
                        "接受派遣 dispatch.workshop_help",
                    )
                    assert available_dispatch.code == "DISPATCH_ACCEPTED"
                    with sqlite3.connect(runtime.settings.database_path) as connection:
                        inventory_text = connection.execute(
                            "SELECT inventory_json FROM players WHERE platform=? AND platform_user_id=?",
                            (adapter, available_user),
                        ).fetchone()[0]
                        order = connection.execute(
                            "SELECT status, remaining_quantity FROM market_orders WHERE order_id=?",
                            (available_order_id,),
                        ).fetchone()
                        lock = connection.execute(
                            "SELECT quantity FROM market_item_locks WHERE order_id=?",
                            (available_order_id,),
                        ).fetchone()
                    assert json.loads(inventory_text) == {"item.mat.wood": 2}
                    assert tuple(order) == ("listed", 2)
                    assert tuple(lock) == (2,)
                finally:
                    await runtime.close()

    asyncio.run(run())
