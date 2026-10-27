"""Content and runtime contracts for the second wayfaring volume."""

from __future__ import annotations

import asyncio
import base64
import copy
import json
import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.config import XiuxianSettings
from nonebot_plugin_xiuxian_3.xiuxian.content import (
    ContentBundle,
    ContentError,
    bundled_content,
)
from nonebot_plugin_xiuxian_3.xiuxian.exploration.rules import battle_roll_bp
from nonebot_plugin_xiuxian_3.xiuxian.rewards.rules import reward_pool_outcomes
from nonebot_plugin_xiuxian_3.xiuxian.routine.wayfaring import (
    TIMETRACE_PASS_KEY,
    WAYFARING_PASS_KEY,
    parse_wayfaring_snapshot,
    wayfaring_definition,
)
from test_wayfaring import Ed25519PrivateKey, _signed_receipt
from test_wayfaring_content import (
    ADAPTERS,
    START,
    Clock,
    _change,
    _content,
    _send,
    _state,
)

PASS_FILE = "道历/行卷.json"
HERB_KEY = "item.herb.time_trace"
REP_LABEL = "道统服务处名望"


def _replace_record(
    content: ContentBundle, kind: str, record_key: str, **changes
) -> ContentBundle:
    records = dict(content._records)
    row = copy.deepcopy(dict(records[kind, record_key]))
    row.update(changes)
    records[kind, record_key] = row
    return replace(content, _records=records)


def _points(root: Path, *, points: int, daily: int, weekly: int) -> None:
    # Only the test content changes: every point still comes from a real
    # exploration settle.
    _change(
        root,
        PASS_FILE,
        TIMETRACE_PASS_KEY,
        lambda row: row["sources"]["exploration.settle"].update(points=points),
    )
    _change(
        root,
        PASS_FILE,
        TIMETRACE_PASS_KEY,
        lambda row: row.update(daily_point_cap=daily, weekly_point_cap=weekly),
    )


async def _gather(runtime, adapter: str, clock: Clock, tag: str) -> None:
    operation = next(
        candidate
        for candidate in (f"{tag}-{seed}" for seed in range(500))
        if battle_roll_bp(f"{candidate}:battle") >= 1000
    )
    started = await _send(runtime, adapter, operation, "开始探索 近郊采集")
    assert started.code == "EXPLORATION_STARTED", started
    clock.value = datetime.fromisoformat(started.data["ends_at"]) + timedelta(seconds=1)
    settled = await _send(runtime, adapter, f"{tag}-settle", "结算探索")
    assert settled.code == "EXPLORATION_SETTLED", settled


def _pass_row(runtime, pass_key: str) -> sqlite3.Row:
    with sqlite3.connect(runtime.settings.database_path) as db:
        db.row_factory = sqlite3.Row
        row = db.execute(
            "SELECT * FROM wayfaring_passes WHERE pass_key = ? ORDER BY id DESC LIMIT 1",
            (pass_key,),
        ).fetchone()
        assert row is not None
        return row


def test_timetrace_volume_contract_matches_its_content() -> None:
    bundle = ContentBundle.load(Path(__file__).parents[1] / "data")
    definition = wayfaring_definition(bundle, pass_key=TIMETRACE_PASS_KEY)
    assert definition.key == TIMETRACE_PASS_KEY
    assert definition.name == "时序行卷"
    assert (definition.cycle_days, definition.max_level, definition.points_per_level) == (
        21,
        24,
        60,
    )
    assert (definition.daily_point_cap, definition.weekly_point_cap) == (120, 500)
    assert definition.total_points == 1440
    assert set(definition.sources) == {
        "exploration.settle",
        "livelihood.harvest",
        "production.complete",
        "specials.settle_dispatch",
        "time_fort.settle",
    }
    assert definition.sources["specials.settle_dispatch"] == {
        "key": "specials.settle_dispatch",
        "name": "结算派遣",
        "points": 30,
    }
    assert len(definition.free_rewards) == len(definition.paid_rewards) == 24
    assert definition.local_reputation_key == "local.dao_service"
    assert definition.local_reputation_maximum == 1000
    assert definition.reward_labels[HERB_KEY] == "时痕草"
    assert definition.reward_labels["local_reputation"] == REP_LABEL
    assert definition.reward(1, "free") == {HERB_KEY: 1}
    assert definition.reward(24, "paid") == {HERB_KEY: 8, "item.mat.array_sand": 8}
    # The first volume keeps its own identity, numbers and sources.
    first = wayfaring_definition(bundle)
    assert first.key == WAYFARING_PASS_KEY
    assert (first.cycle_days, first.max_level, first.total_points) == (28, 30, 2400)
    assert len(first.sources) == 8
    # A frozen cycle snapshot restores without reading current content.
    restored = parse_wayfaring_snapshot(
        json.loads(json.dumps(definition.snapshot())), pass_key=TIMETRACE_PASS_KEY
    )
    assert restored == definition


