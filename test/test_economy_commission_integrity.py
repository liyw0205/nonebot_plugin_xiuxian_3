from __future__ import annotations

import asyncio
import json
import re
import sqlite3
from datetime import datetime, timedelta, timezone
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


async def _send(runtime, adapter: str, user: str, operation_id: str, command: str):
    return await runtime.adapters.dispatch(
        adapter,
        CommandContext(adapter=adapter, user_id=user, operation_id=operation_id),
        command,
    )


def _prepare_producer(runtime, user: str) -> None:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            """
            UPDATE players SET stage = 'cultivator', realm_key = 'qi_sensing', realm_layer = 1,
                subprofession_key = 'alchemy', energy = 20, energy_max = 20, inventory_json = ?
            WHERE platform_user_id = ?
            """,
            (
                json.dumps(
                    {
                        "item.herb.blood_grass": 3,
                        "item.food.coarse_spirit_rice": 2,
                        "item.tool.basic_furnace": 1,
                    },
                    ensure_ascii=False,
                ),
                user,
            ),
        )


def _row(database: str, sql: str, *args: object):
    with sqlite3.connect(database) as connection:
        return connection.execute(sql, args).fetchone()


def _order(database: str, commission_id: str) -> tuple[object, ...]:
    return _row(
        database,
        "SELECT status, result_json, snapshot_json, reward_stones FROM production_commission_orders "
        "WHERE commission_id=?",
        commission_id,
    )


def _state(database: str, user: str) -> tuple[object, ...]:
    return _row(
        database,
        "SELECT spirit_stones, stamina, energy, inventory_json FROM players WHERE platform_user_id=?",
        user,
    )


def _ledger(database: str) -> int:
    return int(_row(database, "SELECT COUNT(*) FROM economy_ledger_entries")[0])


def _operations(database: str) -> int:
    return int(_row(database, "SELECT COUNT(*) FROM operations")[0])


def _update(database: str, sql: str, *args: object) -> None:
    with sqlite3.connect(database) as connection:
        connection.execute(sql, args)


async def _publish_and_accept(runtime, publisher: tuple[str, str], producer: tuple[str, str], prefix: str) -> str:
    """Publish a producer-supplied commission and accept it with a high quality roll."""

    publisher_adapter, publisher_user = publisher
    producer_adapter, producer_user = producer
    created = await _send(runtime, publisher_adapter, publisher_user, f"{prefix}-create", "发布生产委托 疗伤丹 50 生产者供料")
    assert created.code == "COMMISSION_CREATED", (created.code, created.message)
    commission_id = str(created.data["commission_id"])
    accept_operation = next(
        f"{prefix}-accept-{index}"
        for index in range(1024)
        if random_quality_bp(f"{prefix}-accept-{index}") >= 1000
    )
    accepted = await _send(runtime, producer_adapter, producer_user, accept_operation, f"接取生产委托 {commission_id}")
    assert accepted.code == "COMMISSION_ACCEPTED", (accepted.code, accepted.message)
    return commission_id


async def _boot(data_dir: str, clock: MutableClock, publisher: tuple[str, str], producer: tuple[str, str]):
    runtime = create_runtime(data_dir=data_dir, clock=clock)
    for adapter, user in (publisher, producer):
        assert (await _send(runtime, adapter, user, f"{user}-create-player", "开始修仙")).ok
        assert (await _send(runtime, adapter, user, f"{user}-seek", "寻仙问道")).ok
    _prepare_producer(runtime, producer[1])
    return runtime


def _assert_frozen(database: str, commission_id: str, states: dict[str, tuple], ledger: int, operations: int) -> None:
    for user, before in states.items():
        assert _state(database, user) == before, user
    assert _ledger(database) == ledger
    assert _operations(database) == operations


