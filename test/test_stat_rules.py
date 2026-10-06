from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError
from nonebot_plugin_xiuxian_3.xiuxian.stats.models import StatSnapshot, StatSnapshotError
from nonebot_plugin_xiuxian_3.xiuxian.stats.rules import (
    COMBAT_STAT_KEYS,
    DERIVED_KEYS,
    STAT_KEYS,
    apply_constitution_combat_effect,
    build_stat_preview,
    frozen_combat_stats,
    stats_formula,
)


@pytest.fixture(scope="module")
def content() -> ContentBundle:
    return ContentBundle.load(Path(__file__).parents[1] / "data")


def _player(**values) -> dict:
    return {
        "qualification": dict.fromkeys(STAT_KEYS, 10),
        "realm_key": "mortal", "realm_layer": 0, "path_key": None,
        "max_hp": 0, "max_mp": 0, "initiative": 0, "carry_capacity": 0,
        "exploration_efficiency_bp": 0, **values,
    }


def _equipment(**values) -> dict:
    return {
        "item_key": "item.weapon.sword.wood_training_blade", "slot": "weapon",
        "durability_bp": 10_000, "temper_level": 0, "affixes": {}, "effects": [],
        **values,
    }


def _manuals(**bonuses) -> dict:
    return {
        "cultivation_gain_bp": 0, "damage_reflection_bp": 0,
        "combat_stat_bonus_bp": {"attack": 0, "max_hp": 0, "initiative": 0, "agility": 0, **bonuses},
    }


def _changed_content(content: ContentBundle, edit) -> ContentBundle:
    records = dict(content._records)
    rules = deepcopy(records[("advancement_rule", "stats.formula")])
    edit(rules)
    records[("advancement_rule", "stats.formula")] = rules
    return replace(content, _records=records)


def _snapshot_payload(content: ContentBundle) -> dict:
    preview = build_stat_preview(_player(), content)
    return StatSnapshot(
        snapshot_id="stats-example", player_id=1,
        base_stats=preview["base_stats"], path_stats=preview["path_stats"],
        derived_stats=preview["derived_stats"], source_refs=tuple(preview["source_refs"]),
        formula_fingerprint=preview["formula_fingerprint"], purpose="battle",
        created_at="2026-10-07T00:00:00+00:00",
    ).payload()


def test_base_and_permanent_stats_use_one_formula_and_combat_mapping(content: ContentBundle) -> None:
    row = _player(max_hp=600, max_mp=480, initiative=20, carry_capacity=50, exploration_efficiency_bp=1500)
    original = deepcopy(row)
    preview = build_stat_preview(row, content)
    derived = preview["derived_stats"]
    assert set(derived) == set(DERIVED_KEYS)
    assert derived["max_hp"] == 100 + 8 * 10 + 5 * 10 + 600
    assert derived["max_mp"] == 60 + 10 * 10 + 4 * 10 + 480
    assert derived["initiative"] == 10 + 10 + 20
    assert derived["carry_capacity"] == 20 + 2 * 10 + 50
    assert derived["exploration_rate_bp"] == 10_000 + 50 * 10 + 1500
    assert derived["attack"] == 10 + 10 // 2
    assert preview["combat_stats"] == {
        key: derived["max_mp" if key == "max_mana" else key] for key in COMBAT_STAT_KEYS
    }
    permanent = next(source for source in preview["source_refs"] if source["key"] == "permanent")
    assert permanent["effect"]["max_mp"] == 480
    assert row == original


def test_realm_formula_does_not_invent_missing_breakthrough_rewards(content: ContentBundle) -> None:
    row = _player(realm_key="nascent_soul", realm_layer=3)
    preview = build_stat_preview(row, content)
    rank = content.require("realm", "nascent_soul")["rank"]
    assert preview["derived_stats"]["max_hp"] == 100 + 20 * rank + 3 * 2 + 80 + 50
    assert preview["derived_stats"]["max_mp"] == 60 + 18 * rank + 2 * 2 + 100 + 40
    rewarded = build_stat_preview({**row, "max_hp": 600, "max_mp": 480}, content)
    assert rewarded["derived_stats"]["max_hp"] - preview["derived_stats"]["max_hp"] == 600
    assert rewarded["derived_stats"]["max_mp"] - preview["derived_stats"]["max_mp"] == 480


