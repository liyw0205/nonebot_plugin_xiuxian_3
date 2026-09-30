"""从内容包读取并校验灵兽、灵骑和灵具规则。"""

from __future__ import annotations

import hashlib
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
    transport_injury_chance_bp: int = 0
    transport_injury_recovery_seconds: int = 0
    stamina: int = 0
    effect: dict[str, Any] | None = None
    instance_mode: str | None = None
    durability_bp: int = 0


@dataclass(frozen=True, slots=True)
class CompanionEvolutionDefinition:
    key: str
    source_key: str
    target_key: str
    kind: str
    required_level: int
    required_affinity: int
    costs: dict[str, int]
    success_bp: int
    failure_recovery_seconds: int
    skill_slots: int


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
        transport_experience = row.get("transport_experience", 0)
        injury_chance_bp = row.get("transport_injury_chance_bp", 0)
        injury_recovery_seconds = row.get("transport_injury_recovery_seconds", 0)
        if (
            any(
                isinstance(value, bool) or not isinstance(value, int) or value < 0
                for value in (transport_experience, injury_chance_bp, injury_recovery_seconds)
            )
            or injury_chance_bp > 10_000
        ):
            raise ValueError(f"灵兽运输规则无效: {key}")
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
            transport_experience=transport_experience,
            transport_injury_chance_bp=injury_chance_bp,
            transport_injury_recovery_seconds=injury_recovery_seconds,
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


def companion_evolution_definitions(
    content: ContentBundle | None = None,
) -> dict[str, CompanionEvolutionDefinition]:
    bundle = _bundle(content)
    companions = companion_definitions(bundle)
    result: dict[str, CompanionEvolutionDefinition] = {}
    for row in bundle.list("companion_evolution", include_locked=False):
        key = row.get("key")
        source_key = row.get("source_key")
        target_key = row.get("target_key")
        kind = row.get("kind")
        costs = row.get("costs", {})
        if (
            not isinstance(key, str)
            or not isinstance(source_key, str)
            or not isinstance(target_key, str)
            or kind not in {"beast", "mount"}
            or not isinstance(costs, dict)
        ):
            raise ValueError(f"灵兽蜕变内容记录无效: {row!r}")
        if source_key not in companions or target_key not in companions:
            raise ValueError(f"灵兽蜕变引用了未知品种: {key}")
        if companions[source_key].kind != kind or companions[target_key].kind != kind:
            raise ValueError(f"灵兽蜕变品种不一致: {key}")
        normalized_costs: dict[str, int] = {}
        for raw_cost_key, raw_amount in costs.items():
            if isinstance(raw_amount, bool) or not isinstance(raw_amount, int) or raw_amount < 0:
                raise ValueError(f"灵兽蜕变消耗无效: {key}")
            normalized_costs[str(raw_cost_key)] = raw_amount
        required_level = row.get("required_level")
        required_affinity = row.get("required_affinity", 0)
        success_bp = row.get("success_bp", 10000)
        failure_recovery_seconds = row.get("failure_recovery_seconds", 0)
        skill_slots = row.get("skill_slots", 0)
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in (required_level, required_affinity, success_bp, failure_recovery_seconds, skill_slots)
        ) or success_bp > 10000:
            raise ValueError(f"灵兽蜕变门槛无效: {key}")
        result[key] = CompanionEvolutionDefinition(
            key=key,
            source_key=source_key,
            target_key=target_key,
            kind=kind,
            required_level=required_level,
            required_affinity=required_affinity,
            costs=normalized_costs,
            success_bp=success_bp,
            failure_recovery_seconds=failure_recovery_seconds,
            skill_slots=skill_slots,
        )
    return result


def companion_evolution_definition(
    value: str,
    content: ContentBundle | None = None,
) -> CompanionEvolutionDefinition:
    definitions = companion_evolution_definitions(content)
    normalized = str(value or "").strip()
    if normalized in definitions:
        return definitions[normalized]
    for definition in definitions.values():
        if definition.source_key == normalized:
            return definition
    raise ValueError(f"unsupported companion evolution: {value}")


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


def mount_transport_duration(base_seconds: int, definition: CompanionDefinition, level: int) -> int:
    """Apply the content-defined mount travel modifier to a route duration."""

    effect = definition.effect or {}
    if effect.get("type") != "transport_duration_multiplier_bp":
        return max(1, int(base_seconds))
    per_level = int(effect.get("value_per_level", 0))
    multiplier_bp = max(0, 10_000 - per_level * max(0, int(level)))
    return max(1, (int(base_seconds) * multiplier_bp + 9_999) // 10_000)


def mount_transport_stamina(base_cost: int, gear: tuple[dict[str, object], ...], content: ContentBundle | None = None) -> int:
    """Apply the active mount-tack stamina effect, never reducing cost below one."""

    total = int(base_cost)
    bundle = _bundle(content)
    for item in gear:
        if str(item.get("status", "")) != "equipped" or int(item.get("durability_bp", 0)) <= 0:
            continue
        record = bundle.get("companion", str(item.get("gear_key", "")), include_locked=False)
        if record is None or record.get("kind") != "mount_tack":
            continue
        effect = record.get("effect")
        if isinstance(effect, dict) and effect.get("type") == "transport_stamina_cost_delta":
            total += int(effect.get("value", 0))
    return max(1, total)


def mount_transport_injury_roll_bp(operation_id: str) -> int:
    """Return the deterministic hazard roll used by a transport settlement."""

    digest = hashlib.blake2b(f"{operation_id}:mount-injury".encode("utf-8"), digest_size=2).digest()
    return int.from_bytes(digest, "big") % 10_000


__all__ = [
    "CompanionDefinition",
    "CompanionEvolutionDefinition",
    "companion_definition",
    "companion_definitions",
    "companion_evolution_definition",
    "companion_evolution_definitions",
    "level_after_experience",
    "mount_transport_duration",
    "mount_transport_stamina",
    "mount_transport_injury_roll_bp",
]
