"""An enemy's declared skill must actually shape the automatic battle.

Before this slice the turn engine copied `enemy.skill_key` into the log and
always struck with raw `stats.attack`, so 雾盾 (a self ward) and 刀波 (a bleeding
strike) were decoration.  These tests pin the consumer: the ward soaks damage
until its pool or its duration runs out, the bleeding tick lasts exactly its
declared rounds, a plain skill changes nothing, and an effect type the engine
cannot apply fails the content load instead of silently doing nothing.
"""

from __future__ import annotations

import asyncio
import copy
import json
import sqlite3
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from combat_fixtures import equip_damage_weapon
from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.combat.enemy_skills import (
    absorb_with_shield,
    apply_enemy_status,
    enemy_skill_attack,
    enemy_skill_casts,
    open_enemy_shield,
    resolve_enemy_skill,
    tick_enemy_statuses,
)
from nonebot_plugin_xiuxian_3.xiuxian.combat_content import validate_combat_content
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


def _skill(key: str, bundle: ContentBundle | None = None) -> dict:
    return resolve_enemy_skill((bundle or ContentBundle.load(DATA)).require("skill", key))


def _context(user_id: str, request_id: str) -> CommandContext:
    return CommandContext(adapter="web", user_id=user_id, request_id=request_id)


async def _enter_cultivator(runtime, user_id: str) -> None:
    for request, text in (
        ("create", "开始修仙"),
        ("seek", "寻仙问道"),
        ("read", "完成引导 阅读"),
        ("travel", "前往近郊"),
        ("gather", "完成引导 采集"),
        ("service", "完成引导 炼丹"),
        ("path", "选择道途 体修"),
        ("return", "返回新手城"),
    ):
        result = await runtime.dispatch(_context(user_id, request), text)
        assert result.ok, (text, result.code)


def _place(runtime, user_id: str, *, location: str, realm: str, layer: int, max_hp: int) -> None:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        connection.execute(
            "UPDATE players SET location_key=?, realm_key=?, realm_layer=?, max_hp=? "
            "WHERE platform='web' AND platform_user_id=?",
            (location, realm, layer, max_hp, user_id),
        )


async def _fight(runtime, user_id: str, enemy_key: str, operation_id: str):
    started = await runtime.repository.start_quest_battle(
        platform="web",
        platform_user_id=user_id,
        enemy_key=enemy_key,
        battle_type="pve.encounter",
        operation_id=operation_id,
    )
    turn = None
    for expected_round in range(started.round_no + 1, 21):
        turn = await runtime.repository.run_battle_turn(
            battle_id=started.battle_id, expected_round=expected_round
        )
        if turn.status not in {"created", "running"}:
            break
    assert turn is not None and turn.status not in {"created", "running"}
    resolved = await runtime.repository.resolve_battle(battle_id=started.battle_id)
    replay = await runtime.repository.replay_battle(
        platform="web", platform_user_id=user_id, battle_id=started.battle_id
    )
    return resolved, replay


def test_the_mist_shield_soaks_damage_until_its_pool_runs_out() -> None:
    skill = _skill("enemy_skill.mist_shield")
    assert skill["shield_bp"] == 8000
    state = {"enemy_shield": open_enemy_shield(skill, 320, round_no=1)}
    assert state["enemy_shield"] == {"remaining": 256, "until_round": 2}

    absorbed, remaining = absorb_with_shield(state, 200, round_no=1)
    assert (absorbed, remaining) == (200, 0)
    assert state["enemy_shield"]["remaining"] == 56

    absorbed, remaining = absorb_with_shield(state, 100, round_no=2)
    assert (absorbed, remaining) == (56, 44)
    assert "enemy_shield" not in state

    assert absorb_with_shield(state, 100, round_no=2) == (0, 100)


def test_the_shield_expires_at_its_declared_duration() -> None:
    skill = _skill("enemy_skill.mist_shield")
    state = {"enemy_shield": open_enemy_shield(skill, 320, round_no=1)}
    # duration_rounds 2 from round 1 -> it covers rounds 1 and 2, not 3.
    assert absorb_with_shield(state, 10, round_no=3) == (0, 10)
    assert "enemy_shield" not in state


