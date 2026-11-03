"""Content-backed contract for 器修机关 (kind ``entity``).

``data/战斗/实体.json`` shipped one ``device.scout_doll`` record with
``status: locked`` and no consumer anywhere in the package.  Foundation docs
freeze the shape ("one device, attack 50%, three rounds, durability and
repair"), so this loader owns parsing and validation and the runtime owns
assembly, deployment, combat actions and durability.

The loader is deliberately strict: every reference (path, realm, item, codex
entry) must resolve, every rate must be a bounded integer, and the combat
window must agree with the shared ``MAX_TURNS`` battle model.
"""

from __future__ import annotations

from typing import Any

from ..content import ContentBundle, ContentError, bundled_content

KIND = "entity"
KEY_PREFIX = "device."
ENTITY_TYPES = {"summoned_device"}
CURRENCY_FIELDS = {"spirit_stones"}
REQUIRED_FIELDS = {
    "key",
    "name",
    "desc",
    "entity_type",
    "status",
    "owner_path_key",
    "max_instances",
    "required_realm",
    "min_layer",
    "assembly",
    "maintenance",
    "durability",
    "combat",
}
# The battle model runs at most twenty rounds, so a device window longer than
# that could never be consumed and would silently be dead content.
MAX_ROUNDS = 20
MAX_MULTIPLIER_BP = 20_000


def _bundle(content: ContentBundle | None) -> ContentBundle:
    return content if content is not None else bundled_content()


def _text(row: dict[str, Any], field: str, key: str) -> str:
    value = row.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ContentError(f"entity {key} requires a {field}")
    return value.strip()


def _positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ContentError(f"entity {label} must be a positive integer")
    return int(value)


def _cost_block(
    value: Any,
    field: str,
    key: str,
    *,
    bundle: ContentBundle,
    allow_zero: bool,
) -> dict[str, Any]:
    """Validate one ``assembly``/``maintenance`` cost block."""

    if not isinstance(value, dict):
        raise ContentError(f"entity {key} {field} must be an object")
    unknown = set(value) - ({"spirit_stones"} | {"items"})
    if unknown:
        raise ContentError(f"entity {key} {field} has unknown fields: {sorted(unknown)}")
    stones = value.get("spirit_stones", 0)
    if isinstance(stones, bool) or not isinstance(stones, int) or stones < 0:
        raise ContentError(f"entity {key} {field}.spirit_stones must be a non-negative integer")
    if stones == 0 and not allow_zero:
        raise ContentError(f"entity {key} {field}.spirit_stones must be positive")
    items = value.get("items", {})
    if not isinstance(items, dict) or not items:
        raise ContentError(f"entity {key} {field}.items must be a non-empty object")
    normalised: dict[str, int] = {}
    for item_key, quantity in items.items():
        if not isinstance(item_key, str) or bundle.get("item", item_key, include_locked=False) is None:
            raise ContentError(f"entity {key} {field} references an unknown item: {item_key!r}")
        normalised[item_key] = _positive_int(
            quantity, f"{key} {field}.items[{item_key}]"
        )
    return {"spirit_stones": int(stones), "items": normalised}


