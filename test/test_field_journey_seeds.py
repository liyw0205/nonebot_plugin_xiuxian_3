from __future__ import annotations

import hashlib
import json
from pathlib import Path

from test_seed_migration import ROOT, deploy, host, preserved


# Exact 9219b3bf6f908f08ee884149af311a30e8caeb9f Git blobs, reconstructed
# from append-only additions so source archives do not require Git history.
BASELINE_HASHES = {
    "剧情/主线.json": "c6a7d898649bd4465c82135c801d0d6b114db7143c510981113237f4a1e8d023",
    "生活/生活.json": "8c51de6c4c25efd1bc744aec66d674c629985ba74a8f1b6424b1f88a07325fd3",
    "奖励/奖励.json": "1661a190cb5058413a9c2e3d13c741432ce890e85acc871c16353ef408066bf1",
    "图鉴/条目.json": "e754947be1ed84b3de76e9feff2022e3cc83da75b7747a2610e2a8c8a7a60986",
    "来源/来源.json": "8c8f7f57ecec35b7c8fb1e34699552420041b067383dbbe60a4cf2b50882a01f",
}


def old_field_journey_seeds() -> dict[str, bytes]:
    result = {}
    for relative, expected in BASELINE_HASHES.items():
        text = (ROOT / "data" / relative).read_text(encoding="utf-8")
        if relative == "剧情/主线.json":
            marker = text.index('    {\n      "key": "field_seeds.1"')
            text = text[:marker].rstrip()[:-1] + "\n  ]\n}\n"
        elif relative in {"生活/生活.json", "奖励/奖励.json"}:
            first = text.index('  "records": [\n') + len('  "records": [\n')
            marker = text.index('    {\n      "key": "idle.herb_vale_gather"') if relative == "生活/生活.json" else text.index('    {"key": "reward_pool.idle.mist_lamp"')
            text = text[:first] + text[marker:]
        else:
            text = "".join(line for line in text.splitlines(keepends=True)
                           if "leaf_watch" not in line)
        blob = text.encode("utf-8")
        assert hashlib.sha256(blob).hexdigest() == expected, relative
        result[relative] = blob
    return result


def test_field_journey_seeds_upgrade_backup_replay_custom_and_merge(host: Path) -> None:
    old = old_field_journey_seeds()
    rules = json.loads((ROOT / "scripts/seed_migrations.json").read_text(encoding="utf-8"))
    for relative, blob in old.items():
        assert BASELINE_HASHES[relative] in rules[relative]["old_sha256"]
        (host / "data" / relative).write_bytes(blob)
    result = deploy(host)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "种子更新 5 个" in result.stdout
    backup = next((host / ".xiuxian3/backups").glob("deploy-*"))
    for relative, blob in old.items():
        assert (host / "data" / relative).read_bytes() == (ROOT / "data" / relative).read_bytes()
        assert (backup / "data" / relative).read_bytes() == blob
    preserved(host)
    result = deploy(host)
    assert result.returncode == 0 and "种子更新 0 个" in result.stdout, result.stdout + result.stderr
    preserved(host)

    custom = {}
    for relative in old:
        document = json.loads((ROOT / "data" / relative).read_bytes())
        document["records"][0]["desc"] += " 本地保留的内容。"
        custom[relative] = (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        (host / "data" / relative).write_bytes(custom[relative])
    result = deploy(host)
    assert result.returncode == 0 and "种子更新 0 个" in result.stdout, result.stdout + result.stderr
    assert all((host / "data" / relative).read_bytes() == blob for relative, blob in custom.items())
    preserved(host)

    # The retained custom mainline lacks the watch unlock; attempted companion
    # seed replacements must roll back with source and TOML, leaving user data.
    before = dict(old)
    document = json.loads(before["剧情/主线.json"])
    document["records"][0]["body"] += " 本地保留的剧情。"
    before["剧情/主线.json"] = (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    for relative, blob in before.items():
        (host / "data" / relative).write_bytes(blob)
    source = host / "src/plugins/nonebot_plugin_xiuxian_3/__init__.py"
    source.write_bytes(b"# previous user source\n")
    previous_source = source.read_bytes()
    previous_toml = (host / "pyproject.toml").read_bytes()
    result = deploy(host)
    assert result.returncode != 0
    assert "requirements.mainline_stage" in result.stdout + result.stderr
    assert "leaf_watch.2" in result.stdout + result.stderr
    assert "已回退" in result.stderr
    assert all((host / "data" / relative).read_bytes() == blob for relative, blob in before.items())
    assert source.read_bytes() == previous_source
    assert (host / "pyproject.toml").read_bytes() == previous_toml
    preserved(host)

    current = json.loads((ROOT / "data/剧情/主线.json").read_bytes())
    existing_keys = {row["key"] for row in document["records"]}
    document["records"].extend(row for row in current["records"] if row["key"] not in existing_keys)
    merged = (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    (host / "data/剧情/主线.json").write_bytes(merged)
    result = deploy(host)
    assert result.returncode == 0 and "种子更新 4 个" in result.stdout, result.stdout + result.stderr
    assert (host / "data/剧情/主线.json").read_bytes() == merged
    assert all((host / "data" / relative).read_bytes() == (ROOT / "data" / relative).read_bytes()
               for relative in old if relative != "剧情/主线.json")
    preserved(host)
