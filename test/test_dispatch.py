from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime
from nonebot_plugin_xiuxian_3.xiuxian.exploration.rules import battle_roll_bp, settlement_result
from nonebot_plugin_xiuxian_3.xiuxian.specials.dispatch_rules import (
    DISPATCHES,
    HERB_SEARCH,
    TOWN_DELIVERY,
    WORKSHOP_HELP,
    choose_outcome,
)


class MutableClock:
    def __init__(self, value: datetime):
        self.value = value

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **kwargs: int) -> None:
        self.value += timedelta(**kwargs)


def _context(adapter: str, user: str, operation_id: str) -> CommandContext:
    return CommandContext(adapter=adapter, user_id=user, operation_id=operation_id)


async def _send(runtime, adapter: str, user: str, operation_id: str, text: str):
    return await runtime.adapters.dispatch(adapter, _context(adapter, user, operation_id), text)


async def _mortal(runtime, adapter: str, user: str, prefix: str) -> None:
    assert (await _send(runtime, adapter, user, f"{prefix}-create", "开始修仙")).ok
    assert (await _send(runtime, adapter, user, f"{prefix}-seek", "寻仙问道")).ok


async def _cultivator(runtime, adapter: str, user: str, prefix: str) -> None:
    await _mortal(runtime, adapter, user, prefix)
    assert (await _send(runtime, adapter, user, f"{prefix}-read", "完成引导 阅读")).ok
    assert (await _send(runtime, adapter, user, f"{prefix}-outskirts", "前往近郊")).ok
    assert (await _send(runtime, adapter, user, f"{prefix}-gather-lesson", "完成引导 采集")).ok
    assert (await _send(runtime, adapter, user, f"{prefix}-service", "完成引导 炼丹")).ok
    assert (await _send(runtime, adapter, user, f"{prefix}-path", "选择道途 体修")).code == "CULTIVATION_ENTERED"


async def _gather_wood(runtime, clock: MutableClock, adapter: str, user: str, prefix: str) -> None:
    operation_id = next(
        f"{prefix}-gather-{index}"
        for index in range(10000)
        if settlement_result("explore.gather_outskirts", f"{prefix}-gather-{index}").get("item.mat.wood") == 1
        and battle_roll_bp(f"{prefix}-gather-{index}:battle") >= 1000
    )
    started = await _send(runtime, adapter, user, operation_id, "开始探索 近郊采集")
    assert started.code == "EXPLORATION_STARTED"
    clock.advance(seconds=30)
    settled = await _send(runtime, adapter, user, f"{prefix}-gather-settle", "结算探索")
    assert settled.code == "EXPLORATION_SETTLED"
    assert settled.data["result"]["item.mat.wood"] == 1


def _forced_dispatch_seed(dispatch_key: str, outcome: str) -> str:
    definition = DISPATCHES[dispatch_key]
    return next(
        seed
        for index in range(10000)
        if (seed := f"forced-{dispatch_key}-{index}")
        and choose_outcome(definition, seed) == outcome
    )


def _force_uuid(seed: str, assignment: str):
    return patch(
        "nonebot_plugin_xiuxian_3.xiuxian.specials.dispatch_repository.uuid4",
        side_effect=[SimpleNamespace(hex=seed), SimpleNamespace(hex=assignment)],
    )


def _player_row(runtime, adapter: str, user: str) -> tuple[int, str, int, int]:
    with sqlite3.connect(runtime.settings.database_path) as connection:
        row = connection.execute(
            "SELECT id, inventory_json, stamina, energy FROM players WHERE platform = ? AND platform_user_id = ?",
            (adapter, user),
        ).fetchone()
    assert row is not None
    return int(row[0]), str(row[1]), int(row[2]), int(row[3])


