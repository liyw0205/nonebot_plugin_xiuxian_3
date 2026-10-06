"""Shared character attribute labels for player-facing views."""

from __future__ import annotations

from typing import Mapping, Sequence

STAT_LABELS = {
    "max_hp": "气血上限", "max_mp": "灵力上限", "attack": "攻势",
    "carry_capacity": "负重", "initiative": "先手", "agility": "步法",
    "training_rate_bp": "修炼效率", "exploration_rate_bp": "探索效率",
    "breakthrough_prepare_bp": "破境准备", "hp_regen": "气血回复",
    "mana_regen": "灵力回复", "damage_reduction_bp": "护体",
    "crit_chance_bp": "会心", "crit_damage_bp": "会心伤势", "evasion_bp": "闪避",
    "accuracy_bp": "命中", "anti_crit_bp": "抗暴", "damage_reflection_bp": "反震",
    "lifesteal_bp": "汲血", "mana_leech_bp": "摄灵", "healing_reduction_bp": "抑愈",
    "recovery_reduction_bp": "封息",
}
SOURCE_LABELS = {
    "realm": "境界", "qualification": "资质根基", "permanent": "历练所得",
    "path": "道途", "equipment": "随身法器", "manual": "所修功法", "constitution": "天生体质",
}
PROFILE_STATS = ("max_hp", "max_mp", "attack", "carry_capacity", "initiative")


def stat_value_text(stat_key: str, value: int) -> str:
    return f"{value / 100:g}%" if stat_key.endswith("_bp") else str(value)


def stat_lines(stats: Mapping[str, int], keys: Sequence[str] = tuple(STAT_LABELS)) -> list[str]:
    return [f"- **{STAT_LABELS[key]}**：{stat_value_text(key, stats[key])}" for key in keys]
