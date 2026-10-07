from __future__ import annotations

import asyncio
import json
import shutil
import sqlite3
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest
from test_auction import MutableClock

from nonebot_plugin_xiuxian_3.adapters.onebot import normalize_event as normalize_onebot_event
from nonebot_plugin_xiuxian_3.adapters.qq import normalize_event as normalize_qq_event
from nonebot_plugin_xiuxian_3.runtime import create_runtime


ITEM_KEY = "item.material.cloud_iron"
RULE_PATH = Path("经济") / "拍卖.json"
ITEM_PATH = Path("道具") / "材料.json"


def _context(identity, operation, command):
    adapter, user = identity
    if adapter == "qq.official":
        from nonebot.adapters.qq.event import GroupMessageCreateEvent
        from nonebot.adapters.qq.models.qq import GroupMemberAuthor

        context = normalize_qq_event(GroupMessageCreateEvent(
            id=f"auction-{operation}", content=command, timestamp="2026-10-07T12:00:00+00:00",
            author=GroupMemberAuthor(id=user, bot=False, member_openid=user, member_role="member", username="道友"),
            group_id="auction-group", group_openid="auction-group",
        )).context
    else:
        from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message
        from nonebot.adapters.onebot.v11.event import Sender

        context = normalize_onebot_event(GroupMessageEvent(
            time=1_791_374_400, self_id=9001, post_type="message", sub_type="normal",
            user_id=int(user), message_type="group", message_id=9003,
            message=Message(command), original_message=Message(command), raw_message=command,
            font=0, sender=Sender(user_id=int(user), nickname="道友"), group_id=3001,
        )).context
    return replace(context, operation_id=operation)


async def _send(runtime, identity, operation, command):
    return await runtime.adapters.dispatch(identity[0], _context(identity, operation, command), command)


def _change_record(data_dir, relative_path, key, changes):
    path = data_dir / relative_path
    document = json.loads(path.read_text(encoding="utf-8"))
    record = next(record for record in document["records"] if record["key"] == key)
    if changes is None:
        document["records"].remove(record)
    else:
        record.update(changes)
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")


async def _setup(tmp_path, adapter, rules):
    data_dir = tmp_path / "data"
    shutil.copytree(Path(__file__).parents[1] / "data", data_dir)
    _change_record(data_dir, RULE_PATH, "auction.weekly", rules)
    _change_record(data_dir, Path("奖励") / "奖励.json", "reward.onboarding.seeking", {
        "entries": [
            {"kind": "currency", "currency_key": "currency.spirit_stone", "quantity": 300},
            {"kind": "item", "item_key": ITEM_KEY, "quantity": 6},
        ],
    })
    clock = MutableClock(datetime(2026, 10, 7, 12, tzinfo=timezone.utc))
    runtime = create_runtime(data_dir=data_dir, clock=clock)
    other = "onebot.v11" if adapter == "qq.official" else "qq.official"
    identities = ((adapter, "1001"), (other, "1002"), (adapter, "1003"))
    for identity in identities:
        assert (await _send(runtime, identity, "create:" + identity[1], "开始修仙")).ok
        assert (await _send(runtime, identity, "seek:" + identity[1], "寻仙问道")).ok
    return runtime, data_dir, clock, identities


def _database(runtime):
    with sqlite3.connect(runtime.settings.database_path) as connection:
        return tuple(connection.iterdump())


def _assets(runtime):
    with sqlite3.connect(runtime.settings.database_path) as connection:
        return {
            str(user): (int(balance), json.loads(inventory))
            for user, balance, inventory in connection.execute(
                "SELECT platform_user_id, spirit_stones, inventory_json FROM players ORDER BY id"
            )
        }


async def _replay(runtime, identity, operation, command, original):
    before = _database(runtime)
    result = await _send(runtime, identity, operation, command)
    assert result.code == original.code, result
    assert result.data["idempotent_replay"] is True
    assert {key: value for key, value in result.data.items() if key != "idempotent_replay"} == {
        key: value for key, value in original.data.items() if key != "idempotent_replay"
    }
    assert _database(runtime) == before
    assert ITEM_KEY not in result.message
    return result


