from __future__ import annotations

import asyncio
import copy
import sqlite3
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError
from nonebot_plugin_xiuxian_3.xiuxian.livelihood.rules import residence_definition
from test_data_completion import Flow


DATA = Path(__file__).parents[1] / "data"
RESIDENCES = (
    ("residence.town_room", 1),
    ("residence.courtyard", 2),
    ("residence.herb_court", 2),
)


def _set_resources(flow: Flow, *, stamina: int, energy: int, maximum: int = 20) -> None:
    with flow.runtime.repository._connect() as db:
        db.execute(
            "UPDATE players SET stamina = ?, stamina_max = ?, energy = ?, energy_max = ? "
            "WHERE platform_user_id = 'player'",
            (stamina, maximum, energy, maximum),
        )


def _player_state(flow: Flow) -> tuple[int, int]:
    with sqlite3.connect(flow.runtime.settings.database_path) as db:
        stamina, _, energy, _ = db.execute(
            "SELECT stamina, stamina_max, energy, energy_max "
            "FROM players WHERE platform_user_id = 'player'"
        ).fetchone()
    return stamina, energy


def _assert_player_copy(*messages: str) -> None:
    for message in messages:
        for marker in ("running", "settled", "item.", "rest_id", "residence_id", "snapshot"):
            assert marker not in message


def test_rest_content_contract_is_closed() -> None:
    bundle = ContentBundle.load(DATA)
    for key, slots in RESIDENCES:
        definition = residence_definition(key, bundle)
        assert definition.rest_slots == slots
        assert definition.rest_duration_seconds == 1800
        assert definition.rest_stamina == 8
        assert definition.rest_energy == 8
        assert definition.rest_daily_limit == 2

    records = dict(bundle._records)
    record = copy.deepcopy(records[("livelihood", "residence.town_room")])
    record["rest"]["daily_limit"] = 0
    records[("livelihood", "residence.town_room")] = record
    broken = replace(bundle, _records=records)
    with pytest.raises(ContentError, match="rest values"):
        residence_definition("residence.town_room", broken)

    records = dict(bundle._records)
    record = copy.deepcopy(records[("livelihood", "residence.town_room")])
    record["rest"]["unknown"] = 1
    records[("livelihood", "residence.town_room")] = record
    broken = replace(bundle, _records=records)
    with pytest.raises(ContentError, match="rest fields"):
        residence_definition("residence.town_room", broken)


def test_rest_round_trip_caps_restoration_and_enforces_daily_quota(tmp_path) -> None:
    async def run() -> None:
        flow = Flow(tmp_path)
        try:
            await flow.enter("体修")
            assert (await flow.send("租住居所")).code == "RESIDENCE_LEASED"
            _set_resources(flow, stamina=10, energy=10)

            started = await flow.send("休整", "rest-1")
            assert started.code == "REST_STARTED"
            assert started.data["used_today"] == 1
            assert started.data["daily_limit"] == 2
            _assert_player_copy(started.message)

            early = await flow.send("结算休整", "rest-set-1", ok=False)
            assert early.code == "REST_NOT_READY"

            flow.now += timedelta(seconds=1800)
            settled = await flow.send("结算休整", "rest-set-1")
            assert settled.code == "REST_SETTLED"
            assert settled.data["restored_stamina"] == 8
            assert settled.data["restored_energy"] == 8
            _assert_player_copy(settled.message)
            assert _player_state(flow) == (18, 18)

            after_settle = flow.dump()
            replay = await flow.send("结算休整", "rest-set-1")
            assert replay.data["idempotent_replay"] is True
            assert flow.dump() == after_settle

            conflict = await flow.send("休整", "rest-set-1", ok=False)
            assert conflict.code == "OPERATION_CONFLICT"
            assert flow.dump() == after_settle

            second = await flow.send("休整", "rest-2")
            assert second.code == "REST_STARTED"
            assert second.data["used_today"] == 2
            flow.now += timedelta(seconds=1800)
            capped = await flow.send("结算休整", "rest-set-2")
            assert capped.code == "REST_SETTLED"
            assert capped.data["restored_stamina"] == 2
            assert capped.data["restored_energy"] == 2
            assert _player_state(flow) == (20, 20)

            _set_resources(flow, stamina=5, energy=5)
            before_third = flow.dump()
            third = await flow.send("休整", "rest-3", ok=False)
            assert third.code == "REST_DAILY_LIMIT"
            assert flow.dump() == before_third

            profile = await flow.send("我的居所")
            assert profile.data["rest_slots"] == 1
            assert profile.data["rest_used_today"] == 2
            assert profile.data["rest_daily_limit"] == 2
            assert profile.data["rest_running_until"] is None
            _assert_player_copy(profile.message)
        finally:
            await flow.runtime.close()

    asyncio.run(run())


