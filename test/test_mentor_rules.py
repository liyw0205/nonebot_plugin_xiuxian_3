from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError, bundled_content
from nonebot_plugin_xiuxian_3.xiuxian.social.mentor_rules import (
    is_graduation_ready,
    mentor_graduation_definition,
    mentor_graduation_from_snapshot,
)


@pytest.fixture
def snapshot() -> dict[str, object]:
    return {
        "key": "social.mentor_graduation",
        "required_realm": "qi_gathering",
        "required_rank": 2,
        "required_layer": 3,
        "local_reputation_key": "local.xuantian.new_town",
        "local_reputation_maximum": 100,
        "apprentice_local_reputation": 10,
        "master_contribution": 20,
        "service_reputation": 2,
    }


def _replace(content: ContentBundle, kind: str, key: str, **values: object) -> ContentBundle:
    record = content.require(kind, key)
    return ContentBundle(content.root, content.manifest, {
        **content._records, (kind, key): {**record, **values},
    })


def _content(snapshot: dict[str, object], *, status: str = "active") -> ContentBundle:
    content = bundled_content()
    record = {
        "name": "师门出师", "desc": "修有所成，见证出师。", "status": status,
        **{key: value for key, value in snapshot.items() if key not in {"required_rank", "local_reputation_maximum"}},
    }
    return ContentBundle(content.root, content.manifest, {
        **content._records,
        ("social_interaction", "social.mentor_graduation"): record,
        ("realm", "qi_gathering"): {
            **content.require("realm", "qi_gathering"), "rank": snapshot.get("required_rank"),
        },
        ("location", "xuantian.new_town"): {
            **content.require("location", "xuantian.new_town"),
            "local_reputation_maximum": snapshot.get("local_reputation_maximum"),
        },
    })


def test_graduation_definition_uses_current_content_and_is_immutable(snapshot: dict[str, object]) -> None:
    definition = mentor_graduation_definition(_content(snapshot))
    assert definition.snapshot() == snapshot
    snapshot["master_contribution"] = 99
    exported = definition.snapshot()
    exported["service_reputation"] = 99
    assert definition.master_contribution == 20
    assert definition.service_reputation == 2
    with pytest.raises(FrozenInstanceError):
        definition.required_layer = 1


def test_graduation_content_and_snapshot_allow_zero_rewards(snapshot: dict[str, object]) -> None:
    snapshot.update(apprentice_local_reputation=0, master_contribution=0, service_reputation=0)
    definition = mentor_graduation_definition(_content(snapshot))
    assert definition.snapshot() == snapshot
    assert mentor_graduation_from_snapshot(snapshot) == definition


@pytest.mark.parametrize("field", (
    "key", "required_realm", "required_rank", "required_layer", "local_reputation_key",
    "local_reputation_maximum", "apprentice_local_reputation", "master_contribution", "service_reputation",
))
def test_graduation_snapshot_rejects_missing_fields(snapshot: dict[str, object], field: str) -> None:
    del snapshot[field]
    with pytest.raises(ValueError):
        mentor_graduation_from_snapshot(snapshot)


@pytest.mark.parametrize("value", (None, False, 1, "{}", [], ()))
def test_graduation_snapshot_rejects_non_objects(value: object) -> None:
    with pytest.raises(ValueError):
        mentor_graduation_from_snapshot(value)


def test_graduation_snapshot_rejects_extra_fields(snapshot: dict[str, object]) -> None:
    snapshot["name"] = "师门出师"
    with pytest.raises(ValueError):
        mentor_graduation_from_snapshot(snapshot)


@pytest.mark.parametrize("field", (
    "required_rank", "required_layer", "local_reputation_maximum",
    "apprentice_local_reputation", "master_contribution", "service_reputation",
))
@pytest.mark.parametrize("value", (True, False, "1", 1.0, None, -1))
def test_graduation_snapshot_and_content_reject_invalid_numbers(
    snapshot: dict[str, object], field: str, value: object,
) -> None:
    snapshot[field] = value
    with pytest.raises(ValueError):
        mentor_graduation_from_snapshot(snapshot)
    with pytest.raises(ContentError):
        mentor_graduation_definition(_content(snapshot))


