"""Content contract for the data-backed achievement table."""

from __future__ import annotations

import asyncio
import copy
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.content import (
    ContentBundle,
    ContentError,
    bundled_content,
)
from nonebot_plugin_xiuxian_3.xiuxian.rewards.rules import local_reputation_maximum
from nonebot_plugin_xiuxian_3.xiuxian.routine import repository as routine_repository
from nonebot_plugin_xiuxian_3.xiuxian.routine import rules as routine_rules
from nonebot_plugin_xiuxian_3.xiuxian.routine import use_cases as routine_use_cases
from nonebot_plugin_xiuxian_3.xiuxian.routine.achievement_content import (
    achievement_definitions,
)
from nonebot_plugin_xiuxian_3.xiuxian.routine.rules import (
    ACHIEVEMENTS,
    achievement,
    achievement_reward,
    honor_title,
)
from test_routine import MutableClock, _context, _enter_mortal

ACHIEVEMENT_FILE = "功业/功业.json"
SHIPPED = (
    "achievement.first_checkin",
    "achievement.first_craft",
    "achievement.first_dispatch",
    "achievement.codex_5",
    "achievement.tower_10",
    "achievement.three_day_checkin",
)


def _replace_achievement(
    content: ContentBundle, record_key: str, **changes
) -> ContentBundle:
    records = dict(content._records)
    row = copy.deepcopy(dict(records["achievement", record_key]))
    row.update(changes)
    records["achievement", record_key] = row
    return replace(content, _records=records)


def test_achievement_content_matches_the_shipped_table() -> None:
    bundle = ContentBundle.load(Path(__file__).parents[1] / "data")
    definitions = achievement_definitions(bundle)
    assert tuple(definition.key for definition in definitions) == SHIPPED
    assert definitions == ACHIEVEMENTS
    assert len(definitions) == 6

    first = achievement("achievement.first_checkin")
    assert first.label == "首次道历问安"
    assert first.source_event == "routine.checkin.daily"
    assert achievement_reward(first) == {"local_reputation": 3}
    assert first.local_reputation_key == "local.xuantian.new_town"

    dispatch = achievement("achievement.first_dispatch")
    assert achievement_reward(dispatch) == {"title_key": "title.dispatch_helper"}
    assert dispatch.local_reputation_key is None

    third = achievement("achievement.three_day_checkin")
    assert third.label == "三日不辍"
    assert third.source_event == "routine.checkin.daily:3"
    assert achievement_reward(third) == {"local_reputation": 5}

    # Every reference the table uses must resolve against the same content.
    for definition in definitions:
        reward = achievement_reward(definition)
        title = reward.get("title_key")
        if title is not None:
            assert honor_title(str(title)).closed is False
        if "local_reputation" in reward:
            assert definition.local_reputation_key is not None
            assert local_reputation_maximum(definition.local_reputation_key, bundle) > 0


@pytest.mark.parametrize(
    "key,changes",
    [
        ("achievement.first_checkin", {"reward": {"exp": 1}}),
        ("achievement.first_dispatch", {"reward": {"title_key": "title.missing"}}),
        ("achievement.first_checkin", {"reward": {"local_reputation": 3}, "local_reputation_key": None}),
        ("achievement.first_craft", {"local_reputation_key": "local.xuantian.new_town"}),
        ("achievement.first_craft", {"reward": {"service_reputation": 0}}),
        ("achievement.first_craft", {"reward": {"service_reputation": True}}),
        ("achievement.first_craft", {"key": "achievementx.bad"}),
        ("achievement.first_craft", {"label": " "}),
        ("achievement.first_craft", {"source_event": ""}),
        ("achievement.first_checkin", {"local_reputation_key": "local.missing"}),
        ("achievement.first_craft", {"unexpected": 1}),
        ("achievement.first_craft", {"reward": {}}),
    ],
)
def test_achievement_content_rejects_invalid_records(key: str, changes: dict) -> None:
    content = bundled_content()
    with pytest.raises(ContentError):
        achievement_definitions(_replace_achievement(content, key, **changes))


def test_achievement_content_requires_at_least_one_active_record() -> None:
    content = bundled_content()
    records = {
        identity: row
        for identity, row in content._records.items()
        if identity[0] != "achievement"
    }
    with pytest.raises(ContentError, match="missing"):
        achievement_definitions(replace(content, _records=records))


