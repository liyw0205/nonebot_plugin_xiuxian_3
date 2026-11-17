from __future__ import annotations

import hashlib
import json

from scripts.install_plugin_source import _seed_plan
from test_bounty_patrol_seeds import old_bounty_patrol_seeds
from test_field_journey_seeds import old_field_journey_seeds
from test_patrol_seeds import old_patrol_seeds
from test_seed_migration import ROOT, old_official_place_codex


BASELINES = {
    "生活/生活.json": ("36458bfb4f80805fd6d1ac7bb34a48d7929df2a5935a0c38c9b5846ce1cf6f4f", ("idle.camp.", "town_commission.camp_supplies")),
    "奖励/奖励.json": ("46a2023d4eb3edacf0347449dd9d2505552838145581332e5648cfcde5592f8b", ("reward_pool.idle.camp.",)),
    "图鉴/条目.json": ("eb4f74a2649893ed43a87764f94e8c5364356561d5be1a525dfbbcb070acd03b", ("codex.story.camp.",)),
    "来源/来源.json": ("b9b424b8331ade3795ae49d09de17b8cd060ceb708d7ec9cc13dafda2613849d", ("source.idle.camp.", "source.armor.patrol_vest")),
    "生产/配方.json": ("ca93aa0948054094820e7ade8d26548610ede5cab60b36c9712ee3f92899220d", ("recipe.armor.patrol_vest",)),
    "装备/防具.json": ("b8ef578785ecf7916e413674a1c48971a0479701bd302771101037065fbe06fd", ("item.armor.patrol_vest",)),
}


def old_camp_seeds():
    result = {}
    for relative, (expected, prefixes) in BASELINES.items():
        lines = (ROOT / "data" / relative).read_text(encoding="utf-8").splitlines(keepends=True)
        markers = tuple('    {"key":"' + prefix for prefix in
                        (*prefixes, "source.survey.", "source.deposit.", "recipe.field.root_wedge"))
        blob = "".join(line for line in lines if not line.startswith(markers)).encode("utf-8")
        assert hashlib.sha256(blob).hexdigest() == expected, relative
        result[relative] = blob
    return result


def test_camp_seed_plan_upgrade_replay_and_custom_preservation(tmp_path):
    manifest = json.loads((ROOT / "scripts/seed_migrations.json").read_text(encoding="utf-8"))
    source, host = tmp_path / "source", tmp_path / "host"
    old = old_camp_seeds()
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


def test_camp_seed_additions_preserve_previous_official_baselines():
    assert old_field_journey_seeds()
    assert old_patrol_seeds()
    assert old_bounty_patrol_seeds()
    assert old_official_place_codex()
