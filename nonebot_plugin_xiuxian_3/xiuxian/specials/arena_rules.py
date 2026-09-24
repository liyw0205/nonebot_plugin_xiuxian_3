"""Pure, versioned rules for the first asynchronous arena mode."""

from __future__ import annotations

import hashlib
from datetime import timedelta
from typing import Mapping

CONTENT_VERSION = "content-0.6"
RULE_VERSION = "arena-0.1.0"
ARENA_MODE_KEY = "arena.spar"
ARENA_RANK_MODE_KEY = "arena.rank"
ARENA_PRACTICE_MODE_KEY = "arena.practice"
SNAPSHOT_VALID_DAYS = 7
SNAPSHOT_MATCH_DELAY_SECONDS = 30 * 60
DAILY_CHALLENGE_LIMIT = 5
WEEKLY_RANK_LIMIT = 20
DAILY_PRACTICE_LIMIT = 3
DAILY_COUNTED_OPPONENT_LIMIT = 2
MAX_ROUNDS = 15
WIN_RATING_DELTA = 25
LOSS_RATING_DELTA = -10
DRAW_RATING_DELTA = 5


def battle_roll_bp(seed: str) -> int:
    digest = hashlib.blake2b(seed.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big") % 10_000


def rating_band(rating: int) -> int:
    value = max(0, int(rating))
    if value < 500:
        return 0
    if value < 1_000:
        return 1
    if value < 1_500:
        return 2
    return 3


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


def _stats(player: Mapping[str, object]) -> dict[str, int]:
    qualification = player.get("qualification", {})
    if not isinstance(qualification, Mapping):
        qualification = {}
    body = max(0, int(qualification.get("body", 0)))
    agility = max(0, int(qualification.get("agility", 0)))
    return {
        "max_hp": max(1, int(player.get("max_hp", 0)), 100 + body * 4),
        "attack": max(1, 10 + body // 2 + int(player.get("attack_bonus", 0))),
        "initiative": max(1, 8 + agility // 2, int(player.get("initiative", 0))),
        "agility": agility,
    }


def simulate_match(
    challenger: Mapping[str, object], defender: Mapping[str, object], *, seed: str
) -> tuple[str, int, list[dict[str, object]]]:
    """Resolve both immutable snapshots without accepting client actions."""

    left = _stats(challenger)
    right = _stats(defender)
    hp = {"challenger": left["max_hp"], "defender": right["max_hp"]}
    stats = {"challenger": left, "defender": right}
    sequence = 0
    actions: list[dict[str, object]] = []
    for round_no in range(1, MAX_ROUNDS + 1):
        if left["initiative"] == right["initiative"]:
            first = "challenger" if battle_roll_bp(f"{seed}:first:{round_no}") < 5_000 else "defender"
        else:
            first = "challenger" if left["initiative"] > right["initiative"] else "defender"
        order = (first, "defender" if first == "challenger" else "challenger")
        for actor in order:
            target = "defender" if actor == "challenger" else "challenger"
            if hp[actor] <= 0 or hp[target] <= 0:
                continue
            sequence += 1
            actor_stats = stats[actor]
            target_stats = stats[target]
            hit_bp = max(2_000, min(9_800, 8_500 + actor_stats["initiative"] * 20 - target_stats["agility"] * 20))
            hit_roll = battle_roll_bp(f"{seed}:round:{round_no}:action:{sequence}:hit")
            hit = hit_roll < hit_bp
            damage = 0
            if hit:
                variance = battle_roll_bp(f"{seed}:round:{round_no}:action:{sequence}:damage") % 5
                damage = max(1, actor_stats["attack"] - 2 + variance)
                hp[target] = max(0, hp[target] - damage)
            action = {
                "sequence_no": sequence,
                "round_no": round_no,
                "actor_key": actor,
                "strategy_key": "arena.auto.basic",
                "skill_key": "skill.arena.basic_attack",
                "target_key": target,
                "hit_roll_bp": hit_roll,
                "hit_bp": hit_bp,
                "damage": damage,
                "state": {"challenger_hp": hp["challenger"], "defender_hp": hp["defender"]},
            }
            actions.append(action)
            if hp[target] <= 0:
                outcome = "challenger_won" if target == "defender" else "defender_won"
                return outcome, round_no, actions
        if hp["challenger"] <= 0 or hp["defender"] <= 0:
            break
    return "draw", MAX_ROUNDS, actions


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
    "CONTENT_VERSION",
    "DAILY_CHALLENGE_LIMIT",
    "DAILY_COUNTED_OPPONENT_LIMIT",
    "DAILY_PRACTICE_LIMIT",
    "MAX_ROUNDS",
    "RULE_VERSION",
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
