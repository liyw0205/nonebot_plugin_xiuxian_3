from __future__ import annotations

import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError
from nonebot_plugin_xiuxian_3.xiuxian.specials.final_arena_content import (
    final_arena_alias_map,
    final_arena_defaults,
    final_arena_tiers,
)
from nonebot_plugin_xiuxian_3.xiuxian.specials.final_arena_rules import (
    arena_is_open,
    arena_missing_requirements,
    arena_window,
    final_arena_definition,
    next_tier_no,
    resolve_final_arena_tier,
)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
ARENA_FILE = Path("特殊/终局天榜.json")
LOCATION_FILE = Path("地图/地点.json")
REGION_FILE = Path("地图/区域.json")


def _copy_data(tmp_path: Path) -> Path:
    target = tmp_path / "data"
    shutil.copytree(DATA, target)
    return target


def _document(root: Path, relative: Path) -> dict:
    return json.loads((root / relative).read_text(encoding="utf-8"))


def _write(root: Path, relative: Path, document: dict) -> None:
    (root / relative).write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _record(document: dict, key: str) -> dict:
    return next(row for row in document["records"] if row["key"] == key)


def test_shipped_arena_content_matches_the_frozen_world_row() -> None:
    bundle = ContentBundle.load(DATA)
    assert ARENA_FILE.as_posix() in bundle.manifest["files"]

    defaults = final_arena_defaults(bundle)
    assert defaults["location_key"] == "location.final_arena"
    assert defaults["schedule"] == {
        "kind": "utc_block",
        "block_hours": 4,
        "duration_seconds": 7200,
        "claim_window_seconds": 86400,
    }
    assert defaults["attempt_limit_per_round"] == 3
    assert defaults["stamina_cost"] == 15
    assert defaults["required_realm"] == "tribulation"
    assert defaults["required_layer"] == 6

    # The frozen world row: 渡劫 L6, activity-round gated, 15 stamina.
    location = bundle.get("location", "location.final_arena", include_locked=True)
    assert location["status"] == "open"
    assert location["codex_entry_key"] == "codex.place.final_arena"
    assert location["requirements"] == [
        {"type": "realm", "realm_key": "tribulation", "min_layer": 6}
    ]
    assert bundle.get("codex_entry", "codex.place.final_arena", include_locked=True) is not None

    edges = {
        (edge["from"], edge["to"]): edge
        for region in bundle.list("world_region", include_locked=True)
        for edge in region["connections"]
    }
    for source, target in (
        ("tribulation.sky_terrace", "location.final_arena"),
        ("location.final_arena", "tribulation.sky_terrace"),
    ):
        edge = edges[(source, target)]
        assert edge["duration_seconds"] == 900
        assert edge["stamina"] == 15
        assert "item_key" not in edge and "daily_start_limit" not in edge
        assert edge["requirements"] == [
            {"type": "realm", "realm_key": "tribulation", "min_layer": 6}
        ]

    tiers = final_arena_tiers(bundle)
    assert [record["key"] for record in tiers] == [
        "tier.final_arena.1",
        "tier.final_arena.2",
        "tier.final_arena.3",
    ]
    assert [record["required_best_tier"] for record in tiers] == [0, 1, 2]
    assert tiers[-1]["title_key"] == "title.final_arena.summit"
    for record in tiers:
        assert record["aliases"], record["key"]
        enemy = bundle.get("enemy", record["enemy_key"], include_locked=False)
        assert enemy is not None and enemy["location_key"] == "location.final_arena"
        assert isinstance(enemy.get("combat_profile"), dict)

    aliases = final_arena_alias_map(bundle)
    assert aliases["初阶"] == "tier.final_arena.1"
    assert aliases["中阶"] == "tier.final_arena.2"
    assert aliases["上阶"] == "tier.final_arena.3"
    assert resolve_final_arena_tier("天榜上阶", bundle) == "tier.final_arena.3"
    assert resolve_final_arena_tier("不存在的层级", bundle) is None


def test_windows_are_four_hour_utc_blocks() -> None:
    definition = final_arena_definition(ContentBundle.load(DATA))
    inside = datetime(2026, 11, 3, 5, 0, tzinfo=timezone.utc)
    round_id, start, end, claim = arena_window(inside, definition)
    assert round_id == "final_arena:202611030400"
    assert start == datetime(2026, 11, 3, 4, 0, tzinfo=timezone.utc)
    assert end == datetime(2026, 11, 3, 6, 0, tzinfo=timezone.utc)
    assert claim == datetime(2026, 11, 4, 6, 0, tzinfo=timezone.utc)
    assert arena_is_open(inside, definition)
    assert arena_is_open(datetime(2026, 11, 3, 6, 0, tzinfo=timezone.utc), definition) is False
    assert arena_is_open(datetime(2026, 11, 3, 7, 59, tzinfo=timezone.utc), definition) is False
    assert arena_is_open(datetime(2026, 11, 3, 8, 0, tzinfo=timezone.utc), definition)
    assert arena_window(datetime(2026, 11, 3, 23, 59, tzinfo=timezone.utc), definition)[0] == (
        "final_arena:202611032000"
    )
    assert next_tier_no(0, definition) == 1
    assert next_tier_no(2, definition) == 3
    assert next_tier_no(3, definition) == 3


def test_realm_gate_follows_the_location_row() -> None:
    definition = final_arena_definition(ContentBundle.load(DATA))
    assert arena_missing_requirements(
        realm_key="tribulation", realm_layer=6, definition=definition
    ) == ()
    assert arena_missing_requirements(
        realm_key="tribulation", realm_layer=10, definition=definition
    ) == ()
    missing = arena_missing_requirements(
        realm_key="tribulation", realm_layer=5, definition=definition
    )
    assert missing and "tribulation" in missing[0]
    missing_low = arena_missing_requirements(
        realm_key="dao_union", realm_layer=10, definition=definition
    )
    assert missing_low


