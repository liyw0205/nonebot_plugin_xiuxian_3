"""Focused contract for the two trade-endpoint delivery bounties.

Both bounties ask for a material the two P1 trade-endpoint secret realms
actually drop, reuse an existing reward pool and an existing local-reputation
key, and are gated to the realm/layer that can reach those realms. This file
pins the contract, proves the delivery target is really produced by those
realms' reward pools, proves the wired pool pays out, and covers four bad
record rejections.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from nonebot_plugin_xiuxian_3.xiuxian.adventures.rules import (
    bounty_definitions,
    reward_map,
)
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError
from nonebot_plugin_xiuxian_3.xiuxian.rewards.rules import (
    local_reputation_maximum,
    reward_pool_outcomes,
)
from nonebot_plugin_xiuxian_3.xiuxian.adventures.secret_realm_rules import (
    secret_realm_definitions,
)

DATA = Path(__file__).parents[1] / "data"

# key -> (item, amount, pool, reputation, source realm key)
EXPECTED = {
    "bounty.market.demon_core_run": (
        "item.demon_core",
        2,
        "reward_pool.bounty.demon_relief",
        "local.demon.abyss_market",
        "instance.secret_realm.abyss_market_run",
    ),
    "bounty.market.beast_blood_run": (
        "item.beast_blood",
        2,
        "reward_pool.bounty.beast_habitat",
        "local.beast.three_realms_trade_port",
        "instance.secret_realm.trade_port_convoy",
    ),
}


def _bundle() -> ContentBundle:
    return ContentBundle.load(DATA)


def test_market_bounties_follow_the_shipped_contract() -> None:
    bundle = _bundle()
    by_key = {definition.key: definition for definition in bounty_definitions(bundle)}
    assert set(EXPECTED).issubset(by_key)
    for key, (item, amount, pool, reputation, _realm) in EXPECTED.items():
        definition = by_key[key]
        assert definition.target_kind == "inventory_gain", key
        assert definition.target_key == item, key
        assert definition.target_amount == amount, key
        assert definition.consume_target is True, key
        assert definition.daily_limit == 1, key
        assert definition.duration_seconds == 21600, key
        assert definition.required_realm == "nascent_soul" and definition.required_layer == 1, key
        assert definition.reward_pool_key == pool, key
        assert definition.reputation_key == reputation, key
        assert definition.runtime_status == "open", key
        assert definition.path_keys == (), key
        # Delivery target, reward pool and reputation location must all be real.
        assert bundle.get("item", item, include_locked=False) is not None, key
        assert bundle.get("reward", pool, include_locked=False) is not None, key
        assert local_reputation_maximum(reputation, bundle) > 0, key


def test_market_bounty_targets_are_produced_by_their_realms() -> None:
    """Each delivery target must come from the realm the bounty points at."""

    bundle = _bundle()
    definitions = secret_realm_definitions(bundle)
    for key, (item, _amount, _pool, _reputation, realm) in EXPECTED.items():
        record = definitions[realm]
        produced = set(record.first_reward)
        for _weight, rewards in record.repeat_reward_pool:
            produced.update(rewards)
        assert item in produced, f"{key} asks for {item} but {realm} does not drop it"


def test_market_bounty_pool_pays_and_reputation_key_resolves() -> None:
    bundle = _bundle()
    by_key = {definition.key: definition for definition in bounty_definitions(bundle)}
    for key, (_item, _amount, pool, reputation, _realm) in EXPECTED.items():
        # These bounties reuse existing pools, so only require a real payout.
        outcomes = reward_pool_outcomes(pool, bundle)
        assert outcomes, pool
        assert all(weight > 0 and rewards for weight, rewards in outcomes), pool
        paid = reward_map(by_key[key], bundle, seed=f"market:{key}")
        assert paid and all(quantity > 0 for quantity in paid.values()), key
        # The concrete payout must be one of the pool's declared outcomes.
        assert tuple(sorted(paid.items())) in {
            tuple(sorted(rewards.items())) for _, rewards in outcomes
        }, key
        # A pool must never pay a local reputation the bounty does not declare.
        for _weight, rewards in outcomes:
            for reward_key in rewards:
                if reward_key.startswith("local."):
                    assert reward_key == reputation, (key, reward_key)
        assert local_reputation_maximum(reputation, bundle) > 0, key


@pytest.mark.parametrize(
    "invalid_field",
    (
        "inactive_target",
        "zero_amount",
        "consume_on_wrong_kind",
        "inactive_reputation",
    ),
)
def test_market_bounty_records_reject_bad_content(tmp_path: Path, invalid_field: str) -> None:
    data_dir = tmp_path / invalid_field
    shutil.copytree(DATA, data_dir / "data")
    bounty_path = data_dir / "data" / "任务" / "悬赏.json"
    document = json.loads(bounty_path.read_text(encoding="utf-8"))
    record = next(
        row for row in document["records"] if row["key"] == "bounty.market.demon_core_run"
    )
    if invalid_field == "inactive_target":
        record["target_key"] = "item.missing"
    elif invalid_field == "zero_amount":
        record["target_amount"] = 0
    elif invalid_field == "consume_on_wrong_kind":
        record["target_kind"] = "dispatch_successes"
        record["target_key"] = "dispatch.town_delivery"
        record["consume_target"] = True
    elif invalid_field == "inactive_reputation":
        record["reputation_key"] = "local.missing.place"
    else:  # pragma: no cover - guarded by the parametrize list
        raise AssertionError(invalid_field)
    bounty_path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    with pytest.raises(ContentError):
        bounty_definitions(ContentBundle.load(data_dir / "data"))
