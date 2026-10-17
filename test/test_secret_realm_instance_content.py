from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from nonebot_plugin_xiuxian_3.xiuxian.adventures import (
    ancestral_hall_rules,
    ancient_domain_rules,
    boundary_rift_rules,
    dao_origin_rules,
    demon_abyss_rules,
    heaven_echo_rules,
    legacy_manor_rules,
    time_fort_rules,
    void_ruins_rules,
)
from nonebot_plugin_xiuxian_3.xiuxian.adventures.secret_realm_content import (
    KIND,
    node_aliases,
    node_labels,
    secret_realm_record,
    secret_realm_records,
)
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError

ROOT = Path(__file__).resolve().parents[1]
REALM_FILE = Path("冒险/秘境专用.json")

INSTANCE_KEYS = (
    "instance.legacy.demon_abyss_echo",
    "instance.legacy.demon_reliquary",
    "instance.secret_realm.ancestral_hall",
    "instance.secret_realm.ancient_domain",
    "instance.secret_realm.boundary_rift",
    "instance.secret_realm.dao_origin",
    "instance.secret_realm.demon_abyss",
    "instance.secret_realm.heaven_echo",
    "instance.secret_realm.time_fort",
    "instance.secret_realm.void_ruins",
)


def _records(data_dir: Path) -> dict[str, dict]:
    document = json.loads((data_dir / REALM_FILE).read_text(encoding="utf-8"))
    assert document["kind"] == KIND
    return {record["key"]: record for record in document["records"]}


def _write_record(data_dir: Path, record: dict) -> None:
    document = json.loads((data_dir / REALM_FILE).read_text(encoding="utf-8"))
    document["records"] = [
        record if row["key"] == record["key"] else row for row in document["records"]
    ]
    (data_dir / REALM_FILE).write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _copy_data(tmp_path: Path) -> Path:
    data_dir = tmp_path / "data"
    shutil.copytree(
        ROOT / "data", data_dir, ignore=shutil.ignore_patterns("*.sqlite3*", "*.db*")
    )
    return data_dir


def test_secret_realm_manifest_registers_the_dedicated_file() -> None:
    manifest = json.loads((ROOT / "data/内容清单.json").read_text(encoding="utf-8"))
    assert REALM_FILE.as_posix() in manifest["files"]


def test_secret_realm_records_cover_every_dedicated_instance() -> None:
    records = {record["key"]: record for record in secret_realm_records()}
    assert tuple(sorted(records)) == INSTANCE_KEYS
    for record in records.values():
        assert record["name"].strip() and record["desc"].strip()
        assert record["nodes"], "every realm needs nodes"
        assert len({node["key"] for node in record["nodes"]}) == len(record["nodes"])
        for node in record["nodes"]:
            assert node["label"].strip()


def test_ancestral_hall_record_matches_the_shipped_contract() -> None:
    record = secret_realm_record(ancestral_hall_rules.ANCESTRAL_HALL_KEY)
    assert record["location_key"] == "beast.ancestral_lake"
    assert record["enemy_key"] == "enemy.ancestral_spirit"
    assert record["stamina_cost"] == 25 and record["weekly_limit"] == 1
    assert record["expiry_seconds"] == 3600
    assert record["story_flag"] == "story.ancestral_hall"
    assert record["codex_entry_key"] == "codex.domain.ancestral_hall"
    assert tuple(node["key"] for node in record["nodes"]) == ancestral_hall_rules.ANCESTRAL_HALL_NODES
    assert node_labels(record) == ancestral_hall_rules.ANCESTRAL_HALL_NODE_LABELS
    assert ancestral_hall_rules.resolve_ancestral_hall_node("祖灵门") == "ancestral_gate"
    assert ancestral_hall_rules.resolve_ancestral_hall_node("5") == "founder_altar"


def test_ancient_domain_record_matches_the_shipped_contract() -> None:
    record = secret_realm_record(ancient_domain_rules.ANCIENT_DOMAIN_KEY)
    assert record["location_key"] == ancient_domain_rules.ANCIENT_DOMAIN_LOCATION == "cave.ancient_domain"
    assert record["party_type"] == ancient_domain_rules.ANCIENT_DOMAIN_PARTY_TYPE
    assert record["enemy_key"] == ancient_domain_rules.ANCIENT_DOMAIN_ENEMY
    assert record["stamina_cost"] == 40 and record["weekly_limit"] == 1
    assert record["energy_suppression"] == 10
    assert record["first_reward"] == {"item.ancient_fruit": 2}
    assert record["repeat_reward"] == {"item.ancient_fruit": 1}
    assert tuple(node["key"] for node in record["nodes"]) == ancient_domain_rules.ANCIENT_DOMAIN_NODES
    assert ancient_domain_rules.resolve_ancient_domain_node("本源封印") == "origin_seal"


