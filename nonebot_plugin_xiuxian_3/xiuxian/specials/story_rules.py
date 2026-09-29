"""Branching story rules."""

from __future__ import annotations

from dataclasses import dataclass


STORY_KEY = "story.xuantian.road"
ENDING_REPUTATION = 10


@dataclass(frozen=True, slots=True)
class StoryBranchDefinition:
    key: str
    label: str
    required_source_count: int
    source_kind: str
    source_label: str
    ending_key: str
    flag_key: str
    codex_entry_key: str
    appearance_key: str


BRANCHES: dict[str, StoryBranchDefinition] = {
    "merchant": StoryBranchDefinition(
        key="merchant",
        label="商路",
        required_source_count=3,
        source_kind="commission",
        source_label="已交付城镇委托",
        ending_key="ending.merchant",
        flag_key="flag.road.merchant",
        codex_entry_key="codex.story.xuantian.road.merchant",
        appearance_key="appearance.home.merchant",
    ),
    "warden": StoryBranchDefinition(
        key="warden",
        label="守望",
        required_source_count=2,
        source_kind="battle",
        source_label="已结算战斗胜利",
        ending_key="ending.warden",
        flag_key="flag.road.warden",
        codex_entry_key="codex.story.xuantian.road.warden",
        appearance_key="appearance.home.warden",
    ),
    "gardener": StoryBranchDefinition(
        key="gardener",
        label="药圃",
        required_source_count=2,
        source_kind="gardener",
        source_label="灵田收获或成功药材派遣",
        ending_key="ending.gardener",
        flag_key="flag.road.gardener",
        codex_entry_key="codex.story.xuantian.road.gardener",
        appearance_key="appearance.home.gardener",
    ),
}


def resolve_branch(value: str) -> str | None:
    normalized = value.strip().casefold()
    aliases = {
        "商路": "merchant",
        "商人": "merchant",
        "守望": "warden",
        "守望者": "warden",
        "药圃": "gardener",
        "园丁": "gardener",
    }
    key = aliases.get(normalized, normalized.removeprefix("choice."))
    return key if key in BRANCHES else None


def completed_nodes(branch_key: str, evidence_count: int) -> tuple[str, ...]:
    definition = BRANCHES[branch_key]
    if definition.source_kind == "commission":
        return tuple(f"node.merchant.{index}" for index in range(1, evidence_count + 1))
    prefix = branch_key
    return ("node.arrival",) + tuple(
        f"node.{prefix}.{index}" for index in range(1, evidence_count + 1)
    )


__all__ = [
    "BRANCHES",
    "ENDING_REPUTATION",
    "STORY_KEY",
    "StoryBranchDefinition",
    "completed_nodes",
    "resolve_branch",
]
