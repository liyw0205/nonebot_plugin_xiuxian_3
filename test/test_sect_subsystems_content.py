from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pytest

from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError
from nonebot_plugin_xiuxian_3.xiuxian.social import (
    sect_alliance_rules,
    sect_beacon_rules,
    sect_exchange_rules,
    sect_war_rules,
)
from nonebot_plugin_xiuxian_3.xiuxian.social.social_content import (
    SECT_ALLIANCE_KEY,
    SECT_BEACON_KEY,
    SECT_EXCHANGE_KEY,
    SECT_WAR_KEY,
    sect_alliance_record,
    sect_beacon_record,
    sect_exchange_record,
    sect_war_record,
)

ROOT = Path(__file__).resolve().parents[1]
SOCIAL_FILE = Path("社交/玩家互动.json")


def _copy_data(tmp_path: Path) -> Path:
    data_dir = tmp_path / "data"
    shutil.copytree(
        ROOT / "data", data_dir, ignore=shutil.ignore_patterns("*.sqlite3*", "*.db*")
    )
    return data_dir


def _record(data_dir: Path, key: str) -> dict:
    document = json.loads((data_dir / SOCIAL_FILE).read_text(encoding="utf-8"))
    return next(row for row in document["records"] if row["key"] == key)


def _write_record(data_dir: Path, record: dict) -> None:
    document = json.loads((data_dir / SOCIAL_FILE).read_text(encoding="utf-8"))
    document["records"] = [
        record if row["key"] == record["key"] else row for row in document["records"]
    ]
    (data_dir / SOCIAL_FILE).write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def test_alliance_record_matches_the_module_constants() -> None:
    record = sect_alliance_record()
    assert record["min_sect_level"] == sect_alliance_rules.ALLIANCE_MIN_SECT_LEVEL == 5
    assert (
        record["confirmation_seconds"]
        == sect_alliance_rules.ALLIANCE_CONFIRMATION_SECONDS
        == 86400
    )
    assert (
        record["duration_seconds"] == sect_alliance_rules.ALLIANCE_DURATION_SECONDS == 604800
    )
    assert (
        record["research_weekly_cap"]
        == sect_alliance_rules.ALLIANCE_RESEARCH_WEEKLY_CAP
        == 3
    )
    assert record["breach_fee"] == sect_alliance_rules.ALLIANCE_BREACH_FEE == 10000
    assert (
        record["cooldown_seconds"]
        == sect_alliance_rules.SECT_ALLIANCE_COOLDOWN_SECONDS
        == 86400
    )
    assert (
        sect_alliance_rules.alliance_week_id(datetime(2026, 10, 15, tzinfo=timezone.utc))
        == "2026-W42"
    )


def test_beacon_record_matches_the_module_constants() -> None:
    record = sect_beacon_record()
    assert record["anchor_cost"] == sect_beacon_rules.VOID_BEACON_ANCHOR_COST == 10
    assert record["sand_cost"] == sect_beacon_rules.VOID_BEACON_SAND_COST == 30
    assert record["build_seconds"] == sect_beacon_rules.VOID_BEACON_BUILD_SECONDS == 86400
    assert (
        record["maintenance_anchor_cost"]
        == sect_beacon_rules.VOID_BEACON_MAINTENANCE_ANCHOR_COST
        == 2
    )
    assert record["route_discount"] == sect_beacon_rules.VOID_BEACON_ROUTE_DISCOUNT == 1


