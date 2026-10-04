from __future__ import annotations

import asyncio
import json
import shutil
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.economy.rules import resolve_market_item
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError
from nonebot_plugin_xiuxian_3.xiuxian.items.rules import resolve_item
from nonebot_plugin_xiuxian_3.xiuxian.production.rules import random_quality_bp


def _context(adapter: str, user: str, request: str, operation: str = "") -> CommandContext:
    return CommandContext(
        adapter=adapter,
        user_id=user,
        request_id=request,
        operation_id=operation,
        can_write_assets=True,
    )


async def _player(runtime, adapter: str, user: str, *, realm: str, location: str, inventory: dict[str, int], subprofession: str | None = None) -> None:
    await runtime.adapters.dispatch(adapter, _context(adapter, user, f"create-{adapter}"), "开始修仙")
    await runtime.adapters.dispatch(adapter, _context(adapter, user, f"seek-{adapter}"), "寻仙问道")
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            """
            UPDATE players SET stage='cultivator', realm_key=?, realm_layer=1,
                location_key=?, subprofession_key=?, selected_service=?,
                stamina=30, stamina_max=30, energy=30, energy_max=30,
                spirit_stones=1000, inventory_json=?, durability_json='{}', intro_json='{}'
            WHERE platform=? AND platform_user_id=?
            """,
            (realm, location, subprofession, subprofession, json.dumps(inventory), adapter, user),
        )


def test_cloud_tea_is_consumed_once_and_frozen_into_qq_onebot_cultivation() -> None:
    async def run() -> None:
        for adapter in ("qq.official", "onebot.v11"):
            with TemporaryDirectory() as data_dir:
                runtime = create_runtime(data_dir=Path(data_dir) / adapter)
                user = f"tea-{adapter}"
                await _player(
                    runtime,
                    adapter,
                    user,
                    realm="qi_gathering",
                    location="xuantian.spirit_field",
                    inventory={"item.food.cloud_tea": 2},
                )
                used = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "tea-use", "tea-use-op"),
                    "使用 云灵茶",
                )
                assert used.code == "ITEM_USED"
                assert "提高 **5%**" in used.message
                assert "bp" not in used.message
                replay = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "tea-replay", "tea-use-op"),
                    "使用 item.food.cloud_tea",
                )
                assert replay.data["idempotent_replay"] is True
                duplicate = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "tea-duplicate", "tea-duplicate-op"),
                    "使用 云茶",
                )
                assert duplicate.code == "ITEM_EFFECT_ALREADY_PENDING"
                started = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "cultivation-start", "cultivation-tea-op"),
                    "开始修炼",
                )
                assert started.code == "CULTIVATION_STARTED"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    snapshot_text, effects_text = connection.execute(
                        "SELECT snapshot_json, item_effects_json FROM cultivation_sessions JOIN players ON players.id=cultivation_sessions.player_id"
                    ).fetchone()
                snapshot = json.loads(snapshot_text)
                assert snapshot["pending_state_bonus_bp"] == 500
                assert snapshot["state_bp"] == 10500
                assert json.loads(effects_text) == {}
                await runtime.close()

    asyncio.run(run())


def test_mist_barrier_reduces_risk_once_and_expires_for_qq_onebot() -> None:
    async def run() -> None:
        for adapter in ("qq.official", "onebot.v11"):
            with TemporaryDirectory() as data_dir:
                runtime = create_runtime(data_dir=Path(data_dir) / adapter)
                user = f"barrier-{adapter}"
                await _player(
                    runtime,
                    adapter,
                    user,
                    realm="golden_core",
                    location="cave.mist_grotto_2",
                    inventory={"item.array.mist_barrier": 1},
                )
                used = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "barrier-use", "barrier-op"),
                    "使用 迷雾屏障阵 雾隐洞天二层",
                )
                assert used.code == "ITEM_USED"
                assert "降低 **5%**" in used.message
                assert "bp" not in used.message
                replay = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "barrier-replay", "barrier-op"),
                    "使用 迷雾屏障阵 雾隐洞天二层",
                )
                assert replay.data["idempotent_replay"] is True
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    barrier_id, expires_at = connection.execute(
                        "SELECT barrier_id, expires_at FROM mist_barrier_instances"
                    ).fetchone()
                    connection.execute(
                        "UPDATE players SET inventory_json=? WHERE platform=? AND platform_user_id=?",
                        (json.dumps({"item.array.mist_barrier": 1}), adapter, user),
                    )
                started = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "explore-start", "explore-barrier-op"),
                    "开始探索 洞天二层探索",
                )
                assert started.code == "EXPLORATION_STARTED"
                assert started.data["risk_reduction_bp"] == 500
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    snapshot = json.loads(connection.execute("SELECT snapshot_json FROM exploration_sessions").fetchone()[0])
                    assert snapshot["barrier_id"] == barrier_id
                    assert snapshot["battle_chance_bp"] == 3500
                    connection.execute(
                        "UPDATE mist_barrier_instances SET expires_at=? WHERE barrier_id=?",
                        ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(), barrier_id),
                    )
                assert await runtime.repository.expire_mist_barriers() == 1
                assert await runtime.repository.expire_mist_barriers() == 0
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    assert connection.execute(
                        "SELECT status FROM mist_barrier_instances WHERE barrier_id=?", (barrier_id,)
                    ).fetchone()[0] == "expired"
                await runtime.close()

    asyncio.run(run())


