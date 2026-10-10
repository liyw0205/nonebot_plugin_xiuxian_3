from __future__ import annotations

import asyncio
import json
import shutil
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pytest

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.exploration.rules import battle_roll_bp
from nonebot_plugin_xiuxian_3.xiuxian.production.rules import random_quality_bp
from nonebot_plugin_xiuxian_3.xiuxian.quests.repository import QuestRepositoryMixin
from nonebot_plugin_xiuxian_3.xiuxian.quests.rules import GUIDANCE_CLAIM_OPERATION


ROOT = Path(__file__).parents[1]
ADAPTERS = ("qq.official", "onebot.v11")


def _context(adapter: str, user: str, request: str, operation_id: str = "") -> CommandContext:
    return CommandContext(
        adapter=adapter,
        user_id=user,
        request_id=request,
        operation_id=operation_id,
        can_write_assets=True,
    )


def _table_state(runtime, adapter: str, user: str) -> tuple[object, ...]:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        player = connection.execute(
            "SELECT spirit_stones, inventory_json, cultivation, total_cultivation, "
            "faction_reputation_json FROM players WHERE platform=? AND platform_user_id=?",
            (adapter, user),
        ).fetchone()
        events = connection.execute(
            "SELECT quest_key, component_key, source_operation_id, outcome, payload_json "
            "FROM quest_events WHERE player_id=(SELECT id FROM players WHERE platform=? AND platform_user_id=?) "
            "ORDER BY quest_key, component_key, source_operation_id",
            (adapter, user),
        ).fetchall()
        progress = connection.execute(
            "SELECT quest_key, status, progress_json, snapshot_json, source_operation_id "
            "FROM quest_progress WHERE player_id=(SELECT id FROM players WHERE platform=? AND platform_user_id=?) "
            "ORDER BY quest_key",
            (adapter, user),
        ).fetchall()
        claims = connection.execute(
            "SELECT operation_id, request_hash, result_json FROM operations "
            "WHERE player_id=(SELECT id FROM players WHERE platform=? AND platform_user_id=?) "
            "AND operation_name=? ORDER BY operation_id",
            (adapter, user, GUIDANCE_CLAIM_OPERATION),
        ).fetchall()
    return player, events, progress, claims


def _finish_exploration(runtime, exploration_id: str) -> None:
    end = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE exploration_sessions SET ends_at=? WHERE exploration_id=?",
            (end, exploration_id),
        )


def _finish_production(runtime, order_id: str) -> None:
    end = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    start = (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat()
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE production_orders SET starts_at=?, ends_at=? WHERE order_id=?",
            (start, end, order_id),
        )


