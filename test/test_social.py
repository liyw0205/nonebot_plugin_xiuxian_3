from __future__ import annotations

import asyncio
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

    def advance(self, **kwargs: int) -> None:
        self.value += timedelta(**kwargs)


def _context(user: str, operation_id: str = "") -> CommandContext:
    return CommandContext(adapter="web", user_id=user, operation_id=operation_id)


async def _create_player(runtime, user: str) -> None:
    assert (await runtime.dispatch(_context(user), "开始修仙")).ok
    assert (await runtime.dispatch(_context(user), "寻仙问道")).ok


def _promote(runtime, users: tuple[str, ...], *, stones: int = 2_000) -> None:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        for user in users:
            connection.execute(
                "UPDATE players SET realm_key = 'foundation', realm_layer = 1, spirit_stones = ? WHERE platform_user_id = ?",
                (stones, user),
            )


def test_sect_creation_is_idempotent_and_requires_foundation() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            await _create_player(runtime, "founder")
            blocked = await runtime.dispatch(_context("founder", "create-blocked"), "创建宗门 天道院")
            assert blocked.code == "SECT_REQUIREMENT_MISSING"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute(
                    "SELECT spirit_stones FROM players WHERE platform_user_id = 'founder'"
                ).fetchone()[0] == 100
            _promote(runtime, ("founder",))
            created = await runtime.dispatch(_context("founder", "create-sect"), "创建宗门 天道院 守正求真")
            replay = await runtime.dispatch(_context("founder", "create-sect"), "创建宗门 天道院 守正求真")
            assert created.code == "SECT_CREATED"
            assert replay.data["idempotent_replay"] is True
            assert replay.data["sect_id"] == created.data["sect_id"]
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute(
                    "SELECT spirit_stones FROM players WHERE platform_user_id = 'founder'"
                ).fetchone()[0] == 1_000
                assert connection.execute("SELECT COUNT(*) FROM sects").fetchone()[0] == 1
            await runtime.close()

    asyncio.run(run())


def test_sect_application_review_leave_and_cooldown() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            for user in ("leader", "applicant", "other"):
                await _create_player(runtime, user)
            _promote(runtime, ("leader", "other"))
            created = await runtime.dispatch(_context("leader", "sect-create"), "创建宗门 青云门 求道问真")
            sect_id = created.data["sect_id"]
            submitted = await runtime.dispatch(_context("applicant", "sect-apply"), f"申请入宗 {sect_id} 寻求同道")
            replay = await runtime.dispatch(_context("applicant", "sect-apply"), f"申请入宗 {sect_id} 寻求同道")
            assert submitted.code == "SECT_APPLICATION_SUBMITTED"
            assert replay.data["idempotent_replay"] is True
            forbidden = await runtime.dispatch(_context("applicant"), "宗门申请列表")
            assert forbidden.code == "SECT_PERMISSION_DENIED"
            listing = await runtime.dispatch(_context("leader"), "宗门申请列表")
            assert listing.code == "SECT_APPLICATIONS"
            application_id = submitted.data["application_id"]
            reviewed = await runtime.dispatch(_context("leader", "sect-review"), f"审批入宗 {application_id} 同意")
            review_replay = await runtime.dispatch(_context("leader", "sect-review"), f"审批入宗 {application_id} 同意")
            assert reviewed.data["status"] == "accepted"
            assert review_replay.data["idempotent_replay"] is True
            profile = await runtime.dispatch(_context("applicant"), "我的宗门")
            assert profile.data["sect_id"] == sect_id
            left = await runtime.dispatch(_context("applicant", "sect-leave"), "离开宗门")
            assert left.code == "SECT_LEFT"
            blocked = await runtime.dispatch(_context("applicant", "sect-apply-after-leave"), f"申请入宗 {sect_id}")
            assert blocked.code == "SECT_JOIN_COOLDOWN"
            leader_leave = await runtime.dispatch(_context("leader", "leader-leave"), "离开宗门")
            assert leader_leave.code == "SECT_PERMISSION_DENIED"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute(
                    "SELECT status FROM sect_members WHERE sect_id = ? AND player_id = (SELECT id FROM players WHERE platform_user_id = 'applicant') ORDER BY id DESC LIMIT 1",
                    (sect_id,),
                ).fetchone()[0] == "left"
            clock.advance(hours=24)
            reopened = await runtime.dispatch(_context("applicant", "sect-apply-after-cooldown"), f"申请入宗 {sect_id}")
            assert reopened.code == "SECT_APPLICATION_SUBMITTED"
            await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("kind", ["onebot", "qq"])
def test_real_adapters_reach_sect_slice(kind: str) -> None:
    pytest.importorskip("nonebot")
    from nonebot_plugin_xiuxian_3.adapters.onebot import normalize_event
    from nonebot_plugin_xiuxian_3.adapters.qq import normalize_event as normalize_qq_event

    def onebot_event(content: str, message_id: int, user_id: int):
        from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message
        from nonebot.adapters.onebot.v11.event import Sender

        return GroupMessageEvent(
            time=1_735_689_600,
            self_id=9001,
            post_type="message",
            sub_type="normal",
            user_id=user_id,
            message_type="group",
            message_id=message_id,
            message=Message(content),
            original_message=Message(content),
            raw_message=content,
            font=0,
            sender=Sender(user_id=user_id, nickname="道友"),
            group_id=2002,
        )

    def qq_event(content: str, message_id: int, user_id: str):
        from nonebot.adapters.qq.event import GroupMessageCreateEvent
        from nonebot.adapters.qq.models.qq import GroupMemberAuthor

        return GroupMessageCreateEvent(
            id=str(message_id),
            content=content,
            timestamp="2026-01-01T00:00:00+00:00",
            author=GroupMemberAuthor(id="raw", bot=False, member_openid=user_id, username="道友"),
            group_id="raw-group",
            group_openid="group-openid",
        )

    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)

            def normalize(content: str, message_id: int, user_id):
                raw = onebot_event(content, message_id, int(user_id)) if kind == "onebot" else qq_event(content, message_id, str(user_id))
                return normalize_event(raw) if kind == "onebot" else normalize_qq_event(raw)

            async def dispatch(content: str, message_id: int, user_id):
                normalized = normalize(content, message_id, user_id)
                return await runtime.dispatch(normalized.context, normalized.text)

            platform = "onebot.v11" if kind == "onebot" else "qq.official"
            adapter_user = 7001 if kind == "onebot" else "qq-sect-user"
            assert (await dispatch("开始修仙", 9000, adapter_user)).ok
            assert (await dispatch("寻仙问道", 9001, adapter_user)).ok
            uid = str(adapter_user)
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute("UPDATE players SET realm_key = 'foundation', realm_layer = 1, spirit_stones = 2000 WHERE platform = ? AND platform_user_id = ?", (platform, uid))
            created = await dispatch("创建宗门 归元阁", 9002, adapter_user)
            assert created.code == "SECT_CREATED"
            profile = await dispatch("我的宗门", 9003, adapter_user)
            assert profile.code == "SECT_PROFILE"
            assert profile.data["sect_id"] == created.data["sect_id"]
            await runtime.close()

    asyncio.run(run())
