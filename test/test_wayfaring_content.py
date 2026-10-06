from __future__ import annotations

import asyncio
import base64
import json
import shutil
import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from nonebot_plugin_xiuxian_3.adapters.onebot import normalize_event
from nonebot_plugin_xiuxian_3.adapters.qq import normalize_event as normalize_qq_event
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.config import XiuxianSettings
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError
from nonebot_plugin_xiuxian_3.xiuxian.routine.wayfaring import (
    wayfaring_definition,
    wayfaring_week_start,
)
from test_adapter_simulation import _onebot_group_event, _qq_group_event
from test_wayfaring import Ed25519PrivateKey, _signed_receipt


ADAPTERS = ("qq.official", "onebot.v11")
PASS_KEY = "pass.wayfaring"
PASS_FILE = "道历/行卷.json"
HERB_KEY = "item.herb.blood_grass"
START = datetime(2026, 9, 21, 12, tzinfo=timezone.utc)


class Clock:
    def __init__(self) -> None:
        self.value = START

    def __call__(self) -> datetime:
        return self.value


def _content(tmp_path: Path) -> Path:
    root = tmp_path / "content"
    shutil.copytree(Path(__file__).parents[1] / "data", root)
    return root


def _change(root: Path, filename: str, key: str, change) -> None:
    path = root / filename
    document = json.loads(path.read_text(encoding="utf-8"))
    change(next(row for row in document["records"] if row["key"] == key))
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")


def _daily_points(root: Path, points: int) -> None:
    # Only the test content changes: every point still comes from a real check-in.
    _change(
        root,
        PASS_FILE,
        PASS_KEY,
        lambda row: row["sources"]["routine.checkin.daily"].update(points=points),
    )


async def _send(runtime, adapter: str, operation: str, command: str):
    if adapter == "qq.official":
        message = normalize_qq_event(_qq_group_event(command))
    else:
        message = normalize_event(_onebot_group_event(command))
    return await runtime.adapters.dispatch(
        adapter,
        replace(message.context, operation_id=operation),
        message.text,
    )


def _state(runtime) -> dict[str, list]:
    with sqlite3.connect(runtime.settings.database_path) as db:
        return {
            table: db.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
            for table in (
                "players",
                "operations",
                "wayfaring_passes",
                "wayfaring_point_events",
                "wayfaring_claims",
                "honor_titles",
                "player_reputations",
            )
        }


def _snapshot(runtime, *, latest: bool = True) -> dict:
    order = "DESC" if latest else "ASC"
    with sqlite3.connect(runtime.settings.database_path) as db:
        return json.loads(
            db.execute(
                f"SELECT snapshot_json FROM wayfaring_passes ORDER BY id {order} LIMIT 1"
            ).fetchone()[0]
        )