def test_qq_dispatch_town_freezes_result_and_settles_idempotently() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 27, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            adapter, user = "qq.official", "qq-dispatch-town"
            await _cultivator(runtime, adapter, user, "qq")
            cultivation = await _send(runtime, adapter, user, "qq-cultivate", "开始修炼")
            assert cultivation.code == "CULTIVATION_STARTED"
            busy_dispatch = await _send(runtime, adapter, user, "qq-cultivation-lock", "接受派遣 dispatch.town_delivery")
            assert busy_dispatch.code == "DISPATCH_SLOT_BUSY"
            cancelled_cultivation = await _send(runtime, adapter, user, "qq-cancel-cultivation", "取消修炼")
            assert cancelled_cultivation.code == "CULTIVATION_CANCELLED"
            preview = await _send(runtime, adapter, user, "qq-preview", "派遣预览 dispatch.town_delivery")
            assert preview.code == "DISPATCH_PREVIEW"
            assert preview.data["dispatches"][0]["ready"] is True
            delayed_seed = _forced_dispatch_seed(TOWN_DELIVERY, "delayed")
            with _force_uuid(delayed_seed, "town-delayed"):
                accepted = await _send(runtime, adapter, user, "qq-accept", "接受派遣 dispatch.town_delivery")
            assert accepted.code == "DISPATCH_ACCEPTED"
            assert accepted.data["outcome"] == "delayed"
            replay_accept = await _send(runtime, adapter, user, "qq-accept", "接受派遣 dispatch.town_delivery")
            assert replay_accept.data["idempotent_replay"] is True
            assert replay_accept.data["assignment_id"] == accepted.data["assignment_id"]
            conflict = await _send(runtime, adapter, user, "qq-accept", "接受派遣 dispatch.herb_search")
            assert conflict.code == "OPERATION_CONFLICT"
            busy = await _send(runtime, adapter, user, "qq-busy", "接受派遣 dispatch.town_delivery")
            assert busy.code == "DISPATCH_SLOT_BUSY"
            exploration_busy = await _send(runtime, adapter, user, "qq-exploration-busy", "开始探索 近郊采集")
            assert exploration_busy.code == "EXPLORATION_BUSY"
            early = await _send(runtime, adapter, user, "qq-early", "结算派遣")
            assert early.code == "DISPATCH_NOT_READY"

            assignment = accepted.data["assignment_id"]
            with sqlite3.connect(runtime.settings.database_path) as connection:
                snapshot_text, before_stones = connection.execute(
                    "SELECT snapshot_json, (SELECT spirit_stones FROM players WHERE id = dispatch_assignments.player_id) "
                    "FROM dispatch_assignments WHERE assignment_id = ?",
                    (assignment,),
                ).fetchone()
            snapshot = json.loads(snapshot_text)
            assert snapshot["outcome"] == accepted.data["outcome"]
            assert snapshot["risk_pool"] == "dispatch.town.v0.1"
            assert "cultivation" not in snapshot["reward"]
            assert datetime.fromisoformat(accepted.data["ends_at"]) - datetime.fromisoformat(
                accepted.data["accepted_at"]
            ) == timedelta(minutes=45)
            clock.value = datetime.fromisoformat(accepted.data["ends_at"])
            settled = await _send(runtime, adapter, user, "qq-settle", "结算派遣")
            assert settled.code == "DISPATCH_SETTLED"
            assert settled.data["outcome"] == accepted.data["outcome"]
            replay = await _send(runtime, adapter, user, "qq-settle", "结算派遣")
            assert replay.data["idempotent_replay"] is True
            assert replay.data["reward"] == settled.data["reward"]
            with sqlite3.connect(runtime.settings.database_path) as connection:
                after_stones = connection.execute(
                    "SELECT spirit_stones FROM players WHERE platform = ? AND platform_user_id = ?",
                    (adapter, user),
                ).fetchone()[0]
            assert after_stones - before_stones == settled.data["reward"].get("spirit_stones", 0)
            assert settled.data["reward"].get("local.xuantian.new_town", 0) in (1, 3)

            with sqlite3.connect(runtime.settings.database_path) as connection:
                stones_before_success = connection.execute(
                    "SELECT spirit_stones FROM players WHERE platform = ? AND platform_user_id = ?",
                    (adapter, user),
                ).fetchone()[0]
            success_seed = _forced_dispatch_seed(TOWN_DELIVERY, "success")
            with _force_uuid(success_seed, "town-success"):
                success_accept = await _send(
                    runtime, adapter, user, "qq-accept-success", "接受派遣 dispatch.town_delivery"
                )
            assert success_accept.code == "DISPATCH_ACCEPTED"
            assert success_accept.data["outcome"] == "success"
            clock.value = datetime.fromisoformat(success_accept.data["ends_at"])
            success = await _send(runtime, adapter, user, "qq-settle-success", "结算派遣")
            assert success.code == "DISPATCH_SETTLED"
            assert success.data["reward"]["spirit_stones"] == 30
            with sqlite3.connect(runtime.settings.database_path) as connection:
                stones_after_success = connection.execute(
                    "SELECT spirit_stones FROM players WHERE platform = ? AND platform_user_id = ?",
                    (adapter, user),
                ).fetchone()[0]
            assert stones_after_success - stones_before_success == 30
            await runtime.close()

    asyncio.run(run())