def test_item_content_aliases_and_labels_follow_the_active_content_bundle(tmp_path: Path) -> None:
    content_dir = tmp_path / "content"
    shutil.copytree(Path(__file__).parents[1] / "data", content_dir)
    materials = content_dir / "道具" / "材料.json"
    document = json.loads(materials.read_text(encoding="utf-8"))
    tea = next(row for row in document["records"] if row["key"] == "item.food.cloud_tea")
    tea["name"] = "青灵茶"
    tea["aliases"] = ["青茶"]
    materials.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    content = ContentBundle.load(content_dir)
    market_item = resolve_market_item("青茶", content)
    assert market_item.key == "item.food.cloud_tea"
    assert market_item.label == "青灵茶"

    async def run() -> None:
        runtime = create_runtime(data_dir=content_dir)
        adapter, user = "onebot.v11", "content-backed-item"
        await _player(
            runtime,
            adapter,
            user,
            realm="qi_gathering",
            location="xuantian.spirit_field",
            inventory={"item.food.cloud_tea": 1},
        )
        result = await runtime.adapters.dispatch(
            adapter,
            _context(adapter, user, "content-use", "content-use-op"),
            "使用 青茶",
        )
        assert result.ok
        assert "青灵茶已饮尽" in result.message
        await runtime.close()

    asyncio.run(run())


def test_item_original_name_replays_after_content_rename_and_alias_removal(tmp_path: Path) -> None:
    source_data = Path(__file__).parents[1] / "data"

    async def run() -> None:
        for adapter in ("qq.official", "onebot.v11"):
            content_dir = tmp_path / adapter.replace(".", "-")
            shutil.copytree(source_data, content_dir)
            runtime = create_runtime(data_dir=content_dir)
            user = f"item-history-{adapter}"
            await _player(
                runtime,
                adapter,
                user,
                realm="qi_gathering",
                location="xuantian.spirit_field",
                inventory={"item.food.cloud_tea": 1},
            )
            used = await runtime.adapters.dispatch(
                adapter,
                _context(adapter, user, "history-use", "history-use-op"),
                "使用 云灵茶",
            )
            assert used.code == "ITEM_USED"
            await runtime.close()

            materials = content_dir / "道具" / "材料.json"
            document = json.loads(materials.read_text(encoding="utf-8"))
            tea = next(row for row in document["records"] if row["key"] == "item.food.cloud_tea")
            tea["name"] = "玄灵茶"
            tea["aliases"] = ["玄茶"]
            tea["status"] = "closed"
            materials.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            runtime = create_runtime(data_dir=content_dir)
            replay = await runtime.adapters.dispatch(
                adapter,
                _context(adapter, user, "history-replay", "history-use-op"),
                "使用 云灵茶",
            )
            assert replay.code == "ITEM_USED"
            assert replay.data["idempotent_replay"] is True
            assert "云灵茶已饮尽" in replay.message
            conflict = await runtime.adapters.dispatch(
                adapter,
                _context(adapter, user, "history-conflict", "history-use-op"),
                "使用 玄茶",
            )
            assert conflict.code == "OPERATION_CONFLICT"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                inventory, operation_count = connection.execute(
                    "SELECT p.inventory_json, (SELECT COUNT(*) FROM operations WHERE operation_id=?) "
                    "FROM players p WHERE p.platform=? AND p.platform_user_id=?",
                    ("history-use-op", adapter, user),
                ).fetchone()
            assert json.loads(inventory) == {}
            assert operation_count == 1
            await runtime.close()

    asyncio.run(run())


