from __future__ import annotations

import asyncio
import copy
import json
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest

from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError
from nonebot_plugin_xiuxian_3.xiuxian.livelihood.rules import residence_definition
from test_data_completion import Flow


DATA = Path(__file__).parents[1] / "data"
RESIDENCES = (
    ("residence.town_room", 10),
    ("residence.courtyard", 20),
    ("residence.herb_court", 24),
)
HERB = "item.herb.blood_grass"
LEAF = "item.herb.spirit_leaf"
DISTINCT_ITEMS = (
    "item.herb.blood_grass",
    "item.herb.spirit_leaf",
    "item.herb.time_trace",
    "item.tool.mining_pickaxe",
    "item.tool.mining_pickaxe_t2",
    "item.tool.basic_furnace",
    "item.tool.basic_hammer",
    "item.weapon.wood_sword",
    "item.weapon.cloud_sword",
    "item.weapon.ironwood_spear",
    "item.weapon.wingwood_dagger",
)


def _seed_inventory(flow: Flow, items: dict[str, int]) -> None:
    with flow.runtime.repository._connect() as db:
        db.execute(
            "UPDATE players SET inventory_json=? WHERE platform_user_id = 'player'",
            (json.dumps(items, ensure_ascii=False),),
        )


def _inventory(flow: Flow) -> dict[str, int]:
    with flow.runtime.repository._connect() as db:
        raw = db.execute(
            "SELECT inventory_json FROM players WHERE platform_user_id = 'player'"
        ).fetchone()[0]
    return json.loads(raw)


def _storage_rows(flow: Flow) -> list[tuple[str, int]]:
    with sqlite3.connect(flow.runtime.settings.database_path) as db:
        return [
            (row[0], row[1])
            for row in db.execute(
                "SELECT item_key, quantity FROM residence_storage ORDER BY item_key"
            ).fetchall()
        ]


def _assert_player_copy(*messages: str) -> None:
    for message in messages:
        for marker in ("item.", "storage", "snapshot", "player_id", "residence_storage"):
            assert marker not in message


def test_storage_content_contract_is_closed() -> None:
    bundle = ContentBundle.load(DATA)
    for key, slots in RESIDENCES:
        definition = residence_definition(key, bundle)
        assert definition.storage_slots == slots

    records = dict(bundle._records)
    record = copy.deepcopy(records[("livelihood", "residence.town_room")])
    record["capacity"]["storage_slots"] = -1
    records[("livelihood", "residence.town_room")] = record
    broken = replace(bundle, _records=records)
    with pytest.raises(ContentError, match="storage slot count"):
        residence_definition("residence.town_room", broken)


def test_storage_deposit_merges_and_withdraw_keeps_slots(tmp_path) -> None:
    async def run() -> None:
        flow = Flow(tmp_path)
        try:
            await flow.enter("体修")
            assert (await flow.send("租住居所")).code == "RESIDENCE_LEASED"
            _seed_inventory(flow, {HERB: 10, LEAF: 3})

            first = await flow.send("存入居所 止血草 4", "store-1")
            assert first.code == "STORAGE_DEPOSITED"
            assert first.data["quantity"] == 4
            assert first.data["stored_quantity"] == 4
            assert first.data["used_slots"] == 1
            assert first.data["capacity"] == 10
            assert _inventory(flow) == {HERB: 6, LEAF: 3}
            assert _storage_rows(flow) == [(HERB, 4)]
            _assert_player_copy(first.message)
            assert "止血草" in first.message

            merged = await flow.send("存入居所 止血草 3", "store-2")
            assert merged.code == "STORAGE_DEPOSITED"
            assert merged.data["stored_quantity"] == 7
            assert merged.data["used_slots"] == 1
            assert _inventory(flow) == {HERB: 3, LEAF: 3}

            second_slot = await flow.send("存入居所 灵叶")
            assert second_slot.code == "STORAGE_DEPOSITED"
            assert second_slot.data["used_slots"] == 2
            assert _inventory(flow) == {HERB: 3, LEAF: 2}

            profile = await flow.send("我的物资箱")
            assert profile.code == "STORAGE_PROFILE"
            assert profile.data["used_slots"] == 2
            assert profile.data["capacity"] == 10
            assert "止血草 ×7" in profile.message
            assert "灵叶 ×1" in profile.message
            _assert_player_copy(profile.message)

            withdrawn = await flow.send("取回居所 止血草 2", "take-1")
            assert withdrawn.code == "STORAGE_WITHDRAWN"
            assert withdrawn.data["stored_quantity"] == 5
            assert withdrawn.data["used_slots"] == 2
            assert _inventory(flow) == {HERB: 5, LEAF: 2}

            last = await flow.send("取回居所 灵叶 1", "take-2")
            assert last.code == "STORAGE_WITHDRAWN"
            assert last.data["used_slots"] == 1
            assert last.data["stored_quantity"] == 0
            assert _storage_rows(flow) == [(HERB, 5)]

            residence = await flow.send("我的居所")
            assert residence.data["storage_capacity"] == 10
            assert residence.data["storage_used_slots"] == 1
            _assert_player_copy(residence.message)
        finally:
            await flow.runtime.close()

    asyncio.run(run())


