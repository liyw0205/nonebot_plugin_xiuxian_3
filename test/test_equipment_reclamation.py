from __future__ import annotations

import asyncio
import json
import shutil
import sqlite3
from pathlib import Path

from nonebot_plugin_xiuxian_3.runtime import create_runtime
from test_equipment import _context, _enter_cultivator, _set_equipment_resources


ROOT = Path(__file__).parents[1]


def _instance_id(runtime, user: str) -> str:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        row = connection.execute(
            "SELECT instance_id FROM equipment_instances WHERE player_id="
            "(SELECT id FROM players WHERE platform='web' AND platform_user_id=?) "
            "AND status IN ('active', 'broken') ORDER BY id LIMIT 1",
            (user,),
        ).fetchone()
    assert row is not None
    return str(row[0])


def _assets(runtime, user: str) -> tuple[dict[str, int], int]:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        row = connection.execute(
            "SELECT inventory_json, spirit_stones FROM players WHERE platform='web' AND platform_user_id=?",
            (user,),
        ).fetchone()
    assert row is not None
    return json.loads(row[0]), int(row[1])


async def _ready(runtime, user: str) -> str:
    await _enter_cultivator(runtime, user)
    _set_equipment_resources(runtime, user, ironstone=20, stones=1_000)
    made = await runtime.dispatch(_context(user, "reclaim-materialize"), "强化法器 木纹剑")
    assert made.ok, (made.code, made.message)
    instance_id = _instance_id(runtime, user)
    unequipped = await runtime.dispatch(
        _context(user, "reclaim-unequip", operation_id="reclaim-unequip"),
        f"卸下法器 {instance_id}",
    )
    assert unequipped.ok
    return instance_id


def test_reclamation_preview_archives_and_replays_without_refunding_growth(tmp_path: Path) -> None:
    async def run() -> None:
        data_dir = tmp_path / "data"
        shutil.copytree(ROOT / "data", data_dir)
        runtime = create_runtime(data_dir=data_dir)
        user = "equipment-reclamation-main"
        try:
            await _enter_cultivator(runtime, user)
            _set_equipment_resources(runtime, user, ironstone=20, stones=1_000)
            made = await runtime.dispatch(_context(user, "reclaim-materialize"), "强化法器 木纹剑")
            assert made.ok
            instance_id = _instance_id(runtime, user)
            before = _assets(runtime, user)
            equipped_preview = await runtime.dispatch(
                _context(user, "reclaim-equipped"), f"装备回收预览 {instance_id}"
            )
            assert equipped_preview.code == "EQUIPMENT_RECLAMATION_EQUIPPED"
            unequipped = await runtime.dispatch(
                _context(user, "reclaim-unequip", operation_id="reclaim-unequip"),
                f"卸下法器 {instance_id}",
            )
            assert unequipped.ok
            preview = await runtime.dispatch(
                _context(user, "reclaim-preview"), f"装备回收预览 {instance_id}"
            )
            assert preview.ok and preview.data["yields"] == {"item.ore.ironstone": 1}
            assert _assets(runtime, user) == before
            after_preview = _assets(runtime, user)
            result = await runtime.dispatch(
                _context(user, "reclaim", operation_id="equipment-reclaim-1"),
                f"回收装备 {instance_id}",
            )
            assert result.ok and result.code == "EQUIPMENT_RECLAIMED"
            assert result.data["status"] == "archived"
            assets_after = _assets(runtime, user)
            assert assets_after[0].get("item.ore.ironstone", 0) == after_preview[0].get(
                "item.ore.ironstone", 0
            ) + 1
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute(
                    "SELECT status, equipped FROM equipment_instances WHERE instance_id=?", (instance_id,)
                ).fetchone() == ("archived", 0)
                assert connection.execute(
                    "SELECT COUNT(*) FROM equipment_reclamation_events"
                ).fetchone()[0] == 1
            replay = await runtime.dispatch(
                _context(user, "reclaim-replay", operation_id="equipment-reclaim-1"),
                f"回收装备 {instance_id}",
            )
            assert replay.ok and replay.data["idempotent_replay"]
            listed = await runtime.dispatch(_context(user, "reclaim-list"), "我的装备")
            assert instance_id not in {row["instance_id"] for row in listed.data["equipment"]}
        finally:
            await runtime.close()

    asyncio.run(run())