def test_onebot_herb_dispatch_partial_and_failure_refund() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 27, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            adapter, user = "onebot.v11", "ob-dispatch-herb"
            await _mortal(runtime, adapter, user, "ob")
            unavailable = await _send(runtime, adapter, user, "ob-herb-locked", "接受派遣 dispatch.herb_search")
            assert unavailable.code == "DISPATCH_REQUIREMENT_MISSING"
            assert (await _send(runtime, adapter, user, "ob-outskirts", "前往近郊")).ok
            assert (await _send(runtime, adapter, user, "ob-gather-lesson", "完成引导 采集")).ok

            partial_seed = _forced_dispatch_seed(HERB_SEARCH, "partial")
            with _force_uuid(partial_seed, "herb-partial"):
                accepted = await _send(runtime, adapter, user, "ob-herb-partial", "接受派遣 dispatch.herb_search")
            assert accepted.code == "DISPATCH_ACCEPTED"
            assert accepted.data["outcome"] == "partial"
            clock.advance(hours=1)
            settled = await _send(runtime, adapter, user, "ob-herb-partial-settle", "结算派遣")
            assert settled.code == "DISPATCH_SETTLED"
            assert settled.data["outcome"] == "partial"
            assert 1 <= settled.data["reward"]["item.herb.blood_grass"] <= 2
            assert "codex.dispatch.herb_search" not in settled.data["reward"]
            assert not any(key in settled.data["reward"] for key in ("cultivation", "total_cultivation"))

            _, _, stamina_before, _ = _player_row(runtime, adapter, user)
            failed_seed = _forced_dispatch_seed(HERB_SEARCH, "failed")
            with _force_uuid(failed_seed, "herb-failed"):
                failed_accept = await _send(runtime, adapter, user, "ob-herb-failed", "接受派遣 dispatch.herb_search")
            assert failed_accept.code == "DISPATCH_ACCEPTED"
            assert failed_accept.data["outcome"] == "failed"
            clock.advance(hours=1)
            failed = await _send(runtime, adapter, user, "ob-herb-failed-settle", "结算派遣")
            assert failed.data["reward"] == {}
            assert failed.data["refunded"] == {"stamina": 2}
            _, _, stamina_after, _ = _player_row(runtime, adapter, user)
            assert stamina_before - stamina_after == 2
            await runtime.close()

    asyncio.run(run())


