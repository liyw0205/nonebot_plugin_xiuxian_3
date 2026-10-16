from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pytest

from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError
from nonebot_plugin_xiuxian_3.xiuxian.events import cross_realm_rules, void_frontier_rules
from nonebot_plugin_xiuxian_3.xiuxian.events.cross_realm_rules import cross_realm_action_values
from nonebot_plugin_xiuxian_3.xiuxian.events.season_content import (
    VOID_FRONTIER_SEASON_KEY,
    season_record,
)

ROOT = Path(__file__).resolve().parents[1]
EVENT_FILE = Path("事件/事件.json")
SEASON_FILE = Path("事件/赛季.json")

EXPECTED_ALIASES = {
    "event.beast_trade": {
        "贸易": "trade",
        "跨界贸易": "trade",
        "妖血": "blood",
        "提交妖血": "blood",
    },
    "event.boundary_rift": {"路线": "route", "首领": "boss", "完成": "complete"},
    "event.ancient_domain_open": {"完成": "complete", "远古洞天": "complete"},
}


def _copy_data(tmp_path: Path) -> Path:
    data_dir = tmp_path / "data"
    shutil.copytree(
        ROOT / "data", data_dir, ignore=shutil.ignore_patterns("*.sqlite3*", "*.db*")
    )
    return data_dir


def _record(data_dir: Path, relative: Path, key: str) -> dict:
    document = json.loads((data_dir / relative).read_text(encoding="utf-8"))
    return next(row for row in document["records"] if row["key"] == key)


def _write_record(data_dir: Path, relative: Path, record: dict) -> None:
    document = json.loads((data_dir / relative).read_text(encoding="utf-8"))
    document["records"] = [
        record if row["key"] == record["key"] else row for row in document["records"]
    ]
    (data_dir / relative).write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def test_cross_realm_tables_match_their_event_records() -> None:
    tables = {
        "event.beast_trade": cross_realm_rules.BEAST_TRADE_ACTION_VALUES,
        "event.boundary_rift": cross_realm_rules.BOUNDARY_RIFT_ACTION_VALUES,
        "event.ancient_domain_open": cross_realm_rules.ANCIENT_DOMAIN_OPEN_ACTION_VALUES,
    }
    assert cross_realm_rules.BEAST_TRADE_EVENT_KEY == "event.beast_trade"
    assert cross_realm_rules.BOUNDARY_RIFT_EVENT_KEY == "event.boundary_rift"
    assert cross_realm_rules.ANCIENT_DOMAIN_OPEN_EVENT_KEY == "event.ancient_domain_open"
    for event_key, table in tables.items():
        record = _record(ROOT / "data", EVENT_FILE, event_key)
        assert table == EXPECTED_ALIASES[event_key]
        assert record["action_aliases"] == table
        assert set(table.values()) <= set(record["public_event"]["contributions"])


def test_cross_realm_loader_rejects_unknown_action(tmp_path: Path) -> None:
    data_dir = _copy_data(tmp_path)
    record = _record(data_dir, EVENT_FILE, "event.beast_trade")
    record["action_aliases"]["贸易"] = "not-a-contribution"
    _write_record(data_dir, EVENT_FILE, record)
    bundle = ContentBundle.load(data_dir)
    with pytest.raises(ContentError, match="unknown action"):
        cross_realm_action_values("event.beast_trade", bundle)


def test_void_frontier_record_matches_the_module_constants() -> None:
    record = season_record(VOID_FRONTIER_SEASON_KEY)
    assert void_frontier_rules.SEASON_KEY == VOID_FRONTIER_SEASON_KEY == "season.void_frontier"
    assert record["duration_days"] == void_frontier_rules.SEASON_DAYS == 28
    assert record["claim_days"] == void_frontier_rules.CLAIM_DAYS == 7
    assert record["weekly_cap"] == void_frontier_rules.WEEKLY_CAP == 5
    assert record["rank_limit"] == void_frontier_rules.RANKED_PLACES == 100
    assert record["anchor"] == void_frontier_rules.SEASON_ANCHOR == datetime(
        2025, 1, 1, tzinfo=timezone.utc
    )
    assert record["weekly_reward"] == void_frontier_rules.WEEKLY_REWARD == {
        "void_merit": 20,
        "alliance_points": 10,
    }
    assert record["score_values"] == void_frontier_rules.SCORE_VALUES == {
        "route_completed": 30,
        "storm_rescue": 50,
        "cross_server_victory": 100,
        "alliance_contract": 20,
    }
    assert record["boards"] == {}


