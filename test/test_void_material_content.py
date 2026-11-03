from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError
from nonebot_plugin_xiuxian_3.xiuxian.economy.void_material_content import (
    void_material_defaults,
)
from nonebot_plugin_xiuxian_3.xiuxian.economy.void_material_rules import (
    admission_missing,
    fee_for,
    is_expired,
    listing_expiry,
    validate_listing_request,
)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
MARKET_FILE = Path("经济/虚空物资寄售.json")
DEFAULTS = "market.void_material.defaults"


def _copy_data(tmp_path: Path) -> Path:
    target = tmp_path / "data"
    shutil.copytree(DATA, target)
    return target


def _document(root: Path) -> dict:
    return json.loads((root / MARKET_FILE).read_text(encoding="utf-8"))


def _write(root: Path, document: dict) -> None:
    (root / MARKET_FILE).write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _record(document: dict) -> dict:
    return next(row for row in document["records"] if row["key"] == DEFAULTS)


def test_shipped_market_content_matches_the_frozen_economy_row() -> None:
    bundle = ContentBundle.load(DATA)
    assert MARKET_FILE.as_posix() in bundle.manifest["files"]

    raw = bundle.require("void_material_market", DEFAULTS)
    assert raw["status"] == "active"
    # economy v0.5: six hours, 800 bp fee, realm or merit admission.
    assert raw["listing_hours"] == 6
    assert raw["fee_bp"] == 800

    record = void_material_defaults(bundle)
    assert record["expire_grace_minutes"] == 5
    assert record["max_listings_per_player"] == 5
    assert record["admission"] == {
        "realm": "void_refining",
        "min_layer": 1,
        "merit_key": "void_merit",
        "min_merit": 500,
    }
    assert "item.void_crystal" in record["allowed_item_keys"]
    assert "虚空寄售" in record["aliases"]


def test_every_whitelisted_item_is_tradeable_and_unbound() -> None:
    bundle = ContentBundle.load(DATA)
    record = void_material_defaults(bundle)
    for item_key in record["allowed_item_keys"]:
        item = bundle.get("item", item_key, include_locked=False)
        assert item is not None
        assert item.get("tradeable") is True
        assert str(item.get("bind_type", "")) != "character_bound"


def test_fee_rounds_down_and_never_exceeds_gross() -> None:
    assert fee_for(gross=400, fee_bp=800) == (32, 368)
    assert fee_for(gross=100, fee_bp=800) == (8, 92)
    # A gross below the fee granularity costs nothing rather than going negative.
    assert fee_for(gross=1, fee_bp=800) == (0, 1)
    assert fee_for(gross=0, fee_bp=800) == (0, 0)


def test_admission_accepts_realm_or_merit() -> None:
    common = dict(
        merit_key="void_merit",
        required_realm="void_refining",
        required_layer=1,
        required_merit=500,
    )
    assert admission_missing(realm_key="void_refining", realm_layer=1, merit=0, **common) == []
    assert admission_missing(realm_key="mortal", realm_layer=0, merit=500, **common) == []
    missing = admission_missing(realm_key="mortal", realm_layer=0, merit=499, **common)
    assert len(missing) == 2


def test_listing_request_validation_and_expiry() -> None:
    allowed = ("item.void_crystal",)
    assert (
        validate_listing_request(
            item_key="item.void_crystal", allowed_item_keys=allowed, quantity=1, unit_price=10, held=1
        )
        is None
    )
    assert (
        validate_listing_request(
            item_key="item.void_anchor", allowed_item_keys=allowed, quantity=1, unit_price=10, held=1
        )
        == "VOID_MARKET_ITEM_FORBIDDEN"
    )
    assert (
        validate_listing_request(
            item_key="item.void_crystal", allowed_item_keys=allowed, quantity=2, unit_price=10, held=1
        )
        == "VOID_MARKET_NOT_ENOUGH_ITEMS"
    )
    assert (
        validate_listing_request(
            item_key="item.void_crystal", allowed_item_keys=allowed, quantity=0, unit_price=10, held=1
        )
        == "INVALID_VOID_MARKET_COMMAND"
    )

    from datetime import datetime, timezone

    created = datetime(2026, 11, 3, 5, 0, tzinfo=timezone.utc)
    expires = listing_expiry(created_at=created, listing_hours=6)
    assert expires.isoformat() == "2026-11-03T11:00:00+00:00"
    assert is_expired(expires_at=expires.isoformat(), now=created) is False
    assert is_expired(expires_at=expires.isoformat(), now=expires) is True


@pytest.mark.parametrize(
    "mutate, expected",
    [
        (lambda row: row.update(listing_hours=0), "must be between 1 and 72"),
        (lambda row: row.update(listing_hours=100), "must be between 1 and 72"),
        (lambda row: row.update(fee_bp=-1), "must be between 0 and 2000"),
        (lambda row: row.update(fee_bp=5000), "must be between 0 and 2000"),
        (lambda row: row.update(expire_grace_minutes=90), "must be between 0 and 60"),
        (lambda row: row.update(max_listings_per_player=0), "must be between 1 and 50"),
        (lambda row: row.update(admission={"realm": "void_refining"}), "admission is malformed"),
        (
            lambda row: row.update(
                admission={"realm": "nope", "min_layer": 1, "merit_key": "void_merit", "min_merit": 500}
            ),
            "unknown realm",
        ),
        (
            lambda row: row.update(
                admission={"realm": "void_refining", "min_layer": 99, "merit_key": "void_merit", "min_merit": 500}
            ),
            "min_layer is outside realm",
        ),
        (
            lambda row: row.update(
                admission={"realm": "void_refining", "min_layer": 1, "merit_key": "nope", "min_merit": 500}
            ),
            "merit_key is unsupported",
        ),
        (lambda row: row.update(allowed_item_keys=[]), "must be a non-empty list"),
        (lambda row: row.update(allowed_item_keys=["item.nope"]), "unknown item"),
        (
            lambda row: row.update(allowed_item_keys=["item.void_archive"]),
            "untradeable",
        ),
        (
            lambda row: row.update(allowed_item_keys=["item.void_crystal", "item.void_crystal"]),
            "repeats the item",
        ),
        (lambda row: row.update(aliases=["   "]), "malformed alias"),
        (lambda row: row.pop("fee_bp"), "missing fields"),
        (lambda row: row.update(status="locked"), "not active"),
    ],
)
def test_malformed_market_content_is_rejected(tmp_path: Path, mutate, expected: str) -> None:
    root = _copy_data(tmp_path)
    document = _document(root)
    mutate(_record(document))
    _write(root, document)

    bundle = ContentBundle.load(root)
    with pytest.raises(ContentError) as excinfo:
        void_material_defaults(bundle)
    assert expected in str(excinfo.value)