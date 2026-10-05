from __future__ import annotations

import asyncio
import json
import sqlite3
import shutil
import pytest
from tempfile import TemporaryDirectory
from pathlib import Path

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError, bundled_content
from nonebot_plugin_xiuxian_3.xiuxian.advancement.skill_rules import (
    available_skill_keys,
    effective_skill_effect,
    skill_definition,
    skill_definitions,
)


def _context(
    user_id: str,
    request_id: str,
    *,
    adapter: str = "web",
    operation_id: str = "",
) -> CommandContext:
    return CommandContext(adapter=adapter, user_id=user_id, request_id=request_id, operation_id=operation_id)


async def _enter_cultivator(runtime, user_id: str, *, adapter: str = "web") -> None:
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
        result = await runtime.dispatch(_context(user_id, f"setup-{index}", adapter=adapter), command)
        assert result.ok, (command, result.code, result.message)


def _set_resources(runtime, user_id: str, *, insights: int, stones: int, adapter: str = "web") -> None:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE players SET skill_insights = ?, spirit_stones = ? WHERE platform = ? AND platform_user_id = ?",
            (insights, stones, adapter, user_id),
        )


def test_skill_duplicate_alias_is_rejected(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    shutil.copytree(Path(__file__).parents[1] / "data", data_dir)
    path = data_dir / "技能" / "技能.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    player_skills = [row for row in document["records"] if row.get("owner_type") == "player"]
    player_skills[1]["aliases"] = [player_skills[0]["name"]]
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        skill_definitions(ContentBundle.load(data_dir))
    except ContentError as exc:
        assert "duplicated" in str(exc)
    else:
        raise AssertionError("duplicate skill aliases must be rejected")


def test_skill_progression_costs_snapshots_and_operation_replay() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            assert (await runtime.dispatch(_context("missing", "preview"), "神通预览")).ok
            assert (await runtime.dispatch(_context("missing", "profile"), "我的神通")).code == "PLAYER_NOT_FOUND"
            user = "skill-progress"
            await _enter_cultivator(runtime, user)
            _set_resources(runtime, user, insights=4, stones=500)

            first = await runtime.dispatch(
                _context(user, "train-1", operation_id="skill-1"), "参悟神通 基础攻击"
            )
            assert first.code == "SKILL_TRAINED"
            assert first.data["level"] == 1
            assert first.data["effective_effect"]["value"] == 10300
            replay = await runtime.dispatch(
                _context(user, "train-1-replay", operation_id="skill-1"), "参悟神通 基础攻击"
            )
            assert replay.data["idempotent_replay"] is True
            conflict = await runtime.dispatch(
                _context(user, "train-1-conflict", operation_id="skill-1"), "参悟神通 重击"
            )
            assert conflict.code == "OPERATION_CONFLICT"

            second = await runtime.dispatch(
                _context(user, "train-2", operation_id="skill-2"), "参悟神通 基础攻击"
            )
            third = await runtime.dispatch(
                _context(user, "train-3", operation_id="skill-3"), "参悟神通 基础攻击"
            )
            assert second.data["level"] == 2
            assert third.data["level"] == 3
            assert third.data["effective_effect"]["value"] == 10900
            maxed = await runtime.dispatch(_context(user, "train-4"), "参悟神通 基础攻击")
            assert maxed.code == "SKILL_MAXED"

            profile = await runtime.dispatch(_context(user, "profile"), "我的神通")
            assert profile.code == "SKILL_PROFILE"
            assert profile.data["insight_balance"] == 0
            assert profile.data["skills"][0]["level"] == 3
            with sqlite3.connect(runtime.settings.database_path) as connection:
                player = connection.execute(
                    "SELECT skill_insights, spirit_stones FROM players WHERE platform_user_id = ?", (user,)
                ).fetchone()
                mastery = connection.execute(
                    "SELECT level, snapshot_json FROM skill_masteries WHERE player_id = (SELECT id FROM players WHERE platform_user_id = ?)",
                    (user,),
                ).fetchone()
                events = connection.execute(
                    "SELECT COUNT(*) FROM skill_resource_events WHERE player_id = (SELECT id FROM players WHERE platform_user_id = ?)",
                    (user,),
                ).fetchone()[0]
            assert player == (0, 360)
            assert mastery[0] == 3
            assert json.loads(mastery[1])["realm_key"] == "qi_sensing"
            assert events == 6
            await runtime.close()

    asyncio.run(run())


def test_skill_operation_replay_uses_frozen_result_after_content_closes_skill(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    shutil.copytree(Path(__file__).parents[1] / "data", data_dir)

    async def run() -> None:
        user = "skill-replay-content-change"
        runtime = create_runtime(data_dir=data_dir)
        await _enter_cultivator(runtime, user)
        _set_resources(runtime, user, insights=1, stones=20)
        trained = await runtime.dispatch(
            _context(user, "train", operation_id="skill-replay-content-change-1"),
            "参悟神通 基础攻击",
        )
        assert trained.code == "SKILL_TRAINED"
        await runtime.close()

        skill_path = data_dir / "技能" / "技能.json"
        document = json.loads(skill_path.read_text(encoding="utf-8"))
        skill = next(row for row in document["records"] if row["key"] == "skill.basic_attack")
        skill["name"] = "已封神通"
        skill["status"] = "locked"
        skill["effect"]["value"] = 19000
        skill_path.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")

        runtime = create_runtime(data_dir=data_dir)
        replay = await runtime.repository.train_skill(
            platform="web",
            platform_user_id=user,
            skill_reference="基础攻击",
            operation_id="skill-replay-content-change-1",
        )
        assert replay.already_completed is True
        assert replay.label == "基础攻击"
        assert replay.effective_effect["value"] == 10300
        profile = await runtime.repository.get_skill_profile(
            platform="web", platform_user_id=user
        )
        assert profile.skills[0].label == "基础攻击"
        assert profile.skills[0].effective_effect["value"] == 10300
        await runtime.close()

    asyncio.run(run())


def test_skill_growth_reads_effect_field_declared_in_content() -> None:
    definition = skill_definition("机弩穿云")
    effect = effective_skill_effect(definition, 1)
    assert effect["value"] == 13800
    assert effect["type"] == "physical_damage_multiplier_bp"
    assert "attack_multiplier_bp" not in effect


def test_nascent_skill_catalog_covers_each_path_with_configured_growth() -> None:
    late_skills = [
        definition
        for definition in skill_definitions().values()
        if definition.min_realm_key == "nascent_soul"
    ]
    assert {definition.path_key for definition in late_skills} == {
        "body",
        "spell",
        "device",
        "demonic",
        "beast",
        "support",
    }
    assert {definition.max_level for definition in late_skills} == {3, 5}
    assert all(
        definition.key not in available_skill_keys(
            definition.path_key,
            realm_key="foundation",
            realm_layer=10,
        )
        for definition in late_skills
    )
    assert all(
        definition.key in available_skill_keys(
            definition.path_key,
            realm_key="nascent_soul",
            realm_layer=1,
            inventory={"item.manual.skill_legacy": 1},
        )
        for definition in late_skills
    )


def test_skill_catalog_covers_every_open_realm_for_all_paths() -> None:
    paths = {"body", "spell", "device", "demonic", "beast", "support"}
    realms = (
        "qi_sensing",
        "qi_gathering",
        "foundation",
        "golden_core",
        "nascent_soul",
        "soul_transformation",
        "void_refining",
        "dao_union",
        "tribulation",
    )
    definitions = skill_definitions()
    elite_pool = bundled_content().require("reward", "reward_pool.bounty.elite_hunt")
    assert any(
        "item.manual.skill_legacy" in outcome.get("rewards", {})
        for outcome in elite_pool["outcomes"]
    )
    supported_effects = {
        "physical_damage_multiplier_bp",
        "spell_damage_multiplier_bp",
        "damage_bonus_bp",
    }
    assert {
        item.effect.get("type")
        for item in skill_definitions().values()
        if item.status == "active" and item.path_key in paths
    } <= supported_effects
    path_skills = [item for item in definitions.values() if item.path_key in paths]
    assert len(path_skills) == len(paths) * len(realms) * 2
    assert {item.effect.get("type") for item in path_skills} <= supported_effects

    player_names = [item.label for item in definitions.values() if item.path_key in paths]
    assert len(player_names) == len(set(player_names))
    realm_labels = ("感气", "聚气", "筑基", "金丹", "元婴", "化神", "炼虚", "合道", "渡劫")
    assert all(not any(label in name for label in realm_labels) for name in player_names)
    assert {item.style_key for item in path_skills} >= {
        "attack",
        "burst",
        "support",
        "sustained",
        "negative",
        "charge",
        "poison",
        "burn",
        "reflect",
    }
    for path_key in paths:
        for realm_key in realms:
            matching = [
                item
                for item in path_skills
                if item.path_key == path_key and item.min_realm_key == realm_key
            ]
            if realm_key == "qi_sensing":
                matching = [
                    item
                    for item in path_skills
                    if item.path_key == path_key and item.min_realm_key in {None, realm_key}
                ]
            assert len(matching) == 2, (path_key, realm_key, matching)
            matching_styles = {item.style_key for item in matching}
            assert "attack" in matching_styles
            assert len(matching_styles) <= 2
            for definition in matching:
                available = available_skill_keys(path_key, realm_key=realm_key, realm_layer=1)
                if definition.acquisition_item_key:
                    assert definition.key not in available
                    assert definition.key in available_skill_keys(
                        path_key,
                        realm_key=realm_key,
                        realm_layer=1,
                        inventory={definition.acquisition_item_key: 1},
                    )
                else:
                    assert definition.key in available
            if realm_key != "qi_sensing":
                for definition in matching:
                    assert definition.key not in available_skill_keys(
                        path_key,
                        realm_key=realms[realms.index(realm_key) - 1],
                        realm_layer=10,
                        inventory={"item.manual.skill_legacy": 1},
                    )


def test_rare_skill_manual_is_required_and_consumed_only_on_first_training() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            user = "skill-manual-gate"
            await _enter_cultivator(runtime, user)
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE players SET realm_key = 'foundation', realm_layer = 1, skill_insights = 10, "
                    "spirit_stones = 10000 WHERE platform = 'web' AND platform_user_id = ?",
                    (user,),
                )
            skill_key = "skill.body.foundation.variant"
            missing = await runtime.dispatch(
                _context(user, "manual-missing"), f"参悟神通 {skill_key}"
            )
            assert missing.code == "SKILL_NOT_AVAILABLE"

            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE players SET inventory_json = ? WHERE platform = 'web' AND platform_user_id = ?",
                    (json.dumps({"item.manual.skill_legacy": 1}), user),
                )
            learned = await runtime.dispatch(
                _context(user, "manual-learn", operation_id="manual-learn"),
                f"参悟神通 {skill_key}",
            )
            assert learned.code == "SKILL_TRAINED"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                inventory = json.loads(connection.execute(
                    "SELECT inventory_json FROM players WHERE platform = 'web' AND platform_user_id = ?",
                    (user,),
                ).fetchone()[0])
            assert "item.manual.skill_legacy" not in inventory

            refined = await runtime.dispatch(
                _context(user, "manual-refine", operation_id="manual-refine"),
                f"参悟神通 {skill_key}",
            )
            assert refined.code == "SKILL_TRAINED"
            assert refined.data["level"] == 2
            await runtime.close()

    asyncio.run(run())


