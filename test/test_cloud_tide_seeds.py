from __future__ import annotations

import hashlib
import json
from pathlib import Path

from test_seed_migration import deploy, host, preserved


ROOT = Path(__file__).resolve().parents[1]
BASELINES = {
    "剧情/主线.json": "75c2ddfc88e7a6d6829104f7b840d944b4bfd522704da23c4ed0140c9c0d7e5d",
    "图鉴/条目.json": "0e6180662fc8e7ada7424b3a1714c2b948fd8057a9966fbe54edaf9a37bff140",
}


def before_cloud_tide_release(relative: str, text: str) -> str:
    """Rebuild the pinned c53fc18 official blobs for migration tests only."""
    from test_cloud_party_seeds import before_cloud_party_release

    text = before_cloud_party_release(relative, text)
    if relative == "图鉴/条目.json":
        return "".join(line for line in text.splitlines(keepends=True) if '"codex.story.cloud_tide_handover"' not in line)
    if relative != "剧情/主线.json":
        return text
    stages = {row["key"]: row for row in json.loads(text)["records"]}
    trial = stages["cloud_tide.1"]["objectives"][-1]
    trial_json = json.dumps(trial, ensure_ascii=False)
    trial_json = trial_json.replace(', "owned_receipts": true', "")
    text = text.replace(json.dumps(trial, ensure_ascii=False), trial_json)
    final = stages["cloud_tide.3"]
    evidence = json.dumps(final["objectives"][-1]["delivery_evidence"], ensure_ascii=False)
    text = text.replace(', "delivery_evidence": ' + evidence, "")
    action = dict(final["actions"][-2])
    old_action = {**action, "description": "身在青石镇且金丹一层后接单。"}
    replacements = (
        (final["objectives"][-1]["label"], "本关交付候潮备材并实交两云铁一阵砂"),
        (action, old_action),
        (final["retry"]["message"], "需要本关实际回镇和本人候潮备材交单。旧行程、旧交单或缺料不算；补足两云铁一阵砂，过期次日重接，重启后进度保留。"),
    )
    for current, old in replacements:
        encoded = json.dumps(current, ensure_ascii=False)
        assert text.count(encoded) == 1
        text = text.replace(encoded, json.dumps(old, ensure_ascii=False))
    return text.replace(', "codex.story.cloud_tide_handover": 1', "")


def old_cloud_tide_seeds():
    result = {}
    for relative, expected in BASELINES.items():
        blob = before_cloud_tide_release(relative, (ROOT / "data" / relative).read_text(encoding="utf-8")).encode("utf-8")
        assert hashlib.sha256(blob).hexdigest() == expected, f"{relative}: {hashlib.sha256(blob).hexdigest()}"
        result[relative] = blob
    return result


def test_cloud_tide_seed_upgrade_backup_replay_and_custom_rollback(host):
    old = old_cloud_tide_seeds()
    rules = json.loads((ROOT / "scripts/seed_migrations.json").read_text(encoding="utf-8"))
    for relative, blob in old.items():
        assert rules[relative]["old_sha256"][BASELINES[relative]] == f"c53fc1842cd5d2dd111d61bd08fee8fc3968c327:data/{relative}"
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
    custom_codex["records"][0]["desc"] += " 本地潮簿。"
    custom_blob = (json.dumps(custom_codex, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    (host / "data/图鉴/条目.json").write_bytes(custom_blob)
    (host / "data/剧情/主线.json").write_bytes(old["剧情/主线.json"])
    source = host / "src/plugins/nonebot_plugin_xiuxian_3/__init__.py"
    source.write_bytes(b"# previous tide source\n")
    previous_toml = (host / "pyproject.toml").read_bytes()
    result = deploy(host)
    assert result.returncode != 0 and "codex.story.cloud_tide_handover" in result.stdout + result.stderr
    assert "已回退" in result.stderr
    assert (host / "data/图鉴/条目.json").read_bytes() == custom_blob
    assert (host / "data/剧情/主线.json").read_bytes() == old["剧情/主线.json"]
    assert source.read_bytes() == b"# previous tide source\n"
    assert (host / "pyproject.toml").read_bytes() == previous_toml
    preserved(host)


def test_cloud_tide_keeps_supported_historical_seed_hashes():
    from test_mist_lamp_seeds import old_mist_lamp_seeds

    assert old_cloud_tide_seeds()
    assert old_mist_lamp_seeds()
