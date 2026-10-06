from __future__ import annotations

import asyncio
import json
import sqlite3
import shutil
import pytest
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory
from pathlib import Path

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError
from nonebot_plugin_xiuxian_3.xiuxian.advancement.constitution_rules import constitution_definitions
from nonebot_plugin_xiuxian_3.xiuxian.stats.rules import build_stat_preview


class MutableClock:
    def __init__(self, value: datetime):
        self.value = value

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **kwargs: int) -> None:
        self.value += timedelta(**kwargs)


def _context(user_id: str, request_id: str, *, operation_id: str = "") -> CommandContext:
    return CommandContext(adapter="web", user_id=user_id, request_id=request_id, operation_id=operation_id)


async def _enter_cultivator(runtime, user_id: str) -> None:
    commands = (
        "开始修仙",
        "寻仙问道",
        "完成引导 阅读",
        "前往近郊",
        "完成引导 采集",
        "完成引导 炼丹",
        "选择道途 体修",
    )
    for index, command in enumerate(commands):
        result = await runtime.dispatch(_context(user_id, f"setup-{index}"), command)
        assert result.ok, (command, result.code, result.message)


def _add_item(runtime, user_id: str, item_key: str, quantity: int) -> None:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        row = connection.execute(
            "SELECT inventory_json FROM players WHERE platform_user_id = ?", (user_id,)
        ).fetchone()
        inventory = json.loads(row[0])
        inventory[item_key] = int(inventory.get(item_key, 0)) + quantity
        connection.execute(
            "UPDATE players SET inventory_json = ? WHERE platform_user_id = ?",
            (json.dumps(inventory, ensure_ascii=False, sort_keys=True), user_id),
        )


