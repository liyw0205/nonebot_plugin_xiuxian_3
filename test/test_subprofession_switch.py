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
from nonebot_plugin_xiuxian_3.xiuxian.paths.subprofession_switch_content import (
    subprofession_switch_definition,
)
from nonebot_plugin_xiuxian_3.xiuxian.player.path_rules import subprofession_records

ROOT = Path(__file__).parents[1]
CRAFTS = [record["name"] for record in subprofession_records("support")]


class Flow:
    def __init__(self, tmp_path: Path, adapter: str = "onebot.v11"):
        self.root = tmp_path / "content"
        shutil.copytree(ROOT / "data", self.root)
        self.now = datetime(2026, 11, 5, 12, tzinfo=timezone.utc)
        self.adapter = adapter
        self.runtime = create_runtime(
            data_dir=self.root, clock=lambda: self.now, adapters=(adapter,)
        )
        self.sequence = 0
        self.user = "subprofession-switch-player"

    async def send(self, command, operation=None, *, ok=True):
        self.sequence += 1
        result = await self.runtime.adapters.dispatch(
            self.adapter,
            CommandContext(
                adapter=self.adapter,
                user_id=self.user,
                request_id=str(self.sequence),
                operation_id=operation or f"{self.user}:{self.sequence}",
                can_write_assets=True,
            ),
            command,
        )
        if ok:
            assert result.ok, (command, result.code, result.message)
        return result

    async def enter(self, path: str = "辅修", craft: str | None = None):
        command = f"选择道途 {path}" + (f" {craft}" if path == "辅修" and craft else "")
        for item in (
            "开始修仙 青玄",
            "寻仙问道",
            "完成引导 阅读",
            "前往近郊",
            "完成引导 采集",
            "完成引导 布阵",
            command,
        ):
            await self.send(item)

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

    async def ready(self, craft: str | None = None, *, stones=5000):
        await self.enter("辅修", craft or CRAFTS[0])
        self.set_player(realm_key="foundation", realm_layer=1, spirit_stones=stones)

    async def close(self):
        await self.runtime.close()

    def reopen(self):
        self.runtime = create_runtime(
            data_dir=self.root, clock=lambda: self.now, adapters=(self.adapter,)
        )


def _write_rule(data_root: Path, document: dict) -> None:
    (data_root / "道途" / "辅修切换.json").write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _rule_document(data_root: Path) -> dict:
    return json.loads((data_root / "道途" / "辅修切换.json").read_text(encoding="utf-8"))