def _replace_first_guidance_reward(path: Path, *, currency: int | None = None, invalid_item: bool = False) -> None:
    document = json.loads(path.read_text(encoding="utf-8"))
    record = next(
        row for row in document["records"] if row["key"] == "reward.quest.first_seeking"
    )
    if currency is not None:
        next(entry for entry in record["entries"] if entry["kind"] == "currency")["quantity"] = currency
    if invalid_item:
        next(entry for entry in record["entries"] if entry["kind"] == "item")["item_key"] = "item.missing"
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_guidance_quests_use_settled_sources_and_shared_claim_transaction(adapter: str) -> None:
    async def run() -> None:
        with TemporaryDirectory() as temp:
            data_dir = Path(temp) / "data"
            shutil.copytree(ROOT / "data", data_dir)
            _replace_first_guidance_reward(data_dir / "奖励" / "奖励.json", currency=777)
            runtime = create_runtime(data_dir=data_dir, adapters=(adapter,))
            user = f"guidance-{adapter}"
            first_claim_operation = f"guidance-seeking-claim-{adapter}"
            try:
                created = await runtime.adapters.dispatch(
                    adapter, _context(adapter, user, "create"), "开始修仙"
                )
                assert created.code == "PLAYER_CREATED"
                initial = await runtime.adapters.dispatch(
                    adapter, _context(adapter, user, "status-before"), "引路簿"
                )
                assert initial.code == "GUIDANCE_QUEST_STATUS"
                assert all(item["status"] == "active" for item in initial.data["quests"])

                gather_claim_blocked = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "claim-gather-before", "guidance-early-gather-claim"),
                    "领取引路嘉奖 第一次采集",
                )
                assert gather_claim_blocked.code == "QUEST_REQUIREMENT_MISSING"

                blocked = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "claim-before", "guidance-early-claim"),
                    "领取引路嘉奖 第一次寻仙",
                )
                assert blocked.code == "QUEST_REQUIREMENT_MISSING"

                seeking = await runtime.adapters.dispatch(
                    adapter, _context(adapter, user, "seeking"), "寻仙问道"
                )
                assert seeking.code == "SEEKING_STARTED"
                before = _table_state(runtime, adapter, user)
                def fail_after_asset_grant(*args, **kwargs):
                    raise RuntimeError("injected claim progress failure")

                with patch.object(
                    QuestRepositoryMixin,
                    "_upsert_progress",
                    staticmethod(fail_after_asset_grant),
                ):
                    failed = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, user, "claim-failed", first_claim_operation),
                        "领取引路嘉奖 第一次寻仙",
                    )
                assert failed.code == "PERSISTENCE_ERROR"
                assert _table_state(runtime, adapter, user) == before

                seeking_claim = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "claim-seeking", first_claim_operation),
                    "领取引路嘉奖 第一次寻仙",
                )
                assert seeking_claim.code == "GUIDANCE_REWARD_CLAIMED"
                assert seeking_claim.data["reward"]["spirit_stones"] == 777
                assert seeking_claim.data["reward"]["item.food.coarse_spirit_rice"] == 3
                assert "item.food" not in seeking_claim.message

                operation_conflict = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "claim-conflict", first_claim_operation),
                    "领取引路嘉奖 第一次入道",
                )
                assert operation_conflict.code == "OPERATION_CONFLICT"
                replay = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "claim-replay", first_claim_operation),
                    "领取引路嘉奖 第一次寻仙",
                )
                assert replay.data["idempotent_replay"] is True
                assert replay.data["reward"] == seeking_claim.data["reward"]

                travel = await runtime.adapters.dispatch(
                    adapter, _context(adapter, user, "travel"), "前往近郊"
                )
                assert travel.code == "TRAVEL_COMPLETED"
                gather_operation = next(
                    f"{adapter}-gather-{index}"
                    for index in range(1000)
                    if battle_roll_bp(f"{adapter}-gather-{index}:battle") >= 1000
                )
                gathering = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "gather-start", gather_operation),
                    "开始探索 近郊采集",
                )
                assert gathering.code == "EXPLORATION_STARTED"
                _finish_exploration(runtime, str(gathering.data["exploration_id"]))
                gathered = await runtime.adapters.dispatch(
                    adapter, _context(adapter, user, "gather-settle"), "结算探索"
                )
                assert gathered.code == "EXPLORATION_SETTLED"
                assert gathered.data["mode_key"] == "explore.gather_outskirts"
                assert gathered.data["status"] == "settled"

                for request, command in (
                    ("read-intro", "完成引导 阅读"),
                    ("gather-intro", "完成引导 采集"),
                    ("service-intro", "完成引导 炼丹"),
                ):
                    result = await runtime.adapters.dispatch(
                        adapter, _context(adapter, user, request), command
                    )
                    assert result.ok, (command, result.code)
                entered = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "enter-cultivation"),
                    "选择道途 辅修 炼丹",
                )
                assert entered.code == "CULTIVATION_ENTERED"

                cultivation_claim = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "claim-cultivation", f"{adapter}-cultivation-claim"),
                    "领取引路嘉奖 第一次入道",
                )
                assert cultivation_claim.code == "GUIDANCE_REWARD_CLAIMED"
                assert cultivation_claim.data["reward"]["spirit_stones"] == 200
                assert cultivation_claim.data["reward"]["item.manual.basic_qi"] == 1

                gathering_claim = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "claim-gather", f"{adapter}-gather-claim"),
                    "领取引路嘉奖 第一次采集",
                )
                assert gathering_claim.code == "GUIDANCE_REWARD_CLAIMED"
                assert gathering_claim.data["reward"]["item.herb.blood_grass"] == 2
                assert gathering_claim.data["reward"]["cultivation"] == 30
                assert gathering_claim.data["reward"]["item.manual.sunrise_breath"] == 1
                gather_claim_state = _table_state(runtime, adapter, user)
                assert json.loads(gather_claim_state[0][1])["item.manual.sunrise_breath"] == 1
                gathering_replay = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "claim-gather-replay", f"{adapter}-gather-claim"),
                    "领取引路嘉奖 第一次采集",
                )
                assert gathering_replay.data["idempotent_replay"] is True
                assert gathering_replay.data["reward"] == gathering_claim.data["reward"]
                assert _table_state(runtime, adapter, user) == gather_claim_state

                start_operation = next(
                    f"{adapter}-production-start-{index}"
                    for index in range(1000)
                    if random_quality_bp(f"{adapter}-production-start-{index}") >= 500
                )
                started = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "production-start", start_operation),
                    "开始生产 疗伤丹",
                )
                assert started.code == "PRODUCTION_STARTED"
                _finish_production(runtime, str(started.data["order_id"]))
                completed = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "production-complete", f"{adapter}-production-complete"),
                    "领取生产",
                )
                assert completed.code == "PRODUCTION_COMPLETED"
                assert completed.data["success"] is True

                craft_claim = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "claim-craft", f"{adapter}-craft-claim"),
                    "领取引路嘉奖 第一次生产",
                )
                assert craft_claim.code == "GUIDANCE_REWARD_CLAIMED"
                assert craft_claim.data["reward"]["spirit_stones"] == 50
                assert craft_claim.data["reward"]["faction_reputation.xuantian"] == 2

                status = await runtime.adapters.dispatch(
                    adapter, _context(adapter, user, "status-after"), "引路簿"
                )
                assert all(item["status"] == "claimed" for item in status.data["quests"])
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    events = connection.execute(
                        "SELECT quest_key, source_operation_id FROM quest_events "
                        "WHERE player_id=(SELECT id FROM players WHERE platform=? AND platform_user_id=?) "
                        "AND component_key='completion' ORDER BY quest_key",
                        (adapter, user),
                    ).fetchall()
                    progress = connection.execute(
                        "SELECT quest_key, status FROM quest_progress "
                        "WHERE player_id=(SELECT id FROM players WHERE platform=? AND platform_user_id=?) "
                        "ORDER BY quest_key",
                        (adapter, user),
                    ).fetchall()
                    source_operations = dict(
                        connection.execute(
                            "SELECT operation_id, operation_name FROM operations WHERE player_id="
                            "(SELECT id FROM players WHERE platform=? AND platform_user_id=?)",
                            (adapter, user),
                        ).fetchall()
                    )
                assert len(events) == 4
                assert {
                    quest_key: source_operations[source_operation_id]
                    for quest_key, source_operation_id in events
                } == {
                    "quest.first_seeking": "player.start_seeking",
                    "quest.first_cultivation": "player.enter_cultivation",
                    "quest.first_gather": "exploration.settle",
                    "quest.first_craft": "production.complete",
                }
                assert all(status == "claimed" for _, status in progress)
                before_recovery = _table_state(runtime, adapter, user)
            finally:
                await runtime.close()

            _replace_first_guidance_reward(
                data_dir / "奖励" / "奖励.json", invalid_item=True
            )
            recovered = create_runtime(data_dir=data_dir, adapters=(adapter,))
            try:
                replay = await recovered.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "claim-after-restart", first_claim_operation),
                    "领取引路嘉奖 第一次寻仙",
                )
                assert replay.code == "GUIDANCE_REWARD_CLAIMED"
                assert replay.data["idempotent_replay"] is True
                assert replay.data["reward"]["spirit_stones"] == 777
                assert _table_state(recovered, adapter, user) == before_recovery
            finally:
                await recovered.close()

    asyncio.run(run())


