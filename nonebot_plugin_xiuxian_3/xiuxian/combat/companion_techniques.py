"""Resolve the small allowlist of frozen companion combat effects."""

from __future__ import annotations

from typing import Any

_TRIGGERS = {
    "opening_attack_bp": "first_attack",
    "first_guard_bp": "first_received_damage",
}


def apply_companion_techniques(
    companions: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    *,
    trigger: str,
    amount: int,
    used: set[str],
) -> tuple[int, list[dict[str, Any]], set[str]]:
    """Apply matching effects once and return the changed amount and replay events."""

    if trigger not in {"first_attack", "first_received_damage"}:
        raise ValueError("unsupported companion technique trigger")
    matching: list[dict[str, Any]] = []
    next_used = set(used)
    for companion in companions:
        if not isinstance(companion, dict):
            raise ValueError("companion battle snapshot is malformed")
        if companion.get("kind") != "beast":
            continue
        techniques = companion.get("techniques", [])
        if not isinstance(techniques, list):
            raise ValueError("companion technique snapshot is malformed")
        for technique in techniques:
            if not isinstance(technique, dict):
                raise ValueError("companion technique snapshot is malformed")
            key = technique.get("technique_key")
            effect = technique.get("effect")
            if not isinstance(key, str) or not key or not isinstance(effect, dict):
                raise ValueError("companion technique snapshot is malformed")
            effect_type = effect.get("type")
            value = effect.get("value")
            if effect_type not in _TRIGGERS:
                raise ValueError("companion technique effect is unsupported")
            if type(value) is not int or not 1 <= value <= 5000:
                raise ValueError("companion technique effect value is invalid")
            if _TRIGGERS[effect_type] != trigger or key in used:
                continue
            matching.append(
                {
                    "technique_key": key,
                    "name": str(technique.get("name", key)),
                    "effect_type": effect_type,
                    "value": value,
                }
            )

    if not matching or (trigger == "first_received_damage" and amount <= 0):
        return amount, [], next_used

    combined_bp = min(5000, sum(int(item["value"]) for item in matching))
    if trigger == "first_attack":
        changed = amount + amount * combined_bp // 10_000
        delta = changed - amount
    else:
        changed = amount * (10_000 - combined_bp) // 10_000
        delta = amount - changed
    events = [
        {
            "technique_key": item["technique_key"],
            "name": item["name"],
            "trigger": trigger,
            "effect_type": item["effect_type"],
            "value": item["value"],
            "combined_bp": combined_bp,
            "amount_changed": delta,
        }
        for item in matching
    ]
    next_used.update(str(item["technique_key"]) for item in matching)
    return changed, events, next_used


__all__ = ["apply_companion_techniques"]