def test_third_checkin_achievement_claims_once_after_three_days(tmp_path: Path) -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
        runtime = create_runtime(data_dir=str(tmp_path), clock=clock)
        user = "achievement-third-checkin"
        try:
            await _enter_mortal(runtime, user)
            status = await runtime.dispatch(_context(user, "honor-status"), "功业录")
            assert status.code == "HONOR_STATUS"
            views = {item["achievement_key"]: item for item in status.data["achievements"]}
            assert len(status.data["achievements"]) == 6
            assert views["achievement.three_day_checkin"]["state"] == "pending"

            early = await runtime.dispatch(
                _context(user, "early", operation_id="early-claim"), "领取功业 6"
            )
            assert early.code == "ACHIEVEMENT_NOT_COMPLETED"

            assert (await runtime.dispatch(_context(user, "daily-1"), "道历问安")).ok
            clock.advance(days=1)
            assert (await runtime.dispatch(_context(user, "daily-2"), "道历问安")).ok
            clock.advance(days=1)
            assert (await runtime.dispatch(_context(user, "daily-3"), "道历问安")).ok

            claimable = await runtime.dispatch(_context(user, "honor-again"), "功业录")
            views = {
                item["achievement_key"]: item for item in claimable.data["achievements"]
            }
            assert views["achievement.three_day_checkin"]["state"] == "claimable"

            claimed = await runtime.dispatch(
                _context(user, "claim", operation_id="third-claim"), "领取功业 6"
            )
            assert claimed.code == "ACHIEVEMENT_CLAIMED", claimed
            assert claimed.data["reward"] == {"local_reputation": 5}
            replay = await runtime.dispatch(
                _context(user, "replay", operation_id="third-claim"), "领取功业 6"
            )
            assert replay.data["idempotent_replay"] is True
            assert replay.message == claimed.message
            duplicate = await runtime.dispatch(
                _context(user, "duplicate", operation_id="third-claim-2"), "领取功业 6"
            )
            assert duplicate.code == "ACHIEVEMENT_ALREADY_CLAIMED"
        finally:
            await runtime.close()

    asyncio.run(run())


def _closed_table(*keys: str) -> tuple:
    return tuple(
        replace(definition, closed=True) if definition.key in keys else definition
        for definition in ACHIEVEMENTS
    )


def test_closed_achievement_stays_in_the_table() -> None:
    content = _replace_achievement(
        bundled_content(), "achievement.first_craft", status="closed"
    )
    definitions = achievement_definitions(content)
    assert tuple(definition.key for definition in definitions) == SHIPPED
    assert [definition.key for definition in definitions if definition.closed] == [
        "achievement.first_craft"
    ]
    assert ACHIEVEMENTS[1].closed is False


def test_locked_achievement_stays_out_of_the_table() -> None:
    content = _replace_achievement(
        bundled_content(), "achievement.first_craft", status="locked"
    )
    definitions = achievement_definitions(content)
    assert [definition.key for definition in definitions] == [
        key for key in SHIPPED if key != "achievement.first_craft"
    ]


def test_invalid_achievement_status_is_rejected() -> None:
    content = _replace_achievement(
        bundled_content(), "achievement.first_craft", status="paused"
    )
    with pytest.raises(ContentError, match="status"):
        achievement_definitions(content)


def test_closed_achievement_keeps_claimed_history_and_numbering(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 22, tzinfo=timezone.utc))
        runtime = create_runtime(data_dir=str(tmp_path), clock=clock)
        user = "achievement-closed"
        try:
            await _enter_mortal(runtime, user)
            assert (await runtime.dispatch(_context(user, "daily-1"), "道历问安")).ok
            claimed = await runtime.dispatch(
                _context(user, "claim", operation_id="closed-claim"), "领取功业 1"
            )
            assert claimed.code == "ACHIEVEMENT_CLAIMED", claimed

            closed = _closed_table(
                "achievement.first_checkin", "achievement.first_craft"
            )
            monkeypatch.setattr(routine_rules, "ACHIEVEMENTS", closed)
            monkeypatch.setattr(routine_use_cases, "ACHIEVEMENTS", closed)
            monkeypatch.setattr(routine_repository, "ACHIEVEMENTS", closed)

            status = await runtime.dispatch(_context(user, "status-closed"), "功业录")
            views = {
                item["achievement_key"]: item for item in status.data["achievements"]
            }
            assert [item["index"] for item in status.data["achievements"]] == [
                1,
                2,
                3,
                4,
                5,
                6,
            ]
            assert views["achievement.first_checkin"]["state"] == "claimed"
            assert views["achievement.first_craft"]["state"] == "content_closed"

            blocked = await runtime.dispatch(
                _context(user, "blocked", operation_id="closed-claim-2"), "领取功业 2"
            )
            assert blocked.code == "CONTENT_CLOSED", blocked
            assert blocked.message == "这项功业依赖的内容尚未开放。"

            replay = await runtime.dispatch(
                _context(user, "replay", operation_id="closed-claim"), "领取功业 1"
            )
            assert replay.code == "ACHIEVEMENT_CLAIMED"
            assert replay.data["idempotent_replay"] is True
        finally:
            await runtime.close()

    asyncio.run(run())
