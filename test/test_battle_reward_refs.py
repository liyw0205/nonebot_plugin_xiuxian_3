"""Battle rewards declared as `reward_refs` must actually be paid.

`combat_content.py` validated `enemy.reward_refs` and then dropped it, so the four
enemies that declare a `reward.battle.*` table carried `reward={}` and paid nothing.
This module pins the adoption plus the two table fields that were unread before:
entry-level `chance_bp` and record-level `material_pool`.
"""

from __future__ import annotations

import copy
from dataclasses import replace
from pathlib import Path

import pytest

from nonebot_plugin_xiuxian_3.xiuxian.combat.rules import enemy_definition
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle
from nonebot_plugin_xiuxian_3.xiuxian.rewards.rules import (
    RewardContentError,
    battle_reward_tables,
    roll_bp,
)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

DECLARED = (
    "enemy.wood_rat",
    "enemy.iron_boar",
    "enemy.bandit_apprentice",
    "enemy.mist_guardian",
)


def _bundle() -> ContentBundle:
    return ContentBundle.load(DATA)


def test_the_four_declaring_enemies_freeze_their_declared_table() -> None:
    bundle = _bundle()
    frozen = {}
    for key in DECLARED:
        definition = enemy_definition(key, content=bundle)
        assert definition.reward_refs, key
        assert definition.reward == {}, f"{key} still carries an inline reward"
        frozen[key] = battle_reward_tables(definition.reward_refs, bundle, seed="battle-1")

    # The fixed parts of each table land exactly.
    assert frozen["enemy.wood_rat"]["cultivation"] == 10
    assert frozen["enemy.iron_boar"]["cultivation"] == 30
    assert frozen["enemy.iron_boar"]["spirit_stones"] == 8
    assert frozen["enemy.iron_boar"]["item.ore.ironstone"] == 1
    assert frozen["enemy.bandit_apprentice"]["cultivation"] == 60
    assert frozen["enemy.bandit_apprentice"]["spirit_stones"] == 20
    assert frozen["enemy.mist_guardian"]["cultivation"] == 160


def test_other_enemies_keep_their_inline_reward() -> None:
    bundle = _bundle()
    wisp = enemy_definition("enemy.spring_wisp", content=bundle)
    assert wisp.reward_refs == ()
    assert wisp.reward == {}


def test_frozen_reward_is_stable_for_a_seed_and_rolls_once_per_battle() -> None:
    bundle = _bundle()
    first = battle_reward_tables(["reward.battle.wood_rat"], bundle, seed="same-battle")
    second = battle_reward_tables(["reward.battle.wood_rat"], bundle, seed="same-battle")
    assert first == second
    # A different battle may differ only in the rolled quantity, never the shape.
    assert set(
        battle_reward_tables(["reward.battle.wood_rat"], bundle, seed="other-battle")
    ) == set(first)


def test_chance_entry_appears_at_roughly_its_declared_rate() -> None:
    bundle = _bundle()
    hits = sum(
        1
        for index in range(1000)
        if "item.pill.focus_low"
        in battle_reward_tables(
            ["reward.battle.bandit_apprentice"], bundle, seed=f"seed-{index}"
        )
    )
    # 2000 bp declared; 1000 draws keep this well inside a +-60 bp window.
    assert 140 <= hits <= 260, hits


def test_material_pool_always_yields_one_material_inside_its_range() -> None:
    bundle = _bundle()
    allowed = {"item.herb.spirit_leaf", "item.mat.array_sand", "item.ore.ironstone"}
    seen = set()
    for index in range(200):
        reward = battle_reward_tables(
            ["reward.battle.mist_guardian"], bundle, seed=f"seed-{index}"
        )
        picked = allowed & set(reward)
        assert len(picked) == 1, reward
        material = picked.pop()
        seen.add(material)
        assert 1 <= reward[material] <= 3, reward
    # The weighted pool is not collapsed onto a single material.
    assert len(seen) == 3, seen


def test_roll_helper_is_deterministic_and_bounded() -> None:
    assert roll_bp("a") == roll_bp("a")
    assert roll_bp("a") != roll_bp("b")
    assert all(0 <= roll_bp(f"seed-{index}") < 10_000 for index in range(100))


def _with_reward(bundle: ContentBundle, key: str, **changes: object) -> ContentBundle:
    records = dict(bundle._records)
    row = copy.deepcopy(records[("reward", key)])
    row.update(changes)
    records[("reward", key)] = row
    return replace(bundle, _records=records)


@pytest.mark.parametrize(
    "changes, message",
    [
        ({"entries": []}, "requires entries"),
        ({"entries": [{"kind": "blessing", "blessing_key": "x"}]}, "unsupported kind"),
        ({"entries": [{"kind": "item"}]}, "requires item_key"),
        ({"entries": [{"kind": "item", "item_key": "item.x", "chance_bp": 10_001}]}, "chance_bp"),
        ({"entries": [{"kind": "item", "item_key": "item.x"}]}, "quantity"),
        (
            {
                "material_pool": {
                    "selection": "all",
                    "quantity_range": [1, 1],
                    "entries": [{"item_key": "item.x", "weight": 1}],
                }
            },
            "unsupported",
        ),
        (
            {
                "material_pool": {
                    "quantity_range": [1, 1],
                    "entries": [{"item_key": "item.x", "weight": 0}],
                }
            },
            "positive weight",
        ),
    ],
)
def test_broken_tables_raise_instead_of_paying_nothing(
    changes: dict[str, object], message: str
) -> None:
    bundle = _with_reward(_bundle(), "reward.battle.wood_rat", **changes)
    with pytest.raises(RewardContentError, match=message):
        battle_reward_tables(["reward.battle.wood_rat"], bundle, seed="broken")
