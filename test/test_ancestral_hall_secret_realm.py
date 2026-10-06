from __future__ import annotations

import asyncio
import json
import sqlite3
from combat_fixtures import equip_damage_weapon
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


async def _player(
    runtime, adapter: str, user: str, *, damage: int = 10_000, max_hp: int = 500_000,
    realm: str = "soul_transformation", location: str = "beast.ancestral_lake",
    reputation: int = 3000, stability: int = 50, initiative: int = 9999,
) -> None:
    assert (await runtime.adapters.dispatch(adapter, _ctx(adapter, user, f"{user}:create"), "开始修仙")).ok
    assert (await runtime.adapters.dispatch(adapter, _ctx(adapter, user, f"{user}:seek"), "寻仙问道")).ok
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE players SET realm_key=?, realm_layer=1, location_key=?, stamina=100, stamina_max=100, "
            "max_hp=?, initiative=?, faction_reputation_json=?, bloodline_stability=? "
            "WHERE platform=? AND platform_user_id=?",
            (
                realm, location, max_hp, initiative,
                json.dumps({"beast": reputation}), stability, adapter, user,
            ),
        )
    if damage:
        equip_damage_weapon(runtime, adapter, user, damage)


async def _command(runtime, adapter: str, user: str, operation: str, command: str):
    return await runtime.adapters.dispatch(adapter, _ctx(adapter, user, operation), command)


async def _reach_spirit(runtime, adapter: str, user: str, prefix: str):
    entered = await _command(runtime, adapter, user, f"{prefix}:enter", "进入秘境 祖灵殿")
    assert entered.code == "ANCESTRAL_HALL_ENTERED"
    for index, node in enumerate(("祖灵门", "誓言石阵", "血脉回廊")):
        result = await _command(runtime, adapter, user, f"{prefix}:node:{index}", f"选择秘境节点 {node}")
        assert result.ok, result
    spirit = await _command(runtime, adapter, user, f"{prefix}:spirit", "选择秘境节点 祖灵守灵")
    assert spirit.code == "ANCESTRAL_HALL_COMBAT_PENDING"
    return entered, spirit


async def _win(runtime, adapter: str, user: str, prefix: str):
    entered, _ = await _reach_spirit(runtime, adapter, user, prefix)
    battle = await _command(runtime, adapter, user, f"{prefix}:combat", "结算秘境")
    assert battle.code == "ANCESTRAL_HALL_BATTLE_SETTLED", battle
    assert battle.data["current_node"] == "founder_altar"
    altar = await _command(runtime, adapter, user, f"{prefix}:altar", "选择秘境节点 始祖祭坛")
    assert altar.code == "ANCESTRAL_HALL_ROUTE_CLEARED"
    settled = await _command(runtime, adapter, user, f"{prefix}:settle", "结算秘境")
    assert settled.code == "ANCESTRAL_HALL_SETTLED", settled
    return entered, settled