def test_skill_growth_configuration_changes_preview_and_settlement() -> None:
    async def run(data_dir: Path) -> None:
        skill_path = data_dir / "养成" / "神通.json"
        document = json.loads(skill_path.read_text(encoding="utf-8"))
        definition = next(row for row in document["records"] if row["key"] == "skill.basic_attack")
        definition["max_level"] = 4
        definition["growth"]["effect_fields"]["value"] = 500
        definition["cost_by_target_level"] = {
            "1": {"resource.skill_insight": 2, "currency.spirit_stone": 35},
            "2": {"resource.skill_insight": 3, "currency.spirit_stone": 55},
            "3": {"resource.skill_insight": 4, "currency.spirit_stone": 75},
            "4": {"resource.skill_insight": 5, "currency.spirit_stone": 95},
        }
        skill_path.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")

        runtime = create_runtime(data_dir=data_dir)
        preview = await runtime.dispatch(_context("missing", "preview-config"), "神通预览")
        assert "上限 4 级" in preview.message
        assert "技能心得 2" in preview.message
        assert "灵石 35" in preview.message
        assert "resource.skill_insight" not in preview.message

        user = "skill-custom-growth"
        await _enter_cultivator(runtime, user)
        _set_resources(runtime, user, insights=20, stones=300)
        trained_results = [
            await runtime.dispatch(
                _context(user, f"train-custom-{level}", operation_id=f"skill-custom-{level}"),
                "参悟神通 基础攻击",
            )
            for level in range(1, 5)
        ]
        trained = trained_results[0]
        assert all(result.code == "SKILL_TRAINED" for result in trained_results)
        assert [result.data["effective_effect"]["value"] for result in trained_results] == [
            10500,
            11000,
            11500,
            12000,
        ]
        assert trained.data["resource_costs"] == {
            "resource.skill_insight": 2,
            "currency.spirit_stone": 35,
        }
        assert "bp" not in trained.message
        maxed = await runtime.dispatch(_context(user, "train-custom-maxed"), "参悟神通 基础攻击")
        assert maxed.code == "SKILL_MAXED"

        with sqlite3.connect(runtime.settings.database_path) as connection:
            mastery_columns = {row[1] for row in connection.execute("PRAGMA table_info(skill_masteries)")}
            mastery = connection.execute(
                "SELECT level, snapshot_json FROM skill_masteries WHERE player_id = (SELECT id FROM players WHERE platform_user_id = ?)",
                (user,),
            ).fetchone()
        snapshot = json.loads(mastery[1])
        assert "max_level" not in mastery_columns
        assert "path_key" not in mastery_columns
        assert mastery[0] == 4
        await runtime.close()

    with TemporaryDirectory() as directory:
        data_dir = Path(directory) / "data"
        shutil.copytree(Path(__file__).parents[1] / "data", data_dir)
        asyncio.run(run(data_dir))


