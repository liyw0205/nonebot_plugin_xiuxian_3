from __future__ import annotations

import hashlib
import json
from pathlib import Path

from test_seed_migration import deploy, host, preserved


ROOT = Path(__file__).resolve().parents[1]
RELATIVE = "战斗/敌人.json"
OLD_SHA = "7803c4807d84e41ec1a66054aca51aed8c0b7ec58fcd6917416b674718117246"
OLD_SOURCE = f"4f1ad3c70ac9c1e6734cc8c17392d9742e1f0d3b:data/{RELATIVE}"
SOURCE_RELATIVE = "来源/来源.json"
SOURCE_OLD_SHA = "0584f524734f89520676b8369e69b122962b8440609cb36a7a55837a879e7b13"
SOURCE_OLD_REF = f"2f2ec0e10b9d6639b487f9f5b02f2f8ff8eafee5:data/{SOURCE_RELATIVE}"


FIXTURES = {
    RELATIVE: ROOT / "test/fixtures/official_seeds/cloud_party_pre_cooperation_enemies.json",
    SOURCE_RELATIVE: ROOT / "test/fixtures/official_seeds/cloud_party_pre_cooperation_sources.json",
}


def before_cloud_party_release(relative: str, text: str) -> str:
    """Rebuild party-specific legacy inputs without dropping unrelated enemies."""
    if relative == SOURCE_RELATIVE:
        party_sources = (
            '    {"key":"source.party.cloud_boat"',
            '    {"key":"source.party.basalt_canal"',
        )
        return "".join(
            line for line in text.splitlines(keepends=True)
            if not line.startswith(party_sources)
        )
    if relative != RELATIVE:
        return text
    document = json.loads(text)
    historical = json.loads(FIXTURES[RELATIVE].read_bytes())
    guardian = next(
        row for row in historical["records"]
        if row.get("key") == "enemy.cloud_boat_guardian"
    )
    document["records"] = [
        guardian if row.get("key") == "enemy.cloud_boat_guardian" else row
        for row in document["records"]
    ]
    return json.dumps(document, ensure_ascii=False, indent=2) + "\n"


def old_cloud_party_seeds():
    result = {}
    for relative, expected in (
        (RELATIVE, OLD_SHA),
        (SOURCE_RELATIVE, SOURCE_OLD_SHA),
    ):
        blob = FIXTURES[relative].read_bytes()
        assert hashlib.sha256(blob).hexdigest() == expected
        result[relative] = blob
    return result


def test_cloud_party_seed_upgrade_backup_replay_and_custom_preservation(host):
    old = old_cloud_party_seeds()
    manifest = json.loads((ROOT / "scripts/seed_migrations.json").read_text(encoding="utf-8"))
    assert manifest[RELATIVE]["old_sha256"][OLD_SHA] == OLD_SOURCE
    assert manifest[SOURCE_RELATIVE]["old_sha256"][SOURCE_OLD_SHA] == SOURCE_OLD_REF
    path = host / "data" / RELATIVE
    for relative, blob in old.items():
        (host / "data" / relative).write_bytes(blob)
    result = deploy(host)
    assert result.returncode == 0 and "种子更新 2 个" in result.stdout, result.stdout + result.stderr
    backup = next((host / ".xiuxian3/backups").glob("deploy-*"))
    for relative, blob in old.items():
        assert (backup / "data" / relative).read_bytes() == blob
        assert (host / "data" / relative).read_bytes() == (ROOT / "data" / relative).read_bytes()
    preserved(host)
    result = deploy(host)
    assert result.returncode == 0 and "种子更新 0 个" in result.stdout, result.stdout + result.stderr
    custom = json.loads(path.read_text(encoding="utf-8"))
    custom["records"][0]["desc"] += " 本地护航规则。"
    blob = (json.dumps(custom, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    path.write_bytes(blob)
    result = deploy(host)
    assert result.returncode == 0 and "种子更新 0 个" in result.stdout, result.stdout + result.stderr
    assert path.read_bytes() == blob
    preserved(host)


def test_cloud_party_invalid_custom_entry_rolls_back_source_toml_and_seed(host):
    path = host / "data" / RELATIVE
    custom = json.loads(path.read_text(encoding="utf-8"))
    enemy = next(row for row in custom["records"] if row["key"] == "enemy.cloud_boat_guardian")
    enemy["combat_profile"]["party_profile"]["entry"]["stamina"] = True
    blob = (json.dumps(custom, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    path.write_bytes(blob)
    source = host / "src/plugins/nonebot_plugin_xiuxian_3/__init__.py"
    original_source = source.read_bytes()
    original_toml = (host / "pyproject.toml").read_bytes()
    result = deploy(host)
    assert result.returncode != 0 and "party entry" in result.stdout + result.stderr
    assert "已回退" in result.stderr
    assert path.read_bytes() == blob
    assert source.read_bytes() == original_source
    assert (host / "pyproject.toml").read_bytes() == original_toml
    preserved(host)