@pytest.mark.parametrize("adapter", ["qq.official", "onebot.v11"])
def test_ancestral_hall_complete_and_idempotent_on_both_adapters(adapter: str) -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, adapters=(adapter,))
            user = f"ancestral-{adapter}"
            await _player(runtime, adapter, user)
            preview = await _command(runtime, adapter, user, "preview", "秘境预览")
            assert any(item["instance_key"] == "instance.secret_realm.ancestral_hall" for item in preview.data["realms"])

            entered = await _command(runtime, adapter, user, "first:enter", "进入秘境 祖灵殿")
            assert entered.code == "ANCESTRAL_HALL_ENTERED"
            skipped = await _command(runtime, adapter, user, "skip", "选择秘境节点 始祖祭坛")
            assert skipped.code == "ANCESTRAL_HALL_NODE_FORBIDDEN"
            for index, node in enumerate(("祖灵门", "誓言石阵", "血脉回廊", "祖灵守灵")):
                result = await _command(runtime, adapter, user, f"first:node:{index}", f"选择秘境节点 {node}")
                assert result.ok, result
            replay_entry = await _command(runtime, adapter, user, "first:enter", "进入秘境 祖灵殿")
            assert replay_entry.data["run_id"] == entered.data["run_id"]
            conflict = await _command(runtime, adapter, user, "first:node:0", "选择秘境节点 誓言石阵")
            assert conflict.code == "OPERATION_CONFLICT"

            battle = await _command(runtime, adapter, user, "first:battle", "结算秘境")
            assert battle.code == "ANCESTRAL_HALL_BATTLE_SETTLED"
            assert battle.data["current_node"] == "founder_altar"
            altar = await _command(runtime, adapter, user, "altar", "选择秘境节点 始祖祭坛")
            assert altar.code == "ANCESTRAL_HALL_ROUTE_CLEARED"
            settled = await _command(runtime, adapter, user, "finish", "结算秘境")
            replay = await _command(runtime, adapter, user, "finish", "结算秘境")
            quota = await _command(runtime, adapter, user, "weekly", "进入秘境 祖灵殿")
            assert settled.data["story_flag_written"] is True
            assert replay.data["idempotent_replay"] is True
            assert quota.code == "ANCESTRAL_HALL_QUOTA_EXHAUSTED"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                player = connection.execute(
                    "SELECT stamina, bloodline_stability, intro_json FROM players WHERE platform=? AND platform_user_id=?",
                    (adapter, user),
                ).fetchone()
                battle_record = connection.execute(
                    "SELECT enemy_key, reward_status FROM battle_sessions WHERE battle_type='pve.secret_realm.ancestral_hall'"
                ).fetchone()
            assert player[0] == 75
            assert player[1] == 50
            assert json.loads(player[2])["flags"].count("story.ancestral_hall") == 1
            assert battle_record == ("enemy.ancestral_spirit", "none")
            with sqlite3.connect(runtime.settings.database_path) as connection:
                codex_count = connection.execute(
                    "SELECT COUNT(*) FROM codex_entries WHERE player_id=(SELECT id FROM players WHERE platform=? AND platform_user_id=?) AND entry_key='codex.domain.ancestral_hall'",
                    (adapter, user),
                ).fetchone()[0]
            assert codex_count == 1

            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE ancestral_hall_runs SET quota_key='1990-W01' WHERE run_id=?", (entered.data["run_id"],)
                )
            # The first-clear story flag remains unique after the weekly quota rolls over.
            second = await _win(runtime, adapter, user, "repeat")
            assert second[1].data["story_flag_written"] is False
            with sqlite3.connect(runtime.settings.database_path) as connection:
                codex_count = connection.execute(
                    "SELECT COUNT(*) FROM codex_entries WHERE player_id=(SELECT id FROM players WHERE platform=? AND platform_user_id=?) AND entry_key='codex.domain.ancestral_hall'",
                    (adapter, user),
                ).fetchone()[0]
            assert codex_count == 1
            await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize(
    ("entry_adapter", "resume_adapter"),
    [("qq.official", "onebot.v11"), ("onebot.v11", "qq.official")],
)
def test_ancestral_hall_resumes_after_adapter_identity_handoff(entry_adapter, resume_adapter) -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 28, 12, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            user = f"handoff-{entry_adapter}"
            await _player(runtime, entry_adapter, user)
            entered = await _command(runtime, entry_adapter, user, "handoff:enter", "进入秘境 祖灵殿")
            assert entered.ok
            with sqlite3.connect(runtime.settings.database_path) as connection:
                connection.execute(
                    "UPDATE players SET platform=? WHERE platform=? AND platform_user_id=?",
                    (resume_adapter, entry_adapter, user),
                )
            await runtime.close()

            runtime = create_runtime(data_dir=data_dir, clock=clock)
            for index, node in enumerate(("祖灵门", "誓言石阵", "血脉回廊", "祖灵守灵")):
                result = await _command(runtime, resume_adapter, user, f"handoff:node:{index}", f"选择秘境节点 {node}")
                assert result.ok, result
            won = await _command(runtime, resume_adapter, user, "handoff:battle", "结算秘境")
            assert won.code == "ANCESTRAL_HALL_BATTLE_SETTLED"
            await runtime.close()

    asyncio.run(run())