def test_skill_realm_gate_is_read_from_content() -> None:
    async def run(data_dir: Path) -> None:
        skill_path = data_dir / "技能" / "技能.json"
        document = json.loads(skill_path.read_text(encoding="utf-8"))
        skill = next(row for row in document["records"] if row["key"] == "skill.body.mountain_palm")
        skill["min_realm_key"] = "qi_gathering"
        skill["min_layer"] = 1
        skill_path.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")

        runtime = create_runtime(data_dir=data_dir)
        user = "skill-realm-gate"
        await _enter_cultivator(runtime, user)
        _set_resources(runtime, user, insights=2, stones=100)

        preview = await runtime.dispatch(_context(user, "realm-preview"), "神通预览")
        assert "聚气 L1 起可参悟" in preview.message
        locked = await runtime.dispatch(_context(user, "realm-locked"), "参悟神通 崩山掌")
        assert locked.code == "SKILL_NOT_AVAILABLE"

        with sqlite3.connect(runtime.settings.database_path) as connection:
            connection.execute(
                "UPDATE players SET realm_key = 'qi_gathering', realm_layer = 1 WHERE platform_user_id = ?",
                (user,),
            )
        unlocked = await runtime.dispatch(
            _context(user, "realm-unlocked", operation_id="skill-realm-unlocked"),
            "参悟神通 崩山掌",
        )
        assert unlocked.code == "SKILL_TRAINED"
        assert unlocked.data["effective_effect"]["value"] == 16900
        await runtime.close()

    with TemporaryDirectory() as directory:
        data_dir = Path(directory) / "data"
        shutil.copytree(Path(__file__).parents[1] / "data", data_dir)
        asyncio.run(run(data_dir))


