"""Pure automatic combat previews that never create a runtime session."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ..content import ContentError
from ..stats.rules import frozen_combat_stats

SPAR_CONTENT_KEY = "social.spar"
TRAINING_DUMMY_KEY = "enemy.training_dummy"


@dataclass(frozen=True, slots=True)
class SparDefinition:
    max_rounds: int
    environment_key: str


def spar_definition(content: Any) -> SparDefinition:
    row = _required_record(content, "social_interaction", SPAR_CONTENT_KEY)
    _validate_display_fields(row, "social_interaction", SPAR_CONTENT_KEY)
    max_rounds = row.get("max_rounds")
    if type(max_rounds) is not int or max_rounds < 1:
        raise ContentError(f"social_interaction:{SPAR_CONTENT_KEY}.max_rounds must be a positive integer")
    environment = row.get("environment")
    if not isinstance(environment, Mapping):
        raise ContentError(f"social_interaction:{SPAR_CONTENT_KEY}.environment must be an object")
    environment_key = environment.get("key")
    if not isinstance(environment_key, str) or not environment_key.strip():
        raise ContentError(f"social_interaction:{SPAR_CONTENT_KEY}.environment.key must be a non-empty string")
    if environment.get("relation") != "neutral":
        raise ContentError(f"social_interaction:{SPAR_CONTENT_KEY}.environment.relation must be neutral")
    return SparDefinition(max_rounds=max_rounds, environment_key=environment_key.strip())


def training_dummy_preview_rounds(content: Any) -> int:
    row = _required_record(content, "enemy", TRAINING_DUMMY_KEY)
    profile = row.get("combat_profile")
    rounds = profile.get("preview_max_rounds") if isinstance(profile, Mapping) else None
    if type(rounds) is not int or rounds < 1:
        raise ContentError(f"enemy:{TRAINING_DUMMY_KEY}.combat_profile.preview_max_rounds must be a positive integer")
    return rounds


def simulate_spectator_match(
    challenger: Mapping[str, object],
    defender: Mapping[str, object],
    *,
    seed: str,
    environment: Mapping[str, object] | None = None,
    max_rounds: int,
    challenger_skill_key: str = "skill.basic_attack",
    defender_skill_key: str = "skill.basic_attack",
    strategy_key: str = "strategy.spectator.basic_attack",
) -> tuple[str, int, list[dict[str, object]]]:
    """Resolve two frozen stat maps without accepting player-supplied actions."""

    left = frozen_combat_stats(challenger)
    right = frozen_combat_stats(defender)
    hp = {"challenger": left["max_hp"], "defender": right["max_hp"]}
    stats = {"challenger": left, "defender": right}
    skills = {"challenger": challenger_skill_key, "defender": defender_skill_key}
    sequence = 0
    actions: list[dict[str, object]] = []
    round_limit = max(1, int(max_rounds))
    for round_no in range(1, round_limit + 1):
        if left["initiative"] == right["initiative"]:
            first = "challenger" if battle_roll_bp(f"{seed}:first:{round_no}") < 5_000 else "defender"
        else:
            first = "challenger" if left["initiative"] > right["initiative"] else "defender"
        for actor in (first, "defender" if first == "challenger" else "challenger"):
            target = "defender" if actor == "challenger" else "challenger"
            if hp[actor] <= 0 or hp[target] <= 0:
                continue
            sequence += 1
            actor_stats = stats[actor]
            target_stats = stats[target]
            environment_bonus = 0
            if environment:
                relation = str(environment.get("relation", ""))
                environment_bonus = 150 if relation == "same_faction" else -150 if relation == "cross_faction" else 0
                stability_key = f"{actor}_bloodline_stability"
                environment_bonus += max(0, int(environment.get(stability_key, 0))) // 20
            hit_bp = max(
                2_000,
                min(
                    9_800,
                    8_500
                    + actor_stats["initiative"] * 20
                    - target_stats["agility"] * 20
                    + environment_bonus,
                ),
            )
            hit_roll = battle_roll_bp(f"{seed}:round:{round_no}:action:{sequence}:hit")
            damage = 0
            if hit_roll < hit_bp:
                variance = battle_roll_bp(f"{seed}:round:{round_no}:action:{sequence}:damage") % 5
                damage = max(1, actor_stats["attack"] - 2 + variance)
                hp[target] = max(0, hp[target] - damage)
            actions.append(
                {
                    "sequence_no": sequence,
                    "round_no": round_no,
                    "actor_key": actor,
                    "strategy_key": strategy_key,
                    "skill_key": skills[actor],
                    "target_key": target,
                    "hit_roll_bp": hit_roll,
                    "hit_bp": hit_bp,
                    "hit": hit_roll < hit_bp,
                    "damage": damage,
                    "state": {"challenger_hp": hp["challenger"], "defender_hp": hp["defender"]},
                    "environment": dict(environment or {}),
                }
            )
            if hp[target] <= 0:
                return ("challenger_won" if target == "defender" else "defender_won"), round_no, actions
    return "draw", round_limit, actions


def spectator_seed(*, participants: Mapping[str, object], rules: Mapping[str, object]) -> str:
    payload = json.dumps(
        {"participants": participants, "rules": rules},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def public_spectator_summary(snapshot: Mapping[str, object]) -> dict[str, object]:
    realm_key = snapshot.get("realm_key")
    realm_layer = snapshot.get("realm_layer")
    if not isinstance(realm_key, str) or not realm_key:
        raise ValueError("spectator snapshot is missing realm_key")
    if type(realm_layer) is not int or realm_layer < 0:
        raise ValueError("spectator snapshot has invalid realm_layer")
    return {
        "display_name": str(snapshot.get("dao_name") or "未命名"),
        "path_key": str(snapshot.get("path_key") or "未定道途"),
        "realm_key": realm_key,
        "realm_layer": realm_layer,
    }


def _required_record(content: Any, kind: str, key: str) -> Mapping[str, Any]:
    try:
        row = content.get(kind, key, include_locked=False)
    except (AttributeError, KeyError) as exc:
        raise ContentError(f"required content record not found: {kind}:{key}") from exc
    if not isinstance(row, Mapping) or row.get("key") != key:
        raise ContentError(f"required content record not found: {kind}:{key}")
    return row


def _validate_display_fields(row: Mapping[str, Any], kind: str, key: str) -> None:
    for field in ("name", "desc"):
        value = row.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ContentError(f"{kind}:{key}.{field} must be a non-empty string")
    if row.get("status") not in {"active", "open"}:
        raise ContentError(f"{kind}:{key}.status must be active or open")


def battle_roll_bp(seed: str) -> int:
    digest = hashlib.blake2b(seed.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big") % 10_000


__all__ = [
    "SPAR_CONTENT_KEY",
    "SparDefinition",
    "battle_roll_bp",
    "public_spectator_summary",
    "simulate_spectator_match",
    "spar_definition",
    "spectator_seed",
    "training_dummy_preview_rounds",
]
