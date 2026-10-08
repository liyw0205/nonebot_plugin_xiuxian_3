from __future__ import annotations

import asyncio
import json
import sqlite3
from dataclasses import replace
from datetime import datetime, timezone
from tempfile import TemporaryDirectory

import pytest
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message
from nonebot.adapters.onebot.v11.event import Sender
from nonebot.adapters.qq.event import GroupMessageCreateEvent
from nonebot.adapters.qq.models.qq import GroupMemberAuthor

from nonebot_plugin_xiuxian_3.adapters.onebot import normalize_event as normalize_onebot_event
from nonebot_plugin_xiuxian_3.adapters.qq import normalize_event as normalize_qq_event
from nonebot_plugin_xiuxian_3.runtime import create_runtime


ROUND_ID = "sect_war.cross:2026-W39"


class MutableClock:
    def __init__(self, value: datetime):
        self.value = value

    def __call__(self) -> datetime:
        return self.value


def _contexts():
    qq = normalize_qq_event(
        GroupMessageCreateEvent(
            id="reward-box-qq",
            content="跨服宗门战",
            timestamp="2026-09-28T12:00:00+00:00",
            author=GroupMemberAuthor(
                id="reward-box-qq-raw",
                bot=False,
                member_openid="reward-box-qq",
                member_role="member",
                username="QQ成员",
            ),
            group_id="reward-box-qq-group",
            group_openid="reward-box-qq-group",
        )
    ).context
    onebot = normalize_onebot_event(
        GroupMessageEvent(
            time=1_758_819_600,
            self_id=9001,
            post_type="message",
            sub_type="normal",
            user_id=2002,
            message_type="group",
            message_id=9003,
            message=Message("跨服宗门战"),
            original_message=Message("跨服宗门战"),
            raw_message="跨服宗门战",
            font=0,
            sender=Sender(user_id=2002, nickname="OneBot成员"),
            group_id=3001,
        )
    ).context
    return qq, onebot


async def _seed_runtime(data_dir: str, clock: MutableClock):
    runtime = create_runtime(data_dir=data_dir, clock=clock)
    qq_base, onebot_base = _contexts()
    for user, adapter, base in (
        ("reward-box-qq", "qq.official", qq_base),
        ("reward-box-ob", "onebot.v11", onebot_base),
    ):
        context = replace(
            base,
            user_id=user,
            adapter=adapter,
            operation_id=f"create-{user}",
            request_id=f"create-{user}",
        )
        result = await runtime.adapters.dispatch(adapter, context, "开始修仙")
        assert result.code == "PLAYER_CREATED"

    now_text = clock.value.isoformat()
    with sqlite3.connect(runtime.settings.database_path) as connection:
        players = dict(connection.execute("SELECT platform_user_id,id FROM players").fetchall())
        connection.execute(
            "INSERT INTO sects(sect_id,name,name_key,leader_id,status,level,max_members,warehouse_capacity,construction,spirit_stones,sect_merit,warehouse_json,created_at,updated_at) "
            "VALUES ('reward-box-sect','奖励箱宗门','reward-box-sect',?,'active',5,120,100,0,20000,0,?,?,?)",
            (players["reward-box-qq"], json.dumps({"item.void_anchor": 25}), now_text, now_text),
        )
        for user, role in (("reward-box-qq", "leader"), ("reward-box-ob", "vice_leader")):
            connection.execute(
                "INSERT INTO sect_members(sect_id,player_id,role,status,contribution,joined_at,last_action_at,created_at,updated_at) "
                "VALUES ('reward-box-sect',? ,?,'active',?,?,?,?,?)",
                (players[user], role, 20, now_text, now_text, now_text, now_text),
            )
        connection.execute(
            "INSERT INTO sect_cross_server_war_rounds(round_id,week_id,registration_open_at,starts_at,ends_at,claim_expires_at,status,snapshot_json,created_at,updated_at) "
            "VALUES (?, '2026-W39', '2026-09-21T00:00:00+00:00', '2026-09-27T20:00:00+00:00', '2026-09-27T20:30:00+00:00', '2026-10-04T20:30:00+00:00', 'settled', '{}', ?, ?)",
            (ROUND_ID, now_text, now_text),
        )
        connection.execute(
            "INSERT INTO sect_cross_server_war_registrations(round_id,sect_id,operation_id,entry_fee,status,roster_size,score,rank,winner,snapshot_json,registered_at) "
            "VALUES (?, 'reward-box-sect', 'reward-box-registration', 0, 'registered', 2, 0, 1, 1, '{}', ?)",
            (ROUND_ID, now_text),
        )
        for slot, user in enumerate(("reward-box-qq", "reward-box-ob"), 1):
            connection.execute(
                "INSERT INTO sect_cross_server_war_members(round_id,sect_id,player_id,roster_slot,snapshot_json,created_at,updated_at) "
                "VALUES (?, 'reward-box-sect', ?, ?, '{}', ?, ?)",
                (ROUND_ID, players[user], slot, now_text, now_text),
            )
            connection.execute(
                "INSERT INTO sect_cross_server_weekly_rewards(reward_key,round_id,player_id,operation_id,reward_json,created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    f"season.void_frontier.2026-W39:{players[user]}",
                    ROUND_ID,
                    players[user],
                    f"pending-{user}",
                    '{"void_merit": 20, "status": "pending"}',
                    now_text,
                ),
            )
        connection.execute(
            "INSERT INTO sect_cross_server_reward_boxes(box_id,round_id,sect_id,status,reward_json,distributed_json,created_at,updated_at) "
            "VALUES ('reward-box-id', ?, 'reward-box-sect', 'pending', '{\"item.void_crystal\": 10}', '{}', ?, ?)",
            (ROUND_ID, now_text, now_text),
        )
    return runtime, qq_base, onebot_base, players


