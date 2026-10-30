"""Contract for the material-delivery bounty batch tied to the new gathering lines."""

from __future__ import annotations

from pathlib import Path

from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle

DATA = Path(__file__).parents[1] / "data"

EXPECTED = {
    "bounty.ironwood_timber": ("item.mat.wood", 6, "reward_pool.bounty.herb_supply", "qi_sensing", 2),
    "bounty.ironstone_delivery": ("item.ore.ironstone", 4, "reward_pool.bounty.cloud_mine", "qi_sensing", 2),
    "bounty.grotto_iron_order": ("item.material.cloud_iron", 3, "reward_pool.bounty.herb_supply", "golden_core", 1),
}


def test_output_batch_records_follow_the_bounty_contract() -> None:
    bundle = ContentBundle.load(DATA)
    for key, (item, amount, pool, realm, layer) in EXPECTED.items():
        record = bundle.require("bounty", key)
        assert record["target_kind"] == "inventory_gain", key
        assert record["target_key"] == item, key
        assert record["target_amount"] == amount, key
        assert record["consume_target"] is True, key
        assert record["daily_limit"] == 1, key
        assert record["duration_seconds"] == 1800, key
        assert record["status"] == "open", key
        assert record["required_realm"] == realm and record["required_layer"] == layer, key
        assert record["reward_pool_key"] == pool, key
        assert record["reputation_key"] == "local.xuantian.new_town", key
        # The delivery target and the reward pool must both exist as content.
        assert bundle.get("item", item, include_locked=False) is not None, key
        assert bundle.get("reward", pool, include_locked=False) is not None, key


def test_output_batch_targets_are_produced_by_shipped_content() -> None:
    """Each delivery target must come from content that already exists."""

    bundle = ContentBundle.load(DATA)
    produced: set[str] = set()
    for pool in bundle.list("reward"):
        for outcome in pool.get("outcomes") or []:
            produced.update((outcome.get("rewards") or {}).keys())
    for key, (item, _amount, _pool, _realm, _layer) in EXPECTED.items():
        assert item in produced, f"{key} asks for an item nothing produces: {item}"
