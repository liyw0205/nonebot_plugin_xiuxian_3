from __future__ import annotations

import asyncio
import json
import shutil
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.adventures.mainline import (
    LIVELIHOOD_ECHOES_STORY_KEY,
    mainline_definitions,
)
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError


DATA = Path(__file__).parents[1] / "data"
ADAPTERS = ("qq.official", "onebot.v11")


class Clock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **kwargs: int) -> None:
        self.value += timedelta(**kwargs)


def _context(adapter: str, user: str, operation: str) -> CommandContext:
    return CommandContext(
        adapter=adapter,
        user_id=user,
        request_id=f"{adapter}:{user}:{operation}",
        operation_id=f"{adapter}:{user}:{operation}",
        can_write_assets=True,
    )


async def _create_mortal(runtime, adapter: str, user: str) -> int:
    assert (await runtime.adapters.dispatch(adapter, _context(adapter, user, "create"), "开始修仙")).ok
    assert (await runtime.adapters.dispatch(adapter, _context(adapter, user, "seek"), "寻仙问道")).ok
    with sqlite3.connect(runtime.settings.database_path) as connection:
        return int(
            connection.execute(
                "SELECT id FROM players WHERE platform=? AND platform_user_id=?",
                (adapter, user),
            ).fetchone()[0]
        )


def _state(runtime) -> dict[str, list[tuple]]:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        return {
            table: connection.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
            for table in (
                "players", "player_reputations", "mainline_runs", "idle_assignments",
                "operations", "activity_events", "economy_ledger_entries", "production_facility_slots",
            )
        }


def test_livelihood_echoes_content_closes_only_open_sources() -> None:
    bundle = ContentBundle.load(DATA)
    definitions = {
        item.key: item
        for item in mainline_definitions(bundle, story_key=LIVELIHOOD_ECHOES_STORY_KEY)
    }
    stages = [definitions[f"livelihood_echoes.{index}"] for index in (1, 2, 3)]
    assert [item.next_stage_key for item in stages] == [
        "livelihood_echoes.2",
        "livelihood_echoes.3",
        None,
    ]
    assert [item.objectives[0]["route_key"] for item in stages] == [
        "idle.town_errand",
        "idle.herb_watch",
        "idle.workshop_care",
    ]
    for route_key in ("idle.town_errand", "idle.herb_watch", "idle.workshop_care"):
        route = bundle.require("livelihood", route_key)
        assert route["status"] == "active"
        assert bundle.require("reward", route["reward_pool_key"])["status"] == "active"
        assert bundle.require("reward", route["fallback_reward_pool_key"])["status"] == "active"

@pytest.mark.parametrize("source", ["unknown_route", "locked_route", "full_pool", "fallback_pool", "body"])
def test_livelihood_echoes_rejects_invalid_content(tmp_path, source) -> None:
    data_dir = tmp_path / "content"
    shutil.copytree(DATA, data_dir)
    if source in {"unknown_route", "body"}:
        path = data_dir / "剧情" / "主线.json"
        document = json.loads(path.read_text(encoding="utf-8"))
        stage = next(row for row in document["records"] if row["key"] == "livelihood_echoes.2")
        if source == "unknown_route":
            stage["objectives"][0]["route_key"] = "idle.missing"
        else:
            stage["body"] = ""
    else:
        path = data_dir / ("生活/生活.json" if source == "locked_route" else "奖励/奖励.json")
        document = json.loads(path.read_text(encoding="utf-8"))
        key = {
            "locked_route": "idle.herb_watch",
            "full_pool": "reward_pool.idle.herb_watch",
            "fallback_pool": "reward_pool.idle.herb_watch.fallback",
        }[source]
        next(row for row in document["records"] if row["key"] == key)["status"] = "locked"
    path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ContentError):
        mainline_definitions(ContentBundle.load(data_dir), story_key=LIVELIHOOD_ECHOES_STORY_KEY)


