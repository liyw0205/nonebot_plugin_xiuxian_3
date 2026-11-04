from __future__ import annotations

import asyncio
import json
import shutil
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.advancement.reset_content import (
    talent_reset_definition,
)
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError

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
        self.user = "talent-reset-player"

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

    async def enter(self):
        for command in (
            "开始修仙 青玄",
            "寻仙问道",
            "完成引导 阅读",
            "前往近郊",
            "完成引导 采集",
            "完成引导 布阵",
            "选择道途 体修",
        ):
            await self.send(command)

    def player(self):
        with sqlite3.connect(self.runtime.settings.database_path) as db:
            db.row_factory = sqlite3.Row
            return dict(
                db.execute(
                    "SELECT * FROM players WHERE platform_user_id=?", (self.user,)
                ).fetchone()
            )

    def set_player(self, **values):
        with sqlite3.connect(self.runtime.settings.database_path) as db:
            db.execute(
                f"UPDATE players SET {', '.join(key + '=?' for key in values)} "
                "WHERE platform_user_id=?",
                tuple(values.values()) + (self.user,),
            )

    async def close(self):
        await self.runtime.close()

    def reopen(self):
        self.runtime = create_runtime(
            data_dir=self.root, clock=lambda: self.now, adapters=(self.adapter,)
        )


def _write_reset(data_root: Path, document: dict) -> None:
    (data_root / "养成" / "道脉重置.json").write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _reset_document(data_root: Path) -> dict:
    return json.loads((data_root / "养成" / "道脉重置.json").read_text(encoding="utf-8"))


