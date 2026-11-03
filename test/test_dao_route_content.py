from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError
from nonebot_plugin_xiuxian_3.xiuxian.social.dao_route_content import (
    dao_route_alias_map,
    dao_route_defaults,
    dao_route_options,
    resolve_dao_route,
)
from nonebot_plugin_xiuxian_3.xiuxian.social.dao_route_rules import (
    cycle_bounds,
    dao_route_definition,
    dao_route_option,
    dao_route_option_list,
    lock_active,
    majority_route,
    resolve_settlement,
    vote_missing_requirements,
)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
ROUTE_FILE = Path("社交/道统路线.json")
DEFAULTS = "route.dao_settlement.defaults"
GUARD = "route.dao_settlement.guard_world"
ASCEND = "route.dao_settlement.ascend"
REMAIN = "route.dao_settlement.remain"


def _copy_data(tmp_path: Path) -> Path:
    target = tmp_path / "data"
    shutil.copytree(DATA, target)
    return target


def _document(root: Path) -> dict:
    return json.loads((root / ROUTE_FILE).read_text(encoding="utf-8"))


def _write(root: Path, document: dict) -> None:
    (root / ROUTE_FILE).write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _record(document: dict, key: str) -> dict:
    return next(row for row in document["records"] if row["key"] == key)


def test_shipped_route_content_matches_the_frozen_social_row() -> None:
    bundle = ContentBundle.load(DATA)
    assert ROUTE_FILE.as_posix() in bundle.manifest["files"]

    defaults = dao_route_defaults(bundle)
    # social v0.6: sect level 6, three 合道 voters, 1000 sect merit, 7-day lock.
    assert defaults["required_sect_level"] == 6
    assert defaults["required_sect_merit"] == 1000
    assert defaults["required_voters"] == 3
    assert defaults["required_realm"] == "dao_union"
    assert defaults["required_layer"] == 1
    assert defaults["vote_period_days"] == 7
    assert defaults["lock_days"] == 7
    assert defaults["allow_tie_carryover"] is True

    options = dao_route_options(bundle)
    assert set(options) == {GUARD, ASCEND, REMAIN}
    assert options[GUARD]["bonus_key"] == "defense_event_bonus_bp"
    assert options[GUARD]["bonus_bp"] == 1000
    assert options[ASCEND]["bonus_key"] == "dao_fruit_trial_bonus_bp"
    assert options[ASCEND]["bonus_bp"] == 1000
    assert options[REMAIN]["bonus_key"] == "hall_construction_bonus_bp"
    assert options[REMAIN]["bonus_bp"] == 1500


def test_aliases_resolve_to_stable_keys() -> None:
    bundle = ContentBundle.load(DATA)
    aliases = dao_route_alias_map(bundle)
    assert aliases["守界"] == GUARD
    assert aliases["飞升路"] == ASCEND
    assert aliases["留界"] == REMAIN
    assert resolve_dao_route("守界路", bundle) == GUARD
    assert resolve_dao_route(REMAIN, bundle) == REMAIN
    assert resolve_dao_route("不存在的道统", bundle) is None


def test_cycle_bounds_wrap_utc_iso_weeks() -> None:
    from datetime import datetime, timezone

    cycle_id, starts_at, ends_at = cycle_bounds(
        datetime(2026, 11, 3, 5, 0, tzinfo=timezone.utc)
    )
    assert cycle_id == "dao_route:2026-W45"
    assert starts_at.isoformat() == "2026-11-02T00:00:00+00:00"  # Monday
    assert ends_at.isoformat() == "2026-11-09T00:00:00+00:00"

    # Sunday 23:59 still belongs to the same cycle.
    same, _, _ = cycle_bounds(datetime(2026, 11, 8, 23, 59, tzinfo=timezone.utc))
    assert same == cycle_id


def test_majority_and_tie_rules() -> None:
    assert majority_route({GUARD: 2, REMAIN: 1}) == GUARD
    assert majority_route({GUARD: 1, REMAIN: 1}) is None
    assert majority_route({}) is None

    bundle = ContentBundle.load(DATA)
    definition = dao_route_definition(bundle)
    assert resolve_settlement(
        definition=definition, counts={GUARD: 2, REMAIN: 1}, previous_route_key=None
    ) == (GUARD, False)
    # A tie carries last week's route.
    assert resolve_settlement(
        definition=definition, counts={GUARD: 1, REMAIN: 1}, previous_route_key=ASCEND
    ) == (ASCEND, True)
    # A tie with nothing to carry leaves the council undecided.
    assert resolve_settlement(
        definition=definition, counts={GUARD: 1, REMAIN: 1}, previous_route_key=None
    ) == (None, True)


