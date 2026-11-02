from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pytest

from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError
from nonebot_plugin_xiuxian_3.xiuxian.economy.void_market_content import (
    void_market_alias_map,
    void_market_defaults,
    void_market_offers,
)
from nonebot_plugin_xiuxian_3.xiuxian.economy.void_market_rules import (
    business_date,
    resolve_void_market_offer,
    void_market_definition,
    void_market_missing_requirements,
    week_id,
    week_refresh_at,
    week_start,
)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
MARKET_FILE = Path("经济/虚空集市.json")


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


def _record(document: dict, key: str) -> dict:
    return next(row for row in document["records"] if row["key"] == key)


def test_shipped_content_matches_the_frozen_void_market_contract() -> None:
    bundle = ContentBundle.load(DATA)
    assert MARKET_FILE.as_posix() in bundle.manifest["files"]

    defaults = void_market_defaults(bundle)
    assert defaults["location_key"] == "void.void_market"
    assert defaults["week_start_weekday"] == 1
    assert defaults["week_start_hour_utc"] == 0
    assert defaults["stock_slots"] == 20
    assert defaults["daily_purchase_limit"] == 3
    assert defaults["binding_seconds"] == 86400
    assert defaults["required_realm"] == "void_refining"
    assert defaults["required_layer"] == 1
    assert defaults["required_merit"] == 500

    offers = void_market_offers(bundle)
    by_item = {record["item_key"]: record for record in offers}
    assert set(by_item) == {"item.void_crystal", "item.void_anchor", "item.herb.time_trace"}
    assert by_item["item.void_crystal"]["price_spirit_stones"] == 12000
    assert by_item["item.void_anchor"]["price_spirit_stones"] == 5000
    assert by_item["item.herb.time_trace"]["price_spirit_stones"] == 3000
    assert sum(record["stock"] for record in offers) == defaults["stock_slots"]
    for record in offers:
        assert record["quantity"] == 1
        assert record["stock"] > 0
        assert record["aliases"], record["key"]

    aliases = void_market_alias_map(bundle)
    assert aliases["虚晶"] == "offer.void_market.void_crystal"
    assert aliases["虚空锚"] == "offer.void_market.void_anchor"
    assert aliases["时间花"] == "offer.void_market.time_trace"
    assert resolve_void_market_offer("虚晶", bundle) == "offer.void_market.void_crystal"
    assert resolve_void_market_offer("没有此物", bundle) is None

    # The market only exists as an anchor-route terminal; the route itself is
    # the gate that keeps unqualified characters out of the destination.
    route = bundle.get("world_void_route", defaults["location_key"])
    assert route is not None
    assert route["name"] == "虚空集市"


def test_week_boundaries_follow_the_content_week_definition() -> None:
    definition = void_market_definition(ContentBundle.load(DATA))
    sunday_late = datetime(2026, 11, 8, 23, 59, tzinfo=timezone.utc)
    monday = datetime(2026, 11, 9, 0, 0, tzinfo=timezone.utc)
    assert week_start(sunday_late, definition) == datetime(2026, 11, 2, tzinfo=timezone.utc)
    assert week_start(monday, definition) == monday
    assert week_id(monday, definition) == "2026-11-09"
    assert week_refresh_at(monday, definition) == datetime(2026, 11, 16, tzinfo=timezone.utc)
    assert business_date(datetime(2026, 11, 9, 0, 1, tzinfo=timezone.utc)) == "2026-11-09"


def test_purchase_gate_accepts_realm_or_void_merit() -> None:
    definition = void_market_definition(ContentBundle.load(DATA))
    assert void_market_missing_requirements(
        realm_key="void_refining", realm_layer=1, void_merit=0, definition=definition
    ) == ()
    assert void_market_missing_requirements(
        realm_key="nascent_soul", realm_layer=9, void_merit=500, definition=definition
    ) == ()
    missing = void_market_missing_requirements(
        realm_key="nascent_soul", realm_layer=9, void_merit=499, definition=definition
    )
    assert missing and "虚空功勋" in missing[0]


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda document: _record(document, "market.void.defaults").update(week_start_weekday=0), "week_start_weekday"),
        (lambda document: _record(document, "market.void.defaults").update(week_start_hour_utc=24), "week_start_hour_utc"),
        (lambda document: _record(document, "market.void.defaults").update(stock_slots=0), "stock_slots"),
        (lambda document: _record(document, "market.void.defaults").update(daily_purchase_limit=0), "daily_purchase_limit"),
        (lambda document: _record(document, "market.void.defaults").update(binding_seconds=0), "binding_seconds"),
        (lambda document: _record(document, "market.void.defaults").update(required_realm="unknown_realm"), "unknown realm"),
        (lambda document: _record(document, "market.void.defaults").update(location_key="void.unknown"), "anchor-route"),
        (lambda document: _record(document, "market.void.defaults").update(status="locked"), "not active"),
        (lambda document: _record(document, "offer.void_market.void_crystal").update(item_key="item.unknown"), "unknown item"),
        (lambda document: _record(document, "offer.void_market.void_crystal").update(price_spirit_stones=0), "price_spirit_stones"),
        (lambda document: _record(document, "offer.void_market.void_crystal").update(stock=0), "stock"),
        (lambda document: _record(document, "offer.void_market.void_crystal").update(quantity=0), "quantity"),
        (lambda document: _record(document, "offer.void_market.void_crystal").update(aliases=[]), "aliases"),
        (lambda document: _record(document, "offer.void_market.void_crystal").update(key="market.wrong_prefix"), "offer."),
        (lambda document: _record(document, "offer.void_market.void_crystal").update(status="locked"), "not active"),
        (lambda document: _record(document, "offer.void_market.void_anchor").update(aliases=["虚晶"]), "already owned"),
    ],
)
def test_malformed_market_content_is_rejected(tmp_path: Path, mutate, message: str) -> None:
    root = _copy_data(tmp_path)
    document = _document(root)
    mutate(document)
    _write(root, document)
    bundle = ContentBundle.load(root)
    with pytest.raises(ContentError, match=message):
        void_market_offers(bundle)


def test_weekly_stock_must_equal_the_frozen_slot_count(tmp_path: Path) -> None:
    root = _copy_data(tmp_path)
    document = _document(root)
    _record(document, "offer.void_market.time_trace")["stock"] = 7
    _write(root, document)
    with pytest.raises(ContentError, match="stock slots"):
        void_market_offers(ContentBundle.load(root))


def test_unknown_alias_and_closed_defaults_are_rejected(tmp_path: Path) -> None:
    root = _copy_data(tmp_path)
    document = _document(root)
    document["records"].append(
        {
            "key": "market.void.orphan",
            "name": "孤儿记录",
            "desc": "不属于集市报价的额外记录。",
            "status": "active",
            "label": "孤儿",
            "item_key": "item.void_crystal",
            "quantity": 1,
            "price_spirit_stones": 1000,
            "stock": 1,
            "aliases": ["孤儿"],
        }
    )
    _write(root, document)
    with pytest.raises(ContentError, match="offer."):
        void_market_offers(ContentBundle.load(root))