def _context(base, *, adapter: str, user: str, operation_id: str):
    return replace(base, adapter=adapter, user_id=user, operation_id=operation_id, request_id=operation_id)


def _player_state(database_path: str, user: str) -> tuple[int, str]:
    with sqlite3.connect(database_path) as connection:
        return connection.execute(
            "SELECT void_merit,inventory_json FROM players WHERE platform_user_id=?", (user,)
        ).fetchone()


@pytest.mark.parametrize(
    ("adapter", "user", "base_name"),
    (("qq.official", "reward-box-qq", "qq"), ("onebot.v11", "reward-box-ob", "onebot")),
)
def test_cross_server_claim_rejects_malformed_weekly_reward_without_writes(
    adapter: str, user: str, base_name: str
) -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 28, 12, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime, qq_base, onebot_base, players = await _seed_runtime(data_dir, clock)
            raw = '{"void_merit": 20, "status": "pending", "status": "pending"}'
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE sect_cross_server_weekly_rewards SET reward_json=? WHERE player_id=?",
                    (raw, players[user]),
                )
                before = _player_state(runtime.settings.database_path, user)
                before_operations = connection.execute("SELECT COUNT(*) FROM operations").fetchone()[0]
            base = qq_base if base_name == "qq" else onebot_base
            result = await runtime.adapters.dispatch(
                adapter,
                _context(base, adapter=adapter, user=user, operation_id=f"malformed-claim-{base_name}"),
                f"领取跨服宗门战奖励 {ROUND_ID}",
            )
            assert result.ok is False
            assert result.code == "PERSISTENCE_ERROR"
            assert _player_state(runtime.settings.database_path, user) == before
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute("SELECT reward_json FROM sect_cross_server_weekly_rewards WHERE player_id=?", (players[user],)).fetchone()[0] == raw
                assert connection.execute("SELECT COUNT(*) FROM operations").fetchone()[0] == before_operations
            await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize(
    ("adapter", "user", "other_user", "base_name"),
    (
        ("qq.official", "reward-box-qq", "reward-box-ob", "qq"),
        ("onebot.v11", "reward-box-ob", "reward-box-qq", "onebot"),
    ),
)
def test_cross_server_claim_rejects_tampered_reward_owner_without_writes(
    adapter: str, user: str, other_user: str, base_name: str
) -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 28, 12, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime, qq_base, onebot_base, players = await _seed_runtime(data_dir, clock)
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE sect_cross_server_weekly_rewards SET player_id=? WHERE reward_key=?",
                    (
                        players[other_user],
                        f"season.void_frontier.2026-W39:{players[user]}",
                    ),
                )
                before_rows = connection.execute(
                    "SELECT reward_key,round_id,player_id,operation_id,reward_json FROM sect_cross_server_weekly_rewards ORDER BY player_id"
                ).fetchall()
            base = qq_base if base_name == "qq" else onebot_base
            result = await runtime.adapters.dispatch(
                adapter,
                _context(base, adapter=adapter, user=user, operation_id=f"tampered-owner-{base_name}"),
                f"领取跨服宗门战奖励 {ROUND_ID}",
            )
            assert result.code == "PERSISTENCE_ERROR"
            assert _player_state(runtime.settings.database_path, user)[0] == 0
            assert _player_state(runtime.settings.database_path, other_user)[0] == 0
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute(
                    "SELECT reward_key,round_id,player_id,operation_id,reward_json FROM sect_cross_server_weekly_rewards ORDER BY player_id"
                ).fetchall() == before_rows
                assert connection.execute(
                    "SELECT 1 FROM operations WHERE operation_id=?", (f"tampered-owner-{base_name}",)
                ).fetchone() is None
            await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize(
    ("adapter", "user", "base_name"),
    (("qq.official", "reward-box-qq", "qq"), ("onebot.v11", "reward-box-ob", "onebot")),
)
def test_cross_server_claim_operation_failure_rolls_back_and_retries(
    adapter: str, user: str, base_name: str
) -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 28, 12, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime, qq_base, onebot_base, players = await _seed_runtime(data_dir, clock)
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "CREATE TRIGGER fail_cross_claim_operation BEFORE INSERT ON operations "
                    "WHEN NEW.operation_id='claim-box-failure' BEGIN SELECT RAISE(ABORT, 'injected claim failure'); END"
                )
            base = qq_base if base_name == "qq" else onebot_base
            context = _context(base, adapter=adapter, user=user, operation_id="claim-box-failure")
            failed = await runtime.adapters.dispatch(
                adapter, context, f"领取跨服宗门战奖励 {ROUND_ID}"
            )
            assert failed.code == "PERSISTENCE_ERROR"
            assert _player_state(runtime.settings.database_path, user)[0] == 0
            with sqlite3.connect(runtime.settings.database_path) as connection:
                reward_json = connection.execute(
                    "SELECT reward_json FROM sect_cross_server_weekly_rewards WHERE player_id=?",
                    (players[user],),
                ).fetchone()[0]
                assert json.loads(reward_json)["status"] == "pending"
                assert connection.execute("SELECT 1 FROM operations WHERE operation_id='claim-box-failure'").fetchone() is None
                connection.execute("DROP TRIGGER fail_cross_claim_operation")
            retried = await runtime.adapters.dispatch(adapter, context, f"领取跨服宗门战奖励 {ROUND_ID}")
            assert retried.code == "CROSS_SERVER_WAR_REWARD_CLAIMED"
            assert _player_state(runtime.settings.database_path, user)[0] == 20
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute(
                    "SELECT operation_id FROM sect_cross_server_weekly_rewards WHERE player_id=?",
                    (players[user],),
                ).fetchone()[0] == "claim-box-failure"
            await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize(
    ("adapter", "user", "base_name"),
    (("qq.official", "reward-box-qq", "qq"), ("onebot.v11", "reward-box-ob", "onebot")),
)
def test_cross_server_expired_auto_grant_rejects_bad_reward_and_recovers_once(
    adapter: str, user: str, base_name: str
) -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 28, 12, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime, qq_base, onebot_base, players = await _seed_runtime(data_dir, clock)
            player_ids = (players["reward-box-qq"], players["reward-box-ob"])
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE sect_cross_server_weekly_rewards SET reward_json=? WHERE player_id=?",
                    ('{"void_merit":20,"status":"pending","void_merit":999}', player_ids[0]),
                )
            clock.value = datetime(2026, 10, 4, 20, 30, tzinfo=timezone.utc)
            base = qq_base if base_name == "qq" else onebot_base
            context = _context(base, adapter=adapter, user=user, operation_id=f"auto-grant-{base_name}")
            failed = await runtime.adapters.dispatch(adapter, context, f"跨服宗门战 {ROUND_ID}")
            assert failed.code == "PERSISTENCE_ERROR"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                merits = dict(
                    connection.execute(
                        "SELECT platform_user_id,void_merit FROM players WHERE platform_user_id IN ('reward-box-qq','reward-box-ob')"
                    ).fetchall()
                )
                statuses = [
                    json.loads(value)["status"]
                    for (value,) in connection.execute(
                        "SELECT reward_json FROM sect_cross_server_weekly_rewards WHERE round_id=? ORDER BY player_id",
                        (ROUND_ID,),
                    )
                ]
                assert merits == {"reward-box-qq": 0, "reward-box-ob": 0}
                assert statuses.count("pending") == 2
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE sect_cross_server_weekly_rewards SET reward_json=? WHERE player_id=?",
                    ('{"void_merit":20,"status":"pending"}', player_ids[0]),
                )
            recovered = await runtime.adapters.dispatch(adapter, context, f"跨服宗门战 {ROUND_ID}")
            assert recovered.code == "CROSS_SERVER_WAR_STATUS"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                merits = dict(
                    connection.execute(
                        "SELECT platform_user_id,void_merit FROM players WHERE platform_user_id IN ('reward-box-qq','reward-box-ob')"
                    ).fetchall()
                )
                rewards = [
                    (json.loads(value), operation_id)
                    for value, operation_id in connection.execute(
                        "SELECT reward_json,operation_id FROM sect_cross_server_weekly_rewards WHERE round_id=? ORDER BY player_id",
                        (ROUND_ID,),
                    )
                ]
                assert merits == {"reward-box-qq": 20, "reward-box-ob": 20}
                assert all(reward["status"] == "claimed" for reward, _ in rewards)
                assert all(operation_id.endswith(":auto") for _, operation_id in rewards)
            again = await runtime.adapters.dispatch(
                adapter,
                _context(base, adapter=adapter, user=user, operation_id=f"auto-grant-replay-{base_name}"),
                f"跨服宗门战 {ROUND_ID}",
            )
            assert again.code == "CROSS_SERVER_WAR_STATUS"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                merits = dict(
                    connection.execute(
                        "SELECT platform_user_id,void_merit FROM players WHERE platform_user_id IN ('reward-box-qq','reward-box-ob')"
                    ).fetchall()
                )
                assert merits == {"reward-box-qq": 20, "reward-box-ob": 20}
            await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize(
    ("adapter", "user", "base_name"),
    (("qq.official", "reward-box-qq", "qq"), ("onebot.v11", "reward-box-ob", "onebot")),
)
def test_cross_server_reward_box_replay_is_idempotent_after_full_allocation(
    adapter: str, user: str, base_name: str
) -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 28, 12, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime, qq_base, onebot_base, players = await _seed_runtime(data_dir, clock)
            base = qq_base if base_name == "qq" else onebot_base
            target = user
            context = _context(base, adapter=adapter, user=user, operation_id="allocate-box")
            command = f"分配跨服宗门战奖励 {ROUND_ID} {target} 10"
            first = await runtime.adapters.dispatch(adapter, context, command)
            assert first.code == "CROSS_SERVER_REWARD_ALLOCATED"
            replay = await runtime.adapters.dispatch(adapter, context, command)
            assert replay.code == "CROSS_SERVER_REWARD_ALLOCATED"
            assert replay.data["idempotent_replay"] is True
            inventory = json.loads(_player_state(runtime.settings.database_path, target)[1])
            assert inventory["item.void_crystal"] == 10
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute("SELECT COUNT(*) FROM sect_cross_server_reward_allocations").fetchone()[0] == 1
                assert connection.execute("SELECT status FROM sect_cross_server_reward_boxes WHERE box_id='reward-box-id'").fetchone()[0] == "distributed"
            await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize(
    ("adapter", "user", "base_name"),
    (("qq.official", "reward-box-qq", "qq"), ("onebot.v11", "reward-box-ob", "onebot")),
)
def test_cross_server_allocation_operation_failure_rolls_back_and_retries(
    adapter: str, user: str, base_name: str
) -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 28, 12, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime, qq_base, onebot_base, _ = await _seed_runtime(data_dir, clock)
            base = qq_base if base_name == "qq" else onebot_base
            operation_id = "allocation-box-failure"
            context = _context(base, adapter=adapter, user=user, operation_id=operation_id)
            command = f"分配跨服宗门战奖励 {ROUND_ID} {user} 10"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "CREATE TRIGGER fail_cross_allocation_operation BEFORE INSERT ON operations "
                    "WHEN NEW.operation_id='allocation-box-failure' BEGIN SELECT RAISE(ABORT, 'injected allocation failure'); END"
                )
            failed = await runtime.adapters.dispatch(adapter, context, command)
            assert failed.code == "PERSISTENCE_ERROR"
            assert _player_state(runtime.settings.database_path, user)[1] == "{}"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                distributed_json, allocation_count, operation_count = connection.execute(
                    "SELECT distributed_json, "
                    "(SELECT COUNT(*) FROM sect_cross_server_reward_allocations), "
                    "(SELECT COUNT(*) FROM operations WHERE operation_id=?) "
                    "FROM sect_cross_server_reward_boxes WHERE box_id='reward-box-id'",
                    (operation_id,),
                ).fetchone()
                assert distributed_json == "{}"
                assert allocation_count == 0
                assert operation_count == 0
                connection.execute("DROP TRIGGER fail_cross_allocation_operation")
            retried = await runtime.adapters.dispatch(adapter, context, command)
            assert retried.code == "CROSS_SERVER_REWARD_ALLOCATED"
            assert _player_state(runtime.settings.database_path, user)[1] == '{"item.void_crystal": 10}'
            replay = await runtime.adapters.dispatch(adapter, context, command)
            assert replay.code == "CROSS_SERVER_REWARD_ALLOCATED"
            assert replay.data["idempotent_replay"] is True
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute("SELECT COUNT(*) FROM sect_cross_server_reward_allocations").fetchone()[0] == 1
            await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize(
    ("adapter", "user", "base_name"),
    (("qq.official", "reward-box-qq", "qq"), ("onebot.v11", "reward-box-ob", "onebot")),
)
def test_cross_server_reward_box_rejects_tampered_distribution_without_writes(
    adapter: str, user: str, base_name: str
) -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 28, 12, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime, qq_base, onebot_base, players = await _seed_runtime(data_dir, clock)
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE sect_cross_server_reward_boxes SET distributed_json=? WHERE box_id='reward-box-id'",
                    ('{"item.void_crystal": -1}',),
                )
                before = _player_state(runtime.settings.database_path, user)
            base = qq_base if base_name == "qq" else onebot_base
            result = await runtime.adapters.dispatch(
                adapter,
                _context(base, adapter=adapter, user=user, operation_id=f"tampered-box-{base_name}"),
                f"分配跨服宗门战奖励 {ROUND_ID} {user} 10",
            )
            assert result.code == "CROSS_SERVER_REWARD_ALLOCATION_INVALID"
            assert _player_state(runtime.settings.database_path, user) == before
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute("SELECT COUNT(*) FROM sect_cross_server_reward_allocations").fetchone()[0] == 0
                assert connection.execute("SELECT 1 FROM operations WHERE operation_id=?", (f"tampered-box-{base_name}",)).fetchone() is None
            await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize(
    ("adapter", "user", "base_name"),
    (("qq.official", "reward-box-qq", "qq"), ("onebot.v11", "reward-box-ob", "onebot")),
)
def test_cross_server_reward_box_rejects_missing_reward_snapshot_without_writes(
    adapter: str, user: str, base_name: str
) -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 28, 12, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime, qq_base, onebot_base, _ = await _seed_runtime(data_dir, clock)
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE sect_cross_server_reward_boxes SET reward_json='{}' WHERE box_id='reward-box-id'"
                )
            base = qq_base if base_name == "qq" else onebot_base
            result = await runtime.adapters.dispatch(
                adapter,
                _context(base, adapter=adapter, user=user, operation_id=f"missing-reward-{base_name}"),
                f"分配跨服宗门战奖励 {ROUND_ID} {user} 1",
            )
            assert result.code == "CROSS_SERVER_REWARD_ALLOCATION_INVALID"
            assert _player_state(runtime.settings.database_path, user)[1] == "{}"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute("SELECT COUNT(*) FROM sect_cross_server_reward_allocations").fetchone()[0] == 0
                assert connection.execute("SELECT 1 FROM operations WHERE operation_id=?", (f"missing-reward-{base_name}",)).fetchone() is None
            await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize(
    ("adapter", "user", "base_name"),
    (("qq.official", "reward-box-qq", "qq"), ("onebot.v11", "reward-box-ob", "onebot")),
)
def test_cross_server_allocation_replay_uses_operation_when_box_snapshot_is_corrupt(
    adapter: str, user: str, base_name: str
) -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 28, 12, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime, qq_base, onebot_base, _ = await _seed_runtime(data_dir, clock)
            base = qq_base if base_name == "qq" else onebot_base
            context = _context(base, adapter=adapter, user=user, operation_id="allocation-replay-corrupt-box")
            command = f"分配跨服宗门战奖励 {ROUND_ID} {user} 5"
            first = await runtime.adapters.dispatch(adapter, context, command)
            assert first.code == "CROSS_SERVER_REWARD_ALLOCATED"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE sect_cross_server_reward_boxes SET distributed_json='not-json' WHERE box_id='reward-box-id'"
                )
            replay = await runtime.adapters.dispatch(adapter, context, command)
            assert replay.code == "CROSS_SERVER_REWARD_ALLOCATED"
            assert replay.data["idempotent_replay"] is True
            assert json.loads(_player_state(runtime.settings.database_path, user)[1])["item.void_crystal"] == 5
            await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize(
    ("adapter", "user", "base_name"),
    (("qq.official", "reward-box-qq", "qq"), ("onebot.v11", "reward-box-ob", "onebot")),
)
def test_cross_server_claim_replay_after_runtime_restart_does_not_grant_twice(
    adapter: str, user: str, base_name: str
) -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 28, 12, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime, qq_base, onebot_base, _ = await _seed_runtime(data_dir, clock)
            base = qq_base if base_name == "qq" else onebot_base
            context = _context(base, adapter=adapter, user=user, operation_id="restart-claim")
            command = f"领取跨服宗门战奖励 {ROUND_ID}"
            claimed = await runtime.adapters.dispatch(adapter, context, command)
            assert claimed.code == "CROSS_SERVER_WAR_REWARD_CLAIMED"
            assert _player_state(runtime.settings.database_path, user)[0] == 20
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute(
                    "SELECT operation_id FROM sect_cross_server_weekly_rewards w JOIN players p ON p.id=w.player_id WHERE p.platform_user_id=?",
                    (user,),
                ).fetchone()[0] == "restart-claim"
            await runtime.close()

            recovered = create_runtime(data_dir=data_dir, clock=clock)
            replay = await recovered.adapters.dispatch(adapter, context, command)
            assert replay.code == "CROSS_SERVER_WAR_REWARD_CLAIMED"
            assert replay.data["idempotent_replay"] is True
            assert _player_state(recovered.settings.database_path, user)[0] == 20
            with sqlite3.connect(recovered.settings.database_path) as connection:
                assert connection.execute(
                    "SELECT operation_id FROM sect_cross_server_weekly_rewards w JOIN players p ON p.id=w.player_id WHERE p.platform_user_id=?",
                    (user,),
                ).fetchone()[0] == "restart-claim"
            await recovered.close()

    asyncio.run(run())
