from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pytest

from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError
from nonebot_plugin_xiuxian_3.xiuxian.events import rules, season_rules, three_realms_rules
from nonebot_plugin_xiuxian_3.xiuxian.events.demon_rules import (
    DEMON_ACTION_VALUES,
    DEMON_EVENT_KEY,
    demon_action_values,
)
from nonebot_plugin_xiuxian_3.xiuxian.events.season_content import (
    FINAL_HEAVEN_SEASON_KEY,
    THREE_REALMS_SEASON_KEY,
    season_record,
)
from nonebot_plugin_xiuxian_3.xiuxian.social import sect_rules
from nonebot_plugin_xiuxian_3.xiuxian.social.social_content import (
    SECT_KEY,
    sect_rules_record,
)

ROOT = Path(__file__).resolve().parents[1]
SEASON_FILE = Path("事件/赛季.json")
EVENT_FILE = Path("事件/事件.json")
SOCIAL_FILE = Path("社交/玩家互动.json")

ANCHOR = datetime(2025, 1, 1, tzinfo=timezone.utc)


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


def test_three_realms_season_matches_the_module_constants() -> None:
    record = season_record(THREE_REALMS_SEASON_KEY)
    assert three_realms_rules.SEASON_KEY == THREE_REALMS_SEASON_KEY
    assert record["duration_days"] == three_realms_rules.SEASON_DAYS == 28
    assert record["claim_days"] == three_realms_rules.CLAIM_DAYS == 7
    assert record["anchor"] == three_realms_rules.SEASON_ANCHOR == ANCHOR
    assert record["rank_limit"] == three_realms_rules.RANKED_PLACES == 100
    assert record["boards"] == three_realms_rules.BOARDS == {
        "faction_merit": {"label": "阵营功勋榜"},
        "party_contribution": {"label": "多人副本贡献榜"},
        "sect_contribution": {"label": "宗门贡献榜"},
    }


def test_final_heaven_season_matches_the_module_constants() -> None:
    record = season_record(FINAL_HEAVEN_SEASON_KEY)
    assert rules.FINAL_HEAVEN_SEASON_KEY == FINAL_HEAVEN_SEASON_KEY
    assert record["duration_days"] == rules.FINAL_HEAVEN_SEASON_DAYS == 35
    assert record["anchor"] == rules.FINAL_HEAVEN_SEASON_ANCHOR == ANCHOR
    assert record["claim_days"] == season_rules.FINAL_HEAVEN_CLAIM_DAYS == 7
    assert record["rank_limit"] == season_rules.FINAL_HEAVEN_RANKED_PLACES == 10
    assert (
        record["chapter_entitlement"]
        == season_rules.FINAL_HEAVEN_CHAPTER_ENTITLEMENT
        == "chapter.final_heaven"
    )
    assert record["boards"] == season_rules.FINAL_HEAVEN_BOARDS
    assert season_rules.FINAL_HEAVEN_BOARDS["ascension"] == {
        "label": "飞升榜",
        "title_key": "title.season.final_heaven.ascension",
        "title_label": "凌霄先登",
        "score": 1000,
    }
    assert season_rules.FINAL_HEAVEN_BOARDS["dao"]["score"] == 800
    assert season_rules.FINAL_HEAVEN_BOARDS["cooperation"]["score"] == 50


def test_season_windows_still_compute_from_the_content_anchor() -> None:
    now = datetime(2026, 10, 15, tzinfo=timezone.utc)
    season_id, starts_at, ends_at = three_realms_rules.season_window(now)
    assert season_id == "season.three_realms:20261007"
    assert (ends_at - starts_at).days == 28
    final_id, final_start, final_end = rules.final_heaven_season_window(now)
    assert final_id == "season.final_heaven:20260923"
    assert (final_end - final_start).days == 35


def test_demon_action_aliases_match_the_event_record() -> None:
    record = _record(ROOT / "data", EVENT_FILE, DEMON_EVENT_KEY)
    assert record["action_aliases"] == DEMON_ACTION_VALUES == {
        "战斗": "battle",
        "运输": "transport",
        "维修": "maintenance",
    }
    assert set(DEMON_ACTION_VALUES.values()) <= set(
        record["public_event"]["contributions"]
    )


