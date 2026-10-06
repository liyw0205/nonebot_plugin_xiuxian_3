from __future__ import annotations

import asyncio
import json
import shutil
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from test_adapter_simulation import _onebot_group_event, _qq_group_event

from nonebot_plugin_xiuxian_3.adapters.onebot import normalize_event
from nonebot_plugin_xiuxian_3.adapters.qq import normalize_event as normalize_qq_event
from nonebot_plugin_xiuxian_3.runtime import create_runtime

ADAPTERS = ("qq.official", "onebot.v11")
START = datetime(2026, 9, 21, 12, tzinfo=UTC)


class Clock:
    def __init__(self) -> None:
        self.value = START

    def __call__(self) -> datetime:
        return self.value

    def at(self, *, hours: int, seconds: int = 0) -> None:
        self.value = START + timedelta(hours=hours, seconds=seconds)


async def _send(
    runtime, adapter: str, operation: str, command: str, *, user: str | None = None
):
    if adapter == "qq.official":
        event = _qq_group_event(command)
        if user is not None:
            event.author.member_openid = user
        message = normalize_qq_event(event)
    else:
        event = _onebot_group_event(command)
        if user is not None:
            event.user_id = int(user)
            event.sender.user_id = int(user)
        message = normalize_event(event)
    return await runtime.adapters.dispatch(
        adapter,
        replace(message.context, operation_id=operation),
        message.text,
    )


async def _lease(runtime, adapter: str) -> None:
    for operation, command in (
        ("create", "开始修仙"),
        ("seek", "寻仙问道"),
        ("lease", "租住居所"),
    ):
        result = await _send(runtime, adapter, operation, command)
        assert result.ok, (command, result)


def _state(runtime) -> dict[str, list]:
    with sqlite3.connect(runtime.settings.database_path) as db:
        return {
            table: db.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
            for table in (
                "players",
                "residences",
                "field_plots",
                "player_reputations",
                "codex_entries",
                "operations",
            )
        }


def _growth(root: Path, hours: int) -> None:
    path = root / "生活/生活.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    crop = next(row for row in document["records"] if row["key"] == "crop.blood_grass")
    crop["growth_seconds"] = hours * 60 * 60
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")


