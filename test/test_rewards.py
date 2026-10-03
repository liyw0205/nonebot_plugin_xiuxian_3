from __future__ import annotations

import asyncio
import json
import shutil
import sqlite3
from datetime import datetime, timedelta, timezone
from fractions import Fraction
from itertools import product
from math import prod
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle
from nonebot_plugin_xiuxian_3.xiuxian.exploration.rules import (
    settlement_failure_result,
    settlement_result,
)
from nonebot_plugin_xiuxian_3.xiuxian.rewards.rules import (
    RewardContentError,
    RewardGrant,
    combine_reward_grants,
    reward_definition,
    reward_pool_battle_failure_rewards,
    reward_pool_map,
    reward_pool_outcomes,
)


def _context(adapter: str, user: str, operation_id: str) -> CommandContext:
    return CommandContext(adapter=adapter, user_id=user, operation_id=operation_id)


def _reward_axis(key: str, distribution: dict[int, int]) -> tuple[tuple[dict[str, int], int], ...]:
    return tuple(
        (({key: quantity} if quantity else {}), weight)
        for quantity, weight in distribution.items()
    )


def _joint_reward_probabilities(
    *axes: tuple[tuple[dict[str, int], int], ...],
) -> dict[tuple[tuple[str, int], ...], Fraction]:
    total_weight = prod(sum(weight for _, weight in axis) for axis in axes)
    expected: dict[tuple[tuple[str, int], ...], Fraction] = {}
    for choices in product(*axes):
        weight = prod(choice_weight for _, choice_weight in choices)
        rewards: dict[str, int] = {}
        for choice_rewards, _ in choices:
            assert not rewards.keys() & choice_rewards.keys()
            rewards.update(choice_rewards)
        outcome = tuple(sorted(rewards.items()))
        expected[outcome] = expected.get(outcome, Fraction()) + Fraction(weight, total_weight)
    return expected


