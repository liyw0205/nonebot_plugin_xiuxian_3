from __future__ import annotations

import asyncio
import json
import shutil
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory
from pathlib import Path

import pytest

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.xiuxian.adventures.dao_echoes import (
    DAO_ECHOES_LANES,
    DAO_ECHOES_STORY_KEY,
    dao_echoes_definition,
    dao_echoes_definitions,
)
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError
from nonebot_plugin_xiuxian_3.xiuxian.adventures.dao_echoes import dao_echoes_definitions


def _context(operation_id: str) -> CommandContext:
    return CommandContext(adapter="web", user_id="dao-echoes-player", operation_id=operation_id)


class _MutableClock:
    def __init__(self, value: datetime):
        self.value = value

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **kwargs: int) -> None:
        self.value += timedelta(**kwargs)


def test_dao_echoes_contract_has_three_sequential_ten_stage_lanes() -> None:
    stages = dao_echoes_definitions()
    assert len(stages) == 30
    assert tuple(dict.fromkeys(stage.lane for stage in stages)) == DAO_ECHOES_LANES
    for lane in DAO_ECHOES_LANES:
        lane_stages = [stage for stage in stages if stage.lane == lane]
        assert [stage.stage for stage in lane_stages] == list(range(1, 11))
        assert lane_stages[0].prerequisites == ()
        assert all(
            stage.prerequisites == (f"lane.{lane}.chapter.{stage.stage - 1:02d}",)
            for stage in lane_stages[1:]
        )
        assert len({stage.codex_flag for stage in lane_stages}) == 10
    assert dao_echoes_definition("建设者", "01").key == "lane.builder.chapter.01"
    assert dao_echoes_definition("traveler", 10).key == "lane.traveler.chapter.10"


def test_dao_echoes_stage_requires_its_objective_before_claim() -> None:
    async def run() -> None:
        clock = _MutableClock(datetime(2026, 10, 7, 12, 5, tzinfo=timezone.utc))
        with TemporaryDirectory() as tmp_dir:
            data_dir = Path(tmp_dir) / "content"
            shutil.copytree(
                Path(__file__).parents[1] / "data",
                data_dir,
                ignore=shutil.ignore_patterns("*.sqlite3", "*.sqlite3-*", "*.db", "*.db-*"),
            )
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            await runtime.dispatch(_context("create"), "开始修仙")
            await runtime.dispatch(_context("seek"), "寻仙问道")
            locked = await runtime.dispatch(_context("too-early"), "开始道源主线 建设者 1")
            assert locked.code == "DAO_ECHOES_REQUIREMENT_MISSING"
            with runtime.repository._connect() as connection:
                connection.execute(
                    "UPDATE players SET stage='cultivator', realm_key='void_refining', realm_layer=10, "
                    "location_key='xuantian.cloud_city', stamina=5000, stamina_max=5000, "
                    "energy=5000, energy_max=5000 WHERE platform_user_id=?",
                    ("dao-echoes-player",),
                )
                before = connection.execute(
                    "SELECT spirit_stones, inventory_json FROM players WHERE platform_user_id=?",
                    ("dao-echoes-player",),
                ).fetchone()

            out_of_order = await runtime.dispatch(
                _context("out-of-order"), "开始道源主线 建设者 2"
            )
            assert out_of_order.code == "DAO_ECHOES_REQUIREMENT_MISSING"

            started = await runtime.dispatch(_context("start-builder-1"), "开始道源主线 builder 1")
            assert started.code == "DAO_ECHOES_STAGE_STARTED"
            # The objective is real: the claim is refused until the arrival is settled.
            early = await runtime.dispatch(_context("early-claim"), "领取道源主线奖励 builder 1")
            assert early.code == "MAINLINE_OBJECTIVES_INCOMPLETE"

            moved = await runtime.dispatch(_context("travel"), "前往 青石镇")
            assert moved.code == "TRAVEL_STARTED", moved.message
            clock.advance(seconds=181)
            settled = await runtime.dispatch(_context("settle"), "结算移动")
            assert settled.code == "TRAVEL_COMPLETED", settled.message

            claimed = await runtime.dispatch(
                _context("claim-builder-1"), "领取道源主线奖励 builder 1"
            )
            assert claimed.code == "DAO_ECHOES_STAGE_CLAIMED"
            assert claimed.data["first_clear"] is True

            repeated_start = await runtime.dispatch(
                _context("repeat-start-builder-1"), "开始道源主线 builder 1"
            )
            assert repeated_start.data["first_clear"] is False
            # A repeat challenge re-arms the objective: the same gate applies again.
            repeat_early = await runtime.dispatch(
                _context("repeat-early-claim"), "领取道源主线奖励 builder 1"
            )
            assert repeat_early.code == "MAINLINE_OBJECTIVES_INCOMPLETE"
            with runtime.repository._connect() as connection:
                connection.execute(
                    "UPDATE players SET location_key='xuantian.cloud_city', stamina=5000, "
                    "stamina_max=5000 WHERE platform_user_id=?",
                    ("dao-echoes-player",),
                )
            moved_again = await runtime.dispatch(_context("repeat-travel"), "前往 青石镇")
            assert moved_again.code == "TRAVEL_STARTED", moved_again.message
            clock.advance(seconds=181)
            settled_again = await runtime.dispatch(_context("repeat-settle"), "结算移动")
            assert settled_again.code == "TRAVEL_COMPLETED", settled_again.message
            repeated_claim = await runtime.dispatch(
                _context("repeat-claim-builder-1"), "领取道源主线奖励 builder 1"
            )
            assert repeated_claim.data["first_clear"] is False
            assert repeated_claim.data["reward"] == {}

            with runtime.repository._connect() as connection:
                row = connection.execute(
                    "SELECT spirit_stones, inventory_json FROM players WHERE platform_user_id=?",
                    ("dao-echoes-player",),
                ).fetchone()
                assert int(row["spirit_stones"]) == int(before["spirit_stones"])
                assert json.loads(row["inventory_json"]) == json.loads(before["inventory_json"])
            await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("adapter", ["qq.official", "onebot.v11"])
