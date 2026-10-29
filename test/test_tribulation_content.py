"""Content contract for the data-backed tribulation trial."""

from __future__ import annotations

import copy
from dataclasses import replace
from pathlib import Path

import pytest

from nonebot_plugin_xiuxian_3.xiuxian.combat.tribulation_content import (
    TRIAL_KEY,
    tribulation_phases,
    tribulation_trial,
)
from nonebot_plugin_xiuxian_3.xiuxian.combat.tribulation_rules import (
    ENEMY_AGILITY,
    ENEMY_ATTACK,
    ENEMY_INITIATIVE,
    ENEMY_KEY,
    ENEMY_MAX_HP,
    PHASES,
    PROFILE_KEY,
    phase_for_hp,
)
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError

DATA = Path(__file__).parents[1] / "data"


def _replace_trial(bundle, **changes):
    records = dict(bundle._records)
    row = copy.deepcopy(records["tribulation_trial", TRIAL_KEY])
    row.update(changes)
    records["tribulation_trial", TRIAL_KEY] = row
    return replace(bundle, _records=records)


def test_trial_content_matches_the_shipped_scale() -> None:
    bundle = ContentBundle.load(DATA)
    trial = tribulation_trial(bundle)
    assert trial["enemy"] == {
        "max_hp": 150_000,
        "attack": 5_500,
        "initiative": 1_600,
        "agility": 650,
    }
    assert (ENEMY_KEY, PROFILE_KEY, ENEMY_MAX_HP) == (
        "enemy.tribulation_heaven",
        "battle_profile.tribulation_trial",
        150_000,
    )
    assert (ENEMY_ATTACK, ENEMY_INITIATIVE, ENEMY_AGILITY) == (5_500, 1_600, 650)
    assert tribulation_phases(bundle) == PHASES
    assert [(p.key, p.min_hp_bp, p.attack, p.enemy_hit_bonus_bp, p.player_damage_bp) for p in PHASES] == [
        ("thunder", 6667, 5500, 0, 10000),
        ("heart", 3334, 8000, 200, 9500),
        ("dao", 0, 12000, 400, 9000),
    ]
    assert [(p.key, p.label) for p in PHASES] == [
        ("thunder", "雷劫"),
        ("heart", "心魔"),
        ("dao", "道劫"),
    ]
    assert [p.skill_key for p in PHASES] == [
        "skill.tribulation.thunder",
        "skill.tribulation.heart",
        "skill.tribulation.dao",
    ]


@pytest.mark.parametrize(
    "hp,expected",
    [
        (150_000, "thunder"),
        (100_005, "thunder"),
        (100_004, "heart"),
        (50_010, "heart"),
        (50_009, "dao"),
        (0, "dao"),
    ],
)
def test_phase_for_hp_boundaries(hp: int, expected: str) -> None:
    assert phase_for_hp(hp).key == expected


@pytest.mark.parametrize(
    "changes",
    [
        {"enemy": {"max_hp": 0, "attack": 5500, "initiative": 1600, "agility": 650}},
        {"enemy": {"max_hp": 150000, "attack": 5500, "initiative": 1600}},
        {"phases": []},
        {"phases": [{"key": "a", "min_hp_bp": 0, "attack": 1, "skill_key": "skill.tribulation.dao", "enemy_hit_bonus_bp": 0, "player_damage_bp": 9000}] * 2},
        {"status": "closed"},
        {"phases": [{"key": "a", "label": "", "min_hp_bp": 0, "attack": 1, "skill_key": "skill.tribulation.dao", "enemy_hit_bonus_bp": 0, "player_damage_bp": 9000}]},
        {"enemy_key": ""},
    ],
)
def test_trial_content_rejects_broken_records(changes: dict) -> None:
    with pytest.raises(ContentError):
        tribulation_trial(_replace_trial(ContentBundle.load(DATA), **changes))


def test_trial_content_rejects_a_phase_that_does_not_end_at_zero() -> None:
    bundle = ContentBundle.load(DATA)
    row = copy.deepcopy(dict(bundle._records["tribulation_trial", TRIAL_KEY]))
    row["phases"][-1]["min_hp_bp"] = 10
    with pytest.raises(ContentError, match="0 bp"):
        tribulation_trial(_replace_trial(bundle, phases=row["phases"]))
