from __future__ import annotations

import hashlib
import json

from test_seed_migration import ROOT, deploy, host, preserved


BASELINE_COMMIT = "7030af3a8b86af37d9047665b0bb95be81cb301a"
DATA_COMMIT = "363279cf4137e49e625cb3cc8ca5239ec38879fd"
OLD_SEEDS = {
    "战斗/敌人.json": "6251f6a97f46487d42572824ac21806db13f357eba07db6b49fa7ce1ec94c76d",
    "来源/来源.json": "cb068be5996fa56bfa52809e50549d7a96a74a294c106b4cdcbb3d5c4a2a8dcc",
}
FIXTURES = {
    "战斗/敌人.json": ROOT / "test/fixtures/official_seeds/basalt_party_pre_release_enemies.json",
    "来源/来源.json": ROOT / "test/fixtures/official_seeds/basalt_party_pre_release_sources.json",
}


def test_basalt_party_seed_upgrade_replay_and_custom_preservation(host):
    manifest = json.loads((ROOT / "scripts/seed_migrations.json").read_text(encoding="utf-8"))
    old = {}
    for relative, old_sha in OLD_SEEDS.items():
        previous = FIXTURES[relative].read_bytes()
        current = (ROOT / "data" / relative).read_bytes()
        rule = manifest[relative]
        assert hashlib.sha256(previous).hexdigest() == old_sha
        assert rule["old_sha256"][old_sha] == f"{BASELINE_COMMIT}:data/{relative}"
        assert hashlib.sha256(current).hexdigest() == rule["new_sha256"]
        assert rule["new_commit"] == DATA_COMMIT
        path = host / "data" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(previous)
        old[relative] = previous

    upgraded = deploy(host)
    assert upgraded.returncode == 0 and "种子更新 2 个" in upgraded.stdout, upgraded.stdout + upgraded.stderr
    backup = next((host / ".xiuxian3/backups").glob("deploy-*"))
    for relative, previous in old.items():
        assert (backup / "data" / relative).read_bytes() == previous
        assert (host / "data" / relative).read_bytes() == (ROOT / "data" / relative).read_bytes()
    enemies = json.loads((host / "data/战斗/敌人.json").read_text(encoding="utf-8"))
    sources = json.loads((host / "data/来源/来源.json").read_text(encoding="utf-8"))
    assert any(row["key"] == "enemy.basalt_canal_marker" for row in enemies["records"])
    assert any(row["key"] == "source.party.basalt_canal" for row in sources["records"])
    preserved(host)

    repeated = deploy(host)
    assert repeated.returncode == 0 and "种子更新 0 个" in repeated.stdout
    enemy_path = host / "data/战斗/敌人.json"
    custom = json.loads(enemy_path.read_text(encoding="utf-8"))
    custom["records"][0]["desc"] += " 本地自定义守备记录。"
    custom_bytes = (json.dumps(custom, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    enemy_path.write_bytes(custom_bytes)
    preserved_result = deploy(host)
    assert preserved_result.returncode == 0 and "种子更新 0 个" in preserved_result.stdout
    assert enemy_path.read_bytes() == custom_bytes
    preserved(host)
