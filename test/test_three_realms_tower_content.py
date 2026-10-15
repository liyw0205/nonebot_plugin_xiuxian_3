from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from nonebot_plugin_xiuxian_3.xiuxian.combat.rules import enemy_definition
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError
from nonebot_plugin_xiuxian_3.xiuxian.specials.three_realms_tower_rules import (
    FACTIONS,
    MAX_FLOOR,
    NASCENT_SOUL_MAX_FLOOR,
    REBUILD_REPUTATION_KEYS,
    TOWER_KEY,
    WEEKLY_ATTEMPT_LIMIT,
    enemy_key_for,
    floor_definition,
    floor_gate,
    reward_for,
)

ROOT = Path(__file__).resolve().parents[1]
TOWER_FILE = Path("特殊/三界塔.json")


def _tower_record(data_dir: Path) -> dict:
    document = json.loads((data_dir / TOWER_FILE).read_text(encoding="utf-8"))
    return next(row for row in document["records"] if row["key"] == TOWER_KEY)


def _write_tower(data_dir: Path, record: dict) -> None:
    document = json.loads((data_dir / TOWER_FILE).read_text(encoding="utf-8"))
    document["records"] = [record]
    (data_dir / TOWER_FILE).write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def test_three_realms_tower_contract_covers_every_floor_and_faction() -> None:
    record = _tower_record(ROOT / "data")
    assert record["status"] == "active"
    assert record["max_floor"] == MAX_FLOOR == 40
    assert record["weekly_attempt_limit"] == WEEKLY_ATTEMPT_LIMIT == 2
    assert tuple(record["factions"]) == FACTIONS == ("xuantian", "demon", "beast")
    assert tuple(record["rebuild_reputation_keys"]) == REBUILD_REPUTATION_KEYS
    segments = record["segments"]
    assert [segment["floor_min"] for segment in segments] == [1, 11, 21, 31]
    assert [segment["floor_max"] for segment in segments] == [10, 20, 30, 40]
    for segment in segments:
        assert segment["stamina_cost"] == 12
        assert segment["weekly_limit"] == 2
        assert segment["first_clear_reward"] == {"item.mat.array_sand": 2, "spirit_stones": 60}
        assert segment["repeat_reward"] == {"item.mat.array_sand": 1}
    assert [segment["boss_floors"] for segment in segments] == [[10], [20], [30], [40]]


def test_three_realms_tower_rules_match_the_shipped_contract() -> None:
    for floor_no in range(1, MAX_FLOOR + 1):
        definition = floor_definition(floor_no)
        expected_realm = "nascent_soul" if floor_no <= NASCENT_SOUL_MAX_FLOOR else "soul_transformation"
        assert definition.required_realm == expected_realm
        assert definition.required_layer == 1
        assert definition.stamina_cost == 12
        assert definition.weekly_limit == 2
        assert definition.boss is (floor_no in {10, 20, 30, 40})
        for faction in FACTIONS:
            key = enemy_key_for(floor_no, faction)
            assert key.startswith(f"enemy.three_realms_tower.{faction}.")
            # Every composed key must resolve to a real enemy the battle layer accepts.
            assert enemy_definition(key).key == key
        permit_flag, threshold = floor_gate(floor_no)
        if floor_no <= NASCENT_SOUL_MAX_FLOOR:
            assert permit_flag == "story.mainline.three_realms"
            assert threshold == 0
        else:
            assert permit_flag is None
            assert threshold == 500
    assert enemy_key_for(10, "beast") == "enemy.three_realms_tower.beast.floor_10_boss"
    assert enemy_key_for(21, "demon").endswith(".domain_vanguard")
    assert reward_for(1, "seed", first_clear=True) == {
        "item.mat.array_sand": 2,
        "spirit_stones": 60,
    }
    assert reward_for(1, "seed", first_clear=False) in ({}, {"item.mat.array_sand": 1})
    assert reward_for(40, "seed", first_clear=True) == {
        "item.mat.array_sand": 2,
        "spirit_stones": 60,
    }


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda record: record["segments"].pop(1), "contiguous"),
        (
            lambda record: record["segments"][1].update({"floor_min": 12}),
            "contiguous",
        ),
        (
            lambda record: record["segments"][0].update({"required_realm": "unknown_realm"}),
            "unknown_realm",
        ),
        (
            lambda record: record["segments"][0].update(
                {"first_clear_reward": {"item.not_a_real_item": 1}}
            ),
            "not_a_real_item",
        ),
        (lambda record: record["segments"][0].update({"boss_floors": [11]}), "boss floor outside"),
        (lambda record: record.update({"factions": ["xuantian"]}), "factions"),
        (lambda record: record.update({"max_floor": 41}), "max_floor"),
        (lambda record: record["segments"][0].pop("repeat_reward"), "missing or unknown fields"),
    ],
)
def test_three_realms_tower_rejects_invalid_contract(tmp_path: Path, mutate, message: str) -> None:
    data_dir = tmp_path / "data"
    shutil.copytree(ROOT / "data", data_dir, ignore=shutil.ignore_patterns("*.sqlite3*", "*.db*"))
    record = _tower_record(data_dir)
    mutate(record)
    _write_tower(data_dir, record)
    bundle = ContentBundle.load(data_dir)
    with pytest.raises(ContentError, match=message):
        floor_definition(1, bundle)