@pytest.mark.parametrize("adapter", ADAPTERS)
def test_guidance_reward_rejects_bad_content_without_partial_claim(adapter: str) -> None:
    async def run() -> None:
        with TemporaryDirectory() as temp:
            data_dir = Path(temp) / "data"
            shutil.copytree(ROOT / "data", data_dir)
            reward_path = data_dir / "奖励" / "奖励.json"
            original = json.loads(reward_path.read_text(encoding="utf-8"))
            _replace_first_guidance_reward(reward_path, invalid_item=True)
            runtime = create_runtime(data_dir=data_dir, adapters=(adapter,))
            user = f"guidance-invalid-{adapter}"
            operation_id = f"guidance-retry-{adapter}"
            try:
                assert (
                    await runtime.adapters.dispatch(
                        adapter, _context(adapter, user, "create"), "开始修仙"
                    )
                ).ok
                assert (
                    await runtime.adapters.dispatch(
                        adapter, _context(adapter, user, "seek"), "寻仙问道"
                    )
                ).ok
                before = _table_state(runtime, adapter, user)
                rejected = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "bad-reward", operation_id),
                    "领取引路嘉奖 第一次寻仙",
                )
                assert rejected.code == "CONTENT_UNAVAILABLE"
                assert _table_state(runtime, adapter, user) == before
            finally:
                await runtime.close()

            reward_path.write_text(
                json.dumps(original, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            recovered = create_runtime(data_dir=data_dir, adapters=(adapter,))
            try:
                claimed = await recovered.adapters.dispatch(
                    adapter,
                    _context(adapter, user, "good-reward", operation_id),
                    "领取引路嘉奖 第一次寻仙",
                )
                assert claimed.code == "GUIDANCE_REWARD_CLAIMED"
                assert claimed.data["idempotent_replay"] is False
            finally:
                await recovered.close()

    asyncio.run(run())
