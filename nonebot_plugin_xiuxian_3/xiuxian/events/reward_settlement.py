"""Shared atomic asset application for public event claims."""

from __future__ import annotations

import json
from typing import Any

from ..rewards.rules import RewardGrant, reward_totals, reward_value_delta
from ..utils.player import grant_player_state


def grant_public_event_reward(
    connection: Any,
    player: Any,
    *,
    round_id: str,
    operation_id: str,
    claimed_at: str,
    grant: RewardGrant,
) -> dict[str, int]:
    reward = reward_totals(grant)
    grant_player_state(
        connection,
        player,
        updated_at=claimed_at,
        rewards=grant.assets,
        value_delta=reward_value_delta(grant),
        player_values=grant.set_values or None,
        reputation_delta=grant.reputation or None,
    )
    connection.execute(
        "INSERT INTO world_event_claims(round_id, player_id, operation_id, reward_json, claimed_at) VALUES (?, ?, ?, ?, ?)",
        (
            round_id,
            player["id"],
            operation_id,
            json.dumps(reward, ensure_ascii=False, sort_keys=True),
            claimed_at,
        ),
    )
    return reward


__all__ = ["grant_public_event_reward"]
