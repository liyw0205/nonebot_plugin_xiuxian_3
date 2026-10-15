from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError
from nonebot_plugin_xiuxian_3.xiuxian.social import mentor_rules, party_rules
from nonebot_plugin_xiuxian_3.xiuxian.social.social_content import (
    MENTOR_KEY,
    PARTY_KEY,
    mentor_rules_record,
    party_aliases,
    party_definitions,
    realm_rank,
)

ROOT = Path(__file__).resolve().parents[1]
SOCIAL_FILE = Path("社交/玩家互动.json")

EXPECTED_PARTIES = {
    "exploration_pair": (2, 2, "contribution", None),
    "arena_trio": (3, 3, "arena_rating", None),
    "boundary_realm": (2, 5, "contribution", "cave.boundary_realm"),
    "demon_realm": (2, 5, "contribution", "demon.fallen_ruins"),
    "beast_realm": (2, 5, "contribution", "beast.ten_thousand_hills"),
    "standard_pve": (4, 5, "contribution", None),
    "secret_realm_boundary": (2, 5, "contribution", "cave.boundary_realm"),
    "secret_realm_ancient": (3, 3, "contribution", "cave.ancient_domain"),
    "secret_realm_void_ruins": (2, 5, "contribution", "void.archive_ruins"),
    "secret_realm_time_fort": (2, 5, "contribution", "void.archive_ruins"),
    "three_realms_tower_duo": (2, 2, "tower_duo", None),
}


def _records(data_dir: Path) -> dict[str, dict]:
    document = json.loads((data_dir / SOCIAL_FILE).read_text(encoding="utf-8"))
    assert document["kind"] == "social_interaction"
    return {record["key"]: record for record in document["records"]}


def _write_record(data_dir: Path, record: dict) -> None:
    document = json.loads((data_dir / SOCIAL_FILE).read_text(encoding="utf-8"))
    document["records"] = [
        record if row["key"] == record["key"] else row for row in document["records"]
    ]
    (data_dir / SOCIAL_FILE).write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _copy_data(tmp_path: Path) -> Path:
    data_dir = tmp_path / "data"
    shutil.copytree(
        ROOT / "data", data_dir, ignore=shutil.ignore_patterns("*.sqlite3*", "*.db*")
    )
    return data_dir


def test_mentor_record_matches_the_module_constants() -> None:
    record = mentor_rules_record()
    assert record["invitation_ttl_seconds"] == mentor_rules.MENTOR_INVITATION_TTL_SECONDS == 86400
    assert record["max_apprentices"] == mentor_rules.MENTOR_MAX_APPRENTICES == 3
    assert record["master_realm"] == mentor_rules.MENTOR_MASTER_REALM == "foundation"
    assert record["master_min_layer"] == mentor_rules.MENTOR_MASTER_MIN_LAYER == 4
    assert (
        frozenset(record["apprentice_realms"])
        == mentor_rules.MENTOR_APPRENTICE_REALMS
        == frozenset({"mortal", "qi_sensing", "qi_gathering"})
    )
    assert (
        record["apprentice_max_qi_gathering_layer"]
        == mentor_rules.MENTOR_APPRENTICE_MAX_QI_GATHERING_LAYER
        == 6
    )


def test_mentor_eligibility_is_unchanged_on_known_realms() -> None:
    assert mentor_rules.is_master_eligible("foundation", 4)
    assert not mentor_rules.is_master_eligible("foundation", 3)
    assert mentor_rules.is_master_eligible("golden_core", 1)
    assert not mentor_rules.is_master_eligible("qi_gathering", 10)
    assert not mentor_rules.is_master_eligible("mortal", 1)
    assert not mentor_rules.is_master_eligible("foundation", 0)
    assert mentor_rules.is_apprentice_eligible("cultivator", "qi_gathering", 6)
    assert not mentor_rules.is_apprentice_eligible("cultivator", "qi_gathering", 7)
    assert mentor_rules.is_apprentice_eligible("mortal", "mortal", 1)


def test_mentor_eligibility_now_covers_realms_past_the_old_table() -> None:
    # The hardcoded table stopped at tribulation; ranks come from content now.
    for realm_key in ("dao_union", "tribulation"):
        assert realm_rank(realm_key) > realm_rank("foundation")
        assert mentor_rules.is_master_eligible(realm_key, 1)


