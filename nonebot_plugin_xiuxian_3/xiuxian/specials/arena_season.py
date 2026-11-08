"""Pure rules for the local arena weekly ladder.

The board is rebuilt from the immutable match history only: the week window is
derived from the content anchor, a player's rating is the base rating plus the
sum of every recorded rating delta settled before the window ends, and the week's
wins/losses/draws come from the counted matches inside the window.  Nothing here
reads ``players.arena_rating``/``arena_wins``, so a settled week can never move
because of later matches or later player edits.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable, Mapping

WEEK_KEY_PREFIX = "arena.week."
WEEK_LENGTH_DAYS = 7
CLAIM_WINDOW_DAYS = 7
BASE_RATING = 1000


@dataclass(frozen=True, slots=True)
class MatchEvent:
    """One player's side of a settled match, in immutable history."""

    player_id: int
    rating_delta: int
    counted: bool
    outcome: str
    settled_at: datetime


@dataclass(frozen=True, slots=True)
class BoardEntry:
    player_id: int
    rank: int
    rating: int
    wins: int
    losses: int
    draws: int
    first_settled_at: datetime


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def week_start(moment: datetime, anchor: datetime) -> datetime:
    """Start of the seven-day window containing ``moment``."""

    anchor = _aware(anchor)
    moment = _aware(moment)
    periods = (moment - anchor).days // WEEK_LENGTH_DAYS
    start = anchor + timedelta(days=periods * WEEK_LENGTH_DAYS)
    # ``days`` truncates toward zero for negative spans; correct the boundary.
    if start > moment:
        start -= timedelta(days=WEEK_LENGTH_DAYS)
    return start


def week_window(moment: datetime, anchor: datetime) -> tuple[datetime, datetime, str]:
    start = week_start(moment, anchor)
    return start, start + timedelta(days=WEEK_LENGTH_DAYS), week_key(start)


def week_key(start: datetime) -> str:
    return f"{WEEK_KEY_PREFIX}{_aware(start).date().isoformat()}"


def week_window_for_key(key: str, anchor: datetime) -> tuple[datetime, datetime]:
    if not isinstance(key, str) or not key.startswith(WEEK_KEY_PREFIX):
        raise ValueError("arena week key is invalid")
    try:
        start_day = date.fromisoformat(key[len(WEEK_KEY_PREFIX):])
    except ValueError as exc:
        raise ValueError("arena week key is invalid") from exc
    start = datetime.combine(start_day, datetime.min.time(), tzinfo=_aware(anchor).tzinfo)
    return start, start + timedelta(days=WEEK_LENGTH_DAYS)


def week_is_closed(key: str, anchor: datetime, now: datetime) -> bool:
    _start, end = week_window_for_key(key, anchor)
    return _aware(now) >= end


def claim_deadline(key: str, anchor: datetime) -> datetime:
    """A settled week stays claimable for ``CLAIM_WINDOW_DAYS`` days."""

    _start, end = week_window_for_key(key, anchor)
    return end + timedelta(days=CLAIM_WINDOW_DAYS)


def claim_is_open(key: str, anchor: datetime, now: datetime) -> bool:
    return _aware(now) < claim_deadline(key, anchor)


def build_board(
    events: Iterable[MatchEvent],
    *,
    start: datetime,
    end: datetime,
    base_rating: int = BASE_RATING,
) -> tuple[BoardEntry, ...]:
    """Rank the players who scored inside ``[start, end)``.

    Order (``docs/gameplay/specials/arena.md`` §2): rating desc, win rate desc,
    the moment the player first scored in the week asc, then player id asc so the
    order is total and stable.
    """

    start = _aware(start)
    end = _aware(end)
    rating: dict[int, int] = {}
    wins: dict[int, int] = {}
    losses: dict[int, int] = {}
    draws: dict[int, int] = {}
    first: dict[int, datetime] = {}
    counted_week: set[int] = set()
    for event in events:
        settled = _aware(event.settled_at)
        if settled >= end:
            continue
        # Rating is cumulative up to the close of the window: every delta that
        # existed then, counted or not (practice records zero deltas).
        rating[event.player_id] = rating.get(event.player_id, base_rating) + int(event.rating_delta)
        if not (start <= settled < end):
            continue
        if not event.counted:
            continue
        counted_week.add(event.player_id)
        first[event.player_id] = min(first.get(event.player_id, settled), settled)
        if event.outcome == "draw":
            draws[event.player_id] = draws.get(event.player_id, 0) + 1
        elif event.outcome == "won":
            wins[event.player_id] = wins.get(event.player_id, 0) + 1
        else:
            losses[event.player_id] = losses.get(event.player_id, 0) + 1

    def win_rate(player_id: int) -> Fraction:
        played = wins.get(player_id, 0) + losses.get(player_id, 0) + draws.get(player_id, 0)
        return Fraction(wins.get(player_id, 0), played) if played else Fraction(0)

    ordered = sorted(
        counted_week,
        key=lambda player_id: (
            -rating.get(player_id, base_rating),
            -win_rate(player_id),
            first[player_id],
            player_id,
        ),
    )
    return tuple(
        BoardEntry(
            player_id=player_id,
            rank=index + 1,
            rating=rating.get(player_id, base_rating),
            wins=wins.get(player_id, 0),
            losses=losses.get(player_id, 0),
            draws=draws.get(player_id, 0),
            first_settled_at=first[player_id],
        )
        for index, player_id in enumerate(ordered)
    )


def reward_for_rank(record: Mapping[str, Any], rank: int, *, board_size: int) -> dict[str, int]:
    """The frozen payout for a rank: the declared map, else participation."""

    if rank < 1 or rank > board_size:
        raise ValueError("arena rank is outside the board")
    for entry in record["rank_rewards"]:
        if int(entry["rank"]) == rank:
            return dict(entry["reward"])
    return dict(record["default_rank_reward"])


__all__ = [
    "BASE_RATING",
    "CLAIM_WINDOW_DAYS",
    "BoardEntry",
    "MatchEvent",
    "WEEK_KEY_PREFIX",
    "WEEK_LENGTH_DAYS",
    "build_board",
    "claim_deadline",
    "claim_is_open",
    "reward_for_rank",
    "week_is_closed",
    "week_key",
    "week_start",
    "week_window",
    "week_window_for_key",
]
