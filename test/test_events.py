from __future__ import annotations

import asyncio
import json
import sqlite3
import shutil
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.adapters.onebot import normalize_event as normalize_onebot_event
from nonebot_plugin_xiuxian_3.adapters.qq import normalize_event as normalize_qq_event
from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime


class MutableClock:
    def __init__(self, value: datetime):
        self.value = value

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **kwargs: int) -> None:
        self.value += timedelta(**kwargs)


def _context(user_id: str, operation_id: str = "") -> CommandContext:
    return CommandContext(adapter="web", user_id=user_id, operation_id=operation_id)


def _adapter_contexts():
    from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message
    from nonebot.adapters.onebot.v11.event import Sender
    from nonebot.adapters.qq.event import GroupMessageCreateEvent
    from nonebot.adapters.qq.models.qq import GroupMemberAuthor

    qq = normalize_qq_event(
        GroupMessageCreateEvent(
            id="event-qq-message",
            content="灵泉事件",
            timestamp="2026-09-23T20:05:00+00:00",
            author=GroupMemberAuthor(id="qq-raw", bot=False, member_openid="qq-event-user", member_role="member", username="灵泉道友"),
            group_id="qq-raw-group",
            group_openid="event-qq-group",
        )
    ).context
    onebot = normalize_onebot_event(
        GroupMessageEvent(
            time=1_758_650_700,
            self_id=9001,
            post_type="message",
            sub_type="normal",
            user_id=2001,
            message_type="group",
            message_id=9002,
            message=Message("灵泉事件"),
            original_message=Message("灵泉事件"),
            raw_message="灵泉事件",
            font=0,
            sender=Sender(user_id=2001, nickname="采集者"),
            group_id=3001,
        )
    ).context
    return qq, onebot


async def _create_player(runtime, context: CommandContext, user_id: str, prefix: str) -> None:
    base = replace(context, user_id=user_id, operation_id=f"{prefix}-create")
    assert (await runtime.adapters.dispatch(base.adapter, base, "开始修仙")).ok
    assert (
        await runtime.adapters.dispatch(
            base.adapter,
            replace(base, operation_id=f"{prefix}-seek"),
            "寻仙问道",
        )
    ).ok


def _prepare_spring_player(runtime, user_id: str) -> None:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            """
            UPDATE players
            SET stage = 'cultivator', realm_key = 'qi_sensing', realm_layer = 2,
                location_key = 'xuantian.spirit_field', stamina = 30,
                intro_json = ?
            WHERE platform_user_id = ?
            """,
            (json.dumps({"flags": ["guide.gather_blood_grass"]}), user_id),
        )


