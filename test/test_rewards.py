from __future__ import annotations

import asyncio
import json
import shutil
from fractions import Fraction
from itertools import product
from math import prod
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle
from nonebot_plugin_xiuxian_3.xiuxian.rewards.rules import (
    RewardContentError,
    RewardGrant,
    combine_reward_grants,
    reward_definition,
    reward_pool_map,
    reward_pool_outcomes,
)


def _context(adapter: str, user: str, operation_id: str) -> CommandContext:
    return CommandContext(adapter=adapter, user_id=user, operation_id=operation_id)


def test_onboarding_reward_is_loaded_from_content_for_both_adapters() -> None:
    async def run() -> None:
        with TemporaryDirectory() as temp:
            data_dir = Path(temp) / "data"
            shutil.copytree(Path(__file__).parents[1] / "data", data_dir)
            reward_file = data_dir / "奖励" / "奖励.json"
            document = json.loads(reward_file.read_text(encoding="utf-8"))
            record = next(item for item in document["records"] if item["key"] == "reward.onboarding.seeking")
            next(entry for entry in record["entries"] if entry["kind"] == "currency")["quantity"] = 777
            stamina = next(entry for entry in record["entries"] if entry.get("resource_key") == "stamina")
            stamina["quantity"] = 42
            stamina["set_max"] = 42
            reward_file.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            runtime = create_runtime(data_dir=data_dir, adapters=("qq.official", "onebot.v11"))
            try:
                for adapter in ("qq.official", "onebot.v11"):
                    user = f"reward-{adapter}"
                    assert (await runtime.adapters.dispatch(adapter, _context(adapter, user, f"{adapter}-create"), "开始修仙")).ok
                    started = await runtime.adapters.dispatch(
                        adapter, _context(adapter, user, f"{adapter}-seek"), "寻仙问道"
                    )
                    assert started.code == "SEEKING_STARTED"
                    assert started.data["spirit_stones"] == 777
                    assert started.data["stamina"] == 42
                    assert started.data["stamina_max"] == 42
                    assert started.data["reward"] == {
                        "spirit_stones": 777,
                        "item.food.coarse_spirit_rice": 3,
                        "item.herb.blood_grass": 3,
                        "stamina": 42,
                        "energy": 30,
                    }
                    replay = await runtime.adapters.dispatch(
                        adapter, _context(adapter, user, f"{adapter}-seek"), "寻仙问道"
                    )
                    assert replay.code == "SEEKING_ALREADY_DONE"
                    assert replay.data["idempotent_replay"] is True
                    assert replay.data["reward"] == started.data["reward"]
                    conflict = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, user, f"{adapter}-seek"),
                        "寻仙问道 木",
                    )
                    assert conflict.code == "OPERATION_CONFLICT"
            finally:
                await runtime.close()
            recovered = create_runtime(data_dir=data_dir, adapters=("qq.official",))
            try:
                replay = await recovered.adapters.dispatch(
                    "qq.official",
                    _context("qq.official", "reward-qq.official", "qq.official-seek"),
                    "寻仙问道",
                )
                assert replay.code == "SEEKING_ALREADY_DONE"
                assert replay.data["idempotent_replay"] is True
            finally:
                await recovered.close()

    asyncio.run(run())


