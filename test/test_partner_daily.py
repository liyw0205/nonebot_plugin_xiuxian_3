from __future__ import annotations

import asyncio
import copy
import json
from dataclasses import replace
from datetime import datetime, timezone
from urllib.parse import unquote

import pytest

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.content import ContentBundle, ContentError, bundled_content
from nonebot_plugin_xiuxian_3.xiuxian.partner_daily_content import (
    partner_daily_definition,
    partner_daily_snapshot,
)
from test_field_journeys import FieldJourney
from test_companion_old_trail_mainline import _database_state
from test_mainline_vertical_slice import _copy_content
from test_dual_cultivation import MutableClock, _player, _partners
from nonebot_plugin_xiuxian_3.xiuxian.social.partner_daily_migration import ensure_partner_daily_schema
from test_wilderness_idle import starter

TASK_KEY = "task.partner.daily.fieldwork"


def _content(mutator):
    base = bundled_content()
    records = copy.deepcopy(dict(base._records))
    mutator(records)
    return replace(base, _records=records)


def test_partner_daily_static_rule_is_strict_and_snapshot_is_frozen():
    content = bundled_content()
    definition = partner_daily_definition(content)
    frozen = json.loads(json.dumps(definition, ensure_ascii=False))
    assert partner_daily_snapshot(frozen) == definition

    changed = _content(lambda records: records["partner_daily_task", TASK_KEY].update(reward_world_merit=999))
    assert partner_daily_definition(changed)["reward_world_merit"] == 999
    assert partner_daily_snapshot(frozen)["reward_world_merit"] == 5
    with pytest.raises(ContentError):
        partner_daily_definition(_content(
            lambda records: records["partner_daily_task", TASK_KEY].update(status="closed")
        ))

    mutations = (
        lambda row: row.update(extra=True),
        lambda row: row.update(target_each=True),
        lambda row: row.update(deposit_keys=["deposit.missing"]),
        lambda row: row.update(aliases=[row["name"], row["name"]]),
        lambda row: row.update(reward_items={"item.tribulation_token": 1}),
    )
    for mutate in mutations:
        def apply(records, mutate=mutate):
            mutate(records["partner_daily_task", TASK_KEY])

        with pytest.raises(ContentError):
            partner_daily_definition(_content(apply))


@pytest.mark.parametrize("field,value", [
    ("target_each", 0), ("target_each", 11), ("target_each", True),
    ("window_seconds", -1), ("window_seconds", 86401),
    ("daily_limit", 2), ("reward_world_merit", "5"),
    ("reward_items", {"item.missing": 1}), ("reward_items", {"item.spirit_water": True}),
    ("deposit_keys", ["deposit.creek_roots", "deposit.creek_roots"]),
    ("source_kind", "client.success"), ("aliases", [" "]),
    ("name", " "), ("status", "unknown"),
])
def test_partner_daily_rejects_invalid_rule_fields(field, value):
    content = _content(lambda records: records["partner_daily_task", TASK_KEY].update({field: value}))
    with pytest.raises(ContentError):
        partner_daily_definition(content)


def test_partner_daily_loader_strict_json_and_closed_rules(tmp_path):
    root = _copy_content(tmp_path)
    path = root / "社交/道侣日课.json"
    original = path.read_text(encoding="utf-8")
    closed = json.loads(original)
    closed["records"][0]["status"] = "closed"
    path.write_text(json.dumps(closed, ensure_ascii=False), encoding="utf-8")
    bundle = ContentBundle.load(root)
    with pytest.raises(ContentError):
        partner_daily_definition(bundle)
    for damaged in (
        original.replace('"target_each": 1', '"target_each": 1, "target_each": 2'),
        original.replace('"target_each": 1', '"target_each": NaN'),
        original.replace('"deposit.creek_roots"', '"deposit.missing"'),
        original.replace('"target_each": 1,', ''),
    ):
        path.write_text(damaged, encoding="utf-8")
        with pytest.raises(ContentError):
            ContentBundle.load(root)


