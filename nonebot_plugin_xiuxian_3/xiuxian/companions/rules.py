"""从内容包读取并校验灵兽、灵骑和灵具规则。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..content import ContentBundle, bundled_content


@dataclass(frozen=True, slots=True)
class CompanionDefinition:
    key: str
    label: str
    description: str
    kind: str
    source: tuple[str, ...]
    level_min: int
    level_max: int
    capacity: int
    feed_item_key: str | None = None
    feed_experience: int = 0
    transport_experience: int = 0
    stamina: int = 0
    effect: dict[str, Any] | None = None
    instance_mode: str | None = None
    durability_bp: int = 0


def _bundle(content: ContentBundle | None) -> ContentBundle:
    return content or bundled_content()


def companion_definitions(content: ContentBundle | None = None) -> dict[str, CompanionDefinition]:
    result: dict[str, CompanionDefinition] = {}
    for row in _bundle(content).list("companion", include_locked=False):
        key = row.get("key")
        kind = row.get("kind")
        name = row.get("name")
        desc = row.get("desc")
        source = row.get("source", [])
        level_range = row.get("level_range", [1, 1])
        capacity = row.get("capacity_per_player", 1)
        if (
            not isinstance(key, str)
            or not isinstance(kind, str)
            or not isinstance(name, str)
            or not isinstance(desc, str)
            or not isinstance(source, list)
            or any(not isinstance(item, str) for item in source)
            or not isinstance(level_range, list)
            or len(level_range) != 2
            or any(type(item) is not int for item in level_range)
            or level_range[0] < 1
            or level_range[1] < level_range[0]
            or type(capacity) is not int
            or capacity <= 0
        ):
            raise ValueError(f"灵兽内容记录无效: {row!r}")
        effect = row.get("effect")
        if effect is not None and not isinstance(effect, dict):
            raise ValueError(f"灵兽效果无效: {key}")
        result[key] = CompanionDefinition(
            key=key,
            label=name.strip(),
            description=desc.strip(),
            kind=kind,
            source=tuple(source),
            level_min=level_range[0],
            level_max=level_range[1],
            capacity=capacity,
            feed_item_key=str(row["feed_item_key"]) if row.get("feed_item_key") else None,
            feed_experience=int(row.get("feed_experience", 0)),
            transport_experience=int(row.get("transport_experience", 0)),
            stamina=int(row.get("stamina", 0)),
            effect=dict(effect or {}),
            instance_mode=str(row["instance_mode"]) if row.get("instance_mode") else None,
            durability_bp=int(row.get("durability_bp", 0)),
        )
    return result


def companion_definition(value: str, content: ContentBundle | None = None) -> CompanionDefinition:
    normalized = str(value or "").strip()
    definitions = companion_definitions(content)
    aliases = {definition.label: key for key, definition in definitions.items()}
    key = aliases.get(normalized, normalized)
    try:
        return definitions[key]
    except KeyError as exc:
        raise ValueError(f"unsupported companion: {value}") from exc


def level_after_experience(definition: CompanionDefinition, experience: int) -> int:
    exp = max(0, int(experience))
    if definition.kind == "mount":
        return min(definition.level_max, definition.level_min + exp // 50)
    thresholds = (0, 100, 250, 450, 700, 1000)
    level = definition.level_min
    for candidate, threshold in enumerate(thresholds, start=1):
        if exp >= threshold:
            level = min(definition.level_max, candidate)
    return level


__all__ = [
    "CompanionDefinition",
    "companion_definition",
    "companion_definitions",
    "level_after_experience",
]
