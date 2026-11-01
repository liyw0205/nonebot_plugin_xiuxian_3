"""Seeker-stage onboarding: the gap between 寻仙问道 and 入道.

The tier tables are derived from content, so these tests pin both the new guide
records and the tier availability that keeps them reachable after 入道 rather
than turning into content a player outgrows before seeing it.
"""

from __future__ import annotations

from pathlib import Path

from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle
from nonebot_plugin_xiuxian_3.xiuxian.player import intro_rules

DATA = Path(__file__).parents[1] / "data"
NEW_GUIDES = ("guide.seeker_path_hint", "guide.seeker_sect_gate")


def test_seeker_guides_follow_the_guide_contract() -> None:
    bundle = ContentBundle.load(DATA)
    path_hint = intro_rules.guide_definition("guide.seeker_path_hint", bundle)
    assert path_hint["stage"] == "seeker"
    assert path_hint["locations"] == ()
    assert path_hint["output_type"] == "intro_flag"
    assert path_hint["cost"] == {}

    sect_gate = intro_rules.guide_definition("guide.seeker_sect_gate", bundle)
    assert sect_gate["stage"] == "seeker"
    assert sect_gate["locations"] == ("xuantian.sect_gate",)
    assert sect_gate["cost"] == {"resource_key": "stamina", "amount": 1}
    assert sect_gate["output_type"] == "intro_flag"


def test_seeker_stage_offers_the_new_guides_and_mortal_does_not() -> None:
    bundle = ContentBundle.load(DATA)
    mortal = {guide["key"] for guide in intro_rules.guides_for_stage("mortal", bundle)}
    seeker = {guide["key"] for guide in intro_rules.guides_for_stage("seeker", bundle)}
    assert set(NEW_GUIDES).isdisjoint(mortal), "mortal players must not see seeker guides"
    assert set(NEW_GUIDES) <= seeker, "seeker players must see the new guides"
    # The mortal lessons stay available through the seeker stopover.
    assert {"guide.read_world", "guide.gather_blood_grass", "guide.choose_service"} <= seeker


def test_seeker_guides_stay_reachable_after_joining_the_path() -> None:
    """A guide a player outgrows in one stage would be unreachable content."""

    bundle = ContentBundle.load(DATA)
    cultivator = {guide["key"] for guide in intro_rules.guides_for_stage("cultivator", bundle)}
    assert set(NEW_GUIDES) <= cultivator
    assert {"guide.mine_entry", "guide.dispatch_entry", "guide.secret_realm_entry"} <= cultivator


def test_graduation_set_is_still_the_mortal_trio() -> None:
    bundle = ContentBundle.load(DATA)
    assert intro_rules.mortal_guides(bundle) == intro_rules.INTRO_GUIDES


def test_seeker_guides_resolve_by_alias() -> None:
    bundle = ContentBundle.load(DATA)
    assert intro_rules.resolve_guide("道途指引", bundle) == "guide.seeker_path_hint"
    assert intro_rules.resolve_guide("山门指引", bundle) == "guide.seeker_sect_gate"