@pytest.mark.parametrize(
    "change", ["missing", "unknown", "wrong_key", "extra_field", "bool_points"]
)
def test_timetrace_sources_only_accept_its_settled_producers(change: str) -> None:
    content = bundled_content()
    sources = copy.deepcopy(
        content.require("wayfaring_pass", TIMETRACE_PASS_KEY)["sources"]
    )
    if change == "missing":
        sources.pop("production.complete")
    elif change == "unknown":
        sources["bounty.claim"] = {
            "key": "bounty.claim",
            "name": "领取悬赏",
            "points": 25,
        }
    elif change == "wrong_key":
        sources["time_fort.settle"]["key"] = "time_fort.enter"
    elif change == "extra_field":
        sources["production.complete"]["extra"] = 1
    else:
        sources["production.complete"]["points"] = True
    with pytest.raises(ContentError):
        wayfaring_definition(
            _replace_record(
                content, "wayfaring_pass", TIMETRACE_PASS_KEY, sources=sources
            ),
            pass_key=TIMETRACE_PASS_KEY,
        )


def test_volumes_do_not_share_their_source_sets() -> None:
    content = bundled_content()
    timetrace_sources = copy.deepcopy(
        content.require("wayfaring_pass", TIMETRACE_PASS_KEY)["sources"]
    )
    with pytest.raises(ContentError):
        wayfaring_definition(
            _replace_record(
                content, "wayfaring_pass", WAYFARING_PASS_KEY, sources=timetrace_sources
            )
        )


