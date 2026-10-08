from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory

import pytest

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime


class MutableClock:
    def __init__(self, value: datetime):
        self.value = value

    def __call__(self) -> datetime:
        return self.value


def _context(adapter: str, user_id: str, request_id: str, operation_id: str = "") -> CommandContext:
    return CommandContext(
        adapter=adapter,
        user_id=user_id,
        request_id=request_id,
        operation_id=operation_id,
        can_write_assets=True,
    )


async def _seed_weekly_box(runtime, clock: MutableClock, adapter: str, user_id: str) -> tuple[int, str]:
    created = await runtime.adapters.dispatch(
        adapter,
        _context(adapter, user_id, f"create-{adapter}-{user_id}"),
        "开始修仙",
    )
    assert created.code == "PLAYER_CREATED"
    now_text = clock.value.isoformat()
    with sqlite3.connect(runtime.settings.database_path) as connection:
        player_id = int(
            connection.execute(
                "SELECT id FROM players WHERE platform=? AND platform_user_id=?",
                (adapter, user_id),
            ).fetchone()[0]
        )
        connection.execute(
            "INSERT INTO void_route_sessions(session_id,player_id,operation_id,route_key,status,starts_at,ends_at,anchor_cost,stamina_cost,snapshot_json,result_json,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                f"weekly-route-{adapter}-{user_id}",
                player_id,
                f"weekly-route-op-{adapter}-{user_id}",
                "void.first_route",
                "settled",
                now_text,
                now_text,
                1,
                1,
                "{}",
                "{}",
                now_text,
                now_text,
            ),
        )
    season = await runtime.adapters.dispatch(
        adapter,
        _context(adapter, user_id, f"season-{adapter}-{user_id}"),
        "虚空前线",
    )
    assert season.code == "VOID_FRONTIER_SEASON_RANKING"
    return player_id, str(season.data["season_id"])


def _weekly_row(runtime, player_id: int) -> tuple[object, ...]:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        row = connection.execute(
            "SELECT status,claim_operation_id,reward_json FROM void_frontier_weekly_rewards WHERE player_id=?",
            (player_id,),
        ).fetchone()
    assert row is not None
    return tuple(row)


def _player_rewards(runtime, player_id: int) -> tuple[int, int]:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        row = connection.execute(
            "SELECT void_merit,alliance_points FROM players WHERE id=?",
            (player_id,),
        ).fetchone()
    assert row is not None
    return int(row[0]), int(row[1])


@pytest.mark.parametrize(
    "corrupt_reward",
    (
        '{"void_merit":20,"void_merit":999,"alliance_points":10}',
        '{"void_merit":"20","alliance_points":10}',
        '{"void_merit":20}',
    ),
)
def test_void_frontier_weekly_corrupt_snapshot_is_read_only_and_retryable(
    corrupt_reward: str,
) -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 25, 12, tzinfo=timezone.utc))
        for adapter in ("qq.official", "onebot.v11"):
            with TemporaryDirectory() as data_dir:
                runtime = create_runtime(data_dir=data_dir, clock=clock)
                try:
                    player_id, _ = await _seed_weekly_box(runtime, clock, adapter, f"corrupt-{adapter}")
                    with sqlite3.connect(runtime.settings.database_path) as connection:
                        connection.execute(
                            "UPDATE void_frontier_weekly_rewards SET reward_json=? WHERE player_id=?",
                            (corrupt_reward, player_id),
                        )
                    before_rewards = _player_rewards(runtime, player_id)
                    before_row = _weekly_row(runtime, player_id)
                    operation_id = f"void-frontier-corrupt-{adapter}"
                    rejected = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, f"corrupt-{adapter}", "corrupt", operation_id),
                        "领取虚空前线周任务",
                    )
                    assert rejected.code == "PERSISTENCE_ERROR"
                    assert _player_rewards(runtime, player_id) == before_rewards
                    assert _weekly_row(runtime, player_id) == before_row[:1] + (None, corrupt_reward)
                    with sqlite3.connect(runtime.settings.database_path) as connection:
                        assert connection.execute(
                            "SELECT COUNT(*) FROM operations WHERE operation_id=?",
                            (operation_id,),
                        ).fetchone()[0] == 0

                    with sqlite3.connect(runtime.settings.database_path) as connection:
                        connection.execute(
                            "UPDATE void_frontier_weekly_rewards SET reward_json=? WHERE player_id=?",
                            ('{"alliance_points":10,"void_merit":20}', player_id),
                        )
                    retried = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, f"corrupt-{adapter}", "retry", operation_id),
                        "领取虚空前线周任务",
                    )
                    assert retried.code == "VOID_FRONTIER_WEEKLY_CLAIMED"
                    assert retried.data["reward"] == {"void_merit": 20, "alliance_points": 10}
                    assert _player_rewards(runtime, player_id) == (20, 10)
                finally:
                    await runtime.close()

    asyncio.run(run())


