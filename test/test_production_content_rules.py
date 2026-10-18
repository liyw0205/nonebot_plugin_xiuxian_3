from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError
from nonebot_plugin_xiuxian_3.xiuxian.production import endgame_rules, facility_rules
from nonebot_plugin_xiuxian_3.xiuxian.production.content_rules import (
    endgame_defaults,
    endgame_records,
    facility_defaults,
    facility_records,
)

ROOT = Path(__file__).resolve().parents[1]
FACILITY_FILE = Path("生产/设施.json")
ENDGAME_FILE = Path("生产/终局配方.json")


def _copy_data(tmp_path: Path) -> Path:
    data_dir = tmp_path / "data"
    shutil.copytree(
        ROOT / "data", data_dir, ignore=shutil.ignore_patterns("*.sqlite3*", "*.db*")
    )
    return data_dir


def _mutate(data_dir: Path, relative: Path, key: str, mutate) -> None:
    document = json.loads((data_dir / relative).read_text(encoding="utf-8"))
    for index, record in enumerate(document["records"]):
        if record["key"] == key:
            mutate(record)
            break
    else:
        raise AssertionError(f"record {key} not found in {relative}")
    (data_dir / relative).write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def test_manifest_registers_both_files() -> None:
    manifest = json.loads((ROOT / "data/内容清单.json").read_text(encoding="utf-8"))
    assert FACILITY_FILE.as_posix() in manifest["files"]
    assert ENDGAME_FILE.as_posix() in manifest["files"]


def test_facility_defaults_match_the_shipped_contract() -> None:
    defaults = facility_defaults()
    assert defaults["location_key"] == facility_rules.FACILITY_LOCATION == "cave.mist_grotto_2"
    assert defaults["maintenance_fee"] == facility_rules.FACILITY_MAINTENANCE_FEE == 100
    assert defaults["duration_bonus_bp"] == facility_rules.FACILITY_DURATION_BONUS_BP == 1000


def test_facility_records_match_the_shipped_contract() -> None:
    records = facility_records()
    assert [record["key"] for record in records] == [
        "facility.mist_field.1",
        "facility.mist_field.2",
        "facility.mist_field.3",
        "facility.mist_field.4",
        "facility.alchemy_room.1",
        "facility.artifice_table.1",
        "facility.array_base.1",
    ]
    assert [record["name"] for record in records] == ["灵田1", "灵田2", "灵田3", "灵田4", "炼丹房", "炼器台", "阵基"]
    assert [record["facility_kind"] for record in records] == ["field", "field", "field", "field", "alchemy", "artifice", "array"]
    assert [record["slot_index"] for record in records] == [1, 2, 3, 4, 1, 1, 1]
    assert facility_rules.FACILITY_ALIASES == {
        "灵田1": "facility.mist_field.1",
        "灵田2": "facility.mist_field.2",
        "灵田3": "facility.mist_field.3",
        "灵田4": "facility.mist_field.4",
        "灵田": "facility.mist_field.1",
        "炼丹房": "facility.alchemy_room.1",
        "炼丹": "facility.alchemy_room.1",
        "炼器台": "facility.artifice_table.1",
        "炼器": "facility.artifice_table.1",
        "阵基": "facility.array_base.1",
        "布阵": "facility.array_base.1",
    }
    assert facility_rules.resolve_facility("炼丹").slot_key == "facility.alchemy_room.1"
    assert facility_rules.resolve_facility("facility.array_base.1").name == "阵基"
    assert facility_rules.facility_for_kind("field") == facility_rules.FACILITY_DEFINITIONS[:4]
    with pytest.raises(ValueError, match="facility does not exist"):
        facility_rules.resolve_facility("不存在")


def test_endgame_defaults_match_the_shipped_contract() -> None:
    defaults = endgame_defaults()
    assert defaults["success_threshold_bp"] == endgame_rules.SUCCESS_THRESHOLD_BP == 8000
    assert defaults["dao_fruit_progress_cap"] == endgame_rules.DAO_FRUIT_PROGRESS_CAP == 1300
    assert defaults["ascension_certificate_key"] == endgame_rules.ASCENSION_CERTIFICATE_KEY == "item.ascension_certificate"


