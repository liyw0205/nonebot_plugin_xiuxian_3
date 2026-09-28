from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory

import pytest

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime


class MutableClock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs: int) -> None:
        self.now += timedelta(**kwargs)


def _ctx(adapter: str, user: str, operation: str) -> CommandContext:
    return CommandContext(adapter=adapter, user_id=user, operation_id=operation)


async def _player(runtime, adapter: str, user: str, *, debt: int = 37) -> None:
    created = await runtime.adapters.dispatch(adapter, _ctx(adapter, user, f"{user}:create"), "开始修仙")
    assert created.code == "PLAYER_CREATED"
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE players SET realm_key='tribulation', realm_layer=1, tribulation_debt=?, stamina=7, stamina_max=100 "
            "WHERE platform=? AND platform_user_id=?",
            (debt, adapter, user),
        )


async def _finish_route(runtime, adapter: str, user: str, prefix: str):
    for index, node in enumerate(("天劫门槛", "回音长廊", "旁线之门")):
        selected = await runtime.adapters.dispatch(
            adapter, _ctx(adapter, user, f"{prefix}:node:{index}"), f"选择秘境节点 {node}"
        )
        assert selected.ok, selected
    settled = await runtime.adapters.dispatch(adapter, _ctx(adapter, user, f"{prefix}:settle"), "结算秘境")
    assert settled.code == "HEAVEN_ECHO_SETTLED", settled
    return settled


async def _complete(runtime, adapter: str, user: str, prefix: str):
    entered = await runtime.adapters.dispatch(adapter, _ctx(adapter, user, f"{prefix}:enter"), "进入秘境 天劫回音")
    assert entered.code == "HEAVEN_ECHO_ENTERED", entered
    return entered, await _finish_route(runtime, adapter, user, prefix)


@pytest.mark.parametrize("adapter", ["qq.official", "onebot.v11"])
def test_heaven_echo_route_is_idempotent_and_does_not_touch_endgame_resources(adapter: str) -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, adapters=(adapter,))
            user = f"heaven-echo-{adapter}"
            await _player(runtime, adapter, user)
            preview = await runtime.adapters.dispatch(adapter, _ctx(adapter, user, "preview"), "秘境预览")
            assert any(item["instance_key"] == "instance.secret_realm.heaven_echo" for item in preview.data["realms"])
            entered = await runtime.adapters.dispatch(adapter, _ctx(adapter, user, "entry"), "进入秘境 天劫回音")
            replay = await runtime.adapters.dispatch(adapter, _ctx(adapter, user, "entry"), "进入秘境 天劫回音")
            assert entered.ok and replay.data["idempotent_replay"] is True
            skipped = await runtime.adapters.dispatch(adapter, _ctx(adapter, user, "skip"), "选择秘境节点 回音长廊")
            assert skipped.code == "HEAVEN_ECHO_NODE_FORBIDDEN"
            first_node = await runtime.adapters.dispatch(adapter, _ctx(adapter, user, "route:node:0"), "选择秘境节点 天劫门槛")
            assert first_node.ok
            conflict = await runtime.adapters.dispatch(adapter, _ctx(adapter, user, "route:node:0"), "选择秘境节点 回音长廊")
            assert conflict.code == "OPERATION_CONFLICT"
            settled = await _finish_route(runtime, adapter, user, "route")
            assert settled.data["story_flag_written"] is True
            replay_settlement = await runtime.adapters.dispatch(adapter, _ctx(adapter, user, "route:settle"), "结算秘境")
            assert replay_settlement.data["idempotent_replay"] is True
            repeat_entry, repeat_clear = await _complete(runtime, adapter, user, "repeat")
            assert repeat_entry.data["first_clear"] is False
            assert repeat_clear.data["story_flag_written"] is False
            with sqlite3.connect(runtime.settings.database_path) as connection:
                debt, merit, fruit, stamina, intro_json = connection.execute(
                    "SELECT tribulation_debt, ascension_merit, dao_fruit_progress, stamina, intro_json "
                    "FROM players WHERE platform=? AND platform_user_id=?",
                    (adapter, user),
                ).fetchone()
            assert (debt, merit, fruit, stamina) == (37, 0, 0, 7)
            assert json.loads(intro_json)["flags"].count("story.heaven_echo") == 1
            await runtime.close()

    asyncio.run(run())