def test_talent_reset_content_contract_and_rejections(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    shutil.copytree(ROOT / "data", data_root)
    bundle = ContentBundle.load(data_root)
    definition = talent_reset_definition(bundle)
    assert definition.min_realm == "foundation"
    assert definition.spirit_stone_cost == 300
    assert definition.refund_bp == 10000
    assert definition.cooldown_seconds == 604800
    assert definition.preview_ttl_seconds == 900

    document = _reset_document(data_root)
    record = document["records"][0]
    record["min_realm"] = "missing_realm"
    _write_reset(data_root, document)
    with pytest.raises(ContentError, match="unknown realm"):
        talent_reset_definition(ContentBundle.load(data_root))

    document = _reset_document(data_root)
    record = document["records"][0]
    record["min_realm"] = "foundation"
    record["refund_bp"] = 10001
    _write_reset(data_root, document)
    with pytest.raises(ContentError, match="refund_bp"):
        talent_reset_definition(ContentBundle.load(data_root))

    document = _reset_document(data_root)
    record = document["records"][0]
    record["refund_bp"] = 10000
    record["cost"] = {"currency.spirit_stone": 300, "item.herb.blood_grass": 1}
    _write_reset(data_root, document)
    with pytest.raises(ContentError, match="one currency"):
        talent_reset_definition(ContentBundle.load(data_root))

    document = _reset_document(data_root)
    record = document["records"][0]
    record["cost"] = {"currency.spirit_stone": 300}
    record["cooldown_seconds"] = 0
    _write_reset(data_root, document)
    with pytest.raises(ContentError, match="cooldown_seconds"):
        talent_reset_definition(ContentBundle.load(data_root))

    document = _reset_document(data_root)
    record = document["records"][0]
    record["cooldown_seconds"] = 604800
    record["unknown_field"] = True
    _write_reset(data_root, document)
    with pytest.raises(ContentError, match="unknown fields"):
        talent_reset_definition(ContentBundle.load(data_root))


def test_empty_tree_is_refused_and_free_tier_reset_keeps_points(tmp_path: Path) -> None:
    async def run():
        flow = Flow(tmp_path)
        try:
            await flow.enter()
            flow.set_player(realm_key="foundation", realm_layer=1, spirit_stones=1000)
            empty = await flow.send("道脉重置预览", ok=False)
            assert empty.code == "TALENT_RESET_EMPTY"

            await flow.send("解锁天赋 1")
            preview = await flow.send("道脉重置预览")
            assert preview.code == "TALENT_RESET_PREVIEW"
            assert preview.data["refund_points"] == 0
            confirmed = await flow.send("确认道脉重置")
            assert confirmed.code == "TALENT_RESET_CONFIRMED"
            player = flow.player()
            assert player["spirit_stones"] == 700
            assert player["talent_points"] == 0
            with sqlite3.connect(flow.runtime.settings.database_path) as db:
                assert db.execute("SELECT COUNT(*) FROM talent_node_states").fetchone()[0] == 0
                history = db.execute(
                    "SELECT refund_points, node_snapshot_json FROM talent_reset_records"
                ).fetchone()
                events = db.execute("SELECT COUNT(*) FROM talent_point_events").fetchone()[0]
            assert history[0] == 0
            assert len(json.loads(history[1])) == 1
            assert events == 0
        finally:
            await flow.close()

    asyncio.run(run())


def test_confirm_refunds_spent_points_and_clears_current_tree(tmp_path: Path) -> None:
    async def run():
        flow = Flow(tmp_path)
        try:
            await flow.enter()
            flow.set_player(
                realm_key="foundation",
                realm_layer=1,
                spirit_stones=1000,
                talent_points=10,
            )
            for tier in (1, 2, 3):
                await flow.send(f"解锁天赋 {tier}")
            preview = await flow.send("道脉重置预览")
            assert preview.data["refund_points"] == 3
            assert "talent.tree.body.tier1" not in preview.message

            confirmed = await flow.send("确认道脉重置", operation="reset-confirm")
            assert confirmed.code == "TALENT_RESET_CONFIRMED"
            player = flow.player()
            assert player["spirit_stones"] == 700
            assert player["talent_points"] == 10
            with sqlite3.connect(flow.runtime.settings.database_path) as db:
                assert db.execute(
                    "SELECT COUNT(*) FROM talent_node_states WHERE tree_key='body'"
                ).fetchone()[0] == 0
                history = db.execute(
                    "SELECT refund_points, node_snapshot_json FROM talent_reset_records"
                ).fetchone()
                event = db.execute(
                    "SELECT delta, balance_before, balance_after FROM talent_point_events "
                    "WHERE delta > 0 ORDER BY id DESC LIMIT 1"
                ).fetchone()
            assert history[0] == 3
            assert len(json.loads(history[1])) == 3
            assert event == (3, 7, 10)

            replay = await flow.send("确认道脉重置", operation="reset-confirm")
            assert replay.code == "TALENT_RESET_CONFIRMED"
            assert replay.data["idempotent_replay"] is True
            assert flow.player()["talent_points"] == 10

            profile = await flow.send("我的道脉")
            assert "未解锁" in profile.message
            relearn = await flow.send("解锁天赋 1")
            assert relearn.code == "TALENT_UNLOCKED"
        finally:
            await flow.close()

    asyncio.run(run())


def test_cooldown_and_insufficient_stones_are_zero_write(tmp_path: Path) -> None:
    async def run():
        flow = Flow(tmp_path)
        try:
            await flow.enter()
            flow.set_player(
                realm_key="foundation",
                realm_layer=1,
                spirit_stones=1000,
                talent_points=10,
            )
            await flow.send("解锁天赋 1")
            await flow.send("道脉重置预览")
            await flow.send("确认道脉重置")

            await flow.send("解锁天赋 1")
            blocked = await flow.send("道脉重置预览", ok=False)
            assert blocked.code == "TALENT_RESET_COOLDOWN"

            flow.now += timedelta(days=7, seconds=1)
            available = await flow.send("道脉重置预览")
            assert available.code == "TALENT_RESET_PREVIEW"

            flow.set_player(spirit_stones=100)
            poor = await flow.send("确认道脉重置", ok=False)
            assert poor.code == "RESOURCE_INSUFFICIENT"
            assert flow.player()["spirit_stones"] == 100
            with sqlite3.connect(flow.runtime.settings.database_path) as db:
                assert db.execute("SELECT COUNT(*) FROM talent_node_states").fetchone()[0] == 1
        finally:
            await flow.close()

    asyncio.run(run())


def test_expired_preview_and_changed_nodes_conflict(tmp_path: Path) -> None:
    async def run():
        flow = Flow(tmp_path)
        try:
            await flow.enter()
            flow.set_player(
                realm_key="foundation",
                realm_layer=1,
                spirit_stones=1000,
                talent_points=10,
            )
            await flow.send("解锁天赋 1")
            await flow.send("道脉重置预览")
            flow.now += timedelta(minutes=16)
            expired = await flow.send("确认道脉重置", ok=False)
            assert expired.code == "TALENT_RESET_PREVIEW_EXPIRED"
            assert flow.player()["spirit_stones"] == 1000

            await flow.send("道脉重置预览", operation="preview-change")
            await flow.send("解锁天赋 2")
            changed = await flow.send("确认道脉重置", operation="confirm-change", ok=False)
            assert changed.code == "TALENT_RESET_CONFLICT"
            with sqlite3.connect(flow.runtime.settings.database_path) as db:
                assert db.execute("SELECT COUNT(*) FROM talent_node_states").fetchone()[0] == 2
        finally:
            await flow.close()

    asyncio.run(run())


def test_plan_survives_restart_and_help_lists_reset(tmp_path: Path) -> None:
    async def run():
        flow = Flow(tmp_path, adapter="qq.official")
        try:
            await flow.enter()
            flow.set_player(
                realm_key="foundation",
                realm_layer=1,
                spirit_stones=1000,
                talent_points=10,
            )
            await flow.send("解锁天赋 1")
            preview = await flow.send("道脉重置预览")
            plan_id = preview.data["plan_id"]

            help_result = await flow.send("修仙帮助 修炼")
            assert "道脉重置" in help_result.message
            assert "确认道脉重置" in help_result.message
            assert "talent.reset.standard" not in help_result.message

            await flow.close()
            flow.reopen()
            result = await flow.send("确认道脉重置", operation="reset-after-restart")
            assert result.code == "TALENT_RESET_CONFIRMED"
            with sqlite3.connect(flow.runtime.settings.database_path) as db:
                assert db.execute(
                    "SELECT status FROM talent_reset_plans WHERE plan_id=?", (plan_id,)
                ).fetchone()[0] == "confirmed"
            assert flow.player()["spirit_stones"] == 700
            await flow.close()
        finally:
            pass

    asyncio.run(run())
