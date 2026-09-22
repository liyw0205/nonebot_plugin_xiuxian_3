from nonebot_plugin_xiuxian_3.xiuxian.routine.gacha import (
    FATE_PITY_LIMIT,
    reward_totals,
    roll_fate_pool,
)


def test_fate_rules_are_deterministic_and_single_pull_pity_is_guaranteed() -> None:
    first = roll_fate_pool("stable-operation", draw_count=1, pity_before=0)
    replay = roll_fate_pool("stable-operation", draw_count=1, pity_before=0)
    assert first == replay

    draws, pity_after, seed_hash = roll_fate_pool(
        "pity-operation",
        draw_count=1,
        pity_before=FATE_PITY_LIMIT - 1,
    )
    assert draws[0].rarity == "rare"
    assert draws[0].guaranteed is True
    assert pity_after == 0
    assert len(seed_hash) == 64


def test_fate_ten_pull_always_contains_a_rare_result_and_aggregates_rewards() -> None:
    draws, pity_after, _ = roll_fate_pool(
        "ten-operation",
        draw_count=10,
        pity_before=0,
    )
    assert len(draws) == 10
    assert any(draw.rarity == "rare" for draw in draws)
    assert 0 <= pity_after < FATE_PITY_LIMIT
    totals = reward_totals(draws)
    assert sum(totals.values()) == sum(draw.quantity for draw in draws)
