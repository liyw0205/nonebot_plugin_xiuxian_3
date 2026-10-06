from __future__ import annotations

import copy
import json
from collections import Counter
from dataclasses import replace
from datetime import date, timedelta

import pytest

from nonebot_plugin_xiuxian_3.xiuxian.content import (
    ContentBundle,
    ContentError,
    bundled_content,
)
from nonebot_plugin_xiuxian_3.xiuxian.routine import wayfaring
from nonebot_plugin_xiuxian_3.xiuxian.routine.wayfaring import (
    WAYFARING_PASS_KEY,
    parse_wayfaring_snapshot,
    wayfaring_definition,
    wayfaring_week_start,
)


@pytest.fixture(scope="module")
def content() -> ContentBundle:
    return bundled_content()


def _replace_record(
    content: ContentBundle, kind: str, record_key: str, **changes
) -> ContentBundle:
    records = dict(content._records)
    row = copy.deepcopy(dict(records[kind, record_key]))
    row.update(changes)
    records[kind, record_key] = row
    return replace(content, _records=records)


def _replace_pass(content: ContentBundle, **changes) -> ContentBundle:
    return _replace_record(content, "wayfaring_pass", WAYFARING_PASS_KEY, **changes)


def test_wayfaring_default_content_and_detached_snapshots(
    content: ContentBundle,
) -> None:
    definition = wayfaring_definition(content)
    assert (
        definition.cycle_days,
        definition.max_level,
        definition.points_per_level,
    ) == (28, 30, 80)
    assert (definition.daily_point_cap, definition.weekly_point_cap) == (100, 600)
    assert definition.total_points == 2400
    assert len(definition.sources) == 8
    assert "explore.gather_outskirts" not in definition.sources
    assert "bounty.accept" not in definition.sources
    assert definition.sources["routine.claim_dao_contract"] == {
        "key": "dao_contract.daily",
        "name": "领取道契",
        "points": 10,
    }
    assert definition.reward(1, "free") == {"item.herb.blood_grass": 2}
    assert definition.reward(30, "free") == {"title.wayfaring.wayfarer": 1}
    assert definition.reward(1, "paid") == {"title.wayfaring.pathfinder": 1}
    assert definition.local_reputation_maximum == 1000
    assert definition.reward_labels["title.wayfaring.wayfarer"] == "万里行者"
    assert definition.reward_labels["local_reputation"] == "青石镇名望"
    assert [
        definition.level_for_points(points) for points in (0, 79, 80, 2399, 2400, 9999)
    ] == [0, 0, 1, 29, 30, 30]

    snapshot = json.loads(json.dumps(definition.snapshot()))
    restored = parse_wayfaring_snapshot(snapshot)
    assert restored == definition
    snapshot["sources"]["routine.checkin.daily"]["points"] = 99
    snapshot["free_rewards"][0]["item.herb.blood_grass"] = 99
    snapshot["reward_labels"]["item.herb.blood_grass"] = "changed"
    assert restored.sources["routine.checkin.daily"]["points"] == 20
    assert restored.reward(1, "free") == {"item.herb.blood_grass": 2}
    assert restored.reward_labels["item.herb.blood_grass"] == "止血草"
    result = restored.reward(1, "free")
    result["item.herb.blood_grass"] = 999
    assert restored.reward(1, "free") == {"item.herb.blood_grass": 2}


@pytest.mark.parametrize("weekday", range(7))
def test_wayfaring_every_cycle_start_can_reach_final_level(
    content: ContentBundle, weekday: int
) -> None:
    definition = wayfaring_definition(content)
    start = date(2026, 9, 21) + timedelta(days=weekday)
    weeks = Counter(
        wayfaring_week_start(start + timedelta(days=day))
        for day in range(definition.cycle_days)
    )
    maximum = sum(
        min(days * definition.daily_point_cap, definition.weekly_point_cap)
        for days in weeks.values()
    )
    assert maximum >= definition.total_points


def test_wayfaring_rejects_unreachable_cycle(content: ContentBundle) -> None:
    for weekly_cap in (500, 599):
        with pytest.raises(ContentError, match="unreachable"):
            wayfaring_definition(_replace_pass(content, weekly_point_cap=weekly_cap))
    with pytest.raises(ContentError, match="unreachable"):
        wayfaring_definition(_replace_pass(content, cycle_days=23))


@pytest.mark.parametrize(
    "field",
    [
        "cycle_days",
        "max_level",
        "points_per_level",
        "daily_point_cap",
        "weekly_point_cap",
    ],
)
@pytest.mark.parametrize("value", [True, 0, -1, "30", 30.0])
def test_wayfaring_rejects_nonpositive_or_coerced_numbers(
    content: ContentBundle, field: str, value
) -> None:
    with pytest.raises(ContentError):
        wayfaring_definition(_replace_pass(content, **{field: value}))


@pytest.mark.parametrize(
    "changes",
    [
        {"key": "pass.other"},
        {"name": " "},
        {"desc": " "},
        {"desc": []},
        {"status": "closed"},
        {"status": []},
        {"unexpected": 1},
        {"local_reputation_key": "local."},
        {"local_reputation_key": "local.missing"},
    ],
)
def test_wayfaring_rejects_invalid_identity_or_location(
    content: ContentBundle, changes: dict
) -> None:
    with pytest.raises(ContentError):
        wayfaring_definition(_replace_pass(content, **changes))


