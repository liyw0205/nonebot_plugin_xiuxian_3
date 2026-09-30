"""Pure rules for the first asynchronous team arena mode."""

from __future__ import annotations

from typing import Mapping, Sequence

from .arena_rules import MAX_ROUNDS, battle_roll_bp, rating_band

TEAM_ARENA_MODE_KEY = "arena.team"
MIN_TEAM_SIZE = 2
MAX_TEAM_SIZE = 3
TEAM_SNAPSHOT_VALID_DAYS = 7
TEAM_SNAPSHOT_MATCH_DELAY_SECONDS = 30 * 60
TEAM_DAILY_CHALLENGE_LIMIT = 3
TEAM_WIN_RATING_DELTA = 20
TEAM_LOSS_RATING_DELTA = -8


def team_rating(members: Sequence[Mapping[str, object]]) -> int:
    if not members:
        return 0
    return round(sum(int(member.get("arena_rating", 0)) for member in members) / len(members))


def compatible_team_rating(challenger_rating: int, defender_rating: int) -> bool:
    return abs(rating_band(challenger_rating) - rating_band(defender_rating)) <= 1


def _stats(member: Mapping[str, object]) -> dict[str, int]:
    qualification = member.get("qualification", {})
    if not isinstance(qualification, Mapping):
        qualification = {}
    body = max(0, int(qualification.get("body", 0)))
    agility = max(0, int(qualification.get("agility", 0)))
    return {
        "max_hp": max(1, int(member.get("max_hp", 0)), 100 + body * 4),
        "attack": max(1, 10 + body // 2 + int(member.get("attack_bonus", 0))),
        "initiative": max(1, 8 + agility // 2, int(member.get("initiative", 0))),
        "agility": agility,
    }


def simulate_team_match(
    challenger: Sequence[Mapping[str, object]],
    defender: Sequence[Mapping[str, object]],
    *,
    seed: str,
) -> tuple[str, int, list[dict[str, object]]]:
    """Resolve two immutable team snapshots without accepting client actions."""

    sides = {"challenger": list(challenger), "defender": list(defender)}
    stats = {
        side: {str(member["player_id"]): _stats(member) for member in members}
        for side, members in sides.items()
    }
    hp = {
        side: {player_id: values["max_hp"] for player_id, values in side_stats.items()}
        for side, side_stats in stats.items()
    }
    actions: list[dict[str, object]] = []
    sequence = 0
    for round_no in range(1, MAX_ROUNDS + 1):
        order = sorted(
            ((side, str(member["player_id"])) for side, members in sides.items() for member in members),
            key=lambda item: (-stats[item[0]][item[1]]["initiative"], item[0], item[1]),
        )
        for side, actor_id in order:
            enemies = [
                str(member["player_id"])
                for member in sides["defender" if side == "challenger" else "challenger"]
                if hp["defender" if side == "challenger" else "challenger"][str(member["player_id"])] > 0
            ]
            if hp[side][actor_id] <= 0 or not enemies:
                continue
            target_side = "defender" if side == "challenger" else "challenger"
            target_id = enemies[battle_roll_bp(f"{seed}:round:{round_no}:target:{actor_id}") % len(enemies)]
            sequence += 1
            actor_stats = stats[side][actor_id]
            target_stats = stats[target_side][target_id]
            hit_bp = max(2_000, min(9_800, 8_500 + actor_stats["initiative"] * 20 - target_stats["agility"] * 20))
            hit_roll = battle_roll_bp(f"{seed}:round:{round_no}:action:{sequence}:hit")
            damage = 0
            if hit_roll < hit_bp:
                variance = battle_roll_bp(f"{seed}:round:{round_no}:action:{sequence}:damage") % 5
                damage = max(1, actor_stats["attack"] - 2 + variance)
                hp[target_side][target_id] = max(0, hp[target_side][target_id] - damage)
            actions.append(
                {
                    "sequence_no": sequence,
                    "round_no": round_no,
                    "actor_key": f"{side}:{actor_id}",
                    "strategy_key": "arena.team.auto.basic",
                    "skill_key": "skill.arena.basic_attack",
                    "target_key": f"{target_side}:{target_id}",
                    "hit_roll_bp": hit_roll,
                    "damage": damage,
                    "state": {"challenger_hp": hp["challenger"], "defender_hp": hp["defender"]},
                }
            )
            if not any(value > 0 for value in hp[target_side].values()):
                return ("challenger_won" if target_side == "defender" else "defender_won"), round_no, actions
        if not any(value > 0 for value in hp["challenger"].values()) or not any(value > 0 for value in hp["defender"].values()):
            break
    return "draw", MAX_ROUNDS, actions


def team_public_summary(snapshot: Mapping[str, object], *, snapshot_id: str, rating: int, created_at: str) -> dict[str, object]:
    members = snapshot.get("members", [])
    return {
        "snapshot_id": snapshot_id,
        "party_id": str(snapshot.get("party_id", "")),
        "member_count": len(members) if isinstance(members, list) else TEAM_SIZE,
        "members": [
            {
                "display_name": str(member.get("dao_name") or "未命名"),
                "path_key": str(member.get("path_key") or "未定道途"),
                "realm_key": str(member.get("realm_key") or "mortal"),
                "realm_layer": int(member.get("realm_layer", 0)),
            }
            for member in members
            if isinstance(member, Mapping)
        ],
        "rating": rating,
        "summary": f"{len(members) if isinstance(members, list) else 0}人队伍 · {rating_band(rating) + 1}段",
        "created_at": created_at,
    }


__all__ = [
    "TEAM_ARENA_MODE_KEY",
    "TEAM_DAILY_CHALLENGE_LIMIT",
    "MAX_TEAM_SIZE",
    "MIN_TEAM_SIZE",
    "TEAM_SNAPSHOT_MATCH_DELAY_SECONDS",
    "TEAM_SNAPSHOT_VALID_DAYS",
    "TEAM_LOSS_RATING_DELTA",
    "TEAM_WIN_RATING_DELTA",
    "compatible_team_rating",
    "simulate_team_match",
    "team_public_summary",
    "team_rating",
]