def test_onebot_successful_herb_dispatch_records_codex_clue() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 27, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            adapter, user = "onebot.v11", "ob-dispatch-herb-success"
            await _mortal(runtime, adapter, user, "herb-success")
            assert (await _send(runtime, adapter, user, "herb-success-outskirts", "前往近郊")).ok
            assert (await _send(runtime, adapter, user, "herb-success-lesson", "完成引导 采集")).ok

            success_seed = _forced_dispatch_seed(HERB_SEARCH, "success")
            with _force_uuid(success_seed, "herb-success-assignment"):
                accepted = await _send(
                    runtime, adapter, user, "herb-success-accept", "接受派遣 dispatch.herb_search"
                )
            assert accepted.code == "DISPATCH_ACCEPTED"
            clock.value = datetime.fromisoformat(accepted.data["ends_at"])
            settled = await _send(runtime, adapter, user, "herb-success-settle", "结算派遣")
            assert settled.code == "DISPATCH_SETTLED"
            assert settled.data["reward"]["codex.dispatch.herb_search"] == 1

            player_id, _, _, _ = _player_row(runtime, adapter, user)
            with sqlite3.connect(runtime.settings.database_path) as connection:
                entry = connection.execute(
                    "SELECT category, first_seen_operation_id FROM codex_entries "
                    "WHERE player_id = ? AND entry_key = ?",
                    (player_id, "codex.dispatch.herb_search"),
                ).fetchone()
                count = connection.execute(
                    "SELECT COUNT(*) FROM codex_entries WHERE player_id = ? AND entry_key = ?",
                    (player_id, "codex.dispatch.herb_search"),
                ).fetchone()[0]
            assert entry == ("dispatch", settled.operation_id)
            assert count == 1
            await runtime.close()

    asyncio.run(run())


def test_onebot_workshop_uses_public_wood_source_and_failure_refund() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 27, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            adapter, user = "onebot.v11", "ob-dispatch-workshop"
            await _mortal(runtime, adapter, user, "workshop")
            assert (await _send(runtime, adapter, user, "workshop-outskirts", "前往近郊")).ok
            assert (await _send(runtime, adapter, user, "workshop-gather-lesson", "完成引导 采集")).ok
            await _gather_wood(runtime, clock, adapter, user, "workshop-wood-a")
            await _gather_wood(runtime, clock, adapter, user, "workshop-wood-b")
            assert (await _send(runtime, adapter, user, "workshop-service", "完成引导 炼丹")).ok
            player_id, inventory_text, _, energy_before = _player_row(runtime, adapter, user)
            assert json.loads(inventory_text)["item.mat.wood"] == 2

            failed_seed = _forced_dispatch_seed(WORKSHOP_HELP, "failed")
            with _force_uuid(failed_seed, "workshop-failed"):
                accepted = await _send(runtime, adapter, user, "workshop-accept", "接受派遣 dispatch.workshop_help")
            assert accepted.code == "DISPATCH_ACCEPTED"
            assert accepted.data["outcome"] == "failed"
            _, inventory_after_accept, _, energy_after_accept = _player_row(runtime, adapter, user)
            assert "item.mat.wood" not in json.loads(inventory_after_accept)
            assert energy_before - energy_after_accept == 4
            clock.advance(hours=2)
            settled = await _send(runtime, adapter, user, "workshop-settle", "结算派遣")
            assert settled.code == "DISPATCH_SETTLED"
            assert settled.data["refunded"] == {"item.mat.wood": 1}
            _, inventory_after_settle, _, _ = _player_row(runtime, adapter, user)
            assert json.loads(inventory_after_settle)["item.mat.wood"] == 1
            with sqlite3.connect(runtime.settings.database_path) as connection:
                status, outcome = connection.execute(
                    "SELECT status, outcome FROM dispatch_assignments WHERE player_id = ?",
                    (player_id,),
                ).fetchone()
            assert (status, outcome) == ("settled", "failed")
            await runtime.close()

    asyncio.run(run())


