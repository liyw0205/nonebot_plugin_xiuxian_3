from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError
from nonebot_plugin_xiuxian_3.xiuxian.economy.auction_rules import (
    auction_definition,
    auction_definition_from_snapshot,
    auction_week_start,
    minimum_next_bid,
    validate_auction_listing,
)


@pytest.fixture
def snapshot() -> dict[str, object]:
    return {
        "key": "auction.weekly",
        "name": "仙市拍卖",
        "desc": "珍物入市，诸位道友依次出价，价高者得。",
        "slot_limit": 20,
        "duration_seconds": 43200,
        "settlement_grace_seconds": 600,
        "min_quantity": 1,
        "max_quantity": 99,
        "min_starting_bid": 1,
        "min_increment_bp": 500,
    }


def _content(snapshot: dict[str, object], *, status: str = "active") -> ContentBundle:
    return ContentBundle(
        root=Path("."), manifest={},
        _records={("auction", "auction.weekly"): {**snapshot, "status": status}},
    )


def test_auction_default_content_is_registered_and_matches_current_terms(snapshot: dict[str, object]) -> None:
    assert auction_definition().snapshot() == snapshot


def test_auction_snapshot_roundtrip_is_independent_and_immutable(snapshot: dict[str, object]) -> None:
    definition = auction_definition_from_snapshot(snapshot)
    assert definition.snapshot() == snapshot
    snapshot["slot_limit"] = 1
    exported = definition.snapshot()
    exported["min_increment_bp"] = 999
    assert definition.slot_limit == 20
    assert definition.min_increment_bp == 500
    with pytest.raises(FrozenInstanceError):
        definition.slot_limit = 1


@pytest.mark.parametrize("field", (
    "key", "name", "desc", "slot_limit", "duration_seconds", "settlement_grace_seconds",
    "min_quantity", "max_quantity", "min_starting_bid", "min_increment_bp",
))
def test_auction_snapshot_and_content_require_every_field(snapshot: dict[str, object], field: str) -> None:
    del snapshot[field]
    with pytest.raises(ValueError):
        auction_definition_from_snapshot(snapshot)
    with pytest.raises(ContentError, match=f"auction.weekly.*{field}"):
        auction_definition(_content(snapshot))


@pytest.mark.parametrize("field", (
    "slot_limit", "duration_seconds", "settlement_grace_seconds", "min_quantity",
    "max_quantity", "min_starting_bid", "min_increment_bp",
))
@pytest.mark.parametrize("value", (0, -1, True, False, "1", 1.0, None))
def test_auction_snapshot_and_content_reject_invalid_numbers(
    snapshot: dict[str, object], field: str, value: object,
) -> None:
    snapshot[field] = value
    with pytest.raises(ValueError, match=field):
        auction_definition_from_snapshot(snapshot)
    with pytest.raises(ContentError, match=f"auction.weekly.*{field}"):
        auction_definition(_content(snapshot))


@pytest.mark.parametrize("field", ("name", "desc"))
@pytest.mark.parametrize("value", ("", " ", 1, None))
def test_auction_snapshot_and_content_require_display_text(
    snapshot: dict[str, object], field: str, value: object,
) -> None:
    snapshot[field] = value
    with pytest.raises(ValueError, match=field):
        auction_definition_from_snapshot(snapshot)
    with pytest.raises(ContentError, match=f"auction.weekly.*{field}"):
        auction_definition(_content(snapshot))


def test_auction_snapshot_rejects_wrong_identity_and_inverted_quantity_range(snapshot: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="key"):
        auction_definition_from_snapshot({**snapshot, "key": "auction.other"})
    snapshot.update(min_quantity=10, max_quantity=9)
    with pytest.raises(ValueError, match="max_quantity"):
        auction_definition_from_snapshot(snapshot)
    with pytest.raises(ContentError, match="auction.weekly.*max_quantity"):
        auction_definition(_content(snapshot))


@pytest.mark.parametrize("value", (None, False, 1, "{}", [], (), {}))
def test_auction_snapshot_rejects_nonobjects_and_empty_objects(value: object) -> None:
    with pytest.raises(ValueError):
        auction_definition_from_snapshot(value)


