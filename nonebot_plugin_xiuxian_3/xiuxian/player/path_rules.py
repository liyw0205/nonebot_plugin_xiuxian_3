"""Pure rules for first path and sub-profession selection."""

from __future__ import annotations


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

PATH_SKILLS = {
    "body": "skill.body.heavy_strike",
    "spell": "skill.spell.water_bolt",
    "device": "skill.device.scout_doll",
    "demonic": "skill.demonic.pain_exchange",
    "beast": "skill.beast.partial_transform",
    "support": "skill.support.quick_assessment",
}

PATH_ITEM_REWARDS = {
    "device": (("item.tool.basic_hammer", 1),),
    "support:alchemy": (("item.tool.basic_furnace", 1),),
    "support:artifice": (("item.tool.basic_hammer", 1),),
    "support:formation": (("item.mat.array_sand", 3),),
}


def resolve_path(value: str) -> str | None:
    return PATH_ALIASES.get(value.strip())


def resolve_subprofession(value: str) -> str | None:
    return SUBPROFESSION_ALIASES.get(value.strip())


def reward_items(path_key: str, subprofession_key: str | None) -> tuple[tuple[str, int], ...]:
    key = f"{path_key}:{subprofession_key}" if path_key == "support" else path_key
    return (("item.manual.basic_qi", 1), (PATH_SKILLS[path_key], 1), *PATH_ITEM_REWARDS.get(key, ()))