def test_equipment_durability_and_build_percentages_apply_once(content: ContentBundle) -> None:
    equipment = _equipment(
        durability_bp=5000, temper_level=3,
        affixes={"damage": 9, "hp": 7, "max_mana": 11},
        effects=[
            {"type": "flat_stat", "stat": "physical_damage", "value": 7},
            {"type": "flat_stat", "stat": "max_hp", "value": 35},
        ],
    )
    manual = _manuals(attack=1000, max_hp=1000)
    preview = build_stat_preview(
        _player(max_hp=600), content, equipment=(equipment,), manual_effects=manual,
        constitution_effect={"type": "max_hp_bp", "value": 1500},
    )
    hp_before_percentage = 230 + 600 + 7 // 2 + 35 // 2
    attack_before_percentage = 15 + 9 // 2 + 7 // 2 + 3 * 2 // 2
    assert preview["derived_stats"]["max_hp"] == hp_before_percentage * 12_500 // 10_000
    assert preview["derived_stats"]["attack"] == attack_before_percentage * 11_000 // 10_000
    assert preview["combat_stats"]["max_mana"] == 200 + 11 // 2
    source = next(item for item in preview["source_refs"] if item["key"] == "equipment")
    equipment["effects"][0]["value"] = 9999
    manual["combat_stat_bonus_bp"]["max_hp"] = 9999
    assert source["value"]["effects"][0]["value"] == 7
    assert next(item for item in preview["source_refs"] if item["key"] == "manual")["value"]["combat_stat_bonus_bp"]["max_hp"] == 1000


def test_broken_equipment_grants_no_affix_effect_or_tempering(content: ContentBundle) -> None:
    item = _equipment(
        durability_bp=0, temper_level=10, affixes={"hp": 70},
        effects=[{"type": "flat_stat", "stat": "physical_damage", "value": 60}],
    )
    assert build_stat_preview(_player(), content, equipment=(item,))["combat_stats"] == build_stat_preview(_player(), content)["combat_stats"]


def test_manual_reflection_and_equipment_share_content_cap(content: ContentBundle) -> None:
    manual = _manuals()
    manual["damage_reflection_bp"] = 4000
    item = _equipment(affixes={"reflection": 3000})
    preview = build_stat_preview(_player(), content, equipment=(item,), manual_effects=manual)
    assert preview["combat_stats"]["damage_reflection_bp"] == 5000
    assert next(source for source in preview["source_refs"] if source["key"] == "manual")["effect"]["damage_reflection_bp"] == 4000
    assert {"code": "STAT_CAP_APPLIED", "stat_key": "damage_reflection_bp", "cap": 5000} in preview["warnings"]
    changed = _changed_content(content, lambda rules: rules["combat_caps"].update(damage_reflection_bp=4500))
    assert build_stat_preview(_player(), changed, equipment=(item,), manual_effects=manual)["combat_stats"]["damage_reflection_bp"] == 4500


def test_formula_changes_update_both_projections_and_fingerprint(content: ContentBundle) -> None:
    item = _equipment(temper_level=2)
    before = build_stat_preview(_player(), content, equipment=(item,))
    changed = _changed_content(content, lambda rules: rules["formulas"].update(max_hp_body=9, attack_base=17, attack_body_divisor=5, weapon_temper_attack=3))
    after = build_stat_preview(_player(), changed, equipment=(item,))
    assert after["combat_stats"]["max_hp"] == after["derived_stats"]["max_hp"] == 240
    assert after["combat_stats"]["attack"] == after["derived_stats"]["attack"] == 17 + 10 // 5 + 2 * 3
    assert before["formula_fingerprint"] != after["formula_fingerprint"]


@pytest.mark.parametrize("value", (True, 1.5, "3", -1))
@pytest.mark.parametrize("field", ("max_hp", "max_mp", "initiative", "carry_capacity", "exploration_efficiency_bp"))
def test_permanent_values_are_nonnegative_integers(content: ContentBundle, field: str, value) -> None:
    with pytest.raises(ValueError):
        build_stat_preview(_player(**{field: value}), content)


