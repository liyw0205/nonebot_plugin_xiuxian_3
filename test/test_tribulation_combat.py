from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.combat.tribulation_rules import (
    ENEMY_MAX_HP,
    PHASES,
    debt_shield_bp,
    phase_for_hp,
    stat_snapshot,
)


class MutableClock:
    def __init__(self, value: datetime):
        self.value = value

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **kwargs: int) -> None:
        self.value += timedelta(**kwargs)


def _context(user: str, operation_id: str) -> CommandContext:
    return CommandContext(adapter="onebot.v11", user_id=user, operation_id=operation_id)


def _prepare_player(runtime, user: str, *, debt: int = 0) -> None:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE players SET stage='cultivator', realm_key='tribulation', realm_layer=3, "
            "location_key='tribulation.sky_terrace', path_key='body', tribulation_debt=?, "
            "qualification_json=?, inventory_json=? WHERE platform=? AND platform_user_id=?",
            (
                debt,
                json.dumps({"body": 2_000, "agility": 2_000}),
                json.dumps({"item.tribulation_token": 1}),
                "onebot.v11",
                user,
            ),
        )


def test_tribulation_phase_boundaries_and_derived_stats_are_versioned_inputs() -> None:
    assert tuple(phase.key for phase in PHASES) == ("thunder", "heart", "dao")
    assert phase_for_hp(ENEMY_MAX_HP).key == "thunder"
    assert phase_for_hp(100_000).key == "heart"
    assert phase_for_hp(50_010).key == "heart"
    assert phase_for_hp(50_009).key == "dao"
    assert phase_for_hp(0).key == "dao"

    assert debt_shield_bp(0) == 0
    assert debt_shield_bp(9) == 0
    assert debt_shield_bp(10) == 200
    assert debt_shield_bp(100) == 2_000
    assert debt_shield_bp(500) == 2_000

    stats = stat_snapshot(
        {"body": 2_000, "agility": 2_000},
        realm_layer=3,
        equipment=(
            {
                "slot": "weapon",
                "temper_level": 2,
                "affixes": {"hp": 4, "damage": 5, "initiative": 3},
            },
        ),
    )
    assert stats == {
        "max_hp": 155_400,
        "attack": 31_500,
        "initiative": 21_360,
        "agility": 20_550,
    }


def test_tribulation_actions_replay_after_restart_and_settlement_is_idempotent() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 24, 12, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            user = "tribulation-recovery"
            assert (await runtime.dispatch(_context(user, "create"), "开始修仙")).code == "PLAYER_CREATED"
            _prepare_player(runtime, user, debt=30)

            started = await runtime.dispatch(
                _context(user, "trial-start"), "开始天劫试炼 身心劫"
            )
            assert started.code == "TRIAL_STARTED"
            battle_id = started.data["battle_id"]

            with sqlite3.connect(runtime.settings.database_path) as connection:
                snapshot_text, session_status, battle_status = connection.execute(
                    "SELECT t.snapshot_json, t.status, b.status "
                    "FROM tribulation_trial_sessions t JOIN battle_sessions b "
                    "ON json_extract(t.snapshot_json, '$.battle_id') = b.battle_id "
                    "WHERE t.session_id = ?",
                    (started.data["session_id"],),
                ).fetchone()
                actions = connection.execute(
                    "SELECT round_no, actor_key, skill_key, damage, state_json "
                    "FROM battle_actions WHERE battle_id = ? ORDER BY sequence_no",
                    (battle_id,),
                ).fetchall()
            snapshot = json.loads(snapshot_text)
            assert session_status == "preparing"
            assert battle_status == "settled"
            assert snapshot["profile_key"] == "battle_profile.tribulation_trial.v1"
            assert snapshot["tribulation"]["debt_shield_bp"] == 600
            assert snapshot["player"]["stats"]["max_hp"] == 155_000
            assert {json.loads(row[4])["tribulation_phase"] for row in actions} == {
                "thunder",
                "heart",
                "dao",
            }
            assert {row[2] for row in actions if row[1] == "enemy"} == {
                "skill.tribulation.thunder",
                "skill.tribulation.heart",
                "skill.tribulation.dao",
            }
            assert any(row[3] == 28_200 for row in actions), "debt shield must reduce thunder damage"
            assert any(row[3] == 26_790 for row in actions), "heart damage modifier must be replayed"
            assert any(row[3] == 25_380 for row in actions), "dao damage modifier must be replayed"

            replay = await runtime.dispatch(
                _context(user, "replay-command"), f"战斗回放 {battle_id}"
            )
            assert replay.code == "BATTLE_REPLAY"
            assert "三劫天尊" in replay.message
            assert "雷劫" not in replay.message
            assert "（thunder阶段）" in replay.message
            action_count_before = len(replay.data["actions"])
            repeated_turn = await runtime.repository.run_battle_turn(
                battle_id=battle_id, expected_round=1
            )
            assert repeated_turn.already_completed is True

            await runtime.close()
            clock.advance(minutes=31)
            recovered = create_runtime(data_dir=data_dir, clock=clock)
            settled = await recovered.dispatch(
                _context(user, "trial-settle"), "结算天劫试炼"
            )
            assert settled.code == "TRIAL_SUCCEEDED"
            assert settled.data["battle_id"] == battle_id
            assert settled.data["battle_outcome"] == "won"
            assert settled.data["tribulation_debt"] == 30
            replay_settlement = await recovered.dispatch(
                _context(user, "trial-settle"), "结算天劫试炼"
            )
            assert replay_settlement.data["idempotent_replay"] is True

            with sqlite3.connect(recovered.settings.database_path) as connection:
                result = connection.execute(
                    "SELECT status, result_json FROM tribulation_trial_sessions WHERE session_id = ?",
                    (started.data["session_id"],),
                ).fetchone()
                action_count_after = connection.execute(
                    "SELECT COUNT(*) FROM battle_actions WHERE battle_id = ?", (battle_id,)
                ).fetchone()[0]
                operations = connection.execute(
                    "SELECT COUNT(*) FROM operations WHERE operation_id LIKE ?",
                    (f"battle.run_turn:{battle_id}:%",),
                ).fetchone()[0]
            assert result[0] == "succeeded"
            assert json.loads(result[1])["debt_delta"] == 0
            assert action_count_after == action_count_before
            assert operations == len({row[0] for row in actions})
            await recovered.close()

    asyncio.run(run())