@pytest.mark.parametrize(
    "change",
    ["missing", "unknown", "wrong_key", "bool_points", "empty_name", "extra_field"],
)
def test_wayfaring_sources_only_accept_real_settled_producers(
    content: ContentBundle, change: str
) -> None:
    sources = content.require("wayfaring_pass", WAYFARING_PASS_KEY)["sources"]
    if change == "missing":
        sources.pop("production.complete")
    elif change == "unknown":
        sources["bounty.accept"] = {
            "key": "bounty.accept",
            "name": "接取悬赏",
            "points": 15,
        }
    elif change == "wrong_key":
        sources["exploration.settle"]["key"] = "explore.gather_outskirts"
    elif change == "bool_points":
        sources["production.complete"]["points"] = True
    elif change == "empty_name":
        sources["production.complete"]["name"] = " "
    else:
        sources["production.complete"]["extra"] = 1
    with pytest.raises(ContentError):
        wayfaring_definition(_replace_pass(content, sources=sources))


@pytest.mark.parametrize(
    "track,reward",
    [
        ("free", {}),
        ("free", {"item.herb.blood_grass": True}),
        ("free", {"item.herb.blood_grass": 0}),
        ("free", {"exp": 100}),
        ("free", {"item.tribulation_token": 1}),
        ("free", {"title.missing": 1}),
        ("free", {"title.wayfaring.pathfinder": 2}),
        ("paid", {"local_reputation": 1}),
        ("paid", {"item.herb.blood_grass": 1}),
        ("paid", {"item.clue.manual_basic": 1}),
        ("paid", {"realm_layer": 1}),
    ],
)
def test_wayfaring_reward_track_boundaries(
    content: ContentBundle, track: str, reward: dict
) -> None:
    field = f"{track}_rewards"
    rewards = content.require("wayfaring_pass", WAYFARING_PASS_KEY)[field]
    rewards[0] = reward
    with pytest.raises(ContentError):
        wayfaring_definition(_replace_pass(content, **{field: rewards}))


@pytest.mark.parametrize("field", ["free_rewards", "paid_rewards"])
def test_wayfaring_requires_all_level_rewards(
    content: ContentBundle, field: str
) -> None:
    rewards = content.require("wayfaring_pass", WAYFARING_PASS_KEY)[field]
    with pytest.raises(ContentError):
        wayfaring_definition(_replace_pass(content, **{field: rewards[:-1]}))


@pytest.mark.parametrize(
    "kind,key,changes",
    [
        ("item", "item.herb.blood_grass", {"status": "closed"}),
        ("item", "item.clue.recipe_basic", {"status": "closed"}),
        ("item", "item.herb.blood_grass", {"name": ""}),
        (
            "item",
            "item.herb.blood_grass",
            {"effects": [{"type": "breakthrough_material"}]},
        ),
        ("location", "xuantian.new_town", {"status": "closed"}),
        ("location", "xuantian.new_town", {"status": []}),
        ("location", "xuantian.new_town", {"local_reputation_maximum": True}),
    ],
)
def test_wayfaring_validates_current_reward_and_location_references(
    content: ContentBundle, kind: str, key: str, changes: dict
) -> None:
    with pytest.raises(ContentError):
        wayfaring_definition(_replace_record(content, kind, key, **changes))


def test_wayfaring_snapshot_does_not_read_current_content(
    content: ContentBundle, monkeypatch: pytest.MonkeyPatch
) -> None:
    definition = wayfaring_definition(content)
    snapshot = definition.snapshot()

    def unavailable(*args, **kwargs):
        raise AssertionError(
            "current content must not be read during snapshot recovery"
        )

    monkeypatch.setattr(wayfaring, "bundled_content", unavailable)
    monkeypatch.setattr(wayfaring, "local_reputation_maximum", unavailable)
    monkeypatch.setattr(ContentBundle, "get", unavailable)
    assert parse_wayfaring_snapshot(snapshot) == definition


@pytest.mark.parametrize(
    "change",
    [
        "missing",
        "extra",
        "wrong_identity",
        "missing_label",
        "extra_label",
        "empty_label",
        "bool_cap",
        "wrong_rewards",
    ],
)
def test_wayfaring_rejects_corrupt_snapshots(
    content: ContentBundle, change: str
) -> None:
    snapshot = wayfaring_definition(content).snapshot()
    if change == "missing":
        snapshot.pop("sources")
    elif change == "extra":
        snapshot["extra"] = 1
    elif change == "wrong_identity":
        snapshot["key"] = "pass.other"
    elif change == "missing_label":
        snapshot["reward_labels"].pop("item.herb.blood_grass")
    elif change == "extra_label":
        snapshot["reward_labels"]["item.herb.missing"] = "missing"
    elif change == "empty_label":
        snapshot["reward_labels"]["item.herb.blood_grass"] = " "
    elif change == "bool_cap":
        snapshot["local_reputation_maximum"] = True
    else:
        snapshot["free_rewards"][0] = {"exp": 1}
    with pytest.raises(ContentError):
        parse_wayfaring_snapshot(snapshot)


@pytest.mark.parametrize("value", [True, -1, "80", 80.0])
def test_wayfaring_points_require_nonnegative_integer(
    content: ContentBundle, value
) -> None:
    with pytest.raises(ContentError):
        wayfaring_definition(content).level_for_points(value)


@pytest.mark.parametrize(
    "level,track", [(True, "free"), (0, "free"), (31, "free"), (1, "other"), (1, [])]
)
def test_wayfaring_reward_lookup_is_strict(
    content: ContentBundle, level, track
) -> None:
    with pytest.raises(ContentError):
        wayfaring_definition(content).reward(level, track)
