"""Battle-time consumers for the skills an enemy declares.

Automatic combat used to copy ``enemy.skill_key`` into the action log and then
always strike with the raw ``stats.attack``: no declared effect ever ran, so a
mist shield or a bleeding blade wave was decoration.  This module resolves the
single declared skill record into a frozen battle plan and provides the pure
helpers the turn engine applies.

Semantics are derived from the existing records, not added fields:

- ``physical_damage_multiplier_bp`` multiples the attack; ``damage_bonus_bp``
  adds its value to 10000.
- ``shield_max_hp_bp`` (target ``self``) is a ward worth that share of the
  enemy's max HP, active for ``duration_rounds``.  It absorbs player damage
  before HP while active, and a battle opens at most one ward (conservative:
  the record declares no recharge clause, and refreshing it every round would
  make a low-tier guardian unkillable inside the twenty-round contract).
- An effect ``status`` is a damage-over-time on the player whose per-round
  damage is the damage part of the multiplier beyond 10000 bp of the strike.
"""

from __future__ import annotations

from typing import Any, Mapping

from ..content import ContentError

DAMAGE_EFFECT_TYPES = frozenset({"physical_damage_multiplier_bp", "damage_bonus_bp"})
ABSOLUTE_EFFECT_TYPE = "physical_damage_absolute"
SHIELD_EFFECT_TYPE = "shield_max_hp_bp"