def test_storage_full_blocks_new_items_until_a_slot_frees(tmp_path) -> None:
    async def run() -> None:
        flow = Flow(tmp_path)
        try:
            await flow.enter("体修")
            assert (await flow.send("租住居所")).code == "RESIDENCE_LEASED"
            _seed_inventory(flow, {key: 1 for key in DISTINCT_ITEMS})

            for index, key in enumerate(DISTINCT_ITEMS[:10], start=1):
                stored = await flow.send(f"存入居所 {key} 1", f"fill-{index}")
                assert stored.code == "STORAGE_DEPOSITED", (key, stored)
                assert stored.data["used_slots"] == index

            before = flow.dump()
            overflow = await flow.send(f"存入居所 {DISTINCT_ITEMS[10]} 1", "fill-11", ok=False)
            assert overflow.code == "STORAGE_FULL"
            assert flow.dump() == before
            assert _inventory(flow)[DISTINCT_ITEMS[10]] == 1

            freed = await flow.send(f"取回居所 {DISTINCT_ITEMS[0]} 1", "free-1")
            assert freed.code == "STORAGE_WITHDRAWN"
            assert freed.data["used_slots"] == 9

            refilled = await flow.send(f"存入居所 {DISTINCT_ITEMS[10]} 1", "fill-11-retry")
            assert refilled.code == "STORAGE_DEPOSITED"
            assert refilled.data["used_slots"] == 10
            assert _inventory(flow).get(DISTINCT_ITEMS[10], 0) == 0
        finally:
            await flow.runtime.close()

    asyncio.run(run())


def test_storage_requires_active_residence_but_withdrawal_still_works(tmp_path) -> None:
    async def run() -> None:
        flow = Flow(tmp_path)
        try:
            await flow.enter("体修")
            assert (await flow.send("租住居所")).code == "RESIDENCE_LEASED"
            _seed_inventory(flow, {HERB: 6})
            assert (await flow.send("存入居所 止血草 4", "store-expiry")).code == "STORAGE_DEPOSITED"

            with flow.runtime.repository._connect() as db:
                db.execute("UPDATE residences SET status = 'expired'")

            before = flow.dump()
            rejected = await flow.send("存入居所 止血草 1", "store-expired", ok=False)
            assert rejected.code == "RESIDENCE_REQUIRED"
            assert flow.dump() == before

            withdrawn = await flow.send("取回居所 止血草 2", "take-expired")
            assert withdrawn.code == "STORAGE_WITHDRAWN"
            assert withdrawn.data["stored_quantity"] == 2
            assert _inventory(flow) == {HERB: 4}

            profile = await flow.send("我的物资箱")
            assert profile.data["capacity"] == 0
            assert profile.data["used_slots"] == 1
            _assert_player_copy(profile.message)
        finally:
            await flow.runtime.close()

    asyncio.run(run())


