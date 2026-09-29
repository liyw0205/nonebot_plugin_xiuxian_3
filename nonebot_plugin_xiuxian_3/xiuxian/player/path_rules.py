"""Pure rules for first path and sub-profession selection."""

from __future__ import annotations

from ..content import ContentBundle, ContentError, bundled_content


PATH_LABELS = {
    "body": "体修",
    "spell": "法修",
    "device": "器修",
    "demonic": "魔修",
    "beast": "妖修",
    "support": "辅修",
}

PATH_ALIASES = {
    **{key: key for key in PATH_LABELS},
    **{label: key for key, label in PATH_LABELS.items()},
}

SUBPROFESSION_LABELS = {
    "alchemy": "炼丹",
    "artifice": "炼器",
    "formation": "布阵",
}

SUBPROFESSION_ALIASES = {
    **{key: key for key in SUBPROFESSION_LABELS},
    **{label: key for key, label in SUBPROFESSION_LABELS.items()},
}

def resolve_path(value: str) -> str | None:
    return PATH_ALIASES.get(value.strip())


def resolve_subprofession(value: str) -> str | None:
    return SUBPROFESSION_ALIASES.get(value.strip())


def reward_items(
    path_key: str,
    subprofession_key: str | None,
    content: ContentBundle | None = None,
) -> tuple[tuple[str, int], ...]:
    bundle = content or bundled_content()
    path = bundle.get("path", path_key, include_locked=False)
    if path is None:
        raise ContentError(f"unknown active path: {path_key}")
    skill_key = path.get("active_skill")
    if not isinstance(skill_key, str) or not bundle.has("skill", skill_key, include_locked=False):
        raise ContentError(f"path {path_key} references an unavailable active skill")

    item_rewards = path.get("entry_item_rewards")
    if not isinstance(item_rewards, list):
        raise ContentError(f"path {path_key} entry_item_rewards must be a list")
    rows: list[tuple[str, int]] = []
    for reward in item_rewards:
        if not isinstance(reward, dict):
            raise ContentError(f"path {path_key} has an invalid entry item reward")
        item_key = reward.get("item_key")
        quantity = reward.get("quantity")
        if (
            not isinstance(item_key, str)
            or isinstance(quantity, bool)
            or not isinstance(quantity, int)
            or quantity <= 0
        ):
            raise ContentError(f"path {path_key} has an invalid entry item reward")
        if not bundle.has("item", item_key, include_locked=False):
            raise ContentError(f"path {path_key} rewards an unavailable item: {item_key}")
        rows.append((item_key, quantity))

    by_subprofession = path.get("subprofession_item_rewards", {})
    if not isinstance(by_subprofession, dict):
        raise ContentError(f"path {path_key} subprofession_item_rewards must be an object")
    if path_key == "support":
        rewards = by_subprofession.get(subprofession_key or "")
        if not isinstance(rewards, list):
            raise ContentError(f"path {path_key} has no entry rewards for {subprofession_key}")
        for reward in rewards:
            if not isinstance(reward, dict):
                raise ContentError(f"path {path_key} has an invalid sub-profession reward")
            item_key = reward.get("item_key")
            quantity = reward.get("quantity")
            if (
                not isinstance(item_key, str)
                or isinstance(quantity, bool)
                or not isinstance(quantity, int)
                or quantity <= 0
            ):
                raise ContentError(f"path {path_key} has an invalid sub-profession reward")
            if not bundle.has("item", item_key, include_locked=False):
                raise ContentError(f"path {path_key} rewards an unavailable item: {item_key}")
            rows.append((item_key, quantity))
    elif subprofession_key is not None:
        raise ContentError(f"path {path_key} cannot select a sub-profession")

    return (*rows[:1], (skill_key, 1), *rows[1:])
