from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError
from nonebot_plugin_xiuxian_3.xiuxian.paths.rebuild_content import (
    path_rebuild_definition,
)
from nonebot_plugin_xiuxian_3.xiuxian.player.path_rules import subprofession_records

ROOT = Path(__file__).parents[1]


class Flow:
    def __init__(self, tmp_path: Path, adapter: str = "onebot.v11"):
        self.root = tmp_path / "content"
        shutil.copytree(ROOT / "data", self.root)
        self.now = datetime(2026, 11, 4, 12, tzinfo=timezone.utc)
        self.adapter = adapter
        self.runtime = create_runtime(
            data_dir=self.root, clock=lambda: self.now, adapters=(adapter,)
        )
        self.sequence = 0
        self.user = "path-rebuild-player"

    async def send(self, command, operation=None, *, ok=True, user=None):
        self.sequence += 1
        identity = user or self.user
        result = await self.runtime.adapters.dispatch(
            self.adapter,
            CommandContext(
                adapter=self.adapter,
                user_id=identity,
                request_id=str(self.sequence),
                operation_id=operation or f"{identity}:{self.sequence}",
                can_write_assets=True,
            ),
            command,
        )
        if ok:
            assert result.ok, (command, result.code, result.message)
        return result

    async def enter(self, choice="体修"):
        for command in (
            "开始修仙 青玄",
            "寻仙问道",
            "完成引导 阅读",
            "前往近郊",
            "完成引导 采集",
            "完成引导 布阵",
            f"选择道途 {choice}",
        ):
            await self.send(command)

    def player(self):
        with sqlite3.connect(self.runtime.settings.database_path) as db:
            db.row_factory = sqlite3.Row
            return dict(
                db.execute(
                    "SELECT * FROM players WHERE platform_user_id=?",
                    (self.user,),
                ).fetchone()
            )

    def set_player(self, **values):
        with sqlite3.connect(self.runtime.settings.database_path) as db:
            db.execute(
                f"UPDATE players SET {', '.join(key + '=?' for key in values)} "
                "WHERE platform_user_id=?",
                tuple(values.values()) + (self.user,),
            )

    async def ready(self, *, stones=60000, reputation=1000, flag=True, token=1):
        await self.enter()
        inventory = json.loads(self.player()["inventory_json"])
        inventory["item.token.rebuild_path"] = token
        self.set_player(
            realm_key="nascent_soul",
            realm_layer=1,
            spirit_stones=stones,
            talent_points=10,
            faction_reputation_json=json.dumps(
                {"xuantian": reputation, "demon": reputation, "beast": reputation}
            ),
            intro_json=json.dumps(
                {"flags": ["story.mainline.three_realms"] if flag else []}
            ),
            inventory_json=json.dumps(inventory),
        )
        for tier in (1, 2, 3):
            await self.send(f"解锁天赋 {tier}")

    async def close(self):
        await self.runtime.close()

    def reopen(self):
        self.runtime = create_runtime(
            data_dir=self.root, clock=lambda: self.now, adapters=(self.adapter,)
        )


def _write_rebuild(data_root: Path, document: dict) -> None:
    (data_root / "道途" / "重构.json").write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _rebuild_document(data_root: Path) -> dict:
    return json.loads((data_root / "道途" / "重构.json").read_text(encoding="utf-8"))


