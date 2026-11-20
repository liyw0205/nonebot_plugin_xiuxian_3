from __future__ import annotations

import hashlib
import json

from scripts.install_plugin_source import _seed_plan
from test_seed_migration import ROOT


PATROL_BASELINES = {
    "地图/地点.json": "b62f965ff5e37fb2259067f3550a52404421be125fc52c52fa95e24f395e5256",
    "探索/模式.json": "a61b136357635b4741430de164bd652605ffb6f8f5fbbb5a039ba6d81465830a",
    "奖励/奖励.json": "5a0ec9f0b1e4e364cbb4e53dfaf1711948b297dba10ba0dcb10ae44fc34f0080",
    "来源/来源.json": "b56dabd97899f8584a91562cdbf156117667cebe87ba6cc8a18f988b858ec6e0",
}


def old_patrol_seeds():
    markers = {
        "探索/模式.json": '    {\n      "key": "explore.gather_outskirts"',
        "奖励/奖励.json": '    {"key": "reward_pool.idle.leaf_watch"',
        "来源/来源.json": '    {\n      "key": "source.item.herb.blood_grass"',
    }
    result = {}
    for relative, expected in PATROL_BASELINES.items():
        text = (ROOT / "data" / relative).read_text(encoding="utf-8")
        if relative in markers:
            first = text.index('  "records": [\n') + len('  "records": [\n')
            text = text[:first] + text[text.index(markers[relative]):]
        else:
            text = text.replace('        "explore.patrol_outskirts",\n', "")
            text = text.replace('        "explore.relic.creek",\n', "")
            for slug in ("ironwood", "basalt"):
                text = text.replace(', "explore.patrol_' + slug + '"', "")
                text = text.replace(', "explore.relic.' + slug + '"', "")
        blob = text.encode("utf-8")
        assert hashlib.sha256(blob).hexdigest() == expected, relative
        result[relative] = blob
    return result


def test_patrol_changed_seed_plan_accepts_pinned_official_and_preserves_custom(tmp_path):
    old = old_patrol_seeds()
    manifest = json.loads((ROOT / "scripts/seed_migrations.json").read_text(encoding="utf-8"))
    source, target = tmp_path / "source", tmp_path / "host"
    for relative, blob in old.items():
        assert PATROL_BASELINES[relative] in manifest[relative]["old_sha256"]
        src, dst = source / relative, target / "data" / relative
        src.parent.mkdir(parents=True, exist_ok=True)
        dst.parent.mkdir(parents=True, exist_ok=True)
        src.write_bytes((ROOT / "data" / relative).read_bytes())
        dst.write_bytes(blob)
    changes, custom = _seed_plan(source, target)
    assert not custom and {p.as_posix() for p, _ in changes} == set(old)
    for relative, blob in changes:
        (target / "data" / relative).write_bytes(blob)
    assert _seed_plan(source, target) == ([], [])
    for relative in old:
        path = target / "data" / relative
        document = json.loads(path.read_bytes())
        document["records"][0]["desc"] += " 本地保留。"
        path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    changes, custom = _seed_plan(source, target)
    assert not changes and set(custom) == set(old)
