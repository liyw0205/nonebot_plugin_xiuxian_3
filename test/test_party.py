from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime


class MutableClock:
    def __init__(self, value: datetime):
        self.value = value

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **kwargs: int) -> None:
        self.value += timedelta(**kwargs)


def _ctx(adapter: str, user: str, operation: str = "") -> CommandContext:
    return CommandContext(adapter=adapter, user_id=user, operation_id=operation)


async def _create_player(runtime, adapter: str, user: str) -> None:
    assert (await runtime.dispatch(_ctx(adapter, user), "开始修仙")).code == "PLAYER_CREATED"
    assert (await runtime.dispatch(_ctx(adapter, user), "寻仙问道")).code == "SEEKING_STARTED"


def test_qq_and_onebot_party_confirmation_is_idempotent() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            for adapter, leader, member in (
                ("qq.official", "qq-party-leader", "qq-party-member"),
                ("onebot.v11", "onebot-party-leader", "onebot-party-member"),
            ):
                await _create_player(runtime, adapter, leader)
                await _create_player(runtime, adapter, member)
                created = await runtime.dispatch(_ctx(adapter, leader, "party-create" + adapter), "创建探索队伍")
                assert created.code == "PARTY_CREATED"
                replay = await runtime.dispatch(_ctx(adapter, leader, "party-create" + adapter), "创建双人队伍")
                assert replay.code == "PARTY_CREATED"
                assert replay.data["party_id"] == created.data["party_id"]
                party_id = created.data["party_id"]
                invited = await runtime.dispatch(_ctx(adapter, leader, "party-invite" + adapter), f"邀请入队 {member}")
                assert invited.code == "PARTY_INVITED"
                accepted = await runtime.dispatch(_ctx(adapter, member, "party-accept" + adapter), f"同意入队 {party_id}")
                assert accepted.code == "PARTY_JOINED"
                confirmed = await runtime.dispatch(_ctx(adapter, member, "party-confirm" + adapter), f"队伍确认 {party_id}")
                assert confirmed.code == "PARTY_READY"
                confirm_replay = await runtime.dispatch(_ctx(adapter, member, "party-confirm" + adapter), f"确认入队 {party_id}")
                assert confirm_replay.code == "PARTY_READY"
                assert confirm_replay.data["idempotent_replay"] is True
                profile = await runtime.dispatch(_ctx(adapter, leader), "队伍状态")
                assert profile.code == "PARTY_PROFILE"
                assert profile.data["ready"] is True
                assert {item["status"] for item in profile.data["members"]} == {"active"}
            await runtime.close()

    asyncio.run(run())


def test_party_requires_same_location_and_leader_leave_transfers_leadership() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            adapter, leader, member = "qq.official", "party-location-leader", "party-location-member"
            await _create_player(runtime, adapter, leader)
            await _create_player(runtime, adapter, member)
            created = await runtime.dispatch(_ctx(adapter, leader, "party-location-create"), "创建双人队伍")
            party_id = created.data["party_id"]
            with sqlite3.connect(runtime.settings.database_path) as db:
                db.execute(
                    "UPDATE players SET location_key = 'xuantian.suburb' WHERE platform = ? AND platform_user_id = ?",
                    (adapter, member),
                )
            mismatch = await runtime.dispatch(_ctx(adapter, leader, "party-location-invite"), f"邀请入队 {member}")
            assert mismatch.code == "PARTY_LOCATION_MISMATCH"
            with sqlite3.connect(runtime.settings.database_path) as db:
                assert db.execute("SELECT COUNT(*) FROM party_members WHERE party_id = ?", (party_id,)).fetchone()[0] == 1
                db.execute(
                    "UPDATE players SET location_key = 'xuantian.new_town' WHERE platform = ? AND platform_user_id = ?",
                    (adapter, member),
                )
            assert (await runtime.dispatch(_ctx(adapter, leader, "party-location-invite-ok"), f"邀请入队 {member}")).ok
            assert (await runtime.dispatch(_ctx(adapter, member, "party-location-accept"), f"接受入队 {party_id}")).ok
            left = await runtime.dispatch(_ctx(adapter, leader, "party-location-leave"), "退出队伍")
            assert left.code == "PARTY_LEFT"
            assert left.data["leader_player_id"] == (await runtime.repository.get_party(platform=adapter, platform_user_id=member)).leader_player_id
            assert left.data["status"] == "forming"
            member_left = await runtime.dispatch(_ctx(adapter, member, "party-member-leave"), "离开队伍")
            assert member_left.code == "PARTY_LEFT"
            assert member_left.data["status"] == "disbanded"
            await runtime.close()

    asyncio.run(run())


def test_party_invitation_rejection_and_confirmation_expiry() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 23, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            adapter, leader, member = "onebot.v11", "party-expire-leader", "party-expire-member"
            await _create_player(runtime, adapter, leader)
            await _create_player(runtime, adapter, member)
            created = await runtime.dispatch(_ctx(adapter, leader, "party-expire-create"), "创建双人队伍")
            party_id = created.data["party_id"]
            await runtime.dispatch(_ctx(adapter, leader, "party-expire-invite"), f"邀请入队 {member}")
            rejected = await runtime.dispatch(_ctx(adapter, member, "party-reject"), f"拒绝入队 {party_id}")
            assert rejected.code == "PARTY_INVITATION_REJECTED"
            missing = await runtime.dispatch(_ctx(adapter, member, "party-reject-again"), f"拒绝入队 {party_id}")
            assert missing.code == "PARTY_INVITATION_NOT_FOUND"

            second = await runtime.dispatch(_ctx(adapter, leader, "party-expire-create-2"), "退出队伍")
            assert second.code == "PARTY_LEFT"
            created_again = await runtime.dispatch(_ctx(adapter, leader, "party-expire-create-3"), "创建双人队伍")
            party_id = created_again.data["party_id"]
            await runtime.dispatch(_ctx(adapter, leader, "party-expire-invite-2"), f"邀请入队 {member}")
            clock.advance(minutes=6)
            expired = await runtime.dispatch(_ctx(adapter, member, "party-expire-accept"), f"接受入队 {party_id}")
            assert expired.code == "PARTY_CONFIRMATION_EXPIRED"
            with sqlite3.connect(runtime.settings.database_path) as db:
                assert db.execute("SELECT status FROM parties WHERE party_id = ?", (party_id,)).fetchone()[0] == "expired"
                assert db.execute("SELECT status FROM party_members WHERE party_id = ? AND player_id = (SELECT id FROM players WHERE platform_user_id = ?)", (party_id, member)).fetchone()[0] == "expired"
            await runtime.close()

    asyncio.run(run())
