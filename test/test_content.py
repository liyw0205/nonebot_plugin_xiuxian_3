from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError
from nonebot_plugin_xiuxian_3.xiuxian.player.rules import realm_display_name
from nonebot_plugin_xiuxian_3.xiuxian.progression.rules import _content_thresholds, formal_realms, next_layer_threshold


def test_runtime_content_uses_normalized_records() -> None:
    bundle = ContentBundle.load(Path(__file__).parents[1] / "data")

    sword = bundle.require("item", "item.weapon.wood_sword")
    assert sword["item_type"] == "weapon"
    assert sword["status"] == "active"
    assert bundle.require("realm", "foundation")["name"] == "筑基"
    assert bundle.get("item", "item.pill.foundation_guard", include_locked=False)
    assert bundle.label("realm", "soul_transformation") == "化神"
    assert bundle.label("item", "item.weapon.cloud_sword") == "云纹剑"
    assert bundle.require("entity", "device.scout_doll")["status"] == "locked"
    assert next_layer_threshold("soul_transformation", 1) == 28000
    assert realm_display_name("soul_transformation", 1) == "化神境一层"
    constitution = bundle.require("constitution", "constitution.iron_bone")
    assert constitution["effect"] == {"type": "max_hp_bp", "value": 300}
    assert len(bundle.list("constitution", include_locked=False)) == 5
    talents = bundle.list("talent", include_locked=False)
    assert len(talents) == 30
    assert [row["cost_points"] for row in talents if row["tree_key"] == "body"] == [0, 1, 2, 3, 5]
    assert all(row["effect"]["value"] in {100, 150, 200, 250, 300} for row in talents)
    manuals = [row for row in bundle.list("item", include_locked=False) if row.get("item_type") == "manual"]
    weapons = [row for row in bundle.list("item", include_locked=False) if row.get("item_type") == "weapon"]
    armor = [row for row in bundle.list("item", include_locked=False) if row.get("item_type") == "armor"]
    accessories = [row for row in bundle.list("item", include_locked=False) if row.get("item_type") == "accessory"]
    assert len(manuals) >= 18
    for equipment in (weapons, armor):
        assert len(equipment) >= 447
        assert all(
            sum(row.get("quality") == quality for row in equipment) >= 9
            for quality in ("common", "uncommon", "rare", "heaven", "mythic")
        )
        path_items = [row for row in equipment if row.get("path_key") is not None]
        assert len(path_items) >= 432
        assert {row["path_key"] for row in path_items} == {
            "body", "spell", "device", "demonic", "beast", "support",
        }
    assert len(accessories) >= 54
    path_keys = {row["path_key"] for row in accessories}
    assert path_keys == {"body", "spell", "device", "demonic", "beast", "support"}
    for path_key in path_keys:
        path_items = [row for row in accessories if row["path_key"] == path_key]
        assert len(path_items) >= 9
        assert {
            row["requirements"][0]["realm_key"] for row in path_items
        } >= {
            "qi_sensing", "qi_gathering", "foundation", "golden_core", "nascent_soul",
            "soul_transformation", "void_refining", "dao_union", "tribulation",
        }


def test_content_files_keep_business_fields_only() -> None:
    data_root = Path(__file__).parents[1] / "data"
    forbidden = {"generated_at", "schema_version"}
    for path in data_root.rglob("*.json"):
        document = json.loads(path.read_text(encoding="utf-8"))
        assert forbidden.isdisjoint(document), path
        for row in document.get("records", []):
            assert forbidden.isdisjoint(row), f"{path}:{row.get('key')}"


def test_named_core_records_require_player_descriptions() -> None:
    data_root = Path(__file__).parents[1] / "data"
    for path in data_root.rglob("*.json"):
        document = json.loads(path.read_text(encoding="utf-8"))
        for row in document.get("records", []):
            if row.get("name"):
                assert isinstance(row.get("desc"), str) and row["desc"].strip(), (
                    f"{path}:{row.get('key')} requires player-facing desc"
                )


def test_content_manifest_only_registers_content_files() -> None:
    bundle = ContentBundle.load(Path(__file__).parents[1] / "data")
    assert set(bundle.manifest) == {"schema", "status", "files"}


def test_runtime_content_is_optional_for_isolated_data_dirs(tmp_path: Path) -> None:
    assert ContentBundle.load_optional(tmp_path) is None


def test_runtime_content_rejects_path_escape(tmp_path: Path) -> None:
    (tmp_path / "内容清单.json").write_text(
        '{"schema":"xiuxian.content","files":["../outside.json"]}',
        encoding="utf-8",
    )
    with pytest.raises(ContentError, match="escapes data directory"):
        ContentBundle.load(tmp_path)


def test_runtime_content_rejects_duplicate_json_members(tmp_path: Path) -> None:
    (tmp_path / "records.json").write_text(
        '{"schema":"xiuxian.content","schema":"xiuxian.content",'
        '"kind":"realm","records":[]}',
        encoding="utf-8",
    )
    (tmp_path / "内容清单.json").write_text(
        '{"schema":"xiuxian.content","status":"active","files":["records.json"]}',
        encoding="utf-8",
    )
    with pytest.raises(ContentError, match="duplicate JSON object key: schema"):
        ContentBundle.load(tmp_path)


def test_active_realm_with_incomplete_thresholds_fails_instead_of_falling_back(tmp_path: Path) -> None:
    (tmp_path / "realms.json").write_text(
        json.dumps(
            {
                "schema": "xiuxian.content",
                "kind": "realm",
                "records": [
                    {
                        "key": "test_realm",
                        "status": "active",
                        "layer_min": 1,
                        "layer_max": 2,
                        "layer_thresholds": {"1": 0},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "内容清单.json").write_text(
        json.dumps({"schema": "xiuxian.content", "status": "active", "files": ["realms.json"]}),
        encoding="utf-8",
    )

    with pytest.raises(ContentError, match="must configure thresholds"):
        _content_thresholds(ContentBundle.load(tmp_path))


def test_progression_rules_read_thresholds_from_runtime_content(tmp_path: Path) -> None:
    source = Path(__file__).parents[1] / "data"
    data_root = tmp_path / "data"
    shutil.copytree(source, data_root)
    realm_path = data_root / "境界" / "境界.json"
    document = json.loads(realm_path.read_text(encoding="utf-8"))
    sensing = next(row for row in document["records"] if row["key"] == "qi_sensing")
    sensing["layer_thresholds"]["2"] = 987654
    realm_path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")

    bundle = ContentBundle.load(data_root)
    assert next_layer_threshold("qi_sensing", 1, bundle) == 987654
    assert "qi_sensing" in formal_realms(bundle)
