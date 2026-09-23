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

    def is_eligible(self, *, realm_key: str, realm_layer: int, total_cultivation: int) -> bool:
        return (
            realm_key == self.required_realm
            and realm_layer >= self.required_layer
            and total_cultivation >= self.required_total_cultivation
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

MILESTONE_DEFINITIONS = (FOUNDATION_LATE_MILESTONE,)


def due_milestones(*, realm_key: str, realm_layer: int, total_cultivation: int) -> tuple[ProgressionMilestoneDefinition, ...]:
    """Return milestones newly eligible from the player's current progression state."""

    return tuple(
        definition
        for definition in MILESTONE_DEFINITIONS
        if definition.is_eligible(
            realm_key=realm_key,
            realm_layer=realm_layer,
            total_cultivation=total_cultivation,
        )
    )


__all__ = [
    "FOUNDATION_LATE_MILESTONE",
    "MILESTONE_DEFINITIONS",
    "ProgressionMilestoneDefinition",
    "due_milestones",
]