def test_item_replay_rejects_corrupt_result_without_writing_again() -> None:
    async def run() -> None:
        for adapter in ("qq.official", "onebot.v11"):
            with TemporaryDirectory() as data_dir:
                runtime = create_runtime(data_dir=Path(data_dir))
                user = f"item-corrupt-{adapter}"
                await _player(
                    runtime,
                    adapter,
                    user,
                    realm="qi_gathering",
                    location="xuantian.spirit_field",
                    inventory={"item.food.cloud_tea": 1},
                )
                used = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "corrupt-use", "corrupt-op"),
                    "使用 云灵茶",
                )
                assert used.code == "ITEM_USED"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    payload = json.loads(
                        connection.execute(
                            "SELECT result_json FROM operations WHERE operation_id=?", ("corrupt-op",)
                        ).fetchone()[0]
                    )
                    payload["effect"] = {}
                    connection.execute(
                        "UPDATE operations SET result_json=? WHERE operation_id=?",
                        (json.dumps(payload, ensure_ascii=False, sort_keys=True), "corrupt-op"),
                    )
                replay = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "corrupt-replay", "corrupt-op"),
                    "使用 云灵茶",
                )
                assert replay.code == "PERSISTENCE_ERROR"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    inventory, operation_count = connection.execute(
                        "SELECT p.inventory_json, (SELECT COUNT(*) FROM operations WHERE operation_id=?) "
                        "FROM players p WHERE p.platform=? AND p.platform_user_id=?",
                        ("corrupt-op", adapter, user),
                    ).fetchone()
                assert json.loads(inventory) == {}
                assert operation_count == 1
                await runtime.close()

    asyncio.run(run())


