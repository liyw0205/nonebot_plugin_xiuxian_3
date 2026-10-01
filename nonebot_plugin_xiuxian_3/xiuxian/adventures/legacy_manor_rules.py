"""Versioned contracts for clue-driven legacy manors."""

from __future__ import annotations

from dataclasses import dataclass


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


_DEMON_RELIQUARY = LegacyManorDefinition(
    instance_key="instance.legacy.demon_reliquary",
    operation_scope="legacy_manor",
    location_key="demon.fallen_ruins",
    realm_key="nascent_soul",
    realm_layer=1,
    permission="access.demon.fallen_ruins",
    clue="item.clue.demon_contract",
    expiry_seconds=60 * 60,
    story_flag="story.legacy.demon_reliquary",
    node_labels=(
        ("reliquary_seal", "遗府封印"),
        ("pact_archive", "契约档案"),
        ("oath_chamber", "旧誓密室"),
    ),
)

_DEMON_ABYSS_ECHO = LegacyManorDefinition(
    instance_key="instance.legacy.demon_abyss_echo",
    operation_scope="legacy_manor.demon_abyss_echo",
    location_key="demon.abyss_gate",
    realm_key="foundation",
    realm_layer=1,
    permission="access.demon_abyss_gate",
    clue="item.clue.demon_abyss_echo",
    expiry_seconds=60 * 60,
    story_flag="story.legacy.demon_abyss_echo",
    node_labels=(
        ("echo_threshold", "残响门庭"),
        ("sealed_resonance", "封存回声"),
        ("final_whisper", "未竟之言"),
    ),
)

LEGACY_MANOR_DEFINITIONS = {
    _DEMON_RELIQUARY.instance_key: _DEMON_RELIQUARY,
    _DEMON_ABYSS_ECHO.instance_key: _DEMON_ABYSS_ECHO,
}


def get_legacy_manor_definition(instance_key: str) -> LegacyManorDefinition:
    try:
        return LEGACY_MANOR_DEFINITIONS[instance_key]
    except KeyError as exc:
        raise ValueError(f"unknown legacy manor: {instance_key}") from exc


def resolve_legacy_manor_node(value: str, instance_key: str = _DEMON_RELIQUARY.instance_key) -> str | None:
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