def test_sect_record_matches_the_module_constants() -> None:
    record = sect_rules_record()
    assert record["create_cost"] == sect_rules.SECT_CREATE_COST == 1000
    assert record["max_members"] == sect_rules.SECT_MAX_MEMBERS == 20
    assert record["warehouse_capacity"] == sect_rules.SECT_WAREHOUSE_CAPACITY == 50
    assert (
        record["application_ttl_seconds"]
        == sect_rules.SECT_APPLICATION_TTL_SECONDS
        == 86400
    )
    assert (
        record["join_cooldown_seconds"] == sect_rules.SECT_JOIN_COOLDOWN_SECONDS == 86400
    )
    assert sect_rules.SECT_DEFINITION.max_members == 20
    assert sect_rules.SECT_DEFINITION.create_cost == 1000
    assert sect_rules.SECT_DEFINITION.warehouse_capacity == 50
    assert sect_rules.SECT_DEFINITION.application_ttl_seconds == 86400


@pytest.mark.parametrize(
    "relative, key, mutate, message",
    [
        (SEASON_FILE, THREE_REALMS_SEASON_KEY, lambda r: r.pop("name"), "requires a name"),
        (SEASON_FILE, THREE_REALMS_SEASON_KEY, lambda r: r.update({"status": "locked"}), "not open"),
        (SEASON_FILE, THREE_REALMS_SEASON_KEY, lambda r: r.update({"duration_days": 0}), "positive integer"),
        (SEASON_FILE, THREE_REALMS_SEASON_KEY, lambda r: r.update({"anchor": "not-a-date"}), "anchor is invalid"),
        (SEASON_FILE, THREE_REALMS_SEASON_KEY, lambda r: r.update({"anchor": "2025-01-01"}), "timezone-aware"),
        (SEASON_FILE, THREE_REALMS_SEASON_KEY, lambda r: r.update({"boards": {}}), "non-empty object"),
        (SEASON_FILE, FINAL_HEAVEN_SEASON_KEY, lambda r: r["boards"]["ascension"].pop("label"), "requires a label"),
        (SEASON_FILE, FINAL_HEAVEN_SEASON_KEY, lambda r: r["boards"]["dao"].update({"score": 0}), "positive integer"),
        (SEASON_FILE, FINAL_HEAVEN_SEASON_KEY, lambda r: r["boards"]["dao"].update({"title_key": " "}), "invalid title_key"),
        (EVENT_FILE, DEMON_EVENT_KEY, lambda r: r.update({"action_aliases": {}}), "non-empty object"),
        (EVENT_FILE, DEMON_EVENT_KEY, lambda r: r["action_aliases"].update({"战斗": "nope"}), "unknown action"),
        (SOCIAL_FILE, SECT_KEY, lambda r: r.update({"create_cost": 0}), "positive integer"),
        (SOCIAL_FILE, SECT_KEY, lambda r: r.update({"max_members": -1}), "positive integer"),
    ],
)
def test_content_rejects_invalid_contract(
    tmp_path: Path, relative: Path, key: str, mutate, message: str
) -> None:
    data_dir = _copy_data(tmp_path)
    record = _record(data_dir, relative, key)
    mutate(record)
    _write_record(data_dir, relative, record)
    bundle = ContentBundle.load(data_dir)
    with pytest.raises(ContentError, match=message):
        if relative == SEASON_FILE:
            season_record(key, bundle)
        elif relative == EVENT_FILE:
            demon_action_values(bundle)
        else:
            sect_rules_record(bundle)


def test_missing_records_raise_content_error(tmp_path: Path) -> None:
    data_dir = _copy_data(tmp_path)
    document = json.loads((data_dir / SEASON_FILE).read_text(encoding="utf-8"))
    document["records"] = [
        row for row in document["records"] if row["key"] != THREE_REALMS_SEASON_KEY
    ]
    (data_dir / SEASON_FILE).write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    bundle = ContentBundle.load(data_dir)
    with pytest.raises(ContentError, match="missing season content"):
        season_record(THREE_REALMS_SEASON_KEY, bundle)
