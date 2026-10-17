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
    # Reverse only the guard.5-protect.6, void_archive.recorder.1-return.8 and
    # lane.<lane>.chapter.01-10 content deltas; pin the patrol blob.
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
        "void_archive.recorder.1",
        "void_archive.recorder.2",
        "void_archive.recorder.3",
        "void_archive.recorder.4",
        "void_archive.recorder.5",
        "void_archive.recorder.6",
        "void_archive.recorder.7",
        "void_archive.recorder.8",
        "void_archive.escort.1",
        "void_archive.escort.2",
        "void_archive.escort.3",
        "void_archive.escort.4",
        "void_archive.escort.5",
        "void_archive.escort.6",
        "void_archive.escort.7",
        "void_archive.escort.8",
        "void_archive.return.1",
        "void_archive.return.2",
        "void_archive.return.3",
        "void_archive.return.4",
        "void_archive.return.5",
        "void_archive.return.6",
        "void_archive.return.7",
        "void_archive.return.8",
        "lane.builder.chapter.01",
        "lane.builder.chapter.02",
        "lane.builder.chapter.03",
        "lane.builder.chapter.04",
        "lane.builder.chapter.05",
        "lane.builder.chapter.06",
        "lane.builder.chapter.07",
        "lane.builder.chapter.08",
        "lane.builder.chapter.09",
        "lane.builder.chapter.10",
        "lane.witness.chapter.01",
        "lane.witness.chapter.02",
        "lane.witness.chapter.03",
        "lane.witness.chapter.04",
        "lane.witness.chapter.05",
        "lane.witness.chapter.06",
        "lane.witness.chapter.07",
        "lane.witness.chapter.08",
        "lane.witness.chapter.09",
        "lane.witness.chapter.10",
        "lane.traveler.chapter.01",
        "lane.traveler.chapter.02",
        "lane.traveler.chapter.03",
        "lane.traveler.chapter.04",
        "lane.traveler.chapter.05",
        "lane.traveler.chapter.06",
        "lane.traveler.chapter.07",
        "lane.traveler.chapter.08",
        "lane.traveler.chapter.09",
        "lane.traveler.chapter.10",
    ):
        start = text.index(f'      "key": "{key}"')
        try:
            end = text.index("\n    },", start)
        except ValueError:
            # The final record of the file closes without a trailing comma.
            end = text.index("\n    }\n", start)
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
                tail = key in (
                    "chapter.4.stage.3",
                    "domain_frontier.protect.6",
                    "void_archive.return.8",
                    "lane.builder.chapter.10",
                    "lane.witness.chapter.10",
                    "lane.traveler.chapter.10",
                )
                assert count == (0 if tail else 1)
            else:
                assert count == 1
        if key == "lane.builder.chapter.10":
            section = section.replace(
                '      "required_realm": "dao_union",\n      "required_layer": 6,\n',
                '      "required_realm": "void_refining",\n      "required_layer": 10,\n',
                1,
            )
            assert '"dao_union"' not in section
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


SECRET_REALM_FILE = Path("冒险/秘境专用.json")


def old_official_secret_realms() -> bytes:
    # The deployed eight-record blob before the time-fort/void-ruins
    # contentization: reverse only those two records from the current seed.
    document = json.loads((ROOT / "data" / SECRET_REALM_FILE).read_text(encoding="utf-8"))
    document["records"] = [
        record
        for record in document["records"]
        if record["key"]
        not in {"instance.secret_realm.time_fort", "instance.secret_realm.void_ruins"}
    ]
    blob = (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    rule = json.loads((ROOT / "scripts/seed_migrations.json").read_text(encoding="utf-8"))[
        SECRET_REALM_FILE.as_posix()
    ]
    assert hashlib.sha256(blob).hexdigest() in rule["old_sha256"], (
        "the reversed blob must equal the registered old official secret-realm seed"
    )
    return blob


def test_secret_realm_seed_migrates_and_custom_variants_are_preserved(host: Path) -> None:
    old = old_official_secret_realms()
    (host / "data" / SECRET_REALM_FILE).write_bytes(old)
    result = deploy(host)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "matchers=1 handlers=1" in result.stdout
    assert (host / "data" / SECRET_REALM_FILE).read_bytes() == (
        ROOT / "data" / SECRET_REALM_FILE
    ).read_bytes()
    backup_root = host / ".xiuxian3/backups"
    backups = list(backup_root.glob("deploy-*"))
    assert len(backups) == 1
    assert (backups[0] / "data" / SECRET_REALM_FILE).read_bytes() == old
    preserved(host)
    repeated = deploy(host)
    assert repeated.returncode == 0, repeated.stdout + repeated.stderr
    assert "种子更新 0 个" in repeated.stdout
    preserved(host)

    # A customized variant that is NOT the registered old official blob must
    # stay preserved as a custom/unknown seed, never silently overwritten.
    # It keeps every required record (valid content), only rewording a desc.
    custom_document = json.loads((ROOT / "data" / SECRET_REALM_FILE).read_text(encoding="utf-8"))
    custom_document["records"][0]["desc"] = "自定义描述"
    custom = (json.dumps(custom_document, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    (host / "data" / SECRET_REALM_FILE).write_bytes(custom)
    custom_result = deploy(host)
    assert custom_result.returncode == 0, custom_result.stdout + custom_result.stderr
    assert (host / "data" / SECRET_REALM_FILE).read_bytes() == custom
    preserved(host)
