"""Rules for 道统路线议事 (``dao.choose_route`` / ``dao.council_vote``).

A cycle is one UTC ISO week.  Voters are 合道 members of a sect at level 6 or
above; the cycle settles by majority once the week closes and at least
``required_voters`` votes were cast, costing ``required_sect_merit``.  A tie
carries the previous route forward.  Once settled the route is locked for
``lock_days``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from ..content import ContentBundle
from ..world.rules import meets_realm
from .dao_route_content import dao_route_defaults, dao_route_options


@dataclass(frozen=True, slots=True)
class DaoRouteDefinition:
    name: str
    description: str
    required_sect_level: int
    required_sect_merit: int
    required_voters: int
    required_realm: str
    required_layer: int
    vote_period_days: int
    lock_days: int
    allow_tie_carryover: bool


@dataclass(frozen=True, slots=True)
class DaoRouteOption:
    key: str
    name: str
    description: str
    bonus_key: str
    bonus_bp: int
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DaoRouteState:
    sect_id: str
    sect_name: str
    sect_level: int
    sect_merit: int
    route_key: str | None
    route_label: str | None
    locked_until: str | None
    locked: bool
    cycle_id: str
    cycle_starts_at: str
    cycle_ends_at: str
    settled: bool
    quorum: int
    voter_count: int
    my_vote_key: str | None
    my_vote_label: str | None
    eligible: bool
    missing: tuple[str, ...]
    options: tuple[DaoRouteOption, ...] = ()
    tie_carryover: bool = False


@dataclass(frozen=True, slots=True)
class DaoRouteVoteRecord:
    sect_id: str
    cycle_id: str
    route_key: str
    route_label: str
    voter_count: int
    already_completed: bool = False


@dataclass(frozen=True, slots=True)
class DaoRouteSettlementRecord:
    sect_id: str
    cycle_id: str
    route_key: str | None
    route_label: str | None
    tie_carryover: bool
    voter_count: int
    sect_merit_spent: int
    sect_merit_after: int
    locked_until: str | None
    already_completed: bool = False
    options: tuple[DaoRouteOption, ...] = field(default_factory=tuple)


def dao_route_definition(content: ContentBundle) -> DaoRouteDefinition:
    raw = dao_route_defaults(content)
    return DaoRouteDefinition(
        name=str(raw["name"]),
        description=str(raw["description"]),
        required_sect_level=int(raw["required_sect_level"]),
        required_sect_merit=int(raw["required_sect_merit"]),
        required_voters=int(raw["required_voters"]),
        required_realm=str(raw["required_realm"]),
        required_layer=int(raw["required_layer"]),
        vote_period_days=int(raw["vote_period_days"]),
        lock_days=int(raw["lock_days"]),
        allow_tie_carryover=bool(raw["allow_tie_carryover"]),
    )


def dao_route_option_list(content: ContentBundle) -> tuple[DaoRouteOption, ...]:
    return tuple(
        DaoRouteOption(
            key=str(raw["key"]),
            name=str(raw["name"]),
            description=str(raw["description"]),
            bonus_key=str(raw["bonus_key"]),
            bonus_bp=int(raw["bonus_bp"]),
            aliases=tuple(raw["aliases"]),
        )
        for raw in dao_route_options(content).values()
    )


def dao_route_option(content: ContentBundle, key: str) -> DaoRouteOption:
    for option in dao_route_option_list(content):
        if option.key == key:
            return option
    raise KeyError(key)


def cycle_bounds(now: datetime) -> tuple[str, datetime, datetime]:
    """Return ``(cycle_id, starts_at, ends_at)`` for the UTC ISO week of ``now``."""

    moment = now.astimezone(timezone.utc) if now.tzinfo else now.replace(tzinfo=timezone.utc)
    iso_year, iso_week, _ = moment.isocalendar()
    cycle_id = f"dao_route:{iso_year}-W{iso_week:02d}"
    starts_at = datetime.fromisocalendar(iso_year, iso_week, 1).replace(tzinfo=timezone.utc)
    ends_at = starts_at + timedelta(days=7)
    return cycle_id, starts_at, ends_at


def majority_route(counts: dict[str, int]) -> str | None:
    """Return the winning route, or ``None`` when the top count is shared."""

    if not counts:
        return None
    best = max(counts.values())
    winners = [key for key, count in counts.items() if count == best]
    if len(winners) != 1:
        return None
    return winners[0]


def vote_missing_requirements(
    *,
    definition: DaoRouteDefinition,
    realm_key: str,
    realm_layer: int,
    sect_id: str | None,
    sect_level: int,
    sect_status: str,
) -> list[str]:
    """Return every unmet voter prerequisite in player-facing wording."""

    missing: list[str] = []
    if sect_id is None or sect_status != "active":
        missing.append("宗门成员")
    if not meets_realm(
        realm_key, realm_layer, definition.required_realm, definition.required_layer
    ):
        missing.append("合道境界")
    if sect_id is not None and sect_level < definition.required_sect_level:
        missing.append(f"宗门等级 {definition.required_sect_level}")
    return missing


def settlement_due(*, cycle_ends_at: datetime, now: datetime) -> bool:
    return now >= cycle_ends_at


def lock_active(*, locked_until: str | None, now: datetime) -> bool:
    if locked_until is None:
        return False
    return now < datetime.fromisoformat(locked_until)


def locked_until_at(*, settled_at: datetime, definition: DaoRouteDefinition) -> datetime:
    return settled_at + timedelta(days=definition.lock_days)


def resolve_settlement(
    *,
    definition: DaoRouteDefinition,
    counts: dict[str, int],
    previous_route_key: str | None,
) -> tuple[str | None, bool]:
    """Return ``(route_key, tie_carryover)`` for a closed cycle.

    A majority route wins outright.  A tie carries the previous route when the
    contract allows it; with no previous route the settlement keeps no route and
    only records that a tie occurred.
    """

    winner = majority_route(counts)
    if winner is not None:
        return winner, False
    if definition.allow_tie_carryover and previous_route_key is not None:
        return previous_route_key, True
    return None, True