@pytest.mark.parametrize(
    ("realm", "location", "reputation", "stability"),
    [
        ("nascent_soul", "beast.ancestral_lake", 3000, 50),
        ("soul_transformation", "beast.ten_thousand_hills", 3000, 50),
        ("soul_transformation", "beast.ancestral_lake", 2999, 50),
        ("soul_transformation", "beast.ancestral_lake", 3000, 49),
    ],
)
def test_ancestral_hall_entry_requirement_rejection_is_atomic(realm, location, reputation, stability) -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, adapters=("qq.official",))
            user = f"requirements-{realm}-{location}-{reputation}-{stability}"
            await _player(runtime, "qq.official", user, realm=realm, location=location, reputation=reputation, stability=stability)
            denied = await _command(runtime, "qq.official", user, "denied", "进入秘境 祖灵殿")
            assert denied.code == "ANCESTRAL_HALL_REQUIREMENT_MISSING"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                stamina, runs = connection.execute(
                    "SELECT stamina, (SELECT COUNT(*) FROM ancestral_hall_runs) FROM players WHERE platform_user_id=?",
                    (user,),
                ).fetchone()
            assert stamina == 100
            assert runs == 0
            await runtime.close()

    asyncio.run(run())


def test_ancestral_hall_failure_expiry_and_system_compensation() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 28, 12, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            loser = "ancestral-loser"
            await _player(runtime, "onebot.v11", loser, damage=0, max_hp=100, initiative=0)
            entered, _ = await _reach_spirit(runtime, "onebot.v11", loser, "loss")
            lost = await _command(runtime, "onebot.v11", loser, "loss:settle", "结算秘境")
            assert lost.code == "ANCESTRAL_HALL_SETTLED"
            assert lost.data["outcome"] == "lost"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                player = connection.execute(
                    "SELECT stamina, bloodline_stability, intro_json FROM players WHERE platform_user_id=?", (loser,)
                ).fetchone()
            assert player[0] == 75
            assert player[1] == 50
            assert "story.ancestral_hall" not in json.loads(player[2]).get("flags", [])
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute(
                    "SELECT COUNT(*) FROM codex_entries WHERE player_id=(SELECT id FROM players WHERE platform_user_id=?) AND entry_key='codex.domain.ancestral_hall'",
                    (loser,),
                ).fetchone()[0] == 0

            expired_user = "ancestral-expired"
            await _player(runtime, "qq.official", expired_user)
            expired_entry = await _command(runtime, "qq.official", expired_user, "expired:enter", "进入秘境 祖灵殿")
            clock.advance(minutes=61)
            expired = await _command(runtime, "qq.official", expired_user, "expired:settle", "结算秘境")
            assert expired.data["outcome"] == "expired"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                stamina = connection.execute(
                    "SELECT stamina FROM players WHERE platform_user_id=?", (expired_user,)
                ).fetchone()[0]
            assert stamina == 75

            combat_expired_user = "ancestral-combat-expired"
            await _player(runtime, "qq.official", combat_expired_user)
            combat_entry, combat_pending = await _reach_spirit(
                runtime, "qq.official", combat_expired_user, "combat-expired"
            )
            clock.advance(minutes=61)
            combat_expired = await _command(
                runtime, "qq.official", combat_expired_user, "combat-expired:settle", "结算秘境"
            )
            assert combat_expired.data["run_id"] == combat_entry.data["run_id"]
            assert combat_expired.data["outcome"] == "expired"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                battle_status, reward_status = connection.execute(
                    "SELECT status, reward_status FROM battle_sessions WHERE battle_id=?",
                    (combat_pending.data["battle_id"],),
                ).fetchone()
            assert (battle_status, reward_status) == ("settled", "none")

            compensate_user = "ancestral-compensate"
            await _player(runtime, "onebot.v11", compensate_user)
            compensation_entry = await _command(
                runtime, "onebot.v11", compensate_user, "comp:enter", "进入秘境 祖灵殿"
            )
            compensated = await runtime.repository.compensate_ancestral_hall_system_failure(
                run_id=compensation_entry.data["run_id"], operation_id="comp:system-abort"
            )
            replay = await runtime.repository.compensate_ancestral_hall_system_failure(
                run_id=compensation_entry.data["run_id"], operation_id="comp:system-abort"
            )
            assert compensated.status == "system_aborted"
            assert replay.already_completed is True
            retried = await _command(runtime, "onebot.v11", compensate_user, "comp:retry", "进入秘境 祖灵殿")
            assert retried.code == "ANCESTRAL_HALL_ENTERED"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                stamina = connection.execute(
                    "SELECT stamina FROM players WHERE platform_user_id=?", (compensate_user,)
                ).fetchone()[0]
            assert stamina == 75
            await runtime.close()

    asyncio.run(run())


