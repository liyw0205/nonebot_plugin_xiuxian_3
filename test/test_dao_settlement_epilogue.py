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
from nonebot_plugin_xiuxian_3.xiuxian.adventures.mainline import (
    DAO_SETTLEMENT_STORY_KEY,
    mainline_definitions,
)
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError


ROOT = Path(__file__).parents[1]


class Clock:
    def __init__(self) -> None:
        self.value = datetime(2026, 11, 13, 12, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **kwargs: int) -> None:
        self.value += timedelta(**kwargs)


def _copy_content(tmp_path: Path) -> Path:
    content = tmp_path / "content"
    shutil.copytree(ROOT / "data", content)
    return content


def _context(user: str, operation: str) -> CommandContext:
    return CommandContext(
        adapter="onebot.v11",
        user_id=user,
        request_id=operation,
        operation_id=operation,
        can_write_assets=True,
    )


async def _send(runtime, user: str, operation: str, command: str):
    return await runtime.dispatch(_context(user, operation), command)


def _prepare_open_dao_player(runtime, user: str, clock: Clock) -> int:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        row = connection.execute(
            "SELECT id FROM players WHERE platform=? AND platform_user_id=?",
            ("onebot.v11", user),
        ).fetchone()
        assert row is not None
        player_id = int(row[0])
        stamp = clock().isoformat()
        connection.execute(
            """
            UPDATE players SET stage='cultivator', realm_key='dao_union', realm_layer=1,
                location_key='dao.origin_gate', stamina=500, stamina_max=500,
                energy=500, energy_max=500, spirit_stones=5000,
                inventory_json='{"item.dao_fruit_fragment":2}', dao_fruit_progress=470
            WHERE id=?
            """,
            (player_id,),
        )
        connection.execute(
            """
            INSERT INTO player_reputations(player_id, local_json, service_reputation, updated_at)
            VALUES (?, '{}', 100, ?)
            ON CONFLICT(player_id) DO UPDATE SET service_reputation=100, updated_at=excluded.updated_at
            """,
            (player_id, stamp),
        )
        connection.execute(
            """
            INSERT INTO sects(sect_id, name, name_key, leader_id, status, level,
                max_members, warehouse_capacity, construction, spirit_stones, sect_merit,
                warehouse_json, created_at, updated_at)
            VALUES ('dao-settlement-sect', '余响宗', 'dao-settlement-sect:name', ?, 'active',
                6, 80, 100, 0, 0, 1000, '{}', ?, ?)
            """,
            (player_id, stamp, stamp),
        )
        connection.execute(
            """
            INSERT INTO sect_members(sect_id, player_id, role, status, contribution,
                joined_at, last_action_at, created_at, updated_at)
            VALUES ('dao-settlement-sect', ?, 'leader', 'active', 0, ?, ?, ?, ?)
            """,
            (player_id, stamp, stamp, stamp, stamp),
        )
        connection.execute(
            """
            INSERT INTO dao_route_state(sect_id, route_key, cycle_id, locked_until, updated_at)
            VALUES ('dao-settlement-sect', 'route.dao_settlement.remain', 'dao-test', ?, ?)
            """,
            ((clock() + timedelta(days=7)).isoformat(), stamp),
        )
    return player_id


def _force_dispatch_success(content: Path) -> None:
    path = content / "生活" / "生活.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    row = next(item for item in document["records"] if item.get("key") == "dispatch.dao_service")
    row["risk"]["weights"] = {"success": 10000}
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_dao_settlement_contract_rejects_unknown_dispatch_and_exposes_open_chain(tmp_path: Path) -> None:
    content = _copy_content(tmp_path)
    bundle = ContentBundle.load(content)
    definitions = mainline_definitions(bundle, story_key=DAO_SETTLEMENT_STORY_KEY)
    assert [item.key for item in definitions] == [
        "dao_settlement.1",
        "dao_settlement.2",
        "dao_settlement.3",
    ]
    assert definitions[0].objectives[0]["destination_key"] == "dao_service"
    assert definitions[1].objectives[0]["route_key"] == "idle.dao_settlement_watch"
    assert definitions[2].objectives[0]["dispatch_key"] == "dispatch.dao_service"
    assert definitions[2].objectives[0]["type"] == "dispatch_success"

    story_path = content / "剧情" / "主线.json"
    document = json.loads(story_path.read_text(encoding="utf-8"))
    row = next(item for item in document["records"] if item.get("key") == "dao_settlement.3")
    row["objectives"][0]["dispatch_key"] = "dispatch.locked_missing"
    story_path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(ContentError):
        mainline_definitions(ContentBundle.load(content), story_key=DAO_SETTLEMENT_STORY_KEY)