def test_endgame_records_match_the_shipped_contract() -> None:
    recipes = endgame_rules.ENDGAME_RECIPES
    assert set(recipes) == {
        "recipe.dao.fruit_fragment",
        "recipe.tribulation.guard",
        "recipe.ascension.certificate",
    }
    fruit = recipes["recipe.dao.fruit_fragment"]
    assert fruit.duration_seconds == 1200
    assert fruit.inputs == {"item.dao_fruit_fragment": 10, "item.soul_crystal": 5}
    assert fruit.output_progress == 100 and fruit.output_item is None
    assert fruit.required_realm == "dao_union"
    assert fruit.required_endgame_statuses == ("dao_union", "tribulation")
    assert fruit.required_location == "dao.origin_gate"
    guard = recipes["recipe.tribulation.guard"]
    assert guard.duration_seconds == 1800
    assert guard.inputs == {"item.tribulation_token": 1, "item.domain_core": 3}
    assert guard.output_item == "item.tribulation_guard"
    assert guard.required_realm == "tribulation"
    assert guard.required_endgame_statuses == ("tribulation",)
    certificate = recipes["recipe.ascension.certificate"]
    assert certificate.duration_seconds == 600 and certificate.inputs == {}
    assert certificate.output_item == "item.ascension_certificate"
    assert certificate.world_merit_cost == 1000
    assert certificate.required_progress == 800
    assert certificate.required_ascension_merit == 1000
    assert certificate.required_realm == "tribulation"
    assert certificate.required_location == "tribulation.sky_terrace"
    assert endgame_rules.RECIPE_ALIASES == {
        "recipe.dao.fruit_fragment": "recipe.dao.fruit_fragment",
        "recipe.tribulation.guard": "recipe.tribulation.guard",
        "recipe.ascension.certificate": "recipe.ascension.certificate",
        "道果碎片加工": "recipe.dao.fruit_fragment",
        "天劫保护阵": "recipe.tribulation.guard",
        "飞升凭证": "recipe.ascension.certificate",
    }
    assert endgame_rules.resolve_endgame_recipe("飞升凭证") == "recipe.ascension.certificate"
    assert endgame_rules.recipe_roll_bp("op-1") == endgame_rules.recipe_roll_bp("op-1")


@pytest.mark.parametrize(
    "relative, key, mutate, message",
    [
        (FACILITY_FILE, "facility.defaults", lambda r: r.update({"maintenance_fee": 0}), "positive integer"),
        (FACILITY_FILE, "facility.defaults", lambda r: r.update({"location_key": "cave.not_a_location"}), "unknown location"),
        (FACILITY_FILE, "facility.defaults", lambda r: r.pop("desc"), "requires a desc"),
        (FACILITY_FILE, "facility.defaults", lambda r: r.update({"status": "locked"}), "missing production_facility content"),
        (FACILITY_FILE, "facility.mist_field.1", lambda r: r.update({"facility_kind": "kitchen"}), "unsupported facility_kind"),
        (FACILITY_FILE, "facility.mist_field.1", lambda r: r.update({"slot_index": 0}), "positive integer"),
        (FACILITY_FILE, "facility.mist_field.1", lambda r: r.update({"aliases": []}), "non-empty list"),
        (FACILITY_FILE, "facility.mist_field.2", lambda r: r.update({"aliases": ["灵田"]}), "conflicts"),
        (ENDGAME_FILE, "endgame.defaults", lambda r: r.update({"success_threshold_bp": -1}), "positive integer"),
        (ENDGAME_FILE, "endgame.defaults", lambda r: r.update({"ascension_certificate_key": "item.not_an_item"}), "unknown item"),
        (ENDGAME_FILE, "recipe.dao.fruit_fragment", lambda r: r.update({"duration_seconds": 0}), "positive integer"),
        (ENDGAME_FILE, "recipe.dao.fruit_fragment", lambda r: r.update({"inputs": {"item.not_an_item": 1}}), "unknown item"),
        (ENDGAME_FILE, "recipe.dao.fruit_fragment", lambda r: r.update({"inputs": {"item.soul_crystal": 0}}), "positive integer"),
        (ENDGAME_FILE, "recipe.dao.fruit_fragment", lambda r: r.update({"required_realm": "not_a_realm"}), "unknown realm"),
        (ENDGAME_FILE, "recipe.dao.fruit_fragment", lambda r: r.update({"required_endgame_statuses": ["ascended"]}), "unsupported endgame status"),
        (ENDGAME_FILE, "recipe.dao.fruit_fragment", lambda r: r.update({"required_endgame_statuses": []}), "non-empty list"),
        (ENDGAME_FILE, "recipe.ascension.certificate", lambda r: r.update({"required_location": "cave.not_a_location"}), "unknown location"),
        (ENDGAME_FILE, "recipe.ascension.certificate", lambda r: r.update({"output_item": "item.not_an_item"}), "unknown item"),
        (ENDGAME_FILE, "recipe.tribulation.guard", lambda r: r.update({"aliases": ["飞升凭证"]}), "conflicts"),
    ],
)
def test_content_rejects_invalid_contracts(tmp_path: Path, relative: Path, key: str, mutate, message: str) -> None:
    data_dir = _copy_data(tmp_path)
    _mutate(data_dir, relative, key, mutate)
    bundle = ContentBundle.load(data_dir)
    if relative == FACILITY_FILE:
        if key == "facility.defaults":
            with pytest.raises(ContentError, match=message):
                facility_defaults(bundle)
        else:
            with pytest.raises(ContentError, match=message):
                facility_records(bundle)
    else:
        if key == "endgame.defaults":
            with pytest.raises(ContentError, match=message):
                endgame_defaults(bundle)
        else:
            with pytest.raises(ContentError, match=message):
                endgame_records(bundle)