def test_void_frontier_weekly_operation_failure_rolls_back_and_retries_on_both_adapters() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 25, 12, tzinfo=timezone.utc))
        for adapter in ("qq.official", "onebot.v11"):
            with TemporaryDirectory() as data_dir:
                runtime = create_runtime(data_dir=data_dir, clock=clock)
                try:
                    player_id, _ = await _seed_weekly_box(runtime, clock, adapter, f"ledger-{adapter}")
                    operation_id = f"void-frontier-ledger-{adapter}"
                    with sqlite3.connect(runtime.settings.database_path) as connection:
                        connection.execute(
                            "CREATE TRIGGER reject_void_frontier_operation BEFORE INSERT ON operations "
                            "BEGIN SELECT RAISE(ABORT, 'injected operation failure'); END",
                        )
                    failed = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, f"ledger-{adapter}", "failed", operation_id),
                        "领取虚空前线周任务",
                    )
                    assert failed.code == "PERSISTENCE_ERROR"
                    assert _player_rewards(runtime, player_id) == (0, 0)
                    assert _weekly_row(runtime, player_id)[0:2] == ("pending", None)
                    with sqlite3.connect(runtime.settings.database_path) as connection:
                        assert connection.execute(
                            "SELECT COUNT(*) FROM operations WHERE operation_id=?",
                            (operation_id,),
                        ).fetchone()[0] == 0
                        connection.execute("DROP TRIGGER reject_void_frontier_operation")

                    retried = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, f"ledger-{adapter}", "retry", operation_id),
                        "领取虚空前线周任务",
                    )
                    assert retried.code == "VOID_FRONTIER_WEEKLY_CLAIMED"
                    assert _player_rewards(runtime, player_id) == (20, 10)
                finally:
                    await runtime.close()

    asyncio.run(run())