@pytest.mark.parametrize(("field", "value"), (
    ("key", "social.partner"), ("key", None),
    ("required_realm", ""), ("required_realm", " qi_gathering"),
    ("required_realm", None), ("required_realm", 2),
    ("local_reputation_key", ""), ("local_reputation_key", "local."),
    ("local_reputation_key", "local. "), ("local_reputation_key", "faction.xuantian"),
    ("local_reputation_key", " local.xuantian.new_town"), ("local_reputation_key", None),
    ("local_reputation_key", 2), ("local_reputation_maximum", 0),
))
def test_graduation_snapshot_and_content_reject_invalid_fields(
    snapshot: dict[str, object], field: str, value: object,
) -> None:
    snapshot[field] = value
    with pytest.raises(ValueError):
        mentor_graduation_from_snapshot(snapshot)
    with pytest.raises(ContentError):
        mentor_graduation_definition(_content(snapshot))


@pytest.mark.parametrize("field", (
    "required_realm", "required_layer", "local_reputation_key",
    "apprentice_local_reputation", "master_contribution", "service_reputation",
))
def test_graduation_content_rejects_missing_rule_fields(snapshot: dict[str, object], field: str) -> None:
    del snapshot[field]
    with pytest.raises(ContentError, match=field):
        mentor_graduation_definition(_content(snapshot))


@pytest.mark.parametrize("field", ("name", "desc"))
@pytest.mark.parametrize("value", (None, "", " ", 1))
def test_graduation_content_requires_record_copy(
    snapshot: dict[str, object], field: str, value: object,
) -> None:
    content = _replace(_content(snapshot), "social_interaction", "social.mentor_graduation", **{field: value})
    with pytest.raises(ContentError, match=field):
        mentor_graduation_definition(content)


@pytest.mark.parametrize("layer", (0, 11))
def test_graduation_content_rejects_required_layer_outside_realm(
    snapshot: dict[str, object], layer: int,
) -> None:
    snapshot["required_layer"] = layer
    with pytest.raises(ContentError, match="required_layer"):
        mentor_graduation_definition(_content(snapshot))


@pytest.mark.parametrize(("kind", "key"), (
    ("social_interaction", "social.mentor_graduation"),
    ("realm", "qi_gathering"),
    ("location", "xuantian.new_town"),
))
@pytest.mark.parametrize("status", ("closed", "locked"))
def test_graduation_requires_open_content_but_history_is_self_contained(
    snapshot: dict[str, object], kind: str, key: str, status: str,
) -> None:
    content = _replace(_content(snapshot), kind, key, status=status)
    with pytest.raises(ContentError):
        mentor_graduation_definition(content)
    assert mentor_graduation_from_snapshot(snapshot).snapshot() == snapshot


@pytest.mark.parametrize(("kind", "key"), (
    ("social_interaction", "social.mentor_graduation"),
    ("realm", "qi_gathering"),
    ("location", "xuantian.new_town"),
))
def test_graduation_content_rejects_missing_references(
    snapshot: dict[str, object], kind: str, key: str,
) -> None:
    content = _content(snapshot)
    records = dict(content._records)
    del records[(kind, key)]
    with pytest.raises(ContentError):
        mentor_graduation_definition(ContentBundle(content.root, content.manifest, records))
    assert mentor_graduation_from_snapshot(snapshot).snapshot() == snapshot


