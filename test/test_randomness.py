from __future__ import annotations

import pytest

from nonebot_plugin_xiuxian_3.xiuxian.utils.randomness import deterministic_weighted_choice


def test_deterministic_weighted_choice_replays_and_accepts_single_outcome() -> None:
    outcomes = ((1, "first"), (3, "second"))
    selected = deterministic_weighted_choice(outcomes, "stable-seed")

    assert selected in {"first", "second"}
    assert deterministic_weighted_choice(outcomes, "stable-seed") == selected
    assert deterministic_weighted_choice(((7, "only"),), "stable-seed") == "only"


@pytest.mark.parametrize("outcomes", [(), ((0, "empty"),), ((True, "bool"),), ((1.5, "float"),)])
def test_deterministic_weighted_choice_rejects_invalid_weights(outcomes) -> None:
    with pytest.raises(ValueError):
        deterministic_weighted_choice(outcomes, "stable-seed")