@pytest.mark.parametrize("adapter", ["onebot.v11", "qq.official"])
def test_partner_daily_real_fieldwork_atomic_progress_and_independent_claims(tmp_path, adapter):
    async def run():
        journey = FieldJourney(_copy_content(tmp_path), adapter)
        try:
            for user in ("a", "b"):
                await starter(journey.runtime, user=user, adapter=adapter)
            ids: dict[str, int] = {}
            with journey.runtime.repository._connect() as connection:
                for user in ("a", "b"):
                    row = connection.execute(
                        "SELECT id FROM players WHERE platform=? AND platform_user_id=?",
                        (adapter, user),
                    ).fetchone()
                    ids[user] = int(row["id"])
                    connection.execute(
                        "UPDATE players SET realm_key='nascent_soul', realm_layer=1, dao_name=?, "
                        "stamina=100, energy=100, spirit_stones=1000, world_merit=37 WHERE id=?",
                        (f"同行{user}", ids[user]),
                    )

            for user in ("a", "b"):
                start = await journey.send(
                    "勘察地貌 survey.creek_cliff", f"{user}-survey-start", user=user
                )
                assert start.ok, start.message
                for index, node in enumerate(start.data["site"]["nodes"]):
                    result = await journey.send(
                        f"勘察抉择 survey.creek_cliff {node['choices'][0]['key']}",
                        f"{user}-survey-{index}", user=user,
                    )
                    assert result.ok and result.data["success"], result.message
                    journey.clock.advance(seconds=60)

            old_extract = await journey.send(
                "取用资源脉 deposit.creek_roots gentle", "old-extract", user="a"
            )
            assert old_extract.ok
            journey.clock.advance(minutes=5)
            invitation = await journey.send("邀请结为道侣 同行b", "partner-invite", user="a")
            assert invitation.ok, invitation.message
            relation_id = invitation.data["relation_id"]
            accepted = await journey.send(f"接受道侣邀请 {relation_id}", "partner-accept", user="b")
            assert accepted.ok, accepted.message

            started = await journey.send("开始道侣日课", "daily-start", user="a")
            assert started.ok and started.code == "PARTNER_DAILY_START", started.message
            task_id = started.data["task_id"]
            await journey.render(started, "道侣日课", keyboard=True)
            resumed = await journey.send("开始道侣日课", "daily-start-again", user="a")
            assert resumed.ok and resumed.data["resumed"]
            help_page = await journey.send("修仙帮助 社交", user="a")
            assert help_page.ok and "道侣同行日课" in help_page.message
            assert "UTC" in help_page.message and "领取道侣日课" in help_page.message
            with journey.runtime.repository._connect() as connection:
                assert connection.execute(
                    "SELECT COUNT(*) FROM partner_daily_tasks"
                ).fetchone()[0] == 1
                inventory = json.loads(connection.execute(
                    "SELECT inventory_json FROM players WHERE id=?", (ids["a"],)
                ).fetchone()[0])
                inventory["item.mat.root_wedge"] = 1
                connection.execute(
                    "UPDATE players SET inventory_json=? WHERE id=?",
                    (json.dumps(inventory), ids["a"]),
                )

            maintained = await journey.send(
                "养护资源脉 deposit.creek_roots", "daily-maintenance", user="a"
            )
            assert maintained.ok, maintained.message
            assert (await journey.send("道侣日课", user="a")).data["task"]["progress"] == {"self": 0, "partner": 0}
            journey.clock.advance(minutes=15)
            with journey.runtime.repository._connect() as connection:
                connection.execute("UPDATE players SET status='suspended' WHERE id=?", (ids["b"],))
            unavailable_extract = await journey.send(
                "取用资源脉 deposit.creek_roots gentle", "daily-unavailable-extract", user="a"
            )
            assert unavailable_extract.ok, unavailable_extract.message
            assert (await journey.send("道侣日课", user="a")).data["task"]["progress"] == {"self": 0, "partner": 0}
            with journey.runtime.repository._connect() as connection:
                connection.execute("UPDATE players SET status='active' WHERE id=?", (ids["b"],))
            journey.clock.advance(minutes=5)
            assert (await journey.send(
                f"申请解除道侣 {relation_id}", "daily-pause", user="a"
            )).ok
            paused_extract = await journey.send(
                "取用资源脉 deposit.creek_roots gentle", "daily-paused-extract", user="a"
            )
            assert paused_extract.ok, paused_extract.message
            assert (await journey.send("道侣日课", user="a")).data["task"]["progress"] == {"self": 0, "partner": 0}
            assert (await journey.send(
                f"拒绝解除道侣 {relation_id}", "daily-restore", user="b"
            )).ok
            journey.clock.advance(minutes=5)

            # Closing today's rule cannot rewrite the frozen task or its reward.
            original_content = journey.runtime.repository.content
            records = copy.deepcopy(dict(original_content._records))
            records["partner_daily_task", TASK_KEY]["status"] = "closed"
            records["partner_daily_task", TASK_KEY]["reward_world_merit"] = 999
            records["partner_daily_task", TASK_KEY]["reward_items"] = {"item.spirit_water": 7}
            journey.runtime.repository.content = replace(original_content, _records=records)
            status = await journey.send("道侣日课", user="a")
            assert status.ok and status.data["task"]["progress"] == {"self": 0, "partner": 0}
            replay = await journey.send(
                "取用资源脉 deposit.creek_roots gentle", "old-extract", user="a"
            )
            assert replay.ok and replay.data["idempotent_replay"]
            before_read = _database_state(journey.runtime)
            assert (await journey.send("资源脉预览", user="a", writable=False)).ok
            assert (await journey.send("道侣日课", user="b", writable=False)).ok
            assert _database_state(journey.runtime) == before_read
            with journey.runtime.repository._connect() as connection:
                connection.execute(
                    "CREATE TRIGGER fail_daily_projection BEFORE INSERT ON partner_daily_evidence "
                    "BEGIN SELECT RAISE(ABORT, 'daily projection fault'); END"
                )
            before_projection = _database_state(journey.runtime)
            projection_failed = await journey.send(
                "取用资源脉 deposit.creek_roots gentle", "projection-fault", user="a"
            )
            assert projection_failed.code == "PERSISTENCE_ERROR"
            assert _database_state(journey.runtime) == before_projection
            with journey.runtime.repository._connect() as connection:
                connection.execute("DROP TRIGGER fail_daily_projection")

            journey.fail("daily-b-fail")
            before_failure = _database_state(journey.runtime)
            failed = await journey.send(
                "取用资源脉 deposit.creek_roots gentle", "daily-b-fail", user="b"
            )
            assert failed.code == "PERSISTENCE_ERROR"
            assert _database_state(journey.runtime) == before_failure
            journey.repair()

            # Each successful extraction projects evidence in its source receipt transaction.
            extracts = await asyncio.gather(*(
                journey.send("取用资源脉 deposit.creek_roots gentle", f"daily-{user}-extract", user=user)
                for user in ("a", "b")
            ))
            assert all(result.ok for result in extracts), [result.message for result in extracts]
            repeated = await journey.send(
                "取用资源脉 deposit.creek_roots gentle", "daily-a-extract", user="a"
            )
            assert repeated.ok and repeated.data["idempotent_replay"]

            status_a = await journey.send("道侣日课", user="a")
            status_b = await journey.send("同行日课", user="b")
            assert status_a.ok and status_b.ok
            assert status_a.data["task"]["progress"] == {"self": 1, "partner": 1}
            assert status_b.data["task"]["progress"] == {"self": 1, "partner": 1}
            assert "溪崖药根" in status_a.message
            assert "资源脉预览 deposit.creek_roots" in unquote(status_a.message)
            assert "platform_user_id" not in status_a.data["task"]

            journey.clock.advance(days=1)
            assert (await journey.send("道侣日课", user="a")).data["task"]["status"] == "claimable"
            journey.runtime.repository.content = original_content
            assert (await journey.send("开始道侣日课", "unclaimed-next-day", user="a")).code == "PARTNER_DAILY_ACTIVE"

            journey.fail("daily-claim-fault")
            before_claim_fault = _database_state(journey.runtime)
            failed_claim = await journey.send(f"领取道侣日课 {task_id}", "daily-claim-fault", user="a")
            assert failed_claim.code == "PERSISTENCE_ERROR"
            assert _database_state(journey.runtime) == before_claim_fault
            journey.repair()
            before_claim = _daily_player_assets(journey, ids)
            claim_a, claim_b = await asyncio.gather(
                journey.send(f"领取道侣日课 {task_id}", "daily-claim-a", user="a"),
                journey.send(f"领取道侣日课 {task_id}", "daily-claim-b", user="b"),
            )
            assert claim_a.ok and claim_b.ok, (claim_a.message, claim_b.message)
            assert claim_a.data["reward"] == claim_b.data["reward"] == {
                "item.spirit_water": 1, "world_merit": 5
            }
            after_claim = _daily_player_assets(journey, ids)
            for user in ("a", "b"):
                assert after_claim[user][0] == before_claim[user][0] + 5
                assert after_claim[user][1].get("item.spirit_water", 0) == (
                    before_claim[user][1].get("item.spirit_water", 0) + 1
                )
            assert (await journey.send(
                f"领取道侣日课 {task_id}", "daily-claim-a", user="a"
            )).data["idempotent_replay"]
            assert (await journey.send(
                f"领取道侣日课 {task_id}", "daily-claim-a-again", user="a"
            )).code == "PARTNER_DAILY_CLAIMED"
            assert (await journey.send(
                "领取道侣日课 missing-task", "daily-claim-a", user="a"
            )).code == "OPERATION_CONFLICT"

            with journey.runtime.repository._connect() as connection:
                task = connection.execute(
                    "SELECT status, snapshot_json FROM partner_daily_tasks WHERE task_id=?", (task_id,)
                ).fetchone()
                assert task["status"] == "completed"
                assert json.loads(task["snapshot_json"])["reward_world_merit"] == 5
                assert connection.execute(
                    "SELECT COUNT(*) FROM partner_daily_evidence WHERE task_id=?", (task_id,)
                ).fetchone()[0] == 2
                assert connection.execute(
                    "SELECT COUNT(*) FROM partner_daily_claims WHERE task_id=?", (task_id,)
                ).fetchone()[0] == 2
                assert connection.execute(
                    "SELECT COUNT(*) FROM partner_daily_tasks WHERE relation_id=? AND quota_day=?",
                    (relation_id, started.data["quota_day"]),
                ).fetchone()[0] == 1
                assert connection.execute(
                    "SELECT COUNT(*) FROM economy_ledger_entries WHERE reason='partner_daily'"
                ).fetchone()[0] == 4

            # The additive migration is idempotent and leaves legacy relation/player rows intact.
            before = _legacy_social_rows(journey)
            await journey.restart()
            assert _legacy_social_rows(journey) == before
            assert (await journey.send(
                f"领取道侣日课 {task_id}", "daily-claim-a", user="a"
            )).data["idempotent_replay"]
            before_history = _database_state(journey.runtime)
            for user in ("a", "b"):
                history = await journey.send("道侣日课记录", user=user, writable=False)
                assert history.ok and history.code == "PARTNER_DAILY_HISTORY", history.message
                historical = history.data["tasks"][0]
                assert historical["task_id"] == task_id and historical["status"] == "completed"
                assert historical["progress"] == {"self": 1, "partner": 1}
                assert historical["claimed"] and historical["partner_claimed"]
                assert historical["reward_world_merit"] == 5
                assert historical["reward_items"] == {"item.spirit_water": 1}
                await journey.render(history, f"道侣日课 {task_id}")
            assert _database_state(journey.runtime) == before_history
            with journey.runtime.repository._connect() as connection:
                connection.execute(
                    "UPDATE economy_ledger_entries SET amount=amount+1 "
                    "WHERE operation_id='daily-claim-a' AND asset_key='world_merit'"
                )
            before_corrupt = _database_state(journey.runtime)
            assert (await journey.send(
                f"领取道侣日课 {task_id}", "daily-claim-a", user="a"
            )).code == "PERSISTENCE_ERROR"
            bad_history = await journey.send("道侣日课记录", user="a", writable=False)
            assert bad_history.code == "PERSISTENCE_ERROR" and bad_history.retryable
            assert _database_state(journey.runtime) == before_corrupt
        finally:
            await journey.runtime.close()

    asyncio.run(run())


