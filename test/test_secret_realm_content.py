from __future__ import annotations

import asyncio
import json
import shutil
import sqlite3
from combat_fixtures import equip_damage_weapon
from pathlib import Path

import pytest

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError
from nonebot_plugin_xiuxian_3.xiuxian.adventures.secret_realm_rules import (
    repeat_reward,
    resolve_secret_realm,
    secret_realm_definitions,
)


ROOT = Path(__file__).parents[1]
MIST_KEY = "instance.secret_realm.mist_grotto"


def _content_dir(tmp_path: Path) -> Path:
    target = tmp_path / "data"
    shutil.copytree(ROOT / "data", target)
    return target


def _read_secret_realms(data_dir: Path) -> dict:
    path = data_dir / "冒险" / "秘境.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _write_secret_realms(data_dir: Path, document: dict) -> None:
    path = data_dir / "冒险" / "秘境.json"
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _context(adapter: str, user: str, operation_id: str) -> CommandContext:
    return CommandContext(adapter=adapter, user_id=user, operation_id=operation_id)


def test_secret_realm_definition_and_repeat_reward_are_content_backed(tmp_path: Path) -> None:
    data_dir = _content_dir(tmp_path)
    document = _read_secret_realms(data_dir)
    realm = next(row for row in document["records"] if row["key"] == MIST_KEY)
    realm["name"] = "雾中洞府"
    realm["desc"] = "青雾中可见一座静谧洞府。"
    realm["aliases"].append("雾中洞府入口")
    realm["stamina_cost"] = 14
    realm["first_reward"]["spirit_stones"] = 91
    realm["repeat_reward_pool"] = [
        {"weight": 3, "rewards": {"item.material.mist_core": 4}}
    ]
    _write_secret_realms(data_dir, document)

    bundle = ContentBundle.load(data_dir)
    definition = secret_realm_definitions(bundle)[MIST_KEY]
    assert definition.label == "雾中洞府"
    assert definition.description == "青雾中可见一座静谧洞府。"
    assert definition.stamina_cost == 14
    assert definition.first_reward["spirit_stones"] == 91
    assert resolve_secret_realm("雾中洞府入口", bundle) == MIST_KEY
    assert repeat_reward(definition, "any-seed") == {"item.material.mist_core": 4}


@pytest.mark.parametrize(
    "damage",
    [
        "description",
        "realm",
        "location",
        "enemy",
        "item",
        "node",
        "weight",
        "codex_quantity",
        "missing_repeat_rewards",
        "invalid_no_reward",
        "duplicate_alias",
    ],
)
def test_secret_realm_rejects_invalid_content_references(tmp_path: Path, damage: str) -> None:
    data_dir = _content_dir(tmp_path)
    document = _read_secret_realms(data_dir)
    realm = next(row for row in document["records"] if row["key"] == MIST_KEY)
    if damage == "description":
        realm["desc"] = " "
    elif damage == "realm":
        realm["required_realm"] = "realm.unknown"
    elif damage == "location":
        realm["location_key"] = "location.unknown"
    elif damage == "enemy":
        realm["enemy_key"] = "enemy.unknown"
    elif damage == "item":
        realm["first_reward"]["item.unknown"] = 1
    elif damage == "node":
        realm["node_keys"] = ["resource", "choice"]
    elif damage == "weight":
        realm["repeat_reward_pool"][0]["weight"] = 0
    elif damage == "codex_quantity":
        realm["first_reward"]["codex.instance.mist_grotto"] = 2
    elif damage == "missing_repeat_rewards":
        realm["repeat_reward_pool"][1].pop("rewards")
    elif damage == "invalid_no_reward":
        realm["repeat_reward_pool"][0]["no_reward"] = False
    else:
        realm["aliases"] = ["重复入口", "重复入口"]
    _write_secret_realms(data_dir, document)

    with pytest.raises(ContentError):
        secret_realm_definitions(ContentBundle.load(data_dir))