def test_timetrace_rewards_close_over_existing_content_sources() -> None:
    bundle = bundled_content()
    definition = wayfaring_definition(bundle, pass_key=TIMETRACE_PASS_KEY)
    keys = {
        key
        for reward in (*definition.free_rewards, *definition.paid_rewards)
        for key in reward
    }
    items = {key for key in keys if key.startswith("item.")}
    assert items == {
        HERB_KEY,
        "item.herb.blood_grass",
        "item.herb.spirit_leaf",
        "item.mat.wood",
        "item.mat.array_sand",
        "item.ore.ironstone",
        "item.clue.recipe_basic",
        "item.token.spirit_tree_water",
    }
    free_items = {
        key for reward in definition.free_rewards for key in reward if key.startswith("item.")
    }
    for key in items:
        item = bundle.require("item", key)
        assert item["status"] in {"active", "open"}
        if key in free_items:
            effects = item["effects"]
            assert effects and all(
                effect["type"] == "crafting_material" for effect in effects
            )
    materials = {
        key
        for key in items
        if key.startswith(("item.herb.", "item.mat.", "item.ore."))
    }
    for key in materials:
        # No reward may mint an item that has no declared production source.
        sources = bundle.require("item", key)["gathering_sources"]
        assert sources, key
        for source in sources:
            mode = bundle.require("exploration_mode", source["mode_key"])
            assert mode["status"] in {"active", "open"}
            assert reward_pool_outcomes(source["reward_pool_key"], bundle)
    outcomes = reward_pool_outcomes("reward_pool.exploration.time_garden", bundle)
    assert any(HERB_KEY in reward for _, reward in outcomes)
    assert bundle.require("exploration_mode", "explore.time_garden")[
        "reward_pool_key"
    ] == "reward_pool.exploration.time_garden"


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_timetrace_points_respect_daily_and_weekly_caps(
    tmp_path: Path, adapter: str
) -> None:
    async def run() -> None:
        root, clock = _content(tmp_path), Clock()
        _points(root, points=250, daily=250, weekly=500)
        runtime = create_runtime(data_dir=root, clock=clock, adapters=(adapter,))
        try:
            assert (await _send(runtime, adapter, "create", "开始修仙")).ok
            started = await _send(runtime, adapter, "start", "开始行卷 时序")
            assert started.code == "WAYFARING_STARTED", started
            assert started.data["cycle_end"] == (
                START.date() + timedelta(days=20)
            ).isoformat()
            assert (await _send(runtime, adapter, "seek", "寻仙问道")).ok
            assert (await _send(runtime, adapter, "travel", "前往近郊")).ok

            await _gather(runtime, adapter, clock, f"{adapter}-day1-a")
            status = await _send(runtime, adapter, "status-1", "问道行卷")
            assert status.data["pass_key"] == TIMETRACE_PASS_KEY
            assert status.data["total_points"] == 250
            assert status.data["daily_points"] == 250
            assert status.data["current_level"] == 4

            await _gather(runtime, adapter, clock, f"{adapter}-day1-b")
            capped = await _send(runtime, adapter, "status-2", "问道行卷")
            assert capped.data["total_points"] == 250
            assert capped.data["daily_points"] == 250

            # A source outside this volume never scores.
            clock.value += timedelta(days=1)
            assert (await _send(runtime, adapter, "checkin", "道历问安")).ok
            untouched = await _send(runtime, adapter, "status-3", "问道行卷")
            assert untouched.data["total_points"] == 250

            await _gather(runtime, adapter, clock, f"{adapter}-day2")
            weekly = await _send(runtime, adapter, "status-4", "问道行卷")
            assert weekly.data["total_points"] == 500
            assert weekly.data["weekly_points"] == 500

            clock.value += timedelta(days=1)
            await _gather(runtime, adapter, clock, f"{adapter}-day3")
            blocked = await _send(runtime, adapter, "status-5", "问道行卷")
            assert blocked.data["total_points"] == 500
            assert blocked.data["daily_points"] == 0
            assert blocked.data["current_level"] == 8

            with sqlite3.connect(runtime.settings.database_path) as db:
                events = db.execute(
                    "SELECT points, payload_json FROM wayfaring_point_events "
                    "WHERE pass_id = ? ORDER BY id",
                    (_pass_row(runtime, TIMETRACE_PASS_KEY)["id"],),
                ).fetchall()
            assert [points for points, _ in events] == [250, 0, 250, 0]
            assert json.loads(events[1][1])["capped"] is True
            assert json.loads(events[3][1])["capped"] is True

            before = _state(runtime)
            replay = await _send(runtime, adapter, f"{adapter}-day3-settle", "结算探索")
            assert replay.data["idempotent_replay"] is True
            assert (await _send(runtime, adapter, "status-6", "问道行卷")).data == (
                blocked.data
            )
            assert _state(runtime) == before
        finally:
            await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_timetrace_free_and_paid_claims_are_idempotent(
    tmp_path: Path, adapter: str
) -> None:
    if Ed25519PrivateKey is None:
        pytest.skip("cryptography billing extra is not installed")

    async def run() -> None:
        root, clock = _content(tmp_path), Clock()
        clock.value = START - timedelta(days=29)
        private_key = Ed25519PrivateKey.generate()
        settings = XiuxianSettings(
            data_dir=root,
            billing_public_key=base64.urlsafe_b64encode(
                private_key.public_key().public_bytes_raw()
            ).decode("ascii").rstrip("="),
        )
        runtime = create_runtime(settings=settings, clock=clock, adapters=(adapter,))
        try:
            assert (await _send(runtime, adapter, "create", "开始修仙")).ok
            with sqlite3.connect(settings.database_path) as db:
                user_id = db.execute("SELECT platform_user_id FROM players").fetchone()[0]
            receipt = _signed_receipt(private_key, {
                "receipt_id": "timetrace-monthly",
                "subject": f"{adapter}:{user_id}",
                "contract_key": "dao_contract.monthly",
                "amount": 600,
                "currency": "spirit_stones",
                "issued_at": clock.value.isoformat(),
            })
            activated = await _send(runtime, adapter, "contract", f"激活道契 {receipt}")
            assert activated.code == "DAO_CONTRACT_ACTIVATED", activated
            clock.value = START
            started = await _send(runtime, adapter, "start", "开始行卷 时序")
            assert started.code == "WAYFARING_STARTED", started
            assert (await _send(runtime, adapter, "seek", "寻仙问道")).ok
            assert (await _send(runtime, adapter, "travel", "前往近郊")).ok
            for index in range(3):
                await _gather(runtime, adapter, clock, f"{adapter}-claim-{index}")
            status = await _send(runtime, adapter, "status", "问道行卷")
            assert status.data["current_level"] == 1

            free = await _send(runtime, adapter, "claim-free", "领取行卷 1")
            assert free.code == "WAYFARING_LEVEL_CLAIMED", free
            assert free.data["reward"] == {HERB_KEY: 1}
            assert "时痕草" in free.message
            paid = await _send(runtime, adapter, "claim-paid", "领取行卷 1 付费")
            assert paid.code == "WAYFARING_LEVEL_CLAIMED", paid
            assert paid.data["reward"] == {HERB_KEY: 2}
            locked = await _send(runtime, adapter, "claim-2", "领取行卷 2")
            assert locked.code == "WAYFARING_LEVEL_LOCKED", locked

            before = _state(runtime)
            replay = await _send(runtime, adapter, "claim-free", "领取行卷 1")
            assert replay.data["idempotent_replay"] is True
            assert replay.message == free.message
            assert _state(runtime) == before
            with sqlite3.connect(settings.database_path) as db:
                rows = db.execute(
                    "SELECT level, track FROM wayfaring_claims ORDER BY id"
                ).fetchall()
            assert rows == [(1, "free"), (1, "paid")]
        finally:
            await runtime.close()

    asyncio.run(run())