def test_path_rebuild_content_contract_and_rejections(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    shutil.copytree(ROOT / "data", data_root)
    bundle = ContentBundle.load(data_root)
    definition = path_rebuild_definition(bundle)
    assert definition.min_realm == "nascent_soul"
    assert definition.min_layer == 1
    assert definition.spirit_stone_cost == 50000
    assert definition.token_item_key == "item.token.rebuild_path"
    assert definition.token_quantity == 1
    assert definition.level_deduction == 2
    assert definition.preview_ttl_seconds == 86400
    assert definition.required_reputation == {
        "xuantian": 1000,
        "demon": 1000,
        "beast": 1000,
    }

    document = _rebuild_document(data_root)
    document["records"][0]["required_reputation"] = {"xuantian": 1000}
    _write_rebuild(data_root, document)
    with pytest.raises(ContentError, match="required_reputation"):
        path_rebuild_definition(ContentBundle.load(data_root))

    document = _rebuild_document(data_root)
    document["records"][0]["required_reputation"] = {
        "xuantian": 1000,
        "demon": 1000,
        "beast": 1000,
    }
    document["records"][0]["level_deduction"] = 3
    _write_rebuild(data_root, document)
    with pytest.raises(ContentError, match="level_deduction"):
        path_rebuild_definition(ContentBundle.load(data_root))

    document = _rebuild_document(data_root)
    document["records"][0]["level_deduction"] = 2
    document["records"][0]["cost"] = {
        "currency.spirit_stone": 50000,
        "item.manual.basic_qi": 1,
    }
    _write_rebuild(data_root, document)
    with pytest.raises(ContentError, match="token"):
        path_rebuild_definition(ContentBundle.load(data_root))


@pytest.mark.anyio
async def test_path_rebuild_requires_all_gates_without_side_effects(tmp_path: Path) -> None:
    flow = Flow(tmp_path)
    await flow.ready(reputation=999)
    before = flow.player()
    result = await flow.send("道途重构预览 法修", ok=False)
    assert result.code == "PATH_REBUILD_REQUIREMENT"
    assert flow.player()["path_key"] == before["path_key"]
    assert flow.player()["spirit_stones"] == before["spirit_stones"]
    await flow.close()

    flow = Flow(tmp_path / "flag")
    await flow.ready(flag=False)
    result = await flow.send("道途重构预览 法修", ok=False)
    assert result.code == "PATH_REBUILD_QUEST_MISSING"
    await flow.close()

    flow = Flow(tmp_path / "token")
    await flow.ready(token=0)
    result = await flow.send("道途重构预览 法修", ok=False)
    assert result.code == "PATH_REBUILD_TOKEN_MISSING"
    await flow.close()

    flow = Flow(tmp_path / "stones")
    await flow.ready(stones=40000)
    result = await flow.send("道途重构预览 法修", ok=False)
    assert result.code == "PATH_REBUILD_FUNDS"
    await flow.close()

    flow = Flow(tmp_path / "realm")
    await flow.enter()
    result = await flow.send("道途重构预览 法修", ok=False)
    assert result.code == "PATH_REBUILD_REQUIREMENT"
    await flow.close()


@pytest.mark.anyio
async def test_path_rebuild_previews_and_confirms_with_inheritance(tmp_path: Path) -> None:
    flow = Flow(tmp_path)
    await flow.ready()
    preview = await flow.send("道途重构预览 法修")
    assert preview.code == "PATH_REBUILD_PREVIEW"
    assert preview.data["old_level"] == 3
    assert preview.data["inherited_level"] == 1
    assert "灵石 50000" in preview.message
    assert "道途重构令 ×1" in preview.message
    assert "旧道脉节点 3 阶" in preview.message
    assert flow.player()["path_key"] == "body"
    assert flow.player()["spirit_stones"] == 60000
    assert json.loads(flow.player()["inventory_json"])["item.token.rebuild_path"] == 1

    result = await flow.send("确认道途重构")
    assert result.code == "PATH_REBUILD_CONFIRMED"
    player = flow.player()
    assert player["path_key"] == "spell"
    assert player["spirit_stones"] == 10000
    assert json.loads(player["inventory_json"]).get("item.token.rebuild_path", 0) == 0
    with sqlite3.connect(flow.runtime.settings.database_path) as db:
        assert db.execute(
            "SELECT COUNT(*) FROM talent_node_states WHERE tree_key='body'"
        ).fetchone()[0] == 3
        assert db.execute(
            "SELECT COUNT(*) FROM talent_node_states WHERE tree_key='spell'"
        ).fetchone()[0] == 1
        assert db.execute(
            "SELECT from_path_key, to_path_key, old_level, inherited_level FROM path_rebuilds"
        ).fetchone() == ("body", "spell", 3, 1)
    await flow.close()


@pytest.mark.anyio
async def test_path_rebuild_is_one_time_and_replays_the_same_operation(tmp_path: Path) -> None:
    flow = Flow(tmp_path)
    await flow.ready()
    await flow.send("道途重构预览 法修")
    first = await flow.send("确认道途重构", operation="rebuild-once")
    replay = await flow.send("确认道途重构", operation="rebuild-once")
    assert first.code == replay.code == "PATH_REBUILD_CONFIRMED"
    assert replay.data["idempotent_replay"] is True
    stale = await flow.send("确认道途重构", operation="rebuild-second-operation", ok=False)
    assert stale.code == "PATH_REBUILD_STATE"
    assert flow.player()["spirit_stones"] == 10000
    result = await flow.send("道途重构预览 体修", ok=False)
    assert result.code == "PATH_REBUILD_LIMIT_REACHED"
    with sqlite3.connect(flow.runtime.settings.database_path) as db:
        assert db.execute("SELECT COUNT(*) FROM path_rebuilds").fetchone()[0] == 1
    await flow.close()


@pytest.mark.anyio
async def test_path_rebuild_expires_without_spending(tmp_path: Path) -> None:
    flow = Flow(tmp_path)
    await flow.ready()
    await flow.send("道途重构预览 法修")
    flow.now += timedelta(hours=25)
    result = await flow.send("确认道途重构", ok=False)
    assert result.code == "PATH_REBUILD_PREVIEW_EXPIRED"
    player = flow.player()
    assert player["path_key"] == "body"
    assert player["spirit_stones"] == 60000
    assert json.loads(player["inventory_json"])["item.token.rebuild_path"] == 1
    await flow.close()


@pytest.mark.anyio
async def test_path_rebuild_conflicts_when_the_old_tree_changes(tmp_path: Path) -> None:
    flow = Flow(tmp_path)
    await flow.ready()
    await flow.send("道途重构预览 法修")
    await flow.send("解锁天赋 4")
    result = await flow.send("确认道途重构", ok=False)
    assert result.code == "PATH_STATE_CONFLICT"
    assert flow.player()["path_key"] == "body"
    await flow.close()


@pytest.mark.anyio
async def test_path_rebuild_cancel_and_support_subprofession(tmp_path: Path) -> None:
    flow = Flow(tmp_path)
    await flow.ready()
    await flow.send("道途重构预览 法修")
    cancelled = await flow.send("取消道途重构")
    assert cancelled.code == "PATH_REBUILD_CANCELLED"
    assert (await flow.send("确认道途重构", ok=False)).code == "PATH_REBUILD_STATE"
    assert flow.player()["path_key"] == "body"

    invalid = await flow.send("道途重构预览 辅修", ok=False)
    assert invalid.code == "PATH_REBUILD_INVALID"
    subprofession = subprofession_records("support")[0]
    preview = await flow.send(f"道途重构预览 辅修 {subprofession['name']}")
    assert preview.code == "PATH_REBUILD_PREVIEW"
    result = await flow.send("确认道途重构")
    assert result.code == "PATH_REBUILD_CONFIRMED"
    assert flow.player()["path_key"] == "support"
    assert flow.player()["subprofession_key"] == subprofession["key"]
    await flow.close()


@pytest.mark.anyio
async def test_path_rebuild_survives_restart_and_is_listed_in_help(tmp_path: Path) -> None:
    flow = Flow(tmp_path)
    await flow.ready()
    help_result = await flow.send("帮助 修炼")
    assert "道途重构" in help_result.message
    assert "道途重构预览 法修" in help_result.message
    await flow.send("道途重构预览 法修")
    await flow.send("确认道途重构")
    await flow.close()
    flow.reopen()
    listed = await flow.send("道途重构预览 体修", ok=False)
    assert listed.code == "PATH_REBUILD_LIMIT_REACHED"
    await flow.close()
