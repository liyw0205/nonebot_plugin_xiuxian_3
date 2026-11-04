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
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError
from nonebot_plugin_xiuxian_3.xiuxian.paths.switch_content import (
    path_switch_definition,
)

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
        self.user = "path-switch-player"

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

    async def enter(self, choice="体修", *, user=None):
        identity = user or self.user
        for command in (
            "开始修仙 青玄",
            "寻仙问道",
            "完成引导 阅读",
            "前往近郊",
            "完成引导 采集",
            "完成引导 布阵",
            f"选择道途 {choice}",
        ):
            await self.send(command, user=identity)

    def player(self, user=None):
        identity = user or self.user
        with sqlite3.connect(self.runtime.settings.database_path) as db:
            db.row_factory = sqlite3.Row
            return dict(
                db.execute(
                    "SELECT * FROM players WHERE platform_user_id=?",
                    (identity,),
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


def _write_switch(data_root: Path, document: dict) -> None:
    (data_root / "道途" / "切换.json").write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _switch_document(data_root: Path) -> dict:
    return json.loads((data_root / "道途" / "切换.json").read_text(encoding="utf-8"))


def test_path_switch_content_contract_and_rejections(tmp_path: Path) -> None:
    data_root = tmp_path / "data"
    shutil.copytree(ROOT / "data", data_root)
    bundle = ContentBundle.load(data_root)
    definition = path_switch_definition(bundle)
    assert definition.min_realm == "foundation"
    assert definition.min_layer == 1
    assert definition.spirit_stone_cost == 500
    assert definition.token_item_key == "item.token.path_respec"
    assert definition.token_quantity == 1
    assert definition.cooldown_seconds == 604800
    assert definition.preview_ttl_seconds == 900

    document = _switch_document(data_root)
    record = document["records"][0]
    record["min_realm"] = "missing_realm"
    _write_switch(data_root, document)
    with pytest.raises(ContentError, match="unknown realm"):
        path_switch_definition(ContentBundle.load(data_root))

    document = _switch_document(data_root)
    record = document["records"][0]
    record["min_realm"] = "foundation"
    record["cooldown_seconds"] = 0
    _write_switch(data_root, document)
    with pytest.raises(ContentError, match="cooldown_seconds"):
        path_switch_definition(ContentBundle.load(data_root))

    document = _switch_document(data_root)
    record = document["records"][0]
    record["cooldown_seconds"] = 604800
    record["cost"] = {
        "currency.spirit_stone": 500,
        "item.token.path_respec": 1,
        "item.herb.blood_grass": 1,
    }
    _write_switch(data_root, document)
    with pytest.raises(ContentError, match="one item"):
        path_switch_definition(ContentBundle.load(data_root))

    document = _switch_document(data_root)
    record = document["records"][0]
    record["cost"] = {
        "currency.spirit_stone": 500,
        "item.herb.blood_grass": 1,
    }
    _write_switch(data_root, document)
    with pytest.raises(ContentError, match="must be a token"):
        path_switch_definition(ContentBundle.load(data_root))

    document = _switch_document(data_root)
    record = document["records"][0]
    record["cost"] = {
        "currency.spirit_stone": 500,
        "item.token.path_respec": 1,
    }
    record["unknown_field"] = True
    _write_switch(data_root, document)
    with pytest.raises(ContentError, match="unknown fields"):
        path_switch_definition(ContentBundle.load(data_root))


def test_claim_token_is_one_time_and_replays(tmp_path: Path) -> None:
    async def run():
        flow = Flow(tmp_path)
        try:
            await flow.enter("体修")
            early = await flow.send("领取转修令", ok=False)
            assert early.code == "PATH_SWITCH_REQUIREMENT"
            assert "item.token.path_respec" not in flow.player()["inventory_json"]

            flow.set_player(realm_key="foundation", realm_layer=1, spirit_stones=1000)
            claimed = await flow.send("领取转修令", operation="claim-1")
            assert claimed.code == "PATH_SWITCH_TOKEN_CLAIMED"
            assert flow.player()["inventory_json"].count("item.token.path_respec") == 1

            replay = await flow.send("领取转修令", operation="claim-1")
            assert replay.code == "PATH_SWITCH_TOKEN_CLAIMED_ALREADY"
            assert replay.data["idempotent_replay"] is True

            again = await flow.send("领取转修令", operation="claim-2", ok=False)
            assert again.code == "PATH_SWITCH_TOKEN_CLAIMED"
            inventory = json.loads(flow.player()["inventory_json"])
            assert inventory["item.token.path_respec"] == 1

            # A token is consumed by a switch; the next claim waits for the
            # shared seven-day cooldown, so the loop stays repeatable without
            # allowing stockpiling.
            await flow.send("转修道途 法修")
            await flow.send("确认转修")
            waiting = await flow.send("领取转修令", operation="claim-3", ok=False)
            assert waiting.code == "PATH_SWITCH_COOLDOWN"
            flow.now += timedelta(days=7, seconds=1)
            reclaimed = await flow.send("领取转修令", operation="claim-4")
            assert reclaimed.code == "PATH_SWITCH_TOKEN_CLAIMED"
            assert flow.player()["path_key"] == "spell"
        finally:
            await flow.close()

    asyncio.run(run())


def test_preview_and_confirm_switch_keep_old_build_history(tmp_path: Path) -> None:
    async def run():
        flow = Flow(tmp_path)
        try:
            await flow.enter("体修")
            flow.set_player(realm_key="foundation", realm_layer=1, spirit_stones=1000)
            talent = await flow.send("解锁天赋 1")
            assert talent.code == "TALENT_UNLOCKED"
            await flow.send("领取转修令")

            preview = await flow.send("转修道途 法修")
            assert preview.code == "PATH_SWITCH_PREVIEW"
            assert "体修" in preview.message and "法修" in preview.message
            assert "500" in preview.message
            assert flow.player()["spirit_stones"] == 1000
            plan_id = preview.data["plan_id"]

            confirmed = await flow.send("确认转修", operation="confirm-replay")
            assert confirmed.code == "PATH_SWITCH_CONFIRMED"
            replay = await flow.send("确认转修", operation="confirm-replay")
            assert replay.code == "PATH_SWITCH_CONFIRMED"
            assert replay.data["idempotent_replay"] is True
            player = flow.player()
            assert player["path_key"] == "spell"
            assert player["subprofession_key"] is None
            assert player["spirit_stones"] == 500
            inventory = json.loads(player["inventory_json"])
            assert "item.token.path_respec" not in inventory
            assert inventory["skill.body.heavy_strike"] == 1

            with sqlite3.connect(flow.runtime.settings.database_path) as db:
                talent_rows = db.execute(
                    "SELECT node_key, tree_key FROM talent_node_states WHERE player_id = ?",
                    (player["id"],),
                ).fetchall()
                plan = db.execute(
                    "SELECT status, confirm_operation_id FROM path_switch_plans WHERE plan_id = ?",
                    (plan_id,),
                ).fetchone()
            assert talent_rows == [("talent.tree.body.tier1", "body")]
            assert plan[0] == "confirmed"

            profile = await flow.send("我的道脉")
            assert "法修" in profile.message
            assert "灵力运转·第1阶" in profile.message
            assert "体魄淬炼·第1阶" not in profile.message

            play_forward = await flow.send("确认转修", operation="confirm-second", ok=False)
            # The adapter generated a fresh operation id, so the plan is no longer
            # pending; the second confirm must not charge again.
            assert play_forward.code == "PATH_SWITCH_NOT_FOUND"
            assert flow.player()["spirit_stones"] == 500
        finally:
            await flow.close()

    asyncio.run(run())


def test_switch_cooldown_and_expired_preview_are_zero_write(tmp_path: Path) -> None:
    async def run():
        flow = Flow(tmp_path)
        try:
            await flow.enter("体修")
            flow.set_player(realm_key="foundation", realm_layer=1, spirit_stones=2000)
            await flow.send("领取转修令")
            await flow.send("转修道途 法修")
            await flow.send("确认转修")

            blocked = await flow.send("转修道途 体修", ok=False)
            assert blocked.code == "PATH_SWITCH_COOLDOWN"
            assert flow.player()["path_key"] == "spell"

            flow.now += timedelta(days=7, seconds=1)
            ready = await flow.send("转修道途 体修")
            assert ready.code == "PATH_SWITCH_PREVIEW"

            flow.now += timedelta(minutes=16)
            expired = await flow.send("确认转修", ok=False)
            assert expired.code == "PATH_SWITCH_PREVIEW_EXPIRED"
            assert flow.player()["path_key"] == "spell"
            assert flow.player()["spirit_stones"] == 1500
        finally:
            await flow.close()

    asyncio.run(run())


def test_missing_token_and_stones_do_not_change_state(tmp_path: Path) -> None:
    async def run():
        flow = Flow(tmp_path)
        try:
            await flow.enter("体修")
            flow.set_player(realm_key="foundation", realm_layer=1, spirit_stones=1000)
            await flow.send("转修道途 法修")
            missing = await flow.send("确认转修", ok=False)
            assert missing.code == "PATH_SWITCH_TOKEN_MISSING"
            assert flow.player()["path_key"] == "body"

            await flow.send("领取转修令")
            flow.set_player(spirit_stones=100)
            await flow.send("转修道途 法修", operation="preview-poor")
            poor = await flow.send("确认转修", operation="confirm-poor", ok=False)
            assert poor.code == "RESOURCE_INSUFFICIENT"
            player = flow.player()
            assert player["path_key"] == "body"
            assert player["spirit_stones"] == 100
            assert "item.token.path_respec" in json.loads(player["inventory_json"])
        finally:
            await flow.close()

    asyncio.run(run())


def test_support_switch_requires_and_then_clears_subprofession(tmp_path: Path) -> None:
    async def run():
        flow = Flow(tmp_path)
        try:
            await flow.enter("体修")
            flow.set_player(realm_key="foundation", realm_layer=1, spirit_stones=2000)
            await flow.send("领取转修令")

            missing = await flow.send("转修道途 辅修", ok=False)
            assert missing.code == "PATH_SWITCH_INVALID"

            preview = await flow.send("转修道途 辅修 炼器")
            assert preview.code == "PATH_SWITCH_PREVIEW"
            confirmed = await flow.send("确认转修")
            assert confirmed.code == "PATH_SWITCH_CONFIRMED"
            assert flow.player()["subprofession_key"] == "artifice"

            flow.now += timedelta(days=7, seconds=1)
            await flow.send("领取转修令")
            await flow.send("转修道途 体修")
            await flow.send("确认转修")
            assert flow.player()["path_key"] == "body"
            assert flow.player()["subprofession_key"] is None
        finally:
            await flow.close()

    asyncio.run(run())


def test_domain_or_dao_fruit_state_blocks_switch(tmp_path: Path) -> None:
    async def run():
        flow = Flow(tmp_path)
        try:
            await flow.enter("体修")
            flow.set_player(
                realm_key="foundation",
                realm_layer=1,
                spirit_stones=1000,
                domain_key="domain.abyss_shadow",
            )
            await flow.send("领取转修令")
            blocked = await flow.send("转修道途 法修", ok=False)
            assert blocked.code == "PATH_SWITCH_CONFLICT"
            assert flow.player()["path_key"] == "body"
            assert flow.player()["spirit_stones"] == 1000
        finally:
            await flow.close()

    asyncio.run(run())


def test_switch_plan_survives_restart_and_help_lists_commands(tmp_path: Path) -> None:
    async def run():
        flow = Flow(tmp_path, adapter="qq.official")
        try:
            await flow.enter("体修")
            flow.set_player(realm_key="foundation", realm_layer=1, spirit_stones=1000)
            await flow.send("领取转修令")
            preview = await flow.send("转修道途 法修")
            plan_id = preview.data["plan_id"]

            help_result = await flow.send("修仙帮助 修炼")
            assert "道途转修" in help_result.message
            assert "领取转修令" in help_result.message
            assert "确认转修" in help_result.message
            assert "path.switch.standard" not in help_result.message

            await flow.close()
            flow.reopen()
            result = await flow.send(
                "确认转修", operation="confirm-after-restart"
            )
            assert result.code == "PATH_SWITCH_CONFIRMED"
            assert flow.player()["path_key"] == "spell"
            with sqlite3.connect(flow.runtime.settings.database_path) as db:
                status = db.execute(
                    "SELECT status FROM path_switch_plans WHERE plan_id = ?", (plan_id,)
                ).fetchone()[0]
            assert status == "confirmed"
            await flow.close()
        finally:
            pass

    asyncio.run(run())
