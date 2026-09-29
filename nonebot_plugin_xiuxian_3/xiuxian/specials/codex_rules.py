"""Validated content definitions for discovery entries and milestones."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from ..content import ContentBundle, ContentError, bundled_content


@dataclass(frozen=True, slots=True)
class CodexEntryDefinition:
    key: str
    category: str
    label: str
    desc: str


@dataclass(frozen=True, slots=True)
class CodexMilestoneDefinition:
    key: str
    label: str
    desc: str
    entry_keys: tuple[str, ...]
    reputation_key: str | None
    reputation_name: str | None
    reputation_reward: int
    unlocks: tuple[str, ...]


@lru_cache(maxsize=1)
def _default_content() -> ContentBundle:
    return bundled_content()


def _content(content: ContentBundle | None) -> ContentBundle:
    return content if content is not None else _default_content()


def codex_entry_definitions(content: ContentBundle | None = None) -> dict[str, CodexEntryDefinition]:
    bundle = _content(content)
    categories = {row["key"] for row in bundle.list("codex_category", include_locked=False)}
    result: dict[str, CodexEntryDefinition] = {}
    for row in bundle.list("codex_entry", include_locked=False):
        key = row.get("key")
        category = row.get("category")
        name = row.get("name")
        desc = row.get("desc")
        if not isinstance(key, str) or not isinstance(category, str) or category not in categories:
            raise ContentError(f"codex entry has an invalid category: {key!r}")
        if not isinstance(name, str) or not name.strip() or not isinstance(desc, str) or not desc.strip():
            raise ContentError(f"codex entry {key} requires name and desc")
        result[key] = CodexEntryDefinition(key, category, name.strip(), desc.strip())
    return result


def codex_milestones(content: ContentBundle | None = None) -> dict[str, CodexMilestoneDefinition]:
    bundle = _content(content)
    entries = codex_entry_definitions(bundle)
    unlock_keys = {row["key"] for row in bundle.list("codex_unlock", include_locked=False)}
    result: dict[str, CodexMilestoneDefinition] = {}
    for row in bundle.list("codex_milestone", include_locked=False):
        key = row.get("key")
        name = row.get("name")
        desc = row.get("desc")
        entry_keys = row.get("entry_keys")
        unlocks = row.get("unlocks", [])
        reward = row.get("reward", {})
        if not isinstance(key, str) or not isinstance(name, str) or not name.strip():
            raise ContentError(f"codex milestone requires key and name: {key!r}")
        if not isinstance(desc, str) or not desc.strip():
            raise ContentError(f"codex milestone {key} requires desc")
        if (
            not isinstance(entry_keys, list)
            or not entry_keys
            or any(not isinstance(entry_key, str) or entry_key not in entries for entry_key in entry_keys)
            or len(set(entry_keys)) != len(entry_keys)
        ):
            raise ContentError(f"codex milestone {key} has invalid entry_keys")
        if not isinstance(unlocks, list) or any(
            not isinstance(unlock, str) or unlock not in unlock_keys for unlock in unlocks
        ):
            raise ContentError(f"codex milestone {key} has invalid unlocks")
        reputation_key: str | None = None
        reputation_name: str | None = None
        reputation_reward = 0
        if reward:
            if (
                not isinstance(reward, dict)
                or reward.get("type") != "local_reputation"
                or not isinstance(reward.get("reputation_key"), str)
                or not isinstance(reward.get("name"), str)
                or not reward["name"].strip()
                or isinstance(reward.get("amount"), bool)
                or not isinstance(reward.get("amount"), int)
                or reward["amount"] <= 0
            ):
                raise ContentError(f"codex milestone {key} has an invalid reward")
            reputation_key = reward["reputation_key"]
            reputation_name = reward["name"].strip()
            reputation_reward = reward["amount"]
        if not reward and not unlocks:
            raise ContentError(f"codex milestone {key} has no reward")
        result[key] = CodexMilestoneDefinition(
            key=key,
            label=name.strip(),
            desc=desc.strip(),
            entry_keys=tuple(entry_keys),
            reputation_key=reputation_key,
            reputation_name=reputation_name,
            reputation_reward=reputation_reward,
            unlocks=tuple(unlocks),
        )
    return result


def category_labels(content: ContentBundle | None = None) -> dict[str, str]:
    return {
        str(row["key"]): str(row["name"])
        for row in _content(content).list("codex_category", include_locked=False)
    }


def unlock_label(unlock_key: str, content: ContentBundle | None = None) -> str:
    row = _content(content).get("codex_unlock", unlock_key, include_locked=False)
    if row is None:
        return unlock_key
    return str(row["name"])


def category_for_entry(entry_key: str, content: ContentBundle | None = None) -> str | None:
    definition = codex_entry_definitions(content).get(entry_key)
    if definition is not None:
        return definition.category
    if entry_key.startswith(("codex.challenge.", "codex.domain.")):
        return "challenge"
    if entry_key.startswith("codex.story.") or entry_key.startswith("codex.void.archive_"):
        return "story"
    if entry_key.startswith("codex.route.") or entry_key.startswith("codex.void.route_"):
        return "route"
    if entry_key.startswith("codex.dao.service_"):
        return "service"
    return None


def label_for_entry(entry_key: str, content: ContentBundle | None = None) -> str:
    definition = codex_entry_definitions(content).get(entry_key)
    if definition is not None:
        return definition.label
    return entry_key.rsplit(".", 1)[-1].replace("_", " ")


__all__ = [
    "CodexEntryDefinition",
    "CodexMilestoneDefinition",
    "category_for_entry",
    "category_labels",
    "codex_entry_definitions",
    "codex_milestones",
    "label_for_entry",
    "unlock_label",
]
