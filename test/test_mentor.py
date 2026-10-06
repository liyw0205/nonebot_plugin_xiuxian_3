from __future__ import annotations

import asyncio
import json
import shutil
import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pytest

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.social.mentor_repository import MentorRepositoryMixin
from nonebot_plugin_xiuxian_3.xiuxian.utils.player import player_integer


ROOT = Path(__file__).parents[1]


class MutableClock:
    def __init__(self, value: datetime):
        self.value = value

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **kwargs: int) -> None:
        self.value += timedelta(**kwargs)


def _context(user: str, operation_id: str = "") -> CommandContext:
    return CommandContext(adapter="web", user_id=user, operation_id=operation_id)


def _adapter_context(adapter: str, user: str, request_id: str, operation_id: str = "") -> CommandContext:
    return CommandContext(
        adapter=adapter,
        user_id=user,
        request_id=request_id,
        operation_id=operation_id,
        can_write_assets=True,
    )


def _set_new_town_reputation_cap(data_dir: Path, maximum: int) -> None:
    path = data_dir / "地图" / "地点.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    location = next(row for row in document["records"] if row["key"] == "xuantian.new_town")
    location["local_reputation_maximum"] = maximum
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


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

            with patch(
                "nonebot_plugin_xiuxian_3.xiuxian.social.mentor_repository.player_integer",
                wraps=player_integer,
            ) as shared_integer:
                invited = await runtime.dispatch(_context("master", "mentor-invite"), "邀请拜师 apprentice")
            assert any(call.args[1] == "realm_layer" for call in shared_integer.call_args_list)
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
            assert graduated.data["apprentice_service_reputation_gain"] == 2
            assert graduated.data["master_service_reputation_gain"] == 2

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