@pytest.mark.parametrize("value", (True, 10.0, "10", 16, 4))
def test_qualification_is_not_silently_normalized(content: ContentBundle, value) -> None:
    row = _player()
    row["qualification"]["body"] = value
    with pytest.raises(ValueError):
        build_stat_preview(row, content)


def test_duplicate_qualification_json_is_rejected(content: ContentBundle) -> None:
    row = _player()
    qualification = row.pop("qualification")
    row["qualification_json"] = '{"body":3,' + json.dumps(qualification)[1:]
    with pytest.raises(ValueError):
        build_stat_preview(row, content)


@pytest.mark.parametrize(
    "change",
    (
        lambda item: item.pop("effects"),
        lambda item: item.pop("affixes"),
        lambda item: item.update(durability_bp=True),
        lambda item: item.update(durability_bp=10001),
        lambda item: item.update(temper_level=1.5),
        lambda item: item.update(slot="bag"),
        lambda item: item.update(affixes={"damage": "3"}),
        lambda item: item.update(affixes={"unknown": 3}),
        lambda item: item.update(effects=[{"type": "flat_stat", "stat": "max_hp", "value": True}]),
        lambda item: item.update(effects=[{"type": "flat_stat", "stat": "unknown", "value": 3}]),
        lambda item: item.update(effects=[{"type": "unknown", "stat": "max_hp", "value": 3}]),
    ),
)
def test_equipment_sources_fail_closed(content: ContentBundle, change) -> None:
    item = _equipment()
    change(item)
    with pytest.raises(ValueError):
        build_stat_preview(_player(), content, equipment=(item,))


def test_duplicate_equipment_slots_are_rejected(content: ContentBundle) -> None:
    with pytest.raises(ValueError):
        build_stat_preview(_player(), content, equipment=(_equipment(), _equipment()))


@pytest.mark.parametrize(
    "change",
    (
        lambda rules: rules["formulas"].pop("attack_base"),
        lambda rules: rules["formulas"].update(attack_base=True),
        lambda rules: rules["formulas"].update(attack_body_divisor=0),
        lambda rules: rules["formulas"].update(weapon_temper_attack=2.0),
        lambda rules: rules.pop("combat_caps"),
        lambda rules: rules["combat_caps"].pop("anti_crit_bp"),
        lambda rules: rules["combat_caps"].update(anti_crit_bp="1"),
        lambda rules: rules["combat_caps"].update(evasion_bp=10001),
    ),
)
def test_incomplete_or_invalid_formula_parameters_are_rejected(content: ContentBundle, change) -> None:
    with pytest.raises(ContentError):
        stats_formula(_changed_content(content, change))


@pytest.mark.parametrize(
    "change",
    (
        lambda manual: manual.pop("combat_stat_bonus_bp"),
        lambda manual: manual["combat_stat_bonus_bp"].pop("attack"),
        lambda manual: manual["combat_stat_bonus_bp"].update(max_mana=100),
        lambda manual: manual["combat_stat_bonus_bp"].update(max_hp=1.5),
        lambda manual: manual.update(damage_reflection_bp=True),
        lambda manual: manual.update(cultivation_gain_bp=-1),
    ),
)
def test_manual_sources_require_typed_effects(content: ContentBundle, change) -> None:
    manual = _manuals()
    change(manual)
    with pytest.raises(ValueError):
        build_stat_preview(_player(), content, manual_effects=manual)


@pytest.mark.parametrize("effect", ({"type": "unknown", "value": 10}, {"type": "max_hp_bp", "value": True}, {"type": "max_hp_bp"}))
def test_constitution_sources_fail_closed(content: ContentBundle, effect: dict) -> None:
    with pytest.raises(ValueError):
        build_stat_preview(_player(), content, constitution_effect=effect)


@pytest.mark.parametrize("effect_type", ("production_quality_bp", "drop_weight_bp"))
def test_noncombat_constitutions_do_not_change_combat_stats(content: ContentBundle, effect_type: str) -> None:
    plain = build_stat_preview(_player(), content)
    changed = build_stat_preview(_player(), content, constitution_effect={"type": effect_type, "value": 500})
    assert changed["combat_stats"] == plain["combat_stats"]