async def _refused(runtime, identity, operation, command, code=None):
    before = _database(runtime)
    result = await _send(runtime, identity, operation, command)
    assert not result.ok, result
    if code is not None:
        assert result.code == code, result
    assert _database(runtime) == before
    return result


@pytest.mark.parametrize("adapter", ("qq.official", "onebot.v11"))
def test_auction_freezes_identity_rules_and_operations_across_content_changes(tmp_path, adapter):
    async def run():
        old_rules = {"slot_limit": 3, "duration_seconds": 120, "settlement_grace_seconds": 30,
                     "min_quantity": 1, "max_quantity": 3, "min_starting_bid": 100, "min_increment_bp": 500}
        runtime, data_dir, clock, (seller, bidder, rival) = await _setup(tmp_path, adapter, old_rules)
        initial_assets = _assets(runtime)
        created = await _send(runtime, seller, "publish", "发布拍卖 云铁 1 100")
        assert created.code == "AUCTION_CREATED", created
        auction_id = created.data["auction_id"]
        assert created.data["item_label"] == "云铁"
        assert datetime.fromisoformat(created.data["ends_at"]) == clock.value.replace(minute=2)
        bid = await _send(runtime, bidder, "bid-first", f"竞价 {auction_id} 100")
        assert bid.code == "AUCTION_BID_PLACED"
        raised = await _send(runtime, bidder, "bid-self", f"竞价 {auction_id} 110")
        assert raised.code == "AUCTION_BID_PLACED"
        assert _assets(runtime)[bidder[1]][0] == initial_assets[bidder[1]][0] - 110
        outbid = await _send(runtime, rival, "bid-rival", f"竞价 {auction_id} 120")
        assert outbid.code == "AUCTION_BID_PLACED"
        assert _assets(runtime)[bidder[1]][0] == initial_assets[bidder[1]][0]
        await runtime.close()

        new_rules = {"slot_limit": 3, "duration_seconds": 600, "settlement_grace_seconds": 90,
                     "min_quantity": 2, "max_quantity": 2, "min_starting_bid": 130, "min_increment_bp": 2000}
        _change_record(data_dir, ITEM_PATH, ITEM_KEY, {"name": "玄云精铁", "aliases": []})
        _change_record(data_dir, RULE_PATH, "auction.weekly", new_rules)
        runtime = create_runtime(data_dir=data_dir, clock=clock)
        await runtime.initialize()
        history = (
            (seller, "publish", "发布拍卖 云铁 1 100", created),
            (bidder, "bid-first", f"竞价 {auction_id} 100", bid),
            (bidder, "bid-self", f"竞价 {auction_id} 110", raised),
            (rival, "bid-rival", f"竞价 {auction_id} 120", outbid),
        )
        for identity, operation, command, result in history:
            await _replay(runtime, identity, operation, command, result)
        for command in (f"发布拍卖 {ITEM_KEY} 1 100", "发布拍卖 玄云精铁 1 100", "发布拍卖 云铁 2 100", "发布拍卖 云铁 1 101"):
            await _refused(runtime, seller, "publish", command, "OPERATION_CONFLICT")
        await _refused(runtime, bidder, "bid-first", f"竞价 {auction_id} 101", "OPERATION_CONFLICT")
        listed = await _send(runtime, seller, "list-renamed", "拍卖列表")
        assert listed.data["auctions"][0]["item_label"] == "云铁"
        assert ITEM_KEY not in listed.message
        for index, command in enumerate(("发布拍卖 云铁 2 150", "发布拍卖 玄云精铁 1 150", "发布拍卖 玄云精铁 3 150", "发布拍卖 玄云精铁 2 129")):
            await _refused(runtime, seller, f"invalid-new:{index}", command)
        new_created = await _send(runtime, seller, "publish-new", "发布拍卖 玄云精铁 2 150")
        assert new_created.code == "AUCTION_CREATED", new_created
        new_id = new_created.data["auction_id"]
        assert new_created.data["item_label"] == "玄云精铁"
        assert (datetime.fromisoformat(new_created.data["ends_at"]) - clock.value).total_seconds() == 600
        await _refused(runtime, bidder, "old-too-low", f"竞价 {auction_id} 125", "AUCTION_BID_TOO_LOW")
        old_raise = await _send(runtime, bidder, "old-frozen-increment", f"竞价 {auction_id} 126")
        assert old_raise.code == "AUCTION_BID_PLACED"
        assert _assets(runtime)[rival[1]][0] == initial_assets[rival[1]][0]
        new_bid = await _send(runtime, rival, "new-first", f"竞价 {new_id} 150")
        assert new_bid.code == "AUCTION_BID_PLACED"
        await _refused(runtime, rival, "new-too-low", f"竞价 {new_id} 179", "AUCTION_BID_TOO_LOW")
        new_raise = await _send(runtime, rival, "new-self", f"竞价 {new_id} 180")
        assert new_raise.code == "AUCTION_BID_PLACED"
        assert _assets(runtime)[rival[1]][0] == initial_assets[rival[1]][0] - 180
        history += (
            (bidder, "old-frozen-increment", f"竞价 {auction_id} 126", old_raise),
            (seller, "publish-new", "发布拍卖 玄云精铁 2 150", new_created),
            (rival, "new-first", f"竞价 {new_id} 150", new_bid),
            (rival, "new-self", f"竞价 {new_id} 180", new_raise),
        )
        with sqlite3.connect(runtime.settings.database_path) as connection:
            for key, expected in ((auction_id, old_rules), (new_id, new_rules)):
                snapshot = json.loads(connection.execute("SELECT snapshot_json FROM auction_lots WHERE auction_id=?", (key,)).fetchone()[0])
                assert {field: snapshot["rules"][field] for field in expected} == expected
                assert snapshot["item_label"] == ("云铁" if key == auction_id else "玄云精铁")
        await runtime.close()

        _change_record(data_dir, ITEM_PATH, ITEM_KEY, {"status": "locked"})
        runtime = create_runtime(data_dir=data_dir, clock=clock)
        await runtime.initialize()
        await _refused(runtime, seller, "publish-item-closed", "发布拍卖 玄云精铁 2 150", "MARKET_ITEM_FORBIDDEN")
        await _replay(runtime, seller, "publish-new", "发布拍卖 玄云精铁 2 150", new_created)
        await runtime.close()
        _change_record(data_dir, ITEM_PATH, ITEM_KEY, {"status": "active"})
        _change_record(data_dir, RULE_PATH, "auction.weekly", {"status": "locked"})
        runtime = create_runtime(data_dir=data_dir, clock=clock)
        await runtime.initialize()
        await _refused(runtime, seller, "publish-rules-closed", "发布拍卖 玄云精铁 2 150", "CONTENT_ERROR")
        await _replay(runtime, seller, "publish-new", "发布拍卖 玄云精铁 2 150", new_created)
        await runtime.close()
        _change_record(data_dir, ITEM_PATH, ITEM_KEY, {"status": "locked"})
        runtime = create_runtime(data_dir=data_dir, clock=clock)
        await runtime.initialize()
        for identity, operation, command, result in history:
            await _replay(runtime, identity, operation, command, result)
        await _refused(runtime, seller, "publish-closed", "发布拍卖 玄云精铁 2 150")
        listed = await _send(runtime, bidder, "list-closed", "拍卖列表")
        assert {lot["item_label"] for lot in listed.data["auctions"]} == {"云铁", "玄云精铁"}
        assert ITEM_KEY not in listed.message
        clock.advance(seconds=121)
        settled = await _send(runtime, seller, "settle-old", f"结算拍卖 {auction_id}")
        assert settled.code == "AUCTION_SETTLED", settled
        assert settled.data["current_bid"] == 126
        assert settled.data["item_label"] == "云铁"
        await _refused(runtime, seller, "settle-old", f"结算拍卖 {new_id}", "OPERATION_CONFLICT")
        await _refused(runtime, seller, "settle-new", f"结算拍卖 {new_id}", "AUCTION_STATE_CONFLICT")
        await runtime.close()
        runtime = create_runtime(data_dir=data_dir, clock=clock)
        await runtime.initialize()
        await _replay(runtime, seller, "settle-old", f"结算拍卖 {auction_id}", settled)
        clock.advance(seconds=480)
        new_settled = await _send(runtime, seller, "settle-new", f"结算拍卖 {new_id}")
        assert new_settled.code == "AUCTION_SETTLED", new_settled
        assert new_settled.data["current_bid"] == 180
        assert new_settled.data["item_label"] == "玄云精铁"
        await _replay(runtime, seller, "settle-new", f"结算拍卖 {new_id}", new_settled)
        final_assets = _assets(runtime)
        assert final_assets[seller[1]][0] == initial_assets[seller[1]][0] + 306
        assert final_assets[bidder[1]][0] == initial_assets[bidder[1]][0] - 126
        assert final_assets[rival[1]][0] == initial_assets[rival[1]][0] - 180
        assert final_assets[seller[1]][1][ITEM_KEY] == initial_assets[seller[1]][1][ITEM_KEY] - 3
        assert final_assets[bidder[1]][1][ITEM_KEY] == initial_assets[bidder[1]][1].get(ITEM_KEY, 0) + 1
        assert final_assets[rival[1]][1][ITEM_KEY] == initial_assets[rival[1]][1].get(ITEM_KEY, 0) + 2
        with sqlite3.connect(runtime.settings.database_path) as connection:
            assert connection.execute("SELECT COUNT(*) FROM auction_lots WHERE status='settled'").fetchone()[0] == 2
            assert connection.execute("SELECT COUNT(*) FROM auction_item_locks").fetchone()[0] == 0
            assert connection.execute("SELECT COUNT(*) FROM auction_bids WHERE status='won'").fetchone()[0] == 2
        await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("adapter", ("qq.official", "onebot.v11"))
