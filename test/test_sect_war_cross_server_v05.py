from __future__ import annotations

import asyncio
import json
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
from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime


class MutableClock:
    def __init__(self, value: datetime):
        self.value = value

    def __call__(self) -> datetime:
        return self.value


def _contexts() -> tuple[CommandContext, CommandContext]:
    qq = normalize_qq_event(
        GroupMessageCreateEvent(
            id="cross-war-qq",
            content="跨服宗门战",
            timestamp="2026-09-25T12:00:00+00:00",
            author=GroupMemberAuthor(id="qq-raw", bot=False, member_openid="cross-qq", username="QQ成员"),
            group_id="qq-group",
            group_openid="qq-group",
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


def test_qq_and_onebot_cross_server_fortress_war_and_reward_box() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 25, 12, tzinfo=timezone.utc))
        qq_base, onebot_base = _contexts()
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)

            for user, adapter, base in (("cross-qq", "qq.official", qq_base), ("cross-ob", "onebot.v11", onebot_base)):
                context = replace(base, user_id=user, adapter=adapter, operation_id=f"create-{user}", request_id=f"create-{user}")
                assert (await runtime.adapters.dispatch(adapter, context, "开始修仙")).code == "PLAYER_CREATED"

            now_text = clock.value.isoformat()
            with sqlite3.connect(runtime.settings.database_path) as connection:
                players = dict(connection.execute("SELECT platform_user_id,id FROM players").fetchall())
                connection.execute(
                    "INSERT INTO sects(sect_id,name,name_key,leader_id,status,level,max_members,warehouse_capacity,construction,spirit_stones,sect_merit,warehouse_json,created_at,updated_at,content_version,rule_version) VALUES ('cross-sect','跨服堡垒宗','cross-sect',?,'active',5,120,100,0,20000,0,?,?,?,'content-0.5','social-0.5.0')",
                    (players["cross-qq"], json.dumps({"item.void_anchor": 25}), now_text, now_text),
                )
                for user, role, contribution in (("cross-qq", "leader", 20), ("cross-ob", "member", 10)):
                    connection.execute(
                        "INSERT INTO sect_members(sect_id,player_id,role,status,contribution,joined_at,last_action_at,created_at,updated_at) VALUES ('cross-sect',? ,?,'active',?,?,?,?,?)",
                        (players[user], role, contribution, now_text, now_text, now_text, now_text),
                    )
                connection.execute("UPDATE players SET void_power=100, void_power_max=100, space_resistance_bp=8000 WHERE id IN (?,?)", (players["cross-qq"], players["cross-ob"]))
                for source_id, user in (("cross-score-1", "cross-qq"), ("cross-score-2", "cross-ob"), ("cross-score-3", "cross-qq"), ("cross-score-4", "cross-ob")):
                    connection.execute("INSERT INTO operations(operation_id,operation_name,player_id,request_hash,result_json,created_at) VALUES (?, 'test.source', ?, '', '{}', ?)", (source_id, players[user], now_text))

            qq = replace(qq_base, user_id="cross-qq", adapter="qq.official")
            onebot = replace(onebot_base, user_id="cross-ob", adapter="onebot.v11")
            assert (await runtime.adapters.dispatch("qq.official", replace(qq, operation_id="build-fortress"), "建造虚空堡垒")).code == "SECT_FORTRESS_BUILDING"
            denied = await runtime.adapters.dispatch("onebot.v11", replace(onebot, operation_id="member-build"), "建造虚空堡垒")
            assert denied.code == "SECT_PERMISSION_DENIED"

            clock.value += timedelta(hours=49)
            fortress = await runtime.adapters.dispatch("onebot.v11", replace(onebot, operation_id="fortress-status"), "虚空堡垒")
            assert fortress.data["status"] == "active"
            registered = await runtime.adapters.dispatch("qq.official", replace(qq, operation_id="cross-register"), "报名跨服宗门战")
            assert registered.code == "CROSS_SERVER_WAR_REGISTERED"
            assert registered.data["roster_size"] == 2
            round_id = registered.data["round_id"]
            replay = await runtime.adapters.dispatch("qq.official", replace(qq, operation_id="cross-register"), "报名跨服宗门战")
            assert replay.data["idempotent_replay"] is True

            clock.value = datetime(2026, 9, 27, 20, 1, tzinfo=timezone.utc)
            branch = await runtime.adapters.dispatch("onebot.v11", replace(onebot, operation_id="cross-branch"), f"跨服宗门战分支 repair {round_id}")
            assert branch.code == "CROSS_SERVER_WAR_BRANCH_LOCKED"
            conflict = await runtime.adapters.dispatch("qq.official", replace(qq, operation_id="cross-branch-conflict"), f"跨服宗门战分支 break {round_id}")
            assert conflict.code == "FORTRESS_BRANCH_LOCKED"

            for operation, text, adapter, context in (
                ("score-qq-1", f"贡献跨服宗门战 占点 target-a cross-score-1 {round_id}", "qq.official", qq),
                ("score-ob-1", f"贡献跨服宗门战 击败 target-a cross-score-2 {round_id}", "onebot.v11", onebot),
                ("score-qq-2", f"贡献跨服宗门战 摧毁战争机关 target-a cross-score-3 {round_id}", "qq.official", qq),
            ):
                result = await runtime.adapters.dispatch(adapter, replace(context, operation_id=operation), text)
                assert result.code == "CROSS_SERVER_WAR_SCORED"
            limited = await runtime.adapters.dispatch("onebot.v11", replace(onebot, operation_id="score-ob-limit"), f"贡献跨服宗门战 占点 target-a cross-score-4 {round_id}")
            assert limited.code == "CROSS_SERVER_SOURCE_INVALID"

            clock.value = datetime(2026, 9, 27, 20, 31, tzinfo=timezone.utc)
            settled = await runtime.adapters.dispatch("onebot.v11", replace(onebot, operation_id="cross-status-settled"), f"跨服宗门战 {round_id}")
            assert settled.data["status"] == "settled"
            assert settled.data["standings"][0]["score"] == 45

            claimed = await runtime.adapters.dispatch("onebot.v11", replace(onebot, operation_id="cross-claim"), f"领取跨服宗门战奖励 {round_id}")
            assert claimed.code == "CROSS_SERVER_WAR_REWARD_CLAIMED"
            replay_claim = await runtime.adapters.dispatch("onebot.v11", replace(onebot, operation_id="cross-claim"), f"领取跨服宗门战奖励 {round_id}")
            assert replay_claim.data["idempotent_replay"] is True
            allocated = await runtime.repository.allocate_cross_server_reward(
                platform="qq.official",
                platform_user_id="cross-qq",
                round_id=round_id,
                target_platform="qq.official",
                target_platform_user_id="cross-qq",
                quantity=10,
                operation_id="cross-box-allocate",
            )
            assert allocated.reward["item.void_crystal"] == 10
            clock.value = datetime(2026, 10, 5, 21, 0, tzinfo=timezone.utc)
            recovered = await runtime.adapters.dispatch("qq.official", replace(qq, operation_id="cross-expiry-recovery"), f"跨服宗门战 {round_id}")
            assert recovered.data["status"] == "settled"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                merit = connection.execute("SELECT void_merit FROM players WHERE platform_user_id='cross-ob'").fetchone()[0]
                auto_merit = connection.execute("SELECT void_merit FROM players WHERE platform_user_id='cross-qq'").fetchone()[0]
                crystal = json.loads(connection.execute("SELECT inventory_json FROM players WHERE platform_user_id='cross-qq'").fetchone()[0])["item.void_crystal"]
                assert merit == 20
                assert auto_merit == 20
                assert crystal == 10
                assert connection.execute("SELECT status FROM sect_cross_server_reward_boxes WHERE round_id=?", (round_id,)).fetchone()[0] == "distributed"
            await runtime.close()

    asyncio.run(run())


