"""Content invariants for exploration reward variety (phase P3).

The thinnest active exploration pools must offer at least two distinct
outcomes, and every mode with a battle chance must keep a well-defined
battle-failure resolution (an explicit content-backed ``battle_failure_rewards``
where declared, otherwise the documented no-reward-on-loss path).
"""
from __future__ import annotations

from pathlib import Path

from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle
from nonebot_plugin_xiuxian_3.xiuxian.exploration.rules import (
    EXPLORATION_REWARD_POOLS,
    exploration_definition,
    settlement_failure_result,
)
from nonebot_plugin_xiuxian_3.xiuxian.rewards.rules import (
    reward_pool_battle_failure_rewards,
    reward_pool_outcomes,
)

DATA = Path(__file__).parents[1] / "data"


def _bundle() -> ContentBundle:
    return ContentBundle.load(DATA)


def _active_exploration_pool_keys(bundle: ContentBundle) -> list[str]:
    return sorted(
        row["key"]
        for row in bundle.list("reward", include_locked=False)
        if row["key"].startswith("reward_pool.exploration.")
    )


def test_all_active_exploration_pools_have_at_least_two_distinct_outcomes() -> None:
    bundle = _bundle()
    pool_keys = _active_exploration_pool_keys(bundle)
    assert len(pool_keys) == 25
    distinct_counts: dict[str, int] = {}
    for pool_key in pool_keys:
        outcomes = reward_pool_outcomes(pool_key, bundle)
        distinct = {tuple(sorted(rewards.items())) for _, rewards in outcomes}
        distinct_counts[pool_key] = len(distinct)
        assert len(distinct) >= 2, (
            f"exploration pool {pool_key} has only {len(distinct)} distinct outcome(s)"
        )
    # The two historically thinnest pools are explicitly verified.
    assert distinct_counts["reward_pool.exploration.demon_threshold"] >= 2
    assert distinct_counts["reward_pool.exploration.ancestral_lake"] >= 2


def test_every_battle_mode_resolves_a_battle_failure_result() -> None:
    bundle = _bundle()
    battle_modes = [
        mode_key
        for mode_key in EXPLORATION_REWARD_POOLS
        if exploration_definition(mode_key, bundle).battle_chance_bp > 0
    ]
    assert battle_modes, "expected at least one exploration mode with a battle chance"
    for mode_key in battle_modes:
        # Resolves to an explicit content-backed fallback where declared,
        # otherwise to the documented empty (no-reward) loss path.
        result = settlement_failure_result(mode_key, content=bundle)
        assert isinstance(result, dict), mode_key
        assert all(isinstance(value, int) for value in result.values()), mode_key
        declared = reward_pool_battle_failure_rewards(
            EXPLORATION_REWARD_POOLS[mode_key], bundle
        )
        assert result == declared, mode_key


def test_cloud_mine_keeps_explicit_battle_failure_fallback() -> None:
    bundle = _bundle()
    pool_key = EXPLORATION_REWARD_POOLS["explore.cloud_mine"]
    fallback = reward_pool_battle_failure_rewards(pool_key, bundle)
    assert fallback, "cloud_mine must retain an explicit battle-failure fallback"
    assert settlement_failure_result("explore.cloud_mine", content=bundle) == fallback


def test_thinnest_pool_original_outcome_is_still_the_dominant_choice() -> None:
    """The original fixed outcome stays the dominant (first) weighted branch.

    This keeps the documented deterministic frozen rewards stable across the
    existing restart/idempotency contracts while still adding real variety.
    """
    bundle = _bundle()
    for pool_key, original in (
        (
            "reward_pool.exploration.demon_threshold",
            {"item.demon_core": 1, "item.soul_crystal": 1},
        ),
        (
            "reward_pool.exploration.ancestral_lake",
            {"faction_reputation.beast": 30, "item.ancestral_blood": 1},
        ),
    ):
        outcomes = reward_pool_outcomes(pool_key, bundle)
        assert outcomes[0][1] == original
        assert outcomes[0][0] > sum(weight for weight, _ in outcomes[1:])
        second = outcomes[1][1]
        assert second and second != original