def test_subprofession_switch_content_contract_and_rejections(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    shutil.copytree(ROOT / "data", data_root)
    definition = subprofession_switch_definition(ContentBundle.load(data_root))
    assert definition.path_key == "support"
    assert definition.min_realm == "foundation"
    assert definition.min_layer == 1
    assert definition.spirit_stone_cost == 2000
    assert definition.cooldown_seconds == 604800
    assert definition.preview_ttl_seconds == 900

    document = _rule_document(data_root)
    document["records"][0]["path_key"] = "body"
    _write_rule(data_root, document)
    with pytest.raises(ContentError, match="support path"):
        subprofession_switch_definition(ContentBundle.load(data_root))

    document = _rule_document(data_root)
    document["records"][0]["path_key"] = "support"
    document["records"][0]["cost"] = {"currency.spirit_stone": 2000, "item": 1}
    _write_rule(data_root, document)
    with pytest.raises(ContentError, match="exactly one currency"):
        subprofession_switch_definition(ContentBundle.load(data_root))

    document = _rule_document(data_root)
    document["records"][0]["cost"] = {"currency.spirit_stone": 2000}
    document["records"][0]["cooldown_seconds"] = 0
    _write_rule(data_root, document)
    with pytest.raises(ContentError, match="cooldown_seconds"):
        subprofession_switch_definition(ContentBundle.load(data_root))


@pytest.mark.anyio
async def test_subprofession_switch_rejects_non_support_and_invalid_targets(
    tmp_path: Path,
) -> None:
    flow = Flow(tmp_path)
    await flow.enter("体修")
    assert (await flow.send("辅修预览 炼丹", ok=False)).code == (
        "SUBPROFESSION_SWITCH_NOT_SUPPORT"
    )
    await flow.close()

    flow = Flow(tmp_path / "same")
    await flow.ready(CRAFTS[0])
    result = await flow.send(f"辅修预览 {CRAFTS[0]}", ok=False)
    assert result.code == "SUBPROFESSION_SWITCH_INVALID"
    assert (await flow.send("辅修预览 不存在", ok=False)).code == (
        "SUBPROFESSION_SWITCH_INVALID"
    )
    flow.set_player(subprofession_key=None)
    assert (await flow.send(f"辅修预览 {CRAFTS[1]}", ok=False)).code == (
        "SUBPROFESSION_SWITCH_INVALID"
    )
    await flow.close()

    flow = Flow(tmp_path / "funds")
    await flow.ready(CRAFTS[0], stones=1000)
    assert (await flow.send(f"辅修预览 {CRAFTS[1]}", ok=False)).code == (
        "SUBPROFESSION_SWITCH_FUNDS"
    )
    await flow.close()


@pytest.mark.anyio
async def test_subprofession_switch_preview_and_confirm(tmp_path: Path) -> None:
    flow = Flow(tmp_path)
    await flow.ready(CRAFTS[0])
    preview = await flow.send(f"辅修预览 {CRAFTS[1]}")
    assert preview.code == "SUBPROFESSION_SWITCH_PREVIEW"
    assert preview.data["from_subprofession_key"] == subprofession_records("support")[0]["key"]
    assert flow.player()["subprofession_key"] == subprofession_records("support")[0]["key"]
    assert flow.player()["spirit_stones"] == 5000

    result = await flow.send("确认辅修")
    assert result.code == "SUBPROFESSION_SWITCH_CONFIRMED"
    player = flow.player()
    assert player["subprofession_key"] == subprofession_records("support")[1]["key"]
    assert player["spirit_stones"] == 3000
    with sqlite3.connect(flow.runtime.settings.database_path) as db:
        assert db.execute(
            "SELECT from_subprofession_key, to_subprofession_key FROM subprofession_switches"
        ).fetchone() == (
            subprofession_records("support")[0]["key"],
            subprofession_records("support")[1]["key"],
        )
    await flow.close()


@pytest.mark.anyio
async def test_subprofession_switch_cooldown_and_second_switch(tmp_path: Path) -> None:
    flow = Flow(tmp_path)
    await flow.ready(CRAFTS[0])
    await flow.send(f"辅修预览 {CRAFTS[1]}")
    await flow.send("确认辅修")
    blocked = await flow.send(f"辅修预览 {CRAFTS[2]}", ok=False)
    assert blocked.code == "SUBPROFESSION_SWITCH_COOLDOWN"
    flow.now += timedelta(days=7, seconds=1)
    await flow.send(f"辅修预览 {CRAFTS[2]}")
    second = await flow.send("确认辅修")
    assert second.code == "SUBPROFESSION_SWITCH_CONFIRMED"
    assert flow.player()["subprofession_key"] == subprofession_records("support")[2]["key"]
    assert flow.player()["spirit_stones"] == 1000
    await flow.close()


@pytest.mark.anyio
async def test_subprofession_switch_expiry_and_cancel(tmp_path: Path) -> None:
    flow = Flow(tmp_path)
    await flow.ready(CRAFTS[0])
    await flow.send(f"辅修预览 {CRAFTS[1]}")
    flow.now += timedelta(minutes=16)
    expired = await flow.send("确认辅修", ok=False)
    assert expired.code == "SUBPROFESSION_SWITCH_PREVIEW_EXPIRED"
    assert flow.player()["spirit_stones"] == 5000
    assert flow.player()["subprofession_key"] == subprofession_records("support")[0]["key"]

    await flow.send(f"辅修预览 {CRAFTS[1]}")
    cancelled = await flow.send("取消辅修")
    assert cancelled.code == "SUBPROFESSION_SWITCH_CANCELLED"
    assert (await flow.send("确认辅修", ok=False)).code == "SUBPROFESSION_SWITCH_STATE"
    assert flow.player()["spirit_stones"] == 5000
    await flow.close()


@pytest.mark.anyio
async def test_subprofession_switch_replay_and_help(tmp_path: Path) -> None:
    flow = Flow(tmp_path)
    await flow.ready(CRAFTS[0])
    help_result = await flow.send("帮助 修炼")
    assert "辅修切换" in help_result.message
    assert "辅修预览 炼丹" in help_result.message
    await flow.send(f"辅修预览 {CRAFTS[1]}")
    first = await flow.send("确认辅修", operation="craft-once")
    replay = await flow.send("确认辅修", operation="craft-once")
    assert first.code == replay.code == "SUBPROFESSION_SWITCH_CONFIRMED"
    assert replay.data["idempotent_replay"] is True
    assert flow.player()["spirit_stones"] == 3000
    stale = await flow.send("确认辅修", operation="craft-second", ok=False)
    assert stale.code == "SUBPROFESSION_SWITCH_STATE"
    await flow.close()

    flow.reopen()
    assert flow.player()["subprofession_key"] == subprofession_records("support")[1]["key"]
    assert (await flow.send(f"辅修预览 {CRAFTS[0]}", ok=False)).code == (
        "SUBPROFESSION_SWITCH_COOLDOWN"
    )
    await flow.close()
