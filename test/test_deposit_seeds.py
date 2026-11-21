from __future__ import annotations

import hashlib
import json

from scripts.install_plugin_source import _seed_plan
from test_seed_migration import ROOT, old_official_materials
from test_survey_seeds import old_survey_seeds
from test_cloud_party_seeds import before_cloud_party_release


BASELINES = {
    "内容清单.json": "d7060c48cac18ec33924aea7f8337fcc58ded6ad65cbdcf4a74d8e4753def60a",
    "来源/来源.json": "d2458f7f1694046ec678d91bbb331c1c3eff1093d4f6b1ff6d262c380afcbf93",
    "生产/配方.json": "99d3707d4734869336a1e9d44a0fbcf62f588dce4b8d39be200f384566bb0823",
    "道具/材料.json": "f94230676682ce3d76a96692f630f2c0ecf3ae9051a75a079f1a6165fb1c484a",
}
OLD_MANIFEST = ROOT / "test/fixtures/official_seeds/manifest_pre_deposits.json"


def old_deposit_seeds():
    result = {}
    markers = ('    {"key":"source.deposit.', '    {"key":"recipe.field.root_wedge"',
               '    {"key":"item.mat.root_wedge"', '    {"key":"source.relic.',
               '    {"key":"recipe.relic.', '    {"key":"item.relic.',
               '    {"key":"recipe.equipment.repair_kit',
               '    {"key":"item.equipment.repair_kit')
    for relative, expected in BASELINES.items():
        if relative == "内容清单.json":
            blob = OLD_MANIFEST.read_bytes()
        else:
            text = before_cloud_party_release(
                relative, (ROOT / "data" / relative).read_text(encoding="utf-8")
            )
            text = "".join(line for line in text.splitlines(keepends=True)
                           if not line.startswith(markers))
            blob = text.encode("utf-8")
        result[relative] = blob
        assert hashlib.sha256(result[relative]).hexdigest() == expected, relative
    return result


def test_deposit_changed_seed_plan_new_file_replay_and_custom_preservation(tmp_path):
    manifest = json.loads((ROOT / "scripts/seed_migrations.json").read_text(encoding="utf-8"))
    source, host = tmp_path / "source", tmp_path / "host"
    for relative, blob in old_deposit_seeds().items():
        assert BASELINES[relative] in manifest[relative]["old_sha256"]
        path = host / "data" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(blob)
    relatives = {*BASELINES, "探索/资源脉.json"}
    for relative in relatives:
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((ROOT / "data" / relative).read_bytes())
    changes, custom = _seed_plan(source, host)
    assert not custom and {p.as_posix() for p, _ in changes} == relatives
    for relative, blob in changes:
        path = host / "data" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(blob)
    assert _seed_plan(source, host) == ([], [])
    for relative in relatives:
        path = host / "data" / relative
        document = json.loads(path.read_bytes())
        if "records" in document:
            document["records"][0]["desc"] += " 本地描述。"
        else:
            document["status"] = "custom"
        path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    changes, custom = _seed_plan(source, host)
    assert not changes and set(custom) == relatives


def test_deposit_additions_preserve_previous_official_baselines():
    assert old_deposit_seeds()
    assert old_survey_seeds()
    assert old_official_materials()


def test_deposit_source_rows_match_real_producers():
    from nonebot_plugin_xiuxian_3.xiuxian.content import bundled_content
    from nonebot_plugin_xiuxian_3.xiuxian.content_integrity import _validate_source_reference
    from nonebot_plugin_xiuxian_3.xiuxian.exploration.deposit_rules import deposit_definitions

    bundle = bundled_content()
    definitions = deposit_definitions(bundle)
    source = bundle.require("source", "source.deposit.materials")
    produced = set()
    for channel in source["channels"]:
        _validate_source_reference(bundle, source["key"], channel["reference"])
        for plan in definitions[channel["reference"]]["plans"]:
            produced.update(plan["rewards"])
    assert produced == set(source["asset_keys"])
    upkeep = bundle.require("source", "source.deposit.upkeep")
    recipe = bundle.require("recipe", upkeep["channels"][0]["reference"])
    assert set(recipe["outputs"]) == set(upkeep["asset_keys"])