async def _command(runtime, user, text, operation="", *, writable=True):
    return await runtime.adapters.dispatch(
        "web", CommandContext(adapter="web", user_id=user, operation_id=operation,
                              can_write_assets=writable), text,
    )


@pytest.mark.parametrize("adapter", ["onebot.v11", "qq.official"])
def test_partner_daily_history_pagination_privacy_and_recovery(tmp_path, adapter):
    async def run():
        journey = FieldJourney(_copy_content(tmp_path), adapter)
        try:
            assert (await journey.send("道侣日课记录", user="missing")).code == "PLAYER_NOT_FOUND"
            for user, name in (("a", "同行甲"), ("b", "同行乙"), ("c", "旁观丙")):
                await _player(journey.runtime, adapter, user, name)
            before = _database_state(journey.runtime)
            empty = await journey.send("道侣日课记录", user="a", writable=False)
            assert empty.ok and empty.data["tasks"] == [] and not empty.actions
            for value in ("0", "-1", "10001", "1.0", "x", "1 2", "１", "9" * 5000):
                invalid = await journey.send(f"道侣日课记录 {value}", user="a")
                assert invalid.code == "INVALID_PARTNER_DAILY_COMMAND", invalid.message
            for value in (True, 0, -1, 10001, "1"):
                with pytest.raises(ValueError):
                    await journey.runtime.repository.partner_daily_history(
                        platform=adapter, platform_user_id="a", page=value,
                    )
            assert _database_state(journey.runtime) == before
            invite = await journey.send("邀请结为道侣 同行乙", "history-invite", user="a")
            assert invite.ok, invite.message
            relation_id = invite.data["relation_id"]
            assert (await journey.send(f"接受道侣邀请 {relation_id}", "history-accept", user="b")).ok
            task_ids = []
            for day in range(6):
                start = await journey.send("开始道侣日课", f"history-day-{day}", user="a")
                assert start.ok, start.message
                task_ids.append(start.data["task_id"])
                journey.clock.advance(days=1)
            assert (await journey.send(f"申请解除道侣 {relation_id}", "history-end-ask", user="a")).ok
            assert (await journey.send(f"确认解除道侣 {relation_id}", "history-end-confirm", user="b")).ok
            await journey.restart()
            journey.runtime.repository.content = _content(
                lambda records: records["partner_daily_task", TASK_KEY].update(status="closed", reward_world_merit=999)
            )
            before = _database_state(journey.runtime)
            first = await journey.send("道侣日课记录", user="a", writable=False)
            assert first.ok, first.message
            assert [task["task_id"] for task in first.data["tasks"]] == list(reversed(task_ids[1:]))
            assert first.data["page"] == 1 and first.data["page_size"] == 5 and first.data["has_next"]
            assert [action.command for action in first.actions] == ["道侣日课记录 2"]
            await journey.render(first, "道侣日课记录 2", keyboard=True)
            second = await journey.send(first.actions[0].command, user="a", writable=False)
            assert second.ok and len(second.data["tasks"]) == 1 and not second.data["has_next"]
            assert second.data["tasks"][0]["task_id"] == task_ids[0]
            assert [action.command for action in second.actions] == ["道侣日课记录 1"]
            await journey.render(second, f"道侣日课 {task_ids[0]}", keyboard=True)
            for task in first.data["tasks"] + second.data["tasks"]:
                assert task["status"] == "expired" and not task["relation_active"]
                assert task["progress"] == {"self": 0, "partner": 0}
                assert not task["claimed"] and not task["partner_claimed"]
                assert task["reward_world_merit"] == 5
                assert not {"player_a_id", "player_b_id", "relation_id", "platform", "platform_user_id"} & task.keys()
                assert f"道侣日课 {task['task_id']}" in unquote(first.message + second.message)
            details = await journey.send(f"道侣日课 {task_ids[0]}", user="a", writable=False)
            assert details.ok and details.data["task"] == second.data["tasks"][0]
            other_side = await journey.send("同行日课记录 2", user="b", writable=False)
            assert second.data["tasks"][0]["partner_name"] == "同行乙"
            assert other_side.ok and other_side.data == dict(
                second.data, tasks=[dict(second.data["tasks"][0], partner_name="同行甲")],
            )
            stranger = await journey.send("道侣日课记录", user="c", writable=False)
            assert stranger.ok and stranger.data["tasks"] == []
            assert not any(task_id in stranger.message for task_id in task_ids)
            far_page = await journey.send("道侣日课记录 10000", user="a", writable=False)
            assert far_page.ok and far_page.data["tasks"] == [] and not far_page.data["has_next"]
            assert [action.command for action in far_page.actions] == ["道侣日课记录 9999"]
            assert _database_state(journey.runtime) == before
            with journey.runtime.repository._connect() as connection:
                connection.execute("UPDATE players SET status='suspended' WHERE platform_user_id='b'")
            assert (await journey.send("道侣日课记录", user="b")).code == "PLAYER_SUSPENDED"
            with journey.runtime.repository._connect() as connection:
                connection.execute("UPDATE partner_daily_tasks SET snapshot_json='{}' WHERE task_id=?", (task_ids[-1],))
            before_bad = _database_state(journey.runtime)
            corrupt = await journey.send("道侣日课记录", user="a", writable=False)
            assert corrupt.code == "PERSISTENCE_ERROR" and corrupt.retryable
            assert _database_state(journey.runtime) == before_bad
        finally:
            await journey.runtime.close()

    asyncio.run(run())


