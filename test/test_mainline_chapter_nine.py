"""The mainline must not end at chapter 8.

`chapter.8.stage.3` shipped with `next_stage_key: null`, so the玄天 mainline stopped
after 24 stages. This module pins the chapter 9 slice and the chain that reaches it.
"""

from __future__ import annotations

from pathlib import Path

from nonebot_plugin_xiuxian_3.xiuxian.adventures.mainline import MAINLINE_STAGES
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

CHAPTER_NINE = ("chapter.9.stage.1", "chapter.9.stage.2", "chapter.9.stage.3")


def _stages() -> dict[str, object]:
    return {stage.key: stage for stage in MAINLINE_STAGES}


def test_the_mainline_continues_past_chapter_eight() -> None:
    stages = _stages()
    chapters = [key for key in stages if key.startswith("chapter.")]
    assert len(chapters) == 27
    for key in CHAPTER_NINE:
        assert key in stages, key
        stage = stages[key]
        assert stage.label and stage.body
        assert stage.required_realm == "golden_core"
        assert stage.runtime_status == "open"
        assert stage.first_clear_reward and stage.repeat_reward
        assert stage.retry_message


def test_the_chain_runs_from_chapter_eight_into_chapter_nine_and_stops() -> None:
    stages = _stages()
    assert stages["chapter.8.stage.3"].next_stage_key == "chapter.9.stage.1"
    assert stages["chapter.9.stage.1"].next_stage_key == "chapter.9.stage.2"
    assert stages["chapter.9.stage.2"].next_stage_key == "chapter.9.stage.3"
    assert stages["chapter.9.stage.3"].next_stage_key is None
    # Prerequisites follow the same order, so the chain is actually walkable.
    assert tuple(stages["chapter.9.stage.1"].prerequisites) == ("chapter.8.stage.3",)
    assert tuple(stages["chapter.9.stage.2"].prerequisites) == ("chapter.9.stage.1",)
    assert tuple(stages["chapter.9.stage.3"].prerequisites) == ("chapter.9.stage.2",)


def test_chapter_nine_objectives_reference_live_content() -> None:
    bundle = ContentBundle.load(DATA)
    stages = _stages()
    modes = {row["key"]: row for row in bundle.list("exploration_mode", include_locked=False)}
    locations = {row["key"] for row in bundle.list("location", include_locked=False)}

    first = stages["chapter.9.stage.1"].objectives[0]
    assert first["type"] == "travel_arrival"
    assert first["destination_key"] in locations

    escort = stages["chapter.9.stage.2"].objectives[0]
    assert escort["type"] == "exploration_battle_victory"
    assert modes[escort["mode_key"]]["location_key"] == escort["location_key"]
    assert modes[escort["mode_key"]]["battle_chance_bp"] > 0
    assert escort["location_key"] in locations

    ledger = stages["chapter.9.stage.3"].objectives[0]
    assert ledger["type"] == "exploration_reward"
    assert modes[ledger["mode_key"]]["location_key"] == ledger["location_key"]
    assert ledger["quantity"] == 1
    # The reward the objective asks for is really served by that mode's pool.
    pool = next(
        row
        for row in bundle.list("reward", include_locked=False)
        if row["key"] == modes[ledger["mode_key"]]["reward_pool_key"]
    )
    served = {
        item
        for outcome in pool["outcomes"]
        for item in (outcome.get("rewards") or {})
    }
    assert ledger["item_key"] in served, sorted(served)


def test_chapter_nine_stages_are_announced_in_the_journal() -> None:
    """Each new stage writes its own activity event so the journal can show it."""

    stages = _stages()
    for key in CHAPTER_NINE:
        stage = stages[key]
        assert stage.state_events == (f"story.mainline.xuantian:{key}",)
        assert stage.actions, key
        for action in stage.actions:
            assert action["command"] and action["argument"] and action["description"]
