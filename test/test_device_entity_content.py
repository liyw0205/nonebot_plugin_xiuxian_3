from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError
from nonebot_plugin_xiuxian_3.xiuxian.device.entity_content import (
    entity_alias_map,
    entity_definitions,
    resolve_entity_key,
)
from nonebot_plugin_xiuxian_3.xiuxian.device.entity_rules import (
    device_definition,
    device_definitions,
    device_missing_requirements,
    durability_after,
    plan_actions,
    repair_steps_missing,
)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
ENTITY_FILE = Path("战斗/实体.json")
KEY = "device.scout_doll"


def _copy_data(tmp_path: Path) -> Path:
    target = tmp_path / "data"
    shutil.copytree(DATA, target)
    return target


def _document(root: Path) -> dict:
    return json.loads((root / ENTITY_FILE).read_text(encoding="utf-8"))


def _write(root: Path, document: dict) -> None:
    (root / ENTITY_FILE).write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _record(document: dict) -> dict:
    return next(row for row in document["records"] if row["key"] == KEY)


def test_shipped_device_content_matches_the_frozen_foundation_row() -> None:
    bundle = ContentBundle.load(DATA)
    assert ENTITY_FILE.as_posix() in bundle.manifest["files"]

    raw = bundle.require("entity", KEY)
    assert raw["status"] == "active"
    assert raw["entity_type"] == "summoned_device"
    assert raw["owner_path_key"] == "device"

    definition = device_definition(bundle, KEY)
    # Foundation v0.1: one device, attack 50% of the owner, three rounds.
    assert definition.max_instances == 1
    assert definition.attack_multiplier_bp == 5000
    assert definition.duration_rounds == 3
    assert definition.max_actions_per_battle == 3
    assert definition.required_realm == "qi_sensing"
    assert definition.min_layer == 1
    assert definition.assembly_spirit_stones == 120
    assert definition.assembly_items == {"item.mat.wood": 2, "item.ore.ironstone": 1}
    assert definition.maintenance_spirit_stones == 20
    assert definition.maintenance_items == {"item.mat.wood": 1}
    assert definition.max_durability_bp == 10000
    assert definition.loss_per_action_bp == 400
    assert definition.repair_bp_per_material == 2500
    assert definition.codex_entry_key == "codex.path.device"


def test_every_reference_in_the_device_contract_resolves() -> None:
    bundle = ContentBundle.load(DATA)
    definition = device_definition(bundle, KEY)
    assert bundle.get("path", definition.owner_path_key, include_locked=False) is not None
    assert bundle.get("realm", definition.required_realm, include_locked=False) is not None
    assert bundle.get("codex_entry", definition.codex_entry_key, include_locked=False) is not None
    for item_key in (*definition.assembly_items, *definition.maintenance_items):
        assert bundle.get("item", item_key, include_locked=False) is not None


def test_aliases_resolve_to_the_stable_key() -> None:
    bundle = ContentBundle.load(DATA)
    aliases = entity_alias_map(bundle)
    assert aliases["侦查机关"] == KEY
    assert aliases["侦查傀儡"] == KEY
    assert resolve_entity_key("机关傀儡", bundle) == KEY
    assert resolve_entity_key(KEY, bundle) == KEY
    assert resolve_entity_key("不存在的机关", bundle) is None


def test_device_rules_follow_the_frozen_numbers() -> None:
    bundle = ContentBundle.load(DATA)
    definition = device_definition(bundle, KEY)

    assert device_missing_requirements(
        definition=definition, path_key="device", realm_key="qi_sensing", realm_layer=1
    ) == []
    assert "需device道途" in device_missing_requirements(
        definition=definition, path_key="spell", realm_key="qi_sensing", realm_layer=1
    )
    assert "境界要求" in device_missing_requirements(
        definition=definition, path_key="device", realm_key="mortal", realm_layer=0
    )

    # Three strikes cost 1200 bp and never drop below zero.
    assert durability_after(current_bp=10000, actions=3, definition=definition) == 8800
    assert durability_after(current_bp=800, actions=3, definition=definition) == 0
    assert repair_steps_missing(current_bp=8800, definition=definition) == 1
    assert repair_steps_missing(current_bp=0, definition=definition) == 4
    assert repair_steps_missing(current_bp=10000, definition=definition) == 0

    assert plan_actions(
        duration_rounds=3, max_actions_per_battle=3, used_actions=0, round_no=1
    )
    assert not plan_actions(
        duration_rounds=3, max_actions_per_battle=3, used_actions=0, round_no=4
    )
    assert not plan_actions(
        duration_rounds=3, max_actions_per_battle=3, used_actions=3, round_no=2
    )


@pytest.mark.parametrize(
    "mutate, expected",
    [
        (lambda row: row.update(entity_type="summoned_beast"), "entity_type"),
        (lambda row: row.update(owner_path_key="nope"), "unknown path"),
        (lambda row: row.update(required_realm="nope"), "unknown realm"),
        (lambda row: row.update(min_layer=99), "min_layer is outside realm"),
        (lambda row: row.update(max_instances=0), "max_instances"),
        (lambda row: row.pop("assembly"), "missing fields"),
        (
            lambda row: row["assembly"]["items"].update({"item.nope": 1}),
            "unknown item",
        ),
        (
            lambda row: row["assembly"].update({"spirit_stones": 0}),
            "must be positive",
        ),
        (
            lambda row: row["durability"].update({"max_bp": 20000}),
            "cannot exceed 10000",
        ),
        (
            lambda row: row["durability"].update({"loss_per_action_bp": 20000}),
            "loss exceeds max_bp",
        ),
        (
            lambda row: row["combat"].update({"duration_rounds": 21}),
            "duration exceeds",
        ),
        (
            lambda row: row["combat"].update(
                {"duration_rounds": 3, "max_actions_per_battle": 4}
            ),
            "action cap exceeds its duration",
        ),
        (
            lambda row: row["combat"].update({"attack_multiplier_bp": 0}),
            "must be a positive integer",
        ),
        (lambda row: row.update(codex_entry_key="codex.nope"), "unknown codex entry"),
        (lambda row: row.update(aliases=["   "]), "malformed alias"),
        (lambda row: row.update(key="doll.scout"), "must use the device. prefix"),
    ],
)
def test_malformed_device_content_is_rejected(
    tmp_path: Path, mutate, expected: str
) -> None:
    root = _copy_data(tmp_path)
    document = _document(root)
    mutate(_record(document))
    _write(root, document)

    bundle = ContentBundle.load(root)
    with pytest.raises(ContentError) as excinfo:
        entity_definitions(bundle)
    assert expected in str(excinfo.value)


def test_duplicate_alias_across_records_is_rejected(tmp_path: Path) -> None:
    root = _copy_data(tmp_path)
    document = _document(root)
    duplicate = json.loads(json.dumps(_record(document)))
    duplicate.update(
        key="device.second_doll",
        name="第二机关",
        aliases=["侦查傀儡"],
    )
    document["records"].append(duplicate)
    _write(root, document)

    bundle = ContentBundle.load(root)
    with pytest.raises(ContentError) as excinfo:
        entity_definitions(bundle)
    assert "is shared by" in str(excinfo.value)


def test_definition_lookup_rejects_unknown_keys() -> None:
    bundle = ContentBundle.load(DATA)
    assert set(device_definitions(bundle)) == {KEY}
    with pytest.raises(KeyError):
        device_definition(bundle, "device.nope")