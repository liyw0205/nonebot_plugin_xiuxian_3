"""Pure rules for explicit automatic party PVE sessions."""

from __future__ import annotations

from dataclasses import dataclass

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


@dataclass(frozen=True, slots=True)
class PartyEntry:
    stamina: int
    energy: int
    daily_limit: int


def party_material_consumers(bundle: ContentBundle, reward: dict[str, int]) -> list[dict]:
    items = {key for key in reward if key.startswith("item.")}
    consumers = []
    for kind, command in (("recipe", "生产预览"), ("livelihood", "城镇委托")):
        for row in bundle.list(kind, include_locked=False):
            inputs = row.get("inputs", {})
            if kind == "livelihood":
                if row.get("record_type") != "commission":
                    continue
                inputs = {item["item_key"]: item["quantity"] for item in inputs}
            if items.intersection(inputs):
                consumers.append({"key": row["key"], "name": row["name"], "command": command, "inputs": inputs})
    return consumers


def party_entry_for_enemy(enemy_key: str, bundle: ContentBundle | None) -> PartyEntry | None:
    bundle = bundle if bundle is not None else bundled_content()
    row = bundle.get("enemy", enemy_key, include_locked=False)
    if row is None:
        return None
    combat = row.get("combat_profile", {})
    profile = combat.get("party_profile", {}) if isinstance(combat, dict) else {}
    if not isinstance(profile, dict):
        raise ContentError(f"enemy {enemy_key} has invalid party profile")
    if "entry" not in profile:
        return None
    entry = profile["entry"]
    if profile.get("party_type") != "standard_pve" or not isinstance(entry, dict) or set(entry) != {"stamina", "energy", "daily_limit"}:
        raise ContentError(f"enemy {enemy_key} has invalid standard party entry")
    if any(type(entry[key]) is not int or entry[key] < 0 for key in ("stamina", "energy")) or type(entry["daily_limit"]) is not int or entry["daily_limit"] <= 0:
        raise ContentError(f"enemy {enemy_key} has invalid party entry costs or daily_limit")
    reward = profile.get("reward")
    if not isinstance(reward, dict) or not reward:
        raise ContentError(f"enemy {enemy_key} requires a party reward")
    for key, amount in reward.items():
        if type(amount) is not int or amount <= 0 or not isinstance(key, str):
            raise ContentError(f"enemy {enemy_key} has invalid party reward")
        if key.startswith("item."):
            if bundle.get("item", key, include_locked=False) is None:
                raise ContentError(f"enemy {enemy_key} references unavailable party reward {key}")
            if amount != 1:
                raise ContentError(f"enemy {enemy_key} item reward exceeds party member cap")
            if not any(key in consumer["inputs"] for consumer in party_material_consumers(bundle, {key: amount})):
                raise ContentError(f"enemy {enemy_key} party reward {key} has no public material consumer")
        elif key not in {"cultivation", "spirit_stones"}:
            raise ContentError(f"enemy {enemy_key} has unsupported party reward {key}")
    if bundle.get("location", row["location_key"], include_locked=False) is None:
        raise ContentError(f"enemy {enemy_key} references unavailable party location")
    return PartyEntry(**entry)


def validate_standard_party_content(bundle: ContentBundle) -> None:
    locations = set()
    for row in bundle.list("enemy", include_locked=False):
        combat = row.get("combat_profile", {})
        profile = combat.get("party_profile", {}) if isinstance(combat, dict) else {}
        if not isinstance(profile, dict):
            raise ContentError(f"enemy {row['key']} has invalid party profile")
        if "entry" in profile:
            party_entry_for_enemy(row["key"], bundle)
        if profile.get("party_type") == "standard_pve":
            if row["location_key"] in locations:
                raise ContentError("standard party location has multiple enemies")
            locations.add(row["location_key"])


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
        party_entry_for_enemy(enemy.key, bundle)
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
    "PartyEntry",
    "party_entry_for_enemy",
    "party_material_consumers",
    "validate_standard_party_content",
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