def test_reward_parser_rejects_unknown_item_and_wrong_operation(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    shutil.copytree(Path(__file__).parents[1] / "data", data_dir)
    reward_file = data_dir / "奖励" / "奖励.json"
    document = json.loads(reward_file.read_text(encoding="utf-8"))
    record = next(item for item in document["records"] if item["key"] == "reward.onboarding.seeking")
    record["entries"].append({"kind": "item", "item_key": "item.不存在", "quantity": 1})
    reward_file.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    bundle = ContentBundle.load(data_dir)
    try:
        reward_definition("reward.onboarding.seeking", bundle, operation="player.start_seeking")
    except RewardContentError as exc:
        assert "inactive item" in str(exc)
    else:
        raise AssertionError("unknown reward item must fail content validation")

    clean_bundle = ContentBundle.load(Path(__file__).parents[1] / "data")
    try:
        reward_definition("reward.onboarding.seeking", clean_bundle, operation="other.operation")
    except RewardContentError as exc:
        assert "belongs to player.start_seeking" in str(exc)
    else:
        raise AssertionError("a reward must not be applied to a different operation")


def test_reward_parser_rejects_invalid_quantity_and_maximum(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    shutil.copytree(Path(__file__).parents[1] / "data", data_dir)
    reward_file = data_dir / "奖励" / "奖励.json"
    document = json.loads(reward_file.read_text(encoding="utf-8"))
    record = next(item for item in document["records"] if item["key"] == "reward.onboarding.seeking")

    next(entry for entry in record["entries"] if entry["kind"] == "currency")["quantity"] = 0
    reward_file.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    bundle = ContentBundle.load(data_dir)
    try:
        reward_definition("reward.onboarding.seeking", bundle, operation="player.start_seeking")
    except RewardContentError as exc:
        assert "quantity must be positive" in str(exc)
    else:
        raise AssertionError("zero reward quantity must fail content validation")

    document = json.loads((Path(__file__).parents[1] / "data" / "奖励" / "奖励.json").read_text(encoding="utf-8"))
    record = next(item for item in document["records"] if item["key"] == "reward.onboarding.seeking")
    next(entry for entry in record["entries"] if entry.get("resource_key") == "stamina")["set_max"] = "yes"
    reward_file.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    bundle = ContentBundle.load(data_dir)
    try:
        reward_definition("reward.onboarding.seeking", bundle, operation="player.start_seeking")
    except RewardContentError as exc:
        assert "set_max must be positive" in str(exc)
    else:
        raise AssertionError("invalid set_max must fail content validation")


def test_reward_parser_rejects_conflicting_resource_modes_and_empty_reputation(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    shutil.copytree(Path(__file__).parents[1] / "data", data_dir)
    reward_file = data_dir / "奖励" / "奖励.json"
    document = json.loads(reward_file.read_text(encoding="utf-8"))
    base = next(item for item in document["records"] if item["key"] == "reward.event.spirit_spring.base")
    base["entries"].append(
        {"kind": "resource", "resource_key": "cultivation", "quantity": 1, "set_max": 1}
    )
    reward_file.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    bundle = ContentBundle.load(data_dir)
    try:
        reward_definition("reward.event.spirit_spring.base", bundle, operation="event.claim_reward")
    except RewardContentError as exc:
        assert "both delta and fixed values" in str(exc)
    else:
        raise AssertionError("conflicting resource modes must fail content validation")

    document = json.loads(reward_file.read_text(encoding="utf-8"))
    base = next(item for item in document["records"] if item["key"] == "reward.event.spirit_spring.base")
    base["entries"].pop()
    completion = next(
        item for item in document["records"] if item["key"] == "reward.event.spirit_spring.completion"
    )
    completion["entries"][0]["reputation_key"] = "faction_reputation."
    reward_file.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    bundle = ContentBundle.load(data_dir)
    try:
        reward_definition("reward.event.spirit_spring.completion", bundle, operation="event.claim_reward")
    except RewardContentError as exc:
        assert "requires a faction" in str(exc)
    else:
        raise AssertionError("empty reputation keys must fail content validation")


def test_reward_grant_composition_rejects_cross_grant_state_conflicts() -> None:
    delta = RewardGrant("delta", "event.claim_reward", {}, {"stamina": 1}, {}, {})
    fixed = RewardGrant("fixed", "event.claim_reward", {}, {}, {"stamina": 10}, {})
    try:
        combine_reward_grants(delta, fixed)
    except RewardContentError as exc:
        assert "both delta and fixed values" in str(exc)
    else:
        raise AssertionError("cross-grant resource conflicts must fail")


def test_weighted_reward_pool_rejects_invalid_content(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    shutil.copytree(Path(__file__).parents[1] / "data", data_dir)
    reward_file = data_dir / "奖励" / "奖励.json"
    document = json.loads(reward_file.read_text(encoding="utf-8"))
    pool = next(
        item for item in document["records"] if item["key"] == "reward_pool.exploration.trial_outskirts"
    )
    pool["outcomes"] = [{"weight": 0, "rewards": {"cultivation": 1}}]
    reward_file.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
    bundle = ContentBundle.load(data_dir)
    try:
        reward_pool_map("reward_pool.exploration.trial_outskirts", "invalid", bundle)
    except RewardContentError as exc:
        assert "invalid weight" in str(exc)
    else:
        raise AssertionError("invalid weighted pool must fail content validation")


@pytest.mark.parametrize(
    ("pool_key", "distributions"),
    [
        (
            "reward_pool.exploration.gather_outskirts",
            {
                "item.herb.blood_grass": {1: 35, 2: 45, 3: 20},
                "item.ore.ironstone": {0: 50, 1: 35, 2: 15},
                "item.mat.wood": {0: 90, 1: 10},
            },
        ),
        (
            "reward_pool.exploration.spring_gather",
            {
                "item.herb.spirit_leaf": {1: 60, 2: 40},
                "item.mat.array_sand": {0: 60, 1: 40},
                "item.spirit_water": {1: 100},
            },
        ),
    ],
    ids=["outskirts", "spring"],
)
def test_gather_reward_pool_preserves_every_joint_probability(
    pool_key: str, distributions: dict[str, dict[int, int]]
) -> None:
    bundle = ContentBundle.load(Path(__file__).parents[1] / "data")
    outcomes = reward_pool_outcomes(pool_key, bundle)
    total_weight = sum(weight for weight, _ in outcomes)
    expected = {
        tuple(quantity for quantity, _ in combination): prod(
            Fraction(weight, 100) for _, weight in combination
        )
        for combination in product(*(weights.items() for weights in distributions.values()))
    }
    actual = {}
    for weight, rewards in outcomes:
        assert set(rewards) <= distributions.keys()
        assert all(quantity > 0 for quantity in rewards.values())
        quantities = tuple(rewards.get(item_key, 0) for item_key in distributions)
        assert quantities not in actual
        actual[quantities] = Fraction(weight, total_weight)
    assert len(outcomes) == len(expected)
    assert actual == expected
    assert sum(actual.values()) == 1


@pytest.mark.parametrize(
    "pool_key",
    ["reward_pool.exploration.gather_outskirts", "reward_pool.exploration.spring_gather"],
    ids=["outskirts", "spring"],
)
def test_reward_pool_map_is_deterministic_and_returns_detached_results(pool_key: str) -> None:
    content_path = Path(__file__).parents[1] / "data"
    bundle = ContentBundle.load(content_path)
    reloaded = ContentBundle.load(content_path)
    configured = {
        tuple(sorted(rewards.items())) for _, rewards in reward_pool_outcomes(pool_key, bundle)
    }
    selected = set()
    for index in range(2_000):
        seed = f"gather-replay-{index}"
        result = reward_pool_map(pool_key, seed, bundle)
        original = dict(result)
        assert result == reward_pool_map(pool_key, seed, reloaded)
        selected.add(tuple(sorted(result.items())))
        result[next(iter(result))] = 999
        assert reward_pool_map(pool_key, seed, bundle) == original
    assert selected == configured


@pytest.mark.parametrize(
    ("pool_key", "rewards"),
    [
        ("reward_pool.exploration.gather_outskirts", {"item.herb.blood_grass": 7}),
        (
            "reward_pool.exploration.spring_gather",
            {"item.herb.spirit_leaf": 7, "item.mat.array_sand": 3, "item.spirit_water": 4},
        ),
    ],
    ids=["outskirts", "spring"],
)
def test_gather_reward_pool_reads_changed_content_without_mutating_loaded_bundle(
    tmp_path: Path, pool_key: str, rewards: dict[str, int]
) -> None:
    data_dir = tmp_path / "data"
    shutil.copytree(Path(__file__).parents[1] / "data", data_dir)
    original_bundle = ContentBundle.load(data_dir)
    seed = "gather-content-change"
    original = reward_pool_map(pool_key, seed, original_bundle)
    reward_file = data_dir / "奖励" / "奖励.json"
    document = json.loads(reward_file.read_text(encoding="utf-8"))
    pool = next(item for item in document["records"] if item["key"] == pool_key)
    pool["outcomes"] = [{"weight": 7, "rewards": rewards}]
    reward_file.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")

    reloaded = ContentBundle.load(data_dir)
    assert reward_pool_outcomes(pool_key, reloaded) == ((7, rewards),)
    assert reward_pool_map(pool_key, seed, reloaded) == rewards != original
    assert reward_pool_map(pool_key, seed, original_bundle) == original


@pytest.mark.parametrize(
    "pool_key",
    ["reward_pool.exploration.gather_outskirts", "reward_pool.exploration.spring_gather"],
    ids=["outskirts", "spring"],
)
@pytest.mark.parametrize(
    ("outcome", "error"),
    [
        ({"weight": 0, "rewards": {"cultivation": 1}}, "invalid weight"),
        ({"weight": -1, "rewards": {"cultivation": 1}}, "invalid weight"),
        ({"weight": True, "rewards": {"cultivation": 1}}, "invalid weight"),
        ({"weight": "1", "rewards": {"cultivation": 1}}, "invalid weight"),
        ({"weight": 1.5, "rewards": {"cultivation": 1}}, "invalid weight"),
        ({"weight": 1, "rewards": {}}, "requires rewards"),
        ({"weight": 1, "rewards": {"unknown.resource": 1}}, "unsupported reward key"),
        ({"weight": 1, "rewards": {"stamina_max": 1}}, "unsupported reward key"),
        ({"weight": 1, "rewards": {"energy_max": 1}}, "unsupported reward key"),
        ({"weight": 1, "rewards": {"soul_power_max": 1}}, "unsupported reward key"),
        ({"weight": 1, "rewards": {"faction_reputation.": 1}}, "requires a faction key"),
        ({"weight": 1, "rewards": {"item.missing_reward": 1}}, "inactive item"),
        ({"weight": 1, "rewards": {"item.mat.wood": 0}}, "positive integer quantities"),
        ({"weight": 1, "rewards": {"item.mat.wood": -1}}, "positive integer quantities"),
        ({"weight": 1, "rewards": {"item.mat.wood": True}}, "positive integer quantities"),
        ({"weight": 1, "rewards": {"item.mat.wood": "1"}}, "positive integer quantities"),
        ({"weight": 1, "rewards": {"item.mat.wood": 1.5}}, "positive integer quantities"),
    ],
)
def test_gather_reward_pool_rejects_malformed_outcomes(
    tmp_path: Path, pool_key: str, outcome: dict[str, object], error: str
) -> None:
    data_dir = tmp_path / "data"
    shutil.copytree(Path(__file__).parents[1] / "data", data_dir)
    reward_file = data_dir / "奖励" / "奖励.json"
    document = json.loads(reward_file.read_text(encoding="utf-8"))
    pool = next(item for item in document["records"] if item["key"] == pool_key)
    pool["outcomes"] = [outcome]
    reward_file.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    bundle = ContentBundle.load(data_dir)
    with pytest.raises(RewardContentError, match=error) as caught:
        reward_pool_map(pool_key, "invalid-gather", bundle)
    assert pool_key in str(caught.value)
    assert "outcome 0" in str(caught.value)


@pytest.mark.parametrize(
    ("pool_key", "item_key"),
    [
        ("reward_pool.exploration.gather_outskirts", "item.mat.wood"),
        ("reward_pool.exploration.spring_gather", "item.mat.array_sand"),
    ],
    ids=["outskirts", "spring"],
)
def test_gather_reward_pool_rejects_inactive_item_even_when_not_selected(
    tmp_path: Path, pool_key: str, item_key: str
) -> None:
    data_dir = tmp_path / "data"
    shutil.copytree(Path(__file__).parents[1] / "data", data_dir)
    active_bundle = ContentBundle.load(data_dir)
    seed = next(
        f"inactive-item-{index}"
        for index in range(100)
        if item_key not in reward_pool_map(pool_key, f"inactive-item-{index}", active_bundle)
    )
    item_file = data_dir / "道具" / "材料.json"
    document = json.loads(item_file.read_text(encoding="utf-8"))
    item = next(item for item in document["records"] if item["key"] == item_key)
    item["status"] = "locked"
    item_file.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    bundle = ContentBundle.load(data_dir)
    with pytest.raises(RewardContentError, match=f"inactive item {item_key}"):
        reward_pool_map(pool_key, seed, bundle)
