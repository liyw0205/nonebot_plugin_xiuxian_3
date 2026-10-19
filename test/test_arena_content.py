from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError
from nonebot_plugin_xiuxian_3.xiuxian.specials import (
    arena_rules,
    team_arena_rules,
    three_realms_arena_rules,
)
from nonebot_plugin_xiuxian_3.xiuxian.specials.arena_content import (
    arena_defaults,
    spar_record,
    team_record,
    three_realms_record,
)

ROOT = Path(__file__).resolve().parents[1]
ARENA_FILE = Path("特殊/竞技场.json")


def _copy_data(tmp_path: Path) -> Path:
    data_dir = tmp_path / "data"
    shutil.copytree(
        ROOT / "data", data_dir, ignore=shutil.ignore_patterns("*.sqlite3*", "*.db*")
    )
    return data_dir


def _mutate(data_dir: Path, key: str, mutate) -> None:
    document = json.loads((data_dir / ARENA_FILE).read_text(encoding="utf-8"))
    for record in document["records"]:
        if record["key"] == key:
            mutate(record)
            break
    else:
        raise AssertionError(f"record {key} not found")
    (data_dir / ARENA_FILE).write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def test_manifest_registers_the_arena_file() -> None:
    manifest = json.loads((ROOT / "data/内容清单.json").read_text(encoding="utf-8"))
    assert ARENA_FILE.as_posix() in manifest["files"]


def test_spar_record_matches_the_shipped_contract() -> None:
    record = spar_record()
    assert record["mode_key"] == arena_rules.ARENA_MODE_KEY == "arena.spar"
    assert record["rank_mode_key"] == arena_rules.ARENA_RANK_MODE_KEY == "arena.rank"
    assert record["practice_mode_key"] == arena_rules.ARENA_PRACTICE_MODE_KEY == "arena.practice"
    assert record["snapshot_valid_days"] == arena_rules.SNAPSHOT_VALID_DAYS == 7
    assert record["match_delay_seconds"] == arena_rules.SNAPSHOT_MATCH_DELAY_SECONDS == 1800
    assert record["daily_challenge_limit"] == arena_rules.DAILY_CHALLENGE_LIMIT == 5
    assert record["weekly_rank_limit"] == arena_rules.WEEKLY_RANK_LIMIT == 20
    assert record["daily_practice_limit"] == arena_rules.DAILY_PRACTICE_LIMIT == 3
    assert record["daily_counted_opponent_limit"] == arena_rules.DAILY_COUNTED_OPPONENT_LIMIT == 2
    assert record["max_rounds"] == arena_rules.MAX_ROUNDS == 15
    assert record["win_rating_delta"] == arena_rules.WIN_RATING_DELTA == 25
    assert record["loss_rating_delta"] == arena_rules.LOSS_RATING_DELTA == -10
    assert record["draw_rating_delta"] == arena_rules.DRAW_RATING_DELTA == 5


def test_rating_bands_match_the_shipped_contract() -> None:
    assert arena_rules.RATING_BANDS == (500, 1000, 1500)
    assert arena_defaults()["rating_bands"] == (500, 1000, 1500)
    assert arena_rules.rating_band(0) == 0
    assert arena_rules.rating_band(499) == 0
    assert arena_rules.rating_band(500) == 1
    assert arena_rules.rating_band(999) == 1
    assert arena_rules.rating_band(1000) == 2
    assert arena_rules.rating_band(1499) == 2
    assert arena_rules.rating_band(1500) == 3
    assert arena_rules.rating_band(99999) == 3
    assert arena_rules.compatible_rating(400, 900) is True
    assert arena_rules.compatible_rating(0, 1500) is False


def test_rating_delta_semantics_are_unchanged() -> None:
    assert arena_rules.rating_delta("draw", challenger=True) == 5
    assert arena_rules.rating_delta("draw", challenger=False) == 5
    assert arena_rules.rating_delta("challenger_won", challenger=True) == 25
    assert arena_rules.rating_delta("challenger_won", challenger=False) == -10
    assert arena_rules.rating_delta("defender_won", challenger=True) == -10
    assert arena_rules.rating_delta("defender_won", challenger=False) == 25


def test_mode_attempt_limits_are_unchanged() -> None:
    assert arena_rules.mode_attempt_limit("arena.rank") == 20
    assert arena_rules.mode_attempt_limit("arena.practice") == 3
    assert arena_rules.mode_attempt_limit("arena.spar") == 5
    assert arena_rules.mode_attempt_limit("anything-else") == 5


