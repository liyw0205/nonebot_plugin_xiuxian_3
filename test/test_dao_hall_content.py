from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError
from nonebot_plugin_xiuxian_3.xiuxian.social.dao_hall_content import (
    dao_hall_alias_map,
    dao_hall_defaults,
    dao_hall_projects,
    resolve_dao_hall_project,
)
from nonebot_plugin_xiuxian_3.xiuxian.social.dao_hall_rules import (
    can_hold_core_seat,
    dao_hall_definition,
    dao_hall_project,
    dao_hall_project_list,
    effective_core_capacity,
    founding_missing_requirements,
    maintenance_cost,
    rebuild_hours,
)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
HALL_FILE = Path("社交/道统据点.json")
DEFAULTS = "hall.dao_settlement.defaults"
MAIN_HALL = "project.dao_hall.main_hall"
LECTURE = "project.dao_hall.lecture_hall"
WARD = "project.dao_hall.ward_array"


def _copy_data(tmp_path: Path) -> Path:
    target = tmp_path / "data"
    shutil.copytree(DATA, target)
    return target


def _document(root: Path) -> dict:
    return json.loads((root / HALL_FILE).read_text(encoding="utf-8"))


def _write(root: Path, document: dict) -> None:
    (root / HALL_FILE).write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _record(document: dict, key: str) -> dict:
    return next(row for row in document["records"] if row["key"] == key)


def test_shipped_hall_content_matches_the_frozen_social_row() -> None:
    bundle = ContentBundle.load(DATA)
    assert HALL_FILE.as_posix() in bundle.manifest["files"]

    raw = bundle.require("dao_hall", DEFAULTS)
    assert raw["status"] == "active"

    defaults = dao_hall_defaults(bundle)
    # social v0.6: remain_in_world, 2000 world merit + 5000 stones,
    # thirty core seats, weekly 5000, 72h rebuild.
    assert defaults["required_ending"] == "remain_in_world"
    assert defaults["required_world_merit"] == 2000
    assert defaults["spirit_stones"] == 5000
    assert defaults["core_capacity"] == 30
    assert defaults["maintenance_spirit_stones"] == 5000
    assert defaults["maintenance_period_days"] == 7
    assert defaults["rebuild_hours"] == 72
    assert defaults["core_required_realms"] == ("tribulation", "dao_union")


def test_every_project_reference_resolves_and_aliases_are_unique() -> None:
    bundle = ContentBundle.load(DATA)
    projects = dao_hall_projects(bundle)
    assert set(projects) == {MAIN_HALL, LECTURE, WARD}
    assert projects[MAIN_HALL]["required_project_keys"] == ()
    assert projects[LECTURE]["required_project_keys"] == (MAIN_HALL,)
    assert projects[WARD]["required_project_keys"] == (MAIN_HALL,)
    # Construction is paid in world merit only (economy v0.6).
    assert all(project["world_merit"] > 0 for project in projects.values())

    aliases = dao_hall_alias_map(bundle)
    assert aliases["正殿"] == MAIN_HALL
    assert aliases["护山大阵"] == WARD
    assert resolve_dao_hall_project("讲堂", bundle) == LECTURE
    assert resolve_dao_hall_project("不存在的建设", bundle) is None


def test_rules_apply_the_frozen_costs_capacity_and_windows() -> None:
    bundle = ContentBundle.load(DATA)
    definition = dao_hall_definition(bundle)

    assert effective_core_capacity(definition=definition, built=(), content=bundle) == 30
    assert (
        effective_core_capacity(definition=definition, built=(MAIN_HALL,), content=bundle) == 35
    )
    assert maintenance_cost(definition=definition, built=(), content=bundle) == 5000
    assert (
        maintenance_cost(definition=definition, built=(LECTURE,), content=bundle) == 4500
    )
    assert rebuild_hours(definition=definition, built=(), content=bundle) == 72
    assert rebuild_hours(definition=definition, built=(WARD,), content=bundle) == 48

    assert founding_missing_requirements(
        definition=definition,
        ending_key="remain_in_world",
        world_merit=2000,
        spirit_stones=5000,
        already_member=False,
    ) == []
    missing = founding_missing_requirements(
        definition=definition,
        ending_key="ascend",
        world_merit=1999,
        spirit_stones=4999,
        already_member=False,
    )
    assert "留界结局" in missing
    assert any("世界功勋" in item for item in missing)
    assert any("灵石" in item for item in missing)

    # Core seats: 渡劫 or a recorded remain_in_world ending only.
    assert can_hold_core_seat(
        definition=definition, realm_key="tribulation", realm_layer=1, ending_key=None
    )
    assert can_hold_core_seat(
        definition=definition, realm_key="dao_union", realm_layer=1, ending_key=None
    )
    assert can_hold_core_seat(
        definition=definition, realm_key="nascent_soul", realm_layer=9, ending_key="remain_in_world"
    )
    assert not can_hold_core_seat(
        definition=definition, realm_key="nascent_soul", realm_layer=9, ending_key=None
    )


