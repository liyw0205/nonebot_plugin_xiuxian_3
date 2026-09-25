from __future__ import annotations

import asyncio
import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory

from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message
from nonebot.adapters.onebot.v11.event import Sender
from nonebot.adapters.qq.event import GroupMessageCreateEvent
from nonebot.adapters.qq.models.qq import GroupMemberAuthor

from nonebot_plugin_xiuxian_3.adapters.onebot import normalize_event as normalize_onebot_event
from nonebot_plugin_xiuxian_3.adapters.qq import normalize_event as normalize_qq_event
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.persistence.sqlite_repository import SQLitePlayerRepository


class MutableClock:
    def __init__(self, value: datetime):
        self.value = value

    def __call__(self) -> datetime:
        return self.value


def test_sect_war_migration_adds_columns_to_existing_sects_table() -> None:
    with sqlite3.connect(":memory:") as connection:
        connection.execute(
            "CREATE TABLE sects (sect_id TEXT PRIMARY KEY, spirit_stones INTEGER NOT NULL DEFAULT 0)"
        )
        SQLitePlayerRepository._migrate_sect_war_schema(connection)
        columns = {row[1] for row in connection.execute("PRAGMA table_info(sects)")}
        assert {"level", "sect_merit"}.issubset(columns)
        assert connection.execute("SELECT level, sect_merit FROM sects").fetchone() is None


def _contexts():
    qq = normalize_qq_event(
        GroupMessageCreateEvent(
            id="sect-war-qq-message",
            content="宗门战",
            timestamp="2026-09-23T19:00:00+00:00",
            author=GroupMemberAuthor(id="qq-raw", bot=False, member_openid="qq-war-user", username="隐私道号"),
            group_id="qq-raw-group",
            group_openid="qq-war-group",
        )
    ).context
    onebot = normalize_onebot_event(
        GroupMessageEvent(
            time=1_758_647_400,
            self_id=9001,
            post_type="message",
            sub_type="normal",
            user_id=2002,
            message_type="group",
            message_id=9003,
            message=Message("宗门战"),
            original_message=Message("宗门战"),
            raw_message="宗门战",
            font=0,
            sender=Sender(user_id=2002, nickname="OneBot隐私道号"),
            group_id=3001,
        )
    ).context
    return qq, onebot