def test_partner_daily_permissions_relationship_recovery_and_quota(tmp_path):
    async def run():
        clock = MutableClock(datetime(2026, 11, 21, tzinfo=timezone.utc))
        runtime = create_runtime(data_dir=tmp_path, clock=clock, adapters=("web",))
        try:
            assert (await _command(runtime, "a", "道侣日课")).code == "PLAYER_NOT_FOUND"
            for user, name in (("a", "甲"), ("b", "乙"), ("c", "丙")):
                await _player(runtime, "web", user, name)
            assert (await _command(runtime, "a", "道侣日课")).data["has_partner"] is False
            assert (await _command(runtime, "a", "开始道侣日课", "no-partner")).code == "PARTNER_DAILY_NO_PARTNER"
            relation_id = await _partners(runtime, web=True, invitee_name="乙")
            before = _database_state(runtime)
            for text in ("开始道侣日课 extra", "道侣日课 a b", "领取道侣日课 a b"):
                assert (await _command(runtime, "a", text)).code == "INVALID_PARTNER_DAILY_COMMAND"
            assert not (await _command(runtime, "a", "开始道侣日课", "read-only", writable=False)).ok
            assert _database_state(runtime) == before

            starts = await asyncio.gather(*(
                _command(runtime, user, "开始道侣日课", "start-" + user) for user in ("a", "b")
            ))
            assert all(result.ok for result in starts)
            task_id = starts[0].data["task_id"]
            assert starts[1].data["task_id"] == task_id
            assert (await _command(runtime, "c", f"道侣日课 {task_id}")).code == "PARTNER_DAILY_NOT_FOUND"
            assert (await _command(runtime, "c", f"领取道侣日课 {task_id}")).code == "PARTNER_DAILY_RELATION"
            assert (await _command(runtime, "c", "开始道侣日课", "start-a")).code == "OPERATION_CONFLICT"
            assert (await _command(runtime, "a", "领取道侣日课", "early")).code == "PARTNER_DAILY_NOT_COMPLETE"

            pending = await _command(runtime, "a", f"申请解除道侣 {relation_id}", "dissolution")
            assert pending.ok, pending.message
            frozen = await _command(runtime, "a", f"道侣日课 {task_id}")
            assert frozen.ok and frozen.data["task"]["relation_active"] is False
            assert not frozen.actions
            assert (await _command(runtime, "a", "开始道侣日课", "inactive-start")).code == "PARTNER_DAILY_NO_PARTNER"
            assert (await _command(runtime, "a", "领取道侣日课", "inactive-claim")).code == "PARTNER_DAILY_RELATION"
            assert (await _command(runtime, "b", f"拒绝解除道侣 {relation_id}", "keep-relation")).ok
            assert (await _command(runtime, "a", "开始道侣日课", "recover-active")).data["task_id"] == task_id

            with runtime.repository._connect() as connection:
                connection.execute("UPDATE players SET status='suspended' WHERE platform_user_id='b'")
            assert (await _command(runtime, "b", "道侣日课")).code == "PLAYER_SUSPENDED"
            assert (await _command(runtime, "a", "开始道侣日课", "suspended-partner")).code == "PARTNER_DAILY_PLAYER"
            with runtime.repository._connect() as connection:
                connection.execute("UPDATE players SET status='active' WHERE platform_user_id='b'")

            clock.advance(days=1)
            before = _database_state(runtime)
            expired = await _command(runtime, "a", "道侣日课")
            assert expired.data["task"]["status"] == "expired"
            assert _database_state(runtime) == before
            assert (await _command(runtime, "a", f"领取道侣日课 {task_id}")).code == "PARTNER_DAILY_NOT_COMPLETE"
            next_day = await _command(runtime, "b", "开始道侣日课", "next-day")
            assert next_day.ok and next_day.data["task_id"] != task_id
            assert next_day.data["quota_day"] == "2026-11-22"
            assert (await _command(runtime, "a", "开始道侣日课", "start-a")).data["task_id"] == task_id
            with runtime.repository._connect() as connection:
                assert connection.execute("SELECT COUNT(*) FROM partner_daily_tasks").fetchone()[0] == 2

            assert (await _command(runtime, "a", f"申请解除道侣 {relation_id}", "end-ask")).ok
            assert (await _command(runtime, "b", f"确认解除道侣 {relation_id}", "end-confirm")).ok
            assert (await _command(runtime, "a", "道侣日课")).data["has_partner"] is False
            assert (await _command(runtime, "a", "领取道侣日课", "ended-claim")).code == "PARTNER_DAILY_RELATION"
        finally:
            await runtime.close()

    asyncio.run(run())


