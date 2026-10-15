"""Contracts for clue-driven legacy manors (content-backed)."""

from __future__ import annotations

from dataclasses import dataclass

from .secret_realm_content import secret_realm_records

LEGACY_MANOR_PRIMARY_KEY = "instance.legacy.demon_reliquary"


@dataclass(frozen=True, slots=True)
class LegacyManorDefinition:
    instance_key: str
    operation_scope: str
    location_key: str
    realm_key: str
    realm_layer: int
    permission: str
    clue: str
    expiry_seconds: int
    story_flag: str
    node_labels: tuple[tuple[str, str], ...]

    @property
    def nodes(self) -> tuple[str, ...]:
        return tuple(key for key, _ in self.node_labels)

    @property
    def labels(self) -> dict[str, str]:
        return dict(self.node_labels)


def _definition(record: dict) -> LegacyManorDefinition:
    return LegacyManorDefinition(
        instance_key=str(record["key"]),
        operation_scope=str(record["operation_scope"]),
        location_key=str(record["location_key"]),
        realm_key=str(record["realm_key"]),
        realm_layer=int(record["realm_layer"]),
        permission=str(record["permission"]),
        clue=str(record["clue"]),
        expiry_seconds=int(record["expiry_seconds"]),
        story_flag=str(record["story_flag"]),
        node_labels=tuple(
            (str(node["key"]), str(node["label"])) for node in record["nodes"]
        ),
    )


def _manor_records() -> tuple[dict, ...]:
    return tuple(
        record
        for record in secret_realm_records()
        if str(record.get("operation_scope", "")).startswith("legacy_manor")
    )


LEGACY_MANOR_DEFINITIONS = {
    definition.instance_key: definition
    for definition in (_definition(record) for record in _manor_records())
}

_DEMON_RELIQUARY = LEGACY_MANOR_DEFINITIONS[LEGACY_MANOR_PRIMARY_KEY]


def get_legacy_manor_definition(instance_key: str) -> LegacyManorDefinition:
    try:
        return LEGACY_MANOR_DEFINITIONS[instance_key]
    except KeyError as exc:
        raise ValueError(f"unknown legacy manor: {instance_key}") from exc


def resolve_legacy_manor_node(
    value: str, instance_key: str = LEGACY_MANOR_PRIMARY_KEY
) -> str | None:
    definition = get_legacy_manor_definition(instance_key)
    aliases = {key: key for key in definition.nodes}
    aliases.update({label: key for key, label in definition.node_labels})
    aliases.update({str(index + 1): key for index, key in enumerate(definition.nodes)})
    return aliases.get(value.strip())


LEGACY_MANOR_KEY = _DEMON_RELIQUARY.instance_key
LEGACY_MANOR_LOCATION = _DEMON_RELIQUARY.location_key
LEGACY_MANOR_PERMISSION = _DEMON_RELIQUARY.permission
LEGACY_MANOR_CLUE = _DEMON_RELIQUARY.clue
LEGACY_MANOR_EXPIRY_SECONDS = _DEMON_RELIQUARY.expiry_seconds
LEGACY_MANOR_STORY_FLAG = _DEMON_RELIQUARY.story_flag
LEGACY_MANOR_NODES = _DEMON_RELIQUARY.nodes
LEGACY_MANOR_NODE_LABELS = _DEMON_RELIQUARY.labels


__all__ = [
    "LEGACY_MANOR_CLUE",
    "LEGACY_MANOR_DEFINITIONS",
    "LEGACY_MANOR_EXPIRY_SECONDS",
    "LEGACY_MANOR_KEY",
    "LEGACY_MANOR_LOCATION",
    "LEGACY_MANOR_NODE_LABELS",
    "LEGACY_MANOR_NODES",
    "LEGACY_MANOR_PERMISSION",
    "LEGACY_MANOR_STORY_FLAG",
    "LegacyManorDefinition",
    "get_legacy_manor_definition",
    "resolve_legacy_manor_node",
]
