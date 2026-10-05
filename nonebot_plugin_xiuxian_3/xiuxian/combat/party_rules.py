"""Pure rules for explicit automatic party PVE sessions."""

from __future__ import annotations

from ..content import ContentBundle, ContentError, bundled_content
from .rules import EnemyDefinition, enemy_definition


PARTY_BATTLE_TYPE = "pve.party"
PARTY_BATTLE_MAX_TURNS = 20
BOUNDARY_REALM_LOCATION = "cave.boundary_realm"
BOUNDARY_REALM_ENEMY = "enemy.boundary_watcher"
BOUNDARY_REALM_STAMINA_COST = 30
BOUNDARY_REALM_TICKET = "item.soul_crystal"
BOUNDARY_REALM_TICKET_COST = 1
BOUNDARY_REALM_SOUL_POWER_MAX = 300
BOUNDARY_REALM_REWARD = {"item.soul_crystal": 1, "soul_power": 50}
SECRET_REALM_BOUNDARY_PARTY_TYPE = "secret_realm_boundary"
DEMON_REALM_LOCATION = "demon.fallen_ruins"
DEMON_REALM_STAMINA_COST = 20
DEMON_REALM_REWARD = {
    "item.demon_core": 1,
    "world_merit": 20,
    "faction_reputation.demon": 15,
}
BEAST_REALM_LOCATION = "beast.ten_thousand_hills"
BEAST_REALM_STAMINA_COST = 20
BEAST_REALM_REWARD = {
    "item.beast_blood": 1,
    "world_merit": 20,
    "faction_reputation.beast": 15,
}


def party_enemy_for_location(
    location_key: str, *, content: ContentBundle | None = None
) -> EnemyDefinition:
    bundle = content if content is not None else bundled_content()
    candidates: list[str] = []
    for row in bundle.list("enemy", include_locked=False):
        profile = row.get("combat_profile")
        party_profile = profile.get("party_profile") if isinstance(profile, dict) else None
        if (
            row.get("location_key") == location_key
            and isinstance(party_profile, dict)
            and party_profile.get("party_type") == "standard_pve"
        ):
            key = row.get("key")
            if not isinstance(key, str) or not key:
                raise ContentError("standard party enemy has no stable key")
            candidates.append(key)
    if len(candidates) == 1:
        enemy = enemy_definition(candidates[0], content=bundle)
        if not enemy.party_reward:
            raise ContentError(f"party enemy {enemy.key} has no reward")
        return enemy
    if len(candidates) > 1:
        raise ContentError("standard party location has multiple enemies")
    if location_key == BOUNDARY_REALM_LOCATION:
        return enemy_definition(BOUNDARY_REALM_ENEMY, content=bundle)
    if location_key == DEMON_REALM_LOCATION:
        return enemy_definition("enemy.demon_overlord", content=bundle)
    if location_key == BEAST_REALM_LOCATION:
        return enemy_definition("enemy.beast_ancestor", content=bundle)
    raise ValueError("party PVE is not available at this location")


__all__ = [
    "PARTY_BATTLE_MAX_TURNS",
    "PARTY_BATTLE_TYPE",
    "BOUNDARY_REALM_ENEMY",
    "BOUNDARY_REALM_LOCATION",
    "BOUNDARY_REALM_REWARD",
    "BOUNDARY_REALM_STAMINA_COST",
    "BOUNDARY_REALM_TICKET",
    "BOUNDARY_REALM_TICKET_COST",
    "SECRET_REALM_BOUNDARY_PARTY_TYPE",
    "BEAST_REALM_LOCATION",
    "BEAST_REALM_REWARD",
    "BEAST_REALM_STAMINA_COST",
    "DEMON_REALM_LOCATION",
    "DEMON_REALM_REWARD",
    "DEMON_REALM_STAMINA_COST",
    "party_enemy_for_location",
]