def test_commission_settle_rejects_tampered_output_snapshot() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 23, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            publisher = ("qq.official", "commission-publisher")
            producer = ("onebot.v11", "commission-producer")
            runtime = await _boot(data_dir, clock, publisher, producer)
            database = str(runtime.settings.database_path)
            commission_id = await _publish_and_accept(runtime, publisher, producer, "settle")
            clock.advance(seconds=31)
            delivered = await _send(runtime, producer[0], producer[1], "settle-deliver", f"交付生产委托 {commission_id}")
            assert delivered.code == "COMMISSION_DELIVERED", (delivered.code, delivered.message)

            stored_result = str(_order(database, commission_id)[1])
            inflated = re.sub(
                r'("outputs"\s*:\s*\{[^{}]*)(\})',
                r'\1,"item.pill.healing_low":999\2',
                stored_result,
                count=1,
            )
            assert inflated != stored_result
            _update(
                database,
                "UPDATE production_commission_orders SET result_json = ? WHERE commission_id = ?",
                inflated,
                commission_id,
            )
            states = {publisher[1]: _state(database, publisher[1]), producer[1]: _state(database, producer[1])}
            ledger, operations = _ledger(database), _operations(database)

            tampered = await _send(runtime, publisher[0], publisher[1], "settle-claim", f"确认生产委托 {commission_id}")
            assert tampered.code == "PERSISTENCE_ERROR", (tampered.code, tampered.message)
            _assert_frozen(database, commission_id, states, ledger, operations)

            _update(
                database,
                "UPDATE production_commission_orders SET result_json = ? WHERE commission_id = ?",
                stored_result,
                commission_id,
            )
            truncated = json.loads(stored_result)
            truncated["outputs"] = {"item.pill.healing_low": "1"}
            _update(
                database,
                "UPDATE production_commission_orders SET result_json = ? WHERE commission_id = ?",
                json.dumps(truncated, ensure_ascii=False),
                commission_id,
            )
            string_amount = await _send(runtime, publisher[0], publisher[1], "settle-claim", f"确认生产委托 {commission_id}")
            assert string_amount.code == "PERSISTENCE_ERROR", (string_amount.code, string_amount.message)
            _assert_frozen(database, commission_id, states, ledger, operations)

            _update(
                database,
                "UPDATE production_commission_orders SET result_json = ? WHERE commission_id = ?",
                stored_result,
                commission_id,
            )
            settled = await _send(runtime, publisher[0], publisher[1], "settle-claim", f"确认生产委托 {commission_id}")
            assert settled.code == "COMMISSION_SETTLED", (settled.code, settled.message)
            assert settled.data["outputs"] == {"item.pill.healing_low": 1}
            assert settled.data["producer_payment"] == 49
            publisher_after = _state(database, publisher[1])
            assert json.loads(publisher_after[3])["item.pill.healing_low"] == 1
            # One item credit, one producer payment and one platform fee entry.
            assert _ledger(database) == ledger + 3
            await runtime.close()

    asyncio.run(run())


def test_commission_delivery_rejects_tampered_frozen_snapshot() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 23, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            publisher = ("onebot.v11", "delivery-publisher")
            producer = ("qq.official", "delivery-producer")
            runtime = await _boot(data_dir, clock, publisher, producer)
            database = str(runtime.settings.database_path)
            commission_id = await _publish_and_accept(runtime, publisher, producer, "deliver")

            stored_snapshot = str(_order(database, commission_id)[2])
            forced = stored_snapshot.replace(
                '"random_quality_bp":', '"random_quality_bp":10000,"random_quality_bp":', 1
            )
            assert forced != stored_snapshot
            _update(
                database,
                "UPDATE production_commission_orders SET snapshot_json = ? WHERE commission_id = ?",
                forced,
                commission_id,
            )
            clock.advance(seconds=31)
            states = {publisher[1]: _state(database, publisher[1]), producer[1]: _state(database, producer[1])}
            ledger, operations = _ledger(database), _operations(database)

            tampered = await _send(runtime, producer[0], producer[1], "deliver-run", f"交付生产委托 {commission_id}")
            assert tampered.code == "PERSISTENCE_ERROR", (tampered.code, tampered.message)
            _assert_frozen(database, commission_id, states, ledger, operations)

            broken = json.loads(stored_snapshot)
            broken["recipe_key"] = "recipe.pill.unknown"
            _update(
                database,
                "UPDATE production_commission_orders SET snapshot_json = ? WHERE commission_id = ?",
                json.dumps(broken, ensure_ascii=False),
                commission_id,
            )
            mismatched = await _send(runtime, producer[0], producer[1], "deliver-run", f"交付生产委托 {commission_id}")
            assert mismatched.code == "PERSISTENCE_ERROR", (mismatched.code, mismatched.message)
            _assert_frozen(database, commission_id, states, ledger, operations)

            _update(
                database,
                "UPDATE production_commission_orders SET snapshot_json = ? WHERE commission_id = ?",
                stored_snapshot,
                commission_id,
            )
            delivered = await _send(runtime, producer[0], producer[1], "deliver-run", f"交付生产委托 {commission_id}")
            assert delivered.code == "COMMISSION_DELIVERED", (delivered.code, delivered.message)
            assert delivered.data["status"] == "delivered"
            await runtime.close()

    asyncio.run(run())