def _positive_int(value: Any, context: str, *, allow_zero: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ContentError(f"{context} must be an integer")
    if value < 0 or (value == 0 and not allow_zero):
        raise ContentError(f"{context} must be positive")
    return value


def resolve_enemy_skill(skill: Mapping[str, Any]) -> dict[str, Any]:
    """Resolve one enemy skill record into an immutable battle plan."""

    key = skill.get("key")
    name = skill.get("name")
    effect = skill.get("effect")
    if not isinstance(key, str) or not key.strip():
        raise ContentError("enemy skill requires a stable key")
    if not isinstance(name, str) or not name.strip():
        raise ContentError(f"enemy skill {key} requires a name")
    if not isinstance(effect, dict):
        raise ContentError(f"enemy skill {key} requires an effect object")
    effect_type = effect.get("type")
    multiplier_bp = 10_000
    absolute_attack = 0
    shield_bp = 0
    shield_rounds = 0
    if effect_type in DAMAGE_EFFECT_TYPES:
        value = _positive_int(effect.get("value"), f"enemy skill {key} value")
        multiplier_bp = value if effect_type == "physical_damage_multiplier_bp" else 10_000 + value
    elif effect_type == ABSOLUTE_EFFECT_TYPE:
        # Phase-driven trial skills declare a flat strike instead of a stat
        # multiple; the trial path keeps its own phase numbers, but the value
        # is still validated and frozen so the record cannot drift silently.
        absolute_attack = _positive_int(effect.get("attack"), f"enemy skill {key} attack")
    elif effect_type == SHIELD_EFFECT_TYPE:
        value = _positive_int(effect.get("value"), f"enemy skill {key} value")
        if skill.get("target") != "self":
            raise ContentError(f"enemy skill {key} shield must target self")
        shield_bp = value
        shield_rounds = _positive_int(
            effect.get("duration_rounds", 1), f"enemy skill {key} duration_rounds"
        )
    else:
        raise ContentError(f"enemy skill {key} has an unsupported effect type {effect_type!r}")

    status_key = None
    status_rounds = 0
    status_damage_bp = 0
    status = effect.get("status")
    if status is not None:
        if not isinstance(status, dict):
            raise ContentError(f"enemy skill {key} status must be an object")
        status_key = status.get("key")
        if not isinstance(status_key, str) or not status_key.strip():
            raise ContentError(f"enemy skill {key} status requires a key")
        status_rounds = _positive_int(
            status.get("duration_rounds"), f"enemy skill {key} status duration_rounds"
        )
        status_damage_bp = max(0, multiplier_bp - 10_000)
        if status_damage_bp <= 0:
            raise ContentError(f"enemy skill {key} status needs a damage multiplier")
        if shield_bp:
            raise ContentError(f"enemy skill {key} cannot combine a shield and a status")

    return {
        "key": key,
        "name": name.strip(),
        "multiplier_bp": multiplier_bp,
        "absolute_attack": absolute_attack,
        "shield_bp": shield_bp,
        "shield_rounds": shield_rounds,
        "status_key": status_key,
        "status_rounds": status_rounds,
        "status_damage_bp": status_damage_bp,
        "cooldown_rounds": _positive_int(
            skill.get("cooldown_rounds", 0), f"enemy skill {key} cooldown_rounds", allow_zero=True
        ),
    }


def enemy_skill_casts(skill: Mapping[str, Any] | None, round_no: int) -> bool:
    """Whether the declared skill fires this round, per its declared cooldown."""

    if not isinstance(skill, Mapping):
        return False
    cooldown = int(skill.get("cooldown_rounds", 0))
    return (max(1, int(round_no)) - 1) % (cooldown + 1) == 0


def enemy_skill_attack(
    skill: Mapping[str, Any] | None, attack: int, *, round_no: int
) -> int:
    """The attack a declared skill turns into on this round."""

    if not isinstance(skill, Mapping) or not enemy_skill_casts(skill, round_no):
        return max(0, int(attack))
    absolute = int(skill.get("absolute_attack", 0))
    if absolute > 0:
        return absolute
    return max(0, int(attack)) * max(0, int(skill.get("multiplier_bp", 10_000))) // 10_000


def open_enemy_shield(
    skill: Mapping[str, Any] | None, max_hp: int, *, round_no: int
) -> dict[str, int] | None:
    """The single ward a battle opens, or ``None`` when the skill has none."""

    if not isinstance(skill, Mapping):
        return None
    shield_bp = int(skill.get("shield_bp", 0))
    if shield_bp <= 0:
        return None
    pool = max(1, int(max_hp) * shield_bp // 10_000)
    return {"remaining": pool, "until_round": round_no + int(skill.get("shield_rounds", 1)) - 1}


def absorb_with_shield(
    state: dict[str, Any], damage: int, *, round_no: int
) -> tuple[int, int]:
    """Split incoming damage into ``(absorbed, remaining)`` and expire the ward."""

    shield = state.get("enemy_shield")
    if not isinstance(shield, dict):
        return 0, max(0, int(damage))
    if round_no > int(shield.get("until_round", 0)):
        state.pop("enemy_shield", None)
        return 0, max(0, int(damage))
    remaining_pool = max(0, int(shield.get("remaining", 0)))
    absorbed = min(remaining_pool, max(0, int(damage)))
    left = remaining_pool - absorbed
    if left <= 0:
        state.pop("enemy_shield", None)
    else:
        shield["remaining"] = left
        state["enemy_shield"] = shield
    return absorbed, max(0, int(damage)) - absorbed


def apply_enemy_status(
    state: dict[str, Any], skill: Mapping[str, Any] | None, damage: int, *, round_no: int
) -> str | None:
    """Register the declared status from a landed enemy skill strike."""

    if not isinstance(skill, Mapping) or not enemy_skill_casts(skill, round_no):
        return None
    status_key = skill.get("status_key")
    rate_bp = int(skill.get("status_damage_bp", 0))
    if not isinstance(status_key, str) or not status_key or rate_bp <= 0:
        return None
    statuses = state.setdefault("enemy_statuses", {})
    if not isinstance(statuses, dict):
        raise ValueError("enemy statuses must be an object")
    statuses[status_key] = {
        "damage": max(1, max(0, int(damage)) * rate_bp // 10_000),
        "until_round": round_no + int(skill.get("status_rounds", 1)),
    }
    return status_key


def tick_enemy_statuses(
    state: dict[str, Any], *, round_no: int
) -> tuple[int, tuple[str, ...]]:
    """Apply active statuses to the player and drop the expired ones."""

    statuses = state.get("enemy_statuses")
    if not isinstance(statuses, dict) or not statuses:
        return 0, ()
    total = 0
    active: list[str] = []
    for status_key, status in tuple(statuses.items()):
        if not isinstance(status, dict):
            raise ValueError("enemy status must be an object")
        if round_no > int(status.get("until_round", 0)):
            statuses.pop(status_key, None)
            continue
        total += max(0, int(status.get("damage", 0)))
        active.append(str(status_key))
    if not statuses:
        state.pop("enemy_statuses", None)
    return total, tuple(active)


__all__ = [
    "ABSOLUTE_EFFECT_TYPE",
    "DAMAGE_EFFECT_TYPES",
    "SHIELD_EFFECT_TYPE",
    "absorb_with_shield",
    "apply_enemy_status",
    "enemy_skill_attack",
    "enemy_skill_casts",
    "open_enemy_shield",
    "resolve_enemy_skill",
    "tick_enemy_statuses",
]
