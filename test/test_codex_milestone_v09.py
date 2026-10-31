"""Contract for the v0.9 codex milestone groups built over existing entries."""

from __future__ import annotations

from pathlib import Path

from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle
from nonebot_plugin_xiuxian_3.xiuxian.rewards.rules import local_reputation_maximum

DATA = Path(__file__).parents[1] / "data"

EXPECTED = {
    "codex.place.materials_three": (
        ["codex.place.ironwood_grove", "codex.place.basalt_pass", "codex.place.cloud_mine"],
        "local.xuantian.new_town",
        6,
    ),
    "codex.place.grotto_three": (
        ["codex.place.mist_grotto", "codex.place.mist_grotto_2", "codex.place.floating_boat"],
        "local.xuantian.new_town",
        8,
    ),
    "codex.place.city_three": (
        ["codex.place.cloud_city", "codex.place.floating_boat", "codex.place.herb_vale"],
        "local.xuantian.cloud_city",
        8,
    ),
}


def test_v09_milestones_follow_the_milestone_contract() -> None:
    bundle = ContentBundle.load(DATA)
    for key, (entries, reputation, amount) in EXPECTED.items():
        record = bundle.require("codex_milestone", key)
        assert record["entry_keys"] == entries, key
        assert record["status"] == "active", key
        assert record["unlocks"] == [], key
        reward = record["reward"]
        assert reward["type"] == "local_reputation", key
        assert reward["reputation_key"] == reputation, key
        assert reward["amount"] == amount, key
        assert isinstance(reward["name"], str) and reward["name"].strip(), key


def test_v09_milestone_entries_and_reputations_resolve() -> None:
    """Every referenced entry exists and every reputation key has a real ceiling."""

    bundle = ContentBundle.load(DATA)
    milestones = bundle.list("codex_milestone")
    assert len(milestones) == 15, len(milestones)
    seen_entry_sets: set[tuple[str, ...]] = set()
    for record in milestones:
        assert len(set(record["entry_keys"])) == len(record["entry_keys"]), record["key"]
        for entry in record["entry_keys"]:
            assert bundle.get("codex_entry", entry, include_locked=False) is not None, (
                record["key"],
                entry,
            )
        reward = record["reward"]
        if reward.get("type") == "local_reputation" or "reputation_key" in reward:
            assert local_reputation_maximum(reward["reputation_key"], bundle) > 0, record["key"]
        signature = tuple(sorted(record["entry_keys"]))
        assert signature not in seen_entry_sets, f"duplicate milestone entry set: {record['key']}"
        seen_entry_sets.add(signature)
