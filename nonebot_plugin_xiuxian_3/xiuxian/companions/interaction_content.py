"""Validated companion interaction content (companion affinity routines)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..content import ContentBundle, ContentError, bundled_content

_RECORD_FIELDS = frozenset(
    {
        "key",
        "name",
        "desc",
        "base_affinity",
        "constitution_effect",
        "affinity_per_constitution_point",
        "affinity_cap",
        "stamina_cost",
        "daily_limit",
        "status",
    }
)
_OPTIONAL_FIELDS = frozenset({"aliases"})
_STATUSES = frozenset({"active", "open", "locked"})


@dataclass(frozen=True, slots=True)
class CompanionInteractionDefinition:
    key: str
    label: str
    description: str
    base_affinity: int
    constitution_effect: str | None
    affinity_per_constitution_point: int
    affinity_cap: int
    stamina_cost: int
    daily_limit: int
    status: str = "active"
    aliases: tuple[str, ...] = ()

    @property
    def closed(self) -> bool:
        return self.status != "active"


def _bundle(content: ContentBundle | None) -> ContentBundle:
    return content or bundled_content()


def _positive(row: dict[str, Any], field: str, key: str) -> int:
    value = row.get(field)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ContentError(f"companion interaction {key} {field} must be a positive integer")
    return value


def _nonnegative(row: dict[str, Any], field: str, key: str) -> int:
    value = row.get(field)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ContentError(f"companion interaction {key} {field} must be a non-negative integer")
    return value


def companion_interaction_definitions(
    content: ContentBundle | None = None,
) -> dict[str, CompanionInteractionDefinition]:
    bundle = _bundle(content)
    result: dict[str, CompanionInteractionDefinition] = {}
    aliases: set[str] = set()
    for row in bundle.list("companion_interaction", include_locked=True):
        key = row.get("key")
        if not isinstance(key, str) or not key.startswith("interaction."):
            raise ContentError(f"companion interaction key is invalid: {key!r}")
        if key in result:
            raise ContentError(f"duplicate companion interaction {key}")
        if set(row) - _RECORD_FIELDS - _OPTIONAL_FIELDS or not _RECORD_FIELDS <= set(row):
            raise ContentError(f"companion interaction {key} has an invalid field set")
        label = row.get("name")
        description = row.get("desc")
        if not isinstance(label, str) or not label.strip():
            raise ContentError(f"companion interaction {key} has no name")
        if not isinstance(description, str) or not description.strip():
            raise ContentError(f"companion interaction {key} has no description")
        status = row.get("status")
        if not isinstance(status, str) or status not in _STATUSES:
            raise ContentError(f"companion interaction {key} has an invalid status")
        effect = row.get("constitution_effect")
        if effect is not None and (not isinstance(effect, str) or not effect.strip()):
            raise ContentError(f"companion interaction {key} has an invalid constitution effect")
        base = _positive(row, "base_affinity", key)
        per_point = _nonnegative(row, "affinity_per_constitution_point", key)
        cap = _positive(row, "affinity_cap", key)
        if base > cap:
            raise ContentError(f"companion interaction {key} grants more affinity than its cap")
        if per_point and effect is None:
            raise ContentError(
                f"companion interaction {key} scales with a constitution it does not name"
            )
        stamina = _nonnegative(row, "stamina_cost", key)
        limit = _positive(row, "daily_limit", key)
        aliases_row = row.get("aliases", [])
        if not isinstance(aliases_row, list) or any(
            not isinstance(item, str) or not item.strip() for item in aliases_row
        ):
            raise ContentError(f"companion interaction {key} has invalid aliases")
        for alias in aliases_row:
            normalized = alias.strip()
            if normalized in aliases or normalized in result or normalized == key:
                raise ContentError(f"companion interaction alias {normalized} is not unique")
            aliases.add(normalized)
        result[key] = CompanionInteractionDefinition(
            key=key,
            label=label.strip(),
            description=description.strip(),
            base_affinity=base,
            constitution_effect=effect.strip() if isinstance(effect, str) else None,
            affinity_per_constitution_point=per_point,
            affinity_cap=cap,
            stamina_cost=stamina,
            daily_limit=limit,
            status=status,
            aliases=tuple(alias.strip() for alias in aliases_row),
        )
    return result


def companion_interaction_definition(
    value: str, content: ContentBundle | None = None
) -> CompanionInteractionDefinition:
    definitions = companion_interaction_definitions(content)
    normalized = str(value or "").strip()
    if normalized in definitions:
        return definitions[normalized]
    for definition in definitions.values():
        if normalized == definition.label or normalized in definition.aliases:
            return definition
    raise ContentError(f"unknown companion interaction: {normalized}")


def affinity_gain(
    definition: CompanionInteractionDefinition,
    constitution_effect: dict[str, Any] | None,
) -> int:
    """Affinity granted by one interaction, including the constitution bonus."""

    bonus = 0
    if definition.constitution_effect and isinstance(constitution_effect, dict):
        if constitution_effect.get("type") == definition.constitution_effect:
            value = constitution_effect.get("value")
            if isinstance(value, int) and not isinstance(value, bool) and value > 0:
                bonus = value * definition.affinity_per_constitution_point
    return definition.base_affinity + bonus