def test_default_wayfaring_maximum_is_reachable_for_every_start_weekday() -> None:
    definition = wayfaring_definition()
    assert definition.cycle_days == 28
    assert definition.max_level == 30
    assert definition.points_per_level == 80
    assert definition.daily_point_cap == 100
    assert definition.weekly_point_cap == 600
    for weekday in range(7):
        weekly: dict[object, int] = {}
        for day in range(definition.cycle_days):
            current = START.date() + timedelta(days=weekday + day)
            week = wayfaring_week_start(current)
            weekly[week] = weekly.get(week, 0) + min(
                definition.daily_point_cap,
                definition.weekly_point_cap - weekly.get(week, 0),
            )
        assert sum(weekly.values()) >= definition.total_points, weekday


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_real_checkins_reach_last_level_and_expired_completed_pass_cannot_claim(
    tmp_path: Path, adapter: str
) -> None:
    async def run() -> None:
        root, clock = _content(tmp_path), Clock()
        _daily_points(root, 100)
        runtime = create_runtime(data_dir=root, clock=clock, adapters=(adapter,))
        try:
            assert (await _send(runtime, adapter, "create", "开始修仙")).ok
            started = await _send(runtime, adapter, "start", "开始行卷")
            assert started.code == "WAYFARING_STARTED", started
            for day in range(28):
                clock.value = START + timedelta(days=day)
                checked = await _send(runtime, adapter, f"checkin-{day}", "道历问安")
                assert checked.ok, checked
                status = await _send(runtime, adapter, f"status-{day}", "问道行卷")
                assert status.code == "WAYFARING_STATUS", status
                assert status.data["daily_points"] <= 100
                assert status.data["weekly_points"] <= 600
            assert status.data["total_points"] == 2400
            assert status.data["current_level"] == 30
            assert status.data["status"] == "completed"
            claimed = await _send(runtime, adapter, "claim-30", "领取行卷 30")
            assert claimed.code == "WAYFARING_LEVEL_CLAIMED", claimed
            assert claimed.data["reward"] == {"title.wayfaring.wayfarer": 1}
            with sqlite3.connect(runtime.settings.database_path) as db:
                assert (
                    db.execute(
                        "SELECT COUNT(*) FROM operations WHERE operation_name='routine.checkin.daily'"
                    ).fetchone()[0]
                    == 28
                )
                assert (
                    db.execute(
                        "SELECT COUNT(*) FROM wayfaring_point_events e "
                        "LEFT JOIN operations o ON o.operation_id=e.source_operation_id "
                        "WHERE o.operation_name IS NULL OR o.operation_name!='routine.checkin.daily'"
                    ).fetchone()[0]
                    == 0
                )
                assert (
                    db.execute(
                        "SELECT COUNT(*) FROM honor_titles WHERE title_key='title.wayfaring.wayfarer'"
                    ).fetchone()[0]
                    == 1
                )
            clock.value = START + timedelta(days=28)
            before = _state(runtime)
            rejected = await _send(runtime, adapter, "claim-29", "领取行卷 29")
            assert rejected.code == "WAYFARING_LEVEL_LOCKED"
            assert _state(runtime) == before
            closed = await _send(runtime, adapter, "closed", "问道行卷")
            assert closed.data["status"] == "closed"
            before = _state(runtime)
            rejected = await _send(runtime, adapter, "claim-29", "领取行卷 29")
            assert rejected.code == "WAYFARING_LEVEL_LOCKED"
            replay = await _send(runtime, adapter, "claim-30", "领取行卷 30")
            assert replay.data["idempotent_replay"] is True
            assert replay.message == claimed.message
            assert _state(runtime) == before
        finally:
            await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_expired_monthly_contract_blocks_new_paid_claim_but_not_replay(
    tmp_path: Path, adapter: str
) -> None:
    if Ed25519PrivateKey is None:
        pytest.skip("cryptography billing extra is not installed")

    async def run() -> None:
        root, clock = _content(tmp_path), Clock()
        _daily_points(root, 100)
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
                "receipt_id": "wayfaring-monthly-expiry",
                "subject": f"{adapter}:{user_id}",
                "contract_key": "dao_contract.monthly",
                "amount": 600,
                "currency": "spirit_stones",
                "issued_at": clock.value.isoformat(),
            })
            activated = await _send(runtime, adapter, "contract", f"激活道契 {receipt}")
            assert activated.code == "DAO_CONTRACT_ACTIVATED", activated
            clock.value = START
            assert (await _send(runtime, adapter, "start", "开始行卷")).ok
            assert (await _send(runtime, adapter, "checkin-first", "道历问安")).ok
            claimed = await _send(runtime, adapter, "paid-first", "领取行卷 1 付费")
            assert claimed.code == "WAYFARING_LEVEL_CLAIMED", claimed
        finally:
            await runtime.close()

        clock.value += timedelta(days=1)
        runtime = create_runtime(settings=settings, clock=clock, adapters=(adapter,))
        try:
            assert (await _send(runtime, adapter, "checkin-second", "道历问安")).ok
            status = await _send(runtime, adapter, "status", "问道行卷")
            assert status.data["current_level"] == 2
            assert status.data["status"] == "active"
            before = _state(runtime)
            refused = await _send(runtime, adapter, "paid-second", "领取行卷 2 付费")
            assert refused.code == "WAYFARING_PAID_LOCKED", refused
            replay = await _send(runtime, adapter, "paid-first", "领取行卷 1 付费")
            assert replay.data["idempotent_replay"] is True
            assert replay.message == claimed.message
            assert _state(runtime) == before
        finally:
            await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_pass_freezes_rules_rewards_labels_and_reputation_cap_across_restart(
    tmp_path: Path, adapter: str
) -> None:
    async def run() -> None:
        root, clock = _content(tmp_path), Clock()
        _daily_points(root, 100)
        _change(
            root,
            PASS_FILE,
            PASS_KEY,
            lambda row: row["free_rewards"].__setitem__(
                0, {HERB_KEY: 7, "local_reputation": 9}
            ),
        )
        _change(
            root,
            "地图/地点.json",
            "xuantian.new_town",
            lambda row: row.update(local_reputation_maximum=3),
        )
        runtime = create_runtime(data_dir=root, clock=clock, adapters=(adapter,))
        try:
            assert (await _send(runtime, adapter, "create", "开始修仙")).ok
            started = await _send(runtime, adapter, "start", "开始行卷")
            assert started.ok, started
            assert (await _send(runtime, adapter, "checkin-first", "道历问安")).ok
            frozen = _snapshot(runtime)
        finally:
            await runtime.close()

        def changed_pass(row: dict) -> None:
            row.update(status="closed", name="云游新卷", points_per_level=40)
            row["sources"]["routine.checkin.daily"]["points"] = 60
            row["free_rewards"][0] = {HERB_KEY: 99, "local_reputation": 99}

        _change(root, PASS_FILE, PASS_KEY, changed_pass)
        _change(
            root,
            "道具/材料.json",
            HERB_KEY,
            lambda row: row.update(name="新名灵草", status="closed"),
        )
        _change(
            root,
            "地图/地点.json",
            "xuantian.new_town",
            lambda row: row.update(local_reputation_maximum=1000),
        )
        clock.value += timedelta(days=1)
        runtime = create_runtime(data_dir=root, clock=clock, adapters=(adapter,))
        try:
            assert (await _send(runtime, adapter, "checkin-second", "道历问安")).ok
            status = await _send(runtime, adapter, "status-frozen", "问道行卷")
            assert status.data["total_points"] == 200
            assert status.data["current_level"] == 2
            assert _snapshot(runtime) == frozen
            claimed = await _send(runtime, adapter, "claim-first", "领取行卷 1")
            assert claimed.code == "WAYFARING_LEVEL_CLAIMED", claimed
            assert claimed.data["reward"] == {HERB_KEY: 7, "local_reputation": 3}
            assert "止血草" in claimed.message and "新名灵草" not in claimed.message
            assert (
                await _send(runtime, adapter, "start", "开始行卷")
            ).message == started.message
            clock.value = START + timedelta(days=28)
            assert (await _send(runtime, adapter, "status-expired", "问道行卷")).data[
                "status"
            ] == "closed"
            before = _state(runtime)
            rejected = await _send(runtime, adapter, "start-next", "开始行卷")
            assert rejected.code == "CONTENT_UNAVAILABLE", rejected
            assert (
                await _send(runtime, adapter, "claim-first", "领取行卷 1")
            ).message == claimed.message
            assert _state(runtime) == before
        finally:
            await runtime.close()

        _change(root, PASS_FILE, PASS_KEY, lambda row: row.update(status="active"))
        _change(
            root, "道具/材料.json", HERB_KEY, lambda row: row.update(status="active")
        )
        runtime = create_runtime(data_dir=root, clock=clock, adapters=(adapter,))
        try:
            next_pass = await _send(runtime, adapter, "start-next", "开始行卷")
            assert next_pass.code == "WAYFARING_STARTED", next_pass
            assert _snapshot(runtime, latest=False) == frozen
            assert _snapshot(runtime)["points_per_level"] == 40
            assert (await _send(runtime, adapter, "checkin-next", "道历问安")).ok
            status = await _send(runtime, adapter, "status-next", "问道行卷")
            assert status.data["total_points"] == 60
            assert status.data["current_level"] == 1
            latest = await _send(runtime, adapter, "claim-next", "领取行卷 1")
            assert latest.data["reward"] == {HERB_KEY: 99, "local_reputation": 99}
            assert "新名灵草" in latest.message
            assert (
                await _send(runtime, adapter, "claim-first", "领取行卷 1")
            ).message == claimed.message
        finally:
            await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_start_and_claim_failures_are_atomic_and_same_operation_can_retry(
    tmp_path: Path, adapter: str
) -> None:
    async def run() -> None:
        root = _content(tmp_path)
        _daily_points(root, 100)
        runtime = create_runtime(data_dir=root, clock=Clock(), adapters=(adapter,))
        try:
            assert (await _send(runtime, adapter, "create", "开始修仙")).ok
            with sqlite3.connect(runtime.settings.database_path) as db:
                db.execute(
                    "CREATE TRIGGER fail_wayfaring BEFORE INSERT ON operations "
                    "WHEN NEW.operation_name LIKE 'pass.wayfaring.%' "
                    "BEGIN SELECT RAISE(ABORT, 'injected failure'); END"
                )
            before = _state(runtime)
            failed = await _send(runtime, adapter, "start", "开始行卷")
            assert failed.code == "PERSISTENCE_ERROR"
            assert _state(runtime) == before
            with sqlite3.connect(runtime.settings.database_path) as db:
                db.execute("DROP TRIGGER fail_wayfaring")
            started = await asyncio.gather(
                _send(runtime, adapter, "start", "开始行卷"),
                _send(runtime, adapter, "start", "开始行卷"),
            )
            assert all(item.ok for item in started), started
            assert sorted(item.data["idempotent_replay"] for item in started) == [
                False,
                True,
            ]
            assert (await _send(runtime, adapter, "checkin", "道历问安")).ok
            before = _state(runtime)
            with sqlite3.connect(runtime.settings.database_path) as db:
                db.execute(
                    "CREATE TRIGGER fail_wayfaring BEFORE INSERT ON operations "
                    "WHEN NEW.operation_name='pass.wayfaring.claim' "
                    "BEGIN SELECT RAISE(ABORT, 'injected failure'); END"
                )
            failed = await _send(runtime, adapter, "claim", "领取行卷 1")
            assert failed.code == "PERSISTENCE_ERROR"
            assert _state(runtime) == before
            with sqlite3.connect(runtime.settings.database_path) as db:
                db.execute("DROP TRIGGER fail_wayfaring")
            claims = await asyncio.gather(
                _send(runtime, adapter, "claim", "领取行卷 1"),
                _send(runtime, adapter, "claim", "领取行卷 1"),
            )
            assert all(item.ok for item in claims), claims
            assert sorted(item.data["idempotent_replay"] for item in claims) == [
                False,
                True,
            ]
            assert claims[0].message == claims[1].message
            before = _state(runtime)
            conflict = await _send(runtime, adapter, "claim", "领取行卷 1 付费")
            assert conflict.code == "OPERATION_CONFLICT"
            assert _state(runtime) == before
        finally:
            await runtime.close()
        runtime = create_runtime(data_dir=root, clock=Clock(), adapters=(adapter,))
        try:
            replay = await _send(runtime, adapter, "claim", "领取行卷 1")
            assert replay.data["idempotent_replay"] is True
            assert replay.message == claims[0].message
            assert _state(runtime) == before
        finally:
            await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("damage", ["unreadable", "rewards", "source", "labels", "duplicate_reward"])