def test_ancestral_spirit_summon_clear_and_timeout_recovery_are_persisted() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 28, 12, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            user = "ancestral-shadow"
            await _player(runtime, "qq.official", user, damage=0, max_hp=1_000_000, initiative=9999)
            entered, spirit = await _reach_spirit(runtime, "qq.official", user, "shadow")
            battle_id = spirit.data["battle_id"]
            for round_no in range(1, 5):
                turn = await runtime.repository.run_battle_turn(battle_id=battle_id, expected_round=round_no)
                assert turn.status == "running"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                shadow_state = json.loads(connection.execute(
                    "SELECT state_json FROM battle_sessions WHERE battle_id=?", (battle_id,)
                ).fetchone()[0])
                summon = connection.execute(
                    "SELECT strategy_key FROM battle_actions WHERE battle_id=? AND round_no=4 ORDER BY sequence_no DESC LIMIT 1",
                    (battle_id,),
                ).fetchone()[0]
            assert shadow_state["bloodline_shadow"] is True
            assert summon == "strategy.ancestral_spirit.bloodline_call"

            clock.advance(seconds=61)
            timeout = await runtime.repository.run_battle_turn(battle_id=battle_id, expected_round=5)
            assert timeout.status == "running"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                rows = connection.execute(
                    "SELECT strategy_key, damage, state_json FROM battle_actions WHERE battle_id=? AND round_no=5 ORDER BY sequence_no",
                    (battle_id,),
                ).fetchall()
                state = json.loads(connection.execute(
                    "SELECT state_json FROM battle_sessions WHERE battle_id=?", (battle_id,)
                ).fetchone()[0])
                recovery = next(json.loads(row[2]) for row in rows if row[0] == "strategy.ancestral_spirit.bloodline_recovery")
            assert recovery["recovery"] == 800
            assert state["bloodline_shadow"] is False
            assert any(row[0] == "strategy.timeout_defend" for row in rows)

            for round_no in range(6, 9):
                assert (await runtime.repository.run_battle_turn(battle_id=battle_id, expected_round=round_no)).status == "running"
            auto_clear = await runtime.repository.run_battle_turn(battle_id=battle_id, expected_round=9)
            assert auto_clear.status == "running"
            with sqlite3.connect(runtime.settings.database_path) as connection:
                clear_strategy = connection.execute(
                    "SELECT strategy_key FROM battle_actions WHERE battle_id=? AND round_no=9 ORDER BY sequence_no LIMIT 1",
                    (battle_id,),
                ).fetchone()[0]
                battle_status = connection.execute(
                    "SELECT status FROM battle_sessions WHERE battle_id=?", (battle_id,)
                ).fetchone()[0]
            assert clear_strategy == "strategy.ancestral_spirit.clear_shadow"
            assert battle_status == "running"

            compensated = await runtime.repository.compensate_ancestral_hall_system_failure(
                run_id=entered.data["run_id"], operation_id="shadow:abort"
            )
            assert compensated.status == "system_aborted"
            await runtime.close()

    asyncio.run(run())