def test_dao_echoes_content_snapshot_and_close_are_adapter_consistent(
    tmp_path: Path, adapter: str
) -> None:
    source = Path(__file__).parents[1] / "data"
    data_dir = tmp_path / adapter.replace(".", "-")
    shutil.copytree(source, data_dir)
    mainline_path = data_dir / "剧情" / "主线.json"
    document = json.loads(mainline_path.read_text(encoding="utf-8"))
    first = next(row for row in document["records"] if row["key"] == "lane.builder.chapter.01")
    for row in document["records"]:
        if row["key"].startswith("lane.builder."):
            row["lane_name"] = "新名建设者"
    first["name"] = "新碑初校"
    first["desc"] = "你以新法校正旧碑，三界道路重新显出脉络。"
    mainline_path.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
    user = f"dao-snapshot-{adapter}"

    async def run() -> None:
        clock = _MutableClock(datetime(2026, 10, 7, 12, 5, tzinfo=timezone.utc))
        runtime = create_runtime(data_dir=data_dir, clock=clock)
        context = lambda operation_id: CommandContext(
            adapter=adapter, user_id=user, operation_id=f"{adapter}:{operation_id}"
        )
        assert (await runtime.adapters.dispatch(adapter, context("create"), "开始修仙")).ok
        assert (await runtime.adapters.dispatch(adapter, context("seek"), "寻仙问道")).ok
        with runtime.repository._connect() as connection:
            connection.execute(
                "UPDATE players SET stage='cultivator', realm_key='void_refining', realm_layer=10 "
                "WHERE platform=? AND platform_user_id=?",
                (adapter, user),
            )
        started = await runtime.adapters.dispatch(
            adapter, context("start"), "开始道源主线 builder 1"
        )
        assert started.ok
        assert "新名建设者·新碑初校" in started.message
        # The stage objective is real: leave 云城 and settle the arrival at 青石镇.
        with runtime.repository._connect() as connection:
            connection.execute(
                "UPDATE players SET location_key='xuantian.cloud_city', stamina=5000, "
                "stamina_max=5000 WHERE platform=? AND platform_user_id=?",
                (adapter, user),
            )
        moved = await runtime.adapters.dispatch(adapter, context("travel"), "前往 青石镇")
        assert moved.code == "TRAVEL_STARTED", moved.message
        clock.advance(seconds=181)
        settled = await runtime.adapters.dispatch(adapter, context("settle"), "结算移动")
        assert settled.code == "TRAVEL_COMPLETED", settled.message
        await runtime.close()

        document = json.loads(mainline_path.read_text(encoding="utf-8"))
        first = next(row for row in document["records"] if row["key"] == "lane.builder.chapter.01")
        first["status"] = "locked"
        for row in document["records"]:
            if row["key"].startswith("lane.builder."):
                row["lane_name"] = "闭关建设者"
        first["name"] = "不应覆盖旧快照"
        mainline_path.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")

        restored = create_runtime(data_dir=data_dir, clock=clock)
        claimed = await restored.adapters.dispatch(
            adapter, context("claim"), "领取道源主线奖励 builder 1"
        )
        assert claimed.ok
        assert "新名建设者·新碑初校" in claimed.message
        closed = await restored.adapters.dispatch(
            adapter, context("start-closed"), "开始道源主线 builder 1"
        )
        assert closed.code == "CONTENT_CLOSED"
        await restored.close()

    asyncio.run(run())


def test_dao_echoes_rejects_incomplete_lane_contract(tmp_path: Path) -> None:
    source = Path(__file__).parents[1] / "data"
    data_dir = tmp_path / "broken-content"
    shutil.copytree(source, data_dir)
    mainline_path = data_dir / "剧情" / "主线.json"
    document = json.loads(mainline_path.read_text(encoding="utf-8"))
    document["records"] = [
        row for row in document["records"] if row["key"] != "lane.traveler.chapter.10"
    ]
    # Drop the tail's forward link too, so the lane contract itself is what fires.
    for row in document["records"]:
        if row["key"] == "lane.traveler.chapter.09":
            row.pop("next_stage_key", None)
    mainline_path.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")

    with pytest.raises(ContentError, match="exactly 30"):
        dao_echoes_definitions(ContentBundle.load(data_dir))
