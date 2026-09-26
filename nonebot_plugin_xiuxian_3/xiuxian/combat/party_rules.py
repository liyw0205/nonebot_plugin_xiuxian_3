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
BOUNDARY_REALM_SOUL_POWER_MAX = 300
BOUNDARY_REALM_REWARD = {"item.soul_crystal": 1, "soul_power": 50}
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


def party_enemy_for_location(location_key: str) -> EnemyDefinition:
    from .rules import enemy_definition

    if location_key == "xuantian.outskirts":
        return enemy_definition("enemy.wood_rat")
    if location_key == "cave.mist_grotto":
        return enemy_definition("enemy.mist_guardian")
    if location_key == BOUNDARY_REALM_LOCATION:
        return enemy_definition(BOUNDARY_REALM_ENEMY)
    if location_key == DEMON_REALM_LOCATION:
        return enemy_definition("enemy.demon_overlord")
    if location_key == BEAST_REALM_LOCATION:
        return enemy_definition("enemy.beast_ancestor")
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
    "BEAST_REALM_LOCATION",
    "BEAST_REALM_REWARD",
    "BEAST_REALM_STAMINA_COST",
    "DEMON_REALM_LOCATION",
    "DEMON_REALM_REWARD",
    "DEMON_REALM_STAMINA_COST",
    "party_enemy_for_location",
]