def test_void_frontier_weekly_operation_replay_rejects_corruption_then_recovers_after_restart() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 25, 12, tzinfo=timezone.utc))
        for adapter in ("qq.official", "onebot.v11"):
            with TemporaryDirectory() as data_dir:
                runtime = create_runtime(data_dir=data_dir, clock=clock)
                player_id, _ = await _seed_weekly_box(runtime, clock, adapter, f"replay-{adapter}")
                operation_id = f"void-frontier-replay-{adapter}"
                first = await runtime.adapters.dispatch(
                    adapter,
                    _context(adapter, f"replay-{adapter}", "claim", operation_id),
                    "领取虚空前线周任务",
                )
                assert first.code == "VOID_FRONTIER_WEEKLY_CLAIMED"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    original_result = connection.execute(
                        "SELECT result_json FROM operations WHERE operation_id=?",
                        (operation_id,),
                    ).fetchone()
                    assert original_result is not None
                    original_result_json = str(original_result[0])
                    connection.execute(
                        "UPDATE operations SET result_json=? WHERE operation_id=?",
                        ('{"week_id":"2026-09-21"}', operation_id),
                    )
                await runtime.close()

                runtime = create_runtime(data_dir=data_dir, clock=clock)
                try:
                    rejected = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, f"replay-{adapter}", "corrupt-replay", operation_id),
                        "领取虚空前线周任务",
                    )
                    assert rejected.code == "PERSISTENCE_ERROR"
                    assert _player_rewards(runtime, player_id) == (20, 10)
                    with sqlite3.connect(runtime.settings.database_path) as connection:
                        connection.execute(
                            "UPDATE operations SET result_json=? WHERE operation_id=?",
                            (original_result_json, operation_id),
                        )
                finally:
                    await runtime.close()

                runtime = create_runtime(data_dir=data_dir, clock=clock)
                try:
                    replay = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, f"replay-{adapter}", "replay", operation_id),
                        "领取虚空前线周任务",
                    )
                    assert replay.code == "VOID_FRONTIER_WEEKLY_CLAIMED"
                    assert replay.data["idempotent_replay"] is True
                    assert _player_rewards(runtime, player_id) == (20, 10)
                finally:
                    await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize(
    "corrupt_reward",
    (
        '{"void_merit":20,"void_merit":999,"alliance_points":10}',
        '{"void_merit":"20","alliance_points":10}',
    ),
)
def test_void_frontier_expired_weekly_snapshot_recovery_is_atomic(corrupt_reward: str) -> None:
    async def run() -> None:
        for adapter in ("qq.official", "onebot.v11"):
            clock = MutableClock(datetime(2026, 9, 25, 12, tzinfo=timezone.utc))
            with TemporaryDirectory() as data_dir:
                runtime = create_runtime(data_dir=data_dir, clock=clock)
                try:
                    player_id, season_id = await _seed_weekly_box(runtime, clock, adapter, f"expired-{adapter}")
                    with sqlite3.connect(runtime.settings.database_path) as connection:
                        connection.execute(
                            "UPDATE void_frontier_weekly_rewards SET reward_json=? WHERE player_id=?",
                            (corrupt_reward, player_id),
                        )
                        operation_count = int(connection.execute("SELECT COUNT(*) FROM operations").fetchone()[0])

                    clock.value += timedelta(days=36)
                    rejected = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, f"expired-{adapter}", "expired-corrupt"),
                        f"虚空前线 {season_id}",
                    )
                    assert rejected.code == "PERSISTENCE_ERROR"
                    with sqlite3.connect(runtime.settings.database_path) as connection:
                        season_status, box_status, claim_operation_id, claimed_at, reward_json = connection.execute(
                            "SELECT s.status,w.status,w.claim_operation_id,w.claimed_at,w.reward_json "
                            "FROM void_frontier_seasons s JOIN void_frontier_weekly_rewards w ON w.season_id=s.season_id "
                            "WHERE s.season_id=? AND w.player_id=?",
                            (season_id, player_id),
                        ).fetchone()
                        assert season_status == "collecting"
                        assert box_status == "pending"
                        assert claim_operation_id is None
                        assert claimed_at is None
                        assert reward_json == corrupt_reward
                        assert int(connection.execute("SELECT COUNT(*) FROM operations").fetchone()[0]) == operation_count
                    assert _player_rewards(runtime, player_id) == (0, 0)

                    with sqlite3.connect(runtime.settings.database_path) as connection:
                        connection.execute(
                            "UPDATE void_frontier_weekly_rewards SET reward_json=? WHERE player_id=?",
                            ('{"alliance_points":10,"void_merit":20}', player_id),
                        )
                    recovered = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, f"expired-{adapter}", "expired-retry"),
                        f"虚空前线 {season_id}",
                    )
                    assert recovered.code == "VOID_FRONTIER_SEASON_RANKING"
                    assert _player_rewards(runtime, player_id) == (20, 0)
                    with sqlite3.connect(runtime.settings.database_path) as connection:
                        box_status, reward_json = connection.execute(
                            "SELECT status,reward_json FROM void_frontier_weekly_rewards WHERE season_id=? AND player_id=?",
                            (season_id, player_id),
                        ).fetchone()
                        converted_reward = json.loads(reward_json)
                        assert box_status == "converted"
                        assert converted_reward == {"bound": True, "void_merit": 20}
                        assert int(connection.execute("SELECT COUNT(*) FROM operations").fetchone()[0]) == operation_count

                    replay = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, f"expired-{adapter}", "expired-replay"),
                        f"虚空前线 {season_id}",
                    )
                    assert replay.code == "VOID_FRONTIER_SEASON_RANKING"
                    assert _player_rewards(runtime, player_id) == (20, 0)
                finally:
                    await runtime.close()

    asyncio.run(run())


