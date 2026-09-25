"""Pure rules for the first two-player automatic PVE session."""

from __future__ import annotations

from .rules import EnemyDefinition


PARTY_BATTLE_TYPE = "pve.party"
PARTY_BATTLE_RULE_VERSION = "combat-party-0.1.0"
PARTY_BATTLE_CONTENT_VERSION = "content-0.1"
PARTY_BATTLE_MAX_TURNS = 20
PARTY_BATTLE_REWARD = {"cultivation": 30, "spirit_stones": 10}
BOUNDARY_REALM_LOCATION = "cave.boundary_realm"
BOUNDARY_REALM_ENEMY = "enemy.boundary_watcher"
BOUNDARY_REALM_STAMINA_COST = 30
BOUNDARY_REALM_TICKET = "item.soul_crystal"
BOUNDARY_REALM_TICKET_COST = 1
BOUNDARY_REALM_REWARD = {"item.soul_crystal": 1}


def party_enemy_for_location(location_key: str) -> EnemyDefinition:
    from .rules import enemy_definition

    if location_key == "xuantian.outskirts":
        return enemy_definition("enemy.wood_rat")
    if location_key == "cave.mist_grotto":
        return enemy_definition("enemy.mist_guardian")
    if location_key == BOUNDARY_REALM_LOCATION:
        return enemy_definition(BOUNDARY_REALM_ENEMY)
    raise ValueError("party PVE is not available at this location")


__all__ = [
    "PARTY_BATTLE_CONTENT_VERSION",
    "PARTY_BATTLE_MAX_TURNS",
    "PARTY_BATTLE_REWARD",
    "PARTY_BATTLE_RULE_VERSION",
    "PARTY_BATTLE_TYPE",
    "BOUNDARY_REALM_ENEMY",
    "BOUNDARY_REALM_LOCATION",
    "BOUNDARY_REALM_REWARD",
    "BOUNDARY_REALM_STAMINA_COST",
    "BOUNDARY_REALM_TICKET",
    "BOUNDARY_REALM_TICKET_COST",
    "party_enemy_for_location",
]
