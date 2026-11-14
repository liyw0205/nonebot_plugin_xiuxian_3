"""The mainline must not end at chapter 8.

`chapter.8.stage.3` shipped with `next_stage_key: null`, so the玄天 mainline stopped
after 24 stages. This module pins the chapter 9 slice and the chain that reaches it.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.xiuxian.adventures.mainline import MAINLINE_STAGES
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle
from nonebot_plugin_xiuxian_3.runtime import create_runtime

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

CHAPTER_NINE = (
    "chapter.9.stage.1",
    "chapter.9.stage.2",
    "chapter.9.stage.3",
    "chapter.9.stage.4",
)


def _stages() -> dict[str, object]:
    return {stage.key: stage for stage in MAINLINE_STAGES}


def test_the_mainline_continues_past_chapter_eight() -> None:
    stages = _stages()
    chapters = [key for key in stages if key.startswith("chapter.")]
    assert len(chapters) == 41
    for key in CHAPTER_NINE:
        assert key in stages, key
        stage = stages[key]
        assert stage.label and stage.body
        assert stage.required_realm == "golden_core"
        assert stage.runtime_status == "open"
        assert stage.first_clear_reward and stage.repeat_reward
        assert stage.retry_message


def test_the_chain_runs_from_chapter_eight_into_chapter_ten() -> None:
    stages = _stages()
    assert stages["chapter.8.stage.3"].next_stage_key == "chapter.9.stage.1"
    assert stages["chapter.9.stage.1"].next_stage_key == "chapter.9.stage.2"
    assert stages["chapter.9.stage.2"].next_stage_key == "chapter.9.stage.3"
    assert stages["chapter.9.stage.3"].next_stage_key == "chapter.10.stage.1"
    assert stages["chapter.9.stage.4"].next_stage_key is None
    assert tuple(stages["chapter.9.stage.4"].prerequisites) == ("chapter.9.stage.3",)
    assert stages["chapter.9.stage.4"].lane == "chapter9_cloud_ledger"
    # Prerequisites follow the same order, so the chain is actually walkable.
    assert tuple(stages["chapter.9.stage.1"].prerequisites) == ("chapter.8.stage.3",)
    assert tuple(stages["chapter.9.stage.2"].prerequisites) == ("chapter.9.stage.1",)
    assert tuple(stages["chapter.9.stage.3"].prerequisites) == ("chapter.9.stage.2",)
    assert tuple(stages["chapter.10.stage.1"].prerequisites) == ("chapter.9.stage.3",)


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

    night_watch = stages["chapter.9.stage.4"].objectives[0]
    assert night_watch == {
        "key": "claim_cloud_ledger_watch",
        "type": "idle_claim",
        "label": "本关开始后完整领取一次云城店铺",
        "route_key": "idle.cloud_city_shop",
    }
    route = bundle.require("livelihood", night_watch["route_key"], include_locked=False)
    assert route["duration_seconds"] == 8 * 60 * 60
    assert route["requirements"]["location_key"] == "xuantian.cloud_city"


def test_chapter_nine_stages_are_announced_in_the_journal() -> None:
    """Each new stage writes its own activity event so the journal can show it."""

    stages = _stages()
    for key in CHAPTER_NINE:
        stage = stages[key]
        assert stage.state_events == (f"story.mainline.xuantian:{key}",)
        assert stage.actions, key
        for action in stage.actions:
            assert action["command"] and action["argument"] and action["description"]


def test_chapter_nine_actions_target_registered_runtime_commands() -> None:
    """Story action links must remain executable by the shared router."""

    runtime = create_runtime(data_dir=DATA)
    registered = set(runtime.router.commands)
    for key in CHAPTER_NINE:
        for action in _stages()[key].actions:
            assert action["command"].lower() in registered, (key, action["command"])


def test_chapter_nine_action_links_reach_application_handlers() -> None:
    """A public action must dispatch to its use case, not stop at routing."""

    async def run() -> None:
        runtime = create_runtime(data_dir=DATA, adapters=("onebot.v11",))
        context = CommandContext(adapter="onebot.v11", user_id="chapter-nine-action-check")
        try:
            for key in CHAPTER_NINE:
                for index, action in enumerate(_stages()[key].actions):
                    result = await runtime.adapters.dispatch(
                        "onebot.v11",
                        context,
                        f"{action['command']} {action['argument']}",
                    )
                    assert result.code != "COMMAND_NOT_FOUND", (key, index, result.message)
        finally:
            await runtime.close()

    asyncio.run(run())