def test_round_window_and_quota_are_deterministic_across_blocks() -> None:
    definition = final_arena_definition(ContentBundle.load(DATA))
    first = arena_window(datetime(2026, 11, 3, 4, 0, tzinfo=timezone.utc), definition)
    same = arena_window(datetime(2026, 11, 3, 7, 59, tzinfo=timezone.utc), definition)
    nxt = arena_window(datetime(2026, 11, 3, 8, 0, tzinfo=timezone.utc), definition)
    assert first[0] == same[0]
    assert nxt[0] != first[0]
    assert nxt[1] == datetime(2026, 11, 3, 8, 0, tzinfo=timezone.utc)
    assert first[3] - first[2] == timedelta(seconds=definition.claim_window_seconds)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda d: _record(d, "arena.final_heaven.defaults").update(
            schedule={"kind": "utc_block", "block_hours": 5, "duration_seconds": 18000, "claim_window_seconds": 86400}
        ), "door window is invalid"),
        (lambda d: _record(d, "arena.final_heaven.defaults").update(
            schedule={"kind": "utc_block", "block_hours": 4, "duration_seconds": 18000, "claim_window_seconds": 86400}
        ), "door window is invalid"),
        (lambda d: _record(d, "arena.final_heaven.defaults").update(
            schedule={"kind": "utc_block", "block_hours": 4, "duration_seconds": 5400, "claim_window_seconds": 86400}
        ), "door window is invalid"),
        (lambda d: _record(d, "arena.final_heaven.defaults").update(
            schedule={"kind": "weekly", "weekday_utc": 0, "duration_seconds": 14400, "claim_window_seconds": 86400}
        ), "schedule fields are invalid"),
        (lambda d: _record(d, "arena.final_heaven.defaults").update(attempt_limit_per_round=0), "attempt_limit_per_round"),
        (lambda d: _record(d, "arena.final_heaven.defaults").update(stamina_cost=0), "stamina_cost"),
        (lambda d: _record(d, "arena.final_heaven.defaults").update(required_layer=5), "differs from its location record"),
        (lambda d: _record(d, "arena.final_heaven.defaults").update(required_realm="dao_union"), "differs from its location record"),
        (lambda d: _record(d, "arena.final_heaven.defaults").update(location_key="location.missing"), "unknown location"),
        (lambda d: _record(d, "arena.final_heaven.defaults").update(status="locked"), "not active"),
        (lambda d: _record(d, "tier.final_arena.2").update(required_best_tier=0), "contiguous ladder"),
        (lambda d: _record(d, "tier.final_arena.2").update(enemy_key="enemy.missing"), "unknown enemy"),
        (lambda d: _record(d, "tier.final_arena.2").update(enemy_key="location.final_arena"), "must be an enemy key"),
        (lambda d: _record(d, "tier.final_arena.3").pop("desc"), "requires a desc"),
        (lambda d: _record(d, "tier.final_arena.3").update(aliases=[]), "aliases must be a non-empty list"),
        (lambda d: _record(d, "tier.final_arena.3").update(title_key="title.missing"), "unknown title"),
        (lambda d: _record(d, "tier.final_arena.2").update(key="arena.wrong_prefix"), "tier."),
        (lambda d: _record(d, "tier.final_arena.2").update(status="locked"), "not active"),
        (lambda d: _record(d, "tier.final_arena.3").update(aliases=["中阶"]), "already owned"),
    ],
)
def test_malformed_arena_content_is_rejected(tmp_path: Path, mutate, message: str) -> None:
    root = _copy_data(tmp_path)
    document = _document(root, ARENA_FILE)
    mutate(document)
    _write(root, ARENA_FILE, document)
    bundle = ContentBundle.load(root)
    with pytest.raises(ContentError, match=message):
        final_arena_defaults(bundle)
        final_arena_tiers(bundle)


def test_arena_world_row_is_required_to_exist(tmp_path: Path) -> None:
    root = _copy_data(tmp_path)
    document = _document(root, LOCATION_FILE)
    document["records"] = [
        row for row in document["records"] if row["key"] != "location.final_arena"
    ]
    _write(root, LOCATION_FILE, document)
    # Region validation runs first at load time: the arena edge would dangle.
    with pytest.raises(ContentError, match="unknown locations"):
        ContentBundle.load(root)


def test_arena_must_stay_inside_its_region(tmp_path: Path) -> None:
    root = _copy_data(tmp_path)
    document = _document(root, REGION_FILE)
    region = _record(document, "region.tribulation.sky")
    region["location_keys"] = [
        key for key in region["location_keys"] if key != "location.final_arena"
    ]
    region["connections"] = [
        edge
        for edge in region["connections"]
        if edge["to"] != "location.final_arena"
        and edge["from"] != "location.final_arena"
    ]
    _write(root, REGION_FILE, document)
    with pytest.raises(ContentError, match="not assigned to a region"):
        ContentBundle.load(root)


def test_arena_edges_must_touch_a_region_member(tmp_path: Path) -> None:
    root = _copy_data(tmp_path)
    document = _document(root, REGION_FILE)
    region = _record(document, "region.tribulation.sky")
    # Keep the arena as a member but drop the connecting edges: the arena then
    # stays reachable from nowhere, which the world loader refuses to accept.
    region["location_keys"] = ["tribulation.sky_terrace"]
    region["connections"] = [
        edge
        for edge in region["connections"]
        if edge["to"] != "location.final_arena"
        and edge["from"] != "location.final_arena"
    ]
    _write(root, REGION_FILE, document)
    with pytest.raises(ContentError, match="not assigned to a region"):
        ContentBundle.load(root)