def test_auction_snapshot_rejects_extra_fields(snapshot: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        auction_definition_from_snapshot({**snapshot, "fallback": True})


@pytest.mark.parametrize("status", ("closed", "locked"))
def test_auction_content_closure_does_not_reinterpret_frozen_terms(snapshot: dict[str, object], status: str) -> None:
    frozen = auction_definition(_content(snapshot)).snapshot()
    with pytest.raises(ContentError, match="auction.weekly.*status"):
        auction_definition(_content(snapshot, status=status))
    assert auction_definition_from_snapshot(frozen).snapshot() == snapshot


def test_auction_content_changes_new_terms_without_mutating_frozen_terms(snapshot: dict[str, object]) -> None:
    frozen = auction_definition(_content(snapshot)).snapshot()
    changed = {
        **snapshot, "name": "珍宝会", "desc": "珍宝会开，静候出价。", "slot_limit": 2,
        "duration_seconds": 60, "settlement_grace_seconds": 30,
        "min_quantity": 2, "max_quantity": 3, "min_starting_bid": 10, "min_increment_bp": 2000,
    }
    definition = auction_definition(_content(changed))
    assert definition.snapshot() == changed
    assert auction_definition_from_snapshot(frozen).snapshot() == snapshot
    assert minimum_next_bid(100, 10, definition.min_increment_bp) == 120
    assert minimum_next_bid(100, 1, auction_definition_from_snapshot(frozen).min_increment_bp) == 105


def test_auction_missing_content_is_not_replaced_with_defaults() -> None:
    with pytest.raises(ContentError, match="auction.weekly"):
        auction_definition(ContentBundle(Path("."), {}, {}))


@pytest.mark.parametrize(("current", "start", "increment", "expected"), (
    (0, 7, 500, 7), (1, 1, 500, 2), (19, 1, 500, 20), (20, 1, 500, 21),
    (21, 1, 500, 23), (100, 1, 2000, 120), (100, 1, 1, 101),
    (100, 1, 20000, 300), (10**30, 1, 500, 105 * 10**28),
))
def test_auction_minimum_bid_uses_explicit_increment_and_integer_ceiling(
    current: int, start: int, increment: int, expected: int,
) -> None:
    assert minimum_next_bid(current, start, increment) == expected


@pytest.mark.parametrize(("current", "start", "increment"), (
    (-1, 1, 500), (True, 1, 500), (1.0, 1, 500), ("1", 1, 500),
    (0, 0, 500), (0, True, 500), (0, "1", 500), (0, 1.0, 500),
    (1, 1, 0), (1, 1, -1), (1, 1, True), (1, 1, "500"), (1, 1, 500.0),
))
def test_auction_minimum_bid_rejects_implicit_numeric_conversion(current, start, increment) -> None:
    with pytest.raises(ValueError):
        minimum_next_bid(current, start, increment)


def test_auction_listing_uses_definition_limits_and_existing_item_resolver(snapshot: dict[str, object]) -> None:
    definition = auction_definition_from_snapshot({**snapshot, "min_quantity": 2, "max_quantity": 3, "min_starting_bid": 10})
    item = validate_auction_listing("item.mat.wood", 2, 10, definition)
    assert item.key == "item.mat.wood"
    for quantity, starting_bid in ((1, 10), (4, 10), (2, 9)):
        with pytest.raises(ValueError):
            validate_auction_listing("item.mat.wood", quantity, starting_bid, definition)
    with pytest.raises(ValueError):
        validate_auction_listing("item.pill.foundation_guard", 2, 10, definition)


@pytest.mark.parametrize(("quantity", "starting_bid"), (
    (True, 1), ("1", 1), (1.0, 1), (None, 1), (1, True), (1, "1"), (1, 1.0), (1, None),
))
def test_auction_listing_rejects_implicit_numeric_conversion(quantity, starting_bid) -> None:
    with pytest.raises(ValueError):
        validate_auction_listing("item.mat.wood", quantity, starting_bid, auction_definition())


@pytest.mark.parametrize(("value", "expected"), (
    (datetime(2026, 10, 5, 0, 0, tzinfo=timezone.utc), "2026-10-05"),
    (datetime(2026, 10, 5, 7, 59, tzinfo=timezone(timedelta(hours=8))), "2026-09-28"),
    (datetime(2026, 10, 5, 8, 0, tzinfo=timezone(timedelta(hours=8))), "2026-10-05"),
    (datetime(2026, 10, 4, 23, 30, tzinfo=timezone(timedelta(hours=-1))), "2026-10-05"),
))
def test_auction_week_is_based_on_utc_monday(value: datetime, expected: str) -> None:
    assert auction_week_start(value) == expected


@pytest.mark.parametrize("value", (None, "2026-10-05", datetime(2026, 10, 5)))
def test_auction_week_rejects_ambiguous_timestamps(value) -> None:
    with pytest.raises(ValueError):
        auction_week_start(value)