def test_party_record_matches_the_module_constants() -> None:
    records = {record["party_type"]: record for record in party_definitions()}
    assert set(records) == set(EXPECTED_PARTIES)
    for party_type, (minimum, maximum, distribution, location) in EXPECTED_PARTIES.items():
        record = records[party_type]
        assert (record["min_members"], record["max_members"]) == (minimum, maximum)
        assert record["distribution_key"] == distribution
        assert record["required_location"] == location
        assert record["confirmation_ttl_seconds"] == 300
        definition = party_rules.party_definition_for(party_type)
        assert (
            definition.min_members,
            definition.max_members,
            definition.distribution_key,
            definition.required_location,
            definition.confirmation_ttl_seconds,
        ) == (minimum, maximum, distribution, location, 300)
    assert party_rules.PARTY_MAX_MEMBERS == 2
    assert party_rules.ARENA_TRIO_MAX_MEMBERS == 3
    assert party_rules.BOUNDARY_REALM_MIN_MEMBERS == 2
    assert party_rules.BOUNDARY_REALM_MAX_MEMBERS == 5
    assert party_rules.PARTY_CONFIRMATION_TTL_SECONDS == 300


def test_party_alias_and_unknown_type_behaviour() -> None:
    assert party_aliases() == {"party_boundary": "boundary_realm"}
    assert (
        party_rules.party_definition_for("party_boundary")
        == party_rules.BOUNDARY_REALM_DEFINITION
    )
    assert (
        party_rules.party_definition_for("exploration_pair")
        == party_rules.PARTY_DEFINITION
    )
    with pytest.raises(ValueError, match="unsupported party type"):
        party_rules.party_definition_for("not_a_party_type")


@pytest.mark.parametrize(
    "key, mutate, message",
    [
        (MENTOR_KEY, lambda record: record.pop("name"), "requires a name"),
        (MENTOR_KEY, lambda record: record.update({"status": "locked"}), "not open"),
        (MENTOR_KEY, lambda record: record.update({"max_apprentices": 0}), "positive integer"),
        (MENTOR_KEY, lambda record: record.update({"master_realm": "nope"}), "unknown realm"),
        (MENTOR_KEY, lambda record: record.update({"apprentice_realms": []}), "non-empty list"),
        (MENTOR_KEY, lambda record: record.update({"apprentice_realms": ["nope"]}), "unknown realm"),
        (PARTY_KEY, lambda record: record["definitions"][0].update({"min_members": 9}), "below min_members"),
        (PARTY_KEY, lambda record: record["definitions"][0].update({"max_members": 0}), "positive integer"),
        (PARTY_KEY, lambda record: record["definitions"][1].update({"party_type": record["definitions"][0]["party_type"]}), "duplicate party_type"),
        (PARTY_KEY, lambda record: record["definitions"][0].update({"required_location": "cave.not_a_location"}), "unknown location"),
        (PARTY_KEY, lambda record: record["definitions"][0].update({"distribution_key": " "}), "invalid distribution_key"),
        (PARTY_KEY, lambda record: record.update({"aliases": {"": "boundary_realm"}}), "invalid alias"),
        (PARTY_KEY, lambda record: record.update({"definitions": []}), "non-empty list"),
    ],
)
def test_social_content_rejects_invalid_contract(
    tmp_path: Path, key: str, mutate, message: str
) -> None:
    data_dir = _copy_data(tmp_path)
    record = _records(data_dir)[key]
    mutate(record)
    _write_record(data_dir, record)
    bundle = ContentBundle.load(data_dir)
    with pytest.raises(ContentError, match=message):
        if key == MENTOR_KEY:
            mentor_rules_record(bundle)
        else:
            party_definitions(bundle)
            party_aliases(bundle)


def test_social_content_rejects_missing_record(tmp_path: Path) -> None:
    data_dir = _copy_data(tmp_path)
    document = json.loads((data_dir / SOCIAL_FILE).read_text(encoding="utf-8"))
    document["records"] = [
        record for record in document["records"] if record["key"] != MENTOR_KEY
    ]
    (data_dir / SOCIAL_FILE).write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    bundle = ContentBundle.load(data_dir)
    with pytest.raises(ContentError, match="missing social_interaction content"):
        mentor_rules_record(bundle)
