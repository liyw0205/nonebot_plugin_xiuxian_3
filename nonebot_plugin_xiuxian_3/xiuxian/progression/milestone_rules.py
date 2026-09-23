"""Versioned rules for progression milestone qualifications."""

from __future__ import annotations

from dataclasses import dataclass

from .models import LayerUnlock


@dataclass(frozen=True, slots=True)
class ProgressionMilestoneDefinition:
    key: str
    title: str
    description: str
    required_realm: str
    required_layer: int
    required_total_cultivation: int
    content_version: str
    rule_version: str
    required_max_faction_reputation: int = 0

    def is_eligible(
        self,
        *,
        realm_key: str,
        realm_layer: int,
        total_cultivation: int,
        maximum_faction_reputation: int,
    ) -> bool:
        return (
            realm_key == self.required_realm
            and realm_layer >= self.required_layer
            and total_cultivation >= self.required_total_cultivation
            and maximum_faction_reputation >= self.required_max_faction_reputation
        )

    def as_unlock(self) -> LayerUnlock:
        return LayerUnlock(key=self.key, title=self.title, description=self.description, status="open")


FOUNDATION_LATE_MILESTONE = ProgressionMilestoneDefinition(
    key="milestone.foundation_late",
    title="筑基圆满里程碑",
    description="已解锁云舟、精英悬赏和洞天二层的资格检查。",
    required_realm="foundation",
    required_layer=9,
    required_total_cultivation=10_000,
    content_version="content-0.2",
    rule_version="progression-0.2.0",
)

NASCENT_SOUL_LATE_MILESTONE = ProgressionMilestoneDefinition(
    key="milestone.nascent_soul_late",
    title="元婴圆满里程碑",
    description="已解锁跨界秘境、赛季首领和道统前置资格。",
    required_realm="nascent_soul",
    required_layer=9,
    required_total_cultivation=210_000,
    required_max_faction_reputation=1_000,
    content_version="content-0.3",
    rule_version="progression-0.3.0",
)

MILESTONE_DEFINITIONS = (FOUNDATION_LATE_MILESTONE, NASCENT_SOUL_LATE_MILESTONE)


def due_milestones(
    *,
    realm_key: str,
    realm_layer: int,
    total_cultivation: int,
    maximum_faction_reputation: int = 0,
) -> tuple[ProgressionMilestoneDefinition, ...]:
    """Return milestones newly eligible from the player's current progression state."""

    return tuple(
        definition
        for definition in MILESTONE_DEFINITIONS
        if definition.is_eligible(
            realm_key=realm_key,
            realm_layer=realm_layer,
            total_cultivation=total_cultivation,
            maximum_faction_reputation=maximum_faction_reputation,
        )
    )


__all__ = [
    "FOUNDATION_LATE_MILESTONE",
    "MILESTONE_DEFINITIONS",
    "NASCENT_SOUL_LATE_MILESTONE",
    "ProgressionMilestoneDefinition",
    "due_milestones",
]