def _assert_player_copy(result) -> None:
    assert all(
        key not in result.message
        for key in ("item.", "growing", "harvestable", "harvested")
    )


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_renewed_residence_keeps_old_harvest_accessible_and_replay_cannot_take_new_crop(
    tmp_path: Path, adapter: str
) -> None:
    async def run() -> None:
        clock = Clock()
        runtime = create_runtime(data_dir=tmp_path, clock=clock, adapters=(adapter,))
        try:
            await _lease(runtime, adapter)
            clock.at(hours=48)
            old = await _send(runtime, adapter, "plant-old", "灵田播种 止血草")
            assert old.code == "FIELD_PLOT_PLANTED", old
            maintained = await _send(runtime, adapter, "maintain-old", "灵田维护")
            assert maintained.data["plot_id"] == old.data["plot_id"]
            clock.at(hours=72)
            assert (await _send(runtime, adapter, "renew", "租住居所")).ok
            new = await _send(runtime, adapter, "plant-new", "灵田播种 止血草")
            assert new.code == "FIELD_PLOT_PLANTED", new
            clock.at(hours=74)
            profile = await _send(runtime, adapter, "profile-old", "我的灵田")
            assert profile.data["plot_id"] == old.data["plot_id"]
            assert profile.data["status"] == "harvestable"
            _assert_player_copy(profile)
            harvested = await _send(runtime, adapter, "harvest-old", "灵田收获")
            assert harvested.code == "FIELD_PLOT_HARVESTED", harvested
            assert harvested.data["plot_id"] == old.data["plot_id"]
            assert harvested.data["harvest"] == {"item.herb.blood_grass": 3}
            _assert_player_copy(harvested)
        finally:
            await runtime.close()

        runtime = create_runtime(data_dir=tmp_path, clock=clock, adapters=(adapter,))
        try:
            before = _state(runtime)
            replay = await _send(runtime, adapter, "harvest-old", "灵田收获")
            assert replay.message == harvested.message
            assert replay.data["plot_id"] == old.data["plot_id"]
            assert replay.data["idempotent_replay"] is True
            conflict = await _send(runtime, adapter, "harvest-old", "灵田维护")
            assert conflict.code == "OPERATION_CONFLICT"
            assert _state(runtime) == before
            profile = await _send(runtime, adapter, "profile-new", "我的灵田")
            assert profile.data["plot_id"] == new.data["plot_id"]
            assert profile.data["status"] == "growing"
            maintained = await _send(runtime, adapter, "maintain-new", "灵田维护")
            assert maintained.data["plot_id"] == new.data["plot_id"]
            clock.at(hours=76, seconds=1)
            second = await _send(runtime, adapter, "harvest-new", "灵田收获")
            assert second.code == "FIELD_PLOT_HARVESTED", second
            assert second.data["plot_id"] == new.data["plot_id"]
            assert second.data["harvest"] == {"item.herb.blood_grass": 3}
            _assert_player_copy(second)
            with sqlite3.connect(runtime.settings.database_path) as db:
                assert db.execute(
                    "SELECT status FROM field_plots ORDER BY id"
                ).fetchall() == [("harvested",), ("harvested",)]
                energy, inventory, cultivation, total = db.execute(
                    "SELECT energy, inventory_json, cultivation, total_cultivation FROM players"
                ).fetchone()
                assert energy == 26
                assert json.loads(inventory)["item.herb.blood_grass"] == 7
                assert cultivation == total == 0
        finally:
            await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_frozen_growth_selects_earliest_unmaintained_and_mature_plot_not_latest_row(
    tmp_path: Path, adapter: str
) -> None:
    async def run() -> None:
        root = tmp_path / "content"
        shutil.copytree(Path(__file__).parents[1] / "data", root)
        # Different frozen growth periods exercise both directions of selection.
        _growth(root, 40)
        clock = Clock()
        runtime = create_runtime(data_dir=root, clock=clock, adapters=(adapter,))
        try:
            await _lease(runtime, adapter)
            clock.at(hours=48)
            old = await _send(runtime, adapter, "plant-old", "灵田播种 止血草")
            assert old.code == "FIELD_PLOT_PLANTED", old
            assert datetime.fromisoformat(old.data["harvest_at"]) == START + timedelta(
                hours=88
            )
        finally:
            await runtime.close()

        _growth(root, 4)
        items_path = root / "道具/材料.json"
        items = json.loads(items_path.read_text(encoding="utf-8"))
        next(row for row in items["records"] if row["key"] == "item.herb.blood_grass")[
            "name"
        ] = "异名灵草"
        items_path.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
        clock.at(hours=72)
        runtime = create_runtime(data_dir=root, clock=clock, adapters=(adapter,))
        try:
            assert (await _send(runtime, adapter, "renew", "租住居所")).ok
            new = await _send(runtime, adapter, "plant-new", "灵田播种 止血草")
            assert new.code == "FIELD_PLOT_PLANTED", new
            first = await _send(runtime, adapter, "maintain-first", "灵田维护")
            assert first.code == "FIELD_PLOT_MAINTAINED", first
            assert first.data["plot_id"] == new.data["plot_id"]
            second = await _send(runtime, adapter, "maintain-second", "灵田维护")
            assert second.code == "FIELD_PLOT_MAINTAINED", second
            assert second.data["plot_id"] == old.data["plot_id"]
            before = _state(runtime)
            completed = await _send(runtime, adapter, "maintain-exhausted", "灵田维护")
            assert completed.code == "PLOT_MAINTENANCE_MISSED"
            assert _state(runtime) == before
            clock.at(hours=76)
            profile = await _send(runtime, adapter, "profile-mature", "我的灵田")
            assert profile.data["plot_id"] == new.data["plot_id"]
            assert profile.data["status"] == "harvestable"
            harvested_new = await _send(runtime, adapter, "harvest-new", "灵田收获")
            assert harvested_new.data["plot_id"] == new.data["plot_id"]
            assert harvested_new.data["harvest"] == {"item.herb.blood_grass": 3}
            assert "异名灵草" in harvested_new.message
            _assert_player_copy(harvested_new)
            profile = await _send(runtime, adapter, "profile-old-growing", "我的灵田")
            assert profile.data["plot_id"] == old.data["plot_id"]
            assert profile.data["status"] == "growing"
            assert datetime.fromisoformat(
                profile.data["harvest_at"]
            ) == START + timedelta(hours=88)
            clock.at(hours=88)
            harvested_old = await _send(runtime, adapter, "harvest-old", "灵田收获")
            assert harvested_old.data["plot_id"] == old.data["plot_id"]
            assert harvested_old.data["harvest"] == {"item.herb.blood_grass": 3}
            assert (
                "止血草" in harvested_old.message
                and "异名灵草" not in harvested_old.message
            )
            _assert_player_copy(harvested_old)
            terminal = await _send(runtime, adapter, "profile-terminal", "我的灵田")
            assert terminal.data["plot_id"] == new.data["plot_id"]
            assert terminal.data["status"] == "harvested"
        finally:
            await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("adapter", ADAPTERS)
