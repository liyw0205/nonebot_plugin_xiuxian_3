from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Callable

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime


def _context(adapter: str, user: str, request: str, operation: str = "") -> CommandContext:
    return CommandContext(
        adapter=adapter,
        user_id=user,
        request_id=request,
        operation_id=operation,
        can_write_assets=True,
    )


async def _create_player(runtime, adapter: str, user: str) -> None:
    result = await runtime.adapters.dispatch(
        adapter, _context(adapter, user, f"create-{user}"), "开始修仙"
    )
    assert result.ok, (result.code, result.message)


def _database_snapshot(database: str) -> tuple[tuple[str, tuple[tuple[object, ...], ...]], ...]:
    with sqlite3.connect(database) as connection:
        return tuple(
            (
                table,
                tuple(
                    tuple(row)
                    for row in connection.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
                ),
            )
            for table in ("players", "market_orders", "market_item_locks", "economy_ledger_entries", "operations")
        )


def _duplicate_field(raw: str, field: str, replacement: object) -> str:
    payload = json.loads(raw)
    compact = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    marker = json.dumps(field, ensure_ascii=False) + ":"
    offset = compact.index(marker) + len(marker)
    original_value = json.dumps(payload[field], ensure_ascii=False, separators=(",", ":"))
    assert compact[offset : offset + len(original_value)] == original_value
    replacement_value = json.dumps(replacement, ensure_ascii=False, separators=(",", ":"))
    return (
        compact[: offset + len(original_value)]
        + ","
        + marker
        + replacement_value
        + compact[offset + len(original_value) :]
    )


def _set_operation_result(database: str, operation_id: str, value: str) -> None:
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE operations SET result_json = ? WHERE operation_id = ?",
            (value, operation_id),
        )


