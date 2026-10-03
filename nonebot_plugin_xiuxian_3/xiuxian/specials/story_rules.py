"""Content-backed rules for the branching story."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..content import ContentBundle, ContentError, bundled_content
from ..rewards.rules import RewardContentError, reward_definition


STORY_KEY = "story.xuantian.road"
CLAIM_OPERATION = "specials.claim_story_ending"
_SOURCE_KINDS = {"commission", "battle", "harvest_or_dispatch"}


class StoryContentError(ContentError):
    """Raised when the active story definition is incomplete or inconsistent."""


@dataclass(frozen=True, slots=True)
class StoryBranchDefinition:
    key: str
    label: str
    description: str
    aliases: tuple[str, ...]
    required_source_count: int
    source_kind: str
    source_label: str
    ending_key: str
    flag_key: str
    codex_entry_key: str
    appearance_key: str
    completed_nodes: tuple[str, ...]
    harvest_operation_name: str | None
    dispatch_key: str | None


@dataclass(frozen=True, slots=True)
class StoryDefinition:
    key: str
    name: str
    description: str
    entry_node: str
    reward_key: str
    reputation_key: str
    branches: tuple[StoryBranchDefinition, ...]


def story_definition(
    content: ContentBundle | None = None,
    *,
    include_locked: bool = False,
    validate_reward: bool = True,
) -> StoryDefinition:
    bundle = content or bundled_content()
    try:
        row = bundle.require("story", STORY_KEY, include_locked=include_locked)
    except KeyError as exc:
        raise StoryContentError(f"story content is unavailable: {STORY_KEY}") from exc

    name = _required_text(row, "name", STORY_KEY)
    description = _required_text(row, "desc", STORY_KEY)
    entry_node = _required_text(row, "entry_node", STORY_KEY)
    reward_key = _required_text(row, "reward_key", STORY_KEY)
    reputation_key = _required_text(row, "reputation_key", STORY_KEY)
    if validate_reward:
        try:
            reward = reward_definition(reward_key, bundle, operation=CLAIM_OPERATION)
        except RewardContentError as exc:
            raise StoryContentError(f"story {STORY_KEY} has an invalid ending reward") from exc
        if (
            reward.assets
            or reward.value_delta
            or reward.set_values
            or reward.reputation
            or set(reward.local_reputation) != {reputation_key}
        ):
            raise StoryContentError(
                f"story {STORY_KEY} ending reward must grant only its declared local reputation"
            )

    raw_branches = row.get("branches")
    if not isinstance(raw_branches, list) or not raw_branches:
        raise StoryContentError(f"story {STORY_KEY} requires branches")
    branches: list[StoryBranchDefinition] = []
    seen_keys: set[str] = set()
    for index, raw in enumerate(raw_branches):
        label = f"story {STORY_KEY} branch {index}"
        if not isinstance(raw, dict):
            raise StoryContentError(f"{label} must be an object")
        key = _required_text(raw, "key", label)
        if key in seen_keys:
            raise StoryContentError(f"{label} duplicates key {key}")
        seen_keys.add(key)
        branch_label = _required_text(raw, "name", label)
        branch_description = _required_text(raw, "desc", label)
        source_label = _required_text(raw, "source_label", label)
        source_kind = _required_text(raw, "source_kind", label)
        if source_kind not in _SOURCE_KINDS:
            raise StoryContentError(f"{label} has unsupported source_kind {source_kind!r}")
        required_count = raw.get("required_source_count")
        if isinstance(required_count, bool) or not isinstance(required_count, int) or required_count <= 0:
            raise StoryContentError(f"{label} requires a positive required_source_count")
        aliases = _text_list(raw.get("aliases"), "aliases", label)
        nodes = _text_list(raw.get("completed_nodes"), "completed_nodes", label)
        if len(nodes) < required_count or len(set(nodes)) != len(nodes):
            raise StoryContentError(f"{label} completed_nodes must cover its source requirement")

        ending_key = _required_text(raw, "ending_key", label)
        flag_key = _required_text(raw, "flag_key", label)
        codex_key = _required_text(raw, "codex_entry_key", label)
        appearance_key = _required_text(raw, "appearance_key", label)
        if not flag_key.startswith("flag.") or not appearance_key.startswith("appearance."):
            raise StoryContentError(f"{label} has an invalid story unlock key")
        try:
            bundle.require("codex_entry", codex_key, include_locked=include_locked)
        except KeyError as exc:
            raise StoryContentError(f"{label} references an inactive codex entry {codex_key}") from exc
        harvest_operation_name = None
        dispatch_key = None
        if source_kind == "harvest_or_dispatch":
            harvest_operation_name = _required_text(raw, "harvest_operation_name", label)
            dispatch_key = _required_text(raw, "dispatch_key", label)
            if not harvest_operation_name.startswith("livelihood.") or not dispatch_key.startswith("dispatch."):
                raise StoryContentError(f"{label} has invalid harvest or dispatch source keys")

        branches.append(
            StoryBranchDefinition(
                key=key,
                label=branch_label,
                description=branch_description,
                aliases=aliases,
                required_source_count=required_count,
                source_kind=source_kind,
                source_label=source_label,
                ending_key=ending_key,
                flag_key=flag_key,
                codex_entry_key=codex_key,
                appearance_key=appearance_key,
                completed_nodes=nodes,
                harvest_operation_name=harvest_operation_name,
                dispatch_key=dispatch_key,
            )
        )
    return StoryDefinition(
        key=STORY_KEY,
        name=name,
        description=description,
        entry_node=entry_node,
        reward_key=reward_key,
        reputation_key=reputation_key,
        branches=tuple(branches),
    )


def resolve_branch(value: str, content: ContentBundle | None = None) -> str | None:
    normalized = value.strip().casefold()
    for branch in story_definition(
        content,
        include_locked=True,
        validate_reward=False,
    ).branches:
        if normalized in {branch.key.casefold(), branch.label.casefold()} or any(
            normalized == alias.casefold() for alias in branch.aliases
        ):
            return branch.key
    return None


def _required_text(row: dict[str, Any], field: str, label: str) -> str:
    value = row.get(field)
    if not isinstance(value, str) or not value.strip():
        raise StoryContentError(f"{label} requires non-empty {field}")
    return value.strip()


def _text_list(value: Any, field: str, label: str) -> tuple[str, ...]:
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(item, str) or not item.strip() for item in value)
    ):
        raise StoryContentError(f"{label} requires a non-empty string list for {field}")
    return tuple(item.strip() for item in value)


__all__ = [
    "CLAIM_OPERATION",
    "STORY_KEY",
    "StoryBranchDefinition",
    "StoryContentError",
    "StoryDefinition",
    "resolve_branch",
    "story_definition",
]
