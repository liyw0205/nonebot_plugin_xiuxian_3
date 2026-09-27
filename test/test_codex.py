from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from tempfile import TemporaryDirectory

from nonebot_plugin_xiuxian_3.contracts import CommandContext
from nonebot_plugin_xiuxian_3.runtime import create_runtime


class MutableClock:
    def __init__(self, value: datetime):
        self.value = value

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **kwargs: int) -> None:
        self.value += timedelta(**kwargs)


async def _send(runtime, adapter: str, user: str, operation_id: str, text: str):
    context = CommandContext(adapter=adapter, user_id=user, operation_id=operation_id)
    return await runtime.adapters.dispatch(adapter, context, text)


async def _enter_path(runtime, adapter: str, user: str, prefix: str, path: str) -> None:
    for index, command in enumerate(
        (
            "开始修仙",
            "寻仙问道",
            "完成引导 阅读",
            "前往近郊",
            "完成引导 采集",
            "完成引导 炼丹",
            f"选择道途 {path}",
        )
    ):
        result = await _send(runtime, adapter, user, f"{prefix}-{index}", command)
        assert result.ok, (command, result.code, result.message)


async def _advance_to_qi_sensing_l2(runtime, clock: MutableClock, adapter: str, user: str, prefix: str) -> None:
    for index in range(4):
        started = await _send(runtime, adapter, user, f"{prefix}-cultivate-{index}", "开始修炼")
        assert started.code == "CULTIVATION_STARTED"
        clock.advance(minutes=10)
        settled = await _send(runtime, adapter, user, f"{prefix}-settle-{index}", "结算修炼")
        assert settled.code == "CULTIVATION_SETTLED"
        if settled.data["cultivation"] >= 80:
            promoted = await _send(runtime, adapter, user, f"{prefix}-promote", "晋升境界")
            assert promoted.code == "REALM_LAYER_ADVANCED"
            return
    raise AssertionError("normal cultivation did not reach qi sensing layer 2")