def test_exchange_record_matches_the_module_tables() -> None:
    record = sect_exchange_record()
    assert record["daily_cap"] == sect_exchange_rules.SECT_EXCHANGE_DAILY_CAP == 5
    assert frozenset(record["donation_items"]) == sect_exchange_rules.SECT_DONATION_ITEMS == frozenset(
        {
            "item.herb.spirit_leaf",
            "item.herb.blood_grass",
            "item.mat.array_sand",
            "item.material.cloud_iron",
        }
    )
    assert record["donation_aliases"] == sect_exchange_rules.SECT_DONATION_ALIASES == {
        "灵叶": "item.herb.spirit_leaf",
        "止血草": "item.herb.blood_grass",
        "阵砂": "item.mat.array_sand",
        "云铁": "item.material.cloud_iron",
    }
    assert record["supply_recipes"] == sect_exchange_rules.SECT_SUPPLY_RECIPES
    assert sect_exchange_rules.SECT_SUPPLY_RECIPES["sect.exchange.foundation_guard"] == (
        {
            "item.herb.spirit_leaf": 2,
            "item.mat.array_sand": 1,
            "item.herb.blood_grass": 1,
        },
        100,
    )
    assert sect_exchange_rules.SECT_SUPPLY_RECIPES["sect.exchange.golden_core_guard"] == (
        {
            "item.herb.spirit_leaf": 3,
            "item.material.cloud_iron": 1,
            "item.herb.blood_grass": 2,
        },
        200,
    )
    assert record["aliases"] == sect_exchange_rules.SECT_EXCHANGE_ALIASES
    assert len(sect_exchange_rules.SECT_EXCHANGE_ALIASES) == 10
    expected_offers = {
        "sect.exchange.foundation_guard": ("筑基护脉丹", 30, "item.pill.foundation_guard", 1),
        "sect.exchange.cloud_iron": ("云铁", 20, "item.material.cloud_iron", 2),
        "sect.exchange.golden_core_guard": ("金丹护脉丹", 50, "item.pill.golden_core_guard", 1),
        "sect.exchange.array_sand": ("阵砂", 10, "item.mat.array_sand", 5),
    }
    assert set(sect_exchange_rules.SECT_EXCHANGE_OFFERS) == set(expected_offers)
    for key, (label, cost, item_key, quantity) in expected_offers.items():
        offer = sect_exchange_rules.SECT_EXCHANGE_OFFERS[key]
        assert (offer.key, offer.label, offer.contribution_cost, offer.item_key, offer.quantity) == (
            key,
            label,
            cost,
            item_key,
            quantity,
        )


def test_resolve_sect_exchange_offer_behaviour_is_unchanged() -> None:
    resolve = sect_exchange_rules.resolve_sect_exchange_offer
    assert resolve("筑基护脉丹").key == "sect.exchange.foundation_guard"
    assert resolve("筑基保护丹").key == "sect.exchange.foundation_guard"
    assert resolve("sect.exchange.cloud_iron").key == "sect.exchange.cloud_iron"
    assert resolve("阵砂").key == "sect.exchange.array_sand"
    assert resolve("金丹保护丹").key == "sect.exchange.golden_core_guard"
    assert resolve(" 云铁 ") is not None
    assert resolve("not-an-offer") is None
    assert resolve("") is None


def test_war_record_matches_the_module_constants() -> None:
    record = sect_war_record()
    assert record["war_key"] == sect_war_rules.SECT_WAR_KEY == "sect_war"
    assert record["anchor"] == sect_war_rules.SECT_WAR_ANCHOR == datetime(
        2025, 1, 6, tzinfo=timezone.utc
    )
    assert record["rounds_per_week"] == sect_war_rules.SECT_WAR_ROUNDS_PER_WEEK == 2
    assert record["duration_minutes"] == sect_war_rules.SECT_WAR_DURATION_MINUTES == 30
    assert record["registration_fee"] == sect_war_rules.SECT_WAR_REGISTRATION_FEE == 2000
    assert record["max_participants"] == sect_war_rules.SECT_WAR_MAX_PARTICIPANTS == 10
    assert record["min_level"] == sect_war_rules.SECT_WAR_MIN_LEVEL == 4
    assert record["member_threshold"] == sect_war_rules.SECT_WAR_MEMBER_THRESHOLD == 20
    assert record["sect_reward"] == sect_war_rules.SECT_WAR_SECT_REWARD == 100
    assert record["member_reward"] == sect_war_rules.SECT_WAR_MEMBER_REWARD == 30
    assert record["claim_hours"] == sect_war_rules.SECT_WAR_CLAIM_HOURS == 24
    assert record["action_values"] == sect_war_rules.SECT_WAR_ACTION_VALUES == {
        "占点": 10,
        "击败": 5,
        "运输": 15,
        "维修": 15,
    }


def test_sect_war_scores_and_windows_are_unchanged() -> None:
    contribution_value = sect_war_rules.contribution_value
    assert contribution_value("占点", 1) == 10
    assert contribution_value("击败", 4) == 5
    assert contribution_value("运输", 2) == 15
    assert contribution_value("维修", 7) == 15
    assert contribution_value("占点", 0) == 0
    assert contribution_value("占点", -3) == 0
    with pytest.raises(ValueError, match="invalid sect-war action"):
        contribution_value("not-an-action", 1)

    now = datetime(2026, 10, 15, tzinfo=timezone.utc)
    round_id, week, starts_at, ends_at, claim_expires_at = sect_war_rules.sect_war_round_window(now)
    assert round_id == "sect_war:20261012:1"
    assert week == datetime(2026, 10, 12, tzinfo=timezone.utc)
    assert starts_at == datetime(2026, 10, 14, 20, 0, tzinfo=timezone.utc)
    assert ends_at == datetime(2026, 10, 14, 20, 30, tzinfo=timezone.utc)
    assert claim_expires_at == datetime(2026, 10, 15, 20, 30, tzinfo=timezone.utc)
    second = sect_war_rules.sect_war_round_window(now, 1)
    assert second[0] == "sect_war:20261012:2"
    assert second[2] == datetime(2026, 10, 17, 20, 0, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="invalid sect-war round index"):
        sect_war_rules.sect_war_round_window(now, 2)
    canonical = sect_war_rules.sect_war_round_for_id("sect_war:20261012:1")
    assert canonical[0] == "sect_war:20261012:1"
    with pytest.raises(ValueError, match="invalid sect-war round id"):
        sect_war_rules.sect_war_round_for_id("sect_war:nope")


