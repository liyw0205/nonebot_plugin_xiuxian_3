from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "scripts/install_plugin_source.py"
MAINLINE = Path("剧情/主线.json")
OLD_SHA = "9fd8d8a3675f4b04f58e3b3c631e8995a8bd2db51467abb64f8a4a66e6156341"


def old_official_mainline() -> bytes:
    # Reverse only the current guard.5-protect.6 content delta; pin the patrol blob.
    text = (ROOT / "data" / MAINLINE).read_text(encoding="utf-8")
    for key in (
        "domain_frontier.guard.5",
        "domain_frontier.guard.6",
        "domain_frontier.purify.1",
        "domain_frontier.purify.2",
        "domain_frontier.purify.3",
        "domain_frontier.purify.4",
        "domain_frontier.purify.5",
        "domain_frontier.purify.6",
        "domain_frontier.protect.1",
        "domain_frontier.protect.2",
        "domain_frontier.protect.3",
        "domain_frontier.protect.4",
        "domain_frontier.protect.5",
        "domain_frontier.protect.6",
    ):
        start = text.index(f'      "key": "{key}"')
        end = text.index("\n    },", start)
        section = text[start:end]
        for pattern in (
            r'^      "body":[^\n]*\n',
            r'^      "objectives": \[\n.*?^      \],\n',
            r'^      "actions": \[\n.*?^      \],\n',
            r'^      "state_changes":[^\n]*\n',
            r'^      "next_stage_key":[^\n]*\n',
            r'^      "retry": \{\n.*?^      \},\n',
        ):
            section, count = re.subn(pattern, "", section, count=1, flags=re.M | re.S)
            if pattern.startswith('^      "next_stage_key"'):
                # Only the closing tail stage omits ahead reference; others must drop one.
                # Only story-tail stages legitimately omit the ahead reference.
                tail = key in ("chapter.4.stage.3", "domain_frontier.protect.6")
                assert count == (0 if tail else 1)
            else:
                assert count == 1
        text = text[:start] + section + text[end:]
    blob = text.encode("utf-8")
    assert hashlib.sha256(blob).hexdigest() == OLD_SHA
    return blob


@pytest.fixture
def host(tmp_path: Path) -> Path:
    target = tmp_path / "host"
    target.mkdir()
    shutil.copyfile(ROOT / "examples/nonebot/pyproject.toml", target / "pyproject.toml")
    shutil.copytree(ROOT / "data", target / "data")
    (target / ".env").write_bytes(b"preserve_env=1\n")
    (target / "data/xiuxian3.sqlite3").write_bytes(b"database-must-not-change")
    (target / "data/custom.json").write_bytes(b'{"user": "keep"}\n')
    plugin = target / "src/plugins/nonebot_plugin_xiuxian_3"
    plugin.mkdir(parents=True)
    (plugin / "__init__.py").write_bytes(b"# previous installed source\n")
    return target


def deploy(host: Path, *, data_only: bool = False) -> subprocess.CompletedProcess[str]:
    args = [sys.executable, str(HELPER), "--target", str(host),
            "--data-source", str(ROOT / "data"), "--validate-after-install"]
    args += ["--data-only"] if data_only else ["--source", str(ROOT / "nonebot_plugin_xiuxian_3")]
    return subprocess.run(args, cwd=host, capture_output=True, text=True)


def preserved(host: Path) -> None:
    assert (host / ".env").read_bytes() == b"preserve_env=1\n"
    assert (host / "data/xiuxian3.sqlite3").read_bytes() == b"database-must-not-change"
    assert (host / "data/custom.json").read_bytes() == b'{"user": "keep"}\n'


