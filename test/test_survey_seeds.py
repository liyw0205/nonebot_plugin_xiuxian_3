from __future__ import annotations

import hashlib
import json

from scripts.install_plugin_source import _seed_plan
from test_seed_migration import ROOT, old_official_manifest


BASELINES = {
    "内容清单.json": "c4246fa9c525bc454c17e5a345c389b07d44c9526620e35c27a0a8d5f8853bd5",
    "来源/来源.json": "e942a880ea0b533ffa00564d89219c25eb9d54314604215cfda7a48178ee24af",
}


def old_survey_seeds():
    result = {}
    for relative, expected in BASELINES.items():
        text = (ROOT / "data" / relative).read_text(encoding="utf-8")
        if relative == "内容清单.json":
            text = text.replace('    "探索/地貌.json",\n', "")
        else:
            text = "".join(line for line in text.splitlines(keepends=True)
                           if not line.startswith('    {"key":"source.survey.'))
        result[relative] = text.encode("utf-8")
        assert hashlib.sha256(result[relative]).hexdigest() == expected
    return result


def test_survey_seeds_missing_new_file_upgrade_replay_and_custom_preservation(tmp_path):
    rules = json.loads((ROOT / "scripts/seed_migrations.json").read_text(encoding="utf-8"))
    source, host = tmp_path / "source", tmp_path / "host"
    for relative, blob in old_survey_seeds().items():
        assert BASELINES[relative] in rules[relative]["old_sha256"]
        path = host / "data" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(blob)
    relatives = {*BASELINES, "探索/地貌.json"}
    for relative in relatives:
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((ROOT / "data" / relative).read_bytes())
    changes, custom = _seed_plan(source, host)
    assert not custom and {p.as_posix() for p, _ in changes} == relatives
    for path, blob in changes:
        target = host / "data" / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(blob)
    assert _seed_plan(source, host) == ([], [])
    for relative in relatives:
        path = host / "data" / relative
        value = json.loads(path.read_bytes())
        value["local_note"] = "preserved"
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    changes, custom = _seed_plan(source, host)
    assert not changes and set(custom) == relatives


def test_survey_sources_and_historical_manifest_remain_valid():
    from nonebot_plugin_xiuxian_3.xiuxian.content import bundled_content
    from nonebot_plugin_xiuxian_3.xiuxian.content_integrity import validate_source_content

    assert validate_source_content(bundled_content())
    assert old_official_manifest()