def test_void_frontier_rank_rewards_and_window_are_unchanged() -> None:
    assert void_frontier_rules.reward_for_rank(1) == {
        "item.void_crystal": 5,
        "void_merit": 100,
    }
    assert void_frontier_rules.reward_for_rank(2) == {
        "item.void_crystal": 3,
        "void_merit": 60,
    }
    assert void_frontier_rules.reward_for_rank(3) == {
        "item.void_crystal": 2,
        "void_merit": 40,
    }
    assert void_frontier_rules.reward_for_rank(4) == {
        "item.void_crystal": 1,
        "void_merit": 20,
    }
    assert void_frontier_rules.reward_for_rank(99) == {
        "item.void_crystal": 1,
        "void_merit": 20,
    }
    # Each call returns an independent mapping.
    first = void_frontier_rules.reward_for_rank(1)
    first["item.void_crystal"] = 999
    assert void_frontier_rules.reward_for_rank(1)["item.void_crystal"] == 5

    now = datetime(2026, 10, 15, tzinfo=timezone.utc)
    season_id, starts_at, ends_at = void_frontier_rules.season_window(now)
    assert season_id == "season.void_frontier:20261007"
    assert starts_at == datetime(2026, 10, 7, tzinfo=timezone.utc)
    assert (ends_at - starts_at).days == 28
    assert void_frontier_rules.week_id(now) == "2026-10-12"


@pytest.mark.parametrize(
    "relative, key, mutate, message, loader",
    [
        (EVENT_FILE, "event.beast_trade", lambda r: r.update({"action_aliases": {}}), "non-empty object", cross_realm_action_values),
        (EVENT_FILE, "event.beast_trade", lambda r: r["action_aliases"].update({"贸易": "nope"}), "unknown action", cross_realm_action_values),
        (SEASON_FILE, VOID_FRONTIER_SEASON_KEY, lambda r: r.update({"weekly_cap": 0}), "positive integer", season_record),
        (SEASON_FILE, VOID_FRONTIER_SEASON_KEY, lambda r: r.update({"score_values": {}}), "non-empty object", season_record),
        (SEASON_FILE, VOID_FRONTIER_SEASON_KEY, lambda r: r["score_values"].update({"storm_rescue": 0}), "positive integer", season_record),
        (SEASON_FILE, VOID_FRONTIER_SEASON_KEY, lambda r: r["rank_rewards"].append({"rank": 1, "reward": {"void_merit": 5}}), "duplicate rank", season_record),
        (SEASON_FILE, VOID_FRONTIER_SEASON_KEY, lambda r: r.update({"default_rank_reward": {}}), "non-empty object", season_record),
        (SEASON_FILE, VOID_FRONTIER_SEASON_KEY, lambda r: r["weekly_reward"].update({"void_merit": -1}), "positive integer", season_record),
        (SEASON_FILE, VOID_FRONTIER_SEASON_KEY, lambda r: r.update({"anchor": "2025-01-01"}), "timezone-aware", season_record),
        (SEASON_FILE, VOID_FRONTIER_SEASON_KEY, lambda r: r.pop("name"), "requires a name", season_record),
        (SEASON_FILE, VOID_FRONTIER_SEASON_KEY, lambda r: r.update({"rank_rewards": []}), "non-empty list", season_record),
    ],
)
def test_cross_realm_void_frontier_rejects_invalid_contract(
    tmp_path: Path, relative: Path, key: str, mutate, message: str, loader
) -> None:
    data_dir = _copy_data(tmp_path)
    record = _record(data_dir, relative, key)
    mutate(record)
    _write_record(data_dir, relative, record)
    bundle = ContentBundle.load(data_dir)
    with pytest.raises(ContentError, match=message):
        loader(key, bundle)