def test_second_volume_keeps_the_first_volume_queryable_after_restart(
    tmp_path: Path,
) -> None:
    adapter = "onebot.v11"

    async def run() -> None:
        root, clock = _content(tmp_path), Clock()
        runtime = create_runtime(data_dir=root, clock=clock, adapters=(adapter,))
        try:
            assert (await _send(runtime, adapter, "create", "开始修仙")).ok
            assert (await _send(runtime, adapter, "start", "开始行卷")).ok
            for day in range(4):
                clock.value = START + timedelta(days=day)
                assert (await _send(runtime, adapter, f"checkin-{day}", "道历问安")).ok
            claimed = await _send(runtime, adapter, "claim-old", "领取行卷 1")
            assert claimed.code == "WAYFARING_LEVEL_CLAIMED", claimed
            refused = await _send(runtime, adapter, "start-early", "开始行卷 时序")
            assert refused.code == "WAYFARING_ALREADY_STARTED", refused
            clock.value = START + timedelta(days=28)
            assert (await _send(runtime, adapter, "closed", "问道行卷")).data[
                "status"
            ] == "closed"
            switched = await _send(runtime, adapter, "start-new", "开始行卷 时序")
            assert switched.code == "WAYFARING_STARTED", switched
            assert (await _send(runtime, adapter, "checkin-new", "道历问安")).ok
            status = await _send(runtime, adapter, "status-new", "问道行卷")
            assert status.data["pass_key"] == TIMETRACE_PASS_KEY
            assert status.data["total_points"] == 0
            assert _pass_row(runtime, WAYFARING_PASS_KEY)["claimed_free_json"] == "[1]"
        finally:
            await runtime.close()

        runtime = create_runtime(data_dir=root, clock=clock, adapters=(adapter,))
        try:
            latest = await _send(runtime, adapter, "status-latest", "问道行卷")
            assert latest.data["pass_key"] == TIMETRACE_PASS_KEY
            assert latest.data["status"] == "active"
            old = await _send(runtime, adapter, "status-old", "问道行卷 问道")
            assert old.data["pass_key"] == WAYFARING_PASS_KEY
            assert old.data["status"] == "closed"
            explicit = await _send(runtime, adapter, "status-new", "问道行卷 时序")
            assert explicit.data["pass_key"] == TIMETRACE_PASS_KEY
            locked = await _send(runtime, adapter, "claim-new", "领取行卷 1")
            assert locked.code == "WAYFARING_LEVEL_LOCKED", locked
        finally:
            await runtime.close()

    asyncio.run(run())


def test_unknown_volume_arguments_are_rejected(tmp_path: Path) -> None:
    adapter = "onebot.v11"

    async def run() -> None:
        runtime = create_runtime(data_dir=_content(tmp_path), clock=Clock(), adapters=(adapter,))
        try:
            assert (await _send(runtime, adapter, "create", "开始修仙")).ok
            for index, command in enumerate(
                ("开始行卷 未知卷", "问道行卷 未知卷", "开始行卷 时序 额外")
            ):
                result = await _send(runtime, adapter, f"bad-{index}", command)
                assert result.code == "INVALID_WAYFARING_COMMAND", (command, result)
            assert (await _send(runtime, adapter, "status", "问道行卷")).code == (
                "WAYFARING_NOT_STARTED"
            )
        finally:
            await runtime.close()

    asyncio.run(run())