@pytest.mark.parametrize("action", ["harvest", "maintain"])
def test_withered_old_plot_does_not_block_another_eligible_plot(
    tmp_path: Path, adapter: str, action: str
) -> None:
    async def run() -> None:
        root = tmp_path / "content"
        shutil.copytree(Path(__file__).parents[1] / "data", root)
        clock = Clock()
        runtime = create_runtime(data_dir=root, clock=clock, adapters=(adapter,))
        try:
            await _lease(runtime, adapter)
            clock.at(hours=48)
            old = await _send(runtime, adapter, "plant-old", "灵田播种 止血草")
            assert old.ok, old
        finally:
            await runtime.close()
        if action == "maintain":
            _growth(root, 8)
        clock.at(hours=72)
        runtime = create_runtime(data_dir=root, clock=clock, adapters=(adapter,))
        try:
            assert (await _send(runtime, adapter, "renew", "租住居所")).ok
            new = await _send(runtime, adapter, "plant-new", "灵田播种 止血草")
            assert new.ok, new
            clock.at(hours=76, seconds=1)
            profile = await _send(runtime, adapter, "profile", "我的灵田")
            assert profile.data["plot_id"] == new.data["plot_id"]
            _assert_player_copy(profile)
            command = "灵田收获" if action == "harvest" else "灵田维护"
            result = await _send(runtime, adapter, "eligible-action", command)
            assert result.code == (
                "FIELD_PLOT_HARVESTED"
                if action == "harvest"
                else "FIELD_PLOT_MAINTAINED"
            ), result
            assert result.data["plot_id"] == new.data["plot_id"]
            _assert_player_copy(result)
            with sqlite3.connect(runtime.settings.database_path) as db:
                assert (
                    db.execute(
                        "SELECT result_json FROM field_plots WHERE plot_id=?",
                        (old.data["plot_id"],),
                    ).fetchone()[0]
                    == "{}"
                )
        finally:
            await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_earlier_other_players_plot_is_never_selected(
    tmp_path: Path, adapter: str
) -> None:
    async def run() -> None:
        clock = Clock()
        runtime = create_runtime(data_dir=tmp_path, clock=clock, adapters=(adapter,))
        try:
            for operation, command in (
                ("other-create", "开始修仙"),
                ("other-seek", "寻仙问道"),
                ("other-lease", "租住居所"),
            ):
                result = await _send(runtime, adapter, operation, command, user="2002")
                assert result.ok, result
            other = await _send(
                runtime, adapter, "other-plant", "灵田播种 止血草", user="2002"
            )
            assert other.ok, other
            await _lease(runtime, adapter)
            clock.at(hours=1)
            mine = await _send(runtime, adapter, "plant", "灵田播种 止血草")
            assert mine.ok, mine
            maintained = await _send(runtime, adapter, "maintain", "灵田维护")
            assert maintained.data["plot_id"] == mine.data["plot_id"]
            clock.at(hours=5)
            profile = await _send(runtime, adapter, "profile", "我的灵田")
            assert profile.data["plot_id"] == mine.data["plot_id"]
            harvested = await _send(runtime, adapter, "harvest", "灵田收获")
            assert harvested.data["plot_id"] == mine.data["plot_id"]
            assert harvested.data["harvest"] == {"item.herb.blood_grass": 3}
            with sqlite3.connect(runtime.settings.database_path) as db:
                assert db.execute(
                    "SELECT status, maintenance_count, result_json FROM field_plots WHERE plot_id=?",
                    (other.data["plot_id"],),
                ).fetchone() == ("growing", 0, "{}")
        finally:
            await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_two_mature_plots_harvest_earliest_deadline_before_latest_lease(
    tmp_path: Path, adapter: str
) -> None:
    async def run() -> None:
        clock = Clock()
        runtime = create_runtime(data_dir=tmp_path, clock=clock, adapters=(adapter,))
        try:
            await _lease(runtime, adapter)
            clock.at(hours=48)
            old = await _send(runtime, adapter, "plant-old", "灵田播种 止血草")
            assert old.ok, old
            clock.at(hours=72)
            assert (await _send(runtime, adapter, "renew", "租住居所")).ok
            new = await _send(runtime, adapter, "plant-new", "灵田播种 止血草")
            assert new.ok, new
            clock.at(hours=76)
            first = await _send(runtime, adapter, "harvest-first", "灵田收获")
            assert first.code == "FIELD_PLOT_HARVESTED", first
            assert first.data["plot_id"] == old.data["plot_id"]
            second = await _send(runtime, adapter, "harvest-second", "灵田收获")
            assert second.code == "FIELD_PLOT_HARVESTED", second
            assert second.data["plot_id"] == new.data["plot_id"]
            assert (
                first.data["harvest"]
                == second.data["harvest"]
                == {"item.herb.blood_grass": 1}
            )
        finally:
            await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_expired_current_plot_can_be_replanted_while_old_lease_crop_still_grows(
    tmp_path: Path, adapter: str
) -> None:
    async def run() -> None:
        root = tmp_path / "content"
        shutil.copytree(Path(__file__).parents[1] / "data", root)
        _growth(root, 100)
        clock = Clock()
        runtime = create_runtime(data_dir=root, clock=clock, adapters=(adapter,))
        try:
            await _lease(runtime, adapter)
            clock.at(hours=48)
            old = await _send(runtime, adapter, "plant-old", "灵田播种 止血草")
            assert old.ok, old
        finally:
            await runtime.close()

        _growth(root, 4)
        clock.at(hours=72)
        runtime = create_runtime(data_dir=root, clock=clock, adapters=(adapter,))
        try:
            assert (await _send(runtime, adapter, "renew", "租住居所")).ok
            expired = await _send(runtime, adapter, "plant-short", "灵田播种 止血草")
            assert expired.ok, expired
            clock.at(hours=101)
            profile = await _send(runtime, adapter, "profile-old", "我的灵田")
            assert profile.data["plot_id"] == old.data["plot_id"]
            assert profile.data["status"] == "growing"
            with sqlite3.connect(runtime.settings.database_path) as db:
                old_state = db.execute(
                    "SELECT * FROM field_plots WHERE plot_id=?", (old.data["plot_id"],)
                ).fetchone()
                energy, inventory = db.execute(
                    "SELECT energy, inventory_json FROM players"
                ).fetchone()
            planted = await _send(runtime, adapter, "replant", "灵田播种 止血草")
            assert planted.code == "FIELD_PLOT_PLANTED", planted
            assert planted.data["plot_id"] not in {
                old.data["plot_id"],
                expired.data["plot_id"],
            }
            with sqlite3.connect(runtime.settings.database_path) as db:
                assert (
                    db.execute(
                        "SELECT * FROM field_plots WHERE plot_id=?",
                        (old.data["plot_id"],),
                    ).fetchone()
                    == old_state
                )
                assert db.execute(
                    "SELECT status, result_json FROM field_plots WHERE plot_id=?",
                    (expired.data["plot_id"],),
                ).fetchone() == ("withered", "{}")
                current_energy, current_inventory = db.execute(
                    "SELECT energy, inventory_json FROM players"
                ).fetchone()
                assert current_energy == energy - 1
                assert json.loads(current_inventory).get("item.herb.blood_grass", 0) == (
                    json.loads(inventory)["item.herb.blood_grass"] - 1
                )
            before = _state(runtime)
            replay = await _send(runtime, adapter, "replant", "灵田播种 止血草")
            assert replay.data["plot_id"] == planted.data["plot_id"]
            assert replay.data["idempotent_replay"] is True
            assert _state(runtime) == before
        finally:
            await runtime.close()

    asyncio.run(run())