def test_cross_server_fortress_build_is_concurrent_and_idempotent() -> None:
    async def run() -> None:
        now = datetime(2026, 9, 25, 12, tzinfo=timezone.utc)
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=lambda: now)
            context = CommandContext(adapter="qq.official", user_id="concurrent-leader", operation_id="create", can_write_assets=True)
            assert (await runtime.dispatch(context, "开始修仙")).code == "PLAYER_CREATED"
            now_text = now.isoformat()
            with sqlite3.connect(runtime.settings.database_path) as connection:
                player_id = connection.execute("SELECT id FROM players WHERE platform_user_id='concurrent-leader'").fetchone()[0]
                connection.execute(
                    "INSERT INTO sects(sect_id,name,name_key,leader_id,status,level,max_members,warehouse_capacity,construction,spirit_stones,sect_merit,warehouse_json,created_at,updated_at,content_version,rule_version) VALUES ('concurrent-sect','并发宗','concurrent-sect',?,'active',5,120,100,0,10000,0,?,?,?,'content-0.5','social-0.5.0')",
                    (player_id, json.dumps({"item.void_anchor": 20}), now_text, now_text),
                )
                connection.execute(
                    "INSERT INTO sect_members(sect_id,player_id,role,status,contribution,joined_at,last_action_at,created_at,updated_at) VALUES ('concurrent-sect',?,'leader','active',0,?,?,?,?)",
                    (player_id, now_text, now_text, now_text, now_text),
                )
            calls = await asyncio.gather(
                runtime.repository.build_void_fortress(platform="qq.official", platform_user_id="concurrent-leader", operation_id="same-build"),
                runtime.repository.build_void_fortress(platform="qq.official", platform_user_id="concurrent-leader", operation_id="same-build"),
            )
            assert sorted(item.already_completed for item in calls) == [False, True]
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute("SELECT COUNT(*) FROM sect_void_fortresses").fetchone()[0] == 1
                assert connection.execute("SELECT spirit_stones FROM sects WHERE sect_id='concurrent-sect'").fetchone()[0] == 0
            await runtime.close()

    asyncio.run(run())
