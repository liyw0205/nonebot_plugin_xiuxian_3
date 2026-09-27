"""Immutable records exchanged by the secret-realm application."""

from __future__ import annotations

from dataclasses import dataclass, field

from ...contracts import PlayerView


@dataclass(frozen=True, slots=True)
class SecretRealmDefinition:
    key: str
    label: str
    required_realm: str
    required_layer: int
    location_key: str
    stamina_cost: int
    ticket_key: str | None
    ticket_quantity: int
    node_keys: tuple[str, ...]
    enemy_key: str
    first_reward: dict[str, int]
    repeat_reward: dict[str, int]
    quota_period: str
    quota_limit: int
    rule_version: str
    content_version: str
    expiry_seconds: int = 3600


@dataclass(frozen=True, slots=True)
class SecretRealmPreviewRecord:
    player: PlayerView
    definitions: tuple[SecretRealmDefinition, ...]
    active_run_id: str | None = None


@dataclass(frozen=True, slots=True)
class SecretRealmRunRecord:
    player: PlayerView
    run_id: str
    instance_key: str
    label: str
    status: str
    node_index: int
    current_node: str | None
    allowed_nodes: tuple[str, ...]
    battle_id: str | None = None
    reward: dict[str, int] = field(default_factory=dict)
    first_clear: bool = False
    ticket_locked: int = 0
    stamina_locked: int = 0
    outcome: str | None = None
    ticket_refunded: bool = False
    stamina_refunded: int = 0
    already_completed: bool = False


__all__ = ["SecretRealmDefinition", "SecretRealmPreviewRecord", "SecretRealmRunRecord"]