def test_voter_requirements_and_lock_window() -> None:
    from datetime import datetime, timedelta, timezone

    bundle = ContentBundle.load(DATA)
    definition = dao_route_definition(bundle)

    assert vote_missing_requirements(
        definition=definition,
        realm_key="dao_union",
        realm_layer=1,
        sect_id="sect.a",
        sect_level=6,
        sect_status="active",
    ) == []
    missing = vote_missing_requirements(
        definition=definition,
        realm_key="nascent_soul",
        realm_layer=9,
        sect_id=None,
        sect_level=0,
        sect_status="",
    )
    assert "宗门成员" in missing and "合道境界" in missing
    level_missing = vote_missing_requirements(
        definition=definition,
        realm_key="dao_union",
        realm_layer=1,
        sect_id="sect.a",
        sect_level=5,
        sect_status="active",
    )
    assert any("宗门等级" in item for item in level_missing)

    now = datetime(2026, 11, 3, 5, 0, tzinfo=timezone.utc)
    future = (now + timedelta(days=3)).isoformat()
    past = (now - timedelta(days=3)).isoformat()
    assert lock_active(locked_until=future, now=now) is True
    assert lock_active(locked_until=past, now=now) is False
    assert lock_active(locked_until=None, now=now) is False


def test_option_lookup_is_stable() -> None:
    bundle = ContentBundle.load(DATA)
    assert dao_route_option(bundle, REMAIN).bonus_bp == 1500
    assert [option.key for option in dao_route_option_list(bundle)] == [
        GUARD,
        ASCEND,
        REMAIN,
    ]
    with pytest.raises(KeyError):
        dao_route_option(bundle, "route.dao_settlement.nope")


@pytest.mark.parametrize(
    "mutate, expected",
    [
        (lambda row: row.update(required_sect_level=0), "must be a positive integer"),
        (lambda row: row.update(required_sect_merit=0), "must be a positive integer"),
        (lambda row: row.update(required_voters=0), "must be a positive integer"),
        (lambda row: row.update(required_realm="nope"), "unknown realm"),
        (lambda row: row.update(required_layer=99), "required_layer is outside realm"),
        (lambda row: row.update(lock_days=0), "must be a positive integer"),
        (lambda row: row.update(allow_tie_carryover="yes"), "must be a boolean"),
        (lambda row: row.pop("required_voters"), "missing fields"),
        (lambda row: row.update(status="locked"), "not active"),
    ],
)
def test_malformed_defaults_are_rejected(tmp_path: Path, mutate, expected: str) -> None:
    root = _copy_data(tmp_path)
    document = _document(root)
    mutate(_record(document, DEFAULTS))
    _write(root, document)

    bundle = ContentBundle.load(root)
    with pytest.raises(ContentError) as excinfo:
        dao_route_defaults(bundle)
    assert expected in str(excinfo.value)


@pytest.mark.parametrize(
    "mutate, expected",
    [
        (lambda row: row.update(bonus={"key": "nope_bp", "value_bp": 100}), "unsupported bonus key"),
        (
            lambda row: row.update(bonus={"key": "defense_event_bonus_bp", "value_bp": 9000}),
            "bonus exceeds its cap",
        ),
        (lambda row: row.update(bonus={"key": "defense_event_bonus_bp"}), "bonus is malformed"),
        (
            lambda row: row.update(bonus={"key": "defense_event_bonus_bp", "value_bp": 0}),
            "must be a positive integer",
        ),
        (lambda row: row.update(aliases=["   "]), "malformed alias"),
        (lambda row: row.update(key="route.nope"), "must use the route.dao_settlement. prefix"),
        (lambda row: row.pop("bonus"), "missing fields"),
    ],
)
def test_malformed_routes_are_rejected(tmp_path: Path, mutate, expected: str) -> None:
    root = _copy_data(tmp_path)
    document = _document(root)
    mutate(_record(document, GUARD))
    _write(root, document)

    bundle = ContentBundle.load(root)
    with pytest.raises(ContentError) as excinfo:
        dao_route_options(bundle)
    assert expected in str(excinfo.value)


def test_missing_route_option_is_rejected(tmp_path: Path) -> None:
    root = _copy_data(tmp_path)
    document = _document(root)
    document["records"] = [row for row in document["records"] if row["key"] != ASCEND]
    _write(root, document)

    bundle = ContentBundle.load(root)
    with pytest.raises(ContentError) as excinfo:
        dao_route_options(bundle)
    assert "exactly guard_world, ascend and remain" in str(excinfo.value)