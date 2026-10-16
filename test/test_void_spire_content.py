from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from nonebot_plugin_xiuxian_3.xiuxian.combat.rules import enemy_definition
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError
from nonebot_plugin_xiuxian_3.xiuxian.specials.void_spire_rules import (
    MAX_FLOOR,
    floor_definition,
    quota_floor_range,
    reward_for,
    route_codex_for_floor,
    story_codex_for_floor,
    title_for_floor,
)


ROOT = Path(__file__).resolve().parents[1]
TOWER_FILE = Path("特殊/虚空塔.json")


def _tower_records(data_dir: Path) -> list[dict]:
    document = json.loads((data_dir / TOWER_FILE).read_text(encoding="utf-8"))
    return document["records"]


def _write_records(data_dir: Path, records: list[dict]) -> None:
    path = data_dir / TOWER_FILE
    document = json.loads(path.read_text(encoding="utf-8"))
    document["records"] = records
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_void_spire_content_covers_all_floors_and_preserves_open_contract() -> None:
    records = _tower_records(ROOT / "data")
    assert [(row["floor_min"], row["floor_max"]) for row in records] == [
        (1, 15),
        (16, 30),
        (31, 45),
        (46, 60),
        (61, 75),
        (76, 90),
    ]
    assert [row["route_key"] for row in records] == [
        "storm",
        "echo",
        "inscription",
        "witness",
        "origin",
        "ascension",
    ]
    assert [(row["required_realm"], row["required_layer"], row["stamina_cost"], row["weekly_limit"]) for row in records] == [
        ("void_refining", 1, 20, 2),
        ("void_refining", 1, 20, 2),
        ("dao_union", 1, 20, 1),
        ("dao_union", 1, 20, 1),
        ("tribulation", 1, 30, 1),
        ("tribulation", 1, 30, 1),
    ]

    for floor_no in range(1, MAX_FLOOR + 1):
        definition = floor_definition(floor_no)
        assert enemy_definition(definition.enemy_key).key == definition.enemy_key
        assert quota_floor_range(floor_no) == next(
            (row["floor_min"], row["floor_max"])
            for row in records
            if row["floor_min"] <= floor_no <= row["floor_max"]
        )
        assert route_codex_for_floor(floor_no) == f"codex.void.route_spire_{definition.route_key}"
        assert definition.boss is (floor_no in {15, 30, 45, 60, 75, 90})

    assert reward_for(1, "stable-seed", first_clear=True) == {
        "spirit_stones": 120,
        "item.mat.array_sand": 3,
    }
    assert reward_for(15, "stable-seed", first_clear=True) == {
        "spirit_stones": 120,
        "item.mat.array_sand": 3,
        "local.void_supply": 30,
    }
    assert reward_for(31, "stable-seed", first_clear=True) == {}
    assert reward_for(75, "stable-seed", first_clear=True) == {
        "spirit_stones": 180,
        "item.void_crystal": 2,
        "local.dao_service": 50,
        "item.void_anchor": 1,
    }
    assert story_codex_for_floor(45) == "codex.story.void_spire.inscription"
    assert story_codex_for_floor(60) == "codex.story.void_spire.witness"
    assert story_codex_for_floor(75) == "codex.story.void_spire.origin"
    assert title_for_floor(60) == "title.void_spire.witness"
    assert title_for_floor(75) == "title.void_spire.origin"
    assert title_for_floor(31) is None


def test_void_spire_rules_use_host_segment_values(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    shutil.copytree(ROOT / "data", data_dir, ignore=shutil.ignore_patterns("*.sqlite3*", "*.db*"))
    records = _tower_records(data_dir)
    records[0]["stamina_cost"] = 21
    records[0]["reputation_required"] = 601
    _write_records(data_dir, records)

    bundle = ContentBundle.load(data_dir)
    definition = floor_definition(1, bundle)
    assert definition.stamina_cost == 21
    assert definition.reputation_required == 601


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda records: records.pop(1), "cover every floor"),
        (lambda records: records[1].update({"floor_min": 17}), "cover every floor"),
        (lambda records: records[0].update({"required_realm": "unknown_realm"}), "unknown realm"),
        (lambda records: records[0]["enemy_ranges"][0].update({"enemy_key": "enemy.missing"}), "unknown enemy"),
        (lambda records: records[0].update({"route_codex_key": "codex.missing"}), "route codex"),
        (lambda records: records[0].update({"first_clear_reward": {"item.missing": 1}}), "unknown item"),
        (lambda records: records[0].update({"title_key": "title.missing"}), "unknown title"),
        (lambda records: records[0].update({"unexpected": True}), "missing or unknown fields"),
        (lambda records: records[0]["boss_floors"].append(1), "invalid boss floors"),
    ],
)
def test_void_spire_rejects_invalid_content_contract(tmp_path: Path, mutate, message: str) -> None:
    data_dir = tmp_path / "data"
    shutil.copytree(ROOT / "data", data_dir, ignore=shutil.ignore_patterns("*.sqlite3*", "*.db*"))
    records = _tower_records(data_dir)
    mutate(records)
    _write_records(data_dir, records)
    bundle = ContentBundle.load(data_dir)
    with pytest.raises(ContentError, match=message):
        floor_definition(1, bundle)


@pytest.mark.parametrize("lookup", [quota_floor_range, route_codex_for_floor, story_codex_for_floor, title_for_floor])
def test_void_spire_floor_lookups_reject_boolean_floor_numbers(lookup) -> None:
    with pytest.raises(ValueError, match="between 1 and 90"):
        lookup(True)


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda records: records[0]["enemy_ranges"].__setitem__(0, []), "invalid enemy range"),
        (lambda records: records[0].__setitem__("boss_floors", [{"floor": 15}]), "invalid boss floors"),
        (lambda records: records[0].__setitem__("first_clear_reward", {"": 1}), "invalid reward key"),
    ],
)
def test_void_spire_rejects_malformed_nested_contract_values(tmp_path: Path, mutate, message: str) -> None:
    data_dir = tmp_path / "data"
    shutil.copytree(ROOT / "data", data_dir, ignore=shutil.ignore_patterns("*.sqlite3*", "*.db*"))
    records = _tower_records(data_dir)
    mutate(records)
    _write_records(data_dir, records)
    bundle = ContentBundle.load(data_dir)
    with pytest.raises(ContentError, match=message):
        floor_definition(1, bundle)
