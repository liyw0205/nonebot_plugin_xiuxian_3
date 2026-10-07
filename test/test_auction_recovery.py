from __future__ import annotations

import asyncio
import json
import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from nonebot_plugin_xiuxian_3.adapters.onebot import normalize_event
from nonebot_plugin_xiuxian_3.adapters.qq import normalize_event as normalize_qq_event
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.economy import auction_repository
from test_adapter_simulation import _onebot_group_event, _qq_group_event


ADAPTERS = ("qq.official", "onebot.v11")
ITEM = "item.material.cloud_iron"
CREATE = "发布拍卖 云铁 1 100"


class Clock:
    def __init__(self):
        self.value = datetime(2026, 10, 5, 12, tzinfo=timezone.utc)

    def __call__(self):
        return self.value


async def _send(runtime, adapter, user, operation, command):
    if adapter == "qq.official":
        message = normalize_qq_event(_qq_group_event(command, message_id=operation))
    else:
        message = normalize_event(_onebot_group_event(command))
    return await runtime.adapters.dispatch(
        adapter, replace(message.context, user_id=user, operation_id=operation), message.text
    )


async def _setup(path, adapter):
    clock = Clock()
    runtime = create_runtime(data_dir=path, adapters=(adapter,), clock=clock)
    for user, name in (("seller", "青玄"), ("bidder", "白衡"), ("other", "素心"), ("outsider", "清尘")):
        result = await _send(runtime, adapter, user, f"create-{user}", f"开始修仙 {name}")
        assert result.code == "PLAYER_CREATED", result
    # Auction funds and goods are local fixtures, not completed production claims.
    with sqlite3.connect(runtime.settings.database_path) as connection:
        for user, balance in (("seller", 100), ("bidder", 500), ("other", 800), ("outsider", 0)):
            connection.execute(
                "UPDATE players SET spirit_stones=?, inventory_json=? WHERE platform=? AND platform_user_id=?",
                (balance, json.dumps({ITEM: 4} if user == "seller" else {}), adapter, user),
            )
    return runtime, clock


def _database(runtime):
    with sqlite3.connect(runtime.settings.database_path) as connection:
        return tuple(connection.iterdump())


def _unrelated(runtime):
    with sqlite3.connect(runtime.settings.database_path) as connection:
        return {
            table: connection.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
            for table in ("codex_entries", "equipment_instances", "player_reputations", "battle_sessions", "arena_matches")
        }


def _conservation(runtime):
    with sqlite3.connect(runtime.settings.database_path) as connection:
        players = connection.execute("SELECT spirit_stones, inventory_json FROM players").fetchall()
        escrow = connection.execute("SELECT COALESCE(SUM(bid_amount), 0) FROM auction_bids WHERE status='active'").fetchone()[0]
        assert sum(row[0] for row in players) + escrow == 1400
        assert sum(json.loads(row[1]).get(ITEM, 0) for row in players) == 4
        assert all(row[0] >= 0 for row in players)
        for inventory, quantity in connection.execute(
            "SELECT p.inventory_json, SUM(l.quantity) FROM auction_item_locks l "
            "JOIN players p ON p.id=l.seller_player_id GROUP BY p.id"
        ):
            assert 0 < quantity <= json.loads(inventory).get(ITEM, 0)
        expected_currency = {"seller": 100, "bidder": 500, "other": 800, "outsider": 0}
        expected_items = {user: (4 if user == "seller" else 0) for user in expected_currency}
        for user, kind, direction, amount, before, after, operation in connection.execute(
            "SELECT p.platform_user_id,e.asset_kind,e.direction,e.amount,e.before_value,e.after_value,o.operation_id "
            "FROM economy_ledger_entries e JOIN players p ON p.id=e.player_id "
            "LEFT JOIN operations o ON o.operation_id=e.operation_id ORDER BY e.id"
        ):
            assert operation is not None
            assert amount > 0 and before >= 0 and after >= 0
            if direction == "credit":
                assert after == before + amount
            elif direction in {"debit", "lock"}:
                assert after == before - amount
            else:
                assert direction == "release" and after == before
            if kind == "currency":
                expected_currency[user] += amount if direction == "credit" else -amount
            elif direction in {"credit", "debit"}:
                expected_items[user] += amount if direction == "credit" else -amount
        for user, balance, inventory in connection.execute("SELECT platform_user_id,spirit_stones,inventory_json FROM players"):
            assert balance == expected_currency[user]
            assert json.loads(inventory).get(ITEM, 0) == expected_items[user]