def test_ancient_domain_keeps_its_locked_location() -> None:
    locations = json.loads((ROOT / "data/地图/地点.json").read_text(encoding="utf-8"))
    record = next(
        row for row in locations["records"] if row["key"] == "cave.ancient_domain"
    )
    assert record["status"] == "locked", "the ancient domain is a deliberately locked cave"


def test_heaven_echo_record_matches_the_shipped_contract() -> None:
    record = secret_realm_record(heaven_echo_rules.HEAVEN_ECHO_KEY)
    assert "location_key" not in record and "stamina_cost" not in record
    assert record["expiry_seconds"] == 3600
    assert record["story_flag"] == "story.heaven_echo"
    assert tuple(node["key"] for node in record["nodes"]) == heaven_echo_rules.HEAVEN_ECHO_NODES
    assert heaven_echo_rules.resolve_heaven_echo_node("3") == "side_story_gate"


def test_dao_origin_record_matches_the_shipped_contract() -> None:
    record = secret_realm_record(dao_origin_rules.DAO_ORIGIN_KEY)
    assert record["location_key"] == "dao.origin_gate"
    assert record["permission"] == dao_origin_rules.DAO_ORIGIN_PERMISSION
    assert record["stamina_cost"] == 60 and record["quota_key"] == "lifetime"
    assert record["first_reward"] == {
        "story.dao_origin": 1,
        "codex.dao.service_origin": 1,
    }
    assert record["repeat_reward"] == {}
    assert tuple(node["key"] for node in record["nodes"]) == dao_origin_rules.DAO_ORIGIN_NODES
    assert dao_origin_rules.resolve_dao_origin_node("8") == "new_chapter_gate"


def test_demon_abyss_record_matches_the_shipped_contract() -> None:
    record = secret_realm_record(demon_abyss_rules.DEMON_ABYSS_KEY)
    assert record["label"] == demon_abyss_rules.DEMON_ABYSS_LABEL == "魔界深渊秘境"
    assert record["required_flag"] == "access.demon_abyss_gate"
    assert record["stamina_cost"] == 20 and record["quota_limit"] == 1
    assert record["risk_base_bp"] == 0 and record["risk_modifier_bp"] == 50
    assert record["first_reward"] == {
        "faction_reputation.demon": 20,
        "item.clue.demon_abyss_echo": 1,
        "story.demon_abyss_echo": 1,
    }
    assert record["repeat_reward"] == {"item.demon_core": 1}
    assert demon_abyss_rules.DEMON_ABYSS_ENEMIES == {
        "echo_guardian": "enemy.demon_abyss_echo_guardian",
        "abyss_heart": "enemy.demon_abyss_heart",
    }
    assert demon_abyss_rules.resolve_demon_abyss("魔界深渊") == demon_abyss_rules.DEMON_ABYSS_KEY
    assert demon_abyss_rules.resolve_demon_abyss_node("深渊之心") == "abyss_heart"


def test_boundary_rift_record_matches_the_shipped_contract() -> None:
    record = secret_realm_record(boundary_rift_rules.BOUNDARY_RIFT_KEY)
    assert record["location_key"] == "cave.boundary_realm"
    assert record["party_type"] == boundary_rift_rules.BOUNDARY_RIFT_PARTY_TYPE
    assert record["stamina_cost"] == 30 and record["weekly_limit"] == 1
    assert record["ticket_key"] == "item.soul_crystal" and record["ticket_quantity"] == 1
    assert record["first_reward"] == {"item.soul_crystal": 1}
    assert record["repeat_reward"] == {"item.soul_crystal": 1}
    assert [
        (node.key, node.label, node.enemy_key)
        for node in boundary_rift_rules.BOUNDARY_RIFT_NODE_DEFINITIONS
    ] == [
        (node["key"], node["label"], node.get("enemy_key"))
        for node in record["nodes"]
    ]
    assert boundary_rift_rules.resolve_boundary_rift_node("界隙守望者") == "boundary_watcher"


