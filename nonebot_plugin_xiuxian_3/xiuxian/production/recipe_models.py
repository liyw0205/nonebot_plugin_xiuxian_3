"""Stable recipe records shared by production content slices."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RecipeDefinition:
    key: str
    name: str
    profession: str | None
    inputs: dict[str, int]
    energy_cost: int
    duration_seconds: int
    daily_limit: int
    tool_key: str | None
    tool_cost_bp: int
    currency_cost: int
    outputs: dict[str, int]
    high_quality_bonus: dict[str, int]
    failure_refunds: dict[str, int]
    min_realm_layer: int
    required_realm: str
    proficiency_bp: int = 0
    required_location: tuple[str, ...] = ()
    teaching_allowed: bool = False
    required_path: str | None = None
    required_paths: tuple[str, ...] = ()
    required_subprofession: tuple[str, ...] = ()
    content_version: str = "content-0.1"
    rule_version: str = "production-0.1.0"
    success_threshold_bp: int = 4500
    high_quality_threshold_bp: int = 8000
    facility_kind: str | None = None
    failure_refund_bp: int | None = None
    binding_kind: str | None = None
    binding_duration_seconds: int = 0
    binding_slot_limit: int = 0
    cross_realm_faction: str | None = None


__all__ = ["RecipeDefinition"]