@pytest.mark.parametrize(("stage", "realm", "layer", "ready"), (
    ("mortal", "mortal", 0, False), ("seeker", "qi_gathering", 3, False),
    ("cultivator", "qi_sensing", 10, False),
    ("cultivator", "qi_gathering", 2, False), ("cultivator", "qi_gathering", 3, True),
    ("cultivator", "qi_gathering", 10, True),
    ("cultivator", "foundation", 1, True), ("cultivator", "golden_core", 1, True),
    ("cultivator", "nascent_soul", 1, True), ("cultivator", "soul_transformation", 1, True),
    ("cultivator", "void_refining", 1, True), ("cultivator", "dao_union", 1, True),
    ("cultivator", "tribulation", 1, True), ("cultivator", "unknown", 3, False),
    ("cultivator", "foundation", 0, False), ("cultivator", "foundation", 11, False),
    ("cultivator", "qi_gathering", True, False), ("cultivator", "qi_gathering", "3", False),
    ("cultivator", "qi_gathering", 3.0, False), ("cultivator", "qi_gathering", None, False),
))
def test_graduation_uses_a_lower_bound_and_valid_current_realm(
    snapshot: dict[str, object], stage: str, realm: str, layer: object, ready: bool,
) -> None:
    content = _content(snapshot)
    assert is_graduation_ready(stage, realm, layer, mentor_graduation_definition(content), content) is ready


def test_graduation_uses_changed_content_rank_and_layer_bounds(snapshot: dict[str, object]) -> None:
    content = _content(snapshot)
    definition = mentor_graduation_definition(content)
    reordered = _replace(content, "realm", "foundation", rank=1)
    assert not is_graduation_ready("cultivator", "foundation", 10, definition, reordered)
    narrowed = _replace(content, "realm", "foundation", layer_min=2, layer_max=5)
    assert not is_graduation_ready("cultivator", "foundation", 1, definition, narrowed)
    assert is_graduation_ready("cultivator", "foundation", 2, definition, narrowed)
    assert not is_graduation_ready("cultivator", "foundation", 6, definition, narrowed)


@pytest.mark.parametrize("status", ("closed", "locked"))
def test_graduation_rejects_inactive_current_realm(snapshot: dict[str, object], status: str) -> None:
    content = _content(snapshot)
    definition = mentor_graduation_definition(content)
    content = _replace(content, "realm", "foundation", status=status)
    assert not is_graduation_ready("cultivator", "foundation", 1, definition, content)


@pytest.mark.parametrize(("field", "value"), (
    ("rank", True), ("rank", -1), ("rank", "3"), ("rank", 3.0),
    ("layer_min", False), ("layer_min", -1), ("layer_min", "1"),
    ("layer_max", 1.0), ("layer_max", None), ("layer_max", 0),
))
def test_graduation_rejects_corrupt_current_realm_metadata(
    snapshot: dict[str, object], field: str, value: object,
) -> None:
    content = _content(snapshot)
    definition = mentor_graduation_definition(content)
    content = _replace(content, "realm", "foundation", **{field: value})
    with pytest.raises(ContentError):
        is_graduation_ready("cultivator", "foundation", 1, definition, content)


def test_graduation_new_rules_change_qualification_and_rewards(snapshot: dict[str, object]) -> None:
    content = _content(snapshot)
    original = mentor_graduation_definition(content)
    content = _replace(
        content, "social_interaction", "social.mentor_graduation",
        required_realm="foundation", required_layer=2, apprentice_local_reputation=7,
        master_contribution=9, service_reputation=1,
    )
    content = _replace(content, "location", "xuantian.new_town", local_reputation_maximum=41)
    changed = mentor_graduation_definition(content)
    assert changed.required_rank == 3
    assert changed.local_reputation_maximum == 41
    assert (changed.apprentice_local_reputation, changed.master_contribution, changed.service_reputation) == (7, 9, 1)
    assert not is_graduation_ready("cultivator", "foundation", 1, changed, content)
    assert is_graduation_ready("cultivator", "foundation", 2, changed, content)
    assert mentor_graduation_from_snapshot(original.snapshot()).snapshot() == snapshot


def test_graduation_defaults_read_bundled_content() -> None:
    definition = mentor_graduation_definition()
    assert definition.key == "social.mentor_graduation"
    assert is_graduation_ready("cultivator", "foundation", 1, definition)