def test_legacy_manors_match_the_shipped_contract() -> None:
    definitions = legacy_manor_rules.LEGACY_MANOR_DEFINITIONS
    assert tuple(sorted(definitions)) == (
        "instance.legacy.demon_abyss_echo",
        "instance.legacy.demon_reliquary",
    )
    reliquary = definitions["instance.legacy.demon_reliquary"]
    assert reliquary.operation_scope == "legacy_manor"
    assert reliquary.location_key == legacy_manor_rules.LEGACY_MANOR_LOCATION
    assert reliquary.realm_key == "nascent_soul" and reliquary.realm_layer == 1
    assert reliquary.clue == legacy_manor_rules.LEGACY_MANOR_CLUE
    assert reliquary.permission == "access.demon.fallen_ruins"
    assert reliquary.nodes == ("reliquary_seal", "pact_archive", "oath_chamber")
    echo = definitions["instance.legacy.demon_abyss_echo"]
    assert echo.operation_scope == "legacy_manor.demon_abyss_echo"
    assert echo.realm_key == "foundation" and echo.clue == "item.clue.demon_abyss_echo"
    assert echo.nodes == ("echo_threshold", "sealed_resonance", "final_whisper")
    assert legacy_manor_rules.resolve_legacy_manor_node("旧誓密室") == "oath_chamber"
    assert (
        legacy_manor_rules.resolve_legacy_manor_node(
            "未竟之言", "instance.legacy.demon_abyss_echo"
        )
        == "final_whisper"
    )
    with pytest.raises(ValueError, match="unknown legacy manor"):
        legacy_manor_rules.get_legacy_manor_definition("instance.legacy.nope")


def test_time_fort_record_matches_the_shipped_contract() -> None:
    record = secret_realm_record(time_fort_rules.TIME_FORT_KEY)
    assert record["location_key"] == time_fort_rules.TIME_FORT_LOCATION == "void.archive_ruins"
    assert record["party_type"] == time_fort_rules.TIME_FORT_PARTY_TYPE == "secret_realm_time_fort"
    assert record["realm_key"] == time_fort_rules.TIME_FORT_REALM == "void_refining"
    assert record["realm_layer"] == time_fort_rules.TIME_FORT_REALM_LAYER == 1
    assert record["min_members"] == time_fort_rules.TIME_FORT_MIN_MEMBERS == 2
    assert record["max_members"] == time_fort_rules.TIME_FORT_MAX_MEMBERS == 5
    assert record["stamina_cost"] == time_fort_rules.TIME_FORT_STAMINA_COST == 40
    assert record["weekly_limit"] == time_fort_rules.TIME_FORT_WEEKLY_LIMIT == 1
    assert record["expiry_seconds"] == time_fort_rules.TIME_FORT_EXPIRY_SECONDS == 3600
    assert record["permission"] == time_fort_rules.TIME_FORT_PERMISSION == "access.void.time_fort"
    assert record["story_flag"] == time_fort_rules.TIME_FORT_STORY_FLAG == "story.mainline.void_archive.time_fort"
    assert record["storm_interval_rounds"] == time_fort_rules.TIME_FORT_STORM_INTERVAL == 3
    assert record["storm_damage_bp"] == time_fort_rules.TIME_FORT_STORM_DAMAGE_BP == 500
    assert record["enemy_key"] == time_fort_rules.TIME_FORT_ENEMY == "enemy.time_fort_keeper"
    assert record["first_reward"] == time_fort_rules.TIME_FORT_FIRST_REWARD == {"item.mat.array_sand": 2}
    assert record["repeat_reward"] == time_fort_rules.TIME_FORT_REPEAT_REWARD == {"item.mat.array_sand": 1}
    assert tuple(node["key"] for node in record["nodes"]) == time_fort_rules.TIME_FORT_NODES
    assert node_labels(record) == time_fort_rules.TIME_FORT_NODE_LABELS
    assert time_fort_rules.resolve_time_fort_node("堡垒门庭") == "fort_gate"
    assert time_fort_rules.resolve_time_fort_node("5") == "time_keeper"


