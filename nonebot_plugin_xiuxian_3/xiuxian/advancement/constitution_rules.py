"""Pure, versioned rules for the v0.1 constitution profile."""

from __future__ import annotations

from dataclasses import dataclass


CONTENT_VERSION = "content-0.1"
RULE_VERSION = "advancement-0.1.0"
CONSTITUTION_RESET_ITEM = "item.token.constitution_reset"
RESHAPE_COOLDOWN_SECONDS = 30 * 24 * 60 * 60


@dataclass(frozen=True, slots=True)
class ConstitutionDefinition:
    key: str
    label: str
    description: str
    effect: dict[str, int | str]
    content_version: str = CONTENT_VERSION
    rule_version: str = RULE_VERSION


CONSTITUTION_DEFINITIONS = {
    "constitution.iron_bone": ConstitutionDefinition(
        key="constitution.iron_bone",
        label="铁骨",
        description="淬炼体魄，提升气血上限。",
        effect={"type": "max_hp_bp", "value": 300},
    ),
    "constitution.spirit_root": ConstitutionDefinition(
        key="constitution.spirit_root",
        label="灵根",
        description="灵力易感，提升灵力上限。",
        effect={"type": "max_mana_bp", "value": 300},
    ),
    "constitution.wind_step": ConstitutionDefinition(
        key="constitution.wind_step",
        label="风行",
        description="身法轻灵，提升先手。",
        effect={"type": "initiative_bp", "value": 300},
    ),
    "constitution.craft_hand": ConstitutionDefinition(
        key="constitution.craft_hand",
        label="巧手",
        description="熟于火候，提升生产质量。",
        effect={"type": "production_quality_bp", "value": 300},
    ),
    "constitution.beast_affinity": ConstitutionDefinition(
        key="constitution.beast_affinity",
        label="御兽",
        description="亲近灵兽，提升灵兽亲和。",
        effect={"type": "beast_affinity", "value": 5},
    ),
    "constitution.fortune_seed": ConstitutionDefinition(
        key="constitution.fortune_seed",
        label="福缘",
        description="机缘相随，提升非保底掉落权重。",
        effect={"type": "drop_weight_bp", "value": 300},
    ),
}

CONSTITUTION_ALIASES = {
    "铁骨": "constitution.iron_bone",
    "体魄": "constitution.iron_bone",
    "灵根": "constitution.spirit_root",
    "风行": "constitution.wind_step",
    "巧手": "constitution.craft_hand",
    "御兽": "constitution.beast_affinity",
    "福缘": "constitution.fortune_seed",
    **{key: key for key in CONSTITUTION_DEFINITIONS},
}


def constitution_definition(value: str | None) -> ConstitutionDefinition:
    normalized = (value or "").strip()
    key = CONSTITUTION_ALIASES.get(normalized, normalized)
    try:
        return CONSTITUTION_DEFINITIONS[key]
    except KeyError as exc:
        raise ValueError(f"unsupported constitution: {value}") from exc


def constitution_options() -> tuple[ConstitutionDefinition, ...]:
    return tuple(CONSTITUTION_DEFINITIONS.values())


__all__ = [
    "CONSTITUTION_ALIASES",
    "CONSTITUTION_DEFINITIONS",
    "CONSTITUTION_RESET_ITEM",
    "CONTENT_VERSION",
    "RESHAPE_COOLDOWN_SECONDS",
    "RULE_VERSION",
    "ConstitutionDefinition",
    "constitution_definition",
    "constitution_options",
]