@pytest.mark.parametrize("adapter", ["qq.official", "onebot.v11"])
def test_active_secret_realm_uses_frozen_content_after_restart(tmp_path: Path, adapter: str) -> None:
    async def run() -> None:
        data_dir = _content_dir(tmp_path)
        user = f"{adapter}:secret-content-freeze"
        runtime = create_runtime(data_dir=data_dir, adapters=(adapter,))
        try:
            assert (await runtime.dispatch(_context(adapter, user, "create"), "开始修仙")).ok
            assert (await runtime.dispatch(_context(adapter, user, "seek"), "寻仙问道")).ok
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE players SET stage='cultivator', realm_key='qi_gathering', realm_layer=4, "
                    "location_key='cave.mist_grotto', stamina=30, stamina_max=30, max_hp=5000, "
                    "initiative=100, inventory_json=? "
                    "WHERE platform=? AND platform_user_id=?",
                    (json.dumps({"item.cave_pass_basic": 1}), adapter, user),
                )
            equip_damage_weapon(runtime, adapter, user, 500)
            entered = await runtime.dispatch(
                _context(adapter, user, "enter"), "进入秘境 雾隐秘境"
            )
            assert entered.code == "SECRET_REALM_ENTERED"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                snapshot = json.loads(
                    connection.execute(
                        "SELECT snapshot_json FROM secret_realm_runs WHERE run_id=?",
                        (entered.data["run_id"],),
                    ).fetchone()[0]
                )
            assert snapshot["label"] == "雾隐秘境"
            assert snapshot["enemy_key"] == "enemy.mist_guardian"
            assert snapshot["node_keys"] == ["resource", "encounter", "choice"]
        finally:
            await runtime.close()

        document = _read_secret_realms(data_dir)
        realm = next(row for row in document["records"] if row["key"] == MIST_KEY)
        realm["name"] = "雾中洞府"
        realm["desc"] = "青雾中可见一座静谧洞府。"
        realm["enemy_key"] = "enemy.spring_wisp"
        realm["node_keys"] = ["resource", "encounter"]
        realm["first_reward"] = {"spirit_stones": 999}
        _write_secret_realms(data_dir, document)

        recovered = create_runtime(data_dir=data_dir, adapters=(adapter,))
        try:
            preview = await recovered.dispatch(_context(adapter, user, "preview"), "秘境预览")
            current = next(row for row in preview.data["realms"] if row["instance_key"] == MIST_KEY)
            assert current["label"] == "雾中洞府"
            assert current["desc"] == "青雾中可见一座静谧洞府。"
            assert current["nodes"] == ("resource", "encounter")

            resource = await recovered.dispatch(
                _context(adapter, user, "resource"), "选择秘境节点 资源"
            )
            assert resource.data["current_node"] == "encounter"
            battle = await recovered.dispatch(
                _context(adapter, user, "encounter"), "选择秘境节点 遭遇"
            )
            assert battle.code == "SECRET_REALM_COMBAT_PENDING"
            assert "## 雾隐秘境有守护者拦路" in battle.message
            with sqlite3.connect(recovered.settings.database_path) as connection:
                enemy_key = connection.execute(
                    "SELECT enemy_key FROM battle_sessions WHERE battle_id=?",
                    (battle.data["battle_id"],),
                ).fetchone()[0]
            assert enemy_key == "enemy.mist_guardian"

            progress = await recovered.dispatch(
                _context(adapter, user, "combat"), "结算秘境"
            )
            assert progress.data["current_node"] == "choice"
            cleared = await recovered.dispatch(
                _context(adapter, user, "choice"), "选择秘境节点 选择"
            )
            assert cleared.data["status"] == "cleared"
            settled = await recovered.dispatch(
                _context(adapter, user, "settle"), "结算秘境"
            )
            assert settled.data["reward"] == {
                "spirit_stones": 80,
                "item.material.mist_core": 2,
                "codex.instance.mist_grotto": 1,
            }
        finally:
            await recovered.close()

    asyncio.run(run())