def test_heaven_echo_mixed_adapter_restart_expiry_and_system_compensation() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 28, 12, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            user = "heaven-echo-handoff"
            await _player(runtime, "qq.official", user, debt=63)
            entered = await runtime.adapters.dispatch("qq.official", _ctx("qq.official", user, "handoff:enter"), "进入秘境 天劫回音")
            assert entered.ok
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE players SET platform='onebot.v11' WHERE platform='qq.official' AND platform_user_id=?",
                    (user,),
                )
            await runtime.close()

            runtime = create_runtime(data_dir=data_dir, clock=clock)
            for index, node in enumerate(("天劫门槛", "回音长廊")):
                selected = await runtime.adapters.dispatch("onebot.v11", _ctx("onebot.v11", user, f"handoff:{index}"), f"选择秘境节点 {node}")
                assert selected.ok
            clock.advance(hours=1, seconds=1)
            expired = await runtime.adapters.dispatch("onebot.v11", _ctx("onebot.v11", user, "handoff:settle"), "结算秘境")
            assert expired.code == "HEAVEN_ECHO_SETTLED" and expired.data["outcome"] == "expired"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                debt, stamina, intro_json = connection.execute(
                    "SELECT tribulation_debt, stamina, intro_json FROM players WHERE platform='onebot.v11' AND platform_user_id=?",
                    (user,),
                ).fetchone()
            assert debt == 63 and stamina == 7 and "story.heaven_echo" not in json.loads(intro_json).get("flags", [])

            entered_again = await runtime.adapters.dispatch("onebot.v11", _ctx("onebot.v11", user, "handoff:again"), "进入秘境 天劫回音")
            assert entered_again.ok
            clock.advance(hours=1, seconds=1)
            expired_on_node = await runtime.adapters.dispatch("onebot.v11", _ctx("onebot.v11", user, "handoff:node-expire"), "选择秘境节点 天劫门槛")
            assert expired_on_node.code == "HEAVEN_ECHO_EXPIRED"
            settled_on_node_expiry = await runtime.adapters.dispatch("onebot.v11", _ctx("onebot.v11", user, "handoff:node-expire:settle"), "结算秘境")
            assert settled_on_node_expiry.code == "HEAVEN_ECHO_SETTLED"
            assert settled_on_node_expiry.data["outcome"] == "expired"

            user2 = "heaven-echo-compensation"
            await _player(runtime, "qq.official", user2, debt=11)
            entered2 = await runtime.adapters.dispatch("qq.official", _ctx("qq.official", user2, "comp:enter"), "进入秘境 天劫回音")
            compensated = await runtime.repository.compensate_heaven_echo_system_failure(run_id=entered2.data["run_id"], operation_id="comp:abort")
            replay = await runtime.repository.compensate_heaven_echo_system_failure(run_id=entered2.data["run_id"], operation_id="comp:abort")
            assert compensated.outcome == "system_aborted" and replay.already_completed is True
            with sqlite3.connect(runtime.settings.database_path) as connection:
                status, debt2, stamina2 = connection.execute(
                    "SELECT r.status, p.tribulation_debt, p.stamina FROM heaven_echo_runs r JOIN players p ON p.id=r.player_id WHERE r.run_id=?",
                    (entered2.data["run_id"],),
                ).fetchone()
            assert (status, debt2, stamina2) == ("system_aborted", 11, 7)
            await runtime.close()

    asyncio.run(run())


def test_heaven_echo_rejects_requirement_and_active_final_battle_atomically() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, adapters=("qq.official",))
            user = "heaven-echo-gates"
            created = await runtime.adapters.dispatch("qq.official", _ctx("qq.official", user, "create"), "开始修仙")
            assert created.ok
            denied = await runtime.adapters.dispatch("qq.official", _ctx("qq.official", user, "denied"), "进入秘境 天劫回音")
            assert denied.code == "HEAVEN_ECHO_REQUIREMENT_MISSING"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                player_id = connection.execute("SELECT id FROM players WHERE platform=? AND platform_user_id=?", ("qq.official", user)).fetchone()[0]
                assert connection.execute("SELECT COUNT(*) FROM heaven_echo_runs WHERE player_id=?", (player_id,)).fetchone()[0] == 0
                connection.execute("UPDATE players SET realm_key='tribulation', realm_layer=1 WHERE id=?", (player_id,))
                now = datetime.now(timezone.utc).isoformat()
                connection.execute(
                    "INSERT INTO final_battle_sessions(battle_id, initiator_id, create_operation_id, status, round_no, action_sequence, starts_at, expires_at, snapshot_json, state_json, result_json, content_version, rule_version, created_at, updated_at) "
                    "VALUES (?, ?, ?, 'lobby', 0, 0, ?, ?, '{}', '{}', '{}', 'test', 'test', ?, ?)",
                    ("heaven-echo-final", player_id, "heaven-echo-final:create", now, "2099-01-01T00:00:00+00:00", now, now),
                )
                connection.execute(
                    "INSERT INTO final_battle_members(battle_id, player_id, role, asset_lock_status, snapshot_json, created_at, updated_at) VALUES (?, ?, 'initiator', 'released', '{}', ?, ?)",
                    ("heaven-echo-final", player_id, now, now),
                )
            final_denied = await runtime.adapters.dispatch("qq.official", _ctx("qq.official", user, "final-denied"), "进入秘境 天劫回音")
            assert final_denied.code == "HEAVEN_ECHO_FINAL_BATTLE_ACTIVE"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute("UPDATE final_battle_sessions SET status='settled' WHERE battle_id='heaven-echo-final'")
                connection.execute("UPDATE players SET endgame_status='ascended' WHERE id=?", (player_id,))
            ended_denied = await runtime.adapters.dispatch("qq.official", _ctx("qq.official", user, "ended-denied"), "进入秘境 天劫回音")
            assert ended_denied.code == "HEAVEN_ECHO_REQUIREMENT_MISSING"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute("SELECT COUNT(*) FROM heaven_echo_runs WHERE player_id=?", (player_id,)).fetchone()[0] == 0
            await runtime.close()

    asyncio.run(run())
