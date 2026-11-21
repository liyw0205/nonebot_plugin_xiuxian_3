"""Strict content contract for companion battle techniques."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from ..content import ContentBundle, ContentError, bundled_content

_FIELDS = frozenset(
    {
        "key",
        "name",
        "desc",
        "compatible_species",
        "slot_no",
        "unlock_evolution_key",
        "effect",
        "status",
    }
)
_STATUSES = frozenset({"active", "locked"})
_EFFECT_LIMITS = {"opening_attack_bp": 5000, "first_guard_bp": 5000}
_KEY_PATTERN = re.compile(r"technique\.beast\.[a-z0-9_]+\Z")


@dataclass(frozen=True, slots=True)
class CompanionTechniqueDefinition:
    key: str
    label: str
    description: str
    compatible_species: tuple[str, ...]
    slot_no: int
    unlock_evolution_key: str
    effect: dict[str, Any]
    status: str

    @property
    def closed(self) -> bool:
        return self.status != "active"


def _bundle(content: ContentBundle | None) -> ContentBundle:
    return content or bundled_content()


def _species_ancestors(species_key: str, evolutions: dict[str, Any]) -> set[str]:
    ancestors = {species_key}
    changed = True
    while changed:
        changed = False
        for evolution in evolutions.values():
            if evolution.target_key in ancestors and evolution.source_key not in ancestors:
                ancestors.add(evolution.source_key)
                changed = True
    return ancestors


def companion_technique_definitions(
    content: ContentBundle | None = None,
) -> dict[str, CompanionTechniqueDefinition]:
    bundle = _bundle(content)
    from .rules import companion_definitions, companion_evolution_definitions

    species = companion_definitions(bundle, include_locked=True)
    evolutions = companion_evolution_definitions(bundle, include_locked=True)
    result: dict[str, CompanionTechniqueDefinition] = {}
    for row in bundle.list("companion_technique", include_locked=True):
        key = row.get("key")
        if not isinstance(key, str) or _KEY_PATTERN.fullmatch(key) is None:
            raise ContentError(f"companion technique key is invalid: {key!r}")
        if set(row) != _FIELDS:
            raise ContentError(f"companion technique {key} has an invalid field set")
        if key in result:
            raise ContentError(f"duplicate companion technique {key}")
        name = row.get("name")
        description = row.get("desc")
        if not isinstance(name, str) or not name.strip():
            raise ContentError(f"companion technique {key} has no name")
        if not isinstance(description, str) or not description.strip():
            raise ContentError(f"companion technique {key} has no description")
        status = row.get("status")
        if not isinstance(status, str) or status not in _STATUSES:
            raise ContentError(f"companion technique {key} has an invalid status")
        compatible = row.get("compatible_species")
        if (
            not isinstance(compatible, list)
            or not compatible
            or any(not isinstance(item, str) or not item for item in compatible)
            or len(set(compatible)) != len(compatible)
        ):
            raise ContentError(f"companion technique {key} has invalid compatible_species")
        for species_key in compatible:
            definition = species.get(species_key)
            if definition is None or definition.kind != "beast":
                raise ContentError(
                    f"companion technique {key} references unavailable beast {species_key}"
                )
        slot_no = row.get("slot_no")
        if type(slot_no) is not int or slot_no not in {1, 2}:
            raise ContentError(f"companion technique {key} has an invalid slot_no")
        evolution_key = row.get("unlock_evolution_key")
        evolution = evolutions.get(evolution_key) if isinstance(evolution_key, str) else None
        if evolution is None or evolution.kind != "beast" or evolution.skill_slots < slot_no:
            raise ContentError(f"companion technique {key} has an invalid unlock_evolution_key")
        for species_key in compatible:
            if evolution.target_key not in _species_ancestors(species_key, evolutions):
                raise ContentError(
                    f"companion technique {key} unlock evolution does not lead to {species_key}"
                )
        effect = row.get("effect")
        if not isinstance(effect, dict) or set(effect) != {"type", "value"}:
            raise ContentError(f"companion technique {key} has an invalid effect")
        effect_type = effect.get("type")
        value = effect.get("value")
        limit = _EFFECT_LIMITS.get(effect_type) if isinstance(effect_type, str) else None
        if (
            limit is None
            or type(value) is not int
            or not 1 <= value <= limit
        ):
            raise ContentError(f"companion technique {key} has an unsupported effect")
        result[key] = CompanionTechniqueDefinition(
            key=key,
            label=name.strip(),
            description=description.strip(),
            compatible_species=tuple(compatible),
            slot_no=slot_no,
            unlock_evolution_key=evolution_key,
            effect=dict(effect),
            status=status,
        )
    return result


def companion_technique_eligible(
    technique: CompanionTechniqueDefinition,
    *,
    companion_key: str,
    skill_slots: int,
    evolution_stage: str,
    content: ContentBundle | None = None,
) -> bool:
    if (
        technique.closed
        or companion_key not in technique.compatible_species
        or skill_slots < technique.slot_no
        or evolution_stage != "evolved"
    ):
        return False
    from .rules import companion_evolution_definitions

    evolutions = companion_evolution_definitions(_bundle(content), include_locked=True)
    unlock = evolutions[technique.unlock_evolution_key]
    return unlock.target_key in _species_ancestors(companion_key, evolutions)


__all__ = [
    "CompanionTechniqueDefinition",
    "companion_technique_definitions",
    "companion_technique_eligible",
]