def test_storage_survives_restart_and_replays_once(tmp_path) -> None:
    async def run() -> None:
        flow = Flow(tmp_path)
        try:
            await flow.enter("体修")
            assert (await flow.send("租住居所")).code == "RESIDENCE_LEASED"
            _seed_inventory(flow, {HERB: 8})
            stored = await flow.send("存入居所 止血草 5", "store-restart")
            assert stored.code == "STORAGE_DEPOSITED"
        finally:
            await flow.runtime.close()

        flow.runtime = create_runtime(
            data_dir=flow.root, clock=lambda: flow.now, adapters=("onebot.v11",)
        )
        try:
            profile = await flow.send("我的物资箱")
            assert profile.data["items"] == [
                {"item_key": HERB, "label": "止血草", "quantity": 5}
            ]

            after_restart = flow.dump()
            replay = await flow.send("存入居所 止血草 5", "store-restart")
            assert replay.code == "STORAGE_DEPOSITED"
            assert replay.data["idempotent_replay"] is True
            assert replay.data["stored_quantity"] == 5
            assert flow.dump() == after_restart
            assert _inventory(flow) == {HERB: 3}

            conflict = await flow.send("存入居所 止血草 1", "store-restart", ok=False)
            assert conflict.code == "OPERATION_CONFLICT"
            assert flow.dump() == after_restart

            withdrawn = await flow.send("取回居所 止血草 5", "take-restart")
            assert withdrawn.code == "STORAGE_WITHDRAWN"
            assert _inventory(flow) == {HERB: 8}
            assert _storage_rows(flow) == []
        finally:
            await flow.runtime.close()

    asyncio.run(run())


def test_storage_rejects_bad_inputs_without_writing(tmp_path) -> None:
    async def run() -> None:
        flow = Flow(tmp_path)
        try:
            await flow.enter("体修")
            assert (await flow.send("租住居所")).code == "RESIDENCE_LEASED"
            _seed_inventory(flow, {HERB: 2})

            before = flow.dump()
            unknown = await flow.send("存入居所 不存在之物 1", "bad-unknown", ok=False)
            assert unknown.code == "ITEM_NOT_FOUND"
            assert flow.dump() == before

            zero = await flow.send("存入居所 止血草 0", "bad-zero", ok=False)
            assert zero.code == "INVALID_STORAGE_COMMAND"
            non_numeric = await flow.send("存入居所 止血草 许多", "bad-text", ok=False)
            assert non_numeric.code == "INVALID_STORAGE_COMMAND"
            empty = await flow.send("存入居所", "bad-empty", ok=False)
            assert empty.code == "INVALID_STORAGE_COMMAND"
            assert flow.dump() == before

            too_many = await flow.send("存入居所 止血草 3", "bad-stock", ok=False)
            assert too_many.code == "RESOURCE_INSUFFICIENT"
            assert flow.dump() == before

            missing = await flow.send("取回居所 灵叶 1", "bad-missing", ok=False)
            assert missing.code == "STORAGE_ITEM_NOT_FOUND"
            assert flow.dump() == before

            assert (await flow.send("存入居所 止血草 2", "good-store")).code == "STORAGE_DEPOSITED"
            before_overdraw = flow.dump()
            overdraw = await flow.send("取回居所 止血草 3", "bad-overdraw", ok=False)
            assert overdraw.code == "STORAGE_QUANTITY_INSUFFICIENT"
            assert flow.dump() == before_overdraw
            assert _inventory(flow).get(HERB, 0) == 0
        finally:
            await flow.runtime.close()

    asyncio.run(run())


def test_storage_corrupt_row_fails_closed_and_keeps_rows(tmp_path) -> None:
    async def run() -> None:
        flow = Flow(tmp_path)
        try:
            await flow.enter("体修")
            assert (await flow.send("租住居所")).code == "RESIDENCE_LEASED"
            _seed_inventory(flow, {HERB: 5})
            assert (await flow.send("存入居所 止血草 5", "store-corrupt")).code == "STORAGE_DEPOSITED"

            with sqlite3.connect(flow.runtime.settings.database_path) as db:
                db.execute("UPDATE residence_storage SET quantity = 'bad'")

            before = flow.dump()
            rejected = await flow.send("我的物资箱", ok=False)
            assert rejected.code == "PERSISTENCE_ERROR"
            assert flow.dump() == before
            assert _storage_rows(flow) == [(HERB, "bad")]
        finally:
            await flow.runtime.close()

    asyncio.run(run())