def test_livelihood_echoes_help_and_full_chain_on_both_adapters() -> None:
    async def run() -> None:
        clock = Clock(datetime(2026, 11, 20, 8, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock, adapters=ADAPTERS)
            try:
                help_result = await runtime.adapters.dispatch(
                    "qq.official", _context("qq.official", "help", "help"), "修仙帮助 生活"
                )
                assert help_result.code == "HELP_CATEGORY"
                assert "青石镇常驻生计回响主线" in help_result.message
                assert "作坊值守" in help_result.message

                for adapter in ADAPTERS:
                    user = f"livelihood-{adapter}"
                    dispatch = lambda operation, command: runtime.adapters.dispatch(
                        adapter, _context(adapter, user, operation), command
                    )
                    player_id = await _create_mortal(runtime, adapter, user)

                    assert (await dispatch("status", "青石镇常驻生计回响主线")).code == "MAINLINE_STATUS"
                    assert (await dispatch("stage1-start", "开始青石镇常驻生计回响主线 镇中行旅")).code == "MAINLINE_STARTED"
                    assert (await dispatch("town-preview", "挂机预览 镇中行旅")).code == "IDLE_PREVIEW"
                    assert (await dispatch("town-start", "开始挂机 镇中行旅")).code == "IDLE_STARTED"
                    assert (await dispatch("town-early", "领取挂机")).code == "IDLE_CLAIM_TOO_EARLY"
                    assert (await dispatch("stage1-early", "领取青石镇常驻生计回响主线奖励 镇中行旅")).code == "MAINLINE_OBJECTIVES_INCOMPLETE"
                    clock.advance(hours=2)
                    assert (await dispatch("town-claim", "领取挂机")).code == "IDLE_CLAIMED"
                    assert (await dispatch("stage1-claim", "领取青石镇常驻生计回响主线奖励 镇中行旅")).code == "MAINLINE_REWARD_CLAIMED"

                    assert (await dispatch("stage2-start", "开始青石镇常驻生计回响主线 灵圃看护")).code == "MAINLINE_STARTED"
                    before = _state(runtime)
                    missing_residence = await dispatch("herb-start", "开始挂机 灵圃看护")
                    assert missing_residence.code == "IDLE_REQUIREMENT_MISSING"
                    assert _state(runtime) == before
                    assert (await dispatch("lease", "租住居所 客房")).code == "RESIDENCE_LEASED"
                    clock.advance(days=4)
                    before = _state(runtime)
                    assert (await dispatch("herb-start", "开始挂机 灵圃看护")).code == "IDLE_REQUIREMENT_MISSING"
                    assert _state(runtime) == before
                    assert (await dispatch("lease-renew", "租住居所 客房")).code == "RESIDENCE_LEASED"
                    assert (await dispatch("herb-start", "开始挂机 灵圃看护")).code == "IDLE_STARTED"
                    clock.advance(hours=29)
                    expired = await dispatch("herb-expired", "领取挂机")
                    assert expired.code == "IDLE_CLAIMED" and expired.data["fallback"] is True
                    assert (await dispatch("stage2-expired", "领取青石镇常驻生计回响主线奖励 灵圃看护")).code == "MAINLINE_OBJECTIVES_INCOMPLETE"

                    clock.advance(days=1)
                    assert (await dispatch("herb-retry-start", "开始挂机 灵圃看护")).code == "IDLE_STARTED"
                    clock.advance(hours=4)
                    assert (await dispatch("herb-claim", "领取挂机")).code == "IDLE_CLAIMED"
                    assert (await dispatch("stage2-claim", "领取青石镇常驻生计回响主线奖励 灵圃看护")).code == "MAINLINE_REWARD_CLAIMED"

                    assert (await dispatch("stage3-start", "开始青石镇常驻生计回响主线 作坊值守")).code == "MAINLINE_STARTED"
                    before = _state(runtime)
                    assert (await dispatch("workshop-start", "开始挂机 作坊值守")).code == "IDLE_REQUIREMENT_MISSING"
                    assert _state(runtime) == before
                    for index, command in enumerate((
                        "完成引导 阅读", "前往近郊", "完成引导 采集", "完成引导 炼丹", "选择道途 器修",
                    )):
                        result = await dispatch(f"tool-source-{index}", command)
                        assert result.ok, (command, result.code, result.message)
                    before = _state(runtime)
                    assert (await dispatch("unavailable-facility", "开始挂机 作坊值守 facility.artifice_table.1")).code == "IDLE_REQUIREMENT_MISSING"
                    assert _state(runtime) == before
                    workshop = await dispatch("workshop-start", "开始挂机 作坊值守")
                    assert workshop.code == "IDLE_STARTED", workshop.message
                    assert workshop.data["tool_key"] == "item.tool.basic_hammer"
                    assert workshop.data["facility_slot_key"] is None
                    clock.advance(hours=3)
                    assert (await dispatch("workshop-claim", "领取挂机")).code == "IDLE_CLAIMED"
                    claimed = await dispatch("stage3-claim", "领取青石镇常驻生计回响主线奖励 作坊值守")
                    assert claimed.code == "MAINLINE_REWARD_CLAIMED", claimed.message
                    replay = await dispatch("stage3-claim", "领取青石镇常驻生计回响主线奖励 作坊值守")
                    assert replay.data["idempotent_replay"] is True

                    with sqlite3.connect(runtime.settings.database_path) as connection:
                        inventory, durability = connection.execute(
                            "SELECT inventory_json, durability_json FROM players WHERE id=?", (player_id,)
                        ).fetchone()
                        assert json.loads(inventory)["item.tool.basic_hammer"] == 1
                        assert json.loads(durability)["item.tool.basic_hammer"] == 9950
                        assert connection.execute(
                            "SELECT COUNT(*) FROM operations WHERE operation_id LIKE ?",
                            (f"{adapter}:{user}:stage%-claim",),
                        ).fetchone()[0] == 3
            finally:
                await runtime.close()

    asyncio.run(run())


def test_livelihood_echoes_rejects_old_other_and_exhausted_sources() -> None:
    async def run() -> None:
        clock = Clock(datetime(2026, 11, 22, 0, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock, adapters=("onebot.v11",))
            adapter, user = "onebot.v11", "source-owner"

            async def send(operation, command, *, owner=user):
                return await runtime.adapters.dispatch(adapter, _context(adapter, owner, operation), command)

            try:
                await _create_mortal(runtime, adapter, user)
                await _create_mortal(runtime, adapter, "source-other")
                assert (await send("old-start", "开始挂机 镇中行旅")).ok
                assert (await send("story-start", "开始青石镇常驻生计回响主线 镇中行旅")).ok
                clock.advance(hours=2)
                assert (await send("old-claim", "领取挂机")).ok
                assert (await send("other-start", "开始挂机 镇中行旅", owner="source-other")).ok
                clock.advance(hours=2)
                assert (await send("other-claim", "领取挂机", owner="source-other")).ok
                before = _state(runtime)
                assert (await send("story-claim", "领取青石镇常驻生计回响主线奖励 镇中行旅")).code == "MAINLINE_OBJECTIVES_INCOMPLETE"
                assert _state(runtime) == before

                assert (await send("new-start", "开始挂机 镇中行旅")).ok
                clock.advance(hours=2)
                assert (await send("new-claim", "领取挂机")).ok
                assert (await send("story-claim", "领取青石镇常驻生计回响主线奖励 镇中行旅")).ok
                clock.advance(seconds=1)
                assert (await send("story-repeat", "开始青石镇常驻生计回响主线 镇中行旅")).ok
                before = _state(runtime)
                assert (await send("daily-retry", "开始挂机 镇中行旅")).code == "IDLE_DAILY_LIMIT"
                assert (await send("repeat-claim", "领取青石镇常驻生计回响主线奖励 镇中行旅")).code == "MAINLINE_OBJECTIVES_INCOMPLETE"
                assert _state(runtime) == before
                clock.advance(days=1)
                assert (await send("daily-retry", "开始挂机 镇中行旅")).ok
                clock.advance(hours=2)
                assert (await send("retry-claim", "领取挂机")).ok
                repeated = await send("repeat-claim", "领取青石镇常驻生计回响主线奖励 镇中行旅")
                assert repeated.code == "MAINLINE_REWARD_CLAIMED"
                assert repeated.data["first_clear"] is False
                assert repeated.data["reward"] == {"spirit_stones": 4}
            finally:
                await runtime.close()

    asyncio.run(run())


def test_livelihood_echoes_recovers_frozen_sources_and_rolls_back_failed_rewards(tmp_path) -> None:
    async def run() -> None:
        data_dir = tmp_path / "content"
        shutil.copytree(DATA, data_dir)
        clock = Clock(datetime(2026, 11, 24, 0, tzinfo=timezone.utc))
        adapter, user = "onebot.v11", "recover-echoes"
        runtime = create_runtime(data_dir=data_dir, clock=clock, adapters=(adapter,))

        async def send(operation, command):
            return await runtime.adapters.dispatch(adapter, _context(adapter, user, operation), command)

        try:
            await _create_mortal(runtime, adapter, user)
            assert (await send("story-start", "开始青石镇常驻生计回响主线 镇中行旅")).ok
            idle = await send("idle-start", "开始挂机 镇中行旅")
            assert idle.code == "IDLE_STARTED"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                frozen_idle = json.loads(connection.execute(
                    "SELECT snapshot_json FROM idle_assignments WHERE assignment_id=?",
                    (idle.data["assignment_id"],),
                ).fetchone()[0])
            await runtime.close()

            story_path = data_dir / "剧情" / "主线.json"
            document = json.loads(story_path.read_text(encoding="utf-8"))
            stage = next(row for row in document["records"] if row["key"] == "livelihood_echoes.1")
            stage["objectives"][0]["route_key"] = "idle.herb_watch"
            stage["first_clear_reward"]["spirit_stones"] = 9999
            stage["body"] = "热更新后的故事只影响新开始的关卡。" + stage["body"]
            story_path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
            runtime = create_runtime(data_dir=data_dir, clock=clock, adapters=(adapter,))
            assert (await send("status", "青石镇常驻生计回响主线")).code == "MAINLINE_STATUS"
            clock.advance(hours=2)

            with sqlite3.connect(runtime.settings.database_path) as connection:
                run_id, original = connection.execute(
                    "SELECT id, snapshot_json FROM mainline_runs WHERE story_key=?",
                    (LIVELIHOOD_ECHOES_STORY_KEY,),
                ).fetchone()
                broken = json.loads(original)
                broken["baseline_idle_assignment_id"] = True
                connection.execute("UPDATE mainline_runs SET snapshot_json=? WHERE id=?", (json.dumps(broken), run_id))
            before = _state(runtime)
            assert (await send("broken-baseline", "领取青石镇常驻生计回响主线奖励 镇中行旅")).code == "PERSISTENCE_ERROR"
            assert _state(runtime) == before
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute("UPDATE mainline_runs SET snapshot_json=? WHERE id=?", (original, run_id))

            for operation_name, operation, command in (
                ("specials.claim_idle", "idle-claim", "领取挂机"),
                ("mainline.claim_first_clear", "story-claim", "领取青石镇常驻生计回响主线奖励 镇中行旅"),
            ):
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "CREATE TRIGGER fail_echoes_ledger BEFORE INSERT ON operations "
                        f"WHEN NEW.operation_name='{operation_name}' "
                        "BEGIN SELECT RAISE(ABORT, 'injected echoes ledger failure'); END"
                    )
                before = _state(runtime)
                failed = await send(operation, command)
                assert failed.code == "PERSISTENCE_ERROR", failed.message
                assert _state(runtime) == before
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute("DROP TRIGGER fail_echoes_ledger")
                claimed = await send(operation, command)
                assert claimed.ok, claimed.message
                if operation_name == "specials.claim_idle":
                    assert claimed.data["reward"] == frozen_idle["full_reward"]
                    assert claimed.data["fallback"] is False
                else:
                    assert claimed.data["reward"] == {"spirit_stones": 18, "local_reputation": 2}
                before = _state(runtime)
                replay = await send(operation, command)
                assert replay.data["idempotent_replay"] is True
                assert replay.data["reward"] == claimed.data["reward"]
                assert _state(runtime) == before
            before = _state(runtime)
            assert (await send("story-claim", "领取青石镇常驻生计回响主线奖励 灵圃看护")).code == "OPERATION_CONFLICT"
            assert _state(runtime) == before
        finally:
            await runtime.close()

    asyncio.run(run())