def test_bad_pass_snapshot_rejects_without_writes_but_keeps_operation_replay(
    tmp_path: Path, damage: str
) -> None:
    async def run() -> None:
        root, adapter = _content(tmp_path), "qq.official"
        _daily_points(root, 100)
        runtime = create_runtime(data_dir=root, clock=Clock(), adapters=(adapter,))
        try:
            assert (await _send(runtime, adapter, "create", "开始修仙")).ok
            assert (await _send(runtime, adapter, "start", "开始行卷")).ok
            assert (await _send(runtime, adapter, "checkin", "道历问安")).ok
            claim = await _send(runtime, adapter, "claim", "领取行卷 1")
            assert claim.ok, claim
            snapshot = _snapshot(runtime)
            if damage == "rewards":
                del snapshot["free_rewards"]
            elif damage == "source":
                snapshot["sources"]["routine.checkin.daily"]["points"] = True
            elif damage == "labels":
                del snapshot["reward_labels"]
            encoded = "{" if damage == "unreadable" else json.dumps(snapshot)
            if damage == "duplicate_reward":
                encoded = encoded.replace(
                    f'"{HERB_KEY}": 2', f'"{HERB_KEY}": 2, "{HERB_KEY}": 200', 1
                )
            with sqlite3.connect(runtime.settings.database_path) as db:
                db.execute("UPDATE wayfaring_passes SET snapshot_json=?", (encoded,))
            before = _state(runtime)
            assert (
                await _send(runtime, adapter, "status", "问道行卷")
            ).code == "CONTENT_UNAVAILABLE"
            assert (
                await _send(runtime, adapter, "claim-new", "领取行卷 1")
            ).code == "CONTENT_UNAVAILABLE"
            replay = await _send(runtime, adapter, "claim", "领取行卷 1")
            assert replay.message == claim.message
            assert replay.data["idempotent_replay"] is True
            assert _state(runtime) == before
        finally:
            await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("damage", ["unreachable", "boolean", "missing_item"])