def test_partner_daily_closed_corrupt_rules_and_old_schema_migration(tmp_path):
    async def run():
        clock = MutableClock(datetime(2026, 11, 21, tzinfo=timezone.utc))
        runtime = create_runtime(data_dir=tmp_path, clock=clock, adapters=("web",))
        try:
            await _player(runtime, "web", "a", "甲")
            await _player(runtime, "web", "b", "乙")
            await _partners(runtime, web=True, invitee_name="乙")
            # A pre-feature database has all legacy tables and data, and none of the daily tables.
            with runtime.repository._connect() as connection:
                for table in ("partner_daily_claims", "partner_daily_evidence", "partner_daily_tasks"):
                    connection.execute(f"DROP TABLE {table}")
            before = _database_state(runtime)
            with runtime.repository._connect() as connection:
                ensure_partner_daily_schema(connection)
                ensure_partner_daily_schema(connection)
            after = _database_state(runtime)
            # Compare every legacy INSERT, including players, relationships and operation receipts.
            assert [line for line in after if line.startswith("INSERT INTO")]
            assert [line for line in after if line.startswith("INSERT INTO")] == [
                line for line in before if line.startswith("INSERT INTO")
            ]
            for mutate in (
                lambda row: row.update(status="closed"),
                lambda row: row.update(target_each=True),
                lambda row: row.update(deposit_keys=["deposit.missing"]),
                lambda row: row.update(source_kind="client.success"),
            ):
                runtime.repository.content = _content(
                    lambda records: mutate(records["partner_daily_task", TASK_KEY])
                )
                before = _database_state(runtime)
                result = await _command(runtime, "a", "开始道侣日课", "unavailable")
                assert result.code == "PARTNER_DAILY_UNAVAILABLE"
                assert _database_state(runtime) == before
            runtime.repository.content = _content(
                lambda records: records["partner_daily_task", TASK_KEY].update(window_seconds=60)
            )
            started = await _command(runtime, "a", "开始道侣日课", "short-task")
            assert started.ok
            clock.advance(seconds=60)
            assert (await _command(runtime, "a", "道侣日课")).data["task"]["status"] == "expired"
            restored = await _command(runtime, "a", "开始道侣日课", "same-day-expired")
            assert restored.ok and restored.data["task_id"] == started.data["task_id"]
            assert restored.data["status"] == "expired"
            with runtime.repository._connect() as connection:
                connection.execute("UPDATE partner_daily_tasks SET snapshot_json='{}'")
            before_bad = _database_state(runtime)
            assert (await _command(runtime, "a", "道侣日课")).code == "PERSISTENCE_ERROR"
            assert (await _command(runtime, "a", "开始道侣日课", "short-task")).code == "PERSISTENCE_ERROR"
            assert _database_state(runtime) == before_bad
        finally:
            await runtime.close()

    asyncio.run(run())


def _daily_player_assets(journey: FieldJourney, ids: dict[str, int]) -> dict[str, tuple[int, dict[str, int]]]:
    with journey.runtime.repository._connect() as connection:
        result = {}
        for user, player_id in ids.items():
            row = connection.execute(
                "SELECT world_merit, inventory_json FROM players WHERE id=?", (player_id,)
            ).fetchone()
            result[user] = (int(row["world_merit"]), json.loads(row["inventory_json"]))
        return result


def _legacy_social_rows(journey: FieldJourney) -> tuple:
    with journey.runtime.repository._connect() as connection:
        return tuple(
            connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in (
                "players", "partner_relations", "partner_tasks",
                "partner_cultivation_invitations", "partner_cultivation_settlements",
            )
        )
