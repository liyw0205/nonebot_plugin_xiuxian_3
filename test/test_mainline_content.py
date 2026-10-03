from __future__ import annotations

import asyncio
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime


def _context(adapter: str, user: str, operation_id: str) -> CommandContext:
    return CommandContext(adapter=adapter, user_id=user, operation_id=f"{adapter}:{operation_id}")


def test_xuantian_mainline_chapter_two_content_runs_on_both_adapters() -> None:
    async def run() -> None:
        now = datetime(2026, 9, 22, tzinfo=timezone.utc)
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=lambda: now)
            for adapter, user in (("qq.official", "chapter2-qq"), ("onebot.v11", "chapter2-onebot")):
                async def send(operation_id: str, command: str):
                    return await runtime.adapters.dispatch(adapter, _context(adapter, user, operation_id), command)

                assert (await send("create", "开始修仙")).ok
                assert (await send("seek", "寻仙问道")).ok
                for number in (1,):
                    assert (await send(f"start-{number}", f"开始主线 {number}")).ok
                    assert (await send(f"claim-{number}", f"领取主线奖励 {number}")).ok
                with runtime.repository._connect() as connection:
                    connection.execute(
                        "UPDATE players SET realm_key='qi_sensing', realm_layer=3 WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    )
                for number in (2, 3):
                    assert (await send(f"start-{number}", f"开始主线 {number}")).ok
                    assert (await send(f"claim-{number}", f"领取主线奖励 {number}")).ok
                assert (await send("commission-list", "城镇委托")).code == "COMMISSION_LIST"
                assert (await send("commission-accept", "接取委托 止血草供应")).code == "COMMISSION_ACCEPTED"
                assert (await send("commission-deliver", "交付委托 止血草供应")).code == "COMMISSION_DELIVERED"
                assert (await send("town-start", "开始主线 城镇委托")).ok
                assert (await send("town-claim", "领取主线奖励 城镇委托")).ok

                with runtime.repository._connect() as connection:
                    connection.execute(
                        "UPDATE players SET realm_key='foundation', realm_layer=6 WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    )
                for alias in ("云城初见", "商会听潮", "云铁入山", "矿兽试锋"):
                    assert (await send(f"start-{alias}", f"开始主线 {alias}")).ok
                    assert (await send(f"claim-{alias}", f"领取主线奖励 {alias}")).ok
                with runtime.repository._connect() as connection:
                    connection.execute(
                        "UPDATE players SET realm_key='golden_core', realm_layer=6 WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    )
                for alias in ("云舟试航", "阵堂初会", "阵纹试炼", "玄天新章"):
                    assert (await send(f"start-{alias}", f"开始主线 {alias}")).ok
                    claimed = await send(f"claim-{alias}", f"领取主线奖励 {alias}")
                    assert claimed.code == "MAINLINE_REWARD_CLAIMED"
                    replay = await send(f"claim-{alias}", f"领取主线奖励 {alias}")
                    assert replay.data["idempotent_replay"] is True
                with runtime.repository._connect() as connection:
                    count = connection.execute(
                        "SELECT COUNT(*) FROM mainline_runs WHERE player_id=(SELECT id FROM players WHERE platform=? AND platform_user_id=?) AND story_key=? AND first_clear_claimed=1",
                        (adapter, user, "story.mainline.xuantian"),
                    ).fetchone()[0]
                    assert count == 12
                    reputation = connection.execute(
                        "SELECT local_json FROM player_reputations WHERE player_id=(SELECT id FROM players WHERE platform=? AND platform_user_id=?)",
                        (adapter, user),
                    ).fetchone()[0]
                    assert json.loads(reputation)["local.xuantian.cloud_city"] == 10
            await runtime.close()

    asyncio.run(run())


def test_mainline_runtime_behavior_changes_with_content_json(tmp_path: Path) -> None:
    source = Path(__file__).parents[1] / "data"
    data_dir = tmp_path / "content"
    shutil.copytree(source, data_dir)
    mainline_path = data_dir / "剧情" / "主线.json"
    document = json.loads(mainline_path.read_text(encoding="utf-8"))
    first = next(row for row in document["records"] if row["key"] == "chapter.1.stage.1")
    first["first_clear_reward"]["local_reputation"] = 11
    mainline_path.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")

    async def run() -> None:
        now = datetime(2026, 9, 22, tzinfo=timezone.utc)
        runtime = create_runtime(data_dir=data_dir, clock=lambda: now)
        assert (await runtime.dispatch(_context("onebot.v11", "content-mainline", "create"), "开始修仙")).ok
        assert (await runtime.dispatch(_context("onebot.v11", "content-mainline", "seek"), "寻仙问道")).ok
        assert (await runtime.dispatch(_context("onebot.v11", "content-mainline", "start"), "开始主线 1")).ok
        claimed = await runtime.dispatch(
            _context("onebot.v11", "content-mainline", "claim"), "领取主线奖励 1"
        )
        assert claimed.data["reward"]["local_reputation"] == 11
        await runtime.close()

    asyncio.run(run())


def test_mainline_claim_uses_start_snapshot_after_content_closes(tmp_path: Path) -> None:
    source = Path(__file__).parents[1] / "data"
    data_dir = tmp_path / "content"
    shutil.copytree(source, data_dir)
    mainline_path = data_dir / "剧情" / "主线.json"

    async def run() -> None:
        now = datetime(2026, 9, 22, tzinfo=timezone.utc)
        runtime = create_runtime(data_dir=data_dir, clock=lambda: now)
        assert (await runtime.dispatch(_context("onebot.v11", "snapshot-mainline", "create"), "开始修仙")).ok
        assert (await runtime.dispatch(_context("onebot.v11", "snapshot-mainline", "seek"), "寻仙问道")).ok
        assert (await runtime.dispatch(_context("onebot.v11", "snapshot-mainline", "start"), "开始主线 1")).ok
        await runtime.close()

        document = json.loads(mainline_path.read_text(encoding="utf-8"))
        first = next(row for row in document["records"] if row["key"] == "chapter.1.stage.1")
        first["status"] = "locked"
        first["first_clear_reward"]["local_reputation"] = 99
        first["first_clear_reward"].pop("codex.place.outskirts")
        mainline_path.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")

        reloaded = create_runtime(data_dir=data_dir, clock=lambda: now)
        status = await reloaded.dispatch(
            _context("onebot.v11", "snapshot-mainline", "status"), "主线道途"
        )
        assert status.data["status"] == "running"
        claimed = await reloaded.dispatch(
            _context("onebot.v11", "snapshot-mainline", "claim"), "领取主线奖励 1"
        )
        assert claimed.code == "MAINLINE_REWARD_CLAIMED"
        assert claimed.data["reward"]["local_reputation"] == 3
        assert claimed.data["reward"]["codex.place.outskirts"] == 1
        replay = await reloaded.dispatch(
            _context("onebot.v11", "snapshot-mainline", "claim"), "领取主线奖励 1"
        )
        assert replay.data["idempotent_replay"] is True
        with reloaded.repository._connect() as connection:
            reputation = connection.execute(
                "SELECT local_json FROM player_reputations WHERE player_id=(SELECT id FROM players WHERE platform=? AND platform_user_id=?)",
                ("onebot.v11", "snapshot-mainline"),
            ).fetchone()[0]
            assert json.loads(reputation)["local.xuantian.new_town"] == 3
            events = connection.execute(
                "SELECT COUNT(*) FROM activity_events WHERE player_id=(SELECT id FROM players WHERE platform=? AND platform_user_id=?) AND event_key=?",
                ("onebot.v11", "snapshot-mainline", "codex.place.outskirts"),
            ).fetchone()[0]
            assert events == 1
        await reloaded.close()

    asyncio.run(run())


@pytest.mark.parametrize("adapter", ["qq.official", "onebot.v11"])
def test_mainline_reputation_uses_frozen_location_cap_after_restart(
    tmp_path: Path, adapter: str
) -> None:
    source = Path(__file__).parents[1] / "data"
    data_dir = tmp_path / adapter.replace(".", "-")
    shutil.copytree(source, data_dir)
    location_path = data_dir / "地图" / "地点.json"
    locations = json.loads(location_path.read_text(encoding="utf-8"))
    town = next(row for row in locations["records"] if row["key"] == "xuantian.new_town")
    town["local_reputation_maximum"] = 4
    location_path.write_text(json.dumps(locations, ensure_ascii=False, indent=2), encoding="utf-8")

    mainline_path = data_dir / "剧情" / "主线.json"
    user = f"mainline-cap-{adapter}"

    async def run() -> None:
        now = datetime(2026, 9, 22, tzinfo=timezone.utc)
        runtime = create_runtime(data_dir=data_dir, clock=lambda: now)

        async def send(runtime_instance, operation_id: str, command: str):
            return await runtime_instance.adapters.dispatch(
                adapter, _context(adapter, user, operation_id), command
            )

        assert (await send(runtime, "create", "开始修仙")).ok
        assert (await send(runtime, "seek", "寻仙问道")).ok
        with runtime.repository._connect() as connection:
            player_id = connection.execute(
                "SELECT id FROM players WHERE platform=? AND platform_user_id=?",
                (adapter, user),
            ).fetchone()[0]
            connection.execute(
                "INSERT INTO player_reputations(player_id, local_json, updated_at) VALUES (?, ?, ?)",
                (player_id, json.dumps({"local.xuantian.new_town": 3}), now.isoformat()),
            )
        assert (await send(runtime, "start", "开始主线 1")).ok
        await runtime.close()

        story = json.loads(mainline_path.read_text(encoding="utf-8"))
        first = next(row for row in story["records"] if row["key"] == "chapter.1.stage.1")
        first["status"] = "locked"
        first["first_clear_reward"]["local_reputation"] = 99
        mainline_path.write_text(json.dumps(story, ensure_ascii=False, indent=2), encoding="utf-8")
        locations = json.loads(location_path.read_text(encoding="utf-8"))
        town = next(row for row in locations["records"] if row["key"] == "xuantian.new_town")
        town["local_reputation_maximum"] = 1
        location_path.write_text(json.dumps(locations, ensure_ascii=False, indent=2), encoding="utf-8")

        restored = create_runtime(data_dir=data_dir, clock=lambda: now)
        claimed = await send(restored, "claim", "领取主线奖励 1")
        assert claimed.code == "MAINLINE_REWARD_CLAIMED"
        assert claimed.data["reward"]["local_reputation"] == 1
        replay = await send(restored, "claim", "领取主线奖励 1")
        assert replay.data["idempotent_replay"] is True
        with restored.repository._connect() as connection:
            reputation_json = connection.execute(
                "SELECT local_json FROM player_reputations WHERE player_id=?", (player_id,)
            ).fetchone()[0]
            run = connection.execute(
                "SELECT snapshot_json, result_json FROM mainline_runs WHERE player_id=? AND stage_key=?",
                (player_id, "chapter.1.stage.1"),
            ).fetchone()
            operation = connection.execute(
                "SELECT result_json FROM operations WHERE operation_id=?",
                (f"{adapter}:claim",),
            ).fetchone()[0]
        assert json.loads(reputation_json)["local.xuantian.new_town"] == 4
        assert json.loads(run["snapshot_json"])["definition"]["local_reputation_maximum"] == 4
        assert json.loads(run["result_json"])["reward"]["local_reputation"] == 1
        assert json.loads(operation)["reward"]["local_reputation"] == 1
        await restored.close()

    asyncio.run(run())


@pytest.mark.parametrize("adapter", ["qq.official", "onebot.v11"])
def test_mainline_reward_failure_rolls_back_and_same_operation_recovers(
    tmp_path: Path, adapter: str
) -> None:
    async def run() -> None:
        now = datetime(2026, 9, 22, tzinfo=timezone.utc)
        runtime = create_runtime(data_dir=tmp_path / adapter.replace(".", "-"), clock=lambda: now)
        user = f"mainline-recovery-{adapter}"

        async def send(operation_id: str, command: str):
            return await runtime.adapters.dispatch(
                adapter, _context(adapter, user, operation_id), command
            )

        assert (await send("create", "开始修仙")).ok
        assert (await send("seek", "寻仙问道")).ok
        assert (await send("start", "开始主线 1")).ok
        with runtime.repository._connect() as connection:
            player_id = connection.execute(
                "SELECT id FROM players WHERE platform=? AND platform_user_id=?",
                (adapter, user),
            ).fetchone()[0]
            connection.execute(
                """
                CREATE TRIGGER fail_mainline_claim
                BEFORE INSERT ON operations
                WHEN NEW.operation_name = 'mainline.claim_first_clear'
                BEGIN SELECT RAISE(ABORT, 'injected mainline operation failure'); END
                """
            )

        failed = await send("claim", "领取主线奖励 1")
        assert failed.code == "PERSISTENCE_ERROR"
        with runtime.repository._connect() as connection:
            status = connection.execute(
                "SELECT status, first_clear_claimed FROM mainline_runs WHERE player_id=? AND stage_key=?",
                (player_id, "chapter.1.stage.1"),
            ).fetchone()
            reputation = connection.execute(
                "SELECT local_json FROM player_reputations WHERE player_id=?", (player_id,)
            ).fetchone()
            claim_operation_count = connection.execute(
                "SELECT COUNT(*) FROM operations WHERE operation_id=?", (f"{adapter}:claim",)
            ).fetchone()[0]
            connection.execute("DROP TRIGGER fail_mainline_claim")
        assert tuple(status) == ("running", 0)
        assert reputation is None
        assert claim_operation_count == 0

        claimed = await send("claim", "领取主线奖励 1")
        assert claimed.code == "MAINLINE_REWARD_CLAIMED"
        assert claimed.data["reward"]["local_reputation"] == 3
        replay = await send("claim", "领取主线奖励 1")
        assert replay.data["idempotent_replay"] is True
        with runtime.repository._connect() as connection:
            reputation_json = connection.execute(
                "SELECT local_json FROM player_reputations WHERE player_id=?", (player_id,)
            ).fetchone()[0]
            claim_operation_count = connection.execute(
                "SELECT COUNT(*) FROM operations WHERE operation_id=?", (f"{adapter}:claim",)
            ).fetchone()[0]
        assert json.loads(reputation_json)["local.xuantian.new_town"] == 3
        assert claim_operation_count == 1
        await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("broken_json", ["{", "[]", '{"local.xuantian.new_town": true}'])
def test_mainline_invalid_reputation_json_rejects_claim_atomically(
    tmp_path: Path, broken_json: str
) -> None:
    async def run() -> None:
        now = datetime(2026, 9, 22, tzinfo=timezone.utc)
        runtime = create_runtime(data_dir=tmp_path, clock=lambda: now)
        adapter = "onebot.v11"
        user = "mainline-invalid-reputation"

        async def send(operation_id: str, command: str):
            return await runtime.adapters.dispatch(
                adapter, _context(adapter, user, operation_id), command
            )

        assert (await send("create", "开始修仙")).ok
        assert (await send("seek", "寻仙问道")).ok
        assert (await send("start", "开始主线 1")).ok
        with runtime.repository._connect() as connection:
            player_id = connection.execute(
                "SELECT id FROM players WHERE platform=? AND platform_user_id=?",
                (adapter, user),
            ).fetchone()[0]
            connection.execute(
                "INSERT INTO player_reputations(player_id, local_json, updated_at) VALUES (?, ?, ?)",
                (player_id, broken_json, now.isoformat()),
            )

        rejected = await send("claim", "领取主线奖励 1")
        assert rejected.code == "PERSISTENCE_ERROR"
        with runtime.repository._connect() as connection:
            status = connection.execute(
                "SELECT status, first_clear_claimed FROM mainline_runs WHERE player_id=? AND stage_key=?",
                (player_id, "chapter.1.stage.1"),
            ).fetchone()
            stored_json = connection.execute(
                "SELECT local_json FROM player_reputations WHERE player_id=?", (player_id,)
            ).fetchone()[0]
            claim_operation_count = connection.execute(
                "SELECT COUNT(*) FROM operations WHERE operation_id=?", (f"{adapter}:claim",)
            ).fetchone()[0]
        assert tuple(status) == ("running", 0)
        assert stored_json == broken_json
        assert claim_operation_count == 0
        await runtime.close()

    asyncio.run(run())


def test_mainline_invalid_run_snapshot_does_not_fall_back_to_current_content(
    tmp_path: Path,
) -> None:
    async def run() -> None:
        now = datetime(2026, 9, 22, tzinfo=timezone.utc)
        runtime = create_runtime(data_dir=tmp_path, clock=lambda: now)
        adapter = "onebot.v11"
        user = "mainline-invalid-snapshot"

        async def send(operation_id: str, command: str):
            return await runtime.adapters.dispatch(
                adapter, _context(adapter, user, operation_id), command
            )

        assert (await send("create", "开始修仙")).ok
        assert (await send("seek", "寻仙问道")).ok
        assert (await send("start", "开始主线 1")).ok
        with runtime.repository._connect() as connection:
            player_id = connection.execute(
                "SELECT id FROM players WHERE platform=? AND platform_user_id=?",
                (adapter, user),
            ).fetchone()[0]
            connection.execute(
                "UPDATE mainline_runs SET snapshot_json='{' WHERE player_id=? AND stage_key=?",
                (player_id, "chapter.1.stage.1"),
            )

        rejected = await send("claim", "领取主线奖励 1")
        assert rejected.code == "PERSISTENCE_ERROR"
        with runtime.repository._connect() as connection:
            run = connection.execute(
                "SELECT status, first_clear_claimed FROM mainline_runs WHERE player_id=? AND stage_key=?",
                (player_id, "chapter.1.stage.1"),
            ).fetchone()
            reputation = connection.execute(
                "SELECT local_json FROM player_reputations WHERE player_id=?", (player_id,)
            ).fetchone()
            claim_operation_count = connection.execute(
                "SELECT COUNT(*) FROM operations WHERE operation_id=?",
                (f"{adapter}:claim",),
            ).fetchone()[0]
        assert tuple(run) == ("running", 0)
        assert reputation is None
        assert claim_operation_count == 0
        await runtime.close()

    asyncio.run(run())


def test_mainline_operation_input_conflict_does_not_create_second_run() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            user = "mainline-conflict"
            assert (await runtime.dispatch(_context("onebot.v11", user, "create"), "开始修仙")).ok
            assert (await runtime.dispatch(_context("onebot.v11", user, "seek"), "寻仙问道")).ok
            assert (await runtime.dispatch(_context("onebot.v11", user, "same"), "开始主线 1")).ok
            conflict = await runtime.dispatch(_context("onebot.v11", user, "same"), "开始主线 2")
            assert conflict.code == "OPERATION_CONFLICT"
            with runtime.repository._connect() as connection:
                count = connection.execute(
                    "SELECT COUNT(*) FROM mainline_runs WHERE player_id=(SELECT id FROM players WHERE platform=? AND platform_user_id=?)",
                    ("onebot.v11", user),
                ).fetchone()[0]
                assert count == 1
            await runtime.close()

    asyncio.run(run())