def test_void_ruins_record_matches_the_shipped_contract() -> None:
    record = secret_realm_record(void_ruins_rules.VOID_RUINS_KEY)
    assert record["location_key"] == void_ruins_rules.VOID_RUINS_LOCATION == "void.archive_ruins"
    assert record["party_type"] == void_ruins_rules.VOID_RUINS_PARTY_TYPE == "secret_realm_void_ruins"
    assert record["realm_key"] == void_ruins_rules.VOID_RUINS_REALM == "void_refining"
    assert record["realm_layer"] == void_ruins_rules.VOID_RUINS_REALM_LAYER == 1
    assert record["min_members"] == void_ruins_rules.VOID_RUINS_MIN_MEMBERS == 2
    assert record["max_members"] == void_ruins_rules.VOID_RUINS_MAX_MEMBERS == 5
    assert record["stamina_cost"] == void_ruins_rules.VOID_RUINS_STAMINA_COST == 50
    assert record["anchor_lock"] == void_ruins_rules.VOID_RUINS_ANCHOR_LOCK == 1
    assert record["weekly_limit"] == void_ruins_rules.VOID_RUINS_WEEKLY_LIMIT == 1
    assert record["expiry_seconds"] == void_ruins_rules.VOID_RUINS_EXPIRY_SECONDS == 3600
    assert record["permission"] == void_ruins_rules.VOID_RUINS_ROUTE_PERMISSION == "access.void.time_fort"
    assert record["codex_entry_key"] == void_ruins_rules.VOID_RUINS_CODEX == "codex.void.route_ruins"
    assert record["repeat_reward"] == void_ruins_rules.VOID_RUINS_REPEAT_REWARD == {"item.void_crystal": 1}
    assert "first_reward" not in record, "the void-ruins first bonus is flag+codex, not an asset map"
    assert tuple(node["key"] for node in record["nodes"]) == void_ruins_rules.VOID_RUINS_NODES
    assert node_labels(record) == void_ruins_rules.VOID_RUINS_NODE_LABELS
    assert void_ruins_rules.VOID_RUINS_ENEMIES == {
        ("rift_sentinel", False): "enemy.void_ruins_sentinel",
        ("rift_sentinel", True): "enemy.void_ruins_sentinel_unstable",
        ("archive_keeper", False): "enemy.void_ruins_keeper",
        ("archive_keeper", True): "enemy.void_ruins_keeper_unstable",
    }
    assert void_ruins_rules.resolve_void_ruins_node("裂隙哨卫") == "rift_sentinel"
    assert void_ruins_rules.resolve_void_ruins_node("10") == "exit_gate"


def test_node_aliases_resolve_key_label_and_ordinal() -> None:
    for record in secret_realm_records():
        aliases = node_aliases(record)
        for index, node in enumerate(record["nodes"], start=1):
            assert aliases[node["key"]] == node["key"]
            assert aliases[node["label"]] == node["key"]
            assert aliases[str(index)] == node["key"]


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda record: record.pop("name"), "requires a name"),
        (lambda record: record.update({"status": "locked"}), "is not active"),
        (lambda record: record["nodes"].clear(), "requires nodes"),
        (lambda record: record["nodes"][1].update({"key": record["nodes"][0]["key"]}), "duplicate key"),
        (lambda record: record["nodes"][0].pop("label"), "missing or unknown fields"),
        (lambda record: record["nodes"][0].update({"label": "  "}), "requires a label"),
        (lambda record: record.update({"stamina_cost": 0}), "positive integer"),
        (lambda record: record.update({"expiry_seconds": -1}), "positive integer"),
        (lambda record: record.update({"location_key": "cave.not_a_location"}), "unknown location"),
        (lambda record: record.update({"first_reward": {"": 1}}), "empty reward key"),
        (lambda record: record.update({"first_reward": {"item.x": 0}}), "positive integer"),
        (lambda record: record.update({"aliases": []}), "non-empty list"),
        (lambda record: record.update({"min_members": 3}), "member bounds must be declared together"),
        (
            lambda record: record.update({"min_members": 6, "max_members": 5}),
            "max_members is below min_members",
        ),
        (lambda record: record.update({"min_members": 0, "max_members": 5}), "positive integer"),
        (lambda record: record.update({"realm_key": "void_refining"}), "realm gate must be declared together"),
        (lambda record: record.update({"realm_layer": 1}), "realm gate must be declared together"),
        (
            lambda record: record.update({"realm_key": "not_a_realm", "realm_layer": 1}),
            "references unknown realm",
        ),
        (
            lambda record: record.update({"storm_interval_rounds": 3}),
            "storm contract must be declared together",
        ),
        (
            lambda record: record.update({"storm_damage_bp": 500}),
            "storm contract must be declared together",
        ),
        (
            lambda record: record["nodes"][0].update({"unstable_enemy_key": "enemy.x"}),
            "without a base enemy",
        ),
        (
            lambda record: record["nodes"][0].update({"unstable_enemy_key": "  "}),
            "invalid unstable enemy",
        ),
        (
            lambda record: record["nodes"][0].update({"enemy_key": "enemy.x", "unstable_enemy_key": "enemy.y", "extra": 1}),
            "missing or unknown fields",
        ),
    ],
)
def test_secret_realm_rejects_invalid_contract(tmp_path: Path, mutate, message: str) -> None:
    data_dir = _copy_data(tmp_path)
    record = _records(data_dir)["instance.secret_realm.ancestral_hall"]
    mutate(record)
    _write_record(data_dir, record)
    bundle = ContentBundle.load(data_dir)
    with pytest.raises(ContentError, match=message):
        secret_realm_record("instance.secret_realm.ancestral_hall", bundle)


def test_secret_realm_rejects_unknown_instance(tmp_path: Path) -> None:
    bundle = ContentBundle.load(_copy_data(tmp_path))
    with pytest.raises(ContentError, match="not active"):
        secret_realm_record("instance.secret_realm.nope", bundle)
