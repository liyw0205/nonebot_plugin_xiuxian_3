"""Contracts for the six mid/late bounty-variety records and their pools.

The board previously leaned on inventory_gain (31 of 45) while
production_completed and public_service_completions had a single record each.
This slice adds six bounties across foundation..void_refining that use the
underused target kinds, and two weighted pools that actually pay out. The
test pins the shipped contract, proves every target source resolves through
the same loader the runtime uses, and proves every new pool yields a real
reward for a deterministic seed.
"""

from __future__ import annotations

from pathlib import Path

from nonebot_plugin_xiuxian_3.xiuxian.adventures.rules import (
    bounty_definitions,
    reward_map,
)
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle
from nonebot_plugin_xiuxian_3.xiuxian.content_integrity import validate_content_references
from nonebot_plugin_xiuxian_3.xiuxian.rewards.rules import reward_pool_outcomes
from nonebot_plugin_xiuxian_3.xiuxian.specials.dispatch_rules import resolve_dispatch

DATA = Path(__file__).resolve().parents[1] / "data"

# key -> (target_kind, target_key, realm, layer, pool, reputation)
EXPECTED = {
    "bounty.foundation.workshop_order": (
        "production_completed", None, "foundation", 1,
        "reward_pool.bounty.craft_commission", "local.xuantian.new_town",
    ),
    "bounty.foundation.service_round": (
        "public_service_completions", None, "foundation", 4,
        "reward_pool.bounty.service_commission", "local.xuantian.new_town",
    ),
    "bounty.golden_core.patrol_dispatch": (
        "dispatch_successes", "dispatch.golden_core.vein_survey", "golden_core", 1,
        "reward_pool.bounty.craft_commission", "local.xuantian.cloud_city",
    ),
    "bounty.nascent.ruins_hunt": (
        "exploration_battle_wins", "enemy.demon_ruins_scout", "nascent_soul", 1,
        "reward_pool.bounty.service_commission", "local.demon.abyss_market",
    ),
    "bounty.soul.domain_courier": (
        "dispatch_successes", "dispatch.soul.domain_relay", "soul_transformation", 1,
        "reward_pool.bounty.craft_commission", "local.xuantian.domain_front",
    ),
    "bounty.void.archive_watch": (
        "exploration_battle_wins", "enemy.archive_keeper", "void_refining", 1,
        "reward_pool.bounty.service_commission", "local.xuantian.floating_boat",
    ),
}
NEW_POOLS = (
    "reward_pool.bounty.craft_commission",
    "reward_pool.bounty.service_commission",
)


def _bundle() -> ContentBundle:
    return ContentBundle.load(DATA)


def test_six_new_bounties_follow_the_shipped_contract() -> None:
    bundle = _bundle()
    by_key = {definition.key: definition for definition in bounty_definitions(bundle)}
    assert set(EXPECTED).issubset(by_key)
    for key, (kind, target, realm, layer, pool, reputation) in EXPECTED.items():
        definition = by_key[key]
        assert definition.target_kind == kind, key
        assert definition.target_key == target, key
        assert definition.required_realm == realm and definition.required_layer == layer, key
        assert definition.reward_pool_key == pool, key
        assert definition.reputation_key == reputation, key
        assert definition.runtime_status == "open", key
        assert definition.target_amount >= 2, key
        assert definition.consume_target is False, key
        assert definition.daily_limit == 1, key
        # The loader resolves every non-keyless target to real content.
        if kind == "inventory_gain":
            assert bundle.get("item", target, include_locked=False) is not None, key
        elif kind == "exploration_battle_wins":
            assert bundle.get("enemy", target, include_locked=False) is not None, key
        elif kind == "dispatch_successes":
            assert resolve_dispatch(target, bundle).key == target, key
        else:  # keyless kinds are intentionally null
            assert target is None, key


def test_every_new_pool_has_distinct_weighted_outcomes_and_pays_out() -> None:
    bundle = _bundle()
    by_key = {definition.key: definition for definition in bounty_definitions(bundle)}
    for pool in NEW_POOLS:
        outcomes = reward_pool_outcomes(pool, bundle)
        assert len(outcomes) >= 2, pool
        normalized = {tuple(sorted(rewards.items())) for _, rewards in outcomes}
        assert len(normalized) >= 2, pool  # genuinely distinct results
        assert all(weight > 0 and rewards for weight, rewards in outcomes), pool
        # Each bounty wired to this pool selects a concrete, non-empty reward.
        for key, definition in by_key.items():
            if definition.reward_pool_key != pool:
                continue
            paid = reward_map(definition, bundle, seed=f"variety:{key}")
            assert paid and all(quantity > 0 for quantity in paid.values()), key
            assert any(name in paid for name in ("spirit_stones", "local_reputation")), key


def test_release_inventory_counts_the_new_records() -> None:
    summary = validate_content_references(_bundle())
    assert summary["bounties"] == 51