def test_dispatch_cancellation_refunds_but_consumes_daily_quota() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 27, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            adapter, user = "qq.official", "qq-dispatch-cancel"
            await _mortal(runtime, adapter, user, "cancel")
            _, _, stamina_before, _ = _player_row(runtime, adapter, user)
            for index in range(3):
                accepted = await _send(
                    runtime,
                    adapter,
                    user,
                    f"cancel-accept-{index}",
                    "接受派遣 dispatch.town_delivery",
                )
                assert accepted.code == "DISPATCH_ACCEPTED"
                clock.advance(seconds=30)
                cancelled = await _send(
                    runtime,
                    adapter,
                    user,
                    f"cancel-dispatch-{index}",
                    "取消派遣",
                )
                assert cancelled.code == "DISPATCH_CANCELLED"
                assert cancelled.data["refunded"] == {"stamina": 3}
            limited = await _send(runtime, adapter, user, "cancel-limit", "接受派遣 dispatch.town_delivery")
            assert limited.code == "DISPATCH_DAILY_LIMIT"
            _, _, stamina_after, _ = _player_row(runtime, adapter, user)
            assert stamina_after == stamina_before
            await runtime.close()

    asyncio.run(run())


def test_dispatch_rule_tables_are_closed_and_partial_outputs_round_down() -> None:
    assert {key: sum(weight for _, weight in definition.risk_weights) for key, definition in DISPATCHES.items()} == {
        TOWN_DELIVERY: 10000,
        HERB_SEARCH: 10000,
        WORKSHOP_HELP: 10000,
        "dispatch.demon_relief": 10000,
        "dispatch.beast_relocation": 10000,
    }
    from nonebot_plugin_xiuxian_3.xiuxian.specials.dispatch_rules import reward_for

    town_partial = reward_for(DISPATCHES[TOWN_DELIVERY], "town", "partial")
    assert town_partial == {"spirit_stones": 15, "local.xuantian.new_town": 1}
    herb_partial = reward_for(DISPATCHES[HERB_SEARCH], "herb", "partial")
    assert herb_partial["item.herb.blood_grass"] in (1, 2)
    assert "codex.dispatch.herb_search" not in herb_partial
    workshop_success = reward_for(DISPATCHES[WORKSHOP_HELP], "workshop", "success")
    assert workshop_success["service_reputation"] == 2
    assert "cultivation" not in workshop_success


def test_dispatch_slot_is_atomic_under_concurrent_accepts() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 27, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            adapter, user = "onebot.v11", "ob-dispatch-race"
            await _mortal(runtime, adapter, user, "race")
            results = await asyncio.gather(
                _send(runtime, adapter, user, "race-accept-a", "接受派遣 dispatch.town_delivery"),
                _send(runtime, adapter, user, "race-accept-b", "接受派遣 dispatch.town_delivery"),
            )
            assert sorted(result.code for result in results) == ["DISPATCH_ACCEPTED", "DISPATCH_SLOT_BUSY"]
            _, _, stamina, _ = _player_row(runtime, adapter, user)
            assert stamina == 27
            with sqlite3.connect(runtime.settings.database_path) as connection:
                assert connection.execute("SELECT COUNT(*) FROM dispatch_assignments").fetchone()[0] == 1
            await runtime.close()

    asyncio.run(run())


def test_dispatch_confirmation_expiry_disables_cancellation() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 27, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            adapter, user = "qq.official", "qq-dispatch-expired-confirmation"
            await _mortal(runtime, adapter, user, "expiry")
            _, _, stamina_before, _ = _player_row(runtime, adapter, user)
            accepted = await _send(runtime, adapter, user, "expiry-accept", "接受派遣 dispatch.town_delivery")
            assert accepted.code == "DISPATCH_ACCEPTED"
            clock.advance(seconds=61)
            expired = await _send(runtime, adapter, user, "expiry-cancel", "取消派遣")
            assert expired.code == "DISPATCH_CANCEL_WINDOW_EXPIRED"
            clock.value = datetime.fromisoformat(accepted.data["ends_at"])
            settled = await _send(runtime, adapter, user, "expiry-settle", "结算派遣")
            assert settled.code == "DISPATCH_SETTLED"
            _, _, stamina_after, _ = _player_row(runtime, adapter, user)
            assert stamina_before - stamina_after == 3
            await runtime.close()

    asyncio.run(run())