@pytest.mark.parametrize("adapter", ("qq.official", "onebot.v11"))
def test_mentor_graduation_uses_shared_reputation_transaction_and_recovers(adapter: str) -> None:
    async def run() -> None:
        with TemporaryDirectory() as temp:
            data_dir = Path(temp) / "data"
            shutil.copytree(ROOT / "data", data_dir)
            _set_new_town_reputation_cap(data_dir, 997)
            runtime = create_runtime(data_dir=data_dir, adapters=(adapter,))
            master = f"mentor-master-{adapter}"
            apprentice = f"mentor-apprentice-{adapter}"
            try:
                for user in (master, apprentice):
                    assert (await runtime.adapters.dispatch(
                        adapter, _adapter_context(adapter, user, f"{user}-create"), "开始修仙"
                    )).code == "PLAYER_CREATED"
                    assert (await runtime.adapters.dispatch(
                        adapter, _adapter_context(adapter, user, f"{user}-seek"), "寻仙问道"
                    )).code == "SEEKING_STARTED"

                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE players SET realm_key='foundation', realm_layer=4 WHERE platform=? AND platform_user_id=?",
                        (adapter, master),
                    )
                invited = await runtime.adapters.dispatch(
                    adapter,
                    _adapter_context(adapter, master, f"{master}-invite", f"{master}-invite-op"),
                    f"邀请拜师 {adapter}:{apprentice}",
                )
                relation_id = invited.data["relation_id"]
                accepted = await runtime.adapters.dispatch(
                    adapter,
                    _adapter_context(adapter, apprentice, f"{apprentice}-accept", f"{apprentice}-accept-op"),
                    f"接受拜师 {relation_id}",
                )
                assert accepted.code == "MENTOR_ACCEPTED"

                with sqlite3.connect(runtime.settings.database_path) as connection:
                    apprentice_id = connection.execute(
                        "SELECT id FROM players WHERE platform=? AND platform_user_id=?",
                        (adapter, apprentice),
                    ).fetchone()[0]
                    connection.execute(
                        "UPDATE players SET stage='cultivator', realm_key='qi_gathering', realm_layer=3 WHERE id=?",
                        (apprentice_id,),
                    )
                    connection.execute(
                        "INSERT INTO production_orders(order_id, player_id, operation_id, recipe_key, status, "
                        "starts_at, ends_at, energy_cost, currency_cost, snapshot_json, result_json, created_at, updated_at) "
                        "VALUES (?, ?, ?, 'recipe.pill.healing_low', 'completed', ?, ?, 0, 0, '{}', '{}', ?, ?)",
                        (
                            f"{adapter}-mentor-production",
                            apprentice_id,
                            f"{adapter}-mentor-production-op",
                            "2026-09-23T00:00:00+00:00",
                            "2026-09-23T00:01:00+00:00",
                            "2026-09-23T00:00:00+00:00",
                            "2026-09-23T00:01:00+00:00",
                        ),
                    )
                    master_id = connection.execute(
                        "SELECT id FROM players WHERE platform=? AND platform_user_id=?",
                        (adapter, master),
                    ).fetchone()[0]
                    for player_id, local_json, service in (
                        (apprentice_id, "{", 99),
                        (master_id, "{}", 100),
                    ):
                        connection.execute(
                            "INSERT INTO player_reputations(player_id, local_json, service_reputation, updated_at) "
                            "VALUES (?, ?, ?, '2026-09-23T00:00:00+00:00')",
                            (player_id, local_json, service),
                        )

                operation_id = f"{adapter}-mentor-graduate-op"
                before_invalid = _mentor_graduation_state(runtime, adapter, master, apprentice, relation_id, operation_id)
                invalid = await runtime.adapters.dispatch(
                    adapter,
                    _adapter_context(adapter, master, f"{master}-invalid-graduate", operation_id),
                    f"师徒毕业 {relation_id}",
                )
                assert invalid.code == "PERSISTENCE_ERROR"
                assert _mentor_graduation_state(
                    runtime, adapter, master, apprentice, relation_id, operation_id
                ) == before_invalid

                with sqlite3.connect(runtime.settings.database_path) as connection:
                    connection.execute(
                        "UPDATE player_reputations SET local_json=? WHERE player_id=?",
                        ('{"local.xuantian.new_town": 995}', apprentice_id),
                    )
                before_failure = _mentor_graduation_state(runtime, adapter, master, apprentice, relation_id, operation_id)
                with patch.object(
                    MentorRepositoryMixin,
                    "_mentor_record_operation",
                    side_effect=RuntimeError("injected failure after reputation writes"),
                ):
                    failed = await runtime.adapters.dispatch(
                        adapter,
                        _adapter_context(adapter, master, f"{master}-failed-graduate", operation_id),
                        f"师徒毕业 {relation_id}",
                    )
                assert failed.code == "PERSISTENCE_ERROR"
                assert _mentor_graduation_state(
                    runtime, adapter, master, apprentice, relation_id, operation_id
                ) == before_failure

                graduated = await runtime.adapters.dispatch(
                    adapter,
                    _adapter_context(adapter, master, f"{master}-graduate", operation_id),
                    f"师徒毕业 {relation_id}",
                )
                assert graduated.code == "MENTOR_GRADUATED"
                assert graduated.data["apprentice_local_reputation"] == 2
                assert graduated.data["apprentice_service_reputation_gain"] == 1
                assert graduated.data["master_service_reputation_gain"] == 0
                assert "徒弟地方名望**：+2" in graduated.message
                assert "徒弟服务信誉**：+1" in graduated.message
                assert "师傅服务信誉**" not in graduated.message
                settled_state = _mentor_graduation_state(
                    runtime, adapter, master, apprentice, relation_id, operation_id
                )
                assert settled_state[1] == (apprentice, '{"local.xuantian.new_town": 997}', 100)
                assert settled_state[2] == (master, "{}", 100)
                assert settled_state[3]["apprentice_local_reputation"] == 2
                assert settled_state[3]["apprentice_service_reputation_gain"] == 1
                assert settled_state[3]["master_service_reputation_gain"] == 0
                await runtime.close()
            finally:
                if not runtime._closed:
                    await runtime.close()

            _set_new_town_reputation_cap(data_dir, 996)
            recovered = create_runtime(data_dir=data_dir, adapters=(adapter,))
            try:
                replay = await recovered.adapters.dispatch(
                    adapter,
                    _adapter_context(adapter, master, f"{master}-graduate-replay", operation_id),
                    f"师徒毕业 {relation_id}",
                )
                assert replay.code == "MENTOR_GRADUATED"
                assert replay.data["idempotent_replay"] is True
                assert replay.data["apprentice_local_reputation"] == 2
                assert replay.data["apprentice_service_reputation_gain"] == 1
                assert replay.data["master_service_reputation_gain"] == 0
                assert _mentor_graduation_state(
                    recovered, adapter, master, apprentice, relation_id, operation_id
                ) == settled_state
            finally:
                await recovered.close()

    asyncio.run(run())


def _mentor_graduation_state(runtime, adapter: str, master: str, apprentice: str, relation_id: str, operation_id: str):
    with sqlite3.connect(runtime.settings.database_path) as connection:
        relation = connection.execute(
            "SELECT status, master_contribution, graduate_operation_id FROM mentor_relations WHERE relation_id=?",
            (relation_id,),
        ).fetchone()
        reputations = connection.execute(
            "SELECT platform_user_id, local_json, service_reputation FROM players "
            "LEFT JOIN player_reputations ON players.id=player_reputations.player_id "
            "WHERE platform=? AND platform_user_id IN (?, ?) "
            "ORDER BY CASE platform_user_id WHEN ? THEN 0 ELSE 1 END",
            (adapter, master, apprentice, apprentice),
        ).fetchall()
        operation = connection.execute(
            "SELECT result_json FROM operations WHERE operation_id=?", (operation_id,)
        ).fetchone()
    return (
        relation,
        (reputations[0][0], reputations[0][1] or "{}", reputations[0][2] or 0),
        (reputations[1][0], reputations[1][1] or "{}", reputations[1][2] or 0),
        json.loads(operation[0]) if operation is not None else None,
    )


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
            author=GroupMemberAuthor(id="raw", bot=False, member_openid=user_id, member_role="member", username="道友"),
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