def test_spirit_spring_event_uses_qq_onebot_and_original_exploration_operation() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 23, 20, 5, tzinfo=timezone.utc))
        qq, onebot = _adapter_contexts()
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            await _create_player(runtime, qq, "qq-event-user", "qq")
            await _create_player(runtime, onebot, "2001", "onebot")
            _prepare_spring_player(runtime, "2001")

            status = await runtime.adapters.dispatch(
                "qq.official", replace(qq, operation_id="qq-event-status"), "灵泉事件"
            )
            assert status.code == "EVENT_STATUS"
            assert status.data["round_id"] == "20260923"
            assert status.data["status"] == "open"
            assert status.data["minimum_contribution"] == 10

            started = await runtime.adapters.dispatch(
                "onebot.v11", replace(onebot, operation_id="ob-spring-start"), "开始探索 灵泉采集"
            )
            assert started.code == "EXPLORATION_STARTED"
            clock.advance(minutes=2)
            settled = await runtime.adapters.dispatch(
                "onebot.v11", replace(onebot, operation_id="ob-spring-settle"), "结算探索"
            )
            assert settled.code == "EXPLORATION_SETTLED"
            contribution = settled.data["result"]["item.herb.spirit_leaf"]
            replay = await runtime.adapters.dispatch(
                "onebot.v11", replace(onebot, operation_id="ob-spring-settle"), "结算探索"
            )
            assert replay.data["idempotent_replay"] is True

            with sqlite3.connect(runtime.settings.database_path) as connection:
                player_ids = dict(
                    connection.execute("SELECT platform_user_id, id FROM players").fetchall()
                )
                onebot_id = player_ids["2001"]
                qq_id = player_ids["qq-event-user"]
                onebot_contribution = connection.execute(
                    "SELECT contribution FROM world_event_contributions WHERE round_id = '20260923' AND player_id = ?",
                    (onebot_id,),
                ).fetchone()[0]
            assert onebot_contribution == contribution
            assert contribution >= 1

            # Fill the public target using a second player's audited contribution row.
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE world_event_contributions SET contribution = 10, updated_at = ? WHERE round_id = '20260923' AND player_id = ?",
                    (clock.value.isoformat(), onebot_id),
                )
                connection.execute(
                    """
                    INSERT INTO world_event_contributions(round_id, player_id, contribution, updated_at)
                    VALUES ('20260923', ?, 90, ?)
                    ON CONFLICT(round_id, player_id) DO UPDATE SET contribution = 90, updated_at = excluded.updated_at
                    """,
                    (qq_id, clock.value.isoformat()),
                )
            clock.advance(minutes=24)
            settled_event = await runtime.adapters.dispatch(
                "qq.official", replace(qq, operation_id="qq-event-status-after"), "灵泉事件"
            )
            assert settled_event.data["status"] == "settled"
            assert settled_event.data["success"] is True
            assert settled_event.data["total_contribution"] == 100

            claimed = await runtime.adapters.dispatch(
                "onebot.v11",
                replace(onebot, operation_id="ob-event-claim"),
                "领取灵泉事件奖励 20260923",
            )
            assert claimed.code == "EVENT_REWARD_CLAIMED"
            assert claimed.data["minimum_contribution"] == 10
            assert claimed.data["reward"] == {
                "cultivation": 150,
                "faction_reputation.xuantian": 10,
                "spirit_stones": 100,
            }
            replay_claim = await runtime.adapters.dispatch(
                "onebot.v11",
                replace(onebot, operation_id="ob-event-claim"),
                "领取灵泉事件奖励 20260923",
            )
            assert replay_claim.code == claimed.code
            assert replay_claim.data["idempotent_replay"] is True
            assert replay_claim.data["minimum_contribution"] == claimed.data["minimum_contribution"]
            duplicate_claim = await runtime.adapters.dispatch(
                "onebot.v11",
                replace(onebot, operation_id="ob-event-claim-duplicate"),
                "领取灵泉事件奖励 20260923",
            )
            assert duplicate_claim.code == "EVENT_REWARD_ALREADY_CLAIMED"

            with sqlite3.connect(runtime.settings.database_path) as connection:
                player = connection.execute(
                    "SELECT spirit_stones, cultivation, faction_reputation_json FROM players WHERE platform_user_id = '2001'"
                ).fetchone()
            assert player[0] == 200
            assert player[1] == 150
            assert json.loads(player[2])["xuantian"] == 10
            await runtime.close()

    asyncio.run(run())


