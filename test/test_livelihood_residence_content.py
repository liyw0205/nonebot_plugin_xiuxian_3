from __future__ import annotations

import asyncio
import json
import shutil
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime


class MutableClock:
    def __init__(self, value: datetime):
        self.value = value

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **kwargs: int) -> None:
        self.value += timedelta(**kwargs)


def _context(user: str, operation_id: str = "") -> CommandContext:
    return CommandContext(adapter="web", user_id=user, operation_id=operation_id)


def _edit_livelihood(data_dir: Path, *, residence_edit, crop_edit) -> None:
    path = data_dir / "生活" / "生活.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    for row in document["records"]:
        if row.get("key") == "residence.town_room":
            residence_edit(row)
        elif row.get("key") == "crop.blood_grass":
            crop_edit(row)
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_residence_and_crop_snapshots_survive_content_close_and_restart() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
        with TemporaryDirectory() as temp:
            data_dir = Path(temp) / "data"
            shutil.copytree(Path(__file__).parents[1] / "data", data_dir)

            def edit_residence(row: dict[str, object]) -> None:
                row["name"] = "听雨客舍"
                row["aliases"] = ["听雨舍"]
                row["rent"]["amount"] = 31
                row["rent"]["period_business_days"] = 5

            def edit_crop(row: dict[str, object]) -> None:
                row["name"] = "赤玉止血草"
                row["aliases"] = ["赤玉草"]
                row["growth_seconds"] = 3600
                row["maintenance"]["energy"] = 2
                row["maintenance"]["minimum_count"] = 2
                row["harvest"][0]["quantity"] = 4
                row["reputation"]["amount"] = 2

            _edit_livelihood(data_dir, residence_edit=edit_residence, crop_edit=edit_crop)
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            user = "livelihood-content-snapshot"
            assert (await runtime.dispatch(_context(user, "create"), "开始修仙")).ok
            assert (await runtime.dispatch(_context(user, "seek"), "寻仙问道")).ok
            leased = await runtime.dispatch(_context(user, "lease"), "租住居所 听雨舍")
            assert leased.code == "RESIDENCE_LEASED"
            assert leased.data["rent_cost"] == 31
            planted = await runtime.dispatch(_context(user, "plant"), "灵田播种 赤玉草")
            assert planted.code == "FIELD_PLOT_PLANTED"
            assert planted.data["required_maintenance"] == 2
            with sqlite3.connect(runtime.settings.database_path) as connection:
                residence_snapshot = json.loads(
                    connection.execute(
                        "SELECT snapshot_json FROM residences WHERE residence_id=?",
                        (leased.data["residence_id"],),
                    ).fetchone()[0]
                )
                plot_snapshot = json.loads(
                    connection.execute(
                        "SELECT snapshot_json FROM field_plots WHERE plot_id=?",
                        (planted.data["plot_id"],),
                    ).fetchone()[0]
                )
            assert residence_snapshot["rent_cost"] == 31
            assert residence_snapshot["lease_days"] == 5
            assert residence_snapshot["label"] == "听雨客舍"
            assert plot_snapshot["growth_seconds"] == 3600
            assert plot_snapshot["maintenance_energy"] == 2
            assert plot_snapshot["required_maintenance"] == 2
            assert plot_snapshot["maintained_harvest"] == {"item.herb.blood_grass": 4}
            assert plot_snapshot["reputation_delta"] == 2
            await runtime.close()

            def close_records(row: dict[str, object]) -> None:
                row["name"] = "已封存内容"
                row["aliases"] = []
                row["status"] = "locked"

            _edit_livelihood(data_dir, residence_edit=close_records, crop_edit=close_records)
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            replay_lease = await runtime.dispatch(_context(user, "lease"), "租住居所 听雨舍")
            replay_plant = await runtime.dispatch(_context(user, "plant"), "灵田播种 赤玉草")
            assert replay_lease.data["idempotent_replay"] is True
            assert replay_plant.data["idempotent_replay"] is True
            profile = await runtime.dispatch(_context(user), "我的居所")
            field_profile = await runtime.dispatch(_context(user), "我的灵田")
            assert "听雨客舍" in profile.message
            assert "赤玉止血草" in field_profile.message

            assert (await runtime.dispatch(_context(user, "maintain-1"), "灵田维护")).ok
            assert (await runtime.dispatch(_context(user, "maintain-2"), "灵田维护")).ok
            clock.advance(hours=1)
            harvested = await runtime.dispatch(_context(user, "harvest"), "灵田收获")
            assert harvested.code == "FIELD_PLOT_HARVESTED"
            assert harvested.data["harvest"] == {"item.herb.blood_grass": 4}
            assert harvested.data["local_reputation_delta"] == 2
            await runtime.close()

    asyncio.run(run())


def test_corrupt_residence_field_and_operation_json_are_rejected_without_writes() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            user = "livelihood-corrupt-snapshot"
            assert (await runtime.dispatch(_context(user, "create"), "开始修仙")).ok
            assert (await runtime.dispatch(_context(user, "seek"), "寻仙问道")).ok
            leased = await runtime.dispatch(_context(user, "lease"), "租住居所")
            planted = await runtime.dispatch(_context(user, "plant"), "灵田播种")
            assert leased.ok and planted.ok
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE residences SET snapshot_json='{}' WHERE residence_id=?",
                    (leased.data["residence_id"],),
                )
                connection.execute(
                    "UPDATE residences SET ends_at='2020-01-01T00:00:00+00:00' WHERE residence_id=?",
                    (leased.data["residence_id"],),
                )
            profile = await runtime.dispatch(_context(user), "我的居所")
            assert profile.code == "PERSISTENCE_ERROR"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute(
                    "SELECT status FROM residences WHERE residence_id=?",
                    (leased.data["residence_id"],),
                ).fetchone()[0] == "active"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE field_plots SET snapshot_json='{}' WHERE plot_id=?",
                    (planted.data["plot_id"],),
                )
            field_profile = await runtime.dispatch(_context(user), "我的灵田")
            assert field_profile.code == "PERSISTENCE_ERROR"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE operations SET result_json='{' WHERE operation_id='lease'"
                )
            replay = await runtime.dispatch(_context(user, "lease"), "租住居所")
            assert replay.code == "PERSISTENCE_ERROR"
            await runtime.close()

    asyncio.run(run())