def test_rest_full_resources_does_not_consume_quota(tmp_path) -> None:
    async def run() -> None:
        flow = Flow(tmp_path)
        try:
            await flow.enter("体修")
            assert (await flow.send("租住居所")).code == "RESIDENCE_LEASED"
            _set_resources(flow, stamina=20, energy=20)
            full = await flow.send("休整", "rest-full", ok=False)
            assert full.code == "REST_NOT_NEEDED"

            _set_resources(flow, stamina=12, energy=12)
            started = await flow.send("休整", "rest-after-full")
            assert started.code == "REST_STARTED"
            assert started.data["used_today"] == 1
        finally:
            await flow.runtime.close()

    asyncio.run(run())


def test_rest_blocks_active_cultivation(tmp_path) -> None:
    async def run() -> None:
        flow = Flow(tmp_path)
        try:
            await flow.enter("体修")
            assert (await flow.send("租住居所")).code == "RESIDENCE_LEASED"
            _set_resources(flow, stamina=10, energy=10)
            assert (await flow.send("开始修炼", "rest-cultivate")).code == "CULTIVATION_STARTED"
            blocked = await flow.send("休整", "rest-blocked", ok=False)
            assert blocked.code == "REST_BLOCKED"
            assert "修炼" in blocked.message
        finally:
            await flow.runtime.close()

    asyncio.run(run())


def test_rest_survives_restart_and_settles_after_lease_expiry(tmp_path) -> None:
    async def run() -> None:
        flow = Flow(tmp_path)
        try:
            await flow.enter("体修")
            assert (await flow.send("租住居所")).code == "RESIDENCE_LEASED"
            _set_resources(flow, stamina=4, energy=4)
            started = await flow.send("休整", "rest-restart")
            assert started.code == "REST_STARTED"
            assert started.data["used_today"] == 1
        finally:
            await flow.runtime.close()

        # Resume on the same data root; the running session and operation
        # replay must survive without re-running onboarding commands.
        flow.runtime = create_runtime(
            data_dir=flow.root, clock=lambda: flow.now, adapters=("onebot.v11",)
        )
        try:
            flow.now += timedelta(seconds=1800)
            profile = await flow.send("我的居所")
            assert profile.data["rest_running_until"] == started.data["ends_at"]
            settled = await flow.send("结算休整", "rest-restart-settle")
            assert settled.code == "REST_SETTLED"
            assert settled.data["restored_stamina"] == 8
            assert settled.data["restored_energy"] == 8
            assert _player_state(flow) == (12, 12)

            replay = await flow.send("结算休整", "rest-restart-settle")
            assert replay.data["idempotent_replay"] is True
            assert _player_state(flow) == (12, 12)
        finally:
            await flow.runtime.close()

        # An expired lease only blocks a new rest; the old session already
        # settled, and a fresh rest now needs an active residence again.
        flow.runtime = create_runtime(
            data_dir=flow.root, clock=lambda: flow.now, adapters=("onebot.v11",)
        )
        try:
            with flow.runtime.repository._connect() as db:
                db.execute("UPDATE residences SET status = 'expired'")
                db.execute("UPDATE players SET stamina = 3, energy = 3")
            expired = await flow.send("休整", "rest-expired", ok=False)
            assert expired.code == "RESIDENCE_REQUIRED"
        finally:
            await flow.runtime.close()

    asyncio.run(run())


def test_rest_corrupt_snapshot_rolls_back_and_can_retry(tmp_path) -> None:
    async def run() -> None:
        flow = Flow(tmp_path)
        try:
            await flow.enter("体修")
            assert (await flow.send("租住居所")).code == "RESIDENCE_LEASED"
            _set_resources(flow, stamina=5, energy=5)
            started = await flow.send("休整", "rest-corrupt")
            assert started.code == "REST_STARTED"
            with sqlite3.connect(flow.runtime.settings.database_path) as db:
                raw = db.execute(
                    "SELECT snapshot_json FROM rest_sessions WHERE rest_id = ?",
                    (started.data["rest_id"],),
                ).fetchone()[0]
                db.execute(
                    "UPDATE rest_sessions SET snapshot_json = ? WHERE rest_id = ?",
                    ('{"residence_id": 1}', started.data["rest_id"]),
                )
            flow.now += timedelta(seconds=1800)
            before = flow.dump()
            rejected = await flow.send("结算休整", "rest-corrupt-settle", ok=False)
            assert rejected.code == "PERSISTENCE_ERROR"
            assert flow.dump() == before

            with sqlite3.connect(flow.runtime.settings.database_path) as db:
                db.execute(
                    "UPDATE rest_sessions SET snapshot_json = ? WHERE rest_id = ?",
                    (raw, started.data["rest_id"]),
                )
            retried = await flow.send("结算休整", "rest-corrupt-settle")
            assert retried.code == "REST_SETTLED"
            assert retried.data["restored_stamina"] == 8
            assert _player_state(flow) == (13, 13)
        finally:
            await flow.runtime.close()

    asyncio.run(run())