def test_team_record_matches_the_shipped_contract() -> None:
    record = team_record()
    assert record["mode_key"] == team_arena_rules.TEAM_ARENA_MODE_KEY == "arena.team"
    assert record["min_team_size"] == team_arena_rules.MIN_TEAM_SIZE == 2
    assert record["max_team_size"] == team_arena_rules.MAX_TEAM_SIZE == 3
    assert record["snapshot_valid_days"] == team_arena_rules.TEAM_SNAPSHOT_VALID_DAYS == 7
    assert record["match_delay_seconds"] == team_arena_rules.TEAM_SNAPSHOT_MATCH_DELAY_SECONDS == 1800
    assert record["daily_challenge_limit"] == team_arena_rules.TEAM_DAILY_CHALLENGE_LIMIT == 3
    assert record["win_rating_delta"] == team_arena_rules.TEAM_WIN_RATING_DELTA == 20
    assert record["loss_rating_delta"] == team_arena_rules.TEAM_LOSS_RATING_DELTA == -8


def test_three_realms_record_matches_the_shipped_contract() -> None:
    record = three_realms_record()
    assert record["mode_key"] == three_realms_arena_rules.THREE_REALMS_ARENA_MODE_KEY == "arena.three_realms"
    assert record["required_realm"] == three_realms_arena_rules.THREE_REALMS_ARENA_MIN_REALM == "nascent_soul"
    assert record["required_layer"] == three_realms_arena_rules.THREE_REALMS_ARENA_MIN_LAYER == 1
    assert record["permit_key"] == three_realms_arena_rules.THREE_REALMS_ARENA_PERMIT_KEY == "item.permit.three_realms_arena"
    assert record["factions"] == three_realms_arena_rules.THREE_REALMS == ("xuantian", "demon", "beast")


@pytest.mark.parametrize(
    "key, mutate, message",
    [
        ("arena.defaults", lambda r: r.update({"status": "locked"}), "missing arena_rule content"),
        ("arena.defaults", lambda r: r.pop("desc"), "requires a desc"),
        ("arena.defaults", lambda r: r.update({"rating_bands": []}), "non-empty list"),
        ("arena.defaults", lambda r: r.update({"rating_bands": [1000, 500]}), "strictly ascending"),
        ("arena.defaults", lambda r: r.update({"rating_bands": [500, 500]}), "strictly ascending"),
        ("arena.defaults", lambda r: r.update({"rating_bands": [0]}), "positive integer"),
        ("arena.defaults", lambda r: r.update({"factions": ["abyss"]}), "unsupported faction"),
        ("arena.spar", lambda r: r.update({"status": "locked"}), "missing arena_rule content"),
        ("arena.spar", lambda r: r.update({"max_rounds": 0}), "positive integer"),
        ("arena.spar", lambda r: r.update({"daily_challenge_limit": "5"}), "positive integer"),
        ("arena.spar", lambda r: r.update({"win_rating_delta": 0}), "positive integer"),
        ("arena.spar", lambda r: r.update({"loss_rating_delta": "x"}), "must be an integer"),
        ("arena.spar", lambda r: r.pop("rank_mode_key"), "rank_mode_key is invalid"),
        ("arena.team", lambda r: r.update({"min_team_size": 4, "max_team_size": 3}), "max_team_size is below min_team_size"),
        ("arena.team", lambda r: r.update({"min_team_size": 0}), "positive integer"),
        ("arena.team", lambda r: r.update({"daily_challenge_limit": 0}), "positive integer"),
        ("arena.three_realms", lambda r: r.update({"required_realm": "not_a_realm"}), "unknown realm"),
        ("arena.three_realms", lambda r: r.update({"required_layer": 0}), "positive integer"),
        ("arena.three_realms", lambda r: r.update({"permit_key": ""}), "permit_key is invalid"),
        ("arena.three_realms", lambda r: r.update({"factions": ["abyss"]}), "unsupported faction"),
    ],
)
def test_content_rejects_invalid_contracts(tmp_path: Path, key: str, mutate, message: str) -> None:
    data_dir = _copy_data(tmp_path)
    _mutate(data_dir, key, mutate)
    bundle = ContentBundle.load(data_dir)
    if key == "arena.defaults":
        with pytest.raises(ContentError, match=message):
            arena_defaults(bundle)
    elif key == "arena.spar":
        with pytest.raises(ContentError, match=message):
            spar_record(bundle)
    elif key == "arena.team":
        with pytest.raises(ContentError, match=message):
            team_record(bundle)
    else:
        with pytest.raises(ContentError, match=message):
            three_realms_record(bundle)
