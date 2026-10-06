"""Rules for progression milestone qualifications."""

from __future__ import annotations

from dataclasses import dataclass

from ..content import ContentBundle
from .models import LayerUnlock
from .rules import progression_unlock_definitions


@dataclass(frozen=True, slots=True)
class ProgressionMilestoneDefinition:
    key: str
    title: str
    description: str
    required_realm: str
    required_layer: int
    required_total_cultivation: int
    required_max_faction_reputation: int
    required_domain_level: int
    required_void_route_count: int
    unlock_status: str

    def is_eligible(
        self,
        *,
        realm_key: str,
        realm_layer: int,
        total_cultivation: int,
        maximum_faction_reputation: int,
        domain_level: int,
        void_route_count: int,
    ) -> bool:
        return (
            realm_key == self.required_realm
            and realm_layer >= self.required_layer
            and total_cultivation >= self.required_total_cultivation
            and maximum_faction_reputation >= self.required_max_faction_reputation
            and domain_level >= self.required_domain_level
            and void_route_count >= self.required_void_route_count
        )

    def as_unlock(self) -> LayerUnlock:
        return LayerUnlock(
            key=self.key,
            title=self.title,
            description=self.description,
            status=self.unlock_status,
        )


def milestone_definitions(
    content: ContentBundle | None = None,
) -> tuple[ProgressionMilestoneDefinition, ...]:
    return tuple(
        ProgressionMilestoneDefinition(
            key=definition.key,
            title=definition.title,
            description=definition.description,
            required_realm=definition.required_realm,
            required_layer=definition.required_layer,
            required_total_cultivation=definition.required_total_cultivation,
            required_max_faction_reputation=definition.required_max_faction_reputation,
            required_domain_level=definition.required_domain_level,
            required_void_route_count=definition.required_void_route_count,
            unlock_status=definition.unlock_status,
        )
        for definition in progression_unlock_definitions(content)
        if definition.trigger == "qualification"
    )


def due_milestones(
    *,
    realm_key: str,
    realm_layer: int,
    total_cultivation: int,
    maximum_faction_reputation: int = 0,
    domain_level: int = 0,
    void_route_count: int = 0,
    content: ContentBundle | None = None,
) -> tuple[ProgressionMilestoneDefinition, ...]:
    """Return milestones newly eligible from the player's current progression state."""

    return tuple(
        definition
        for definition in milestone_definitions(content)
        if definition.is_eligible(
            realm_key=realm_key,
            realm_layer=realm_layer,
            total_cultivation=total_cultivation,
            maximum_faction_reputation=maximum_faction_reputation,
            domain_level=domain_level,
            void_route_count=void_route_count,
        )
    )


__all__ = [
    "ProgressionMilestoneDefinition",
    "due_milestones",
    "milestone_definitions",
]