def test_expired_dispatch_recovery_projects_routine_and_honor_sources_on_both_adapters() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 27, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            for adapter in ("qq.official", "onebot.v11"):
                runtime = create_runtime(data_dir=f"{data_dir}/{adapter}", clock=clock)
                user = f"dispatch-recovery-{adapter}"
                prefix = adapter.replace(".", "-")
                await _mortal(runtime, adapter, user, prefix)
                campaign = await _send(runtime, adapter, user, f"{prefix}-campaign", "七日入道")
                assert campaign.code == "SEVEN_DAY_STATUS"
                success_seed = _forced_dispatch_seed(TOWN_DELIVERY, "success")
                with _force_uuid(success_seed, f"{prefix}-assignment"):
                    accepted = await _send(
                        runtime,
                        adapter,
                        user,
                        f"{prefix}-accept",
                        "接受派遣 dispatch.town_delivery",
                    )
                assert accepted.code == "DISPATCH_ACCEPTED"

                clock.advance(hours=24)
                assert await runtime.repository.recover_expired_dispatches() == 0
                clock.advance(days=5, minutes=31)
                await runtime.initialize()
                for _ in range(100):
                    with sqlite3.connect(runtime.settings.database_path) as connection:
                        status = connection.execute(
                            "SELECT status FROM dispatch_assignments WHERE assignment_id=?",
                            (accepted.data["assignment_id"],),
                        ).fetchone()[0]
                    if status == "settled":
                        break
                    await asyncio.sleep(0.01)
                assert status == "settled"
                assert await runtime.repository.recover_expired_dispatches() == 0

                honors = await _send(runtime, adapter, user, f"{prefix}-honors", "功业录")
                assert honors.code == "HONOR_STATUS"
                dispatch_achievement = honors.data["achievements"][2]
                assert dispatch_achievement["achievement_key"] == "achievement.first_dispatch"
                assert dispatch_achievement["state"] == "claimable"
                assert honors.data["titles"][3]["title_key"] == "title.dispatch_helper"
                assert honors.data["titles"][3]["acquired"] is True

                seven_day = await _send(runtime, adapter, user, f"{prefix}-seven-day", "七日入道")
                dispatch_goal = seven_day.data["goals"][5]
                assert dispatch_goal["day"] == 6
                assert dispatch_goal["state"] == "claimable"
                goal_claim = await _send(
                    runtime, adapter, user, f"{prefix}-claim-goal", "领取七日目标 6"
                )
                assert goal_claim.code == "SEVEN_DAY_GOAL_CLAIMED"

                claim_context = _context(adapter, user, f"{prefix}-claim-achievement")
                achievement = await runtime.adapters.dispatch(adapter, claim_context, "领取功业 3")
                replay = await runtime.adapters.dispatch(adapter, claim_context, "领取功业 3")
                assert achievement.code == "ACHIEVEMENT_CLAIMED"
                assert achievement.data["achievement_key"] == "achievement.first_dispatch"
                assert replay.data["idempotent_replay"] is True

                with sqlite3.connect(runtime.settings.database_path) as connection:
                    source_count = connection.execute(
                        "SELECT COUNT(*) FROM activity_events WHERE player_id=("
                        "SELECT id FROM players WHERE platform=? AND platform_user_id=?"
                        ") AND event_key='specials.dispatch.settled'",
                        (adapter, user),
                    ).fetchone()[0]
                    recovery_operations = connection.execute(
                        "SELECT COUNT(*) FROM operations WHERE operation_id=?",
                        (f"specials.dispatch.recovery:{accepted.data['assignment_id']}",),
                    ).fetchone()[0]
                assert source_count == 1
                assert recovery_operations == 1
                await runtime.close()

    asyncio.run(run())
