"""Validated tribulation-trial definition loaded from the content package."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..content import ContentBundle, ContentError, bundled_content

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .tribulation_rules import TribulationPhase

TRIAL_KEY = "trial.tribulation.heaven"


def tribulation_trial(content: ContentBundle | None = None) -> dict[str, Any]:
    """Return the validated trial record (enemy scale plus ordered phases)."""

    bundle = content or bundled_content()
    rows = bundle.list("tribulation_trial")
    if not rows:
        raise ContentError("tribulation trial content is missing")
    row = next((item for item in rows if item.get("key") == TRIAL_KEY), None)
    if row is None:
        raise ContentError(f"tribulation trial content is missing: {TRIAL_KEY}")
    if row.get("status") not in {"active", "open"}:
        raise ContentError("tribulation trial content is closed")
    enemy = row.get("enemy")
    if not isinstance(enemy, dict) or set(enemy) != {"max_hp", "attack", "initiative", "agility"}:
        raise ContentError("tribulation trial enemy is invalid")
    for field in ("max_hp", "attack", "initiative", "agility"):
        _positive(enemy[field], f"enemy {field}")
    phases = row.get("phases")
    if not isinstance(phases, list) or not phases:
        raise ContentError("tribulation trial phases are missing")
    seen: set[str] = set()
    parsed: list[dict[str, Any]] = []
    for phase in phases:
        if not isinstance(phase, dict):
            raise ContentError("tribulation trial phase is invalid")
        if set(phase) != {
            "key", "label", "min_hp_bp", "attack", "skill_key",
            "enemy_hit_bonus_bp", "player_damage_bp",
        }:
            raise ContentError("tribulation trial phase fields are invalid")
        key = _text(phase["key"], "phase key")
        label = _text(phase["label"], f"phase {key} label")
        if key in seen:
            raise ContentError(f"duplicate tribulation phase: {key}")
        seen.add(key)
        bp = _bounded(phase["min_hp_bp"], f"phase {key} min_hp_bp", 10_000)
        attack = _positive(phase["attack"], f"phase {key} attack")
        skill = _text(phase["skill_key"], f"phase {key} skill")
        skill_row = bundle.get("skill", skill, include_locked=False)
        if skill_row is None or skill_row.get("owner_type") != "enemy":
            raise ContentError(f"phase {key} references unavailable enemy skill {skill}")
        hit = _bounded(phase["enemy_hit_bonus_bp"], f"phase {key} hit bonus", 10_000)
        damage = _bounded(phase["player_damage_bp"], f"phase {key} damage bp", 10_000)
        if damage <= 0:
            raise ContentError(f"phase {key} damage bp must be positive")
        parsed.append({
            "key": key, "label": label, "min_hp_bp": bp, "attack": attack, "skill_key": skill,
            "enemy_hit_bonus_bp": hit, "player_damage_bp": damage,
        })
    if [item["min_hp_bp"] for item in parsed] != sorted(
        (item["min_hp_bp"] for item in parsed), reverse=True
    ) or len({item["min_hp_bp"] for item in parsed}) != len(parsed):
        raise ContentError("tribulation phases must descend strictly")
    if parsed[-1]["min_hp_bp"] != 0:
        raise ContentError("the final tribulation phase must start at 0 bp")
    return {
        "key": TRIAL_KEY,
        "enemy_key": _text(row.get("enemy_key"), "enemy key"),
        "battle_profile_key": _text(row.get("battle_profile_key"), "profile key"),
        "enemy": dict(enemy),
        "phases": parsed,
    }


def tribulation_phases(content: ContentBundle | None = None) -> tuple["TribulationPhase", ...]:
    from .tribulation_rules import TribulationPhase

    return tuple(
        TribulationPhase(
            key=item["key"],
            label=item["label"],
            min_hp_bp=item["min_hp_bp"],
            attack=item["attack"],
            skill_key=item["skill_key"],
            enemy_hit_bonus_bp=item["enemy_hit_bonus_bp"],
            player_damage_bp=item["player_damage_bp"],
        )
        for item in tribulation_trial(content)["phases"]
    )


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContentError(f"tribulation trial {field} must be a non-empty string")
    return value.strip()


def _positive(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ContentError(f"tribulation trial {field} must be a positive integer")
    return value


def _bounded(value: Any, field: str, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= maximum:
        raise ContentError(f"tribulation trial {field} is out of range")
    return value


__all__ = ["TRIAL_KEY", "tribulation_phases", "tribulation_trial"]