def test_bad_pass_content_refuses_new_pass_atomically(
    tmp_path: Path, damage: str
) -> None:
    async def run() -> None:
        root = _content(tmp_path)

        def corrupt(row: dict) -> None:
            if damage == "unreachable":
                row["weekly_point_cap"] = 500
            elif damage == "boolean":
                row["points_per_level"] = True
            else:
                row["free_rewards"][0] = {"item.missing": 1}

        _change(root, PASS_FILE, PASS_KEY, corrupt)
        with pytest.raises(ContentError):
            wayfaring_definition(ContentBundle.load(root))
        runtime = create_runtime(data_dir=root, clock=Clock())
        try:
            assert (await _send(runtime, "onebot.v11", "create", "开始修仙")).ok
            before = _state(runtime)
            refused = await _send(runtime, "onebot.v11", "start", "开始行卷")
            assert refused.code == "CONTENT_UNAVAILABLE", refused
            assert _state(runtime) == before
        finally:
            await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("damage", ["unreadable", "missing_total", "not_object", "duplicate_total"])
@pytest.mark.parametrize("operation,command", [("start", "开始行卷"), ("claim", "领取行卷 1")])
def test_malformed_operation_result_cannot_reexecute_pass_mutation(
    tmp_path: Path, operation: str, command: str, damage: str
) -> None:
    async def run() -> None:
        root, adapter = _content(tmp_path), "qq.official"
        _daily_points(root, 100)
        runtime = create_runtime(data_dir=root, clock=Clock(), adapters=(adapter,))
        try:
            assert (await _send(runtime, adapter, "create", "开始修仙")).ok
            assert (await _send(runtime, adapter, "start", "开始行卷")).ok
            assert (await _send(runtime, adapter, "checkin", "道历问安")).ok
            assert (await _send(runtime, adapter, "claim", "领取行卷 1")).ok
            with sqlite3.connect(runtime.settings.database_path) as db:
                payload = json.loads(db.execute(
                    "SELECT result_json FROM operations WHERE operation_id=?", (operation,)
                ).fetchone()[0])
                del payload["total_points"]
                encoded = {
                    "unreadable": "{",
                    "missing_total": json.dumps(payload),
                    "not_object": "[]",
                    "duplicate_total": json.dumps(payload)[:-1] + ', "total_points": 0, "total_points": 999}',
                }[damage]
                db.execute(
                    "UPDATE operations SET result_json=? WHERE operation_id=?",
                    (encoded, operation),
                )
            before = _state(runtime)
            refused = await _send(runtime, adapter, operation, command)
            assert refused.code == "PERSISTENCE_ERROR", refused
            assert _state(runtime) == before
        finally:
            await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_expired_query_projects_only_unseen_in_cycle_sources_after_restart(
    tmp_path: Path, adapter: str
) -> None:
    async def run() -> None:
        root, clock = _content(tmp_path), Clock()
        runtime = create_runtime(data_dir=root, clock=clock, adapters=(adapter,))
        try:
            assert (await _send(runtime, adapter, "create", "开始修仙")).ok
            assert (await _send(runtime, adapter, "start", "开始行卷")).ok
            assert (await _send(runtime, adapter, "checkin-first", "道历问安")).ok
            clock.value += timedelta(days=27)
            assert (await _send(runtime, adapter, "checkin-last", "道历问安")).ok
        finally:
            await runtime.close()

        clock.value += timedelta(days=1)
        runtime = create_runtime(data_dir=root, clock=clock, adapters=(adapter,))
        try:
            assert (await _send(runtime, adapter, "checkin-outside", "道历问安")).ok
            status = await _send(runtime, adapter, "status", "问道行卷")
            assert status.data["status"] == "closed"
            assert status.data["total_points"] == 40
            with sqlite3.connect(runtime.settings.database_path) as db:
                sources = db.execute(
                    "SELECT source_operation_id FROM wayfaring_point_events ORDER BY source_operation_id"
                ).fetchall()
                assert sources == [("checkin-first",), ("checkin-last",)]
            before = _state(runtime)
            assert (await _send(runtime, adapter, "status-again", "问道行卷")).data == status.data
            assert _state(runtime) == before
        finally:
            await runtime.close()

    asyncio.run(run())