@pytest.mark.parametrize(
    "key, mutate, message, loader",
    [
        (SECT_ALLIANCE_KEY, lambda r: r.pop("name"), "requires a name", sect_alliance_record),
        (SECT_ALLIANCE_KEY, lambda r: r.update({"breach_fee": 0}), "positive integer", sect_alliance_record),
        (SECT_BEACON_KEY, lambda r: r.update({"status": "locked"}), "not open", sect_beacon_record),
        (SECT_BEACON_KEY, lambda r: r.update({"route_discount": -1}), "positive integer", sect_beacon_record),
        (SECT_EXCHANGE_KEY, lambda r: r.update({"daily_cap": 0}), "positive integer", sect_exchange_record),
        (SECT_EXCHANGE_KEY, lambda r: r.update({"donation_items": []}), "non-empty list", sect_exchange_record),
        (SECT_EXCHANGE_KEY, lambda r: r.update({"donation_items": ["item.nope"]}), "unknown item", sect_exchange_record),
        (SECT_EXCHANGE_KEY, lambda r: r["donation_aliases"].update({"灵叶": "item.nope"}), "outside donation_items", sect_exchange_record),
        (SECT_EXCHANGE_KEY, lambda r: r["supply_recipes"]["sect.exchange.foundation_guard"].update({"contribution": 0}), "positive integer", sect_exchange_record),
        (SECT_EXCHANGE_KEY, lambda r: r["supply_recipes"]["sect.exchange.foundation_guard"]["materials"].update({"item.nope": 1}), "unknown item", sect_exchange_record),
        (SECT_EXCHANGE_KEY, lambda r: r["offers"][1].update({"key": r["offers"][0]["key"]}), "duplicate key", sect_exchange_record),
        (SECT_EXCHANGE_KEY, lambda r: r["offers"][0].update({"label": " "}), "requires a label", sect_exchange_record),
        (SECT_EXCHANGE_KEY, lambda r: r["offers"][0].update({"item_key": "item.nope"}), "unknown item", sect_exchange_record),
        (SECT_EXCHANGE_KEY, lambda r: r["aliases"].update({"阵砂": "sect.exchange.nope"}), "unknown offer", sect_exchange_record),
        (SECT_EXCHANGE_KEY, lambda r: r.update({"offers": []}), "non-empty list", sect_exchange_record),
        (SECT_WAR_KEY, lambda r: r.update({"war_key": " "}), "war_key is invalid", sect_war_record),
        (SECT_WAR_KEY, lambda r: r.update({"anchor": "not-a-date"}), "anchor is invalid", sect_war_record),
        (SECT_WAR_KEY, lambda r: r.update({"anchor": "2025-01-06"}), "timezone-aware", sect_war_record),
        (SECT_WAR_KEY, lambda r: r.update({"action_values": {}}), "non-empty object", sect_war_record),
        (SECT_WAR_KEY, lambda r: r["action_values"].update({"占点": 0}), "positive integer", sect_war_record),
        (SECT_WAR_KEY, lambda r: r.update({"claim_hours": 0}), "positive integer", sect_war_record),
    ],
)
def test_sect_subsystem_content_rejects_invalid_contract(
    tmp_path: Path, key: str, mutate, message: str, loader
) -> None:
    data_dir = _copy_data(tmp_path)
    record = _record(data_dir, key)
    mutate(record)
    _write_record(data_dir, record)
    bundle = ContentBundle.load(data_dir)
    with pytest.raises(ContentError, match=message):
        loader(bundle)


def test_missing_sect_record_raises_content_error(tmp_path: Path) -> None:
    data_dir = _copy_data(tmp_path)
    document = json.loads((data_dir / SOCIAL_FILE).read_text(encoding="utf-8"))
    document["records"] = [
        row for row in document["records"] if row["key"] != SECT_WAR_KEY
    ]
    (data_dir / SOCIAL_FILE).write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    bundle = ContentBundle.load(data_dir)
    with pytest.raises(ContentError, match="missing social_interaction content"):
        sect_war_record(bundle)
