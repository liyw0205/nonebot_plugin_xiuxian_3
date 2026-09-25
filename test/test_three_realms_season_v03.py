from __future__ import annotations

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
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.events.three_realms_rules import season_window


class MutableClock:
    def __init__(self, value: datetime):
        self.value = value

    def __call__(self) -> datetime:
        return self.value


def _contexts():
    qq = normalize_qq_event(
        GroupMessageCreateEvent(
            id="three-realms-qq-message",
            content="三界赛季",
            timestamp="2026-09-23T20:05:00+00:00",
            author=GroupMemberAuthor(id="qq-raw", bot=False, member_openid="three-qq-user", username="匿名道号"),
            group_id="qq-raw-group",
            group_openid="three-qq-group",
        )
    ).context
    onebot = normalize_onebot_event(
        GroupMessageEvent(
            time=1_758_650_700,
            self_id=9001,
            post_type="message",
            sub_type="normal",
            user_id=2002,
            message_type="group",
            message_id=9003,
            message=Message("三界赛季"),
            original_message=Message("三界赛季"),
            raw_message="三界赛季",
            font=0,
            sender=Sender(user_id=2002, nickname="OneBot匿名道号"),
            group_id=3001,
        )
    ).context
    return qq, onebot


def test_three_realms_freeze_claim_and_binding_across_adapters() -> None:
    async def run() -> None:
        initial = datetime(2026, 9, 23, 20, 5, tzinfo=timezone.utc)
        season_id, starts_at, ends_at = season_window(initial)
        clock = MutableClock(starts_at + timedelta(days=2))
        qq, onebot = _contexts()
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            actors = [
                ("qq-season-player", qq, "qq"),
                ("onebot-season-player", onebot, "ob"),
                ("third-season-player", qq, "third"),
            ]
            for user_id, context, prefix in actors:
                actor = replace(context, user_id=user_id, operation_id=f"{prefix}-create")
                assert (await runtime.adapters.dispatch(actor.adapter, actor, "开始修仙")).code == "PLAYER_CREATED"
                assert (await runtime.adapters.dispatch(actor.adapter, replace(actor, operation_id=f"{prefix}-seek"), "寻仙问道")).code == "SEEKING_STARTED"

            event_time = (starts_at + timedelta(days=1)).isoformat()
            with sqlite3.connect(runtime.settings.database_path) as connection:
                player_ids = dict(connection.execute("SELECT platform_user_id, id FROM players").fetchall())
                for index, user_id in enumerate(("qq-season-player", "onebot-season-player", "third-season-player"), start=1):
                    player_id = player_ids[user_id]
                    connection.execute(
                        "INSERT INTO world_event_rounds(round_id,event_key,location_key,status,starts_at,ends_at,claim_expires_at,target_quantity,total_contribution,result_json,rule_version,created_at,updated_at) VALUES (?, 'event.beast_trade', 'beast.three_realms_trade_port', 'settled', ?, ?, ?, 1, ?, '{}', 'events-0.3.1', ?, ?)",
                        (f"season-event-{index}", starts_at.isoformat(), ends_at.isoformat(), ends_at.isoformat(), 100 - index * 10, event_time, event_time),
                    )
                    connection.execute(
                        "INSERT INTO world_event_contribution_events(round_id,player_id,source_operation_id,quantity,applied_quantity,occurred_at) VALUES (?, ?, ?, ?, ?, ?)",
                        (f"season-event-{index}", player_id, f"season-source-{index}", 100 - index * 10, 100 - index * 10, event_time),
                    )
                    connection.execute(
                        "INSERT INTO parties(party_id,party_type,status,leader_id,location_key,confirmation_deadline,content_version,rule_version,created_at,updated_at) VALUES (?, 'beast_realm', 'disbanded', ?, 'beast.beast_hills', ?, 'content-0.3', 'combat-0.3', ?, ?)",
                        (f"season-party-{index}", player_id, ends_at.isoformat(), event_time, event_time),
                    )
                    connection.execute(
                        "INSERT INTO party_battle_sessions(battle_id,party_id,start_operation_id,battle_type,enemy_key,location_key,status,round_no,action_sequence,starts_at,turn_deadline,snapshot_json,state_json,result_json,content_version,rule_version,created_at,updated_at) VALUES (?, ?, ?, 'pve.party', 'enemy.test', 'beast.beast_hills', 'settled', 10, 10, ?, ?, '{}', '{}', ?, 'content-0.3', 'combat-0.3', ?, ?)",
                        (f"season-battle-{index}", f"season-party-{index}", f"season-battle-op-{index}", event_time, ends_at.isoformat(), json.dumps({"contribution": {str(player_id): 100 - index * 10}}), event_time, event_time),
                    )
                connection.execute(
                    "INSERT INTO sects(sect_id,name,name_key,motto,leader_id,status,max_members,warehouse_capacity,construction,spirit_stones,created_at,updated_at,content_version,rule_version) VALUES ('season-sect','三界宗','season-sect','', ?, 'active', 10, 10, 0, 0, ?, ?, 'content-0.1', 'social-0.1')",
                    (player_ids["qq-season-player"], event_time, event_time),
                )
                for index, user_id in enumerate(("qq-season-player", "onebot-season-player", "third-season-player"), start=1):
                    player_id = player_ids[user_id]
                    connection.execute(
                        "INSERT INTO sect_members(sect_id,player_id,role,status,contribution,joined_at,last_action_at,created_at,updated_at) VALUES ('season-sect', ?, 'member', 'active', ?, ?, ?, ?, ?)",
                        (player_id, 100 - index * 10, event_time, event_time, event_time, event_time),
                    )
                    connection.execute(
                        "INSERT INTO sect_contribution_events(sect_id,player_id,source_operation_id,quantity,occurred_at) VALUES ('season-sect', ?, ?, ?, ?)",
                        (player_id, f"season-sect-source-{index}", 100 - index * 10, event_time),
                    )

            current = await runtime.adapters.dispatch("qq.official", replace(qq, user_id="qq-season-player", operation_id="qq-season-open"), "三界赛季 阵营功勋")
            assert current.code == "THREE_REALMS_SEASON_RANKING"
            assert current.data["status"] == "collecting"
            public = json.dumps(current.data, ensure_ascii=False)
            assert "qq-season-player" not in public
            assert "匿名道号" not in public

            clock.value = ends_at
            frozen = await runtime.adapters.dispatch("onebot.v11", replace(onebot, user_id="onebot-season-player", operation_id="ob-season-freeze"), f"三界赛季 {season_id}")
            assert frozen.code == "THREE_REALMS_SEASON_RANKING"
            assert frozen.data["status"] == "frozen"
            assert {entry["board_key"] for entry in frozen.data["standings"]} == {"faction_merit", "party_contribution", "sect_contribution"}

            claim = await runtime.adapters.dispatch("qq.official", replace(qq, user_id="qq-season-player", operation_id="qq-season-claim"), f"领取三界赛季奖励 {season_id}")
            assert claim.code == "THREE_REALMS_REWARD_CLAIMED"
            assert claim.data["rewards"] == {"item.soul_crystal": 15, "world_merit": 600}
            replay = await runtime.adapters.dispatch("qq.official", replace(qq, user_id="qq-season-player", operation_id="qq-season-claim"), f"领取三界赛季奖励 {season_id}")
            assert replay.data["idempotent_replay"] is True
            duplicate = await runtime.adapters.dispatch("qq.official", replace(qq, user_id="qq-season-player", operation_id="qq-season-claim-again"), f"领取三界赛季奖励 {season_id}")
            assert duplicate.code == "THREE_REALMS_REWARD_ALREADY_CLAIMED"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                inventory = json.loads(connection.execute("SELECT inventory_json FROM players WHERE platform_user_id='qq-season-player'").fetchone()[0])
                assert inventory["item.soul_crystal"] == 15
                assert connection.execute("SELECT quantity FROM season_item_bindings WHERE season_id=?", (season_id,)).fetchone()[0] == 15
                assert connection.execute("SELECT COUNT(*) FROM three_realms_rankings WHERE season_id=?", (season_id,)).fetchone()[0] == 9
            clock.value = ends_at + timedelta(days=8)
            expired = await runtime.adapters.dispatch("onebot.v11", replace(onebot, user_id="onebot-season-player", operation_id="ob-season-expired"), f"领取三界赛季奖励 {season_id}")
            assert expired.code == "THREE_REALMS_REWARD_EXPIRED"
            history = await runtime.adapters.dispatch("qq.official", replace(qq, user_id="qq-season-player", operation_id="qq-season-history"), f"三界赛季 {season_id}")
            assert history.data["status"] == "frozen"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute("SELECT COUNT(*) FROM three_realms_rankings WHERE season_id=?", (season_id,)).fetchone()[0] == 9

    import asyncio

    asyncio.run(run())
