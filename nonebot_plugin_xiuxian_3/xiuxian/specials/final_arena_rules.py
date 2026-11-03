"""Rules for the endgame final arena (``location.final_arena``).

The arena reuses the public-event UTC block window shape (four-hour blocks)
so the round gate matches the rest of the activity system instead of inventing
a second time model.  A round is a UTC block; each character may attempt the
arena ``attempt_limit_per_round`` times inside one round.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from ..content import ContentBundle
from ..world.rules import meets_realm
from .final_arena_content import final_arena_alias_map, final_arena_defaults, final_arena_tiers


@dataclass(frozen=True, slots=True)
class FinalArenaTier:
    key: str
    label: str
    enemy_key: str
    required_best_tier: int
    title_key: str | None = None

    @property
    def tier_index(self) -> int:
        """One-based tier number derived from the ladder position."""

        return self.required_best_tier + 1


@dataclass(frozen=True, slots=True)
class FinalArenaDefinition:
    location_key: str
    block_hours: int
    duration_seconds: int
    claim_window_seconds: int
    attempt_limit_per_round: int
    stamina_cost: int
    required_realm: str
    required_layer: int
    tiers: tuple[FinalArenaTier, ...]

    def tier(self, tier_key: str) -> FinalArenaTier:
        for tier in self.tiers:
            if tier.key == tier_key:
                return tier
        raise ValueError(f"unsupported final arena tier: {tier_key}")

    def tier_by_number(self, tier_no: int) -> FinalArenaTier:
        for tier in self.tiers:
            if tier.tier_index == tier_no:
                return tier
        raise ValueError(f"unsupported final arena tier number: {tier_no}")

    @property
    def summit_tier(self) -> FinalArenaTier:
        return self.tiers[-1]


def final_arena_definition(content: ContentBundle | None = None) -> FinalArenaDefinition:
    defaults = final_arena_defaults(content)
    schedule = defaults["schedule"]
    tiers = tuple(
        FinalArenaTier(
            key=str(record["key"]),
            label=str(record["label"]),
            enemy_key=str(record["enemy_key"]),
            required_best_tier=int(record["required_best_tier"]),
            title_key=str(record["title_key"]) if record.get("title_key") else None,
        )
        for record in final_arena_tiers(content)
    )
    return FinalArenaDefinition(
        location_key=str(defaults["location_key"]),
        block_hours=int(schedule["block_hours"]),
        duration_seconds=int(schedule["duration_seconds"]),
        claim_window_seconds=int(schedule["claim_window_seconds"]),
        attempt_limit_per_round=int(defaults["attempt_limit_per_round"]),
        stamina_cost=int(defaults["stamina_cost"]),
        required_realm=str(defaults["required_realm"]),
        required_layer=int(defaults["required_layer"]),
        tiers=tiers,
    )


# Built at import so a host loading malformed arena content fails the deploy
# validation gate instead of the first player command.
DEFINITIONS = final_arena_definition()


def resolve_final_arena_tier(value: str, content: ContentBundle | None = None) -> str | None:
    normalized = value.strip()
    if not normalized:
        return None
    try:
        aliases = final_arena_alias_map(content)
    except (KeyError, ValueError):
        return None
    return aliases.get(normalized)


def arena_window(
    value: datetime, definition: FinalArenaDefinition = DEFINITIONS
) -> tuple[str, datetime, datetime, datetime]:
    """Return ``(round_id, start, end, claim_expires_at)`` for the round containing ``value``."""

    moment = value.astimezone(timezone.utc) if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    start = moment.replace(minute=0, second=0, microsecond=0)
    start = start.replace(hour=(start.hour // definition.block_hours) * definition.block_hours)
    end = start + timedelta(seconds=definition.duration_seconds)
    claim_expires_at = end + timedelta(seconds=definition.claim_window_seconds)
    return (f"final_arena:{start:%Y%m%d%H%M}", start, end, claim_expires_at)


def arena_is_open(value: datetime, definition: FinalArenaDefinition = DEFINITIONS) -> bool:
    _, start, end, _ = arena_window(value, definition)
    moment = value.astimezone(timezone.utc) if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    return start <= moment < end


def arena_missing_requirements(
    *,
    realm_key: str,
    realm_layer: int,
    definition: FinalArenaDefinition = DEFINITIONS,
) -> tuple[str, ...]:
    """Return the player-facing reasons the arena itself refuses the character."""

    if meets_realm(realm_key, realm_layer, definition.required_realm, definition.required_layer):
        return ()
    return (f"{definition.required_realm} L{definition.required_layer}",)


def next_tier_no(best_tier: int, definition: FinalArenaDefinition = DEFINITIONS) -> int:
    """Return the highest tier number the ladder currently admits."""

    return min(best_tier + 1, len(definition.tiers))


__all__ = [
    "DEFINITIONS",
    "FinalArenaDefinition",
    "FinalArenaTier",
    "arena_is_open",
    "arena_missing_requirements",
    "arena_window",
    "final_arena_definition",
    "next_tier_no",
    "resolve_final_arena_tier",
]
