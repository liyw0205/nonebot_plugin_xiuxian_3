from __future__ import annotations

import asyncio
import sqlite3
from dataclasses import replace
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
    assert (await runtime.dispatch(_context(user, f"{user}-create"), "开始修仙")).ok
    assert (await runtime.dispatch(_context(user, f"{user}-seek"), "寻仙问道")).ok


def _set_realm(runtime, user: str, realm: str, layer: int, *, stage: str | None = None) -> None:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        if stage is None:
            connection.execute(
                "UPDATE players SET realm_key = ?, realm_layer = ? WHERE platform_user_id = ?",
                (realm, layer, user),
            )
        else:
            connection.execute(
                "UPDATE players SET stage = ?, realm_key = ?, realm_layer = ? WHERE platform_user_id = ?",
                (stage, realm, layer, user),
            )


def test_mentor_invite_accept_reject_and_expiry() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 23, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            for user in ("master", "apprentice", "other"):
                await _create_player(runtime, user)
            _set_realm(runtime, "master", "foundation", 4)

            invited = await runtime.dispatch(_context("master", "mentor-invite"), "邀请拜师 apprentice")
            assert invited.code == "MENTOR_INVITED"
            replay = await runtime.dispatch(_context("master", "mentor-invite"), "邀请拜师 apprentice")
            assert replay.data["idempotent_replay"] is True
            accepted = await runtime.dispatch(
                _context("apprentice", "mentor-accept"), f"接受拜师 {invited.data['relation_id']}"
            )
            assert accepted.code == "MENTOR_ACCEPTED"
            assert accepted.data["status"] == "active"

            rejected = await runtime.dispatch(_context("master", "mentor-invite-reject"), "邀请拜师 other")
            assert rejected.code == "MENTOR_INVITED"
            refused = await runtime.dispatch(
                _context("other", "mentor-reject"), f"拒绝拜师 {rejected.data['relation_id']}"
            )
            assert refused.code == "MENTOR_REJECTED"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute(
                    "SELECT status FROM mentor_relations WHERE relation_id = ?",
                    (rejected.data["relation_id"],),
                ).fetchone()[0] == "rejected"

            clock.advance(hours=25)
            expired = await runtime.dispatch(_context("master", "mentor-expire"), "邀请拜师 other")
            assert expired.code == "MENTOR_INVITED"
            clock.advance(hours=25)
            late = await runtime.dispatch(
                _context("other", "mentor-late"), f"接受拜师 {expired.data['relation_id']}"
            )
            assert late.code == "MENTOR_INVITATION_EXPIRED"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute(
                    "SELECT status FROM mentor_relations WHERE relation_id = ?",
                    (expired.data["relation_id"],),
                ).fetchone()[0] == "expired"
            await runtime.close()

    asyncio.run(run())


def test_higher_realm_player_can_invite_apprentice() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            await _create_player(runtime, "master")
            await _create_player(runtime, "apprentice")
            _set_realm(runtime, "master", "dao_union", 10)

            invited = await runtime.dispatch(
                _context("master", "high-realm-mentor-invite"), "邀请拜师 apprentice"
            )
            assert invited.code == "MENTOR_INVITED"
            accepted = await runtime.dispatch(
                _context("apprentice", "high-realm-mentor-accept"),
                f"接受拜师 {invited.data['relation_id']}",
            )
            assert accepted.code == "MENTOR_ACCEPTED"
            await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize(
    ("realm", "layer", "expected"),
    (
        ("foundation", 3, False),
        ("foundation", 4, True),
        ("golden_core", 1, True),
        ("dao_union", 10, True),
        ("unknown", 10, False),
        ("dao_union", 0, False),
    ),
)
def test_master_eligibility_uses_foundation_l4_as_minimum(
    realm: str, layer: int, expected: bool
) -> None:
    from nonebot_plugin_xiuxian_3.xiuxian.social.mentor_rules import is_master_eligible

    assert is_master_eligible(realm, layer) is expected


