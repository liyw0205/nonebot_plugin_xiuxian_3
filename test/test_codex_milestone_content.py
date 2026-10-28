"""Content contract for the extended codex milestone set."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle
from nonebot_plugin_xiuxian_3.xiuxian.rewards.rules import local_reputation_maximum
from nonebot_plugin_xiuxian_3.xiuxian.specials.codex_rules import codex_milestones

DATA = Path(__file__).parents[1] / "data"
SHIPPED = (
    "codex.xuantian.place_3",
    "codex.xuantian.materials_5",
    "codex.xuantian.creature_3",
    "codex.paths_6",
    "codex.cloud_city.discovery_3",
    "codex.domain.frontier_records_3",
    "codex.challenge.trials_3",
    "codex.story.threads_3",
    "codex.route.three_roads",
    "codex.service.town_three",
    "codex.place.xuantian_five",
    "codex.challenge.domain_3",
)


class MutableClock:
    def __init__(self, value: datetime):
        self.value = value

    def __call__(self) -> datetime:
        return self.value


def _context(user_id: str, request_id: str) -> CommandContext:
    return CommandContext(adapter="web", user_id=user_id, request_id=request_id)


def test_milestones_cover_every_referenced_entry_with_a_real_reward() -> None:
    bundle = ContentBundle.load(DATA)
    milestones = codex_milestones(bundle)
    assert tuple(milestones) == SHIPPED
    assert len(milestones) == 12

    for key, definition in milestones.items():
        assert definition.entry_keys, key
        for entry_key in definition.entry_keys:
            assert bundle.has("codex_entry", entry_key, include_locked=True), (key, entry_key)
        if definition.reputation_key:
            assert local_reputation_maximum(definition.reputation_key, bundle) > 0, key
            assert definition.reputation_reward > 0, key
            assert definition.reputation_name, key
        for unlock in definition.unlocks:
            assert bundle.has("codex_unlock", unlock, include_locked=False), (key, unlock)

    added = SHIPPED[6:]
    for key in added:
        assert milestones[key].entry_keys
    assert milestones["codex.place.xuantian_five"].reputation_key == (
        "local.xuantian.cloud_city"
    )


def test_codex_status_lists_every_milestone_in_order() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            user = "codex-milestones"
            await runtime.dispatch(_context(user, "create"), "开始修仙")
            await runtime.dispatch(_context(user, "seek"), "寻仙问道")
            status = await runtime.dispatch(_context(user, "codex"), "图鉴")
            milestones = status.data["milestones"]
            assert [item["milestone_key"] for item in milestones] == list(SHIPPED)
            assert milestones[6]["milestone_key"] == "codex.challenge.trials_3"
            await runtime.close()

    asyncio.run(run())
