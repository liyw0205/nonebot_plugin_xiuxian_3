from __future__ import annotations

import asyncio
import json
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.xiuxian.adventures.dao_echoes import (
    DAO_ECHOES_LANES,
    DAO_ECHOES_STAGES,
    DAO_ECHOES_STORY_KEY,
    dao_echoes_definition,
)
from nonebot_plugin_xiuxian_3.runtime import create_runtime


def _context(operation_id: str) -> CommandContext:
    return CommandContext(adapter="web", user_id="dao-echoes-player", operation_id=operation_id)


def test_dao_echoes_contract_has_three_sequential_ten_stage_lanes() -> None:
    assert len(DAO_ECHOES_STAGES) == 30
    assert tuple(dict.fromkeys(stage.lane for stage in DAO_ECHOES_STAGES)) == DAO_ECHOES_LANES
    for lane in DAO_ECHOES_LANES:
        stages = [stage for stage in DAO_ECHOES_STAGES if stage.lane == lane]
        assert [stage.stage for stage in stages] == list(range(1, 11))
        assert stages[0].prerequisites == ()
        assert all(
            stage.prerequisites == (f"lane.{lane}.chapter.{stage.stage - 1:02d}",)
            for stage in stages[1:]
        )
        assert len({stage.codex_flag for stage in stages}) == 10
    assert dao_echoes_definition("建设者", "01").key == "lane.builder.chapter.01"
    assert dao_echoes_definition("traveler", 10).key == "lane.traveler.chapter.10"


def test_dao_echoes_all_stages_produce_mainline_qualification_evidence() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            await runtime.dispatch(_context("create"), "开始修仙")
            await runtime.dispatch(_context("seek"), "寻仙问道")
            locked = await runtime.dispatch(
                _context("too-early"), "开始道源主线 建设者 1"
            )
            assert locked.code == "DAO_ECHOES_REQUIREMENT_MISSING"
            with runtime.repository._connect() as connection:
                connection.execute(
                    "UPDATE players SET stage='cultivator', realm_key='void_refining', realm_layer=10 "
                    "WHERE platform_user_id=?",
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

            for lane in DAO_ECHOES_LANES:
                for stage in range(1, 11):
                    started = await runtime.dispatch(
                        _context(f"start-{lane}-{stage}"),
                        f"开始道源主线 {lane} {stage}",
                    )
                    assert started.code == "DAO_ECHOES_STAGE_STARTED"
                    claimed = await runtime.dispatch(
                        _context(f"claim-{lane}-{stage}"),
                        f"领取道源主线奖励 {lane} {stage}",
                    )
                    assert claimed.code == "DAO_ECHOES_STAGE_CLAIMED"
                    assert claimed.data["first_clear"] is True

            replay = await runtime.dispatch(
                _context("claim-builder-1"), "领取道源主线奖励 builder 1"
            )
            assert replay.code == "DAO_ECHOES_STAGE_CLAIMED"
            assert replay.data["idempotent_replay"] is True

            repeated_start = await runtime.dispatch(
                _context("repeat-start-builder-1"), "开始道源主线 builder 1"
            )
            conflict = await runtime.dispatch(
                _context("repeat-start-builder-1"), "开始道源主线 builder 2"
            )
            assert conflict.code == "OPERATION_CONFLICT"
            active_status = await runtime.dispatch(_context("active-status"), "道源主线")
            assert active_status.data["stages"][0]["status"] == "running"
            qualification = await runtime.dispatch(
                _context("record-mainline"), "记录合道主线"
            )
            assert qualification.code == "QUEST_ACTION_RECORDED"
            assert qualification.data["progress"]["three_realm_mainline"] == 1
            repeated_claim = await runtime.dispatch(
                _context("repeat-claim-builder-1"), "领取道源主线奖励 builder 1"
            )
            assert repeated_start.data["first_clear"] is False
            assert repeated_claim.data["first_clear"] is False
            assert repeated_claim.data["reward"] == {}

            status = await runtime.dispatch(_context("status"), "道源主线")
            assert status.code == "DAO_ECHOES_STATUS"
            assert len(status.data["stages"]) == 30
            assert all(lane["completed"] == 10 for lane in status.data["lanes"])
            assert status.data["story_key"] == DAO_ECHOES_STORY_KEY

            with runtime.repository._connect() as connection:
                row = connection.execute(
                    "SELECT spirit_stones, inventory_json FROM players WHERE platform_user_id=?",
                    ("dao-echoes-player",),
                ).fetchone()
                assert int(row["spirit_stones"]) == int(before["spirit_stones"])
                assert json.loads(row["inventory_json"]) == json.loads(before["inventory_json"])
                run_count = connection.execute(
                    "SELECT COUNT(*) AS count FROM mainline_runs WHERE player_id="
                    "(SELECT id FROM players WHERE platform_user_id=?) AND story_key=? "
                    "AND status='claimed' AND first_clear_claimed=1",
                    ("dao-echoes-player", DAO_ECHOES_STORY_KEY),
                ).fetchone()
                assert int(run_count["count"]) == 30
                flag_count = connection.execute(
                    "SELECT COUNT(*) AS count FROM activity_events WHERE player_id="
                    "(SELECT id FROM players WHERE platform_user_id=?) AND event_key LIKE 'codex.story.dao_echoes.%'",
                    ("dao-echoes-player",),
                ).fetchone()
                assert int(flag_count["count"]) == 30
            await runtime.close()

    asyncio.run(run())
