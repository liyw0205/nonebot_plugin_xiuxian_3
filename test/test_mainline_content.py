from __future__ import annotations

import asyncio
import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.adventures.mainline import MAINLINE_STORY_KEY, mainline_definitions
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError
from mainline_fixtures import (
    grant_blood_grass,
    grant_spirit_field_prerequisites,
    mark_mainline_snapshot_legacy,
)


def _context(adapter: str, user: str, operation_id: str) -> CommandContext:
    return CommandContext(adapter=adapter, user_id=user, operation_id=f"{adapter}:{operation_id}")


def test_xuantian_mainline_chapter_two_content_runs_on_both_adapters() -> None:
    async def run() -> None:
        now = [datetime(2026, 9, 22, tzinfo=timezone.utc)]
        with TemporaryDirectory() as tmp_dir:
            # Travel truth must come from the content pack, exactly as production runtime.
            data_dir = Path(tmp_dir) / "content"
            shutil.copytree(
                Path(__file__).parents[1] / "data",
                data_dir,
                ignore=shutil.ignore_patterns("*.sqlite3", "*.sqlite3-*", "*.db", "*.db-*"),
            )
            runtime = create_runtime(data_dir=data_dir, clock=lambda: now[0])
            for adapter, user in (("qq.official", "chapter2-qq"), ("onebot.v11", "chapter2-onebot")):
                async def send(operation_id: str, command: str):
                    return await runtime.adapters.dispatch(adapter, _context(adapter, user, operation_id), command)

                assert (await send("create", "开始修仙")).ok
                assert (await send("seek", "寻仙问道")).ok
                for number in (1,):
                    assert (await send(f"start-{number}", f"开始主线 {number}")).ok
                    mark_mainline_snapshot_legacy(runtime, adapter, user, f"chapter.1.stage.{number}")
                    assert (await send(f"claim-{number}", f"领取主线奖励 {number}")).ok
                grant_spirit_field_prerequisites(runtime, adapter, user, layer=3)
                for number in (2, 3):
                    assert (await send(f"start-{number}", f"开始主线 {number}")).ok
                    mark_mainline_snapshot_legacy(runtime, adapter, user, f"chapter.1.stage.{number}")
                    assert (await send(f"claim-{number}", f"领取主线奖励 {number}")).ok
                assert (await send("commission-list", "城镇委托")).code == "COMMISSION_LIST"
                assert (await send("commission-accept", "接取委托 止血草供应")).code == "COMMISSION_ACCEPTED"
                assert (await send("commission-deliver", "交付委托 止血草供应")).code == "COMMISSION_DELIVERED"
                assert (await send("town-start", "开始主线 城镇委托")).ok
                now[0] += timedelta(days=1)
                grant_blood_grass(runtime, adapter, user)
                assert (await send("commission-list-next", "城镇委托")).code == "COMMISSION_LIST"
                assert (await send("commission-accept-next", "接取委托 止血草供应")).code == "COMMISSION_ACCEPTED"
                assert (await send("commission-deliver-next", "交付委托 止血草供应")).code == "COMMISSION_DELIVERED"
                assert (await send("town-claim", "领取主线奖励 城镇委托")).ok

                with runtime.repository._connect() as connection:
                    connection.execute(
                        "UPDATE players SET realm_key='golden_core', realm_layer=6 WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    )
                assert (await send("start-云城初见", "开始主线 云城初见")).ok
                early = await send("claim-云城初见-early", "领取主线奖励 云城初见")
                assert early.code == "MAINLINE_OBJECTIVES_INCOMPLETE"
                assert (await send("cloud-travel-start", "前往 云城")).code == "TRAVEL_STARTED"
                now[0] += timedelta(minutes=4)
                assert (await send("cloud-travel-settle", "结算移动")).code == "TRAVEL_COMPLETED"
                cloud_claim = await send("claim-云城初见", "领取主线奖励 云城初见")
                assert cloud_claim.code == "MAINLINE_REWARD_CLAIMED"
                assert cloud_claim.data["next_stage_key"] == "chapter.2.stage.3"
                assert (await send("start-商会听潮", "开始主线 商会听潮")).ok
                tide_early = await send("claim-商会听潮-early", "领取主线奖励 商会听潮")
                assert tide_early.code == "MAINLINE_OBJECTIVES_INCOMPLETE"
                with runtime.repository._connect() as connection:
                    connection.execute(
                        "UPDATE players SET spirit_stones = spirit_stones + 600 WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    )
                assert (await send("boat-travel-start", "前往 云舟渡口")).code == "TRAVEL_STARTED"
                now[0] += timedelta(minutes=2)
                assert (await send("boat-travel-settle", "结算移动")).code == "TRAVEL_COMPLETED"
                tide_claim = await send("claim-商会听潮", "领取主线奖励 商会听潮")
                assert tide_claim.code == "MAINLINE_REWARD_CLAIMED"
                assert tide_claim.data["next_stage_key"] == "chapter.3.stage.1"
                with runtime.repository._connect() as connection:
                    connection.execute(
                        "UPDATE players SET location_key='xuantian.cloud_city' WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    )
                assert (await send("start-云铁入山", "开始主线 云铁入山")).ok
                mine_early = await send("claim-云铁入山-early", "领取主线奖励 云铁入山")
                assert mine_early.code == "MAINLINE_OBJECTIVES_INCOMPLETE"
                assert (await send("mine-travel-start", "前往 云铁矿区")).code == "TRAVEL_STARTED"
                now[0] += timedelta(minutes=3)
                assert (await send("mine-travel-settle", "结算移动")).code == "TRAVEL_COMPLETED"
                mine_claim = await send("claim-云铁入山", "领取主线奖励 云铁入山")
                assert mine_claim.code == "MAINLINE_REWARD_CLAIMED"
                assert mine_claim.data["next_stage_key"] == "chapter.3.stage.2"
                assert (await send("start-矿兽试锋", "开始主线 矿兽试锋")).ok
                beast_early = await send("claim-矿兽试锋-early", "领取主线奖励 矿兽试锋")
                assert beast_early.code == "MAINLINE_OBJECTIVES_INCOMPLETE"
                with runtime.repository._connect() as connection:
                    player_row = connection.execute(
                        "SELECT id, inventory_json, stamina FROM players WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    ).fetchone()
                    inventory = json.loads(player_row["inventory_json"] or "{}")
                    inventory["item.permit.cloud_mine"] = max(int(inventory.get("item.permit.cloud_mine", 0)), 1)
                    connection.execute(
                        "UPDATE players SET inventory_json=?, stamina=MAX(stamina, 40) WHERE id=?",
                        (json.dumps(inventory, ensure_ascii=False, sort_keys=True), player_row["id"]),
                    )
                mining = await send("mine-start", "开始探索 云铁矿区采集")
                assert mining.code == "EXPLORATION_STARTED", mining.message
                now[0] += timedelta(minutes=3)
                settled = await send("mine-settle", "结算探索")
                assert settled.code == "EXPLORATION_SETTLED", settled.message
                assert settled.data["result"].get("item.material.cloud_iron", 0) >= 1
                beast_claim = await send("claim-矿兽试锋", "领取主线奖励 矿兽试锋")
                assert beast_claim.code == "MAINLINE_REWARD_CLAIMED"
                assert beast_claim.data["next_stage_key"] == "chapter.3.stage.3"
                assert (await send("start-云舟试航", "开始主线 云舟试航")).ok
                trial_early = await send("claim-云舟试航-early", "领取主线奖励 云舟试航")
                assert trial_early.code == "MAINLINE_OBJECTIVES_INCOMPLETE"
                with runtime.repository._connect() as connection:
                    connection.execute(
                        "UPDATE players SET spirit_stones = spirit_stones + 600 WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    )
                for hop, wait_minutes in (("前往 云城", 3), ("前往 云舟渡口", 1)):
                    assert (await send(f"return-travel-{hop}", hop)).code == "TRAVEL_STARTED"
                    now[0] += timedelta(minutes=wait_minutes)
                    assert (await send(f"return-settle-{hop}", "结算移动")).code == "TRAVEL_COMPLETED"
                assert (await send("trial-start", "开始探索 云舟试炼")).code == "EXPLORATION_STARTED"
                now[0] += timedelta(minutes=5)
                trial_settled = await send("trial-settle", "结算探索")
                assert trial_settled.code == "EXPLORATION_SETTLED"
                assert trial_settled.data["result"].get("item.ticket.cloud_boat_fragment", 0) >= 1
                trial_claim = await send("claim-云舟试航", "领取主线奖励 云舟试航")
                assert trial_claim.code == "MAINLINE_REWARD_CLAIMED"
                assert trial_claim.data["next_stage_key"] == "chapter.4.stage.1"
                assert (await send("start-阵堂初会", "开始主线 阵堂初会")).ok
                hall_early = await send("claim-阵堂初会-early", "领取主线奖励 阵堂初会")
                assert hall_early.code == "MAINLINE_OBJECTIVES_INCOMPLETE"
                # 公开回程航线自深渊门/洞天二层始发：渡口→深渊门→返回云舟，全程公开玩法
                with runtime.repository._connect() as connection:
                    connection.execute(
                        "UPDATE players SET spirit_stones = MAX(spirit_stones, 1200), stamina = MAX(stamina, 40) "
                        "WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    )
                assert (await send("abyss-board", "乘坐云舟 魔界引导")).code == "CLOUD_BOAT_STARTED"
                now[0] += timedelta(minutes=5)
                assert (await send("abyss-settle", "结算云舟")).ok
                assert (await send("return-board", "乘坐云舟 返回云城")).code == "CLOUD_BOAT_STARTED"
                now[0] += timedelta(minutes=3)
                assert (await send("return-settle", "结算云舟")).ok
                for hop, wait_minutes in (("前往 青石镇", 3), ("前往 宗门山门", 1), ("前往 玄天阵堂", 1)):
                    hop_result = await send(f"hall-route-{hop}", hop)
                    assert hop_result.code == "TRAVEL_STARTED", (hop, hop_result.code, hop_result.message)
                    now[0] += timedelta(minutes=wait_minutes)
                    settle_result = await send(f"hall-settle-{hop}", "结算移动")
                    assert settle_result.code == "TRAVEL_COMPLETED", (hop, settle_result.code, settle_result.message)
                hall_claim = await send("claim-阵堂初会", "领取主线奖励 阵堂初会")
                assert hall_claim.code == "MAINLINE_REWARD_CLAIMED"
                assert hall_claim.data["next_stage_key"] == "chapter.4.stage.2"
                assert (await send("start-阵纹试炼", "开始主线 阵纹试炼")).ok
                sand_early = await send("claim-阵纹试炼-early", "领取主线奖励 阵纹试炼")
                assert sand_early.code == "MAINLINE_OBJECTIVES_INCOMPLETE"
                with runtime.repository._connect() as connection:
                    connection.execute(
                        "UPDATE players SET stamina = MAX(stamina, 80) WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    )
                    here = connection.execute(
                        "SELECT location_key FROM players WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    ).fetchone()["location_key"]
                assert here == "xuantian.array_hall", here
                for hop, wait_minutes in (
                    ("前往 宗门山门", 1), ("前往 青石镇", 1), ("前往 近郊", 1), ("前往 玄武岩径", 2),
                ):
                    hop_result = await send(f"sand-travel-{hop}", hop)
                    assert hop_result.code == "TRAVEL_STARTED", (hop, hop_result.code, hop_result.message)
                    now[0] += timedelta(minutes=wait_minutes)
                    settle_result = await send(f"sand-settle-{hop}", "结算移动")
                    assert settle_result.code == "TRAVEL_COMPLETED", (hop, settle_result.code, settle_result.message)
                sand_obtained = 0
                for round_index in range(5):
                    gathered = await send(f"sand-gather-{round_index}", "开始探索 玄武岩径采集")
                    assert gathered.code == "EXPLORATION_STARTED", gathered.message
                    now[0] += timedelta(seconds=151)
                    sand_settled = await send(f"sand-gather-settle-{round_index}", "结算探索")
                    assert sand_settled.code == "EXPLORATION_SETTLED", sand_settled.message
                    sand_obtained += int(sand_settled.data["result"].get("item.mat.array_sand", 0))
                    if sand_obtained >= 1:
                        break
                assert sand_obtained >= 1
                sand_claim = await send("claim-阵纹试炼", "领取主线奖励 阵纹试炼")
                assert sand_claim.code == "MAINLINE_REWARD_CLAIMED"
                assert sand_claim.data["next_stage_key"] == "chapter.4.stage.3"
                assert (await send("start-玄天新章", "开始主线 玄天新章")).ok
                finale_early = await send("claim-玄天新章-early", "领取主线奖励 玄天新章")
                assert finale_early.code == "MAINLINE_OBJECTIVES_INCOMPLETE"
                for hop, wait_minutes in (("前往 近郊", 1), ("前往 青石镇", 1)):
                    hop_result = await send(f"finale-travel-{hop}", hop)
                    assert hop_result.code == "TRAVEL_STARTED", (hop, hop_result.code, hop_result.message)
                    now[0] += timedelta(minutes=wait_minutes)
                    settle_result = await send(f"finale-settle-{hop}", "结算移动")
                    assert settle_result.code == "TRAVEL_COMPLETED", (hop, settle_result.code, settle_result.message)
                finale_claim = await send("claim-玄天新章", "领取主线奖励 玄天新章")
                assert finale_claim.code == "MAINLINE_REWARD_CLAIMED"
                assert finale_claim.data["next_stage_key"] == "chapter.5.stage.1"
                replay = await send("claim-玄天新章", "领取主线奖励 玄天新章")
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


def test_mainline_tail_stage_may_close_without_next_stage_key(tmp_path: Path) -> None:
    source = Path(__file__).parents[1] / "data"
    data_dir = tmp_path / "content"
    shutil.copytree(source, data_dir)
    definitions = mainline_definitions(ContentBundle.load(data_dir), story_key=MAINLINE_STORY_KEY)
    finale = next(item for item in definitions if item.key == "chapter.6.stage.3")
    assert finale.next_stage_key is None
    assert finale.objectives and finale.actions and finale.state_events and finale.retry_message

    story_path = data_dir / "剧情" / "主线.json"
    document = json.loads(story_path.read_text(encoding="utf-8"))
    middle = next(row for row in document["records"] if row["key"] == "chapter.4.stage.2")
    del middle["next_stage_key"]
    story_path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ContentError, match="requires next_stage_key"):
        mainline_definitions(ContentBundle.load(data_dir), story_key=MAINLINE_STORY_KEY)


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
        mark_mainline_snapshot_legacy(runtime, "onebot.v11", "content-mainline", "chapter.1.stage.1")
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
        mark_mainline_snapshot_legacy(runtime, "onebot.v11", "snapshot-mainline", "chapter.1.stage.1")
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
        mark_mainline_snapshot_legacy(runtime, adapter, user, "chapter.1.stage.1")
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
        mark_mainline_snapshot_legacy(runtime, adapter, user, "chapter.1.stage.1")
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
        mark_mainline_snapshot_legacy(runtime, adapter, user, "chapter.1.stage.1")
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
