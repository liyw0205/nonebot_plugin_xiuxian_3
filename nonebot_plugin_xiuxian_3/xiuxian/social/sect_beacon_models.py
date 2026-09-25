"""DTOs for the void beacon application boundary."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class VoidBeaconRecord:
    sect_id: str
    status: str
    build_ends_at: str | None
    maintenance_due_at: str | None
    route_discount: int = 0
    already_completed: bool = False


@dataclass(frozen=True, slots=True)
class SectAllianceRecord:
    alliance_id: str
    sect_id: str
    partner_sect_id: str
    partner_sect_name: str
    status: str
    confirmation_expires_at: str
    starts_at: str | None
    ends_at: str | None
    termination_requested: bool = False
    synced_recipe_keys: tuple[str, ...] = field(default_factory=tuple)
    already_completed: bool = False


@dataclass(frozen=True, slots=True)
class AllianceResearchRecord:
    alliance_id: str
    recipe_key: str
    week_id: str
    source_sect_id: str
    target_sect_id: str
    already_completed: bool = False


__all__ = ["AllianceResearchRecord", "SectAllianceRecord", "VoidBeaconRecord"]