def entity_definitions(content: ContentBundle | None = None) -> dict[str, dict[str, Any]]:
    """Return every validated entity record keyed by its stable key."""

    bundle = _bundle(content)
    definitions: dict[str, dict[str, Any]] = {}
    aliases: dict[str, str] = {}
    for row in bundle.list(KIND):
        key = row.get("key")
        if not isinstance(key, str) or not key.startswith(KEY_PREFIX):
            raise ContentError(f"entity {key!r} must use the {KEY_PREFIX} prefix")
        missing = REQUIRED_FIELDS - set(row)
        if missing:
            raise ContentError(f"entity {key} is missing fields: {sorted(missing)}")
        name = _text(row, "name", key)
        _text(row, "desc", key)
        entity_type = row.get("entity_type")
        if entity_type not in ENTITY_TYPES:
            raise ContentError(f"entity {key} has an unsupported entity_type: {entity_type!r}")
        status = row.get("status")
        if status not in {"active", "open", "locked"}:
            raise ContentError(f"entity {key} has an invalid status: {status!r}")

        path_key = _text(row, "owner_path_key", key)
        if bundle.get("path", path_key, include_locked=False) is None:
            raise ContentError(f"entity {key} references an unknown path: {path_key!r}")

        realm_key = _text(row, "required_realm", key)
        realm = bundle.get("realm", realm_key, include_locked=False)
        if realm is None:
            raise ContentError(f"entity {key} references an unknown realm: {realm_key!r}")
        min_layer = row.get("min_layer")
        if isinstance(min_layer, bool) or not isinstance(min_layer, int):
            raise ContentError(f"entity {key} min_layer must be an integer")
        if not int(realm.get("layer_min", 1)) <= min_layer <= int(realm.get("layer_max", 1)):
            raise ContentError(f"entity {key} min_layer is outside realm {realm_key}")

        max_instances = row.get("max_instances")
        if isinstance(max_instances, bool) or not isinstance(max_instances, int) or max_instances < 1:
            raise ContentError(f"entity {key} max_instances must be a positive integer")

        assembly = _cost_block(
            row.get("assembly"), "assembly", key, bundle=bundle, allow_zero=False
        )
        maintenance = _cost_block(
            row.get("maintenance"), "maintenance", key, bundle=bundle, allow_zero=False
        )

        durability = row.get("durability")
        if not isinstance(durability, dict):
            raise ContentError(f"entity {key} durability must be an object")
        if set(durability) != {"max_bp", "loss_per_action_bp", "repair_bp_per_material"}:
            raise ContentError(f"entity {key} durability fields are invalid")
        max_bp = _positive_int(durability.get("max_bp"), f"{key} durability.max_bp")
        if max_bp > 10_000:
            raise ContentError(f"entity {key} durability.max_bp cannot exceed 10000")
        loss = _positive_int(
            durability.get("loss_per_action_bp"), f"{key} durability.loss_per_action_bp"
        )
        if loss > max_bp:
            raise ContentError(f"entity {key} durability loss exceeds max_bp")
        repair = _positive_int(
            durability.get("repair_bp_per_material"), f"{key} durability.repair_bp_per_material"
        )
        if repair > max_bp:
            raise ContentError(f"entity {key} repair step exceeds max_bp")

        combat = row.get("combat")
        if not isinstance(combat, dict):
            raise ContentError(f"entity {key} combat must be an object")
        if set(combat) != {
            "attack_multiplier_bp",
            "duration_rounds",
            "max_actions_per_battle",
        }:
            raise ContentError(f"entity {key} combat fields are invalid")
        multiplier = _positive_int(
            combat.get("attack_multiplier_bp"), f"{key} combat.attack_multiplier_bp"
        )
        if multiplier > MAX_MULTIPLIER_BP:
            raise ContentError(f"entity {key} combat multiplier is out of range")
        duration_rounds = _positive_int(
            combat.get("duration_rounds"), f"{key} combat.duration_rounds"
        )
        if duration_rounds > MAX_ROUNDS:
            raise ContentError(f"entity {key} combat duration exceeds the battle round limit")
        max_actions = _positive_int(
            combat.get("max_actions_per_battle"), f"{key} combat.max_actions_per_battle"
        )
        if max_actions > MAX_ROUNDS:
            raise ContentError(f"entity {key} combat action cap exceeds the round limit")
        if max_actions > duration_rounds:
            raise ContentError(f"entity {key} combat action cap exceeds its duration")

        codex_key = row.get("codex_entry_key")
        if codex_key is not None:
            if not isinstance(codex_key, str) or bundle.get(
                "codex_entry", codex_key, include_locked=False
            ) is None:
                raise ContentError(f"entity {key} references an unknown codex entry: {codex_key!r}")

        names = [name]
        raw_aliases = row.get("aliases", [])
        if not isinstance(raw_aliases, list):
            raise ContentError(f"entity {key} aliases must be a list")
        for alias in raw_aliases:
            if not isinstance(alias, str) or not alias.strip():
                raise ContentError(f"entity {key} has a malformed alias")
            names.append(alias.strip())
        for label in names:
            owner = aliases.get(label)
            if owner is not None and owner != key:
                raise ContentError(f"entity alias {label!r} is shared by {owner} and {key}")
            aliases[label] = key

        definitions[key] = {
            "key": key,
            "name": name,
            "desc": str(row["desc"]).strip(),
            "aliases": tuple(names),
            "entity_type": str(entity_type),
            "status": str(status),
            "owner_path_key": path_key,
            "max_instances": int(max_instances),
            "required_realm": realm_key,
            "min_layer": int(min_layer),
            "assembly": assembly,
            "maintenance": maintenance,
            "durability": {
                "max_bp": max_bp,
                "loss_per_action_bp": loss,
                "repair_bp_per_material": repair,
            },
            "combat": {
                "attack_multiplier_bp": multiplier,
                "duration_rounds": duration_rounds,
                "max_actions_per_battle": max_actions,
            },
            "codex_entry_key": codex_key,
        }
    return definitions


def entity_alias_map(content: ContentBundle | None = None) -> dict[str, str]:
    """Return ``label -> entity key`` for every accepted player alias."""

    mapping: dict[str, str] = {}
    for key, entry in entity_definitions(content).items():
        for label in entry["aliases"]:
            mapping[label] = key
    return mapping


def resolve_entity_key(value: str | None, content: ContentBundle | None = None) -> str | None:
    """Resolve a stable key or a Chinese label to the entity key."""

    if value is None:
        return None
    definitions = entity_definitions(content)
    if value in definitions:
        return value
    return entity_alias_map(content).get(value.strip())