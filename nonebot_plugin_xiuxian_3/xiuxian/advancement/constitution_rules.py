"""Data-backed constitution choices and reshape configuration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..content import ContentBundle, ContentError, bundled_content

CONSUMED_EFFECT_TYPES = frozenset(
    {
        "max_hp_bp",
        "max_mana_bp",
        "initiative_bp",
        "production_quality_bp",
        "drop_weight_bp",
    }
)


@dataclass(frozen=True, slots=True)
class ConstitutionDefinition:
    key: str
    label: str
    description: str
    effect: dict[str, Any]
    status: str = "active"


def _default_content() -> ContentBundle:
    return bundled_content()


def default_content_bundle() -> ContentBundle:
    return _default_content()


def constitution_definitions(content: ContentBundle | None = None) -> dict[str, ConstitutionDefinition]:
    bundle = content or _default_content()
    definitions: dict[str, ConstitutionDefinition] = {}
    used_references: dict[str, str] = {}
    for row in bundle.list("constitution"):
        key = row.get("key")
        name = row.get("name")
        description = row.get("desc")
        effect = row.get("effect")
        if (
            not isinstance(key, str)
            or not isinstance(name, str)
            or not name.strip()
            or not isinstance(description, str)
            or not description.strip()
        ):
            raise ContentError(f"constitution record requires key, name and desc: {row!r}")
        if (
            not isinstance(effect, dict)
            or not isinstance(effect.get("type"), str)
            or not effect["type"]
            or isinstance(effect.get("value"), bool)
            or not isinstance(effect.get("value"), int)
        ):
            raise ContentError(f"constitution {key} requires a typed integer effect")
        status = row.get("status")
        if not isinstance(status, str) or status not in {"active", "open", "locked"}:
            raise ContentError(f"constitution {key} has an invalid status: {status!r}")
        if status == "active" and effect["type"] not in CONSUMED_EFFECT_TYPES:
            raise ContentError(f"active constitution {key} has an unsupported effect: {effect['type']}")
        if effect["value"] < 0:
            raise ContentError(f"constitution {key} effect value cannot be negative")
        aliases = row.get("aliases", [])
        if not isinstance(aliases, list) or any(
            not isinstance(alias, str) or not alias.strip() for alias in aliases
        ):
            raise ContentError(f"constitution {key} aliases must be a string list")
        definition = ConstitutionDefinition(
            key=key,
            label=name.strip(),
            description=description.strip(),
            effect=dict(effect),
            status=status,
        )
        for reference in (definition.key, definition.label, *aliases):
            normalized_reference = reference.strip()
            previous = used_references.get(normalized_reference)
            if previous is not None and previous != key:
                raise ContentError(
                    f"constitution name or alias is duplicated: {normalized_reference!r}"
                )
            used_references[normalized_reference] = key
        definitions[key] = definition
    return definitions


def constitution_reshape_rules(content: ContentBundle | None = None) -> dict[str, Any]:
    bundle = content or _default_content()
    rules = bundle.require(
        "advancement_rule", "constitution.reshape", include_locked=False
    )
    item_key = rules.get("reset_item_key")
    cooldown = rules.get("cooldown_seconds")
    if (
        not isinstance(item_key, str)
        or not item_key
        or not isinstance(cooldown, int)
        or isinstance(cooldown, bool)
        or cooldown <= 0
    ):
        raise ContentError("constitution.reshape requires reset_item_key and positive cooldown_seconds")
    if bundle.get("item", item_key) is None:
        raise ContentError(f"constitution.reshape references unknown reset item: {item_key}")
    return rules


def constitution_definition(
    value: str | None,
    content: ContentBundle | None = None,
) -> ConstitutionDefinition:
    bundle = content or _default_content()
    definitions = constitution_definitions(bundle)
    aliases = {
        alias: key
        for key, definition in definitions.items()
        for alias in (key, definition.label)
    }
    for row in bundle.list("constitution"):
        key = row.get("key")
        if key in definitions:
            aliases.update({str(alias).strip(): str(key) for alias in row.get("aliases", [])})
    normalized = (value or "").strip()
    key = aliases.get(normalized, normalized)
    definition = definitions.get(key)
    if definition is None or definition.status != "active":
        raise ValueError(f"unsupported constitution: {value}")
    return definition


def constitution_options(content: ContentBundle | None = None) -> tuple[ConstitutionDefinition, ...]:
    definitions = constitution_definitions(content)
    return tuple(item for item in definitions.values() if item.status == "active")


__all__ = [
    "ConstitutionDefinition",
    "constitution_definition",
    "constitution_definitions",
    "constitution_options",
    "constitution_reshape_rules",
    "default_content_bundle",
]
