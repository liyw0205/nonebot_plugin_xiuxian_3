"""Pure, versioned rules for v0.1 skill mastery."""

from __future__ import annotations

from dataclasses import dataclass


CONTENT_VERSION = "content-0.1"
RULE_VERSION = "advancement-0.1.0"
SKILL_INSIGHT_RESOURCE = "resource.skill_insight"
MAX_SKILL_LEVEL = 3
SKILL_LEVEL_COSTS = {
    1: (1, 20),
    2: (1, 40),
    3: (2, 80),
}
EFFECT_DELTA_BP_PER_LEVEL = 300


@dataclass(frozen=True, slots=True)
class SkillDefinition:
    key: str
    label: str
    path_key: str | None
    effect: dict[str, int | str]
    description: str
    content_version: str = CONTENT_VERSION
    rule_version: str = RULE_VERSION


SKILL_DEFINITIONS = {
    "skill.basic_attack": SkillDefinition(
        key="skill.basic_attack",
        label="基础攻击",
        path_key=None,
        effect={"type": "physical_damage_multiplier_bp", "value": 10000},
        description="以基础招式造成物理伤害。",
    ),
    "skill.body.heavy_strike": SkillDefinition(
        key="skill.body.heavy_strike",
        label="重击",
        path_key="body",
        effect={"type": "physical_damage_multiplier_bp", "value": 14000},
        description="借体魄发力，强化近身一击。",
    ),
    "skill.spell.water_bolt": SkillDefinition(
        key="skill.spell.water_bolt",
        label="水箭",
        path_key="spell",
        effect={"type": "spell_damage_multiplier_bp", "value": 15000},
        description="凝水成箭，强化术法伤害。",
    ),
    "skill.device.scout_doll": SkillDefinition(
        key="skill.device.scout_doll",
        label="侦查机关",
        path_key="device",
        effect={"type": "summon_attack_multiplier_bp", "value": 5000},
        description="操纵侦查机关协同行动。",
    ),
    "skill.demonic.pain_exchange": SkillDefinition(
        key="skill.demonic.pain_exchange",
        label="痛苦交换",
        path_key="demonic",
        effect={"type": "damage_bonus_bp", "value": 4500},
        description="以气血代价换取伤害增幅。",
    ),
    "skill.beast.partial_transform": SkillDefinition(
        key="skill.beast.partial_transform",
        label="半化形",
        path_key="beast",
        effect={"type": "stat_bonus_bp", "value": 2000},
        description="借血脉化形，短暂强化身法。",
    ),
    "skill.support.quick_assessment": SkillDefinition(
        key="skill.support.quick_assessment",
        label="快速鉴定",
        path_key="support",
        effect={"type": "next_item_or_device_effect_bp", "value": 1000},
        description="洞察物性，强化下一次器物效果。",
    ),
    # v0.3 combat keys are registered here so their mastery snapshots can be
    # consumed by the automatic battle engine without a second skill catalog.
    "skill.body.mountain_domain": SkillDefinition(
        key="skill.body.mountain_domain",
        label="山岳领域",
        path_key="body",
        effect={"type": "physical_damage_multiplier_bp", "value": 16000},
        description="以山岳之势压制敌手。",
    ),
    "skill.spell.five_element_cycle": SkillDefinition(
        key="skill.spell.five_element_cycle",
        label="五行轮转",
        path_key="spell",
        effect={"type": "spell_damage_multiplier_bp", "value": 17000},
        description="引五行循环造成术法伤害。",
    ),
    "skill.device.thousand_doll_array": SkillDefinition(
        key="skill.device.thousand_doll_array",
        label="千机傀儡阵",
        path_key="device",
        effect={"type": "summon_attack_multiplier_bp", "value": 9000},
        description="以千机傀儡阵协同攻击。",
    ),
    "skill.demonic.abyss_communion": SkillDefinition(
        key="skill.demonic.abyss_communion",
        label="深渊共鸣",
        path_key="demonic",
        effect={"type": "damage_bonus_bp", "value": 7000},
        description="借深渊回响换取伤害增幅。",
    ),
    "skill.beast.ancestral_form": SkillDefinition(
        key="skill.beast.ancestral_form",
        label="祖灵真形",
        path_key="beast",
        effect={"type": "physical_damage_multiplier_bp", "value": 15500},
        description="唤醒祖灵真形强化攻击。",
    ),
    "skill.soul.suppression": SkillDefinition(
        key="skill.soul.suppression",
        label="神魂镇压",
        path_key="soul",
        effect={"type": "soul_damage_multiplier_bp", "value": 15000},
        description="以神魂之力压制敌方行动。",
    ),
}

SKILL_ALIASES = {
    "基础攻击": "skill.basic_attack",
    "重击": "skill.body.heavy_strike",
    "水箭": "skill.spell.water_bolt",
    "侦查机关": "skill.device.scout_doll",
    "痛苦交换": "skill.demonic.pain_exchange",
    "半化形": "skill.beast.partial_transform",
    "快速鉴定": "skill.support.quick_assessment",
    "山岳领域": "skill.body.mountain_domain",
    "五行轮转": "skill.spell.five_element_cycle",
    "千机傀儡阵": "skill.device.thousand_doll_array",
    "深渊共鸣": "skill.demonic.abyss_communion",
    "祖灵真形": "skill.beast.ancestral_form",
    "神魂镇压": "skill.soul.suppression",
    **{key: key for key in SKILL_DEFINITIONS},
}


def skill_definition(value: str | None) -> SkillDefinition:
    normalized = (value or "").strip()
    key = SKILL_ALIASES.get(normalized, normalized)
    try:
        return SKILL_DEFINITIONS[key]
    except KeyError as exc:
        raise ValueError(f"unsupported skill: {value}") from exc


def skill_cost(target_level: int) -> tuple[int, int]:
    try:
        return SKILL_LEVEL_COSTS[int(target_level)]
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"unsupported skill level: {target_level}") from exc


def available_skill_keys(path_key: str | None) -> tuple[str, ...]:
    return tuple(
        definition.key
        for definition in SKILL_DEFINITIONS.values()
        if definition.path_key is None or definition.path_key == path_key
    )


def effective_skill_effect(definition: SkillDefinition, level: int) -> dict[str, int | str]:
    if level < 0 or level > MAX_SKILL_LEVEL:
        raise ValueError("skill level is out of range")
    effect = dict(definition.effect)
    effect["level"] = level
    effect["value"] = int(definition.effect["value"]) + EFFECT_DELTA_BP_PER_LEVEL * level
    return effect


__all__ = [
    "CONTENT_VERSION",
    "EFFECT_DELTA_BP_PER_LEVEL",
    "MAX_SKILL_LEVEL",
    "RULE_VERSION",
    "SKILL_ALIASES",
    "SKILL_DEFINITIONS",
    "SKILL_INSIGHT_RESOURCE",
    "SKILL_LEVEL_COSTS",
    "SkillDefinition",
    "available_skill_keys",
    "effective_skill_effect",
    "skill_cost",
    "skill_definition",
]
