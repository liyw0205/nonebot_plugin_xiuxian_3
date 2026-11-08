"""The trial's declared `automatic_phase_selection` must reach the battle.

`enemy.tribulation_heaven.behavior.automatic_phase_selection` was validated
nowhere and read nowhere: the turn engine advanced thunder -> heart -> dao by HP
unconditionally.  The trial now validates the behaviour block, freezes the flag
into the battle snapshot, and keeps the entry phase when the content says the
heaven does not select its own phase.
"""

from __future__ import annotations

import asyncio
import copy
import json
import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory

import pytest

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.combat.tribulation_rules import (
    AUTOMATIC_PHASE_SELECTION,
    ENEMY_MAX_HP,
    PHASES,
    phase_for_hp,
)
from nonebot_plugin_xiuxian_3.xiuxian.combat.tribulation_content import tribulation_trial
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError

ENEMY_KEY = "enemy.tribulation_heaven"


class MutableClock:
    def __init__(self, value: datetime):
        self.value = value

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **kwargs: int) -> None:
        self.value += timedelta(**kwargs)


def _context(user: str, operation_id: str) -> CommandContext:
    return CommandContext(adapter="onebot.v11", user_id=user, operation_id=operation_id)


def _bundle() -> ContentBundle:
    from pathlib import Path

    return ContentBundle.load(Path(__file__).resolve().parents[1] / "data")


def _with_behavior(bundle: ContentBundle, **behavior: object) -> ContentBundle:
    records = dict(bundle._records)
    row = copy.deepcopy(records[("enemy", ENEMY_KEY)])
    row["behavior"] = {**row["behavior"], **behavior}
    records[("enemy", ENEMY_KEY)] = row
    return replace(bundle, _records=records)


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


def test_the_shipped_trial_declares_automatic_selection_and_still_advances() -> None:
    assert AUTOMATIC_PHASE_SELECTION is True
    assert tribulation_trial()["automatic_phase_selection"] is True
    assert [phase.key for phase in PHASES] == ["thunder", "heart", "dao"]
    assert phase_for_hp(ENEMY_MAX_HP).key == "thunder"
    assert phase_for_hp(100_000).key == "heart"
    assert phase_for_hp(0).key == "dao"


def test_a_trial_that_does_not_select_keeps_its_entry_phase() -> None:
    assert phase_for_hp(0, automatic=False).key == "thunder"
    assert phase_for_hp(ENEMY_MAX_HP, automatic=False).key == "thunder"


def test_the_flag_is_read_from_content_and_validated() -> None:
    bundle = _bundle()
    off = _with_behavior(bundle, automatic_phase_selection=False)
    assert tribulation_trial(off)["automatic_phase_selection"] is False

    broken = _with_behavior(bundle, automatic_phase_selection="yes")
    with pytest.raises(ContentError, match="must be a boolean"):
        tribulation_trial(broken)

    records = dict(bundle._records)
    row = copy.deepcopy(records[("enemy", ENEMY_KEY)])
    row.pop("behavior")
    records[("enemy", ENEMY_KEY)] = row
    with pytest.raises(ContentError, match="behavior is invalid"):
        tribulation_trial(replace(bundle, _records=records))


def test_a_frozen_off_flag_keeps_the_battle_in_the_entry_phase() -> None:
    async def run() -> None:
        from pathlib import Path
        import shutil

        clock = MutableClock(datetime(2026, 9, 24, 12, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            content_root = Path(data_dir) / "content"
            shutil.copytree(Path(__file__).resolve().parents[1] / "data", content_root)
            enemy_file = content_root / "战斗" / "敌人.json"
            document = json.loads(enemy_file.read_text(encoding="utf-8"))
            record = next(row for row in document["records"] if row["key"] == ENEMY_KEY)
            record["behavior"]["automatic_phase_selection"] = False
            enemy_file.write_text(
                json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            runtime = create_runtime(data_dir=content_root, clock=clock)
            user = "tribulation-phase-flag"
            assert (await runtime.dispatch(_context(user, "create"), "开始修仙")).code == "PLAYER_CREATED"
            _prepare_player(runtime, user, debt=30)
            started = await runtime.dispatch(_context(user, "trial-start"), "开始天劫试炼 身心劫")
            assert started.code == "TRIAL_STARTED"
            battle_id = started.data["battle_id"]

            with sqlite3.connect(runtime.settings.database_path) as connection:
                snapshot = json.loads(
                    connection.execute(
                        "SELECT snapshot_json FROM battle_sessions WHERE battle_id = ?", (battle_id,)
                    ).fetchone()[0]
                )
            # The trial really froze the content's answer, not a default.
            assert snapshot["tribulation"]["automatic_phase_selection"] is False

            for expected_round in range(1, 6):
                turn = await runtime.repository.run_battle_turn(
                    battle_id=battle_id, expected_round=expected_round
                )
                if turn.status not in {"created", "running"}:
                    break

            with sqlite3.connect(runtime.settings.database_path) as connection:
                rows = connection.execute(
                    "SELECT state_json FROM battle_actions WHERE battle_id = ? ORDER BY sequence_no",
                    (battle_id,),
                ).fetchall()
            states = [json.loads(row[0]) for row in rows]
            assert states, "the trial produced no actions"
            assert {state["tribulation_phase"] for state in states} == {"thunder"}
            # The HP did cross the boundary, so only the flag kept it there.
            assert min(state["enemy_hp"] for state in states) < 100_000

    asyncio.run(run())
