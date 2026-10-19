"""Rules for the first asynchronous arena mode (content-backed)."""

from __future__ import annotations

from datetime import timedelta
from typing import Mapping

from ..combat.spectator_rules import battle_roll_bp, simulate_spectator_match
from .arena_content import arena_defaults, spar_record
from .three_realms_arena_rules import THREE_REALMS_ARENA_MODE_KEY

_SPAR = spar_record()
_DEFAULTS = arena_defaults()

ARENA_MODE_KEY = str(_SPAR["mode_key"])
ARENA_RANK_MODE_KEY = str(_SPAR["rank_mode_key"])
ARENA_PRACTICE_MODE_KEY = str(_SPAR["practice_mode_key"])
SNAPSHOT_VALID_DAYS = int(_SPAR["snapshot_valid_days"])
SNAPSHOT_MATCH_DELAY_SECONDS = int(_SPAR["match_delay_seconds"])
DAILY_CHALLENGE_LIMIT = int(_SPAR["daily_challenge_limit"])
WEEKLY_RANK_LIMIT = int(_SPAR["weekly_rank_limit"])
DAILY_PRACTICE_LIMIT = int(_SPAR["daily_practice_limit"])
DAILY_COUNTED_OPPONENT_LIMIT = int(_SPAR["daily_counted_opponent_limit"])
MAX_ROUNDS = int(_SPAR["max_rounds"])
WIN_RATING_DELTA = int(_SPAR["win_rating_delta"])
LOSS_RATING_DELTA = int(_SPAR["loss_rating_delta"])
DRAW_RATING_DELTA = int(_SPAR["draw_rating_delta"])
RATING_BANDS = tuple(int(band) for band in _DEFAULTS["rating_bands"])


def rating_band(rating: int) -> int:
    value = max(0, int(rating))
    for band, threshold in enumerate(RATING_BANDS):
        if value < threshold:
            return band
    return len(RATING_BANDS)


def compatible_rating(challenger_rating: int, defender_rating: int) -> bool:
    return abs(rating_band(challenger_rating) - rating_band(defender_rating)) <= 1


def rating_delta(outcome: str, *, challenger: bool) -> int:
    if outcome == "draw":
        return DRAW_RATING_DELTA
    won = outcome == "challenger_won"
    if not challenger:
        won = not won
    return WIN_RATING_DELTA if won else LOSS_RATING_DELTA


def mode_period_prefix(mode_key: str, now) -> str:
    """Return the UTC period prefix used for mode-specific attempt limits."""

    if mode_key == ARENA_RANK_MODE_KEY:
        monday = now.date() - timedelta(days=now.weekday())
        return monday.isoformat() + "%"
    return now.date().isoformat() + "%"


def mode_attempt_limit(mode_key: str) -> int:
    if mode_key == ARENA_RANK_MODE_KEY:
        return WEEKLY_RANK_LIMIT
    if mode_key == ARENA_PRACTICE_MODE_KEY:
        return DAILY_PRACTICE_LIMIT
    return DAILY_CHALLENGE_LIMIT


def simulate_match(
    challenger: Mapping[str, object],
    defender: Mapping[str, object],
    *,
    seed: str,
    environment: Mapping[str, object] | None = None,
    max_rounds: int = MAX_ROUNDS,
) -> tuple[str, int, list[dict[str, object]]]:
    """Resolve both immutable snapshots without accepting client actions."""
    return simulate_spectator_match(
        challenger,
        defender,
        seed=seed,
        environment=environment,
        max_rounds=max_rounds,
        challenger_skill_key="skill.arena.basic_attack",
        defender_skill_key="skill.arena.basic_attack",
        strategy_key="arena.auto.basic",
    )


def public_summary(player: Mapping[str, object], *, snapshot_id: str, rating: int, created_at: str) -> dict[str, object]:
    realm = str(player.get("realm_key", "mortal"))
    layer = int(player.get("realm_layer", 0))
    label = str(player.get("dao_name") or "未命名")
    return {
        "snapshot_id": snapshot_id,
        "display_name": label,
        "path_key": str(player.get("path_key") or "未定道途"),
        "realm_key": realm,
        "realm_layer_range": f"L{max(0, layer)}–L{max(0, layer)}",
        "rating": int(rating),
        "summary": f"{realm} · L{max(0, layer)} · {rating_band(rating) + 1}段",
        "created_at": created_at,
    }


__all__ = [
    "ARENA_MODE_KEY",
    "ARENA_PRACTICE_MODE_KEY",
    "ARENA_RANK_MODE_KEY",
    "THREE_REALMS_ARENA_MODE_KEY",
    "DAILY_CHALLENGE_LIMIT",
    "DAILY_COUNTED_OPPONENT_LIMIT",
    "DAILY_PRACTICE_LIMIT",
    "MAX_ROUNDS",
    "RATING_BANDS",
    "SNAPSHOT_MATCH_DELAY_SECONDS",
    "SNAPSHOT_VALID_DAYS",
    "WEEKLY_RANK_LIMIT",
    "compatible_rating",
    "mode_attempt_limit",
    "mode_period_prefix",
    "public_summary",
    "rating_band",
    "rating_delta",
    "simulate_match",
]