def test_commission_replay_and_operation_ledger_stay_bound_to_the_order() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 23, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            publisher = ("qq.official", "replay-publisher")
            producer = ("onebot.v11", "replay-producer")
            runtime = await _boot(data_dir, clock, publisher, producer)
            database = str(runtime.settings.database_path)
            commission_id = await _publish_and_accept(runtime, publisher, producer, "replay")
            clock.advance(seconds=31)
            assert (await _send(runtime, producer[0], producer[1], "replay-deliver", f"交付生产委托 {commission_id}")).code == "COMMISSION_DELIVERED"
            settled = await _send(runtime, publisher[0], publisher[1], "replay-settle", f"确认生产委托 {commission_id}")
            assert settled.code == "COMMISSION_SETTLED", (settled.code, settled.message)
            after_settle = _state(database, publisher[1])
            ledger, operations = _ledger(database), _operations(database)

            stored = str(_row(database, "SELECT result_json FROM operations WHERE operation_id=?", "replay-settle")[0])
            forged = json.loads(stored)
            forged["producer_payment"] = 9999
            _update(
                database,
                "UPDATE operations SET result_json = ? WHERE operation_id = ?",
                json.dumps(forged, ensure_ascii=False),
                "replay-settle",
            )
            forged_replay = await _send(runtime, publisher[0], publisher[1], "replay-settle", f"确认生产委托 {commission_id}")
            assert forged_replay.code == "PERSISTENCE_ERROR", (forged_replay.code, forged_replay.message)
            _assert_frozen(database, commission_id, {publisher[1]: after_settle}, ledger, operations)

            duplicate = stored.replace('"outputs":', '"outputs":{},"outputs":', 1)
            assert duplicate != stored
            _update(database, "UPDATE operations SET result_json = ? WHERE operation_id = ?", duplicate, "replay-settle")
            duplicated = await _send(runtime, publisher[0], publisher[1], "replay-settle", f"确认生产委托 {commission_id}")
            assert duplicated.code == "PERSISTENCE_ERROR", (duplicated.code, duplicated.message)
            _assert_frozen(database, commission_id, {publisher[1]: after_settle}, ledger, operations)

            _update(
                database,
                "UPDATE operations SET result_json = ? WHERE operation_id = ?",
                stored,
                "replay-settle",
            )
            replay = await _send(runtime, publisher[0], publisher[1], "replay-settle", f"确认生产委托 {commission_id}")
            assert replay.code == "COMMISSION_SETTLED", (replay.code, replay.message)
            assert replay.data["idempotent_replay"] is True
            assert replay.data["producer_payment"] == 49
            _assert_frozen(database, commission_id, {publisher[1]: after_settle}, ledger, operations)
            await runtime.close()

            restarted = create_runtime(data_dir=data_dir, clock=clock)
            after_restart = await _send(restarted, publisher[0], publisher[1], "replay-settle", f"确认生产委托 {commission_id}")
            assert after_restart.code == "COMMISSION_SETTLED", (after_restart.code, after_restart.message)
            assert after_restart.data["idempotent_replay"] is True
            _assert_frozen(database, commission_id, {publisher[1]: after_settle}, ledger, operations)
            await restarted.close()

    asyncio.run(run())


def test_commission_escrow_and_platform_fee_stay_consistent() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 23, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            publisher = ("onebot.v11", "escrow-publisher")
            producer = ("qq.official", "escrow-producer")
            runtime = await _boot(data_dir, clock, publisher, producer)
            database = str(runtime.settings.database_path)
            commission_id = await _publish_and_accept(runtime, publisher, producer, "escrow")
            clock.advance(seconds=31)
            assert (await _send(runtime, producer[0], producer[1], "escrow-deliver", f"交付生产委托 {commission_id}")).code == "COMMISSION_DELIVERED"

            stored = str(_order(database, commission_id)[1])
            skewed = json.loads(stored)
            skewed["producer_payment"] = 50
            skewed["platform_fee"] = 50
            _update(
                database,
                "UPDATE production_commission_orders SET result_json = ? WHERE commission_id = ?",
                json.dumps(skewed, ensure_ascii=False),
                commission_id,
            )
            states = {publisher[1]: _state(database, publisher[1]), producer[1]: _state(database, producer[1])}
            ledger, operations = _ledger(database), _operations(database)
            skewed_settle = await _send(runtime, publisher[0], publisher[1], "escrow-settle", f"确认生产委托 {commission_id}")
            assert skewed_settle.code == "PERSISTENCE_ERROR", (skewed_settle.code, skewed_settle.message)
            _assert_frozen(database, commission_id, states, ledger, operations)

            _update(
                database,
                "UPDATE production_commission_orders SET result_json = ? WHERE commission_id = ?",
                stored,
                commission_id,
            )
            settled = await _send(runtime, publisher[0], publisher[1], "escrow-settle", f"确认生产委托 {commission_id}")
            assert settled.code == "COMMISSION_SETTLED", (settled.code, settled.message)
            assert settled.data["producer_payment"] + settled.data["platform_fee"] == 50
            await runtime.close()

    asyncio.run(run())
