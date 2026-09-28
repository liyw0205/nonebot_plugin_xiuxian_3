"""Pure, versioned rules for low-tier equipment growth."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from ..content import ContentBundle
from ..versions import active_content_version


# Compatibility export for historical equipment snapshots.
CONTENT_VERSION = active_content_version(fallback="content-0.1")
RULE_VERSION = "advancement-0.1.0"
MAX_TEMPER_LEVEL = 3
TEMPER_MATERIAL = "item.ore.ironstone"
REFINEMENT_MATERIAL = "item.ore.ironstone"
REFINEMENT_PITY_FAILURES = 3
REFINEMENT_SUCCESS_BP = 7500

TEMPER_COSTS = {
    1: (1, 20),
    2: (2, 40),
    3: (3, 80),
}
TEMPER_SUCCESS_BP = {1: 10000, 2: 9000, 3: 7500}


@dataclass(frozen=True, slots=True)
class EquipmentDefinition:
    key: str
    label: str
    slot: str
    max_temper_level: int = MAX_TEMPER_LEVEL


_FALLBACK_EQUIPMENT_DEFINITIONS = {
    "item.weapon.wood_sword": EquipmentDefinition(
        key="item.weapon.wood_sword", label="木纹剑", slot="weapon"
    ),
    "item.weapon.cloud_sword": EquipmentDefinition(
        key="item.weapon.cloud_sword", label="云纹剑", slot="weapon"
    ),
    "item.armor.cotton_robe": EquipmentDefinition(
        key="item.armor.cotton_robe", label="棉袍", slot="armor"
    ),
}


def _content_equipment_definitions() -> dict[str, EquipmentDefinition]:
    bundle = ContentBundle.load_optional(Path(__file__).resolve().parents[3] / "data")
    if bundle is None:
        return dict(_FALLBACK_EQUIPMENT_DEFINITIONS)
    result: dict[str, EquipmentDefinition] = {}
    for row in bundle.list("item", include_locked=False):
        key = row.get("key")
        if not isinstance(key, str) or row.get("item_type") not in {"weapon", "armor"}:
            continue
        fallback = _FALLBACK_EQUIPMENT_DEFINITIONS.get(key)
        result[key] = EquipmentDefinition(
            key=key,
            label=str(row.get("name") or (fallback.label if fallback else key)),
            slot=str(row.get("equipment_slot") or (fallback.slot if fallback else row["item_type"])),
            max_temper_level=int(
                ((row.get("growth") or {}).get("temper") or {}).get(
                    "max_level", fallback.max_temper_level if fallback else MAX_TEMPER_LEVEL
                )
            ),
        )
    for key, definition in _FALLBACK_EQUIPMENT_DEFINITIONS.items():
        result.setdefault(key, definition)
    return result


EQUIPMENT_DEFINITIONS = _content_equipment_definitions()

EQUIPMENT_ALIASES = {
    "木纹剑": "item.weapon.wood_sword",
    "木剑": "item.weapon.wood_sword",
    "云纹剑": "item.weapon.cloud_sword",
    "云剑": "item.weapon.cloud_sword",
    "棉袍": "item.armor.cotton_robe",
    **{key: key for key in EQUIPMENT_DEFINITIONS},
    **{definition.label: key for key, definition in EQUIPMENT_DEFINITIONS.items()},
}

AFFIX_POOL = (
    ("damage", 1),
    ("hp", 5),
    ("initiative", 1),
)


def equipment_definition(value: str | None) -> EquipmentDefinition:
    normalized = (value or "").strip()
    key = EQUIPMENT_ALIASES.get(normalized, normalized)
    try:
        return EQUIPMENT_DEFINITIONS[key]
    except KeyError as exc:
        raise ValueError(f"unsupported equipment: {value}") from exc


def temper_cost(target_level: int) -> tuple[int, int]:
    try:
        return TEMPER_COSTS[int(target_level)]
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"unsupported temper level: {target_level}") from exc


def temper_success_bp(target_level: int) -> int:
    try:
        return TEMPER_SUCCESS_BP[int(target_level)]
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"unsupported temper level: {target_level}") from exc


def temper_roll_bp(seed: str) -> int:
    digest = hashlib.blake2b(seed.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big") % 10000


def refinement_roll_bp(seed: str) -> int:
    return temper_roll_bp(f"{seed}:success")


def refinement_affix(seed: str) -> tuple[str, int]:
    digest = hashlib.sha256(f"{seed}:affix".encode("utf-8")).digest()
    return AFFIX_POOL[int.from_bytes(digest[:8], "big") % len(AFFIX_POOL)]


__all__ = [
    "AFFIX_POOL",
    "CONTENT_VERSION",
    "EQUIPMENT_ALIASES",
    "EQUIPMENT_DEFINITIONS",
    "MAX_TEMPER_LEVEL",
    "REFINEMENT_MATERIAL",
    "REFINEMENT_PITY_FAILURES",
    "REFINEMENT_SUCCESS_BP",
    "RULE_VERSION",
    "TEMPER_COSTS",
    "TEMPER_MATERIAL",
    "TEMPER_SUCCESS_BP",
    "EquipmentDefinition",
    "equipment_definition",
    "refinement_affix",
    "refinement_roll_bp",
    "temper_cost",
    "temper_roll_bp",
    "temper_success_bp",
]
