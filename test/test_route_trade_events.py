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
from nonebot_plugin_xiuxian_3.xiuxian.livelihood.route_rules import route_definitions
from test_livelihood import MutableClock


def _context(operation: str) -> CommandContext:
    return CommandContext(adapter="web", user_id="trade-events", operation_id=operation)


def test_dynamic_ironwood_route_freezes_event_and_status_replays(tmp_path: Path) -> None:
    async def run() -> None:
        data_dir = tmp_path / "data"
        shutil.copytree(Path(__file__).parents[1] / "data", data_dir)
        clock = MutableClock(datetime(2026, 11, 12, tzinfo=timezone.utc))
        runtime = create_runtime(data_dir=data_dir, clock=clock)
        assert (await runtime.dispatch(_context("create"), "开始修仙")).ok
        assert (await runtime.dispatch(_context("seek"), "寻仙问道")).ok
        with sqlite3.connect(runtime.settings.database_path) as connection:
            player_id = connection.execute(
                "SELECT id FROM players WHERE platform='web' AND platform_user_id='trade-events'"
            ).fetchone()[0]
            connection.execute(
                "UPDATE players SET stage='seeker', inventory_json=?, stamina=30 WHERE id=?",
                (json.dumps({"item.mat.wood": 2}), player_id),
            )

        preview = await runtime.dispatch(_context("preview"), "运输预览 铁木行商 木材 2")
        assert preview.code == "ROUTE_PREVIEW"
        assert preview.data["ready"] is True
        assert len(preview.data["event_labels"]) == 3
        assert "route." not in preview.message

        started = await runtime.dispatch(_context("ironwood-start"), "开始运输 铁木行商 木材 2")
        assert started.code == "ROUTE_STARTED"
        with sqlite3.connect(runtime.settings.database_path) as connection:
            frozen = json.loads(connection.execute(
                "SELECT snapshot_json FROM livelihood_trade_routes WHERE route_id=?",
                (started.data["route_id"],),
            ).fetchone()[0])
        assert frozen["event"]["outcome"] in {"success", "partial", "failed"}
        assert frozen["event"]["name"] == started.data["event_label"]

        await runtime.close()
        life_path = data_dir / "生活" / "生活.json"
        life = json.loads(life_path.read_text(encoding="utf-8"))
        ironwood = next(row for row in life["records"] if row["key"] == "route.town_ironwood_grove")
        ironwood["events"][0]["name"] = "改名后的诱饵"
        ironwood["events"][0]["reward_bonus_stones"] = 9999
        life_path.write_text(json.dumps(life, ensure_ascii=False), encoding="utf-8")
        runtime = create_runtime(data_dir=data_dir, clock=clock)

        status = await runtime.dispatch(_context("status-before"), "运输状态")
        assert status.code == "ROUTE_STATUS"
        assert status.data["ready"] is False
        assert status.data["event_label"] == frozen["event"]["name"]
        clock.advance(seconds=3600)
        ready = await runtime.dispatch(_context("status-after"), "运输状态")
        assert ready.data["ready"] is True
        settled = await runtime.dispatch(_context("ironwood-settle"), "结算运输")
        assert settled.code == "ROUTE_SETTLED"
        event = frozen["event"]
        expected_stones = 28 * event["reward_multiplier_bp"] // 10_000 + event["reward_bonus_stones"]
        assert settled.data["reward_stones"] == expected_stones
        assert settled.data["event_outcome"] == event["outcome"]
        if event["outcome"] == "failed":
            assert settled.data["returned_cargo"] == {"item.mat.wood": 2}
        if event["outcome"] == "success":
            assert settled.data["item_rewards"] == {"item.mat.array_sand": 1}
        replay = await runtime.dispatch(_context("ironwood-settle"), "结算运输")
        assert replay.data == {**settled.data, "idempotent_replay": True}
        await runtime.close()

    asyncio.run(run())


def test_route_event_contract_rejects_invalid_reward_item(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    shutil.copytree(Path(__file__).parents[1] / "data", data_dir)
    path = data_dir / "生活" / "生活.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    record = next(row for row in document["records"] if row["key"] == "route.town_ironwood_grove")
    record["events"][0]["item_rewards"] = {"item.missing": 1}
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ContentError, match="references invalid item"):
        route_definitions(ContentBundle.load(data_dir))