def test_reclamation_rejects_foreign_busy_and_rolls_back_event_failure(tmp_path: Path) -> None:
    async def run() -> None:
        data_dir = tmp_path / "data"
        shutil.copytree(ROOT / "data", data_dir)
        runtime = create_runtime(data_dir=data_dir)
        owner = "equipment-reclamation-owner"
        other = "equipment-reclamation-other"
        try:
            instance_id = await _ready(runtime, owner)
            await _enter_cultivator(runtime, other)
            foreign = await runtime.dispatch(
                _context(other, "reclaim-foreign"), f"回收装备 {instance_id}"
            )
            assert foreign.code == "EQUIPMENT_NOT_OWNED"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                owner_id = connection.execute(
                    "SELECT id FROM players WHERE platform='web' AND platform_user_id=?", (owner,)
                ).fetchone()[0]
                connection.execute(
                    "INSERT INTO cultivation_sessions(session_id, player_id, operation_id, mode_key, status, starts_at, ends_at, created_at, updated_at) "
                    "VALUES ('reclaim-lock', ?, 'reclaim-lock-op', 'basic', 'running', '2026-11-18T00:00:00+00:00', '2026-11-18T00:00:00+00:00', '2026-11-18T00:00:00+00:00', '2026-11-18T00:00:00+00:00')",
                    (owner_id,),
                )
            busy = await runtime.dispatch(
                _context(owner, "reclaim-busy"), f"回收装备 {instance_id}"
            )
            assert busy.code == "EQUIPMENT_BUSY"
            before_assets = _assets(runtime, owner)
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute("DELETE FROM cultivation_sessions WHERE session_id='reclaim-lock'")
                connection.execute(
                    "CREATE TRIGGER reject_equipment_reclamation BEFORE INSERT ON equipment_reclamation_events "
                    "BEGIN SELECT RAISE(ABORT, 'forced reclamation event failure'); END"
                )
            failed = await runtime.dispatch(
                _context(owner, "reclaim-failure", operation_id="reclaim-retry"),
                f"回收装备 {instance_id}",
            )
            assert failed.code == "PERSISTENCE_ERROR" and failed.retryable
            assert _assets(runtime, owner) == before_assets
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute(
                    "SELECT status FROM equipment_instances WHERE instance_id=?", (instance_id,)
                ).fetchone()[0] == "active"
                connection.execute("DROP TRIGGER reject_equipment_reclamation")
            retried = await runtime.dispatch(
                _context(owner, "reclaim-retry", operation_id="reclaim-retry"),
                f"回收装备 {instance_id}",
            )
            assert retried.ok and retried.code == "EQUIPMENT_RECLAIMED"
        finally:
            await runtime.close()

    asyncio.run(run())


def test_reclamation_concurrent_replay_survives_restart_and_closed_rules(tmp_path: Path) -> None:
    async def run() -> None:
        data_dir = tmp_path / "data"
        shutil.copytree(ROOT / "data", data_dir)
        first = create_runtime(data_dir=data_dir)
        second = create_runtime(data_dir=data_dir)
        user = "equipment-reclamation-replay"
        try:
            instance_id = await _ready(first, user)
            command = f"回收装备 {instance_id}"
            results = await asyncio.gather(
                first.dispatch(_context(user, "reclaim-race-1", operation_id="reclaim-race"), command),
                second.dispatch(_context(user, "reclaim-race-2", operation_id="reclaim-race"), command),
            )
            assert all(result.ok and result.code == "EQUIPMENT_RECLAIMED" for result in results)
            assert sum(bool(result.data["idempotent_replay"]) for result in results) == 1
            with sqlite3.connect(first.settings.database_path) as connection:
                assert connection.execute(
                    "SELECT COUNT(*) FROM equipment_reclamation_events"
                ).fetchone()[0] == 1
        finally:
            await second.close()
            await first.close()

        growth_path = data_dir / "装备" / "成长.json"
        document = json.loads(growth_path.read_text(encoding="utf-8"))
        next(row for row in document["records"] if row["key"] == "equipment.growth.common")["status"] = "closed"
        growth_path.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
        recovered = create_runtime(data_dir=data_dir)
        try:
            replay = await recovered.dispatch(
                _context(user, "reclaim-after-restart", operation_id="reclaim-race"), command
            )
            assert replay.ok and replay.data["idempotent_replay"]
            with sqlite3.connect(recovered.settings.database_path) as connection:
                assert connection.execute(
                    "SELECT COUNT(*) FROM equipment_reclamation_events"
                ).fetchone()[0] == 1
        finally:
            await recovered.close()

    asyncio.run(run())