def test_skill_path_resource_and_long_action_gates() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            user = "skill-gates"
            await _enter_cultivator(runtime, user)
            _set_resources(runtime, user, insights=1, stones=20)
            wrong_path = await runtime.dispatch(_context(user, "wrong"), "参悟神通 水箭")
            assert wrong_path.code == "SKILL_NOT_AVAILABLE"
            insufficient = await runtime.dispatch(_context(user, "insufficient"), "参悟神通 基础攻击")
            assert insufficient.ok
            no_resources = await runtime.dispatch(_context(user, "no-resources"), "参悟神通 基础攻击")
            assert no_resources.code == "SKILL_RESOURCE_INSUFFICIENT"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute(
                    "SELECT skill_insights, spirit_stones FROM players WHERE platform_user_id = ?", (user,)
                ).fetchone() == (0, 0)

            other = "skill-busy"
            await _enter_cultivator(runtime, other)
            _set_resources(runtime, other, insights=2, stones=100)
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE players SET energy = 10, inventory_json = ? WHERE platform = 'web' AND platform_user_id = ?",
                    (
                        json.dumps(
                            {"item.food.coarse_spirit_rice": 1, "item.manual.basic_qi": 1}
                        ),
                        other,
                    ),
                )
            started = await runtime.dispatch(_context(other, "retreat"), "开始闭关")
            assert started.ok
            blocked = await runtime.dispatch(_context(other, "blocked"), "参悟神通 基础攻击")
            assert blocked.code == "SKILL_BUSY"
            await runtime.close()

    asyncio.run(run())


def test_skill_concurrent_training_consumes_one_available_level() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            user = "skill-concurrent"
            await _enter_cultivator(runtime, user)
            _set_resources(runtime, user, insights=1, stones=20)
            results = await asyncio.gather(
                *(
                    runtime.dispatch(
                        _context(user, f"concurrent-{index}", operation_id=f"skill-concurrent-{index}"),
                        "参悟神通 基础攻击",
                    )
                    for index in range(10)
                )
            )
            assert sum(result.ok for result in results) == 1
            assert {result.code for result in results} == {"SKILL_TRAINED", "SKILL_RESOURCE_INSUFFICIENT"}
            await runtime.close()

    asyncio.run(run())


def test_skill_training_runs_through_qq_and_onebot_v11_adapters() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            for adapter in ("qq.official", "onebot.v11"):
                user = f"skill-{adapter}"
                await _enter_cultivator(runtime, user, adapter=adapter)
                _set_resources(runtime, user, insights=1, stones=20, adapter=adapter)
                result = await runtime.adapters.dispatch(
                    adapter,
                    _context(user, f"train-{adapter}", adapter=adapter, operation_id=f"train-{adapter}"),
                    "参悟神通 基础攻击",
                )
                assert result.code == "SKILL_TRAINED"
                assert result.data["resource_costs"] == {
                    "resource.skill_insight": 1,
                    "currency.spirit_stone": 20,
                }
            await runtime.close()

    asyncio.run(run())