def test_item_operation_conflict_does_not_consume_a_second_item() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=Path(data_dir))
            adapter, user = "qq.official", "item-operation-conflict"
            await _player(
                runtime,
                adapter,
                user,
                realm="qi_gathering",
                location="xuantian.spirit_field",
                inventory={"item.food.cloud_tea": 1, "item.array.mist_barrier": 1},
            )
            first = await runtime.adapters.dispatch(
                adapter,
                _context(adapter, user, "first", "same-item-operation"),
                "使用 云灵茶",
            )
            assert first.code == "ITEM_USED"
            conflict = await runtime.adapters.dispatch(
                adapter,
                _context(adapter, user, "conflict", "same-item-operation"),
                "使用 迷雾屏障阵",
            )
            assert conflict.code == "OPERATION_CONFLICT"
            assert "请求编号" not in conflict.message
            with sqlite3.connect(runtime.settings.database_path) as connection:
                inventory = json.loads(
                    connection.execute(
                        "SELECT inventory_json FROM players WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    ).fetchone()[0]
                )
            assert inventory == {"item.array.mist_barrier": 1}
            await runtime.close()

    asyncio.run(run())


def test_food_use_changes_player_state_through_shared_transaction() -> None:
    async def run() -> None:
        for adapter in ("qq.official", "onebot.v11"):
            with TemporaryDirectory() as data_dir:
                runtime = create_runtime(data_dir=Path(data_dir) / adapter)
                user = f"food-{adapter}"
                await _player(
                    runtime,
                    adapter,
                    user,
                    realm="qi_gathering",
                    location="xuantian.spirit_field",
                    inventory={"item.food.coarse_spirit_rice": 2},
                )
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE players SET stamina=10 WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    )
                used = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "food-use", "food-use-op"),
                    "使用 粗糙灵米 体力",
                )
                assert used.code == "ITEM_USED"
                assert "恢复 **3**" in used.message
                assert "bp" not in used.message
                replay = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "food-replay", "food-use-op"),
                    "使用 粗糙灵米 体力",
                )
                assert replay.data["idempotent_replay"] is True
                cooldown = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "food-cooldown", "food-cooldown-op"),
                    "使用 粗糙灵米 精力",
                )
                assert cooldown.code == "ITEM_COOLDOWN"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    stamina, energy, inventory = connection.execute(
                        "SELECT stamina, energy, inventory_json FROM players WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    ).fetchone()
                assert (stamina, energy) == (13, 30)
                assert json.loads(inventory) == {"item.food.coarse_spirit_rice": 1}
                await runtime.close()

    asyncio.run(run())


def test_food_recovery_is_capped_idempotent_and_cooldown_survives_restart() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            now = [datetime(2026, 10, 5, tzinfo=timezone.utc)]
            runtime = create_runtime(data_dir=Path(data_dir), clock=lambda: now[0])
            for adapter in ("qq.official", "onebot.v11"):
                user = f"food-{adapter}"
                await _player(
                    runtime,
                    adapter,
                    user,
                    realm="qi_gathering",
                    location="xuantian.spirit_field",
                    inventory={"item.food.coarse_spirit_rice": 2},
                )
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE players SET stamina=29, energy=20 WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    )
                used = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, f"{adapter}-food-use", f"{adapter}-food-use-op"),
                    "使用 粗糙灵米 体力",
                )
                assert used.code == "ITEM_USED"
                assert used.data["effect"]["resource"] == "stamina"
                assert used.data["effect"]["requested"] == 3
                assert used.data["effect"]["restored"] == 1

                with sqlite3.connect(runtime.settings.database_path) as connection:
                    inventory, stamina, energy, cooldown = connection.execute(
                        "SELECT inventory_json, stamina, energy, "
                        "(SELECT cooldown_until FROM item_use_cooldowns "
                        " WHERE player_id=players.id AND item_key='item.food.coarse_spirit_rice') "
                        "FROM players WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    ).fetchone()
                assert json.loads(inventory) == {"item.food.coarse_spirit_rice": 1}
                assert (stamina, energy) == (30, 20)
                assert cooldown is not None

            await runtime.close()
            runtime = create_runtime(data_dir=Path(data_dir), clock=lambda: now[0])
            for adapter in ("qq.official", "onebot.v11"):
                user = f"food-{adapter}"
                replay = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, f"{adapter}-food-replay", f"{adapter}-food-use-op"),
                    "使用 item.food.coarse_spirit_rice 体力",
                )
                assert replay.data["idempotent_replay"] is True
                input_conflict = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, f"{adapter}-food-input-conflict", f"{adapter}-food-use-op"),
                    "使用 粗糙灵米 精力",
                )
                assert input_conflict.code == "OPERATION_CONFLICT"
                cooling = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, f"{adapter}-food-cooling", f"{adapter}-food-cooling-op"),
                    "使用 粗糙灵米 精力",
                )
                assert cooling.code == "ITEM_COOLDOWN"

            now[0] += timedelta(minutes=11)
            for adapter in ("qq.official", "onebot.v11"):
                user = f"food-{adapter}"
                recovered = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, f"{adapter}-food-second", f"{adapter}-food-second-op"),
                    "使用 粗糙灵米 精力",
                )
                assert recovered.code == "ITEM_USED"
                assert recovered.data["effect"]["resource"] == "energy"
                assert recovered.data["effect"]["restored"] == 3
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    inventory, energy = connection.execute(
                        "SELECT inventory_json, energy FROM players WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    ).fetchone()
                assert json.loads(inventory) == {}
                assert energy == 23
            await runtime.close()

    asyncio.run(run())


def test_food_content_amount_is_read_from_json_for_both_adapters(tmp_path: Path) -> None:
    content_dir = tmp_path / "content"
    shutil.copytree(Path(__file__).parents[1] / "data", content_dir)
    materials = content_dir / "道具" / "材料.json"
    document = json.loads(materials.read_text(encoding="utf-8"))
    rice = next(row for row in document["records"] if row["key"] == "item.food.coarse_spirit_rice")
    rice["effects"][0]["amount"] = 7
    materials.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    async def run() -> None:
        runtime = create_runtime(data_dir=content_dir)
        for adapter in ("qq.official", "onebot.v11"):
            user = f"food-content-{adapter}"
            await _player(
                runtime,
                adapter,
                user,
                realm="qi_gathering",
                location="xuantian.spirit_field",
                inventory={"item.food.coarse_spirit_rice": 1},
            )
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE players SET stamina=10 WHERE platform=? AND platform_user_id=?",
                    (adapter, user),
                )
            used = await runtime.adapters.dispatch(
                adapter,
                _context(adapter, user, f"{adapter}-food-content", f"{adapter}-food-content-op"),
                "使用 粗糙灵米 体力",
            )
            assert used.code == "ITEM_USED"
            assert used.data["effect"]["requested"] == 7
            assert used.data["effect"]["restored"] == 7
            assert "版本" not in used.message
        await runtime.close()

    asyncio.run(run())