def test_sect_war_registration_contribution_settlement_and_rewards_across_adapters() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 23, 19, 0, tzinfo=timezone.utc))
        qq, onebot = _contexts()
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            actors: dict[str, tuple[str, object]] = {}
            for index in range(11):
                actors[f"a{index}"] = ("qq.official" if index % 2 == 0 else "onebot.v11", qq if index % 2 == 0 else onebot)
            actors["b0"] = ("onebot.v11", onebot)
            actors["low0"] = ("qq.official", qq)

            for index, (user, (adapter, base)) in enumerate(actors.items()):
                context = replace(base, user_id=user, operation_id=f"create-{user}", request_id=f"create-{user}")
                created = await runtime.adapters.dispatch(adapter, context, "开始修仙")
                assert created.code == "PLAYER_CREATED"

            now_text = clock.value.isoformat()
            with sqlite3.connect(runtime.settings.database_path) as connection:
                player_ids = dict(connection.execute("SELECT platform_user_id,id FROM players").fetchall())
                for sect_id, leader, level in (("sect-a", "a0", 4), ("sect-b", "b0", 4), ("sect-low", "low0", 3)):
                    connection.execute(
                        "INSERT INTO sects(sect_id,name,name_key,leader_id,status,level,max_members,warehouse_capacity,construction,spirit_stones,sect_merit,created_at,updated_at,content_version,rule_version) "
                        "VALUES (?, ?, ?, ?, 'active', ?, 80, 100, 0, 5000, 0, ?, ?, 'content-0.3', 'social-0.3.1')",
                        (sect_id, sect_id, sect_id, player_ids[leader], level, now_text, now_text),
                    )
                    members = [leader] if sect_id != "sect-a" else [f"a{index}" for index in range(11)]
                    for member in members:
                        role = "leader" if member == leader else "member"
                        connection.execute(
                            "INSERT INTO sect_members(sect_id,player_id,role,status,contribution,joined_at,last_action_at,created_at,updated_at) "
                            "VALUES (?, ?, ?, 'active', 0, ?, ?, ?, ?)",
                            (sect_id, player_ids[member], role, now_text, now_text, now_text, now_text),
                        )

                source_owners = {
                    "a0": ["a0-occupy-1", "a0-occupy-2", "a0-occupy-3"],
                    "a1": ["a1-transport", "a1-repair"],
                    "b0": ["b0-defeat"],
                }
                for user, operation_ids in source_owners.items():
                    for operation_id in operation_ids:
                        connection.execute(
                            "INSERT INTO operations(operation_id,operation_name,player_id,request_hash,result_json,created_at) VALUES (?, 'test.source', ?, '', '{}', ?)",
                            (operation_id, player_ids[user], now_text),
                        )

            def ctx(user: str, operation: str):
                adapter, base = actors[user]
                return adapter, replace(base, user_id=user, operation_id=operation, request_id=operation)

            status_adapter, status_context = ctx("a0", "war-status-open")
            status = await runtime.adapters.dispatch(status_adapter, status_context, "宗门战")
            assert status.code == "SECT_WAR_STATUS"
            assert status.data["status"] == "open"
            round_id = status.data["round_id"]

            adapter, leader_context = ctx("a0", "war-register-a")
            denied_member_adapter, denied_member_context = ctx("a1", "war-register-member")
            denied_member = await runtime.adapters.dispatch(denied_member_adapter, denied_member_context, f"报名宗门战 {round_id}")
            assert denied_member.code == "SECT_WAR_REQUIREMENT_MISSING"
            low_adapter, low_context = ctx("low0", "war-register-low")
            low_level = await runtime.adapters.dispatch(low_adapter, low_context, f"报名宗门战 {round_id}")
            assert low_level.code == "SECT_WAR_REQUIREMENT_MISSING"

            registered = await runtime.adapters.dispatch(adapter, leader_context, f"报名宗门战 {round_id}")
            assert registered.code == "SECT_WAR_REGISTERED"
            registration_replay = await runtime.adapters.dispatch(adapter, leader_context, f"报名宗门战 {round_id}")
            assert registration_replay.data["idempotent_replay"] is True
            opponent_adapter, opponent_context = ctx("b0", "war-register-b")
            opponent = await runtime.adapters.dispatch(opponent_adapter, opponent_context, f"报名宗门战 {round_id}")
            assert opponent.code == "SECT_WAR_REGISTERED"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute("SELECT spirit_stones FROM sects WHERE sect_id='sect-a'").fetchone()[0] == 3000
                roster = connection.execute(
                    "SELECT COUNT(*) FROM sect_war_members WHERE round_id=? AND sect_id='sect-a'", (round_id,)
                ).fetchone()[0]
                assert roster == 10

            clock.value = datetime(2026, 9, 23, 20, 5, tzinfo=timezone.utc)
            ob_adapter, ob_context = ctx("a1", "war-status-running")
            running = await runtime.adapters.dispatch(ob_adapter, ob_context, f"宗门战 {round_id}")
            assert running.data["status"] == "running"

            a0_adapter, a0_context = ctx("a0", "war-a0-foreign-source")
            foreign = await runtime.adapters.dispatch(a0_adapter, a0_context, f"贡献宗门战 占点 b0-defeat {round_id}")
            assert foreign.code == "SECT_WAR_SOURCE_INVALID"

            a0_adapter, a0_first = ctx("a0", "war-a0-occupy-1")
            first = await runtime.adapters.dispatch(a0_adapter, a0_first, f"贡献宗门战 占点 a0-occupy-1 {round_id}")
            assert first.data["player_contribution"] == 10
            replay = await runtime.adapters.dispatch(a0_adapter, a0_first, f"贡献宗门战 占点 a0-occupy-1 {round_id}")
            assert replay.data["idempotent_replay"] is True
            same_source_adapter, same_source_context = ctx("a0", "war-a0-source-reuse")
            same_source = await runtime.adapters.dispatch(same_source_adapter, same_source_context, f"贡献宗门战 占点 a0-occupy-1 {round_id}")
            assert same_source.code == "SECT_WAR_SOURCE_INVALID"
            _, second_context = ctx("a0", "war-a0-occupy-2")
            second = await runtime.adapters.dispatch("qq.official", second_context, f"贡献宗门战 占点 a0-occupy-2 {round_id}")
            assert second.data["player_contribution"] == 20
            _, third_context = ctx("a0", "war-a0-occupy-limit")
            limited = await runtime.adapters.dispatch("qq.official", third_context, f"贡献宗门战 占点 a0-occupy-3 {round_id}")
            assert limited.code == "SECT_WAR_SOURCE_INVALID"

            _, transport_context = ctx("a1", "war-a1-transport")
            transport = await runtime.adapters.dispatch("onebot.v11", transport_context, f"贡献宗门战 运输 a1-transport {round_id}")
            _, repair_context = ctx("a1", "war-a1-repair")
            repair = await runtime.adapters.dispatch("onebot.v11", repair_context, f"贡献宗门战 维修 a1-repair {round_id}")
            assert transport.data["player_contribution"] == 15
            assert repair.data["player_contribution"] == 30
            _, defeat_context = ctx("b0", "war-b0-defeat")
            defeat = await runtime.adapters.dispatch("onebot.v11", defeat_context, f"贡献宗门战 击败 b0-defeat {round_id}")
            assert defeat.data["player_contribution"] == 5

            clock.value = datetime(2026, 9, 23, 20, 31, tzinfo=timezone.utc)
            _, settled_context = ctx("a0", "war-settle")
            settled = await runtime.adapters.dispatch("qq.official", settled_context, f"宗门战 {round_id}")
            assert settled.data["status"] == "settled"
            assert settled.data["winner_sect_id"] == "sect-a"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute("SELECT sect_merit FROM sects WHERE sect_id='sect-a'").fetchone()[0] == 100
                assert connection.execute("SELECT sect_merit FROM sects WHERE sect_id='sect-b'").fetchone()[0] == 0

            _, claim_context = ctx("a0", "war-claim-a0")
            claimed = await runtime.adapters.dispatch("qq.official", claim_context, f"领取宗门战奖励 {round_id}")
            assert claimed.code == "SECT_WAR_REWARD_CLAIMED"
            assert claimed.data["reward"]["world_merit"] == 30
            claim_replay = await runtime.adapters.dispatch("qq.official", claim_context, f"领取宗门战奖励 {round_id}")
            assert claim_replay.data["idempotent_replay"] is True
            _, duplicate_context = ctx("a0", "war-claim-a0-new-operation")
            duplicate = await runtime.adapters.dispatch("qq.official", duplicate_context, f"领取宗门战奖励 {round_id}")
            assert duplicate.code == "SECT_WAR_REWARD_ALREADY_CLAIMED"

            clock.value = datetime(2026, 9, 24, 20, 31, tzinfo=timezone.utc)
            _, auto_claim_context = ctx("a1", "war-claim-a1-after-deadline")
            auto_claim = await runtime.adapters.dispatch("onebot.v11", auto_claim_context, f"领取宗门战奖励 {round_id}")
            assert auto_claim.code == "SECT_WAR_REWARD_EXPIRED"
            assert auto_claim.data["reward"]["world_merit"] == 30
            with sqlite3.connect(runtime.settings.database_path) as connection:
                world_merit = dict(connection.execute("SELECT platform_user_id,world_merit FROM players").fetchall())
                assert world_merit["a0"] == 30
                assert world_merit["a1"] == 30
                auto_status = connection.execute(
                    "SELECT status FROM sect_war_claims WHERE round_id=? AND player_id=?",
                    (round_id, next(player_id for user, player_id in player_ids.items() if user == "a1")),
                ).fetchone()[0]
                assert auto_status == "auto_granted"

            public = str(settled.data) + claimed.message
            assert "a0" not in public
            assert "qq-war-user" not in public
            assert "OneBot隐私道号" not in public

    asyncio.run(run())