def test_spirit_spring_event_failed_round_threshold_and_expiry_are_atomic() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 27, 20, 5, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            user = "event-failure-user"
            await runtime.dispatch(_context(user, "create"), "开始修仙")
            await runtime.dispatch(_context(user, "seek"), "寻仙问道")
            status = await runtime.dispatch(_context(user, "status"), "灵泉事件")
            assert status.code == "EVENT_STATUS"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                player_id = connection.execute(
                    "SELECT id FROM players WHERE platform_user_id = ?", (user,)
                ).fetchone()[0]
                connection.execute(
                    "INSERT INTO world_event_contributions(round_id, player_id, contribution, updated_at) VALUES (?, ?, 2, ?)",
                    (status.data["round_id"], player_id, clock.value.isoformat()),
                )
            clock.advance(minutes=31)
            failed = await runtime.dispatch(_context(user, "failed-status"), "灵泉事件")
            assert failed.data["success"] is False
            insufficient = await runtime.dispatch(
                _context(user, "insufficient-claim"), f"领取灵泉事件奖励 {status.data['round_id']}"
            )
            assert insufficient.code == "EVENT_CONTRIBUTION_INSUFFICIENT"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE world_event_contributions SET contribution = 10 WHERE round_id = ? AND player_id = ?",
                    (status.data["round_id"], player_id),
                )
            claimed = await runtime.dispatch(
                _context(user, "failed-claim"), f"领取灵泉事件奖励 {status.data['round_id']}"
            )
            assert claimed.code == "EVENT_REWARD_CLAIMED"
            assert claimed.data["reward"] == {"cultivation": 150, "spirit_stones": 100}
            assert claimed.data["reward_snapshot"]["completion"] is None
            assert claimed.data["reward_snapshot"]["final"]["reputation"] == {}
            clock.advance(hours=25)
            expired = await runtime.dispatch(
                _context(user, "expired-claim"), f"领取灵泉事件奖励 {status.data['round_id']}"
            )
            assert expired.code == "EVENT_REWARD_EXPIRED"

            clock.value = datetime(2026, 9, 28, 21, 0, tzinfo=timezone.utc)
            closed = await runtime.dispatch(_context(user, "closed"), "灵泉事件")
            assert closed.code == "EVENT_NOT_ACTIVE"
            await runtime.close()

    asyncio.run(run())


