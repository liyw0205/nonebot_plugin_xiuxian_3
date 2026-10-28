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


MATERIAL_FILE = Path("道具/材料.json")


def old_official_materials() -> bytes:
    # The deployed blob before the time-garden slice: reverse only the
    # time_trace item additions (the new record and its gathering_sources).
    document = json.loads((ROOT / "data" / MATERIAL_FILE).read_text(encoding="utf-8"))
    document["records"] = [
        record
        for record in document["records"]
        if record["key"] != "item.herb.time_trace"
    ]
    blob = (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    rule = json.loads((ROOT / "scripts/seed_migrations.json").read_text(encoding="utf-8"))[
        MATERIAL_FILE.as_posix()
    ]
    assert hashlib.sha256(blob).hexdigest() in rule["old_sha256"], (
        "the reversed blob must equal the registered old official material seed"
    )
    return blob


def test_material_seed_migrates_and_custom_variants_are_preserved(host: Path) -> None:
    old = old_official_materials()
    (host / "data" / MATERIAL_FILE).write_bytes(old)
    result = deploy(host)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "matchers=1 handlers=1" in result.stdout
    assert (host / "data" / MATERIAL_FILE).read_bytes() == (
        ROOT / "data" / MATERIAL_FILE
    ).read_bytes()
    backup_root = host / ".xiuxian3/backups"
    backups = list(backup_root.glob("deploy-*"))
    assert len(backups) == 1
    assert (backups[0] / "data" / MATERIAL_FILE).read_bytes() == old
    preserved(host)
    repeated = deploy(host)
    assert repeated.returncode == 0, repeated.stdout + repeated.stderr
    assert "种子更新 0 个" in repeated.stdout
    preserved(host)

    # A customized variant that is NOT the registered old official blob must
    # stay preserved as a custom/unknown seed, never silently overwritten.
    custom_document = json.loads((ROOT / "data" / MATERIAL_FILE).read_text(encoding="utf-8"))
    custom_document["records"][0]["desc"] = "自定义描述"
    custom = (json.dumps(custom_document, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    (host / "data" / MATERIAL_FILE).write_bytes(custom)
    custom_result = deploy(host)
    assert custom_result.returncode == 0, custom_result.stdout + custom_result.stderr
    assert (host / "data" / MATERIAL_FILE).read_bytes() == custom
    preserved(host)


LOCATION_FILE = Path("地图/地点.json")


def old_official_locations() -> bytes:
    # The deployed blob before the place-codex wiring: strip only the 17
    # codex_entry_key properties this slice added (the 16 pre-existing keys
    # and their properties stay untouched).
    added_keys = (
        "abyss_depths", "abyss_gate", "ancestral_lake", "ancient_domain",
        "archive_ruins", "array_hall", "boundary_realm", "dao_service",
        "first_route", "floating_boat", "mist_grotto", "mist_grotto_2",
        "sect_gate", "time_garden", "trade_port", "void_portal", "war_front",
    )
    text = (ROOT / "data" / LOCATION_FILE).read_text(encoding="utf-8")
    for tail in added_keys:
        pattern = f',\n      "codex_entry_key": "codex.place.{tail}"'
        assert pattern in text, tail
        text = text.replace(pattern, "", 1)
    blob = text.encode("utf-8")
    rule = json.loads((ROOT / "scripts/seed_migrations.json").read_text(encoding="utf-8"))[
        LOCATION_FILE.as_posix()
    ]
    assert hashlib.sha256(blob).hexdigest() in rule["old_sha256"], (
        "the reversed blob must equal the registered old official location seed"
    )
    return blob


def test_location_seed_migrates_and_custom_variants_are_preserved(host: Path) -> None:
    old = old_official_locations()
    (host / "data" / LOCATION_FILE).write_bytes(old)
    result = deploy(host)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "matchers=1 handlers=1" in result.stdout
    assert (host / "data" / LOCATION_FILE).read_bytes() == (
        ROOT / "data" / LOCATION_FILE
    ).read_bytes()
    backup_root = host / ".xiuxian3/backups"
    backups = list(backup_root.glob("deploy-*"))
    assert len(backups) == 1
    assert (backups[0] / "data" / LOCATION_FILE).read_bytes() == old
    preserved(host)
    repeated = deploy(host)
    assert repeated.returncode == 0, repeated.stdout + repeated.stderr
    assert "种子更新 0 个" in repeated.stdout
    preserved(host)

    # A customized variant that is NOT the registered old official blob must
    # stay preserved as a custom/unknown seed, never silently overwritten.
    custom_document = json.loads((ROOT / "data" / LOCATION_FILE).read_text(encoding="utf-8"))
    custom_document["records"][0]["desc"] = "自定义描述"
    custom = (json.dumps(custom_document, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    (host / "data" / LOCATION_FILE).write_bytes(custom)
    custom_result = deploy(host)
    assert custom_result.returncode == 0, custom_result.stdout + custom_result.stderr
    assert (host / "data" / LOCATION_FILE).read_bytes() == custom
    preserved(host)


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


MANIFEST_FILE = Path("内容清单.json")
TRADE_FILE = Path("经济/跨界贸易.json")


def old_official_manifest() -> bytes:
    # The manifest before the cross-realm trade file was registered: remove
    # only that entry from the current manifest.
    document = json.loads((ROOT / "data" / MANIFEST_FILE).read_text(encoding="utf-8"))
    document["files"] = [
        entry
        for entry in document["files"]
        if entry
        not in {
            "经济/跨界贸易.json",
            "经济/贸易许可.json",
            "生产/设施.json",
            "生产/终局配方.json",
            "任务/跨界任务.json",
            "特殊/竞技场.json",
            "功业/功业.json",
        }
    ]
    blob = (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    rule = json.loads((ROOT / "scripts/seed_migrations.json").read_text(encoding="utf-8"))[
        MANIFEST_FILE.as_posix()
    ]
    assert hashlib.sha256(blob).hexdigest() in rule["old_sha256"], (
        "the reversed manifest must equal the registered old official manifest seed"
    )
    return blob


def test_manifest_seed_migrates_when_the_trade_file_is_registered(host: Path) -> None:
    # An old official manifest without the trade file must migrate, and the
    # new data file must be installed alongside it (it does not exist yet).
    old = old_official_manifest()
    (host / "data" / MANIFEST_FILE).write_bytes(old)
    # The host fixture copies the full data tree; an old host predating the
    # trade slice would not have the new file, so remove it explicitly.
    (host / "data" / TRADE_FILE).unlink()
    (host / "data" / "经济/贸易许可.json").unlink()
    (host / "data" / "生产/设施.json").unlink()
    (host / "data" / "生产/终局配方.json").unlink()
    (host / "data" / "任务/跨界任务.json").unlink()
    (host / "data" / "特殊/竞技场.json").unlink()
    (host / "data" / "功业/功业.json").unlink()
    result = deploy(host)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "matchers=1 handlers=1" in result.stdout
    assert (host / "data" / MANIFEST_FILE).read_bytes() == (
        ROOT / "data" / MANIFEST_FILE
    ).read_bytes()
    assert (host / "data" / TRADE_FILE).read_bytes() == (
        ROOT / "data" / TRADE_FILE
    ).read_bytes()
    backup_root = host / ".xiuxian3/backups"
    backups = list(backup_root.glob("deploy-*"))
    assert len(backups) == 1
    assert (backups[0] / "data" / MANIFEST_FILE).read_bytes() == old
    preserved(host)
    repeated = deploy(host)
    assert repeated.returncode == 0, repeated.stdout + repeated.stderr
    assert "种子更新 0 个" in repeated.stdout
    preserved(host)


def old_official_trade_seed() -> bytes:
    document = json.loads((ROOT / "data" / TRADE_FILE).read_text(encoding="utf-8"))
    document["records"] = [
        record
        for record in document["records"]
        if record["key"]
        not in {
            "trade.xuantian_to_demon.array_sand",
            "trade.three_realms.soul_crystal",
        }
    ]
    blob = (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    rule = json.loads((ROOT / "scripts/seed_migrations.json").read_text(encoding="utf-8"))[
        TRADE_FILE.as_posix()
    ]
    assert hashlib.sha256(blob).hexdigest() in rule["old_sha256"]
    return blob


def test_known_official_trade_seed_migrates_with_backup_and_repeat_is_idempotent(
    host: Path,
) -> None:
    old = old_official_trade_seed()
    trade_path = host / "data" / TRADE_FILE
    trade_path.write_bytes(old)

    result = deploy(host)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "matchers=1 handlers=1" in result.stdout
    assert "种子更新 1 个" in result.stdout
    assert trade_path.read_bytes() == (ROOT / "data" / TRADE_FILE).read_bytes()
    backups = list((host / ".xiuxian3/backups").glob("deploy-*"))
    assert len(backups) == 1
    assert (backups[0] / "data" / TRADE_FILE).read_bytes() == old
    preserved(host)

    repeated = deploy(host)
    assert repeated.returncode == 0, repeated.stdout + repeated.stderr
    assert "种子更新 0 个" in repeated.stdout
    preserved(host)


def test_custom_trade_seed_is_preserved(host: Path) -> None:
    custom = old_official_trade_seed() + b"\n"
    trade_path = host / "data" / TRADE_FILE
    trade_path.write_bytes(custom)

    result = deploy(host)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "种子更新 0 个" in result.stdout
    assert trade_path.read_bytes() == custom
    preserved(host)


GUIDE_FILE = Path("引导/引导.json")


def old_official_guides() -> bytes:
    # The deployed three-guide blob before the cultivator tier: drop only the
    # three added records and the label/command/aliases fields this slice
    # introduced, leaving the mortal trio byte-identical.
    document = json.loads((ROOT / "data" / GUIDE_FILE).read_text(encoding="utf-8"))
    document["records"] = [
        record
        for record in document["records"]
        if record["key"]
        not in {
            "guide.mine_entry",
            "guide.dispatch_entry",
            "guide.secret_realm_entry",
        }
    ]
    for record in document["records"]:
        for field in ("label", "command", "aliases"):
            record.pop(field, None)
        if record["key"] == "guide.choose_service":
            # The cooking option was added with the cultivator tier; the prior
            # official blob listed only alchemy/artifice/formation.
            record["options"] = ["alchemy", "artifice", "formation"]
    blob = (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    rule = json.loads((ROOT / "scripts/seed_migrations.json").read_text(encoding="utf-8"))[
        GUIDE_FILE.as_posix()
    ]
    assert hashlib.sha256(blob).hexdigest() in rule["old_sha256"], (
        "the reversed blob must equal a registered old official guide seed"
    )
    return blob


def test_known_official_guide_seed_migrates_with_backup_and_repeat_is_idempotent(
    host: Path,
) -> None:
    old = old_official_guides()
    guide_path = host / "data" / GUIDE_FILE
    guide_path.write_bytes(old)

    result = deploy(host)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "matchers=1 handlers=1" in result.stdout
    assert "种子更新 1 个" in result.stdout
    assert guide_path.read_bytes() == (ROOT / "data" / GUIDE_FILE).read_bytes()
    backups = list((host / ".xiuxian3/backups").glob("deploy-*"))
    assert len(backups) == 1
    assert (backups[0] / "data" / GUIDE_FILE).read_bytes() == old
    preserved(host)

    repeated = deploy(host)
    assert repeated.returncode == 0, repeated.stdout + repeated.stderr
    assert "种子更新 0 个" in repeated.stdout
    preserved(host)


def test_custom_guide_seed_is_preserved(host: Path) -> None:
    # A curated variant that is NOT a registered official blob must survive as a
    # custom seed instead of being overwritten by the shipped guide table.
    custom_document = json.loads((ROOT / "data" / GUIDE_FILE).read_text(encoding="utf-8"))
    custom_document["records"][0]["desc"] = "自定义引导描述"
    custom = (json.dumps(custom_document, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    guide_path = host / "data" / GUIDE_FILE
    guide_path.write_bytes(custom)

    result = deploy(host)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "种子更新 0 个" in result.stdout
    assert guide_path.read_bytes() == custom
    preserved(host)


PASS_FILE = Path("道历/行卷.json")


def old_official_wayfaring_passes() -> bytes:
    # The deployed single-volume blob before the timetrace volume: the seed is
    # hand-formatted (inline source objects), so reverse by text instead of a
    # json re-dump that would reformat every untouched line.
    text = (ROOT / "data" / PASS_FILE).read_text(encoding="utf-8")
    start = text.index('    },\n    {\n      "key": "pass.timetrace"')
    closing = "      ]\n    }\n  ]\n}"
    end = text.index(closing, start)
    blob = (text[:start] + "    }\n  ]\n}" + text[end + len(closing):]).encode("utf-8")
    rule = json.loads((ROOT / "scripts/seed_migrations.json").read_text(encoding="utf-8"))[
        PASS_FILE.as_posix()
    ]
    assert hashlib.sha256(blob).hexdigest() in rule["old_sha256"], (
        "the reversed blob must equal the registered old official wayfaring seed"
    )
    return blob


def test_known_official_wayfaring_seed_migrates_with_backup_and_repeat_is_idempotent(
    host: Path,
) -> None:
    old = old_official_wayfaring_passes()
    pass_path = host / "data" / PASS_FILE
    pass_path.write_bytes(old)

    result = deploy(host)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "matchers=1 handlers=1" in result.stdout
    assert "种子更新 1 个" in result.stdout
    assert pass_path.read_bytes() == (ROOT / "data" / PASS_FILE).read_bytes()
    backups = list((host / ".xiuxian3/backups").glob("deploy-*"))
    assert len(backups) == 1
    assert (backups[0] / "data" / PASS_FILE).read_bytes() == old
    preserved(host)

    repeated = deploy(host)
    assert repeated.returncode == 0, repeated.stdout + repeated.stderr
    assert "种子更新 0 个" in repeated.stdout
    preserved(host)


def test_custom_wayfaring_seed_is_preserved(host: Path) -> None:
    # A host that curated its own volume table must keep it: the shipped
    # two-volume seed is not a registered old blob and must not overwrite it.
    custom_document = json.loads((ROOT / "data" / PASS_FILE).read_text(encoding="utf-8"))
    custom_document["records"][0]["desc"] = "自定义行卷描述"
    custom = (json.dumps(custom_document, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    pass_path = host / "data" / PASS_FILE
    pass_path.write_bytes(custom)

    result = deploy(host)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "种子更新 0 个" in result.stdout
    assert pass_path.read_bytes() == custom
    preserved(host)


SEED_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "official_seeds"
PLACE_CODEX_FILE = Path("图鉴/条目.json")
DAILY_TASK_FILE = Path("任务/任务.json")
PILL_FILE = Path("道具/丹药.json")
COMPANION_FILE = Path("灵兽/灵兽.json")
COMPANION_EVOLUTION_FILE = Path("灵兽/蜕变.json")
RECIPE_FILE = Path("生产/配方.json")

PLACE_CODEX_ADDED = frozenset(
    {
        "codex.place.sect_gate",
        "codex.place.mist_grotto",
        "codex.place.abyss_gate",
        "codex.place.trade_port",
        "codex.place.dao_service",
        "codex.place.array_hall",
        "codex.place.ancient_domain",
        "codex.place.abyss_depths",
        "codex.place.ancestral_lake",
        "codex.place.void_portal",
        "codex.place.first_route",
        "codex.place.archive_ruins",
        "codex.place.time_garden",
        "codex.place.war_front",
        "codex.place.boundary_realm",
        "codex.place.floating_boat",
        "codex.place.mist_grotto_2",
    }
)


def _registered_old_blob(relative: Path, blob: bytes) -> bytes:
    """Pin a reconstructed or archived blob against the migration table."""

    rule = json.loads((ROOT / "scripts/seed_migrations.json").read_text(encoding="utf-8"))[
        relative.as_posix()
    ]
    assert hashlib.sha256(blob).hexdigest() in rule["old_sha256"], (
        f"the reversed blob must equal a registered old official seed: {relative}"
    )
    return blob


def _without_records(relative: Path, keys: frozenset[str]) -> bytes:
    document = json.loads((ROOT / "data" / relative).read_text(encoding="utf-8"))
    document["records"] = [
        record for record in document["records"] if record["key"] not in keys
    ]
    blob = (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    return _registered_old_blob(relative, blob)


def old_official_place_codex() -> bytes:
    return _without_records(PLACE_CODEX_FILE, PLACE_CODEX_ADDED)


def old_official_daily_tasks() -> bytes:
    # The daily slice reserialised the whole board, so the deployed blob is
    # archived verbatim instead of reconstructed from the current formatting.
    return _registered_old_blob(
        DAILY_TASK_FILE, (SEED_FIXTURES / "daily_tasks.json").read_bytes()
    )


def old_official_pills() -> bytes:
    # Reserialised by the time-craft slice; see old_official_daily_tasks.
    return _registered_old_blob(
        PILL_FILE, (SEED_FIXTURES / "pills.json").read_bytes()
    )


def old_official_companions() -> bytes:
    # Reserialised by the companion-evolution slice; see old_official_daily_tasks.
    return _registered_old_blob(
        COMPANION_FILE, (SEED_FIXTURES / "companions.json").read_bytes()
    )


def old_official_companion_evolutions() -> bytes:
    return _without_records(
        COMPANION_EVOLUTION_FILE,
        frozenset(
            {
                "beast.evolution.iron_rat_2",
                "mount.evolution.bamboo_deer_1",
            }
        ),
    )


def old_official_recipes() -> bytes:
    return _without_records(
        RECIPE_FILE, frozenset({"recipe.pill.time_ward", "recipe.array.time_anchor"})
    )


@pytest.mark.parametrize(
    "reverse",
    [
        old_official_place_codex,
        old_official_daily_tasks,
        old_official_pills,
        old_official_companions,
        old_official_companion_evolutions,
        old_official_recipes,
    ],
)
def test_goal_a_i_seed_reverse_helpers_match_registered_old_blobs(reverse) -> None:
    # Every seed file the A-I goals changed must be upgradeable from the blob
    # that preceded the change; the helper asserts the digest itself.
    assert reverse()


A_I_CHANGED_SEEDS = (
    "任务/任务.json",
    "冒险/秘境专用.json",
    "图鉴/条目.json",
    "地图/地点.json",
    "引导/引导.json",
    "灵兽/灵兽.json",
    "灵兽/蜕变.json",
    "生产/配方.json",
    "经济/跨界贸易.json",
    "道具/丹药.json",
    "道历/行卷.json",
)


def test_goal_a_i_changed_seeds_all_declare_migration_rules() -> None:
    rules = json.loads(
        (ROOT / "scripts/seed_migrations.json").read_text(encoding="utf-8")
    )
    missing = [relative for relative in A_I_CHANGED_SEEDS if relative not in rules]
    assert missing == [], "changed seeds without a migration rule: " + ", ".join(missing)


def test_content_manifest_covers_every_data_file() -> None:
    manifest = json.loads((ROOT / "data" / MANIFEST_FILE).read_text(encoding="utf-8"))
    listed = set(manifest["files"])
    on_disk = {
        path.relative_to(ROOT / "data").as_posix()
        for path in (ROOT / "data").rglob("*.json")
    }
    # The manifest describes the table it belongs to but does not list itself.
    on_disk.discard(MANIFEST_FILE.as_posix())
    assert sorted(on_disk - listed) == []
    assert sorted(listed - on_disk) == []


def test_known_official_place_codex_seed_migrates_with_backup_and_repeat_is_idempotent(
    host: Path,
) -> None:
    # The codex entries and the location wiring shipped together, so an old
    # host carries the previous blob of both files; migrating only one of them
    # would leave 17 dangling codex references.
    old = old_official_place_codex()
    old_locations = old_official_locations()
    codex_path = host / "data" / PLACE_CODEX_FILE
    location_path = host / "data" / LOCATION_FILE
    codex_path.write_bytes(old)
    location_path.write_bytes(old_locations)

    result = deploy(host)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "matchers=1 handlers=1" in result.stdout
    assert "种子更新 2 个" in result.stdout
    assert codex_path.read_bytes() == (ROOT / "data" / PLACE_CODEX_FILE).read_bytes()
    assert location_path.read_bytes() == (ROOT / "data" / LOCATION_FILE).read_bytes()
    backups = list((host / ".xiuxian3/backups").glob("deploy-*"))
    assert len(backups) == 1
    assert (backups[0] / "data" / PLACE_CODEX_FILE).read_bytes() == old
    assert (backups[0] / "data" / LOCATION_FILE).read_bytes() == old_locations
    preserved(host)

    repeated = deploy(host)
    assert repeated.returncode == 0, repeated.stdout + repeated.stderr
    assert "种子更新 0 个" in repeated.stdout
    preserved(host)


def test_custom_place_codex_seed_is_preserved(host: Path) -> None:
    custom_document = json.loads(
        (ROOT / "data" / PLACE_CODEX_FILE).read_text(encoding="utf-8")
    )
    custom_document["records"][0]["desc"] = "自定义图鉴描述"
    custom = (json.dumps(custom_document, ensure_ascii=False, indent=2) + "\n").encode(
        "utf-8"
    )
    codex_path = host / "data" / PLACE_CODEX_FILE
    codex_path.write_bytes(custom)

    result = deploy(host)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "种子更新 0 个" in result.stdout
    assert codex_path.read_bytes() == custom
    preserved(host)