def test_mentor_graduation_requires_progress_and_rewards_once() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            await _create_player(runtime, "master")
            await _create_player(runtime, "apprentice")
            _set_realm(runtime, "master", "foundation", 4)
            invited = await runtime.dispatch(_context("master", "mentor-invite"), "邀请拜师 apprentice")
            relation_id = invited.data["relation_id"]
            assert (await runtime.dispatch(_context("apprentice", "mentor-accept"), f"接受拜师 {relation_id}")).ok

            not_ready = await runtime.dispatch(_context("master", "mentor-graduate-early"), f"师徒毕业 {relation_id}")
            assert not_ready.code == "MENTOR_GRADUATION_NOT_READY"

            _set_realm(runtime, "apprentice", "qi_gathering", 3, stage="cultivator")
            with sqlite3.connect(runtime.settings.database_path) as connection:
                apprentice_id = connection.execute(
                    "SELECT id FROM players WHERE platform_user_id = 'apprentice'"
                ).fetchone()[0]
                connection.execute(
                    """
                    INSERT INTO production_orders(
                        order_id, player_id, operation_id, recipe_key, status,
                        starts_at, ends_at, energy_cost, currency_cost,
                        snapshot_json, result_json, created_at, updated_at
                    ) VALUES ('mentor-production', ?, 'mentor-production-op', 'recipe.pill.healing_low',
                              'completed', '2026-09-23T00:00:00+00:00', '2026-09-23T00:01:00+00:00',
                              0, 0, '{}', '{}', '2026-09-23T00:00:00+00:00', '2026-09-23T00:01:00+00:00')
                    """,
                    (apprentice_id,),
                )
            graduated = await runtime.dispatch(_context("master", "mentor-graduate"), f"师徒毕业 {relation_id}")
            assert graduated.code == "MENTOR_GRADUATED"
            assert graduated.data["apprentice_local_reputation"] == 10
            assert graduated.data["master_contribution"] == 20
            assert graduated.data["service_reputation_delta"] == 2

            replay = await runtime.dispatch(_context("master", "mentor-graduate"), f"师徒毕业 {relation_id}")
            assert replay.code == "MENTOR_GRADUATED"
            assert replay.data["idempotent_replay"] is True
            second_operation = await runtime.dispatch(
                _context("master", "mentor-graduate-again"), f"师徒毕业 {relation_id}"
            )
            assert second_operation.code == "MENTOR_STATE_CONFLICT"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                master_id = connection.execute(
                    "SELECT id FROM players WHERE platform_user_id = 'master'"
                ).fetchone()[0]
                apprentice_id = connection.execute(
                    "SELECT id FROM players WHERE platform_user_id = 'apprentice'"
                ).fetchone()[0]
                master_rep = connection.execute(
                    "SELECT service_reputation FROM player_reputations WHERE player_id = ?", (master_id,)
                ).fetchone()[0]
                apprentice_rep = connection.execute(
                    "SELECT local_json, service_reputation FROM player_reputations WHERE player_id = ?", (apprentice_id,)
                ).fetchone()
                assert master_rep == 2
                assert '"local.xuantian.new_town": 10' in apprentice_rep[0]
                assert apprentice_rep[1] == 2
            await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize("kind", ["onebot", "qq"])
def test_real_adapters_reach_mentor_slice(kind: str) -> None:
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

    def qq_event(content: str, message_id: str, user_id: str):
        from nonebot.adapters.qq.event import GroupMessageCreateEvent
        from nonebot.adapters.qq.models.qq import GroupMemberAuthor

        return GroupMessageCreateEvent(
            id=message_id,
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
                raw = (
                    onebot_event(content, message_id, int(user_id))
                    if kind == "onebot"
                    else qq_event(content, str(message_id), str(user_id))
                )
                return normalize_event(raw) if kind == "onebot" else normalize_qq_event(raw)

            async def dispatch(content: str, message_id: int, user_id):
                normalized = normalize(content, message_id, user_id)
                return await runtime.dispatch(normalized.context, normalized.text)

            platform = "onebot.v11" if kind == "onebot" else "qq.official"
            master_user = 7101 if kind == "onebot" else "qq-mentor-master"
            apprentice_user = 7102 if kind == "onebot" else "qq-mentor-apprentice"
            assert (await dispatch("开始修仙", 100, master_user)).code == "PLAYER_CREATED"
            assert (await dispatch("寻仙问道", 101, master_user)).code == "SEEKING_STARTED"
            assert (await dispatch("开始修仙", 200, apprentice_user)).code == "PLAYER_CREATED"
            assert (await dispatch("寻仙问道", 201, apprentice_user)).code == "SEEKING_STARTED"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE players SET realm_key = 'foundation', realm_layer = 4 WHERE platform = ? AND platform_user_id = ?",
                    (platform, str(master_user)),
                )
            invitation = await dispatch(f"邀请拜师 {platform}:{apprentice_user}", 102, master_user)
            assert invitation.code == "MENTOR_INVITED"
            accepted = await dispatch(f"接受拜师 {invitation.data['relation_id']}", 202, apprentice_user)
            assert accepted.code == "MENTOR_ACCEPTED"
            await runtime.close()

    asyncio.run(run())
