from __future__ import annotations

import asyncio
import json
import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta, timezone
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


def _adapter_contexts() -> tuple[CommandContext, CommandContext]:
    from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message
    from nonebot.adapters.onebot.v11.event import Sender
    from nonebot.adapters.qq.event import GroupMessageCreateEvent
    from nonebot.adapters.qq.models.qq import GroupMemberAuthor

    qq = normalize_qq_event(
        GroupMessageCreateEvent(
            id="arena-qq-message",
            content="挑战竞技场",
            timestamp="2026-09-25T00:00:00+00:00",
            author=GroupMemberAuthor(
                id="qq-raw", bot=False, member_openid="arena-qq-user", username="QQ道友"
            ),
            group_id="qq-raw-group",
            group_openid="arena-qq-group",
        )
    ).context
    onebot = normalize_onebot_event(
        GroupMessageEvent(
            time=1_758_758_400,
            self_id=9001,
            post_type="message",
            sub_type="normal",
            user_id=2002,
            message_type="group",
            message_id=9003,
            message=Message("发布竞技场快照"),
            original_message=Message("发布竞技场快照"),
            raw_message="发布竞技场快照",
            font=0,
            sender=Sender(user_id=2002, nickname="OneBot道友"),
            group_id=3001,
        )
    ).context
    return qq, onebot


async def _cultivator(runtime, context: CommandContext, prefix: str) -> None:
    commands = (
        "开始修仙",
        "寻仙问道",
        "完成引导 阅读",
        "前往近郊",
        "完成引导 采集",
        "完成引导 炼丹",
        "选择道途 体修",
    )
    for index, command in enumerate(commands):
        result = await runtime.adapters.dispatch(
            context.adapter,
            replace(context, operation_id=f"{prefix}-{index}"),
            command,
        )
        assert result.ok, (command, result.code, result.message)


def test_arena_async_snapshot_flow_across_qq_and_onebot() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 25, tzinfo=timezone.utc))
        qq, onebot = _adapter_contexts()
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            qq = replace(qq, user_id="arena-qq-private")
            onebot = replace(onebot, user_id="arena-onebot-private")
            await _cultivator(runtime, qq, "qq")
            await _cultivator(runtime, onebot, "ob")

            published = await runtime.adapters.dispatch(
                onebot.adapter, replace(onebot, operation_id="ob-publish"), "发布竞技场快照"
            )
            assert published.code == "ARENA_SNAPSHOT_PUBLISHED"
            snapshot_id = published.data["snapshot_id"]
            before = await runtime.adapters.dispatch(
                qq.adapter, replace(qq, operation_id="qq-before"), "挑战竞技场"
            )
            assert before.code == "ARENA_OPPONENT_UNAVAILABLE"

            clock.advance(minutes=31)
            listed = await runtime.adapters.dispatch(
                qq.adapter, replace(qq, operation_id="qq-list"), "竞技场列表"
            )
            assert listed.code == "ARENA_SNAPSHOT_LIST"
            assert listed.data["snapshots"][0]["snapshot_id"] == snapshot_id
            challenged = await runtime.adapters.dispatch(
                qq.adapter,
                replace(qq, operation_id="qq-challenge-1"),
                f"挑战竞技场 {snapshot_id}",
            )
            assert challenged.code == "ARENA_MATCH_SETTLED"
            assert challenged.data["rounds"] <= 15
            match_id = challenged.data["match_id"]
            replayed = await runtime.adapters.dispatch(
                qq.adapter,
                replace(qq, operation_id="qq-challenge-1"),
                f"挑战竞技场 {snapshot_id}",
            )
            assert replayed.data["idempotent_replay"] is True
            assert replayed.data["match_id"] == match_id

            replay = await runtime.adapters.dispatch(
                onebot.adapter,
                replace(onebot, operation_id="ob-replay"),
                f"竞技场回放 {match_id}",
            )
            assert replay.code == "ARENA_REPLAY"
            assert replay.data["actions"]
            public = json.dumps(listed.data, ensure_ascii=False)
            assert "arena-onebot-private" not in public
            assert "arena-qq-private" not in public

            claim = await runtime.adapters.dispatch(
                qq.adapter,
                replace(qq, operation_id="qq-claim"),
                f"领取竞技场结果 {match_id}",
            )
            assert claim.code == "ARENA_RESULT_ACKNOWLEDGED"
            assert (
                await runtime.adapters.dispatch(
                    qq.adapter,
                    replace(qq, operation_id="qq-claim"),
                    f"领取竞技场结果 {match_id}",
                )
            ).data["idempotent_replay"] is True
            with sqlite3.connect(runtime.settings.database_path) as connection:
                players = {
                    row[0]: row[1:]
                    for row in connection.execute(
                        "SELECT platform_user_id, spirit_stones, total_cultivation, arena_rating FROM players"
                    )
                }
                assert players["arena-qq-private"][:2] == (300, 0)
                assert players["arena-qq-private"][2] in {990, 1025}
                assert connection.execute("SELECT COUNT(*) FROM battle_sessions").fetchone()[0] == 0
            await runtime.close()

    asyncio.run(run())


def test_arena_snapshot_antifarm_cap_and_revoke() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 25, tzinfo=timezone.utc))
        qq, onebot = _adapter_contexts()
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            qq = replace(qq, user_id="arena-cap-qq")
            onebot = replace(onebot, user_id="arena-cap-ob")
            await _cultivator(runtime, qq, "cap-qq")
            await _cultivator(runtime, onebot, "cap-ob")
            published = await runtime.adapters.dispatch(
                onebot.adapter, replace(onebot, operation_id="cap-publish"), "发布竞技场快照"
            )
            snapshot_id = published.data["snapshot_id"]
            clock.advance(minutes=31)
            results = []
            for index in range(5):
                results.append(
                    await runtime.adapters.dispatch(
                        qq.adapter,
                        replace(qq, operation_id=f"cap-challenge-{index}"),
                        f"挑战竞技场 {snapshot_id}",
                    )
                )
            assert all(result.code == "ARENA_MATCH_SETTLED" for result in results)
            assert results[2].data["score_counted"] is False
            sixth = await runtime.adapters.dispatch(
                qq.adapter,
                replace(qq, operation_id="cap-challenge-6"),
                f"挑战竞技场 {snapshot_id}",
            )
            assert sixth.code == "ARENA_DAILY_CAP"
            revoked = await runtime.adapters.dispatch(
                onebot.adapter,
                replace(onebot, operation_id="cap-revoke"),
                f"撤销竞技场快照 {snapshot_id}",
            )
            assert revoked.code == "ARENA_SNAPSHOT_REVOKED"
            clock.advance(days=1)
            unavailable = await runtime.adapters.dispatch(
                qq.adapter,
                replace(qq, operation_id="cap-after-revoke"),
                f"挑战竞技场 {snapshot_id}",
            )
            assert unavailable.code == "ARENA_SNAPSHOT_EXPIRED"
            await runtime.close()

    asyncio.run(run())
