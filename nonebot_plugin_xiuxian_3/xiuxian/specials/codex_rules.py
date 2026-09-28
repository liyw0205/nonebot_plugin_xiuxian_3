"""Versioned rules for the v0.1 discovery codex."""

from __future__ import annotations

from nonebot_plugin_xiuxian_3.xiuxian.versions import module_content_version, module_rule_version

from dataclasses import dataclass

from ..player.path_rules import PATH_LABELS


CONTENT_VERSION = module_content_version(__name__)
RULE_VERSION = module_rule_version(__name__)


@dataclass(frozen=True, slots=True)
class CodexEntryDefinition:
    key: str
    category: str
    label: str


@dataclass(frozen=True, slots=True)
class CodexMilestoneDefinition:
    key: str
    label: str
    entry_keys: tuple[str, ...]
    reputation_reward: int = 0
    unlocks: tuple[str, ...] = ()


_ENTRY_LABELS = {
    "codex.place.new_town": ("place", "青石镇"),
    "codex.place.outskirts": ("place", "玄天近郊"),
    "codex.place.spirit_field": ("place", "灵泉谷"),
    "codex.material.blood_grass": ("material", "止血草"),
    "codex.material.spirit_leaf": ("material", "灵叶"),
    "codex.material.ironstone": ("material", "铁石"),
    "codex.material.wood": ("material", "木材"),
    "codex.material.array_sand": ("material", "阵砂"),
    "codex.creature.wood_rat": ("creature", "木鼠"),
    "codex.creature.iron_boar": ("creature", "铁背野猪"),
    "codex.creature.mist_guardian": ("creature", "雾隐守卫"),
    "codex.route.town_road": ("route", "青石镇商路"),
    "codex.route.boundary": ("route", "界隙裂隙路线"),
    "codex.dispatch.herb_search": ("dispatch", "药材搜寻"),
    "codex.instance.mist_grotto": ("challenge", "雾隐洞天"),
    "codex.instance.cloud_boat": ("challenge", "云舟秘境"),
    "codex.domain.ancient_domain": ("challenge", "远古洞天秘境"),
    "codex.void.route_ruins": ("route", "虚空遗迹航道"),
    "codex.dao.service_origin": ("service", "道源服务篇章"),
    "codex.challenge.mist_trial.floor_5": ("challenge", "雾隐试炼塔五层"),
    "codex.challenge.mist_trial.floor_10": ("challenge", "雾隐试炼塔十层"),
    "codex.story.dispatch_demon_relief": ("story", "魔界救援线索"),
    "codex.story.dispatch_beast_relocation": ("story", "妖界迁徙线索"),
    "codex.story.beast_habitat": ("story", "万兽栖地保护记录"),
}
for _floor_no in range(1, 46):
    _ENTRY_LABELS.setdefault(
        f"codex.challenge.mist_trial.floor_{_floor_no}",
        ("challenge", f"雾隐试炼塔第 {_floor_no} 层"),
    )
for _floor_no in range(1, 41):
    _ENTRY_LABELS.setdefault(
        f"codex.challenge.three_realms.floor_{_floor_no}",
        ("challenge", f"三界塔第 {_floor_no} 层"),
    )
for _floor_no in range(1, 31):
    _ENTRY_LABELS.setdefault(
        f"codex.challenge.void_spire.floor_{_floor_no}",
        ("challenge", f"虚空塔第 {_floor_no} 层"),
    )
_ENTRY_LABELS.setdefault("codex.void.route_spire_storm", ("route", "虚空塔风暴路线"))
_ENTRY_LABELS.setdefault("codex.void.route_spire_echo", ("route", "虚空塔回响路线"))
for _faction, _label in (("xuantian", "玄天"), ("demon", "魔界"), ("beast", "妖界")):
    _ENTRY_LABELS.setdefault(
        f"codex.story.three_realms.faction_{_faction}",
        ("story", f"三界塔{_label}阵营记录"),
    )
    _ENTRY_LABELS.setdefault(
        f"codex.story.three_realms.reconstruction_{_faction}",
        ("story", f"三界塔{_label}重建记录"),
    )
    _ENTRY_LABELS.setdefault(
        f"codex.story.three_realms.domain_{_faction}",
        ("story", f"三界塔{_label}领域记录"),
    )

ENTRY_DEFINITIONS: dict[str, CodexEntryDefinition] = {
    key: CodexEntryDefinition(key, category, label)
    for key, (category, label) in _ENTRY_LABELS.items()
}
ENTRY_DEFINITIONS.update(
    {
        f"codex.path.{path_key}": CodexEntryDefinition(
            f"codex.path.{path_key}", "path", f"{label}道途"
        )
        for path_key, label in PATH_LABELS.items()
    }
)
PLACE_KEYS = tuple(key for key, value in ENTRY_DEFINITIONS.items() if value.category == "place")
MATERIAL_KEYS = tuple(key for key, value in ENTRY_DEFINITIONS.items() if value.category == "material")
CREATURE_KEYS = tuple(key for key, value in ENTRY_DEFINITIONS.items() if value.category == "creature")
PATH_KEYS = tuple(key for key, value in ENTRY_DEFINITIONS.items() if value.category == "path")

MILESTONES: dict[str, CodexMilestoneDefinition] = {
    "codex.xuantian.place_3": CodexMilestoneDefinition(
        "codex.xuantian.place_3",
        "玄天地点三览",
        PLACE_KEYS,
        reputation_reward=5,
        unlocks=("commission.town.extra_offer",),
    ),
    "codex.xuantian.materials_5": CodexMilestoneDefinition(
        "codex.xuantian.materials_5",
        "玄天材料五录",
        MATERIAL_KEYS,
        reputation_reward=5,
        unlocks=("hint.herb_route",),
    ),
    "codex.xuantian.creature_3": CodexMilestoneDefinition(
        "codex.xuantian.creature_3",
        "近郊异兽三录",
        CREATURE_KEYS,
        unlocks=("display.codex_creature_badge", "hint.tower_route"),
    ),
    "codex.paths_6": CodexMilestoneDefinition(
        "codex.paths_6",
        "六道途百科",
        PATH_KEYS,
        unlocks=("encyclopedia.paths_6",),
    ),
}


def category_for_entry(entry_key: str) -> str | None:
    definition = ENTRY_DEFINITIONS.get(entry_key)
    if definition is not None:
        return definition.category
    if entry_key.startswith("codex.challenge."):
        return "challenge"
    if entry_key.startswith("codex.domain."):
        return "challenge"
    if entry_key.startswith("codex.story."):
        return "story"
    if entry_key.startswith("codex.route."):
        return "route"
    if entry_key.startswith("codex.void.route_"):
        return "route"
    if entry_key.startswith("codex.void.archive_"):
        return "story"
    if entry_key.startswith("codex.dao.service_"):
        return "service"
    return None


def label_for_entry(entry_key: str) -> str:
    definition = ENTRY_DEFINITIONS.get(entry_key)
    if definition is not None:
        return definition.label
    return entry_key.rsplit(".", 1)[-1].replace("_", " ")


__all__ = [
    "CONTENT_VERSION",
    "CREATURE_KEYS",
    "ENTRY_DEFINITIONS",
    "MATERIAL_KEYS",
    "MILESTONES",
    "PATH_KEYS",
    "PLACE_KEYS",
    "RULE_VERSION",
    "CodexEntryDefinition",
    "CodexMilestoneDefinition",
    "category_for_entry",
    "label_for_entry",
]