async def _rejected(runtime, adapter, user, operation, command, *, code=None):
    before = _database(runtime)
    result = await _send(runtime, adapter, user, operation, command)
    assert not result.ok, result
    if code is not None:
        assert result.code == code, result
    assert _database(runtime) == before
    return result


def _replay(original, replay):
    assert replay.ok == original.ok
    assert replay.code == original.code
    assert replay.message == original.message
    assert replay.data == {**original.data, "idempotent_replay": True}


def _write_snapshot(runtime, auction, raw):
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute("UPDATE auction_lots SET snapshot_json=? WHERE auction_id=?", (raw, auction))


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_auction_corrupt_snapshots_never_write_and_recover(tmp_path, adapter):
    async def run():
        runtime, clock = await _setup(tmp_path, adapter)
        untouched = _unrelated(runtime)
        created = await _send(runtime, adapter, "seller", "lot", CREATE)
        assert created.code == "AUCTION_CREATED", created
        auction = created.data["auction_id"]
        bid = await _send(runtime, adapter, "bidder", "bid", f"竞价 {auction} 100")
        assert bid.code == "AUCTION_BID_PLACED", bid
        with sqlite3.connect(runtime.settings.database_path) as connection:
            original = connection.execute("SELECT snapshot_json FROM auction_lots WHERE auction_id=?", (auction,)).fetchone()[0]
        snapshot = json.loads(original)
        corruptions = (
            "{",
            '{"quantity":2,' + original[1:],
            json.dumps({key: value for key, value in snapshot.items() if key != "item_label"}),
            json.dumps({key: value for key, value in snapshot.items() if key != "rules"}),
            json.dumps({**snapshot, "quantity": True}),
            json.dumps({**snapshot, "quantity": 1.5}),
            json.dumps({**snapshot, "quantity": 0}),
            json.dumps({**snapshot, "starting_bid": -1}),
        )
        opened_at = clock.value
        for corrupt in corruptions:
            _write_snapshot(runtime, auction, corrupt)
            clock.value = opened_at
            await _rejected(runtime, adapter, "outsider", "list", "拍卖列表")
            await _rejected(runtime, adapter, "other", "outbid", f"竞价 {auction} 105")
            clock.value = datetime.fromisoformat(created.data["ends_at"]) + timedelta(seconds=1)
            await _rejected(runtime, adapter, "seller", "settle", f"结算拍卖 {auction}")
            _conservation(runtime)
        before = _database(runtime)
        _replay(created, await _send(runtime, adapter, "seller", "lot", CREATE))
        _replay(bid, await _send(runtime, adapter, "bidder", "bid", f"竞价 {auction} 100"))
        assert _database(runtime) == before
        _write_snapshot(runtime, auction, original)
        await runtime.close()

        runtime = create_runtime(data_dir=tmp_path, adapters=(adapter,), clock=clock)
        settled = await _send(runtime, adapter, "seller", "settle", f"结算拍卖 {auction}")
        assert settled.code == "AUCTION_SETTLED", settled
        assert settled.data["current_bid"] == 100
        _conservation(runtime)
        assert _unrelated(runtime) == untouched
        await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_auction_corrupt_operation_results_reject_and_replay_after_repair(tmp_path, adapter):
    async def run():
        runtime, clock = await _setup(tmp_path, adapter)
        created = await _send(runtime, adapter, "seller", "lot", CREATE)
        assert created.code == "AUCTION_CREATED", created
        auction = created.data["auction_id"]
        bid_command, settle_command = f"竞价 {auction} 100", f"结算拍卖 {auction}"
        bid = await _send(runtime, adapter, "bidder", "bid", bid_command)
        assert bid.code == "AUCTION_BID_PLACED", bid
        clock.value = datetime.fromisoformat(created.data["ends_at"]) + timedelta(seconds=1)
        settled = await _send(runtime, adapter, "seller", "settle", settle_command)
        assert settled.code == "AUCTION_SETTLED", settled
        history = (("seller", "lot", CREATE, created), ("bidder", "bid", bid_command, bid), ("seller", "settle", settle_command, settled))
        for user, operation, command, _ in history:
            with sqlite3.connect(runtime.settings.database_path) as connection:
                original = connection.execute("SELECT result_json FROM operations WHERE operation_id=?", (operation,)).fetchone()[0]
            payload = json.loads(original)
            corruptions = (
                "{", "[]", '{"quantity":2,' + original[1:],
                json.dumps({key: value for key, value in payload.items() if key != "item_label"}),
                json.dumps({**payload, "current_bid": True}),
                json.dumps({**payload, "quantity": 1.5}),
                json.dumps({**payload, "ends_at": "2026-10-05"}),
            )
            if payload["current_bid"] > 0:
                corruptions += (json.dumps({**payload, "status": "unsold"}),)
            if operation == "lot":
                corruptions += (
                    json.dumps({**payload, "status": "unsold"}),
                    json.dumps({**payload, "status": "open", "current_bid": payload["starting_bid"], "current_bidder_platform_user_id": "bidder"}),
                    json.dumps({**payload, "quantity": payload["quantity"] + 1}),
                    json.dumps({**payload, "starting_bid": payload["starting_bid"] + 1}),
                    json.dumps({**payload, "seller_platform_user_id": "other"}),
                )
            elif operation == "bid":
                corruptions += (
                    json.dumps({**payload, "status": "settled"}),
                    json.dumps({**payload, "status": "open", "current_bid": 0, "current_bidder_platform_user_id": None}),
                    json.dumps({**payload, "auction_id": "auction-other"}),
                    json.dumps({**payload, "current_bid": payload["current_bid"] + 1}),
                    json.dumps({**payload, "current_bidder_platform_user_id": "other"}),
                )
            else:
                corruptions += tuple(
                    json.dumps({**payload, "status": status}) for status in ("open", "settling")
                )
                corruptions += (json.dumps({**payload, "auction_id": "auction-other"}),)
            for corrupt in corruptions:
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute("UPDATE operations SET result_json=? WHERE operation_id=?", (corrupt, operation))
                await _rejected(runtime, adapter, user, operation, command)
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute("UPDATE operations SET result_json=? WHERE operation_id=?", (original, operation))
                owner = connection.execute("SELECT player_id FROM operations WHERE operation_id=?", (operation,)).fetchone()[0]
                outsider = connection.execute("SELECT id FROM players WHERE platform_user_id='outsider'").fetchone()[0]
                connection.execute("UPDATE operations SET player_id=? WHERE operation_id=?", (outsider, operation))
            await _rejected(runtime, adapter, user, operation, command, code="OPERATION_CONFLICT")
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute("UPDATE operations SET player_id=? WHERE operation_id=?", (owner, operation))
        await runtime.close()

        runtime = create_runtime(data_dir=tmp_path, adapters=(adapter,), clock=clock)
        await runtime.initialize()
        before = _database(runtime)
        for user, operation, command, original in history:
            _replay(original, await _send(runtime, adapter, user, operation, command))
        assert _database(runtime) == before
        _conservation(runtime)
        await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_auction_operation_fault_rolls_back_assets_locks_and_ledgers(tmp_path, monkeypatch, adapter):
    async def run():
        runtime, clock = await _setup(tmp_path, adapter)
        untouched, history = _unrelated(runtime), []
        real_record = auction_repository.record_operation

        def fail_after_record(*args, **kwargs):
            real_record(*args, **kwargs)
            raise RuntimeError("injected auction operation failure")

        async def attempt(user, operation, command, code):
            with monkeypatch.context() as patch:
                patch.setattr(auction_repository, "record_operation", fail_after_record)
                await _rejected(runtime, adapter, user, operation, command, code="PERSISTENCE_ERROR")
            result = await _send(runtime, adapter, user, operation, command)
            assert result.code == code, result
            assert result.data["idempotent_replay"] is False
            history.append((user, operation, command, result))
            _conservation(runtime)
            return result

        created = await attempt("seller", "lot", CREATE, "AUCTION_CREATED")
        auction = created.data["auction_id"]
        await attempt("bidder", "bid", f"竞价 {auction} 100", "AUCTION_BID_PLACED")
        await attempt("other", "outbid", f"竞价 {auction} 105", "AUCTION_BID_PLACED")
        clock.value = datetime.fromisoformat(created.data["ends_at"]) + timedelta(seconds=1)
        await attempt("seller", "settle", f"结算拍卖 {auction}", "AUCTION_SETTLED")
        expired = await attempt("seller", "expiring-lot", CREATE, "AUCTION_CREATED")
        expiring = expired.data["auction_id"]
        await attempt("bidder", "expiring-bid", f"竞价 {expiring} 200", "AUCTION_BID_PLACED")
        clock.value = datetime.fromisoformat(expired.data["settlement_deadline"])
        await attempt("outsider", "expire", f"结算拍卖 {expiring}", "AUCTION_SETTLEMENT_EXPIRED")
        unsold = await attempt("seller", "unsold-lot", CREATE, "AUCTION_CREATED")
        clock.value = datetime.fromisoformat(unsold.data["ends_at"]) + timedelta(seconds=1)
        await attempt("outsider", "unsold", f"结算拍卖 {unsold.data['auction_id']}", "AUCTION_UNSOLD")
        assert _unrelated(runtime) == untouched
        with sqlite3.connect(runtime.settings.database_path) as connection:
            assert connection.execute("SELECT COUNT(*) FROM auction_item_locks").fetchone()[0] == 0
            assert connection.execute("SELECT COUNT(*) FROM auction_bids WHERE status='active'").fetchone()[0] == 0
            assert connection.execute("SELECT COUNT(*) FROM operations WHERE operation_name LIKE 'economy.%auction'").fetchone()[0] == len(history)
            balances = dict(connection.execute("SELECT platform_user_id,spirit_stones FROM players"))
            assert balances == {"seller": 205, "bidder": 500, "other": 695, "outsider": 0}
        await runtime.close()

        runtime = create_runtime(data_dir=tmp_path, adapters=(adapter,), clock=clock)
        await runtime.initialize()
        before = _database(runtime)
        for user, operation, command, original in history:
            _replay(original, await _send(runtime, adapter, user, operation, command))
        assert _database(runtime) == before
        _conservation(runtime)
        await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_auction_identity_self_bid_and_funds_checks_never_release_escrow(tmp_path, adapter):
    async def run():
        runtime, _ = await _setup(tmp_path, adapter)
        created = await _send(runtime, adapter, "seller", "lot", CREATE)
        assert created.code == "AUCTION_CREATED", created
        auction = created.data["auction_id"]
        await _rejected(runtime, adapter, "other", "lot", CREATE, code="OPERATION_CONFLICT")
        await _rejected(runtime, adapter, "seller", "lot", "发布拍卖 云铁 2 100", code="OPERATION_CONFLICT")
        await _rejected(runtime, adapter, "seller", "self-bid", f"竞价 {auction} 100", code="AUCTION_SELF_BID")
        await _rejected(runtime, adapter, "outsider", "poor-bid", f"竞价 {auction} 100", code="BALANCE_INSUFFICIENT")
        bid = await _send(runtime, adapter, "bidder", "bid", f"竞价 {auction} 100")
        assert bid.code == "AUCTION_BID_PLACED", bid
        await _rejected(runtime, adapter, "other", "bid", f"竞价 {auction} 100", code="OPERATION_CONFLICT")
        await _rejected(runtime, adapter, "bidder", "bid", f"竞价 {auction} 105", code="OPERATION_CONFLICT")
        await _rejected(runtime, adapter, "bidder", "over-budget", f"竞价 {auction} 501", code="BALANCE_INSUFFICIENT")
        await _rejected(runtime, adapter, "other", "low-bid", f"竞价 {auction} 104", code="AUCTION_BID_TOO_LOW")
        rebid = await _send(runtime, adapter, "bidder", "rebid", f"竞价 {auction} 105")
        assert rebid.code == "AUCTION_BID_PLACED", rebid
        before = _database(runtime)
        listed = await _send(runtime, adapter, "outsider", "list", "拍卖列表")
        assert listed.code == "AUCTION_LISTED", listed
        assert _database(runtime) == before
        with sqlite3.connect(runtime.settings.database_path) as connection:
            assert connection.execute("SELECT spirit_stones FROM players WHERE platform_user_id='bidder'").fetchone()[0] == 395
            assert connection.execute("SELECT COUNT(*) FROM auction_bids WHERE status='active'").fetchone()[0] == 1
        _conservation(runtime)
        await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_auction_corrupt_item_locks_and_bid_escrow_reject_without_asset_changes(tmp_path, adapter):
    async def run():
        runtime, clock = await _setup(tmp_path, adapter)
        created = await _send(runtime, adapter, "seller", "lot", CREATE)
        assert created.code == "AUCTION_CREATED", created
        auction = created.data["auction_id"]
        assert (await _send(runtime, adapter, "bidder", "bid", f"竞价 {auction} 100")).ok
        with sqlite3.connect(runtime.settings.database_path) as connection:
            connection.row_factory = sqlite3.Row
            lock = dict(connection.execute("SELECT * FROM auction_item_locks WHERE auction_id=?", (auction,)).fetchone())
            bid = dict(connection.execute("SELECT * FROM auction_bids WHERE auction_id=?", (auction,)).fetchone())
            other_id = connection.execute("SELECT id FROM players WHERE platform_user_id='other'").fetchone()[0]
        corruptions = (
            ("UPDATE auction_item_locks SET quantity=2 WHERE auction_id=?", (auction,), "AUCTION_ITEM_LOCKED"),
            ("UPDATE auction_item_locks SET seller_player_id=? WHERE auction_id=?", (other_id, auction), "AUCTION_ITEM_LOCKED"),
            ("UPDATE auction_item_locks SET item_key='item.herb.blood_grass' WHERE auction_id=?", (auction,), "AUCTION_ITEM_LOCKED"),
            ("DELETE FROM auction_item_locks WHERE auction_id=?", (auction,), "AUCTION_ITEM_LOCKED"),
            ("UPDATE auction_bids SET bid_amount=101 WHERE auction_id=?", (auction,), "PERSISTENCE_ERROR"),
            ("UPDATE auction_bids SET bidder_player_id=? WHERE auction_id=?", (other_id, auction), "PERSISTENCE_ERROR"),
            ("UPDATE auction_bids SET status='outbid' WHERE auction_id=?", (auction,), "PERSISTENCE_ERROR"),
        )
        for statement, parameters, code in corruptions:
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(statement, parameters)
            clock.value = datetime.fromisoformat(created.data["created_at"])
            await _rejected(runtime, adapter, "other", "outbid", f"竞价 {auction} 105", code=code)
            clock.value = datetime.fromisoformat(created.data["ends_at"]) + timedelta(seconds=1)
            await _rejected(runtime, adapter, "seller", "settle", f"结算拍卖 {auction}", code=code)
            clock.value = datetime.fromisoformat(created.data["settlement_deadline"])
            await _rejected(runtime, adapter, "seller", "expire", f"结算拍卖 {auction}", code=code)
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute("DELETE FROM auction_item_locks WHERE auction_id=?", (auction,))
                connection.execute(
                    f"INSERT INTO auction_item_locks({','.join(lock)}) VALUES ({','.join('?' for _ in lock)})",
                    tuple(lock.values()),
                )
                connection.execute(
                    "UPDATE auction_bids SET bidder_player_id=?,bid_amount=?,status=? WHERE id=?",
                    (bid["bidder_player_id"], bid["bid_amount"], bid["status"], bid["id"]),
                )
            _conservation(runtime)
        await runtime.close()
        runtime = create_runtime(data_dir=tmp_path, adapters=(adapter,), clock=clock)
        expired = await _send(runtime, adapter, "seller", "expire", f"结算拍卖 {auction}")
        assert expired.code == "AUCTION_SETTLEMENT_EXPIRED", expired
        with sqlite3.connect(runtime.settings.database_path) as connection:
            assert connection.execute("SELECT COUNT(*) FROM auction_item_locks").fetchone()[0] == 0
            assert connection.execute("SELECT status FROM auction_bids WHERE auction_id=?", (auction,)).fetchone()[0] == "refunded"
        _conservation(runtime)
        await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_two_runtimes_replay_same_requests_and_serialize_competing_bids(tmp_path, adapter):
    async def run():
        first, clock = await _setup(tmp_path, adapter)
        second = create_runtime(data_dir=tmp_path, adapters=(adapter,), clock=clock)
        await second.initialize()
        created = await asyncio.gather(
            _send(first, adapter, "seller", "lot", CREATE),
            _send(second, adapter, "seller", "lot", CREATE),
        )
        assert all(result.code == "AUCTION_CREATED" for result in created), created
        assert sorted(result.data["idempotent_replay"] for result in created) == [False, True]
        auction = created[0].data["auction_id"]
        assert created[1].data["auction_id"] == auction
        bids = await asyncio.gather(
            _send(first, adapter, "bidder", "bid", f"竞价 {auction} 100"),
            _send(second, adapter, "bidder", "bid", f"竞价 {auction} 100"),
        )
        assert all(result.code == "AUCTION_BID_PLACED" for result in bids), bids
        assert sorted(result.data["idempotent_replay"] for result in bids) == [False, True]
        competing = await asyncio.gather(
            _send(first, adapter, "bidder", "bid-low", f"竞价 {auction} 105"),
            _send(second, adapter, "other", "bid-high", f"竞价 {auction} 120"),
        )
        assert competing[1].code == "AUCTION_BID_PLACED", competing
        assert competing[0].code in {"AUCTION_BID_PLACED", "AUCTION_BID_TOO_LOW"}, competing
        with sqlite3.connect(first.settings.database_path) as connection:
            assert connection.execute("SELECT COUNT(*) FROM auction_lots").fetchone()[0] == 1
            assert connection.execute("SELECT COUNT(*) FROM auction_item_locks").fetchone()[0] == 1
            assert connection.execute("SELECT current_bid FROM auction_lots").fetchone()[0] == 120
            assert connection.execute("SELECT COUNT(*) FROM auction_bids WHERE status='active'").fetchone()[0] == 1
            assert connection.execute("SELECT COUNT(*) FROM economy_ledger_entries WHERE operation_id='lot'").fetchone()[0] == 1
        _conservation(first)
        await first.close()
        await second.close()

        runtime = create_runtime(data_dir=tmp_path, adapters=(adapter,), clock=clock)
        await runtime.initialize()
        before = _database(runtime)
        _replay(competing[1], await _send(runtime, adapter, "other", "bid-high", f"竞价 {auction} 120"))
        assert _database(runtime) == before
        clock.value = datetime.fromisoformat(created[0].data["ends_at"]) + timedelta(seconds=1)
        settled = await _send(runtime, adapter, "seller", "settle", f"结算拍卖 {auction}")
        assert settled.code == "AUCTION_SETTLED", settled
        with sqlite3.connect(runtime.settings.database_path) as connection:
            balances = dict(connection.execute("SELECT platform_user_id, spirit_stones FROM players"))
            assert balances == {"seller": 220, "bidder": 500, "other": 680, "outsider": 0}
            inventory = dict(connection.execute("SELECT platform_user_id, inventory_json FROM players"))
            assert json.loads(inventory["seller"]) == {ITEM: 3}
            assert json.loads(inventory["other"]) == {ITEM: 1}
            assert connection.execute("SELECT COUNT(*) FROM auction_item_locks").fetchone()[0] == 0
        _conservation(runtime)
        await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_auction_offset_timestamps_keep_bid_and_settlement_boundaries(tmp_path, adapter):
    async def run():
        runtime, clock = await _setup(tmp_path, adapter)
        sold = await _send(runtime, adapter, "seller", "sold-lot", CREATE)
        expired = await _send(runtime, adapter, "seller", "expired-lot", CREATE)
        assert sold.code == expired.code == "AUCTION_CREATED"
        offset = timezone(timedelta(hours=8))
        with sqlite3.connect(runtime.settings.database_path) as connection:
            for result in (sold, expired):
                auction = result.data["auction_id"]
                raw = connection.execute("SELECT snapshot_json FROM auction_lots WHERE auction_id=?", (auction,)).fetchone()[0]
                snapshot = json.loads(raw)
                for key in ("created_at", "ends_at", "settlement_deadline"):
                    snapshot[key] = datetime.fromisoformat(snapshot[key]).astimezone(offset).isoformat()
                connection.execute(
                    "UPDATE auction_lots SET created_at=?,ends_at=?,settlement_deadline=?,snapshot_json=? WHERE auction_id=?",
                    (snapshot["created_at"], snapshot["ends_at"], snapshot["settlement_deadline"], json.dumps(snapshot), auction),
                )
        await runtime.close()

        runtime = create_runtime(data_dir=tmp_path, adapters=(adapter,), clock=clock)
        ends = datetime.fromisoformat(sold.data["ends_at"])
        deadline = datetime.fromisoformat(sold.data["settlement_deadline"])
        clock.value = ends - timedelta(seconds=1)
        for user, operation, result in (("bidder", "sold-bid", sold), ("other", "expired-bid", expired)):
            bid = await _send(runtime, adapter, user, operation, f"竞价 {result.data['auction_id']} 100")
            assert bid.code == "AUCTION_BID_PLACED", bid
            assert datetime.fromisoformat(bid.data["ends_at"]) == ends
            assert bid.data["ends_at"].endswith("+08:00")
        clock.value = ends
        await _rejected(
            runtime, adapter, "other", "too-late", f"竞价 {sold.data['auction_id']} 105",
            code="AUCTION_STATE_CONFLICT",
        )
        clock.value = deadline - timedelta(seconds=1)
        settled = await _send(runtime, adapter, "seller", "sold-settle", f"结算拍卖 {sold.data['auction_id']}")
        assert settled.code == "AUCTION_SETTLED", settled
        clock.value = deadline
        refunded = await _send(runtime, adapter, "outsider", "expired-settle", f"结算拍卖 {expired.data['auction_id']}")
        assert refunded.code == "AUCTION_SETTLEMENT_EXPIRED", refunded
        _conservation(runtime)
        with sqlite3.connect(runtime.settings.database_path) as connection:
            assert connection.execute("SELECT COUNT(*) FROM auction_item_locks").fetchone()[0] == 0
            assert dict(connection.execute("SELECT platform_user_id,spirit_stones FROM players")) == {
                "seller": 200, "bidder": 400, "other": 800, "outsider": 0,
            }
        await runtime.close()

    asyncio.run(run())
