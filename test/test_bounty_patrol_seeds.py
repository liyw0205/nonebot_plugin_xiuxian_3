from __future__ import annotations

import hashlib
import json

from scripts.install_plugin_source import _seed_plan
from test_seed_migration import ROOT


BASELINES = {
    "任务/悬赏.json": ("e478f67601200523144dd7df53d98bcf692d7cee0b96959b7baefb98500fdd5d", '    {\n      "key": "bounty.herb_supply"'),
    "奖励/奖励.json": ("45bbfc9a2526ba8eb44ea14b7cf1d56bb2970040dda4434bcea7738ee3e908a7", '    {\n      "key": "reward_pool.patrol.outskirts.cart.careful"'),
    "来源/来源.json": ("83df26fcefbb04d1803b2936aae049c81b6be1647a90f82e4559850e80d72270", '    {\n      "key": "source.patrol.outskirts"'),
}


def old_bounty_patrol_seeds():
    result = {}
    for relative, (expected, marker) in BASELINES.items():
        text = (ROOT / "data" / relative).read_text(encoding="utf-8")
        first = text.index('  "records": [\n') + len('  "records": [\n')
        blob = (text[:first] + text[text.index(marker):]).encode("utf-8")
        assert hashlib.sha256(blob).hexdigest() == expected, relative
        result[relative] = blob
    return result


def test_patrol_contract_seed_plan_and_custom_preservation(tmp_path):
    manifest = json.loads((ROOT / "scripts/seed_migrations.json").read_text(encoding="utf-8"))
    source, host = tmp_path / "source", tmp_path / "host"
    old = old_bounty_patrol_seeds()
    for relative, blob in old.items():
        assert BASELINES[relative][0] in manifest[relative]["old_sha256"]
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