def test_auction_frozen_end_and_grace_boundaries_release_or_transfer_once(tmp_path, adapter):
    async def run():
        rules = {"slot_limit": 3, "duration_seconds": 60, "settlement_grace_seconds": 20,
                 "min_quantity": 1, "max_quantity": 99, "min_starting_bid": 1, "min_increment_bp": 500}
        runtime, data_dir, clock, (seller, bidder, rival) = await _setup(tmp_path, adapter, rules)
        initial_assets = _assets(runtime)
        lots = []
        for name in ("unsold", "just-in-time", "expired"):
            result = await _send(runtime, seller, "publish:" + name, "发布拍卖 云铁 1 100")
            assert result.code == "AUCTION_CREATED", result
            lots.append(result.data["auction_id"])
        unsold_id, sold_id, expired_id = lots
        await _refused(runtime, seller, "publish-full", "发布拍卖 云铁 1 100", "AUCTION_SLOT_FULL")
        assert (await _send(runtime, bidder, "bid-timely", f"竞价 {sold_id} 100")).code == "AUCTION_BID_PLACED"
        assert (await _send(runtime, rival, "bid-expired", f"竞价 {expired_id} 100")).code == "AUCTION_BID_PLACED"
        clock.advance(seconds=59)
        await _refused(runtime, seller, "settle-unsold", f"结算拍卖 {unsold_id}", "AUCTION_STATE_CONFLICT")
        clock.advance(seconds=1)
        await _refused(runtime, rival, "bid-too-late", f"竞价 {sold_id} 105", "AUCTION_STATE_CONFLICT")
        unsold = await _send(runtime, seller, "settle-unsold", f"结算拍卖 {unsold_id}")
        assert unsold.code == "AUCTION_UNSOLD"
        assert _assets(runtime)[seller[1]] == initial_assets[seller[1]]
        replacement = await _send(runtime, seller, "publish-full", "发布拍卖 云铁 1 100")
        assert replacement.code == "AUCTION_CREATED"
        await runtime.close()

        _change_record(data_dir, ITEM_PATH, ITEM_KEY, {"name": "玄云精铁", "aliases": [], "status": "locked"})
        _change_record(data_dir, RULE_PATH, "auction.weekly", {
            "duration_seconds": 3600, "settlement_grace_seconds": 999, "min_increment_bp": 2000, "status": "locked",
        })
        runtime = create_runtime(data_dir=data_dir, clock=clock)
        await runtime.initialize()
        await _replay(runtime, seller, "settle-unsold", f"结算拍卖 {unsold_id}", unsold)
        clock.advance(seconds=19)
        settled = await _send(runtime, seller, "settle-timely", f"结算拍卖 {sold_id}")
        assert settled.code == "AUCTION_SETTLED", settled
        assert settled.data["item_label"] == "云铁"
        await runtime.close()
        _change_record(data_dir, ITEM_PATH, ITEM_KEY, None)
        _change_record(data_dir, RULE_PATH, "auction.weekly", None)
        runtime = create_runtime(data_dir=data_dir, clock=clock)
        await runtime.initialize()
        await _refused(runtime, seller, "publish-removed", "发布拍卖 云铁 1 100", "CONTENT_ERROR")
        listed = await _send(runtime, bidder, "list-removed", "拍卖列表")
        assert {lot["auction_id"] for lot in listed.data["auctions"]} == {expired_id, replacement.data["auction_id"]}
        assert {lot["item_label"] for lot in listed.data["auctions"]} == {"云铁"}
        assert ITEM_KEY not in listed.message
        clock.advance(seconds=1)
        expired = await _send(runtime, seller, "settle-expired", f"结算拍卖 {expired_id}")
        assert expired.code == "AUCTION_SETTLEMENT_EXPIRED", expired
        assert expired.data["status"] == "expired"
        assert expired.data["item_label"] == "云铁"
        assert _assets(runtime)[rival[1]] == initial_assets[rival[1]]
        clock.advance(seconds=40)
        replacement_unsold = await _send(runtime, seller, "settle-replacement", f"结算拍卖 {replacement.data['auction_id']}")
        assert replacement_unsold.code == "AUCTION_UNSOLD"
        await runtime.close()
        runtime = create_runtime(data_dir=data_dir, clock=clock)
        await runtime.initialize()
        settlements = (
            ("settle-unsold", unsold_id, unsold),
            ("settle-timely", sold_id, settled),
            ("settle-expired", expired_id, expired),
            ("settle-replacement", replacement.data["auction_id"], replacement_unsold),
        )
        for operation, auction_id, result in settlements:
            await _replay(runtime, seller, operation, f"结算拍卖 {auction_id}", result)
        final_assets = _assets(runtime)
        assert final_assets[seller[1]][0] == initial_assets[seller[1]][0] + 100
        assert final_assets[seller[1]][1][ITEM_KEY] == initial_assets[seller[1]][1][ITEM_KEY] - 1
        assert final_assets[bidder[1]][0] == initial_assets[bidder[1]][0] - 100
        assert final_assets[bidder[1]][1][ITEM_KEY] == initial_assets[bidder[1]][1].get(ITEM_KEY, 0) + 1
        with sqlite3.connect(runtime.settings.database_path) as connection:
            assert connection.execute("SELECT COUNT(*) FROM auction_lots").fetchone()[0] == 4
            assert connection.execute("SELECT COUNT(*) FROM auction_item_locks").fetchone()[0] == 0
            assert connection.execute("SELECT COUNT(*) FROM auction_bids WHERE status='active'").fetchone()[0] == 0
            assert connection.execute("SELECT COUNT(*) FROM economy_ledger_entries WHERE reason='auction.refund'").fetchone()[0] == 1
        await runtime.close()

    asyncio.run(run())