def test_void_frontier_freeze_weekly_box_and_claim_across_adapters() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 25, 12, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            for adapter, user_id in (("qq.official", "frontier-qq"), ("onebot.v11", "frontier-ob")):
                assert (await runtime.adapters.dispatch(adapter, _context(adapter, user_id, f"create-{user_id}"), "开始修仙")).code == "PLAYER_CREATED"

            now = clock.value.isoformat()
            with sqlite3.connect(runtime.settings.database_path) as connection:
                players = dict(connection.execute("SELECT platform_user_id,id FROM players").fetchall())
                for index, user_id in enumerate(("frontier-qq", "frontier-ob"), start=1):
                    player_id = players[user_id]
                    connection.execute(
                        "INSERT INTO void_route_sessions(session_id,player_id,operation_id,route_key,status,starts_at,ends_at,anchor_cost,stamina_cost,snapshot_json,result_json,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (f"frontier-route-{index}", player_id, f"frontier-route-op-{index}", "void.first_route", "settled", now, now, 1, 1, "{}", "{}", now, now),
                    )

            season = await runtime.adapters.dispatch("qq.official", _context("qq.official", "frontier-qq", "status"), "虚空前线")
            assert season.code == "VOID_FRONTIER_SEASON_RANKING"
            assert season.data["status"] == "collecting"
            assert season.data["standings"][0]["score"] == 30
            assert "frontier-qq" not in json.dumps(season.data, ensure_ascii=False)

            weekly = await runtime.adapters.dispatch("onebot.v11", _context("onebot.v11", "frontier-ob", "weekly", "weekly"), "领取虚空前线周任务")
            assert weekly.code == "VOID_FRONTIER_WEEKLY_CLAIMED"
            replay = await runtime.adapters.dispatch("onebot.v11", _context("onebot.v11", "frontier-ob", "weekly", "weekly"), "领取虚空前线周任务")
            assert replay.data["idempotent_replay"] is True

            clock.value = datetime(2026, 10, 7, tzinfo=timezone.utc)
            season_id = season.data["season_id"]
            frozen = await runtime.adapters.dispatch("onebot.v11", _context("onebot.v11", "frontier-ob", "freeze"), f"虚空前线 {season_id}")
            assert frozen.data["status"] == "frozen"
            assert {item["score"] for item in frozen.data["standings"] if item["board_key"] == "player_score"} == {30}

            claim = await runtime.adapters.dispatch("qq.official", _context("qq.official", "frontier-qq", "claim", "claim"), f"领取虚空前线奖励 {season_id}")
            assert claim.code == "VOID_FRONTIER_REWARD_CLAIMED"
            duplicate = await runtime.adapters.dispatch("qq.official", _context("qq.official", "frontier-qq", "claim-again"), f"领取虚空前线奖励 {season_id}")
            assert duplicate.code == "VOID_FRONTIER_REWARD_ALREADY_CLAIMED"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                inventory, void_merit, alliance_points = connection.execute(
                    "SELECT inventory_json,void_merit,alliance_points FROM players WHERE platform_user_id='frontier-ob'"
                ).fetchone()
                assert json.loads(inventory).get("item.void_crystal", 0) == 0
                assert void_merit == 20
                assert alliance_points == 10
            await runtime.close()

    asyncio.run(run())


