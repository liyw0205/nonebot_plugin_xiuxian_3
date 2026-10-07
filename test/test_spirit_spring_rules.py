from __future__ import annotations

import json

import pytest

from nonebot_plugin_xiuxian_3.xiuxian.content import ContentError, bundled_content
from nonebot_plugin_xiuxian_3.xiuxian.events.spirit_spring_rules import (
    spirit_spring_definition,
    spirit_spring_result,
)


def test_spirit_spring_result_returns_frozen_configuration() -> None:
    definition = spirit_spring_definition()
    payload = json.dumps(
        {"success": False, "configuration": definition.snapshot()},
        ensure_ascii=False,
        sort_keys=True,
    )

    result, restored = spirit_spring_result(payload)

    assert result["success"] is False
    assert restored.snapshot() == definition.snapshot()


def test_spirit_spring_definition_rejects_a_record_with_the_wrong_key() -> None:
    content = bundled_content()

    class WrongKeyContent:
        def require(self, kind: str, key: str, *, include_locked: bool = True):
            record = content.require(kind, key, include_locked=include_locked)
            if kind == "event":
                record["key"] = "event.other"
            return record

    with pytest.raises(ContentError, match="event fields are invalid"):
        spirit_spring_definition(WrongKeyContent())  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "payload",
    (
        '{"success":false,"success":true,"configuration":{}}',
        '{"success":false,"configuration":{"event_key":"event.spirit_spring","event_key":"tampered"}}',
        "not-json",
        "[]",
    ),
)
def test_spirit_spring_result_rejects_invalid_persisted_json(payload: str) -> None:
    with pytest.raises(ContentError):
        spirit_spring_result(payload)


def test_spirit_spring_result_rejects_incomplete_snapshot() -> None:
    with pytest.raises(ContentError, match="configuration snapshot is missing"):
        spirit_spring_result('{"success":false}')


def test_spirit_spring_result_rejects_extra_top_level_fields() -> None:
    definition = spirit_spring_definition()
    payload = json.dumps(
        {
            "success": False,
            "configuration": definition.snapshot(),
            "unexpected": "value",
        },
        ensure_ascii=False,
    )

    with pytest.raises(ContentError, match="invalid fields"):
        spirit_spring_result(payload)


def test_spirit_spring_result_requires_boolean_success() -> None:
    definition = spirit_spring_definition()
    payload = json.dumps(
        {"success": 1, "configuration": definition.snapshot()},
        ensure_ascii=False,
    )

    with pytest.raises(ContentError, match="success is invalid"):
        spirit_spring_result(payload)


def test_spirit_spring_result_rejects_unreachable_contribution_threshold() -> None:
    definition = spirit_spring_definition()
    snapshot = definition.snapshot()
    snapshot["minimum_contribution"] = snapshot["contribution_cap"] + 1
    payload = json.dumps({"success": False, "configuration": snapshot}, ensure_ascii=False)

    with pytest.raises(ContentError, match="exceeds contribution cap"):
        spirit_spring_result(payload)


@pytest.mark.parametrize("settled_at", ("2026-09-23T20:05:00", "not-a-time", 1, None))
def test_spirit_spring_result_requires_timezone_aware_settled_at(settled_at: object) -> None:
    definition = spirit_spring_definition()
    payload = json.dumps(
        {
            "success": True,
            "settled_at": settled_at,
            "configuration": definition.snapshot(),
        },
        ensure_ascii=False,
    )

    with pytest.raises(ContentError, match="settled_at"):
        spirit_spring_result(payload)