@pytest.mark.parametrize("value", (True, 1.5, "4", -1))
def test_frozen_combat_values_never_recompute_or_coerce(content: ContentBundle, value) -> None:
    stats = build_stat_preview(_player(), content)["combat_stats"]
    stats["max_hp"] = value
    with pytest.raises(ValueError):
        frozen_combat_stats({"stats": stats, "qualification": dict.fromkeys(STAT_KEYS, 10)})


def test_frozen_combat_requires_complete_snapshot_and_returns_copy(content: ContentBundle) -> None:
    stats = build_stat_preview(_player(), content)["combat_stats"]
    assert frozen_combat_stats({"stats": stats}) == stats
    assert frozen_combat_stats({"stats": stats}) is not stats
    for invalid in ({}, stats, {"stats": {"max_hp": 1, "attack": 1, "initiative": 0, "agility": 0}}):
        with pytest.raises(ValueError):
            frozen_combat_stats(invalid)
    with pytest.raises(ValueError):
        frozen_combat_stats({"stats": {**stats, "unexpected": 1}})


@pytest.mark.parametrize("field", ("snapshot_id", "player_id", "base_stats", "path_stats", "derived_stats", "source_refs", "formula_fingerprint", "purpose", "created_at"))
def test_snapshot_fields_are_required_without_compatibility_defaults(content: ContentBundle, field: str) -> None:
    payload = _snapshot_payload(content)
    payload.pop(field)
    with pytest.raises(StatSnapshotError):
        StatSnapshot.from_payload(payload)


@pytest.mark.parametrize(
    "change",
    (
        lambda payload: payload.update(player_id=True),
        lambda payload: payload.update(player_id=1.5),
        lambda payload: payload["derived_stats"].update(max_hp="230"),
        lambda payload: payload["derived_stats"].update(max_mp=1.5),
        lambda payload: payload["derived_stats"].pop("attack"),
        lambda payload: payload["base_stats"].update(body=11),
        lambda payload: payload.update(source_refs=[]),
        lambda payload: payload["source_refs"][0].pop("multiplier_zone"),
        lambda payload: payload["source_refs"].pop(),
        lambda payload: payload["source_refs"].append(deepcopy(payload["source_refs"][0])),
        lambda payload: payload["source_refs"][1]["value"].update(body=11),
        lambda payload: payload.update(purpose=""),
        lambda payload: payload.update(created_at="2026-10-07T00:00:00"),
    ),
)
def test_snapshot_semantic_corruption_is_rejected(content: ContentBundle, change) -> None:
    payload = _snapshot_payload(content)
    change(payload)
    with pytest.raises(StatSnapshotError):
        StatSnapshot.from_payload(payload)


def test_frozen_snapshot_does_not_read_changed_formula_and_payload_does_not_alias(content: ContentBundle) -> None:
    payload = _snapshot_payload(content)
    stored = StatSnapshot.from_payload(payload)
    changed = _changed_content(content, lambda rules: rules["formulas"].update(max_hp_body=100))
    assert build_stat_preview(_player(), changed)["derived_stats"]["max_hp"] != stored.derived_stats["max_hp"]
    assert StatSnapshot.from_payload(payload).payload() == stored.payload()
    outgoing = stored.payload()
    qualification_source = next(item for item in outgoing["source_refs"] if item["key"] == "qualification")
    qualification_source["value"]["body"] = 999
    assert next(item for item in stored.source_refs if item["key"] == "qualification")["value"]["body"] == 10


def test_constitution_keeps_explicit_high_tier_scale(content: ContentBundle) -> None:
    stats = build_stat_preview(_player(), content)["combat_stats"]
    stats.update(max_hp=80_000, attack=8_000, initiative=1_000, agility=400)
    result = apply_constitution_combat_effect(stats, {"type": "max_hp_bp", "value": 1000})
    assert result["max_hp"] == 88_000
    assert result["attack"] == 8_000
    assert stats["max_hp"] == 80_000
