"""Rules derived from owned cultivation manuals."""

from __future__ import annotations

from ..content import ContentBundle, ContentError, bundled_content

_MANUAL_EFFECTS = {
    "cultivation_permission",
    "breakthrough_bonus_bp",
    "cultivation_gain_bp",
    "combat_stat_bonus_bp",
    "damage_reflection_bp",
}
_COMBAT_STATS = {"attack", "max_hp", "initiative", "agility"}


def _owned_manual_effects(
    inventory: dict[str, int], content: ContentBundle | None = None
):
    bundle = content or bundled_content()
    for item in bundle.list("item", include_locked=False):
        item_key = item.get("key")
        if item.get("item_type") != "manual" or int(inventory.get(str(item_key), 0)) <= 0:
            continue
        effects = item.get("effects")
        if not isinstance(effects, list):
            raise ContentError(f"manual {item_key} effects must be a list")
        for effect in effects:
            if not isinstance(effect, dict) or effect.get("type") not in _MANUAL_EFFECTS:
                raise ContentError(f"manual {item_key} has an unsupported effect")
            effect_type = effect["type"]
            if effect_type == "cultivation_permission":
                target = effect.get("target")
                if not isinstance(target, str) or not bundle.has("realm", target):
                    raise ContentError(f"manual {item_key} has an invalid cultivation permission")
                yield item_key, effect
                continue
            if effect_type == "breakthrough_bonus_bp":
                realm_key = effect.get("target_realm")
                if not isinstance(realm_key, str) or not bundle.has("realm", realm_key):
                    raise ContentError(f"manual {item_key} has an invalid breakthrough target")
            value = effect.get("value")
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ContentError(f"manual {item_key} effect value must be a non-negative integer")
            if effect_type == "breakthrough_bonus_bp" and value > 10_000:
                raise ContentError(f"manual {item_key} breakthrough bonus must be 0..10000")
            if effect_type == "cultivation_gain_bp" and value > 5_000:
                raise ContentError(f"manual {item_key} cultivation bonus must be 0..5000")
            if effect_type == "damage_reflection_bp" and value > 5_000:
                raise ContentError(f"manual {item_key} reflection must be 0..5000")
            if effect_type == "combat_stat_bonus_bp":
                stat = effect.get("stat")
                if stat not in _COMBAT_STATS or value > 3_000:
                    raise ContentError(f"manual {item_key} has an invalid combat stat bonus")
            yield item_key, effect


def manual_grants_permission(
    inventory: dict[str, int],
    permission_realm: str,
    content: ContentBundle | None = None,
) -> bool:
    bundle = content or bundled_content()
    target = bundle.get("realm", permission_realm, include_locked=False)
    if target is None:
        raise ContentError(f"manual permission references unknown realm: {permission_realm}")
    target_rank = int(target.get("rank", -1))
    owned_effects = tuple(_owned_manual_effects(inventory, bundle))
    for _, effect in owned_effects:
        if effect["type"] != "cultivation_permission":
            continue
        realm = bundle.get("realm", effect["target"], include_locked=False)
        if realm is not None and int(realm.get("rank", -1)) >= target_rank:
            return True
    return False


def manual_breakthrough_bonus(
    inventory: dict[str, int],
    target_realm: str,
    content: ContentBundle | None = None,
) -> int:
    bundle = content or bundled_content()
    if not bundle.has("realm", target_realm):
        raise ContentError(f"manual bonus references unknown realm: {target_realm}")

    bonuses = [
        int(effect["value"])
        for _, effect in _owned_manual_effects(inventory, bundle)
        if effect["type"] == "breakthrough_bonus_bp"
        and effect["target_realm"] == target_realm
    ]
    return max(bonuses, default=0)


def manual_effect_totals(
    inventory: dict[str, int], content: ContentBundle | None = None
) -> dict[str, object]:
    totals: dict[str, object] = {
        "cultivation_gain_bp": 0,
        "combat_stat_bonus_bp": {stat: 0 for stat in _COMBAT_STATS},
        "damage_reflection_bp": 0,
    }
    stat_totals = totals["combat_stat_bonus_bp"]
    assert isinstance(stat_totals, dict)
    for _, effect in _owned_manual_effects(inventory, content):
        effect_type = effect["type"]
        if effect_type == "cultivation_gain_bp":
            totals[effect_type] = int(totals[effect_type]) + int(effect["value"])
        elif effect_type == "combat_stat_bonus_bp":
            stat = str(effect["stat"])
            stat_totals[stat] += int(effect["value"])
        elif effect_type == "damage_reflection_bp":
            totals[effect_type] = int(totals[effect_type]) + int(effect["value"])
    return totals


__all__ = [
    "manual_breakthrough_bonus",
    "manual_effect_totals",
    "manual_grants_permission",
]