async def _assert_replay_rejects_corruption(
    runtime,
    adapter: str,
    user: str,
    operation_id: str,
    command: str,
    corrupt: Callable[[str], str],
) -> None:
    database = str(runtime.settings.database_path)
    with sqlite3.connect(database) as connection:
        original = str(
            connection.execute(
                "SELECT result_json FROM operations WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()[0]
        )
    corrupted = corrupt(original)
    assert corrupted != original
    _set_operation_result(database, operation_id, corrupted)
    before = _database_snapshot(database)

    rejected = await runtime.adapters.dispatch(
        adapter,
        _context(adapter, user, f"{operation_id}-corrupt-replay", operation_id),
        command,
    )
    assert rejected.code == "PERSISTENCE_ERROR", (rejected.code, rejected.message)
    assert _database_snapshot(database) == before

    _set_operation_result(database, operation_id, original)
    replayed = await runtime.adapters.dispatch(
        adapter,
        _context(adapter, user, f"{operation_id}-repaired-replay", operation_id),
        command,
    )
    assert replayed.ok, (replayed.code, replayed.message)
    assert replayed.data["idempotent_replay"] is True
    assert _database_snapshot(database) == _with_operation_result(before, operation_id, original)


def _with_operation_result(
    snapshot: tuple[tuple[str, tuple[tuple[object, ...], ...]], ...],
    operation_id: str,
    result_json: str,
) -> tuple[tuple[str, tuple[tuple[object, ...], ...]], ...]:
    updated = []
    for table, rows in snapshot:
        if table != "operations":
            updated.append((table, rows))
            continue
        updated.append(
            (
                table,
                tuple(
                    tuple(result_json if index == 4 and row[0] == operation_id else value for index, value in enumerate(row))
                    for row in rows
                ),
            )
        )
    return tuple(updated)


def test_market_operation_replay_rejects_corrupt_results_on_both_adapters() -> None:
    async def run() -> None:
        for adapter in ("qq.official", "onebot.v11"):
            with TemporaryDirectory() as data_dir:
                runtime = create_runtime(
                    data_dir=Path(data_dir) / adapter,
                    clock=lambda: datetime(2026, 10, 6, 12, tzinfo=timezone.utc),
                )
                seller = f"market-integrity-seller-{adapter}"
                buyer = f"market-integrity-buyer-{adapter}"
                try:
                    await _create_player(runtime, adapter, seller)
                    await _create_player(runtime, adapter, buyer)
                    with sqlite3.connect(runtime.settings.database_path) as connection:
                        connection.execute(
                            "UPDATE players SET inventory_json = ?, location_key = ?, spirit_stones = 1000 "
                            "WHERE platform = ? AND platform_user_id = ?",
                            (json.dumps({"item.food.cloud_tea": 2}), "beast.ten_thousand_hills", adapter, seller),
                        )
                        connection.execute(
                            "UPDATE players SET location_key = ?, faction_reputation_json = ?, spirit_stones = 1000 "
                            "WHERE platform = ? AND platform_user_id = ?",
                            ("demon.abyss_market", json.dumps({"demon": 200}), adapter, buyer),
                        )

                    create_operation = f"{adapter}-market-create"
                    created = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, seller, "market-create", create_operation),
                        "发布摆摊 item.food.cloud_tea 2 100",
                    )
                    assert created.code == "MARKET_ORDER_CREATED", (created.code, created.message)
                    order_id = str(created.data["order_id"])
                    create_command = "发布摆摊 item.food.cloud_tea 2 100"

                    await _assert_replay_rejects_corruption(
                        runtime,
                        adapter,
                        seller,
                        create_operation,
                        create_command,
                        lambda raw: _duplicate_field(raw, "total_price", 9999),
                    )
                    await _assert_replay_rejects_corruption(
                        runtime,
                        adapter,
                        seller,
                        create_operation,
                        create_command,
                        lambda raw: json.dumps({**json.loads(raw), "quantity": True}, ensure_ascii=False),
                    )
                    await _assert_replay_rejects_corruption(
                        runtime,
                        adapter,
                        seller,
                        create_operation,
                        create_command,
                        lambda raw: json.dumps({**json.loads(raw), "total_price": 9999}, ensure_ascii=False),
                    )
                    await _assert_replay_rejects_corruption(
                        runtime,
                        adapter,
                        seller,
                        create_operation,
                        create_command,
                        lambda _raw: "[]",
                    )
                    await _assert_replay_rejects_corruption(
                        runtime,
                        adapter,
                        seller,
                        create_operation,
                        create_command,
                        lambda raw: raw[:-1],
                    )

                    conflict = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, seller, "market-create-conflict", create_operation),
                        "发布摆摊 item.food.cloud_tea 1 100",
                    )
                    assert conflict.code == "LEDGER_CONFLICT"

                    buy_operation = f"{adapter}-market-buy"
                    buy_command = f"购买摆摊 {order_id} 1"
                    bought = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, buyer, "market-buy", buy_operation),
                        buy_command,
                    )
                    assert bought.code == "MARKET_ORDER_PURCHASED", (bought.code, bought.message)
                    await _assert_replay_rejects_corruption(
                        runtime,
                        adapter,
                        buyer,
                        buy_operation,
                        buy_command,
                        lambda raw: _duplicate_field(raw, "status", "settled"),
                    )

                    cancel_operation = f"{adapter}-market-cancel"
                    cancel_command = f"取消摆摊 {order_id}"
                    cancelled = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, seller, "market-cancel", cancel_operation),
                        cancel_command,
                    )
                    assert cancelled.code == "MARKET_ORDER_CANCELLED", (cancelled.code, cancelled.message)
                    await _assert_replay_rejects_corruption(
                        runtime,
                        adapter,
                        seller,
                        cancel_operation,
                        cancel_command,
                        lambda raw: _duplicate_field(raw, "quantity", 999),
                    )

                    expire_create_operation = f"{adapter}-market-expire-create"
                    expire_create = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, seller, "market-expire-create", expire_create_operation),
                        "发布摆摊 item.food.cloud_tea 1 100",
                    )
                    assert expire_create.code == "MARKET_ORDER_CREATED", (expire_create.code, expire_create.message)
                    expired_order_id = str(expire_create.data["order_id"])
                    with sqlite3.connect(runtime.settings.database_path) as connection:
                        connection.execute(
                            "UPDATE market_orders SET expires_at = ? WHERE order_id = ?",
                            ("2026-10-05T12:00:00+00:00", expired_order_id),
                        )
                    expire_operation = f"{adapter}-market-expire"
                    expire_command = f"清理摆摊 {expired_order_id}"
                    expired = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, seller, "market-expire", expire_operation),
                        expire_command,
                    )
                    assert expired.code == "MARKET_ORDER_EXPIRED", (expired.code, expired.message)
                    await _assert_replay_rejects_corruption(
                        runtime,
                        adapter,
                        seller,
                        expire_operation,
                        expire_command,
                        lambda raw: _duplicate_field(raw, "item_key", "item.pill.healing_low"),
                    )

                    await runtime.close()
                    runtime = create_runtime(
                        data_dir=Path(data_dir) / adapter,
                        clock=lambda: datetime(2026, 10, 6, 12, tzinfo=timezone.utc),
                    )
                    after_restart = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, seller, "market-create-after-restart", create_operation),
                        create_command,
                    )
                    assert after_restart.ok, (after_restart.code, after_restart.message)
                    assert after_restart.data["idempotent_replay"] is True
                    for replay_user, replay_operation, replay_command in (
                        (buyer, buy_operation, buy_command),
                        (seller, cancel_operation, cancel_command),
                        (seller, expire_operation, expire_command),
                    ):
                        replay = await runtime.adapters.dispatch(
                            adapter,
                            _context(
                                adapter,
                                replay_user,
                                f"{replay_operation}-after-restart",
                                replay_operation,
                            ),
                            replay_command,
                        )
                        assert replay.ok, (replay.code, replay.message)
                        assert replay.data["idempotent_replay"] is True
                finally:
                    await runtime.close()

    asyncio.run(run())