def test_official_seed_domain_frontier_stage_is_content_validated(tmp_path: Path) -> None:
    # The "body is too short" gate lives in explicit story validation at deploy time:
    # an official seed whose guard.1 keeps only title text must fail the validator.
    from nonebot_plugin_xiuxian_3.xiuxian.adventures.mainline import (
        DOMAIN_FRONTIER_STORY_KEY,
        mainline_definitions,
    )
    from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError

    data_dir = tmp_path / "data"
    shutil.copytree(ROOT / "data", data_dir)
    mainline_path = data_dir / MAINLINE
    mainline = json.loads(mainline_path.read_text(encoding="utf-8"))
    records = list(mainline["records"])
    for index, row in enumerate(records):
        if row.get("key") == "domain_frontier.guard.1":
            records[index] = {k: v for k, v in row.items()
                              if k in {"key", "story_key", "chapter", "stage", "name", "desc", "status"}}
    mainline["records"] = records
    mainline_path.write_text(json.dumps(mainline, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    bundle = ContentBundle.load(data_dir)
    with pytest.raises(ContentError, match="domain_frontier.guard.1 body is too short"):
        mainline_definitions(bundle, story_key=DOMAIN_FRONTIER_STORY_KEY)
    # The shipped official seed itself must always pass the same validator.
    assert mainline_definitions(None, story_key=DOMAIN_FRONTIER_STORY_KEY)


@pytest.mark.parametrize("data_only", [False, True])
def test_known_official_seed_migrates_with_backup_and_repeat_is_idempotent(host: Path, data_only: bool) -> None:
    old = old_official_mainline()
    (host / "data" / MAINLINE).write_bytes(old)
    if data_only:
        shutil.copytree(ROOT / "nonebot_plugin_xiuxian_3", host / "src/plugins/nonebot_plugin_xiuxian_3", dirs_exist_ok=True)
    result = deploy(host, data_only=data_only)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "matchers=1 handlers=1" in result.stdout
    assert (host / "data" / MAINLINE).read_bytes() == (ROOT / "data" / MAINLINE).read_bytes()
    backup_root = (host / "data" if data_only else host) / ".xiuxian3/backups"
    backups = list(backup_root.glob("deploy-*"))
    assert len(backups) == 1
    assert (backups[0] / "data" / MAINLINE).read_bytes() == old
    assert json.loads((backups[0] / "deployment.json").read_text())["status"] == "complete"
    preserved(host)
    repeated = deploy(host, data_only=data_only)
    assert repeated.returncode == 0, repeated.stdout + repeated.stderr
    assert "种子更新 0 个" in repeated.stdout
    preserved(host)


@pytest.mark.parametrize("data_only", [False, True])
def test_custom_title_only_conflict_rolls_back_source_toml_and_seeds(host: Path, data_only: bool) -> None:
    custom = old_official_mainline() + b"\n"
    (host / "data" / MAINLINE).write_bytes(custom)
    missing = host / "data/技能/技能.json"
    missing.unlink()
    if data_only:
        shutil.copytree(ROOT / "nonebot_plugin_xiuxian_3", host / "src/plugins/nonebot_plugin_xiuxian_3", dirs_exist_ok=True)
    previous_source = (host / "src/plugins/nonebot_plugin_xiuxian_3/__init__.py").read_bytes()
    previous_toml = (host / "pyproject.toml").read_bytes()
    result = deploy(host, data_only=data_only)
    assert result.returncode == 1
    assert "body is too short" in result.stdout + result.stderr
    assert "已回退" in result.stderr and "自定义" in result.stderr
    assert (host / "data" / MAINLINE).read_bytes() == custom
    assert not missing.exists()
    assert (host / "pyproject.toml").read_bytes() == previous_toml
    assert (host / "src/plugins/nonebot_plugin_xiuxian_3/__init__.py").read_bytes() == previous_source
    backup_root = (host / "data" if data_only else host) / ".xiuxian3/backups"
    journal = next(backup_root.glob("deploy-*/deployment.json"))
    assert json.loads(journal.read_text())["status"] == "rolled_back"
    preserved(host)


def test_valid_user_mainline_is_preserved_not_replaced(host: Path) -> None:
    custom = (ROOT / "data" / MAINLINE).read_bytes() + b"\n"
    (host / "data" / MAINLINE).write_bytes(custom)
    result = deploy(host)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (host / "data" / MAINLINE).read_bytes() == custom
    preserved(host)


def test_malformed_preserved_json_fails_inside_transaction_and_restores_official_seed(host: Path) -> None:
    old = old_official_mainline()
    (host / "data" / MAINLINE).write_bytes(old)
    (host / "data/custom.json").write_bytes(b'{"unfinished":')
    previous_toml = (host / "pyproject.toml").read_bytes()
    previous_source = (host / "src/plugins/nonebot_plugin_xiuxian_3/__init__.py").read_bytes()
    result = deploy(host)
    assert result.returncode == 1
    assert "JSON 有语法冲突" in result.stderr and "已回退" in result.stderr
    assert (host / "data" / MAINLINE).read_bytes() == old
    assert (host / "data/custom.json").read_bytes() == b'{"unfinished":'
    assert (host / "pyproject.toml").read_bytes() == previous_toml
    assert (host / "src/plugins/nonebot_plugin_xiuxian_3/__init__.py").read_bytes() == previous_source


def test_migration_manifest_targets_match_current_official_seeds() -> None:
    manifest = json.loads((ROOT / "scripts/seed_migrations.json").read_text(encoding="utf-8"))
    assert MAINLINE.as_posix() in manifest
    for relative, rule in manifest.items():
        assert hashlib.sha256((ROOT / "data" / relative).read_bytes()).hexdigest() == rule["new_sha256"]
        assert all(re.fullmatch(r"[0-9a-f]{64}", old) for old in rule["old_sha256"])
        assert all(re.fullmatch(r"[0-9a-f]{40}:data/.+\.json", provenance) for provenance in rule["old_sha256"].values())