def test_codex_place_milestone_claim_unlocks_extra_commission_on_both_adapters() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 27, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            for adapter, user in (("qq.official", "codex-qq"), ("onebot.v11", "codex-onebot")):
                prefix = adapter.replace(".", "-")
                await _enter_path(runtime, adapter, user, prefix, "体修")
                before = await _send(runtime, adapter, user, f"{prefix}-codex-before", "我的图鉴 地点")
                assert before.code == "CODEX_OVERVIEW"
                assert {item["entry_key"] for item in before.data["entries"]} == {
                    "codex.place.new_town",
                    "codex.place.outskirts",
                }
                not_ready = await _send(
                    runtime,
                    adapter,
                    user,
                    f"{prefix}-claim-before",
                    "领取图鉴里程碑 1",
                )
                assert not_ready.code == "CODEX_MILESTONE_NOT_READY"

                await _advance_to_qi_sensing_l2(runtime, clock, adapter, user, prefix)
                spirit_field = await _send(runtime, adapter, user, f"{prefix}-spirit-field", "前往灵泉谷")
                assert spirit_field.code == "TRAVEL_COMPLETED"
                overview = await _send(runtime, adapter, user, f"{prefix}-codex-ready", "我的图鉴 地点")
                assert {item["entry_key"] for item in overview.data["entries"]} == {
                    "codex.place.new_town",
                    "codex.place.outskirts",
                    "codex.place.spirit_field",
                }
                honors = await _send(runtime, adapter, user, f"{prefix}-honors", "功业录")
                assert honors.code == "HONOR_STATUS", (honors.code, honors.message, honors.data)
                codex_achievement = next(
                    item
                    for item in honors.data["achievements"]
                    if item["achievement_key"] == "achievement.codex_5"
                )
                assert codex_achievement["state"] == "claimable"
                achievement_context = CommandContext(
                    adapter=adapter, user_id=user, operation_id=f"{prefix}-claim-codex-achievement"
                )
                achievement = await runtime.adapters.dispatch(adapter, achievement_context, "领取功业 4")
                achievement_replay = await runtime.adapters.dispatch(
                    adapter, achievement_context, "领取功业 4"
                )
                assert achievement.code == "ACHIEVEMENT_CLAIMED"
                assert achievement.data["achievement_key"] == "achievement.codex_5"
                assert achievement_replay.data["idempotent_replay"] is True
                offers_before = await _send(runtime, adapter, user, f"{prefix}-offers-before", "城镇委托")
                assert len(offers_before.data["commissions"]) == 3
                assert all(
                    item["commission_key"] != "town_commission.spirit_leaf"
                    for item in offers_before.data["commissions"]
                )
                locked_offer = await _send(
                    runtime,
                    adapter,
                    user,
                    f"{prefix}-extra-offer-locked",
                    "接取委托 灵泉谷灵叶收集",
                )
                assert locked_offer.code == "LIVELIHOOD_CONTENT_CLOSED"

                claim_context = CommandContext(
                    adapter=adapter, user_id=user, operation_id=f"{prefix}-claim-place"
                )
                claimed = await runtime.adapters.dispatch(adapter, claim_context, "领取图鉴里程碑 1")
                replayed = await runtime.adapters.dispatch(adapter, claim_context, "领取图鉴里程碑 1")
                assert claimed.code == "CODEX_MILESTONE_CLAIMED"
                assert claimed.data["reward"] == {"local.xuantian.new_town": 5}
                assert replayed.data["idempotent_replay"] is True
                duplicate = await _send(
                    runtime,
                    adapter,
                    user,
                    f"{prefix}-claim-place-again",
                    "领取图鉴里程碑 1",
                )
                assert duplicate.code == "CODEX_MILESTONE_ALREADY_CLAIMED"

                offers_after = await _send(runtime, adapter, user, f"{prefix}-offers-after", "城镇委托")
                assert len(offers_after.data["commissions"]) == 4
                assert any(
                    item["commission_key"] == "town_commission.spirit_leaf"
                    for item in offers_after.data["commissions"]
                )
                accepted_offer = await _send(
                    runtime,
                    adapter,
                    user,
                    f"{prefix}-extra-offer-accept",
                    "接取委托 灵泉谷灵叶收集",
                )
                assert accepted_offer.code == "COMMISSION_ACCEPTED"
            await runtime.close()

    asyncio.run(run())


def test_arena_match_records_both_publicly_observed_paths_in_codex() -> None:
    async def run() -> None:
        clock = MutableClock(datetime(2026, 9, 27, tzinfo=timezone.utc))
        with TemporaryDirectory() as data_dir:
            runtime = create_runtime(data_dir=data_dir, clock=clock)
            await _enter_path(runtime, "qq.official", "codex-observer", "observer", "体修")
            await _enter_path(runtime, "onebot.v11", "codex-opponent", "opponent", "法修")
            published = await _send(
                runtime, "onebot.v11", "codex-opponent", "opponent-publish", "发布竞技场快照"
            )
            assert published.code == "ARENA_SNAPSHOT_PUBLISHED"
            clock.advance(minutes=31)
            match = await _send(
                runtime,
                "qq.official",
                "codex-observer",
                "observer-challenge",
                f"挑战竞技场 {published.data['snapshot_id']}",
            )
            assert match.code == "ARENA_MATCH_SETTLED"

            observer_codex = await _send(
                runtime, "qq.official", "codex-observer", "observer-codex", "我的图鉴 道途"
            )
            opponent_codex = await _send(
                runtime, "onebot.v11", "codex-opponent", "opponent-codex", "我的图鉴 道途"
            )
            observer_paths = {item["entry_key"] for item in observer_codex.data["entries"]}
            opponent_paths = {item["entry_key"] for item in opponent_codex.data["entries"]}
            assert {"codex.path.body", "codex.path.spell"} <= observer_paths
            assert {"codex.path.body", "codex.path.spell"} <= opponent_paths
            await runtime.close()

    asyncio.run(run())
