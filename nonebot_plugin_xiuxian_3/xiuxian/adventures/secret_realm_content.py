"""Content-backed contracts for the dedicated secret realms.

Enemy identifiers are validated as non-empty identifiers only: the combat
layer resolves them by composing content records with generated enemies
(the same reason the three-realms tower validates an enemy prefix rather
than concrete enemy keys).
"""

from __future__ import annotations

from typing import Any

from ..content import ContentBundle, ContentError, bundled_content

KIND = "secret_realm_instance"

_OPTIONAL_STRING_FIELDS = (
    "party_type",
    "permission",
    "required_flag",
    "story_flag",
    "codex_entry_key",
    "operation_scope",
    "clue",
    "realm_key",
    "label",
)
_OPTIONAL_INT_FIELDS = ("stamina_cost", "weekly_limit", "quota_limit", "expiry_seconds", "realm_layer")
_OPTIONAL_FLAG_FIELDS = ("energy_suppression", "risk_base_bp", "risk_modifier_bp", "ticket_quantity")


def _bundle(content: ContentBundle | None) -> ContentBundle:
    return content if content is not None else bundled_content()


def _positive_int(value: Any, field: str, key: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ContentError(f"secret realm {key} {field} must be a positive integer")
    return int(value)


def _non_negative_int(value: Any, field: str, key: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ContentError(f"secret realm {key} {field} must be a non-negative integer")
    return int(value)


def _reward_map(value: Any, *, field: str, key: str, bundle: ContentBundle) -> dict[str, int]:
    if not isinstance(value, dict):
        raise ContentError(f"secret realm {key} {field} must be an object")
    rewards: dict[str, int] = {}
    for reward_key, raw_amount in value.items():
        reward_key = str(reward_key)
        amount = _positive_int(raw_amount, f"{field}.{reward_key}", key)
        if reward_key.startswith("item."):
            try:
                bundle.require("item", reward_key, include_locked=True)
            except KeyError as exc:
                raise ContentError(
                    f"secret realm {key} {field} references unknown item {reward_key}"
                ) from exc
        elif not reward_key.strip():
            raise ContentError(f"secret realm {key} {field} has an empty reward key")
        rewards[reward_key] = amount
    return rewards


def _nodes(value: Any, *, key: str, bundle: ContentBundle) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, list) or not value:
        raise ContentError(f"secret realm {key} requires nodes")
    nodes: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, node in enumerate(value):
        if not isinstance(node, dict):
            raise ContentError(f"secret realm {key} node {index} must be an object")
        unknown = set(node) - {"key", "label", "enemy_key"}
        if unknown or "key" not in node or "label" not in node:
            raise ContentError(f"secret realm {key} node {index} has missing or unknown fields")
        node_key = node["key"]
        label = node["label"]
        if not isinstance(node_key, str) or not node_key.strip() or node_key in seen:
            raise ContentError(f"secret realm {key} node {index} has an invalid or duplicate key")
        if not isinstance(label, str) or not label.strip():
            raise ContentError(f"secret realm {key} node {index} requires a label")
        seen.add(node_key)
        normalized: dict[str, Any] = {"key": node_key, "label": label.strip()}
        enemy_key = node.get("enemy_key")
        if enemy_key is not None:
            if not isinstance(enemy_key, str) or not enemy_key.strip():
                raise ContentError(f"secret realm {key} node {index} has an invalid enemy")
            normalized["enemy_key"] = enemy_key
        nodes.append(normalized)
    return tuple(nodes)


def _validated(row: dict[str, Any], bundle: ContentBundle) -> dict[str, Any]:
    key = str(row.get("key"))
    if row.get("status") != "active":
        raise ContentError(f"secret realm {key} is not active")
    for field in ("name", "desc"):
        if not isinstance(row.get(field), str) or not row[field].strip():
            raise ContentError(f"secret realm {key} requires a {field}")
    record: dict[str, Any] = {"key": key, "name": row["name"], "desc": row["desc"]}

    location_key = row.get("location_key")
    if location_key is not None:
        if not isinstance(location_key, str) or not location_key.strip():
            raise ContentError(f"secret realm {key} has an invalid location")
        try:
            bundle.require("location", location_key, include_locked=True)
        except KeyError as exc:
            raise ContentError(
                f"secret realm {key} references unknown location {location_key}"
            ) from exc
        record["location_key"] = location_key

    enemy_key = row.get("enemy_key")
    if enemy_key is not None:
        if not isinstance(enemy_key, str) or not enemy_key.strip():
            raise ContentError(f"secret realm {key} has an invalid enemy")
        record["enemy_key"] = enemy_key

    for field in _OPTIONAL_STRING_FIELDS:
        value = row.get(field)
        if value is None:
            continue
        if not isinstance(value, str) or not value.strip():
            raise ContentError(f"secret realm {key} has an invalid {field}")
        record[field] = value.strip()

    for field in _OPTIONAL_INT_FIELDS:
        value = row.get(field)
        if value is None:
            continue
        record[field] = _positive_int(value, field, key)

    for field in _OPTIONAL_FLAG_FIELDS:
        value = row.get(field)
        if value is None:
            continue
        record[field] = _non_negative_int(value, field, key)

    ticket_key = row.get("ticket_key")
    if ticket_key is not None:
        if not isinstance(ticket_key, str) or not ticket_key.strip():
            raise ContentError(f"secret realm {key} has an invalid ticket")
        try:
            bundle.require("item", ticket_key, include_locked=True)
        except KeyError as exc:
            raise ContentError(f"secret realm {key} references unknown ticket {ticket_key}") from exc
        record["ticket_key"] = ticket_key

    record["nodes"] = _nodes(row.get("nodes"), key=key, bundle=bundle)
    for field in ("first_reward", "repeat_reward"):
        value = row.get(field)
        if value is None:
            continue
        record[field] = _reward_map(value, field=field, key=key, bundle=bundle)
    return record


def secret_realm_records(content: ContentBundle | None = None) -> tuple[dict[str, Any], ...]:
    bundle = _bundle(content)
    rows = bundle.list(KIND, include_locked=False)
    if not rows:
        raise ContentError("no dedicated secret realm content is active")
    return tuple(_validated(row, bundle) for row in sorted(rows, key=lambda item: str(item.get("key"))))


def secret_realm_record(key: str, content: ContentBundle | None = None) -> dict[str, Any]:
    bundle = _bundle(content)
    row = bundle.get(KIND, key, include_locked=False)
    if row is None:
        raise ContentError(f"dedicated secret realm is not active: {key}")
    return _validated(row, bundle)


def node_aliases(record: dict[str, Any]) -> dict[str, str]:
    """Stable key, display label and 1-based ordinal all resolve to the node key."""

    aliases: dict[str, str] = {}
    for index, node in enumerate(record["nodes"], start=1):
        aliases[node["key"]] = node["key"]
        aliases[node["label"]] = node["key"]
        aliases[str(index)] = node["key"]
    return aliases


def node_labels(record: dict[str, Any]) -> dict[str, str]:
    return {node["key"]: node["label"] for node in record["nodes"]}


__all__ = [
    "KIND",
    "node_aliases",
    "node_labels",
    "secret_realm_record",
    "secret_realm_records",
]