def test_food_recovery_choices_follow_content_resources(tmp_path: Path) -> None:
    content_dir = tmp_path / "content"
    shutil.copytree(Path(__file__).parents[1] / "data", content_dir)
    materials = content_dir / "道具" / "材料.json"
    document = json.loads(materials.read_text(encoding="utf-8"))
    rice = next(row for row in document["records"] if row["key"] == "item.food.coarse_spirit_rice")
    rice["effects"][0]["resources"] = ["stamina"]
    materials.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    async def run() -> None:
        runtime = create_runtime(data_dir=content_dir)
        for adapter in ("qq.official", "onebot.v11"):
            user = f"food-choice-{adapter}"
            await _player(
                runtime,
                adapter,
                user,
                realm="qi_gathering",
                location="xuantian.spirit_field",
                inventory={"item.food.coarse_spirit_rice": 1},
            )
            invalid = await runtime.adapters.dispatch(
                adapter,
                _context(adapter, user, f"{adapter}-invalid", f"{adapter}-invalid-op"),
                "使用 粗糙灵米 精力",
            )
            assert invalid.code == "ITEM_CHOICE_INVALID"
            assert "体力" in invalid.message
            with sqlite3.connect(runtime.settings.database_path) as connection:
                inventory, operation_count = connection.execute(
                    "SELECT inventory_json, (SELECT COUNT(*) FROM operations WHERE operation_id=?) "
                    "FROM players WHERE platform=? AND platform_user_id=?",
                    (f"{adapter}-invalid-op", adapter, user),
                ).fetchone()
            assert json.loads(inventory) == {"item.food.coarse_spirit_rice": 1}
            assert operation_count == 0
        await runtime.close()

    asyncio.run(run())


def test_food_write_failure_rolls_back_and_operation_can_retry() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=Path(data_dir))
            for adapter in ("qq.official", "onebot.v11"):
                user = f"food-recovery-{adapter}"
                operation_id = f"{adapter}-food-recovery-op"
                await _player(
                    runtime,
                    adapter,
                    user,
                    realm="qi_gathering",
                    location="xuantian.spirit_field",
                    inventory={"item.food.coarse_spirit_rice": 1},
                )
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE players SET stamina=20 WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    )
                    connection.execute(
                        f"""
                        CREATE TRIGGER fail_food_operation_{adapter.replace('.', '_')}
                        BEFORE INSERT ON operations
                        WHEN NEW.operation_id = '{operation_id}'
                        BEGIN SELECT RAISE(ABORT, 'injected food operation failure'); END
                        """
                    )
                failed = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, f"{adapter}-food-failed", operation_id),
                    "使用 粗糙灵米 体力",
                )
                assert failed.code == "PERSISTENCE_ERROR"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    inventory, stamina, cooldown, operation_count = connection.execute(
                        "SELECT p.inventory_json, p.stamina, c.cooldown_until, "
                        "(SELECT COUNT(*) FROM operations WHERE operation_id=?) "
                        "FROM players p LEFT JOIN item_use_cooldowns c ON c.player_id=p.id "
                        "AND c.item_key='item.food.coarse_spirit_rice' "
                        "WHERE p.platform=? AND p.platform_user_id=?",
                        (operation_id, adapter, user),
                    ).fetchone()
                    connection.execute(f"DROP TRIGGER fail_food_operation_{adapter.replace('.', '_')}")
                assert json.loads(inventory) == {"item.food.coarse_spirit_rice": 1}
                assert stamina == 20
                assert cooldown is None
                assert operation_count == 0

                retried = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, f"{adapter}-food-retry", operation_id),
                    "使用 粗糙灵米 体力",
                )
                assert retried.code == "ITEM_USED"
                assert retried.data["effect"]["restored"] == 3
            await runtime.close()

    asyncio.run(run())