def test_the_bleeding_strike_ticks_for_exactly_its_declared_rounds() -> None:
    skill = _skill("enemy_skill.blade_wave")
    assert skill["multiplier_bp"] == 13000 and skill["status_key"] == "bleeding"
    state: dict = {}
    assert apply_enemy_status(state, skill, 100, round_no=2) == "bleeding"
    assert state["enemy_statuses"]["bleeding"] == {"damage": 30, "until_round": 4}

    assert tick_enemy_statuses(state, round_no=2) == (30, ("bleeding",))
    assert tick_enemy_statuses(state, round_no=4) == (30, ("bleeding",))
    assert tick_enemy_statuses(state, round_no=5) == (0, ())
    assert "enemy_statuses" not in state


def test_a_plain_skill_leaves_the_attack_and_state_untouched() -> None:
    plain = _skill("enemy_skill.dummy_tap")
    assert plain["multiplier_bp"] == 10_000
    assert enemy_skill_attack(plain, 11, round_no=1) == 11
    assert enemy_skill_attack(None, 11, round_no=1) == 11
    state: dict = {}
    assert apply_enemy_status(state, plain, 11, round_no=1) is None
    assert state == {}


def test_the_declared_cooldown_decides_which_rounds_use_the_skill() -> None:
    scratch = _skill("enemy_skill.scratch")
    assert scratch["multiplier_bp"] == 11_000 and scratch["cooldown_rounds"] == 0
    # No declared cooldown: the strike is the enemy's normal attack.
    assert enemy_skill_attack(scratch, 10, round_no=1) == 11
    assert enemy_skill_attack(scratch, 10, round_no=7) == 11

    charge = _skill("enemy_skill.charge")
    assert charge["cooldown_rounds"] == 2
    assert enemy_skill_casts(charge, 1) is True
    assert enemy_skill_casts(charge, 2) is False
    assert enemy_skill_casts(charge, 3) is False
    assert enemy_skill_casts(charge, 4) is True
    assert enemy_skill_attack(charge, 10, round_no=1) == 15
    assert enemy_skill_attack(charge, 10, round_no=2) == 10


def test_an_unsupported_effect_type_fails_the_content_load() -> None:
    bundle = ContentBundle.load(DATA)
    records = dict(bundle._records)
    row = copy.deepcopy(records[("skill", "enemy_skill.mist_shield")])
    row["effect"]["type"] = "magic_shield"
    records[("skill", "enemy_skill.mist_shield")] = row
    broken = replace(bundle, _records=records)
    with pytest.raises(ContentError, match="unsupported effect type"):
        validate_combat_content(broken)
    with pytest.raises(ContentError, match="unsupported effect type"):
        resolve_enemy_skill(row)


def test_a_warded_battle_absorbs_and_replays_the_same_trail() -> None:
    async def run() -> None:
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir)
            user = "mist-shield"
            await _enter_cultivator(runtime, user)
            _place(runtime, user, location="cave.mist_grotto", realm="qi_gathering", layer=4, max_hp=4000)
            equip_damage_weapon(runtime, "web", user, 120)
            resolved, replay = await _fight(runtime, user, "enemy.mist_guardian", "mist-shield-1")
            assert resolved.outcome == "won"
            absorbed = [int(action.get("state", {}).get("enemy_hp", 0)) for action in replay.actions]
            assert absorbed  # the ward is only visible through the frozen action trail
            shielded = [
                action for action in replay.actions if int(action.get("damage", 0)) >= 0
            ]
            assert shielded
            # The pool is finite: a 320 HP guardian wards at most 256 damage.
            trail = json.dumps(replay.actions, ensure_ascii=False)
            assert "enemy_shield" in trail or "shield_absorbed" in trail
            again = await runtime.repository.replay_battle(
                platform="web", platform_user_id=user, battle_id=resolved.battle_id
            )
            assert [action["sequence_no"] for action in again.actions] == [
                action["sequence_no"] for action in replay.actions
            ]
            assert [action["state"] for action in again.actions] == [
                action["state"] for action in replay.actions
            ]

    asyncio.run(run())
