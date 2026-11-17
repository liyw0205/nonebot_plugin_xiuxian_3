from __future__ import annotations

import hashlib
import json

from scripts.install_plugin_source import _seed_plan
from test_camp_seeds import old_camp_seeds
from test_deposit_seeds import old_deposit_seeds
from test_patrol_seeds import old_patrol_seeds
from test_seed_migration import ROOT, old_official_locations, old_official_materials
from test_survey_seeds import old_survey_seeds


BASELINES = {
    "地图/地点.json": "ea1f319a28279ce5582aef08d208c6ea33bc5e8c39ed90e7475d45c24320cdbf",
    "奖励/奖励.json": "463dbc1ba9117d18c2d0ee1f64cdb80e16f9d155d07cfd30edecf3050ca1ba3b",
    "战斗/遭遇池.json": "0a5d3a9817f29b0e490ae60b0b85645c08d2c5187090138bd1275f85abe43563",
    "探索/模式.json": "491ceea54255ca5f6ed11cf6f64c098d2f809b21bd320e2f4c8948cca07f7aa1",
    "来源/来源.json": "2281c82d53044841fcab4cf4b7df33874302de471b97c5d8524b582d174ea80b",
    "生产/配方.json": "a65d93832cc74095b6cb7ac4971646a5ec9a2dd1ca1fe8e07f6a71ed57960401",
    "生活/生活.json": "24bbd3e894258a44110c00bb2956c67aae3d0f7018a07d26f33c574705c8e52b",
    "装备/饰品.json": "c6f1242d3fe68f1732d57c435a314df0305787639791f2b73ac426746797fc30",
    "道具/材料.json": "7ff23ab82eefb1b136db89148dfc829b955cadddd410bd629448f1991ca9eed3",
}


def old_relic_seeds():
    result = {}
    prefixes = (
        "explore.relic.", "reward_pool.relic.", "source.relic.", "recipe.relic.",
        "recipe.equipment.repair_kit", "town_commission.relic_fragments",
        "town_commission.repair_kits", "item.accessory.field_compass", "item.relic.",
        "item.equipment.repair_kit",
    )
    markers = tuple('    {"key":"' + prefix for prefix in prefixes)
    for relative, expected in BASELINES.items():
        text = (ROOT / "data" / relative).read_text(encoding="utf-8")
        text = "".join(line for line in text.splitlines(keepends=True)
                       if not line.startswith((*markers, '    {"key": "encounter.relic.')))
        if relative == "地图/地点.json":
            text = text.replace('        "explore.relic.creek",\n', "")
            for slug in ("ironwood", "basalt"):
                text = text.replace(', "explore.relic.' + slug + '"', "")
        blob = text.encode("utf-8")
        assert hashlib.sha256(blob).hexdigest() == expected, relative
        result[relative] = blob
    return result


def test_relic_seed_plan_upgrade_replay_and_custom_preservation(tmp_path):
    manifest = json.loads((ROOT / "scripts/seed_migrations.json").read_text(encoding="utf-8"))
    source, host = tmp_path / "source", tmp_path / "host"
    old = old_relic_seeds()
    for relative, blob in old.items():
        assert BASELINES[relative] in manifest[relative]["old_sha256"]
        src, dst = source / relative, host / "data" / relative
        src.parent.mkdir(parents=True, exist_ok=True)
        dst.parent.mkdir(parents=True, exist_ok=True)
        src.write_bytes((ROOT / "data" / relative).read_bytes())
        dst.write_bytes(blob)
    changes, custom = _seed_plan(source, host)
    assert not custom and {p.as_posix() for p, _ in changes} == set(old)
    for relative, blob in changes:
        (host / "data" / relative).write_bytes(blob)
    assert _seed_plan(source, host) == ([], [])
    for relative in old:
        path = host / "data" / relative
        document = json.loads(path.read_bytes())
        document["records"][0]["desc"] += " 本地保留。"
        path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    changes, custom = _seed_plan(source, host)
    assert not changes and set(custom) == set(old)


def test_relic_additions_preserve_previous_official_baselines():
    assert old_relic_seeds()
    assert old_survey_seeds()
    assert old_deposit_seeds()
    assert old_camp_seeds()
    assert old_patrol_seeds()
    assert old_official_locations()
    assert old_official_materials()