def test_usable_item_rejects_an_unknown_content_location(tmp_path: Path) -> None:
    content_dir = tmp_path / "content"
    shutil.copytree(Path(__file__).parents[1] / "data", content_dir)
    formation_file = content_dir / "阵法" / "阵法.json"
    document = json.loads(formation_file.read_text(encoding="utf-8"))
    barrier = next(row for row in document["records"] if row["key"] == "item.array.mist_barrier")
    barrier["effects"][0]["location_key"] = "cave.unknown"
    formation_file.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    content = ContentBundle.load(content_dir)
    with pytest.raises(ContentError, match="location_key"):
        resolve_item("item.array.mist_barrier", content)


def test_restore_choice_rejects_invalid_content_contract(tmp_path: Path) -> None:
    for index, (field, value, message) in enumerate(
        (
            ("resources", [], "resources"),
            ("resources", ["spirit"], "resources"),
            ("cooldown_seconds", 0, "cooldown_seconds"),
            ("amount", True, "amount"),
        )
    ):
        content_dir = tmp_path / str(index)
        shutil.copytree(Path(__file__).parents[1] / "data", content_dir)
        materials = content_dir / "道具" / "材料.json"
        document = json.loads(materials.read_text(encoding="utf-8"))
        rice = next(row for row in document["records"] if row["key"] == "item.food.coarse_spirit_rice")
        rice["effects"][0][field] = value
        materials.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        content = ContentBundle.load(content_dir)
        with pytest.raises(ContentError, match=message):
            resolve_item("item.food.coarse_spirit_rice", content)


def test_cloud_sword_production_materializes_equipment_instance() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            adapter, user = "onebot.v11", "cloud-sword-instance"
            await _player(
                runtime,
                adapter,
                user,
                realm="golden_core",
                location="cave.mist_grotto_2",
                subprofession="artifice",
                inventory={
                    "item.material.cloud_iron": 4,
                    "item.mat.array_sand": 1,
                    "item.mat.wood": 2,
                    "item.tool.basic_hammer": 1,
                },
            )
            claimed = await runtime.adapters.dispatch(
                adapter,
                _context(adapter, user, "facility-claim"),
                "认领设施槽位 炼器台",
            )
            assert claimed.code == "FACILITY_SLOT_CLAIMED"
            await runtime.repository.maintain_facilities()
            operation = next(
                f"cloud-sword-{index}"
                for index in range(256)
                if random_quality_bp(f"cloud-sword-{index}") >= 1000
            )
            started = await runtime.adapters.dispatch(
                adapter,
                _context(adapter, user, "production-start", operation),
                "开始生产 云纹剑",
            )
            assert started.code == "PRODUCTION_STARTED"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE production_orders SET ends_at=? WHERE order_id=?",
                    ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(), started.data["order_id"]),
                )
            settled = await runtime.adapters.dispatch(
                adapter,
                _context(adapter, user, "production-settle"),
                "领取生产",
            )
            assert settled.data["outputs"] == {"item.weapon.cloud_sword": 1}
            with sqlite3.connect(runtime.settings.database_path) as connection:
                instance = connection.execute(
                    "SELECT item_key, status, durability_bp FROM equipment_instances WHERE player_id=(SELECT id FROM players WHERE platform=? AND platform_user_id=?)",
                    (adapter, user),
                ).fetchone()
                inventory = json.loads(connection.execute("SELECT inventory_json FROM players WHERE platform=? AND platform_user_id=?", (adapter, user)).fetchone()[0])
            assert instance[0:2] == ("item.weapon.cloud_sword", "active")
            assert 8500 <= instance[2] <= 10000
            assert inventory.get("item.weapon.cloud_sword", 0) == 0
            await runtime.close()

    asyncio.run(run())


def test_bound_production_items_are_not_market_tradeable() -> None:
    for item in ("item.pill.core_condense", "item.pill.golden_core_guard", "item.array.mist_barrier"):
        try:
            resolve_market_item(item)
        except ValueError:
            continue
        raise AssertionError(f"{item} unexpectedly became tradeable")

    # A content record may declare a character-bound default while still
    # allowing unbound stacks to enter the market; active bindings are checked
    # by the repository transaction.
    character_bound_tradeable = resolve_market_item("item.weapon.green_frost_sword")
    assert character_bound_tradeable.key == "item.weapon.green_frost_sword"
