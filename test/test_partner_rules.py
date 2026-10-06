from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError
from nonebot_plugin_xiuxian_3.xiuxian.social.partner_rules import (
    partner_definition,
    partner_definition_from_snapshot,
)


@pytest.fixture
def snapshot() -> dict[str, object]:
    return {
        "key": "social.partner",
        "required_realm": "nascent_soul",
        "required_rank": 5,
        "required_layer": 1,
        "invitation_ttl_seconds": 86400,
        "dissolution_ttl_seconds": 86400,
        "reunion_cooldown_seconds": 259200,
        "max_active_relations": 1,
        "cooldown_scope": "pair",
    }


def _content(snapshot: dict[str, object], *, status: str = "active") -> ContentBundle:
    return ContentBundle(
        root=Path("."),
        manifest={},
        _records={
            ("social_interaction", "social.partner"): {
                **{key: value for key, value in snapshot.items() if key != "required_rank"},
                "status": status,
            },
            ("realm", str(snapshot["required_realm"])): {
                "key": snapshot["required_realm"],
                "status": "active",
                "rank": snapshot["required_rank"],
            },
        },
    )


def test_partner_snapshot_roundtrip_is_independent_and_immutable(snapshot: dict[str, object]) -> None:
    definition = partner_definition_from_snapshot(snapshot)
    assert definition.snapshot() == snapshot
    snapshot["required_rank"] = 99
    exported = definition.snapshot()
    exported["required_layer"] = 99
    assert definition.required_rank == 5
    assert definition.required_layer == 1
    with pytest.raises(FrozenInstanceError):
        definition.required_layer = 2


def test_partner_content_uses_the_snapshot_contract(snapshot: dict[str, object]) -> None:
    snapshot.update(required_rank=0, required_layer=0, invitation_ttl_seconds=1)
    assert partner_definition(_content(snapshot)) == partner_definition_from_snapshot(snapshot)


@pytest.mark.parametrize("field", (
    "key", "required_realm", "required_rank", "required_layer", "invitation_ttl_seconds",
    "dissolution_ttl_seconds", "reunion_cooldown_seconds", "max_active_relations", "cooldown_scope",
))
def test_partner_snapshot_rejects_each_missing_field(snapshot: dict[str, object], field: str) -> None:
    del snapshot[field]
    with pytest.raises(ValueError):
        partner_definition_from_snapshot(snapshot)


@pytest.mark.parametrize("value", (None, False, 1, "{}", [], ()))
def test_partner_snapshot_rejects_non_objects(value: object) -> None:
    with pytest.raises(ValueError):
        partner_definition_from_snapshot(value)


def test_partner_snapshot_rejects_extra_fields(snapshot: dict[str, object]) -> None:
    snapshot["fallback"] = True
    with pytest.raises(ValueError):
        partner_definition_from_snapshot(snapshot)


@pytest.mark.parametrize("field", (
    "required_rank", "required_layer", "invitation_ttl_seconds", "dissolution_ttl_seconds",
    "reunion_cooldown_seconds", "max_active_relations",
))
@pytest.mark.parametrize("value", (True, False, "1", 1.0, None, -1))
def test_partner_snapshot_and_content_reject_invalid_numbers(
    snapshot: dict[str, object], field: str, value: object,
) -> None:
    snapshot[field] = value
    with pytest.raises(ValueError):
        partner_definition_from_snapshot(snapshot)
    with pytest.raises(ContentError):
        partner_definition(_content(snapshot))


@pytest.mark.parametrize("field", (
    "invitation_ttl_seconds", "dissolution_ttl_seconds", "reunion_cooldown_seconds", "max_active_relations",
))
def test_partner_snapshot_and_content_reject_zero_limits(snapshot: dict[str, object], field: str) -> None:
    snapshot[field] = 0
    with pytest.raises(ValueError):
        partner_definition_from_snapshot(snapshot)
    with pytest.raises(ContentError):
        partner_definition(_content(snapshot))


@pytest.mark.parametrize(("field", "value"), (
    ("key", "social.mentor"), ("key", None),
    ("required_realm", ""), ("required_realm", " "), ("required_realm", " nascent_soul"),
    ("required_realm", None), ("required_realm", 5),
    ("max_active_relations", 2), ("cooldown_scope", "player"), ("cooldown_scope", None),
))
def test_partner_snapshot_and_content_reject_unsupported_fields(
    snapshot: dict[str, object], field: str, value: object,
) -> None:
    snapshot[field] = value
    with pytest.raises(ValueError):
        partner_definition_from_snapshot(snapshot)
    with pytest.raises(ContentError):
        partner_definition(_content(snapshot))


@pytest.mark.parametrize("status", ("closed", "locked"))
def test_partner_snapshot_remains_valid_after_content_closes(
    snapshot: dict[str, object], status: str,
) -> None:
    assert partner_definition_from_snapshot(snapshot).snapshot() == snapshot
    with pytest.raises(ContentError):
        partner_definition(_content(snapshot, status=status))


def test_partner_content_requires_an_open_realm_reference(snapshot: dict[str, object]) -> None:
    content = _content(snapshot)
    realm = content._records[("realm", "nascent_soul")]
    content = ContentBundle(content.root, content.manifest, {
        **content._records, ("realm", "nascent_soul"): {**realm, "status": "locked"},
    })
    with pytest.raises(ContentError):
        partner_definition(content)
    assert partner_definition_from_snapshot(snapshot).required_realm == "nascent_soul"


def test_partner_content_rejects_missing_required_fields(snapshot: dict[str, object]) -> None:
    del snapshot["invitation_ttl_seconds"]
    with pytest.raises(ContentError, match="social.partner.*invitation_ttl_seconds"):
        partner_definition(_content(snapshot))