def test_dao_settlement_public_path_freezes_objectives_and_replays(tmp_path: Path) -> None:
    async def run() -> None:
        content = _copy_content(tmp_path)
        _force_dispatch_success(content)
        clock = Clock()
        runtime = create_runtime(data_dir=content, clock=clock)
        user = "dao-settlement-public"
        try:
            assert (await _send(runtime, user, "create", "开始修仙")).ok
            assert (await _send(runtime, user, "seek", "寻仙问道")).ok
            player_id = _prepare_open_dao_player(runtime, user, clock)

            help_life = await _send(runtime, user, "help-life", "修仙帮助 生活")
            assert "道统余响主线" in help_life.message
            assert "道统据点看守" in help_life.message

            started_one = await _send(runtime, user, "stage-1-start", "开始道统余响主线 抵达服务处")
            assert started_one.code == "MAINLINE_STARTED", started_one.message
            early = await _send(runtime, user, "stage-1-early", "领取道统余响主线奖励 抵达服务处")
            assert early.code == "MAINLINE_OBJECTIVES_INCOMPLETE"

            travel = await _send(runtime, user, "travel", "前往 道统服务处")
            assert travel.code == "TRAVEL_STARTED", travel.message
            settled_travel = await _send(runtime, user, "travel-settle", "结算移动")
            assert settled_travel.code == "TRAVEL_COMPLETED", settled_travel.message
            claimed_one = await _send(runtime, user, "stage-1-claim", "领取道统余响主线奖励 抵达服务处")
            assert claimed_one.code == "MAINLINE_REWARD_CLAIMED", claimed_one.message

            started_two = await _send(runtime, user, "stage-2-start", "开始道统余响主线 据点值守")
            assert started_two.code == "MAINLINE_STARTED", started_two.message
            idle = await _send(runtime, user, "idle-start", "开始挂机 道统据点看守")
            assert idle.code == "IDLE_STARTED", idle.message
            clock.advance(hours=12)
            idle_claim = await _send(runtime, user, "idle-claim", "领取挂机")
            assert idle_claim.code == "IDLE_CLAIMED", idle_claim.message
            assert idle_claim.data["fallback"] is False
            claimed_two = await _send(runtime, user, "stage-2-claim", "领取道统余响主线奖励 据点值守")
            assert claimed_two.code == "MAINLINE_REWARD_CLAIMED", claimed_two.message

            started_three = await _send(runtime, user, "stage-3-start", "开始道统余响主线 公开轮值")
            assert started_three.code == "MAINLINE_STARTED", started_three.message
            pending = await _send(runtime, user, "stage-3-pending", "领取道统余响主线奖励 公开轮值")
            assert pending.code == "MAINLINE_OBJECTIVES_INCOMPLETE"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                row = connection.execute(
                    "SELECT status FROM mainline_runs WHERE player_id=? AND stage_key=?",
                    (player_id, "dao_settlement.3"),
                ).fetchone()
                assert row[0] == "running"

            accepted = await _send(runtime, user, "dispatch-accept", "接受派遣 道统服务")
            assert accepted.code == "DISPATCH_ACCEPTED", accepted.message
            clock.advance(hours=8)
            settled = await _send(runtime, user, "dispatch-settle", "结算派遣")
            assert settled.code == "DISPATCH_SETTLED", settled.message
            assert settled.data["outcome"] == "success"
            claimed_three = await _send(runtime, user, "stage-3-claim", "领取道统余响主线奖励 公开轮值")
            assert claimed_three.code == "MAINLINE_REWARD_CLAIMED", claimed_three.message
            replay = await _send(runtime, user, "stage-3-claim", "领取道统余响主线奖励 公开轮值")
            assert replay.code == "MAINLINE_REWARD_CLAIMED"
            assert replay.data["idempotent_replay"] is True
        finally:
            await runtime.close()

    asyncio.run(run())


def test_dao_settlement_dispatch_objective_ignores_partial_and_old_events(tmp_path: Path) -> None:
    async def run() -> None:
        content = _copy_content(tmp_path)
        _force_dispatch_success(content)
        clock = Clock()
        runtime = create_runtime(data_dir=content, clock=clock)
        user = "dao-settlement-boundary"
        try:
            assert (await _send(runtime, user, "create", "开始修仙")).ok
            assert (await _send(runtime, user, "seek", "寻仙问道")).ok
            player_id = _prepare_open_dao_player(runtime, user, clock)
            stamp = (clock() - timedelta(minutes=1)).isoformat()
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "INSERT INTO activity_events(player_id,event_key,source_operation_id,occurred_at,payload_json) VALUES(?,?,?,?,?)",
                    (player_id, "specials.dispatch.settled", "old-op", stamp, json.dumps({"dispatch_key": "dispatch.dao_service", "outcome": "success"})),
                )
            assert (await _send(runtime, user, "one-start", "开始道统余响主线 抵达服务处")).code == "MAINLINE_STARTED"
            travel = await _send(runtime, user, "travel", "前往 道统服务处")
            assert travel.code == "TRAVEL_STARTED"
            assert (await _send(runtime, user, "travel-settle", "结算移动")).code == "TRAVEL_COMPLETED"
            assert (await _send(runtime, user, "one-claim", "领取道统余响主线奖励 抵达服务处")).code == "MAINLINE_REWARD_CLAIMED"
            assert (await _send(runtime, user, "two-start", "开始道统余响主线 据点值守")).code == "MAINLINE_STARTED"
            assert (await _send(runtime, user, "idle-start", "开始挂机 道统据点看守")).code == "IDLE_STARTED"
            clock.advance(hours=12)
            assert (await _send(runtime, user, "idle-claim", "领取挂机")).code == "IDLE_CLAIMED"
            assert (await _send(runtime, user, "two-claim", "领取道统余响主线奖励 据点值守")).code == "MAINLINE_REWARD_CLAIMED"
            assert (await _send(runtime, user, "three-start", "开始道统余响主线 公开轮值")).code == "MAINLINE_STARTED"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "INSERT INTO activity_events(player_id,event_key,source_operation_id,occurred_at,payload_json) VALUES(?,?,?,?,?)",
                    (player_id, "specials.dispatch.settled", "partial-op", clock().isoformat(), json.dumps({"dispatch_key": "dispatch.dao_service", "outcome": "partial"})),
                )
            rejected = await _send(runtime, user, "three-reject", "领取道统余响主线奖励 公开轮值")
            assert rejected.code == "MAINLINE_OBJECTIVES_INCOMPLETE"
        finally:
            await runtime.close()

    asyncio.run(run())