def test_spirit_spring_reward_content_is_shared_by_adapters_and_replay() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 23, 20, 5, tzinfo=timezone.utc))
        with TemporaryDirectory() as temp:
            data_dir = Path(temp) / "data"
            shutil.copytree(Path(__file__).parents[1] / "data", data_dir)
            reward_file = data_dir / "奖励" / "奖励.json"
            document = json.loads(reward_file.read_text(encoding="utf-8"))
            base = next(
                item for item in document["records"]
                if item["key"] == "reward.event.spirit_spring.base"
            )
            next(entry for entry in base["entries"] if entry["kind"] == "currency")["quantity"] = 321
            next(entry for entry in base["entries"] if entry.get("resource_key") == "cultivation")["quantity"] = 234
            completion = next(
                item for item in document["records"]
                if item["key"] == "reward.event.spirit_spring.completion"
            )
            next(entry for entry in completion["entries"] if entry["kind"] == "reputation")["quantity"] = 17
            reward_file.write_text(
                json.dumps(document, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

            qq, onebot = _adapter_contexts()
            runtime = create_runtime(
                data_dir=data_dir,
                adapters=("qq.official", "onebot.v11"),
                clock=clock,
            )
            try:
                contexts = (("qq.official", qq, "content-qq"), ("onebot.v11", onebot, "content-ob"))
                statuses = []
                for adapter, context, prefix in contexts:
                    await _create_player(runtime, context, context.user_id, prefix)
                    status = await runtime.adapters.dispatch(
                        adapter, replace(context, operation_id=f"{prefix}-status"), "灵泉事件"
                    )
                    assert status.code == "EVENT_STATUS"
                    statuses.append(status)
                assert {status.data["round_id"] for status in statuses} == {"20260923"}

                with sqlite3.connect(runtime.settings.database_path) as connection:
                    player_ids = dict(
                        connection.execute(
                            "SELECT platform_user_id, id FROM players WHERE platform_user_id IN (?, ?)",
                            (qq.user_id, onebot.user_id),
                        ).fetchall()
                    )
                    for player_id in player_ids.values():
                        connection.execute(
                            """
                            INSERT INTO world_event_contributions(round_id, player_id, contribution, updated_at)
                            VALUES ('20260923', ?, 100, ?)
                            """,
                            (player_id, clock.value.isoformat()),
                        )

                clock.advance(minutes=31)
                for adapter, context, prefix in contexts:
                    claimed = await runtime.adapters.dispatch(
                        adapter,
                        replace(context, operation_id=f"{prefix}-claim"),
                        "领取灵泉事件奖励 20260923",
                    )
                    assert claimed.code == "EVENT_REWARD_CLAIMED"
                    assert claimed.data["reward"] == {
                        "cultivation": 234,
                        "faction_reputation.xuantian": 17,
                        "spirit_stones": 321,
                    }
                    assert "玄天界声望" in claimed.message
                    with sqlite3.connect(runtime.settings.database_path) as connection:
                        row = connection.execute(
                            "SELECT cultivation, total_cultivation, faction_reputation_json FROM players WHERE platform_user_id = ?",
                            (context.user_id,),
                        ).fetchone()
                        assert row[0:2] == (234, 234)
                        assert json.loads(row[2])["xuantian"] == 17
                        payload = json.loads(
                            connection.execute(
                                "SELECT result_json FROM operations WHERE operation_id = ?",
                                (f"{prefix}-claim",),
                            ).fetchone()[0]
                        )
                    assert payload["reward_snapshot"]["final"]["value_delta"] == {
                        "cultivation": 234
                    }
                    assert payload["reward_snapshot"]["completion"]["reputation"] == {
                        "faction_reputation.xuantian": 17
                    }

                conflict = await runtime.adapters.dispatch(
                    "qq.official",
                    replace(qq, operation_id="content-qq-claim"),
                    "领取灵泉事件奖励 20260922",
                )
                assert conflict.code == "OPERATION_CONFLICT"

                await runtime.close()
                recovered = create_runtime(
                    data_dir=data_dir,
                    adapters=("qq.official",),
                    clock=clock,
                )
                try:
                    replay = await recovered.adapters.dispatch(
                        "qq.official",
                        replace(qq, operation_id="content-qq-claim"),
                        "领取灵泉事件奖励 20260923",
                    )
                    assert replay.code == "EVENT_REWARD_CLAIMED"
                    assert replay.data["idempotent_replay"] is True
                    assert replay.data["reward"] == {
                        "cultivation": 234,
                        "faction_reputation.xuantian": 17,
                        "spirit_stones": 321,
                    }
                    assert replay.data["reward_snapshot"]["completion"]["reputation"] == {
                        "faction_reputation.xuantian": 17
                    }
                finally:
                    await recovered.close()
            finally:
                if not runtime._closed:
                    await runtime.close()

    asyncio.run(run())


def test_spirit_spring_round_uses_content_and_freezes_old_configuration() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 23, 20, 5, tzinfo=timezone.utc))
        with TemporaryDirectory() as temp:
            data_dir = Path(temp) / "data"
            shutil.copytree(Path(__file__).parents[1] / "data", data_dir)
            (data_dir / "xiuxian3.sqlite3").unlink(missing_ok=True)

            event_path = data_dir / "事件" / "事件.json"
            event_document = json.loads(event_path.read_text(encoding="utf-8"))
            event = next(row for row in event_document["records"] if row["key"] == "event.spirit_spring")
            event.update(
                {
                    "duration_seconds": 600,
                    "schedule": {"weekdays": [3], "local_time": "20:00"},
                    "contribution": {
                        "source_item_key": "item.spirit_water",
                        "per_quantity": 2,
                        "max_per_player": 7,
                    },
                    "global_goal": {"item_key": "item.spirit_water", "quantity": 40},
                    "claim": {
                        "min_contribution": 2,
                        "window_seconds": 3600,
                        "reward_key": "reward.event.spirit_spring.base",
                        "completion_bonus_key": "reward.event.spirit_spring.completion",
                    },
                }
            )
            event_path.write_text(json.dumps(event_document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            item_path = data_dir / "道具" / "材料.json"
            item_document = json.loads(item_path.read_text(encoding="utf-8"))
            next(row for row in item_document["records"] if row["key"] == "item.spirit_water")["name"] = "澄心泉露"
            item_path.write_text(json.dumps(item_document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            qq, onebot = _adapter_contexts()
            runtime = create_runtime(data_dir=data_dir, clock=clock, adapters=("onebot.v11",))
            await _create_player(runtime, onebot, "spring-config-user", "config")
            _prepare_spring_player(runtime, "spring-config-user")
            try:
                status = await runtime.adapters.dispatch(
                    "onebot.v11", replace(onebot, user_id="spring-config-user", operation_id="config-status"), "灵泉事件"
                )
                assert status.code == "EVENT_STATUS"
                assert status.data["ends_at"] == "2026-09-23T20:10:00+00:00"
                assert status.data["target_quantity"] == 40
                assert status.data["minimum_contribution"] == 2
                assert status.data["contribution_cap"] == 7
                assert status.data["source_item_name"] == "澄心泉露"

                started = await runtime.adapters.dispatch(
                    "onebot.v11", replace(onebot, user_id="spring-config-user", operation_id="config-start"), "开始探索 灵泉采集"
                )
                assert started.ok
                clock.advance(minutes=2)
                settled = await runtime.adapters.dispatch(
                    "onebot.v11", replace(onebot, user_id="spring-config-user", operation_id="config-settle"), "结算探索"
                )
                assert settled.code == "EXPLORATION_SETTLED"
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    contribution = connection.execute(
                        "SELECT contribution FROM world_event_contributions"
                    ).fetchone()[0]
                assert contribution == settled.data["result"]["item.spirit_water"] * 2
            finally:
                await runtime.close()

            changed_event = json.loads(event_path.read_text(encoding="utf-8"))
            next(row for row in changed_event["records"] if row["key"] == "event.spirit_spring")["status"] = "closed"
            event_path.write_text(json.dumps(changed_event, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            changed_reward = json.loads((data_dir / "奖励" / "奖励.json").read_text(encoding="utf-8"))
            base = next(row for row in changed_reward["records"] if row["key"] == "reward.event.spirit_spring.base")
            for entry in base["entries"]:
                if entry["kind"] == "currency":
                    entry["quantity"] = 777
                elif entry.get("resource_key") == "cultivation":
                    entry["quantity"] = 888
            (data_dir / "奖励" / "奖励.json").write_text(
                json.dumps(changed_reward, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            clock.advance(minutes=14)
            recovered = create_runtime(data_dir=data_dir, clock=clock, adapters=("onebot.v11",))
            try:
                claimed = await recovered.adapters.dispatch(
                    "onebot.v11",
                    replace(onebot, user_id="spring-config-user", operation_id="config-claim"),
                    "领取灵泉事件奖励 20260923",
                )
                assert claimed.code == "EVENT_REWARD_CLAIMED"
                assert claimed.data["reward"] == {"cultivation": 150, "spirit_stones": 100}
            finally:
                await recovered.close()

            invalid = json.loads(event_path.read_text(encoding="utf-8"))
            invalid_event = next(row for row in invalid["records"] if row["key"] == "event.spirit_spring")
            invalid_event["status"] = "open"
            invalid_event["contribution"]["source_item_key"] = "item.missing"
            invalid["records"] = [
                invalid_event if row["key"] == "event.spirit_spring" else row for row in invalid["records"]
            ]
            event_path.write_text(json.dumps(invalid, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            invalid_clock = MutableClock(datetime(2026, 9, 24, 20, 5, tzinfo=timezone.utc))
            invalid_runtime = create_runtime(data_dir=data_dir, clock=invalid_clock, adapters=("onebot.v11",))
            try:
                await _create_player(invalid_runtime, onebot, "invalid-config-user", "invalid")
                rejected = await invalid_runtime.adapters.dispatch(
                    "onebot.v11", replace(onebot, user_id="invalid-config-user", operation_id="invalid-status"), "灵泉事件"
                )
                assert rejected.code == "PERSISTENCE_ERROR"
                with sqlite3.connect(invalid_runtime.settings.database_path) as connection:
                    assert connection.execute("SELECT COUNT(*) FROM world_event_rounds").fetchone()[0] == 1
                    assert connection.execute(
                        "SELECT stamina FROM players WHERE platform_user_id = ?", ("invalid-config-user",)
                    ).fetchone()[0] == 30
            finally:
                await invalid_runtime.close()

    asyncio.run(run())
