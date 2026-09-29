"""Battle-time consumers for configured player skill styles."""

from __future__ import annotations

from typing import Any


def prepare_skill_action(
    skill: dict[str, Any], state: dict[str, Any], round_no: int
) -> tuple[int, int, bool]:
    effect = dict(skill.get("effect", {}))
    style = dict(skill.get("combat_style", {}))
    style_key = str(style.get("key", "attack"))
    style_effect = dict(style.get("effect", {}))
    skill_key = str(skill.get("skill_key", ""))
    multiplier = _damage_multiplier(effect)
    hit_bonus_bp = 0
    if style_key == "burst":
        hit_bonus_bp = -int(style_effect.get("hit_penalty_bp", 0))
    if style_key == "charge":
        charged_key = str(state.get("charged_skill_key", ""))
        charged_round = int(state.get("charged_skill_round", round_no))
        if charged_key == skill_key and charged_round < round_no:
            state.pop("charged_skill_key", None)
            state.pop("charged_skill_round", None)
            multiplier = multiplier * int(style_effect.get("charge_multiplier_bp", 10_000)) // 10_000
        else:
            state["charged_skill_key"] = skill_key
            state["charged_skill_round"] = round_no
            return 0, 0, True
    return multiplier, hit_bonus_bp, False


def apply_player_skill_style(
    skill: dict[str, Any],
    state: dict[str, Any],
    *,
    round_no: int,
    player_attack: int,
    hit: bool,
    enemy_acted: bool,
    direct_damage: int = 0,
) -> int:
    """Apply configured effects and return damage from active status effects."""

    statuses = state.setdefault("skill_statuses", {})
    if not isinstance(statuses, dict):
        raise ValueError("battle skill statuses must be an object")
    tick_damage = 0
    for status_key, status in tuple(statuses.items()):
        if not isinstance(status, dict):
            raise ValueError(f"battle skill status {status_key} must be an object")
        start = int(status["start_round"])
        end = int(status["end_round"])
        if round_no > end:
            statuses.pop(status_key, None)
        elif start <= round_no <= end:
            tick_damage += int(status["damage"])

    if not hit:
        return tick_damage
    style = dict(skill.get("combat_style", {}))
    style_key = str(style.get("key", "attack"))
    style_effect = dict(style.get("effect", {}))
    duration = int(style_effect.get("duration_rounds", 1))
    expires_round = round_no + duration - 1 + int(enemy_acted)
    if style_key == "support":
        state["player_guard_bp"] = int(style_effect["damage_reduction_bp"])
        state["player_guard_until_round"] = expires_round
    elif style_key in {"sustained", "poison", "burn"}:
        source_damage = direct_damage if style_key == "burn" else player_attack
        status_damage = max(
            1,
            max(0, source_damage) * int(style_effect["damage_over_time_bp"]) // 10_000,
        )
        statuses[style_key] = {
            "damage": status_damage,
            "start_round": round_no + 1,
            "end_round": round_no + duration,
            "skill_key": str(skill.get("skill_key", "")),
        }
        if style_key == "poison":
            statuses[style_key]["enemy_attack_reduction_bp"] = int(
                style_effect["enemy_attack_reduction_bp"]
            )
            statuses[style_key]["enemy_attack_reduction_until_round"] = expires_round
    elif style_key == "negative":
        state["enemy_attack_reduction_bp"] = int(style_effect["enemy_attack_reduction_bp"])
        state["enemy_debuff_until_round"] = expires_round
    elif style_key == "reflect":
        state["player_reflect_damage_bp"] = int(style_effect["damage_reflection_bp"])
        state["player_reflect_until_round"] = expires_round
    return tick_damage


def mitigate_enemy_attack(
    attack: int, state: dict[str, Any], *, round_no: int
) -> int:
    reductions = [
        int(state.get("enemy_attack_reduction_bp", 0))
        if round_no <= int(state.get("enemy_debuff_until_round", 0))
        else 0
    ]
    statuses = state.get("skill_statuses", {})
    if isinstance(statuses, dict):
        reductions.extend(
            int(status.get("enemy_attack_reduction_bp", 0))
            for status in statuses.values()
            if isinstance(status, dict)
            and round_no
            <= int(status.get("enemy_attack_reduction_until_round", status.get("end_round", 0)))
        )
    reduction = max(reductions, default=0)
    return max(0, attack * (10_000 - min(10_000, reduction)) // 10_000)


def mitigate_player_damage(
    damage: int, state: dict[str, Any], *, round_no: int, equipment_reduction_bp: int = 0
) -> int:
    guard = (
        int(state.get("player_guard_bp", 0))
        if round_no <= int(state.get("player_guard_until_round", 0))
        else 0
    )
    reduction = min(10_000, max(0, equipment_reduction_bp) + max(0, guard))
    return max(0, damage * (10_000 - min(10_000, reduction)) // 10_000)


def reflected_enemy_damage(
    damage: int, state: dict[str, Any], *, round_no: int
) -> int:
    skill_reflection = (
        int(state.get("player_reflect_damage_bp", 0))
        if round_no <= int(state.get("player_reflect_until_round", 0))
        else 0
    )
    manual_reflection = int(state.get("manual_reflect_damage_bp", 0))
    reflection_bp = min(10_000, skill_reflection + manual_reflection)
    return max(0, damage) * reflection_bp // 10_000


def _damage_multiplier(effect: dict[str, Any]) -> int:
    value = int(effect.get("value", 10_000))
    effect_type = str(effect.get("type", ""))
    if effect_type == "damage_bonus_bp":
        return 10_000 + value
    if effect_type.endswith("_multiplier_bp"):
        return value
    return 10_000


__all__ = [
    "apply_player_skill_style",
    "mitigate_enemy_attack",
    "mitigate_player_damage",
    "prepare_skill_action",
    "reflected_enemy_damage",
]