def test_project_lookup_is_stable() -> None:
    bundle = ContentBundle.load(DATA)
    assert dao_hall_project(bundle, LECTURE).world_merit == 600
    assert [project.key for project in dao_hall_project_list(bundle)] == [
        MAIN_HALL,
        LECTURE,
        WARD,
    ]
    with pytest.raises(KeyError):
        dao_hall_project(bundle, "project.dao_hall.nope")


@pytest.mark.parametrize(
    "mutate, expected",
    [
        (lambda row: row.update(required_ending="ascend"), "unsupported ending"),
        (lambda row: row.update(required_world_merit=0), "must be a positive integer"),
        (lambda row: row.update(core_capacity=0), "must be a positive integer"),
        (lambda row: row.update(rebuild_hours=0), "must be between 1 and 720"),
        (lambda row: row.update(maintenance_period_days=-1), "must be a positive integer"),
        (lambda row: row.update(core_required_realms=["nope"]), "unknown realm"),
        (lambda row: row.update(core_required_realms=[]), "core_required_realms"),
        (lambda row: row.pop("spirit_stones"), "missing fields"),
        (lambda row: row.update(status="locked"), "not active"),
    ],
)
def test_malformed_hall_defaults_are_rejected(tmp_path: Path, mutate, expected: str) -> None:
    root = _copy_data(tmp_path)
    document = _document(root)
    mutate(_record(document, DEFAULTS))
    _write(root, document)

    bundle = ContentBundle.load(root)
    with pytest.raises(ContentError) as excinfo:
        dao_hall_defaults(bundle)
    assert expected in str(excinfo.value)


@pytest.mark.parametrize(
    "mutate, expected",
    [
        (lambda row: row.update(world_merit=0), "must be a positive integer"),
        (lambda row: row.update(effects={"unknown_effect": 5}), "unknown effects"),
        (
            lambda row: row.update(effects={"maintenance_discount_bp": 9000}),
            "must be between",
        ),
        (
            lambda row: row.update(effects={"core_capacity_bonus": 999}),
            "must be between",
        ),
        (lambda row: row.update(effects={}), "non-empty object"),
        (
            lambda row: row.update(required_project_keys=["project.dao_hall.nope"]),
            "unknown project",
        ),
        (lambda row: row.update(required_project_keys=[MAIN_HALL]), "cannot require itself"),
        (lambda row: row.pop("world_merit"), "missing fields"),
        (lambda row: row.update(key="project.nope"), "must use the project.dao_hall. prefix"),
    ],
)
def test_malformed_projects_are_rejected(tmp_path: Path, mutate, expected: str) -> None:
    root = _copy_data(tmp_path)
    document = _document(root)
    mutate(_record(document, MAIN_HALL))
    _write(root, document)

    bundle = ContentBundle.load(root)
    with pytest.raises(ContentError) as excinfo:
        dao_hall_projects(bundle)
    assert expected in str(excinfo.value)


def test_circular_project_prerequisites_are_rejected(tmp_path: Path) -> None:
    root = _copy_data(tmp_path)
    document = _document(root)
    _record(document, MAIN_HALL)["required_project_keys"] = [LECTURE]
    _write(root, document)

    bundle = ContentBundle.load(root)
    with pytest.raises(ContentError) as excinfo:
        dao_hall_projects(bundle)
    assert "circular prerequisite" in str(excinfo.value)