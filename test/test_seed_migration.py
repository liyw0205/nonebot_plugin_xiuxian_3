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

    def replace_record_field(key: str, pattern: str, replacement: str) -> None:
        nonlocal text
        start = text.index(f'      "key": "{key}"')
        end = text.index("\n    },", start)
        flags = re.M | (re.S if ".*?" in pattern else 0)
        section, count = re.subn(pattern, replacement, text[start:end], count=1, flags=flags)
        assert count == 1, (key, pattern)
        text = text[:start] + section + text[end:]

    replace_record_field("chapter.1.stage.3", r'^      "required_realm":.*$', '      "required_realm": "qi_sensing",')
    replace_record_field("chapter.1.stage.3", r'^      "required_layer":.*$', '      "required_layer": 3,')
    replace_record_field(
        "chapter.1.stage.3",
        r'^      "actions": \[\n.*?^      \],',
        '      "actions": [\n'
        '        {"command": "前往", "argument": "雾隐洞天一层", "description": "达到气府境四层并持有雾隐洞天一层凭证后启程。"},\n'
        '        {"command": "开始探索", "argument": "雾隐洞天探索", "description": "完成自动遭遇战并结算探索，战胜守卫或雾灵才算守门成功。"}\n'
        '      ],',
    )
    replace_record_field(
        "chapter.2.stage.1",
        r'^      "body":.*$',
        '      "body": "雾隐线索带你回到青石镇，药铺掌柜正守着一批迟迟未到的止血草。镇里的商路不靠一句承诺运转：先把委托接进自己的委托簿，再从公开采集或已有库存备齐三株止血草，最后在订单仍有效时交付。掌柜会把这次交货记入镇务账册，商路因此向你开放；材料不足或订单过期不会吞掉物品，补齐后仍可接当天的其他委托重试。",',
    )
    replace_record_field(
        "chapter.2.stage.1",
        r'^      "actions": \[\n.*?^      \],',
        '      "actions": [\n'
        '        {"command": "查看委托", "argument": "城镇委托", "description": "先查看当日公开订单，再接取止血草供应。"},\n'
        '        {"command": "交付委托", "argument": "止血草供应", "description": "接取订单后交付三株止血草，结算事务会同时写入名望与信誉。"}\n'
        '      ],',
    )
    replace_record_field(
        "chapter.2.stage.1",
        r'^        "message":.*$',
        '        "message": "委托材料不足或订单过期时保留主线进行中，不发放商路奖励；接取并交付新的公开订单后可再次结算。"',
    )
    replace_record_field(
        "chapter.2.stage.1",
        r'^      "prerequisites":.*$',
        '      "prerequisites": ["chapter.1.stage.3", "livelihood.town_commission.delivered"],',
    )
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
        "chapter.5.stage.1",
        "chapter.5.stage.2",
        "chapter.5.stage.3",
        "chapter.6.stage.1",
        "chapter.6.stage.2",
        "chapter.6.stage.3",
        "chapter.7.stage.1",
        "chapter.7.stage.2",
        "chapter.7.stage.3",
        "chapter.8.stage.1",
        "chapter.8.stage.2",
        "chapter.8.stage.3",
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
                # Only story-tail stages legitimately omit the ahead reference. The
                # archive returner now hands off to the optional supply lane, so the
                # historical fixture must remove that link while reconstructing its old tail.
                tail = key in (
                    "chapter.8.stage.3",
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
    # The three grotto-volume stages were appended after the previous last record,
    # and appending turned that record's closing brace into a comma. Truncating at
    # the previous last record restores the original tail exactly.
    last = text.index('      "key": "lane.traveler.chapter.10"')
    last_end = text.index("\n    }", last) + len("\n    }")
    text = text[:last_end] + "\n  ]\n}\n"
    # chapter.4.stage.3 gained a forward link in this slice; the old blob has none.
    link = text.index('      "key": "chapter.4.stage.3"')
    link_end = text.index("\n    }", link)
    linked = text[link:link_end]
    assert '\n      "next_stage_key": "chapter.5.stage.1",' in linked
    text = text[:link] + linked.replace('\n      "next_stage_key": "chapter.5.stage.1",', '', 1) + text[link_end:]
    blob = text.encode("utf-8")
    assert hashlib.sha256(blob).hexdigest() == OLD_SHA
    return blob


@pytest.fixture
def host(tmp_path: Path) -> Path:
    target = tmp_path / "host"
    target.mkdir()
    shutil.copyfile(ROOT / "examples/nonebot/pyproject.toml", target / "pyproject.toml")
    shutil.copytree(ROOT / "data", target / "data", ignore=shutil.ignore_patterns("*.sqlite3*", "*.db*"))
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


@pytest.mark.parametrize("custom", [False, True])
def test_cultivation_seed_upgrade_preserves_custom_and_repeats(host: Path, custom: bool) -> None:
    relative = Path("生活/生活.json")
    old = (ROOT / "test/fixtures/official_seeds/livelihood_pre_reachability.json").read_bytes()
    rule = json.loads((ROOT / "scripts/seed_migrations.json").read_text())[relative.as_posix()]
    assert hashlib.sha256(old).hexdigest() in rule["old_sha256"]
    original = (ROOT / "data" / relative).read_bytes() + b"\n" if custom else old
    path = host / "data" / relative
    path.write_bytes(original)
    result = deploy(host)
    assert result.returncode == 0, result.stdout + result.stderr
    assert path.read_bytes() == (original if custom else (ROOT / "data" / relative).read_bytes())
    backups = list((host / ".xiuxian3/backups").glob("deploy-*"))
    assert len(backups) == 1
    if not custom:
        assert (backups[0] / "data" / relative).read_bytes() == original
    repeated = deploy(host)
    assert repeated.returncode == 0, repeated.stdout + repeated.stderr
    assert "种子更新 0 个" in repeated.stdout
    preserved(host)


def pre_construction_livelihood() -> bytes:
    # Exact bytes from 208a16bc47e1d90cd0dd8e712f77efd76519f3f8:data/生活/生活.json.
    blob = (ROOT / "test/fixtures/official_seeds/construction_v0136_livelihood.json").read_bytes()
    assert hashlib.sha256(blob).hexdigest() == "1eaef8b80ac72c1fc351e734f6aba2ff25adb880ed5351e1130c9e129c9644eb"
    return blob


@pytest.mark.parametrize("custom", [False, True])
def test_construction_seed_upgrade_from_v0136_backup_repeat_and_custom(host: Path, custom: bool) -> None:
    path = host / "data/生活/生活.json"
    old = pre_construction_livelihood()
    original = old + b"\n" if custom else old
    path.write_bytes(original)
    result = deploy(host)
    assert result.returncode == 0, result.stdout + result.stderr
    assert path.read_bytes() == (original if custom else (ROOT / "data/生活/生活.json").read_bytes())
    backups = list((host / ".xiuxian3/backups").glob("deploy-*"))
    assert len(backups) == 1
    if not custom:
        assert (backups[0] / "data/生活/生活.json").read_bytes() == old
    repeated = deploy(host)
    assert repeated.returncode == 0, repeated.stdout + repeated.stderr
    assert "种子更新 0 个" in repeated.stdout
    preserved(host)


def test_custom_invalid_construction_phase_rolls_back_installed_source(host: Path) -> None:
    path = host / "data/生活/生活.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    project = next(row for row in document["records"] if row["key"] == "project.ironwood_bridge")
    project["stages"][0]["service_points"] = True
    original = json.dumps(document, ensure_ascii=False).encode("utf-8")
    path.write_bytes(original)
    old_source = (host / "src/plugins/nonebot_plugin_xiuxian_3/__init__.py").read_bytes()
    result = deploy(host)
    assert result.returncode != 0
    assert "project stage" in result.stdout + result.stderr
    assert path.read_bytes() == original
    assert (host / "src/plugins/nonebot_plugin_xiuxian_3/__init__.py").read_bytes() == old_source
    preserved(host)


SECRET_REALM_FILE = Path("冒险/秘境专用.json")


@pytest.mark.parametrize("custom", [False, True])
def test_fieldwork_seeds_upgrade_from_v0134_and_preserve_custom(host: Path, custom: bool) -> None:
    files = {
        "生活/生活.json": "fieldwork_v0134_livelihood.json",
        "战斗/敌人.json": "fieldwork_v0134_enemies.json",
        "战斗/遭遇池.json": "fieldwork_v0134_encounters.json",
    }
    manifest = json.loads((ROOT / "scripts/seed_migrations.json").read_text())
    originals = {}
    for relative, fixture in files.items():
        original = (ROOT / "test/fixtures/official_seeds" / fixture).read_bytes()
        assert hashlib.sha256(original).hexdigest() in manifest[relative]["old_sha256"]
        originals[relative] = original + (b"\n" if custom else b"")
        (host / "data" / relative).write_bytes(originals[relative])
    result = deploy(host)
    assert result.returncode == 0, result.stdout + result.stderr
    backup = next((host / ".xiuxian3/backups").glob("deploy-*"))
    for relative in files:
        assert (host / "data" / relative).read_bytes() == (originals[relative] if custom else (ROOT / "data" / relative).read_bytes())
        if not custom:
            assert (backup / "data" / relative).read_bytes() == originals[relative]
    repeated = deploy(host)
    assert repeated.returncode == 0 and "种子更新 0 个" in repeated.stdout, repeated.stdout + repeated.stderr
    preserved(host)


COMMON_SECRET_REALM_FILE = Path("冒险/秘境.json")


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
    # The deployed blob before the time-garden slice: reverse the time_trace
    # item additions and the later cloud-rice crop-chain items.
    document = json.loads((ROOT / "data" / MATERIAL_FILE).read_text(encoding="utf-8"))
    document["records"] = [
        record
        for record in document["records"]
        if record["key"]
        not in {
            "item.herb.time_trace",
            "item.grain.cloud_rice",
            "item.food.cloud_rice_meal",
            "item.material.ward_plate",
        }
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
    # The discoverability slice rewrote exploration actions on existing records.
    action_reverts = (
        ('      "actions": ["read_entry_requirements", "explore.cloud_city_patrol", "explore.cloud_city_escort"]', '      "actions": [\n        "read_entry_requirements"\n      ]'),
        ('      "actions": ["event.boundary_rift", "explore.boundary_rift"]', '      "actions": ["event.boundary_rift"]'),
        ('      "actions": ["progression.trial.dao_origin", "explore.dao_origin"]', '      "actions": ["progression.trial.dao_origin"]'),
        ('      "actions": ["world.intro.demon", "explore.demon_threshold"]', '      "actions": [\n        "world.intro.demon"\n      ]'),
        ('      "actions": ["progression.tribulation_trial", "explore.tribulation_echo"]', '      "actions": ["progression.tribulation_trial"]'),
        ('      "actions": ["world.enter_void_route"]', '      "actions": ["world.enter_void_route", "explore.void_route"]'),
        # The tending slice listed 灵田巡护 on the spirit field, so the reversed
        # blob drops that one action line again.
        (
            '        "explore.spring_gather",\n        "explore.spirit_field_tending",',
            '        "explore.spring_gather",',
        ),
        # The trade-endpoint slice registered one secret realm on each trade
        # location, so the reversed blob must drop those two entries again.
        (
            '      "actions": [\n        "economy.trade.xuantian_to_demon",\n        "production.demon_contract",\n        "instance.secret_realm.abyss_market_run"\n      ]',
            '      "actions": [\n        "economy.trade.xuantian_to_demon",\n        "production.demon_contract"\n      ]',
        ),
        (
            '      "actions": [\n        "economy.trade.three_realms",\n        "instance.secret_realm.trade_port_convoy"\n      ]',
            '      "actions": [\n        "economy.trade.three_realms"\n      ]',
        ),
        # The inert-location slice registered one exploration mode on the array
        # hall and one on the war front, so the reversed blob drops both.
        (
            '      "actions": [\n        "progression.recover_foundation_shock",\n        "explore.array_hall_drill"\n      ]',
            '      "actions": [\n        "progression.recover_foundation_shock"\n      ]',
        ),
        (
            '      "actions": ["event.demon_invasion", "explore.war_front_patrol"]',
            '      "actions": ["event.demon_invasion"]',
        ),
    )
    for new_line, old_line in action_reverts:
        assert new_line in text, new_line
        text = text.replace(new_line, old_line, 1)
    for tail in added_keys:
        pattern = f',\n      "codex_entry_key": "codex.place.{tail}"'
        assert pattern in text, tail
        text = text.replace(pattern, "", 1)
    # The depths slice also opened two terminal locations; an old host still
    # has them locked, so the reversed blob must flip both statuses back.
    for key in ("cave.ancient_domain", "demon.abyss_depths"):
        end = text.index(f'"key": "{key}"')
        start = text.rindex("    {", 0, end)
        block = text[start:end]
        assert block.count('"status": "open"') == 1, key
        text = (
            text[:start]
            + block.replace('"status": "open"', '"status": "locked"', 1)
            + text[end:]
        )
    # The endgame-arena slice appended one terminal location; an old host does
    # not know it, so the reversed blob must drop the whole record.
    marker = ',\n    {\n      "name": "终局天榜"'
    arena_start = text.index(marker)
    arena_end = text.index('\n  ],\n  "schema"', arena_start)
    text = text[:arena_start] + text[arena_end:]
    assert "location.final_arena" not in text
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
            "经济/虚空集市.json",
            "经济/贸易许可.json",
            "生产/设施.json",
            "生产/终局配方.json",
            "任务/跨界任务.json",
            "特殊/竞技场.json",
            "特殊/终局天榜.json",
            "功业/功业.json",
            "道历/道号.json",
            "道历/道契.json",
            "道历/七日目标.json",
            "战斗/渡劫.json",
            "社交/道统据点.json",
            "社交/道统路线.json",
            "事件/飞升日.json",
            "社交/道侣协作.json",
            "经济/虚空物资寄售.json",
            "灵兽/互动.json",
            "道具/转修令.json",
            "道途/切换.json",
            "道具/重构令.json",
            "道途/重构.json",
            "道途/辅修切换.json",
            "养成/道脉重置.json",
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
    (host / "data" / "经济/虚空集市.json").unlink()
    (host / "data" / "经济/贸易许可.json").unlink()
    (host / "data" / "生产/设施.json").unlink()
    (host / "data" / "生产/终局配方.json").unlink()
    (host / "data" / "任务/跨界任务.json").unlink()
    (host / "data" / "特殊/竞技场.json").unlink()
    (host / "data" / "特殊/终局天榜.json").unlink()
    (host / "data" / "功业/功业.json").unlink()
    (host / "data" / "道历/道号.json").unlink()
    (host / "data" / "道历/道契.json").unlink()
    (host / "data" / "道历/七日目标.json").unlink()
    (host / "data" / "战斗/渡劫.json").unlink()
    (host / "data" / "灵兽/互动.json").unlink()
    (host / "data" / "道具/转修令.json").unlink()
    (host / "data" / "道途/切换.json").unlink()
    (host / "data" / "道具/重构令.json").unlink()
    (host / "data" / "道途/重构.json").unlink()
    (host / "data" / "道途/辅修切换.json").unlink()
    (host / "data" / "养成/道脉重置.json").unlink()
    result = deploy(host)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "matchers=1 handlers=1" in result.stdout
    assert (host / "data" / MANIFEST_FILE).read_bytes() == (
        ROOT / "data" / MANIFEST_FILE
    ).read_bytes()
    assert (host / "data" / TRADE_FILE).read_bytes() == (
        ROOT / "data" / TRADE_FILE
    ).read_bytes()
    assert (host / "data" / "灵兽/互动.json").read_bytes() == (
        ROOT / "data" / "灵兽/互动.json"
    ).read_bytes()
    assert (host / "data" / "道具/转修令.json").read_bytes() == (
        ROOT / "data" / "道具/转修令.json"
    ).read_bytes()
    assert (host / "data" / "道途/切换.json").read_bytes() == (
        ROOT / "data" / "道途/切换.json"
    ).read_bytes()
    assert (host / "data" / "道具/重构令.json").read_bytes() == (
        ROOT / "data" / "道具/重构令.json"
    ).read_bytes()
    assert (host / "data" / "道途/重构.json").read_bytes() == (
        ROOT / "data" / "道途/重构.json"
    ).read_bytes()
    assert (host / "data" / "道途/辅修切换.json").read_bytes() == (
        ROOT / "data" / "道途/辅修切换.json"
    ).read_bytes()
    assert (host / "data" / "养成/道脉重置.json").read_bytes() == (
        ROOT / "data" / "养成/道脉重置.json"
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
            "guide.seeker_path_hint",
            "guide.seeker_sect_gate",
            "guide.idle_entry",
            "guide.qi_gathering_breath",
            "guide.qi_gathering_ascent",
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


def test_pre_refuge_mainline_migrates_with_real_official_fixture(host: Path) -> None:
    old = (SEED_FIXTURES / "mainline_pre_refuge.json").read_bytes()
    manifest = json.loads((ROOT / "scripts/seed_migrations.json").read_text(encoding="utf-8"))
    rule = manifest[MAINLINE.as_posix()]
    assert hashlib.sha256(old).hexdigest() in rule["old_sha256"]
    (host / "data" / MAINLINE).write_bytes(old)
    migrated = deploy(host)
    assert migrated.returncode == 0, migrated.stdout + migrated.stderr
    assert (host / "data" / MAINLINE).read_bytes() == (ROOT / "data" / MAINLINE).read_bytes()
    assert any(path.read_bytes() == old for path in host.glob(".xiuxian3/backups/deploy-*/data/剧情/主线.json"))
    preserved(host)


def test_custom_pre_refuge_mainline_is_preserved(host: Path) -> None:
    custom = (SEED_FIXTURES / "mainline_pre_refuge.json").read_bytes() + b"\n"
    (host / "data" / MAINLINE).write_bytes(custom)
    result = deploy(host)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (host / "data" / MAINLINE).read_bytes() == custom
    preserved(host)


BOUNTY_SOURCE_SEEDS = {
    Path("任务/悬赏.json"): "bounties_pre_reachability.json",
    Path("生产/配方.json"): "recipes_pre_reachability.json",
    Path("生活/生活.json"): "livelihood_pre_reachability.json",
}
PLACE_CODEX_FILE = Path("图鉴/条目.json")
DAILY_TASK_FILE = Path("任务/任务.json")
PILL_FILE = Path("道具/丹药.json")
COMPANION_FILE = Path("灵兽/灵兽.json")
COMPANION_EVOLUTION_FILE = Path("灵兽/蜕变.json")
RECIPE_FILE = Path("生产/配方.json")

PLACE_CODEX_ADDED = frozenset(
    {
        "codex.story.herb_vale_gather",
        "codex.story.ironwood_gather",
        "codex.story.basalt_sifting",
        "codex.story.spring_gleaning",
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
        "codex.place.final_arena",
        "codex.escort.cloud_city_escort",
        "codex.escort.spirit_field_tending",
        "codex.story.xuantian.road.wanderer",
        "codex.route.seeker_herb_tending",
        "codex.story.xuantian.road.sojourner",
        "codex.escort.array_hall_drill",
        "codex.escort.war_front_patrol",
        "codex.creature.array_hall_sentry",
        "codex.creature.war_front_vanguard",
        "codex.creature.jade_rat",
        "codex.creature.cloud_elk",
        "codex.material.ward_plate",
        "codex.material.recipe_basic",
        "codex.material.manual_basic",
        "codex.material.demon_contract",
        "codex.material.demon_abyss_echo",
        "codex.material.beast_bloodline",
        "codex.material.mist_cave_route",
        "codex.story.companion_old_trail.1",
        "codex.story.companion_old_trail.2",
        "codex.story.companion_old_trail.3",
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


def test_bounty_source_seeds_upgrade_together_with_backup_and_idempotency(host: Path) -> None:
    old = {
        relative: _registered_old_blob(relative, (SEED_FIXTURES / fixture).read_bytes())
        for relative, fixture in BOUNTY_SOURCE_SEEDS.items()
    }
    for relative, blob in old.items():
        (host / "data" / relative).write_bytes(blob)
    result = deploy(host)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "matchers=1 handlers=1" in result.stdout
    backups = list((host / ".xiuxian3/backups").glob("deploy-*"))
    assert len(backups) == 1
    for relative, blob in old.items():
        assert (host / "data" / relative).read_bytes() == (ROOT / "data" / relative).read_bytes()
        assert (backups[0] / "data" / relative).read_bytes() == blob
    preserved(host)
    repeated = deploy(host)
    assert repeated.returncode == 0, repeated.stdout + repeated.stderr
    assert "种子更新 0 个" in repeated.stdout
    preserved(host)


def test_unknown_bounty_source_seeds_are_preserved(host: Path) -> None:
    custom = {
        relative: (ROOT / "data" / relative).read_bytes() + b"\n"
        for relative in BOUNTY_SOURCE_SEEDS
    }
    for relative, blob in custom.items():
        (host / "data" / relative).write_bytes(blob)
    result = deploy(host)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "种子更新 0 个" in result.stdout
    for relative, blob in custom.items():
        assert (host / "data" / relative).read_bytes() == blob
    preserved(host)


def test_unknown_livelihood_missing_story_source_fails_and_rolls_back(host: Path) -> None:
    path = host / "data/生活/生活.json"
    custom = (SEED_FIXTURES / "livelihood_pre_reachability.json").read_bytes() + b"\n"
    path.write_bytes(custom)
    previous_source = (host / "src/plugins/nonebot_plugin_xiuxian_3/__init__.py").read_bytes()
    previous_toml = (host / "pyproject.toml").read_bytes()
    result = deploy(host)
    assert result.returncode != 0
    assert "claim_companion_patrol references unknown idle route" in result.stdout + result.stderr
    assert "已回退" in result.stderr
    assert path.read_bytes() == custom
    assert (host / "src/plugins/nonebot_plugin_xiuxian_3/__init__.py").read_bytes() == previous_source
    assert (host / "pyproject.toml").read_bytes() == previous_toml
    preserved(host)


def _without_records(relative: Path, keys: frozenset[str], *, source: Path | None = None) -> bytes:
    document = json.loads((source or ROOT / "data" / relative).read_text(encoding="utf-8"))
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
    # The archived blob predates the evolution codex entries this phase adds, so
    # it is used verbatim.
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
        RECIPE_FILE,
        frozenset(
            {
                "recipe.pill.time_ward",
                "recipe.array.time_anchor",
                "recipe.food.cloud_rice_meal",
                "recipe.array.war_front_ward",
            }
        ),
        source=SEED_FIXTURES / "recipes_pre_reachability.json",
    )


def old_official_common_secret_realms() -> bytes:
    # The seed is hand-formatted, so the deployed blob is archived verbatim;
    # removing the two new records from the current file would change spacing.
    return _registered_old_blob(
        COMMON_SECRET_REALM_FILE,
        (SEED_FIXTURES / "common_secret_realms.json").read_bytes(),
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
        old_official_common_secret_realms,
    ],
)
def test_goal_a_i_seed_reverse_helpers_match_registered_old_blobs(reverse) -> None:
    # Each registered legacy fixture must match its pre-migration blob digest.
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


def _historical_mainline_prefix(text: str, marker: int) -> str:
    """Rebuild a pre-slice blob without later chapter-nine records or fixes."""

    prefix = text[:marker]
    prefix, count = re.subn(
        r'    \{\n      "key": "chapter\.9\.stage\.4".*?\n    \},\n',
        "",
        prefix,
        count=1,
        flags=re.S,
    )
    assert count == 1
    prefix = prefix.replace(
        '{"command": "开始探索", "argument": "云城护送", "description": "在云城街巷开启护送探索，遭遇战由自动战斗结算。"}',
        '{"command": "探索", "argument": "云城护送", "description": "在云城街巷开启护送探索，遭遇战由自动战斗结算。"}',
    )
    return prefix.replace(
        '{"command": "开始探索", "argument": "雾隐洞天", "description": "在洞天内开启探索，结算时按奖池取得灵叶。"}',
        '{"command": "探索", "argument": "雾隐洞天", "description": "在洞天内开启探索，结算时按奖池取得灵叶。"}',
    )


def test_companion_old_trail_seeds_upgrade_together_and_preserve_custom(host: Path) -> None:
    mainline = (ROOT / "data" / MAINLINE).read_text(encoding="utf-8")
    marker = mainline.index('    {\n      "key": "companion_old_trail.1"')
    old_mainline = (
        _historical_mainline_prefix(mainline, marker).rstrip()[:-1] + "\n  ]\n}\n"
    ).encode("utf-8")
    assert hashlib.sha256(old_mainline).hexdigest() == "ad6aae6f0a4037c52c17ea17e902188bcca190676d455bca6a49fa178c4ed473"
    codex_file = Path("图鉴/条目.json")
    codex = (ROOT / "data" / codex_file).read_text(encoding="utf-8")
    old_codex, count = re.subn(
        r'    \{\n      "key": "codex\.story\.companion_old_trail\.[123]",.*?\n    \},\n',
        "", codex, flags=re.S,
    )
    assert count == 3
    old_codex_blob = old_codex.encode("utf-8")
    assert hashlib.sha256(old_codex_blob).hexdigest() == "898a3030272173423d2c55371beaf5a46fa73483fe06538aaf2c5723fcf1389f"
    old_blobs = {MAINLINE: old_mainline, codex_file: old_codex_blob}
    for relative, blob in old_blobs.items():
        (host / "data" / relative).write_bytes(blob)
    upgraded = deploy(host)
    assert upgraded.returncode == 0, upgraded.stdout + upgraded.stderr
    assert "种子更新 2 个" in upgraded.stdout
    backup = next((host / ".xiuxian3/backups").glob("deploy-*"))
    for relative, blob in old_blobs.items():
        assert (host / "data" / relative).read_bytes() == (ROOT / "data" / relative).read_bytes()
        assert (backup / "data" / relative).read_bytes() == blob
    preserved(host)
    repeated = deploy(host)
    assert repeated.returncode == 0, repeated.stdout + repeated.stderr
    assert "种子更新 0 个" in repeated.stdout
    for relative in old_blobs:
        document = json.loads((ROOT / "data" / relative).read_text(encoding="utf-8"))
        document["records"][0]["desc"] = "自定义旧兽道内容"
        custom = (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        (host / "data" / relative).write_bytes(custom)
        old_blobs[relative] = custom
    custom_deploy = deploy(host)
    assert custom_deploy.returncode == 0, custom_deploy.stdout + custom_deploy.stderr
    assert "种子更新 0 个" in custom_deploy.stdout
    assert all((host / "data" / relative).read_bytes() == blob for relative, blob in old_blobs.items())
    preserved(host)


def test_spring_supper_mainline_seed_upgrade_backup_repeat_and_custom_preservation(host: Path) -> None:
    text = (ROOT / "data" / MAINLINE).read_text(encoding="utf-8")
    marker = text.index('    {\n      "key": "spring_supper.1"')
    old = (
        _historical_mainline_prefix(text, marker).rstrip()[:-1] + "\n  ]\n}\n"
    ).encode("utf-8")
    assert hashlib.sha256(old).hexdigest() == "0ebe7d841042d1688778d1a19d7b640e5edaa621ecc9778989ae015cd1260fb8"
    _registered_old_blob(MAINLINE, old)
    path = host / "data" / MAINLINE
    path.write_bytes(old)
    result = deploy(host)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "种子更新 1 个" in result.stdout
    assert path.read_bytes() == (ROOT / "data" / MAINLINE).read_bytes()
    backup = next((host / ".xiuxian3/backups").glob("deploy-*"))
    assert (backup / "data" / MAINLINE).read_bytes() == old
    preserved(host)
    repeated = deploy(host)
    assert repeated.returncode == 0, repeated.stdout + repeated.stderr
    assert "种子更新 0 个" in repeated.stdout
    document = json.loads(text)
    stage = next(row for row in document["records"] if row["key"] == "spring_supper.1")
    stage["body"] += "阿禾把自家稻畦的水口另作了标记。"
    custom = (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    path.write_bytes(custom)
    custom_deploy = deploy(host)
    assert custom_deploy.returncode == 0, custom_deploy.stdout + custom_deploy.stderr
    assert "种子更新 0 个" in custom_deploy.stdout
    assert path.read_bytes() == custom
    preserved(host)


def _pre_ironwood_mainline() -> bytes:
    text = (ROOT / "data" / MAINLINE).read_text(encoding="utf-8")
    marker = text.index('    {\n      "key": "ironwood_craft.1"')
    old = (
        _historical_mainline_prefix(text, marker).rstrip()[:-1] + "\n  ]\n}\n"
    ).encode("utf-8")
    assert hashlib.sha256(old).hexdigest() == "bb15ca2fd397b5afb12c591ade83268ece040763c343a613665ec9db774eba9a"
    return _registered_old_blob(MAINLINE, old)


def test_ironwood_seed_upgrade_backup_repeat_and_custom_preservation(host: Path) -> None:
    old = _pre_ironwood_mainline()
    path = host / "data" / MAINLINE
    path.write_bytes(old)
    upgraded = deploy(host)
    assert upgraded.returncode == 0, upgraded.stdout + upgraded.stderr
    assert "种子更新 1 个" in upgraded.stdout
    assert path.read_bytes() == (ROOT / "data" / MAINLINE).read_bytes()
    backup = next((host / ".xiuxian3/backups").glob("deploy-*"))
    assert (backup / "data" / MAINLINE).read_bytes() == old
    preserved(host)
    repeated = deploy(host)
    assert repeated.returncode == 0, repeated.stdout + repeated.stderr
    assert "种子更新 0 个" in repeated.stdout
    document = json.loads(path.read_text(encoding="utf-8"))
    stage = next(row for row in document["records"] if row["key"] == "ironwood_craft.2")
    stage["body"] += "鲁槐另记下本地溪水的水位。"
    custom = (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    path.write_bytes(custom)
    result = deploy(host)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "种子更新 0 个" in result.stdout
    assert path.read_bytes() == custom
    preserved(host)


def test_ironwood_missing_custom_dispatch_rolls_back_source_and_seed(host: Path) -> None:
    old = _pre_ironwood_mainline()
    mainline = host / "data" / MAINLINE
    mainline.write_bytes(old)
    livelihood = host / "data/生活/生活.json"
    document = json.loads(livelihood.read_text(encoding="utf-8"))
    document["records"] = [row for row in document["records"] if row["key"] != "dispatch.ironwood_bridge_works"]
    custom = (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    livelihood.write_bytes(custom)
    source = host / "src/plugins/nonebot_plugin_xiuxian_3/__init__.py"
    previous_source, previous_toml = source.read_bytes(), (host / "pyproject.toml").read_bytes()
    result = deploy(host)
    assert result.returncode != 0
    assert "ironwood_craft.2 objective survey_bridge references unknown dispatch" in result.stdout + result.stderr
    assert "已回退" in result.stderr
    assert mainline.read_bytes() == old and livelihood.read_bytes() == custom
    assert source.read_bytes() == previous_source
    assert (host / "pyproject.toml").read_bytes() == previous_toml
    preserved(host)
