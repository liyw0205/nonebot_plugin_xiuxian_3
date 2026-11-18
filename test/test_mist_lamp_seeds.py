from __future__ import annotations

import hashlib
import json
from pathlib import Path

from test_seed_migration import deploy, host, preserved


ROOT = Path(__file__).resolve().parents[1]
BASELINES = {
    "剧情/主线.json": "df303282c65581f376ed4a035f140fa96e158f893b1e51ccd6df71177baedacd",
    "图鉴/条目.json": "cfb0df5264b01d7fd7fdc10f58bed19b9da1f1ae1c0c699c3e8b27d885b879ac",
}


def before_mist_lamp_release(relative: str, text: str) -> str:
    """Rebuild the fixed 3d83636 official blobs for migration tests only."""
    if relative == "图鉴/条目.json":
        return "".join(line for line in text.splitlines(keepends=True) if '"codex.story.mist_lamp_handover"' not in line)
    if relative != "剧情/主线.json":
        return text
    stages = {row["key"]: row for row in json.loads(text)["records"]}
    final = stages["mist_lamp.3"]
    evidence = json.dumps(final["objectives"][-1]["delivery_evidence"], ensure_ascii=False)
    text = text.replace(', "delivery_evidence": ' + evidence, "")
    text = text.replace(', "owned_receipts": true', "")
    replacements = (
        (final["objectives"][-1]["label"], "本关交付灯阵续灵并实交聚灵阵"),
        (final["actions"][-2]["description"], "查看当日公示后接取。"),
        (final["retry"]["message"], "需要本关新制成功的聚灵阵和本人灯阵续灵交单。旧阵、失败、只接未交不能交卷，材料不足补给，过期次日重接，重启后进度保留。"),
    )
    for current, old in replacements:
        encoded = json.dumps(current, ensure_ascii=False)
        assert text.count(encoded) == 1
        text = text.replace(encoded, json.dumps(old, ensure_ascii=False))
    return text.replace(', "codex.story.mist_lamp_handover": 1', "")


def old_mist_lamp_seeds():
    result = {}
    for relative, expected in BASELINES.items():
        blob = before_mist_lamp_release(relative, (ROOT / "data" / relative).read_text(encoding="utf-8")).encode("utf-8")
        assert hashlib.sha256(blob).hexdigest() == expected, relative
        result[relative] = blob
    return result


def test_mist_lamp_seed_upgrade_backup_replay_and_custom_rollback(host):
    old = old_mist_lamp_seeds()
    rules = json.loads((ROOT / "scripts/seed_migrations.json").read_text(encoding="utf-8"))
    for relative, blob in old.items():
        assert rules[relative]["old_sha256"][BASELINES[relative]] == f"3d83636536ec6223af405511c70bc21de04ae7c6:data/{relative}"
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

    custom_codex = json.loads(old["图鉴/条目.json"])
    custom_codex["records"][0]["desc"] += " 本地灯簿。"
    custom_blob = (json.dumps(custom_codex, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    (host / "data/图鉴/条目.json").write_bytes(custom_blob)
    (host / "data/剧情/主线.json").write_bytes(old["剧情/主线.json"])
    source = host / "src/plugins/nonebot_plugin_xiuxian_3/__init__.py"
    source.write_bytes(b"# previous lamp source\n")
    previous_toml = (host / "pyproject.toml").read_bytes()
    result = deploy(host)
    assert result.returncode != 0 and "codex.story.mist_lamp_handover" in result.stdout + result.stderr
    assert "已回退" in result.stderr
    assert (host / "data/图鉴/条目.json").read_bytes() == custom_blob
    assert (host / "data/剧情/主线.json").read_bytes() == old["剧情/主线.json"]
    assert source.read_bytes() == b"# previous lamp source\n"
    assert (host / "pyproject.toml").read_bytes() == previous_toml
    preserved(host)


def test_mist_lamp_keeps_supported_historical_seed_hashes():
    from test_camp_seeds import old_camp_seeds
    from test_field_journey_seeds import old_field_journey_seeds
    from test_herb_shelter_seeds import old_herb_shelter_seeds
    from test_seed_migration import old_official_place_codex

    assert old_mist_lamp_seeds()
    assert old_herb_shelter_seeds()
    assert old_field_journey_seeds()
    assert old_camp_seeds()
    assert old_official_place_codex()