class MutableClock:
    def __init__(self) -> None:
        self.current = datetime(2026, 9, 1, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.current

    def advance(self, **kwargs: int) -> None:
        self.current += timedelta(**kwargs)


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


def test_spirit_tree_harvest_uses_content_and_replays_across_adapters_and_restart() -> None:
    async def run() -> None:
        with TemporaryDirectory() as temp:
            data_dir = Path(temp) / "data"
            shutil.copytree(Path(__file__).parents[1] / "data", data_dir)
            reward_file = data_dir / "奖励" / "奖励.json"
            document = json.loads(reward_file.read_text(encoding="utf-8"))
            pool = next(
                item
                for item in document["records"]
                if item["key"] == "reward_pool.routine.spirit_tree_harvest"
            )
            configured_reward = {
                "spirit_stones": 37,
                "item.seed.spirit_tree": 2,
                "local.xuantian.new_town": 4,
            }
            pool["outcomes"] = [{"weight": 1, "rewards": configured_reward}]
            reward_file.write_text(
                json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            location_file = data_dir / "地图" / "地点.json"
            locations = json.loads(location_file.read_text(encoding="utf-8"))
            new_town = next(
                item for item in locations["records"] if item["key"] == "xuantian.new_town"
            )
            new_town["local_reputation_maximum"] = 1002
            location_file.write_text(
                json.dumps(locations, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )

            clock = MutableClock()
            adapters = ("qq.official", "onebot.v11")
            users = {adapter: f"tree-{adapter}" for adapter in adapters}
            runtime = create_runtime(data_dir=data_dir, adapters=adapters, clock=clock)
            try:
                for adapter in adapters:
                    user = users[adapter]
                    assert (
                        await runtime.adapters.dispatch(
                            adapter, _context(adapter, user, f"{adapter}-create"), "开始修仙"
                        )
                    ).ok
                    assert (
                        await runtime.adapters.dispatch(
                            adapter, _context(adapter, user, f"{adapter}-seek"), "寻仙问道"
                        )
                    ).ok

                for day in range(7):
                    for adapter in adapters:
                        watered = await runtime.adapters.dispatch(
                            adapter,
                            _context(adapter, users[adapter], f"{adapter}-water-{day}"),
                            "浇灌灵木",
                        )
                        assert watered.ok
                    if day < 6:
                        clock.advance(days=1)

                player_ids: dict[str, int] = {}
                baseline_assets: dict[str, tuple[int, int]] = {}
                with sqlite3.connect(runtime.settings.database_path) as connection:
                    for adapter in adapters:
                        row = connection.execute(
                            "SELECT id FROM players WHERE platform=? AND platform_user_id=?",
                            (adapter, users[adapter]),
                        ).fetchone()
                        assert row is not None
                        player_ids[adapter] = int(row[0])
                        connection.execute(
                            """
                            INSERT INTO player_reputations(player_id, local_json, service_reputation, updated_at)
                            VALUES (?, ?, 0, ?)
                            ON CONFLICT(player_id) DO UPDATE SET local_json=excluded.local_json
                            """,
                            (
                                row[0],
                                json.dumps({"local.xuantian.new_town": 999}),
                                clock().isoformat(),
                            ),
                        )
                        assets = connection.execute(
                            "SELECT spirit_stones, inventory_json FROM players WHERE id=?",
                            (row[0],),
                        ).fetchone()
                        assert assets is not None
                        baseline_assets[adapter] = (
                            int(assets[0]),
                            int(json.loads(assets[1]).get("item.seed.spirit_tree", 0)),
                        )

                expected_after: dict[str, tuple[int, int, int, str]] = {}
                for adapter in adapters:
                    user = users[adapter]
                    operation_id = f"{adapter}-harvest"
                    harvested = await runtime.adapters.dispatch(
                        adapter,
                        _context(adapter, user, operation_id),
                        "收获灵木",
                    )
                    assert harvested.code == "SPIRIT_TREE_HARVESTED"
                    assert harvested.data["reward"] == configured_reward
                    assert "青石镇名望 ×4" in harvested.message
                    assert "reward_pool." not in harvested.message
                    assert "local." not in harvested.message

                    with sqlite3.connect(runtime.settings.database_path) as connection:
                        player = connection.execute(
                            "SELECT spirit_stones, inventory_json FROM players WHERE id=?",
                            (player_ids[adapter],),
                        ).fetchone()
                        reputation = connection.execute(
                            "SELECT local_json FROM player_reputations WHERE player_id=?",
                            (player_ids[adapter],),
                        ).fetchone()
                        harvest = connection.execute(
                            "SELECT pool_key, seed, reward_json FROM spirit_tree_harvests WHERE operation_id=?",
                            (operation_id,),
                        ).fetchone()
                    assert player is not None and reputation is not None and harvest is not None
                    inventory = json.loads(player[1])
                    assert player[0] == baseline_assets[adapter][0] + configured_reward["spirit_stones"]
                    assert inventory.get("item.seed.spirit_tree", 0) == (
                        baseline_assets[adapter][1] + configured_reward["item.seed.spirit_tree"]
                    )
                    assert json.loads(reputation[0])["local.xuantian.new_town"] == 1002
                    assert harvest[0] == "reward_pool.routine.spirit_tree_harvest"
                    assert json.loads(harvest[2]) == configured_reward
                    expected_after[adapter] = (
                        player[0],
                        inventory.get("item.seed.spirit_tree", 0),
                        json.loads(reputation[0])["local.xuantian.new_town"],
                        harvest[1],
                    )
            finally:
                await runtime.close()

            document = json.loads(reward_file.read_text(encoding="utf-8"))
            pool = next(
                item
                for item in document["records"]
                if item["key"] == "reward_pool.routine.spirit_tree_harvest"
            )
            pool["outcomes"] = [
                {
                    "weight": 1,
                    "rewards": {
                        "spirit_stones": 91,
                        "item.seed.spirit_tree": 3,
                        "local.xuantian.new_town": 1,
                    },
                }
            ]
            reward_file.write_text(
                json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            locations = json.loads(location_file.read_text(encoding="utf-8"))
            new_town = next(
                item for item in locations["records"] if item["key"] == "xuantian.new_town"
            )
            new_town["local_reputation_maximum"] = 2
            location_file.write_text(
                json.dumps(locations, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )

            recovered = create_runtime(data_dir=data_dir, adapters=adapters, clock=clock)
            try:
                for adapter in adapters:
                    operation_id = f"{adapter}-harvest"
                    replay = await recovered.adapters.dispatch(
                        adapter,
                        _context(adapter, users[adapter], operation_id),
                        "收获灵木",
                    )
                    assert replay.code == "SPIRIT_TREE_HARVESTED"
                    assert replay.data["idempotent_replay"] is True
                    assert replay.data["reward"] == configured_reward
                    conflict = await recovered.adapters.dispatch(
                        adapter,
                        _context(adapter, users[adapter], operation_id),
                        "浇灌灵木",
                    )
                    assert conflict.code == "OPERATION_CONFLICT"
                    with sqlite3.connect(recovered.settings.database_path) as connection:
                        player = connection.execute(
                            "SELECT spirit_stones, inventory_json FROM players WHERE id=?",
                            (player_ids[adapter],),
                        ).fetchone()
                        reputation = connection.execute(
                            "SELECT local_json FROM player_reputations WHERE player_id=?",
                            (player_ids[adapter],),
                        ).fetchone()
                        harvest_count = connection.execute(
                            "SELECT COUNT(*) FROM spirit_tree_harvests WHERE operation_id=?",
                            (operation_id,),
                        ).fetchone()[0]
                    assert player is not None and reputation is not None
                    inventory = json.loads(player[1])
                    assert (
                        player[0],
                        inventory.get("item.seed.spirit_tree", 0),
                        json.loads(reputation[0])["local.xuantian.new_town"],
                        expected_after[adapter][3],
                    ) == expected_after[adapter]
                    assert harvest_count == 1
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
    ("pool_key", "axes"),
    [
        (
            "reward_pool.exploration.gather_outskirts",
            (
                _reward_axis("item.herb.blood_grass", {1: 35, 2: 45, 3: 20}),
                _reward_axis("item.ore.ironstone", {0: 50, 1: 35, 2: 15}),
                _reward_axis("item.mat.wood", {0: 90, 1: 10}),
            ),
        ),
        (
            "reward_pool.exploration.spring_gather",
            (
                _reward_axis("item.herb.spirit_leaf", {1: 60, 2: 40}),
                _reward_axis("item.mat.array_sand", {0: 60, 1: 40}),
                _reward_axis("item.spirit_water", {1: 100}),
            ),
        ),
        (
            "reward_pool.exploration.mist_grotto",
            (
                (({"cultivation": 300}, 30), ({"cultivation": 400}, 45), ({"cultivation": 500}, 25)),
                tuple(
                    ({item_key: quantity}, material_weight * quantity_weight)
                    for item_key, material_weight in (
                        ("item.herb.spirit_leaf", 45),
                        ("item.mat.array_sand", 30),
                        ("item.ore.ironstone", 25),
                    )
                    for quantity, quantity_weight in ((1, 45), (2, 35), (3, 20))
                ),
            ),
        ),
        (
            "reward_pool.exploration.mist_grotto_2",
            (
                _reward_axis("cultivation", {900: 30, 1100: 45, 1300: 25}),
                _reward_axis("item.material.cloud_iron", {1: 60, 2: 40}),
            ),
        ),
        (
            "reward_pool.exploration.cloud_boat_trial",
            (
                _reward_axis("cultivation", {600: 30, 750: 40, 900: 30}),
                _reward_axis("item.ticket.cloud_boat_fragment", {1: 60, 2: 40}),
            ),
        ),
        (
            "reward_pool.exploration.cloud_mine",
            (_reward_axis("item.material.cloud_iron", {1: 25, 2: 40, 3: 25, 4: 10}),),
        ),
    ],
    ids=["outskirts", "spring", "mist-grotto", "mist-grotto-two", "cloud-boat", "cloud-mine"],
)
def test_exploration_reward_pool_preserves_every_joint_probability(
    pool_key: str, axes: tuple[tuple[tuple[dict[str, int], int], ...], ...]
) -> None:
    bundle = ContentBundle.load(Path(__file__).parents[1] / "data")
    outcomes = reward_pool_outcomes(pool_key, bundle)
    total_weight = sum(weight for weight, _ in outcomes)
    expected = _joint_reward_probabilities(*axes)
    actual: dict[tuple[tuple[str, int], ...], Fraction] = {}
    for weight, rewards in outcomes:
        assert all(quantity > 0 for quantity in rewards.values())
        key = tuple(sorted(rewards.items()))
        assert key not in actual
        actual[key] = Fraction(weight, total_weight)
    assert len(outcomes) == len(expected)
    assert actual == expected
    assert sum(actual.values()) == 1


def test_beast_hunt_pool_preserves_original_outcomes_and_explicit_no_reward() -> None:
    bundle = ContentBundle.load(Path(__file__).parents[1] / "data")
    outcomes = reward_pool_outcomes("reward_pool.exploration.beast_hunt", bundle)
    total_weight = sum(weight for weight, _ in outcomes)
    actual = {
        tuple(sorted(rewards.items())): Fraction(weight, total_weight)
        for weight, rewards in outcomes
    }
    assert actual == {
        (("item.beast_blood", 1),): Fraction(45, 100),
        (("faction_reputation.beast", 15),): Fraction(30, 100),
        (("item.clue.beast_bloodline", 1),): Fraction(15, 100),
        (): Fraction(10, 100),
    }


def test_spirit_tree_pool_preserves_joint_reward_probabilities() -> None:
    outcomes = reward_pool_outcomes("reward_pool.routine.spirit_tree_harvest")
    total_weight = sum(weight for weight, _ in outcomes)
    actual = {
        tuple(sorted(rewards.items())): Fraction(weight, total_weight)
        for weight, rewards in outcomes
    }
    assert total_weight == 10_000
    assert actual == _joint_reward_probabilities(
        _reward_axis("spirit_stones", {80: 25, 100: 50, 120: 25}),
        _reward_axis("item.seed.spirit_tree", {0: 70, 1: 30}),
        (({"local.xuantian.new_town": 2}, 100),),
    )


def test_reward_pool_item_weight_bonus_only_increases_item_outcomes() -> None:
    pool_key = "reward_pool.exploration.beast_hunt"
    normal = [reward_pool_map(pool_key, f"bonus-{index}") for index in range(2_000)]
    boosted = [
        reward_pool_map(pool_key, f"bonus-{index}", item_weight_bonus_bp=100_000)
        for index in range(2_000)
    ]
    normal_item_count = sum(
        any(key.startswith("item.") for key in result) for result in normal
    )
    boosted_item_count = sum(
        any(key.startswith("item.") for key in result) for result in boosted
    )
    assert boosted_item_count > normal_item_count
    assert any(not result for result in normal)
    assert any(not result for result in boosted)
    assert boosted == [
        reward_pool_map(pool_key, f"bonus-{index}", item_weight_bonus_bp=100_000)
        for index in range(2_000)
    ]


@pytest.mark.parametrize(
    "pool_key",
    [
        "reward_pool.exploration.gather_outskirts",
        "reward_pool.exploration.spring_gather",
        "reward_pool.exploration.mist_grotto",
        "reward_pool.exploration.mist_grotto_2",
        "reward_pool.exploration.cloud_boat_trial",
        "reward_pool.exploration.cloud_mine",
        "reward_pool.exploration.beast_hunt",
        "reward_pool.routine.spirit_tree_harvest",
    ],
    ids=["outskirts", "spring", "mist-grotto", "mist-grotto-two", "cloud-boat", "cloud-mine", "beast-hunt", "spirit-tree"],
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
        if result:
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
        (
            "reward_pool.exploration.mist_grotto",
            {"cultivation": 700, "item.ore.ironstone": 5},
        ),
        (
            "reward_pool.exploration.mist_grotto_2",
            {"cultivation": 1700, "item.material.cloud_iron": 7},
        ),
        (
            "reward_pool.exploration.cloud_boat_trial",
            {"cultivation": 1700, "item.ticket.cloud_boat_fragment": 7},
        ),
        (
            "reward_pool.exploration.cloud_mine",
            {"item.material.cloud_iron": 7},
        ),
        (
            "reward_pool.exploration.beast_hunt",
            {"item.beast_blood": 7},
        ),
        (
            "reward_pool.routine.spirit_tree_harvest",
            {"spirit_stones": 17, "local.xuantian.new_town": 1},
        ),
    ],
    ids=["outskirts", "spring", "mist-grotto", "mist-grotto-two", "cloud-boat", "cloud-mine", "beast-hunt", "spirit-tree"],
)
def test_exploration_reward_pool_reads_changed_content_without_mutating_loaded_bundle(
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
    [
        "reward_pool.exploration.gather_outskirts",
        "reward_pool.exploration.spring_gather",
        "reward_pool.exploration.mist_grotto",
        "reward_pool.exploration.mist_grotto_2",
        "reward_pool.exploration.cloud_boat_trial",
        "reward_pool.exploration.cloud_mine",
        "reward_pool.exploration.beast_hunt",
        "reward_pool.routine.spirit_tree_harvest",
    ],
    ids=["outskirts", "spring", "mist-grotto", "mist-grotto-two", "cloud-boat", "cloud-mine", "beast-hunt", "spirit-tree"],
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
        ({"weight": 1, "no_reward": False}, "no_reward must be true"),
        ({"weight": 1, "no_reward": True, "rewards": {"item.mat.wood": 1}}, "cannot combine"),
    ],
)
def test_exploration_reward_pool_rejects_malformed_outcomes(
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


@pytest.mark.parametrize("local_key", ["local.", "local.xuantian.missing"])
def test_reward_pool_rejects_local_reputation_without_active_location(
    tmp_path: Path, local_key: str
) -> None:
    data_dir = tmp_path / "data"
    shutil.copytree(Path(__file__).parents[1] / "data", data_dir)
    reward_file = data_dir / "奖励" / "奖励.json"
    document = json.loads(reward_file.read_text(encoding="utf-8"))
    pool = next(
        item
        for item in document["records"]
        if item["key"] == "reward_pool.routine.spirit_tree_harvest"
    )
    pool["outcomes"] = [{"weight": 1, "rewards": {local_key: 1}}]
    reward_file.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(RewardContentError, match="local reputation|must name a location"):
        reward_pool_map(
            "reward_pool.routine.spirit_tree_harvest",
            "invalid-local-reputation",
            ContentBundle.load(data_dir),
        )


@pytest.mark.parametrize("maximum", [0, True, "1000"])
def test_reward_pool_rejects_invalid_local_reputation_maximum(
    tmp_path: Path, maximum: object
) -> None:
    data_dir = tmp_path / "data"
    shutil.copytree(Path(__file__).parents[1] / "data", data_dir)
    location_file = data_dir / "地图" / "地点.json"
    document = json.loads(location_file.read_text(encoding="utf-8"))
    new_town = next(item for item in document["records"] if item["key"] == "xuantian.new_town")
    new_town["local_reputation_maximum"] = maximum
    location_file.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(RewardContentError, match="positive local_reputation_maximum"):
        reward_pool_map(
            "reward_pool.routine.spirit_tree_harvest",
            "invalid-local-reputation-maximum",
            ContentBundle.load(data_dir),
        )


@pytest.mark.parametrize("bonus", [-1, True, 1.5, "100"])
def test_reward_pool_rejects_invalid_item_weight_bonus(bonus: object) -> None:
    with pytest.raises(RewardContentError, match="non-negative integer"):
        reward_pool_map(
            "reward_pool.exploration.beast_hunt",
            "invalid-item-bonus",
            item_weight_bonus_bp=bonus,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    ("mode_key", "pool_key"),
    [
        ("explore.trial_outskirts", "reward_pool.exploration.trial_outskirts"),
        ("explore.gather_outskirts", "reward_pool.exploration.gather_outskirts"),
        ("explore.spring_gather", "reward_pool.exploration.spring_gather"),
        ("explore.mist_grotto", "reward_pool.exploration.mist_grotto"),
        ("explore.mist_grotto_2", "reward_pool.exploration.mist_grotto_2"),
        ("explore.cloud_boat_trial", "reward_pool.exploration.cloud_boat_trial"),
        ("explore.cloud_mine", "reward_pool.exploration.cloud_mine"),
        ("explore.beast_hunt", "reward_pool.exploration.beast_hunt"),
    ],
)
@pytest.mark.parametrize("resource_key", ["stamina", "soul_power"])
def test_exploration_reward_pool_rejects_non_cultivation_player_values(
    tmp_path: Path, mode_key: str, pool_key: str, resource_key: str
) -> None:
    data_dir = tmp_path / "data"
    shutil.copytree(Path(__file__).parents[1] / "data", data_dir)
    reward_file = data_dir / "奖励" / "奖励.json"
    document = json.loads(reward_file.read_text(encoding="utf-8"))
    pool = next(item for item in document["records"] if item["key"] == pool_key)
    pool["outcomes"] = [{"weight": 1, "rewards": {resource_key: 1}}]
    reward_file.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    bundle = ContentBundle.load(data_dir)

    with pytest.raises(RewardContentError, match="contains unsupported state"):
        settlement_result(mode_key, "unsupported-exploration-resource", content=bundle)


def test_exploration_reward_pool_accepts_cultivation_and_assets() -> None:
    with TemporaryDirectory() as temp:
        data_dir = Path(temp) / "data"
        shutil.copytree(Path(__file__).parents[1] / "data", data_dir)
        reward_file = data_dir / "奖励" / "奖励.json"
        document = json.loads(reward_file.read_text(encoding="utf-8"))
        pool = next(
            item for item in document["records"] if item["key"] == "reward_pool.exploration.mist_grotto"
        )
        rewards = {
            "cultivation": 17,
            "total_cultivation": 170,
            "spirit_stones": 5,
            "item.herb.spirit_leaf": 2,
        }
        pool["outcomes"] = [{"weight": 1, "rewards": rewards}]
        reward_file.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        bundle = ContentBundle.load(data_dir)

        assert settlement_result("explore.mist_grotto", "allowed-exploration-reward", content=bundle) == rewards


@pytest.mark.parametrize(
    ("pool_key", "item_key"),
    [
        ("reward_pool.exploration.gather_outskirts", "item.mat.wood"),
        ("reward_pool.exploration.spring_gather", "item.mat.array_sand"),
        ("reward_pool.exploration.mist_grotto", "item.ore.ironstone"),
        ("reward_pool.exploration.beast_hunt", "item.clue.beast_bloodline"),
    ],
    ids=["outskirts", "spring", "mist-grotto", "beast-hunt"],
)
def test_exploration_reward_pool_rejects_inactive_item_even_when_not_selected(
    tmp_path: Path, pool_key: str, item_key: str
) -> None:
    data_dir = tmp_path / "data"
    shutil.copytree(Path(__file__).parents[1] / "data", data_dir)
    seed = "inactive-item"
    item_file = data_dir / "道具" / "材料.json"
    document = json.loads(item_file.read_text(encoding="utf-8"))
    item = next(item for item in document["records"] if item["key"] == item_key)
    item["status"] = "locked"
    item_file.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    bundle = ContentBundle.load(data_dir)
    with pytest.raises(RewardContentError, match=f"inactive item {item_key}"):
        reward_pool_map(pool_key, seed, bundle)


def test_reward_pool_battle_failure_rewards_are_content_backed() -> None:
    bundle = ContentBundle.load(Path(__file__).parents[1] / "data")
    assert reward_pool_battle_failure_rewards(
        "reward_pool.exploration.cloud_mine", bundle
    ) == {"item.material.cloud_iron": 1}
    assert reward_pool_battle_failure_rewards(
        "reward_pool.exploration.mist_grotto", bundle
    ) == {}
    assert reward_pool_battle_failure_rewards(
        "reward_pool.exploration.mist_grotto_2", bundle
    ) == {}
    assert reward_pool_battle_failure_rewards(
        "reward_pool.exploration.cloud_boat_trial", bundle
    ) == {}
    assert reward_pool_battle_failure_rewards(
        "reward_pool.exploration.beast_hunt", bundle
    ) == {}


@pytest.mark.parametrize(
    ("failure_rewards", "error"),
    [
        ({"item.missing": 1}, "references inactive item"),
        ({"item.material.cloud_iron": 0}, "positive integer quantities"),
        ([], "requires rewards"),
    ],
)
def test_reward_pool_rejects_invalid_battle_failure_rewards(
    tmp_path: Path, failure_rewards: object, error: str
) -> None:
    data_dir = tmp_path / "data"
    shutil.copytree(Path(__file__).parents[1] / "data", data_dir)
    reward_file = data_dir / "奖励" / "奖励.json"
    document = json.loads(reward_file.read_text(encoding="utf-8"))
    pool = next(
        item for item in document["records"] if item["key"] == "reward_pool.exploration.cloud_mine"
    )
    pool["battle_failure_rewards"] = failure_rewards
    reward_file.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    bundle = ContentBundle.load(data_dir)

    with pytest.raises(RewardContentError, match=error):
        reward_pool_battle_failure_rewards("reward_pool.exploration.cloud_mine", bundle)
    with pytest.raises(RewardContentError, match=error):
        reward_pool_map("reward_pool.exploration.cloud_mine", "bad-failure-pool", bundle)


def test_exploration_failure_reward_rejects_unsupported_player_values(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    shutil.copytree(Path(__file__).parents[1] / "data", data_dir)
    reward_file = data_dir / "奖励" / "奖励.json"
    document = json.loads(reward_file.read_text(encoding="utf-8"))
    pool = next(
        item for item in document["records"] if item["key"] == "reward_pool.exploration.cloud_mine"
    )
    pool["battle_failure_rewards"] = {"stamina": 1}
    reward_file.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    bundle = ContentBundle.load(data_dir)

    with pytest.raises(RewardContentError, match="contains unsupported state"):
        settlement_failure_result("explore.cloud_mine", content=bundle)