def test_void_frontier_projects_unobserved_alliance_expiry() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 25, 12, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            for adapter, user_id in (("qq.official", "expiry-qq"), ("onebot.v11", "expiry-ob")):
                assert (await runtime.adapters.dispatch(adapter, _context(adapter, user_id, f"create-{user_id}"), "开始修仙")).code == "PLAYER_CREATED"
            now_text = clock.value.isoformat()
            with sqlite3.connect(runtime.settings.database_path) as connection:
                players = dict(connection.execute("SELECT platform_user_id,id FROM players").fetchall())
                for sect_id, name, user_id in (("expiry-sect-a", "到期甲宗", "expiry-qq"), ("expiry-sect-b", "到期乙宗", "expiry-ob")):
                    connection.execute(
                        "INSERT INTO sects(sect_id,name,name_key,leader_id,status,level,max_members,warehouse_capacity,construction,spirit_stones,sect_merit,warehouse_json,created_at,updated_at) VALUES (?,?,?,?, 'active',5,120,100,0,20000,0,'{}',?,?)",
                        (sect_id, name, name.casefold(), players[user_id], now_text, now_text),
                    )
                    connection.execute(
                        "INSERT INTO sect_members(sect_id,player_id,role,status,contribution,joined_at,last_action_at,created_at,updated_at) VALUES (?,?, 'leader','active',0,?,?,?,?)",
                        (sect_id, players[user_id], now_text, now_text, now_text, now_text),
                    )

            proposal = await runtime.adapters.dispatch(
                "qq.official", _context("qq.official", "expiry-qq", "alliance-propose"), "发起生产联盟 expiry-sect-b"
            )
            assert proposal.code == "ALLIANCE_PROPOSED"
            confirmed = await runtime.adapters.dispatch(
                "onebot.v11",
                _context("onebot.v11", "expiry-ob", "alliance-confirm"),
                f"确认生产联盟 {proposal.data['alliance_id']}",
            )
            assert confirmed.code == "ALLIANCE_CONFIRMED"

            # No read touches the alliance after its end time. The season
            # projection must still recognize a natural contract expiry.
            clock.value += timedelta(days=8)
            season = await runtime.adapters.dispatch(
                "qq.official", _context("qq.official", "expiry-qq", "season-status"), "虚空前线"
            )
            assert season.code == "VOID_FRONTIER_SEASON_RANKING"
            assert {item["score"] for item in season.data["standings"] if item["board_key"] == "player_score"} == {20}
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute("SELECT COUNT(*) FROM void_frontier_score_events WHERE score_key='alliance_contract'").fetchone()[0] == 2
            await runtime.close()

    asyncio.run(run())


def test_void_frontier_converts_pending_boxes_when_first_read_is_late() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 25, 12, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            assert (await runtime.adapters.dispatch("qq.official", _context("qq.official", "late-box", "create"), "开始修仙")).code == "PLAYER_CREATED"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                player_id = connection.execute("SELECT id FROM players WHERE platform_user_id='late-box'").fetchone()[0]
                now_text = clock.value.isoformat()
                connection.execute(
                    "INSERT INTO void_route_sessions(session_id,player_id,operation_id,route_key,status,starts_at,ends_at,anchor_cost,stamina_cost,snapshot_json,result_json,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    ("late-route", player_id, "late-route-op", "void.archive_ruins", "settled", now_text, now_text, 1, 1, "{}", "{}", now_text, now_text),
                )
            season = await runtime.adapters.dispatch("qq.official", _context("qq.official", "late-box", "status"), "虚空前线")
            season_id = season.data["season_id"]
            clock.value += timedelta(days=36)
            late = await runtime.adapters.dispatch(
                "qq.official", _context("qq.official", "late-box", "late-status"), f"虚空前线 {season_id}"
            )
            assert late.data["status"] == "frozen"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                status, merit, alliance_points = connection.execute(
                    "SELECT w.status,p.void_merit,p.alliance_points FROM void_frontier_weekly_rewards w JOIN players p ON p.id=w.player_id WHERE w.source_key='route:late-route-op'"
                ).fetchone()
                assert status == "converted"
                assert merit == 20
                assert alliance_points == 0
            await runtime.close()

    asyncio.run(run())
