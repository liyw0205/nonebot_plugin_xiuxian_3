"""The arena weekly-ladder contract must be complete before any settlement code.

`arena.season` declares the week anchor, the board size, the local reputation and
title keys, and flat per-rank payouts.  Every reference is validated at load so
a typo cannot produce an empty or mispriced settlement later.
"""

from __future__ import annotations

import copy
from dataclasses import replace
from datetime import timezone
from pathlib import Path

import pytest

from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError
from nonebot_plugin_xiuxian_3.xiuxian.specials.arena_content import season_record

DATA = Path(__file__).resolve().parents[1] / "data"
KEY = "arena.season"


def _bundle() -> ContentBundle:
    return ContentBundle.load(DATA)


def _with(bundle: ContentBundle, **changes: object) -> ContentBundle:
    records = dict(bundle._records)
    row = copy.deepcopy(records[("arena_rule", KEY)])
    row.update(changes)
    records[("arena_rule", KEY)] = row
    return replace(bundle, _records=records)


def test_the_shipped_season_contract_resolves_every_reference() -> None:
    record = season_record()
    assert record["key"] == KEY
    assert record["week_anchor"].tzinfo is not None
    assert record["week_anchor"].utcoffset() == timezone.utc.utcoffset(None)
    assert record["board_size"] == 20
    assert record["local_reputation_key"] == "local.xuantian.new_town"
    assert record["title_key"] == "title.arena.season_champion"
    ranks = [entry["rank"] for entry in record["rank_rewards"]]
    assert ranks == [1, 2, 3]
    assert record["rank_rewards"][0]["reward"] == {"spirit_stones": 800, "local_reputation": 20}
    # Participation pays less than any ranked slot.
    assert record["default_rank_reward"]["spirit_stones"] < min(
        entry["reward"]["spirit_stones"] for entry in record["rank_rewards"]
    )


@pytest.mark.parametrize(
    "changes, message",
    [
        ({"week_anchor": "2026-01-05T00:00:00"}, "timezone"),
        ({"week_anchor": "not-a-time"}, "ISO timestamp"),
        ({"week_anchor": None}, "ISO timestamp"),
        ({"board_size": 0}, "board_size"),
        ({"local_reputation_key": "somewhere.else"}, "local reputation"),
        ({"title_key": "title.not.real"}, "unknown title"),
        ({"rank_rewards": []}, "non-empty list"),
        ({"rank_rewards": [{"rank": 21, "reward": {"spirit_stones": 1}}]}, "exceeds board_size"),
        (
            {
                "rank_rewards": [
                    {"rank": 1, "reward": {"spirit_stones": 1}},
                    {"rank": 1, "reward": {"spirit_stones": 1}},
                ]
            },
            "duplicate rank",
        ),
        ({"rank_rewards": [{"rank": 1, "reward": {"spirit_stones": 0}}]}, "positive integer"),
        ({"rank_rewards": [{"rank": 1, "reward": {"merit": 5}}]}, "unsupported reward"),
        ({"rank_rewards": [{"rank": 1, "reward": {"item.not.real": 1}}]}, "unavailable item"),
        ({"default_rank_reward": {}}, "non-empty object"),
        ({"default_rank_reward": {"spirit_stones": 1, "mercy": 2}}, "unsupported reward"),
        ({"status": "locked"}, "missing arena_rule content"),
    ],
)
def test_malformed_season_contracts_are_rejected(changes: dict, message: str) -> None:
    with pytest.raises(ContentError, match=message):
        season_record(_with(_bundle(), **changes))


def test_rank_rewards_may_grant_a_real_item() -> None:
    bundle = _bundle()
    record = season_record(
        _with(
            bundle,
            rank_rewards=[{"rank": 1, "reward": {"spirit_stones": 10, "item.pill.focus_low": 1}}],
        )
    )
    assert record["rank_rewards"][0]["reward"]["item.pill.focus_low"] == 1