def test_constitution_duplicate_name_is_rejected(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    shutil.copytree(Path(__file__).parents[1] / "data", data_dir)
    path = data_dir / "养成" / "体质.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    document["records"][1]["name"] = document["records"][0]["name"]
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        constitution_definitions(ContentBundle.load(data_dir))
    except ContentError as exc:
        assert "duplicated" in str(exc)
    else:
        raise AssertionError("duplicate constitution names must be rejected")


def test_constitution_preview_selection_and_profile_are_idempotent() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            user = "constitution-select"
            preview = await runtime.dispatch(_context(user, "preview"), "体质预览")
            assert preview.ok
            assert all(label in preview.message for label in ("铁骨", "灵根", "风行", "巧手", "福缘"))
            assert "御兽" not in preview.message

            before = await runtime.dispatch(_context(user, "before"), "选择体质 铁骨")
            assert before.code == "PLAYER_NOT_FOUND"
            await _enter_cultivator(runtime, user)

            selected = await runtime.dispatch(
                _context(user, "select", operation_id="constitution-select-1"), "选择体质 铁骨"
            )
            assert selected.code == "CONSTITUTION_SELECTED"
            assert selected.data["constitution_key"] == "constitution.iron_bone"
            replay = await runtime.dispatch(
                _context(user, "replay", operation_id="constitution-select-1"), "选择体质 铁骨"
            )
            assert replay.data["idempotent_replay"] is True
            assert replay.data["effect"] == selected.data["effect"]

            duplicate = await runtime.dispatch(_context(user, "duplicate"), "选择体质 风行")
            assert duplicate.code == "CONSTITUTION_ALREADY_SELECTED"
            profile = await runtime.dispatch(_context(user, "profile"), "我的体质")
            assert profile.code == "CONSTITUTION_PROFILE"
            assert profile.data["label"] == "铁骨"
            await runtime.close()

    asyncio.run(run())


def test_constitution_operation_replay_uses_frozen_result_after_content_closes_choice(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    shutil.copytree(Path(__file__).parents[1] / "data", data_dir)

    async def run() -> None:
        user = "constitution-replay-content-change"
        runtime = create_runtime(data_dir=data_dir)
        await _enter_cultivator(runtime, user)
        selected = await runtime.dispatch(
            _context(user, "select", operation_id="constitution-replay-content-change-1"),
            "选择体质 铁骨",
        )
        assert selected.code == "CONSTITUTION_SELECTED"
        await runtime.close()

        constitution_path = data_dir / "养成" / "体质.json"
        document = json.loads(constitution_path.read_text(encoding="utf-8"))
        constitution = next(
            row for row in document["records"] if row["key"] == "constitution.iron_bone"
        )
        constitution["name"] = "已封体质"
        constitution["status"] = "locked"
        constitution["effect"]["value"] = 1
        constitution_path.write_text(
            json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        runtime = create_runtime(data_dir=data_dir)
        replay = await runtime.repository.select_constitution(
            platform="web",
            platform_user_id=user,
            constitution_key="铁骨",
            operation_id="constitution-replay-content-change-1",
        )
        assert replay.already_completed is True
        assert replay.label == "铁骨"
        assert replay.effect == {"type": "max_hp_bp", "value": 300}
        profile = await runtime.repository.get_constitution(
            platform="web", platform_user_id=user
        )
        assert profile.label == "铁骨"
        assert profile.effect == {"type": "max_hp_bp", "value": 300}
        await runtime.close()

    asyncio.run(run())


def test_spirit_root_is_frozen_into_training_spectator_stats() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            user = "constitution-spirit-root"
            await _enter_cultivator(runtime, user)
            selected = await runtime.dispatch(
                _context(user, "select", operation_id="constitution-spirit-root-select"),
                "选择体质 灵根",
            )
            assert selected.code == "CONSTITUTION_SELECTED"
            assert selected.data["effect"] == {"type": "max_mana_bp", "value": 300}

            profile = await runtime.dispatch(_context(user, "profile"), "我的体质")
            assert profile.data["effect"] == {"type": "max_mana_bp", "value": 300}

            returned = await runtime.dispatch(_context(user, "return"), "返回新手城")
            assert returned.ok
            preview = await runtime.dispatch(_context(user, "battle"), "开始训练战")
            assert preview.code == "TRAINING_SPECTATOR"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.row_factory = sqlite3.Row
                player = connection.execute(
                    "SELECT * FROM players WHERE platform_user_id = ?", (user,)
                ).fetchone()
                snapshot, _ = runtime.repository._spectator_player_snapshot(connection, player)
            base_mana = build_stat_preview(dict(player), runtime.content)["derived_stats"]["max_mp"]
            assert snapshot["stats"]["max_mana"] == base_mana + base_mana * 300 // 10_000
            await runtime.close()

    asyncio.run(run())


def test_modified_constitution_json_changes_frozen_combat_stats(tmp_path: Path) -> None:
    content_dir = tmp_path / "content"
    shutil.copytree(Path(__file__).parents[1] / "data", content_dir)
    body_path = content_dir / "养成" / "体质.json"
    document = json.loads(body_path.read_text(encoding="utf-8"))
    iron_bone = next(row for row in document["records"] if row["key"] == "constitution.iron_bone")
    iron_bone["effect"]["value"] = 1_250
    body_path.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")

    async def run() -> None:
        runtime = create_runtime(data_dir=content_dir)
        user = "constitution-combat-config"
        await _enter_cultivator(runtime, user)
        returned = await runtime.dispatch(_context(user, "return"), "返回新手城")
        assert returned.ok
        selected = await runtime.dispatch(_context(user, "select"), "选择体质 铁骨")
        assert selected.ok
        with sqlite3.connect(runtime.settings.database_path) as connection:
            player = connection.execute(
                "SELECT max_hp, qualification_json, spirit_stones, cultivation, total_cultivation, stamina, energy "
                "FROM players WHERE platform_user_id = ?",
                (user,),
            ).fetchone()
        body = json.loads(player[1]).get("body", 0)
        before = player[2:]

        started = await runtime.dispatch(
            _context(user, "battle", operation_id="constitution-combat-start"), "开始训练战"
        )
        assert started.code == "TRAINING_SPECTATOR"
        assert started.data["status"] == "spectator"
        assert started.data["actions"]
        with sqlite3.connect(runtime.settings.database_path) as connection:
            current = connection.execute(
                "SELECT max_hp, spirit_stones, cultivation, total_cultivation, stamina, energy "
                "FROM players WHERE platform_user_id = ?",
                (user,),
            ).fetchone()
        assert current[0] == player[0]
        assert current[1:] == before
        await runtime.close()

    asyncio.run(run())


def test_modified_spirit_root_json_changes_frozen_mana_stats(tmp_path: Path) -> None:
    content_dir = tmp_path / "content"
    shutil.copytree(Path(__file__).parents[1] / "data", content_dir)
    body_path = content_dir / "养成" / "体质.json"
    document = json.loads(body_path.read_text(encoding="utf-8"))
    spirit_root = next(row for row in document["records"] if row["key"] == "constitution.spirit_root")
    spirit_root["effect"]["value"] = 1_250
    body_path.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")

    async def run() -> None:
        runtime = create_runtime(data_dir=content_dir)
        user = "constitution-spirit-root-config"
        await _enter_cultivator(runtime, user)
        assert (await runtime.dispatch(_context(user, "return"), "返回新手城")).ok
        selected = await runtime.dispatch(_context(user, "select"), "选择体质 灵根")
        assert selected.data["effect"] == {"type": "max_mana_bp", "value": 1_250}
        with sqlite3.connect(runtime.settings.database_path) as connection:
            connection.row_factory = sqlite3.Row
            player = connection.execute(
                "SELECT * FROM players WHERE platform_user_id = ?", (user,)
            ).fetchone()
            snapshot, _ = runtime.repository._spectator_player_snapshot(connection, player)
        base_mana = build_stat_preview(dict(player), runtime.content)["derived_stats"]["max_mp"]
        assert snapshot["stats"]["max_mana"] == base_mana + base_mana * 1_250 // 10_000
        await runtime.close()

    asyncio.run(run())


def test_constitution_selection_respects_long_action_lock() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            user = "constitution-busy"
            await _enter_cultivator(runtime, user)
            started = await runtime.dispatch(_context(user, "retreat"), "开始闭关")
            assert started.ok
            blocked = await runtime.dispatch(_context(user, "select"), "选择体质 风行")
            assert blocked.code == "CONSTITUTION_BUSY"
            await runtime.close()

    asyncio.run(run())


def test_constitution_selection_is_unique_under_concurrency() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            user = "constitution-concurrent"
            await _enter_cultivator(runtime, user)
            results = await asyncio.gather(
                *(
                    runtime.dispatch(
                        _context(user, f"select-{index}", operation_id=f"constitution-{index}"),
                        "选择体质 福缘",
                    )
                    for index in range(12)
                )
            )
            assert sum(result.ok for result in results) == 1
            assert {result.code for result in results} == {
                "CONSTITUTION_SELECTED",
                "CONSTITUTION_ALREADY_SELECTED",
            }
            with sqlite3.connect(runtime.settings.database_path) as connection:
                count = connection.execute(
                    "SELECT COUNT(*) FROM constitution_profiles WHERE player_id = (SELECT id FROM players WHERE platform_user_id = ?)",
                    (user,),
                ).fetchone()[0]
            assert count == 1
            await runtime.close()

    asyncio.run(run())


def test_constitution_reshape_consumes_token_and_enforces_cooldown() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            user = "constitution-reshape"
            await _enter_cultivator(runtime, user)
            selected = await runtime.dispatch(_context(user, "select"), "选择体质 铁骨")
            assert selected.ok
            _add_item(runtime, user, "item.token.constitution_reset", 1)

            reshaped = await runtime.dispatch(
                _context(user, "reshape", operation_id="constitution-reshape-1"), "重塑体质 风行"
            )
            assert reshaped.code == "CONSTITUTION_RESHAPED"
            assert reshaped.data["constitution_key"] == "constitution.wind_step"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                inventory = json.loads(
                    connection.execute(
                        "SELECT inventory_json FROM players WHERE platform_user_id = ?", (user,)
                    ).fetchone()[0]
                )
            assert inventory.get("item.token.constitution_reset", 0) == 0

            replay = await runtime.dispatch(
                _context(user, "reshape-replay", operation_id="constitution-reshape-1"), "重塑体质 风行"
            )
            assert replay.data["idempotent_replay"] is True
            cooldown = await runtime.dispatch(_context(user, "cooldown"), "重塑体质 巧手")
            assert cooldown.code == "CONSTITUTION_COOLDOWN"

            clock.advance(days=30)
            _add_item(runtime, user, "item.token.constitution_reset", 1)
            reshaped_again = await runtime.dispatch(
                _context(user, "reshape-again", operation_id="constitution-reshape-2"), "重塑体质 巧手"
            )
            assert reshaped_again.code == "CONSTITUTION_RESHAPED"
            assert reshaped_again.data["reshape_count"] == 2
            await runtime.close()

    asyncio.run(run())


def test_constitution_rules_follow_modified_content(tmp_path: Path) -> None:
    source_data = Path(__file__).parents[1] / "data"
    content_dir = tmp_path / "content"
    shutil.copytree(source_data, content_dir)

    rules_path = content_dir / "养成" / "规则.json"
    rules_document = json.loads(rules_path.read_text(encoding="utf-8"))
    reshape_rules = next(
        row for row in rules_document["records"] if row["key"] == "constitution.reshape"
    )
    reshape_rules["reset_item_key"] = "item.token.rename_card"
    reshape_rules["cooldown_seconds"] = 3_600
    rules_path.write_text(
        json.dumps(rules_document, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
        runtime = create_runtime(data_dir=content_dir, clock=clock)
        preview = await runtime.dispatch(_context("preview", "custom-preview"), "体质预览")
        assert "改名卡" in preview.message
        assert "1 小时" in preview.message

        user = "constitution-custom-rules"
        await _enter_cultivator(runtime, user)
        assert (await runtime.dispatch(_context(user, "select-custom"), "选择体质 铁骨")).ok
        _add_item(runtime, user, "item.token.rename_card", 1)
        reshaped = await runtime.dispatch(
            _context(user, "reshape-custom", operation_id="constitution-custom-1"),
            "重塑体质 风行",
        )
        assert reshaped.code == "CONSTITUTION_RESHAPED"
        with sqlite3.connect(runtime.settings.database_path) as connection:
            inventory = json.loads(
                connection.execute(
                    "SELECT inventory_json FROM players WHERE platform_user_id = ?", (user,)
                ).fetchone()[0]
            )
        assert "item.token.rename_card" not in inventory

        blocked = await runtime.dispatch(_context(user, "cooldown-custom"), "重塑体质 福缘")
        assert blocked.code == "CONSTITUTION_COOLDOWN"
        assert "1 小时后" in blocked.message

        clock.advance(hours=1)
        _add_item(runtime, user, "item.token.rename_card", 1)
        next_reshape = await runtime.dispatch(
            _context(user, "reshape-custom-again", operation_id="constitution-custom-2"),
            "重塑体质 福缘",
        )
        assert next_reshape.code == "CONSTITUTION_RESHAPED"
        await runtime.close()

    asyncio.run(run())


def test_constitution_reshape_requires_existing_profile_and_token() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            user = "constitution-missing"
            await _enter_cultivator(runtime, user)
            missing = await runtime.dispatch(_context(user, "reshape"), "重塑体质 福缘")
            assert missing.code == "CONSTITUTION_NOT_SELECTED"
            selected = await runtime.dispatch(_context(user, "select"), "选择体质 福缘")
            assert selected.ok
            no_token = await runtime.dispatch(_context(user, "reshape"), "重塑体质 巧手")
            assert no_token.code == "RESOURCE_INSUFFICIENT"
            await runtime.close()

    asyncio.run(run())
