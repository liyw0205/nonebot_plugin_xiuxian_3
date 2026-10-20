from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError
from nonebot_plugin_xiuxian_3.xiuxian.rewards.rules import local_reputation_maximum
from nonebot_plugin_xiuxian_3.xiuxian.specials.dispatch_rules import dispatch_definitions

ROOT = Path(__file__).resolve().parents[1]
LIFE_FILE = Path("生活/生活.json")

NEW_DISPATCHES = (
    "dispatch.foundation.patrol",
    "dispatch.foundation.escort",
    "dispatch.golden_core.vein_survey",
    "dispatch.golden_core.pill_run",
    "dispatch.nascent.ruins_watch",
    "dispatch.nascent.beast_census",
    "dispatch.soul.domain_relay",
    "dispatch.soul.abyss_manifest",
    "dispatch.void.garden_tending",
    "dispatch.void.route_courier",
)

EXPECTED_REALM_COVERAGE = {
    "foundation": 2,
    "golden_core": 2,
    "nascent_soul": 2,
    "soul_transformation": 2,
    "void_refining": 2,
}


def _copy_data(tmp_path: Path, name: str) -> Path:
    data_dir = tmp_path / name
    shutil.copytree(
        ROOT / "data", data_dir, ignore=shutil.ignore_patterns("*.sqlite3*", "*.db*")
    )
    return data_dir


def _mutate(data_dir: Path, key: str, mutate) -> None:
    document = json.loads((data_dir / LIFE_FILE).read_text(encoding="utf-8"))
    for record in document["records"]:
        if record["key"] == key:
            mutate(record)
            break
    else:
        raise AssertionError(f"record {key} not found")
    (data_dir / LIFE_FILE).write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def test_all_ten_mid_high_dispatches_load() -> None:
    definitions = dispatch_definitions()
    for key in NEW_DISPATCHES:
        assert key in definitions, f"{key} missing from loaded dispatches"


def test_every_mid_high_realm_has_exactly_two_dispatches() -> None:
    definitions = dispatch_definitions()
    counts: dict[str, int] = {}
    for definition in definitions.values():
        if definition.required_realm in EXPECTED_REALM_COVERAGE:
            counts[definition.required_realm] = (
                counts.get(definition.required_realm, 0) + 1
            )
    assert counts == EXPECTED_REALM_COVERAGE


def test_new_dispatch_rewards_reference_provenance_closed_items() -> None:
    bundle = ContentBundle.load(ROOT / "data")
    sources = bundle.require("source", "source.item.void_materials", include_locked=False)
    closed = set(sources["asset_keys"])
    for item in bundle.list("item"):
        if item.get("gathering_sources"):
            closed.add(item["key"])
    document = json.loads((ROOT / "data" / LIFE_FILE).read_text(encoding="utf-8"))
    for record in document["records"]:
        if record.get("record_type") != "dispatch" or record["key"] not in NEW_DISPATCHES:
            continue
        for outcome in ("success", "partial"):
            for reward_key in record["rewards"].get(outcome, {}):
                if reward_key.startswith("item."):
                    assert reward_key in closed, (
                        f"{record['key']} rewards {reward_key} without closed provenance"
                    )
                elif reward_key.startswith("local."):
                    local_reputation_maximum(reward_key, bundle)


def test_new_dispatch_contracts_match_the_shipped_values() -> None:
    definitions = dispatch_definitions()
    patrol = definitions["dispatch.foundation.patrol"]
    assert patrol.duration_seconds == 1200
    assert patrol.daily_limit == 3
    assert ("stamina", 4) in patrol.costs
    assert patrol.rewards == (
        (
            "success",
            {
                "item.mat.array_sand": (1, 2),
                "spirit_stones": 60,
                "local.xuantian.new_town": 4,
            },
        ),
        ("partial", {"spirit_stones": 30, "local.xuantian.new_town": 1}),
    )
    courier = definitions["dispatch.void.route_courier"]
    assert courier.duration_seconds == 3600
    assert courier.required_realm == "void_refining" and courier.required_layer == 1
    courier_success = dict(courier.rewards)["success"]
    assert courier_success["item.soul_crystal"] == (2, 3)
    relay = definitions["dispatch.soul.domain_relay"]
    cost_map = dict(relay.costs)
    assert relay.failure_refunds and all(
        amount <= cost_map[resource] for resource, amount in relay.failure_refunds
    )
    assert relay.requirement == "soul_transformation_1"


def test_content_rejects_invalid_dispatch_contracts(tmp_path: Path) -> None:
    data_dir = _copy_data(tmp_path, "dur")
    # Duration below the 10-minute floor.
    _mutate(data_dir, "dispatch.foundation.patrol", lambda r: r.update({"duration_seconds": 300}))
    with pytest.raises(ContentError, match="outside the allowed range"):
        dispatch_definitions(ContentBundle.load(data_dir))

    # Risk weights no longer total 10000.
    data_dir = _copy_data(tmp_path, "risk")
    _mutate(
        data_dir,
        "dispatch.foundation.patrol",
        lambda r: r["risk"]["weights"].update({"success": 9000}),
    )
    with pytest.raises(ContentError, match="must total 10000"):
        dispatch_definitions(ContentBundle.load(data_dir))

    # Reward references an inactive item.
    data_dir = _copy_data(tmp_path, "reward-item")
    _mutate(
        data_dir,
        "dispatch.foundation.patrol",
        lambda r: r["rewards"]["success"].update({"item.not_an_item": 1}),
    )
    with pytest.raises(ContentError, match="references inactive item"):
        dispatch_definitions(ContentBundle.load(data_dir))

    # Duplicate alias across dispatches: patrol already owns 洞天巡护.
    data_dir = _copy_data(tmp_path, "alias")
    _mutate(
        data_dir,
        "dispatch.golden_core.vein_survey",
        lambda r: r.update({"aliases": ["洞天巡护", "勘测"]}),
    )
    with pytest.raises(ContentError, match="duplicate name or alias"):
        dispatch_definitions(ContentBundle.load(data_dir))

    # Failure refund exceeds its cost.
    data_dir = _copy_data(tmp_path, "refund")
    _mutate(
        data_dir,
        "dispatch.foundation.patrol",
        lambda r: r["failure_refunds"].update({"stamina": 9}),
    )
    with pytest.raises(ContentError, match="invalid failure refund"):
        dispatch_definitions(ContentBundle.load(data_dir))

    # Unsupported outcome name in rewards.
    data_dir = _copy_data(tmp_path, "outcome")
    _mutate(
        data_dir,
        "dispatch.void.garden_tending",
        lambda r: r["rewards"].update({"delayed": {"spirit_stones": 50}}),
    )
    with pytest.raises(ContentError, match="invalid delayed rewards"):
        dispatch_definitions(ContentBundle.load(data_dir))
