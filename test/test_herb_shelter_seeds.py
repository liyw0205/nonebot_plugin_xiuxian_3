from __future__ import annotations

import hashlib
import json
from pathlib import Path

from test_seed_migration import host


ROOT = Path(__file__).resolve().parents[1]
BASELINES = {
    "剧情/主线.json": "51a3a2c6969d4cfceee5c1ac8dbb733a05059c00a655f5a2ae0b00cd6f2cec39",
    "图鉴/条目.json": "813a83c76e6bf0b744e56b9593926904098cd0334e9460fca824a62d64bfee5e",
}


def before_herb_shelter_release(relative: str, text: str) -> str:
    """Reconstruct pinned Git blobs, never exclude records from live contracts."""
    if relative == "图鉴/条目.json":
        return "".join(line for line in text.splitlines(keepends=True) if '"codex.story.herb_shelter"' not in line)
    if relative != "剧情/主线.json":
        return text
    stages = {row["key"]: row for row in json.loads(text)["records"]}
    replacements = []
    for key, label in (("herb_shelter.2", "本关交付药棚救治委托并交出一枚疗伤丹"), ("herb_shelter.3", "本关交付止血草供应并交出三份止血草")):
        objective = stages[key]["objectives"][-1]
        replacements.append((objective["label"], label))
        evidence = json.dumps(objective["delivery_evidence"], ensure_ascii=False)
        text = text.replace(', "delivery_evidence": ' + evidence, "")
    replacements.extend((
        (stages["herb_shelter.2"]["actions"][-2]["description"], "查看城镇委托期限后接单，炼药与交付都须在本关发生。"),
        (stages["herb_shelter.2"]["retry"]["message"], "需要本关新炉成功出丹和本人药棚救治交单两项记录。旧炉、失败、尚未领取、只接未交和旧交单不算；缺料按采药与拾穗日限补给，过期委托次日重接，主线保留。"),
        (stages["herb_shelter.3"]["retry"]["message"], "只认本关开始后的本人止血草供应交单；旧交单、缺药和过期订单不能交卷。材料不足不扣药，过期按原委托规则次日重接，主线进度保留。"),
    ))
    for current, old in replacements:
        encoded = json.dumps(current, ensure_ascii=False)
        assert text.count(encoded) == 1
        text = text.replace(encoded, json.dumps(old, ensure_ascii=False))
    return text.replace(', "codex.story.herb_shelter": 1', "")


def old_herb_shelter_seeds():
    result = {}
    for relative, expected in BASELINES.items():
        blob = before_herb_shelter_release(relative, (ROOT / "data" / relative).read_text(encoding="utf-8")).encode("utf-8")
        assert hashlib.sha256(blob).hexdigest() == expected, relative
        result[relative] = blob
    return result


def test_herb_shelter_seeds_upgrade_backup_replay_custom_and_rollback(host):
    from test_seed_migration import deploy, preserved

    old = old_herb_shelter_seeds()
    manifest = json.loads((ROOT / "scripts/seed_migrations.json").read_text(encoding="utf-8"))
    for relative, blob in old.items():
        assert manifest[relative]["old_sha256"][BASELINES[relative]] == f"8f55e2a4872df3521d0542ae43ebad5acb073487:data/{relative}"
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

    custom = {}
    for relative in old:
        document = json.loads((ROOT / "data" / relative).read_bytes())
        document["records"][0]["desc"] += " 自定义药棚记录。"
        custom[relative] = (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        (host / "data" / relative).write_bytes(custom[relative])
    result = deploy(host)
    assert result.returncode == 0 and "种子更新 0 个" in result.stdout, result.stdout + result.stderr
    assert all((host / "data" / relative).read_bytes() == blob for relative, blob in custom.items())
    preserved(host)

    codex = json.loads(old["图鉴/条目.json"])
    codex["records"][0]["desc"] += " 本地旧版图鉴。"
    custom_codex = (json.dumps(codex, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    (host / "data/图鉴/条目.json").write_bytes(custom_codex)
    (host / "data/剧情/主线.json").write_bytes(old["剧情/主线.json"])
    source = host / "src/plugins/nonebot_plugin_xiuxian_3/__init__.py"
    source.write_bytes(b"# previous source\n")
    previous_toml = (host / "pyproject.toml").read_bytes()
    result = deploy(host)
    assert result.returncode != 0 and "codex.story.herb_shelter" in result.stdout + result.stderr
    assert "已回退" in result.stderr
    assert (host / "data/图鉴/条目.json").read_bytes() == custom_codex
    assert (host / "data/剧情/主线.json").read_bytes() == old["剧情/主线.json"]
    assert source.read_bytes() == b"# previous source\n"
    assert (host / "pyproject.toml").read_bytes() == previous_toml
    preserved(host)
